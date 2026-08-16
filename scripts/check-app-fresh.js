#!/usr/bin/env node
// check-app-fresh.js — is the app he is looking at actually running the code we just wrote?
//
//   node scripts/check-app-fresh.js
//
// ─── THE FAILURE THIS EXISTS FOR ─────────────────────────────────────────────
//
// 2026-08-15. A session changed the MEA feature end to end, verified it, committed it, and
// stopped the backend on the way out — leaving the Vite dev server up. The next thing the
// author did was look at the app and say *"i dont see the updates"*. The page was still
// painted, every control still moved, and nothing behind it was answering. Nothing in the
// repo noticed, because nothing was watching.
//
// The backend is plain uvicorn with no file watching, so it serves whatever Python it
// imported at startup until somebody restarts it. That gives two ways to be looking at a
// lie, and this script is the check for both:
//
//   1. **STALE** — a backend is listening, but it started BEFORE the newest change to
//      `src/camea/`. Every request it answers is the old app.
//   2. **HALF-DEAD** — the Vite dev server is up and the backend is not. This is the worse
//      of the two: a page that loads, renders, and fails every request it makes.
//
// ⭐ `camea --headless --reload` makes case 1 fix itself — uvicorn's reloader restarts the
// child on any change under `src/camea/`, so `uptime_s` resets and this check goes green on
// its own. That is the intended dev loop; this script is what catches the loop not being in
// it.
//
// ─── AND WHAT IT MUST NOT DO ─────────────────────────────────────────────────
//
// ⛔ It must not fire when nothing is running. Most turns in this repo touch Python with no
// dev server anywhere, and a gate that reddens those is a gate that gets switched off
// (stop-gates.js, rule 3). Nothing listening on either port is a silent pass, always.
//
// ⛔ It never starts, stops or restarts anything. It does not own those processes — a
// session does, and a session is the only thing that knows whether the author is mid-click.
// This reports; the turn's owner acts.
//
// Ports are the documented dev-loop pair (docs/FRONTEND.md), overridable for a second stack:
//   CAMEA_DEV_PORT=8000   CAMEA_DEV_WEB_PORT=5173
// `CAMEA_SKIP_APP_FRESH=1` turns the whole check off.
//
// Exit 0 = fresh, or nothing to be stale. Exit 1 = the app is not what the tree says it is.

const fs = require('fs');
const net = require('net');
const path = require('path');

const REPO_ROOT = path.resolve(__dirname, '..');
const SRC = path.join(REPO_ROOT, 'src', 'camea');

const API_PORT = Number(process.env.CAMEA_DEV_PORT || 8000);
const WEB_PORT = Number(process.env.CAMEA_DEV_WEB_PORT || 5173);

// A probe must never be the slow part of a Stop hook, and both of these are loopback.
const PROBE_MS = 1500;

// `uptime_s` comes back rounded to 0.1 s, a restart takes a moment to bind, and a file's
// mtime and the server's clock are read at different instants. Two seconds of slack is far
// below the interval that matters (a human editing code) and kills the flapping.
const SLACK_S = 2;

// ---------------------------------------------------------------------------

/** Newest mtime under src/camea, in epoch seconds. The whole tree, not just changed files:
 *  what makes a running server stale is the newest code on disk, whatever git thinks of it
 *  (a file edited and committed in an earlier turn is still newer than a server started
 *  before it). */
function newestPython(dir) {
  let newest = 0;
  let entries;
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return 0;
  }
  for (const e of entries) {
    if (e.name === '__pycache__') continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) {
      newest = Math.max(newest, newestPython(p));
    } else if (e.name.endsWith('.py')) {
      try {
        newest = Math.max(newest, fs.statSync(p).mtimeMs / 1000);
      } catch {
        /* raced with a write; the next file speaks for it */
      }
    }
  }
  return newest;
}

/** Is anything listening? A bare TCP connect — it asks nothing of the process behind it, so
 *  it works for Vite, for the backend, and for whatever else grabbed the port. */
function listening(port) {
  return new Promise((resolve) => {
    const sock = net.createConnection({ host: '127.0.0.1', port });
    const done = (answer) => {
      sock.destroy();
      resolve(answer);
    };
    sock.setTimeout(PROBE_MS);
    sock.once('connect', () => done(true));
    sock.once('timeout', () => done(false));
    sock.once('error', () => done(false));
  });
}

/** `GET /api/health` -> its `uptime_s`, or null if this is not a Camea backend. */
async function backendUptime(port) {
  try {
    const res = await fetch(`http://127.0.0.1:${port}/api/health`, {
      signal: AbortSignal.timeout(PROBE_MS),
    });
    if (!res.ok) return null;
    const body = await res.json();
    return typeof body.uptime_s === 'number' ? body.uptime_s : null;
  } catch {
    return null;
  }
}

function ago(seconds) {
  if (seconds < 90) return `${Math.round(seconds)}s ago`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min ago`;
  return `${(seconds / 3600).toFixed(1)} h ago`;
}

// ---------------------------------------------------------------------------

async function main() {
  if (process.env.CAMEA_SKIP_APP_FRESH === '1') return 0;

  const [apiUp, webUp] = await Promise.all([listening(API_PORT), listening(WEB_PORT)]);

  // Nothing running: there is no stale app to be looking at. The common case, and silent.
  if (!apiUp && !webUp) return 0;

  if (!apiUp) {
    console.log(
      `THE APP IS HALF-DEAD. The Vite dev server is up on :${WEB_PORT} and nothing is ` +
        `listening on :${API_PORT}.\n\n` +
        `That page still loads and still paints — and every request it makes fails, which ` +
        `looks exactly like an app that ignored your change. Whoever is at the browser is ` +
        `seeing a frozen picture of the last thing the backend said.\n\n` +
        `Start it:\n` +
        `    uv run camea --headless --reload --port ${API_PORT}\n`,
    );
    return 1;
  }

  const uptime = await backendUptime(API_PORT);
  if (uptime === null) {
    // Something owns the port but does not answer /api/health. Not ours to judge.
    console.log(
      `note: :${API_PORT} is taken by something that is not a Camea backend — freshness ` +
        `not checked.`,
    );
    return 0;
  }

  const startedAt = Date.now() / 1000 - uptime;
  const newest = newestPython(SRC);
  if (newest <= startedAt + SLACK_S) return 0;

  const behind = newest - startedAt;
  console.log(
    `THE RUNNING APP IS STALE. The backend on :${API_PORT} started ${ago(uptime)}, and ` +
      `src/camea/ has changed ${ago(Date.now() / 1000 - newest)} — ${Math.round(behind)}s ` +
      `after it came up.\n\n` +
      `uvicorn does not watch its own files, so that process is still serving the Python it ` +
      `imported at startup. Anything you just changed under src/camea/ is NOT what the ` +
      `browser is talking to, and clicking through it proves nothing.\n\n` +
      `Restart it — and start it with --reload so this cannot happen again:\n` +
      `    uv run camea --headless --reload --port ${API_PORT}\n\n` +
      `(The frontend needs none of this; Vite hot-reloads. If the author is mid-click and a ` +
      `restart would interrupt them, say so instead of doing it silently.)\n`,
  );
  return 1;
}

main().then(
  (code) => process.exit(code),
  (e) => {
    // A probe that fell over is not evidence of a stale app. Say so and pass.
    console.log(`note: could not check whether the running app is fresh (${e.message}).`);
    process.exit(0);
  },
);
