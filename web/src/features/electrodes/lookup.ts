// THE CLIENT-SIDE ELECTRODE LOOKUP — a pure mirror of the server's click rule, so a click resolves
// with no round trip: a pixel selects electrode `col-row` ONLY within `hit_radius_px` of that
// centre; the gaps between pads select NOTHING (his rule — a miss deselects, so a wrong highlight
// cannot linger). Arrow keys step the SELECTION one cell along the grid axes instead (col/row ±1),
// which is the misclick recovery.
//
// ⭐ **THE TOLERANCE IS MEASURED ON SCREEN, NOT IN MOSAIC PIXELS (2026-08-11, R45.7).** `hit_radius_px`
// is a distance in the mosaic's own pixels, and the pad+margin it describes is only aimable while the
// mosaic is drawn near 1:1. Zoomed out to fit, his 5319×7356 video mosaic draws 1024 px wide: the
// 30.6 px pitch becomes 5.9 CSS px and the 9.2 px disc becomes 1.8 — **measured 24 % of clicks hit**,
// and because the miss depends on sub-pixel phase it fails in bands ("missing patches"). So the
// radius grows as you zoom out, capped at the cell's circumradius (√½ · pitch) — the point where the
// nearest centre is by definition the one you pointed at, never a neighbour's ground. Zoomed in, the
// cap never binds and his strict rule is exactly what runs.
//
// The index is a bucket hash on ~pitch-sized cells: lookup probes the 3×3 neighbourhood of the
// clicked bucket, which always covers a hit_radius_px disc (the radius is ~30% of pitch), and takes
// the NEAREST centre inside the radius. Coordinates are whatever space the payload's cells are in
// (document world px for the snapshot feature; mosaic.png canvas px for the videomosaic) — the
// caller converts, this module never guesses.

import type { ElectrodeMapPayload } from '../../api';

/** One resolved electrode. `electrode` is the id the user reads: `col-row` (e.g. "12-8"). */
export interface ElectrodeHit {
  electrode: string;
  col: number;
  row: number;
  centerX: number;
  centerY: number;
  /** Distance from the queried point to the centre, px. 0 for `electrodeAt` (no query point). */
  distance: number;
  /** 1 = detected on the pixels, 2 = inferred from the lattice (occluded/dead pad). */
  kind: number;
  /**
   * The same centre in the ARRAY's own frame, µm — x along columns, y along rows, rotation taken
   * out, origin at electrode 1-1's lattice position (R45.8). **null when the map carries no µm at
   * all**: a map fitted without a device spec, or one written before R45.8. Not-known must stay
   * distinguishable from 0.0, so it is null, never a zero.
   */
  xUm: number | null;
  yUm: number | null;
}

export interface ElectrodeIndex {
  payload: ElectrodeMapPayload;
  /** Bucket edge, px — ~one pitch, so a radius disc never spans more than the 3×3 neighbourhood. */
  cellSize: number;
  /** `bx,by` bucket → indices into the payload's flat cell arrays. */
  buckets: Map<string, number[]>;
  /** `col,row` → index into the flat cell arrays (the arrow-step lookup). */
  byCell: Map<string, number>;
}

/** The id the user reads for a grid position: `col-row`. */
export function electrodeId(col: number, row: number): string {
  return `${col}-${row}`;
}

/** The smallest click target that is honestly aimable with a mouse — a RADIUS, so an 8 px disc.
 *  Below this the pad on screen is smaller than the pointer tip and "click the pad" stops being a
 *  real instruction. Deliberately modest: it must not loosen a map whose pads are already big
 *  enough to aim at (a 14 px pitch at 1:1 has a 12 px target and stays under his strict rule). */
export const MIN_CLICK_SCREEN_PX = 4;

/**
 * The selection radius to use at a given zoom, in the payload's own pixel space.
 *
 * `scale` is screen CSS px per mosaic px (1 = the mosaic drawn 1:1). The radius is the strict
 * `hit_radius_px` grown, if needed, to keep a `MIN_CLICK_SCREEN_PX` target on screen — but never
 * past √½ · pitch, the farthest any point inside a cell can be from that cell's own centre. Since
 * the lookup takes the NEAREST centre, staying inside that cap means the answer is always the
 * electrode you pointed at; it can never be stolen from the neighbour.
 */
export function hitRadiusAt(payload: ElectrodeMapPayload, scale = 1): number {
  const strict = payload.hit_radius_px;
  const cap = Math.max(strict, Math.SQRT1_2 * payload.pitch_px);
  if (!Number.isFinite(scale) || scale <= 0) return strict;
  return Math.min(Math.max(strict, MIN_CLICK_SCREEN_PX / scale), cap);
}

