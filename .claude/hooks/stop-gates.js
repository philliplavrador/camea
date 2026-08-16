#!/usr/bin/env node
// Stop hook — run the checks the turn's own changes make relevant, and BLOCK the
// turn (exit 2) when one fails, feeding the output back to Claude.
//
// Imported from Labstock's stop-lint.js on 2026-08-13 and re-tabled for Camea. The
// mechanism is unchanged; every command, cost and skip-reason in it is Camea's.
//
// WHY EXIT 2: Claude Code only forwards a hook's stderr to the model when the hook exits
// with code 2. Exit 0 is invisible, which makes a gate that exits 0 on failure a comment.
//
// ─── THE FOUR RULES THE TABLE RESPECTS ───────────────────────────────────────
//
//   1. Only what changed. A gate whose paths did not change never runs, so a turn
//      that touched nothing relevant costs one `git status` and nothing else.
//
//   2. Name the trigger, and admit it may not be yours. changedFiles() reads
//      `git status --porcelain` — the WHOLE working tree, not this turn's edits. Every
//      session and subagent works in this one checkout on `master`, so during a
//      concurrent /build a gate can be tripped by another agent's in-flight file. Every
//      failure message therefore names the files that selected the gate and says so.
//
//   3. A gate that CANNOT run is a note, not a red. Missing node_modules, a script that
//      has not landed yet, no `uv` on this machine — the gate SKIPS with a one-line note
//      and the turn is not blocked. A false red teaches people to ignore the hook, which
//      costs more than the gate was worth.
//
//   4. ⭐ A gate that costs TOO MUCH is also a note. This is Camea's addition, and it is
//      forced by a measurement: the Python suite takes **3m26s** (unit 64 s + api 133 s,
//      measured 2026-08-13, 588 tests). A three-and-a-half-minute tax on every turn that
//      touches a `.py` file is a hook that gets switched off in a week. So the expensive
//      suites are listed as OWED — named, with the exact command, in the hook's own
//      output — and are run by /build's verify block and by ship.js on the merged tree,
//      where the cost is paid once instead of per-turn.
//
//      `CAMEA_STOP_FULL=1` runs them anyway, which is what a long unattended session
//      should set.
//
// ─── AND ONE THING THIS HOOK MUST NEVER DO ───────────────────────────────────
//
//   ⛔ It never runs `tests/slow/test_solver_312.py`. That suite needs the 35 GB mirror
//      and a GPU and takes ~130 s, and its failure is the one result in this repo that
//      must stop everything and be looked at by a person (CLAUDE.md § The 312/312 solver
//      guard is sacred). What the hook does instead is the cheap half: check-engine.js
//      proves the four guarded files are still byte-identical to archive/analysis/mosaic/,
//      in 53 ms. A green there is NOT a green on the guard.
//
// Dry run (never executes a gate):
//   node .claude/hooks/stop-gates.js --dry-run     (or CAMEA_STOP_DRY=1)

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

// Anchored on this file, not on cwd, so `git status` and the npm scripts all resolve the
// same way however the hook was invoked.
//
// THE DRIVE LETTER IS UPPERCASED ON PURPOSE. `__dirname` keeps whatever spelling node was
// launched with, and a session's cwd is often `d:\Projects\…`, lowercase. A module resolver
// keys on the string, so `D:/Projects/Camea` and `d:/Projects/Camea` are two module
// instances of everything — which is how vitest ends up unable to find the suite it is in,
// reporting every file as FAIL with zero tests evaluated. Measured in the Labstock repo
// this was imported from; the failure mode is the toolchain's, not that repo's.
const REPO_ROOT = canonicalRoot(path.resolve(__dirname, '..', '..'));

function canonicalRoot(p) {
  return process.platform === 'win32' ? p.replace(/^([a-z]):/, (_, d) => `${d.toUpperCase()}:`) : p;
}

const DRY_RUN = process.env.CAMEA_STOP_DRY === '1' || process.argv.includes('--dry-run');
const FULL = process.env.CAMEA_STOP_FULL === '1' || process.argv.includes('--full');

// `require`d by a test instead of run as the hook: then nothing here may read stdin or
// exit the process.
const IS_MAIN = require.main === module;

// Re-entry guard: if this Stop hook already ran and blocked, don't loop.
let payload = {};
if (IS_MAIN && !DRY_RUN && !process.stdin.isTTY) {
  try {
    payload = JSON.parse(fs.readFileSync(0, 'utf8'));
  } catch {
    /* no stdin — fine */
  }
}
if (payload.stop_hook_active) process.exit(0);

