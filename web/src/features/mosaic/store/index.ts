// THE MOSAIC SWEEP STORE — public API. The six step-UIs import from here; nothing reaches into a module
// file directly. Build to this surface and the steps stay thin (they hold the JSX; the spine holds none).

// The store hook + its state/action interface.
export { useSweepStore } from './sweepStore';
export type { SweepState } from './sweepStore';

// The store-facing types (evidence, decision, banner, hooks, positions).
export type {
  Tile,
  Tiles,
  TileState,
  Position,
  Evidence,
  Banner,
  BannerKind,
  PlacementDecision,
  UndoEntry,
  MoveSource,
  SweepHooks,
} from './types';

// The constants that must not diverge (BEHAVIOUR §7).
export {
  TILE,
  FADE_MS,
  THIN_MARGIN,
  SNAP_RADIUS,
  SNAP_RADIUS_MAX,
  MAX_CANDIDATES,
  UNDO_DEPTH,
  FOLD_MS,
  AUTOSAVE_MS,
  SCORE_DEBOUNCE,
  RECHECK_TOL_PX,
  SOLVER_MARGIN_MIN,
  SOLVER_NCC_MIN,
  SOLVER_DISAGREE_PX,
  CONFIDENT_DISAGREE_PX,
  SMALL_APERTURE_MAX,
  FLOAT_ALPHA,
  FLOAT_ALPHA_MIN,
  FLOAT_ALPHA_MAX,
  FLOAT_ALPHA_STEP,
} from './constants';

// The pure solver-fallback classifier (BEHAVIOUR R15) — exported so a step or a test can classify
// synthetic evidence without touching the store.
export { classifyPlacement, matchConfidence } from './placement';

// The pure state-machine helpers — the transition table, the derived views, and the fact-clearing rules.
export {
  statusFor,
  stateFor,
  tileOf,
  anchoredTrials,
  activeTrials,
  anyPlaced,
  nextTrial,
  prevTrial,
  counts,
  applyState,
  applyPos,
  markStaleAfter,
  setTile,
  positionsOf,
  solverXY,
  type Counts,
} from './machine';

// The anchor-field request builders and the R22 field signature.
export {
  buildMatchRequest,
  buildPrefetchRequest,
  buildScoreRequest,
  fieldSignature,
  type MatchInputs,
} from './field';
