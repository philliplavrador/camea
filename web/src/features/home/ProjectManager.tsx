// ─────────────────────────────────────────────────────────────────────────────────────────────
// THE PROJECT MANAGER — Camea's home (2026-07-24). "What do you want to do today?"
//
// A project = one dataset + one task (feature), living in ONE FOLDER the user named when he made it.
// Rename / delete / open / export them here. Creating one lives in the new-project flow (`/new`);
// opening one navigates to `/project/:id`.
//
// ⭐ **THERE IS NO FIRST-RUN "choose a store" SCREEN** (his ruling, 2026-07-25). Nothing has to be
// picked before he can start: the home opens straight onto his projects, or onto an honest empty
// state. Each project carries its own save folder, and Camea remembers only the list of them.
//
// ⛔ NO DATASET KNOWLEDGE. Every number on a card is read off the analysis summary the server returns;
// nothing here names a trial, a count or an exclusion.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { useNavigate } from 'react-router-dom';
import { getDocument, type AnalysisSummary, type MosaicDocument } from '../../api';
import { useDocument } from '../../store/documentStore';
import { useToast } from '../../app';
import { Button, Card, Badge } from '../../design';
import { useProjects } from './useProjects';
import { shortPath } from './pathText';
import styles from './ProjectManager.module.css';

const TASK_LABEL: Record<string, string> = { mosaic: 'Build mosaic' };
const taskLabel = (feature: string): string => TASK_LABEL[feature] ?? feature;

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

