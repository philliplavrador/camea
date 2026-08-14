// ─────────────────────────────────────────────────────────────────────────────────────────────
// THE SHELF — what an Analyze MEA project holds, one row per recording.
//
// ⛔ **A SHELF, NOT A PIPELINE.** The video feature is a pipeline — survey → mosaic → electrodes →
// regions, each step locked until the one before it is done (R46.1). This is not: the order you
// look at things in is yours. ⛔ Do not import `PipelineNav`.
//
// ⭐ **EVERY NUMBER ON A ROW IS READ OFF THE FILE, EVERY TIME IT IS ASKED FOR.** Nothing about what
// is *in* a recording is stored (I1); the document keeps a path, an id and where the bytes
// currently are. So a row that has lost its file shows **no numbers at all** rather than zeros — a
// row of zeros reads as a silent chip, which is a lie about his data.
//
// 🔴 **TWO LIVE WARNINGS, AND NEITHER GOES BEHIND THE `?`.** 001 moved a line of prose behind the
// `?` on his instruction, and it would be easy to read that as *"explanations go behind the `?` on
// this screen"*. It is the opposite instruction. What went behind the `?` was "this part of Camea
// is not written yet" — a fact about the **app**. These are facts about **his data, right now**:
// his recording is not where he left it. That is R3's standing exception (W1–W11), and a fact he
// must not be able to miss cannot live somewhere he has to hover to find.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { useCallback, useEffect, useRef, useState } from 'react';
import { addRecordings, listRecordings, removeRecording } from '../../api';
import type { MeaShelfEntry } from '../../api';
import { useToast } from '../../app';
import { Button, LiveWarning } from '../../design';
import { ImportRecordings } from './ImportRecordings';
import styles from './RecordingShelf.module.css';

/** How often to re-read the shelf while a copy is running. Off entirely when nothing is copying —
 *  a screen that polls forever is a screen that keeps a laptop's fan on for no reason. */
const COPY_POLL_MS = 700;

/**
 * The four words a row can say about where Camea is reading it from.
 *
 * ⚠️ **Plain English, not the wire's vocabulary.** The document calls these `referenced` /
 * `copying` / `stored` / `failed`; he is a biologist, and *"referenced"* is a word about our
 * implementation rather than about his recording. What he needs to know is which disk it is coming
 * off and whether that is settled yet.
 */
function copyWords(r: MeaShelfEntry): { text: string; tone: 'ok' | 'busy' | 'warn' } {
  switch (r.copy_state) {
    case 'stored':
      return { text: 'In the project', tone: 'ok' };
    case 'copying':
      return { text: `Copying… ${Math.round(r.copy_pct ?? 0)}%`, tone: 'busy' };
    case 'failed':
      return { text: 'Still in your folder — the copy did not finish', tone: 'warn' };
    default:
      return { text: 'In your folder — copying', tone: 'busy' };
  }
}

export interface RecordingShelfProps {
  analysisId: string;
}

