import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { cx } from '../cx';
import styles from './Help.module.css';

export interface HelpProps {
  /**
   * The tooltip body. TEXT ONLY — it may be a backend-measured `why` string and a `"` in it must
   * not break out into markup (BEHAVIOUR R3.7). `\n` renders as a real line break. An empty or
   * whitespace-only body HIDES the `?` entirely, so a `?` never promises what it cannot give (R3.3).
   */
  body: string;
  /** Accessible name for the trigger. Defaults to "More information". */
  label?: string;
  className?: string;
}

const TIP_MAX_W = 340;

/**
 * The hover-`?`. THE app's one explanation surface (BEHAVIOUR R3): everything that used to be a
 * paragraph on the page lives in one of these. It is NOT a live warning — a warning about current
 * state stays on the page (R3.8, see LiveWarning).
 *
 * The tooltip is portalled to <body> and positioned `fixed`, by necessity: every rail and pane is
 * `overflow: auto`, and a bubble nested inside one is clipped at its edge (R3.4). It hides on blur,
 * on Escape, and on scroll — the scroll listener is in the CAPTURE phase, because a scroll inside an
 * `overflow:auto` pane does not bubble to window (R3.5).
 */
export function Help({ body, label = 'More information', className }: HelpProps) {
  const trimmed = body.trim();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number }>({ top: 0, left: 0 });
  const tipId = useId();

  const place = useCallback(() => {
    const el = triggerRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const left = Math.max(8, Math.min(r.left, window.innerWidth - TIP_MAX_W - 8));
    setPos({ top: r.bottom + 6, left });
  }, []);

  const show = useCallback(() => {
    place();
    setOpen(true);
  }, [place]);

  const hide = useCallback(() => setOpen(false), []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') hide();
    };
    // capture phase: a scroll inside an overflow:auto pane never reaches window on the bubble path.
    window.addEventListener('scroll', hide, true);
    window.addEventListener('resize', hide);
    document.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('scroll', hide, true);
      window.removeEventListener('resize', hide);
      document.removeEventListener('keydown', onKey);
    };
  }, [open, hide]);

  // A `?` with an empty body hides itself (R3.3).
  if (!trimmed) return null;

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        data-testid="help"
        tabIndex={0}
        aria-label={label}
        aria-describedby={open ? tipId : undefined}
        className={cx(styles.help, className)}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
      />
      {open &&
        createPortal(
          <div
            id={tipId}
            role="tooltip"
            data-testid="help-tooltip"
            className={styles.tip}
            style={{ top: pos.top, left: pos.left }}
          >
            {trimmed}
          </div>,
          document.body,
        )}
    </>
  );
}
