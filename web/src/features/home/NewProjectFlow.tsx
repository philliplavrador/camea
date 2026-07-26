// ─────────────────────────────────────────────────────────────────────────────────────────────
// NEW PROJECT — name → task → dataset (2026-07-24). Route `/new`.
//
// Name it → pick a task ("Build mosaic" is the only one today) → attach a dataset. On create, the flow
// opens a session for the dataset and asks the SERVER to author the document (`createAnalysis` — the doc
// is never authored in the browser), then navigates to `/project/:id` where the mosaic wizard mounts.
//
// ⛔ NO DATASET KNOWLEDGE: `squareTrials` picks the largest N×N shape group off the dataset summary; no
// trial number is named.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getDataset, openSessionAndWait, createAnalysis } from '../../api';
import { useToast } from '../../app';
import { Button, Card } from '../../design';
import { DatasetPicker } from './DatasetBrowser';
import styles from './NewProjectFlow.module.css';

type Phase = 'name' | 'task' | 'dataset';

/** The largest SQUARE (N×N) shape group's trials — a mosaic wants square tiles. No trial number named. */
function squareTrials(shapes: { w: number; h: number; n: number; trials: number[] }[]): number[] | null {
  const square = shapes.filter((s) => s.w === s.h).sort((a, b) => b.n - a.n)[0];
  return square ? [...square.trials].sort((a, b) => a - b) : null;
}

const TASKS = [{ key: 'mosaic', label: 'Build mosaic', blurb: 'Place tiles, sweep to verify, export.' }];

const STEPS: { key: Phase; label: string }[] = [
  { key: 'name', label: 'Name' },
  { key: 'task', label: 'Task' },
  { key: 'dataset', label: 'Dataset' },
];

export function NewProjectFlow() {
  const navigate = useNavigate();
  const toast = useToast();

  const [phase, setPhase] = useState<Phase>('name');
  const [name, setName] = useState('');
  const [task, setTask] = useState('mosaic');
  const [creating, setCreating] = useState<string | null>(null); // progress message while creating

  async function onDatasetSelected(datasetKey: string): Promise<void> {
    if (creating) return;
    setCreating('reading dataset…');
    try {
      const detail = await getDataset(datasetKey);
      const trials = squareTrials(detail.summary.shapes ?? []);
      if (!trials || trials.length === 0) {
        throw new Error('this dataset has no square (N×N) frames to build a mosaic from.');
      }
      setCreating('opening session…');
      const sess = await openSessionAndWait(
        { dataset_key: datasetKey, trials },
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
          <DatasetPicker onSelect={(key) => void onDatasetSelected(key)} />
        </div>
      )}
    </section>
  );
}
