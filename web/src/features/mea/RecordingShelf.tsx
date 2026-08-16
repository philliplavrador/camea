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
import {
  addRecordings,
  listRecordings,
  meaEnvelopes,
  removeRecording,
  renameRecording,
  startMeaEnvelopes,
  useRunningJobs,
  useStopJob,
} from '../../api';
import type {
  MeaEnvelopeRow,
  MeaEnvelopeStatus,
  MeaShelfEntry,
  RunningJobView,
} from '../../api';
import { useToast } from '../../app';
import {
  NOT_READ_YET,
  READING_LABEL,
  READ_NOT_POSSIBLE,
  READ_STOPPED,
} from '../../core/trace/wholeRecording';
import { Button, LiveWarning, Progress, useDelayedFlag } from '../../design';
import { formatBytes, formatSeconds } from './format';
import { useElapsedText } from './useElapsed';
import { ImportRecordings } from './ImportRecordings';
import { SHELF_SORTS, orderShelf, shelfAssays } from './shelfOrder';
import type { ShelfSort } from './shelfOrder';
import styles from './RecordingShelf.module.css';

/** How often to re-read the shelf while a copy is running. Off entirely when nothing is copying —
 *  a screen that polls forever is a screen that keeps a laptop's fan on for no reason. */
const COPY_POLL_MS = 700;

/** How often to re-read the envelope status while a one-off read runs — `MeaTrace`'s cadence. */
const ENVELOPE_POLL_MS = 2000;

/**
 * ⭐ **The kind string the copy job is registered under** (`recordings.py :: COPY_JOB_KIND`). A wire
 * value, not dataset knowledge — see `pairCopies` for the one thing it is used for.
 */
const COPY_JOB_KIND = 'mea_copy';

/**
 * The four words a row can say about where Camea is reading it from.
 *
 * ⚠️ **Plain English, not the wire's vocabulary.** The document calls these `referenced` /
 * `copying` / `stored` / `failed`; he is a biologist, and *"referenced"* is a word about our
 * implementation rather than about his recording. What he needs to know is which disk it is coming
 * off and whether that is settled yet.
 *
 * ⛔ **`copying` is not here.** It is the one state with a number and a time attached, so it is a
 * `<Progress>` on the row rather than a sentence (R48) — see `copyBar` in the render.
 */
function copyWords(r: MeaShelfEntry): { text: string; tone: 'ok' | 'busy' | 'warn' } {
  switch (r.copy_state) {
    case 'stored':
      return { text: 'In the project', tone: 'ok' };
    case 'failed':
      return { text: 'Still in your folder — the copy did not finish', tone: 'warn' };
    default:
      return { text: 'In your folder — copying', tone: 'busy' };
  }
}

/** What a row is called, everywhere it has to be named — the label he sees, never the minted id. */
function nameOf(r: MeaShelfEntry): string {
  return r.label || r.run_id || r.id;
}

/**
 * ⏱️ **WHICH LIVE COPY JOB BELONGS TO WHICH COPYING ROW (BEHAVIOUR R48.4).**
 *
 * The copy loop measures both an ETA and a real MB/s, and puts them on its job — but `MeaShelfEntry`
 * carries `copy_pct` and no job id, so the row cannot simply look its own up. It is matched by
 * ORDER instead, which is exact for one reason worth writing down: `copy_state === 'copying'` is
 * itself DERIVED from "a live copy job exists for this recording" (`shelf_entry` →
 * `_live_copy_job`), and the jobs are submitted in document order (`_start_copies` iterates the
 * recordings as they were appended). So the k-th copying row in **document order** is the k-th
 * oldest copy job, and `/api/jobs/running` is documented as oldest-first.
 *
 * ⚠️ **And it refuses to guess when the two lists disagree.** The shelf and the running list are
 * polled on different clocks, so for a poll or two they can be one apart; pairing through that skew
 * would put one recording's time on another's row. An empty map is the honest answer — the bar
 * keeps its real percentage and the time slot falls back to R48.4's sentence.
 *
 * ⛔ Pass the rows in DOCUMENT order (`rows`), never the sorted view (`shown`).
 */
