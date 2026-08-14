// ANALYZE MEA — the typed request boundary for the STANDALONE task. Same seam as
// videomosaic.ts: the feature calls these, never `api.POST('/api/mea/...')` directly.
//
// ⚠️ **Not `mea.ts`.** That file is the video pipeline's electrical half — attach a recording to an
// optical project, resolve a `col-row` grid id through a chip seating nobody has established yet.
// This one is the task that has no microscope in it: no mosaic, no calcium, no seating question.
// The two share a backend module (`core/mearecording.py`) and nothing else, deliberately.
//
// ⛔ THE SERVER OWNS THE DOCUMENT. Nothing here authors or mutates one.

import { api, unwrap } from './client';
import type { AnalysisSummary } from './types';

/**
 * Create an Analyze MEA project (`POST /api/mea/projects` → 201).
 *
 * ⭐ **A NAME, AND NOTHING ELSE.** No session, no probe, no folder — this is the only create in
 * Camea that asks the user for no path at all. The project is a shelf; recordings go on it from
 * inside, afterwards. A blank name is allowed and comes back as a placeholder.
 */
export async function createMeaProject(name: string): Promise<AnalysisSummary> {
  return unwrap(await api.POST('/api/mea/projects', { body: { name } }));
}
