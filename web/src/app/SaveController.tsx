import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Button } from '../design/primitives/Button';
import { SaveContext, useSaveController, type SaveApi, type Saver } from './saveContext';

/**
 * SAVE, reachable from EVERY screen (BEHAVIOUR R5). Since R2 the project file is the app's ONLY
 * memory, so the one control that makes a session resumable must never be buried behind a step.
 *
 * The split: the SHELL owns the top-bar button and the global `Ctrl/⌘+S` binding; the FEATURE owns
 * the document, so it registers WHAT to save via `useRegisterSaver` (in `saveContext.ts`). This keeps
 * the shell feature-agnostic (it knows nothing about tiles/anchors) and gives R5.2 its single
 * dispatch point.
 *
 * 🔴 ONE DISPATCH POINT. The feature must NOT bind its own `Ctrl+S` — the sweep's key handler already
 * lets Ctrl/⌘ combos fall through (BEHAVIOUR §3.1), and a second binding would save twice. The shell
 * is the one place `Ctrl+S` is handled, above any feature key gate (R5.2).
 */
export function SaveControllerProvider({ children }: { children: ReactNode }) {
  const saverRef = useRef<Saver | null>(null);
  const savingRef = useRef(false);
  const [hasSaver, setHasSaver] = useState(false);
  const [saving, setSaving] = useState(false);

  const registerSaver = useCallback((saver: Saver) => {
    saverRef.current = saver;
    setHasSaver(true);
    return () => {
      // Only clear if we are still the registered saver (guards against out-of-order cleanup).
      if (saverRef.current === saver) {
        saverRef.current = null;
        setHasSaver(false);
      }
    };
  }, []);

  const save = useCallback(async () => {
    const saver = saverRef.current;
    if (!saver || savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    try {
      await saver();
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }, []);

  // Ctrl/⌘+S from ANY screen (R5.2). Handled on window, above every feature key gate.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === 's') {
        e.preventDefault(); // stop the browser's own "save page" dialog
        void save();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [save]);

  const api = useMemo<SaveApi>(
    () => ({ registerSaver, save: () => void save(), saving, canSave: hasSaver }),
    [registerSaver, save, saving, hasSaver],
  );

  return <SaveContext.Provider value={api}>{children}</SaveContext.Provider>;
}

/** The top-bar Save button (TID.saveProject). Delegates to whatever saver the open feature registered. */
export function SaveButton() {
  const { save, saving } = useSaveController();
  return (
    <Button
      data-testid="save-project"
      size="sm"
      kbd="Ctrl S"
      onClick={save}
      disabled={saving}
      title="Save the project file (Ctrl+S)"
    >
      {saving ? 'Saving…' : 'Save…'}
    </Button>
  );
}
