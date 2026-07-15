// THE WIZARD STEP HEADER — a PROGRESS INDICATOR, not a menu (BEHAVIOUR R4.2/R4.3).
//
// A step is LOCKED until everything before it is ready; clicking a locked step toasts and does NOT
// navigate (the feature owns the toast). This is the feature's own header rather than the design-system
// `Stepper` because the specs read a precise selector contract off each step — `wizard-step-<id>` with
// `data-locked` / `data-active` / `aria-current` (tests/e2e/pages.ts `TID.step`) — that the generic
// primitive does not (and should not) carry.

import styles from './WizardNav.module.css';
import type { MosaicStepId } from './steps/types';

const STEPS: Array<{ id: MosaicStepId; label: string }> = [
  { id: 'load', label: 'Load' },
  { id: 'range', label: 'Range' },
  { id: 'screen', label: 'Screen' },
  { id: 'place', label: 'Place' },
  { id: 'sweep', label: 'Sweep' },
  { id: 'mosaic', label: 'Mosaic' },
];

export interface WizardNavProps {
  current: MosaicStepId;
  /** How many steps (from the start) are reachable — a step at index ≥ `reachable` is LOCKED (R4.3). */
  reachable: number;
  /** Fired on any step click; the feature decides to navigate or to toast the locked nudge. */
  onStep: (id: MosaicStepId, locked: boolean) => void;
}

export function WizardNav({ current, reachable, onStep }: WizardNavProps) {
  const currentIndex = STEPS.findIndex((s) => s.id === current);
  return (
    <ol className={styles.nav} data-testid="wizard-steps" aria-label="Mosaic steps">
      {STEPS.map((step, i) => {
        const active = step.id === current;
        const done = currentIndex >= 0 && i < currentIndex;
        const locked = i >= reachable;
        return (
          <li key={step.id} className={styles.item}>
            <button
              type="button"
              data-testid={`wizard-step-${step.id}`}
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
              onClick={() => onStep(step.id, locked)}
            >
              <span className={styles.n} aria-hidden="true">
                {done ? '✓' : i + 1}
              </span>
              <span className={styles.label}>{step.label}</span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
