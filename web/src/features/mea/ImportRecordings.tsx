// ─────────────────────────────────────────────────────────────────────────────────────────────
// IMPORT RECORDINGS — ⭐ **ONE COMPONENT, TWO MOUNT POINTS.**
//
// The new-project wizard's Files step and the in-project **+ Add recordings** button are the SAME
// tick-list. That is the point of this file, not a tidiness note: two implementations of "browse a
// folder, tick the recordings you mean" would drift within a week — one would grow the duration
// column, the other the refusal-by-name — and he would meet a different picker depending on which
// door he came through.
//
// ⚠️ **THE WIZARD MOUNT HAS NO PROJECT YET, AND THAT SHAPES THE WHOLE CONTRACT.** This component
// hands back **a list of chosen paths and nothing else** — no `analysis_id`, no POST of its own, no
// document, no create. The CALLER decides what to do with the list: the wizard passes it to
// `POST /api/mea/projects` as `paths`; the shelf passes it to `POST /{id}/recordings`. ⛔ A picker
// that created or mutated anything itself could not be mounted in the wizard at all.
//
// ⭐ **AND THE CALLER OWNS THE BUTTON.** This renders the folder bar, the list and its warnings; the
// action row is the caller's, because in the wizard that button says **Create** and belongs at the
// bottom of the step, and in the shelf it says **Add** and belongs in a modal footer. A confirm
// button in here would give the wizard two of them.
//
// ⭐ **TWO DOORS TO THE FILES, AND THEY ARE NOT EQUIVALENT.**
//   1. Camea's own picker — `FolderPicker` to choose a folder, then `GET /api/mea/browse` lists
//      every recording underneath with a tick box each. **This is the one he will actually use**:
//      he drives Camea over VSCode remote, where there is no desktop.
//   2. The native multi-select dialog, when Camea runs with `--window`. A shortcut, never the only
//      door — and when it is not there it says so in one line rather than appearing to do nothing.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { useCallback, useEffect, useState } from 'react';
import { browseRecordings, pickOpenFilePaths } from '../../api';
import type { MeaRecordingCandidate } from '../../api';
import { FolderPicker } from '../../core/picker/FolderPicker';
import { Button, LiveWarning } from '../../design';
import styles from './ImportRecordings.module.css';

/** A row he picked through the native dialog: an exact file, whose facts we have not read. */
function fromDialog(path: string): MeaRecordingCandidate {
  const parts = path.split('/');
  const name = parts.pop() ?? path;
  return {
    path,
    // MaxLab calls every recording `data.raw.h5`, so the run folder is the only part of the name
    // that identifies one.
    label: name === 'data.raw.h5' ? `${parts.pop() ?? ''}/${name}` : name,
    run_id: '',
    assay: '',
    bytes: 0,
    duration_s: null,
    n_channels: null,
    n_spikes: null,
    readable: true,
    problem: '',
  };
}

export interface ImportRecordingsProps {
  /**
   * ⭐ **THE WHOLE OUTPUT OF THIS COMPONENT.** Fires on every tick with the paths currently chosen.
   * The caller does the POST — see the header for why it cannot be done here.
   */
  onChange: (paths: string[]) => void;
  /** Disables the controls while the caller is mid-request. */
  busy?: boolean;
}

