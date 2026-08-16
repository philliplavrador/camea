// ─────────────────────────────────────────────────────────────────────────────────────────────
// REGIONS — ⭐ **THE POINT OF THE WHOLE PIPELINE.** The survey mosaic is built and its electrodes
// are numbered; now each *fixed-field* calcium recording — a video of ONE parked field — is placed
// on that mosaic, so the electrodes underneath it can be NAMED. That electrode list is the
// scientific answer: it is what pairs a calcium trace with the MEA channels that were recording
// the same cells. (Since 2026-08-15 one step follows: Orientation, where the chip's seating is
// settled against these located regions — `onNext` is its door.)
//
// ⛔ THE SERVER OWNS THE DOCUMENT (same rule as the build and the electrode map, the opposite of the
// snapshot mosaic). `locate` and `snap` are 202 jobs that SAVE `doc["regions"]` themselves; this
// screen adopts what comes back — `result.region` / a refetch of `getRegions` — and never authors a
// region, never computes an NCC, never decides where a rectangle "really" is.
//
// ⭐ **CONFIRM IS THE HUMAN'S SIGNATURE** (I3, applied to a rectangle instead of a tile). A located
// region is born `unconfirmed` and nothing here promotes it — not a high NCC, not a fat margin, not
// `confident`. Those are evidence for him to weigh. Dragging or snapping puts it back to
// `unconfirmed` SERVER-side, and this screen renders whatever came back rather than guessing.
//
// ⭐ **A DROP IS NOT A COMMIT.** Dragging the rectangle moves it on screen only; the position is
// posted when he presses **Snap** (or `S`), because the number worth keeping is the server's masked
// NCC on the real pixels, not the browser's guess at what the drag meant (R23 — correct beats fast).
//
// ⚠️ R45.7 — every hit target here is a SCREEN distance. At fit zoom a 5319×7356 mosaic draws about
// 1024 px wide, so a field that is 700 mosaic px across is ~135 CSS px, and a small one is a few
// pixels: the drag handle is therefore never allowed below `DRAG_MIN_PX` CSS px, whatever the zoom.
//
// Numbers, not prose (R3): the evidence is a facts grid with the explanations behind hover `?`s.
// What is WRONG RIGHT NOW — an uncertain location, a searched (not measured) zoom, a rotated chip, a
// stale mosaic — is a live warning that stays on the page (R3.8/§5).
// ─────────────────────────────────────────────────────────────────────────────────────────────

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from 'react';
import {
  cancelJob,
  deleteRegion,
  formatElapsed,
  formatEta,
  getRegions,
  locateRegion,
  outputUrl,
  pickOpenFilePath,
  pickOpenFilePaths,
  relocateRegion,
  snapRegion,
  updateRegion,
  useJob,
} from '../../api';
import type {
  ElectrodeMapPayload,
  JobRef,
  RegionRecord,
  RegionsPayload,
  VideoMosaicDocument,
} from '../../api';
import { Button, Help, Kbd, LiveWarning, Panel, Progress, cx } from '../../design';
import { fmtSeconds, fmtWhen, phaseOf } from './format';
import { forSubmit, normalisePath } from '../home/pathText';
import { PreviewViewer, type FrameRequest, type ViewFrame } from './PreviewViewer';
import { WorkFrame } from './WorkFrame';
// ⛔ **NOT FOR A PROGRESS BAR ANY MORE (R48.2).** This module used to lend three of them — the
// well, the bar, the phase/eta row — to this file across a feature's own boundary, and they are
// deleted: every wait here is `design/primitives/Progress`. What is still borrowed is the camera's
// own chrome (`zoomBtn` — the Fields switch sits INSIDE `PreviewViewer`'s zoom bar and has to look
// like the buttons beside it) and the rail's action stack.
import vm from './VideoMosaicFeature.module.css';
import styles from './RegionsStep.module.css';

const errMsg = (e: unknown): string => (e instanceof Error ? e.message : String(e));

/** ⚠️ R45.7 — a handle is a distance ON SCREEN. Never let the grab box fall below this. */
const DRAG_MIN_PX = 24;
/** Rotation is not corrected; past this the reseated chip is worth saying out loud. */
const ANGLE_NOTE_DEG = 2;
/** How far off-stage a quiet outline may be before it is culled. */
const CULL_PX = 80;
/** A candidate this close to the record's own corner IS the placement, not a rival. */
const RIVAL_SAME_SPOT_PX = 1.0;
/** A ghost's score label needs this much drawn width (SCREEN px, R45.7) before it can say it. */
const GHOST_LABEL_MIN_PX = 56;
/** What `[` and `]` move the overlay by. */
const FADE_STEP = 10;
/** Above this the overlay counts as "up", so the flash key swaps to the mosaic instead of to it. */
const FADE_MID = 50;

/** How far Snap may look. `nearby` is the default: the server derives the window from the drag. */
type SnapReach = 'nearby' | 'wider' | 'far';
/**
 * ⚠️ R45.7 — the two wider searches are SCREEN distances, converted to mosaic px with the
 * viewer's current scale at snap time. A budget written in mosaic px means nothing as a gesture:
 * at fit zoom on a big mosaic 160 mosaic px is a few CSS px, at 100 % it is a hand-span. These
 * mean the same thing at any zoom (regions.md §A records the 506-px disaster this rule is from);
 * the server still clamps, and the result quotes the width actually searched.
 */
const SNAP_REACH_SCREEN_PX: Record<Exclude<SnapReach, 'nearby'>, number> = {
  wider: 160,
  far: 320,
};

const f2 = (v: number): string => v.toFixed(2);
const f3 = (v: number): string => v.toFixed(3);
const f4 = (v: number): string => v.toFixed(4);

/** The file's own name, whatever separators its path used. */
const basenameOf = (p: string): string => p.split(/[\\/]/).filter(Boolean).pop() ?? p;

/** One waiting item of a several-at-once run: what to POST, and what a refusal calls it. */
interface QueueJob {
  label: string;
  start: () => Promise<JobRef>;
  /** The row this item re-places, when it is a re-locate — so the LIST can mark the one running. */
  regionId?: string;
}

/**
 * The middle value of a list. ⭐ **THE WHOLE-BATCH ETA RESTS ON THIS** (R48.3): the median of the
 * items already placed is what the ones still waiting are expected to cost. A MEDIAN, not a mean,
 * because one 900 MB recording among five small ones would drag an average up for ever, while the
 * median simply reports the ordinary file — and an ordinary file is what is waiting.
 */