export function ProjectManager() {
  const navigate = useNavigate();
  const { state, refresh, remove, rename } = useProjects();
  const toast = useToast();

  async function onRename(p: AnalysisSummary): Promise<void> {
    const next = window.prompt('Rename project', p.name);
    if (next == null) return;
    const name = next.trim();
    if (!name || name === p.name) return;
    try {
      await rename(p.analysis_id, name);
    } catch (e) {
      toast.push(`Rename failed: ${e instanceof Error ? e.message : String(e)}`, { tone: 'danger' });
    }
  }

  /**
   * ⭐ REMOVE ≠ DELETE, and the app does not guess which he meant. The folder is his — he named it —
   * so taking the card off the home screen must not be a synonym for destroying a week of sweeping.
   * (`window.confirm` on purpose: R38 — Playwright can answer it, a custom modal it cannot.)
   */
  async function onForget(p: AnalysisSummary): Promise<void> {
    if (!window.confirm(`Remove "${p.name}" from this list?\n\nThe files stay in ${p.folder}.`))
      return;
    try {
      await remove(p.analysis_id, false);
      toast.push(`Removed "${p.name}" from the list — the files are still there.`);
    } catch (e) {
      toast.push(`Remove failed: ${e instanceof Error ? e.message : String(e)}`, { tone: 'danger' });
    }
  }

  async function onDelete(p: AnalysisSummary): Promise<void> {
    if (
      !window.confirm(
        `Delete "${p.name}" and its files?\n\nThis removes the document, the autosave and the ` +
          `exports from ${p.folder}. Anything else you keep in that folder is left alone. ` +
          `This cannot be undone.`,
      )
    )
      return;
    try {
      await remove(p.analysis_id, true);
      toast.push(`Deleted "${p.name}".`, { tone: 'default' });
    } catch (e) {
      toast.push(`Delete failed: ${e instanceof Error ? e.message : String(e)}`, { tone: 'danger' });
    }
  }

  async function onExport(p: AnalysisSummary): Promise<void> {
    try {
      const { doc } = await getDocument(p.analysis_id);
      // Reuse the document store's save-as (native dialog → prompt fallback, R38) on this project's doc.
      const prev = useDocument.getState().doc;
      useDocument.getState().openDocument(doc as MosaicDocument, { analysisId: p.analysis_id });
      const res = await useDocument.getState().saveAs();
      if (prev) useDocument.getState().openDocument(prev); // restore whatever was open (usually nothing)
      if (res) toast.push(`Exported — ${res.path}`, { tone: 'good' });
    } catch (e) {
      toast.push(`Export failed: ${e instanceof Error ? e.message : String(e)}`, { tone: 'danger' });
    }
  }

  return (
    <section className={styles.home} data-testid="project-manager">
      <header className={styles.head}>
        <div>
          <h1 className={styles.greeting}>What do you want to do today?</h1>
          <p className={styles.sub} data-testid="project-count">
            {state.status === 'ready'
              ? `${state.projects.length} project${state.projects.length === 1 ? '' : 's'}`
              : ' '}
          </p>
        </div>
        <div className={styles.actions}>
          <Button variant="primary" data-testid="new-project" onClick={() => navigate('/new')}>
            + New project
          </Button>
          <Button variant="ghost" data-testid="refresh-projects" onClick={refresh}>
            Refresh
          </Button>
        </div>
      </header>

      {state.status === 'loading' && <p className={styles.muted}>Loading projects…</p>}
      {state.status === 'error' && (
        <p className={styles.error} data-testid="projects-error">
          {state.message}
        </p>
      )}
      {state.status === 'ready' && state.projects.length === 0 && (
        <div className={styles.empty} data-testid="projects-empty">
          <p>No projects yet.</p>
          <Button variant="primary" onClick={() => navigate('/new')}>
            Create your first project
          </Button>
        </div>
      )}
      {state.status === 'ready' && state.projects.length > 0 && (
        <div className={styles.grid} role="list" data-testid="project-grid">
          {state.projects.map((p) => (
            <ProjectCard
              key={p.analysis_id}
              project={p}
              onOpen={() => navigate(`/project/${p.analysis_id}`)}
              onRename={() => void onRename(p)}
              onForget={() => void onForget(p)}
              onDelete={() => void onDelete(p)}
              onExport={() => void onExport(p)}
            />
          ))}
        </div>
      )}

      {/* A folder that has moved or is on an unplugged drive. Said out loud, never silently dropped. */}
      {state.status === 'ready' && state.unreadable.length > 0 && (
        <div className={styles.unreadable} data-testid="projects-unreadable">
          {state.unreadable.length} remembered folder
          {state.unreadable.length === 1 ? '' : 's'} could not be read — moved, renamed, or on a
          drive that is not plugged in:
          <ul>
            {state.unreadable.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

interface ProjectCardProps {
  project: AnalysisSummary;
  onOpen: () => void;
  onRename: () => void;
  onForget: () => void;
  onDelete: () => void;
  onExport: () => void;
}

function ProjectCard({ project: p, onOpen, onRename, onForget, onDelete, onExport }: ProjectCardProps) {
  const placed = p.n_anchored != null && p.n_tiles != null ? `${p.n_anchored}/${p.n_tiles} anchored` : null;
  return (
    <div className={styles.cardWrap} role="listitem">
      <Card
        interactive
        className={styles.card}
        data-testid="project-card"
        data-project-id={p.analysis_id}
        onClick={onOpen}
        role="button"
        tabIndex={0}
        onKeyDown={(e: React.KeyboardEvent) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onOpen();
          }
        }}
      >
        <div className={styles.cardHead}>
          <span className={styles.cardName} data-testid="project-name">
            {p.name}
          </span>
          <Badge state="unverified">{taskLabel(p.feature)}</Badge>
        </div>
        <div className={styles.cardFacts}>
          <span className={styles.dataset} title={p.dataset}>
            {p.dataset}
          </span>
          {placed && <span className={styles.placed}>{placed}</span>}
          <span className={styles.modified}>Updated {fmtDate(p.modified)}</span>
        </div>
        {/* ⭐ He chose this folder. Show it to him — it is how he finds his work in Explorer. */}
        {p.folder && (
          <span className={styles.folder} title={p.folder} data-testid="project-folder">
            {shortPath(p.folder, 44)}
          </span>
        )}
        {p.independent_of_method === false && (
          <span className={styles.provenance} title="A machine placed tiles in this project.">
            machine-assisted
          </span>
        )}
      </Card>
      <div className={styles.cardMenu}>
        <button type="button" data-testid="project-rename" onClick={onRename} title="Rename">
          Rename
        </button>
        <button type="button" data-testid="project-export" onClick={onExport} title="Export to a file">
          Export
        </button>
        <button
          type="button"
          data-testid="project-forget"
          onClick={onForget}
          title="Take it off this list — the files stay where they are"
        >
          Remove
        </button>
        <button
          type="button"
          className={styles.danger}
          data-testid="project-delete"
          onClick={onDelete}
          title="Delete this project's files"
        >
          Delete
        </button>
      </div>
    </div>
  );
}
