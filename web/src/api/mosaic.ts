// MOSAIC — the typed request boundary for the mosaic feature's backend routes. Features call THESE, not
// `api.POST('/api/mosaic/...')` directly, so there is one typed seam against the frozen contract.
//
// ⛔ NO DATASET KNOWLEDGE. Nothing here names a trial, a count or an exclusion. The `refuse` list, the
// `trials` list and the `pass_split` are all values the CALLER computed from the human's document.

import { api, unwrap } from './client';
import type {
  RunDetectRequest,
  RunDetection,
  GapsResponse,
  BlankProposeRequest,
  BlankProposal,
  BuildStartRequest,
  BuildResult,
  SeedRequest,
  SeedResponse,
  MachineEvidenceRequest,
  MachineEvidenceResponse,
  DiscardMachineRequest,
  DiscardMachineResponse,
  MatchAnchorRequest,
  MatchResult,
  MatchScoreRequest,
  ScoreResult,
  RecheckRequest,
  ExportRequest,
  QcRequest,
  QcReport,
  MosaicDocument,
  JobRef,
} from './types';

// ── Run / gaps / screen ─────────────────────────────────────────────────────────

/**
 * Detect the run and pass split, or override them (`POST /api/mosaic/run`). ⭐ NOT a session reload —
 * a pure function of the session's inventory (milliseconds). Returns `gaps` with the run, because the
 * caller needs them the moment the trial list changes (a "consecutive" pair across a gap is a
 * multi-step jump; miss it and the next solve is silently poisoned).
 */
export async function detectRun(req: RunDetectRequest): Promise<RunDetection> {
  return unwrap(await api.POST('/api/mosaic/run', { body: req }));
}

/**
 * The gaps in a trial list (`POST /api/mosaic/gaps`) — a PURE function over the list. ⭐ This route is
 * the single place the app touches the exclusion module, and `gaps()` is the ONLY symbol it may reach
 * (BEHAVIOUR R2.5). Call it on EVERY change to the excluded set.
 */
export async function computeGaps(trials: number[]): Promise<GapsResponse> {
  return unwrap(await api.POST('/api/mosaic/gaps', { body: { trials } }));
}

/**
 * The Screen step's blank RECOMMENDATION (`POST /api/mosaic/screen/propose`). ⭐ It recommends; the
 * human ticks; nothing is auto-excluded. Needs `pass_split` because the threshold is defined in the
 * mosaic's terms (the 2nd percentile of pass-1 texture). No blur judgement, ever (BEHAVIOUR R17).
 */
export async function proposeScreen(req: BlankProposeRequest): Promise<BlankProposal> {
  return unwrap(await api.POST('/api/mosaic/screen/propose', { body: req }));
}

// ── Build / seed ─────────────────────────────────────────────────────────────────

/**
 * Start a solve (`POST /api/mosaic/build` → 202 `JobRef`). Poll with `useJob` for the ticking ETA.
 * ⭐ `trials` is the document's ACTIVE list (everything the user has NOT excluded) — the ONLY way a
 * frame ever leaves a build (BEHAVIOUR R35). `config: null` = t33's shipped defaults, the one-button
 * path; `pass_split` is the DETECTED value the caller sends, never a literal.
 */
export async function startBuild(req: BuildStartRequest): Promise<JobRef> {
  return unwrap(await api.POST('/api/mosaic/build', { body: req }));
}

/** A finished build's full result (`GET /api/mosaic/builds/{build_id}`). */
export async function getBuild(buildId: string): Promise<BuildResult> {
  return unwrap(
    await api.GET('/api/mosaic/builds/{build_id}', { params: { path: { build_id: buildId } } }),
  );
}

/**
 * Apply a build to a document (`POST /api/mosaic/seed`) — THE SERVER does this, not the front end.
 * 🔴 A re-solve must not destroy the human's work: it keeps every `anchored`/`human` tile and seeds
 * around them by the MEDIAN offset; if none of the human's tiles are in the build it REFUSES (409)
 * rather than guess (BEHAVIOUR R26).
 */
export async function seedBuild(req: SeedRequest): Promise<SeedResponse> {
  return unwrap(await api.POST('/api/mosaic/seed', { body: req }));
}

// ── Provenance ──────────────────────────────────────────────────────────────────

