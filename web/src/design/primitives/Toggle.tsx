import type { ReactNode } from 'react';
import { cx } from '../cx';
import { Kbd } from './Kbd';
import styles from './Toggle.module.css';

export interface ToggleProps {
  checked: boolean;
  onChange: (next: boolean) => void;
  children: ReactNode;
  /** An optional key hint (e.g. D for Difference). */
  kbd?: ReactNode;
  disabled?: boolean;
  className?: string;
}

/**
 * A pill switch — `use cache`, `outstanding only`, Difference `D`. A real `role="switch"` so the
 * on/off state is announced. This is a display/behaviour toggle, never a way to hide the exclusion
 * control (BEHAVIOUR I1: there is no exclusion toggle).
 */
export function Toggle({ checked, onChange, children, kbd, disabled, className }: ToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      className={cx(styles.toggle, checked && styles.on, className)}
      onClick={() => onChange(!checked)}
    >
      <span className={styles.dot} aria-hidden="true" />
      <span className={styles.label}>{children}</span>
      {kbd != null && <Kbd tone={checked ? 'onAccent' : 'default'}>{kbd}</Kbd>}
    </button>
  );
}
