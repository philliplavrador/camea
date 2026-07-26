import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError, type ErrorEnvelope } from '../../api/client';
import type { components } from '../../api/schema';

export type DatasetSummary = components['schemas']['DatasetSummary'];
export type DatasetListResponse = components['schemas']['DatasetListResponse'];
export type AnalysisRef = components['schemas']['AnalysisRef'];
export type ShapeGroup = components['schemas']['ShapeGroup'];

export type DatasetsState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; data: DatasetListResponse };

export interface DatasetsHook {
  state: DatasetsState;
  /** Re-read the remembered roots (GET /api/datasets). */
  refetch: () => void;
  /** Point Camea at a new folder (POST /api/datasets/scan, remembered) and adopt the fresh listing. */
  scanRoot: (root: string) => Promise<void>;
}

/**
 * Load the home screen: every dataset under every remembered root (GET /api/datasets). The app
 * carries no knowledge of where the data is — this is whatever the user has pointed Camea at. There
 * are NO trial numbers, ranges, counts or exclusion list here; every number shown is read off the
 * response (HARD RULE 3 / BEHAVIOUR I1).
 */
export function useDatasets(): DatasetsHook {
  const [state, setState] = useState<DatasetsState>({ status: 'loading' });
  const reqSeq = useRef(0);

  const refetch = useCallback(() => {
    const seq = ++reqSeq.current;
    setState({ status: 'loading' });
    api
      .GET('/api/datasets')
      .then((r) => {
        if (seq !== reqSeq.current) return; // a newer request superseded this one
        // Read the HTTP status off the (always-present) response before narrowing: /api/datasets has no
        // error response in the contract, so the openapi-fetch error branch narrows `r` to `never`.
        const status = r.response.status;
        if (r.error !== undefined || r.data === undefined) {
          setState({ status: 'error', message: `datasets request failed (${status})` });
          return;
        }
        setState({ status: 'ready', data: r.data });
      })
      .catch((e: unknown) => {
        if (seq === reqSeq.current) setState({ status: 'error', message: String(e) });
      });
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  const scanRoot = useCallback(async (root: string) => {
    const seq = ++reqSeq.current;
    const r = await api.POST('/api/datasets/scan', { body: { root, depth: 3, remember: true } });
    if (r.error !== undefined || r.data === undefined) {
      // The backend says WHY ("no such directory: …"). Show that, not a bare status code.
      throw new ApiError(r.response.status, r.error as ErrorEnvelope | undefined);
    }
    if (seq !== reqSeq.current) return;
    // The scan response lists only the datasets under the root just added. Re-read the whole set, or
    // adding a second root would appear to make the first one's datasets vanish.
    setState({ status: 'ready', data: r.data });
    const all = await api.GET('/api/datasets');
    if (seq === reqSeq.current && all.data !== undefined) {
      setState({ status: 'ready', data: all.data });
    }
  }, []);

  return { state, refetch, scanRoot };
}
