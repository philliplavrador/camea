// ─────────────────────────────────────────────────────────────────────────────────────────────
// NEW PROJECT — name → task → where the DATA comes from. Route `/new`.
//
// ⭐ **ONE PATH QUESTION, AND IT IS NEVER "WHERE SHOULD THIS GO?"** (his ruling 2026-08-10 — R44):
// *"camea saves project-specific files to its own repo automatically."* Both tasks now name only
// their input — a dataset folder, or a video file — and the project is created in Camea's store.
//
// Name it → pick a task → say where the data is. On create, the dataset flow opens a session and
// asks the SERVER to author the document (`createAnalysis` — never authored in the browser), then
// navigates to `/project/:id`. The video flow probes, creates and starts the build.
//
// ⚠️ This is the third shape of this step and the last two are worth knowing, because their reasons
// still hold even though their UI is gone. It was a dataset BROWSER over a registry of "data roots"
// (2026-07-25: replaced by path boxes — the app keeps no roots and recommends no folders), then two
// boxes, from and into (R42), with the video task deferring its "into" to the finished screen (R43).
// R44 removes the question rather than moving it again.
//
// ⛔ NO DATASET KNOWLEDGE: which trials are the mosaic is decided by `mosaicTrials` — ONE shared
// implementation (legacy/mosaic/trials.ts), read off what the backend measured. No number here.
//
// ⭐ **THE SNAPSHOT TASK IS NO LONGER OFFERED HERE** (2026-08-11). It moved to `src/legacy/mosaic`
// and was taken out of `TASKS`, so a new project is always the video pipeline. Everything below it
// — the `dataset` phase, `onCreate`, `ProjectPaths` — is deliberately LEFT IN PLACE: it is what
// still creates a snapshot project if the task ever comes back, and existing snapshot projects
// still open through the FeatureGate. See `src/legacy/mosaic` and `src/camea/legacy/__init__.py`.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { useCallback, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  getDataset,
  openSessionAndWait,
  createAnalysis,
  createVideoProject,
  startVideoBuild,
} from '../../api';
import { useToast } from '../../app';
import { Button, Card } from '../../design';
import { mosaicTrials } from '../../legacy/mosaic/trials';
import { ProjectPaths } from './ProjectPaths';
import { VideoPaths } from './VideoPaths';
import styles from './NewProjectFlow.module.css';

type Phase = 'name' | 'task' | 'dataset';

/** The dataset, once the user has confirmed it. ⭐ No folder: the app owns that (R44). */
interface Choice {
  datasetKey: string;
}

/** The video task's choice — a probed FILE, and nothing else. */
interface VideoChoice {
  videoPath: string;
  videoName: string;
}

// ⭐ ONE TASK, SO NO TASK QUESTION. The snapshot builder (`{ key: 'mosaic', label: 'Build mosaic',
// blurb: 'Place tiles, sweep to verify, export.' }`) was retired from this list on 2026-08-11.
// Add a second entry here and the `task` phase — its cards, its step in the stepper, its Back
// button — comes back on its own. That is why the phase machinery below is kept, not deleted.
const TASKS = [
  {
    key: 'videomosaic',
    label: 'Build mosaic from video',
    blurb: 'Point Camea at a survey video — it builds the mosaic automatically.',
  },
];

/** The only task, when there is only one — then asking "what do you want to do?" is a list of one,
 *  so we skip straight past it. `null` as soon as a second task returns. */
const ONLY_TASK: string | null = TASKS.length === 1 ? TASKS[0].key : null;

const STEPS: { key: Phase; label: string }[] = [
  { key: 'name', label: 'Name' },
  // The Task step is dropped from the stepper while there is nothing to choose — a numbered step
  // he never sees would only make the count lie.
  ...(ONLY_TASK ? [] : [{ key: 'task' as Phase, label: 'Task' }]),
  { key: 'dataset', label: 'Data' },
];