// ---------------------------------------------------------------------------
// THE TABLE. One row per gate: { match, label, cmd, cwd?, hint, cost, deferred?,
//                                skipWhen?, results? }
//
//   match      predicate over ONE normalized (forward-slash, repo-relative) changed
//              path. Every path that matches is recorded as a trigger, because the
//              failure message has to name them (rule 2).
//   cmd        run from REPO_ROOT, or from `cwd` under it. Must exist — if an npm script
//              is missing the row SKIPS with a note instead of failing.
//   hint       what Claude should do about a failure. Printed as `[label] hint`.
//   cost       measured wall-clock on this machine, 2026-08-13. Recorded so nobody has to
//              re-measure to know what a row costs, and so rule 4 can be argued from
//              numbers rather than from feel.
//   deferred   true → NOT run by default (rule 4). Reported as owed, with the command.
//              CAMEA_STOP_FULL=1 runs it.
//   skipWhen   () => reason | null, for a gate that cannot run on this machine.
//   results    (output) => { total, failed } | null, for a gate that is a TEST RUNNER.
//              Present → a non-zero exit with no failing test is re-run before it is
//              believed (rule 3, after the fact). Absent → exit code is the verdict.
//
// Ordered cheapest-first, so the fast answers land first.
// ---------------------------------------------------------------------------
const GATES = [
  {
    // 53ms. The most important cheap check in the repo.
    label: 'engine',
    match: (p) => /^src\/camea\/engine\/(t27|t33|quality|render)\.py$/.test(p),
    cmd: 'node scripts/check-engine.js',
    cost: '53ms',
    hint:
      'a GUARDED ENGINE FILE HAS CHANGED. Those four files are byte-identical copies of ' +
      'archive/analysis/mosaic/ and are the only thing the 312/312 solver guard protects. ' +
      'ruff cannot see them (pyproject.toml excludes them deliberately, so nobody fixes ' +
      'their 29 cosmetic errors by accident), so this is the check. Read the output before ' +
      'anything else:',
  },
  {
    // 92ms
    label: 'ruff',
    match: (p) => p.endsWith('.py'),
    cmd: 'uv run ruff check .',
    cost: '92ms',
    hint: '`uv run ruff check .` fails — fix before finishing:',
    skipWhen: () => (hasUv() ? null : 'no `uv` on PATH, so the Python gates cannot run here'),
  },
  {
    // 116ms
    label: 'links',
    match: (p) => p.endsWith('.md'),
    cmd: 'node scripts/check-links.js',
    cost: '116ms',
    hint:
      'a Markdown link or anchor is dangling. Docs here are Claude-facing ground truth — a ' +
      'doc pointing at a moved file sends the next session to the wrong place:',
  },
  {
    // ~120ms — two loopback probes, and a walk of src/camea for the newest .py mtime.
    //
    // ⭐ THE ONLY GATE THAT ASKS ABOUT THE WORLD RATHER THAN THE TREE. Everything else here
    // decides from files; this one asks whether the process the author is looking at is
    // running the code those files describe. uvicorn does not watch its own source, so a
    // running backend serves whatever it imported at startup — and the symptom of that is
    // not an error, it is the change appearing not to have happened.
    //
    // Silent when nothing is listening, which is most turns. See the script's header.
    label: 'stale-app',
    match: (p) => p.startsWith('src/camea/') && p.endsWith('.py'),
    cmd: 'node scripts/check-app-fresh.js',
    cost: '120ms',
    hint:
      'the app that is actually running is NOT the code in this tree. Read the lines below and ' +
      'restart it before you tell him anything is done — a click-through against a stale ' +
      'backend proves nothing, and "i dont see the updates" is what he says next:',
  },
  {
    // 120ms. A RATCHET, not a pass/fail: 13 of the 48 rulings had no citing test on
    // 2026-08-13 when this landed, and reddening the turn on somebody else's debt is how a
    // gate gets switched off. `--max 13` tolerates exactly that debt and fails on a 14th.
    // When one of the thirteen gets covered, LOWER THE NUMBER HERE and it can never come
    // back. The list is in scripts/check-rulings.js's header.
    label: 'rulings',
    match: (p) => p === 'docs/BEHAVIOUR.md' || p.startsWith('web/tests/e2e/'),
    cmd: 'node scripts/check-rulings.js --max 13',
    cost: '120ms',
    hint:
      'a ruling in docs/BEHAVIOUR.md has no test citing it. Every ruling is supposed to be ' +
      'backed by a Playwright test in web/tests/e2e/ (CLAUDE.md) — a ruling with no test is ' +
      'a hope, and the first refactor that contradicts it does so silently:',
  },
  {
    // 6.0s
    label: 'tsc',
    match: (p) => /^web\/(src|tests)\/.*\.(ts|tsx)$/.test(p) || /^web\/[^/]*\.ts$/.test(p),
    cmd: 'npx tsc -b --noEmit',
    cwd: 'web',
    cost: '6.0s',
    hint: 'TypeScript does not compile:',
    skipWhen: () => webInstalled(),
  },
  {
    // 6.4s. Only on api changes, and it is the gate that stops a hand-written
    // backend-owned type — HARD RULE 2 in docs/FRONTEND.md.
    label: 'check:api',
    match: (p) => p.startsWith('src/camea/api/') || p === 'web/src/api/schema.d.ts',
    cmd: 'npm run check:api --silent',
    cwd: 'web',
    cost: '6.4s',
    hint:
      'the generated API client has drifted from the live backend. The contract is ' +
      'GENERATED, never hand-written: refresh docs/openapi.json, run `npm run gen:api`, ' +
      'and commit web/src/api/schema.d.ts. This catches drift in BOTH directions — a ' +
      'hand-edited schema.d.ts and a backend change nobody regenerated:',
    skipWhen: () => webInstalled() || (hasUv() ? null : 'no `uv` on PATH — check:api dumps a fresh schema from the backend'),
  },
  {
    // 14.5s
    label: 'vitest',
    match: (p) => p.startsWith('web/src/'),
    cmd: 'npm test --silent',
    cwd: 'web',
    cost: '14.5s',
    hint: 'the frontend unit suite is RED:',
    results: vitestResults,
    skipWhen: () => webInstalled(),
  },
  {
    // 90ms. This hook's own tests — fast (no real suite runs), and the thing keeping the
    // crash/red distinction and the selection table honest. Editing the hook without
    // running them is the failure this file exists to prevent, one level up.
    label: 'hooks',
    match: (p) => p.startsWith('.claude/hooks/'),
    cmd: 'node .claude/hooks/stop-gates.test.js',
    cost: '90ms',
    hint:
      "the Stop hook's own tests are RED — this is the thing that decides whether a turn " +
      'gets blocked, so do not leave it broken:',
  },
  {
    // 22.5s — the slowest gate that still runs by default.
    label: 'eslint',
    match: (p) => /^web\/.*\.(ts|tsx|js|jsx|mjs|cjs)$/.test(p),
    cmd: 'npm run lint --silent',
    cwd: 'web',
    cost: '22.5s',
    hint: '`npm run lint` fails in web/:',
    skipWhen: () => webInstalled(),
  },

  // ─── DEFERRED (rule 4): named, not run. See the header. ───────────────────
  {
    // 64s, 454 tests
    label: 'pytest-unit',
    match: (p) =>
      (p.startsWith('src/camea/') && p.endsWith('.py')) || p.startsWith('tests/unit/'),
    cmd: 'uv run pytest tests/unit -q -m "not slow"',
    cost: '64s',
    deferred: true,
    hint: 'the Python unit suite is RED:',
    results: pytestResults,
    skipWhen: () => (hasUv() ? null : 'no `uv` on PATH'),
  },
  {
    // 133s, 134 tests — the slowest thing in the repo that is not the 312/312 guard.
    label: 'pytest-api',
    match: (p) =>
      p.startsWith('src/camea/api/') ||
      p.startsWith('src/camea/features/') ||
      p.startsWith('tests/api/'),
    cmd: 'uv run pytest tests/api -q -m "not slow"',
    cost: '133s',
    deferred: true,
    hint: 'the API suite is RED:',
    results: pytestResults,
    skipWhen: () => (hasUv() ? null : 'no `uv` on PATH'),
  },
  {
    // 4.4s — cheap, and deferred for the OTHER reason in rule 3/4: it is already red.
    //
    // `uv run mypy` (the form pyproject.toml configures, via packages = ["camea"]) exits 2
    // with *"Package 'camea' cannot be type checked due to missing py.typed marker"* — the
    // configured invocation does not work at all. `uv run mypy src/camea` does work and
    // reports **48 errors in 14 files**, all pre-existing (measured 2026-08-13).
    //
    // Wiring that in as a blocking gate would redden every turn that touches a .py file on
    // day one, which is exactly the always-red failure this file's rule 3 exists to
    // prevent. So it is deferred and it is FILED, not papered over. When the 48 are fixed,
    // delete `deferred` from this row and the ratchet closes behind them.
    label: 'mypy',
    match: (p) => p.startsWith('src/camea/') && p.endsWith('.py'),
    cmd: 'uv run mypy src/camea',
    cost: '4.4s',
    deferred: true,
    hint: 'mypy is RED (note: 48 errors were already there on 2026-08-13):',
    skipWhen: () => (hasUv() ? null : 'no `uv` on PATH'),
  },
  {
    label: 'e2e',
    match: (p) => p.startsWith('web/tests/e2e/') || p === 'docs/BEHAVIOUR.md',
    cmd: 'npm run e2e',
    cwd: 'web',
    cost: 'minutes, and it needs the backend running',
    deferred: true,
    hint:
      'the Playwright suite is RED. Those tests ARE docs/BEHAVIOUR.md — each one backs a ' +
      'numbered ruling, so a red here means a ruling is no longer true:',
    skipWhen: () => webInstalled(),
  },
];

