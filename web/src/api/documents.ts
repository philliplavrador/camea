// DOCUMENTS — load / save / autosave. The project file is the app's ONLY memory between launches
// (BEHAVIOUR R2): the app carries no dataset knowledge, so save → quit → load is the one thing that
// makes a session resumable.
//
// These are the thin, typed request functions. The stateful part — holding the doc, tracking dirty,
// saving from anywhere (Ctrl+S), the debounced autosave crash-net, and PRESERVING UNKNOWN KEYS — lives
// in `store/documentStore.ts`, which orchestrates these calls.
//
// 🔴 UNKNOWN KEYS ROUND-TRIP VERBATIM. `Document` carries an index signature, and none of these
// functions reshapes the body — they pass the exact object through. The server owns normalisation
// (structural-validate → normalise → stamp → full-validate → write), which is also what strips a stale
// `EXCLUDED_TRIALS` block on re-save (BEHAVIOUR R2.4) — the front end never resurrects dataset knowledge.

import { api, unwrap } from './client';
import { pollJobUntilDone, type JobWatch } from './jobs';
import type {
  Document,
  DocumentResponse,
  JobRef,
  SaveDocumentRequest,
  SaveResult,
  LoadDocumentRequest,
  LoadDocumentResponse,
  ValidationReport,
} from './types';

/**
 * Read a stored analysis document (`GET /api/analyses/{id}/document`). `recovered: true` reads the
 * AUTOSAVE instead — only offer it when `Workspace.recovery()` says the autosave is NEWER than the
 * document; an older autosave is noise.
 */
export async function getDocument(analysisId: string, recovered = false): Promise<DocumentResponse> {
  return unwrap(
    await api.GET('/api/analyses/{analysis_id}/document', {
      params: {
        path: { analysis_id: analysisId },
        ...(recovered ? { query: { recovered: true } } : {}),
      },
    }),
  );
}

/**
 * Durable save into the workspace (`PUT /api/analyses/{id}/document`). This is a real save (it clears
 * dirty), distinct from the autosave crash-net. The server validates+normalises+stamps atomically.
 */
export async function putDocument(analysisId: string, doc: Document): Promise<SaveResult> {
  const body: SaveDocumentRequest = { doc };
  return unwrap(
    await api.PUT('/api/analyses/{analysis_id}/document', {
      params: { path: { analysis_id: analysisId } },
      body,
    }),
  );
}

/**
 * The autosave crash-net (`POST /api/analyses/{id}/autosave`). Debounced 2 s, plus unconditionally on
 * every `A`/`E` — the store owns that scheduling. 🔴 A FAILURE IS LOUD and must never be swallowed
 * (BEHAVIOUR R29/W4): the store surfaces it. A `409 range_mismatch` (the doc's id/range disagrees with
 * the slot) throws here — it is refused, not merged.
 *
 * ⚠️ This is a CRASH NET, not a save: a successful autosave does NOT clear the document's dirty flag.
 */
export async function autosaveDocument(analysisId: string, doc: Document): Promise<SaveResult> {
  return unwrap(
    await api.POST('/api/analyses/{analysis_id}/autosave', {
      params: { path: { analysis_id: analysisId } },
      body: { doc },
    }),
  );
}

/**
 * `Save…` — a file the user names (`POST /api/documents/save-as`). Reachable from EVERY screen (Ctrl+S),
 * because since R2 this file is the app's only memory. Refused inside `data/`, the repo, or the dataset.
 */
export async function saveDocumentAs(path: string, doc: Document): Promise<SaveResult> {
  const body: SaveDocumentRequest = { path, doc };
  return unwrap(await api.POST('/api/documents/save-as', { body }));
}

/**
 * Submit the load (`POST /api/documents/load` → **202 `JobRef`**, kind `document_load`). Use this
 * when the screen drives the bar itself with `useJob`; `loadDocument` below waits for you.
 *
 * ⏱️ **It became a job on 2026-08-16 (BEHAVIOUR R48).** It runs the *same* `FrameStore.load` the open
 * job does — ~5 s and 340 MiB — and it ran that on the request thread with no bar, no estimate and no
 * way to stop it. It now reports the same seven open phases, off the same counter.
 *
 * 🔴 **EVERY REFUSAL IS STILL SYNCHRONOUS** and still throws from THIS call: the missing file (404),
 * a document that names no dataset (400), a dataset not on this machine (404), and — the one that
 * matters — the **range guard** (`409 range_mismatch`), which needs the dataset's identity and not a
 * single pixel. A document for the wrong acquisition is refused by the request that asked for it.
 */
export async function startDocumentLoad(req: LoadDocumentRequest): Promise<JobRef> {
  return unwrap(await api.POST('/api/documents/load', { body: req }));
}

/**
 * `Load a project…` — submit the load and wait for the document. Works COLD — with no session open,
 * the server bootstraps one from the file's own `data_dir`, then re-reads the file against that
 * session's scope so the range guard runs against the session it belongs to.
 *
 * `onProgress` fires on every poll so the Load screen can paint the open phases with a `<Progress>`
 * (R48) instead of hanging on a request that does not come back.
 */
export async function loadDocument(
  req: LoadDocumentRequest,
  opts: JobWatch = {},
): Promise<LoadDocumentResponse> {
  const ref = await startDocumentLoad(req);
  const job = await pollJobUntilDone(ref.job_id, { onUpdate: opts.onProgress, signal: opts.signal });
  const result = job.result;
  if (!result || result.kind !== 'document_load') {
    throw new Error('loading the project finished without a document');
  }
  return result;
}

/** Structural validation without writing (`POST /api/documents/validate`). No trial number is special. */
export async function validateDocument(doc: Document): Promise<ValidationReport> {
  return unwrap(await api.POST('/api/documents/validate', { body: { doc } }));
}
