// PROJECTS — the manager's read model. A "project" IS an analysis (one dataset + one task/feature +
// a name + a document + outputs); the manager lists, renames and deletes them. Create lives in the
// new-project flow (it needs an open session to author the document on the server).
//
// ⚠️ `listAnalyses` (GET /api/workspace/analyses) 409s with `no_workspace` until the store folder is
// chosen once — the manager checks the workspace first and shows the first-run prompt, so this hook is
// only mounted once a store exists.

import { useCallback, useEffect, useState } from 'react';
import {
  listAnalyses,
  deleteAnalysis,
  renameAnalysis,
  type AnalysisSummary,
} from '../../api';

export type ProjectsState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; projects: AnalysisSummary[] };

export interface UseProjects {
  state: ProjectsState;
  refresh: () => void;
  remove: (id: string) => Promise<void>;
  rename: (id: string, name: string) => Promise<AnalysisSummary>;
}

export function useProjects(): UseProjects {
  const [state, setState] = useState<ProjectsState>({ status: 'loading' });
  const [reloadKey, setReloadKey] = useState(0);
  const refresh = useCallback(() => setReloadKey((k) => k + 1), []);

  useEffect(() => {
    let cancelled = false;
    setState({ status: 'loading' });
    listAnalyses().then(
      ({ analyses }) => {
        if (!cancelled) setState({ status: 'ready', projects: analyses });
      },
      (e: unknown) => {
        if (!cancelled)
          setState({ status: 'error', message: e instanceof Error ? e.message : String(e) });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  const remove = useCallback(
    async (id: string) => {
      await deleteAnalysis(id);
      refresh();
    },
    [refresh],
  );

  const rename = useCallback(
    async (id: string, name: string) => {
      const updated = await renameAnalysis(id, name);
      refresh();
      return updated;
    },
    [refresh],
  );

  return { state, refresh, remove, rename };
}