// ---------------------------------------------------------------------------
// Skip probes
// ---------------------------------------------------------------------------

let uvSeen = null;
function hasUv() {
  if (uvSeen === null) {
    try {
      execSync('uv --version', { stdio: 'ignore', cwd: REPO_ROOT });
      uvSeen = true;
    } catch {
      uvSeen = false;
    }
  }
  return uvSeen;
}

function webInstalled() {
  return fs.existsSync(path.join(REPO_ROOT, 'web', 'node_modules'))
    ? null
    : 'web/node_modules is not installed (`cd web && npm install`), so the frontend gates cannot run here';
}

// `npm run <name>` → is that script actually declared? Guards against a script that has
// not landed yet or one that got renamed, both of which would otherwise read as a red
// suite on every turn that touched those paths.
function missingScript(gate) {
  const m = /^npm (?:run )?([\w:.-]+)/.exec(gate.cmd);
  if (!m) return null; // not an npm script (node/npx/uv rows)
  const name = m[1] === 'test' && !/^npm run/.test(gate.cmd) ? 'test' : m[1];
  const manifest = path.join(REPO_ROOT, gate.cwd || '.', 'package.json');
  try {
    const scripts = JSON.parse(fs.readFileSync(manifest, 'utf8')).scripts || {};
    if (scripts[name]) return null;
    return `"${name}" is not a script in ${path.posix.join(gate.cwd || '.', 'package.json')} yet`;
  } catch {
    return null; // can't read the manifest — let the command speak for itself
  }
}

