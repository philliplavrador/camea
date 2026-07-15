import { createContext, useContext } from 'react';

/**
 * The toast context + hook, kept in their own module so `ToastProvider.tsx` exports only a component
 * (React Fast Refresh wants component-only files). See `ToastProvider.tsx` for the behaviour.
 *
 * ⚠️ A toast is NOT a live warning. A warning about CURRENT STATE stays on the page (BEHAVIOUR R3.8 /
 * §5, the `LiveWarning` primitive). A toast is a passing acknowledgement that self-dismisses.
 */
export type ToastTone = 'default' | 'danger' | 'good';

export interface ToastApi {
  /** Show a transient message. Returns nothing — a toast is fire-and-forget. */
  push: (message: string, opts?: { tone?: ToastTone; durationMs?: number }) => void;
}

export const ToastContext = createContext<ToastApi | null>(null);

/** The one message channel every screen shares. Throws if used outside <ToastProvider>. */
export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within <ToastProvider>');
  return ctx;
}
