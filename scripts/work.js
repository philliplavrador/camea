#!/usr/bin/env node
// work.js — the branch mechanics behind /start-work and /commit-work.
//
// Two verbs and nothing else. The interviewing, the building and the judging all happen
// in the session; this file only moves refs, and it refuses in the cases where moving one
// would take somebody else's work with it.
//
//   node scripts/work.js start  <slug>    open wip/<slug> and switch to it
//   node scripts/work.js save   [message] commit whatever is outstanding, push it
//   node scripts/work.js finish           wip/<slug> -> ready/<slug>, push, back to master
//   node scripts/work.js where            what this checkout is on
//
// ─── Why `save` exists at all ────────────────────────────────────────────────
//
// Work is saved to a branch as it goes, and only shows as `ready` once /commit-work runs.
// The saving is not for him — he never reads those commits — it is so a session that dies
// or gets closed loses nothing. That matters most in a cloud session, where the machine
// holding an unpushed branch disappears with the session, so `save` pushes as well as
// commits.
//
// ─── What is different from Labstock's copy ──────────────────────────────────
//
// Labstock branches a pile from `origin/main`, because main IS production there — Railway
// builds every push to it — and branching from the local main would fold unshipped work
// into a new pile. Camea deploys nothing. `master` is just the trunk, so a pile branches
// from the LOCAL master and there is no ahead-of-origin refusal to make. Everything else
// is the same, including the refusals below, which are about other sessions rather than
// about production.

const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const REPO_ROOT = path.join(__dirname, '..');
const LOCK = path.join(REPO_ROOT, 'workflow', '.locks', 'main-checkout.json');
const TRUNK = 'master';
const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

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
    die(`git ${args.join(' ')} failed.`, String(e.stderr || e.message).trim());
    return null;
  }
}

const branch = () => git(['rev-parse', '--abbrev-ref', 'HEAD']);
// `-uall` because plain --porcelain collapses an untracked DIRECTORY to one entry (`?? scripts/`).
// The refusal below shows him the files that are in the way and counts them, and both would
// be wrong — a new directory of forty files would read as "1 uncommitted file".
const dirty = () => git(['status', '--porcelain', '-uall']) || '';

function readLock() {
  try {
    return JSON.parse(fs.readFileSync(LOCK, 'utf8'));
  } catch {
    return null;
  }
}

function slugFromBranch(b) {
  const m = /^(wip|ready)\/(.+)$/.exec(b || '');
  return m ? { prefix: m[1], slug: m[2] } : null;
}

function cmdWhere() {
  const b = branch();
  const p = slugFromBranch(b);
  const d = dirty();
  console.log(`branch      ${b}`);
  console.log(
    `pile        ${p ? `${p.slug} (${p.prefix === 'ready' ? 'ready' : 'in progress'})` : '— not on a pile —'}`,
  );
  console.log(`uncommitted ${d ? `${d.split('\n').length} file(s)` : 'none'}`);
  const lock = readLock();
  if (lock) {
    console.log(
      `lock        held by ${lock.holder}${lock.plan ? ` (plan ${lock.plan})` : ''} since ${lock.since}`,
    );
  }
}

function cmdStart(slug) {
  if (!slug) die('which piece of work? node scripts/work.js start <slug>');
  if (!SLUG.test(slug)) {
    die(
      `bad name "${slug}".`,
      'Lowercase letters, digits and single hyphens.\n' +
        `  Try: ${slug
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, '-')
          .replace(/^-|-$/g, '')}`,
    );
  }

  const d = dirty();
  if (d) {
    die(
      `this checkout has ${d.split('\n').length} uncommitted file(s), so switching branches would carry them onto the new pile.`,
      `${d.split('\n').slice(0, 8).join('\n')}\n\n` +
        'They may belong to another session. Commit them where they belong first.\n' +
        "Never stash, reset or restore to clear the way — that discards other sessions' work.",
    );
  }

  const lock = readLock();
  if (lock) {
    console.log(`! the checkout lock is held by ${lock.holder}${lock.plan ? ` (plan ${lock.plan})` : ''}.`);
    console.log('  The tree is clean, so this is proceeding — but if that session is still');
    console.log('  running, do this work somewhere else.\n');
  }

  const wip = `wip/${slug}`;
  const ready = `ready/${slug}`;
  for (const b of [wip, ready]) {
    if (git(['rev-parse', '--verify', '--quiet', b], { allowFail: true })) {
      die(`"${slug}" already exists as ${b}.`, 'Pick another name, or carry on with that one.');
    }
  }

  // Branch from the LOCAL trunk. Nothing deploys off master, so master is not a pointer to
  // anything running and there is no version of it to be "behind".
  git(['switch', '-c', wip, TRUNK]);
  console.log(`on ${wip}, branched from ${TRUNK}`);
  console.log('Work here. `work.js save` commits and pushes as you go; /commit-work finishes it.');
}

function cmdSave(message) {
  const b = branch();
  const p = slugFromBranch(b);
  if (!p) die(`this checkout is on "${b}", which is not a pile.`, 'Nothing to save. /start-work opens one.');

  if (!dirty()) {
    console.log('nothing to save');
  } else {
    git(['add', '-A']);
    git(['commit', '-q', '-m', message || `wip(${p.slug}): saving progress`]);
    console.log(`saved: ${git(['log', '-1', '--oneline'])}`);
  }

  // Push every time. The whole reason work is committed as it goes is that a session can
  // die, and a commit that only exists on a machine that disappears is not a save.
  const pushed = git(['push', '-u', 'origin', b, '--quiet'], { allowFail: true });
  console.log(
    pushed === null
      ? '! could not push — the work is committed locally but not on GitHub'
      : `pushed ${b}`,
  );
}

function cmdFinish() {
  const b = branch();
  const p = slugFromBranch(b);
  if (!p) die(`this checkout is on "${b}", which is not a pile.`);
  if (p.prefix === 'ready') {
    die(`${p.slug} is already finished.`, 'The board can land it: node scripts/piles.js');
  }

  if (dirty()) {
    git(['add', '-A']);
    git(['commit', '-q', '-m', `feat(${p.slug}): finishing touches`]);
    console.log('committed the last changes');
  }

  const ready = `ready/${p.slug}`;
  git(['branch', '-m', ready]);
  git(['push', '-u', 'origin', ready, '--quiet'], { allowFail: true });
  // Delete the old wip ref on GitHub, or the board sees the pile twice and 'ready' wins
  // by accident rather than by intent.
  git(['push', 'origin', '--delete', b, '--quiet'], { allowFail: true });
  git(['switch', TRUNK, '--quiet']);

  console.log(`${p.slug} is ready.`);
  console.log(`  ${ready} exists. Nothing has landed on ${TRUNK} — only shipping does that.`);
  console.log('  /show-commits picks what goes in.');
}

const [cmd, ...rest] = process.argv.slice(2);
if (cmd === 'start') cmdStart(rest[0]);
else if (cmd === 'save') cmdSave(rest.join(' ') || null);
else if (cmd === 'finish') cmdFinish();
else if (cmd === 'where' || !cmd) cmdWhere();
else die(`unknown command "${cmd}".`, 'start <slug> | save [message] | finish | where');