function skipReason(gate) {
  if (gate.skipWhen) {
    const why = gate.skipWhen();
    if (why) return why;
  }
  return missingScript(gate);
}

// ---------------------------------------------------------------------------
// Changed files
// ---------------------------------------------------------------------------

// Every file the tree currently holds as changed — staged, unstaged, OR untracked.
// The untracked case is the one an old-style `git diff HEAD` misses, and it is exactly
// the file Claude just created. NOTE: this is the whole working tree, not this turn's
// edits (rule 2).
//
// ⚠️ `-uall` IS LOAD-BEARING, and its absence is silent. Plain `git status --porcelain`
// collapses an untracked DIRECTORY into a single entry — `?? scripts/` — instead of
// listing the files inside it. Every gate matcher tests a file path, so a brand-new
// directory selects NOTHING and the hook reports a clean pass over work it never looked
// at. Measured on 2026-08-13 while importing this hook: 29 new files across two new
// directories showed up as 2 entries and selected 0 of 11 gates.
function changedFiles() {
  try {
    return execSync('git status --porcelain -uall', { encoding: 'utf8', cwd: REPO_ROOT })
      .split(/\r?\n/)
      .filter(Boolean)
      .map((l) => l.slice(3).trim())
      .map((p) => {
        // A rename prints `old -> new`; the new path is the one to gate on. Paths
        // with spaces or non-ASCII come back quoted.
        const renamed = p.split(' -> ');
        return renamed[renamed.length - 1].replace(/^"|"$/g, '');
      })
      .map((p) => p.replace(/\\/g, '/'))
      .filter(Boolean)
      .filter((p) => !p.includes('node_modules/') && !p.startsWith('dist/'));
  } catch {
    return [];
  }
}

const changed = changedFiles();

