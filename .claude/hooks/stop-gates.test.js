#!/usr/bin/env node
// Tests for stop-gates.js — the hook that decides whether a turn gets blocked.
//
//   node .claude/hooks/stop-gates.test.js
//
// Editing the gate hook without running these is the failure the hook itself exists to
// prevent, one level up — so `stop-gates.js` carries a gate row that runs this file when
// anything under .claude/hooks/ changes.
//
// Two things are worth testing and nothing else is:
//
//   1. **Which gates a path selects.** The table is the whole design, and a matcher that is
//      subtly wrong is invisible: the hook reports a clean pass over work it never checked.
//      That is not hypothetical — during the 2026-08-13 import, `git status --porcelain`
//      without `-uall` collapsed 29 new files in two new directories into 2 entries and
//      selected 0 of 11 gates, reporting green.
//
//   2. **Red vs crashed**, for the two test-runner parsers. A suite with a failing test must
//      block; a runner that fell over having evaluated nothing must not. Those are
//      indistinguishable from an exit code alone, and the parsers are what tell them apart.

const assert = require('assert');
const { GATES, vitestResults, pytestResults } = require('./stop-gates.js');

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    passed++;
  } catch (e) {
    failed++;
    console.error(`✗ ${name}\n  ${e.message}`);
  }
}

const selects = (p) =>
  GATES.filter((g) => g.match(p))
    .map((g) => g.label)
    .sort();

function expectGates(path, want) {
  test(`${path} → ${want.join(' ') || '(none)'}`, () => {
    assert.deepStrictEqual(selects(path), [...want].sort(), `got: ${selects(path).join(' ')}`);
  });
}

// ─── 1. Selection ────────────────────────────────────────────────────────────

// The guarded four, and only the guarded four, pull in the engine gate.
expectGates('src/camea/engine/t27.py', ['engine', 'ruff', 'pytest-unit', 'mypy']);
expectGates('src/camea/engine/t33.py', ['engine', 'ruff', 'pytest-unit', 'mypy']);
expectGates('src/camea/engine/quality.py', ['engine', 'ruff', 'pytest-unit', 'mypy']);
expectGates('src/camea/engine/render.py', ['engine', 'ruff', 'pytest-unit', 'mypy']);
// excluded.py lives in engine/ but is NOT guarded — it holds gaps(), a pure function, and
// is ordinary code. A matcher that caught it would block every turn that touched it.
expectGates('src/camea/engine/excluded.py', ['ruff', 'pytest-unit', 'mypy']);

// An api change owes the generated-contract check; a core change does not.
expectGates('src/camea/api/schemas.py', [
  'ruff',
  'check:api',
  'pytest-unit',
  'pytest-api',
  'mypy',
]);
expectGates('src/camea/core/dataset.py', ['ruff', 'pytest-unit', 'mypy']);
expectGates('src/camea/features/videomosaic/routes.py', [
  'ruff',
  'pytest-unit',
  'pytest-api',
  'mypy',
]);

// A hand-edited generated client is exactly what check:api exists to catch, so the file
// itself selects it.
expectGates('web/src/api/schema.d.ts', ['check:api', 'tsc', 'vitest', 'eslint']);
expectGates('web/src/features/mosaic/Sweep.tsx', ['tsc', 'vitest', 'eslint']);

// BEHAVIOUR.md and the e2e specs are two halves of one contract, so both pull the ratchet.
expectGates('docs/BEHAVIOUR.md', ['links', 'rulings', 'e2e']);
expectGates('web/tests/e2e/regions.spec.ts', ['rulings', 'tsc', 'eslint', 'e2e']);

// An api test changing must NOT drag in the 64s unit suite. Scope is the point of the table.
expectGates('tests/api/test_routes.py', ['ruff', 'pytest-api']);
expectGates('tests/unit/test_document.py', ['ruff', 'pytest-unit']);

// Nothing at all: the cheap path, one `git status` and done.
expectGates('pyproject.toml', []);
expectGates('uv.lock', []);

// This file, and the hook beside it.
expectGates('.claude/hooks/stop-gates.js', ['hooks']);
expectGates('.claude/hooks/stop-gates.test.js', ['hooks']);

// ─── 2. Red vs crashed ───────────────────────────────────────────────────────

test('vitest: a real red is a red', () => {
  const out = 'Test Files  1 failed | 1 passed (2)\n     Tests  1 failed | 2 passed (3)\n';
  assert.deepStrictEqual(vitestResults(out), { total: 3, failed: 1 });
});

test('vitest: a crash evaluated nothing', () => {
  const out = 'Test Files  2 failed (2)\n     Tests  no tests\n';
  assert.deepStrictEqual(vitestResults(out), { total: 0, failed: 0 });
});

test('vitest: no summary at all is null, not zero', () => {
  assert.strictEqual(vitestResults('Error: Cannot find module\n'), null);
});

test('vitest: colour codes do not hide the summary', () => {
  const out = '[2m     Tests  [22m[31m1 failed[39m | 2 passed (3)\n';
  assert.deepStrictEqual(vitestResults(out), { total: 3, failed: 1 });
});

test('pytest: a green run', () => {
  const out = '588 passed, 19 deselected, 3 warnings in 205.90s (0:03:25)\n';
  assert.deepStrictEqual(pytestResults(out), { total: 588, failed: 0 });
});

test('pytest: a real red is a red', () => {
  const out = '2 failed, 586 passed, 19 deselected in 204.11s\n';
  assert.deepStrictEqual(pytestResults(out), { total: 588, failed: 2 });
});

test('pytest: a collection error counts as failed', () => {
  const out = '3 errors in 1.20s\n';
  assert.deepStrictEqual(pytestResults(out), { total: 3, failed: 3 });
});

test('pytest: nothing ran', () => {
  assert.deepStrictEqual(pytestResults('no tests ran in 0.12s\n'), { total: 0, failed: 0 });
});

test('pytest: an internal error with no summary is null', () => {
  assert.strictEqual(pytestResults('INTERNALERROR> Traceback (most recent call last):\n'), null);
});

// ─── 3. The table's own invariants ───────────────────────────────────────────

test('every gate has a label, a match, a cmd, a hint and a measured cost', () => {
  for (const g of GATES) {
    for (const field of ['label', 'cmd', 'hint', 'cost']) {
      assert.ok(g[field], `gate ${g.label || '?'} is missing ${field}`);
    }
    assert.strictEqual(typeof g.match, 'function', `gate ${g.label} has no match()`);
  }
});

test('labels are unique', () => {
  const labels = GATES.map((g) => g.label);
  assert.strictEqual(new Set(labels).size, labels.length, `duplicate label in ${labels}`);
});

test('⛔ no gate ever runs the 312/312 guard', () => {
  for (const g of GATES) {
    assert.ok(
      !/tests[/\\]slow|-m\s+["']?slow|test_solver_312/.test(g.cmd),
      `gate ${g.label} would run the slow guard: ${g.cmd}\n` +
        '  That suite needs the 35 GB mirror and a GPU and must only ever be started by a person.',
    );
  }
});

// ─── ───────────────────────────────────────────────────────────────────────────

console.log(`${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
