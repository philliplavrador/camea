// ELECTRODES — the typed request boundary for the electrode-map stage of BOTH features. Same seam
// as mosaic.ts / videomosaic.ts: features call THESE, never `api.POST('/api/.../electrodes/...')`
// directly.
//
// The two features share one payload but split on document ownership, exactly like build vs export:
//   • mosaic (snapshots): the document is CLIENT-owned. `mapElectrodes` posts the working doc; the
//     job result carries `electrodes` for the CLIENT to merge into its document and save.
//   • videomosaic: the document is SERVER-owned. The job saves `electrodes` into it and the result
//     carries the already-durable doc — adopt or refetch, never author.
//
// `GET` answers 404 (`not_found`) until a map exists — a normal first-visit state, not a failure.
//
// ⭐ **`coverage` IS THE USER'S DECLARATION, AND IT IS NOT OPTIONAL HERE** (R45.8, 2026-08-11). Only
// he can say whether the mosaic shows the WHOLE chip or a piece of it, and the answer changes what
// the fit is allowed to do: "full" lets the server check the measured shape against the MaxWell
// array (220 × 120 = 26,400) and refuse a fit that disagrees; "partial" enforces nothing but the
// 17.5 µm pitch. Both call sites therefore pass it explicitly — the server's own default is the
// assumption-free one, but a UI that leaned on that default would be mapping without asking.

import { api, unwrap } from './client';
import type {
  ArrayCoverage,
  ElectrodeDevice,
  ElectrodeMapPayload,
  JobRef,
  MosaicDocument,
} from './types';

/**
 * ⭐ **THE DEVICE, READ RATHER THAN RETYPED** (`GET /api/electrodes/device`). R45.8 put every device
 * number in exactly one place — the backend's `DeviceSpec`/`MAXWELL` — and the coverage question the
 * UI asks *before* mapping promptly wrote them out a second time as button prose ("220 × 120",
 * "26,400", "17.5 µm"), in TypeScript, where nothing keeps them honest. Change the spec and the panel
 * goes on promising the old array while the fitter enforces the new one: the UI describing a rule it
 * is not the one enforcing. This is the fix — the UI asks.
 *
 * CORE, not a feature: the route is `/api/electrodes/device`, because BOTH features map the same chip
 * off the same core module. It touches no image, no session and no disk.
 */
export async function getElectrodeDevice(): Promise<ElectrodeDevice> {
  return unwrap(await api.GET('/api/electrodes/device'));
}

/**
 * Fit the electrode lattice of the built snapshot mosaic (`POST /api/mosaic/electrodes/map` → 202
 * `JobRef`, job kind `electrode_map`). Renders the placed tiles server-side (the export's own
 * compositor), so it holds the `gpu` lease. `includeUnverified` defaults true — the same tile set
 * the export defaults to.
 */
export async function mapElectrodes(
  sessionId: string,
  doc: MosaicDocument,
  coverage: ArrayCoverage,
  includeUnverified = true,
): Promise<JobRef> {
  return unwrap(
    await api.POST('/api/mosaic/electrodes/map', {
      body: {
        session_id: sessionId,
        doc,
        include_unverified: includeUnverified,
        array_coverage: coverage,
      },
    }),
  );
}

/**
 * The full electrode map of a snapshot project, plus `stale` (computed against the SAVED document's
 * tile positions). Cell x/y are DOCUMENT-WORLD px — the space the core viewer's tiles live in.
 */
export async function getElectrodeMap(analysisId: string): Promise<ElectrodeMapPayload> {
  return unwrap(
    await api.GET('/api/mosaic/electrodes/{analysis_id}', {
      params: { path: { analysis_id: analysisId } },
    }),
  );
}

/**
 * Fit the electrode lattice of the built video mosaic (`POST /api/videomosaic/electrodes/map` → 202
 * `JobRef`). The job SAVES `electrodes` into the server-owned document; the result's `doc` is
 * already durable.
 */
export async function videoMapElectrodes(
  analysisId: string,
  coverage: ArrayCoverage,
): Promise<JobRef> {
  return unwrap(
    await api.POST('/api/videomosaic/electrodes/map', {
      body: { analysis_id: analysisId, array_coverage: coverage },
    }),
  );
}

/**
 * The video project's electrode map + `stale` (the map's `source_stamp` vs the current build's
 * `built_at`). Cell x/y are `mosaic.png` canvas px, 1:1.
 */
export async function videoGetElectrodeMap(analysisId: string): Promise<ElectrodeMapPayload> {
  return unwrap(
    await api.GET('/api/videomosaic/{analysis_id}/electrodes', {
      params: { path: { analysis_id: analysisId } },
    }),
  );
}
