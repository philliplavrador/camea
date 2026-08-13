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
export type RecomputeResult = Schemas['RecomputeResult'];

// ── Datasets / browser ────────────────────────────────────────────────────────
export type DatasetSummary = Schemas['DatasetSummary'];
export type DatasetListResponse = Schemas['DatasetListResponse'];
export type DatasetDetail = Schemas['DatasetDetail'];
export type DatasetAtRequest = Schemas['DatasetAtRequest'];
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

// ── Projects — one project is ONE FOLDER, and Camea owns it (R44) ────────────────
export type AnalysisSummary = Schemas['AnalysisSummary'];
export type AnalysisListResponse = Schemas['AnalysisListResponse'];
export type CreateAnalysisRequest = Schemas['CreateAnalysisRequest'];
export type MigrationReport = Schemas['MigrationReport'];
export type MigratedProject = Schemas['MigratedProject'];
export type FailedMigration = Schemas['FailedMigration'];

// ── Outputs — ⭐ the only door to a project's files (R44) ─────────────────────────
export type OutputEntry = Schemas['OutputEntry'];
export type OutputListResponse = Schemas['OutputListResponse'];
export type CopyOutputsRequest = Schemas['CopyOutputsRequest'];
export type CopyOutputsResponse = Schemas['CopyOutputsResponse'];

// ── Mosaic: run / gaps / screen ──────────────────────────────────────────────────
export type RunDetectRequest = Schemas['RunDetectRequest'];
export type RunDetection = Schemas['RunDetection'];
export type PassSplit = Schemas['PassSplit'];
export type RescopeRequest = Schemas['RescopeRequest'];
export type RescopeResponse = Schemas['RescopeResponse'];
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
export type RecomputeRequest = Schemas['RecomputeRequest'];
export type ExportRequest = Schemas['ExportRequest'];
export type QcRequest = Schemas['QcRequest'];
export type QcReport = Schemas['QcReport'];
export type MachineEvidenceRequest = Schemas['MachineEvidenceRequest'];
export type MachineEvidenceResponse = Schemas['MachineEvidenceResponse'];
export type DiscardMachineRequest = Schemas['DiscardMachineRequest'];
export type DiscardMachineResponse = Schemas['DiscardMachineResponse'];

// ── Electrodes — the fitted MEA lattice (shared by both features) ─────────────────
// R45.8: `array_coverage` is the user's own declaration about the PICTURE — "full" = the whole chip
// is in frame (so the fit may be checked against the device's 220 × 120), "partial" = only some of
// it (so nothing but the 17.5 µm scale applies and 1-1 is the top-left of the IMAGED REGION). The
// union is read off the generated request, never re-typed here.
export type ArrayCoverage = Schemas['ElectrodeMapRequest']['array_coverage'];
/**
 * ⭐ THE CHIP, OFF THE WIRE (`GET /api/electrodes/device`). Every device number lives in the
 * backend's `DeviceSpec`/`MAXWELL` and nowhere else — this alias is how the UI READS them instead of
 * retyping them into button prose, where nothing would keep them honest.
 */
export type ElectrodeDevice = Schemas['ElectrodeDevice'];
export type ElectrodeCells = Schemas['ElectrodeCells'];
export type ElectrodeMapBlock = Schemas['ElectrodeMapBlock'];
export type ElectrodeMapPayload = Schemas['ElectrodeMapPayload'];
export type ElectrodeMapRequest = Schemas['ElectrodeMapRequest'];
export type ElectrodeMapResult = Schemas['ElectrodeMapResult'];
export type VideoElectrodeMapRequest = Schemas['VideoElectrodeMapRequest'];

// ── The electrical half: what an electrode actually recorded ──────────────────────
/**
 * ⭐ The mosaic says WHERE each electrode is; a MaxWell recording says WHAT it measured. Three
 * things these types deliberately keep visible, because each one silently corrupts the pairing the
 * whole app exists to produce:
 *   • `recorded: false` is the ORDINARY answer — only ~1k of the chip's 26.4k pads are routed at
 *     acquisition, so most clicks have no trace and must say so rather than draw an empty chart.
 *   • `health.flat` means the waveform did not reconstruct. MaxWell compresses the raw stream with
 *     a proprietary filter whose decoder ships with MaxLab Live; the published one does not decode
 *     this project's files. A railed window looks exactly like a real silent electrode.
 *   • `orientation.confirmed: false` means the chip's seating in the mosaic is not yet established
 *     — no file records it — so the electrode's identity is provisional, not settled.
 */
export type MeaAttachment = Schemas['MeaAttachment'];
export type MeaAttachRequest = Schemas['MeaAttachRequest'];
export type MeaOrientation = Schemas['MeaOrientation'];
export type MeaRecordingSummary = Schemas['MeaRecordingSummary'];
export type MeaSpike = Schemas['MeaSpike'];
export type MeaSyncEpisode = Schemas['MeaSyncEpisode'];
export type TraceHealthPayload = Schemas['TraceHealthPayload'];
export type ElectrodeTracePayload = Schemas['ElectrodeTracePayload'];

// ── Videomosaic: probe / create / build / save ────────────────────────────────────
export type VideoSource = Schemas['VideoSource'];
export type VideoProbeRequest = Schemas['VideoProbeRequest'];
export type CreateVideoProjectRequest = Schemas['CreateVideoProjectRequest'];
export type VideoBuildRequest = Schemas['VideoBuildRequest'];
export type VideoCanvasSize = Schemas['VideoCanvasSize'];
export type VideoKeyframeRecord = Schemas['VideoKeyframeRecord'];
export type VideoMosaicBuildResult = Schemas['VideoMosaicBuildResult'];
export type VideoMosaicDocument = Schemas['VideoMosaicDocument'];

// ── Videomosaic: regions — a recording located on the built mosaic ─────────────────
// The document is SERVER-owned here (as with the build and the video electrode map): the locate/snap
// jobs save `doc["regions"]` themselves, so these types are what the UI READS, never what it authors.
export type RegionRecord = Schemas['RegionRecord'];
export type RegionsPayload = Schemas['RegionsPayload'];
export type RegionZoom = Schemas['RegionZoom'];
export type RegionCandidate = Schemas['RegionCandidate'];
export type RegionElectrodes = Schemas['RegionElectrodes'];
export type LocateRegionRequest = Schemas['LocateRegionRequest'];
export type SnapRegionRequest = Schemas['SnapRegionRequest'];
export type RegionUpdateRequest = Schemas['RegionUpdateRequest'];
export type LocateRegionResult = Schemas['LocateRegionResult'];
/**
 * The TWO states a region can be in. ⭐ `unconfirmed` until the human says otherwise — nothing
 * promotes itself (I3, applied to a rectangle instead of a tile). Read off the RECORD, whose union is
 * the clean literal pair; the PATCH request's copy is nullable ("leave it alone") and would drag a
 * `null` into every consumer.
 */
export type RegionStatus = RegionRecord['status'];

// ── System: settings / fs / dialogs / health ──────────────────────────────────────
export type Settings = Schemas['Settings'];
export type SettingsUpdate = Schemas['SettingsUpdate'];
export type FsListResponse = Schemas['FsListResponse'];
export type FsEntry = Schemas['FsEntry'];
export type HealthResponse = Schemas['HealthResponse'];
export type DialogPathResponse = Schemas['DialogPathResponse'];
