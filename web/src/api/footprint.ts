// FOOTPRINT — the typed request boundary for `GET /api/videomosaic/mea/footprint`. Same seam as
// mea.ts / electrodes.ts: features call this, never `api.GET('/api/videomosaic/...')` directly.
//
// ⭐ **GEOMETRY ONLY, CHEAP ON PURPOSE.** The payload is the four candidate seatings' recorded-pad
// footprints — which Camea `col-row` grid ids the recording's routed electrodes land on under each
// of the four ways the chip could be sitting — read from the recording's mapping alone (no video,
// no spikes, no raw stream). It is what lets the Orientation step draw all four candidates as
// PICTURES the moment it opens.
//
// ⛔ It ranks nothing and proposes nothing — the evidence lives in the orientation job
// (`testMeaOrientation`), and the CHOICE is always a human click (`attachMea` with `confirmed`).
//
// Refusals mirror the orientation route's: no MEA attached and no electrode map are both 409s whose
// message is an instruction — show it verbatim (the R45.8 discipline), never trim it to a code.

import { api, unwrap } from './client';
import type { MeaFootprintPayload } from './types';

/** The four seatings' footprints for a project (optionally for one specific recording run). */
export async function getMeaFootprint(
  analysisId: string,
  opts: { runId?: string } = {},
): Promise<MeaFootprintPayload> {
  return unwrap(
    await api.GET('/api/videomosaic/mea/footprint', {
      params: { query: { analysis_id: analysisId, run_id: opts.runId ?? null } },
    }),
  );
}
