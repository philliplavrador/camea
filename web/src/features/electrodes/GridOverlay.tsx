// THE MAPPED LATTICE, DRAWN — the shared overlay both identification screens mount (the snapshot
// Electrodes step and the videomosaic screen). It answers "what got mapped, and where is electrode
// 47-113?" by eye, before anything is clicked.
//
// One <canvas> in SCREEN space, redrawn from the view matrix — never a DOM node per cell: a real
// map is 26 400 positions, and 26 400 spans would cost more than the mosaic underneath. The canvas
// layers under the tiles are never touched by this (R20).
//
// Detail follows the zoom, because drawing what cannot be resolved is noise:
//   any zoom          the array OUTLINE (from the mean lattice vectors — the frame of the map)
//   ≥ 5 px apart      a dot per pad: green detected on the pixels, amber inferred from the lattice
//   ≥ 34 px apart     the col-row id under each dot, while `idsOn`

import { useEffect, useRef } from 'react';
import type { ElectrodeMapPayload } from '../../api';

/** Pad dots appear once neighbouring centres are at least this far apart on screen, CSS px. */
export const DOTS_MIN_STEP_PX = 5;
/** …and ids once there is room to read one. */
export const IDS_MIN_STEP_PX = 34;

const DETECTED = 'rgba(110, 231, 160, 0.75)';
const INFERRED = 'rgba(255, 196, 61, 0.85)';
const OUTLINE = 'rgba(120, 190, 255, 0.55)';

export interface GridOverlayProps {
  payload: ElectrodeMapPayload;
  /** The view matrix of the surface underneath: screen = world × scale + t. */
  scale: number;
  tx: number;
  ty: number;
  /** The stage's CSS size. */
  width: number;
  height: number;
  idsOn?: boolean;
  className?: string;
}

/** The cells' own origin: where centre (col 1, row 1) sits, averaged over every cell so a single
 *  drifted cell cannot tilt the frame. Cheap enough to redo per draw (one pass over the arrays). */
function latticeOrigin(payload: ElectrodeMapPayload): [number, number] {
  const { col, row, x, y } = payload.cells;
  const [a1x, a1y] = payload.a1;
  const [a2x, a2y] = payload.a2;
  let ox = 0;
  let oy = 0;
  for (let i = 0; i < col.length; i++) {
    ox += x[i] - (col[i] - 1) * a1x - (row[i] - 1) * a2x;
    oy += y[i] - (col[i] - 1) * a1y - (row[i] - 1) * a2y;
  }
  const n = Math.max(1, col.length);
  return [ox / n, oy / n];
}

export function GridOverlay({
  payload,
  scale,
  tx,
  ty,
  width,
  height,
  idsOn = false,
  className,
}: GridOverlayProps) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const cvs = ref.current;
    if (!cvs || width === 0 || height === 0) return;
    const dpr = window.devicePixelRatio || 1;
    const bw = Math.round(width * dpr);
    const bh = Math.round(height * dpr);
    if (cvs.width !== bw || cvs.height !== bh) {
      cvs.width = bw;
      cvs.height = bh;
    }
    const g = cvs.getContext('2d');
    if (!g) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, width, height);
    if (!(scale > 0)) return;

    const sx = (x: number): number => x * scale + tx;
    const sy = (y: number): number => y * scale + ty;
    const { col, row, x, y, kind } = payload.cells;
    const [a1x, a1y] = payload.a1;
    const [a2x, a2y] = payload.a2;

    // The outline: half a cell out from the corner positions, so the frame sits on the array's
    // edge rather than on the outermost centres.
    const [ox, oy] = latticeOrigin(payload);
    const at = (c: number, r: number): [number, number] => [
      sx(ox + c * a1x + r * a2x),
      sy(oy + c * a1y + r * a2y),
    ];
    const quad = [
      at(-0.5, -0.5),
      at(payload.cols - 0.5, -0.5),
      at(payload.cols - 0.5, payload.rows - 0.5),
      at(-0.5, payload.rows - 0.5),
    ];
    g.beginPath();
    g.moveTo(quad[0][0], quad[0][1]);
    for (let i = 1; i < quad.length; i++) g.lineTo(quad[i][0], quad[i][1]);
    g.closePath();
    g.strokeStyle = OUTLINE;
    g.lineWidth = 1;
    g.stroke();

    const step = payload.pitch_px * scale;
    if (step < DOTS_MIN_STEP_PX) return;

    const rad = Math.max(0.7, Math.min(2.4, step * 0.11));
    const m = 8; // cull margin
    const det = new Path2D();
    const inf = new Path2D();
    for (let i = 0; i < col.length; i++) {
      const px = sx(x[i]);
      if (px < -m || px > width + m) continue;
      const py = sy(y[i]);
      if (py < -m || py > height + m) continue;
      const p = kind[i] === 2 ? inf : det;
      p.moveTo(px + rad, py);
      p.arc(px, py, rad, 0, Math.PI * 2);
    }
    g.fillStyle = DETECTED;
    g.fill(det);
    g.fillStyle = INFERRED;
    g.fill(inf);

    if (!idsOn || step < IDS_MIN_STEP_PX) return;
    g.font = '10px ui-monospace, SFMono-Regular, Menlo, monospace';
    g.textAlign = 'center';
    g.textBaseline = 'top';
    g.fillStyle = 'rgba(226, 240, 255, 0.94)';
    g.shadowColor = 'rgba(0, 0, 0, 0.9)';
    g.shadowBlur = 3;
    for (let i = 0; i < col.length; i++) {
      const px = sx(x[i]);
      if (px < -m || px > width + m) continue;
      const py = sy(y[i]);
      if (py < -m || py > height + m) continue;
      g.fillText(`${col[i]}-${row[i]}`, px, py + rad + 2);
    }
    g.shadowBlur = 0;
  }, [payload, scale, tx, ty, width, height, idsOn]);

  return <canvas ref={ref} className={className} data-testid="electrode-grid-layer" aria-hidden="true" />;
}
