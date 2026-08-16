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
// ⭐ **AND EVERY TASK ASKS FOR ITS DATA AGAIN** (2026-08-14, plan 002). For one day `Analyze MEA`
// was the exception: picking its card created the project outright, with no Data step. That was an
// intermediate state, shipped knowingly, and it is over — *"you create the project then you select
// what you want to do in this project ... then after that it asks you to upload the files you need
// for that task."* So the shape is **Name → Task → Files, for both tasks**, which is what restores
// R41 and R44.2 rather than needing an exception written against them.
//
// ⚠️ **`createNow` IS GONE FROM `TASKS` WITH IT.** 001 left the invariant *"`dataStep: null` and
// `createNow` being set are the same fact said twice, and they must agree"*; both changed together,
// which is exactly what that invariant existed to force. ⛔ Do not reintroduce a create-on-card-
// click path for a task that has a Data step — the two would race for the same project.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { useCallback, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  getDataset,
  openSessionAndWait,
  createAnalysis,
  createMeaProject,
  createVideoProject,
  startVideoBuild,
  useJob,
  useStopJob,
} from '../../api';
import type { AnalysisSummary } from '../../api';
import { useToast } from '../../app';
import { Button, Card, LiveWarning, Progress } from '../../design';
// ⭐ **THE SAME COMPONENT THE PROJECT'S OWN "+ Add recordings" MOUNTS** — one tick-list, two mount
// points. ⚠️ This is a feature importing another feature's file, which the app otherwise forbids;
// it is allowed here for the one reason the rule exists to protect: `NewProjectFlow` is *about* the
// tasks, so it already names every one of them (`TASKS`) and is the wizard half of `FeatureGate`'s
// seam. A second picker written to avoid this import would be the actual harm.
import { ImportRecordings } from '../mea/ImportRecordings';
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
  /**
   * What the third step asks for. ⚠️ **`null` is still supported and is still meaningful** — a task
   * with nothing to ask would skip the step — but no task is `null` today, and one that became so
   * would also need a `createNow` again. The two are the same fact said twice and they must agree.
   */
  dataStep: 'video' | 'dataset' | 'recordings' | null;
  /**
   * ⭐ Set on a task with NO Data step: picking its card creates the project outright and the flow
   * ends there. ⛔ Unused since 2026-08-14 (plan 002), and left standing for the same reason the
   * whole `task` phase was left standing through the year it had nothing to ask: it is the seam a
   * future task with no input would use, and rebuilding it is more expensive than keeping it.
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
    dataStep: 'recordings',
  },
];

/** The only task, when there is only one — then asking "what do you want to do?" is a list of one,
 *  so we skip straight past it. `null` as soon as a second task returns (it has). */
const ONLY_TASK: string | null = TASKS.length === 1 ? TASKS[0].key : null;

const taskOf = (key: string): Task => TASKS.find((t) => t.key === key) ?? TASKS[0];

