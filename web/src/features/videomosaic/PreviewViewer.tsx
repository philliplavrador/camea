// THE MOSAIC VIEWER — one camera, mounted by every step that shows the built mosaic.
//
// Extracted from `VideoMosaicFeature` when a SECOND step needed it (locating region recordings,
// 2026-08-11). Two screens sharing a camera by copy would drift, and the drift would show up as
// "the rectangle is in the wrong place on this tab" — a bug about geometry that is really a bug
// about duplication.
//
// ⭐ THE OVERLAY CONTRACT. `overlay` is handed the live view matrix and the stage size and renders
// into an absolutely-positioned layer ABOVE the picture, in SCREEN space: `screen = world * scale
// + t`, the one convention `core/viewer/camera.ts` and `features/electrodes/GridOverlay` also use.
// An overlay that wants to be dragged puts `pointer-events: auto` on its own node and calls
// `stopPropagation()` on pointerdown — otherwise the press below is a pan, which is correct for
// everywhere it is NOT over the interactive node.

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type PointerEvent as ReactPointerEvent,
} from 'react';
import type { ElectrodeMapPayload } from '../../api';
import { videoOutputUrl } from '../../api';
import { cx } from '../../design';
import { type ElectrodeSelection } from '../electrodes/ElectrodePanel';
import { GridOverlay, IDS_MIN_STEP_PX } from '../electrodes/GridOverlay';
import { hitRadiusAt } from '../electrodes/lookup';
import styles from './VideoMosaicFeature.module.css';

/** The live camera, as an overlay sees it. `screen = world * scale + t`. */
export interface ViewFrame {
  scale: number;
  tx: number;
  ty: number;
  /** The stage's CSS size, for culling. */
  width: number;
  height: number;
}

/**
 * An outside request to point the camera at a world-space rectangle (`frameTo`). It is a REQUEST,
 * not state: the camera moves once per `nonce` and never again, so a re-render cannot yank the view
 * back from wherever the user has panned it since.
 */
export interface FrameRequest {
  x: number;
  y: number;
  w: number;
  h: number;
  /** Bumped by the caller per request, so asking for the same rectangle twice still frames. */
  nonce: number;
}

// ── The preview — a real zoom/pan viewer over the built mosaic ────────────────────────────────
//
// ⭐ 100 % MEANS 100 % OF THE MOSAIC (2026-08-07). This viewer used to show `preview.png` in both
// states — 2048 px on the long side, 7.3 % of the pixels of a 5331×7552 build — so "view at 100%"
// was a 3.7× lie and the real file, sitting on disk behind a working route the whole time, was
// never once requested. Zooming now fetches `mosaic.png`. The browser was never the bottleneck:
// Chrome decodes the full 40 Mpx file in ~80 ms against a 2²⁹-pixel ceiling. The small preview
// still serves the fit view, so the screen paints instantly after a build; the full file is
// fetched the moment the zoom passes the point where the preview would blur, and layered ON TOP so
// the picture never blanks.
//
// ⭐ **WHEEL TO ZOOM, DRAG TO PAN (2026-08-11).** It used to be a scroll box with a fit ↔ 100 %
// toggle, and that was enough while the screen was only ever *looked* at. Identification made it a
// working surface: at fit, his 5319×7356 mosaic draws 1024 px wide, so an electrode is 5.9 CSS px
// and pointing at one is not a thing a hand can do. Now the camera is continuous between fit and
// 8×, the click identifies whatever the current zoom can honestly resolve (R45.7), and the mapped
// lattice is DRAWN — outline when zoomed out, pad dots as they become separable, ids when there is
// room for text. "Which electrode is this?" is answerable by eye before you even click.

interface ViewState {
  scale: number; // CSS px per mosaic px
  tx: number; //   screen x of mosaic x=0
  ty: number;
}

