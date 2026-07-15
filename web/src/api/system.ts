// SYSTEM — the app-wide odds and ends every screen may touch: health, the GPU probe, remembered
// settings, and the SERVED folder picker (`GET /api/fs/list`).
//
// ⭐ `listDir` is what keeps the app usable headless and drivable by Playwright: the native dialogs
// need a pywebview window; this needs nothing. It is directories-only and has no write path.
//
// ⛔ NO DATASET KNOWLEDGE in settings — a remembered PATH is not knowledge about the data at that path.

import { api, unwrap } from './client';
import type { HealthResponse, GpuInfo, Settings, SettingsUpdate, FsListResponse } from './types';

/** Cheap liveness probe — touches no engine, no GPU, no disk. What a launcher polls while painting. */
export async function getHealth(): Promise<HealthResponse> {
  return unwrap(await api.GET('/api/health'));
}

/**
 * The GPU probe (`GET /api/gpu`). `reason` is a STRING FOR THE HUMAN, never a verdict: "no GPU" because
 * a CUDA DLL is off the path is FIXABLE and is not the same as "no card". The first call costs ~200 ms
 * and is memoised for the process (BEHAVIOUR: Place screen states the real cost either way).
 */
export async function getGpu(): Promise<GpuInfo> {
  return unwrap(await api.GET('/api/gpu'));
}

export async function getSettings(): Promise<Settings> {
  return unwrap(await api.GET('/api/settings'));
}

export async function updateSettings(update: SettingsUpdate): Promise<Settings> {
  return unwrap(await api.PUT('/api/settings', { body: update }));
}

/**
 * List a directory's sub-directories for the served folder picker (`GET /api/fs/list`). Omit `path` to
 * get the filesystem roots (so the picker can start from nothing). A folder is flagged `is_dataset`
 * when it has a `log.txt` and at least one `NNN.xml` — recognised by SHAPE, never by name.
 */
export async function listDir(path?: string | null): Promise<FsListResponse> {
  return unwrap(
    await api.GET('/api/fs/list', { params: { query: path != null ? { path } : {} } }),
  );
}
