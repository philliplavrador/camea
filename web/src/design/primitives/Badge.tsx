import type { ReactNode } from 'react';
import { cx } from '../cx';
import styles from './Badge.module.css';

/** The tile states + a couple of facts the status bar and rails surface (BEHAVIOUR §4). */
export type BadgeState =
  | 'anchored'
  | 'unverified'
  | 'excluded'
  | 'unplaced'
  | 'blank'
  | 'diverted'
  | 'cursor'
  | 'gpu';

export interface BadgeProps {
  state: BadgeState;
  children: ReactNode;
  className?: string;
}

/** A small state pill with a leading status dot. The colour IS the meaning (§4 of the brief). */
export function Badge({ state, children, className }: BadgeProps) {
  return <span className={cx(styles.badge, styles[state], className)}>{children}</span>;
}
