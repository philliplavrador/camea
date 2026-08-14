// ─────────────────────────────────────────────────────────────────────────────────────────────
// THE CHIP MAP — every pad that was actually recorded, drawn where it really sits, coloured by
// how much happened on it. Click one to read it.
//
// ⭐ **THE WHOLE CHIP, NOT JUST THE RECORDED BLOCK** (his answer, 2026-08-14, asked with side-by-
// side mockups). The outline is the chip; the dots sit in their real place inside it. Measured on
// his own mirror, that is the difference between seeing that 000690 recorded a corner and 000691
// recorded nearly everything — fill the window with the dots instead and those two look identical.
// It opens fitted to the chip; he zooms in to work.
//
// ⭐ **ONE `<canvas>`, NEVER A DOM NODE PER PAD.** ~1k dots here, and the same rule that governs
// `features/electrodes/GridOverlay` (26,400 positions) applies for the same reason. The camera is
// wheel-zoom-at-pointer + drag-pan, matching `features/videomosaic/PreviewViewer`.
//
// ⚠️ **`core/viewer/Viewer.tsx` COULD NOT BE REUSED, AND PLAN 003 ASSUMED IT COULD.** That viewer
// is built around image tiles and keys its whole lifecycle on image URLs; there is no image here,
// only points. Only `core/viewer/camera.ts`'s pure maths is shared-able, and the gesture handling
// below follows `PreviewViewer` rather than inventing a third convention.
//
// ═════════════════════════════════════════════════════════════════════════════════════════════
// 🔴 **A PAD WITH NO SPIKES IS DRAWN AS A HOLLOW RING, AND IT IS NOT A FAULT.**
// ═════════════════════════════════════════════════════════════════════════════════════════════
// A ring is a different SHAPE, so it can never be misread as "a slightly dim colour" — that is the
// whole point, and it survives being printed in black and white (his call, 2026-08-14).
//
// ⭐ And it means *"nothing was here"*, never *"this one broke"*. His correction, the same day:
// *"of the neurons that are being used not all of them are near neurons"* — among the pads that
// WERE wired up, many simply have no cell near them, so zero spikes is the **ordinary, expected**
// answer. ⛔ Nothing on this screen may call such a pad dead, failed or silent-in-a-bad-way. The
// sentence lives once, in `activityScale.ts :: SILENT_MEANING`.
//
// ⛔ **AND A PAD THAT WAS NEVER WIRED UP IS NOT DRAWN AT ALL** — that is a different fact again
// (the absence of a measurement, not a measurement of absence), and drawing it would invent data.
//
// ⛔ **NO CHIP-SEATING WARNING, EVER.** `features/electrodes/MeaTracePanel` carries one because
// that screen has a microscope in it and has to guess how the chip sat under it. This screen works
// in the chip's own frame, where the file states its own `electrode`/`x_um`/`y_um` and every id is
// exact. Importing that doubt would teach a doubt that does not exist.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { PointerEvent as ReactPointerEvent } from 'react';
import type { MeaChipActivity, MeaChipLayout } from '../../api';
import { Button } from '../../design';
import {
  SCALE_CAVEAT,
  SILENT_MEANING,
  activityScale,
  formatRate,
  rampColour,
} from './activityScale';
import styles from './ChipMap.module.css';

/** How far past fit you may zoom in. A pad is ~17 µm; this is plenty to separate neighbours. */
const MAX_ZOOM_FACTOR = 60;
/** A press that travels no further than this is a click, not a pan. Same slop as PreviewViewer. */
const CLICK_SLOP_PX = 4;
/** A dot never shrinks below this on screen, or a fitted chip is a grey haze. CSS px. */
const MIN_DOT_PX = 1.1;
/** …and never grows past this share of the pitch, so neighbours stay visibly separate. */
const DOT_PITCH_FRACTION = 0.34;

interface View {
  scale: number;
  tx: number;
  ty: number;
}

export interface ChipMapProps {
  layout: MeaChipLayout;
  activity: MeaChipActivity;
  /** The channel currently being read, or null. */
  selected: number | null;
  onSelect: (channel: number) => void;
}

interface Pad {
  channel: number;
  electrode: number;
  x: number;
  y: number;
  nSpikes: number;
  rateHz: number;
  /** Where on the colour ramp, or null when it recorded nothing (⇒ a hollow ring). */
  t: number | null;
}

