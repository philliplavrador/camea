// ─────────────────────────────────────────────────────────────────────────────────────────────
// PASTE A PATH — the fast way to point Camea at a folder (2026-07-24).
//
// The tree-walking modal (FolderPicker) is a fine fallback but a slow primary: the user usually
// ALREADY KNOWS the path and just wants to paste it. So: one monospace box, Enter, done.
//   · paste tolerance — Windows backslashes and Explorer's "Copy as path" quotes are normalised
//   · shell-style completion — typing `D:/Proj` lists the matching sub-folders (GET /api/fs/list),
//     Tab/Enter completes, and a folder that IS a dataset is marked ◆
//   · quick-start chips — the drives + home the backend reports, plus the paths already chosen
//
// ⛔ NO DATASET KNOWLEDGE (HARD RULE 3). Every suggestion and every chip is read off the backend;
// nothing here names a folder, a dataset or a number. `is_dataset` is the backend's shape test
// (a log.txt + one NNN.xml), never a name match.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { api } from '../../api/client';
import type { components } from '../../api/schema';
import { Button } from '../../design/primitives/Button';
import { cx } from '../../design/cx';
import { normalisePath, splitPath, forSubmit, shortPath } from './pathText';
import styles from './PathField.module.css';

type FsEntry = components['schemas']['FsEntry'];

const MAX_SUGGESTIONS = 8;
const DEBOUNCE_MS = 120;

export interface PathFieldProps {
  /** Commit the path. Throw (or reject) to show the message inline under the box. */
  onSubmit: (path: string) => Promise<void> | void;
  /** Copy on the commit button — "Add root", "Use this folder". */
  submitLabel: string;
  placeholder?: string;
  /** Paths already chosen. Rendered as chips; clicking one loads it back into the box. */
  known?: readonly string[];
  knownLabel?: string;
  /** Opens the tree-walking FolderPicker. Omit to hide the fallback link. */
  onBrowse?: () => void;
  'data-testid'?: string;
}

