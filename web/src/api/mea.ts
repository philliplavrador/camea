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
import { type JobWatch, pollJobUntilDone } from './jobs';
import type { components } from './schema';
import type {
  ElectrodeTracePayload,
  JobRef,
  MeaAttachment,
  MeaOrientation,
} from './types';

// ── the trace-viewer port (2026-08-15): the whole recording, and the cache that affords it ──────
export type VideoMeaEnvelopeStatus = components['schemas']['VideoMeaEnvelopeStatus'];
export type VideoMeaEnvelopeRow = components['schemas']['VideoMeaEnvelopeRow'];

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
 *
 * ⏱️ **A JOB SINCE 2026-08-16 (R48).** The route answers **202 `JobRef`** now: it walks a directory
 * tree and then opens every `data.raw.h5` under it through HDF5 — an unbounded number of unbounded
 * reads that used to sit on the request thread with no bar, no time and no Stop, and that
 * *"Use this seating"* re-ran in full behind a frozen screen. This wrapper submits and waits, so the
 * caller still just gets its `MeaAttachment`; pass `watch.onProgress` to draw the bar (the
 * `job_id` for a Stop arrives on the first call — R48.7).
 *
 * ⚠️ The cheap refusals are still synchronous (a folder that does not exist is a 404 the POST
 * answers). What only the scan can discover — nothing found, nothing readable, two chips in one
 * folder — comes back as the job's failure, i.e. a rejected promise with the server's sentence.
 */
export async function attachMea(
  analysisId: string,
  opts: { meaDir?: string; confirm?: boolean; orientation?: MeaOrientation } = {},
  watch: JobWatch = {},
): Promise<MeaAttachment> {
  const ref: JobRef = unwrap(
    await api.POST('/api/videomosaic/mea/attach', {
      body: {
        analysis_id: analysisId,
        mea_dir: opts.meaDir ?? null,
        confirm: opts.confirm ?? false,
        orientation: opts.orientation ?? null,
      },
    }),
  );
  const job = await pollJobUntilDone(ref.job_id, {
    onUpdate: watch.onProgress,
    signal: watch.signal,
  });
  const result = job.result;
  if (!result || result.kind !== 'mea_attach') {
    throw new Error('the recording scan finished without saying what it found');
  }
  return result.attachment;
}

/**
 * One electrode's stored trace and its spikes, for a window.
 *
 * `electrode` is the Camea grid id the user clicked (`"col-row"`).
 *
 * ⭐ **`maxPoints` IS HOW YOU ASK FOR MORE THAN 30 SECONDS** (same contract as the Analyze MEA
 * route, ported 2026-08-15). Leave it out and you get raw samples, capped at `max_window_s`. Pass
 * it — the number of columns you can actually draw — and the server folds the window into that
 * many min/max pairs (`min_uv`/`max_uv`, `resolution: "envelope"`) and the cap does not apply. A
 * window too wide to read live needs the per-run cache; without one this is a **409** whose detail
 * names `needs: envelope` — offer `startMeaEnvelopeRead`, never an error screen.
 *
 * ⚠️ Label your axis from the RETURNED `t0_s`/`t1_s`, never from what you asked for — the raw path
 * clamps silently and the envelope path snaps to stored bucket edges.
 */
export async function getElectrodeTrace(
  analysisId: string,
  electrode: string,
  opts: { runId?: string; t0?: number; t1?: number; maxPoints?: number } = {},
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
          max_points: opts.maxPoints ?? null,
        },
      },
    }),
  );
}

/**
 * Which attached recordings can be shown whole yet (`GET .../mea/envelopes`), and the way to start
 * the one-off read for the ones that cannot (`POST`, below).
 *
 * ⚠️ `ready: false` never means a recording is broken — only that the whole of it cannot be drawn
 * at once yet, while narrow windows still read live.
 */
export async function getMeaEnvelopes(analysisId: string): Promise<VideoMeaEnvelopeStatus> {
  return unwrap(
    await api.GET('/api/videomosaic/{analysis_id}/mea/envelopes', {
      params: { path: { analysis_id: analysisId } },
    }),
  );
}

/**
 * ⭐ The backfill — read every attached recording end to end, once (~a minute each, as background
 * jobs). The voltage panel's "Read it now" button. Calling it twice costs nothing; recordings that
 * already have a cache are skipped. R44: the cache lives in the project store, never beside his
 * recording.
 */
export async function startMeaEnvelopeRead(analysisId: string): Promise<VideoMeaEnvelopeStatus> {
  return unwrap(
    await api.POST('/api/videomosaic/{analysis_id}/mea/envelopes', {
      params: { path: { analysis_id: analysisId }, query: { force: false } },
    }),
  );
}

/**
 * Score the four possible chip seatings against a located region (202 → `JobRef`, job kind
 * `mea_orientation`). Reads every frame of the region recording, so it is a job, not a call.
 *
 * ⭐ **IT PROPOSES; IT NEVER APPLIES.** The result carries `best` only when `decisive` is true, and
 * applying it is a separate `attachMea({orientation})` that a human triggers. 🔴 And the whole
 * result is unvalidated — render `caveat` verbatim beside it (issue 003).
 */
export async function testMeaOrientation(
  analysisId: string,
  opts: { regionId?: string; runId?: string } = {},
): Promise<JobRef> {
  return unwrap(
    await api.POST('/api/videomosaic/mea/orientation', {
      body: {
        analysis_id: analysisId,
        region_id: opts.regionId ?? null,
        run_id: opts.runId ?? null,
      },
    }),
  );
}