function median(xs: number[]): number | null {
  if (xs.length === 0) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

// ── props ─────────────────────────────────────────────────────────────────────────────────────

export interface RegionsStepProps {
  analysisId: string;
  /** The build's stamp — the camera's cache-buster, and what a region's location was placed against. */
  builtAt: string | null;
  /** The mosaic's own size, so screen ↔ mosaic px means something. */
  canvas: { w: number; h: number } | null;
  /** The electrode map, passed straight through to the camera. Regions cannot be located without it. */
  payload: ElectrodeMapPayload | null;
  /**
   * The document the locate/snap job SAVED. The parent adopts it (it never authors one) so the rest
   * of the screen — the pipeline nav, the outputs list — sees the same truth this step does.
   */
  onDocChanged?: (doc: VideoMosaicDocument) => void;
  /** Optional seed from the already-loaded document, so the list paints before the fetch lands. */
  regions?: RegionRecord[];
  /**
   * The way on to the Orientation step. The PARENT passes it only while the document actually has
   * a located region — the same gate the pipeline nav reads — so this button can never open a
   * step the nav would refuse.
   */
  onNext?: () => void;
}

// ── the step ──────────────────────────────────────────────────────────────────────────────────

export function RegionsStep({
  analysisId,
  builtAt,
  canvas,
  payload,
  onDocChanged,
  regions: seed,
  onNext,
}: RegionsStepProps) {
  const [served, setServed] = useState<RegionsPayload | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);

  // the add box
  const [path, setPath] = useState('');
  const [label, setLabel] = useState('');

  // the one job this step can hold (locate, locate-again OR snap — all `locate_region`, one lease)
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobKind, setJobKind] = useState<'locate' | 'snap' | 'relocate' | 'batch' | null>(null);
  const job = useJob(jobId);
  const running = jobId != null && !job.isTerminal;

  // ⭐ SEVERAL AT ONCE (2026-08-16). The lease is the server's — one locate at a time — so the
  // queue lives HERE: each item is POSTed only when the one before it has landed, every finished
  // row appears as it lands (the ordinary refresh), and a refusal is recorded beside its file
  // name WITHOUT killing what is still waiting (R46.7: the sentence is about THAT file, verbatim).
  // "Stop after this one" drains the rest; the single-path box beside it is untouched (R38).
  //
  // ⏱️ **AND IT CARRIES THE CHEAPEST ETA IN THE APP (R48.3).** There is no backend concept of a
  // batch — the server sees N unrelated locate jobs — so the whole-batch time can only be composed
  // here, and it costs one subtraction: how long the placed items took, median, times the number
  // still waiting, plus what the one in flight has left. `file` is on the state because the readout
  // used to say *"Placing 2 of 5"* without ever naming WHICH recording was in the machine.
  const [batch, setBatch] = useState<{
    placing: number;
    total: number;
    file: string;
    startedAt: number;
  } | null>(null);
  const [batchFails, setBatchFails] = useState<{ file: string; message: string }[]>([]);
  /** R48.9 — what a STOPPED run left behind, so the ending is said instead of merely happening. */
  const [batchStopped, setBatchStopped] = useState<{ placed: number; dropped: number } | null>(null);
  const [stopAfter, setStopAfter] = useState(false);
  const [noDialog, setNoDialog] = useState(false);
  const batchQueueRef = useRef<QueueJob[]>([]);
  const batchActiveRef = useRef(false);
  /** How many items of this run have FINISHED, however they finished — placed, refused or stopped. */
  const batchDoneRef = useRef(0);
  /**
   * 🔴 How many actually LANDED. `batchDoneRef` counts endings, not successes: a refused POST and a
   * cancelled job both advance it. R48.9's sentence is a claim about the work — *"2 recordings went
   * through"* — and counting a refusal as one is a falsehood at the exact moment the ruling asks for
   * the truth, so the two numbers are kept apart.
   */
  const batchPlacedRef = useRef(0);
  const batchTotalRef = useRef(0);
  const batchCurrentRef = useRef('');
  /** How long each PLACED item of this run took, ms — the denominator of the batch ETA (R48.3). */
  const batchTimesRef = useRef<number[]>([]);
  const batchItemStartRef = useRef(0);
  /** When the whole run started, so the batch bar can show an elapsed clock too (R48.4). */
  const batchRunStartRef = useRef(0);
  const stopRef = useRef(false);
  /**
   * ⭐ WHICH ROW IS IN THE MACHINE. A re-locate used to grey its own button out and say nothing
   * else, so with the list scrolled the only sign of work was a button that had stopped responding
   * (R48.6 — the missing thing here is identity, not time). Null for a fresh locate: there is no
   * row yet.
   */
  const [activeRegionId, setActiveRegionId] = useState<string | null>(null);
  /** Something this step may not do while a job runs OR a queue is mid-walk. */
  const busy = running || batch != null;

  // the selection, the pending drop, the readouts
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [drop, setDrop] = useState<{ id: string; x: number; y: number } | null>(null);
  const [banner, setBanner] = useState<{ loud: boolean; message: string } | null>(null);
  // how far Snap searches — `nearby` is today's behaviour (the server derives it from the drag)
  const [reach, setReach] = useState<SnapReach>('nearby');
  /** Which reach the LAST posted snap used, so its banner can quote the width only when chosen. */
  const reachSentRef = useRef<SnapReach>('nearby');
  /** The viewer's current CSS-px-per-mosaic-px, captured off every drawn frame (R45.7). */
  const viewScaleRef = useRef(1);
  const [fade, setFade] = useState(60);
  // ⭐ R47 — Space is HELD, not toggled: the eye stays on the boundary while the two pictures swap.
  const [flash, setFlash] = useState(false);
  const [fieldsOn, setFieldsOn] = useState(true);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameText, setRenameText] = useState('');

  // The parent's callback is an inline arrow — hold it in a ref so adopting a document never
  // re-arms the job effect.
  const docCb = useRef(onDocChanged);
  docCb.current = onDocChanged;

  const list = useMemo<RegionRecord[]>(() => served?.regions ?? seed ?? [], [served, seed]);
  const selected = useMemo(() => list.find((r) => r.id === selectedId) ?? null, [list, selectedId]);

  const refresh = useCallback(async () => {
    try {
      const p = await getRegions(analysisId);
      setServed(p);
      setLoadError(null);
    } catch (e) {
      setLoadError(errMsg(e));
    }
  }, [analysisId]);

  useEffect(() => {
    void refresh();
  }, [refresh, builtAt]);

  // Always point at something real: a deleted region must not leave a phantom selection, and one
  // located region is obviously the one to look at.
  useEffect(() => {
    if (list.length === 0) {
      setSelectedId((id) => (id == null ? id : null));
      return;
    }
    setSelectedId((id) => (id != null && list.some((r) => r.id === id) ? id : list[0].id));
  }, [list]);

  // A drop belongs to one region at one moment: changing the selection abandons it.
  useEffect(() => {
    setDrop((d) => (d && d.id === selectedId ? d : null));
  }, [selectedId]);

  // ⭐ ZOOM TO THE RECORDING HE PICKED. A selection CHANGE — a row click, an arrow key — is the one
  // thing that moves the camera; a re-render, a refetch or the list's own keep-something-selected
  // effect never does, and neither does picking the row again (he may have panned away on purpose).
  // The nonce makes each request one-shot on the viewer's side.
  const [frameTo, setFrameTo] = useState<FrameRequest | null>(null);
  const frameSeq = useRef(0);
  const select = useCallback(
    (r: RegionRecord) => {
      if (r.id !== selectedId) {
        frameSeq.current += 1;
        setFrameTo({ x: r.x, y: r.y, w: r.w, h: r.h, nonce: frameSeq.current });
      }
      setSelectedId(r.id);
    },
    [selectedId],
  );

  // ── the queue driver: POST the next item, or fold the tent ──────────────────────────────────
  const advanceBatch = useCallback(async () => {
    for (;;) {
      if (stopRef.current && batchQueueRef.current.length > 0) {
        // 🔴 R48.9 — the run ends and SAYS SO, including this ending: the files that never got
        // their turn used to disappear without a word, and "stopped" looked exactly like "done".
        setBatchStopped({ placed: batchPlacedRef.current, dropped: batchQueueRef.current.length });
        batchQueueRef.current = [];
      }
      const next = batchQueueRef.current.shift();
      if (!next) {
        batchActiveRef.current = false;
        stopRef.current = false;
        setStopAfter(false);
        setBatch(null);
        setActiveRegionId(null);
        return;
      }
      batchCurrentRef.current = next.label;
      batchItemStartRef.current = Date.now();
      setActiveRegionId(next.regionId ?? null);
      setBatch({
        placing: batchDoneRef.current + 1,
        total: batchTotalRef.current,
        file: next.label,
        startedAt: batchItemStartRef.current,
      });
      try {
        const ref = await next.start();
        setJobKind('batch');
        setJobId(ref.job_id);
        return; // the job effect below advances us when this one lands
      } catch (e) {
        // ⛔ R46.7 — the refusal is a sentence about THIS file, kept beside its name. The queue
        // is not the file: the loop carries straight on to the next one.
        // ⏱️ Its duration is NOT recorded: a POST refused in 20 ms is not what placing a recording
        // costs, and folding it into the median would halve the ETA of everything still waiting.
        batchDoneRef.current += 1;
        setBatchFails((f) => [...f, { file: next.label, message: errMsg(e) }]);
      }
    }
  }, []);

  const startBatch = useCallback(
    (items: QueueJob[]) => {
      if (running || batchActiveRef.current || items.length === 0) return;
      batchQueueRef.current = [...items];
      batchDoneRef.current = 0;
      batchPlacedRef.current = 0;
      batchTotalRef.current = items.length;
      batchTimesRef.current = [];
      batchRunStartRef.current = Date.now();
      batchActiveRef.current = true;
      stopRef.current = false;
      setStopAfter(false);
      setBatchFails([]);
      setBatchStopped(null);
      setJobError(null);
      setBanner(null);
      void advanceBatch();
    },
    [advanceBatch, running],
  );

  // ── the job: locate, locate-again and snap land the same way ────────────────────────────────
  useEffect(() => {
    if (!jobId || !job.isTerminal) return;
    const kind = jobKind;
    const inBatch = kind === 'batch';
    if (job.state === 'failed') {
      const msg =
        job.error?.message ??
        (kind === 'snap' ? 'The snap failed.' : 'Locating the recording failed.');
      if (inBatch) {
        // ⛔ A queue item that could not be placed is recorded with its sentence — and the rest
        // of the queue still runs. One bad file must not cost him the other five.
        setBatchFails((f) => [...f, { file: batchCurrentRef.current, message: msg }]);
      } else {
        setJobError(msg);
      }
    } else if (job.state === 'cancelled' && !inBatch) {
      // 🔴 R48.9 — A WAIT THAT ENDS MUST SAY IT ENDED. A stopped locate used to leave the bar
      // simply gone, with nothing on the page to distinguish "you stopped it" from "it worked".
      setJobError(
        kind === 'snap'
          ? 'The snap was stopped. The rectangle is where you dropped it — snap it again when you are ready.'
          : 'Placing the recording was stopped. Nothing was saved.',
      );
    } else if (job.state === 'done') {
      const result = job.job?.result;
      if (result && result.kind === 'locate_region' && result.analysis_id === analysisId) {
        const r = result.region;
        setSelectedId(r.id);
        setDrop(null);
        if (kind === 'locate') setPath('');
        if (kind === 'locate') setLabel('');
        if (kind === 'snap') {
          // The server's own numbers, in the sweep's words. `moved_px` is measured from where he
          // DROPPED it — the local margin is a shoulder inside the window, never the global one.
          const moved = r.moved_px;
          const parts = [
            moved != null ? `Snapped ${f2(moved)} px from the drop.` : 'Snapped.',
            r.ncc != null ? ` NCC ${f4(r.ncc)}` : '',
            r.snap_margin != null ? `, local margin ${f3(r.snap_margin)}` : '',
            r.ncc != null ? '.' : '',
            // A CHOSEN width is quoted back — the server's clamped number, what was actually
            // searched. The default stays silent: it was derived, not asked for.
            reachSentRef.current !== 'nearby' && r.snap_radius_px != null
              ? ` Searched ±${r.snap_radius_px} px around the drop.`
              : '',
          ];
          setBanner({ loud: r.margin_thin || !r.confident, message: parts.join('') });
        }
        if (result.doc) docCb.current?.(result.doc as VideoMosaicDocument);
      }
      void refresh();
    }
    setJobId(null); // done, failed or cancelled
    setJobKind(null);
    if (inBatch) {
      batchDoneRef.current += 1;
      // ⏱️ R48.3 — one more measurement for the batch ETA. Only a run that actually happened: a
      // cancelled item stopped early and is not what the ones still waiting will cost.
      if (job.state === 'done' && batchItemStartRef.current > 0) {
        batchPlacedRef.current += 1;
        batchTimesRef.current.push(Date.now() - batchItemStartRef.current);
      }
      void advanceBatch();
    } else {
      setActiveRegionId(null);
    }
  }, [
    jobId,
    jobKind,
    job.isTerminal,
    job.state,
    job.job,
    job.error,
    analysisId,
    refresh,
    advanceBatch,
  ]);

  // ── adding a recording ──────────────────────────────────────────────────────────────────────
  const locate = useCallback(async () => {
    if (busy) return;
    const p = forSubmit(path);
    if (!p) return;
    setJobError(null);
    setBanner(null);
    try {
      const ref = await locateRegion(analysisId, p, label.trim());
      setJobKind('locate');
      setJobId(ref.job_id);
    } catch (e) {
      // 409 "build first" / "map the electrodes first", 400 "no video file at …" — INSTRUCTIONS,
      // shown verbatim. The typed path stays in the box (R42.5).
      setJobError(errMsg(e));
    }
  }, [analysisId, busy, label, path]);

  const browse = useCallback(async () => {
    // Native open-file dialog; headless answers 501 and the wrapper falls back to prompt (R38).
    const picked = await pickOpenFilePath({ title: 'Which recording do you want to locate?' });
    if (!picked) return;
    setPath(normalisePath(picked));
  }, []);

  // ⭐ SEVERAL AT ONCE — the native multi-select, queued through the one lease. `null` = there is
  // no file explorer in this mode (headless / VSCode remote), said in one line — deliberately not
  // a prompt, which can only carry one path; the typed box beside it is the always-working door
  // (R38), and it is left exactly as it was.
  const pickSeveral = useCallback(async () => {
    setNoDialog(false);
    const picked = await pickOpenFilePaths({ title: 'Which recordings do you want to locate?' });
    if (picked == null) {
      setNoDialog(true);
      return;
    }
    const paths = picked.map((p) => normalisePath(p)).filter((p) => forSubmit(p) !== '');
    startBatch(
      paths.map((p) => ({
        label: basenameOf(p),
        start: () => locateRegion(analysisId, forSubmit(p)),
      })),
    );
  }, [analysisId, startBatch]);

  // ⭐ "Locate again" — re-run one row's placement from the project's own copy of its recording.
  // R46.6: the machine proposes again, so the row comes back `unconfirmed` with fresh evidence —
  // no are-you-sure, because the Confirm button IS the confirm step.
  const relocate = useCallback(
    async (r: RegionRecord) => {
      if (busy) return;
      setJobError(null);
      setBanner(null);
      // ⭐ The row is marked BEFORE the POST, not when the job's first poll lands: the gap is a
      // real fraction of a second and it is the moment he is looking at the row he just clicked.
      setActiveRegionId(r.id);
      try {
        const ref = await relocateRegion(analysisId, r.id);
        setJobKind('relocate');
        setJobId(ref.job_id);
      } catch (e) {
        // "map the electrodes first" / "the project's copy … is missing" — instructions, verbatim.
        setJobError(errMsg(e));
        setActiveRegionId(null);
      }
    },
    [analysisId, busy],
  );

  const cancel = useCallback(async () => {
    if (!jobId) return;
    try {
      await cancelJob(jobId);
    } catch {
      /* it already finished — a no-op, not an error to shout about */
    }
  }, [jobId]);

  /**
   * R48.7 — the batch bar's Stop stops the BATCH: the file in the machine is cancelled and the
   * rest of the queue is dropped. *"Stop after this one"* beside it is the gentler half and stays,
   * because letting the current placement finish is often what he actually wants.
   */
  const stopBatch = useCallback(async () => {
    // ⛔ The queue is NOT emptied here. `advanceBatch` drains it when the cancelled job lands, and
    // it is the one place that counts what never started for R48.9's sentence — clearing it first
    // made that count zero and the ending silent again.
    stopRef.current = true;
    setStopAfter(true);
    await cancel();
  }, [cancel]);

  // ── snap: the drop is posted, never assumed ─────────────────────────────────────────────────
  const snap = useCallback(async () => {
    if (busy || !selected) return;
    const at = drop && drop.id === selected.id ? drop : { x: selected.x, y: selected.y };
    // ⭐ R45.7 — a chosen reach is a SCREEN distance; it becomes mosaic px at the zoom he is
    // looking at, so "wider" is the same gesture whatever the camera is doing. `nearby` sends
    // nothing and keeps today's behaviour: the server derives the window from the drag itself.
    const radius =
      reach === 'nearby'
        ? undefined
        : Math.max(1, Math.round(SNAP_REACH_SCREEN_PX[reach] / (viewScaleRef.current || 1)));
    reachSentRef.current = reach;
    setJobError(null);
    setBanner(null);
    setActiveRegionId(selected.id);
    try {
      const ref = await snapRegion(analysisId, selected.id, at.x, at.y, radius);
      setJobKind('snap');
      setJobId(ref.job_id);
    } catch (e) {
      setJobError(errMsg(e));
      setActiveRegionId(null);
    }
  }, [analysisId, busy, drop, reach, selected]);

  // ── the keyboard ────────────────────────────────────────────────────────────────────────────
  // `S` snaps, exactly as it does in the sweep. ⭐ R47 adds the compare keys: HOLD `Space` to swap
  // the two pictures, `[` / `]` to nudge the overlay. ↑/↓ walk the recordings list and Delete asks
  // the row's own question. Bound while this step is mounted, and never while he is typing in the
  // path, the name or a rename box.
  const snapRef = useRef(snap);
  snapRef.current = snap;
  // ↑/↓ and Delete need the list, the selection and `remove`, which are declared further down —
  // the real handlers land in these refs every render (they are read at key time, never at mount),
  // so the one keyboard effect below never has to re-arm.
  const navRef = useRef<(dir: 1 | -1) => void>(() => {});
  const deleteKeyRef = useRef<() => void>(() => {});
  useEffect(() => {
    const typing = (e: KeyboardEvent): boolean => {
      const el = e.target as HTMLElement | null;
      return /^(INPUT|TEXTAREA|SELECT)$/.test(el?.tagName ?? '') || Boolean(el?.isContentEditable);
    };
    const onKey = (e: KeyboardEvent): void => {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (typing(e)) return;
      if (e.key === 's' || e.key === 'S') {
        e.preventDefault();
        void snapRef.current();
        return;
      }
      if (e.key === ' ') {
        // ⛔ preventDefault ALWAYS, repeat or not: Space would otherwise re-press whatever button
        // has focus (Snap, Confirm) for as long as the key is held down.
        e.preventDefault();
        if (!e.repeat) setFlash(true);
        return;
      }
      if (e.key === '[') {
        e.preventDefault();
        setFade((v) => Math.max(0, v - FADE_STEP));
        return;
      }
      if (e.key === ']') {
        e.preventDefault();
        setFade((v) => Math.min(100, v + FADE_STEP));
        return;
      }
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        navRef.current(e.key === 'ArrowDown' ? 1 : -1);
        return;
      }
      if (e.key === 'Delete') {
        e.preventDefault();
        deleteKeyRef.current();
      }
    };
    const onKeyUp = (e: KeyboardEvent): void => {
      if (e.key === ' ') setFlash(false);
    };
    // ⚠️ Alt-Tab mid-hold never delivers the keyup — without this the overlay stays flashed on and
    // the slider silently means nothing.
    const onBlur = (): void => setFlash(false);
    window.addEventListener('keydown', onKey);
    window.addEventListener('keyup', onKeyUp);
    window.addEventListener('blur', onBlur);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('keyup', onKeyUp);
      window.removeEventListener('blur', onBlur);
    };
  }, []);

  // ⭐ R47 — THE FLASH SHOWS THE OTHER PICTURE. To full when the overlay is down, to nothing when
  // it is already up: a key that always went to 100 % would do nothing at exactly the moment he
  // has pushed the slider up, which is when he is looking hardest.
  const shown = flash ? (fade >= FADE_MID ? 0 : 100) : fade;

  // ── the user's word: rename, confirm, delete ────────────────────────────────────────────────
  const adopt = useCallback(
    (rec: RegionRecord) =>
      setServed((p) =>
        p ? { ...p, regions: (p.regions ?? []).map((r) => (r.id === rec.id ? rec : r)) } : p,
      ),
    [],
  );

  const commitRename = useCallback(
    async (r: RegionRecord) => {
      const name = renameText.trim();
      setRenaming(null);
      if (!name || name === r.name) return;
      setRowError(null);
      try {
        adopt(await updateRegion(analysisId, r.id, { name }));
      } catch (e) {
        setRowError(errMsg(e));
        void refresh();
      }
    },
    [adopt, analysisId, refresh, renameText],
  );

  const setStatus = useCallback(
    async (r: RegionRecord, status: RegionRecord['status']) => {
      setRowError(null);
      try {
        adopt(await updateRegion(analysisId, r.id, { status }));
      } catch (e) {
        setRowError(errMsg(e));
        void refresh();
      }
    },
    [adopt, analysisId, refresh],
  );

  const remove = useCallback(
    async (r: RegionRecord) => {
      // 🔴 The confirmation is not optional and it names what goes: the region takes its still AND
      // the project's copy of the recording with it. `window.confirm` on purpose — R38, Playwright
      // can answer it.
      if (
        !window.confirm(
          `Delete "${r.name}"?\n\nThis removes the located region, its still image and the ` +
            "project's copy of the recording. It cannot be undone.",
        )
      ) {
        return;
      }
      setRowError(null);
      try {
        setServed(await deleteRegion(analysisId, r.id));
      } catch (e) {
        setRowError(errMsg(e));
        void refresh();
      }
    },
    [analysisId, refresh],
  );

  // ⭐ ↑/↓ walk the list — no wrap, and a first press with nothing selected takes the first row.
  // Delete asks EXACTLY the question the row's button does: the same confirm, the same refusal
  // while a job runs. (These land in the refs the keyboard effect reads — see up there.)
  navRef.current = (dir) => {
    if (list.length === 0) return;
    const i = list.findIndex((r) => r.id === selectedId);
    const next = i < 0 ? 0 : Math.min(list.length - 1, Math.max(0, i + dir));
    if (next !== i) select(list[next]);
  };
  deleteKeyRef.current = () => {
    if (selected && !busy) void remove(selected);
  };

  // The rail is the scroller (R47.1): however the selection moved, its row stays visible in it.
  const selRowRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    selRowRef.current?.scrollIntoView({ block: 'nearest' });
  }, [selectedId]);

  // ── dragging the selected rectangle (screen px in, mosaic px out) ────────────────────────────
  const dragRef = useRef<{
    id: string;
    sx: number;
    sy: number;
    ox: number;
    oy: number;
    scale: number;
  } | null>(null);

  const onGrabDown = useCallback(
    (
      e: ReactPointerEvent<HTMLDivElement>,
      r: RegionRecord,
      at: { x: number; y: number },
      scale: number,
    ) => {
      if (e.button !== 0) return;
      e.stopPropagation(); // ⛔ otherwise the press below is a PAN
      e.currentTarget.setPointerCapture?.(e.pointerId);
      dragRef.current = { id: r.id, sx: e.clientX, sy: e.clientY, ox: at.x, oy: at.y, scale };
      setBanner(null);
    },
    [],
  );

  const onGrabMove = useCallback((e: ReactPointerEvent<HTMLDivElement>) => {
    const d = dragRef.current;
    if (!d) return;
    e.stopPropagation();
    let dx = (e.clientX - d.sx) / d.scale;
    let dy = (e.clientY - d.sy) / d.scale;
    // Shift constrains to one axis — the same rule the tile viewer uses (core/viewer/engine.ts).
    if (e.shiftKey) {
      if (Math.abs(dx) > Math.abs(dy)) dy = 0;
      else dx = 0;
    }
    setDrop({ id: d.id, x: d.ox + dx, y: d.oy + dy });
  }, []);

  const onGrabUp = useCallback((e: ReactPointerEvent<HTMLDivElement>) => {
    if (!dragRef.current) return;
    e.stopPropagation();
    dragRef.current = null;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
  }, []);

  // Where each rectangle IS on the mosaic right now: the dropped corner while one is pending,
  // the saved corner otherwise. x/y are TOP-LEFT (R19).
  const cornerOf = useCallback(
    (r: RegionRecord): { x: number; y: number } =>
      drop && drop.id === r.id ? { x: drop.x, y: drop.y } : { x: r.x, y: r.y },
    [drop],
  );

  const moved =
    drop && selected && drop.id === selected.id
      ? Math.hypot(drop.x - selected.x, drop.y - selected.y)
      : 0;

  // ⭐ THE RUNNER-UP SPOTS. The record's `candidates` carry the winner itself at the front, so a
  // RIVAL is any other place the search scored — filtered by distance from the saved corner rather
  // than by rank, so a region he dragged elsewhere shows the machine's original pick as the rival
  // it now is. Evidence, not a warning (R46.7 already owns the warning): drawn only for the
  // SELECTED region, as dashed ghosts nothing can click, drag or confirm.
  const rivals = useMemo(
    () =>
      selected
        ? (selected.candidates ?? []).filter(
            (c) => Math.hypot(c.x - selected.x, c.y - selected.y) > RIVAL_SAME_SPOT_PX,
          )
        : [],
    [selected],
  );

  // ── the overlay (SCREEN space: screen = world × scale + t) ───────────────────────────────────
  const overlay = useCallback(
    (v: ViewFrame): ReactNode => {
      // R45.7 — remember the frame's CSS-px-per-mosaic-px for the snap-reach conversion. Kept
      // ahead of the Fields guard: the camera's scale is true whether or not the layer draws.
      viewScaleRef.current = v.scale;
      if (!fieldsOn) return null;
      return (
        <div className={styles.layer}>
          {/* ⭐ The runner-up ghosts — under the real rectangles, culled like them, gone with the
              Fields switch like them. Same w×h as the selected region at the candidate's TOP-LEFT
              (R19). The score label appears only once the ghost is drawn wide enough to hold it. */}
          {selected &&
            rivals.map((c) => {
              const left = c.x * v.scale + v.tx;
              const top = c.y * v.scale + v.ty;
              const w = selected.w * v.scale;
              const h = selected.h * v.scale;
              if (
                left + w < -CULL_PX ||
                top + h < -CULL_PX ||
                left > v.width + CULL_PX ||
                top > v.height + CULL_PX
              ) {
                return null;
              }
              return (
                <div
                  key={`${c.rank}-${c.x}-${c.y}`}
                  className={styles.ghost}
                  data-testid="region-ghost"
                  data-rank={c.rank}
                  aria-hidden="true"
                  style={{ left, top, width: w, height: h }}
                >
                  {w >= GHOST_LABEL_MIN_PX && (
                    <span className={styles.ghostTag}>{f3(c.ncc)}</span>
                  )}
                </div>
              );
            })}
          {list.map((r) => {
            const isSel = r.id === selectedId;
            const at = cornerOf(r);
            const left = at.x * v.scale + v.tx;
            const top = at.y * v.scale + v.ty;
            const w = r.w * v.scale;
            const h = r.h * v.scale;
            if (
              !isSel &&
              (left + w < -CULL_PX ||
                top + h < -CULL_PX ||
                left > v.width + CULL_PX ||
                top > v.height + CULL_PX)
            ) {
              return null;
            }
            const still = isSel && r.still ? r.still : null;
            return (
              <div key={r.id}>
                <div
                  className={cx(
                    styles.rect,
                    isSel && styles.rectSel,
                    r.status === 'confirmed' && styles.rectOk,
                  )}
                  data-testid="region-rect"
                  data-region-id={r.id}
                  data-selected={isSel || undefined}
                  data-status={r.status}
                  style={{ left, top, width: w, height: h }}
                >
                  {/* ⭐ HIS ASK — the recording's own picture, faded over the mosaic it claims to
                      sit on. It is exactly w×h MOSAIC px, so it rides the camera with the box.
                      ⚠️ The guard reads `shown`, not `fade`: with the slider at 0 a `fade > 0`
                      test would leave the image unmounted and the flash key would show nothing. */}
                  {still && shown > 0 && (
                    <img
                      className={styles.still}
                      data-testid="region-still"
                      alt=""
                      aria-hidden="true"
                      draggable={false}
                      style={{ opacity: shown / 100 }}
                      src={outputUrl(analysisId, still, {
                        v: r.located_at ?? builtAt ?? undefined,
                      })}
                    />
                  )}
                  {isSel && <span className={styles.tag}>{r.name}</span>}
                </div>
                {/* ⚠️ R45.7 — the grab box is a SCREEN distance, never a mosaic one: at fit zoom a
                    field can draw a few CSS px across and would otherwise be undraggable. */}
                {isSel && (
                  <div
                    className={styles.grab}
                    data-testid="region-drag"
                    data-region-id={r.id}
                    style={{
                      left: left + w / 2,
                      top: top + h / 2,
                      width: Math.max(w, DRAG_MIN_PX),
                      height: Math.max(h, DRAG_MIN_PX),
                    }}
                    onPointerDown={(e) => onGrabDown(e, r, at, v.scale)}
                    onPointerMove={onGrabMove}
                    onPointerUp={onGrabUp}
                    onPointerCancel={() => (dragRef.current = null)}
                    title="Drag to move this field · Shift keeps it on one axis · S snaps it"
                  />
                )}
              </div>
            );
          })}
        </div>
      );
    },
    [
      analysisId,
      builtAt,
      cornerOf,
      shown,
      fieldsOn,
      list,
      onGrabDown,
      onGrabMove,
      onGrabUp,
      rivals,
      selected,
      selectedId,
    ],
  );

  const stale = served?.stale ?? false;
  // R46.10 — the rows a rebuild actually invalidated (derived server-side, per row).
  const staleRows = useMemo(() => list.filter((r) => r.stale), [list]);

  // ── ⏱️ THE WHOLE-BATCH BAR AND ITS TIME (BEHAVIOUR R48.3) ────────────────────────────────────
  // ⭐ **PURE CLIENT ARITHMETIC, AND IT HAS TO BE.** The server sees N unrelated locate jobs; only
  // this screen knows they are one act, so only this screen can say how long the act has left. The
  // three ingredients are already here: how many are placed, how long each of those took, and how
  // far the one in flight has got.
  //
  // ⛔ Recomputed every render on purpose (no `useMemo`): it reads the wall clock, and `useJob`'s
  // 1 Hz tick is what repaints it — the same clock the countdown itself runs on (R8.1).
  // ⚠️ R48.11 — this ETA MAY JUMP. The first file's own projection stands in for the ones waiting
  // until a real measurement exists, and a batch of one small file and four big ones will revise
  // upward when the second lands. An honest correction beats a smooth lie (R8.4).
  const batchView = ((): { pct: number; etaText: string | null; elapsedText: string | null } | null => {
    if (!batch) return null;
    const placed = batch.placing - 1;
    const waiting = batch.total - batch.placing;
    const itemElapsedS = Math.max(0, (Date.now() - batch.startedAt) / 1000);
    // The item's own overall fraction, from its own job (R48.5 — the backend's `pct` is already
    // overall across the copy + decode + zoom + match + write of THIS file).
    const frac =
      job.pct != null && Number.isFinite(job.pct) ? Math.min(1, Math.max(0, job.pct / 100)) : 0;
    const medianS = (() => {
      const m = median(batchTimesRef.current);
      return m == null ? null : m / 1000;
    })();
    // What one item costs: measured if anything has finished, otherwise projected from the one
    // running. Null on the first file until its bar has moved off zero — and then the time slot
    // reads "working out how long this will take…", which is exactly true.
    const perItemS = medianS ?? (frac > 0.02 ? itemElapsedS / frac : null);
    const leftHereS =
      frac > 0.02
        ? (itemElapsedS * (1 - frac)) / frac
        : medianS != null
          ? Math.max(0, medianS - itemElapsedS)
          : null;
    const etaS =
      leftHereS == null ? null : perItemS == null ? leftHereS : leftHereS + waiting * perItemS;
    return {
      pct: ((placed + frac) / Math.max(1, batch.total)) * 100,
      etaText: formatEta(etaS),
      elapsedText: formatElapsed((Date.now() - batchRunStartRef.current) / 1000),
    };
  })();

  return (
    <div className={styles.step} data-testid="regions-step">
      <WorkFrame
        testId="regions-work"
        picture={
          <PreviewViewer
            analysisId={analysisId}
            builtAt={builtAt}
            canvas={canvas}
            payload={payload}
            selection={null}
            // ⭐ The lattice is DRAWN here but not clickable: no `onPick`, because on this screen a
            // press is a pan or a drag, never an electrode identification. Seeing the pads while
            // you aim a rectangle is exactly the context this step wants — the electrodes under it
            // ARE the answer it produces. (`PreviewViewer` keys the layer off `showGrid`.)
            showGrid
            overlay={overlay}
            frameTo={frameTo}
            extraTools={
              <button
                type="button"
                role="switch"
                aria-checked={fieldsOn}
                className={cx(vm.zoomBtn, fieldsOn && vm.zoomBtnOn)}
                data-testid="regions-fields-toggle"
                onClick={() => setFieldsOn((on) => !on)}
                title="Show the located fields on the mosaic"
              >
                Fields
              </button>
            }
          />
        }
        rail={
          <>
            {/* ⭐ R47 — ORDER IS THE POINT OF THIS RAIL. The four things he named come before
                everything else: which recording, its signature, the overlay slider, and Snap.
                Adding a recording is a once-per-recording act and waits at the bottom. */}
            {stale && (
              <div data-testid="regions-stale">
                <LiveWarning
                  help={
                    'These rectangles were placed against an earlier build of the mosaic. Camea ' +
                    'never drifts a location onto new pixels, so they are reported as stale ' +
                    'instead: drag each one roughly into place and Snap it, or locate the ' +
                    'recording again. Re-place all stale does the locating for every marked ' +
                    'row, one after another — each result comes back unconfirmed, for you to ' +
                    'check and confirm.'
                  }
                >
                  the mosaic was rebuilt after these were placed —{' '}
                  <b>re-snap before trusting them</b>.
                </LiveWarning>
                {/* ⭐ Every stale row through the same queue the multi-add uses: one at a time,
                    each machine-proposed again (R46.6), refusals kept per file. */}
                {staleRows.length > 0 && (
                  <div className={styles.staleActions}>
                    <Button
                      size="sm"
                      data-testid="regions-replace-stale"
                      disabled={busy}
                      onClick={() =>
                        startBatch(
                          staleRows.map((r) => ({
                            label: r.name || basenameOf(r.source?.name ?? r.id),
                            regionId: r.id, // so the LIST can mark the row that is in the machine
                            start: () => relocateRegion(analysisId, r.id),
                          })),
                        )
                      }
                    >
                      Re-place all stale ({staleRows.length})
                    </Button>
                  </div>
                )}
              </div>
            )}

            {loadError && (
              <div data-testid="regions-load-error">
                <LiveWarning variant="loud">
                  <strong>Could not read the located recordings.</strong> {loadError}
                </LiveWarning>
              </div>
            )}

            {jobError && (
              <div data-testid="regions-error">
                <LiveWarning variant="loud">
                  <strong>Region error.</strong> {jobError}
                </LiveWarning>
              </div>
            )}

            {rowError && (
              <div data-testid="regions-row-error">
                <LiveWarning variant="loud">
                  <strong>That change did not save.</strong> {rowError}
                </LiveWarning>
              </div>
            )}

            {/* ⏱️ ONE recording in the machine, on its own (R48.2/R48.4). A batch draws the
                whole-queue bar below INSTEAD of this one — two bars for one wait is two answers to
                one question. The ETA slot was an always-empty `<span>` here; the primitive fills
                it, and the backend now sends a real number to put in it. */}
            {running && jobKind !== 'batch' && (
              <Panel title={jobKind === 'snap' ? 'Snapping' : 'Locating recording'}>
                <Progress
                  label={job.job?.said_as || 'placing a recording'}
                  // ⭐ R48.9/H9 — A SNAP IS A ONE-SECOND GESTURE AND GETS THE SLIVER, NOT A BAR.
                  // Its two steps have nothing countable inside them, so its `pct` is two fixed
                  // waypoints; drawn as a filling bar that reads as a hang, drawn as the
                  // travelling sliver it reads as what it is.
                  pct={jobKind === 'snap' ? null : job.pct}
                  etaText={jobKind === 'snap' ? null : job.etaText}
                  elapsedText={job.elapsedText}
                  phase={phaseOf(job)}
                  // ⚠️ R48.11 — the locate message names WHICH mode is running. When the lattice
                  // cannot be measured the search goes from 3 scales to 39 and the ETA is supposed
                  // to jump; the sentence beside it is what makes the jump readable.
                  message={job.message}
                  onStop={() => void cancel()}
                  data-testid="regions-progress"
                />
              </Panel>
            )}

            {/* ⭐ THE QUEUE READOUT — visible whenever a several-at-once run is mid-walk. One job
                at a time through the one lease; each landed row appears above as it lands.
                ⏱️ **AND IT IS THE ONLY PLACE THE WHOLE-BATCH TIME CAN COME FROM (R48.3).** The
                server has no idea these N jobs are one act, so the arithmetic is here: median of
                what is placed × what is waiting, plus what is left of the file in the machine. */}
            {batch && (
              <Panel title="Placing recordings">
                {/* ⚠️ The bar keeps its OWN id: `<Progress>` composes `${id}-stop` for its button,
                    and giving it `regions-queue` would collide with the drain button below. */}
                <div data-testid="regions-queue">
                  <Progress
                    label={`Placing ${batch.placing} of ${batch.total}${
                      batch.total - batch.placing > 0
                        ? ` · ${batch.total - batch.placing} waiting`
                        : ''
                    } — ${batch.file}`}
                    pct={batchView?.pct ?? null}
                    etaText={batchView?.etaText ?? null}
                    elapsedText={batchView?.elapsedText ?? null}
                    phase={phaseOf(job)}
                    message={job.message}
                    onStop={() => void stopBatch()}
                    stopLabel="Stop the batch"
                    data-testid="regions-batch"
                  />
                  <div className={styles.queueActions}>
                    <Button
                      variant="ghost"
                      size="sm"
                      data-testid="regions-queue-stop"
                      disabled={stopAfter}
                      onClick={() => {
                        stopRef.current = true;
                        setStopAfter(true);
                      }}
                    >
                      {stopAfter ? 'stopping after this one…' : 'Stop after this one'}
                    </Button>
                  </div>
                </div>
              </Panel>
            )}

            {/* ⭐ R48.6 — ONE SENTENCE NAMING WHAT CAMEA IS BUSY WITH. Eleven controls on this rail
                grey out together while a job runs (the add box, Browse, Pick files, Locate, both
                Delete and Locate-again on every row, Snap, the reach buttons, Confirm) and not one
                of them said why. `said_as` is the backend's own words for the work in flight, so
                the strip at the top of the window and this line always agree. */}
            {busy && (
              <p className={styles.busyNote} data-testid="regions-busy">
                Camea is {job.job?.said_as || 'working on this project'} — the buttons below come
                back when it finishes. Nothing you have done is lost.
              </p>
            )}

            {/* 🔴 R48.9 — a run he STOPPED says what it left undone. Like the fails below it, this
                outlives the queue that produced it and is cleared only when a new run starts. */}
            {batchStopped && !batch && (
              <div data-testid="regions-queue-stopped">
                <LiveWarning variant="warn">
                  <strong>Stopped.</strong> {batchStopped.placed} recording
                  {batchStopped.placed === 1 ? '' : 's'} went through;{' '}
                  <b>
                    {batchStopped.dropped} never started
                  </b>
                  . Nothing was lost — pick them again whenever you like.
                </LiveWarning>
              </div>
            )}

            {/* ⛔ R46.7 — each file that could not be placed stays LISTED, with the server's own
                sentence beside it. It outlives the queue: cleared only when a new run starts. */}
            {batchFails.length > 0 && (
              <div data-testid="regions-queue-fails">
                <LiveWarning variant="loud">
                  <strong>
                    {batchFails.length === 1
                      ? 'One recording could not be placed.'
                      : `${batchFails.length} recordings could not be placed.`}
                  </strong>
                  <ul className={styles.failList}>
                    {batchFails.map((f, i) => (
                      <li key={`${f.file}-${i}`} data-testid="regions-queue-fail">
                        <b>{f.file}</b> — {f.message}
                      </li>
                    ))}
                  </ul>
                </LiveWarning>
              </div>
            )}

            {/* The way on comes first once the document has earned it (R47): settling the chip's
                seating is what the located recordings are FOR, and it has its own step now. */}
            {onNext && (
              <div className={vm.railActions}>
                <Button variant="primary" onClick={onNext} data-testid="vm-to-orientation">
                  Settle the chip
                </Button>
              </div>
            )}

            {/* ── 1 · WHICH RECORDING ─────────────────────────────────────────────────────── */}
            <Panel
              title="Recordings"
              help={
                'One row per located recording. Click a row to put it under judgement on the ' +
                'mosaic; click its name to rename it. The ↑ and ↓ keys walk the list, and Delete ' +
                'removes the selected recording (it asks first, exactly like its button).\n' +
                '\n' +
                'NCC is how well its still matches the mosaic where it was put (1.000 is ' +
                'identical); margin is that score minus the best rival place anywhere on the ' +
                'mosaic — a thin margin means a rival was nearly as good, which on a repeating ' +
                'electrode lattice is exactly the failure to watch for.'
              }
            >
              <div className={styles.list} data-testid="regions-list">
                {list.length === 0 && (
                  <p className={styles.empty} data-testid="regions-empty">
                    no recordings located yet
                  </p>
                )}
                {list.map((r) => {
                  const e = r.electrodes ?? null;
                  const isSel = r.id === selectedId;
                  // ⭐ R48.6 — IS THIS THE ROW IN THE MACHINE? With the list scrolled, a re-locate
                  // used to show nothing but a button that had gone grey, and every other row's
                  // button had gone grey with it. Now the row itself says so.
                  const isRunning = busy && activeRegionId === r.id;
                  const when = fmtWhen(r.located_at);
                  const took = fmtSeconds(r.elapsed_ms);
                  return (
                    <div
                      key={r.id}
                      className={cx(
                        styles.item,
                        isSel && styles.itemSel,
                        r.status === 'confirmed' && styles.itemOk,
                        isRunning && styles.itemRunning,
                      )}
                      data-testid="region-row"
                      data-region-id={r.id}
                      ref={isSel ? selRowRef : undefined}
                      data-selected={isSel || undefined}
                      data-running={isRunning || undefined}
                      data-status={r.status}
                      onClick={() => select(r)}
                    >
                      {/* ⭐ R47 — the row is two lines on a rail. Name, state and Delete read
                          across the top; the numbers sit under them instead of being squeezed
                          out of a 360 px column. */}
                      <div className={styles.itemHead}>
                        {renaming === r.id ? (
                          <input
                            className={cx(styles.input, styles.renameInput)}
                            type="text"
                            aria-label="Region name"
                            data-testid="region-name-input"
                            autoFocus
                            value={renameText}
                            onChange={(ev) => setRenameText(ev.target.value)}
                            onBlur={() => void commitRename(r)}
                            onKeyDown={(ev) => {
                              if (ev.key === 'Enter') {
                                ev.preventDefault();
                                void commitRename(r);
                              } else if (ev.key === 'Escape') {
                                ev.preventDefault();
                                setRenaming(null);
                              }
                            }}
                          />
                        ) : (
                          <button
                            type="button"
                            className={styles.name}
                            data-testid="region-name"
                            title="Rename"
                            onClick={(ev) => {
                              ev.stopPropagation();
                              select(r);
                              setRenameText(r.name);
                              setRenaming(r.id);
                            }}
                          >
                            {r.name}
                          </button>
                        )}

                        <span
                          className={cx(
                            styles.chip,
                            r.status === 'confirmed' ? styles.chipOk : styles.chipOpen,
                          )}
                          data-testid="region-status"
                          data-status={r.status}
                        >
                          {r.status}
                        </span>

                        {/* ⏱️ R48.6 — the row that is being worked on says so, in the same place
                            its state lives. The bar with the time is up on the rail; what was
                            missing down here was IDENTITY. */}
                        {isRunning && (
                          <span
                            className={cx(styles.chip, styles.chipRunning)}
                            data-testid="region-running"
                            title={job.job?.said_as || 'Camea is working on this recording'}
                          >
                            {jobKind === 'snap' ? 'snapping' : 'placing'}
                          </span>
                        )}

                        {/* R46.10 · R47.7 — WHICH rows the rebuild invalidated, said on the row
                            itself. A current-state warning, so it lives on the page, never
                            behind a hover. */}
                        {r.stale && (
                          <span
                            className={cx(styles.chip, styles.chipStale)}
                            data-testid="region-stale"
                            title="Placed against an earlier build of the mosaic — re-snap or locate it again before trusting it"
                          >
                            stale
                          </span>
                        )}

                        <Button
                          variant="ghost"
                          size="sm"
                          className={styles.del}
                          data-testid="region-delete"
                          title="Delete this region, its still and the project's copy of the recording"
                          disabled={busy}
                          onClick={(ev) => {
                            ev.stopPropagation();
                            void remove(r);
                          }}
                        >
                          Delete
                        </Button>
                      </div>

                      {/* ⭐ WHICH FILE the label stands for. The name above is editable, so two
                          recordings renamed alike are told apart by the one thing that cannot
                          collide: the video's own file name. Quiet, and the full path on hover. */}
                      {r.source?.name && (
                        <span
                          className={styles.file}
                          data-testid="region-file"
                          title={r.source.path || r.source.name}
                        >
                          {basenameOf(r.source.name)}
                        </span>
                      )}

                      <span className={styles.rowFacts}>
                        <span className={styles.fact}>
                          <span className={styles.factLabel}>ncc</span>
                          <span data-testid="region-ncc">{r.ncc != null ? f4(r.ncc) : '—'}</span>
                        </span>
                        <span className={styles.fact}>
                          <span className={styles.factLabel}>margin</span>
                          <span data-testid="region-margin" data-thin={r.margin_thin || undefined}>
                            {r.margin != null ? f3(r.margin) : '—'}
                          </span>
                        </span>
                        <span className={styles.fact}>
                          <span className={styles.factLabel}>electrodes</span>
                          <span data-testid="region-electrodes">{e ? e.count : '—'}</span>
                        </span>
                        <Button
                          variant="ghost"
                          size="sm"
                          className={styles.again}
                          data-testid="region-locate-again"
                          title={
                            isRunning
                              ? job.job?.said_as || 'Camea is placing this recording now'
                              : "Search the whole mosaic again for this recording, using the project's own copy of its video"
                          }
                          disabled={busy}
                          onClick={(ev) => {
                            ev.stopPropagation();
                            void relocate(r);
                          }}
                        >
                          {isRunning ? 'Placing…' : 'Locate again'}
                        </Button>
                      </span>

                      {/* When the machine placed it, and how long the search took — receipts,
                          kept quiet under the numbers they date. */}
                      {(when != null || took != null) && (
                        <span className={styles.when} data-testid="region-when">
                          {when != null ? `placed ${when}` : ''}
                          {when != null && took != null ? ' · ' : ''}
                          {took != null ? (
                            <>
                              found in <span data-testid="region-elapsed">{took}</span>
                            </>
                          ) : (
                            ''
                          )}
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            </Panel>

            {/* ── 2 · THE SELECTED REGION: the signature, the overlay, the drop ───────────── */}
            {selected && (
              <RegionDetail
                region={selected}
                rivals={rivals.length}
                moved={moved}
                dropped={drop != null && drop.id === selected.id}
                banner={banner}
                fade={fade}
                shown={shown}
                flash={flash}
                onFade={setFade}
                busy={busy}
                reach={reach}
                onReach={setReach}
                onSnap={() => void snap()}
                onRevert={() => setDrop(null)}
                onStatus={(s) => void setStatus(selected, s)}
              />
            )}

            {/* ── 3 · ADD A RECORDING — once per recording, so it waits at the bottom ─────── */}
            <Panel
              title="Add a recording"
              help={
                'A fixed-field recording is a video of ONE parked field of view. Camea builds a ' +
                'still from it, measures how much it was magnified relative to the mosaic (from ' +
                'the electrode lattice visible in both), and searches the whole mosaic for where ' +
                'it sits.\n' +
                '\n' +
                'The file is COPIED into the project, so moving or deleting the original later ' +
                'does not break the region. The name is a label only — leave it empty to use the ' +
                'file name.\n' +
                '\n' +
                'Paste a path or press Browse. Either way the path is the only thing asked for: ' +
                'where a recording came FROM, never where anything is saved.'
              }
            >
              <div className={styles.addRow}>
                <input
                  className={styles.input}
                  type="text"
                  spellCheck={false}
                  autoComplete="off"
                  aria-label="Recording file path"
                  placeholder="paste the path of a fixed-field recording…"
                  data-testid="regions-path"
                  value={path}
                  disabled={busy}
                  onChange={(e) => {
                    setPath(normalisePath(e.target.value));
                    setJobError(null);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      void locate();
                    }
                  }}
                />
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => void browse()}
                  disabled={busy}
                  data-testid="regions-browse"
                >
                  Browse…
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => void pickSeveral()}
                  disabled={busy}
                  title="Pick several recordings at once — they are located one after another"
                  data-testid="regions-pick-files"
                >
                  Pick files…
                </Button>
              </div>
              {noDialog && (
                <p className={styles.noDialog} data-testid="regions-no-dialog">
                  there is no file dialog in this mode — paste one path at a time instead
                </p>
              )}
              <div className={styles.addRow}>
                <input
                  className={cx(styles.input, styles.nameInput)}
                  type="text"
                  spellCheck={false}
                  autoComplete="off"
                  aria-label="Recording name (optional)"
                  placeholder="name (optional)"
                  data-testid="regions-name"
                  value={label}
                  disabled={busy}
                  onChange={(e) => setLabel(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      void locate();
                    }
                  }}
                />
              </div>
              <div className={styles.addRow}>
                <Button
                  variant="primary"
                  onClick={() => void locate()}
                  disabled={busy || forSubmit(path) === ''}
                  data-testid="regions-locate"
                >
                  Locate on the mosaic
                </Button>
              </div>
            </Panel>
          </>
        }
      />
    </div>
  );
}

// ── The readout — numbers and labels, explanations behind `?`s (R3) ───────────────────────────

/** One attempt of the locating search, as the server recorded it (R46.5's `tried` table). */
interface TriedRow {
  still_kind: string;
  scale: number | null;
  ncc: number | null;
  margin: number | null;
  refused: string | null;
}

/** The served rows, narrowed — the contract types them as a free dict. Order is kept: the table
 *  is shown exactly as served, never re-ranked client-side. */
const triedRows = (r: RegionRecord): TriedRow[] =>
  (r.tried ?? []).map((t) => ({
    still_kind: typeof t.still_kind === 'string' ? t.still_kind : '—',
    scale: typeof t.scale === 'number' ? t.scale : null,
    ncc: typeof t.ncc === 'number' ? t.ncc : null,
    margin: typeof t.margin === 'number' ? t.margin : null,
    refused: typeof t.refused === 'string' && t.refused !== '' ? t.refused : null,
  }));

/**
 * Which attempt won: the record's own `still_kind`, and among its rows the server's rank —
 * margin first, NCC only to break a tie (R46.5: two stills' NCCs are not comparable; how far a
 * winner stands above its own runner-up is).
 */
const triedWinner = (rows: TriedRow[], kind: string): number => {
  let best = -1;
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    if (row.still_kind !== kind || row.refused != null) continue;
    if (best < 0) {
      best = i;
      continue;
    }
    const b = rows[best];
    const bm = b.margin ?? -1;
    const rm = row.margin ?? -1;
    if (rm > bm || (rm === bm && (row.ncc ?? -1) > (b.ncc ?? -1))) best = i;
  }
  return best;
};