export function PathField({
  onSubmit,
  submitLabel,
  placeholder = 'paste a folder path…',
  known = [],
  knownLabel = 'Yours',
  onBrowse,
  'data-testid': testid = 'path-field',
}: PathFieldProps) {
  const [text, setText] = useState('');
  const [entries, setEntries] = useState<FsEntry[]>([]);
  const [starts, setStarts] = useState<string[]>([]); // drives + home, from the backend
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const inputRef = useRef<HTMLInputElement>(null);
  const cache = useRef(new Map<string, FsEntry[]>());
  const reqSeq = useRef(0);

  const { dir, frag } = useMemo(() => splitPath(normalisePath(text)), [text]);

  // The drives / home to start from. One fetch; they do not change while the app is open.
  useEffect(() => {
    let live = true;
    api
      .GET('/api/fs/list', { params: { query: {} } })
      .then((r) => {
        if (live && r.data) setStarts(r.data.roots ?? []);
      })
      .catch(() => {
        /* the chips are a convenience; their absence is not an error worth showing */
      });
    return () => {
      live = false;
    };
  }, []);

  // List whatever folder the text currently points into, debounced. Cached: walking back up a path
  // must not re-hit the disk for a directory we already listed.
  useEffect(() => {
    const cached = cache.current.get(dir);
    if (cached) {
      setEntries(cached);
      return;
    }
    const seq = ++reqSeq.current;
    const t = setTimeout(() => {
      api
        .GET('/api/fs/list', { params: { query: dir ? { path: dir } : {} } })
        .then((r) => {
          if (seq !== reqSeq.current) return;
          const list = r.data
            ? dir
              ? (r.data.entries ?? [])
              : (r.data.roots ?? []).map((p) => ({
                  name: p,
                  path: p,
                  is_dataset: false,
                  n_children: null,
                }))
            : [];
          cache.current.set(dir, list);
          setEntries(list);
        })
        .catch(() => {
          if (seq === reqSeq.current) setEntries([]);
        });
    }, DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [dir]);

  const suggestions = useMemo(() => {
    const f = frag.toLowerCase();
    const hit = entries.filter((e) => e.name.toLowerCase().startsWith(f));
    // An exact, complete match is not a suggestion — it is where you already are.
    const only = hit.length === 1 && hit[0].name.toLowerCase() === f;
    return only ? [] : hit.slice(0, MAX_SUGGESTIONS);
  }, [entries, frag]);

  // The typed path itself, if the backend says that folder is a dataset — "you can stop here".
  const typedIsDataset = useMemo(
    () => entries.some((e) => e.name.toLowerCase() === frag.toLowerCase() && e.is_dataset),
    [entries, frag],
  );

  const complete = useCallback(
    (entry: FsEntry) => {
      setText(`${entry.path.replace(/\/$/, '')}/`);
      setActive(-1);
      setOpen(true);
      inputRef.current?.focus();
    },
    [],
  );

  const submit = useCallback(async () => {
    const path = forSubmit(text);
    if (!path || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onSubmit(path);
      setText('');
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [text, busy, onSubmit]);

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    const n = suggestions.length;
    if (e.key === 'ArrowDown' && n) {
      e.preventDefault();
      setOpen(true);
      setActive((i) => (i + 1) % n);
    } else if (e.key === 'ArrowUp' && n) {
      e.preventDefault();
      setOpen(true);
      setActive((i) => (i <= 0 ? n - 1 : i - 1));
    } else if (e.key === 'Tab' && n && open) {
      e.preventDefault();
      complete(suggestions[Math.max(active, 0)]);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (open && active >= 0 && n) complete(suggestions[active]);
      else void submit();
    } else if (e.key === 'Escape' && open) {
      // Only swallow Escape when there is a menu to close — never steal it from the screen behind.
      e.preventDefault();
      e.stopPropagation();
      setOpen(false);
      setActive(-1);
    }
  }

  const chips = useMemo(() => {
    const seen = new Set(known.map((k) => k.toLowerCase()));
    return starts.filter((s) => !seen.has(s.toLowerCase()));
  }, [starts, known]);

  function load(path: string) {
    setText(path.endsWith('/') ? path : `${path}/`);
    setError(null);
    setOpen(true);
    setActive(-1);
    inputRef.current?.focus();
  }

  return (
    <div className={styles.field} data-testid={testid}>
      <div className={styles.row}>
        <div className={styles.inputWrap}>
          <input
            ref={inputRef}
            className={styles.input}
            type="text"
            spellCheck={false}
            autoComplete="off"
            role="combobox"
            aria-expanded={open && suggestions.length > 0}
            aria-label="Folder path"
            placeholder={placeholder}
            data-testid="path-input"
            value={text}
            onChange={(e) => {
              setText(normalisePath(e.target.value));
              setError(null);
              setActive(-1);
              setOpen(true);
            }}
            onFocus={() => setOpen(true)}
            onBlur={() => window.setTimeout(() => setOpen(false), 120)}
            onKeyDown={onKeyDown}
          />
          {open && suggestions.length > 0 && (
            <ul className={styles.menu} role="listbox" aria-label="Matching folders">
              {suggestions.map((s, i) => (
                <li key={s.path}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={i === active}
                    className={cx(styles.option, i === active && styles.optionActive)}
                    data-testid="path-suggestion"
                    // mousedown, not click: blur would tear the menu down first.
                    onMouseDown={(e) => {
                      e.preventDefault();
                      complete(s);
                    }}
                    onMouseEnter={() => setActive(i)}
                  >
                    <span className={styles.optionIcon} aria-hidden="true">
                      {s.is_dataset ? '◆' : '▸'}
                    </span>
                    <span className={styles.optionName}>{s.name}</span>
                    {s.is_dataset && <span className={styles.optionTag}>dataset</span>}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <Button
          variant="primary"
          size="sm"
          disabled={busy || !text.trim()}
          onClick={() => void submit()}
          data-testid="path-submit"
        >
          {busy ? 'Working…' : submitLabel}
        </Button>

        {onBrowse && (
          <Button variant="ghost" size="sm" onClick={onBrowse} data-testid="path-browse">
            Browse…
          </Button>
        )}
      </div>

      {error && (
        <div className={styles.error} role="alert" data-testid="path-error">
          {error}
        </div>
      )}
      {!error && typedIsDataset && (
        <div className={styles.ok}>◆ that folder is a dataset — press Enter to add it.</div>
      )}

      {(known.length > 0 || chips.length > 0) && (
        <div className={styles.chips}>
          {known.length > 0 && (
            <>
              <span className={styles.chipLabel}>{knownLabel}</span>
              {known.map((k) => (
                <button
                  type="button"
                  key={k}
                  className={cx(styles.chip, styles.chipKnown)}
                  title={k}
                  data-testid="path-known"
                  onClick={() => load(k)}
                >
                  {shortPath(k)}
                </button>
              ))}
            </>
          )}
          {chips.length > 0 && (
            <>
              <span className={styles.chipLabel}>Start from</span>
              {chips.map((c) => (
                <button
                  type="button"
                  key={c}
                  className={styles.chip}
                  title={c}
                  data-testid="path-start"
                  onClick={() => load(c)}
                >
                  {c}
                </button>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}
