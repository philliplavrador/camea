#!/usr/bin/env node
// Verify every relative markdown link and #anchor in the repo's docs.
//
// This exists because a heading rename silently breaks every link pointing at it, and
// nothing else in the toolchain notices. Docs here are Claude-facing ground truth — a
// dangling anchor sends a future session to the wrong place, or to nowhere.
//
//   node scripts/check-links.js     → exit 1 if anything dangles
//
// Only relative links are checked. http(s)/mailto/file are assumed fine; verifying them
// would need the network and would fail offline.
//
// ─── Two rules that keep it honest ───────────────────────────────────────────
//
// 1. **Links inside fenced code blocks, or wholly inside an inline code span, are
//    EXAMPLES and are never followed.** A template that shows `[foo](../../bar.md)` as
//    the form to copy is not claiming that file exists.
//
// 2. **A numbered plan or issue is resolved across its sibling state directories.** A
//    plan's state IS its directory, so every `/build` claim and `/resolve` close moves the
//    file — the checker knows the convention rather than reddening on it. A file present
//    in two state directories at once is reported loudly; that is a half-finished `git mv`.
//
// ─── Why some trees are skipped, and why docs/ is NOT ────────────────────────
//
// The archive halves — `workflow/plans/done/` and `workflow/issues/resolved/` — are skipped
// as link SOURCES. A finished plan and a closed issue are historical records: their links
// were correct on the day they were written, and repointing them would edit the record to
// cite paths it never cited. They are still checked as link TARGETS.
//
// The gitignored trees (`utils/`, `archive/`, `data/`, `learn/`, `output/`) are skipped
// outright. `utils/knowledge/` in particular holds notes written before the 2026-07-14
// revamp that describe the old `app/` + `analysis/` layout — CLAUDE.md says to read those
// as history, and a checker that goes permanently red on deliberate history is a checker
// everyone learns to skip, which is when the next real break reads like the noise.
//
// **`docs/` IS checked**, which is the opposite of the Labstock original this was imported
// from (2026-08-13). There, root `docs/` is the author's own hand-curated tree and is left
// alone. Here it is BEHAVIOUR.md, SPLIT.md, API.md and FRONTEND.md — the ground truth every
// other doc links into, and the place a dangling link costs the most.

const fs = require('fs');
const path = require('path');

// This file lives at scripts/, so the repo root is ONE level up.
// CHECK_LINKS_ROOT exists for testing against a throwaway tree; nothing else sets it.
const ROOT = process.env.CHECK_LINKS_ROOT
  ? path.resolve(process.env.CHECK_LINKS_ROOT)
  : path.resolve(__dirname, '..');

// Matched on BASENAME, so they skip at any depth.
const SKIP_DIRS = new Set([
  'node_modules',
  '.git',
  '.venv',
  '__pycache__',
  'dist',
  'build',
  '.pytest_cache',
  '.ruff_cache',
  '.mypy_cache',
  '.playwright-mcp',
  'playwright-report',
  'test-results',
]);

// Matched on PATH FROM THE REPO ROOT. See the header for why each is here.
const SKIP_PATHS = new Set([
  'utils', // Claude's knowledge base — gitignored, and deliberately historical
  'archive', // finished research + the old app — gitignored reference
  'data', // the read-only 35 GB mirror
  'learn', // big inlined-figure HTML explainers — gitignored
  'output', // rendered PNGs — gitignored
  'workflow/plans/done', // the record: correct when written, never followed again
  'workflow/issues/resolved',
]);

const MAX_DEPTH = 5;

const relFromRoot = (full) => path.relative(ROOT, full).split(path.sep).join('/');

// The plan/issue state families. A target missing from the directory it cites is looked
// for in its siblings before it is called broken.
const STATE_FAMILIES = [
  ['workflow/plans/queued', 'workflow/plans/active', 'workflow/plans/parked', 'workflow/plans/done'],
  [
    'workflow/issues/high',
    'workflow/issues/medium',
    'workflow/issues/low',
    'workflow/issues/resolved',
  ],
];

