import { defineConfig, devices } from '@playwright/test';
import { dirname, resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const webDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(webDir, '..');

/**
 * The committed synthetic dataset lives at tests/fixtures/synthetic. We point the backend at its
 * PARENT (tests/fixtures) as a dataset ROOT — that is how the app discovers datasets. The backend
 * has NO --data-dir flag; `--open <root>` remembers a root and GET /api/datasets lists what is under
 * it. State goes to an isolated dir so a test run never touches the developer's real settings/recents.
 */
const FIXTURES_ROOT = join(repoRoot, 'tests', 'fixtures');
const STATE_DIR = join(webDir, '.playwright-state');
const BACKEND_PORT = 8000;

/**
 * `@slow` marks every spec that drives a REAL solver build. A build monopolises the single backend
 * process (the solve holds the interpreter, so while one runs even a session-open stalls), so two builds
 * must never be in flight at once. Two projects split the suite so each gets the right treatment:
 *
 *   • `fast` — everything that is NOT `@slow`. No build; runs across the (capped, see `workers` below)
 *     pool and stays quick.
 *   • `slow` — only `@slow`. Pinned to ONE worker (`workers: 1`) so exactly one build is ever in flight
 *     — the textbook "tests share a single resource, cannot run in parallel" case per-project `workers`
 *     exists for. Its per-test `timeout` is raised well above the build/export internal assertion
 *     ceilings (`runBuild` and the export file-count each allow up to 180 s) so a genuinely cold build
 *     is never killed by the 30 s default.
 *
 * Kept as plain `grep`/`grepInvert` projects with NO cross-project dependency, so `--grep @slow` still
 * selects exactly the 11 build specs (a dependency would drag the whole fast lane in unfiltered).
 */
const SLOW = /@slow/;

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  // The whole suite drives ONE shared backend process (behind ONE Vite dev server). That backend
  // serves requests essentially one-at-a-time, so heavy parallelism starves the short-timeout
  // assertions: at ≥3 concurrent clients the request queue tail routinely blows a 4 s expect, and the
  // failures wander (a load flake, not a bug). Two workers is the stable ceiling — at most one request
  // is ever queued behind another, which fits inside the assertion windows. The `slow` project pins
  // itself to a single worker on top of this so a solver build never runs beside anything else.
  workers: 2,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : [['list']],
  use: {
    baseURL: 'http://127.0.0.1:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'fast',
      use: { ...devices['Desktop Chrome'] },
      grepInvert: SLOW,
    },
    {
      name: 'slow',
      use: { ...devices['Desktop Chrome'] },
      grep: SLOW,
      workers: 1, // one build at a time — the backend serialises them anyway; this makes it explicit
      timeout: 300_000, // a cold build (+ export) can legitimately outlast the 30 s default
    },
  ],

  // Two servers: the FastAPI backend (headless, pointed at the fixture) and the Vite dev server
  // (which proxies /api and /openapi.json to the backend). Playwright waits for both to be live.
  webServer: [
    {
      command:
        `uv --directory "${repoRoot}" run camea --headless --port ${BACKEND_PORT} ` +
        `--open "${FIXTURES_ROOT}"`,
      url: `http://127.0.0.1:${BACKEND_PORT}/api/health`,
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
      env: { CAMEA_STATE_DIR: STATE_DIR, PYTHONUTF8: '1' },
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      command: 'npm run dev',
      url: 'http://127.0.0.1:5173',
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
      env: { VITE_BACKEND: `http://127.0.0.1:${BACKEND_PORT}` },
    },
  ],
});
