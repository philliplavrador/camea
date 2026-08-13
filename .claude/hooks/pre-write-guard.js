#!/usr/bin/env node
// PreToolUse (Bash|PowerShell|Edit|Write|MultiEdit|NotebookEdit) — refuse the small number
// of actions in this repo that are irreversible, destroy another session's work, or quietly
// break the science.
//
// Imported from Labstock's pre-destructive-db.js on 2026-08-13. That file guards a Postgres
// database; Camea has none. What Camea has instead is three things that cannot be undone by
// re-running a command, and they are the whole content of this file:
//
//   1. `data/` is a READ-ONLY 35 GB rclone mirror. CLAUDE.md: "NEVER WRITE HERE."
//      Nothing in this repo writes there, so any write is a mistake, and a mistake there
//      can silently corrupt the only copy of the raw microscopy.
//   2. `src/camea/engine/{t27,t33,quality,render}.py` are BYTE-IDENTICAL to
//      archive/analysis/mosaic/ and are the only thing the 312/312 solver guard protects.
//      ruff is configured NOT to see them, precisely so nobody can `--fix` them by
//      accident — which means a `ruff format` aimed at the tree is the realistic way they
//      get damaged.
//   3. `git restore` / `git checkout -- <path>` / `git reset --hard` / `git clean` discard
//      whatever is in the working tree, and this tree is shared: a /build team, a /resolve
//      pass and this session are all in it. There is no worktree to absorb the loss.
//
// ─── PERFORMANCE, AND WHY EVERY FUTURE CHECK GOES IN THIS FILE ───────────────
//
// PreToolUse matchers match tool NAMES, not command text, so this file runs on EVERY Bash
// and EVERY edit — hundreds of times a session. It therefore requires nothing but `fs`
// (for the fd-0 read), does ZERO filesystem I/O, and does all its work on one string. The
// process spawn is the entire bill; the matching is free.
//   ⇒ ANY FUTURE PreToolUse CHECK MUST BE ADDED INSIDE THIS FILE, not registered as a
//     second hook. Cost scales with the number of hooks, not the work inside them.
//
// ─── deny vs ask ─────────────────────────────────────────────────────────────
//
// `data/` and the destructive git commands are **deny**: nothing legitimate does them, and
// an agent must not be able to reach for one to unblock itself.
//
// The engine is **ask**, not deny, and that difference is deliberate. He may genuinely want
// the engine changed one day, and a hook that makes it impossible is a wall rather than a
// guard. What the prompt buys is that the change is never accidental and never silent — he
// sees it, and the reason, before it happens.
//
// Fails OPEN on every internal error (exit 0, silent). A guard that can break every tool
// call in a session is worse than the hazard it guards.

const fs = require('fs');

// ─── The four guarded engine files ───────────────────────────────────────────
const ENGINE = /(^|[\\/])src[\\/]camea[\\/]engine[\\/](t27|t33|quality|render)\.py$/i;
// A tree-wide formatter/fixer that would reach them. `ruff check .` alone is fine — it only
// reports. `--fix` and `format` rewrite.
const RUFF_WRITES = /\bruff\s+(format\b|check\b[^|;&]*\s--fix\b|check\b[^|;&]*\s--unsafe-fixes\b)/;

// ─── The read-only mirror ────────────────────────────────────────────────────
// Repo-relative `data/…` or `./data/…`, plus an absolute path ending in `/Camea/data/…`.
const DATA_PATH = /(^|[\s"'=])(\.[\\/])?data[\\/]|[\\/]camea[\\/]data[\\/]/i;
// Commands that write. `ls data/`, `cat data/x`, `find data/` and friends are fine and must
// stay fine — the mirror is for reading.
const WRITERS =
  /\b(rm|rmdir|mv|cp|touch|mkdir|dd|truncate|tee|chmod|chown|unlink|shred|Remove-Item|Move-Item|Copy-Item|New-Item|Set-Content|Add-Content|Out-File)\b/;
const RCLONE_WRITES = /\brclone\s+(sync|copy|move|copyto|moveto|delete|purge|rmdir|mkdir)\b/;
// A shell redirect INTO the mirror: `> data/x`, `>> ./data/x`.
const REDIRECT_INTO_DATA = />>?\s*(\.[\\/])?data[\\/]/i;

// ─── Working-tree destroyers ─────────────────────────────────────────────────
const TREE_DESTROYERS = [
  { re: /\bgit\s+restore\b/, name: 'git restore' },
  { re: /\bgit\s+checkout\s+--\s/, name: 'git checkout -- <path>' },
  { re: /\bgit\s+reset\s+--hard\b/, name: 'git reset --hard' },
  { re: /\bgit\s+clean\b[^|;&]*-[a-z]*[fd]/, name: 'git clean -f/-d' },
  { re: /\bgit\s+stash\b(?!\s+(list|show))/, name: 'git stash' },
];

function decide(kind, reason) {
  process.stdout.write(
    JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'PreToolUse',
        permissionDecision: kind,
        permissionDecisionReason: reason,
      },
    }),
  );
  process.exit(0);
}

