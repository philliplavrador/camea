// ─────────────────────────────────────────────────────────────────────────────────────────────
// NEW PROJECT — name → task → where from / where to (2026-07-25). Route `/new`.
//
// Name it → pick a task ("Build mosaic" is the only one today) → say where the data comes FROM and
// where the project is saved INTO. On create, the flow opens a session for the dataset and asks the
// SERVER to author the document (`createAnalysis` — the doc is never authored in the browser), then
// navigates to `/project/:id` where the mosaic wizard mounts.
//
// ⭐ The last step used to be a dataset BROWSER over a registry of "data roots". His ruling of
// 2026-07-25 replaced it with two path boxes: the app keeps no roots, scans nothing on launch, and
// recommends no folders. See `ProjectPaths.tsx`.
//
// ⛔ NO DATASET KNOWLEDGE: which trials are the mosaic is decided by `mosaicTrials` — ONE shared
// implementation (features/mosaic/trials.ts), read off what the backend measured. No number here.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { useCallback, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getDataset, openSessionAndWait, createAnalysis } from '../../api';
import { useToast } from '../../app';
import { Button, Card } from '../../design';
import { mosaicTrials } from '../mosaic/trials';
import { ProjectPaths } from './ProjectPaths';
import styles from './NewProjectFlow.module.css';

type Phase = 'name' | 'task' | 'dataset';

/** Both paths, once the user has confirmed them. */
interface Choice {
  datasetKey: string;
  folder: string;
}

const TASKS = [{ key: 'mosaic', label: 'Build mosaic', blurb: 'Place tiles, sweep to verify, export.' }];

const STEPS: { key: Phase; label: string }[] = [
  { key: 'name', label: 'Name' },
  { key: 'task', label: 'Task' },
  { key: 'dataset', label: 'Data & folder' },
];

export function NewProjectFlow() {
  const navigate = useNavigate();
  const toast = useToast();

  const [phase, setPhase] = useState<Phase>('name');
  const [name, setName] = useState('');
  const [task, setTask] = useState('mosaic');
  const [choice, setChoice] = useState<Choice | null>(null);
  const [creating, setCreating] = useState<string | null>(null); // progress message while creating

  // Identity-stable so `ProjectPaths`' effect does not re-fire on every render of this screen.
  const onReady = useCallback((c: Choice | null) => setChoice(c), []);

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
        folder: choice.folder,
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

  const stepIndex = STEPS.findIndex((s) => s.key === phase);

  return (
    <section className={styles.flow} data-testid="new-project-flow">
      <header className={styles.head}>
        <h1 className={styles.title}>New project</h1>
        <ol className={styles.stepper}>
          {STEPS.map((s, i) => (
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
                if (e.key === 'Enter' && name.trim()) setPhase('task');
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
              onClick={() => setPhase('task')}
              data-testid="np-next"
            >
              Next
            </Button>
          </div>
        </div>
      )}

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

      {!creating && phase === 'dataset' && (
        <div className={styles.panel}>
          <div className={styles.nav}>
            <Button variant="ghost" onClick={() => setPhase('task')} data-testid="np-back">
              Back
            </Button>
          </div>
          <ProjectPaths onReady={onReady} onCreate={() => void onCreate()} busy={!!creating} />
        </div>
      )}
    </section>
  );
}