function pairCopies(
  rows: MeaShelfEntry[],
  jobs: RunningJobView[],
): Map<string, RunningJobView> {
  const out = new Map<string, RunningJobView>();
  const copying = rows.filter((r) => r.copy_state === 'copying');
  const copies = jobs.filter((j) => j.kind === COPY_JOB_KIND);
  if (copying.length === 0 || copying.length !== copies.length) return out;
  copying.forEach((r, i) => out.set(r.id, copies[i]!));
  return out;
}

export interface RecordingShelfProps {
  analysisId: string;
  /**
   * ⭐ *"You pick one to load, and it opens it up"* — plan 003. The shelf reports the choice and
   * does not own the viewer, so the two can be read separately and the shelf stays a list of
   * facts. ⛔ A recording with no file at either address cannot be opened, and its row says why
   * rather than opening onto an empty chip.
   */
  onOpen?: (recordingId: string) => void;
}

export function RecordingShelf({ analysisId, onOpen }: RecordingShelfProps) {
  const toast = useToast();
  const [rows, setRows] = useState<MeaShelfEntry[] | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  /** ⏱️ The row being removed, NAMED, and which of the two steps is running (R48.7/R48.9). */
  const [removing, setRemoving] = useState<{ id: string; label: string; what: string } | null>(
    null,
  );
  const [confirming, setConfirming] = useState<MeaShelfEntry | null>(null);
  const [editing, setEditing] = useState<{ id: string; value: string } | null>(null);
  // ⭐ **The sort and the type filter are a VIEW** (`shelfOrder.ts`) — client-side, derived on
  // every render, so the 700 ms copy-poll replacing `rows` cannot fight them; keys stay the
  // minted row ids. The default is the document's own order, exactly what the shelf always was.
  const [sort, setSort] = useState<ShelfSort>('as-added');
  const [assay, setAssay] = useState('');
  /**
   * ⭐ **THE READY-TO-VIEW COLUMN** — whether each recording's one-off end-to-end read is done
   * (the read that lets the trace panel show a whole recording at once). By recording id, from
   * `GET …/recordings/envelopes` — a route this shelf never called before; no new endpoint and
   * no write. `null` = not known (the GET failed or has not landed): the column simply does not
   * render, quietly — the shelf's own read failing is the loud one.
   */
  const [envelopes, setEnvelopes] = useState<Map<string, MeaEnvelopeRow> | null>(null);
  /**
   * 🔴 **R48.9 — WHY A ROW'S READ IS OVER WITHOUT THE RECORDING BEING READABLE WHOLE.** By recording
   * id. This poller used to just stop: a row that had been saying `Reading…` went back to offering
   * the button, and an ActivityScan (no continuous trace ⇒ nothing to read ⇒ `ready` never comes)
   * did that on every single click. A wait that ends says that it ended, including badly.
   */
  const [readEnded, setReadEnded] = useState<Map<string, string>>(new Map());
  /** Which recordings had a read running at the last poll — the memory the sentence above needs. */
  const wasReading = useRef(new Set<string>());
  /**
   * ⏱️ Every live job, for the two bars on a row that have one (R48.8 — the strip and the row read
   * the SAME numbers; the row must never compute a second estimate).
   */
  const runningJobs = useRunningJobs();
  const stopJob = useStopJob();

  const applyEnvelopes = useCallback((s: MeaEnvelopeStatus): void => {
    if (!alive.current) return;
    const rows = s.recordings ?? [];
    setEnvelopes(new Map(rows.map((r) => [r.recording_id, r])));
    // R48.9 — compare against what was running a moment ago. A row that HAD a job, has none now and
    // is still not ready has stopped without producing anything, and that is a real state.
    const stopped: string[] = [];
    const settled: string[] = [];
    for (const r of rows) {
      if (r.job_id) {
        wasReading.current.add(r.recording_id);
        settled.push(r.recording_id);
      } else if (r.ready) {
        wasReading.current.delete(r.recording_id);
        settled.push(r.recording_id);
      } else if (wasReading.current.delete(r.recording_id)) {
        stopped.push(r.recording_id);
      }
    }
    setReadEnded((prev) => {
      const next = new Map(prev);
      for (const id of settled) next.delete(id);
      for (const id of stopped) next.set(id, READ_STOPPED);
      // Allocating a new Map on every poll would re-render the whole shelf every 2 s for nothing.
      return next.size === prev.size && [...next].every(([k, v]) => prev.get(k) === v)
        ? prev
        : next;
    });
  }, []);
  /** Which row's name to put focus back on when an edit closes. ⭐ The input and the name-button are
   *  different elements, so React unmounts the focused one and focus would otherwise fall to
   *  `<body>` — i.e. a keyboard user who renames a row has to Tab from the top of the page again. */
  const refocus = useRef<string | null>(null);
  const labelRefs = useRef(new Map<string, HTMLButtonElement>());
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

  // The envelope status, once on arrival…
  useEffect(() => {
    void meaEnvelopes(analysisId)
      .then(applyEnvelopes)
      .catch(() => {
        // Quiet — see the state's comment. Nothing here is his data going missing.
      });
  }, [analysisId, applyEnvelopes]);

  // …and re-read ONLY while a one-off read is running, the same shape as the copy poll above.
  // It stops by itself when the last job ends — including the refused case (an ActivityScan
  // stores no continuous trace): the job goes, `ready` stays false, and the button returns
  // rather than a spinner that never lands. The same stop rule `MeaTrace` uses.
  const envRunning = envelopes != null && [...envelopes.values()].some((r) => r.job_id);
  useEffect(() => {
    if (!envRunning) return;
    const t = setInterval(() => {
      void meaEnvelopes(analysisId)
        .then(applyEnvelopes)
        .catch(() => {});
    }, ENVELOPE_POLL_MS);
    return () => clearInterval(t);
  }, [envRunning, analysisId, applyEnvelopes]);

  /** ⭐ The EXISTING backfill POST — it reads every recording still lacking the one-off pass
   *  (this row among them) and reports a job already running rather than starting a duplicate.
   *  No new endpoint, no write to any file of his. The poll above takes it from here.
   *
   *  🔴 **R48.9 — AND IT ANSWERS FOR THE ROW HE CLICKED.** The POST's own reply already says
   *  whether anything started for it, so a recording that cannot be read end to end at all says so
   *  on the click rather than blinking the button and going quiet. */
  async function readNow(row: MeaShelfEntry): Promise<void> {
    try {
      const s = await startMeaEnvelopes(analysisId);
      applyEnvelopes(s);
      const mine = (s.recordings ?? []).find((r) => r.recording_id === row.id);
      if (!mine?.ready && !mine?.job_id) {
        setReadEnded((prev) => new Map(prev).set(row.id, READ_NOT_POSSIBLE));
      }
    } catch (e) {
      toast.push(e instanceof Error ? e.message : String(e), { tone: 'danger' });
    }
  }

  async function doAdd(): Promise<void> {
    if (busy || picked.length === 0) return;
    setBusy(true);
    try {
      const shelf = await addRecordings(analysisId, picked);
      setRows(shelf.recordings ?? []);
      setAdding(false);
      setPicked([]);
      // New recordings start their one-off read at import — pick up the fresh jobs so the new
      // rows say "Reading…" rather than sitting blank until something else asks.
      void meaEnvelopes(analysisId)
        .then(applyEnvelopes)
        .catch(() => {});
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
    if (busy || removing) return;
    // ⏱️ **R48 — THE BUSY FLAG GOES UP BEFORE THE ROUND TRIP, NOT AFTER IT.** The re-read below is
    // a whole request, and a 1.6 GB `rmtree` after it is seconds on a spinning disk; this used to
    // set nothing until both were done, so the first thing a Remove click did was nothing at all.
    setRemoving({ id: row.id, label: nameOf(row), what: 'checking whether this is the last copy' });
    try {
      await removeSteps(row);
    } finally {
      if (alive.current) setRemoving(null);
    }
  }

  /** The two steps `askThenRemove` reports on, split out so its `finally` cannot swallow a return. */
  async function removeSteps(row: MeaShelfEntry): Promise<void> {
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

  /**
   * Put focus back on the name he was editing, once the button is on the page again.
   *
   * ⚠️ **DEFERRED A FRAME, AND THAT IS NOT A TIDINESS CHOICE.** Enter closes the editor during
   * `keydown`; focusing the name-button synchronously puts it under the cursor in time to receive
   * the *rest* of that same keystroke, which the browser turns into a click — so the editor sprang
   * straight back open with the old name. Caught by the e2e test. One frame later the keystroke is
   * spent, and the focus lands where he left it.
   */
  useEffect(() => {
    if (editing !== null || refocus.current === null) return;
    const id = refocus.current;
    refocus.current = null;
    const t = requestAnimationFrame(() => labelRefs.current.get(id)?.focus());
    return () => cancelAnimationFrame(t);
  }, [editing, rows]);

  /**
   * ⭐ **A RENAME CHANGES WHAT THE ROW IS CALLED, AND NOTHING ELSE.** No file on any disk moves —
   * the backend rewrites the document's `label` only. Enter saves, Esc cancels, and clicking away
   * saves too (an edit he typed and then clicked off is an edit he meant).
   *
   * ⚠️ A name emptied to nothing is treated as "never mind" and reverts quietly, rather than
   * bouncing the backend's refusal at him for something he can see is blank.
   */
  async function commitRename(): Promise<void> {
    if (editing === null) return;
    const { id, value } = editing;
    refocus.current = id;
    setEditing(null);
    const next = value.trim();
    const was = (rows ?? []).find((r) => r.id === id);
    if (!next || was === undefined || next === was.label) return;
    try {
      const shelf = await renameRecording(analysisId, id, next);
      setRows(shelf.recordings ?? []);
    } catch (e) {
      toast.push(e instanceof Error ? e.message : String(e), { tone: 'danger' });
    }
  }

  async function doRemove(row: MeaShelfEntry): Promise<void> {
    setBusy(true);
    setConfirming(null);
    // ⏱️ R48 — a 1.6 GB delete is seconds on a spinning disk, and it is one of R48.9's four
    // genuinely unstoppable waits: `shutil.rmtree` has no callback to poll and no place to check a
    // cancel flag, so the row says so where the Stop button would be rather than growing a dead one.
    setRemoving({ id: row.id, label: nameOf(row), what: 'deleting Camea’s own copy' });
    try {
      const shelf = await removeRecording(analysisId, row.id);
      setRows(shelf.recordings ?? []);
    } catch (e) {
      toast.push(e instanceof Error ? e.message : String(e), { tone: 'danger' });
    } finally {
      setBusy(false);
      if (alive.current) setRemoving(null);
    }
  }

  const list = rows ?? [];
  // ⭐ **A ROW ADDED TWICE FROM THE SAME FILE SAYS SO** — the id is minted precisely because "he
  // may add the same file twice, and a path is not an identity" (the schema's words), so two rows
  // can silently be one recording. The note names the other row so he can tell which is which.
  const dupNames = new Map<string, string>();
  for (const r of list) {
    const twin = list.find((o) => o.id !== r.id && o.source_path === r.source_path);
    if (twin) dupNames.set(r.id, twin.label || twin.run_id || twin.id);
  }
  // ⭐ The one-line summary — facts about the WHOLE shelf, whatever the filter below is showing,
  // because "how much is on this shelf" must not change when he narrows the view of it. Only the
  // non-zero parts are said; a row that lost its file contributes nothing (I1 — no zeros).
  const totalS = list.reduce((n, r) => n + (r.duration_s ?? 0), 0);
  const totalB = list.reduce((n, r) => n + (r.bytes || 0), 0);
  const nCopying = list.filter((r) => r.copy_state === 'copying').length;
  const summaryParts = [
    totalS > 0 ? formatSeconds(totalS) : null,
    totalB > 0 ? formatBytes(totalB) : null,
    nCopying > 0 ? `${nCopying} still copying` : null,
  ].filter(Boolean);
  const assays = shelfAssays(list);
  // A filter value whose assay left the shelf (its last row was removed) falls back to All —
  // silently, because a select holding a value its menu no longer offers is a stuck control.
  const effectiveAssay = assays.includes(assay) ? assay : '';
  const shown = orderShelf(list, sort, effectiveAssay);
  // ⏱️ R48.10 — the shelf's own read is in flight. `rows === null` is genuinely "Camea does not know
  // yet"; the heading below must not answer the question while that is true.
  const shelfWait = useDelayedFlag(rows == null && failure == null);
  // ⏱️ R48 — **THE ADD ITSELF, whose entire progress UI was a greyed-out button still reading
  // `Add 3`.** The POST opens every picked file server-side to confirm it is a MaxLab recording
  // before it writes anything (`routes.post_mea_recordings` → `_read_paths`), which is tens of ms
  // each on a local disk and seconds off a mounted share. Gated on `adding` as well as `busy`,
  // because `busy` is also the remove's flag and that one reports on its own row.
  const addWait = useDelayedFlag(adding && busy);
  const addFor = useElapsedText(adding && busy);
  // ⛔ Document order, never `shown` — see `pairCopies`.
  const copyJobs = pairCopies(list, runningJobs);
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
      {rows == null ? (
        // 🔴 **R48.10 — NEVER STATE A FALSEHOOD WHILE LOADING.** This branch is the whole ruling:
        // the heading below reads `{list.length} recordings`, and `list` is `[]` until the read
        // lands, so the shelf opened by announcing **0 recordings** — a confident, wrong count that
        // then swapped. An in-flight fetch and an empty shelf are different states and must look
        // different, so the count is simply not stated until there is one.
        // ⚠️ **`rows == null`, NOT "in flight".** A read that FAILED leaves `rows` null too, and
        // announcing `0 recordings` over the top of "Camea could not read the shelf" is the same
        // confident wrong count, said next to the admission that Camea does not know. The bar
        // inside is what is gated on the read still being out (`shelfWait`).
        <div className={styles.head}>
          <div className={styles.headline} data-testid="mea-shelf-summary">
            <h2 className={styles.heading}>Recordings</h2>
            {shelfWait && (
              <Progress
                compact
                className={styles.headProgress}
                label="Reading what this project holds"
                // R48.9 — a document read has no denominator worth inventing: it is one request,
                // and a bar filling to a made-up number would be the lie the sliver exists to avoid.
                pct={null}
                data-testid="mea-shelf-loading"
              />
            )}
          </div>
          {addButton}
        </div>
      ) : rows != null && list.length === 0 ? (
        <div className={styles.empty} data-testid="mea-empty">
          <p className={styles.lead}>No recordings yet.</p>
          {addButton}
        </div>
      ) : (
        <div className={styles.head}>
          <div className={styles.headline} data-testid="mea-shelf-summary">
            <h2 className={styles.heading}>
              {list.length} recording{list.length === 1 ? '' : 's'}
            </h2>
            {summaryParts.length > 0 && (
              <span className={styles.summary}>· {summaryParts.join(' · ')}</span>
            )}
          </div>
          {addButton}
        </div>
      )}

      {failure && (
        <LiveWarning variant="loud">
          <span data-testid="mea-shelf-error">{failure}</span>
        </LiveWarning>
      )}

      {/* Plain controls; a one-row shelf has nothing to arrange and shows none. R7.6's spirit:
          "Sort" and "Type" say what they do — no `?`. */}
      {list.length >= 2 && (
        <div className={styles.tools} data-testid="mea-shelf-tools">
          <label className={styles.tool}>
            Sort
            <select
              className={styles.select}
              value={sort}
              onChange={(e) => setSort(e.target.value as ShelfSort)}
              data-testid="mea-shelf-sort"
            >
              {SHELF_SORTS.map(([k, words]) => (
                <option key={k} value={k}>
                  {words}
                </option>
              ))}
            </select>
          </label>
          {/* A type filter with one type filters nothing — it appears when there are two. */}
          {assays.length >= 2 && (
            <label className={styles.tool}>
              Type
              <select
                className={styles.select}
                value={effectiveAssay}
                onChange={(e) => setAssay(e.target.value)}
                data-testid="mea-shelf-filter"
              >
                <option value="">All</option>
                {assays.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
      )}

      <ul className={styles.rows}>
        {shown.map((r) => {
          const words = copyWords(r);
          const env = envelopes?.get(r.id) ?? null;
          // ⏱️ The three waits a row can be in, each with its own bar (R48). The read's job is
          // looked up BY ID — an exact match; only the copy has to be paired (`pairCopies`).
          const readJob = env?.job_id
            ? (runningJobs.find((j) => j.job_id === env.job_id) ?? null)
            : null;
          const copyJob = copyJobs.get(r.id) ?? null;
          const beingRemoved = removing?.id === r.id ? removing : null;
          const ended = readEnded.get(r.id) ?? null;
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
                {editing?.id === r.id ? (
                  <input
                    className={styles.labelInput}
                    value={editing.value}
                    autoFocus
                    aria-label="Recording name"
                    data-testid="mea-rename-input"
                    onChange={(e) => setEditing({ id: r.id, value: e.target.value })}
                    onBlur={() => void commitRename()}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') void commitRename();
                      if (e.key === 'Escape') {
                        refocus.current = r.id;
                        setEditing(null);
                      }
                    }}
                  />
                ) : (
                  <button
                    type="button"
                    ref={(el) => {
                      if (el) labelRefs.current.set(r.id, el);
                      else labelRefs.current.delete(r.id);
                    }}
                    className={styles.labelButton}
                    title="Click to rename"
                    disabled={busy}
                    onClick={() => setEditing({ id: r.id, value: r.label || r.run_id || r.id })}
                    data-testid="mea-recording-label"
                  >
                    {r.label || r.run_id || r.id}
                  </button>
                )}
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
                {dupNames.has(r.id) && (
                  <span className={styles.dup} data-testid="mea-recording-duplicate">
                    same file as &lsquo;{dupNames.get(r.id)}&rsquo;
                  </span>
                )}

                {/* ⏱️ **THE ROW'S BARS LIVE HERE, NOT IN THE SIDE COLUMN** (R48). The side is a
                    nowrap strip of short words and two buttons; a bar with a label, a percentage
                    and a countdown in it needs the width the main column already has. ⛔ And NOT a
                    bar across the top of the shelf — this stylesheet's first line rules that out,
                    and it is right: the copies finish at wildly different times and one number for
                    all of them would be a number about nothing. */}
                {r.copy_state === 'copying' && (
                  <div
                    className={styles.rowProgress}
                    data-tone="busy"
                    data-testid="mea-recording-copy"
                    title={r.copy_error || undefined}
                  >
                    <Progress
                      compact
                      label="Copying it into the project"
                      // ⚠️ The row's own percentage, which is derived from the same job the ETA
                      // comes off — never two clocks (R48.8). `message` carries the copy loop's
                      // measured MB/s, which is the one number that explains the wait: the same
                      // gigabytes off an SSD and off a mounted share are the same bar ten times
                      // slower, and only the rate says which he is looking at.
                      pct={r.copy_pct ?? 0}
                      etaText={copyJob?.etaText ?? null}
                      elapsedText={copyJob?.elapsedText ?? null}
                      message={copyJob?.message ?? null}
                      onStop={
                        copyJob ? () => void stopJob(copyJob.job_id).catch(() => {}) : undefined
                      }
                      // R48.7 — with no job matched there is nothing wired to stop, so say that
                      // rather than render a button that would do nothing.
                      unstoppableWhy={copyJob ? undefined : 'the copy is running in the background'}
                      data-testid="mea-recording-copy-progress"
                    />
                  </div>
                )}

                {!r.missing && env?.job_id && (
                  <div
                    className={styles.rowProgress}
                    data-ready="reading"
                    data-testid="mea-recording-ready"
                  >
                    <Progress
                      compact
                      label={readJob?.said_as || READING_LABEL}
                      // ⭐ The envelope row's own `pct` is the fallback, so the bar is right from
                      // the first frame; the running-jobs list is what carries the TIME.
                      pct={readJob?.pct ?? env.pct}
                      etaText={readJob?.etaText ?? null}
                      elapsedText={readJob?.elapsedText ?? null}
                      // The turnstile's own words: "waiting for 3 recordings in front of it to be
                      // read" — which is why the sentence above no longer promises a minute.
                      message={readJob?.message ?? null}
                      onStop={() => void stopJob(env.job_id).catch(() => {})}
                      data-testid="mea-recording-reading"
                    />
                  </div>
                )}

                {/* 🔴 R48.9 — the read ended and this recording still cannot be shown whole. */}
                {ended && (
                  <span className={styles.readEnded} data-testid="mea-recording-read-ended">
                    {ended}
                  </span>
                )}

                {beingRemoved && (
                  <div className={styles.rowProgress}>
                    <Progress
                      compact
                      // ⭐ It NAMES the row, because a bar on a shelf of five says nothing about
                      // which of them is going.
                      label={`Removing ${beingRemoved.label}`}
                      // R48.9 — an `rmtree` has no callback and no denominator: a filling bar here
                      // would be an invention, so this is the sliver.
                      pct={null}
                      message={beingRemoved.what}
                      unstoppableWhy="a delete cannot be stopped once it starts"
                      data-testid="mea-removing"
                    />
                  </div>
                )}
              </div>

              <div className={styles.rowSide}>
                {/* ⭐ The ready-to-view column. A row whose file is gone has nothing to read, so
                    it shows nothing here — its live warning is the whole story. ⚠️ The RUNNING
                    case is not here: it is a bar in the main column above, under the same testid. */}
                {!r.missing &&
                  env &&
                  !env.job_id &&
                  (env.ready ? (
                    <span
                      className={styles.ready}
                      data-ready="true"
                      data-testid="mea-recording-ready"
                      title="Camea has read this recording end to end, so the whole of it can be shown at once."
                    >
                      Whole recording ready
                    </span>
                  ) : (
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={busy}
                      title={NOT_READ_YET}
                      onClick={() => void readNow(r)}
                      data-testid="mea-recording-read-now"
                    >
                      Read it now
                    </Button>
                  ))}
                {/* ⚠️ `copying` is absent here for the same reason — it is the bar above. */}
                {r.copy_state !== 'copying' && (
                  <span
                    className={styles.copy}
                    data-tone={words.tone}
                    data-testid="mea-recording-copy"
                    title={r.copy_error || undefined}
                  >
                    {words.text}
                  </span>
                )}
                {onOpen && (
                  <Button
                    variant="primary"
                    size="sm"
                    // ⛔ A row with no file at either address opens onto nothing. The row already
                    // says so as a live warning; the button being off is the same fact, said in
                    // the one place he is about to click.
                    disabled={busy || r.missing}
                    onClick={() => onOpen(r.id)}
                    data-testid="mea-open-recording-button"
                  >
                    Open
                  </Button>
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  // ⚠️ `removing` as well as `busy`: the CHECK that runs before a remove is a whole
                  // round trip during which `busy` is still false, and a second click through it
                  // would start the irreversible half twice.
                  disabled={busy || removing != null}
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
            {/* ⏱️ R48.1/R48.9 — past the 400 ms grace only, so a two-file import off a local disk
                still shows nothing. ⛔ Not a filling bar: the opens happen inside one request and
                the count of them does not come back until it is over, so a percentage here would be
                invented. The sliver, a count-up and what Camea is actually doing are what is true. */}
            {addWait && (
              <Progress
                compact
                label={`Adding ${picked.length} recording${picked.length === 1 ? '' : 's'}`}
                pct={null}
                elapsedText={addFor}
                message="Camea opens each one to confirm it is a MaxLab recording before it writes anything."
                unstoppableWhy="this one request has to finish"
                data-testid="mea-adding"
              />
            )}
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
