// THE CONSTANTS THAT MUST NOT DIVERGE (docs/BEHAVIOUR.md §7).
//
// Both halves of the old app hard-coded these; the rewrite keeps ONE copy, here, for the sweep store.
// The camera/render constants that belong to the viewer (FEATHER_PX, UNVERIFIED_ALPHA) and the job
// poll cadence (POLL_MS, owned by src/api/jobs.ts) are NOT re-declared — they live where they are used.
// Numbers marked "measured" were derived from real matches scored against the human ground truth and
// must not be re-tuned "from a vibe" (BEHAVIOUR R15).

/** The subregion edge, px. Positions are TOP-LEFT corners of this square (BEHAVIOUR R19). */
export const TILE = 512;

/** The placement fade, ms. THE FADE IS THE POINT — do not shorten it "to feel snappier" (R13.3, §7). */
export const FADE_MS = 1000;

/** margin below this = the signature of a surviving grid alias. The UI flags it LOUDLY (W2). */
export const THIN_MARGIN = 0.1;

/** Local-search radius for `S` / a drag-snap. */
export const SNAP_RADIUS = 64;
/** ⚠️ NEVER widen a *local* search past this in the UI — the electrode grid repeats every 256 px, so a
 *  wide local search locks onto an alias. To search wide, use a GLOBAL match (R23; MatchAnchorRequest). */
export const SNAP_RADIUS_MAX = 128;

/** ⭐ 9, not 8 — or the key `9` can never fire (R12.5). */
export const MAX_CANDIDATES = 9;

/** Undo depth (R36). */
export const UNDO_DEPTH = 100;
/** Tagged-undo folding window, ms: a held arrow key folds into a single step (R36). */
export const FOLD_MS = 700;

/** Autosave debounce, ms — PLUS unconditionally on every A and E (R29). The timer itself is owned by
 *  the document store; the sweep store only *signals* a judgement (see `SweepHooks.onChange`). */
export const AUTOSAVE_MS = 2000;

/** Live-NCC debounce during a drag, ms (R (drag) — MatchScoreRequest). */
export const SCORE_DEBOUNCE = 150;

/** The stale re-check's agreement tolerance, px. Disagree by more than this and the tile STAYS flagged
 *  (R25 — the re-check is allowed to say NO). */
export const RECHECK_TOL_PX = 5.0;

// ─────────────────────────────────────────────────────────────────────────────────────────────────
// ⭐⭐ THE SOLVER-FALLBACK TRIO (BEHAVIOUR R15). All three are load-bearing and all three were measured
// from 411 real matches. 🔴 NEITHER GATE IS REDUNDANT: on the 298 wrong matches, 4 trip ONLY margin
// (t105: 353 px wrong at NCC 0.7450 — sails past the NCC gate) and 8 trip ONLY ncc (t182: 2,042 px
// wrong at margin 0.3230 — sails past the margin gate). Delete `SOLVER_NCC_MIN` and trial 182 is judged
// CONFIDENT and placed 2,042 px from the human with no banner. With the whole fallback removed: 162/311
// vs 310/311. Do not simplify it. Do not re-tune it.
// ─────────────────────────────────────────────────────────────────────────────────────────────────

/** A match with margin below this is NOT trusted to overrule the solver. */
export const SOLVER_MARGIN_MIN = 0.2;
/** A match with best-NCC below this is NOT trusted to overrule the solver. */
export const SOLVER_NCC_MIN = 0.65;
/** A not-confident match that disagrees with the solver by MORE than this (px) is DIVERTED to the
 *  solver's position (R15). At or below it, the match stands (nothing to divert away from). */
export const SOLVER_DISAGREE_PX = 10.0;

/** A CONFIDENT match landing further than this from the solver raises W11 (the field wins, but say so). */
export const CONFIDENT_DISAGREE_PX = 20.0;
/** `n_anchors ≤ this` on the tile under judgement raises the small-aperture warning W7. */
export const SMALL_APERTURE_MAX = 2;

/** The floating tile's opacity (R13): default 1.00, slider range 0.15–1.00 step 0.05. Session-only —
 *  it is NEVER written to the project file (R13.6). */
export const FLOAT_ALPHA = 1.0;
export const FLOAT_ALPHA_MIN = 0.15;
export const FLOAT_ALPHA_MAX = 1.0;
export const FLOAT_ALPHA_STEP = 0.05;