// ─── Scanning a markdown file for followable links ───────────────────────────

// Split on either line ending. The repo is checked out with core.autocrlf on Windows, so
// the working tree carries CRLF even though git stores LF — leave the \r in place and every
// heading picks up a trailing carriage return, which quietly poisons its slug.
const lines = (text) => text.split(/\r?\n/);

const MD_LINK = /\[([^\]]*)\]\(([^()\s]+(?:\([^()]*\)[^()\s]*)*)\)/g;

// Character ranges covered by an inline code span on this line. A link wholly inside one
// is an example, not a reference.
function codeSpansOn(line) {
  const spans = [];
  const re = /(`+)(?:(?!\1).)*\1/g;
  let m;
  while ((m = re.exec(line)) !== null) spans.push([m.index, m.index + m[0].length]);
  return spans;
}

function linksIn(text) {
  const out = [];
  let inFence = false;
  let fenceMark = '';
  lines(text).forEach((line, i) => {
    const fence = /^\s*(`{3,}|~{3,})/.exec(line);
    if (fence) {
      if (!inFence) {
        inFence = true;
        fenceMark = fence[1][0];
      } else if (fence[1][0] === fenceMark) {
        inFence = false;
      }
      return;
    }
    if (inFence) return;

    const spans = codeSpansOn(line);
    MD_LINK.lastIndex = 0;
    let m;
    while ((m = MD_LINK.exec(line)) !== null) {
      const start = m.index;
      const end = start + m[0].length;
      if (spans.some(([a, b]) => start >= a && end <= b)) continue; // wholly inside code
      out.push({ text: m[1], target: m[2], line: i + 1 });
    }
  });
  return out;
}

// ─── Resolving a moved plan or issue ─────────────────────────────────────────

function resolveAcrossStates(missing) {
  const rel = relFromRoot(missing);
  const dir = path.posix.dirname(rel);
  const base = path.posix.basename(rel);
  if (!/^\d{3}-/.test(base)) return null; // not a numbered plan/issue — report plainly

  const family = STATE_FAMILIES.find((f) => f.includes(dir));
  if (!family) return null;

  const found = family
    .map((d) => path.join(ROOT, d, base))
    .filter((p) => fs.existsSync(p));

  if (found.length === 0) return null;
  if (found.length > 1) {
    return {
      error:
        `exists in ${found.length} state directories at once (${found.map(relFromRoot).join(', ')}) — ` +
        'that is a half-finished git mv; delete the stray copy',
    };
  }
  return { file: found[0] };
}

// ─── Anchors ─────────────────────────────────────────────────────────────────

// github-slugger's order of operations, which is NOT the obvious one: trim the whole
// string FIRST, lowercase, strip punctuation and emoji, and only THEN convert the
// surviving spaces to hyphens. A heading that opens with an emoji ("## ⭐ STORAGE …")
// therefore keeps the space the emoji left behind, and its slug legitimately STARTS with
// a hyphen. Trim after stripping instead and you compute a different anchor, and every
// emoji heading in this repo looks broken when it isn't — CLAUDE.md alone has three.
const slug = (heading) =>
  heading
    .trim()
    .toLowerCase()
    .replace(/[^\w\s-]/gu, '')
    .replace(/\s/g, '-');

// `#L397` is a LINE anchor, not a heading anchor. GitHub renders it on source files, and
// an issue's Evidence block uses the same form to cite a doc by line. No heading ever
// slugifies to "l397", so checking one against the heading set rejects every such link.
const LINE_ANCHOR = /^L(\d+)(?:-L?(\d+))?$/;

const lineCountCache = new Map();
function lineCountOf(file) {
  if (!lineCountCache.has(file)) {
    let count = null;
    if (fs.existsSync(file)) {
      const ls = lines(fs.readFileSync(file, 'utf8'));
      // A file ending in a newline splits to a final empty string that is not a line.
      if (ls.length && ls[ls.length - 1] === '') ls.pop();
      count = ls.length;
    }
    lineCountCache.set(file, count);
  }
  return lineCountCache.get(file);
}

