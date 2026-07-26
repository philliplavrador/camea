// THE SAVE INDICATOR — the quiet "Saved / Saving… / Couldn't save" status that replaces the manual
// Save button (2026-07-24 project-manager reframe). Auto-save IS the durable save now, so there is no
// button to press — this just reflects the document store's `autosave` state.
//
// 🔴 A FAILURE STAYS LOUD (W4): 'failed' renders a prominent warning, never a quiet dash. A project
// that cannot save must never look saved. When no document is open it renders nothing.

import { useDocument } from '../store/documentStore';
import styles from './SaveIndicator.module.css';

function agoText(iso: string | null): string {
  if (!iso) return 'Saved';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return 'Saved';
  const s = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (s < 5) return 'Saved';
  if (s < 60) return `Saved ${s}s ago`;
  const m = Math.floor(s / 60);
  return `Saved ${m}m ago`;
}

export function SaveIndicator() {
  const doc = useDocument((s) => s.doc);
  const autosave = useDocument((s) => s.autosave);
  const dirty = useDocument((s) => s.dirty);

  if (!doc) return null;

  if (autosave.state === 'failed') {
    return (
      <span className={styles.failed} data-testid="save-indicator" data-state="failed" role="status">
        ⚠ Couldn't save{autosave.message ? ` — ${autosave.message}` : ''}
      </span>
    );
  }

  const saving = autosave.state === 'saving' || autosave.state === 'pending' || dirty;
  return (
    <span
      className={styles.ok}
      data-testid="save-indicator"
      data-state={saving ? 'saving' : 'saved'}
      role="status"
    >
      <span className={styles.dot} data-saving={saving || undefined} />
      {saving ? 'Saving…' : agoText(autosave.at)}
    </span>
  );
}
