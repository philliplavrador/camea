import { describe, it, expect, beforeEach, vi } from 'vitest';
import type { MosaicDocument, MatchResult, Candidate } from '../../../api';
import type { Tile, Tiles } from './types';

// The store's only runtime dependency on the backend is these three calls — mock them so the store's
// orchestration (guards, the toggle, the transitions, undo) is tested without a server.
vi.mock('../../../api', () => ({
  matchAnchor: vi.fn(),
  matchScore: vi.fn(),
  computeGaps: vi.fn(),
}));

import { matchAnchor, matchScore, computeGaps } from '../../../api';
import { useSweepStore } from './sweepStore';

const mAnchor = vi.mocked(matchAnchor);
const mScore = vi.mocked(matchScore);
const mGaps = vi.mocked(computeGaps);

// ── factories ─────────────────────────────────────────────────────────────────
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
const anchored = (x: number, y: number, seq: number): Tile =>
  mkTile({ state: 'anchored', status: 'anchor', x, y, seq });
const unverified = (x: number, y: number, seq: number): Tile =>
  mkTile({ state: 'unverified', status: 'unverified', x, y, seq });

function mkDoc(tiles: Tiles, over: Partial<MosaicDocument> = {}): MosaicDocument {
  return {
    tiles,
    cursor: null,
    origin_trial: 0,
    gaps: [],
    unusable_tiles: [],
    modified: 't0',
    ...over,
  } as unknown as MosaicDocument;
}
function mkBest(x: number, y: number, ncc: number, rank = 0): Candidate {
  return { rank, x, y, ncc, npix: 1000, subpixel: true };
}
function confident(target: number, x: number, y: number): MatchResult {
  const best = mkBest(x, y, 0.9);
  return {
    target,
    mode: 'global',
    n_anchors: 1,
    candidates: [best],
    best,
    margin: 0.47,
    margin_thin: false,
    gpu: false,
    elapsed_ms: 1,
    cached: false,
    cache_key: 'k',
  };
}

const S = useSweepStore.getState;

beforeEach(() => {
  useSweepStore.getState().reset();
  mAnchor.mockReset();
  mScore.mockReset();
  mGaps.mockReset();
  mGaps.mockResolvedValue({ gaps: [] });
  // A benign default so the fire-and-forget PREFETCH (which fires the same POST early and discards it —
  // R21) always gets a Promise back, exactly as the real client would. Tests that assert on the
  // FOREGROUND match override this with mockResolvedValue / mockReturnValue.
  mAnchor.mockResolvedValue(confident(0, 0, 0));
  mScore.mockResolvedValue({ target: 0, at: [0, 0], ncc: 0.9, npix: 1000, elapsed_ms: 1 });
});

describe('reset / hydrate', () => {
  it('starts empty', () => {
    expect(S().cursor).toBeNull();
    expect(S().doc).toBeNull();
  });
  it('hydrate adopts tiles, the order, the refuse list and the saved cursor', () => {
    const doc = mkDoc({ 11: mkTile(), 12: mkTile() }, { cursor: 12 });
    S().hydrate(doc, { sessionId: 'S', order: [11, 12], refuse: [7] });
    expect(S().cursor).toBe(12);
    expect(S().order).toEqual([11, 12]);
    expect(S().refuse).toEqual([7]);
  });
});

describe('🔴 R14 — the cursor is never nulled by a viewer deselect', () => {
  beforeEach(() => S().hydrate(mkDoc({ 11: mkTile() }), { sessionId: 'S', order: [11] }));
  it('setCursor(number) sets it; setCursor(null) is IGNORED', () => {
    S().setCursor(11);
    expect(S().cursor).toBe(11);
    S().setCursor(null); // a viewer onSelect(null) from Escape
    expect(S().cursor).toBe(11); // still on the tile under judgement
  });
});

describe('advance / anchor / exclude are NO-OPS when the cursor is null', () => {
  beforeEach(() =>
    S().hydrate(mkDoc({ 11: mkTile(), 12: mkTile() }), { sessionId: 'S', order: [11, 12] }),
  );
  it('none of them mutate the document or call the backend with no cursor', async () => {
    expect(S().cursor).toBeNull();
    await S().anchor();
    await S().exclude();
    await S().advance();
    expect(S().doc!.tiles['11'].state).toBe('unplaced');
    expect(mAnchor).not.toHaveBeenCalled();
  });
});

