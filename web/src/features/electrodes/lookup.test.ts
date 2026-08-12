import { describe, it, expect } from 'vitest';
import type { ElectrodeMapPayload } from '../../api';
import {
  MIN_CLICK_SCREEN_PX,
  buildElectrodeIndex,
  electrodeAt,
  electrodeId,
  hitRadiusAt,
  kindCounts,
  lookupElectrode,
} from './lookup';

/**
 * A tiny 3×2 axis-aligned lattice, pitch 100, hit radius 30 (~30% of pitch — the server's rule).
 * Centres at (100·col + 50, 100·row + 50); cell (2, 1) is kind 2 (inferred), the rest detected.
 *
 * `withUm` adds the R45.8 µm columns — 17.5 µm per 100 px cell, i.e. col·17.5 along x. Off by
 * default, because a map fitted with no device spec carries no µm at all and the lookup must stay
 * honest about that.
 */
function payload(withUm = false): ElectrodeMapPayload {
  const col: number[] = [];
  const row: number[] = [];
  const x: number[] = [];
  const y: number[] = [];
  const kind: number[] = [];
  const x_um: number[] = [];
  const y_um: number[] = [];
  for (let r = 0; r < 2; r++) {
    for (let c = 0; c < 3; c++) {
      col.push(c);
      row.push(r);
      x.push(c * 100 + 50);
      y.push(r * 100 + 50);
      kind.push(c === 2 && r === 1 ? 2 : 1);
      x_um.push(c * 17.5);
      y_um.push(r * 17.5);
    }
  }
  return {
    cols: 3,
    rows: 2,
    pitch_px: 100,
    angle_deg: 0,
    hit_radius_px: 30,
    a1: [100, 0],
    a2: [0, 100],
    canvas_offset: [0, 0],
    stale: false,
    array_coverage: 'partial',
    um_per_px: withUm ? 0.175 : null,
    cells: withUm ? { col, row, x, y, kind, x_um, y_um } : { col, row, x, y, kind },
  };
}

describe('lookupElectrode — the click rule', () => {
  it('a point inside hit_radius_px of a centre resolves to that electrode, with the distance', () => {
    const index = buildElectrodeIndex(payload());
    const hit = lookupElectrode(index, 150 + 20, 50); // 20 px right of centre (1, 0)
    expect(hit).not.toBeNull();
    expect(hit!.electrode).toBe('1-0');
    expect(hit!.col).toBe(1);
    expect(hit!.row).toBe(0);
    expect(hit!.centerX).toBe(150);
    expect(hit!.centerY).toBe(50);
    expect(hit!.distance).toBeCloseTo(20, 6);
    expect(hit!.kind).toBe(1);
  });

  it('a point in the GAP between pads selects NOTHING (miss ⇒ the caller deselects)', () => {
    const index = buildElectrodeIndex(payload());
    // Dead centre of four pads: 50·√2 ≈ 70.7 px from every centre — well outside radius 30.
    expect(lookupElectrode(index, 100, 100)).toBeNull();
    // Just past the radius on one axis.
    expect(lookupElectrode(index, 50 + 31, 50)).toBeNull();
    // And just inside it still hits.
    expect(lookupElectrode(index, 50 + 29, 50)).not.toBeNull();
  });

  it('a point outside the array selects nothing', () => {
    const index = buildElectrodeIndex(payload());
    expect(lookupElectrode(index, -500, -500)).toBeNull();
    expect(lookupElectrode(index, 1e6, 1e6)).toBeNull();
  });

  it('the nearest centre wins when two are in reach of the probe', () => {
    const index = buildElectrodeIndex(payload());
    const hit = lookupElectrode(index, 129, 50); // 21 px from (1,0)@150, 79 px from (0,0)@50
    expect(hit!.electrode).toBe('1-0');
  });
});

describe('hitRadiusAt — the tolerance is a distance ON SCREEN (R45.7)', () => {
  it('at 1:1 (and above) his strict pad+margin radius is what runs, unchanged', () => {
    const p = payload();
    expect(hitRadiusAt(p, 1)).toBe(30);
    expect(hitRadiusAt(p, 4)).toBe(30);
    expect(hitRadiusAt(p)).toBe(30); // no zoom given ⇒ strict
  });

  it('zoomed out it grows to keep a clickable target, capped at the cell (never a neighbour)', () => {
    const p = payload();
    // scale 0.02: the strict 30 px disc would be 1.2 CSS px across — smaller than the pointer, and
    // the radius that would keep MIN_CLICK_SCREEN_PX on screen (200) is past the cell, so the cap
    // binds instead.
    const r = hitRadiusAt(p, 0.02);
    expect(r).toBeGreaterThan(30);
    expect(r).toBeCloseTo(Math.SQRT1_2 * p.pitch_px, 6); // the cap: √½ · pitch = 70.7
    // Mid zoom: exactly the radius that keeps MIN_CLICK_SCREEN_PX on screen.
    expect(hitRadiusAt(p, 0.1)).toBeCloseTo(MIN_CLICK_SCREEN_PX / 0.1, 6);
    // …and a zoom where the pad is already aimable leaves his strict radius alone.
    expect(hitRadiusAt(p, 0.5)).toBe(30);
  });

  it('a nonsense scale falls back to the strict radius rather than inventing one', () => {
    const p = payload();
    expect(hitRadiusAt(p, 0)).toBe(30);
    expect(hitRadiusAt(p, -2)).toBe(30);
    expect(hitRadiusAt(p, Number.NaN)).toBe(30);
  });
});