function Fact({ label, help, children }: { label: string; help?: string; children: ReactNode }) {
  return (
    <div className={styles.dFact}>
      <dt className={styles.dLabel}>
        {label}
        {help ? <Help body={help} /> : null}
      </dt>
      <dd className={styles.dValue}>{children}</dd>
    </div>
  );
}

interface RegionDetailProps {
  region: RegionRecord;
  /** How many runner-up ghosts are on the mosaic for this region. 0 stays silent. */
  rivals: number;
  /** Mosaic px between the saved corner and the dropped one. 0 when nothing is pending. */
  moved: number;
  dropped: boolean;
  banner: { loud: boolean; message: string } | null;
  /** Where the slider sits — what the number under it reads, and what a release returns to. */
  fade: number;
  /** What is actually drawn: `fade`, or the flash key's swap while Space is held (R47). */
  shown: number;
  flash: boolean;
  onFade: (v: number) => void;
  busy: boolean;
  /** How far Snap searches — `nearby` keeps the server's drag-derived default (R45.7). */
  reach: SnapReach;
  onReach: (r: SnapReach) => void;
  onSnap: () => void;
  onRevert: () => void;
  onStatus: (status: RegionRecord['status']) => void;
}

function RegionDetail({
  region: r,
  rivals,
  moved,
  dropped,
  banner,
  fade,
  shown,
  flash,
  onFade,
  busy,
  reach,
  onReach,
  onSnap,
  onRevert,
  onStatus,
}: RegionDetailProps) {
  const zoom = r.zoom ?? null;
  const e = r.electrodes ?? null;
  const ids = e?.ids ?? [];
  const angle = zoom?.angle_delta_deg ?? null;
  const uncertain = !r.confident || r.margin_thin;
  const confirmed = r.status === 'confirmed';
  // R46.5 — the whole tried table, in the served order, with the winner named.
  const tried = triedRows(r);
  const winner = triedWinner(tried, r.still_kind);

  return (
    <div data-testid="region-panel">
      <Panel
        title={r.name}
        help={
          'Everything the machine measured about THIS location, and nothing it did not. A ' +
          'rectangle is where the recording sits on the mosaic; the electrodes below it are the ' +
          'answer the pipeline exists to produce.'
        }
        actions={
          confirmed ? (
            <Button
              variant="ghost"
              size="sm"
              data-testid="region-unconfirm"
              disabled={busy}
              onClick={() => onStatus('unconfirmed')}
            >
              Unconfirm
            </Button>
          ) : (
            <Button
              variant="primary"
              size="sm"
              data-testid="region-confirm"
              disabled={busy}
              onClick={() => onStatus('confirmed')}
            >
              Confirm this location
            </Button>
          )
        }
      >
        <div className={styles.detail}>
          {/* ⚠️ THE UNCERTAIN CASE STAYS ON THE PAGE (§5) — a confident-looking rectangle over a
              thin margin is exactly the mistake this feature can make. */}
          {uncertain && (
            <div data-testid="region-uncertain">
              <LiveWarning
                variant="loud"
                help={
                  'The margin is the winning score minus the best rival place anywhere on the ' +
                  'mosaic. An electrode array repeats every pitch, so a wrong-but-plausible ' +
                  'rival is the normal failure — a thin margin means one nearly won. Check the ' +
                  'faded still against the mosaic underneath it, drag it if it is wrong, and Snap.'
                }
              >
                <b>UNCERTAIN</b> —{' '}
                {r.margin_thin
                  ? 'a rival place scored almost as well'
                  : 'the evidence did not clear the confidence bar'}
                . Check it by eye before confirming.
              </LiveWarning>
            </div>
          )}

          {/* ⚠️ A SEARCH IS NOT A MEASUREMENT (the zoom's own flag says which happened). */}
          {zoom && !zoom.measured && (
            <div data-testid="region-zoom-searched">
              <LiveWarning
                help={
                  'The magnification is normally MEASURED: the electrode lattice appears in both ' +
                  'the recording and the mosaic, and the ratio of the two pitches is the scale. ' +
                  'No lattice could be read here, so a ladder of zoom factors was tried and the ' +
                  'best-scoring one kept. That is a search result, not a measurement.'
                }
              >
                the zoom was <b>searched, not measured</b> — no electrode lattice was readable in
                this recording.
              </LiveWarning>
            </div>
          )}

          {angle != null && Math.abs(angle) > ANGLE_NOTE_DEG && (
            <div data-testid="region-angle-warning">
              <LiveWarning
                help={
                  'Rotation is not solved — the rig and the chip are assumed to sit the same way ' +
                  'for the survey and for the recording. This number is reported so a reseated ' +
                  'chip is visible instead of silently mis-placed: the rectangle is axis-aligned, ' +
                  'so a turned field will not sit squarely however well it snaps.'
                }
              >
                the recording&apos;s lattice is turned <b>{f2(angle)}°</b> from the mosaic&apos;s —{' '}
                <b>rotation is not corrected</b>.
              </LiveWarning>
            </div>
          )}

          {banner && (
            <div data-testid="region-snap-banner">
              <LiveWarning variant={banner.loud ? 'loud' : 'info'}>{banner.message}</LiveWarning>
            </div>
          )}

          {/* ── ⭐ THE OVERLAY — THE TOOL THIS SCREEN IS JUDGED WITH, so it is first (R47) ──── */}
          <div className={styles.fadeBlock} data-flash={flash || undefined}>
            <div className={styles.fadeRow}>
              <label className={styles.fadeLabel} htmlFor={`region-fade-${r.id}`}>
                Recording overlay
                <Help
                  body={
                    'The still Camea built from this recording, drawn inside the rectangle at the ' +
                    'mosaic’s own scale. Slide it up and down: the cells and the electrode ' +
                    'lattice should walk straight through the boundary. If they jump, the ' +
                    'location is wrong however good the score looks.\n' +
                    '\n' +
                    'Hold SPACE to swap between the two pictures without letting go of the ' +
                    'slider — the fastest way to see a boundary jump. [ and ] nudge it by ' +
                    '10% each.'
                  }
                />
              </label>
              <input
                id={`region-fade-${r.id}`}
                className={styles.slider}
                type="range"
                min={0}
                max={100}
                step={1}
                value={fade}
                data-testid="region-fade"
                onChange={(ev) => onFade(Number(ev.target.value))}
                disabled={!r.still}
              />
              <span className={styles.fadeValue} data-testid="region-fade-value">
                {shown}%
              </span>
            </div>
            {r.still && (
              <p className={styles.fadeHint}>
                hold <Kbd>Space</Kbd> to swap · <Kbd>[</Kbd> <Kbd>]</Kbd> to nudge
              </p>
            )}
          </div>

          {/* ── how far Snap searches — plain words, measured on the SCREEN (R45.7) ───────── */}
          <div
            className={styles.reachRow}
            role="radiogroup"
            aria-label="How far Snap searches"
            data-testid="region-snap-reach"
          >
            <span className={styles.reachLabel}>
              Search
              <Help
                body={
                  'How far around the rectangle Snap looks for the true position.\n' +
                  '\n' +
                  'nearby — the default: the search covers the distance you dragged it, plus a ' +
                  'little.\n' +
                  '\n' +
                  'wider / far — look further around the drop, for when the rectangle needs to ' +
                  'move more than you dragged. Both are measured on your screen (about 160 and ' +
                  '320 screen pixels), so they mean the same hand movement at any zoom. The ' +
                  'result says how far was actually searched.'
                }
              />
            </span>
            {(['nearby', 'wider', 'far'] as const).map((k) => (
              <button
                key={k}
                type="button"
                role="radio"
                aria-checked={reach === k}
                data-reach={k}
                className={cx(styles.reachBtn, reach === k && styles.reachBtnOn)}
                onClick={() => onReach(k)}
              >
                {k}
              </button>
            ))}
          </div>

          {/* ── the drop, and the one button that commits it ──────────────────────────────── */}
          <div className={styles.snapRow}>
            <span
              className={styles.dropped}
              data-testid="region-dropped"
              data-pending={dropped || undefined}
            >
              {dropped
                ? `moved ${f2(moved)} px — not saved yet`
                : `at ${f2(r.x)}, ${f2(r.y)} · ${Math.round(r.w)}×${Math.round(r.h)} px`}
              <Help
                body={
                  'Drag the bright rectangle on the mosaic to move it (hold Shift to keep it on ' +
                  'one axis). Nothing is written when you let go: press Snap (or S) and the ' +
                  'server re-searches a small window around where you dropped it and commits the ' +
                  'position it actually measures. Positions are TOP-LEFT corners, never centres.'
                }
              />
            </span>
            {dropped && (
              <Button variant="ghost" size="sm" data-testid="region-revert" onClick={onRevert}>
                Put it back
              </Button>
            )}
            <Button
              variant={dropped ? 'primary' : 'default'}
              size="sm"
              kbd="S"
              data-testid="region-snap"
              disabled={busy}
              onClick={onSnap}
            >
              Snap
            </Button>
          </div>

          {/* ⭐ R47 — THE EVIDENCE IS ONE LINE UNTIL YOU ASK FOR IT. Seven facts in a grid is the
              screen's densest block and none of it is what you reach for while judging a
              placement: the two numbers that matter read across the top, and the rest — the
              still kind, the zoom, how far the last snap pulled, the local margin — is one
              click away. ⛔ Nothing is DELETED behind the fold; it is all still on the page. */}
          <div className={styles.evidence}>
            {/* ⛔ The `?` is a sibling of the fold, NOT inside its <summary>. A <button> nested in
                a <summary> is toggled by its own click, so the one explanation surface the app has
                (R3.2 — focusable, Enter-able) would open the disclosure instead of explaining. */}
            <div className={styles.evidenceLine}>
              <span className={styles.fact}>
                <span className={styles.factLabel}>ncc</span>
                <span data-testid="region-detail-ncc">{r.ncc != null ? f4(r.ncc) : '—'}</span>
              </span>
              <span className={styles.fact}>
                <span className={styles.factLabel}>margin</span>
                <span data-testid="region-detail-margin" data-thin={r.margin_thin || undefined}>
                  {r.margin != null ? f3(r.margin) : '—'}
                </span>
              </span>
              <Help
                body={
                  'NCC — masked normalised cross-correlation of the still against the mosaic ' +
                  'where it was placed: 1.000 is identical, 0 is unrelated. It is the server’s ' +
                  'number on the real pixels, never a browser-side estimate.\n' +
                  '\n' +
                  'MARGIN — best minus runner-up across the WHOLE mosaic. It is the only evidence ' +
                  'that the repeating electrode comb was beaten rather than merely outscored, so ' +
                  'a big margin is worth more than a big NCC.'
                }
              />
            </div>

            {/* The dashed outlines on the mosaic, named — quiet, and SILENT when there are none.
                Evidence, not a warning: the warning above (R46.7) already owns the uncertain case. */}
            {rivals > 0 && (
              <p className={styles.rivalNote} data-testid="region-rivals">
                {rivals} rival spot{rivals === 1 ? '' : 's'} drawn as dashed outlines on the mosaic
              </p>
            )}

            <details className={styles.details}>
              <summary className={styles.summary} data-testid="region-evidence-toggle">
                everything measured
              </summary>
              <dl className={styles.dFacts}>
                <Fact
                  label="Still"
                  help={
                    'Which projection of the recording won the match. median — the field at rest; ' +
                    'max — the brightest each pixel ever got, so only firing cells show; std — how ' +
                    'much each pixel varied. Whether the neurons are visible at rest is a property ' +
                    'of the preparation, so all of them are tried and the best is kept.'
                  }
                >
                  <span data-testid="region-still-kind">{r.still_kind || '—'}</span>
                </Fact>
                <Fact
                  label="Zoom"
                  help={
                    'Multiply recording pixels by this to get mosaic pixels. MEASURED means it ' +
                    "came from the two lattices' pitches; searched means no lattice was readable " +
                    'and a ladder of factors was tried instead.'
                  }
                >
                  <span data-testid="region-zoom" data-measured={zoom?.measured || undefined}>
                    {zoom
                      ? `${zoom.scale.toFixed(3)}× · ${zoom.measured ? 'measured' : 'searched'}`
                      : '—'}
                  </span>
                </Fact>
                {/* ⭐ R46.2 — the actual evidence behind the ratio: the same electrode spacing,
                    measured once in each picture. Shown only when it WAS measured there; a
                    searched zoom keeps its live warning above, and these lines never soften it. */}
                {zoom?.pitch_recording_px != null && (
                  <Fact
                    label="Spacing in this recording"
                    help={
                      'The distance between neighbouring electrodes, measured in this ' +
                      'recording’s own pixels. The same array appears in both pictures, so it ' +
                      'is a ruler: the mosaic’s spacing divided by this one is the zoom.'
                    }
                  >
                    <span data-testid="region-pitch-recording">
                      {f2(zoom.pitch_recording_px)} px
                    </span>
                  </Fact>
                )}
                {zoom?.pitch_mosaic_px != null && (
                  <Fact
                    label="Spacing in the mosaic"
                    help={
                      'The same electrode spacing, measured on the mosaic in mosaic pixels. ' +
                      'Dividing it by the spacing in the recording is what gives the zoom — a ' +
                      'measurement, not a search.'
                    }
                  >
                    <span data-testid="region-pitch-mosaic">{f2(zoom.pitch_mosaic_px)} px</span>
                  </Fact>
                )}
                <Fact
                  label="Placed by"
                  help={
                    'machine — the locating search put it here. hand+snap — you dragged it and ' +
                    'the server re-searched a window around your drop. Either way the position on ' +
                    'file is one the server measured.'
                  }
                >
                  <span data-testid="region-placed-by">{r.placed_by || '—'}</span>
                </Fact>
                {r.moved_px != null && (
                  <Fact
                    label="Snap moved"
                    help={'How far the last snap pulled the rectangle from where you dropped it.'}
                  >
                    <span data-testid="region-moved">{f2(r.moved_px)} px</span>
                  </Fact>
                )}
                {r.snap_margin != null && (
                  <Fact
                    label="Local margin"
                    help={
                      'The runner-up INSIDE the snap window — a neighbouring shoulder, not a rival ' +
                      'place on the mosaic. It says the snap settled cleanly; it does not replace ' +
                      'the global margin above.'
                    }
                  >
                    <span data-testid="region-snap-margin">{f3(r.snap_margin)}</span>
                  </Fact>
                )}
              </dl>

              {/* The measurement's own remark, when it made one — served verbatim, quiet. */}
              {zoom != null && zoom.note !== '' && (
                <p className={styles.zoomNote} data-testid="region-zoom-note">
                  {zoom.note}
                </p>
              )}

              {/* ⭐ R46.5 — EVERY ATTEMPT IT TRIED, so a poor result can be diagnosed instead of
                  merely disbelieved. One row per picture × size, IN THE ORDER SERVED, the winner
                  named; a refused attempt keeps the server's sentence, verbatim. The table
                  scrolls inside the rail, never the page (R47.1). */}
              {tried.length > 0 && (
                <div className={styles.tried} data-testid="region-tried">
                  <span className={styles.triedLabel}>
                    Every attempt
                    <Help
                      body={
                        'Each summary picture built from the recording, matched at each size ' +
                        'that was tried. Attempts are ranked by margin, not by score — two ' +
                        'pictures’ scores are not comparable, but how far a winner stands above ' +
                        'its own runner-up is. The marked row is the one the placement came ' +
                        'from; a refused row says why in the server’s own words.'
                      }
                    />
                  </span>
                  <div className={styles.triedScroll}>
                    <table className={styles.triedTable}>
                      <thead>
                        <tr>
                          <th>still</th>
                          <th>size</th>
                          <th>ncc</th>
                          <th>margin</th>
                        </tr>
                      </thead>
                      <tbody>
                        {tried.map((t, i) => (
                          <tr
                            key={`${t.still_kind}-${t.scale ?? 'x'}-${i}`}
                            data-testid="region-tried-row"
                            data-still={t.still_kind}
                            data-winner={i === winner || undefined}
                          >
                            <td className={styles.triedKind}>
                              {t.still_kind}
                              {i === winner && <span className={styles.triedWon}>won</span>}
                            </td>
                            <td className={styles.triedNum}>
                              {t.scale != null ? `${f3(t.scale)}×` : '—'}
                            </td>
                            {t.refused != null ? (
                              <td className={styles.triedRefused} colSpan={2}>
                                {t.refused}
                              </td>
                            ) : (
                              <>
                                <td className={styles.triedNum}>
                                  {t.ncc != null ? f3(t.ncc) : '—'}
                                </td>
                                <td className={styles.triedNum}>
                                  {t.margin != null ? f3(t.margin) : '—'}
                                </td>
                              </>
                            )}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </details>
          </div>

          {/* ── ⭐ 4 · THE ELECTRODES UNDERNEATH — the answer ───────────────────────────────── */}
          <div className={styles.electrodes} data-testid="region-electrode-block">
            {e ? (
              <>
                <div className={styles.eLine}>
                  <span className={styles.eCount} data-testid="region-electrode-count">
                    {e.count}
                  </span>
                  <span className={styles.eWord}>
                    electrodes
                    <Help
                      body={
                        'Every mapped electrode whose CENTRE falls inside the rectangle. Not ' +
                        '"wholly inside" — an electrode is a point in the map, its centre being ' +
                        'what the lattice fit measured — and not "within a margin", which would ' +
                        'invent a tolerance nobody asked for.\n' +
                        '\n' +
                        'detected = the pad was seen on the mosaic pixels; inferred = the lattice ' +
                        'says a pad belongs there (occluded or dead), so its centre is computed.'
                      }
                    />
                  </span>
                </div>
                {/* ⭐ R47 — THE COUNT IS THE ANSWER; the breakdown is the working. The rail shows
                    how many electrodes this recording covers, and the span of ids, the seen /
                    inferred split and every id itself live one click down. ⛔ Still all present —
                    a number this feature exists to produce is never hidden, only folded. */}
                {ids.length > 0 && (
                  <details className={styles.details}>
                    <summary className={styles.summary} data-testid="region-electrode-list-toggle">
                      which ones
                    </summary>
                    <div className={styles.eBreakdown}>
                      <span className={styles.eRange} data-testid="region-electrode-range">
                        {ids[0]} … {ids[ids.length - 1]}
                      </span>
                      <span className={styles.eSplit} data-testid="region-electrode-split">
                        {e.detected} detected · {e.inferred} inferred
                      </span>
                    </div>
                    <div className={styles.ids} data-testid="region-electrode-list">
                      {ids.join('  ')}
                    </div>
                  </details>
                )}
              </>
            ) : (
              <p className={styles.empty} data-testid="region-electrodes-none">
                no electrode map was readable for this region
              </p>
            )}
          </div>
        </div>
      </Panel>
    </div>
  );
}
