// ─────────────────────────────────────────────────────────────────────────────────────────────
// NEW PROJECT — name → task → where the DATA comes from. Route `/new`.
//
// ⭐ **AT MOST ONE PATH QUESTION, AND IT IS NEVER "WHERE SHOULD THIS GO?"** (his ruling 2026-08-10
// — R44): *"camea saves project-specific files to its own repo automatically."* A task names only
// its input — a dataset folder, or a video file, or **nothing at all** — and the project is created
// in Camea's store either way.
//
// Name it → pick a task → say where the data is, if that task needs to know. On create, the dataset
// flow opens a session and asks the SERVER to author the document (`createAnalysis` — never
// authored in the browser), then navigates to `/project/:id`. The video flow probes, creates and
// starts the build. `Analyze MEA` creates on the click of its card and navigates.
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
// ⭐ **THE SNAPSHOT TASK IS STILL NOT OFFERED HERE** (2026-08-11). It moved to `src/legacy/mosaic`
// and was taken out of `TASKS`; the second task that arrived in 2026-08-14 is not it. Everything
// that served it — the `dataset` phase, `onCreate`, `ProjectPaths` — is deliberately LEFT IN PLACE:
// it is what would create a snapshot project if the task ever came back, and existing snapshot
// projects still open through the FeatureGate. See `src/legacy/mosaic` and
// `src/camea/legacy/__init__.py`.
//
// ⭐ **AND THE QUESTION IS BACK** (2026-08-14). There are two tasks again — the video pipeline,
// renamed to the experiment it actually serves (**Simultaneous MEA + 2P**), and **Analyze MEA**,
// which opens a MaxWell recording on its own. So `ONLY_TASK` is null, and the whole `task` phase
// below — its cards, its step in the stepper, its Back button — woke up on its own, exactly as the
// 2026-08-11 note promised it would. ⛔ Nothing in that machinery was rewritten to do it.
//
// ⭐ **A THIRD OUTCOME: A TASK THAT ASKS FOR NOTHING.** `Analyze MEA` has no input at creation —
// the project is a shelf you put recordings on afterwards — so picking its card **creates and
// navigates**, and the Data step never happens. That is why `STEPS` is per-task now: a numbered
// step he will never reach would only make the count lie.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { useCallback, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  getDataset,
  openSessionAndWait,
  createAnalysis,
  createMeaProject,
  createVideoProject,
  startVideoBuild,
} from '../../api';
import type { AnalysisSummary } from '../../api';
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

interface Task {
  key: string;
  /** ⭐ What HE calls it. `key` is the manifest's and never changes; this is free to. */
  label: string;
  blurb: string;
  /** What the third step asks for — or **null for a task that has nothing left to ask**. */
  dataStep: 'video' | 'dataset' | null;
  /**
   * ⭐ Set on a task with no Data step: picking its card **creates the project outright** and the
   * flow ends there. `dataStep: null` and this being set are the same fact said twice — the first
   * for the stepper, the second for the outcome — and they must agree.
   */
  createNow?: (name: string) => Promise<AnalysisSummary>;
}

// ⭐ TWO TASKS AGAIN (2026-08-14), so the question is real again. The snapshot builder
// (`{ key: 'mosaic', label: 'Build mosaic', blurb: 'Place tiles, sweep to verify, export.' }`) was
// retired from this list on 2026-08-11 and is NOT one of them — it still opens through the
// FeatureGate, it is just not offered to new projects.
//
// ⛔ **THE KEYS ARE THE MANIFEST'S AND DO NOT MOVE.** `videomosaic` is written into every project
// folder in `%LOCALAPPDATA%/Camea/projects/`; renaming it would be a migration, and what he asked
// for was a name. So the label changed and the key did not.
const TASKS: Task[] = [
  {
    key: 'videomosaic',
    label: 'Simultaneous MEA + 2P',
    blurb: 'Point Camea at a survey video — it builds the mosaic automatically.',
    dataStep: 'video',
  },
  {
    key: 'mea',
    label: 'Analyze MEA',
    blurb: 'Open a MaxWell recording on its own — click an electrode, read what it recorded.',
    dataStep: null,
    createNow: createMeaProject,
  },
];

/** The only task, when there is only one — then asking "what do you want to do?" is a list of one,
 *  so we skip straight past it. `null` as soon as a second task returns (it has). */
const ONLY_TASK: string | null = TASKS.length === 1 ? TASKS[0].key : null;

const taskOf = (key: string): Task => TASKS.find((t) => t.key === key) ?? TASKS[0];

