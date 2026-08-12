import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

/**
 * DEV PROXY. In development the Vite server (5173) proxies the two things the app talks to on the
 * backend (the FastAPI process, `uv run camea --headless --port 8000`):
 *   /api/*          the whole route surface
 *   /openapi.json   the live schema (handy in the browser; also what the staleness check dumps)
 *
 * The backend binds 127.0.0.1 and refuses to become a network server, so the target is always
 * loopback. Override the port with VITE_BACKEND if you started the backend elsewhere.
 *
 * The two-terminal dev loop is documented in docs/FRONTEND.md.
 */
const BACKEND = process.env.VITE_BACKEND ?? 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    // Bind IPv4 loopback explicitly. Vite's default `localhost` resolves to IPv6 [::1] on Windows,
    // which does not answer a 127.0.0.1 request — and the backend, Playwright's baseURL and the
    // health checks are all 127.0.0.1. One address family, end to end.
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: BACKEND, changeOrigin: true },
      '/openapi.json': { target: BACKEND, changeOrigin: true },
    },
  },
  build: {
    // Content-hashed filenames satisfy BEHAVIOUR.md R32 (a new index.html must never load an old
    // asset). Vite hashes by default; sourcemaps make the instrument debuggable in WebView2.
    sourcemap: true,
    outDir: 'dist',
  },
  test: {
    // Vitest — UNIT only. Playwright owns e2e (web/e2e); keep the two runners from fighting over
    // *.spec.ts files.
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    // ⭐ `src/legacy/**` is the RETIRED snapshot mosaic builder (moved out of `src/features/mosaic`
    // on 2026-08-11 — see `src/legacy/mosaic/MosaicFeature.tsx` and `src/camea/legacy/__init__.py`).
    // Its 11 unit suites are EXCLUDED, not deleted: the feature still ships and still opens every
    // project already built with it, but nobody is changing it, so it stops costing the default run.
    // `CAMEA_LEGACY` is the opt-in — the frontend's answer to `uv run pytest -m legacy`:
    //     npm test                                   -> skips them
    //     $env:CAMEA_LEGACY=1; npx vitest run        -> runs EVERYTHING, legacy included (PowerShell)
    //     CAMEA_LEGACY=1 npx vitest run              -> the same, from bash
    // ⚠️ A bare `vitest run src/legacy` is NOT enough: a CLI path does not override a config
    // `exclude`, so the env var is the only switch that works.
    // ⛔ Do not delete the files. If the snapshot task ever comes back, drop this one entry.
    exclude: [
      'e2e/**',
      'node_modules/**',
      'dist/**',
      ...(process.env.CAMEA_LEGACY ? [] : ['src/legacy/**']),
    ],
    css: false,
  },
});
