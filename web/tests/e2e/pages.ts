// ─────────────────────────────────────────────────────────────────────────────
// pages.ts — THE PAGE-OBJECT + TESTID CONTRACT.
//
// This file is the single machine-readable source of the selector contract between the e2e specs
// (this task) and the UI (the Wizard/Core agents). Every `data-testid`, `data-*` attribute, role and
// backend route the specs depend on is named HERE and documented in README.md. If a spec needs a hook
// that is not in `TID`, it goes in `TID` first — never a bare string literal buried in a spec.
//
// The specs are written BEFORE the UI exists, so every helper below WILL fail today (by timeout on a
// missing testid). That is the point: these are the acceptance contract the UI must grow into.
//
// Rules for the UI agents reading this:
//   • Expose each `TID.*` string as `data-testid="…"` on the element the comment describes.
//   • Where a `data-*` attribute is named (e.g. a queue chip's `data-state`), expose it too — specs
//     assert on it.
//   • Routes in `ROUTES` are the FROZEN backend contract (docs/openapi.json). The sweep's placement
//     match MUST go through `ROUTES.matchAnchor` so R21/R22 are observable/stubbable.
// ─────────────────────────────────────────────────────────────────────────────

import { type Page, type Locator, expect } from '@playwright/test';
import { FIXTURE, PATHS, SHORT } from './fixture';

export const STEPS = ['load', 'range', 'screen', 'place', 'sweep', 'mosaic', 'electrodes'] as const;
export type StepName = (typeof STEPS)[number];

/**
 * ⭐ THE VIDEO PIPELINE (R46.1) — *"it should be all one pipeline with a progress bar at the top"*.
 * A DIFFERENT set from the snapshot wizard's `STEPS` above, with its own nav (`TID.pipelineStep`):
 * a step is LOCKED until the one before it is done, and the gate is read off the DOCUMENT.
 */
export const PIPELINE = ['survey', 'mosaic', 'electrodes', 'regions'] as const;
export type PipelineStepName = (typeof PIPELINE)[number];

/** The frozen backend routes the specs inspect or stub. (docs/openapi.json — never hand-write a body.) */
export const ROUTES = {
  datasets: '/api/datasets',
  openSession: '/api/sessions',
  matchAnchor: '/api/mosaic/match/anchor', // carries {session_id, target, anchors[], positions{}, refuse[]}
  matchScore: '/api/mosaic/match/score',
  screenPropose: '/api/mosaic/screen/propose',
  build: '/api/mosaic/build',
  export: '/api/mosaic/export',
  recompute: '/api/mosaic/recompute', // 202 job — freeze anchors, re-place the rest (R40)
  gaps: '/api/mosaic/gaps',
  run: '/api/mosaic/run',
  saveAs: '/api/documents/save-as', //   Export a project to a file
  load: '/api/documents/load',
  datasetsAt: '/api/datasets/at', //     "look at THIS folder" — no registry, nothing remembered
  projects: '/api/projects', //          a project IS one folder (list/create/delete/PATCH rename)
  document: '/api/analyses', //          PUT /api/analyses/{id}/document — the durable auto-save (R29)
  electrodes: '/api/mosaic/electrodes', // POST …/map → 202 job (body carries `array_coverage` —
  //                                     R45.8, the user's own declaration); GET …/{id} → 404 until mapped
  electrodeDevice: '/api/electrodes/device', // ⭐ CORE, not a feature: the chip the "whole chip
  //                                     imaged" fit is held to. The UI READS its numbers from here
  //                                     instead of retyping them (R45.8 — one place owns them, and
  //                                     it is the same place that enforces them).
  jobs: '/api/jobs', //                  GET /api/jobs/{id} — the 500 ms poll every long op rides
  regions: '/api/videomosaic/regions', // POST …/locate and …/snap → 202 job (kind `locate_region`);
  //                                     PATCH renames/confirms. GET …/{id}/regions → the list +
  //                                     `stale`. R46 — where each fixed-field recording sits.
  videomosaic: '/api/videomosaic', //    the video feature's prefix, for the PER-PROJECT reads the
  //                                     Regions spec stubs: `…/{id}/regions`, `…/{id}/electrodes`,
  //                                     `…/{id}/outputs/{name}` (the preview the camera draws).
} as const;