// ONE pass over the changed files: each path is offered to every gate, and a gate
// keeps the paths that selected it. A gate with no triggers never runs.
const triggers = new Map();
for (const file of changed) {
  for (const gate of GATES) {
    if (!gate.match(file)) continue;
    if (!triggers.has(gate)) triggers.set(gate, []);
    triggers.get(gate).push(file);
  }
}
const selected = GATES.filter((g) => triggers.has(g));

// Nothing relevant changed: cost so far is one `git status`, and we are done.
if (IS_MAIN && selected.length === 0 && !DRY_RUN) process.exit(0);

// ---------------------------------------------------------------------------
// Result parsers
// ---------------------------------------------------------------------------

function fmtTriggers(files) {
  const shown = files.slice(0, 6).join(', ');
  return files.length > 6 ? `${shown} (+${files.length - 6} more)` : shown;
}

// Vitest's end-of-run summary is the only machine-ish evidence it emits without changing
// the reporter, and the two cases are structurally different there:
//
//    Test Files  1 failed | 1 passed (2)        Test Files  2 failed (2)
//         Tests  1 failed | 2 passed (3)             Tests  no tests
//    a real red ────────────────┘             a crash ─────────┘ nothing was evaluated
//
// Reading the count, not the error text, is deliberate: the alternative is a blocklist of
// crash messages, and that rots the first time vitest rewords one. null = no summary line
// at all, which counts as "evaluated nothing".
function vitestResults(out) {
  // Colour survives piped stdio and the escape sequence sits between the start of the line
  // and the word, so stripping it is load-bearing, not cosmetic.
  // eslint-disable-next-line no-control-regex -- the escape character is the thing matched
  const clean = String(out).replace(/\u001b\[[0-9;]*m/g, '');
  const summaries = clean.split(/\r?\n/).filter((l) => /^\s*Tests\s{2,}\S/.test(l));
  if (summaries.length === 0) return null;
  const line = summaries[summaries.length - 1].replace(/^\s*Tests\s+/, '').trim();
  if (/^no tests/i.test(line)) return { total: 0, failed: 0 };
  const count = (label) => {
    const m = new RegExp(`(\\d+)\\s+${label}`).exec(line);
    return m ? Number(m[1]) : 0;
  };
  const failed = count('failed');
  const parenthesised = /\((\d+)\)/.exec(line);
  const total = parenthesised
    ? Number(parenthesised[1])
    : failed + count('passed') + count('skipped') + count('todo');
  return { total, failed };
}

// pytest's `-q` summary line, e.g.
//   `588 passed, 19 deselected, 3 warnings in 205.90s (0:03:25)`
//   `2 failed, 586 passed, 19 deselected in 204.11s`
//   `no tests ran in 0.12s`
// A collection error prints `ERROR` / `INTERNALERROR` and NO counted summary, which is the
// case that has to be distinguishable from a red suite — same reasoning as vitestResults.
function pytestResults(out) {
  // eslint-disable-next-line no-control-regex
  const clean = String(out).replace(/\u001b\[[0-9;]*m/g, '');
  const lines = clean.split(/\r?\n/).filter(Boolean);
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i].replace(/[=\s]+$/, '').replace(/^[=\s]+/, '');
    if (/^no tests ran/i.test(line)) return { total: 0, failed: 0 };
    if (!/\bin \d+(\.\d+)?s\b/.test(line)) continue;
    // `\b` on the end, and `errors?` as ONE pattern rather than two calls. Counting
    // `error` and `errors` separately double-counts a collection failure — "3 errors"
    // matched both and reported 6. Caught by stop-gates.test.js, 2026-08-13.
    const count = (label) => {
      const m = new RegExp(`(\\d+)\\s+${label}\\b`).exec(line);
      return m ? Number(m[1]) : 0;
    };
    const failed = count('failed') + count('errors?');
    const total = failed + count('passed') + count('skipped') + count('xfailed') + count('xpassed');
    if (total === 0 && failed === 0) continue;
    return { total, failed };
  }
  return null;
}

// ---------------------------------------------------------------------------
// Run
// ---------------------------------------------------------------------------

const failures = [];
const notes = [];
const owed = [];

function attempt(gate) {
  try {
    execSync(gate.cmd, {
      stdio: 'pipe',
      cwd: gate.cwd ? path.join(REPO_ROOT, gate.cwd) : REPO_ROOT,
      maxBuffer: 32 * 1024 * 1024,
    });
    return { ok: true, out: '' };
  } catch (e) {
    return { ok: false, out: (e.stdout?.toString() || '') + (e.stderr?.toString() || '') };
  }
}

