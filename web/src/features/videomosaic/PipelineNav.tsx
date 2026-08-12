// THE PIPELINE HEADER — a PROGRESS INDICATOR, not a menu.
//
// His ask, 2026-08-11: *"they go through step by step, building the mosaic, mapping the
// electrodes, and then finding the region of the non-moving calcium recording. So it should be
// all one pipeline with a progress bar at the top."*
//
// The steps are the experiment's own order, and each one is genuinely a precondition of the next:
// there is no mosaic to map electrodes on until the survey is built, and a located region whose
// electrodes cannot be named is half an answer. So a step is LOCKED until the one before it is
// done, and clicking a locked step nudges instead of navigating.
//
// This mirrors `features/mosaic/WizardNav` deliberately rather than sharing it: the specs read a
// precise selector contract off each step, and the two features' step ids are different sets. The
// duplication is thirty lines of markup; a shared component parameterised over both would be a
// worse trade.

import styles from './PipelineNav.module.css';

/** The pipeline, in order. `regions` is the last step Camea does today — the MEA-side pairing
 *  that consumes its output is deliberately not here yet. */
export const PIPELINE_STEPS = ['survey', 'mosaic', 'electrodes', 'regions'] as const;
export type PipelineStepId = (typeof PIPELINE_STEPS)[number];

const LABELS: Record<PipelineStepId, string> = {
  survey: 'Survey',
  mosaic: 'Mosaic',
  electrodes: 'Electrodes',
  regions: 'Regions',
};

// ⭐ R47 — WHAT THE STEP IS FOR, in three words. R3 strips explanations off every screen, and it is
// right to: but it left nothing at all saying what you are meant to DO here, so a first glance had
// to infer the job from the controls. A name is not a job — "Electrodes" does not tell you the
// screen numbers them. These are imperatives, one line, and they live in the nav rather than over
// the work, so the picture keeps the whole frame.
//
// ⛔ Not a `?`. A `Help` trigger is a <button>, and the step is a <button> — nesting them is
// invalid markup and unreachable by keyboard. The longer explanations stay in the rail panels.
const ACTIONS: Record<PipelineStepId, string> = {
  survey: 'check the video',
  mosaic: 'build the picture',
  electrodes: 'number the pads',
  regions: 'place your recordings',
};

export interface PipelineNavProps {
  current: PipelineStepId;
  /** How many steps (from the start) are reachable — a step at index ≥ this is LOCKED. */
  reachable: number;
  onStep: (id: PipelineStepId, locked: boolean) => void;
}

export function PipelineNav({ current, reachable, onStep }: PipelineNavProps) {
  const currentIndex = PIPELINE_STEPS.indexOf(current);
  return (
    <ol className={styles.nav} data-testid="pipeline-steps" aria-label="Pipeline steps">
      {PIPELINE_STEPS.map((id, i) => {
        const active = id === current;
        const done = currentIndex >= 0 && i < currentIndex;
        const locked = i >= reachable;
        return (
          <li key={id} className={styles.item}>
            <button
              type="button"
              data-testid={`pipeline-step-${id}`}
              data-locked={locked ? 'true' : 'false'}
              data-active={active ? 'true' : 'false'}
              aria-current={active ? 'step' : undefined}
              aria-disabled={locked || undefined}
              className={[
                styles.step,
                active ? styles.on : '',
                done ? styles.done : '',
                locked ? styles.locked : '',
              ]
                .filter(Boolean)
                .join(' ')}
              onClick={() => onStep(id, locked)}
            >
              <span className={styles.n} aria-hidden="true">
                {done ? '✓' : i + 1}
              </span>
              <span className={styles.text}>
                <span className={styles.label}>{LABELS[id]}</span>
                <span className={styles.action} data-testid={`pipeline-action-${id}`}>
                  {ACTIONS[id]}
                </span>
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
