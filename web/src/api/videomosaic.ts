// VIDEOMOSAIC — the typed request boundary for the video-mosaic feature. Same seam as mosaic.ts:
// features call THESE, never `api.POST('/api/videomosaic/...')` directly.
//
// ⛔ THE SERVER OWNS THE DOCUMENT. Nothing here authors or mutates one: create authors it server-side,
// the build job updates and SAVES it server-side (the polled result is already durable), save moves
// the folder server-side. The UI only POSTs and adopts/refetches.
//
// ⭐ There is no export call, on purpose (R43). Exporting used to mean "name a second folder and copy
// the four files the build already wrote"; now the one folder the user names IS the export.

import { api, API_BASE, unwrap } from './client';
import type {
  VideoSource,
  CreateVideoProjectRequest,
  AnalysisSummary,
  JobRef,
} from './types';

/**
 * The probe receipt (`POST /api/videomosaic/probe`): does this path decode as video, and what does it
 * claim to contain? A real frame is decoded — "probed OK" means "this will decode", not "a header
 * parsed". `fps`/`n_frames` are what the container CLAIMS (phone video is often VFR): a receipt, never
 * arithmetic. 400 (not decodable) throws with the backend's reason — show it inline, keep the text.
 */
export async function probeVideo(path: string): Promise<VideoSource> {
  return unwrap(await api.POST('/api/videomosaic/probe', { body: { path } }));
}

/**
 * Create a video project — THE SERVER CREATES THE DOCUMENT (`POST /api/videomosaic/projects` → 201).
 * No session: the video is re-probed server-side and its receipt becomes `doc.source`.
 *
 * ⭐ And no folder (R43): the project is born a DRAFT in Camea's own scratch area, is not listed on
 * the home screen, and gets its real home from `saveVideoProject` once the mosaic exists. A refusal
 * is a 400/409 with a message worth showing verbatim, inline, with the user's typed text kept.
 */
export async function createVideoProject(req: CreateVideoProjectRequest): Promise<AnalysisSummary> {
  return unwrap(await api.POST('/api/videomosaic/projects', { body: req }));
}

/**
 * Start the whole pipeline as ONE cancellable job (`POST /api/videomosaic/build` → 202 `JobRef`):
 * track → keyframes → register → solve → render → save. Poll with `useJob` for the ticking ETA (R8).
 * `config` is always null from the UI — a normal user never tunes computer-vision parameters to get a
 * mosaic. 409 = a build is already running for this project.
 */
export async function startVideoBuild(analysisId: string): Promise<JobRef> {
  return unwrap(
    await api.POST('/api/videomosaic/build', { body: { analysis_id: analysisId, config: null } }),
  );
}

// ⛔ **`saveVideoProject` / `POST /api/videomosaic/save` were DELETED on 2026-08-10 (R44).** They
// moved a finished draft into the folder the user named. There is no draft and no folder to name:
// the project has been in Camea's store since Create. Taking a copy of the mosaic somewhere is
// `copyOutputs` (./outputs.ts) — core's, shared, and available to every feature.

/**
 * One built artifact as an `<img src>`/download URL — `mosaic.png` | `preview.png` | `positions.csv` |
 * `build.json`. 404 until built. 🔴 `buster` must be the build's `built_at`: a rebuild overwrites the
 * SAME path with different bytes, so the URL must change when the pixels do (the R31/R32 lesson).
 */
export function videoOutputUrl(analysisId: string, name: string, buster?: string | null): string {
  const base = `${API_BASE}/api/videomosaic/${encodeURIComponent(analysisId)}/outputs/${encodeURIComponent(name)}`;
  return buster ? `${base}?v=${encodeURIComponent(buster)}` : base;
}
