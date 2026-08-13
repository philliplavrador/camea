// MEA — the typed request boundary for the ELECTRICAL half of the pairing. Same seam as
// electrodes.ts / videomosaic.ts: features call these, never `api.GET('/api/videomosaic/...')`.
//
// The mosaic names electrodes; a MaxWell recording says what they recorded. These three calls are
// how the UI joins them, and each one carries a caveat the screen is obliged to keep visible:
//
//   • `attachMea` PROPOSES before it saves. Called without `confirm` it only reports what it found,
//     so the user reads the actual paths first. Attaching the wrong plate would pair one culture's
//     voltages with another culture's neurons — silently, in a dataset meant to be ground truth.
//   • `getElectrodeTrace` answers `recorded: false` for most pads and that is CORRECT: roughly a
//     thousand of the chip's 26,400 electrodes are routed at acquisition. Render it as a fact.
//   • Its `health` says whether the waveform actually decoded. ⚠️ Never draw `trace_uv` without
//     consulting it — see the note on `ElectrodeTracePayload` in types.ts.

import { api, unwrap } from './client';
import type { ElectrodeTracePayload, MeaAttachment, MeaOrientation } from './types';

/** What electrical data a project has. `attached: false` is a normal first-visit state, not a 404. */
export async function getMea(analysisId: string): Promise<MeaAttachment> {
  return unwrap(
    await api.GET('/api/videomosaic/{analysis_id}/mea', {
      params: { path: { analysis_id: analysisId } },
    }),
  );
}

/**
 * Find the recordings that belong to a project.
 *
 * ⭐ **TWO-STEP ON PURPOSE.** `confirm: false` (the default) discovers and reports only — nothing is
 * written, and the caller shows the user the paths it found. `confirm: true` saves the attachment.
 * Pass `meaDir` to override the search with a folder the user picked.
 */
export async function attachMea(
  analysisId: string,
  opts: { meaDir?: string; confirm?: boolean; orientation?: MeaOrientation } = {},
): Promise<MeaAttachment> {
  return unwrap(
    await api.POST('/api/videomosaic/mea/attach', {
      body: {
        analysis_id: analysisId,
        mea_dir: opts.meaDir ?? null,
        confirm: opts.confirm ?? false,
        orientation: opts.orientation ?? null,
      },
    }),
  );
}

/**
 * One electrode's stored trace and its spikes, for a window.
 *
 * `electrode` is the Camea grid id the user clicked (`"col-row"`). The window is capped server-side
 * — ask for what the chart is showing, not the whole recording.
 */
export async function getElectrodeTrace(
  analysisId: string,
  electrode: string,
  opts: { runId?: string; t0?: number; t1?: number } = {},
): Promise<ElectrodeTracePayload> {
  return unwrap(
    await api.GET('/api/videomosaic/{analysis_id}/mea/trace', {
      params: {
        path: { analysis_id: analysisId },
        query: {
          electrode,
          run_id: opts.runId ?? null,
          t0: opts.t0 ?? 0,
          t1: opts.t1 ?? null,
        },
      },
    }),
  );
}
