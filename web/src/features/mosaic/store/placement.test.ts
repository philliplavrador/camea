import { describe, it, expect } from 'vitest';
import type { MatchResult, Candidate } from '../../../api';
import { classifyPlacement, matchConfidence } from './placement';
import { SOLVER_MARGIN_MIN, SOLVER_NCC_MIN } from './constants';

// ── synthetic evidence ─────────────────────────────────────────────────────────
function mkBest(x: number, y: number, ncc: number | null, rank = 0, npix = 1000): Candidate {
  return { rank, x, y, ncc, npix, subpixel: true };
}
function mkRes(over: Partial<MatchResult> = {}): MatchResult {
  return {
    target: 1,
    mode: 'global',
    n_anchors: 4,
    candidates: [],
    best: null,
    margin: null,
    margin_thin: false,
    gpu: false,
    elapsed_ms: 1,
    cached: false,
    cache_key: 'k',
    ...over,
  };
}

describe('matchConfidence — both gates, OR-ed, each with the measurement', () => {
  it('confident when margin ≥ 0.20 and ncc ≥ 0.65', () => {
    const c = matchConfidence(mkRes({ best: mkBest(0, 0, 0.9), margin: 0.47 }));
    expect(c.confident).toBe(true);
    expect(c.none).toBe(false);
    expect(c.why).toEqual([]);
  });

  it('no candidate at all → not confident, none, with a reason', () => {
    const c = matchConfidence(mkRes({ best: null }));
    expect(c).toMatchObject({ confident: false, none: true });
    expect(c.why[0]).toContain('no candidate');
  });

  it('a refusal is reported as the reason', () => {
    const c = matchConfidence(
      mkRes({ best: null, refused: { reason: 'blank', trials: [1], message: 'x' } }),
    );
    expect(c.none).toBe(true);
    expect(c.why[0]).toContain('blank');
  });

  it('a null best-NCC is UNMEASURABLE, not "below the gate" (no false trip)', () => {
    const c = matchConfidence(mkRes({ best: mkBest(0, 0, null), margin: 0.47 }));
    // margin passes, ncc is null → the ncc gate does not fire on a coerced 0
    expect(c.confident).toBe(true);
  });
});

describe('classifyPlacement — the five outcomes (R15)', () => {
  it('1 — CONFIDENT: the match wins, not diverted', () => {
    const dec = classifyPlacement(mkRes({ best: mkBest(100, 200, 0.9), margin: 0.47 }), [100, 205]);
    expect(dec.confident).toBe(true);
    expect(dec.diverted).toBe(false);
    expect(dec.position).toEqual([100, 200]);
  });

  it('1b — a CONFIDENT match far from the solver still wins (W11 is a banner, not a divert)', () => {
    const dec = classifyPlacement(mkRes({ best: mkBest(100, 200, 0.9), margin: 0.47 }), [900, 900]);
    expect(dec.confident).toBe(true);
    expect(dec.diverted).toBe(false);
    expect(dec.position).toEqual([100, 200]);
    expect(dec.disagreePx).toBeGreaterThan(20);
  });

  it('2 — not confident, NO solver: use the match anyway and flag noSolver', () => {
    const dec = classifyPlacement(mkRes({ best: mkBest(10, 10, 0.5), margin: 0.05 }), null);
    expect(dec.diverted).toBe(false);
    expect(dec.noSolver).toBe(true);
    expect(dec.position).toEqual([10, 10]);
  });

  it('3 — not confident, NO match at all: DIVERT to the solver', () => {
    const dec = classifyPlacement(
      mkRes({ best: null, refused: { reason: 'blank', trials: [1], message: 'x' } }),
      [50, 60],
    );
    expect(dec.none).toBe(true);
    expect(dec.diverted).toBe(true);
    expect(dec.position).toEqual([50, 60]);
  });

  it('4 — not confident but AGREES with the solver (≤ 10 px): the match stands', () => {
    const dec = classifyPlacement(mkRes({ best: mkBest(100, 100, 0.5), margin: 0.05 }), [104, 100]);
    expect(dec.diverted).toBe(false);
    expect(dec.position).toEqual([100, 100]);
    expect(dec.disagreePx).toBeCloseTo(4, 6);
  });

  it('5 — not confident AND disagrees by > 10 px: DIVERT to the solver, keep the rejected match', () => {
    const dec = classifyPlacement(mkRes({ best: mkBest(100, 100, 0.5), margin: 0.05 }), [500, 500]);
    expect(dec.diverted).toBe(true);
    expect(dec.position).toEqual([500, 500]);
    expect(dec.rejected).toMatchObject({ x: 100, y: 100, ncc: 0.5 });
  });
});

describe('🔴 NEITHER GATE IS REDUNDANT — the measured failures that need each one', () => {
  // t105: 353 px wrong at NCC 0.7450 (sails PAST the NCC gate). Only margin catches it.
  it('t105 — margin gate alone catches a high-NCC alias', () => {
    const res = mkRes({ best: mkBest(353, 0, 0.745), margin: 0.05 }); // ncc 0.745 > 0.65, margin 0.05 < 0.20
    const conf = matchConfidence(res);
    expect(conf.confident).toBe(false);
    expect(conf.why.some((w) => w.startsWith('margin'))).toBe(true);
    expect(conf.why.some((w) => w.startsWith('NCC'))).toBe(false); // the NCC gate does NOT fire
    const dec = classifyPlacement(res, [0, 0]);
    expect(dec.diverted).toBe(true); // 353 px from the solver → diverted, not shipped 353 px wrong
  });

  // t182: 2,042 px wrong at margin 0.3230 (sails PAST the margin gate). Only ncc catches it.
  it('t182 — ncc gate alone catches a wide-margin alias', () => {
    const res = mkRes({ best: mkBest(2042, 0, 0.5), margin: 0.323 }); // margin 0.323 > 0.20, ncc 0.5 < 0.65
    const conf = matchConfidence(res);
    expect(conf.confident).toBe(false);
    expect(conf.why.some((w) => w.startsWith('NCC'))).toBe(true);
    expect(conf.why.some((w) => w.startsWith('margin'))).toBe(false); // the margin gate does NOT fire
    const dec = classifyPlacement(res, [0, 0]);
    expect(dec.diverted).toBe(true);
  });

  it('the two constants are exactly the measured values', () => {
    expect(SOLVER_MARGIN_MIN).toBe(0.2);
    expect(SOLVER_NCC_MIN).toBe(0.65);
  });
});
