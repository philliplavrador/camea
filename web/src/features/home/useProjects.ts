// PROJECTS — the manager's read model. A "project" IS an analysis (one dataset + one task/feature +
// a name + a document + outputs), living in ONE FOLDER **in Camea's own store** (R44); the manager
// lists, renames and deletes them. Create lives in the new-project flow (it needs an open session to
// author the document on the server).
//
// ⭐ `listAnalyses` (GET /api/projects) never 409s: there is no store to choose first, so an empty
// list is the honest first-run answer and this hook mounts unconditionally.
//
// ⭐ `migration` rides along on that same response. It is set ONCE — the first launch after R44,
// when projects were brought in from the folders the user used to name — and null forever after.

import { useCallback, useEffect, useState } from 'react';
import {
  listAnalyses,
  deleteAnalysis,
  renameAnalysis,
  type AnalysisSummary,
  type MigrationReport,
} from '../../api';

export type ProjectsState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | {
      status: 'ready';
      projects: AnalysisSummary[];
      unreadable: string[];
      migration: MigrationReport | null;
      /** ⏱️ Set while the launch migration is still moving projects in (R48). The manager polls
       *  this job for the one bar — and refetches the listing when it ends, which is when the
       *  final `migration` report (and every migrated card) arrives. */
      migrationJobId: string | null;
    };

export interface UseProjects {
  state: ProjectsState;
  refresh: () => void;
  /** ⭐ **DELETE MEANS DELETE** (R44) — the project and everything in it. The confirmation is the
   *  caller's job; R42.8's forget-vs-delete is retired with the folders it protected. */
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
      ({ analyses, unreadable, migration, migration_job_id }) => {
        if (!cancelled)
          setState({
            status: 'ready',
            projects: analyses,
            unreadable: unreadable ?? [],
            migration: migration ?? null,
            migrationJobId: migration_job_id ?? null,
          });
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
