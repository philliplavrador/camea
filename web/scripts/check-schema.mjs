// Fail if the committed TypeScript contract (src/api/schema.d.ts) has drifted from the backend.
//
// HARD RULE 2: the contract is GENERATED, never hand-written. This is the CI guard that enforces it.
// It does NOT trust the committed docs/openapi.json — it dumps a FRESH schema straight from the
// backend (`create_app().openapi()`), regenerates the types from that, and diffs against what is
// committed. So it catches drift in BOTH directions:
//   * someone edited schema.d.ts by hand            -> mismatch
//   * the backend changed and docs/openapi.json + schema.d.ts were not regenerated -> mismatch
//
// On mismatch: refresh docs/openapi.json from the backend, then `npm run gen:api`, then commit.
//
// Usage:  node scripts/check-schema.mjs        (npm run check:api)

import { execSync } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const webDir = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const repoRoot = resolve(webDir, '..');
const committed = join(webDir, 'src', 'api', 'schema.d.ts');

const work = mkdtempSync(join(tmpdir(), 'camea-schema-'));
const freshJson = join(work, 'openapi.fresh.json');
const freshTs = join(work, 'schema.fresh.d.ts');
const dumpPy = join(work, 'dump_openapi.py');

// The backend dumps the live schema. We write it to a FILE from Python (utf-8) rather than piping
// stdout — the schema descriptions contain non-ASCII (⭐, →) and a Windows console is cp1252.
writeFileSync(
  dumpPy,
  [
    'import json',
    'from pathlib import Path',
    'from camea.api.app import create_app',
    `Path(r"${freshJson}").write_text(json.dumps(create_app().openapi()), encoding="utf-8")`,
    'print("dumped", ' + `r"${freshJson}"` + ')',
  ].join('\n'),
  'utf-8',
);

function run(cmd, cwd) {
  return execSync(cmd, { cwd, stdio: ['ignore', 'pipe', 'pipe'], encoding: 'utf-8' });
}

try {
  console.log('[check:api] dumping live schema from the backend (uv run python) ...');
  run(`uv run python "${dumpPy}"`, repoRoot);
} catch (e) {
  console.error('[check:api] COULD NOT DUMP the live schema from the backend.');
  console.error(
    '[check:api] The check needs the camea Python env (uv). ' + (e.stderr || e.message),
  );
  process.exit(2);
}

try {
  console.log('[check:api] regenerating types from the live schema (openapi-typescript) ...');
  run(`npx --no-install openapi-typescript "${freshJson}" -o "${freshTs}"`, webDir);
} catch (e) {
  console.error('[check:api] openapi-typescript failed: ' + (e.stderr || e.message));
  process.exit(2);
}

const norm = (s) => s.replace(/\r\n/g, '\n').trimEnd();
const fresh = norm(readFileSync(freshTs, 'utf-8'));
const have = norm(readFileSync(committed, 'utf-8'));

if (fresh === have) {
  console.log('[check:api] OK — src/api/schema.d.ts is in sync with the backend.');
  process.exit(0);
}

console.error('\n[check:api] STALE — src/api/schema.d.ts does NOT match the live backend schema.');
console.error('[check:api] The generated API contract has drifted. To fix:');
console.error('[check:api]   1. refresh docs/openapi.json from the backend:');
console.error(
  '[check:api]      uv run python -c "import json;from camea.api.app import create_app;' +
    "open('docs/openapi.json','w',encoding='utf-8').write(json.dumps(create_app().openapi(),indent=2))\"",
);
console.error('[check:api]   2. npm run gen:api');
console.error('[check:api]   3. commit the updated docs/openapi.json + src/api/schema.d.ts');
process.exit(1);