/**
 * The stepper, for the task in hand. ⭐ **Per-task, because the tasks are not the same length.**
 * A numbered step he never reaches would make the count lie — which is the same reason the Task
 * step itself was dropped while there was only one task to choose from.
 *
 * ⚠️ **`picked` is not a nicety.** Before he has answered "what do you want to do?", `task` is only
 * the default, so its data step is a GUESS — and captioning it `Video` while he is looking at a
 * card called `Analyze MEA` promises the wrong thing. Until he picks, the third step is shown but
 * left neutral: it still says how much is left (it never undercounts, whichever card he takes),
 * without naming something he has not chosen.
 */
function stepsFor(task: string, picked: boolean): { key: Phase; label: string }[] {
  const t = taskOf(task);
  const data: { key: Phase; label: string }[] = !picked
    ? [{ key: 'dataset', label: 'Data' }]
    : t.dataStep
      ? [{ key: 'dataset', label: t.dataStep === 'video' ? 'Video' : 'Data' }]
      : [];
  return [
    { key: 'name', label: 'Name' },
    ...(ONLY_TASK ? [] : [{ key: 'task' as Phase, label: 'Task' }]),
    ...data,
  ];
}

export function NewProjectFlow() {
  const navigate = useNavigate();
  const toast = useToast();

  const [phase, setPhase] = useState<Phase>('name');
  const [name, setName] = useState('');
  // ⭐ `task` starts as the default and `picked` says whether that is his answer or ours — see
  // `stepsFor`. With one task there is nothing to pick, so it is settled from the start.
  const [task, setTask] = useState(TASKS[0].key);
  const [picked, setPicked] = useState(ONLY_TASK != null);
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
  const beforeData = useCallback(() => {
    // Back from the Data step puts the question back in front of him, so his answer to it is
    // unmade too and the third step goes neutral again (`stepsFor`).
    setPicked(ONLY_TASK != null);
    setPhase(ONLY_TASK ? 'name' : 'task');
  }, []);

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

  /**
   * ⭐ **PICKING A TASK THAT ASKS FOR NOTHING IS CREATING IT.** `Analyze MEA` has no path, no
   * probe, no folder and no build to start — the server makes an empty project out of the name and
   * he is inside it. There is nothing left to ask, so there is no third step and no Create button.
   *
   * A failure lands on a toast and leaves him on the task cards with his name intact: unlike the
   * video task there is no inline box to show the refusal next to, because there is no box.
   */
  async function createNow(make: (name: string) => Promise<{ analysis_id: string }>): Promise<void> {
    if (creating) return;
    setCreating('creating project…');
    try {
      const project = await make(name.trim());
      navigate(`/project/${project.analysis_id}`);
    } catch (e) {
      setCreating(null);
      toast.push(
        `Could not create the project: ${e instanceof Error ? e.message : String(e)}`,
        { tone: 'danger' },
      );
    }
  }

  const steps = stepsFor(task, picked);
  const stepIndex = steps.findIndex((s) => s.key === phase);

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

      {/* ⭐ THE TASK PHASE — reachable again since 2026-08-14, and reached WITHOUT being rewritten.
          It was left whole through the year it had nothing to ask (cards, stepper entry, Back), so
          that adding a second entry to `TASKS` was the only edit needed to bring it back. That bet
          paid; keep it whole again if a task is ever retired down to one. */}
      {!creating && phase === 'task' && (
        <div className={styles.panel}>
          <p className={styles.prompt}>What do you want to do?</p>
          <div className={styles.tasks}>
            {TASKS.map((t) => {
              const pick = () => {
                setTask(t.key);
                setPicked(true);
                // ⭐ A task with nothing left to ask brings its own create, and the card IS the
                // Create button.
                if (t.createNow) void createNow(t.createNow);
                else setPhase('dataset');
              };
              return (
                // 🔴 `role`/`tabIndex`/`onKeyDown` are not decoration. `Card` renders a plain
                // `<div>`, so a bare `onClick` here is unreachable by Tab and deaf to Enter and
                // Space — and this is the ONLY door to either task. (The gap sat harmless while the
                // step was skipped; the moment it renders, the whole app is keyboard-dead at step
                // 2.) Same three lines the project cards on the home screen carry, for the same
                // reason — see `ProjectManager.ProjectCard`.
                <Card
                  key={t.key}
                  interactive
                  className={styles.taskCard}
                  data-testid="task-card"
                  data-task={t.key}
                  role="button"
                  tabIndex={0}
                  onClick={pick}
                  onKeyDown={(e: React.KeyboardEvent) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      pick();
                    }
                  }}
                >
                  <span className={styles.taskLabel}>{t.label}</span>
                  <span className={styles.taskBlurb}>{t.blurb}</span>
                </Card>
              );
            })}
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
