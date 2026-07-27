// PROJECTS — where the user's work is written. ⭐ **A PROJECT IS ONE FOLDER, AND HE NAMES IT**
// (his ruling, 2026-07-25). It holds the document, the autosave and `outputs/`, and it is never
// inside the dataset and never inside the repo — the backend refuses both at create time, at the one
// moment he names the place, with a message worth showing him verbatim.
//
// There is no app-managed store to choose any more, so `getWorkspace`/`setWorkspace`/`useWorkspace`
// are gone with it. `listAnalyses` reads the folders Camea remembers he saved into.
//
// ⭐ THE SERVER AUTHORS THE DOCUMENT (`createAnalysis`), via the feature's hook — the front end never
// reimplements `new_doc`/`seed_from_build` (BEHAVIOUR: that was how v1 silently dropped divert counters
// and laundered seeded builds). The document's `id` IS the `analysis_id`; the server's slot guard uses
// that to make a pass-2 autosave overwriting pass-1 records impossible, not merely unlikely.

import { api, unwrap } from './client';
import type {
  ProjectFolderInfo,
  AnalysisListResponse,
  AnalysisSummary,
  CreateAnalysisRequest,
} from './types';

// ── The save folder ───────────────────────────────────────────────────────────────

/**
 * *"Can I save here?"* — asked as he types, BEFORE anything is written. `writable` is PROVED (the
 * server writes and deletes a probe file), so a folder on an unplugged drive says so up front
 * instead of failing an hour into a sweep. A refused place (inside a dataset, inside the repo)
 * throws with the backend's own reason.
 */
export async function checkProjectFolder(path: string): Promise<ProjectFolderInfo> {
  return unwrap(await api.GET('/api/projects/folder', { params: { query: { path } } }));
}

// ── Projects ──────────────────────────────────────────────────────────────────────

export async function listAnalyses(): Promise<AnalysisListResponse> {
  return unwrap(await api.GET('/api/projects'));
}

/**
 * Create a project — THE SERVER CREATES THE DOCUMENT (`POST /api/projects` → 201). `req.folder` is
 * where it goes; the returned `analysis_id` is the document's `id` and the autosave slot key.
 * `trials: null` ⇒ the session's whole list; the mosaic feature passes its own selection.
 */
export async function createAnalysis(req: CreateAnalysisRequest): Promise<AnalysisSummary> {
  return unwrap(await api.POST('/api/projects', { body: req }));
}

/**
 * ⭐ FORGET, OR DELETE — and the app does not guess which. `deleteFiles: false` (the default) takes
 * the project off the home screen and leaves every byte on disk; `true` removes Camea's own files
 * from the folder and leaves anything else he put there alone.
 */
export async function deleteAnalysis(analysisId: string, deleteFiles = false): Promise<void> {
  await unwrap(
    await api.DELETE('/api/projects/{analysis_id}', {
      params: { path: { analysis_id: analysisId }, query: { delete_files: deleteFiles } },
    }),
  );
}

/** Rename a project (`PATCH`). Rewrites the manifest only — the folder never moves, the id is
 *  forever. This is the project manager's rename. */
export async function renameAnalysis(analysisId: string, name: string): Promise<AnalysisSummary> {
  return unwrap(
    await api.PATCH('/api/projects/{analysis_id}', {
      params: { path: { analysis_id: analysisId } },
      body: { name },
    }),
  );
}