export function ImportRecordings({ onChange, busy = false }: ImportRecordingsProps) {
  const [folder, setFolder] = useState<string | null>(null);
  const [browsing, setBrowsing] = useState(false);
  // ⚠️ **TWO LISTS, NOT ONE FILTERED BY PATH PREFIX.** `here` is what the folder he is looking at
  // holds — it is REPLACED on every browse. `chosenElsewhere` is what he picked through the native
  // dialog, which has no folder behind it at all. Deriving "is this row in the current folder?"
  // from `path.startsWith(folder)` looked tidier and was wrong twice over: it assumes the server
  // echoes the path byte-for-byte as we sent it (it normalises), and it silently drops every row if
  // it does not.
  const [here, setHere] = useState<MeaRecordingCandidate[]>([]);
  const [chosenElsewhere, setChosenElsewhere] = useState<MeaRecordingCandidate[]>([]);
  const [ticked, setTicked] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [truncated, setTruncated] = useState(false);
  const [noDialog, setNoDialog] = useState(false);

  useEffect(() => {
    onChange(ticked);
  }, [ticked, onChange]);

  /** Read a folder. ⚠️ Ticks are KEPT: he may gather recordings from two folders in one go, and a
   *  picker that forgot his first choice the moment he looked in a second place would be unusable
   *  for exactly the session he is trying to set up. */
  const look = useCallback((path: string) => {
    setFolder(path);
    setLoading(true);
    setFailure(null);
    browseRecordings(path)
      .then((r) => {
        setHere(r.recordings ?? []);
        setTruncated(r.truncated ?? false);
        // The server's own answer for where it looked — resolved and normalised, which is what
        // should be on screen rather than whatever we happened to send it.
        if (r.path) setFolder(r.path);
      })
      .catch((e: unknown) => setFailure(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  const toggle = (path: string) =>
    setTicked((prev) => (prev.includes(path) ? prev.filter((p) => p !== path) : [...prev, path]));

  // Everything on screen: this folder's recordings, plus anything he picked through the native
  // dialog (which belongs to no folder we browsed).
  const shown = [...here, ...chosenElsewhere];
  const usable = shown.filter((r) => r.readable);
  const allTicked = usable.length > 0 && usable.every((r) => ticked.includes(r.path));

  const toggleAll = () =>
    setTicked((prev) => {
      const paths = usable.map((r) => r.path);
      return allTicked
        ? prev.filter((p) => !paths.includes(p))
        : [...prev, ...paths.filter((p) => !prev.includes(p))];
    });

  async function pickFiles(): Promise<void> {
    setNoDialog(false);
    let picked: string[] | null;
    try {
      picked = await pickOpenFilePaths({ title: 'Choose recordings', filters: ['HDF5 (*.h5)'] });
    } catch (e) {
      setFailure(e instanceof Error ? e.message : String(e));
      return;
    }
    if (picked === null) {
      setNoDialog(true); // no desktop in this mode — say so, do not sit there silently
      return;
    }
    if (picked.length === 0) return; // he cancelled
    setChosenElsewhere((prev) => {
      const known = new Set(prev.map((x) => x.path));
      return [...prev, ...picked.filter((p) => !known.has(p)).map(fromDialog)];
    });
    setTicked((prev) => [...prev, ...picked.filter((p) => !prev.includes(p))]);
  }

  // Anything ticked that is not on screen right now — a recording from a folder he has since
  // browsed away from. He must be able to see it is still on the list, or Create will surprise him.
  const onScreen = new Set([...here, ...chosenElsewhere].map((r) => r.path));
  const elsewhere = ticked.filter((p) => !onScreen.has(p));

  return (
    <div className={styles.import} data-testid="mea-import">
      <div className={styles.bar}>
        <Button
          variant="default"
          size="sm"
          disabled={busy}
          onClick={() => setBrowsing(true)}
          data-testid="mea-choose-folder"
        >
          Choose a folder
        </Button>
        <Button variant="ghost" size="sm" disabled={busy} onClick={() => void pickFiles()}
          data-testid="mea-pick-files">
          Pick files…
        </Button>
        <span className={styles.folder} data-testid="mea-import-folder">
          {folder ?? 'No folder chosen yet.'}
        </span>
      </div>

      {noDialog && (
        <p className={styles.note} data-testid="mea-no-dialog">
          This window has no file explorer. Use <b>Choose a folder</b> — it works the same.
        </p>
      )}

      <div className={styles.list} role="group" aria-label="Recordings">
        {loading && <p className={styles.state}>Looking…</p>}

        {!loading && failure && (
          <LiveWarning variant="loud" className={styles.state}>
            <span data-testid="mea-import-error">{failure}</span>
          </LiveWarning>
        )}

        {!loading && !failure && folder == null && shown.length === 0 && (
          <p className={styles.state} data-testid="mea-import-start">
            Choose the folder your MaxWell recordings are in. Camea lists every recording under it.
          </p>
        )}

        {!loading && !failure && folder != null && shown.length === 0 && (
          <p className={styles.state} data-testid="mea-import-none">
            No recordings in this folder. Try the folder above it.
          </p>
        )}

        {!loading && !failure && shown.length > 0 && (
          <>
            <label className={styles.all}>
              <input
                type="checkbox"
                checked={allTicked}
                disabled={busy || usable.length === 0}
                onChange={toggleAll}
                data-testid="mea-tick-all"
              />
              <span>
                {shown.length} recording{shown.length === 1 ? '' : 's'}
              </span>
            </label>
            {shown.map((r) => (
              <label
                key={r.path}
                className={styles.row}
                data-testid="mea-import-row"
                data-readable={r.readable ? 'true' : 'false'}
                data-path={r.path}
              >
                <input
                  type="checkbox"
                  checked={ticked.includes(r.path)}
                  disabled={busy || !r.readable}
                  onChange={() => toggle(r.path)}
                  data-testid="mea-import-tick"
                />
                <span className={styles.rowLabel}>{r.label || r.path}</span>
                {r.readable ? (
                  <span className={styles.facts}>
                    {[
                      r.duration_s != null ? `${formatSeconds(r.duration_s)}` : null,
                      r.n_channels != null ? `${r.n_channels} channels` : null,
                      r.n_spikes != null ? `${r.n_spikes.toLocaleString()} spikes` : null,
                      r.bytes ? formatBytes(r.bytes) : null,
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </span>
                ) : (
                  // ⛔ **REFUSED BY NAME, ON THE LIST** — never silently dropped. A file missing
                  // from the list makes the folder look emptier than it is, and the one thing worse
                  // than a refusal is one he never saw.
                  <span className={styles.refused} data-testid="mea-import-refused">
                    not a MaxLab recording
                  </span>
                )}
              </label>
            ))}
          </>
        )}

        {truncated && (
          <p className={styles.note}>
            Only the first recordings in this folder are listed. Choose a folder further in.
          </p>
        )}
      </div>

      {elsewhere.length > 0 && (
        <p className={styles.note} data-testid="mea-import-elsewhere">
          {elsewhere.length} more chosen from other folders.
        </p>
      )}

      {browsing && (
        <FolderPicker
          title="Where are your recordings?"
          confirmLabel="Look in this folder"
          initialPath={folder ?? undefined}
          onPick={(p) => {
            setBrowsing(false);
            look(p);
          }}
          onClose={() => setBrowsing(false)}
        />
      )}
    </div>
  );
}

function formatSeconds(s: number): string {
  if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)} s`;
  const m = Math.floor(s / 60);
  return `${m}m ${Math.round(s - m * 60)}s`;
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} kB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}
