#!/usr/bin/env node
// piles.js — what work is sitting around, and what state it is in.
//
// The data layer under /show-commits, /preview and /commit-work. It knows nothing about
// landing anything; it answers "what is there and what would each one do".
//
// ─── The two prefixes are the state ──────────────────────────────────────────
//
//   wip/<slug>      in progress — /start-work is still going
//   ready/<slug>    /commit-work has been run; this may be landed
//
// State is the branch name, deliberately, and it is the same reasoning as
// workflow/issues/ using directories: moving the thing IS the change, so it survives a
// session ending badly, shows up in `git branch`, and needs no metadata file that can
// disagree with reality. There is nothing to keep in sync.
//
// BOTH ARE PUSHED TO ORIGIN where they can be. A wip branch on GitHub is what makes "a
// session that dies loses nothing" true. Being on GitHub is NOT what makes something
// landable; the prefix is.
//
// ─── What is different from Labstock's copy ──────────────────────────────────
//
// Labstock's board carries a DB column, because a pile there can hold a migration that
// rewrites production. Camea has no database and no deployment. What a Camea pile carries
// instead is GATES — which suites it owes before anyone believes it, derived from the
// files it touches. The one that matters is `engine`: a pile touching
// src/camea/engine/{t27,t33,quality,render}.py owes the 312/312 solver guard, which needs
// the 35 GB mirror and a GPU and takes ~130 s, and which nothing automatic will ever run.
//
// There is also no scheduled shipping here. Labstock schedules a ship because a ship is a
// deploy that should happen after lab hours. Landing a Camea pile is a merge into master
// and nothing else, so there is nothing to wait for.
//
// ─── The base is the local master ────────────────────────────────────────────
//
// Nothing deploys off master, so master is not a pointer at anything running — it is just
// the trunk, and /build commits to it directly and may not have pushed. So "what would this
// pile change" is measured against the LOCAL master, not against origin.
//
// Usage:
//   node scripts/piles.js                 human-readable board
//   node scripts/piles.js --json          the same as JSON
//   node scripts/piles.js --slug <slug>   one pile, as JSON

const path = require('path');
const { execFileSync } = require('child_process');

const REPO_ROOT = path.join(__dirname, '..');
const BASE = 'master';
const STALE_DAYS = 7;
const OVERLAP_LINES = 5;

// The four files that are byte-identical to archive/analysis/mosaic/ and under the 312/312
// guard (CLAUDE.md § The 312/312 solver guard is sacred). Touching one is not an ordinary
// change and the board says so in capitals.
const GUARDED_ENGINE = [
  'src/camea/engine/t27.py',
  'src/camea/engine/t33.py',
  'src/camea/engine/quality.py',
  'src/camea/engine/render.py',
];

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

// Refs under both prefixes, local and remote, folded into one entry per slug. A pile
// worked on elsewhere exists only on origin; one just started exists only locally. Either
// is a real pile.
function collectRefs() {
  const out = git(
    [
      'for-each-ref',
      '--format=%(refname)%09%(committerdate:unix)',
      'refs/heads/wip',
      'refs/heads/ready',
      'refs/remotes/origin/wip',
      'refs/remotes/origin/ready',
    ],
    { allowFail: true },
  );

  const bySlug = new Map();
  for (const line of (out || '').split('\n').filter(Boolean)) {
    const [refname, ts] = line.split('\t');
    const m = /^refs\/(heads|remotes\/origin)\/(wip|ready)\/(.+)$/.exec(refname);
    if (!m) continue;
    const [, where, prefix, slug] = m;
    const local = where === 'heads';

    const entry = bySlug.get(slug) || {
      slug,
      local: null,
      remote: null,
      prefixes: new Set(),
      when: 0,
    };
    if (local) entry.local = `${prefix}/${slug}`;
    else entry.remote = `origin/${prefix}/${slug}`;
    entry.prefixes.add(prefix);
    entry.when = Math.max(entry.when, Number(ts) || 0);
    bySlug.set(slug, entry);
  }
  return [...bySlug.values()];
}

// What this pile owes before anybody believes it, read off the files it touches. This is
// the same table as workflow/plans/README.md § What `needs:` means, derived rather than
// declared — a pile has no frontmatter to declare it in.
function gatesFor(files) {
  const engine = files.filter((f) => GUARDED_ENGINE.includes(f));
  const py = files.some((f) => f.startsWith('src/camea/') || f.startsWith('tests/'));
  const api = files.some((f) => f.startsWith('src/camea/api/'));
  const web = files.some((f) => f.startsWith('web/'));
  const e2e = files.some((f) => f.startsWith('web/tests/e2e/'));
  const behaviour = files.includes('docs/BEHAVIOUR.md');

  const owed = [];
  if (py) owed.push('ruff', 'mypy', 'pytest');
  if (api) owed.push('check:api');
  if (web) owed.push('lint', 'tsc', 'vitest');
  if (e2e || behaviour) owed.push('e2e');
  if (files.some((f) => f.endsWith('.md'))) owed.push('links');

  return {
    engine: engine.length > 0,
    engineFiles: engine,
    behaviour,
    owed: [...new Set(owed)],
    // The one line the board prints. Capitals for the engine because it is the only case
    // where the honest answer is "stop and look at this".
    summary: engine.length
      ? `⛔ ENGINE (${engine.length} guarded file${engine.length === 1 ? '' : 's'})`
      : owed.length
        ? owed.join(' ')
        : 'no gates',
  };
}

