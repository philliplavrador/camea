import { forwardRef } from 'react';
import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { cx } from '../cx';
import styles from './IconButton.module.css';

type Variant = 'default' | 'ghost' | 'danger';
type Size = 'sm' | 'md';

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Required — an icon button has no text, so it must name itself for assistive tech. */
  'aria-label': string;
  variant?: Variant;
  size?: Size;
  children: ReactNode;
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { variant = 'default', size = 'md', className, children, type, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type ?? 'button'}
      className={cx(styles.icon, styles[variant], styles[size], className)}
      {...rest}
    >
      {children}
    </button>
  );
});
