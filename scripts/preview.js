#!/usr/bin/env node
// preview.js — run a pile on localhost so you can look at it before it lands.
//
//   node scripts/preview.js list
//   node scripts/preview.js start <slug>
//   node scripts/preview.js stop  <slug>
//   node scripts/preview.js stop-all
//
// ─── Why it gets a working copy of its own ───────────────────────────────────
//
// It NEVER switches this checkout's branch. Several sessions share this tree — a /build
// may be mid-plan in it — and changing its branch underneath them is the same damage as
// `git restore`. So a preview is a git worktree at `../.camea-previews/<slug>`, checked
// out at the pile's ref, and it is removed when you stop it.
//
// This is one of the two worktrees workflow/README.md sanctions. The other is
// /bug-hunter's read-only snapshot. Neither is a session inventing one for itself.
//
// ─── Why the first start of a pile is slow ───────────────────────────────────
//
// A fresh worktree has no `web/node_modules` and no `.venv`, so the first start runs
// `npm install` and lets `uv run` build an environment — a few minutes. Say that out loud
// rather than letting him think it hung. Every start after that reuses what is there.
//
// Labstock's version is slow for a different reason (it restores a copy of the production
// database so he sees real names and prices). Camea has no database. What it has instead is
// the committed synthetic fixture at `tests/fixtures/`, ~5.6 MB, which is what the backend
// is pointed at — so a preview works on a machine with no 35 GB mirror at all.
//
// ─── Ports ───────────────────────────────────────────────────────────────────
//
// 8000 and 5173 are HIS dev servers and are never used here. Previews take slots from
// 5200 upward, ten apart, so two piles can be up at once and neither steals the other's.

const fs = require('fs');
const path = require('path');
const net = require('net');
const { execFileSync, spawn } = require('child_process');
const { listPiles } = require('./piles');

const REPO_ROOT = path.join(__dirname, '..');
const PREVIEW_ROOT = path.resolve(REPO_ROOT, '..', '.camea-previews');
const STATE = path.join(REPO_ROOT, 'workflow', '.previews.json');

// His own dev servers. Deliberately never allocated. (docs/FRONTEND.md § The two-terminal
// dev loop — backend 8000, Vite 5173.)
const RESERVED = new Set([8000, 5173]);
const SLOT_BASE = 5200;
const SLOT_STRIDE = 10;
const MAX_SLOTS = 8;

function die(msg, detail) {
  console.error(`preview: ${msg}`);
  if (detail) console.error(detail);
  process.exit(1);
}

function git(args, { cwd = REPO_ROOT, allowFail = false } = {}) {
  try {
    return execFileSync('git', args, { cwd, encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 }).trim();
  } catch (e) {
    if (allowFail) return null;
    die(`git ${args.join(' ')} failed`, String(e.stderr || e.message).trim());
    return null;
  }
}

function readState() {
  try {
    return JSON.parse(fs.readFileSync(STATE, 'utf8'));
  } catch {
    return {};
  }
}

function writeState(s) {
  fs.mkdirSync(path.dirname(STATE), { recursive: true });
  fs.writeFileSync(STATE, `${JSON.stringify(s, null, 2)}\n`);
}

function portFree(port) {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.once('error', () => resolve(false));
    srv.once('listening', () => srv.close(() => resolve(true)));
    srv.listen(port, '127.0.0.1');
  });
}

async function allocateSlot(state) {
  const taken = new Set(Object.values(state).map((e) => e.slot));
  for (let i = 0; i < MAX_SLOTS; i++) {
    if (taken.has(i)) continue;
    const web = SLOT_BASE + i * SLOT_STRIDE;
    const api = web + 1;
    if (RESERVED.has(web) || RESERVED.has(api)) continue;
    if ((await portFree(web)) && (await portFree(api))) return { slot: i, web, api };
  }
  die(
    `no free preview slot (tried ${MAX_SLOTS}).`,
    'Stop one first: node scripts/preview.js stop-all',
  );
  return null;
}