// Rule 2: every failure names the files that selected the gate, and admits they may not
// be this turn's.
function selectedBy(why) {
  return (
    `selected by: ${fmtTriggers(why)}\n` +
    `(that list is the whole working tree, not just this turn — during a concurrent ` +
    `/build the trigger may be another agent's in-flight file, so check whose it is ` +
    `before "fixing" it.)\n`
  );
}

function fail(gate, why, out, preface = '') {
  failures.push(
    `[${gate.label}] ${gate.hint}\n` + selectedBy(why) + preface + out.trim().slice(-3000),
  );
}

function run(gate, why) {
  const first = attempt(gate);
  if (first.ok) return;

  // Not a test runner: a linter, a link check and a byte comparison all mean what their
  // exit code says, so it is the verdict.
  if (!gate.results) return fail(gate, why, first.out);

  const ran = gate.results(first.out);
  if (ran && ran.failed > 0) return fail(gate, why, first.out);

  // Non-zero, but the runner reports no test as having failed — in fact no test as having
  // run at all. Either it crashed before evaluating anything, or the tree is broken badly
  // enough that nothing collects. Only asking again tells those apart.
  const second = attempt(gate);
  if (second.ok) {
    notes.push(
      `[${gate.label}] COULD NOT RUN (not a failure) — \`${gate.cmd}\` exited non-zero having ` +
        `evaluated ${ran ? ran.total : 0} tests, then passed on an immediate re-run. That is a ` +
        `crashed runner, not a red suite: no test failed, so there is nothing here to fix. The ` +
        `crashed attempt ended:\n${first.out.trim().slice(-800)}`,
    );
    return;
  }

  const reran = gate.results(second.out);
  if (reran && reran.failed > 0) return fail(gate, why, second.out);
  return fail(
    gate,
    why,
    second.out,
    `NOTE: this ran TWICE and reported no test results either time, so the output below is a ` +
      `runner/collection error rather than a failed assertion — do not go looking for a broken ` +
      `test. It is a red because it reproduced: a crash that will not reproduce is downgraded ` +
      `to a note instead.\n`,
  );
}

function main() {
  if (DRY_RUN) {
    const lines = [
      `stop-gates --dry-run — ${changed.length} changed file(s), ${selected.length} gate(s) selected` +
        `${FULL ? ' (FULL: deferred gates would run)' : ''}`,
    ];
    for (const gate of selected) {
      const why = skipReason(gate);
      const verb = why ? 'would SKIP' : gate.deferred && !FULL ? 'would OWE ' : 'would run ';
      lines.push(
        `${verb} [${gate.label}] ${gate.cwd ? `(cd ${gate.cwd}) ` : ''}${gate.cmd}   — ${gate.cost}`,
        `            because ${fmtTriggers(triggers.get(gate))}`,
      );
      if (why) lines.push(`            skipped: ${why}`);
    }
    const idle = GATES.filter((g) => !triggers.has(g)).map((g) => g.label);
    if (idle.length) lines.push(`not selected: ${idle.join(', ')}`);
    process.stdout.write(`${lines.join('\n')}\n`);
    process.exit(0);
  }

  for (const gate of selected) {
    const why = skipReason(gate);
    if (why) {
      notes.push(`[${gate.label}] SKIPPED (not a failure) — ${why}. \`${gate.cmd}\` did not run.`);
      continue;
    }
    // Rule 4: too expensive to pay per-turn. Name it, don't run it.
    if (gate.deferred && !FULL) {
      owed.push(
        `[${gate.label}] OWED, not run (${gate.cost}) — selected by ${fmtTriggers(triggers.get(gate))}\n` +
          `    ${gate.cwd ? `cd ${gate.cwd} && ` : ''}${gate.cmd}`,
      );
      continue;
    }
    run(gate, triggers.get(gate));
  }

  const tail = [
    owed.length
      ? `The turn was not blocked on these, but they are what /build and ship.js will run:\n${owed.join('\n')}`
      : '',
    notes.length ? notes.join('\n') : '',
  ]
    .filter(Boolean)
    .join('\n\n');

  if (failures.length === 0) {
    // Owed work and skips are information, not a block: stdout, exit 0.
    if (tail) fs.writeSync(1, `${tail}\n`);
    process.exit(0);
  }

  fs.writeSync(2, `${failures.join('\n\n')}${tail ? `\n\n${tail}` : ''}\n`);
  process.exit(2);
}

if (IS_MAIN) {
  main();
} else {
  module.exports = { GATES, REPO_ROOT, canonicalRoot, vitestResults, pytestResults, run };
}
