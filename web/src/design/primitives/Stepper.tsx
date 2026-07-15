import { cx } from '../cx';
import type { Step } from './steps';
import styles from './Stepper.module.css';

export interface StepperProps {
  steps: Step[];
  /** The active step's id. */
  current: string;
  /**
   * How many steps (from the start) are reachable. A step at index ≥ `reachable` is LOCKED. This is
   * the gate, not a menu (BEHAVIOUR R4.2/R4.3): e.g. with a session but nothing placed, Sweep is
   * reachable and Mosaic is locked → `reachable = 5`.
   */
  reachable: number;
  /** Fired on any step click, locked or not — a locked click should toast, not navigate (R4.2). */
  onStepClick?: (id: string, locked: boolean) => void;
  className?: string;
}

/**
 * The six-step header — a PROGRESS INDICATOR, not a menu. A step is locked until everything before it
 * is ready; clicking a locked step does nothing but toast (the feature owns the toast). The numbers
 * are earned: this is a real sequence (you cannot Sweep before you Load).
 */
export function Stepper({ steps, current, reachable, onStepClick, className }: StepperProps) {
  const currentIndex = steps.findIndex((s) => s.id === current);
  return (
    <ol className={cx(styles.steps, className)} aria-label="Progress">
      {steps.map((step, i) => {
        const active = i === currentIndex;
        const done = currentIndex >= 0 && i < currentIndex;
        const locked = i >= reachable;
        return (
          <li key={step.id} className={styles.item}>
            <button
              type="button"
              className={cx(styles.step, active && styles.on, done && styles.done, locked && styles.locked)}
              aria-current={active ? 'step' : undefined}
              aria-disabled={locked || undefined}
              onClick={() => onStepClick?.(step.id, locked)}
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
