import { createContext, useContext, useEffect, useRef } from 'react';

/**
 * The save-controller context + hooks, kept in their own module so `SaveController.tsx` exports only
 * components (React Fast Refresh). See `SaveController.tsx` for the behaviour and the R5 rationale.
 */
export type Saver = () => void | Promise<void>;

export interface SaveApi {
  /** A feature registers its save handler; the returned fn unregisters it (call in effect cleanup). */
  registerSaver: (saver: Saver) => () => void;
  /** Run the registered saver (no-op if none, or if a save is already in flight). */
  save: () => void;
  /** True while a save is running — the button shows it and guards a double-fire. */
  saving: boolean;
  /** True when a feature has registered a saver (there is something to save). */
  canSave: boolean;
}

export const SaveContext = createContext<SaveApi | null>(null);

/** Access the save controller. Throws if used outside <SaveControllerProvider>. */
export function useSaveController(): SaveApi {
  const ctx = useContext(SaveContext);
  if (!ctx) throw new Error('useSaveController must be used within <SaveControllerProvider>');
  return ctx;
}

/**
 * A feature calls this to plug its save handler into the shell. The latest `saver` closure is always
 * used (via a ref), so it may freely close over changing document state without re-registering.
 */
export function useRegisterSaver(saver: Saver): void {
  const { registerSaver } = useSaveController();
  const ref = useRef(saver);
  ref.current = saver;
  useEffect(() => registerSaver(() => ref.current()), [registerSaver]);
}
