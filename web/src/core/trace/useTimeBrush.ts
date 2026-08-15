// ─────────────────────────────────────────────────────────────────────────────────────────────
// THE TIME BRUSH — drag sideways across a picture to pick the stretch you want to look at.
//
// ⭐ **A BAND, NOT A BOX** — matplotlib's `SpanSelector`, deliberately not its `RectangleSelector`.
// The band is full height and its height means nothing: only the two x positions are read. A box
// you could size vertically would promise that the voltage axis was being zoomed too, and it is
// not. This hook reports a **time range** and nothing else.
//
// 🔴 **A CLICK IS NOT A ZOOM.** Release within `CLICK_SLOP_PX` of the press and the gesture is
// refused outright — no range reported, and therefore no history entry pushed. matplotlib's exact
// threshold and matplotlib's exact reason ("a threshold that allows the user to cancel a zoom
// action"). Without it every stray click on the chart would bury the place he was in a pile of
// identical history entries.
//
// 🔴 **THE LEFT GUTTER IS NOT A TIME.** The chart reserves space on the left for its y labels
// (`TraceChart`'s `PAD_L`), and an x inside it does not correspond to any moment in the recording.
// A press starting there — or in the right, top or bottom padding — is ignored outright rather
// than clamped, because clamping would silently turn "I pressed on the label" into "I pressed at
// t = 0". The paddings arrive as an argument; this file does not know what they are.
//
// ⚠️ **NOT ONE NUMBER HERE IS ABOUT HIS DATA.** The zoom floor arrives as `minSpanS` and the
// caller derives it from the recording's own sample rate. No sample rate, no duration and no
// window width may ever be written down in this file (HARD RULE: no dataset knowledge in app
// code). `CLICK_SLOP_PX` is a property of a human hand on a mouse, not of a recording.
//
// ⚠️ **The gesture is measured against the picture that was on screen when it started.** The plot
// rectangle and the time axis are read once, at the press, and held for the whole drag — so a
// container that resizes or a fetch that lands mid-drag cannot move the axis under his hand.
//
// The hook does no drawing. It reports `{ dragging, x0, x1 }` and the caller paints the band.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { useCallback, useEffect, useRef, useState } from 'react';
import type { PointerEvent as ReactPointerEvent } from 'react';
import type { TimeView } from './viewStack';

