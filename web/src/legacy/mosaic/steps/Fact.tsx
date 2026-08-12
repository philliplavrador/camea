import type { ReactNode } from 'react';
import { Help, cx } from '../../../design';
import styles from './Fact.module.css';

/**
 * The `.facts` strip and its cells (BEHAVIOUR R4.6 / §2). NUMBERS ONLY — the label is a small, dim,
 * upper-cased micro-cap and the value is the bright mono figure (the instrument readout inversion,
 * DESIGN_BRIEF §2). Every explanation is a hover `?`, never a paragraph on the page (I2/R3).
 */
export function FactsStrip({
  children,
  testid,
  className,
}: {
  children: ReactNode;
  testid?: string;
  className?: string;
}) {
  return (
    <div className={cx(styles.facts, className)} data-testid={testid}>
      {children}
    </div>
  );
}

export function Fact({
  label,
  help,
  value,
  sub,
  valueTestid,
  wide,
  tone,
}: {
  label: ReactNode;
  /** The measured `why` etc. — text-only, empty hides the `?` (R3.3/R3.7). */
  help?: string;
  value: ReactNode;
  sub?: ReactNode;
  valueTestid?: string;
  wide?: boolean;
  /** Colour the value as a live measurement (`warn` = outstanding). */
  tone?: 'warn';
}) {
  return (
    <div className={cx(styles.fact, wide && styles.wide)}>
      <div className={styles.k}>
        {label}
        {help ? <Help body={help} /> : null}
      </div>
      <div className={cx(styles.v, tone === 'warn' && styles.warn)} data-testid={valueTestid}>
        {value}
      </div>
      {sub != null && <div className={styles.sub}>{sub}</div>}
    </div>
  );
}