function describePile(entry) {
  // Prefer the remote ref when both exist: it is what the board on another machine would
  // see, and a local branch ahead of its own remote means /commit-work has not pushed yet.
  const ref = entry.remote || entry.local;
  // 'ready' wins if either side carries it — /commit-work renames, and a half-finished
  // rename must not read as "still in progress" and become unlandable.
  const state = entry.prefixes.has('ready') ? 'ready' : 'in progress';

  const commits = git(['rev-list', '--count', `${BASE}..${ref}`], { allowFail: true });
  const filesRaw = git(['diff', '--name-only', `${BASE}...${ref}`], { allowFail: true });
  const files = filesRaw ? filesRaw.split('\n').filter(Boolean) : [];
  const behind = git(['rev-list', '--count', `${ref}..${BASE}`], { allowFail: true });

  const gates = gatesFor(files);
  const ageDays = entry.when ? Math.floor((Date.now() / 1000 - entry.when) / 86400) : null;

  return {
    slug: entry.slug,
    state,
    ref,
    localRef: entry.local,
    remoteRef: entry.remote,
    pushed: Boolean(entry.remote),
    commits: Number(commits || 0),
    files,
    behindBase: Number(behind || 0),
    gates,
    ageDays,
    stale: ageDays !== null && ageDays >= STALE_DAYS,
  };
}

// Files touched by more than one pile. Not a conflict — git merges most overlaps
// cleanly — but worth naming before landing two that will fight. The real protection is
// re-running the gates on the MERGED result, which is ship.js's job.
function markOverlaps(piles) {
  const owners = new Map();
  for (const p of piles) {
    for (const f of p.files) {
      if (!owners.has(f)) owners.set(f, []);
      owners.get(f).push(p.slug);
    }
  }
  for (const p of piles) p.overlaps = [];
  for (const [file, slugs] of owners) {
    if (slugs.length < 2) continue;
    for (const slug of slugs) {
      const p = piles.find((x) => x.slug === slug);
      p.overlaps.push({ file, with: slugs.filter((s) => s !== slug) });
    }
  }
  return piles;
}

function listPiles() {
  const piles = collectRefs().map(describePile);
  markOverlaps(piles);

  // Ready first, then in progress; stale sinks to the bottom of its group; newest first
  // within that. An untouched pile moves down, it is never binned for him.
  const rank = (p) => (p.stale ? 2 : 0) + (p.state === 'ready' ? 0 : 1);
  return piles.sort((a, b) => rank(a) - rank(b) || (b.ageDays ?? 0) - (a.ageDays ?? 0));
}

function render(piles) {
  if (!piles.length) {
    return 'Nothing in flight. /start-work begins something.';
  }
  // Widths from the content, not guessed. A board whose columns wander gets skimmed.
  const w = Math.max(...piles.map((p) => p.slug.length), 12);
  const gW = Math.max(...piles.map((p) => p.gates.summary.length), 8);
  const lines = [];
  for (const p of piles) {
    const commits = `${p.commits} commit${p.commits === 1 ? '' : 's'}`;
    const line = [
      `  ${p.slug.padEnd(w)}`,
      commits.padEnd(11),
      p.gates.summary.padEnd(gW),
      p.state.padEnd(12),
    ].join(' ');
    let out = line;
    if (p.stale) out += `  untouched ${p.ageDays} days`;
    if (!p.pushed) out += '  (not on GitHub yet)';
    if (p.behindBase > 0) out += `  ${p.behindBase} behind ${BASE}`;
    lines.push(out);
    if (p.gates.engine) {
      lines.push(
        `  ${' '.repeat(w)} ⛔ touches ${p.gates.engineFiles.join(', ')} — the 312/312 guard must be run by hand`,
      );
    }
    if (p.gates.behaviour) {
      lines.push(`  ${' '.repeat(w)} ⚠ edits docs/BEHAVIOUR.md — a ruling is changing`);
    }
    // Capped, because the board is read at a glance. Two piles that both touch a whole
    // subsystem can share dozens of files, and a screenful of ⚠ lines buries every other
    // pile on the board. The count is the signal; --json has the full list.
    for (const o of p.overlaps.slice(0, OVERLAP_LINES)) {
      lines.push(`  ${' '.repeat(w)} ⚠ shares ${o.file} with ${o.with.join(', ')}`);
    }
    if (p.overlaps.length > OVERLAP_LINES) {
      lines.push(
        `  ${' '.repeat(w)} ⚠ …and ${p.overlaps.length - OVERLAP_LINES} more shared file(s)`,
      );
    }
  }
  const ready = piles.filter((p) => p.state === 'ready').length;
  lines.push('');
  lines.push(`${piles.length} pile(s), ${ready} ready to land.`);
  return lines.join('\n');
}

module.exports = { listPiles, describePile, markOverlaps, gatesFor, BASE, STALE_DAYS };

if (require.main === module) {
  const argv = process.argv.slice(2);
  const slugIdx = argv.indexOf('--slug');
  try {
    let piles = listPiles();
    if (slugIdx !== -1) {
      const want = argv[slugIdx + 1];
      piles = piles.filter((p) => p.slug === want);
      if (!piles.length) {
        console.error(`No pile called "${want}".`);
        process.exit(1);
      }
    }
    console.log(
      argv.includes('--json') || slugIdx !== -1 ? JSON.stringify(piles, null, 2) : render(piles),
    );
  } catch (err) {
    console.error(`piles: ${err.message}`);
    process.exit(1);
  }
}
