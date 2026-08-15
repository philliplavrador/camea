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
import type { components } from './schema';
import type { AnalysisSummary } from './types';

export type MeaShelfEntry = components['schemas']['MeaShelfEntry'];
export type MeaShelf = components['schemas']['MeaShelf'];
export type MeaRecordingCandidate = components['schemas']['MeaRecordingCandidate'];
export type MeaBrowseResult = components['schemas']['MeaBrowseResult'];
/** `referenced` · `copying` · `stored` · `failed` — where the app is reading this recording FROM. */
export type MeaCopyState = MeaShelfEntry['copy_state'];

export type MeaChipLayout = components['schemas']['MeaChipLayout'];
export type MeaChipPad = components['schemas']['MeaChipPad'];
export type MeaChipActivity = components['schemas']['MeaChipActivity'];
export type MeaPadActivity = components['schemas']['MeaPadActivity'];
export type MeaChannelTrace = components['schemas']['MeaChannelTrace'];
export type MeaEnvelopeStatus = components['schemas']['MeaEnvelopeStatus'];
export type MeaEnvelopeRow = components['schemas']['MeaEnvelopeRow'];

/**
 * Create an Analyze MEA project (`POST /api/mea/projects` → 201).
 *
 * ⭐ **ONE CALL, WITH THE RECORDINGS ALREADY ON IT** (his instruction, 2026-08-14). The wizard's
 * Files step hands its chosen paths straight to this, so there is never a moment where a project
 * exists with nothing on it because a second call failed. If one of the paths is not a MaxLab
 * recording the whole thing is refused, the message names the file, and **no project is created**.
 *
 * ⚠️ `paths` is optional and `[]` is the empty-shelf project — the one he is left with after
 * removing his last recording. A blank name is allowed and comes back as a placeholder.
 */
export async function createMeaProject(name: string, paths: string[] = [])
  : Promise<AnalysisSummary> {
  return unwrap(await api.POST('/api/mea/projects', { body: { name, paths } }));
}

/**
 * Every recording under a folder (`GET /api/mea/browse`).
 *
 * ⭐ **THE ONE CALL WITH NO PROJECT IN IT**, and that is what lets the import component be mounted
 * in the wizard at all — there is no project yet when he is looking at this list. ⛔ It reads and
 * writes nothing.
 */
export async function browseRecordings(path: string): Promise<MeaBrowseResult> {
  return unwrap(await api.GET('/api/mea/browse', { params: { query: { path } } }));
}

/** What this project holds, with live copy state (`GET /api/mea/{id}/recordings`). */
export async function listRecordings(analysisId: string): Promise<MeaShelf> {
  return unwrap(
    await api.GET('/api/mea/{analysis_id}/recordings', {
      params: { path: { analysis_id: analysisId } },
    }),
  );
}

/**
 * Put several recordings on an existing project's shelf (`POST /api/mea/{id}/recordings` → 201).
 *
 * ⚠️ All or nothing: one path that is not a MaxLab recording and none of them are added, with the
 * refusal naming it. Same rule as at creation, on purpose — one rule he can state to himself beats
 * two that differ by which door he came through.
 */
export async function addRecordings(analysisId: string, paths: string[]): Promise<MeaShelf> {
  return unwrap(
    await api.POST('/api/mea/{analysis_id}/recordings', {
      params: { path: { analysis_id: analysisId } },
      body: { paths },
    }),
  );
}

/**
 * Rename one recording (`PATCH /api/mea/{id}/recordings/{rid}`).
 *
 * ⭐ A rename is a fact about the ROW, never about the bytes — it changes what the shelf calls the
 * recording, and no file on any disk moves or changes. A blank name is refused by the backend.
 */
export async function renameRecording(
  analysisId: string,
  recordingId: string,
  label: string,
): Promise<MeaShelf> {
  return unwrap(
    await api.PATCH('/api/mea/{analysis_id}/recordings/{recording_id}', {
      params: { path: { analysis_id: analysisId, recording_id: recordingId } },
      body: { label },
    }),
  );
}

/**
 * Forget one recording (`DELETE /api/mea/{id}/recordings/{rid}`).
 *
 * ⛔ **Deletes CAMEA'S COPY ONLY.** The user's own file is never touched, whatever happens.
 */
export async function removeRecording(analysisId: string, recordingId: string): Promise<MeaShelf> {
  return unwrap(
    await api.DELETE('/api/mea/{analysis_id}/recordings/{recording_id}', {
      params: { path: { analysis_id: analysisId, recording_id: recordingId } },
    }),
  );
}

