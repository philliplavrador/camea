import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { cx } from '../design/cx';
import { ToastContext, type ToastApi, type ToastTone } from './toastContext';
import styles from './ToastProvider.module.css';

/**
 * Toasts — the shell's transient-message channel. It is feature-agnostic on purpose: the wizard uses
 * it for the locked-step nudge ("Finish the step before it first." — BEHAVIOUR R4.2) and the resume
 * confirmation ("Resumed — N anchored, M excluded." — R2.6); another feature will use it tomorrow.
 *
 * The context + `useToast` hook live in `toastContext.ts` so this file exports only a component.
 */
interface ToastRecord {
  id: number;
  message: string;
  tone: ToastTone;
}

let nextId = 1;
const DEFAULT_MS = 4200;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastRecord[]>([]);
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());

  const dismiss = useCallback((id: number) => {
    setToasts((list) => list.filter((t) => t.id !== id));
    const handle = timers.current.get(id);
    if (handle) {
      clearTimeout(handle);
      timers.current.delete(id);
    }
  }, []);

  const push = useCallback<ToastApi['push']>(
    (message, opts) => {
      const id = nextId++;
      const tone = opts?.tone ?? 'default';
      setToasts((list) => [...list, { id, message, tone }]);
      const handle = setTimeout(() => dismiss(id), opts?.durationMs ?? DEFAULT_MS);
      timers.current.set(id, handle);
    },
    [dismiss],
  );

  // Clear any pending timers on unmount so a late fire cannot touch a dead tree.
  useEffect(() => {
    const map = timers.current;
    return () => {
      for (const handle of map.values()) clearTimeout(handle);
      map.clear();
    };
  }, []);

  const api = useMemo<ToastApi>(() => ({ push }), [push]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      {/* role=status/aria-live: assistive tech announces it; data-testid the specs read (TID.toast). */}
      <div className={styles.region} data-testid="toast" role="status" aria-live="polite">
        {toasts.map((t) => (
          <button
            key={t.id}
            type="button"
            className={cx(styles.toast, styles[t.tone])}
            onClick={() => dismiss(t.id)}
            title="Dismiss"
          >
            {t.message}
          </button>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