function alive(pid) {
  if (!pid) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

// ─── list ────────────────────────────────────────────────────────────────────

function cmdList() {
  const state = readState();
  const rows = Object.entries(state);
  if (!rows.length) {
    console.log('Nothing is previewing. `preview.js start <slug>` opens one.');
    return;
  }
  for (const [slug, e] of rows) {
    const up = alive(e.apiPid) || alive(e.webPid);
    console.log(
      `  ${slug.padEnd(20)} ${up ? 'up  ' : 'down'}  http://127.0.0.1:${e.web}   (api ${e.api})  ${e.dir}`,
    );
  }
  console.log('\nA "down" row is a stopped or crashed preview — its worktree is still there.');
  console.log('Logs: <dir>/.preview-logs/{api,web}.log');
}

// ─── start ───────────────────────────────────────────────────────────────────

async function cmdStart(slug) {
  if (!slug) die('which pile? node scripts/preview.js start <slug>', 'The board: node scripts/piles.js');

  const state = readState();
  const existing = state[slug];
  if (existing && (alive(existing.apiPid) || alive(existing.webPid))) {
    console.log(`${slug} is already up: http://127.0.0.1:${existing.web}`);
    return;
  }

  const pile = listPiles().find((p) => p.slug === slug);
  if (!pile) die(`no pile called "${slug}".`, 'The board: node scripts/piles.js');

  // An `in progress` pile is previewable — that is the point of it. He is looking in order
  // to decide whether to run /commit-work. Only LANDING requires `ready`.
  const ref = pile.remoteRef || pile.localRef;
  const dir = path.join(PREVIEW_ROOT, slug);

  if (!fs.existsSync(dir)) {
    fs.mkdirSync(PREVIEW_ROOT, { recursive: true });
    // Detached: a worktree with a branch checked out would lock that branch out of this
    // checkout, and there is nothing here to commit anyway.
    git(['worktree', 'add', '--detach', dir, ref]);
    console.log(`worktree at ${dir}, detached at ${ref}`);
  } else {
    // Re-point an existing worktree at the pile's current head, so a preview restarted
    // after `work.js save` shows the new commits.
    git(['checkout', '--detach', ref], { cwd: dir, allowFail: true });
    console.log(`reusing ${dir}, now at ${ref}`);
  }

  const { slot, web, api } = await allocateSlot(state);
  const logs = path.join(dir, '.preview-logs');
  fs.mkdirSync(logs, { recursive: true });

  const webModules = path.join(dir, 'web', 'node_modules');
  if (!fs.existsSync(webModules)) {
    console.log('\nFirst start of this pile — installing web dependencies. This takes a few');
    console.log('minutes and only happens once per pile. It has not hung.\n');
    try {
      execFileSync('npm', ['install', '--no-audit', '--no-fund'], {
        cwd: path.join(dir, 'web'),
        stdio: 'inherit',
        shell: process.platform === 'win32',
      });
    } catch (e) {
      die('npm install failed in the preview worktree', String(e.message).trim());
    }
  }

  const apiLog = fs.openSync(path.join(logs, 'api.log'), 'w');
  const webLog = fs.openSync(path.join(logs, 'web.log'), 'w');

  // The backend is headless and bound to loopback by construction. `--open` puts a path in
  // settings.recent_datasets — "start me near here" — and nothing else; it opens no dataset
  // and scans nothing (docs/FRONTEND.md). tests/fixtures holds the committed synthetic
  // dataset, which is the whole reason a preview needs no 35 GB mirror.
  const apiProc = spawn(
    'uv',
    ['run', 'camea', '--headless', '--port', String(api), '--open', 'tests/fixtures'],
    {
      cwd: dir,
      detached: true,
      stdio: ['ignore', apiLog, apiLog],
      shell: process.platform === 'win32',
    },
  );
  apiProc.unref();

  const webProc = spawn('npm', ['run', 'dev', '--', '--port', String(web), '--strictPort'], {
    cwd: path.join(dir, 'web'),
    detached: true,
    stdio: ['ignore', webLog, webLog],
    shell: process.platform === 'win32',
    env: { ...process.env, VITE_BACKEND: `http://127.0.0.1:${api}` },
  });
  webProc.unref();

  state[slug] = {
    slot,
    web,
    api,
    dir,
    ref,
    apiPid: apiProc.pid,
    webPid: webProc.pid,
    started: new Date().toISOString(),
  };
  writeState(state);

  console.log(`\n${slug} is starting.`);
  console.log(`  http://127.0.0.1:${web}      (backend on ${api})`);
  console.log('  Give it a few seconds to boot before you open it.');
  console.log(`  Logs: ${path.join(logs, 'api.log')} · ${path.join(logs, 'web.log')}`);
  console.log('\nLook at it at 1440×900. Stop it with: node scripts/preview.js stop ' + slug);
}

// ─── stop ────────────────────────────────────────────────────────────────────

function killTree(pid) {
  if (!pid) return;
  try {
    if (process.platform === 'win32') {
      execFileSync('taskkill', ['/PID', String(pid), '/T', '/F'], { stdio: 'ignore' });
    } else {
      process.kill(-pid, 'SIGTERM');
    }
  } catch {
    /* already gone */
  }
}

function cmdStop(slug, { removeWorktree = true } = {}) {
  const state = readState();
  const e = state[slug];
  if (!e) die(`nothing called "${slug}" is previewing.`, 'node scripts/preview.js list');

  killTree(e.apiPid);
  killTree(e.webPid);
  delete state[slug];
  writeState(state);
  console.log(`${slug} stopped.`);

  if (removeWorktree && fs.existsSync(e.dir)) {
    // --force because the worktree carries node_modules and logs, which are untracked.
    git(['worktree', 'remove', e.dir, '--force'], { allowFail: true });
    console.log(`  removed ${e.dir}`);
    console.log('  (its next start reinstalls, so use --keep if you will restart it soon)');
  }
}

function cmdStopAll(opts) {
  const state = readState();
  const slugs = Object.keys(state);
  if (!slugs.length) {
    console.log('Nothing is previewing.');
    return;
  }
  for (const slug of slugs) cmdStop(slug, opts);
}

// ─── dispatch ────────────────────────────────────────────────────────────────

const argv = process.argv.slice(2);
const cmd = argv[0];
const arg = argv.find((a, i) => i > 0 && !a.startsWith('--'));
const opts = { removeWorktree: !argv.includes('--keep') };

(async () => {
  if (cmd === 'start') await cmdStart(arg);
  else if (cmd === 'stop') cmdStop(arg, opts);
  else if (cmd === 'stop-all') cmdStopAll(opts);
  else if (cmd === 'list' || !cmd) cmdList();
  else die(`unknown command "${cmd}".`, 'list | start <slug> | stop <slug> [--keep] | stop-all');
})();
