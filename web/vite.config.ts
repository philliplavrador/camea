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
    exclude: ['e2e/**', 'node_modules/**', 'dist/**'],
    css: false,
  },
});
