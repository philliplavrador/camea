// DATASETS — the home screen's data (list / scan / detail) and OPEN (which starts a session job).
//
// ⛔ NO DATASET KNOWLEDGE (HARD RULE 3 / BEHAVIOUR I1). This module never names a trial, a count, a
// range or an exclusion. A dataset opens as "N of whatever is on disk"; which frames are good is the
// human's decision, and it lives in the document, never here.

import { useEffect, useState } from 'react';
import { api, unwrap } from './client';
import { pollJobUntilDone } from './jobs';
import type {
  DatasetListResponse,
  DatasetDetail,
  DatasetScanRequest,
  JobRef,
  Job,
  OpenSessionRequest,
  SessionResponse,
} from './types';

// ── Request functions ───────────────────────────────────────────────────────────

/** Every dataset under every remembered root (`GET /api/datasets`). No pixels loaded. */
export async function listDatasets(): Promise<DatasetListResponse> {
  return unwrap(await api.GET('/api/datasets'));
}

/**
 * Point Camea at a folder (`POST /api/datasets/scan`). A POST, not a GET, because a Windows path in a
 * query string is an encoding trap — and scanning also remembers the root in settings.
 */
export async function scanDatasets(req: DatasetScanRequest): Promise<DatasetListResponse> {
  return unwrap(await api.POST('/api/datasets/scan', { body: req }));
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
  opts: { onProgress?: (job: Job) => void; signal?: AbortSignal } = {},
): Promise<SessionResponse> {
  const ref = await openSession(req);
  const job = await pollJobUntilDone(ref.job_id, { onUpdate: opts.onProgress, signal: opts.signal });
  const result = job.result;
  if (!result || result.kind !== 'open') {
    throw new Error('open-session job finished without a session result');
  }
  return result.session;
}

// ── The home hook ────────────────────────────────────────────────────────────────

export type DatasetsState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; data: DatasetListResponse };

/**
 * Load the home screen (`GET /api/datasets`). Empty `roots` is the honest first-run state — the UI
 * shows the folder picker rather than pretending to know where the data lives.
 *
 * `reloadKey` re-runs the fetch when it changes (e.g. after a `scanDatasets` adds a root).
 */
export function useDatasets(reloadKey?: unknown): DatasetsState {
  const [state, setState] = useState<DatasetsState>({ status: 'loading' });

  useEffect(() => {
    let cancelled = false;
    setState({ status: 'loading' });
    listDatasets()
      .then((data) => {
        if (!cancelled) setState({ status: 'ready', data });
      })
      .catch((e: unknown) => {
        if (!cancelled) setState({ status: 'error', message: describeError(e) });
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  return state;
}

function describeError(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}
