// PROJECTS — the manager's read model. A "project" IS an analysis (one dataset + one task/feature +
// a name + a document + outputs), living in ONE FOLDER the user named; the manager lists, renames,
// removes and deletes them. Create lives in the new-project flow (it needs an open session to author
// the document on the server).
//
// ⭐ `listAnalyses` (GET /api/projects) never 409s: since 2026-07-25 there is no store to choose
// first, so an empty list is the honest first-run answer and this hook mounts unconditionally.

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
  | { status: 'ready'; projects: AnalysisSummary[]; unreadable: string[] };

export interface UseProjects {
  state: ProjectsState;
  refresh: () => void;
  /** `deleteFiles: false` forgets it (files stay); `true` removes Camea's files from the folder. */
  remove: (id: string, deleteFiles?: boolean) => Promise<void>;
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
      ({ analyses, unreadable }) => {
        if (!cancelled)
          setState({ status: 'ready', projects: analyses, unreadable: unreadable ?? [] });
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
    async (id: string, deleteFiles = false) => {
      await deleteAnalysis(id, deleteFiles);
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
