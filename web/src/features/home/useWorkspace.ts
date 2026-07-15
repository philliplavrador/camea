import { useCallback, useEffect, useState } from 'react';
import { api } from '../../api/client';
import type { components } from '../../api/schema';

export type WorkspaceInfo = components['schemas']['WorkspaceInfo'];

export interface WorkspaceHook {
  workspace: WorkspaceInfo | null;
  /** Re-read GET /api/workspace. */
  refresh: () => void;
  /** Choose (and create) the workspace folder — PUT /api/workspace. */
  setWorkspace: (path: string) => Promise<void>;
}

/**
 * The WORKSPACE is where analyses are written — never inside the dataset, never inside the repo
 * (docs/API.md, the one-paragraph model). It is a home-screen concern: you pick it before, or as, you
 * open a dataset into a feature. This hook reads it and lets the browser set it.
 */
export function useWorkspace(): WorkspaceHook {
  const [workspace, setWorkspaceInfo] = useState<WorkspaceInfo | null>(null);

  const refresh = useCallback(() => {
    api
      .GET('/api/workspace')
      .then((r) => {
        if (r.data !== undefined) setWorkspaceInfo(r.data);
      })
      .catch(() => {
        /* a missing workspace is a normal first-run state, not an error to surface */
      });
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const setWorkspace = useCallback(async (path: string) => {
    const r = await api.PUT('/api/workspace', { body: { path, create: true } });
    if (r.error !== undefined || r.data === undefined) {
      throw new Error(`could not set workspace to ${path} (${r.response.status})`);
    }
    setWorkspaceInfo(r.data);
  }, []);

  return { workspace, refresh, setWorkspace };
}
