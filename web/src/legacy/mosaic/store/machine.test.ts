import { describe, it, expect } from 'vitest';
import type { Tile, Tiles } from './types';
import {
  statusFor,
  stateFor,
  applyState,
  applyPos,
  markStaleAfter,
  anchoredTrials,
  activeTrials,
  anyPlaced,
  nextTrial,
  prevTrial,
  counts,
  positionsOf,
  solverXY,
  tileOf,
  setTile,
} from './machine';

// ── factories ────────────────────────────────────────────────────────────────
function mkTile(over: Partial<Tile> = {}): Tile {
  return {
    status: 'unplaced',
    state: 'unplaced',
    x: null,
    y: null,
    blank: false,
    human: false,
    stale: false,
    diverted: false,
    ...over,
  } as Tile;
}
function tiles(entries: Record<number, Partial<Tile>>): Tiles {
  const t: Tiles = {};
  for (const [k, v] of Object.entries(entries)) t[k] = mkTile(v);
  return t;
}

describe('state ↔ status mapping (§4)', () => {
  it('anchored ↔ "anchor" — they differ', () => {
    expect(statusFor('anchored')).toBe('anchor');
    expect(statusFor('unverified')).toBe('unverified');
    expect(statusFor('unplaced')).toBe('unplaced');
    expect(statusFor('excluded')).toBe('excluded');
  });
  it('stateFor prefers state, else derives from status', () => {
    expect(stateFor({ state: 'anchored', status: 'anchor' })).toBe('anchored');
    // when state is absent, derive from status (a loaded legacy record)
    expect(stateFor({ status: 'anchor' } as Tile)).toBe('anchored');
  });
});

describe('applyState — the ONLY place a tile state is written', () => {
  it('anchoring writes both state and status, keeps the position, bumps seq', () => {
    const before = mkTile({ state: 'unverified', status: 'unverified', x: 3, y: 4, seq: 1 });
    const after = applyState(before, 'anchored', [3, 4], 7);
    expect(after.state).toBe('anchored');
    expect(after.status).toBe('anchor');
    expect([after.x, after.y]).toEqual([3, 4]);
    expect(after.seq).toBe(7);
  });

  it('excluding nulls the position (last_xy is set by the caller, not here)', () => {
    const before = mkTile({ state: 'anchored', status: 'anchor', x: 3, y: 4, seq: 2 });
    const after = applyState(before, 'excluded', null, undefined);
    expect(after.state).toBe('excluded');
    expect(after.x).toBeNull();
    expect(after.y).toBeNull();
  });

  it('R34: a tile that LEAVES excluded stops claiming it was thrown out', () => {
    const before = mkTile({
      state: 'excluded',
      status: 'excluded',
      x: null,
      y: null,
      excluded_reason: "the user's eye",
      unusable_reason: 'other',
      last_xy: [5, 6],
    });
    const after = applyState(before, 'anchored', [5, 6], 3);
    expect(after.excluded_reason).toBeUndefined();
    expect(after.unusable_reason).toBeUndefined();
    expect(after.last_xy).toBeUndefined();
    expect((after as Record<string, unknown>).excluded).toBeUndefined();
  });

  it('⚠️ blank is a MEASUREMENT and is NEVER cleared, not even on E→A', () => {
    const before = mkTile({ state: 'excluded', status: 'excluded', blank: true });
    const after = applyState(before, 'anchored', [0, 0], 1);
    expect(after.blank).toBe(true);
  });

  it('does not touch diverted (only a hand move clears it — R34); keeps the provenance', () => {
    const before = mkTile({
      state: 'unverified',
      status: 'unverified',
      x: 1,
      y: 1,
      diverted: true,
      divert_reason: 'why',
    });
    const after = applyState(before, 'anchored', [1, 1], 2);
    expect(after.diverted).toBe(true);
    expect(after.divert_reason).toBe('why');
  });

  it('keeps moved_px honest wherever a position is written', () => {
    const before = mkTile({ state: 'unverified', status: 'unverified', machine: [0, 0] });
    const after = applyState(before, 'anchored', [3, 4], 1);
    expect(after.moved_px).toBeCloseTo(5, 6);
  });
});

describe('applyPos — a hand move kills the divert claim (R34)', () => {
  it('rewrites the position and clears diverted/divert_reason/rejected_match; state untouched (R24)', () => {
    const before = mkTile({
      state: 'anchored',
      status: 'anchor',
      x: 1,
      y: 1,
      diverted: true,
      divert_reason: 'was on the solver',
      rejected_match: { x: 9, y: 9 },
    });
    const after = applyPos(before, [10, 20]);
    expect([after.x, after.y]).toEqual([10, 20]);
    expect(after.diverted).toBe(false);
    expect(after.divert_reason).toBeUndefined();
    expect(after.rejected_match).toBeUndefined();
    expect(after.state).toBe('anchored'); // a drag NEVER demotes an anchor
  });
});

