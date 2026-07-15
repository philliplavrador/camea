/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL prepended to API paths. Empty in dev (the Vite proxy handles /api). */
  readonly VITE_API_BASE?: string;
  /** Backend origin the dev proxy targets (see vite.config.ts). */
  readonly VITE_BACKEND?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