const bucketKey = (bx: number, by: number): string => `${bx},${by}`;

/** Build the spatial + grid index once per payload. O(n cells). */
export function buildElectrodeIndex(payload: ElectrodeMapPayload): ElectrodeIndex {
  // hit_radius_px is ~30% of pitch, so a pitch-sized bucket guarantees the 3×3 probe covers the
  // disc. Guard against a degenerate pitch (an empty/near-empty fit) — never a zero cell size.
  const cellSize = Math.max(payload.pitch_px, payload.hit_radius_px * 2, 1);
  const buckets = new Map<string, number[]>();
  const byCell = new Map<string, number>();
  const { col, row, x, y } = payload.cells;
  for (let i = 0; i < col.length; i++) {
    const key = bucketKey(Math.floor(x[i] / cellSize), Math.floor(y[i] / cellSize));
    const bucket = buckets.get(key);
    if (bucket) bucket.push(i);
    else buckets.set(key, [i]);
    byCell.set(`${col[i]},${row[i]}`, i);
  }
  return { payload, cellSize, buckets, byCell };
}

/** A µm column entry, or null — the arrays are ABSENT (not zeroed) when no device supplied a scale. */
const um = (arr: number[] | undefined, i: number): number | null => {
  const v = arr?.[i];
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
};

function hitAt(index: ElectrodeIndex, i: number, distance: number): ElectrodeHit {
  const { col, row, x, y, kind, x_um, y_um } = index.payload.cells;
  return {
    electrode: electrodeId(col[i], row[i]),
    col: col[i],
    row: row[i],
    centerX: x[i],
    centerY: y[i],
    distance,
    kind: kind[i],
    xUm: um(x_um, i),
    yUm: um(y_um, i),
  };
}

/**
 * Resolve a point to an electrode — the click rule. Returns the NEAREST centre within the radius
 * `hitRadiusAt(payload, scale)` allows, or null (a gap / outside the array): the caller must treat
 * null as DESELECT. Pass the viewer's current `scale` (screen px per mosaic px) so the target stays
 * aimable when zoomed out; omitting it applies his strict pad+margin rule unchanged.
 */
export function lookupElectrode(
  index: ElectrodeIndex,
  x: number,
  y: number,
  scale = 1,
): ElectrodeHit | null {
  const { cells } = index.payload;
  const radius = hitRadiusAt(index.payload, scale);
  // The bucket probe must cover the radius disc: buckets are ~one pitch, so a radius above one
  // bucket edge needs a wider ring than 3×3 (it cannot exceed √½·pitch, so ±2 always suffices).
  const reach = Math.max(1, Math.ceil(radius / index.cellSize));
  const bx = Math.floor(x / index.cellSize);
  const by = Math.floor(y / index.cellSize);
  let best = -1;
  let bestD2 = Infinity;
  for (let dx = -reach; dx <= reach; dx++) {
    for (let dy = -reach; dy <= reach; dy++) {
      const bucket = index.buckets.get(bucketKey(bx + dx, by + dy));
      if (!bucket) continue;
      for (const i of bucket) {
        const ddx = cells.x[i] - x;
        const ddy = cells.y[i] - y;
        const d2 = ddx * ddx + ddy * ddy;
        if (d2 < bestD2) {
          bestD2 = d2;
          best = i;
        }
      }
    }
  }
  if (best < 0) return null;
  const d = Math.sqrt(bestD2);
  return d <= radius ? hitAt(index, best, d) : null;
}

/**
 * The electrode at an exact grid position, or null when that position does not exist (off the
 * array's edge / an absent corner). The arrow-key step: Up = row−1, Down = row+1, Left = col−1,
 * Right = col+1 — a null keeps the current selection (stepping off the edge is a no-op).
 */
export function electrodeAt(index: ElectrodeIndex, col: number, row: number): ElectrodeHit | null {
  const i = index.byCell.get(`${col},${row}`);
  return i == null ? null : hitAt(index, i, 0);
}

/** How many cells carry each `kind` — 1 detected on the pixels, 2 inferred from the lattice. */
export function kindCounts(payload: ElectrodeMapPayload): { detected: number; inferred: number } {
  let detected = 0;
  let inferred = 0;
  for (const k of payload.cells.kind) {
    if (k === 1) detected += 1;
    else if (k === 2) inferred += 1;
  }
  return { detected, inferred };
}
