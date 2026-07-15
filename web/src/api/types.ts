// Friendly aliases for the GENERATED contract types.
//
// HARD RULE 2: the contract is generated, never hand-written. Every type below is an *alias* of a
// schema `openapi-typescript` produced from docs/openapi.json — not a re-declaration. Features import
// `MatchResult` / `MosaicDocument` / `Job` from here instead of reaching into
// `components['schemas'][...]`, so there is exactly one place the app names a backend type, and it
// tracks the backend automatically when `npm run gen:api` regenerates the schema.
//
// ⛔ Do NOT add a hand-shaped request/response interface to this file. If the backend owns the shape,
// it belongs to the generated `components` and is aliased here. If it drifts, regenerate.

import type { components } from './schema';

type Schemas = components['schemas'];

// ── Primitives shared across the contract ────────────────────────────────────
/** A world top-left corner, `[x, y]`. Positions in Camea are TOP-LEFT, never centres (BEHAVIOUR R19). */
export type Position = [number, number];

// ── Jobs ─────────────────────────────────────────────────────────────────────
export type Job = Schemas['Job'];
export type JobRef = Schemas['JobRef'];
export type JobError = Schemas['JobError'];
export type JobListResponse = Schemas['JobListResponse'];
export type JobCancelResponse = Schemas['JobCancelResponse'];
/** The five lifecycle states a job moves through. */
export type JobState = Job['state'];
export type OpenJobResult = Schemas['OpenJobResult'];
export type BuildResult = Schemas['BuildResult'];
export type ExportResult = Schemas['ExportResult'];
export type ExportedFile = Schemas['ExportedFile'];
export type RecheckResult = Schemas['RecheckResult'];
export type RecheckRow = Schemas['RecheckRow'];

// ── Datasets / browser ────────────────────────────────────────────────────────
export type DatasetSummary = Schemas['DatasetSummary'];
export type DatasetListResponse = Schemas['DatasetListResponse'];
export type DatasetDetail = Schemas['DatasetDetail'];
export type DatasetScanRequest = Schemas['DatasetScanRequest'];
export type TrialMeta = Schemas['TrialMeta'];
export type SnapshotBlock = Schemas['SnapshotBlock'];
export type ShapeGroup = Schemas['ShapeGroup'];
export type AnalysisRef = Schemas['AnalysisRef'];

// ── Sessions ───────────────────────────────────────────────────────────────────
export type SessionResponse = Schemas['SessionResponse'];
export type SessionListResponse = Schemas['SessionListResponse'];
export type OpenSessionRequest = Schemas['OpenSessionRequest'];
export type SkippedFrame = Schemas['SkippedFrame'];
export type Tone = Schemas['Tone'];
export type ToneUpdate = Schemas['ToneUpdate'];
export type ToneSnapshot = Schemas['ToneSnapshot'];
export type GpuInfo = Schemas['GpuInfo'];
export type TextureResponse = Schemas['TextureResponse'];
export type LogResponse = Schemas['LogResponse'];
export type LogEntry = Schemas['LogEntry'];
export type ThumbsResponse = Schemas['ThumbsResponse'];

// ── Documents (the generic envelope + the mosaic payload) ───────────────────────
export type Document = Schemas['Document'];
export type DocumentResponse = Schemas['DocumentResponse'];
export type MosaicDocument = Schemas['MosaicDocument'];
export type TileRecord = Schemas['TileRecord'];
/** The FOUR tile states. There are no others (BEHAVIOUR §4). Derived from the contract, not spelled out. */
export type TileState = TileRecord['state'];
export type Provenance = Schemas['Provenance'];
export type HumanEdits = Schemas['HumanEdits'];
export type BlankScanBlock = Schemas['BlankScanBlock'];
export type BuildBlock = Schemas['BuildBlock'];
export type RunBlock = Schemas['RunBlock'];
export type TolerancePx = Schemas['TolerancePx'];
export type Scale = Schemas['Scale'];
export type SeededFrom = Schemas['SeededFrom'];
export type SaveResult = Schemas['SaveResult'];
export type SaveDocumentRequest = Schemas['SaveDocumentRequest'];
export type AutosaveRequest = Schemas['AutosaveRequest'];
export type LoadDocumentRequest = Schemas['LoadDocumentRequest'];
export type LoadDocumentResponse = Schemas['LoadDocumentResponse'];
export type ValidateDocumentRequest = Schemas['ValidateDocumentRequest'];
export type ValidationReport = Schemas['ValidationReport'];
export type DocumentProblem = Schemas['DocumentProblem'];

// ── Workspace / analyses ────────────────────────────────────────────────────────
export type WorkspaceInfo = Schemas['WorkspaceInfo'];
export type WorkspaceSetRequest = Schemas['WorkspaceSetRequest'];
export type AnalysisSummary = Schemas['AnalysisSummary'];
export type AnalysisListResponse = Schemas['AnalysisListResponse'];
export type CreateAnalysisRequest = Schemas['CreateAnalysisRequest'];

// ── Mosaic: run / gaps / screen ──────────────────────────────────────────────────
export type RunDetectRequest = Schemas['RunDetectRequest'];
export type RunDetection = Schemas['RunDetection'];
export type PassSplit = Schemas['PassSplit'];
export type GapsRequest = Schemas['GapsRequest'];
export type GapsResponse = Schemas['GapsResponse'];
export type BlankProposeRequest = Schemas['BlankProposeRequest'];
export type BlankProposal = Schemas['BlankProposal'];

// ── Mosaic: build / seed ─────────────────────────────────────────────────────────
export type BuildStartRequest = Schemas['BuildStartRequest'];
export type BuildConfig = Schemas['BuildConfig'];
export type PerTileEvidence = Schemas['PerTileEvidence'];
export type SeedRequest = Schemas['SeedRequest'];
export type SeedResponse = Schemas['SeedResponse'];

// ── Mosaic: match / score (the sweep primitive) ───────────────────────────────────
export type MatchAnchorRequest = Schemas['MatchAnchorRequest'];
export type MatchResult = Schemas['MatchResult'];
export type Candidate = Schemas['Candidate'];
export type CompositeInfo = Schemas['CompositeInfo'];
export type Refusal = Schemas['Refusal'];
export type RejectedMatch = Schemas['RejectedMatch'];
export type MatchScoreRequest = Schemas['MatchScoreRequest'];
export type ScoreResult = Schemas['ScoreResult'];

// ── Mosaic: recheck / export / qc / provenance ────────────────────────────────────
export type RecheckRequest = Schemas['RecheckRequest'];
export type ExportRequest = Schemas['ExportRequest'];
export type QcRequest = Schemas['QcRequest'];
export type QcReport = Schemas['QcReport'];
export type MachineEvidenceRequest = Schemas['MachineEvidenceRequest'];
export type MachineEvidenceResponse = Schemas['MachineEvidenceResponse'];
export type DiscardMachineRequest = Schemas['DiscardMachineRequest'];
export type DiscardMachineResponse = Schemas['DiscardMachineResponse'];

// ── System: settings / fs / dialogs / health ──────────────────────────────────────
export type Settings = Schemas['Settings'];
export type SettingsUpdate = Schemas['SettingsUpdate'];
export type FsListResponse = Schemas['FsListResponse'];
export type FsEntry = Schemas['FsEntry'];
export type HealthResponse = Schemas['HealthResponse'];
export type DialogPathResponse = Schemas['DialogPathResponse'];
