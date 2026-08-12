import { forwardRef } from 'react';
import type { AnchorHTMLAttributes } from 'react';
import { cx } from '../cx';
import styles from './Button.module.css';

type Variant = 'primary' | 'default' | 'ghost' | 'danger';
type Size = 'sm' | 'md' | 'lg';

export interface ButtonLinkProps extends AnchorHTMLAttributes<HTMLAnchorElement> {
  variant?: Variant;
  size?: Size;
  block?: boolean;
}

/**
 * A link that looks like a `Button` — same CSS module, so the two can never drift apart.
 *
 * It exists for the one thing a `<button>` cannot do: `<a download>`, which hands the bytes to the
 * browser's downloader. That matters for a 40 Mpx mosaic — the file streams straight to disk and is
 * never decoded, so the cost is the same whatever the canvas size.
 */
export const ButtonLink = forwardRef<HTMLAnchorElement, ButtonLinkProps>(function ButtonLink(
  { variant = 'default', size = 'md', block, className, children, ...rest },
  ref,
) {
  return (
    <a
      ref={ref}
      className={cx(styles.btn, styles[variant], styles[size], block && styles.block, className)}
      {...rest}
    >
      {children}
    </a>
  );
});
