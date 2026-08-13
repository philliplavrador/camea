#!/usr/bin/env node
// ship.js — land a ready pile on master.
//
// ─── What "ship" means here ──────────────────────────────────────────────────
//
// In Labstock, shipping is a deploy: Railway builds every push to main, so a ship puts
// code in front of a lab that is using it, and the whole apparatus around it — the
// after-hours rule, the scheduler, the add-only migration gate — exists because of that.
//
// **Camea deploys nothing.** There is no server, no release step and no user. So a ship
// here is a merge into master and nothing else, and that is deliberate rather than
// unfinished: the pile flow was imported whole on 2026-08-13, with the shipping half wired
// to the only thing there is to wire it to. If Camea ever grows a release step, this file
// is the one place that changes.
//
// ─── What it still buys you ──────────────────────────────────────────────────
//
// The merge is done with --no-commit, the gates are run on the MERGED tree, and the merge
// is committed only if they pass. That is the check Labstock does at ship time and it is
// the one thing a per-pile gate run cannot give you: two piles that each pass alone can
// fail together, and the merged result is the only place that shows up.
//
//   node scripts/ship.js <slug>              merge it, gates first
//   node scripts/ship.js <slug> --dry-run    say what would happen, change nothing
//   node scripts/ship.js <slug> --no-gates   merge without running them (say why out loud)
//
// ⛔ A pile touching the guarded engine is REFUSED unless you pass --guard-was-green,
//    because the 312/312 suite needs the 35 GB mirror and a GPU and no script may claim it
//    ran. See CLAUDE.md § The 312/312 solver guard is sacred.

const fs = require('fs');
const path = require('path');
const { execFileSync, spawnSync } = require('child_process');
const { listPiles, BASE } = require('./piles');

const REPO_ROOT = path.join(__dirname, '..');
const LOCK = path.join(REPO_ROOT, 'workflow', '.locks', 'main-checkout.json');

// Every gate that a script may honestly run. `e2e` is absent because it needs the app up
// with a dataset open; the engine guard is absent because it needs hardware. Both are
// named in the closing report instead, so nobody mistakes silence for a pass.
const GATE_CMDS = {
  ruff: { label: 'ruff', argv: ['uv', 'run', 'ruff', 'check', '.'] },
  mypy: { label: 'mypy', argv: ['uv', 'run', 'mypy'] },
  pytest: { label: 'pytest (fast)', argv: ['uv', 'run', 'pytest', '-q', '-m', 'not slow'] },
  links: { label: 'link check', argv: ['node', 'scripts/check-links.js'] },
  lint: { label: 'eslint', argv: ['npm', 'run', 'lint', '--silent'], cwd: 'web' },
  tsc: { label: 'tsc', argv: ['npx', 'tsc', '-b', '--noEmit'], cwd: 'web' },
  vitest: { label: 'vitest', argv: ['npm', 'test', '--silent'], cwd: 'web' },
  'check:api': { label: 'check:api', argv: ['npm', 'run', 'check:api', '--silent'], cwd: 'web' },
};

function die(msg, detail) {
  console.error(`REFUSED: ${msg}`);
  if (detail) console.error(detail);
  process.exit(1);
}

function git(args, { allowFail = false } = {}) {
  try {
    return execFileSync('git', args, {
      cwd: REPO_ROOT,
      encoding: 'utf8',
      maxBuffer: 32 * 1024 * 1024,
    }).trim();
  } catch (e) {
    if (allowFail) return null;
    throw new Error(`git ${args.join(' ')} failed: ${String(e.stderr || e.message).trim()}`);
  }
}

function run(gate) {
  const [cmd, ...rest] = gate.argv;
  const r = spawnSync(cmd, rest, {
    cwd: gate.cwd ? path.join(REPO_ROOT, gate.cwd) : REPO_ROOT,
    encoding: 'utf8',
    shell: process.platform === 'win32', // npm/npx/uv are .cmd shims on Windows
    maxBuffer: 64 * 1024 * 1024,
  });
  return { ok: r.status === 0, output: `${r.stdout || ''}${r.stderr || ''}`.trim() };
}

const argv = process.argv.slice(2);
const slug = argv.find((a) => !a.startsWith('--'));
const DRY = argv.includes('--dry-run');
const NO_GATES = argv.includes('--no-gates');
const GUARD_GREEN = argv.includes('--guard-was-green');

if (!slug) die('which pile? node scripts/ship.js <slug>', 'The board: node scripts/piles.js');

const pile = listPiles().find((p) => p.slug === slug);
if (!pile) die(`No pile called "${slug}".`, 'The board: node scripts/piles.js');

if (pile.state !== 'ready') {
  die(
    `"${slug}" is still in progress.`,
    'Only a ready pile lands. /commit-work marks one ready, once you have looked at it.',
  );
}

const branchNow = git(['rev-parse', '--abbrev-ref', 'HEAD']);
// `-uall`: plain --porcelain collapses an untracked directory to one entry, so the count
// and the file list in the refusal below would both understate what is in the way.
const dirty = git(['status', '--porcelain', '-uall']) || '';