export function RecordingShelf({ analysisId }: RecordingShelfProps) {
  const toast = useToast();
  const [rows, setRows] = useState<MeaShelfEntry[] | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState<MeaShelfEntry | null>(null);
  const alive = useRef(true);

  /**
   * Re-read the shelf. -> the rows, or **`null` when the read itself failed**.
   *
   * ⚠️ **`null` and `[]` are different answers and the difference is load-bearing**: `[]` is an
   * empty shelf, `null` is "Camea could not find out". `askThenRemove` below is the reason — it has
   * to decide whether a remove is the irreversible kind, and a failed read that came back as `[]`
   * would fall through to stale data on exactly the click that cannot be undone.
   */
  const refresh = useCallback(async (): Promise<MeaShelfEntry[] | null> => {
    try {
      const shelf = await listRecordings(analysisId);
      if (alive.current) {
        setRows(shelf.recordings ?? []);
        setFailure(null);
      }
      return shelf.recordings ?? [];
    } catch (e) {
      if (alive.current) setFailure(e instanceof Error ? e.message : String(e));
      return null;
    }
  }, [analysisId]);

  useEffect(() => {
    alive.current = true;
    void refresh();
    return () => {
      alive.current = false;
    };
  }, [refresh]);

  // Poll ONLY while something is copying. `copy_state` is derived server-side from the disk and the
  // job registry, so this stops by itself the moment the last copy lands — including after a
  // restart, where the job is gone and the answer becomes "in your folder" rather than a bar that
  // never fills.
  const copying = (rows ?? []).some((r) => r.copy_state === 'copying');
  useEffect(() => {
    if (!copying) return;
    const t = setInterval(() => void refresh(), COPY_POLL_MS);
    return () => clearInterval(t);
  }, [copying, refresh]);

  async function doAdd(): Promise<void> {
    if (busy || picked.length === 0) return;
    setBusy(true);
    try {
      const shelf = await addRecordings(analysisId, picked);
      setRows(shelf.recordings ?? []);
      setAdding(false);
      setPicked([]);
    } catch (e) {
      // ⛔ The refusal NAMES the file, and it is the backend's sentence verbatim — this screen does
      // not paraphrase a reason it did not work out.
      toast.push(e instanceof Error ? e.message : String(e), { tone: 'danger' });
    } finally {
      setBusy(false);
    }
  }

  /**
   * ⭐ **REMOVE IS INSTANT, WITH EXACTLY ONE EXCEPTION** (his rulings, 2026-08-14).
   *
   * The rule: *"forgets it and deletes Camea's copy. The user's original file is never touched, and
   * there is no confirm box for deleting a copy Camea made itself."* ⛔ **Do not add a box to the
   * other cases to make this consistent** — he was asked twice and said no both times.
   *
   * The exception, which he was asked about separately once it was noticed: that instruction
   * assumes there is always his own copy to fall back on. When **our copy exists and his original
   * has gone**, ours is the last one, and removing it is the only unrecoverable act in this
   * feature. Then, and only then, it asks.
   *
   * ⚠️ **The condition is `stored` AND the source is gone.** A `referenced` recording whose source
   * has vanished has no copy at all, so removing it destroys nothing and must NOT prompt — getting
   * the two the wrong way round would put a box in front of the harmless case and none in front of
   * the harmful one.
   *
   * ⚠️ And it re-reads the shelf first, so the question is asked about the disk as it is **at the
   * moment he clicks** — a drive that has been plugged back in must not still be warned about.
   *
   * 🔴 **IF THE RE-READ FAILS, NOTHING IS REMOVED.** Not "fall back to what the screen last knew":
   * the whole point of the re-read is to find out whether this click is the irreversible kind, and
   * proceeding on stale data is precisely the case where it would be irreversible and unannounced.
   * Camea could not check, so Camea does not do it, and says so.
   */
  async function askThenRemove(row: MeaShelfEntry): Promise<void> {
    if (busy) return;
    const rows_ = await refresh();
    if (rows_ === null) {
      toast.push('Camea could not check that recording just now, so nothing was removed. Try again.',
        { tone: 'danger' });
      return;
    }
    const fresh = rows_.find((r) => r.id === row.id);
    if (fresh === undefined) return; // already gone — another tab, or a double click
    if (fresh.copy_state === 'stored' && !fresh.source_present) {
      setConfirming(fresh);
      return;
    }
    await doRemove(fresh);
  }

  async function doRemove(row: MeaShelfEntry): Promise<void> {
    setBusy(true);
    setConfirming(null);
    try {
      const shelf = await removeRecording(analysisId, row.id);
      setRows(shelf.recordings ?? []);
    } catch (e) {
      toast.push(e instanceof Error ? e.message : String(e), { tone: 'danger' });
    } finally {
      setBusy(false);
    }
  }

  const list = rows ?? [];
  const addButton = (
    <Button
      variant="primary"
      size="sm"
      disabled={busy}
      onClick={() => setAdding(true)}
      data-testid="mea-add-recordings"
    >
      + Add recordings
    </Button>
  );

  return (
    <div className={styles.shelf} data-testid="mea-shelf">
      {/* ⭐ **001's EMPTY STATE, KEPT — and it is not a leftover.** It is what he sees the moment he
          removes his last recording, and the wizard can produce it too (he chose "Create it empty",
          2026-08-14). The one thing that changed is that the button WORKS now, and the `?` beside
          it in the header no longer says it does not. */}
      {rows != null && list.length === 0 ? (
        <div className={styles.empty} data-testid="mea-empty">
          <p className={styles.lead}>No recordings yet.</p>
          {addButton}
        </div>
      ) : (
        <div className={styles.head}>
          <h2 className={styles.heading}>
            {list.length} recording{list.length === 1 ? '' : 's'}
          </h2>
          {addButton}
        </div>
      )}

      {failure && (
        <LiveWarning variant="loud">
          <span data-testid="mea-shelf-error">{failure}</span>
        </LiveWarning>
      )}

      <ul className={styles.rows}>
        {list.map((r) => {
          const words = copyWords(r);
          return (
            <li
              key={r.id}
              className={styles.row}
              data-testid="mea-recording"
              data-recording-id={r.id}
              data-copy={r.copy_state}
              data-missing={r.missing ? 'true' : 'false'}
            >
              <div className={styles.rowMain}>
                <span className={styles.label} data-testid="mea-recording-label">
                  {r.label || r.run_id || r.id}
                </span>
                {r.missing ? (
                  // 🔴 LIVE WARNING, ON THE PAGE. Never behind the `?` — see the header.
                  <LiveWarning variant="warn" className={styles.gone}>
                    <span data-testid="mea-recording-missing">
                      This recording is no longer where you left it (<b>{r.source_path}</b>), and
                      Camea has no copy of it yet.
                    </span>
                  </LiveWarning>
                ) : (
                  <span className={styles.facts} data-testid="mea-recording-facts">
                    {[
                      r.duration_s != null ? formatSeconds(r.duration_s) : null,
                      r.n_channels != null ? `${r.n_channels} channels` : null,
                      r.n_spikes != null ? `${r.n_spikes.toLocaleString()} spikes` : null,
                      r.bytes ? formatBytes(r.bytes) : null,
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </span>
                )}
              </div>

              <div className={styles.rowSide}>
                <span
                  className={styles.copy}
                  data-tone={words.tone}
                  data-testid="mea-recording-copy"
                  title={r.copy_error || undefined}
                >
                  {words.text}
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  onClick={() => void askThenRemove(r)}
                  data-testid="mea-remove-recording"
                >
                  Remove
                </Button>
              </div>
            </li>
          );
        })}
      </ul>

      {adding && (
        <div className={styles.backdrop} onMouseDown={() => !busy && setAdding(false)}>
          <div
            className={styles.dialog}
            role="dialog"
            aria-modal="true"
            aria-label="Add recordings"
            data-testid="mea-add-dialog"
            onMouseDown={(e) => e.stopPropagation()}
          >
            <h2 className={styles.dialogTitle}>Add recordings</h2>
            {/* ⭐ THE SAME COMPONENT THE WIZARD'S FILES STEP MOUNTS. Check by reading this import,
                not by eye — that is the whole reason there is only one of it. */}
            <ImportRecordings onChange={setPicked} busy={busy} />
            <div className={styles.dialogFoot}>
              <Button variant="ghost" onClick={() => setAdding(false)} disabled={busy}>
                Cancel
              </Button>
              <Button
                variant="primary"
                disabled={busy || picked.length === 0}
                onClick={() => void doAdd()}
                data-testid="mea-add-confirm"
              >
                {picked.length > 0 ? `Add ${picked.length}` : 'Add'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {confirming && (
        <div className={styles.backdrop} onMouseDown={() => setConfirming(null)}>
          <div
            className={styles.dialog}
            role="alertdialog"
            aria-modal="true"
            aria-label="Remove the last copy"
            data-testid="mea-remove-confirm"
            onMouseDown={(e) => e.stopPropagation()}
          >
            <h2 className={styles.dialogTitle}>Remove {confirming.label}?</h2>
            <p className={styles.dialogBody}>
              Your own copy of this recording is no longer where you put it, so this is the only one
              left.
            </p>
            <div className={styles.dialogFoot}>
              <Button variant="ghost" onClick={() => setConfirming(null)}>
                Cancel
              </Button>
              <Button
                variant="danger"
                onClick={() => void doRemove(confirming)}
                data-testid="mea-remove-anyway"
              >
                Remove anyway
              </Button>
            </div>
          </div>
        </div>
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
