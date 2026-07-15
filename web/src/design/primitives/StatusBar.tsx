import type { ReactNode } from 'react';
import { cx } from '../cx';
import styles from './StatusBar.module.css';

export interface StatusBarProps {
  children: ReactNode;
  className?: string;
}

/**
 * The instrument's footer readout shell. The Sweep fills it: `trial n` · a state badge · `pass n` ·
 * `top-left (x, y)` · a hint · `ms/frame · fps`. That perf pair (see PerfReadout) is contract, not
 * chrome — it must read ~6 ms (BEHAVIOUR R20); ~90 ms is the visible symptom of a per-frame rebake.
 */
export function StatusBar({ children, className }: StatusBarProps) {
  return (
    <div className={cx(styles.bar, className)} role="status">
      {children}
    </div>
  );
}

export interface StatusItemProps {
  /** A dim micro-cap label, e.g. `trial`. Optional — a badge item has none. */
  label?: ReactNode;
  children: ReactNode;
  /** Push this item and everything after it to the right edge. */
  push?: boolean;
  className?: string;
}

export function StatusItem({ label, children, push, className }: StatusItemProps) {
  return (
    <span className={cx(styles.item, push && styles.push, className)}>
      {label != null && <span className={styles.label}>{label}</span>}
      <span className={styles.value}>{children}</span>
    </span>
  );
}

export interface PerfReadoutProps {
  /** Milliseconds per frame. Must read ~6; the readout goes red past ~16 (a dropped 60 fps frame). */
  msPerFrame: number;
  fps: number;
  className?: string;
}

/** The live ms/frame · fps readout. Red when the frame budget is blown — the layered-canvas alarm. */
export function PerfReadout({ msPerFrame, fps, className }: PerfReadoutProps) {
  const hot = msPerFrame > 16;
  return (
    <span className={cx(styles.item, styles.push, className)}>
      <span className={cx(styles.value, styles.perf, hot && styles.perfHot)}>
        {msPerFrame.toFixed(1)} ms/frame
      </span>
      <span className={styles.value}>{Math.round(fps)} fps</span>
    </span>
  );
}
