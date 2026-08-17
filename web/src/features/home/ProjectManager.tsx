// ─────────────────────────────────────────────────────────────────────────────────────────────
// THE PROJECT MANAGER — Camea's home (2026-07-24). "What do you want to do today?"
//
// A project = one dataset + one task (feature), living in ONE FOLDER **in Camea's own store**
// (R44). Rename / delete / open / export them here. Creating one lives in the new-project flow
// (`/new`); opening one navigates to `/project/:id`, where the Outputs panel is how its files are
// browsed — the app is the only door to them.
//
// ⭐ **NOTHING IS PICKED BEFORE HE CAN START.** No first-run "choose a store" screen (2026-07-25)
// and, since R44, no per-project save folder either: the home opens straight onto his projects, or
// onto an honest empty state.
//
// ⛔ NO DATASET KNOWLEDGE. Every number on a card is read off the analysis summary the server returns;
// nothing here names a trial, a count or an exclusion.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  getDocument,
  useJob,
  useStopJob,
  type AnalysisSummary,
  type MigrationReport,
  type MosaicDocument,
} from '../../api';
import { useDocument } from '../../store/documentStore';
import { useToast } from '../../app';
import { Button, Card, Badge, Progress, useDelayedFlag } from '../../design';
import { useProjects } from './useProjects';
import { shortPath } from './pathText';
import styles from './ProjectManager.module.css';

/**
 * ⭐ **ONE NAME PER TASK, AND THE CHOOSER OWNS IT.** These have to read the same as the cards on
 * `/new` (`NewProjectFlow.TASKS`) — a project he made by clicking "Analyze MEA" must not come back
 * to him as something else. The keys are the manifest's and never move; only these labels do.
 * `mosaic` is the retired snapshot builder: off the chooser, still openable, still named.
 */
const TASK_LABEL: Record<string, string> = {
  mosaic: 'Build mosaic',
  videomosaic: 'Simultaneous MEA + 2P',
  mea: 'Analyze MEA',
};
const taskLabel = (feature: string): string => TASK_LABEL[feature] ?? feature;

/**
 * What a card says where its input's name would go, when it has not been given one. ⭐ Every task
 * before this one was a wrapper around a folder or a file, so the line was never empty; `Analyze
 * MEA` is a **shelf**, filled from inside the project, and it is born with nothing on it. A blank
 * line there would read as a card that failed to load rather than one that is simply new.
 *
 * ⚠️ Since issue 011 this is the EMPTY-shelf line only: a shelf with recordings on it puts its
 * count there instead (`inputCount` below) — the card was saying "No recordings yet" over a shelf
 * of five, which is a false statement on the screen whose job is state.
 */
const NO_INPUT_YET: Record<string, string> = { mea: 'No recordings yet' };

/**
 * ⭐ **What an `Analyze MEA` card says instead of a dataset name: how much is on its shelf**
 * (issue 011). The count rides in `n_tiles` — the summary's one per-feature count slot, the same
 * one the mosaic fills with tiles and videomosaic with placed keyframes — and each feature's card
 * renders it in its own words. Derived server-side from the document's shelf when the summary is
 * built, never stored; `null`/`0` fall through to `NO_INPUT_YET`, which is the honest empty state.
 */