/** What the third step is CALLED, once he has picked a task and we know what it will ask for. */
const DATA_STEP_LABEL: Record<'video' | 'dataset' | 'recordings', string> = {
  video: 'Video',
  dataset: 'Data',
  recordings: 'Files',
};

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
      ? [{ key: 'dataset', label: DATA_STEP_LABEL[t.dataStep] }]
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
  /**
   * ⭐ ⏱️ **THE FIRST THING A NEW USER EVER WAITS ON (BEHAVIOUR R48).** Creating a project from a
   * dataset loads its whole frame stack — tens of seconds on a real one — and this screen used to
   * render `j.phase ?? j.message` and drop `j.pct` and `j.eta_s` on the floor, both of which were
   * already on the wire and already being polled. Watching the job with `useJob` gets the ticking
   * countdown (R8) and a Stop for free.
   */
  const [createJobId, setCreateJobId] = useState<string | null>(null);
  const createJob = useJob(createJobId);
  const stopJob = useStopJob();
  // Set when HE pressed Stop, so the rejection that follows is reported as his decision rather than
  // as a failure the app is apologising for (R48.9 — a wait that ends says how it ended).
  const stoppedRef = useRef(false);
  // The Files step's chosen paths, and the refusal that has to stay next to the tick-list rather
  // than fly past on a toast — the fix for it is one untick away.
  const [meaPaths, setMeaPaths] = useState<string[]>([]);
  const [meaError, setMeaError] = useState<string | null>(null);

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
    stoppedRef.current = false;
    setCreating('Reading the dataset');
    try {
      const detail = await getDataset(choice.datasetKey);
      const trials = mosaicTrials(detail.summary.shapes ?? [], detail.blocks ?? []);
      if (!trials || trials.length === 0) {
        throw new Error('this dataset has no square (N×N) frames to build a mosaic from.');
      }
      setCreating('Opening the dataset');
      try {
        const sess = await openSessionAndWait(
          { dataset_key: choice.datasetKey, trials },
          {
            onProgress: (j) => {
              setCreateJobId(j.job_id);
              setCreating(j.said_as || 'Opening the dataset');
            },
          },
        );
        setCreateJobId(null);
        setCreating('Creating the project');
        const project = await createAnalysis({
          session_id: sess.session_id,
          feature: task,
          name: name.trim() || detail.summary.name || 'Untitled project',
          trials,
        });
        navigate(`/project/${project.analysis_id}`);
      } finally {
        setCreateJobId(null);
      }
    } catch (e) {
      setCreating(null);
      // R48.9 — his own Stop is not a failure. Say what happened, in the right tone.
      if (stoppedRef.current) {
        toast.push('Stopped — no project was created.', { tone: 'default' });
        return;
      }
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
    setCreating('Creating the project');
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
   * ⭐ Left for a future task that asks for nothing. See `Task.createNow` — unused since plan 002
   * gave `Analyze MEA` its Files step, and kept for the same reason the whole `task` phase was kept
   * through the year it had one entry.
   */
  async function createNow(make: (name: string) => Promise<{ analysis_id: string }>): Promise<void> {
    if (creating) return;
    setCreating('Creating the project');
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

  /**
   * ⭐ **ANALYZE MEA: CREATE, WITH THE RECORDINGS ALREADY ON IT.** One call — `POST
   * /api/mea/projects` takes the name and the chosen paths together. ⛔ Never create-then-add: a
   * second call that failed would strand a project he can see on the home screen and cannot use,
   * and he would have to delete it himself before he could try again.
   *
   * ⭐ **CREATE WORKS WITH NOTHING TICKED** (his ruling, 2026-08-14, asked with mockups). An empty
   * project is a state the app can already be in — it is what he is left with the moment he removes
   * his last recording — so a wizard that could not produce one would be a door that opens only one
   * way. He lands on the shelf's empty state, whose **Add recordings** button does the same job.
   *
   * A refusal (one of the files is not a MaxLab recording) keeps him on this step with his ticks
   * intact, and says so inline: the tick-list is right there, so unticking the named file and
   * pressing Create again is the whole repair.
   */
  async function onCreateMea(): Promise<void> {
    if (creating) return;
    setCreating(meaPaths.length > 0 ? 'Creating the project' : 'Creating an empty project');
    setMeaError(null);
    try {
      const project = await createMeaProject(name.trim(), meaPaths);
      navigate(`/project/${project.analysis_id}`);
    } catch (e) {
      setCreating(null);
      setMeaError(e instanceof Error ? e.message : String(e));
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

      {/* ⏱️ R48 — the wait that used to be one word. ⚠️ No `useDelayedFlag` grace here on purpose:
          the step panel is REPLACED while creating, so 400 ms of nothing would be a blank screen,
          not a spared flash. (R48.1's grace protects content that is still on screen.) */}
      {creating && (
        <div className={styles.creating} data-testid="np-creating">
          <Progress
            data-testid="np-progress"
            label={createJobId ? createJob.job?.said_as || creating : creating}
            pct={createJobId ? createJob.pct : null}
            etaText={createJobId ? createJob.etaText : null}
            elapsedText={createJobId ? createJob.elapsedText : null}
            phase={createJobId ? createJob.phase : null}
            message={createJobId ? createJob.message : null}
            onStop={
              createJobId && !createJob.isTerminal && (createJob.job?.cancellable ?? true)
                ? () => {
                    stoppedRef.current = true;
                    void stopJob(createJobId);
                  }
                : undefined
            }
            unstoppableWhy={createJobId ? undefined : 'this step cannot be stopped once it starts'}
          />
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

      {/* ⭐ ANALYZE MEA — THE FILES STEP. Kept MOUNTED while creating (only hidden), for the same
          reason the video step is: a refusal must land back on the tick-list with his ticks intact,
          not on a remount that forgot them. */}
      {phase === 'dataset' && task === 'mea' && (
        <div className={styles.panel} style={creating ? { display: 'none' } : undefined}>
          <div className={styles.nav}>
            <Button variant="ghost" onClick={beforeData} data-testid="np-back">
              Back
            </Button>
          </div>
          <p className={styles.prompt}>Which recordings?</p>
          <ImportRecordings onChange={setMeaPaths} busy={!!creating} />
          {meaError && (
            <LiveWarning variant="loud">
              <span data-testid="np-mea-error">{meaError}</span>
            </LiveWarning>
          )}
          <div className={styles.nav}>
            <span className={styles.meaCount} data-testid="np-mea-count">
              {meaPaths.length > 0
                ? `${meaPaths.length} chosen`
                : 'None chosen — the project starts empty and you can add them later.'}
            </span>
            <Button
              variant="primary"
              disabled={!!creating}
              onClick={() => void onCreateMea()}
              data-testid="np-create"
            >
              Create
            </Button>
          </div>
        </div>
      )}

      {!creating && phase === 'dataset' && task !== 'videomosaic' && task !== 'mea' && (
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
