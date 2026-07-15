import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { api } from '../../api/client';
import type { components } from '../../api/schema';
import { Button } from '../../design/primitives/Button';
import { cx } from '../../design/cx';
import styles from './FolderPicker.module.css';

type FsListResponse = components['schemas']['FsListResponse'];

export interface FolderPickerProps {
  title: string;
  /** Copy on the confirm button — "Scan this folder" for a data root, "Use this folder" for a workspace. */
  confirmLabel: string;
  /** Where to start; omit to open at the drives / mount points. */
  initialPath?: string;
  onPick: (path: string) => void;
  onClose: () => void;
}

/**
 * A served folder picker. The native OS dialog does not exist headless (BEHAVIOUR R38 / the app runs
 * over VSCode remote), so the picker walks the filesystem through the backend: GET /api/fs/list
 * returns a folder's sub-directories, whether each is a dataset (recognised BY SHAPE, never by name),
 * and the drives to start from. Used for both the DATA ROOT and the WORKSPACE.
 */
export function FolderPicker({
  title,
  confirmLabel,
  initialPath,
  onPick,
  onClose,
}: FolderPickerProps) {
  const [path, setPath] = useState<string | undefined>(initialPath);
  const [data, setData] = useState<FsListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [failure, setFailure] = useState<string | null>(null);
  const reqSeq = useRef(0);
  const dialogRef = useRef<HTMLDivElement>(null);

  const navigate = useCallback((next: string | undefined) => {
    const seq = ++reqSeq.current;
    setLoading(true);
    setFailure(null);
    api
      .GET('/api/fs/list', { params: { query: { path: next } } })
      .then((r) => {
        if (seq !== reqSeq.current) return;
        if (r.error !== undefined || r.data === undefined) {
          setFailure(`could not read that folder (${r.response.status})`);
          return;
        }
        setData(r.data);
        setPath(r.data.path || undefined);
      })
      .catch((e: unknown) => {
        if (seq === reqSeq.current) setFailure(String(e));
      })
      .finally(() => {
        if (seq === reqSeq.current) setLoading(false);
      });
  }, []);

  useEffect(() => {
    navigate(initialPath);
    // initialPath is a one-shot starting point; re-navigation is user-driven from here on.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Escape closes; focus the dialog so the key lands and the picker is reachable by keyboard.
  useEffect(() => {
    dialogRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
      }
    };
    document.addEventListener('keydown', onKey, true);
    return () => document.removeEventListener('keydown', onKey, true);
  }, [onClose]);

  const atRoots = !path;
  const parent = data?.parent ?? undefined;
  const entries = atRoots
    ? (data?.roots ?? []).map((p) => ({ name: p, path: p, is_dataset: false, n_children: null }))
    : (data?.entries ?? []);

  return createPortal(
    <div className={styles.backdrop} onMouseDown={onClose}>
      <div
        ref={dialogRef}
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        data-testid="folder-picker"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className={styles.head}>
          <h2 className={styles.title}>{title}</h2>
          <button type="button" className={styles.close} aria-label="Close" onClick={onClose}>
            ✕
          </button>
        </div>

        <div className={styles.pathbar}>
          <button
            type="button"
            className={styles.up}
            onClick={() => navigate(parent)}
            disabled={atRoots}
            aria-label="Parent folder"
            title="Parent folder"
          >
            ↑
          </button>
          <span className={styles.path} data-testid="folder-picker-path">
            {path ?? 'Drives'}
          </span>
        </div>

        <div className={styles.list} role="listbox" aria-label="Folders">
          {loading && <div className={styles.state}>Reading…</div>}
          {!loading && failure && <div className={cx(styles.state, styles.error)}>{failure}</div>}
          {!loading && !failure && data?.error && (
            <div className={cx(styles.state, styles.error)}>{data.error}</div>
          )}
          {!loading && !failure && entries.length === 0 && !data?.error && (
            <div className={styles.state}>No sub-folders here.</div>
          )}
          {!loading &&
            !failure &&
            entries.map((entry) => (
              <button
                type="button"
                key={entry.path}
                className={styles.row}
                data-testid="folder-picker-entry"
                data-dataset={entry.is_dataset ? 'true' : 'false'}
                onClick={() => navigate(entry.path)}
                onDoubleClick={() => {
                  if (entry.is_dataset) onPick(entry.path);
                }}
              >
                <span className={styles.folderIcon} aria-hidden="true">
                  {entry.is_dataset ? '◆' : '▸'}
                </span>
                <span className={styles.rowName}>{entry.name}</span>
                {entry.is_dataset && <span className={styles.datasetTag}>dataset</span>}
                {entry.n_children != null && entry.n_children > 0 && (
                  <span className={styles.childCount}>{entry.n_children}</span>
                )}
              </button>
            ))}
        </div>

        <div className={styles.foot}>
          <span className={styles.footHint}>
            {atRoots ? 'Open a drive to begin.' : data?.is_dataset ? 'This folder is a dataset.' : ''}
          </span>
          <div className={styles.footActions}>
            <Button variant="ghost" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              data-testid="folder-picker-confirm"
              disabled={atRoots || !path}
              onClick={() => path && onPick(path)}
            >
              {confirmLabel}
            </Button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
