// WORKSPACE & ANALYSES — where the user's work is written. An ANALYSIS is a document + its outputs,
// bound to one dataset, living in a WORKSPACE folder the user chose — never inside the dataset, never
// inside the repo (the backend refuses both at `setWorkspace`).
//
// ⭐ THE SERVER AUTHORS THE DOCUMENT (`createAnalysis`), via the feature's hook — the front end never
// reimplements `new_doc`/`seed_from_build` (BEHAVIOUR: that was how v1 silently dropped divert counters
// and laundered seeded builds). The document's `id` IS the `analysis_id`; the server's slot guard uses
// that to make a pass-2 autosave overwriting pass-1 records impossible, not merely unlikely.

import { useEffect, useState } from 'react';
import { api, unwrap } from './client';
import type {
  WorkspaceInfo,
  WorkspaceSetRequest,
  AnalysisListResponse,
  AnalysisSummary,
  CreateAnalysisRequest,
} from './types';

// ── Workspace ────────────────────────────────────────────────────────────────────

/**
 * The current workspace. `writable` is PROVED (the server writes and deletes a probe file), so a
 * workspace on an unplugged drive shows up as `writable: false` on the Load screen — not as a 500 an
 * hour into a sweep.
 */
export async function getWorkspace(): Promise<WorkspaceInfo> {
  return unwrap(await api.GET('/api/workspace'));
}

/** Choose the workspace folder. Refused inside a dataset or the repo (the server enforces it). */
export async function setWorkspace(req: WorkspaceSetRequest): Promise<WorkspaceInfo> {
  return unwrap(await api.PUT('/api/workspace', { body: req }));
}

// ── Analyses ──────────────────────────────────────────────────────────────────────

export async function listAnalyses(): Promise<AnalysisListResponse> {
  return unwrap(await api.GET('/api/workspace/analyses'));
}

/**
 * Create an analysis — THE SERVER CREATES THE DOCUMENT (`POST /api/workspace/analyses` → 201). The
 * returned `analysis_id` is the document's `id` and the autosave slot key. `trials: null` ⇒ the
 * session's whole list; the mosaic feature passes its own selection.
 */
export async function createAnalysis(req: CreateAnalysisRequest): Promise<AnalysisSummary> {
  return unwrap(await api.POST('/api/workspace/analyses', { body: req }));
}

export async function deleteAnalysis(analysisId: string): Promise<void> {
  await unwrap(
    await api.DELETE('/api/workspace/analyses/{analysis_id}', {
      params: { path: { analysis_id: analysisId } },
    }),
  );
}

// ── A read hook for the browser card / Load screen ──────────────────────────────────

export type WorkspaceState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; info: WorkspaceInfo };

export function useWorkspace(reloadKey?: unknown): WorkspaceState {
  const [state, setState] = useState<WorkspaceState>({ status: 'loading' });

  useEffect(() => {
    let cancelled = false;
    setState({ status: 'loading' });
    getWorkspace()
      .then((info) => {
        if (!cancelled) setState({ status: 'ready', info });
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setState({ status: 'error', message: e instanceof Error ? e.message : String(e) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  return state;
}