export function ChipMap({ layout, activity, selected, onSelect }: ChipMapProps) {
  const boxRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [box, setBox] = useState({ w: 0, h: 0 });
  const [view, setView] = useState<View | null>(null);
  const [hover, setHover] = useState<{ pad: Pad; sx: number; sy: number } | null>(null);

  // ── the pads, joined to their tallies and coloured ──────────────────────────────────────────
  // ⭐ The scale is built from THIS recording's rates, every time (I1). `activityScale` is the one
  // place that decides how a rate becomes a colour, and it is HELD pending `docs/MAXWELL.md` —
  // see its header. Nothing in this file knows the mapping.
  const scale = useMemo(
    () => activityScale((activity.pads ?? []).map((p) => p.rate_hz)),
    [activity],
  );

  const pads = useMemo<Pad[]>(() => {
    // The two routes return the same pads in the same order, but join by channel anyway: an
    // index join would fail silently and invisibly if that ever stopped being true, and a chip
    // map showing one pad's activity on another pad's position is the exact failure this app
    // exists to prevent.
    const rates = new Map((activity.pads ?? []).map((p) => [p.channel, p]));
    return (layout.pads ?? []).map((p) => {
      const a = rates.get(p.channel);
      const rateHz = a?.rate_hz ?? 0;
      return {
        channel: p.channel,
        electrode: p.electrode,
        x: p.x_um,
        y: p.y_um,
        nSpikes: a?.n_spikes ?? 0,
        rateHz,
        t: scale.position(rateHz),
      };
    });
  }, [layout, activity, scale]);

  // ── the chip's own extent, in µm ────────────────────────────────────────────────────────────
  // Half a pitch of margin so the outline sits on the chip's edge rather than through the centres
  // of its outermost pads.
  const chip = useMemo(() => {
    const pitch = layout.pitch_um || 1;
    const half = pitch / 2;
    return {
      x0: -half,
      y0: -half,
      w: Math.max(pitch, layout.chip_cols * pitch),
      h: Math.max(pitch, layout.chip_rows * pitch),
      pitch,
    };
  }, [layout]);

  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      setBox({ w: el.clientWidth, h: el.clientHeight });
    });
    ro.observe(el);
    setBox({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  const fitScale = useMemo(() => {
    if (box.w === 0 || box.h === 0) return 0;
    const pad = 16;
    return Math.min((box.w - pad * 2) / chip.w, (box.h - pad * 2) / chip.h);
  }, [box, chip]);

  const fit = useCallback(() => {
    if (!(fitScale > 0)) return;
    setView({
      scale: fitScale,
      tx: (box.w - chip.w * fitScale) / 2 - chip.x0 * fitScale,
      ty: (box.h - chip.h * fitScale) / 2 - chip.y0 * fitScale,
    });
  }, [fitScale, box, chip]);

  // Fit when the picture arrives, when the box first has a size, and on a new recording.
  useEffect(() => {
    setView(null);
  }, [layout.recording_id]);
  useEffect(() => {
    if (view == null && fitScale > 0) fit();
  }, [view, fitScale, fit]);

  // ── wheel = zoom at the pointer ─────────────────────────────────────────────────────────────
  // A native non-passive listener: React's is passive, so it could not `preventDefault` and the
  // page would scroll away underneath the zoom. (`PreviewViewer` learned this first.)
  useEffect(() => {
    const el = boxRef.current;
    if (!el || !(fitScale > 0)) return;
    const onWheel = (e: WheelEvent): void => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      const step = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY;
      setView((v) => {
        if (!v) return v;
        const s = Math.min(fitScale * MAX_ZOOM_FACTOR,
          Math.max(fitScale, v.scale * Math.exp(-step * 0.0022)));
        const k = s / v.scale;
        const sx = e.clientX - r.left;
        const sy = e.clientY - r.top;
        return { scale: s, tx: sx - (sx - v.tx) * k, ty: sy - (sy - v.ty) * k };
      });
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [fitScale]);

  // ── the hit rule ────────────────────────────────────────────────────────────────────────────
  // ⚠️ **THE LESSON R45.7 COST AN AFTERNOON, APPLIED HERE UP FRONT.** A hit radius expressed in
  // world units becomes a sub-pixel target when the picture is zoomed out, and the failures come
  // in bands — which reads to a user as "there are missing patches", not as "my click missed".
  // So: grow the radius to keep a usable on-screen target, and cap it at the cell circumradius so
  // nearest-centre can never take a neighbour's ground.
  const hitRadiusUm = useCallback(
    (s: number): number => Math.min(chip.pitch * Math.SQRT1_2, Math.max(chip.pitch * 0.5, 6 / s)),
    [chip.pitch],
  );

  const padAt = useCallback(
    (sx: number, sy: number, v: View): Pad | null => {
      const wx = (sx - v.tx) / v.scale;
      const wy = (sy - v.ty) / v.scale;
      const r = hitRadiusUm(v.scale);
      let best: Pad | null = null;
      let bestD = r * r;
      for (const p of pads) {
        const dx = p.x - wx;
        const dy = p.y - wy;
        const d = dx * dx + dy * dy;
        if (d <= bestD) {
          bestD = d;
          best = p;
        }
      }
      return best;
    },
    [pads, hitRadiusUm],
  );

  // ── drag = pan; a press that did not travel is a click, and a click selects ──────────────────
  const drag = useRef<{ x: number; y: number; tx: number; ty: number; moved: boolean } | null>(null);
  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>): void => {
    if (!view || e.button !== 0) return;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    drag.current = { x: e.clientX, y: e.clientY, tx: view.tx, ty: view.ty, moved: false };
  };
  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>): void => {
    const d = drag.current;
    const el = boxRef.current;
    if (!el || !view) return;
    const r = el.getBoundingClientRect();
    const sx = e.clientX - r.left;
    const sy = e.clientY - r.top;
    if (d) {
      const dx = e.clientX - d.x;
      const dy = e.clientY - d.y;
      if (!d.moved && Math.hypot(dx, dy) <= CLICK_SLOP_PX) return;
      d.moved = true;
      setHover(null);
      setView({ scale: view.scale, tx: d.tx + dx, ty: d.ty + dy });
      return;
    }
    // ⭐ Hover names the electrode without a click — a `Done when` box.
    const pad = padAt(sx, sy, view);
    setHover(pad ? { pad, sx, sy } : null);
  };
  const onPointerUp = (e: ReactPointerEvent<HTMLDivElement>): void => {
    const d = drag.current;
    drag.current = null;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
    if (!d || d.moved || !view) return;
    const el = boxRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const pad = padAt(e.clientX - r.left, e.clientY - r.top, view);
    if (pad) onSelect(pad.channel);
  };

  // ── the keyboard ────────────────────────────────────────────────────────────────────────────
  // ⚠️ 001 shipped a screen whose only control was untabbable and found it in review. A canvas is
  // the easiest place in the app to leave keyboard-dead, so the arrows step to the nearest pad in
  // that direction — which on a sparse routing is more useful than stepping by array index anyway.
  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>): void => {
    const dirs: Record<string, [number, number]> = {
      ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1],
    };
    const dir = dirs[e.key];
    if (!dir) return;
    e.preventDefault();
    const from = pads.find((p) => p.channel === selected) ?? null;
    if (!from) {
      if (pads[0]) onSelect(pads[0].channel);
      return;
    }
    let best: Pad | null = null;
    let bestScore = Infinity;
    for (const p of pads) {
      if (p === from) continue;
      const dx = p.x - from.x;
      const dy = p.y - from.y;
      const along = dx * dir[0] + dy * dir[1];
      if (along <= 0) continue;                       // not in the direction pressed
      const across = Math.abs(dx * dir[1] - dy * dir[0]);
      const score = along + across * 3;               // prefer straight ahead over far off-axis
      if (score < bestScore) {
        bestScore = score;
        best = p;
      }
    }
    if (best) onSelect(best.channel);
  };

  // ── the drawing ─────────────────────────────────────────────────────────────────────────────
  useEffect(() => {
    const cvs = canvasRef.current;
    if (!cvs || !view || box.w === 0 || box.h === 0) return;
    const dpr = window.devicePixelRatio || 1;
    const bw = Math.round(box.w * dpr);
    const bh = Math.round(box.h * dpr);
    if (cvs.width !== bw || cvs.height !== bh) {
      cvs.width = bw;
      cvs.height = bh;
    }
    const g = cvs.getContext('2d');
    if (!g) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, box.w, box.h);

    const sx = (x: number): number => x * view.scale + view.tx;
    const sy = (y: number): number => y * view.scale + view.ty;

    // The chip's outline first — it is the frame everything else is read against.
    const css = getComputedStyle(cvs);
    g.strokeStyle = css.getPropertyValue('--chip-outline').trim() || 'rgba(120, 190, 255, 0.55)';
    g.lineWidth = 1;
    g.strokeRect(sx(chip.x0), sy(chip.y0), chip.w * view.scale, chip.h * view.scale);

    const rad = Math.max(MIN_DOT_PX, chip.pitch * view.scale * DOT_PITCH_FRACTION);
    const m = 8;
    const ringCol = css.getPropertyValue('--chip-ring').trim() || 'rgba(150, 160, 175, 0.75)';

    // Pads that fired: filled with their colour. Grouped by colour would save state changes, but
    // ~1k arcs is nothing and per-pad fill keeps this readable.
    for (const p of pads) {
      const px = sx(p.x);
      if (px < -m || px > box.w + m) continue;
      const py = sy(p.y);
      if (py < -m || py > box.h + m) continue;
      g.beginPath();
      g.arc(px, py, rad, 0, Math.PI * 2);
      if (p.t == null) {
        // 🔴 A HOLLOW RING — no colour, because "no spikes" is not a position on the ramp. It
        // means nothing was near this pad, not that anything failed. See the header.
        g.strokeStyle = ringCol;
        g.lineWidth = Math.max(0.8, rad * 0.32);
        g.stroke();
      } else {
        g.fillStyle = rampColour(p.t);
        g.fill();
      }
    }

    // The selection last, on top of everything.
    const sel = pads.find((p) => p.channel === selected);
    if (sel) {
      const px = sx(sel.x);
      const py = sy(sel.y);
      g.beginPath();
      g.arc(px, py, rad + 3.5, 0, Math.PI * 2);
      g.strokeStyle = css.getPropertyValue('--chip-select').trim() || '#ffffff';
      g.lineWidth = 2;
      g.stroke();
    }
  }, [pads, view, box, chip, selected]);

  const hoverLabel = hover
    ? `Electrode ${hover.pad.electrode} · channel ${hover.pad.channel} · ` +
      (hover.pad.nSpikes === 0
        ? SILENT_MEANING
        : `${hover.pad.nSpikes.toLocaleString()} spikes · ${formatRate(hover.pad.rateHz)}`)
    : '';

  return (
    <div className={styles.wrap} data-testid="mea-chip-map">
      <div className={styles.toolbar}>
        <span className={styles.where} data-testid="mea-chip-extent">
          {layout.chip_cols.toLocaleString()} × {layout.chip_rows.toLocaleString()} pads
          {layout.chip_extent === 'recorded' ? ' recorded' : ' on the chip'} ·{' '}
          <b>{(layout.pads?.length ?? 0).toLocaleString()}</b> wired up for this recording
        </span>
        <Button size="sm" variant="ghost" onClick={fit} data-testid="mea-chip-fit">
          Fit
        </Button>
      </div>

      <div
        ref={boxRef}
        className={styles.stage}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={() => setHover(null)}
        onKeyDown={onKeyDown}
        tabIndex={0}
        role="application"
        aria-label={
          `The chip: ${layout.pads?.length ?? 0} recorded pads of a ` +
          `${layout.chip_cols} by ${layout.chip_rows} array, coloured by how much happened on each. ` +
          'Arrow keys move between pads.'
        }
      >
        <canvas ref={canvasRef} className={styles.canvas} data-testid="mea-chip-canvas" />
        {hover && (
          <div
            className={styles.tip}
            style={{ left: hover.sx, top: hover.sy }}
            data-testid="mea-chip-hover"
          >
            {hoverLabel}
          </div>
        )}
      </div>

      <ChipLegend scale={scale} />
    </div>
  );
}

/**
 * The legend. ⭐ **In real units** — spikes per second — with the caveat that equal colour steps
 * are not equal rate steps, because the provisional scale spreads the colours out.
 *
 * ⭐ And the ring is in the legend beside the colours, saying what it means in his terms.
 */
function ChipLegend({ scale }: { scale: ReturnType<typeof activityScale> }) {
  return (
    <div className={styles.legend} data-testid="mea-chip-legend">
      <div className={styles.ramp}>
        <span className={styles.rampEnd}>quiet</span>
        {scale.legend.map((s) => (
          <span key={s.t} className={styles.swatch} style={{ background: s.colour }}>
            <span className={styles.swatchLabel}>{formatRate(s.rateHz)}</span>
          </span>
        ))}
        <span className={styles.rampEnd}>busy</span>
      </div>
      <div className={styles.legendRow} data-testid="mea-chip-legend-silent">
        <span className={styles.ringSwatch} aria-hidden="true" />
        <span>
          {SILENT_MEANING} — <b>{scale.nSilent.toLocaleString()}</b> of{' '}
          {(scale.nSilent + scale.nLive).toLocaleString()} recorded pads
        </span>
      </div>
      <p className={styles.caveat}>{SCALE_CAVEAT}</p>
    </div>
  );
}
