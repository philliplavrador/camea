// ⭐⭐ THE SOLVER FALLBACK — his ruling, 2026-07-12 (BEHAVIOUR R15):
//   "i still want it to place at where the solver thinks it is but i dont want it to anchor it without
//    user approval"
//
// This is the one place that answers "where does the tile go?". It is a PURE function of a match result
// and the solver's position — no tile lookups, no store, no network — so the load-bearing classifier can
// be unit-tested exhaustively on synthetic evidence.
//
// ⛔ IT DECIDES A POSITION, NEVER A STATE. Everything it places lands `unverified`: outside the anchor
//    field, with no vote. Only `A` anchors, and only the user presses `A` (I3 — NOTHING is auto-anchored).

import type { MatchResult } from '../../../api';
import type { PlacementDecision, Position } from './types';
import { SOLVER_MARGIN_MIN, SOLVER_NCC_MIN, SOLVER_DISAGREE_PX } from './constants';

function fmt(n: number, d: number): string {
  return n.toFixed(d);
}

interface Confidence {
  confident: boolean;
  /** No candidate at all (a blank refusal or an empty list). */
  none: boolean;
  /** PLAIN-text reasons, each carrying the measurement (never a bare assertion). */
  why: string[];
}

/**
 * Is the anchor-composite match good enough to OVERRULE the batch solve? Permissive on purpose: neither
 * signal separates alone, so the two gates are OR'd and the disagreement gate in `classifyPlacement` is
 * what stops a permissive test from costing anything.
 *
 * 🔴 BOTH GATES STAY. margin alone misses t105 (353 px wrong at NCC 0.7450); ncc alone misses t182
 * (2,042 px wrong at margin 0.3230). See constants.ts.
 */
export function matchConfidence(res: MatchResult | null): Confidence {
  if (!res || !res.best) {
    const why =
      res && res.refused ? `matcher refused (${res.refused.reason})` : 'no candidate at all';
    return { confident: false, none: true, why: [why] };
  }
  const why: string[] = [];
  const margin = res.margin ?? null;
  if (margin !== null && margin < SOLVER_MARGIN_MIN) {
    why.push(`margin ${fmt(margin, 4)} < ${SOLVER_MARGIN_MIN.toFixed(2)}`);
  }
  // A null best-NCC is UNMEASURABLE, not "below the gate" — do not coerce it to 0 and trip the gate
  // (v1's `isFinite(null)` quirk). The `none` path and the margin gate cover the honest-null case.
  const ncc = res.best.ncc;
  if (ncc !== null && Number.isFinite(ncc) && ncc < SOLVER_NCC_MIN) {
    why.push(`NCC ${fmt(ncc, 4)} < ${SOLVER_NCC_MIN.toFixed(2)}`);
  }
  return { confident: why.length === 0, none: false, why };
}

/**
 * ⭐ WHERE DOES THE TILE GO? Given the match `res` and the solver's position `solver` (from
 * `tile.machine`, already translated into the document's frame), return the placement decision.
 *
 * The four outcomes, in order:
 *   1. CONFIDENT           → the match wins. The anchor field is human-certified and a big aperture; a
 *                            big trusted reference does not lie the way a tile-pair does. This is what
 *                            makes the sweep get MORE accurate as it goes.
 *   2. not confident, no solver → use the match anyway and SAY SO. A tile with no position is useless.
 *   3. not confident, no match at all (blank) → the solver's answer is the only position there is → DIVERT.
 *   4. not confident but AGREES with the solver (≤ 10 px) → the match stands (nothing to divert away from).
 *   5. not confident AND disagrees by > 10 px → DIVERT to the solver.
 */
export function classifyPlacement(
  res: MatchResult | null,
  solver: Position | null,
): PlacementDecision {
  const conf = matchConfidence(res);
  const best: Position | null = res && res.best ? [res.best.x, res.best.y] : null;
  const disagreePx = best && solver ? Math.hypot(best[0] - solver[0], best[1] - solver[1]) : null;

  const base = { confident: conf.confident, none: conf.none, why: conf.why };

  // 1 — confident: the match wins.
  if (conf.confident) {
    return {
      ...base,
      position: best,
      diverted: false,
      noSolver: false,
      disagreePx,
      rejected: null,
    };
  }
  // 2 — not confident and nothing to fall back to: use the match, announce it.
  if (!solver) {
    return {
      ...base,
      position: best,
      diverted: false,
      noSolver: true,
      disagreePx: null,
      rejected: null,
    };
  }
  // 3 — not confident and NO match at all: the solver is the only position there is.
  if (conf.none) {
    return {
      ...base,
      position: solver,
      diverted: true,
      noSolver: false,
      disagreePx: null,
      rejected: rejectedOf(res, null),
    };
  }
  // 4 — not confident but agrees with the solver: leave the match in place (keeps the sub-pixel refit).
  if (disagreePx !== null && disagreePx <= SOLVER_DISAGREE_PX) {
    return {
      ...base,
      position: best,
      diverted: false,
      noSolver: false,
      disagreePx,
      rejected: null,
    };
  }
  // 5 — not confident AND disagrees past the grading bar: DIVERT to the solver.
  return {
    ...base,
    position: solver,
    diverted: true,
    noSolver: false,
    disagreePx,
    rejected: rejectedOf(res, disagreePx),
  };
}

/** The rejected match, kept in full as the evidence FOR a divert (BEHAVIOUR R15c / W3). Its NCC is the
 *  REJECTED alias's score — the honest NCC at the shipped (solver) position is re-measured separately by
 *  the store, and never written here (writing `best.ncc` onto the shipped position is exactly the R15c
 *  bug). */
function rejectedOf(res: MatchResult | null, disagreePx: number | null) {
  if (!res || !res.best) return null;
  return {
    x: res.best.x,
    y: res.best.y,
    ncc: res.best.ncc,
    margin: res.margin ?? null,
    npix: res.best.npix,
    rank: res.best.rank,
    n_anchors: res.n_anchors,
    px_from_solver: disagreePx,
  };
}