describe('A — origin, then the toggle (R11)', () => {
  it('A on the first tile with nothing placed makes it the origin (0,0)', async () => {
    S().hydrate(mkDoc({ 11: mkTile(), 12: mkTile() }), { sessionId: 'S', order: [11, 12] });
    S().setCursor(11);
    await S().anchor();
    const t = S().doc!.tiles['11'];
    expect(t.state).toBe('anchored');
    expect([t.x, t.y]).toEqual([0, 0]);
    expect(S().doc!.origin_trial).toBe(11);
    expect(S().warnings.noAnchors).toBe(false);
    expect(S().banner!.message).toContain('Origin');
    // (A prefetch for the NEXT tile fires afterwards — R21 — so the match mock IS called; the point is
    // the ORIGIN itself lands at (0,0) with no foreground match, which the (0,0) assertion above proves.)
  });

  it('⭐ A on an anchored tile UN-ANCHORS it: → unverified, KEEPS its position, cascades stale, warns W10', async () => {
    S().hydrate(
      mkDoc({ 11: anchored(0, 0, 1), 12: unverified(5, 5, 2), 13: unverified(9, 9, 3) }),
      { sessionId: 'S', order: [11, 12, 13] },
    );
    S().setCursor(11);
    await S().anchor(); // toggles
    const t = S().doc!.tiles['11'];
    expect(t.state).toBe('unverified');
    expect([t.x, t.y]).toEqual([0, 0]); // position KEPT (not thrown away)
    expect(S().doc!.tiles['12'].stale).toBe(true); // downstream flagged stale
    expect(S().doc!.tiles['13'].stale).toBe(true);
    expect(S().warnings.noAnchors).toBe(true); // W10 — no anchors left
    expect(S().banner!.message).toContain('No anchors left');
  });

  it('R11.5 — un-anchoring the origin does NOT move anything and origin_trial STAYS', async () => {
    S().hydrate(mkDoc({ 11: anchored(0, 0, 1) }, { origin_trial: 11 }), {
      sessionId: 'S',
      order: [11],
    });
    S().setCursor(11);
    await S().anchor();
    expect(S().doc!.origin_trial).toBe(11);
    expect([S().doc!.tiles['11'].x, S().doc!.tiles['11'].y]).toEqual([0, 0]);
  });

  it('A on a positioned unverified tile certifies it in place (no match needed)', async () => {
    S().hydrate(mkDoc({ 11: anchored(0, 0, 1), 12: unverified(100, 0, 2) }), {
      sessionId: 'S',
      order: [11, 12],
    });
    S().setCursor(12);
    await S().anchor();
    expect(S().doc!.tiles['12'].state).toBe('anchored');
    expect(mAnchor).not.toHaveBeenCalled();
  });
});

describe('E — exclude (recomputes gaps via the route, cascades stale on an anchor)', () => {
  it('excludes the cursor tile, keeps last_xy, sets unusable_reason, updates unusable_tiles', async () => {
    mGaps.mockResolvedValue({ gaps: [[11, 13]] });
    S().hydrate(
      mkDoc({ 11: anchored(0, 0, 1), 12: unverified(5, 5, 2), 13: unverified(9, 9, 3) }),
      { sessionId: 'S', order: [11, 12, 13] },
    );
    S().setCursor(12);
    await S().exclude();
    const t = S().doc!.tiles['12'];
    expect(t.state).toBe('excluded');
    expect(t.x).toBeNull();
    expect(t.last_xy).toEqual([5, 5]);
    expect(t.unusable_reason).toBe('other'); // not blank
    expect(S().doc!.unusable_tiles).toEqual([12]);
    expect(mGaps).toHaveBeenCalledWith([11, 13]); // active list, via the route (R2.5/R35)
    expect(S().doc!.gaps).toEqual([[11, 13]]);
  });

  it('excluding an ANCHOR cascades stale to every later-judged tile', async () => {
    S().hydrate(mkDoc({ 11: anchored(0, 0, 1), 12: unverified(5, 5, 2) }), {
      sessionId: 'S',
      order: [11, 12],
    });
    S().setCursor(11);
    await S().exclude();
    expect(S().doc!.tiles['11'].state).toBe('excluded');
    expect(S().doc!.tiles['12'].stale).toBe(true);
    expect(S().banner!.message).toContain('was an anchor');
  });

  it('a blank tile excluded records unusable_reason "blank" (a measurement, not the eye)', async () => {
    const blank12 = mkTile({
      state: 'unverified',
      status: 'unverified',
      x: 5,
      y: 5,
      seq: 2,
      blank: true,
    });
    S().hydrate(mkDoc({ 11: anchored(0, 0, 1), 12: blank12 }), { sessionId: 'S', order: [11, 12] });
    S().setCursor(12);
    await S().exclude();
    expect(S().doc!.tiles['12'].unusable_reason).toBe('blank');
  });
});

