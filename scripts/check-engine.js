#!/usr/bin/env node
// Prove the guarded engine is still byte-identical to the research original.
//
//   node scripts/check-engine.js     → exit 1 if any of the four files has drifted
//
// ─── What this is protecting ─────────────────────────────────────────────────
//
// `src/camea/engine/{t27,t33,quality,render}.py` are BYTE-IDENTICAL copies of
// `archive/analysis/mosaic/`. CLAUDE.md: *"The engine is byte-identical to the research
// original; do not reformat or 'improve' it."* They currently trip 29 ruff errors, all
// cosmetic, and `pyproject.toml` excludes them from the linter **so that nobody can fix
// those errors by accident** — which means the linter cannot be the thing that notices a
// change here. This can.
//
// The real guard is `tests/slow/test_solver_312.py`: 312 tiles within 10 px of the
// hand-authored ground truth, pass-1 deviation exactly 0. It takes ~130 s, needs a GPU and
// the 35 GB mirror, and therefore **cannot run in CI and is never run automatically**. This
// script is the cheap half — it costs one file read each and answers a narrower question:
// *did the bytes move?* A green here is not a green there.
//
// ─── Why a missing archive/ is a note, not a failure ─────────────────────────
//
// `archive/` is gitignored (~32 GB of finished research), so it is absent on a fresh
// clone, in CI, and inside the /bug-hunter worktree. A gate that goes red because a
// gitignored directory is missing is a gate everyone learns to skip, and then the next real
// drift reads exactly like the noise. So: no archive → exit 0, say why.

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const LIVE = path.join(ROOT, 'src', 'camea', 'engine');
const ORIGINAL = path.join(ROOT, 'archive', 'analysis', 'mosaic');
const FILES = ['t27.py', 't33.py', 'quality.py', 'render.py'];

if (!fs.existsSync(ORIGINAL)) {
  console.log(
    `archive/analysis/mosaic/ is not present, so drift cannot be checked here.\n` +
      `  (archive/ is gitignored — absent on a fresh clone, in CI, and in a hunt worktree.)\n` +
      `  The four engine files were NOT verified. Run this on the machine that has the mirror.`,
  );
  process.exit(0);
}

const drifted = [];
const missing = [];

for (const name of FILES) {
  const live = path.join(LIVE, name);
  const orig = path.join(ORIGINAL, name);
  if (!fs.existsSync(live)) {
    missing.push(`src/camea/engine/${name} is gone`);
    continue;
  }
  if (!fs.existsSync(orig)) {
    missing.push(`archive/analysis/mosaic/${name} is gone — cannot compare ${name}`);
    continue;
  }
  const a = fs.readFileSync(live);
  const b = fs.readFileSync(orig);
  if (!a.equals(b)) {
    // Name the first differing line so the message is actionable rather than just alarming.
    const la = a.toString('utf8').split(/\r?\n/);
    const lb = b.toString('utf8').split(/\r?\n/);
    let at = 0;
    while (at < la.length && at < lb.length && la[at] === lb[at]) at++;
    drifted.push({
      name,
      line: at + 1,
      live: (la[at] ?? '<end of file>').trim().slice(0, 100),
      orig: (lb[at] ?? '<end of file>').trim().slice(0, 100),
      bytes: `${a.length} vs ${b.length}`,
    });
  }
}

for (const m of missing) console.error(`✗ ${m}`);

for (const d of drifted) {
  console.error(`✗ src/camea/engine/${d.name} has DRIFTED from the research original.`);
  console.error(`    first difference at line ${d.line}  (${d.bytes} bytes)`);
  console.error(`    live     ${d.live}`);
  console.error(`    original ${d.orig}`);
  console.error(`    diff src/camea/engine/${d.name} archive/analysis/mosaic/${d.name}`);
}

if (drifted.length || missing.length) {
  console.error(
    `\nThose four files are the guarded science and are supposed to be byte-identical\n` +
      `(CLAUDE.md § The 312/312 solver guard is sacred). A reformat is not a cleanup here,\n` +
      `it is an unreviewed edit to the placement engine.\n\n` +
      `If the change was NOT deliberate: revert it.\n` +
      `  git checkout -- src/camea/engine/\n\n` +
      `If it WAS deliberate and he approved it: the 312/312 guard has to be run by hand,\n` +
      `because nothing runs it for you — it needs the 35 GB mirror and a GPU, ~130 s:\n` +
      `  uv run pytest tests/slow/test_solver_312.py -q -m slow -s\n` +
      `312/312 within 10 px, pass-1 deviation exactly 0. If it is RED: stop, and do not\n` +
      `fix forward.`,
  );
  process.exit(1);
}

console.log(`engine: ${FILES.length} files byte-identical to archive/analysis/mosaic/`);
