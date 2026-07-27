// ─────────────────────────────────────────────────────────────────────────────────────────────
// WHICH TRIALS ARE THIS MOSAIC — ⭐ ONE IMPLEMENTATION, AND IT LIVES HERE.
//
// 🔴 There used to be TWO copies of this rule — one in the new-project flow (which chose the trials a
// project is CREATED with) and one in `MosaicFeature` (which chose the trials a project is OPENED
// with). They drifted the moment one was corrected, and the symptom was baffling: a project whose
// document held 10 tiles opened onto a Range screen reading "11 snapshots", because the session had
// been loaded from the other copy's answer. `core/workspace.py`'s docstring records the same lesson
// about v1's three copies of the write guard. Import this; do not inline it.
//
// **His ruling, 2026-07-25:** *"if you read the log file you should be able to find out exactly which
// snapshots are part of the mosaic. only include those snapshots as part of it"* (BEHAVIOUR R2.8).
//
// ⛔ NO DATASET KNOWLEDGE (HARD RULE 3 / BEHAVIOUR I1). No trial number, count or range appears here.
// Both filters are computed from what the BACKEND measured off `log.txt` and the per-trial XML.
// ─────────────────────────────────────────────────────────────────────────────────────────────

export interface ShapeGroupLike {
  w: number;
  h: number;
  n: number;
  trials: number[];
}

export interface BlockLike {
  lo: number;
  hi: number;
  n: number;
}

/**
 * The trials a mosaic project opens on, or `null` when this dataset holds no square frames at all.
 *
 * Two filters, in this order:
 *   1. **shape** — square (N×N) tiles only. That is mosaic policy (512 = `t33.TILE`); a 512×128 frame
 *      is real data this feature cannot place. A session holds exactly one shape anyway — the backend
 *      refuses a mixed-shape open.
 *   2. **acquisition** — the ONE contiguous run of Snapshot trials holding the most of them. An
 *      imaging session interleaves runs (load a settings profile, take frames, load another), and
 *      `log.txt` records that, so a run with no other trial type inside it is one acquisition. The
 *      snapshots taken before the mosaic scan started — 260620d's `1` and `5–7`, the fixture's stray
 *      `5` — are their own little blocks, and they are not tiles of this mosaic.
 *
 * On 260620d this yields the whole 11–348 run (338 tiles, R2.1); on the committed fixture, 11–20
 * (10 tiles). Both are contiguous, which is *why* the Gaps field reads none on a fresh open (R2.3).
 *
 * ⚠️ **Deterministic.** `findOpenSession` matches an already-open session on the exact trial list this
 * returns, so the same dataset must always give the same answer — no `Date`, no ordering surprises.
 */
export function mosaicTrials(
  shapes: readonly ShapeGroupLike[],
  blocks: readonly BlockLike[],
): number[] | null {
  const square = [...shapes].filter((s) => s.w === s.h).sort((a, b) => b.n - a.n)[0];
  if (!square) return null;
  const squares = [...square.trials].sort((a, b) => a - b);
  if (!blocks || blocks.length === 0) return squares;

  // The acquisition holding the most square frames — not merely the longest block, which could be a
  // run of frames this feature cannot place.
  const best = [...blocks]
    .map((b) => squares.filter((t) => t >= b.lo && t <= b.hi))
    .sort((a, b) => b.length - a.length)[0];
  return best && best.length > 0 ? best : squares;
}