/** The space a chart reserves around its plot area, in CSS px — `TraceChart`'s `PAD_*`. */
export interface PlotPad {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

/** The plot area itself, in CSS px measured from the element's top-left corner. */
export interface PlotRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

/**
 * Release this close to the press and it was a click, not a zoom. matplotlib's threshold, in CSS
 * px so it means the same thing on every display density.
 */
export const CLICK_SLOP_PX = 5;

const clamp = (v: number, a: number, b: number): number => Math.min(b, Math.max(a, v));

/**
 * Where the picture lives inside an element of `cssW × cssH`. Mirrors `TraceChart`'s own
 * arithmetic, including its 1 px floor — a panel narrower than its own gutters must still produce
 * a usable rect rather than a negative width.
 */
export function plotRect(cssW: number, cssH: number, pad: PlotPad): PlotRect {
  return {
    left: pad.left,
    top: pad.top,
    width: Math.max(1, cssW - pad.left - pad.right),
    height: Math.max(1, cssH - pad.top - pad.bottom),
  };
}

/** Is this point on the picture (rather than on a label or in the margin)? */
export function inPlot(x: number, y: number, rect: PlotRect): boolean {
  return (
    x >= rect.left && x <= rect.left + rect.width && y >= rect.top && y <= rect.top + rect.height
  );
}

/**
 * The moment an x position points at, given the range the picture is showing.
 * **Clipped at both gutters**: an x left of the plot reads as `t0`, an x right of it as `t1`, so a
 * drag that runs off the edge selects to the edge instead of off the end of the recording.
 */
export function timeAtX(x: number, rect: PlotRect, t0: number, t1: number): number {
  const f = clamp((x - rect.left) / rect.width, 0, 1);
  return t0 + f * (t1 - t0);
}

/**
 * The inverse — where a moment sits on screen. Not clipped: like `TraceChart`'s own `xOf`, it may
 * return a position outside the plot, and the caller clips when it draws.
 */
export function xAtTime(t: number, rect: PlotRect, t0: number, t1: number): number {
  const span = Math.max(1e-9, t1 - t0); // the same guard TraceChart uses on a zero-width axis
  return rect.left + ((t - t0) / span) * rect.width;
}

/**
 * The range a drag from `xa` to `xb` chose — or `null` when it must be refused, silently.
 *
 * Refused in exactly two cases, and they are refused the same way so neither can push a history
 * entry: the release was within `CLICK_SLOP_PX` of the press (a click), or the resulting range is
 * narrower than `minSpanS` (a zoom past what the stored samples can actually resolve).
 *
 * Right-to-left is identical to left-to-right — the pair is normalised, never rejected.
 */
export function brushRange(
  xa: number,
  xb: number,
  rect: PlotRect,
  t0: number,
  t1: number,
  minSpanS: number,
): TimeView | null {
  if (Math.abs(xb - xa) < CLICK_SLOP_PX) return null;
  const a = timeAtX(Math.min(xa, xb), rect, t0, t1);
  const b = timeAtX(Math.max(xa, xb), rect, t0, t1);
  // Written as a positive test so a NaN anywhere in the arithmetic refuses rather than escapes.
  if (!(b > a) || !(b - a >= minSpanS)) return null;
  return { t0: a, t1: b };
}

export interface TimeBrushOptions {
  /** The range the picture is currently showing — the axis the pointer is read against. */
  t0: number;
  t1: number;
  /** The chart's padding, in CSS px. `TraceChart` exports these; pass them straight through. */
  pad: PlotPad;
  /**
   * The narrowest stretch worth zooming to, in seconds. A narrower drag is refused exactly like a
   * click. ⛔ Derive it from the recording (its sample rate arrives on the payload) — this hook
   * must never learn a rate.
   */
  minSpanS: number;
  /** Called once, on release, with the chosen range. Never called for a refused gesture. */
  onSelect: (view: TimeView) => void;
}

export interface TimeBrush {
  /** True while a drag is in flight — paint the band, and nothing else. */
  dragging: boolean;
  /**
   * The band to paint, in CSS px from the element's left edge. Normalised (`x0 <= x1`) and clipped
   * to the plot area, so it never paints over the number gutter. Meaningless when not dragging.
   */
  x0: number;
  x1: number;
  /** Spread onto the element carrying the picture (the canvas, or an overlay the same size). */
  handlers: {
    onPointerDown: (e: ReactPointerEvent<HTMLElement>) => void;
    onPointerMove: (e: ReactPointerEvent<HTMLElement>) => void;
    onPointerUp: (e: ReactPointerEvent<HTMLElement>) => void;
    onPointerCancel: (e: ReactPointerEvent<HTMLElement>) => void;
  };
}

/** Everything the gesture froze at the press. Nothing in here changes until it ends. */
interface Drag {
  pointerId: number;
  rect: PlotRect;
  /** The element's left edge in client coords, so a move event becomes an element-relative x. */
  originX: number;
  t0: number;
  t1: number;
  minSpanS: number;
  /** The press, raw and unclipped — the `CLICK_SLOP_PX` test is measured on it. */
  startX: number;
  /** The band, normalised and clipped, for painting. */
  x0: number;
  x1: number;
}

function band(d: Drag, x: number): Drag {
  const a = clamp(d.startX, d.rect.left, d.rect.left + d.rect.width);
  const b = clamp(x, d.rect.left, d.rect.left + d.rect.width);
  return { ...d, x0: Math.min(a, b), x1: Math.max(a, b) };
}

export function useTimeBrush({ t0, t1, pad, minSpanS, onSelect }: TimeBrushOptions): TimeBrush {
  const [drag, setDrag] = useState<Drag | null>(null);
  // The captured element is kept out of state: releasing capture is a side effect, and a state
  // updater is not allowed to have one.
  const captured = useRef<{ el: HTMLElement; pointerId: number } | null>(null);

  const release = useCallback((): void => {
    const c = captured.current;
    captured.current = null;
    // `releasePointerCapture` throws for a pointer we never captured, so ask first. Both calls are
    // optional-chained: jsdom implements neither, and the unit tests must not need them.
    if (c?.el.hasPointerCapture?.(c.pointerId)) c.el.releasePointerCapture?.(c.pointerId);
  }, []);

  // ── Esc cancels a drag in flight, AND NOTHING ELSE ──────────────────────────────────────────
  // ⚠️ The listener exists ONLY while a drag is in flight and is removed the instant it ends, so
  // there is no standing global Esc handler to collide with the app's other meanings for the key
  // (R45.3 scopes Esc explicitly; R14 — Esc must not kill the sweep — is untouched). It cannot be
  // an element handler instead: the pointer is captured and focus may be anywhere on the page.
  // It stops propagation because one press should cancel the drag *or* do the page's thing, never
  // both at once.
  const dragging = drag !== null;
  useEffect(() => {
    if (!dragging) return;
    const onKey = (e: KeyboardEvent): void => {
      if (e.key !== 'Escape') return;
      e.stopPropagation();
      release();
      setDrag(null);
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [dragging, release]);

  // Unmounting mid-drag (he clicks another pad) must not leave the pointer captured.
  useEffect(() => release, [release]);

  const onPointerDown = (e: ReactPointerEvent<HTMLElement>): void => {
    if (e.button !== 0 || drag) return;
    const el = e.currentTarget;
    const r = el.getBoundingClientRect();
    const rect = plotRect(r.width, r.height, pad);
    const x = e.clientX - r.left;
    const y = e.clientY - r.top;
    if (!inPlot(x, y, rect)) return; // a label is not a time — see the header
    // ⭐ Capture, so a drag that leaves the canvas still completes on release. Without it, letting
    // go over the panel beside the chart would strand the band on screen forever.
    el.setPointerCapture?.(e.pointerId);
    captured.current = { el, pointerId: e.pointerId };
    setDrag(
      band(
        {
          pointerId: e.pointerId,
          rect,
          originX: r.left,
          t0,
          t1,
          minSpanS,
          startX: x,
          x0: x,
          x1: x,
        },
        x,
      ),
    );
  };

  const onPointerMove = (e: ReactPointerEvent<HTMLElement>): void => {
    if (!drag || e.pointerId !== drag.pointerId) return;
    setDrag(band(drag, e.clientX - drag.originX));
  };

  const onPointerUp = (e: ReactPointerEvent<HTMLElement>): void => {
    // ⚠️ Guard on the id BEFORE releasing: a second finger going up must not drop the capture the
    // first one is still holding.
    if (!drag || e.pointerId !== drag.pointerId) return;
    release();
    setDrag(null);
    const chosen = brushRange(
      drag.startX,
      e.clientX - drag.originX,
      drag.rect,
      drag.t0,
      drag.t1,
      drag.minSpanS,
    );
    if (chosen) onSelect(chosen);
  };

  const onPointerCancel = (e: ReactPointerEvent<HTMLElement>): void => {
    if (!drag || e.pointerId !== drag.pointerId) return;
    release();
    setDrag(null);
  };

  return {
    dragging,
    x0: drag?.x0 ?? 0,
    x1: drag?.x1 ?? 0,
    handlers: { onPointerDown, onPointerMove, onPointerUp, onPointerCancel },
  };
}