if (dirty) {
  die(
    `this checkout has ${dirty.split('\n').length} uncommitted file(s).`,
    `${dirty.split('\n').slice(0, 8).join('\n')}\n\n` +
      'A merge would fold them in. Commit them where they belong first.\n' +
      'Never stash, reset or restore to clear the way.',
  );
}

if (fs.existsSync(LOCK)) {
  let lock = {};
  try {
    lock = JSON.parse(fs.readFileSync(LOCK, 'utf8'));
  } catch {
    /* unreadable lock is still a held lock */
  }
  die(
    `the checkout lock is held by ${lock.holder || 'somebody'}${lock.plan ? ` (plan ${lock.plan})` : ''}${lock.since ? `, since ${lock.since}` : ''}.`,
    'Somebody is editing files in this tree. Landing a merge under them corrupts their work.\n' +
      'If nothing is actually running, that session died holding the lock — ask before removing it.',
  );
}

// ⛔ The engine refusal. A script cannot run the 312/312 guard (35 GB mirror + a GPU,
// ~130 s) and must never imply that it did. So a pile touching the four guarded files
// stops here and asks for a human to say the guard was green.
if (pile.gates.engine && !GUARD_GREEN) {
  die(
    `"${slug}" touches the guarded engine: ${pile.gates.engineFiles.join(', ')}.`,
    'Those four files are byte-identical to archive/analysis/mosaic/ and are the only thing\n' +
      'the 312/312 solver guard protects. Nothing automatic runs it — it needs the 35 GB\n' +
      'mirror and a GPU, and takes about 130 seconds:\n\n' +
      '  uv run pytest tests/slow/test_solver_312.py -q -m slow -s\n\n' +
      'Run it. If it is GREEN, land the pile with --guard-was-green.\n' +
      'If it is RED: stop. Do not fix forward. (CLAUDE.md § The 312/312 solver guard is sacred.)',
  );
}

const owed = pile.gates.owed.filter((g) => GATE_CMDS[g]);
const unrunnable = pile.gates.owed.filter((g) => !GATE_CMDS[g]);

console.log(`${slug} — ${pile.commits} commit(s), ${pile.files.length} file(s), onto ${BASE}`);
console.log(`gates: ${owed.length ? owed.join(', ') : 'none'}${NO_GATES ? '  (SKIPPED by --no-gates)' : ''}`);
if (unrunnable.length) console.log(`by hand afterwards: ${unrunnable.join(', ')}`);
if (pile.gates.engine) console.log('⛔ engine touched — the 312/312 guard was declared green by hand');
if (pile.gates.behaviour) console.log('⚠ docs/BEHAVIOUR.md is edited — a ruling is changing');

if (DRY) {
  console.log('\n--dry-run: nothing was changed.');
  process.exit(0);
}

// ─── The merge ───────────────────────────────────────────────────────────────
// --no-commit --no-ff: the merged tree exists in the working copy and the index, but no
// commit yet, so `git merge --abort` is a clean and complete undo if a gate goes red.

if (branchNow !== BASE) {
  git(['switch', BASE, '--quiet']);
  console.log(`switched to ${BASE}`);
}

const ref = pile.remoteRef || pile.localRef;
try {
  execFileSync('git', ['merge', '--no-commit', '--no-ff', ref], {
    cwd: REPO_ROOT,
    encoding: 'utf8',
  });
} catch (e) {
  const conflicts = git(['diff', '--name-only', '--diff-filter=U'], { allowFail: true }) || '';
  git(['merge', '--abort'], { allowFail: true });
  die(
    `${slug} does not merge cleanly into ${BASE}.`,
    (conflicts ? `Conflicting:\n${conflicts}\n\n` : '') +
      'The merge was aborted and this tree is untouched. Rebase the pile on ' +
      `${BASE} and try again.\n${String(e.stderr || e.message).trim()}`,
  );
}

console.log(`merged ${ref} into ${BASE} (not committed yet)\n`);

if (!NO_GATES) {
  const failed = [];
  for (const key of owed) {
    const gate = GATE_CMDS[key];
    process.stdout.write(`  ${gate.label} … `);
    const { ok, output } = run(gate);
    console.log(ok ? 'ok' : 'RED');
    if (!ok) failed.push({ key, label: gate.label, output });
  }

  if (failed.length) {
    git(['merge', '--abort'], { allowFail: true });
    console.error(`\nREFUSED: ${failed.length} gate(s) red on the MERGED tree.\n`);
    for (const f of failed) {
      console.error(`── ${f.label} ──`);
      console.error(f.output.split('\n').slice(-40).join('\n'));
      console.error('');
    }
    console.error(
      `The merge was aborted, so ${BASE} is exactly as it was and the pile is untouched.\n` +
        'Two piles that each pass alone can fail together — that is what this run is for.\n' +
        `Fix it on ${ref}, then ship again.`,
    );
    process.exit(1);
  }
  console.log('\nall gates green on the merged tree');
}

git(['commit', '--no-edit', '--quiet']);
console.log(`\n${slug} is on ${BASE}: ${git(['log', '-1', '--oneline'])}`);
console.log('Nothing was pushed — that is your call.');
if (unrunnable.length) {
  console.log(`\nStill owed by hand: ${unrunnable.join(', ')}`);
  if (unrunnable.includes('e2e')) {
    console.log('  cd web && npm run e2e     (needs the backend running)');
  }
}
