// OUTPUTS — ⭐ **THE ONLY DOOR TO A PROJECT'S FILES** (his ruling, 2026-08-10 — BEHAVIOUR R44).
//
//   *"if users want to browse their project data they have to do it through the app itself"*, and
//   *"click into a project and browse your outputs, select the one(s) you want and save it into
//   somewhere."*
//
// Three calls, and between them they are that sentence: **list** what a project built, **read** one
// of those files (preview / download), and **copy** the chosen ones to a folder he names at that
// moment. ⛔ There is no `revealPath` any more — showing a project in Explorer was the last door out
// of the app, and R44 closed it.

import { api, API_BASE, unwrap } from './client';
import type { CopyOutputsResponse, OutputListResponse } from './types';

/**
 * Everything this project has built, newest first. Read off the DIRECTORY, not the document — so a
 * file written by an older Camea, or deleted underneath us, shows up as it actually is.
 *
 * An empty list is a normal answer ("nothing built yet"), never an error.
 */
export async function listOutputs(analysisId: string): Promise<OutputListResponse> {
  return unwrap(
    await api.GET('/api/projects/{analysis_id}/outputs', {
      params: { path: { analysis_id: analysisId } },
    }),
  );
}

/**
 * The URL of one output's bytes — for an `<img src>` or an `<a href>`.
 *
 * `v` is a cache-buster the caller passes (the build's `built_at`); the response itself says
 * `no-store`, because a rebuild overwrites in place. `download` asks for a `Content-Disposition`
 * attachment, which is how the **web** build lets him take a copy with no native dialog at all.
 */
export function outputUrl(
  analysisId: string,
  name: string,
  opts: { download?: boolean; v?: string } = {},
): string {
  const q = new URLSearchParams();
  if (opts.download) q.set('download', 'true');
  if (opts.v) q.set('v', opts.v);
  const query = q.toString();
  return (
    `${API_BASE}/api/projects/${encodeURIComponent(analysisId)}` +
    `/outputs/${encodeURIComponent(name)}${query ? `?${query}` : ''}`
  );
}

/**
 * ⭐ **THE ONE WAY WORK LEAVES CAMEA** — copy the chosen outputs into a folder he names.
 *
 * It is a COPY: the project keeps its outputs, so the store stays the home and what leaves is what
 * he asked for. Throws with the backend's own reason, which is worth showing verbatim:
 *   * 409 `refused` — the destination is inside a dataset (⛔ never onto the evidence), or already
 *     holds a file of that name. **A clash refuses the whole request**, naming the files; nothing is
 *     half-copied and nothing of his is overwritten.
 *   * 404 — a name that is not this project's output.
 */
export async function copyOutputs(
  analysisId: string,
  names: string[],
  dest: string,
): Promise<CopyOutputsResponse> {
  return unwrap(
    await api.POST('/api/projects/{analysis_id}/outputs/copy', {
      params: { path: { analysis_id: analysisId } },
      body: { names, dest },
    }),
  );
}
