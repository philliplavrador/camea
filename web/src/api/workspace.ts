// PROJECTS — where the user's work is written. ⭐ **A PROJECT IS ONE FOLDER, AND CAMEA OWNS IT**
// (his ruling, 2026-08-10 — BEHAVIOUR R44): `%LOCALAPPDATA%/Camea/projects/<analysis_id>/`, created
// automatically, never named by the user. The one path he still names is where the DATA comes from.
//
// ⚠️ **This reverses R42/R43.** `checkProjectFolder` is gone with `GET /api/projects/folder`, and
// `CreateAnalysisRequest` no longer carries a `folder` — there is no save-folder question left to
// ask. Browsing a project's files is `./outputs.ts`; that is the only door, by his ruling.
//
// ⭐ THE SERVER AUTHORS THE DOCUMENT (`createAnalysis`), via the feature's hook — the front end never
// reimplements `new_doc`/`seed_from_build` (BEHAVIOUR: that was how v1 silently dropped divert counters
// and laundered seeded builds). The document's `id` IS the `analysis_id`; the server's slot guard uses
// that to make a pass-2 autosave overwriting pass-1 records impossible, not merely unlikely.

import { api, unwrap } from './client';
import type { AnalysisListResponse, AnalysisSummary, CreateAnalysisRequest } from './types';

/**
 * The home screen's list. `unreadable` names store folders whose manifest could not be read — shown,
 * never silently dropped. `migration` is set ONCE, on the first launch after R44, when projects were
 * brought in from the folders he used to name; it is null on every ordinary launch.
 */
export async function listAnalyses(): Promise<AnalysisListResponse> {
  return unwrap(await api.GET('/api/projects'));
}

/**
 * ONE project, by id (`GET /api/projects/{id}`) — what `/project/:id` opens with.
 *
 * ⭐ Ask for THIS project, never filter the listing. (Under R43 that mattered because a building
 * video mosaic was reachable-but-unlisted; R44 lists everything, but asking for what you want is
 * still cheaper and still gives an honest 404 for "no such project".)
 */
export async function getProject(analysisId: string): Promise<AnalysisSummary> {
  return unwrap(
    await api.GET('/api/projects/{analysis_id}', {
      params: { path: { analysis_id: analysisId } },
    }),
  );
}

/**
 * Create a project — THE SERVER CREATES THE DOCUMENT (`POST /api/projects` → 201). It goes into
 * Camea's store; the returned `analysis_id` is the document's `id`, the autosave slot key, and the
 * folder's name. `trials: null` ⇒ the session's whole list; the mosaic feature passes its selection.
 */
export async function createAnalysis(req: CreateAnalysisRequest): Promise<AnalysisSummary> {
  return unwrap(await api.POST('/api/projects', { body: req }));
}

/**
 * ⭐ **DELETE MEANS DELETE** (R44) — the project and everything in it, outputs included.
 *
 * ⚠️ R42.8's Remove-vs-Delete is retired. It existed because the folder was one the user had named
 * and might hold his own files; in an app-owned store there is no such folder, and a project the app
 * stops listing is one nobody could reach again. **The confirmation is the caller's job.**
 */
export async function deleteAnalysis(analysisId: string): Promise<void> {
  await unwrap(
    await api.DELETE('/api/projects/{analysis_id}', {
      params: { path: { analysis_id: analysisId } },
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