/** Zoom ceiling — 8 mosaic px per CSS px is well past the point where the pixels themselves show. */
const MAX_SCALE = 8;
/** A framed rectangle's longer side fills about this much of the shorter viewport side. */
const FRAME_FILL = 0.5;
/** `preview.png` is ~2048 px on the long side; past this the full file is worth its bytes. */
const FULL_RES_ABOVE = 0.34;
/** A press that travels further than this is a pan, not an identification click. */
const CLICK_SLOP_PX = 4;

export function PreviewViewer({
  analysisId,
  builtAt,
  canvas,
  payload,
  selection,
  onPick,
  showGrid = true,
  overlay,
  extraTools,
  frameTo,
}: {
  analysisId: string;
  builtAt: string | null;
  canvas: { w: number; h: number } | null;
  payload: ElectrodeMapPayload | null;
  selection: ElectrodeSelection | null;
  onPick?: (x: number, y: number, scale: number) => void;
  /** The electrode lattice layer. Off on screens whose subject is something else. */
  showGrid?: boolean;
  /** Draw in screen space above the picture — see the overlay contract at the top of the file. */
  overlay?: (v: ViewFrame) => ReactNode;
  /** Extra buttons for the zoom bar, so a step can add its own without forking the camera. */
  extraTools?: ReactNode;
  /** Point the camera at a world rectangle, once per `nonce` — see `FrameRequest`. */
  frameTo?: FrameRequest | null;
}) {
  const boxRef = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({ w: 0, h: 0 });
  const [view, setView] = useState<ViewState | null>(null);
  const [idsOn, setIdsOn] = useState(false);
  const [fullReady, setFullReady] = useState(false);
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);

  // The map exists AND the build told us the canvas: a plain click identifies. Without the canvas
  // size the preview's own pixels are the only frame there is, and the map's coordinates would not
  // mean anything in it — so identification stays off rather than answering with a guess.
  const identify = payload != null && canvas != null && onPick != null;
  // ⚠️ DRAWING the lattice and CLICKING it are different permissions. A step that shows the map as
  // context (the regions step) wants the dots and the array outline without turning the picture
  // into an electrode picker — so the layer keys off `showGrid`, never off `identify`.
  const drawGrid = payload != null && canvas != null && showGrid;

  // ── the camera ────────────────────────────────────────────────────────────────────────────────
  // The mosaic's own size drives the camera. It comes from the build block; if a build ever lands
  // without one, the preview's natural size stands in — a viewer with no picture is not an option.
  const world = canvas ?? natural;
  const fitScale = world && box.w > 0 ? Math.min(box.w / world.w, box.h / world.h) : 0;

  /** Keep the picture on the stage: centred while it is smaller than the box, inside it when not. */
  const clampView = useCallback(
    (v: ViewState): ViewState => {
      if (!world) return v;
      const w = world.w * v.scale;
      const h = world.h * v.scale;
      const axis = (t: number, drawn: number, avail: number): number =>
        drawn <= avail ? (avail - drawn) / 2 : Math.min(0, Math.max(avail - drawn, t));
      return { scale: v.scale, tx: axis(v.tx, w, box.w), ty: axis(v.ty, h, box.h) };
    },
    [world, box.w, box.h],
  );

  const setScaleAt = useCallback(
    (next: number, sx: number, sy: number) => {
      setView((v) => {
        if (!v || !world) return v;
        const s = Math.min(MAX_SCALE, Math.max(fitScale, next));
        if (s === v.scale) return v;
        const k = s / v.scale;
        return clampView({ scale: s, tx: sx - (sx - v.tx) * k, ty: sy - (sy - v.ty) * k });
      });
    },
    [world, clampView, fitScale],
  );

  const fitNow = useCallback(() => {
    if (!world || box.w === 0) return;
    setView(clampView({ scale: fitScale, tx: 0, ty: 0 }));
  }, [world, box.w, clampView, fitScale]);

  // Measure the stage; fit the first time it and the canvas are both known.
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const measure = (): void => setBox({ w: el.clientWidth, h: el.clientHeight });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    // A new build invalidates the loaded pixels and the camera alike.
    setFullReady(false);
    setView(null);
  }, [builtAt]);

  useEffect(() => {
    if (view == null) fitNow();
    else setView((v) => (v ? clampView(v) : v)); // a resize must not strand the picture off-stage
  }, [view == null, fitNow, clampView]); // eslint-disable-line react-hooks/exhaustive-deps

  // ⭐ Frame a rectangle ON REQUEST — centred, at the zoom where its longer side fills FRAME_FILL
  // of the shorter viewport side, clamped to the same [fit, MAX_SCALE] range the wheel obeys. The
  // `nonce` guard is what keeps this a one-shot: the deps re-run on every resize and camera change,
  // and a request already honoured must never fire again mid-pan.
  const framed = useRef(0);
  useEffect(() => {
    if (!frameTo || frameTo.nonce === framed.current) return;
    if (!world || box.w === 0 || box.h === 0 || fitScale === 0) return;
    framed.current = frameTo.nonce;
    const s = Math.min(
      MAX_SCALE,
      Math.max(fitScale, (FRAME_FILL * Math.min(box.w, box.h)) / Math.max(frameTo.w, frameTo.h, 1)),
    );
    setView(
      clampView({
        scale: s,
        tx: box.w / 2 - (frameTo.x + frameTo.w / 2) * s,
        ty: box.h / 2 - (frameTo.y + frameTo.h / 2) * s,
      }),
    );
  }, [frameTo, world, box.w, box.h, fitScale, clampView]);

  // Wheel = zoom at the pointer. A native non-passive listener: React's is passive, so it could not
  // preventDefault and the page would scroll away underneath the zoom.
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent): void => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      const step = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY; // lines vs pixels
      setView((v) =>
        v
          ? ((): ViewState => {
              const s = Math.min(MAX_SCALE, Math.max(fitScale, v.scale * Math.exp(-step * 0.0022)));
              const k = s / v.scale;
              const sx = e.clientX - r.left;
              const sy = e.clientY - r.top;
              return clampView({ scale: s, tx: sx - (sx - v.tx) * k, ty: sy - (sy - v.ty) * k });
            })()
          : v,
      );
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [clampView, fitScale]);

  // Drag = pan. A press that did not travel is a click, and a click identifies. The pointer is
  // CAPTURED for the drag, so a pan that runs off the stage keeps panning and still ends cleanly.
  const drag = useRef<{ x: number; y: number; tx: number; ty: number; moved: boolean } | null>(null);
  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>): void => {
    if (!view || e.button !== 0) return;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    drag.current = { x: e.clientX, y: e.clientY, tx: view.tx, ty: view.ty, moved: false };
  };
  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>): void => {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (!d.moved && Math.hypot(dx, dy) <= CLICK_SLOP_PX) return;
    d.moved = true;
    setView((v) => (v ? clampView({ scale: v.scale, tx: d.tx + dx, ty: d.ty + dy }) : v));
  };
  const onPointerUp = (e: ReactPointerEvent<HTMLDivElement>): void => {
    const d = drag.current;
    drag.current = null;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
    if (!d || d.moved || !view || !identify) return;
    const el = boxRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    onPick?.(
      (e.clientX - r.left - view.tx) / view.scale,
      (e.clientY - r.top - view.ty) / view.scale,
      view.scale,
    );
  };

  const wantFull = (view?.scale ?? 0) > FULL_RES_ABOVE || fullReady;
  const loading = wantFull && !fullReady;
  const zoomPct = view ? Math.round(view.scale * 100) : null;
  const atFit = view != null && fitScale > 0 && Math.abs(view.scale - fitScale) < 1e-6;
  const marker =
    payload && selection && view
      ? {
          left: selection.hit.centerX * view.scale + view.tx,
          top: selection.hit.centerY * view.scale + view.ty,
          d: Math.max(12, hitRadiusAt(payload, view.scale) * view.scale * 2),
        }
      : null;

  return (
    <div className={styles.viewerWrap}>
      <div
        className={styles.viewer}
        data-testid="vm-viewer"
        ref={boxRef}
        data-fit={atFit || undefined}
        data-loading={loading || undefined}
        data-identify={identify || undefined}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={() => (drag.current = null)}
        onDoubleClick={(e) => {
          const el = boxRef.current;
          if (!el || !view) return;
          const r = el.getBoundingClientRect();
          setScaleAt(view.scale * 2, e.clientX - r.left, e.clientY - r.top);
        }}
        title={
          identify
            ? 'Click an electrode to identify it · wheel to zoom · drag to pan'
            : 'Wheel to zoom · drag to pan'
        }
      >
        <div
          className={styles.world}
          style={
            view && world
              ? {
                  width: world.w,
                  height: world.h,
                  transform: `translate(${view.tx}px, ${view.ty}px) scale(${view.scale})`,
                }
              : { width: 'auto', height: 'auto' }
          }
        >
          {/* The small file paints immediately and stays as the base; the full one layers over it
              once decoded, so zooming never blanks the picture. */}
          <img
            className={styles.preview}
            data-testid="vm-preview"
            alt="Mosaic preview"
            src={videoOutputUrl(analysisId, 'preview.png', builtAt)}
            onLoad={(e) =>
              setNatural({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })
            }
            draggable={false}
          />
          {wantFull && (
            <img
              className={styles.previewFull}
              data-testid="vm-preview-full"
              data-ready={fullReady || undefined}
              alt=""
              aria-hidden="true"
              src={videoOutputUrl(analysisId, 'mosaic.png', builtAt)}
              onLoad={() => setFullReady(true)}
              draggable={false}
            />
          )}
        </div>

        {payload && view && drawGrid && (
          <GridOverlay
            payload={payload}
            scale={view.scale}
            tx={view.tx}
            ty={view.ty}
            width={box.w}
            height={box.h}
            idsOn={idsOn}
            className={styles.gridLayer}
          />
        )}

        {marker && selection && (
          <div
            className={styles.vmMarker}
            data-testid="vm-electrode-marker"
            data-electrode={selection.hit.electrode}
            style={{
              left: marker.left,
              top: marker.top,
              width: marker.d,
              height: marker.d,
            }}
          >
            <span className={styles.vmMarkerLabel}>{selection.hit.electrode}</span>
          </div>
        )}

        {/* ⭐ The step's own layer, in SCREEN space, above the picture and below the note. */}
        {overlay && view && overlay({ ...view, width: box.w, height: box.h })}

        {loading && <div className={styles.viewerNote}>loading full resolution…</div>}
      </div>

      <div className={styles.zoomBar}>
        <button
          type="button"
          className={styles.zoomBtn}
          data-testid="vm-zoom-out"
          onClick={() => setScaleAt((view?.scale ?? 1) / 1.6, box.w / 2, box.h / 2)}
          title="Zoom out"
        >
          −
        </button>
        <span className={styles.zoomLevel} data-testid="vm-zoom-level">
          {zoomPct != null ? `${zoomPct}%` : '—'}
        </span>
        <button
          type="button"
          className={styles.zoomBtn}
          data-testid="vm-zoom-in"
          onClick={() => setScaleAt((view?.scale ?? 1) * 1.6, box.w / 2, box.h / 2)}
          title="Zoom in"
        >
          +
        </button>
        <button
          type="button"
          className={styles.zoomBtn}
          data-testid="vm-zoom-toggle"
          onClick={() => (atFit ? setScaleAt(1, box.w / 2, box.h / 2) : fitNow())}
          title={atFit ? 'View the full-resolution mosaic' : 'Fit the whole mosaic'}
        >
          {atFit ? '100%' : 'Fit'}
        </button>
        {extraTools}
        {drawGrid && (
          <button
            type="button"
            role="switch"
            aria-checked={idsOn}
            className={cx(styles.zoomBtn, idsOn && styles.zoomBtnOn)}
            data-testid="vm-electrode-ids-toggle"
            onClick={() => setIdsOn((v) => !v)}
            title={`Label every visible electrode (from ${IDS_MIN_STEP_PX} px between centres — zoom in)`}
          >
            IDs
          </button>
        )}
      </div>
    </div>
  );
}