function main() {
  let payload;
  try {
    payload = JSON.parse(fs.readFileSync(0, 'utf8'));
  } catch {
    process.exit(0); // no stdin / malformed → allow
  }

  const input = payload?.tool_input || {};

  // ── The edit tools: judge the path ────────────────────────────────────────
  const filePath = input.file_path || input.notebook_path;
  if (typeof filePath === 'string' && filePath) {
    if (ENGINE.test(filePath)) return decide('ask', engineReason(filePath));
    if (DATA_PATH.test(filePath)) return decide('deny', dataReason(filePath));
    process.exit(0);
  }

  // ── The shells: judge the command ─────────────────────────────────────────
  const command = input.command;
  if (typeof command !== 'string' || !command) process.exit(0);

  // One shell line can hold several invocations. Split on the operators so a match in
  // `echo "never rm data/"` can't be blamed on a neighbouring real command.
  for (const part of command.split(/&&|\|\||;|\||\n/)) {
    const seg = part.trim();
    if (!seg) continue;

    if (RUFF_WRITES.test(seg)) return decide('ask', ruffReason(seg));

    const writesToData =
      (DATA_PATH.test(seg) && (WRITERS.test(seg) || RCLONE_WRITES.test(seg))) ||
      REDIRECT_INTO_DATA.test(seg);
    if (writesToData) return decide('deny', dataReason(seg));

    for (const d of TREE_DESTROYERS) {
      if (d.re.test(seg)) return decide('deny', treeReason(d.name, seg));
    }
  }

  process.exit(0); // the overwhelmingly common case: print NOTHING
}

function engineReason(what) {
  return (
    `This touches the GUARDED ENGINE.\n\n` +
    `  ${what}\n\n` +
    `src/camea/engine/{t27,t33,quality,render}.py are byte-identical copies of ` +
    `archive/analysis/mosaic/ and are the only thing tests/slow/test_solver_312.py ` +
    `protects — 312 tiles within 10 px of the hand-authored ground truth, pass-1 deviation ` +
    `exactly 0. pyproject.toml excludes these four from ruff on purpose (they trip 29 ` +
    `cosmetic errors and all 29 stay), so a reformat here is not a cleanup, it is an ` +
    `unreviewed edit to the placement science.\n\n` +
    `If this change is deliberate and he asked for it, approve and then run the guard by ` +
    `hand — nothing runs it for you (35 GB mirror + a GPU, ~130 s):\n` +
    `  uv run pytest tests/slow/test_solver_312.py -q -m slow -s\n` +
    `If it goes RED: stop. Do not fix forward. (CLAUDE.md § The 312/312 solver guard is sacred.)`
  );
}

function dataReason(what) {
  return (
    `Refused: this writes into data/.\n\n` +
    `  ${what}\n\n` +
    `data/ is the read-only ~35 GB rclone mirror of the Drive folder. CLAUDE.md says ` +
    `plainly: NEVER WRITE HERE. It is the raw microscopy, nothing in this repo writes to ` +
    `it, and a mistake there is not recoverable from anything in this checkout.\n\n` +
    `Reading it is fine — ls, cat, find, python open() for read. If you need to WRITE ` +
    `something derived from a dataset, it belongs in the project's own directory under ` +
    `%LOCALAPPDATA%/Camea/projects/<analysis_id>/outputs/ (BEHAVIOUR R44), or in your ` +
    `session scratchpad if it is throwaway.`
  );
}

function treeReason(name, what) {
  return (
    `Refused: \`${name}\` discards work in this checkout.\n\n` +
    `  ${what}\n\n` +
    `This working tree is shared. A /build team, a /resolve pass and this session can all ` +
    `be in it at once, and there is no worktree to absorb the loss — whatever it throws ` +
    `away may be somebody else's half-finished plan, with no record that it existed.\n\n` +
    `If files are in the way of something you need to do: find out whose they are and ` +
    `commit them where they belong. If you genuinely need to discard your OWN changes, ` +
    `name the exact files and say so out loud first — never sweep the tree.`
  );
}

function ruffReason(what) {
  return (
    `This runs ruff in WRITE mode over the tree.\n\n` +
    `  ${what}\n\n` +
    `pyproject.toml excludes src/camea/engine/{t27,t33,quality,render}.py from ruff so that ` +
    `their 29 cosmetic errors can never be "fixed" by accident — those four files are ` +
    `byte-identical to the research original and under the 312/312 guard. The exclusion ` +
    `should hold, but a formatter aimed at the whole tree is the realistic way they get ` +
    `damaged, and the damage is silent.\n\n` +
    `If you meant it, approve — then run \`node scripts/check-engine.js\` afterwards to ` +
    `prove the four files did not move.`
  );
}

try {
  main();
} catch {
  process.exit(0); // a broken guard must never block a tool call it has no opinion on
}