describe('lookupElectrode — zoomed out, the click still lands on what you pointed at', () => {
  it('a gap click that misses at 1:1 resolves to the NEAREST pad when zoomed out', () => {
    const index = buildElectrodeIndex(payload());
    // 40 px right of (0,0): a miss under the strict rule, and the nearest centre once zoomed out.
    expect(lookupElectrode(index, 90, 50, 1)).toBeNull();
    const hit = lookupElectrode(index, 90, 50, 0.05);
    expect(hit!.electrode).toBe('0-0');
    expect(hit!.distance).toBeCloseTo(40, 6);
  });

  it('it can never cross into the next cell — the far corner of a cell still resolves to ITS pad', () => {
    const index = buildElectrodeIndex(payload());
    // 45,45 px from (0,0)@(50,50) — inside its cell, but nearer to it than to any other centre.
    const hit = lookupElectrode(index, 95, 95, 0.02);
    expect(hit!.electrode).toBe('0-0');
    // The exact four-corner point is equidistant from four pads: whichever wins, the distance is
    // the cell circumradius, so no pad is ever claimed from further away than that.
    const corner = lookupElectrode(index, 100, 100, 0.02);
    expect(corner!.distance).toBeCloseTo(Math.SQRT1_2 * 100, 6);
  });

  it('outside the array is still nothing, at any zoom', () => {
    const index = buildElectrodeIndex(payload());
    expect(lookupElectrode(index, -500, -500, 0.02)).toBeNull();
    expect(lookupElectrode(index, 400, 50, 0.02)).toBeNull(); // 150 px past the last centre
  });
});

describe('electrodeAt — the arrow-key neighbour', () => {
  it('an existing neighbour resolves (col/row ±1 along the GRID axes)', () => {
    const index = buildElectrodeIndex(payload());
    const right = electrodeAt(index, 1 + 1, 0); // Right = col+1
    expect(right).not.toBeNull();
    expect(right!.electrode).toBe('2-0');
    expect(right!.distance).toBe(0);
    const down = electrodeAt(index, 2, 0 + 1); // Down = row+1
    expect(down!.electrode).toBe('2-1');
    expect(down!.kind).toBe(2); // the inferred pad is still addressable — every position has an id
  });

  it('stepping off the edge answers null (the caller keeps the current selection)', () => {
    const index = buildElectrodeIndex(payload());
    expect(electrodeAt(index, -1, 0)).toBeNull();
    expect(electrodeAt(index, 3, 0)).toBeNull();
    expect(electrodeAt(index, 0, 2)).toBeNull();
  });
});

describe('the µm carried on a hit (R45.8)', () => {
  it('a hit carries the array-frame µm when the map has them, by click and by arrow step', () => {
    const index = buildElectrodeIndex(payload(true));
    const hit = lookupElectrode(index, 150 + 20, 50); // cell (1, 0)
    expect(hit!.xUm).toBeCloseTo(17.5, 6);
    expect(hit!.yUm).toBeCloseTo(0, 6);
    const down = electrodeAt(index, 1, 1);
    expect(down!.xUm).toBeCloseTo(17.5, 6);
    expect(down!.yUm).toBeCloseTo(17.5, 6);
  });

  it('a map with no device carries NO µm — null, never a zero standing in for "not known"', () => {
    const index = buildElectrodeIndex(payload(/* withUm */ false));
    const hit = lookupElectrode(index, 150, 50);
    expect(hit!.xUm).toBeNull();
    expect(hit!.yUm).toBeNull();
    expect(electrodeAt(index, 0, 0)!.xUm).toBeNull();
  });
});

describe('helpers', () => {
  it('electrodeId is `col-row`', () => {
    expect(electrodeId(12, 8)).toBe('12-8');
  });

  it('kindCounts splits detected vs inferred', () => {
    expect(kindCounts(payload())).toEqual({ detected: 5, inferred: 1 });
  });
});
