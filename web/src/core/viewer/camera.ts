// The camera math — pure functions over a { scale, tx, ty } matrix, so they are unit-testable
// without a canvas. `tx`/`ty` are the screen-pixel position of world-origin (0, 0); `scale` is
// screen-px per world-px. World coordinates are the image plane; screen coordinates are CSS pixels.

import type { ViewMatrix } from './types';

/** The zoom is clamped to this range everywhere (fit, wheel, 1:1, +/-). Ported from v1. */
export const SCALE_MIN = 0.02;
export const SCALE_MAX = 16;

export const clamp = (v: number, a: number, b: number): number => Math.min(b, Math.max(a, v));

export function screenToWorld(view: ViewMatrix, sx: number, sy: number): [number, number] {
  return [(sx - view.tx) / view.scale, (sy - view.ty) / view.scale];
}

export function worldToScreen(view: ViewMatrix, wx: number, wy: number): [number, number] {
  return [wx * view.scale + view.tx, wy * view.scale + view.ty];
}

/**
 * The new view for a zoom to `scale` that keeps the world point under (sx, sy) fixed on screen.
 * Pure: returns a fresh matrix, clamped to [SCALE_MIN, SCALE_MAX].
 */
export function zoomToView(view: ViewMatrix, scale: number, sx: number, sy: number): ViewMatrix {
  const [wx, wy] = screenToWorld(view, sx, sy);
  const s = clamp(scale, SCALE_MIN, SCALE_MAX);
  return { scale: s, tx: sx - wx * s, ty: sy - wy * s };
}

export interface Bbox {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

/** The view that fits `box` (world rect) into `cssW × cssH` with `pad` px of margin, centred. */
export function fitView(box: Bbox, cssW: number, cssH: number, pad: number): ViewMatrix {
  const scale = clamp(
    Math.min((cssW - pad) / (box.x1 - box.x0), (cssH - pad) / (box.y1 - box.y0)),
    SCALE_MIN,
    SCALE_MAX,
  );
  return {
    scale,
    tx: cssW / 2 - ((box.x0 + box.x1) / 2) * scale,
    ty: cssH / 2 - ((box.y0 + box.y1) / 2) * scale,
  };
}