// ── opening one recording ────────────────────────────────────────────────────────────────────────
//
// ⛔ **NONE OF THESE CARRY A CHIP SEATING**, and none of them ever should. `mea.ts` (the video
// pipeline's half) resolves a `col-row` id through an orientation nobody has established, and
// reports every identity as provisional. Here the file states its own `electrode`, `x_um` and
// `y_um`, so a pad's identity is a fact — importing that doubt would make the screen lie.

/**
 * The chip this recording describes (`GET /api/mea/{id}/recordings/{rid}/layout`).
 *
 * ⭐ Every **routed** pad at the file's own µm position, plus the size of the whole chip so the map
 * can show *which part of it* was recorded. ⛔ Only routed pads: a pad that was never wired up is
 * the absence of a measurement, and drawing it would invent data.
 */
export async function meaChipLayout(analysisId: string, recordingId: string)
  : Promise<MeaChipLayout> {
  return unwrap(
    await api.GET('/api/mea/{analysis_id}/recordings/{recording_id}/layout', {
      params: { path: { analysis_id: analysisId, recording_id: recordingId } },
    }),
  );
}

/**
 * How much happened on each pad (`GET /api/mea/{id}/recordings/{rid}/activity`).
 *
 * One row per routed pad, **in the same order as `meaChipLayout`'s `pads`**, so the two zip
 * together without a join. ⭐ It comes from MaxWell's spike table, which needs no proprietary
 * decoder — so this is trustworthy even on a machine where the waveform reads as a flat line.
 */
export async function meaChipActivity(analysisId: string, recordingId: string)
  : Promise<MeaChipActivity> {
  return unwrap(
    await api.GET('/api/mea/{analysis_id}/recordings/{recording_id}/activity', {
      params: { path: { analysis_id: analysisId, recording_id: recordingId } },
    }),
  );
}

/**
 * One pad's waveform and spikes for a window (`GET /api/mea/{id}/recordings/{rid}/trace`).
 *
 * ⭐ **Asked for by `channel`**, because the chip map was drawn from the file's own coordinates so
 * the clicked dot already knows its channel. ⚠️ Read `health.flat` before believing `trace_uv` —
 * a railed window looks exactly like a genuinely silent electrode.
 *
 * ⭐ **`maxPoints` IS HOW YOU ASK FOR MORE THAN 30 SECONDS.** Leave it out and you get raw samples,
 * capped at `max_window_s`. Pass it — the number of columns you can actually draw — and the server
 * folds the window into that many min/max pairs (`min_uv`/`max_uv`, with `resolution: "envelope"`)
 * and the cap does not apply, so a whole recording costs the same as a second of one.
 *
 * ⚠️ **Label your axis from the RETURNED `t0_s`/`t1_s`, never from what you asked for.** Both paths
 * may hand back a different range: the raw path clamps silently to the cap, and the envelope path
 * snaps to the stored bucket edges.
 */
export async function meaChannelTrace(
  analysisId: string,
  recordingId: string,
  channel: number,
  window: { t0?: number; t1?: number; maxPoints?: number } = {},
): Promise<MeaChannelTrace> {
  return unwrap(
    await api.GET('/api/mea/{analysis_id}/recordings/{recording_id}/trace', {
      params: {
        path: { analysis_id: analysisId, recording_id: recordingId },
        query: {
          channel,
          t0: window.t0 ?? 0,
          t1: window.t1 ?? null,
          max_points: window.maxPoints ?? null,
        },
      },
    }),
  );
}

/**
 * Which recordings can be shown whole yet (`GET .../recordings/envelopes`), and the way to start
 * the one-off read for the ones that cannot (`POST`).
 *
 * ⭐ **THE BACKFILL.** New recordings get this at import; anything already in a project catches up
 * here. `ready: false` never means a recording is broken — only that the whole of it cannot be
 * drawn at once yet, while narrow windows still read live.
 */
export async function meaEnvelopes(analysisId: string): Promise<MeaEnvelopeStatus> {
  return unwrap(
    await api.GET('/api/mea/{analysis_id}/recordings/envelopes', {
      params: { path: { analysis_id: analysisId } },
    }),
  );
}

export async function startMeaEnvelopes(analysisId: string): Promise<MeaEnvelopeStatus> {
  return unwrap(
    await api.POST('/api/mea/{analysis_id}/recordings/envelopes', {
      params: { path: { analysis_id: analysisId }, query: { force: false } },
    }),
  );
}
