import type { ReactNode } from 'react';
import { cx } from '../cx';
import styles from './Kbd.module.css';

export interface KbdProps {
  children: ReactNode;
  /** A wider cap for a word key (Space, Shift). */
  wide?: boolean;
  /** `onAccent` = drawn on a filled (accent) surface, e.g. inside a primary Button. */
  tone?: 'default' | 'onAccent';
  className?: string;
}

/** A keycap. The sweep IS the keyboard — the keys are shown, not hidden (BEHAVIOUR §3.3). */
export function Kbd({ children, wide, tone = 'default', className }: KbdProps) {
  return (
    <kbd className={cx(styles.kbd, wide && styles.wide, tone === 'onAccent' && styles.onAccent, className)}>
      {children}
    </kbd>
  );
}
