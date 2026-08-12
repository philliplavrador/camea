import { describe, it, expect } from 'vitest';
import type { Tile, Tiles } from './types';
import {
  buildMatchRequest,
  buildPrefetchRequest,
  buildScoreRequest,
  fieldSignature,
} from './field';

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
function anchored(x: number, y: number): Tile {
  return mkTile({ state: 'anchored', status: 'anchor', x, y });
}

const order = [11, 12, 13, 14];
const tiles: Tiles = {
  11: anchored(0, 0),
  12: anchored(100, 0),
  13: mkTile({ state: 'unverified', status: 'unverified', x: 200, y: 0 }),
  14: mkTile(),
};
const inp = { sessionId: 'S', target: 13, tiles, order, refuse: [99] };

describe('buildMatchRequest — the request body IS the memo key', () => {
  it('anchors are the certified field MINUS the target, with their positions', () => {
    const req = buildMatchRequest(inp)!;
    expect(req.anchors).toEqual([11, 12]);
    expect(req.positions).toEqual({ '11': [0, 0], '12': [100, 0] });
    expect(req.session_id).toBe('S');
    expect(req.max_candidates).toBe(9); // ⭐ so key 9 can fire
    expect(req.refuse).toEqual([99]); // the blank list is part of the cache key
  });

  it('never ships the target inside its own anchors (a correction must not 400)', () => {
    // target 12 is itself anchored — it must be filtered out
    const req = buildMatchRequest({ ...inp, target: 12 })!;
    expect(req.anchors).not.toContain(12);
    expect(req.anchors).toEqual([11]);
  });

  it('returns null when there is no field to match against', () => {
    const empty: Tiles = { 11: mkTile(), 12: mkTile() };
    expect(
      buildMatchRequest({ sessionId: 'S', target: 11, tiles: empty, order: [11, 12], refuse: [] }),
    ).toBeNull();
  });

  it('local mode carries near + radius', () => {
    const req = buildMatchRequest(inp, { mode: 'local', near: [200, 5] })!;
    expect(req.mode).toBe('local');
    expect(req.near).toEqual([200, 5]);
    expect(req.radius).toBe(64);
  });
});

describe('buildPrefetchRequest — the A-branch (R21)', () => {
  it('INCLUDES the tile under judgement in anchors (assume the user presses A)', () => {
    // judged = 13 (unverified, placed), next = 14
    const req = buildPrefetchRequest({ sessionId: 'S', tiles, order, refuse: [] }, 13, 14)!;
    expect(req.target).toBe(14);
    expect(req.anchors).toContain(13); // 🔴 the whole point — assume A on 13
    expect(req.anchors).toEqual([11, 12, 13]);
    expect(req.positions['13']).toEqual([200, 0]);
  });

  it('does not add an unplaced or excluded judged tile to the field', () => {
    const t2: Tiles = { ...tiles, 13: mkTile() }; // 13 now unplaced
    const req = buildPrefetchRequest({ sessionId: 'S', tiles: t2, order, refuse: [] }, 13, 14)!;
    expect(req.anchors).toEqual([11, 12]); // 13 not added (no position)
  });
});

describe('buildScoreRequest', () => {
  it('scores at a point against the field minus target', () => {
    const req = buildScoreRequest(inp, [201, 1])!;
    expect(req.at).toEqual([201, 1]);
    expect(req.anchors).toEqual([11, 12]);
  });
});

describe('fieldSignature — R22 stamp', () => {
  it('is stable for the same field', () => {
    expect(fieldSignature(tiles, order, 13)).toBe(fieldSignature(tiles, order, 13));
  });
  it('changes when an anchor moves', () => {
    const moved: Tiles = { ...tiles, 12: anchored(101, 0) };
    expect(fieldSignature(moved, order, 13)).not.toBe(fieldSignature(tiles, order, 13));
  });
  it('excludes the target from the signature (a tile is never an anchor for its own match)', () => {
    // signature for target 12 (itself anchored) omits 12; differs from target 13's which includes 12
    expect(fieldSignature(tiles, order, 12)).not.toBe(fieldSignature(tiles, order, 13));
  });
});