/** THE TESTID REGISTRY. Grouped by screen; see README.md for the human-readable table. */
export const TID = {
  // ── Home / shell (2026-07-24: the home is a PROJECT MANAGER — R41) ─────────────
  manager: 'project-manager', //            the home. ⭐ No first-run prompt since 2026-07-25 (R41.2)
  newProject: 'new-project', //             the "New project" CTA
  projectCard: 'project-card', //           data-project-id; the card is the Open affordance
  projectName: 'project-name',
  projectDataDir: 'project-data-dir', //    where its DATA came from — the one path HE named
  projectRename: 'project-rename',
  projectExport: 'project-export',
  projectDelete: 'project-delete', //       ⭐ R44: delete means delete. There is no Remove.
  projectGrid: 'project-grid',
  projectsUnreadable: 'projects-unreadable', // store folders that could not be read
  projectsMigrated: 'projects-migrated', //  the one-time R44 "your projects moved" notice
  // the new-project flow (/new): name → task → where the DATA is (R44: no save folder)
  newProjectFlow: 'new-project-flow',
  npName: 'np-name',
  npNext: 'np-next',
  npBack: 'np-back',
  npCancel: 'np-cancel',
  npCreate: 'np-create',
  taskCard: 'task-card', //                 data-task = videomosaic | mea (⭐ two tasks again since
  //                                        2026-08-14, so the Task step is a real stop). ⚠️ Address
  //                                        a card by `data-task`, NEVER by position.
  projectNoInput: 'project-no-input', //    a card whose task has been given nothing yet ("No
  //                                        recordings yet") — where a video's filename would sit
  // ── Analyze MEA (the standalone task) ───────────────────────────────────────
  meaFeature: 'mea-feature', //             the project screen root
  meaProjectName: 'mea-project-name',
  meaEmpty: 'mea-empty', //                 the empty state: no recordings on the shelf yet
  meaAddRecordings: 'mea-add-recordings', // ⭐ ENABLED since 002. Opens the same picker the wizard
  //                                        showed him — `mea-add-dialog`.
  // ── the shelf (002) ─────────────────────────────────────────────────────────
  meaShelf: 'mea-shelf',
  meaRecording: 'mea-recording', //         one row; data-recording-id, data-copy, data-missing
  meaRecordingLabel: 'mea-recording-label',
  meaRecordingFacts: 'mea-recording-facts', // duration · channels · spikes · size, READ OFF THE
  //                                        FILE every time. Absent on a row that lost its file.
  meaRecordingCopy: 'mea-recording-copy', // where Camea is reading it from, in plain words
  meaRecordingMissing: 'mea-recording-missing', // 🔴 the live warning: not where you left it
  meaRemove: 'mea-remove-recording',
  meaRemoveConfirm: 'mea-remove-confirm', // ⭐ the ONE confirm on this screen — appears only when
  //                                        Camea's copy is the last one left (his ruling 2026-08-14)
  meaRemoveAnyway: 'mea-remove-anyway',
  meaAddDialog: 'mea-add-dialog',
  meaAddConfirm: 'mea-add-confirm',
  // ── the import tick-list (002) — ⭐ ONE component, mounted in the wizard AND in the shelf ──
  meaImport: 'mea-import',
  meaChooseFolder: 'mea-choose-folder',
  meaPickFiles: 'mea-pick-files', //        the native multi-select; a 501 with no window
  meaImportFolder: 'mea-import-folder',
  meaImportRow: 'mea-import-row', //        data-readable, data-path
  meaImportTick: 'mea-import-tick',
  meaImportRefused: 'mea-import-refused', // ⛔ a file refused BY NAME, on the list, never dropped
  meaImportNone: 'mea-import-none', //      "no recordings in this folder"
  meaImportError: 'mea-import-error', //    the browse itself failed (a live warning, not a toast)
  meaImportStart: 'mea-import-start', //    before he has chosen a folder
  meaTickAll: 'mea-tick-all',
  npMeaCount: 'np-mea-count', //            the wizard Files step's running count
  npMeaError: 'np-mea-error', //            a refusal, INLINE beside the ticks (never a toast)
  // ── the ONE path box (R41.3 → R42 → ⭐ R44: "into" is gone, the app owns the folder) ────────
  paths: 'project-paths',
  fromField: 'from-field', //               "Pull data from" — a PathField
  datasetChoice: 'dataset-choice', //       shown ONLY when one folder holds several acquisitions
  card: 'dataset-card', //                  the RECEIPT for the folder he typed, not a browse card
  cardName: 'dataset-name',
  cardSnapshots: 'dataset-snapshots',
  cardShapes: 'dataset-shapes',
  // the shared path widgets (PathField / FolderPicker)
  pathInput: 'path-input',
  pathSubmit: 'path-submit',
  pathBrowse: 'path-browse',
  pathError: 'path-error',
  topbar: 'topbar',
  homeLink: 'home-link',
  saveIndicator: 'save-indicator', //       R5/R29 (reframed) — "Saved / Saving… / Couldn't save"; data-state
  toast: 'toast', //                        role=status|alert; transient messages (locked-step, resume…)

  // ── Wizard nav ────────────────────────────────────────────────────────────
  wizard: 'wizard',
  wizardSteps: 'wizard-steps',
  step: (n: StepName) => `wizard-step-${n}`, // each: data-locked, data-active, aria-current, text label

  // ── 1 · Load ──────────────────────────────────────────────────────────────
  loadDir: 'load-dir',
  loadBrowse: 'load-browse',
  loadOpen: 'load-open',
  loadOpenDataset: 'load-open-dataset', //  the open project's dataset name + its "N trials · K excluded"
  loadPhase: 'load-phase',
  loadProject: 'load-project', //           R5.3 — "Load a project…" (reachable cold)
  loadResultFORBIDDEN: 'load-result', //    R4.5/§6.6 — must NOT exist

  // ── 2 · Range ─────────────────────────────────────────────────────────────
  rangeFacts: 'range-facts',
  factTrials: 'fact-trials',
  factRange: 'fact-range',
  // 2026-07-24: the Pass split fact + its override input are GONE (R4.6) — an internal build detail now.
  factGaps: 'fact-gaps', //                 text "none" on fresh open (R2.3); grows only on user exclude
  rangeLo: 'range-lo',
  rangeHi: 'range-hi',
  rangeApply: 'range-apply',
  contactSheet: 'contact-sheet',
  contactCell: 'contact-cell', //           data-trial, data-out, data-out-reason=range|unusable
  sheetLegend: 'sheet-legend',
  sheetNOut: 'sheet-n-out', //              how many loaded snapshots are NOT tiles of this mosaic

  // ── 3 · Screen ────────────────────────────────────────────────────────────
  screenFacts: 'screen-facts',
  factRecommended: 'fact-recommended',
  factThreshold: 'fact-threshold',
  screenGrid: 'screen-grid',
  screenCard: 'screen-card', //             data-trial, data-choice=keep|hand|exclude
  screenKeep: 'screen-keep', //             within a card; aria-pressed
  screenHand: 'screen-handplace', //        DEFAULT selected (R6.2)
  screenExclude: 'screen-exclude',
  screenTexture: 'screen-card-texture',
  screenPlaceNext: 'screen-place-next', //  "Place the tiles →" (fires putRefusals first — R6.7)
  // NEGATIVE — bulk actions are GONE (R6b). These must NOT exist:
  bulkTickAllFORBIDDEN: 'screen-tick-all',
  bulkTickNoneFORBIDDEN: 'screen-tick-none',
  bulkExcludeTickedFORBIDDEN: 'screen-exclude-ticked',

  // ── 4 · Place ─────────────────────────────────────────────────────────────
  placeCost: 'place-cost',
  placeGpu: 'place-gpu',
  placeRun: 'place-run',
  placeCancel: 'place-cancel',
  placeUseCache: 'place-use-cache',
  placeSkip: 'place-skip', //               "Skip — place by hand" (destructive — R27)
  placeProgressBar: 'place-progress-bar',
  placeEta: 'place-eta', //                 R8 — ticks DOWN every second, never frozen > 2 s
  placePhase: 'place-phase',
  placeLog: 'place-log', //                 last 8 lines (R8.7)
  placeWorklist: 'place-worklist',
  placeWorklistItem: 'place-worklist-item',
  placeAdvanced: 'place-advanced',

  // ── 5 · Sweep (the stage) ─────────────────────────────────────────────────
  stage: 'stage',
  // The <canvas> also EXPOSES these live data-* attributes (R9 — the display must not lie about what
  // it draws, which is a different thing from tile state):
  //   data-anchor-layer      integer — how many certified tiles are BAKED INTO the drawn field
  //                          (R9.1 = 0 at sweep start; R9.2 increments on A). NOT the same as state.
  //   data-unverified-drawn  "true"/"false" — the unverified layer is maintained but NOT drawn in the
  //                          sweep (R9.3/R9.4/R9.5). Must be "false".
  //   data-diff              "true"/"false" — Difference mode (mirrors sweep-difference aria-pressed).
  //   data-float-alpha       the floating tile's current opacity 0.15–1.00 (R13; default "1").
  canvas: 'sweep-canvas',
  banner: 'banner', //                      the loud running commentary (divert/stale/end-of-run…)
  // action cluster — all seven carry a `?` (R7.1)
  actAnchor: 'sweep-anchor',
  actExclude: 'sweep-exclude',
  actNext: 'sweep-next',
  actReplay: 'sweep-replay',
  actDifference: 'sweep-difference',
  actAlternatives: 'sweep-alternatives',
  actSnap: 'sweep-snap',
  // camera
  camFit: 'sweep-fit',
  camOneOne: 'sweep-oneone',
  camUndo: 'sweep-undo',
  camRedo: 'sweep-redo',
  // header counts (each hidden at zero where noted)
  headerAnchored: 'header-anchored',
  headerUnverified: 'header-unverified',
  headerDiverted: 'header-diverted', //     hidden at 0 (R15b)
  // left rail
  queue: 'queue',
  queueChip: 'queue-chip', //               data-trial, data-state, data-cursor, data-stale
  queueBack: 'queue-back',
  queueFilterOutstanding: 'queue-filter-outstanding',
  queueCount: 'queue-count',
  rescue: 'rescue',
  rescueItem: 'rescue-item', //             data-trial
  rescueBtn: 'rescue-btn',
  opacitySlider: 'opacity-slider', //       R13 — 15..100, step 5, default 100
  toneLo: 'tone-lo',
  toneHi: 'tone-hi',
  toneApply: 'tone-apply',
  toneAuto: 'tone-auto',
  keysCheatsheet: 'keys-cheatsheet',
  // right rail — evidence
  evidence: 'evidence',
  evNcc: 'evidence-ncc',
  evNccMeter: 'evidence-ncc-meter',
  evMargin: 'evidence-margin',
  evAnchors: 'evidence-anchors',
  evComposite: 'evidence-composite-area',
  evOverlap: 'evidence-overlap',
  evTook: 'evidence-took',
  evMachineNote: 'evidence-machine-note', // "At the machine's position, untouched" etc. (R28)
  alternativesList: 'alternatives-list',
  alternativesItem: 'alternatives-item', // data-rank (0-indexed storage); DISPLAY is rank+1 (R12.3)
  stalePanel: 'stale-panel',
  staleRecheck: 'stale-recheck',
  staleItem: 'stale-item', //               data-trial (the "go and look" buttons)
  buildStalePanel: 'build-stale-panel',
  buildStaleResolve: 'build-stale-resolve',
  // Recompute (R40) — freeze the anchors, re-place the rest against their composite.
  recomputePanel: 'recompute-panel',
  recomputeBtn: 'recompute-btn',
  recomputeSummary: 'recompute-summary', // "N anchored → re-place M"
  recomputeHint: 'recompute-hint', //       shown when nothing is anchored
  // status bar
  statusBar: 'status-bar',
  statusTrial: 'status-trial', //           "trial <n>" — never "trial —" (R14)
  statusState: 'status-state', //           the state badge
  statusPass: 'status-pass',
  statusTopleft: 'status-topleft', //       "top-left <x, y>" (R19)
  statusHint: 'status-hint',
  statusMsFrame: 'status-msframe', //       ~6 ms during a sweep (R20)
  statusFps: 'status-fps',

  // ── 6 · Mosaic ────────────────────────────────────────────────────────────
  // ⛔ `mosaic-dir` / `mosaic-browse` are GONE (R44): an export goes into the project's own
  //    outputs/, and the Outputs panel below is how it leaves Camea.
  mosaicBasename: 'mosaic-basename',
  outTiff: 'mosaic-out-tiff',
  outPng: 'mosaic-out-png',
  outCsv: 'mosaic-out-csv',
  outGt: 'mosaic-out-gt',
  outQc: 'mosaic-out-qc',
  mosaicRender: 'mosaic-render-mode',
  mosaicIncludeUnverified: 'mosaic-include-unverified',
  mosaicUmPerPx: 'mosaic-umperpx',
  mosaicExport: 'mosaic-export',
  mosaicAutosaveNote: 'mosaic-autosave-note',
  provenancePanel: 'provenance-panel',
  provenanceStamp: 'provenance-stamp', //   W5 — "NOT AN INDEPENDENT GROUND TRUTH…"
  exportFiles: 'export-files',
  exportFile: 'export-file', //             data-kind = tiff|coverage|png|positions|gt|qc|qc_md; data-path = written path

  // ── 7 · Electrodes (the post-export identification stage, 2026-08-11) ─────
  // The step nav button is TID.step('electrodes') → `wizard-step-electrodes` (STEPS above).
  electrodesViewer: 'electrodes-viewer', //    the step root (canvas + rail)
  electrodesCanvas: 'electrodes-canvas', //    the READ-ONLY core-viewer <canvas>
  electrodesMap: 'electrodes-map', //          Map electrodes / Re-run (both states, one testid)
  electrodesProgress: 'electrodes-progress', // the map job block (bar + phase + cancel)
  electrodesPhase: 'electrodes-phase',
  electrodesCancel: 'electrodes-cancel',
  electrodesMapError: 'electrodes-map-error', // ⭐ the refusal, VERBATIM. Under "whole chip imaged"
  //                                           the strict fit ends in a map or a refusal that names
  //                                           both shapes and says to answer "part of the chip" —
  //                                           it is shown whole, beside a live coverage question.
  electrodePanel: 'electrode-panel', //        the shared readout (both features mount it)
  electrodeId: 'electrode-id', //              the id line, text `col-row`; data-kind = 1|2
  electrodeStale: 'electrode-stale', //        the "map is stale — re-run" live warning
  electrodeIdsToggle: 'electrode-ids-toggle', // role=switch; the IDs overlay (off by default)
  electrodeMarker: 'electrode-marker', //      the snapshot highlight ring; data-electrode
  // ── R45.8 · the device spec + the coverage question (2026-08-11) ────────────
  // ⭐ HE PICKS BEFORE ANY MAPPING. The Map/Re-run button is DISABLED until one segment is pressed —
  // a map that quietly assumed "partial" would be an answer he never gave.
  electrodeCoverage: 'electrode-coverage', //  role=radiogroup, aria-label "Array coverage"; both
  //                                           features mount it (pre-map panel AND the readout)
  electrodeCoverageFull: 'electrode-coverage-full', //       "Whole chip imaged"; aria-pressed
  electrodeCoveragePartial: 'electrode-coverage-partial', // "Part of the chip"; aria-pressed
  electrodeCoverageMode: 'electrode-coverage-mode', // the grid fact; data-coverage = full|partial
  electrodeUm: 'electrode-um', //              the selection's centre in µm — array frame, x along
  //                                           columns; ABSENT when the map carries no device scale
  electrodeUmPerPx: 'electrode-um-per-px', //  the MEASURED scale (device pitch ÷ measured pitch)
  electrodeDevice: 'electrode-device', //      the named sensor spec that supplied the µm
  // ⛔ there is deliberately NO `electrode-shape-corrected` id: a full map is never repaired, so a
  //    corrected shape cannot happen (R45.8). The refusal is what the user reads instead.
  electrodePartialNote: 'electrode-partial-note', // live warning — "1-1 is the top-left of the
  //                                           IMAGED REGION, not of the chip"
  // videomosaic
  vmMapElectrodes: 'vm-map-electrodes', //     Map electrodes / Re-run on the video screen
  vmElectrodesProgress: 'vm-electrodes-progress',
  vmElectrodesCancel: 'vm-electrodes-cancel',
  vmElectrodesMapError: 'vm-electrodes-map-error', // the same refusal, verbatim, on the video screen
  vmViewer: 'vm-viewer', //                    the preview scroller; data-fit / data-identify
  vmZoomToggle: 'vm-zoom-toggle', //           Fit ↔ 100% — shown once plain click means identify
  vmElectrodeMarker: 'vm-electrode-marker', // the video highlight ring; data-electrode
  vmElectrodeIdsToggle: 'vm-electrode-ids-toggle', // role=switch; the video screen's IDs overlay

  // ── The pipeline header (R46.1) ───────────────────────────────────────────
  // Survey → Mosaic → Electrodes → Regions. A step is LOCKED until the one before it is done, and
  // the gate is read off the DOCUMENT, never off where the user has clicked.
  pipelineSteps: 'pipeline-steps', //        the <ol>; aria-label "Pipeline steps"
  pipelineStep: (n: PipelineStepName) => `pipeline-step-${n}`, // the nav BUTTONS (the `vm-step-*`
  //                                         ids below are the step BODIES). Each carries
  //                                         data-locked, data-active, aria-current — R46.1.
  pipelineAction: (n: PipelineStepName) => `pipeline-action-${n}`, // ⭐ R47 — what the step is FOR,
  //                                         in three words, under its name.
  vmStepSurvey: 'vm-step-survey',
  vmStepMosaic: 'vm-step-mosaic',
  vmStepElectrodes: 'vm-step-electrodes',
  vmToMosaic: 'vm-to-mosaic', //             the forward button on each step — the pipeline walked
  vmToElectrodes: 'vm-to-electrodes',
  vmToRegions: 'vm-to-regions',

  // ── ⭐ R47 · the work frame — picture left, tools right, nothing else scrolls ──
  vmRail: 'vm-rail', //                      the tool rail; the ONE scroller on a picture step
  vmFiles: 'vm-files', //                    opens the outputs drawer (R44's door, asked for)
  outputsDrawer: 'outputs-drawer', //        role=dialog; Escape closes it
  outputsScrim: 'outputs-scrim',
  outputsClose: 'outputs-close',
  outputsPanel: 'outputs-panel', //          R44's browse-and-copy panel, wherever it is mounted
  outputRow: 'output-row', //                data-name; one per file actually on disk

  // ── 4 · Regions — where a fixed-field calcium recording sits (R46) ────────
  // ⭐ The deliverable: a located rectangle NAMES THE ELECTRODES UNDER IT, which is what pairs an
  // MEA channel with the neuron whose calcium trace sits on top of it.
  regionsStep: 'regions-step', //            the step root
  regionsPath: 'regions-path', //            the typeable video path — ⚠️ R38: headless has no native
  regionsBrowse: 'regions-browse', //        picker, so the typed box is the only drivable door
  regionsName: 'regions-name', //            optional label; defaults to the file name
  regionsLocate: 'regions-locate', //        starts the 202 locate job
  regionsProgress: 'regions-progress', //    the job block (bar + phase + cancel)
  regionsPhase: 'regions-phase',
  regionsEta: 'regions-eta',
  regionsCancel: 'regions-cancel',
  regionsError: 'regions-error', //          the refusal, VERBATIM (no mosaic / no electrode map /
  //                                         could not be placed) — never trimmed to a code
  regionsLoadError: 'regions-load-error',
  regionsList: 'regions-list', //            one row per located recording
  regionsEmpty: 'regions-empty',
  regionsStale: 'regions-stale', //          live warning: the mosaic was rebuilt (R46.10)
  regionsFieldsToggle: 'regions-fields-toggle', // show every rectangle, or only the selected one
  regionRow: 'region-row', //                data-region-id; data-status
  regionName: 'region-name', //              click to rename
  regionNameInput: 'region-name-input',
  regionStatus: 'region-status', //          unconfirmed | confirmed (R46.6)
  regionConfirm: 'region-confirm', //        ⭐ the human's signature — nothing promotes itself
  regionUnconfirm: 'region-unconfirm',
  regionDelete: 'region-delete',
  regionPanel: 'region-panel', //            the readout for the selected region (R3: numbers)
  regionRect: 'region-rect', //              the outline on the mosaic; data-region-id, data-selected
  regionDrag: 'region-drag', //              the draggable body of the SELECTED rectangle
  regionDropped: 'region-dropped', //        "dragged, not yet snapped" state
  regionSnap: 'region-snap', //              re-runs the bounded local match at the settled scale
  regionRevert: 'region-revert',
  regionSnapBanner: 'region-snap-banner', // the measured distance + NCC, like the sweep's snap
  regionSnapMargin: 'region-snap-margin',
  regionMoved: 'region-moved',
  regionsWork: 'regions-work', //            ⭐ R47 — the two-pane frame the step is now built on
  regionStill: 'region-still', //            ⭐ the recording's own picture, faded into the rectangle
  regionFade: 'region-fade', //              its opacity slider (R46.8)
  regionFadeValue: 'region-fade-value', //   what is DRAWN — swaps while Space is held (R47)
  regionEvidenceToggle: 'region-evidence-toggle', // ncc + margin on the rail; the rest folded (R47)
  regionStillKind: 'region-still-kind', //   which projection won: median | max | std (R46.5)
  regionZoom: 'region-zoom', //              the scale
  regionZoomSearched: 'region-zoom-searched', // ⚠️ shown when it was SEARCHED, not measured (R46.2)
  regionNcc: 'region-ncc',
  regionMargin: 'region-margin', //          best − runner-up: the alias evidence
  regionDetailNcc: 'region-detail-ncc',
  regionDetailMargin: 'region-detail-margin',
  regionUncertain: 'region-uncertain', //    the flagged-not-hidden warning (R46.7)
  regionAngleWarning: 'region-angle-warning', // the lattice angles disagree; rotation is not solved
  regionPlacedBy: 'region-placed-by', //     machine | hand | hand+snap
  regionElectrodes: 'region-electrodes', //  ⭐ THE ANSWER
  regionElectrodeCount: 'region-electrode-count',
  regionElectrodeRange: 'region-electrode-range',
  regionElectrodeBlock: 'region-electrode-block',
  regionElectrodeSplit: 'region-electrode-split',
  regionElectrodeList: 'region-electrode-list',
  regionElectrodeListToggle: 'region-electrode-list-toggle',
  regionElectrodesNone: 'region-electrodes-none',
  regionsRowError: 'regions-row-error',

  // ── Help (R3/R7) ──────────────────────────────────────────────────────────
  help: 'help', //                          the 14 px `?`; role=button, tabindex=0; data-empty hides it
  helpTooltip: 'help-tooltip', //           body-level, position:fixed (R3.4)

  // ── The eleven live warnings (§5) — each STAYS on the page, never a tooltip ─
  warnBuildStale: 'warn-build-stale', //        W1
  warnThinMargin: 'warn-thin-margin', //        W2
  warnDivert: 'warn-divert', //                 W3 (block + magenta outline + header count + banner)
  warnAutosaveFailed: 'warn-autosave-failed', // W4
  // W5 = provenanceStamp above
  warnRefusedBlank: 'warn-refused-blank', //    W6
  warnSmallAperture: 'warn-small-aperture', //  W7
  warnStale: 'warn-stale', //                   W8
  warnPass1NoConfidence: 'warn-pass1-no-confidence', // W9
  warnNoAnchors: 'warn-no-anchors', //          W10
  warnConfidentDisagree: 'warn-confident-disagree', // W11
} as const;

