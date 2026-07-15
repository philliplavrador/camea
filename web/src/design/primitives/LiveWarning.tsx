import type { ReactNode } from 'react';
import { cx } from '../cx';
import { Help } from './Help';
import styles from './LiveWarning.module.css';

export type LiveWarningVariant = 'warn' | 'loud' | 'info';

export interface LiveWarningProps {
  /**
   * The warning prose. It may contain inline `<b>`/`<strong>`. It lays out as ONE flowing paragraph
   * (BEHAVIOUR R1): the container is `display: block`, NEVER flex — flex made every `<b>` and every
   * bare text node its own boxed column with a gutter. If a warning ever needs an icon, wrap the text
   * in a span; do not make this container flex.
   */
  children: ReactNode;
  /** `warn` (amber, default) · `loud` (red, pulses — a thin margin) · `info` (blue). */
  variant?: LiveWarningVariant;
  /**
   * Optional background that goes behind a `?` ON the warning. The BACKGROUND may hide; the FACT that
   * the warning is firing may not (BEHAVIOUR §5). The `?` is inline at the end — it does not make the
   * container flex.
   */
  help?: string;
  /** Defaults to `alert` for `loud`, `status` otherwise. */
  role?: 'status' | 'alert';
  className?: string;
}

/**
 * A LIVE WARNING ABOUT CURRENT STATE — the one exception to "everything explanatory hides behind a
 * `?`" (BEHAVIOUR R3.8, §5). It fires only when something is wrong right now and it changes what the
 * user would do (a stale build, a thin margin, a diverted tile, no anchors left, a failed autosave,
 * the provenance stamp). It stays on the page; it must never be tidied into a tooltip.
 */
export function LiveWarning({ children, variant = 'warn', help, role, className }: LiveWarningProps) {
  const resolvedRole = role ?? (variant === 'loud' ? 'alert' : 'status');
  return (
    <div className={cx(styles.warn, styles[variant], className)} role={resolvedRole}>
      {children}
      {help ? <Help body={help} label="Why this warning" /> : null}
    </div>
  );
}
