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
  getRegions,
  locateRegion,
  outputUrl,
  pickOpenFilePath,
  snapRegion,
  updateRegion,
  useJob,
} from '../../api';
import type {
  ElectrodeMapPayload,
  RegionRecord,
  RegionsPayload,
  VideoMosaicDocument,
} from '../../api';
import { Button, Help, Kbd, LiveWarning, Panel, cx } from '../../design';
import { forSubmit, normalisePath } from '../home/pathText';
import { PreviewViewer, type FrameRequest, type ViewFrame } from './PreviewViewer';
import { WorkFrame } from './WorkFrame';
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

const f2 = (v: number): string => v.toFixed(2);
const f3 = (v: number): string => v.toFixed(3);
const f4 = (v: number): string => v.toFixed(4);

/** The file's own name, whatever separators its path used. */
const basenameOf = (p: string): string => p.split(/[\\/]/).filter(Boolean).pop() ?? p;

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

  // the one job this step can hold (locate OR snap — both are `locate_region`, one lease)
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobKind, setJobKind] = useState<'locate' | 'snap' | null>(null);
  const job = useJob(jobId);
  const running = jobId != null && !job.isTerminal;

  // the selection, the pending drop, the readouts
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [drop, setDrop] = useState<{ id: string; x: number; y: number } | null>(null);
  const [banner, setBanner] = useState<{ loud: boolean; message: string } | null>(null);
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

  // ── the job: locate and snap land the same way ──────────────────────────────────────────────
  useEffect(() => {
    if (!jobId || !job.isTerminal) return;
    const kind = jobKind;
    if (job.state === 'failed') {
      setJobError(
        job.error?.message ??
          (kind === 'snap' ? 'The snap failed.' : 'Locating the recording failed.'),
      );
      setJobId(null);
      setJobKind(null);
      return;
    }
    if (job.state === 'done') {
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
          ];
          setBanner({ loud: r.margin_thin || !r.confident, message: parts.join('') });
        }
        if (result.doc) docCb.current?.(result.doc as VideoMosaicDocument);
      }
      void refresh();
    }
    setJobId(null); // done or cancelled
    setJobKind(null);
  }, [jobId, jobKind, job.isTerminal, job.state, job.job, job.error, analysisId, refresh]);

  // ── adding a recording ──────────────────────────────────────────────────────────────────────
  const locate = useCallback(async () => {
    if (running) return;
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
  }, [analysisId, label, path, running]);

  const browse = useCallback(async () => {
    // Native open-file dialog; headless answers 501 and the wrapper falls back to prompt (R38).
    const picked = await pickOpenFilePath({ title: 'Which recording do you want to locate?' });
    if (!picked) return;
    setPath(normalisePath(picked));
  }, []);

  const cancel = useCallback(async () => {
    if (!jobId) return;
    try {
      await cancelJob(jobId);
    } catch {
      /* it already finished — a no-op, not an error to shout about */
    }
  }, [jobId]);

  // ── snap: the drop is posted, never assumed ─────────────────────────────────────────────────
  const snap = useCallback(async () => {
    if (running || !selected) return;
    const at = drop && drop.id === selected.id ? drop : { x: selected.x, y: selected.y };
    setJobError(null);
    setBanner(null);
    try {
      const ref = await snapRegion(analysisId, selected.id, at.x, at.y);
      setJobKind('snap');
      setJobId(ref.job_id);
    } catch (e) {
      setJobError(errMsg(e));
    }
  }, [analysisId, drop, running, selected]);

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
    if (selected && !running) void remove(selected);
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
                    'recording again.'
                  }
                >
                  the mosaic was rebuilt after these were placed —{' '}
                  <b>re-snap before trusting them</b>.
                </LiveWarning>
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

            {running && (
              <div data-testid="regions-progress">
                <Panel
                  title={jobKind === 'snap' ? 'Snapping' : 'Locating recording'}
                  className={vm.progress}
                >
                  <div className={vm.barWell}>
                    <div
                      className={vm.bar}
                      style={{
                        transform: `scaleX(${Math.max(2, Math.min(100, job.pct ?? 0)) / 100})`,
                      }}
                    />
                  </div>
                  <div className={vm.progressRow}>
                    <span className={vm.phase} data-testid="regions-phase">
                      {job.phase ?? 'starting…'}
                      {job.phaseIndex != null && job.nPhases != null
                        ? ` · ${job.phaseIndex + 1}/${job.nPhases}`
                        : ''}
                    </span>
                    <span className={vm.eta} data-testid="regions-eta">
                      {job.etaText ?? ''}
                    </span>
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={() => void cancel()}
                      data-testid="regions-cancel"
                    >
                      Cancel
                    </Button>
                  </div>
                  {job.message && <div className={vm.msg}>{job.message}</div>}
                </Panel>
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
                  return (
                    <div
                      key={r.id}
                      className={cx(
                        styles.item,
                        isSel && styles.itemSel,
                        r.status === 'confirmed' && styles.itemOk,
                      )}
                      data-testid="region-row"
                      data-region-id={r.id}
                      ref={isSel ? selRowRef : undefined}
                      data-selected={isSel || undefined}
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

                        <Button
                          variant="ghost"
                          size="sm"
                          className={styles.del}
                          data-testid="region-delete"
                          title="Delete this region, its still and the project's copy of the recording"
                          disabled={running}
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
                      </span>
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
                busy={running}
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
                  disabled={running}
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
                  disabled={running}
                  data-testid="regions-browse"
                >
                  Browse…
                </Button>
              </div>
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
                  disabled={running}
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
                  disabled={running || forSubmit(path) === ''}
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