// ─────────────────────────────────────────────────────────────────────────────
// Small locator helpers
// ─────────────────────────────────────────────────────────────────────────────
export const byId = (page: Page, id: string): Locator => page.getByTestId(id);

/** The receipt for the synthetic dataset, once a path has been typed that resolves to it. */
export const fixtureCard = (page: Page): Locator =>
  page.getByTestId(TID.card).filter({ hasText: FIXTURE.name });

/**
 * Type a path into one of the two path boxes and commit it (Enter). `PathField` keeps the text and
 * shows the backend's message inline on failure — so a wrong path fails as a visible `path-error`,
 * not a vanished form.
 */
export async function fillPath(page: Page, fieldId: string, path: string): Promise<void> {
  const field = page.getByTestId(fieldId);
  const input = field.getByTestId(TID.pathInput);
  await input.fill(path);
  // Dismiss the completion menu first: Enter with an active suggestion COMPLETES rather than submits.
  await input.press('Escape');
  await field.getByTestId(TID.pathSubmit).click();
}

// ─────────────────────────────────────────────────────────────────────────────
// Page objects
// ─────────────────────────────────────────────────────────────────────────────

export class Home {
  constructor(readonly page: Page) {}
  async open() {
    await this.page.goto('/');
    await expect(byId(this.page, TID.manager)).toBeVisible();
  }
  card() {
    return fixtureCard(this.page);
  }
  /**
   * Create a project on the fixture via the new-project flow (name → task → where the DATA is) →
   * enters the Mosaic feature at `/project/:id` (R41.3; R4.5 lands it on Range).
   *
   * ⭐ **ONE PATH, AND NO HARNESS SETUP** (R44). It used to type two — a data folder and a save
   * folder — and before that it needed a store to have been chosen and a root registered. Now the
   * app owns where the project goes, so the test types what the user types: where his data is.
   */
  async openFixture(name = 'e2e project') {
    await byId(this.page, TID.newProject).click();
    await expect(this.page).toHaveURL(/\/new(\/|$)/);
    await byId(this.page, TID.npName).fill(name);
    await byId(this.page, TID.npNext).click();
    // ⚠️ **THIS IS THE RETIRED SNAPSHOT LANE'S DOOR, AND IT IS STILL SHUT.** The card it needs is
    // `data-task="mosaic"`, which left `NewProjectFlow.TASKS` on 2026-08-11 and did NOT come back
    // when the Task step did on 2026-08-14 (the second task is `mea`, a different thing entirely).
    // So every spec in `RETIRED_SNAPSHOT_SPECS` still fails here, by timeout, for the one reason
    // that is true — restoring the snapshot task is what makes them green, not editing this line.
    // ⛔ Do NOT "fix" it to `.first()`: that would click `Simultaneous MEA + 2P` and drive the
    // wrong pipeline, turning an honest red into a confusing one.
    await this.page.locator(`[data-testid="${TID.taskCard}"][data-task="mosaic"]`).click();

    await fillPath(this.page, TID.fromField, PATHS.data);
    await expect(this.card()).toBeVisible();

    await byId(this.page, TID.npCreate).click();
    await expect(this.page).toHaveURL(/\/project\//);
  }
}

export class Wizard {
  constructor(readonly page: Page) {}
  step(n: StepName) {
    return byId(this.page, TID.step(n));
  }
  /** True when the step is gated (BEHAVIOUR R4.2/R4.3). Reads the element's `data-locked`. */
  async isLocked(n: StepName): Promise<boolean> {
    return (await this.step(n).getAttribute('data-locked')) === 'true';
  }
  async isActive(n: StepName): Promise<boolean> {
    const el = this.step(n);
    return (
      (await el.getAttribute('data-active')) === 'true' ||
      (await el.getAttribute('aria-current')) === 'step'
    );
  }
  /** Click a step tab (only succeeds if it is unlocked). */
  async goto(n: StepName) {
    await this.step(n).click();
  }
  async expectActive(n: StepName) {
    await expect
      .poll(() => this.isActive(n), { timeout: SHORT, message: `step "${n}" should be active` })
      .toBe(true);
  }
}

/** The Sweep stage: keyboard-first, so this is mostly key presses + readouts. */
export class Sweep {
  constructor(readonly page: Page) {}
  canvas() {
    return byId(this.page, TID.canvas);
  }
  banner() {
    return byId(this.page, TID.banner);
  }
  status(id: string) {
    return byId(this.page, id);
  }
  chip(trial: number) {
    return this.page.locator(`[data-testid="${TID.queueChip}"][data-trial="${trial}"]`);
  }
  /** Put keyboard focus on the stage so sweep keys dispatch (the handler is stage-scoped). */
  async focus() {
    await this.canvas().click({ position: { x: 5, y: 5 } });
  }
  async press(key: string) {
    await this.page.keyboard.press(key);
  }
  /**
   * Press Space and return the trial the cursor COMMITS to. R33 (commit-at-display): the cursor moves
   * only when the async match lands and the tile is displayed — so a synchronous `currentTrial()` right
   * after `press('Space')` returns the PRE-advance tile. This waits for the commit, exactly as the
   * poll-based advance assertions elsewhere in the suite do. It changes no ruling; it reads the cursor
   * at the moment R33 defines it to be valid.
   */
  async advance(): Promise<number> {
    const before = await this.currentTrial();
    await this.press('Space');
    await expect
      .poll(() => this.currentTrial(), { timeout: SHORT })
      .not.toBe(before);
    return this.currentTrial();
  }
  /** Set the floating-tile opacity slider (R13; 15–100). Fires an input event the UI must honour.
   *  Uses the native value setter so React's controlled-input value tracker registers the change and
   *  fires onChange — a plain `.value =` assignment is swallowed by the tracker on a controlled input. */
  async setOpacity(pct: number) {
    await byId(this.page, TID.opacitySlider).evaluate((el, v) => {
      const input = el as HTMLInputElement;
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
      setter?.call(input, String(v));
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
    }, pct);
  }
  /** Wait out the 1 s placement fade so a pixel probe reads the settled frame (FADE_MS = 1000). */
  async settleFade() {
    await this.page.waitForTimeout(1100);
  }
  /** The integer trial the status bar reports. Throws if it reads "—" (R14 regression). */
  async currentTrial(): Promise<number> {
    const t = (await this.status(TID.statusTrial).textContent())?.match(/-?\d+/)?.[0];
    return Number(t);
  }
  async headerCount(id: string): Promise<number> {
    const el = byId(this.page, id);
    if ((await el.count()) === 0) return 0; // hidden at zero
    return Number((await el.textContent())?.match(/\d+/)?.[0] ?? 0);
  }
  /**
   * Read one RGBA pixel off the visible sweep canvas (device pixels). Used by the Difference-mode
   * probes (§3.5, R13.4). Returns [r,g,b,a] 0–255.
   */
  async pixel(x: number, y: number): Promise<[number, number, number, number]> {
    return this.page.evaluate(
      ({ id, x, y }) => {
        const c = document.querySelector<HTMLCanvasElement>(`[data-testid="${id}"]`);
        if (!c) throw new Error('sweep canvas not found');
        const ctx = c.getContext('2d', { willReadFrequently: true });
        if (!ctx) throw new Error('no 2d context');
        const d = ctx.getImageData(x, y, 1, 1).data;
        return [d[0], d[1], d[2], d[3]] as [number, number, number, number];
      },
      { id: TID.canvas, x, y },
    );
  }
  /** How many certified tiles are BAKED INTO the drawn anchor field (R9 `data-anchor-layer`). */
  async anchorLayerCount(): Promise<number> {
    return Number((await this.canvas().getAttribute('data-anchor-layer')) ?? 'NaN');
  }
  /** Whether the unverified layer is drawn — must be false in the sweep (R9.4 `data-unverified-drawn`). */
  async unverifiedDrawn(): Promise<boolean> {
    return (await this.canvas().getAttribute('data-unverified-drawn')) === 'true';
  }
  /** Whether Difference mode is on (R-D `data-diff`). */
  async diffOn(): Promise<boolean> {
    return (await this.canvas().getAttribute('data-diff')) === 'true';
  }
  /** The floating tile's current opacity 0.15–1.00 (R13 `data-float-alpha`). */
  async floatAlpha(): Promise<number> {
    return Number((await this.canvas().getAttribute('data-float-alpha')) ?? 'NaN');
  }
  /** How many device pixels wide/high the canvas backing store is. */
  async size(): Promise<{ w: number; h: number }> {
    return this.page.evaluate((id) => {
      const c = document.querySelector<HTMLCanvasElement>(`[data-testid="${id}"]`);
      if (!c) throw new Error('sweep canvas not found');
      return { w: c.width, h: c.height };
    }, TID.canvas);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Flow helpers — drive the app to a given screen. All fail loudly (by timeout) until the UI exists.
// ─────────────────────────────────────────────────────────────────────────────

/** Home → open the fixture → land in the wizard (R4.5: the session open navigates to Range). */
export async function enterMosaic(page: Page): Promise<{ home: Home; wizard: Wizard }> {
  const home = new Home(page);
  await home.open();
  await home.openFixture();
  const wizard = new Wizard(page);
  await expect(byId(page, TID.wizard)).toBeVisible({ timeout: SHORT });
  return { home, wizard };
}

/** Drive to the Sweep and put focus on the stage. Does NOT run a build (canvas starts empty — R9). */
export async function enterSweep(page: Page): Promise<Sweep> {
  const { wizard } = await enterMosaic(page);
  await wizard.goto('sweep');
  const sweep = new Sweep(page);
  await expect(sweep.canvas()).toBeVisible({ timeout: SHORT });
  await sweep.focus();
  return sweep;
}

/** Answer the next `window.prompt` (the headless save/load path — R38) with `value`. */
export function answerNextPrompt(page: Page, value: string) {
  page.once('dialog', (d) => d.accept(value));
}

/**
 * Record every `POST /api/mosaic/match/anchor` body (R21/R22 — the request carries the anchor set that
 * is the server-memo cache key). Returns a live array of parsed bodies + a helper to await the next.
 */
export function recordMatchAnchor(page: Page) {
  const bodies: MatchAnchorBody[] = [];
  page.on('request', (req) => {
    if (req.method() === 'POST' && req.url().includes(ROUTES.matchAnchor)) {
      const b = req.postDataJSON() as MatchAnchorBody | null;
      if (b) bodies.push(b);
    }
  });
  return {
    bodies,
    /** Wait until at least `n` match requests have been seen. */
    async waitFor(n: number, timeout = SHORT) {
      await expect
        .poll(() => bodies.length, { timeout, message: `expected ≥${n} match/anchor requests` })
        .toBeGreaterThanOrEqual(n);
    },
  };
}

export interface MatchAnchorBody {
  session_id: string;
  target: number;
  anchors: number[];
  positions: Record<string, [number, number]>;
  mode?: string;
  refuse?: number[];
}

/** A schema-shaped MatchResult (docs/openapi.json MatchResult) for stubbing decidePlacement (R15). */
function matchResult(
  target: number,
  at: [number, number],
  ncc: number,
  margin: number,
): unknown {
  const best = { rank: 0, x: at[0], y: at[1], ncc, npix: 1000, subpixel: false };
  return {
    target,
    mode: 'anchor',
    n_anchors: 1,
    composite: null,
    candidates: [best, { rank: 1, x: at[0] + 300, y: at[1], ncc: ncc - margin, npix: 900, subpixel: false }],
    best,
    margin,
    margin_thin: margin < 0.1,
    refused: null,
    dropped_anchors: [],
    gpu: false,
    elapsed_ms: 12,
    cached: false,
    cache_key: `stub-${target}-${at[0]}-${at[1]}`,
  };
}

/** Not confident: ncc < SOLVER_NCC_MIN (0.65) AND margin < SOLVER_MARGIN_MIN (0.20). */
export const lowConfidenceMatch = (target: number, at: [number, number]) =>
  matchResult(target, at, 0.5, 0.05);
/** Confident: ncc ≥ 0.65 AND margin ≥ 0.20 — the field/match wins even if it disagrees with the solver. */
export const confidentMatch = (target: number, at: [number, number]) =>
  matchResult(target, at, 0.92, 0.4);

/**
 * Stub every `POST /api/mosaic/match/anchor` with a crafted MatchResult, so the CLIENT-SIDE
 * decidePlacement logic (R15) can be driven deterministically regardless of the clean fixture. The
 * factory receives the requested `target` and returns the result to serve.
 */
export async function stubMatchAnchor(
  page: Page,
  factory: (target: number, body: MatchAnchorBody) => unknown,
) {
  await page.route(`**${ROUTES.matchAnchor}`, async (route, req) => {
    const body = req.postDataJSON() as MatchAnchorBody;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(factory(body.target, body)),
    });
  });
}

/**
 * Stub `POST /api/mosaic/screen/propose` to flag `trials` as recommended blanks, so the Screen step's
 * three-way control (R6) can be exercised deterministically. The committed synthetic fixture is too
 * small for the real blank scan to determine a threshold (it needs ≥20 pass-1 reference frames; the
 * fixture has ≤11), so it proposes nothing — this crafts the recommendation the same way
 * `stubMatchAnchor` crafts a MatchResult for R15, testing the UI on deterministic input, not the scan.
 */
export async function stubScreenPropose(page: Page, trials: number[]) {
  const proposed = [...trials].sort((a, b) => a - b);
  const texture: Record<string, number> = {};
  for (const t of proposed) texture[String(t)] = 100 + t;
  await page.route(`**${ROUTES.screenPropose}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        threshold: 250,
        threshold_source: 'stubbed for the R6 three-way-control test (fixture too small to scan)',
        measure: 'std of DoG(sigma=3, sigma=30) of the frame as read',
        texture,
        proposed,
        n_proposed: proposed.length,
        n_scanned: proposed.length,
        margin_warning: null,
      }),
    });
  });
}

/**
 * Run the solver on the Place step and wait for it to finish (a build gives every tile a `machine`
 * position — the input decidePlacement needs to divert against). @slow: it exercises a real build.
 */
export async function runBuild(page: Page, timeout = 180_000) {
  const wizard = new Wizard(page);
  await wizard.goto('place');
  await byId(page, TID.placeRun).click();
  // The build finishes when the worklist / "Placed" summary appears (or Sweep becomes unlocked).
  await expect(byId(page, TID.placeWorklist)).toBeVisible({ timeout });
}
