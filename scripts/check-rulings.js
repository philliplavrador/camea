#!/usr/bin/env node
// Every ruling in docs/BEHAVIOUR.md should be backed by a Playwright test.
//
//   node scripts/check-rulings.js            → list rulings with no test in web/tests/e2e/
//   node scripts/check-rulings.js --strict   → and exit 1 if there are any
//   node scripts/check-rulings.js --max 13   → exit 1 only if there are MORE than 13
//
// ─── The ratchet, and why it is a --max rather than a --strict ───────────────
//
// On 2026-08-13, when this was written, **13 of 48 rulings had no citation** — R1, R16,
// R18, R25, R26, R30, R31, R32, R34, R35, R36, R39, R45.9. Wiring `--strict` into the Stop
// hook that day would have reddened every turn that touched docs/BEHAVIOUR.md, on a debt
// nobody in that turn created. A checker that is always red is a checker everyone learns to
// skip, and then the next real gap reads exactly like the noise.
//
// So the gate passes `--max 13`: the existing debt is tolerated, and **adding a 14th
// uncited ruling fails**. That is the property worth having — a new ruling arrives with a
// test or it does not arrive. When somebody covers one of the thirteen, lower the number in
// .claude/hooks/stop-gates.js and the ratchet closes behind them.
//
// ─── Why this exists ─────────────────────────────────────────────────────────
//
// CLAUDE.md: *"The ~44 decisions the user paid days to discover … are captured there as
// testable statements, each backed by a Playwright test in web/tests/e2e/."* That sentence
// is the contract, and nothing enforced it. A ruling with no test is not a ruling — it is a
// hope, and the first refactor that contradicts it does so silently.
//
// This is the Camea analogue of the check Labstock runs on its migrations (does the
// migration's change appear in schema.sql?): a document claims something is true, and this
// asks whether anything actually proves it.
//
// ─── What "backed by" means here, and what it does NOT mean ──────────────────
//
// It means the ruling's identifier appears somewhere in `web/tests/e2e/**` — a test name, a
// comment above the assertion, a fixture note. That is a **citation check, not a coverage
// check.** It cannot tell you the test actually exercises the ruling, only that somebody
// connected the two. A test named `R31` that asserts nothing still passes this.
//
// That is a deliberately weak bar and it is still worth having, because the failure it
// catches is the common one: a ruling gets written down and no test is ever written for it.
// The strong version of this check is a person reading the spec.
//
// ─── Sub-rulings ─────────────────────────────────────────────────────────────
//
// A ruling may be sub-numbered (R45.8). A spec citing `R45.8` counts for R45.8; a spec
// citing bare `R45` counts for R45 and for nothing beneath it, because the sub-numbers were
// added precisely when one ruling grew several separable claims.

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const BEHAVIOUR = path.join(ROOT, 'docs', 'BEHAVIOUR.md');
const E2E = path.join(ROOT, 'web', 'tests', 'e2e');

const STRICT = process.argv.includes('--strict');
const maxIdx = process.argv.indexOf('--max');
// `--max 0` is meaningful (identical to --strict), so test for the flag, not for truthiness.
const MAX = maxIdx !== -1 ? Number(process.argv[maxIdx + 1]) : null;

if (!fs.existsSync(BEHAVIOUR)) {
  console.error('✗ docs/BEHAVIOUR.md is missing.');
  process.exit(1);
}
if (!fs.existsSync(E2E)) {
  console.log('web/tests/e2e/ is not present, so ruling coverage cannot be checked here.');
  process.exit(0);
}

// `### R44 — …` / `#### R45.8 — …`
const rulings = [];
for (const line of fs.readFileSync(BEHAVIOUR, 'utf8').split(/\r?\n/)) {
  const m = /^#{2,4}\s+(R\d+(?:\.\d+)?)\b\s*[—–-]?\s*(.*)$/.exec(line.trim());
  if (m) rulings.push({ id: m[1], title: m[2].replace(/^[⭐\s]+/, '').slice(0, 70) });
}

// One read of every spec, then one regex per ruling over the joined text. The suite is a
// few dozen files; reading them once is cheaper than walking them 48 times.
let corpus = '';
(function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full);
    else if (/\.(ts|tsx|js|mjs)$/.test(entry.name)) corpus += `\n${fs.readFileSync(full, 'utf8')}`;
  }
})(E2E);

const uncited = rulings.filter(
  // Word-boundary on both sides so `R4` does not match `R45`, and `R45` does not match
  // `R45.8` — a sub-ruling has to be cited by its own number.
  (r) => !new RegExp(`\\b${r.id.replace('.', '\\.')}(?![\\d.])`).test(corpus),
);

if (uncited.length) {
  console.error(`${uncited.length} of ${rulings.length} rulings are not cited by any e2e test:\n`);
  for (const r of uncited) console.error(`  ${r.id.padEnd(7)} ${r.title}`);
  console.error(
    `\nCLAUDE.md says every ruling is backed by a Playwright test in web/tests/e2e/.\n` +
      `Cite the ruling's number in the test that proves it — in the test name or in a\n` +
      `comment above the assertion — so the two can be found from each other.\n` +
      `(This is a citation check, not a coverage check: it proves somebody connected them,\n` +
      `not that the test exercises the ruling.)`,
  );
  if (STRICT) process.exit(1);
  if (MAX !== null && Number.isFinite(MAX) && uncited.length > MAX) {
    console.error(
      `\n⛔ ${uncited.length} uncited, and the ratchet allows ${MAX}. A ruling was added ` +
        `without a test.\n` +
        `   Cite it in a spec, or — if you genuinely mean to widen the debt — raise the ` +
        `--max in\n   .claude/hooks/stop-gates.js and say why.`,
    );
    process.exit(1);
  }
  process.exit(0);
}

console.log(`rulings: ${rulings.length}/${rulings.length} cited by web/tests/e2e/`);
