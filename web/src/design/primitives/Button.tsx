import { forwardRef } from 'react';
import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { cx } from '../cx';
import { Kbd } from './Kbd';
import styles from './Button.module.css';

type Variant = 'primary' | 'default' | 'ghost' | 'danger';
type Size = 'sm' | 'md' | 'lg';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  block?: boolean;
  /** A key hint rendered as an inset keycap — the sweep is keyboard-first, so a button shows its key. */
  kbd?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'default', size = 'md', block, kbd, className, children, type, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type ?? 'button'}
      className={cx(styles.btn, styles[variant], styles[size], block && styles.block, className)}
      {...rest}
    >
      {children}
      {kbd != null && (
        <Kbd tone={variant === 'primary' ? 'onAccent' : 'default'} className={styles.kbd}>
          {kbd}
        </Kbd>
      )}
    </button>
  );
});
