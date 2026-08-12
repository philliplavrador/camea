// ─────────────────────────────────────────────────────────────────────────────────────────────
// THE FILES DRAWER (R47) — one door, opened when you ask for it.
//
// `OutputsPanel` used to be mounted underneath THREE steps of the video-mosaic pipeline, so the
// same list of files sat at the bottom of every screen you worked on, pushing the tools further
// from the picture. It is still the only way to browse a project's files (R44 — that ruling is
// untouched); it is now reached from one quiet button in the project header instead of appearing
// three times unasked.
//
// It wraps the panel — it does not fork it. Everything about listing, ticking, previewing and
// copying, and the verbatim refusals, stays exactly where it was.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { OutputsPanel } from './OutputsPanel';
import styles from './OutputsDrawer.module.css';

export interface OutputsDrawerProps {
  analysisId: string;
  /** Changes when a build finishes, so the list refreshes and previews bust their cache. */
  version?: string | null;
  open: boolean;
  onClose: () => void;
}

export function OutputsDrawer({ analysisId, version, open, onClose }: OutputsDrawerProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  // Where focus was before the drawer took it — a keyboard user must land back on the Files
  // button, not at the top of the document.
  const returnTo = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    returnTo.current = document.activeElement as HTMLElement | null;
    panelRef.current?.focus();
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      returnTo.current?.focus?.();
    };
  }, [open, onClose]);

  if (!open) return null;

  // Portalled to <body> for the same reason the tooltip is (R3.4): the pane it is opened from is
  // `overflow: hidden`, and a drawer nested inside one is clipped at its edge.
  return createPortal(
    <div className={styles.scrim} data-testid="outputs-scrim" onClick={onClose}>
      <div
        ref={panelRef}
        className={styles.drawer}
        data-testid="outputs-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="Project files"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        <div className={styles.head}>
          <span className={styles.title}>Files</span>
          <button
            type="button"
            className={styles.close}
            data-testid="outputs-close"
            aria-label="Close files"
            onClick={onClose}
          >
            ✕
          </button>
        </div>
        <div className={styles.body}>
          <OutputsPanel analysisId={analysisId} version={version} title="Files" />
        </div>
      </div>
    </div>,
    document.body,
  );
}
