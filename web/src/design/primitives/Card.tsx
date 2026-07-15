import type { HTMLAttributes, ReactNode } from 'react';
import { cx } from '../cx';
import styles from './Card.module.css';

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  /** Turns on hover/focus affordance for a clickable card (a dataset tile). */
  interactive?: boolean;
  /** Remove the default inner padding (for a card whose child manages its own edges). */
  flush?: boolean;
}

/** A raised container — a dataset card, a fact, a pane. The quiet ground the bright data sits on. */
export function Card({ children, interactive, flush, className, ...rest }: CardProps) {
  return (
    <div
      className={cx(styles.card, interactive && styles.interactive, flush && styles.flush, className)}
      {...rest}
    >
      {children}
    </div>
  );
}