export function NewProjectFlow() {
  const navigate = useNavigate();
  const toast = useToast();

  const [phase, setPhase] = useState<Phase>('name');
  const [name, setName] = useState('');
  const [task, setTask] = useState(TASKS[0].key);
  const [choice, setChoice] = useState<Choice | null>(null);
  const [videoChoice, setVideoChoice] = useState<VideoChoice | null>(null);
  const [creating, setCreating] = useState<string | null>(null); // progress message while creating

  // Identity-stable so `ProjectPaths`/`VideoPaths`' effects do not re-fire on every render.
  const onReady = useCallback((c: Choice | null) => setChoice(c), []);
  const onVideoReady = useCallback((c: VideoChoice | null) => setVideoChoice(c), []);

  // The two seams the single-task case moves through. With one task there is nothing to ask, so
  // Name goes straight to Data and Back comes straight back — the `task` phase is skipped, not
  // removed. Both revert to a real stop the moment `TASKS` has a second entry.
  const afterName = useCallback(() => {
    if (ONLY_TASK) {
      setTask(ONLY_TASK);
      setPhase('dataset');
    } else setPhase('task');
  }, []);
  const beforeData = useCallback(() => setPhase(ONLY_TASK ? 'name' : 'task'), []);

  async function onCreate(): Promise<void> {
    if (creating || !choice) return;
    setCreating('reading dataset…');
    try {
      const detail = await getDataset(choice.datasetKey);
      const trials = mosaicTrials(detail.summary.shapes ?? [], detail.blocks ?? []);
      if (!trials || trials.length === 0) {
        throw new Error('this dataset has no square (N×N) frames to build a mosaic from.');
      }
      setCreating('opening session…');
      const sess = await openSessionAndWait(
        { dataset_key: choice.datasetKey, trials },
        { onProgress: (j) => setCreating(j.phase ?? j.message ?? 'opening…') },
      );
      setCreating('creating project…');
      const project = await createAnalysis({
        session_id: sess.session_id,
        feature: task,
        name: name.trim() || detail.summary.name || 'Untitled project',
        trials,
      });
      navigate(`/project/${project.analysis_id}`);
    } catch (e) {
      setCreating(null);
      toast.push(
        `Could not create the project: ${e instanceof Error ? e.message : String(e)}`,
        { tone: 'danger' },
      );
    }
  }

  /** No session, no trials and no folder — the server probes the video and authors the document in
   *  the store (R44). Then we start the build here, so he lands on progress with nothing left to
   *  decide; the feature screen re-attaches to the running job by itself. A refusal re-throws so
   *  `VideoPaths` shows the backend's reason INLINE, with the typed path kept. */
  async function onCreateVideo(): Promise<void> {
    if (creating || !videoChoice) return;
    setCreating('creating project…');
    try {
      const project = await createVideoProject({
        name: name.trim() || videoChoice.videoName || 'Untitled project',
        video_path: videoChoice.videoPath,
      });
      // ⚠️ The build is best-effort HERE, never fatal: the project exists either way, and its own
      // screen has a Build button. Failing the create over it would strand a project he can't see.
      await startVideoBuild(project.analysis_id).catch(() => undefined);
      navigate(`/project/${project.analysis_id}`);
    } catch (e) {
      setCreating(null);
      throw e;
    }
  }

  const stepIndex = STEPS.findIndex((s) => s.key === phase);
  const steps = STEPS.map((s) =>
    s.key === 'dataset' && task === 'videomosaic' ? { ...s, label: 'Video' } : s,
  );

  return (
    <section className={styles.flow} data-testid="new-project-flow">
      <header className={styles.head}>
        <h1 className={styles.title}>New project</h1>
        <ol className={styles.stepper}>
          {steps.map((s, i) => (
            <li
              key={s.key}
              className={styles.step}
              data-active={i === stepIndex || undefined}
              data-done={i < stepIndex || undefined}
            >
              <span className={styles.stepNum}>{i + 1}</span>
              {s.label}
            </li>
          ))}
        </ol>
      </header>

      {creating && (
        <div className={styles.creating} data-testid="np-creating">
          {creating}
        </div>
      )}

      {!creating && phase === 'name' && (
        <div className={styles.panel}>
          <label className={styles.field}>
            <span className={styles.fieldLabel}>Project name</span>
            <input
              className={styles.input}
              data-testid="np-name"
              autoFocus
              value={name}
              placeholder="e.g. Retina run"
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && name.trim()) afterName();
              }}
            />
          </label>
          <div className={styles.nav}>
            <Button variant="ghost" onClick={() => navigate('/')} data-testid="np-cancel">
              Cancel
            </Button>
            <Button
              variant="primary"
              disabled={!name.trim()}
              onClick={afterName}
              data-testid="np-next"
            >
              Next
            </Button>
          </div>
        </div>
      )}

      {/* ⭐ THE TASK PHASE — UNREACHABLE TODAY, AND KEPT ANYWAY. With one task in `TASKS` this never
          renders (`afterName` jumps straight to Data), because "what do you want to do?" over a list
          of one is a question with no answer to give. It is left whole — cards, stepper entry, Back —
          so that adding a second task to `TASKS` is the only edit needed to bring it back. ⛔ Do not
          delete it as dead code; it is the seam the snapshot builder was unhooked from on
          2026-08-11, and the seam the next feature will hook into. */}
      {!creating && phase === 'task' && (
        <div className={styles.panel}>
          <p className={styles.prompt}>What do you want to do?</p>
          <div className={styles.tasks}>
            {TASKS.map((t) => (
              <Card
                key={t.key}
                interactive
                className={styles.taskCard}
                data-testid="task-card"
                data-task={t.key}
                onClick={() => {
                  setTask(t.key);
                  setPhase('dataset');
                }}
              >
                <span className={styles.taskLabel}>{t.label}</span>
                <span className={styles.taskBlurb}>{t.blurb}</span>
              </Card>
            ))}
          </div>
          <div className={styles.nav}>
            <Button variant="ghost" onClick={() => setPhase('name')} data-testid="np-back">
              Back
            </Button>
          </div>
        </div>
      )}

      {!creating && phase === 'dataset' && task !== 'videomosaic' && (
        <div className={styles.panel}>
          <div className={styles.nav}>
            <Button variant="ghost" onClick={beforeData} data-testid="np-back">
              Back
            </Button>
          </div>
          <ProjectPaths onReady={onReady} onCreate={() => void onCreate()} busy={!!creating} />
        </div>
      )}

      {/* Kept MOUNTED while creating (only hidden): a create refusal must land back on the boxes with
          the typed paths intact (R42.5), not on a remount that forgot them. Inline display:none,
          not the hidden attribute — .panel's own display:flex would override [hidden]. */}
      {phase === 'dataset' && task === 'videomosaic' && (
        <div className={styles.panel} style={creating ? { display: 'none' } : undefined}>
          <div className={styles.nav}>
            <Button variant="ghost" onClick={beforeData} data-testid="np-back">
              Back
            </Button>
          </div>
          <VideoPaths onReady={onVideoReady} onCreate={onCreateVideo} busy={!!creating} />
        </div>
      )}
    </section>
  );
}