const anchorCache = new Map();
function anchorsOf(file) {
  if (!anchorCache.has(file)) {
    let set = null;
    if (fs.existsSync(file)) {
      set = new Set();
      let inFence = false;
      for (const line of lines(fs.readFileSync(file, 'utf8'))) {
        if (/^\s*(`{3,}|~{3,})/.test(line)) {
          inFence = !inFence;
          continue;
        }
        if (inFence) continue; // a `# comment` inside a fence is not a heading
        const m = /^(#{1,6})\s+(.*)$/.exec(line);
        if (m) set.add(slug(m[2]));
      }
    }
    anchorCache.set(file, set);
  }
  return anchorCache.get(file);
}

// ─── The walk ────────────────────────────────────────────────────────────────

const files = [];
(function walk(dir, depth) {
  if (depth > MAX_DEPTH) return;
  let entries;
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return; // unreadable directory is not a broken link
  }
  for (const entry of entries) {
    if (SKIP_DIRS.has(entry.name)) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (SKIP_PATHS.has(relFromRoot(full))) continue;
      walk(full, depth + 1);
    } else if (entry.name.endsWith('.md')) {
      files.push(full);
    }
  }
})(ROOT, 0);

let checked = 0;
const broken = [];

for (const file of files) {
  for (const link of linksIn(fs.readFileSync(file, 'utf8'))) {
    const target = link.target;
    // `file:` belongs here too. A finding citing evidence outside the repo —
    // ~/.claude/settings.json, say — writes it as a file:// URL, and treating that as a
    // repo-relative path reports a permanent phantom breakage.
    if (/^(https?:|mailto:|file:|#!)/.test(target)) continue;
    checked++;

    const hashAt = target.indexOf('#');
    const rel = hashAt === -1 ? target : target.slice(0, hashAt);
    const hash = hashAt === -1 ? '' : target.slice(hashAt + 1);
    let targetFile = rel ? path.resolve(path.dirname(file), rel) : file;
    const where = `${relFromRoot(file)}:${link.line}`;

    if (rel && !fs.existsSync(targetFile)) {
      const moved = resolveAcrossStates(targetFile);
      if (moved === null) {
        broken.push({ where, target, why: 'file does not exist' });
        continue;
      }
      if (moved.error) {
        broken.push({ where, target, why: moved.error });
        continue;
      }
      targetFile = moved.file; // anchors below validate against the RESOLVED file
    }

    if (!hash) continue;

    const lineAnchor = LINE_ANCHOR.exec(hash);
    if (lineAnchor) {
      // Range form `#L397-L405` — the END is what has to exist.
      //
      // Bounds-checking is deliberately weak and it is worth being honest about what it
      // buys: it catches a citation pointing PAST THE END of a file. It cannot catch one
      // that drifted onto the wrong line, because the wrong line almost always exists too.
      const last = Number(lineAnchor[2] || lineAnchor[1]);
      const count = lineCountOf(targetFile);
      if (count !== null && last > count) {
        broken.push({ where, target, why: `line ${last} is past the end (file has ${count})` });
      }
    } else if (targetFile.endsWith('.md')) {
      const anchors = anchorsOf(targetFile);
      if (anchors && !anchors.has(hash.toLowerCase())) {
        broken.push({ where, target, why: 'no heading produces this anchor' });
      }
    }
    // A non-line, non-heading anchor on a source file is not something we can check.
  }
}

for (const b of broken) {
  console.error(`✗ ${b.where}\n    → ${b.target}\n    ${b.why}`);
}
console.log(`\n${files.length} files · ${checked} internal links checked · ${broken.length} broken`);

if (broken.length) {
  console.error('\nA link or anchor is dangling. If you renamed a heading, repoint the links to it.');
  process.exit(1);
}