describe('markStaleAfter (R11.3 / R24)', () => {
  it('flags anchored/unverified tiles with seq > afterSeq, except the mover', () => {
    const t = tiles({
      11: { state: 'anchored', status: 'anchor', x: 0, y: 0, seq: 1 },
      12: { state: 'unverified', status: 'unverified', x: 1, y: 1, seq: 2 },
      13: { state: 'unverified', status: 'unverified', x: 2, y: 2, seq: 3 },
    });
    const { tiles: out, stale } = markStaleAfter(t, [11, 12, 13], 1, 11);
    expect(stale.sort()).toEqual([12, 13]);
    expect(tileOf(out, 12)!.stale).toBe(true);
    expect(tileOf(out, 13)!.stale).toBe(true);
    expect(tileOf(out, 11)!.stale).toBe(false);
  });

  it('self-limiting: un-anchoring the tile you JUST anchored (highest seq) flags nothing', () => {
    const t = tiles({
      11: { state: 'anchored', status: 'anchor', x: 0, y: 0, seq: 1 },
      12: { state: 'anchored', status: 'anchor', x: 1, y: 1, seq: 2 },
    });
    const { stale } = markStaleAfter(t, [11, 12], 2, 12);
    expect(stale).toEqual([]);
  });

  it('is a no-op when afterSeq is undefined', () => {
    const t = tiles({ 11: { state: 'unverified', status: 'unverified', seq: 5 } });
    expect(markStaleAfter(t, [11], undefined, 99).stale).toEqual([]);
  });
});

describe('derived views (no dataset knowledge — order is whatever the run is)', () => {
  const order = [11, 12, 13, 14];
  const t = tiles({
    11: { state: 'anchored', status: 'anchor', x: 0, y: 0 },
    12: { state: 'unverified', status: 'unverified', x: 5, y: 5 },
    13: { state: 'excluded', status: 'excluded' },
    14: { state: 'unplaced', status: 'unplaced' },
  });

  it('anchoredTrials returns only the certified field', () => {
    expect(anchoredTrials(t, order)).toEqual([11]);
  });
  it('activeTrials = everything not excluded (R35)', () => {
    expect(activeTrials(t, order)).toEqual([11, 12, 14]);
  });
  it('anyPlaced is true when any tile has a position', () => {
    expect(anyPlaced(t, order)).toBe(true);
    expect(anyPlaced(tiles({ 1: {}, 2: {} }), [1, 2])).toBe(false);
  });
  it('nextTrial skips excluded and never wraps (§4.2)', () => {
    expect(nextTrial(order, t, 12)).toBe(14); // 13 is excluded
    expect(nextTrial(order, t, 14)).toBeNull(); // end of the run
  });
  it('prevTrial skips excluded', () => {
    expect(prevTrial(order, t, 14)).toBe(12);
  });
  it('counts: diverted counts ONLY still-unverified diverts (§4.3)', () => {
    const t2 = tiles({
      11: { state: 'anchored', status: 'anchor', x: 0, y: 0, diverted: true }, // anchored divert: not counted
      12: { state: 'unverified', status: 'unverified', x: 1, y: 1, diverted: true }, // counted
    });
    const c = counts(t2, [11, 12]);
    expect(c.anchored).toBe(1);
    expect(c.unverified).toBe(1);
    expect(c.diverted).toBe(1);
  });
});

describe('positionsOf / solverXY', () => {
  it('positionsOf emits only placed anchors, keyed by String(trial)', () => {
    const t = tiles({ 11: { x: 1, y: 2 }, 12: { x: null, y: null } });
    expect(positionsOf(t, [11, 12])).toEqual({ '11': [1, 2] });
  });
  it('solverXY reads tile.machine, or null', () => {
    expect(solverXY(mkTile({ machine: [3, 4] }))).toEqual([3, 4]);
    expect(solverXY(mkTile({}))).toBeNull();
    expect(solverXY(undefined)).toBeNull();
  });
});

describe('setTile is immutable', () => {
  it('returns a new map and does not mutate the input', () => {
    const t = tiles({ 11: { x: 1, y: 1 } });
    const out = setTile(t, 11, mkTile({ x: 9, y: 9 }));
    expect(out).not.toBe(t);
    expect(tileOf(t, 11)!.x).toBe(1);
    expect(tileOf(out, 11)!.x).toBe(9);
  });
});
