// DATASETS — looking at ONE folder the user named, and OPEN (which starts a session job).
//
// ⛔ NO DATASET KNOWLEDGE (HARD RULE 3 / BEHAVIOUR I1). This module never names a trial, a count, a
// range or an exclusion. A dataset opens as "N of whatever is on disk"; which frames are good is the
// human's decision, and it lives in the document, never here.
//
// ⭐ **THERE IS NO ROOT REGISTRY** (his ruling, 2026-07-25). `listDatasets`/`scanDatasets` are gone
// with it: the app does not keep folders to walk on launch and does not go looking for his data. He
// names a folder; `datasetsAt` says what is in THAT folder and remembers nothing.

import { api, unwrap } from './client';
import { pollJobUntilDone, type JobWatch } from './jobs';
import type {
  DatasetListResponse,
  DatasetDetail,
  JobRef,
  OpenSessionRequest,
  SessionResponse,
} from './types';

// ── Request functions ───────────────────────────────────────────────────────────

/**
 * Submit the folder scan (`POST /api/datasets/at` → **202 `JobRef`**, kind `dataset_scan`). Use this
 * when the screen wants to drive the bar itself with `useJob`; `datasetsAt` below is the
 * submit-then-wait convenience that most callers want.
 *
 * ⏱️ **It became a job on 2026-08-16 (BEHAVIOUR R48)** — it is two waits, a tree walk of unbounded
 * breadth and then ~0.2 s of `log.txt` + XML per acquisition, and behind a synchronous request that
 * was one static word on screen for as long as it took.
 *
 * ⚠️ *"No such directory"* is still refused **here**, synchronously, as a `400` — a mistyped path is
 * an `ApiError` the caller can show beside the box he typed it in, never a job that fails a moment
 * later with nobody waiting on it.
 */
export async function startDatasetScan(path: string, depth = 2): Promise<JobRef> {
  // `depth: 2` is the backend's own default, spelled out because openapi-typescript types a field
  // WITH a default as required. 2 = this folder, or the acquisitions directly inside it. Never deeper.
  return unwrap(await api.POST('/api/datasets/at', { body: { path, depth } }));
}

/**
 * *"Look at THIS folder."* — submit the scan and wait for what it found. A POST, not a GET, because
 * a Windows path in a query string is an encoding trap.
 *
 * Either the folder IS an acquisition (`is_dataset`, one entry) or it directly contains some and he
 * picks which — a disambiguation of his own typing, never a suggestion. It looks no deeper, and it
 * writes nothing down.
 *
 * `onProgress` fires on every poll, so a caller that wants a `<Progress>` can draw one (R48) — the
 * walk counts up (*"14 dataset(s) so far"*, no denominator) and the opens that follow carry a real
 * estimate. A caller that passes nothing still just gets the answer.
 */
export async function datasetsAt(path: string, opts: JobWatch = {}): Promise<DatasetListResponse> {
  const ref = await startDatasetScan(path);
  const job = await pollJobUntilDone(ref.job_id, { onUpdate: opts.onProgress, signal: opts.signal });
  const result = job.result;
  if (!result || result.kind !== 'dataset_scan') {
    throw new Error('the folder scan finished without saying what is in it');
  }
  return result;
}

/** Everything sayable about one dataset without loading a pixel (`GET /api/datasets/{key}`). */
export async function getDataset(key: string): Promise<DatasetDetail> {
  return unwrap(await api.GET('/api/datasets/{key}', { params: { path: { key } } }));
}

/**
 * Open a dataset → a session (`POST /api/sessions` → 202 `JobRef`). Poll the job; its result is an
 * `OpenJobResult`.
 *
 * ⚠️ A `409 mixed_shape` surfaces here as an `ApiError` (`err.code === 'mixed_shape'`) BEFORE any job
 * is submitted — the shape check is synchronous, so the caller can act on it rather than wait 5 s for a
 * job to fail. `trials: null` ⇒ every snapshot trial; the mosaic feature passes its 512×512 selection.
 */
export async function openSession(req: OpenSessionRequest): Promise<JobRef> {
  return unwrap(await api.POST('/api/sessions', { body: req }));
}

/**
 * Open a dataset and wait for the session (convenience over `openSession` + `pollJobUntilDone`).
 * `onProgress` fires on every poll so the Load screen can paint the open phases
 * (`scan_dir → parse_log → load_frames → flat_field → tone → texture → done`).
 */
export async function openSessionAndWait(
  req: OpenSessionRequest,
  opts: JobWatch = {},
): Promise<SessionResponse> {
  const ref = await openSession(req);
  const job = await pollJobUntilDone(ref.job_id, { onUpdate: opts.onProgress, signal: opts.signal });
  const result = job.result;
  if (!result || result.kind !== 'open') {
    throw new Error('open-session job finished without a session result');
  }
  return result.session;
}