describe('Space — advance places the next tile against the anchor field (R15)', () => {
  it('confident match → the next tile lands unverified at the match, cursor moves at display (R33)', async () => {
    mAnchor.mockResolvedValue(confident(12, 100, 0));
    S().hydrate(mkDoc({ 11: anchored(0, 0, 1), 12: mkTile() }), {
      sessionId: 'S',
      order: [11, 12],
    });
    S().setCursor(11);
    await S().advance();
    const t = S().doc!.tiles['12'];
    expect(t.state).toBe('unverified');
    expect([t.x, t.y]).toEqual([100, 0]);
    expect(S().cursor).toBe(12); // committed at display
  });

  it('a second Space while a placement is in flight does not start a second advance (R33)', async () => {
    let resolve!: (r: MatchResult) => void;
    mAnchor.mockReturnValue(
      new Promise<MatchResult>((r) => {
        resolve = r;
      }),
    );
    S().hydrate(mkDoc({ 11: anchored(0, 0, 1), 12: mkTile(), 13: mkTile() }), {
      sessionId: 'S',
      order: [11, 12, 13],
    });
    S().setCursor(11);
    const first = S().advance();
    expect(S().advancing).toBe(true);
    await S().advance(); // second Space — must be a no-op (the advancing guard, R33)
    expect(mAnchor).toHaveBeenCalledTimes(1); // only the FIRST advance fired a foreground match
    resolve(confident(12, 100, 0));
    await first;
  });
});

describe('undo / redo (R36)', () => {
  it('undo restores the pre-anchor state; redo re-applies it', async () => {
    S().hydrate(mkDoc({ 11: mkTile(), 12: mkTile() }), { sessionId: 'S', order: [11, 12] });
    S().setCursor(11);
    await S().anchor(); // origin
    expect(S().doc!.tiles['11'].state).toBe('anchored');
    S().undo();
    expect(S().doc!.tiles['11'].state).toBe('unplaced');
    expect(S().doc!.origin_trial).toBe(0); // origin_trial restored too
    S().redo();
    expect(S().doc!.tiles['11'].state).toBe('anchored');
  });
});

describe('the persistence hook (R29 — A/E autosave unconditionally)', () => {
  it('fires onChange with { judgement: true } on an anchor', async () => {
    const onChange = vi.fn();
    S().hydrate(mkDoc({ 11: mkTile() }), { sessionId: 'S', order: [11] });
    S().setHooks({ onChange });
    S().setCursor(11);
    onChange.mockClear();
    await S().anchor();
    expect(onChange).toHaveBeenCalledWith(expect.anything(), { judgement: true });
  });
});

describe('ensureCursor', () => {
  it('lands the cursor on the first non-excluded trial', () => {
    S().hydrate(mkDoc({ 11: mkTile({ state: 'excluded', status: 'excluded' }), 12: mkTile() }), {
      sessionId: 'S',
      order: [11, 12],
    });
    S().ensureCursor();
    expect(S().cursor).toBe(12);
  });
});

describe('display prefs (session-only, R13)', () => {
  it('setFloatAlpha clamps to 0.15–1.00 and snaps to the step', () => {
    S().setFloatAlpha(2);
    expect(S().floatAlpha).toBe(1);
    S().setFloatAlpha(0);
    expect(S().floatAlpha).toBe(0.15);
  });
  it('toggleDiff flips difference mode', () => {
    expect(S().diffMode).toBe(false);
    S().toggleDiff();
    expect(S().diffMode).toBe(true);
  });
});