function inputCount(p: AnalysisSummary): string | null {
  if (p.feature !== 'mea' || p.n_tiles == null || p.n_tiles === 0) return null;
  return `${p.n_tiles} recording${p.n_tiles === 1 ? '' : 's'}`;
}

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

  /**
   * ⏱️ R48 — what this screen is busy with, in his words and NAMING THE PROJECT. A rename showed the
   * old name until the re-list landed and a delete showed nothing at all, which on a project holding
   * gigabyte recording copies is tens of seconds of a card that looks untouched.
   *
   * R48.7/R48.9 — neither has anything to poll: a rename is two round trips and a delete is a
   * `shutil.rmtree` with no callback. So `pct` stays null (the travelling sliver, never a filling
   * bar) and `why` says out loud that there is no Stop, rather than rendering a dead button.
   */
  const [busy, setBusy] = useState<{ label: string; why: string } | null>(null);
  // R48.1 — the 400 ms grace. Most renames beat it; no delete does.
  const showBusy = useDelayedFlag(busy != null);
  const loading = useDelayedFlag(state.status === 'loading');

  // ⏱️ **THE LAUNCH MIGRATION, AS THE ONE BAR (R48).** On the first launch after R44 the server no
  // longer holds every connection while projects move into the store — it answers at once and moves
  // them as a job. This polls that job: pct from bytes, a real ETA, and a Stop wired to the only
  // safe seam (between projects — a move that has started always completes). When it ends, the
  // refetch brings the migrated cards and the once-stated report in one go — never a silent end.
  const migrationJobId = state.status === 'ready' ? state.migrationJobId : null;
  const migJob = useJob(migrationJobId);
  const stopJob = useStopJob();
  useEffect(() => {
    if (migrationJobId && migJob.isTerminal) refresh();
  }, [migrationJobId, migJob.isTerminal, refresh]);

  async function onRename(p: AnalysisSummary): Promise<void> {
    const next = window.prompt('Rename project', p.name);
    if (next == null) return;
    const name = next.trim();
    if (!name || name === p.name) return;
    setBusy({
      label: `Renaming "${p.name}" to "${name}"`,
      why: 'a rename cannot be stopped once it starts',
    });
    try {
      await rename(p.analysis_id, name);
    } catch (e) {
      toast.push(`Rename failed: ${e instanceof Error ? e.message : String(e)}`, { tone: 'danger' });
    } finally {
      setBusy(null);
    }
  }

  /**
   * ⭐ **DELETE MEANS DELETE** (R44). R42.8's Remove-vs-Delete is retired: it existed because the
   * folder was one HE had named and might hold his own files. Camea owns the folder now, so a
   * project taken off this list is one nobody could ever reach again — "remove the card" and
   * "delete the work" are the same act, and it says so.
   *
   * 🔴 **The confirmation is not optional, and it names the outputs**, because those are the files
   * he might not have copied out yet. (`window.confirm` on purpose: R38 — Playwright can answer it,
   * a custom modal it cannot.)
   */
  async function onDelete(p: AnalysisSummary): Promise<void> {
    if (
      !window.confirm(
        `Delete "${p.name}"?\n\nThis deletes the project and everything in it, including any ` +
          `files it built that you have not copied out. This cannot be undone.`,
      )
    )
      return;
    setBusy({
      label: `Deleting "${p.name}" and everything in it`,
      why: 'a delete cannot be stopped once it starts',
    });
    try {
      await remove(p.analysis_id);
      toast.push(`Deleted "${p.name}".`, { tone: 'default' });
    } catch (e) {
      toast.push(`Delete failed: ${e instanceof Error ? e.message : String(e)}`, { tone: 'danger' });
    } finally {
      setBusy(null);
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

      {migrationJobId && !migJob.isTerminal && (
        <Progress
          className={styles.busy}
          data-testid="projects-migrating"
          label={migJob.job?.said_as || "Bringing your projects into Camea's store"}
          pct={migJob.pct}
          etaText={migJob.etaText}
          elapsedText={migJob.elapsedText}
          message={migJob.message}
          onStop={
            (migJob.job?.cancellable ?? true) ? () => void stopJob(migrationJobId) : undefined
          }
        />
      )}

      {state.status === 'ready' && state.migration && <MigrationNotice report={state.migration} />}

      {/* ⏱️ R48.7/R48.9 — no Stop, and the reason said out loud instead of a dead button. The label
          NAMES the project, so a delete of a gigabyte shelf is not a silent card. */}
      {busy && showBusy && (
        <Progress
          className={styles.busy}
          data-testid="projects-busy"
          label={busy.label}
          pct={null}
          unstoppableWhy={busy.why}
        />
      )}

      {/* R48.10 — in flight is not "no projects": this appears only while the list is being read,
          and `projects-empty` only once it has been. */}
      {state.status === 'loading' && loading && (
        <Progress
          className={styles.busy}
          data-testid="projects-loading"
          label="Reading your projects"
          pct={null}
          // R48.7 — one request with nothing to poll. Say so; never a button that does nothing.
          unstoppableWhy="reading the list cannot be stopped once it starts"
        />
      )}
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
              onDelete={() => void onDelete(p)}
              onExport={() => void onExport(p)}
            />
          ))}
        </div>
      )}

      {/* A project folder in the store whose manifest could not be read. Said out loud, never
          silently dropped — one corrupt file must cost him that card, not his home screen. */}
      {state.status === 'ready' && state.unreadable.length > 0 && (
        <div className={styles.unreadable} data-testid="projects-unreadable">
          {state.unreadable.length} project folder
          {state.unreadable.length === 1 ? '' : 's'} in Camea's store could not be read:
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

/**
 * ⭐ **SAID ONCE, ON THE FIRST LAUNCH AFTER R44.** Projects the user had saved into folders he named
 * were moved into Camea's store. A move he did not ask for and is not told about is indistinguishable
 * from a project that vanished — so this states what moved, and names anything that did not.
 */
function MigrationNotice({ report }: { report: MigrationReport }) {
  const moved = report.migrated ?? [];
  const failed = report.failed ?? [];
  return (
    <div className={styles.migration} data-testid="projects-migrated">
      {moved.length > 0 && (
        <p>
          Camea keeps your projects itself now, so {moved.length} project
          {moved.length === 1 ? ' was' : 's were'} moved out of the folder
          {moved.length === 1 ? '' : 's'} you had chosen: {moved.map((m) => m.name).join(', ')}. Open
          a project to browse and copy out its files.
        </p>
      )}
      {failed.length > 0 && (
        <>
          <p>
            {failed.length} could not be moved and {failed.length === 1 ? 'is' : 'are'} still exactly
            where {failed.length === 1 ? 'it was' : 'they were'}:
          </p>
          <ul>
            {failed.map((f) => (
              <li key={f.path}>
                <span className={styles.migrationPath}>{shortPath(f.path, 48)}</span> — {f.reason}
              </li>
            ))}
          </ul>
        </>
      )}
      {report.stopped && (
        <p data-testid="projects-migration-stopped">
          You stopped the move, so the rest stayed exactly where they were. Camea will offer to
          finish next time it starts.
        </p>
      )}
    </div>
  );
}

interface ProjectCardProps {
  project: AnalysisSummary;
  onOpen: () => void;
  onRename: () => void;
  onDelete: () => void;
  onExport: () => void;
}

function ProjectCard({ project: p, onOpen, onRename, onDelete, onExport }: ProjectCardProps) {
  // A videomosaic summary counts PLACED KEYFRAMES in n_tiles — "anchored" is a sweep word it never has.
  const placed =
    p.feature === 'videomosaic'
      ? p.n_tiles != null
        ? `${p.n_tiles} keyframes`
        : null
      : p.n_anchored != null && p.n_tiles != null
        ? `${p.n_anchored}/${p.n_tiles} anchored`
        : null;
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
          {p.dataset ? (
            <span className={styles.dataset} title={p.dataset}>
              {p.dataset}
            </span>
          ) : inputCount(p) ? (
            // ⭐ Issue 011: a shelf with recordings on it says HOW MANY, where every other task
            // shows its input's name. "No recordings yet" is kept for the truly empty shelf only.
            <span className={styles.dataset} data-testid="project-input-count">
              {inputCount(p)}
            </span>
          ) : (
            <span className={styles.datasetEmpty} data-testid="project-no-input">
              {NO_INPUT_YET[p.feature] ?? 'Nothing added yet'}
            </span>
          )}
          {placed && <span className={styles.placed}>{placed}</span>}
          <span className={styles.modified}>Updated {fmtDate(p.modified)}</span>
        </div>
        {/* ⭐ Where its DATA came from — the one path he chose, and the one worth showing. The
            project's own folder is Camea's and is deliberately not advertised as somewhere to go
            (R44): its files are browsed in the app, on the project screen. */}
        {p.data_dir && (
          <span className={styles.folder} title={p.data_dir} data-testid="project-data-dir">
            {shortPath(p.data_dir, 44)}
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
          className={styles.danger}
          data-testid="project-delete"
          onClick={onDelete}
          title="Delete this project and everything in it"
        >
          Delete
        </button>
      </div>
    </div>
  );
}