/**
 * The provenance evidence for a document (`POST /api/mosaic/document/machine-evidence`). ⚠️ Derived
 * from the document's HISTORY (a build block, or a single tile still carrying a `machine` position),
 * never from what it claims about itself. Powers the provenance panel — a live warning (BEHAVIOUR W5).
 */
export async function getMachineEvidence(doc: MosaicDocument): Promise<MachineEvidenceResponse> {
  const body: MachineEvidenceRequest = { doc };
  return unwrap(await api.POST('/api/mosaic/document/machine-evidence', { body }));
}

/**
 * `Skip — place by hand` (`POST /api/mosaic/document/discard-machine`). 🔴 DESTRUCTIVE, OR NOTHING: if
 * anything came from a machine it discards every position and the build; it never launders a seeded
 * build into an "independent ground truth" (BEHAVIOUR R27). `confirm` is literally `true` — no accident
 * path. Call `getMachineEvidence` first to name the count in the confirm.
 */
export async function discardMachine(doc: MosaicDocument): Promise<DiscardMachineResponse> {
  const body: DiscardMachineRequest = { doc, confirm: true };
  return unwrap(await api.POST('/api/mosaic/document/discard-machine', { body }));
}

// ── Match / score — the sweep primitive ─────────────────────────────────────────────

/**
 * ⭐⭐ THE PRIMITIVE (`POST /api/mosaic/match/anchor`): place the next tile (`Space`), the ranked
 * alternatives (`V`, `1`–`9`), rescue an unplaced tile, snap a drag (`mode: 'local'`).
 *
 * 🔴 THE PREFETCH IS THE SAME POST, FIRED EARLY, AND ITS ANSWER IS THROWN AWAY (BEHAVIOUR R21). The
 * server memoises on the anchor set + positions carried IN THIS BODY, so a warm foreground call is a
 * memo hit only when the anchor set it sends matches what the prefetch assumed. ⇒ ⛔ NEVER wrap this in
 * a client-side cache keyed on the trial number — that is exactly how the correctness trap gets sprung
 * (§6.8). This function holds no state; keep it that way. The prefetch must include the tile under
 * judgement in `anchors` (it assumes the user will press `A`).
 */
export async function matchAnchor(req: MatchAnchorRequest): Promise<MatchResult> {
  return unwrap(await api.POST('/api/mosaic/match/anchor', { body: req }));
}

/**
 * `POST /api/mosaic/match/score` — "you dropped it here; what do the pixels say?" One `exact_ncc`, no
 * search (~31 ms). Live during a drag, to label alternatives, and to re-measure a diverted tile's NCC
 * where it actually sits. ⚠️ `ncc` is `null` below the overlap floor — the honest answer, never `0.0`.
 */
export async function matchScore(req: MatchScoreRequest): Promise<ScoreResult> {
  return unwrap(await api.POST('/api/mosaic/match/score', { body: req }));
}

// ── Recheck / export / qc ─────────────────────────────────────────────────────────

/**
 * The GLOBAL staleness re-check (`POST /api/mosaic/recheck` → 202 `JobRef`). 🔴 It NEVER moves a tile —
 * it only measures. Anything disagreeing by more than `tolerance_px` STAYS FLAGGED; the caller clears
 * only the flags it is told it may clear. It must be global, not local (BEHAVIOUR R25).
 */
export async function startRecheck(req: RecheckRequest): Promise<JobRef> {
  return unwrap(await api.POST('/api/mosaic/recheck', { body: req }));
}

/**
 * Export the outputs (`POST /api/mosaic/export` → 202 `JobRef`). 7 files; the coverage mask is
 * MANDATORY (asking for `tiff` implies `coverage`). The result describes the document AS EXPORTED
 * (stamped), never as posted (BEHAVIOUR R37, R28).
 */
export async function startExport(req: ExportRequest): Promise<JobRef> {
  return unwrap(await api.POST('/api/mosaic/export', { body: req }));
}

/** The QC report — what the human did vs what the machine said (`POST /api/mosaic/qc`). */
export async function computeQc(doc: MosaicDocument): Promise<QcReport> {
  const body: QcRequest = { doc };
  return unwrap(await api.POST('/api/mosaic/qc', { body }));
}
