import type { ReactNode } from 'react';
import { cx } from '../cx';
import { Help } from './Help';
import styles from './Panel.module.css';

export interface PanelProps {
  /** A micro-cap section title (the etched legend). */
  title: ReactNode;
  /** Optional hover-`?` background for the section. */
  help?: string;
  /** Optional right-aligned controls in the header. */
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}

/** A rail section: an uppercase micro-cap header (with an optional `?`) over a body. The unit the
 *  Sweep's two rails are built from. */
export function Panel({ title, help, actions, children, className }: PanelProps) {
  return (
    <section className={cx(styles.panel, className)}>
      <h3 className={styles.header}>
        <span className={styles.title}>{title}</span>
        {help ? <Help body={help} /> : null}
        {actions != null && <span className={styles.actions}>{actions}</span>}
      </h3>
      <div className={styles.body}>{children}</div>
    </section>
  );
}
