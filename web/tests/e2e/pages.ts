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
 * `orientation` joined 2026-08-15 (his ruling): the chip-seating question is its own step after
 * Regions, unlocked by a located region in the document.
 */
export const PIPELINE = ['survey', 'mosaic', 'electrodes', 'regions', 'orientation'] as const;
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
  // ── ⏱️ WAITING — the one bar, everywhere (BEHAVIOUR R48) ──────────────────────
  // `<Progress>` composes its ids from the `data-testid` it is given: `${id}`, `${id}-bar`,
  // `${id}-pct`, `${id}-eta`, `${id}-stop`, `${id}-log`. So a screen registers its ROOT id here and
  // the five children follow by construction — that is why there is no entry per suffix.
  runningStrip: 'running-strip', //         ⭐ R48.8: the strip under the top bar. ABSENT when nothing
  //                                        is running — assert `toHaveCount(0)`, not hidden.
  runningSaid: 'running-said', //           what a strip row is waiting for, in his words (R48.6)
  runningEta: 'running-eta', //             ⭐ R48.4: NEVER EMPTY. Either "42 s left" or "working out
  //                                        how long · 12 s". An empty slot here is the bug R48 exists
  //                                        for — four screens had one.
  runningStop: 'running-stop', //           R48.7; rendered only when the server says `cancellable`
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
  projectsLoading: 'projects-loading', //   ⛔ R48.10 — the list IN FLIGHT. `projects-empty` is the
  //                                        ANSWER "no projects", and the two must never coincide.
  projectsBusy: 'projects-busy', //         ⏱️ a rename or a delete, NAMING the project. R48.7 — it
  //                                        carries no Stop and says why (an rmtree has no callback).
  projectsUnreadable: 'projects-unreadable', // store folders that could not be read
  projectsMigrated: 'projects-migrated', //  the one-time R44 "your projects moved" notice
  // the new-project flow (/new): name → task → where the DATA is (R44: no save folder)
  newProjectFlow: 'new-project-flow',
  npName: 'np-name',
  npNext: 'np-next',
  npBack: 'np-back',
  npCancel: 'np-cancel',
  npCreate: 'np-create',
  npCreating: 'np-creating', //             the slot that replaces the step while a project is made
  npProgress: 'np-progress', //             ⏱️ R48 — ⭐ THE FIRST WAIT A NEW USER EVER SEES. The bar
  //                                        (root; `-bar`, `-pct`, `-eta`, `-stop`). Tens of seconds
  //                                        on a real dataset; it used to be one word.
  taskCard: 'task-card', //                 data-task = videomosaic | mea (⭐ two tasks again since
  //                                        2026-08-14, so the Task step is a real stop). ⚠️ Address
  //                                        a card by `data-task`, NEVER by position.
  projectNoInput: 'project-no-input', //    a card whose task has been given nothing yet ("No
  //                                        recordings yet") — where a video's filename would sit
  projectInputCount: 'project-input-count', // issue 011: an Analyze MEA card with recordings says
  //                                        "N recordings" there instead; empty keeps NoInput
  // ── The feature gate (`/project/:id` — which task owns this project?) ─────────
  featureGateError: 'feature-gate-error', // role=alert; not-found / unknown-task / a real failure
  gateProgress: 'gate-progress', //         ⏱️ R48 — the one round trip before a feature mounts.
  //                                        Absent under R48.1's 400 ms grace, which is most of them.

  // ── CORE · the served folder picker (R38 — the native dialog does not exist here) ──
  folderPicker: 'folder-picker', //         role=dialog
  folderPickerEntry: 'folder-picker-entry', // data-dataset = true|false
  folderPickerPath: 'folder-picker-path',
  folderPickerConfirm: 'folder-picker-confirm',
  folderPickerReading: 'folder-picker-reading', // ⏱️ R48.10 — the folder read IN FLIGHT, so it can
  //                                        never be mistaken for "No sub-folders here." (which is
  //                                        the ANSWER). Absent under R48.1's 400 ms grace.

  // ── Analyze MEA (the standalone task) ───────────────────────────────────────
  meaFeature: 'mea-feature', //             the project screen root
  meaProjectName: 'mea-project-name',
  meaEmpty: 'mea-empty', //                 the empty state: no recordings on the shelf yet
  meaAddRecordings: 'mea-add-recordings', // ⭐ ENABLED since 002. Opens the same picker the wizard
  //                                        showed him — `mea-add-dialog`.
  // ── the shelf (002) ─────────────────────────────────────────────────────────
  meaShelf: 'mea-shelf',
  meaShelfSummary: 'mea-shelf-summary', //  one line: N recordings · total length · total size ·
  //                                        M still copying — only the non-zero parts
  meaShelfTools: 'mea-shelf-tools', //      sort + type filter; a client-side VIEW, shown from 2 rows
  meaShelfSort: 'mea-shelf-sort', //        default 'as-added' — the document's own order
  meaShelfFilter: 'mea-shelf-filter', //    by assay; appears only when the shelf holds two types
  meaRecording: 'mea-recording', //         one row; data-recording-id, data-copy, data-missing
  meaRecordingLabel: 'mea-recording-label', //  a BUTTON — click it to rename the row in place
  meaRenameInput: 'mea-rename-input', //    Enter/blur saves, Esc cancels; blank reverts quietly
  meaRecordingFacts: 'mea-recording-facts', // duration · channels · spikes · size, READ OFF THE
  //                                        FILE every time. Absent on a row that lost its file.
  meaRecordingCopy: 'mea-recording-copy', // where Camea is reading it from, in plain words
  meaRecordingReady: 'mea-recording-ready', // the one-off end-to-end read is done (data-ready=
  //                                        'true') or running ('reading'); absent while unread.
  //                                        ⏱️ R48: the RUNNING case is a <Progress> in the row's
  //                                        main column, under this same id — `meaRecordingReading`
  //                                        is the bar inside it.
  meaRecordingReading: 'mea-recording-reading', // the bar: label · pct · ETA · Stop, off the job
  meaRecordingCopyProgress: 'mea-recording-copy-progress', // the copy's bar, inside meaRecordingCopy
  meaRecordingReadEnded: 'mea-recording-read-ended', // 🔴 R48.9 — the read ENDED and the recording
  //                                        still cannot be shown whole (an activity scan stores no
  //                                        continuous trace). Never a poller that just stops.
  meaRemoving: 'mea-removing', //           R48.7 — names the row, and says a delete cannot be stopped
  meaShelfLoading: 'mea-shelf-loading', //  ⏱️ R48.10 — the shelf's own read. ⛔ While it is up the
  //                                        heading says "Recordings", NEVER "0 recordings"
  meaReadNow: 'mea-recording-read-now', //  fires the EXISTING backfill POST; MeaTrace's wording
  meaRecordingDuplicate: 'mea-recording-duplicate', // "same file as '<name>'" — source_path twins
  meaRecordingMissing: 'mea-recording-missing', // 🔴 the live warning: not where you left it
  meaRemove: 'mea-remove-recording',
  meaRemoveConfirm: 'mea-remove-confirm', // ⭐ the ONE confirm on this screen — appears only when
  //                                        Camea's copy is the last one left (his ruling 2026-08-14)
  meaRemoveAnyway: 'mea-remove-anyway',
  meaAddDialog: 'mea-add-dialog',
  meaAddConfirm: 'mea-add-confirm',
  meaAdding: 'mea-adding', //               ⏱️ R48 — the Add POST, which opens every picked file to
  //                                        confirm it before writing. Indeterminate + a count-up
  //                                        (R48.9: the opens are inside one request). Absent under
  //                                        R48.1's 400 ms grace, which a local two-file import is.
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
  meaImportLooking: 'mea-import-looking', // ⏱️ R48.9 — the folder walk: the travelling sliver and a
  //                                        count-up. ⛔ NEVER a filling bar; no denominator exists
  //                                        until the walk returns. Under 400 ms it stays `Looking…`
  meaImportPicking: 'mea-import-picking', // the native dialog is open — a HUMAN, so no ETA and no
  //                                        Stop, and both buttons are dead while it is up
  meaTickAll: 'mea-tick-all',
  npMeaCount: 'np-mea-count', //            the wizard Files step's running count
  npMeaError: 'np-mea-error', //            a refusal, INLINE beside the ticks (never a toast)
  // ── opening one recording (003): the chip, and one pad's trace ───────────────────────────────
  meaOpenButton: 'mea-open-recording-button', // ⛔ OFF on a row whose file is at neither address
  meaOpen: 'mea-open-recording', //         the viewer root
  meaOpenLabel: 'mea-open-label',
  meaOpenFacts: 'mea-open-facts',
  meaOpenUnplaced: 'mea-open-unplaced', // "N of them could not be placed on the chip" — MAXWELL
  //                                        §7.6; shown ONLY when the file total exceeds the pads'
  meaOpenNoDecoder: 'mea-open-no-decoder', // the waveform situation said ONCE, before any pad
  //                                        click — quiet, on the page, MeaTrace's own words
  meaFollowView: 'mea-follow-view', //      the "Colors follow the view" mode row, above the chip;
  //                                        carries the `?` (R7 — a mode control earns one)
  meaFollowViewTick: 'mea-follow-view-tick', // its checkbox; default OFF
  meaFollowStale: 'mea-follow-stale', //    ⭐ R48.10 — "previous": the colours on the chip are the
  //                                        stretch he just left, dimmed and named while the
  //                                        windowed tally is out. The trace's own pattern. No bar.
  meaOpenError: 'mea-open-error', //        🔴 refused BY NAME — never an empty chip map
  meaCloseRecording: 'mea-close-recording',
  meaChipMap: 'mea-chip-map',
  meaChipCanvas: 'mea-chip-canvas', //      ⭐ ONE canvas, never a DOM node per pad
  meaChipExtent: 'mea-chip-extent', //      "220 × 120 pads on the chip · 726 wired up"
  meaChipFit: 'mea-chip-fit',
  meaChipFrameSelected: 'mea-chip-frame-selected', // centre the selected pad; DISABLED, never
  //                                        hidden, with nothing selected (R7.6: no `?` needed)
  meaChipZoomLevel: 'mea-chip-zoom-level', // the live zoom %, Fit = 100% (vm-zoom-level's grammar)
  meaChipHover: 'mea-chip-hover', //        hover names the electrode without a click
  meaChipSaid: 'mea-chip-said', //          the visually hidden live region announcing the selection
  meaChipLegend: 'mea-chip-legend', //      the ramp, in real spikes/s
  meaChipLegendSilent: 'mea-chip-legend-silent', // ⭐ the hollow ring, and what it MEANS
  meaChipBusiest: 'mea-chip-busiest', //    the ranked busiest-pads list beside the legend
  meaChipBusiestPad: 'mea-chip-busiest-pad', // one row; data-channel; aria-pressed when selected
  meaChipSpread: 'mea-chip-spread', //      pads per firing-rate band, beside the legend (§7.2)
  meaChipSpreadBar: 'mea-chip-spread-bar', // one bar; data-band ('silent' | 0..); data-count;
  //                                        aria-pressed while its pads are highlighted on the map
  meaTraceIdle: 'mea-trace-idle', //        "click a pad on the chip"
  meaTraceFacts: 'mea-trace-facts', //      electrode · channel · position · spikes
  meaTraceChart: 'mea-trace-chart', //      the CLOSE-UP's canvas; shared with the video pipeline
  //                                        (core/trace), which is why it keeps the plain name.
  meaTraceOverviewChart: 'mea-trace-overview-chart', // the STRIP's canvas.
  //                                        ⚠️ It has its own id because `MeaTrace` mounts
  //                                        `TraceChart` twice and one id across both made every bare
  //                                        `mea-trace-chart` locator a strict-mode failure — it broke
  //                                        two assertions here before anyone noticed. `TraceChart`
  //                                        takes an optional `testId`; `MeaTracePanel` passes none
  //                                        and is unaffected.
  // ── the whole recording, and dragging a stretch to zoom into it (004) ───────
  // ⛔ `mea-trace-scrub` is GONE with the 1 s window and its slider. His ruling, 2026-08-15: *"I
  //    don't like the slider bar."* The strip below is NOT a scrubber and must not grow a handle.
  meaTraceOverview: 'mea-trace-overview', // the strip: the WHOLE recording, with a box round the
  //                                        stretch the close-up is showing. Draggable, x only.
  meaTraceDetail: 'mea-trace-detail', //    the close-up. tabIndex=0, role=application — it takes
  //                                        the keyboard (+/- zoom, arrows, Backspace, Home).
  meaTraceNav: 'mea-trace-nav', //          the row where the slider used to be
  meaTraceHome: 'mea-trace-home', //        "Whole recording" — ⭐ itself undoable with one Back
  meaTraceBack: 'mea-trace-back', //        "← Back"; DISABLED, never hidden, at the top of history
  meaTraceForward: 'mea-trace-forward', //  "Forward →"; disabled until a Back has been taken
  meaTracePrevSpike: 'mea-trace-prev-spike', // recenter on the nearest spike leftward, current
  //                                        width; steps the WHOLE recording's spike list, so a
  //                                        jump works beyond the loaded close-up. Keys: P / N.
  meaTraceNextSpike: 'mea-trace-next-spike', // …and rightward. Both DISABLED past the last spike.
  meaTracePos: 'mea-trace-pos', //          the readout: "0.00–3.00 s of 3 s · 3.00 s wide · N spikes
  //                                        in view" — the range the SERVER SERVED, not the one asked
  meaTracePointerTime: 'mea-trace-pointer-time', // "cursor 1.2345 s" while the cursor is on the
  //                                        close-up, blank otherwise. ⛔ time only, never a µV
  //                                        (MAXWELL §7.6 leaves the amplitude unit unsettled)
  meaTraceSaid: 'mea-trace-said', //        visually hidden role=status: a keyboard zoom is announced
  meaTraceNeedsEnvelope: 'mea-trace-needs-envelope', // ⭐ a fact + an offer, not an error: the
  //                                        one-off whole-recording read has not been done yet.
  //                                        ⚠️ The e2e fixture never reaches it — 3.0 s at 20 kHz is
  //                                        60k samples, well under the route's live-read budget.
  meaTraceReading: 'mea-trace-reading', //  ⏱️ R48 — the read's bar, INSIDE needs-envelope: label ·
  //                                        pct · ticking ETA · Stop, all off the job. It replaced
  //                                        the bare word `Reading…` on a button
  meaTraceReadEnded: 'mea-trace-read-ended', // 🔴 R48.9 — the read ended and the whole recording
  //                                        still cannot be shown, and WHY
  meaTraceLoading: 'mea-trace-loading', //  ⭐ R48.10 — the empty chart between a pad click and its
  //                                        reply. It keeps the panel's shape; the word inside it
  //                                        waits out the 400 ms grace
  meaTracePlaceholderChart: 'mea-trace-placeholder-chart', // that chart's canvas — its OWN id, so a
  //                                        test asserting the real chart cannot pass on an empty box
  meaTraceStale: 'mea-trace-stale', //      "previous", on the dimmed close-up while a new stretch
  //                                        loads — the chart on screen is the stretch he just left
  meaTraceFlat: 'mea-trace-flat', //        🔴 LIVE WARNING: the waveform did not decode
  meaTraceUndecodable: 'mea-trace-undecodable', // 🔴 …or could not be read at all
  meaTraceNoSpikes: 'mea-trace-no-spikes', // ⭐ a fact, NOT a warning — no neuron was near it
  meaTraceUnrouted: 'mea-trace-unrouted', // this channel was never wired up
  meaTraceError: 'mea-trace-error',
  // ── the ONE path box (R41.3 → R42 → ⭐ R44: "into" is gone, the app owns the folder) ────────
  paths: 'project-paths',
  fromField: 'from-field', //               "Pull data from" — a PathField
  fromScanProgress: 'from-scan-progress', // ⏱️ R48 — the two-stage dataset scan (root; `-bar`,
  //                                        `-pct`, `-eta`, `-stop`). Stage 1 is a count-up with NO
  //                                        denominator (R48.9), stage 2 a real bar over the opens.
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
  loadPhase: 'load-phase', //               the slot the open narrates into — always present
  loadProgress: 'load-progress', //         ⏱️ R48 — the open job's bar inside it (root; `-bar`,
  //                                        `-pct`, `-eta`, `-stop`). Absent under R48.1's 400 ms grace.
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
  screenScanProgress: 'screen-scan-progress', // ⏱️ R48.10 — the scan IN FLIGHT. Distinct from the
  //                                        empty answer ("Nothing recommended.") and from…
  screenScanFailed: 'screen-scan-failed', //  …R48.9's third state: the scan that ended badly.
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
  placeUseCache: 'place-use-cache',
  placeSkip: 'place-skip', //               "Skip — place by hand" (destructive — R27)
  // ⏱️ R48.2 — the build bar is `<Progress>` now, so its children follow from the ROOT id and the
  // per-part ids below are just that root plus a suffix. The phase has no id of its own (the
  // primitive does not give it one); assert on `placeProgress` for "the build is alive".
  placeProgress: 'place-progress', //       the whole bar block
  placeProgressBar: 'place-progress-bar', // the gliding fill (R8.5 — `transition: width`)
  placeEta: 'place-progress-eta', //        R8 — ticks DOWN every second, never frozen > 2 s. Reads
  //                                        "3m 20s left", or R48.4's "working out how long…".
  placeCancel: 'place-progress-stop',
  placeLog: 'place-progress-log', //        last 8 lines (R8.7)
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
  staleRecheckProgress: 'stale-recheck-progress', // ⏱️ R48 — the re-check's own bar (root; `-bar`,
  //                                        `-pct`, `-eta`, `-stop` follow). 120 stale tiles is ~2 min.
  staleRecheckNote: 'stale-recheck-note', // R48.9 — what it says when the re-check ended BADLY
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
  mosaicExportProgress: 'mosaic-export-progress', // ⏱️ R48 — the export's bar (root; `-bar`, `-pct`,
  //                                        `-eta`, `-stop`). The overall pct is phase-weighted (R48.5).
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
  electrodesProgress: 'electrodes-progress', // the map job block
  // ⏱️ R48.2 — the bar inside it is `<Progress>`, so its parts are this root plus a suffix:
  // `-bar`, `-pct`, `-eta` (NEVER empty — R48.4), `-stop`.
  electrodesMapping: 'electrodes-mapping',
  electrodesCancel: 'electrodes-mapping-stop',
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
  vmElectrodesProgress: 'vm-electrodes-progress', // ⏱️ R48.2 — a `<Progress>` root now, so the bar
  //                                           is `-bar`, the time `-eta`, the Stop `-stop`. Its
  //                                           ETA slot used to be a permanently empty `<span>`.
  vmElectrodesCancel: 'vm-electrodes-progress-stop', // R48.7 — composed by the primitive
  vmElectrodesMapError: 'vm-electrodes-map-error', // the same refusal, verbatim, on the video screen
  vmViewer: 'vm-viewer', //                    the preview scroller; data-fit / data-identify
  vmZoomToggle: 'vm-zoom-toggle', //           Fit ↔ 100% — shown once plain click means identify
  vmZoomLevel: 'vm-zoom-level', //             the live zoom % readout
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
  // ── ⏱️ the video feature's waits (R48) — every one a `<Progress>` root ─────
  vmProgress: 'vm-progress', //              the build. All 7 phases carry an ETA since the backend
  //                                         wave; `-eta` is NEVER empty (R48.4).
  vmOpening: 'vm-opening', //                the document read, shown only past the 400 ms grace
  vmAttaching: 'vm-attaching', //            ⭐ R48.10 — "is a build already running?" is IN FLIGHT.
  //                                         The idle `vm-build` button must NOT be on screen while
  //                                         this is: pressing it there earns a 409.
  vmFindMeaProgress: 'vm-find-mea-progress', // the recording scan (a job since R48): the walk, then
  //                                         one HDF5 open per file, counted in its message
  vmToMosaic: 'vm-to-mosaic', //             the forward button on each step — the pipeline walked
  vmToElectrodes: 'vm-to-electrodes',
  vmToRegions: 'vm-to-regions',
  vmToOrientation: 'vm-to-orientation', //   Regions → Orientation; shown only once the DOCUMENT
  //                                         holds a located region (the same gate the nav reads)

  // ── 5 · Orientation — which way round the chip sits (his ruling 2026-08-15) ──
  // ⭐ The four candidate seatings as PICTURES, picked by eye — and the honest test beside them.
  // The mea-* ids survive from the retired Electrodes-rail panel, same meanings.
  orientationStep: 'orientation-step', //    the step root
  orientationWork: 'orientation-work', //    its WorkFrame (picture + rail)
  orientationRefusal: 'orientation-refusal', // 🔴 the footprint route's 409, VERBATIM — an
  //                                         instruction (attach the MEA / map electrodes first)
  orientationCards: 'orientation-cards', //  the 2×2 grid of candidate cards
  orientationCard: 'orientation-card', //    one candidate; data-flip-x, data-flip-y,
  //                                         data-previewed, data-settled, data-winner
  orientationUse: 'orientation-use', //      ⭐ the HUMAN confirm on each card — nothing auto-applies
  orientationFootprint: 'orientation-footprint', // the big viewer's dot layer; data-flip-x/y say
  //                                         which seating is being previewed
  orientationSettled: 'mea-orientation-settled', // "Settled: <seating> — <source>"
  orientationTest: 'mea-test-orientation', // the Test button
  orientationCaveat: 'mea-orientation-caveat', // 🔴 the caveat, on the page, never behind a `?`
  orientationScores: 'mea-orientation-scores', // the four-seating table
  orientationRegionRows: 'orientation-region-rows', // ⭐ one per-region breakdown block; data-region-id
  orientationAlignment: 'orientation-alignment', // what the clock alignment rested on, plain words
  orientationChance: 'orientation-chance', // the luck bar, plain words
  orientationUndecided: 'mea-orientation-undecided', // ⭐ "Cannot tell." — nothing to press
  orientationVerdict: 'orientation-verdict', // the winner sentence, pointing at its card
  orientationWinnerBadge: 'orientation-winner-badge', // the quiet badge on the test winner's card
  orientationSettledBadge: 'orientation-settled-badge', // …and on the settled seating's card
  // ── ⏱️ the orientation step's three waits (R48) ─────────────────────────────
  orientationTestProgress: 'orientation-test-progress', // ⭐ MINUTES of work whose entire progress
  //                                         UI used to be the button's own label. A `<Progress>`
  //                                         root with a real overall pct, an ETA and a Stop.
  orientationTestError: 'orientation-test-error', // R48.9 — a run that FAILED or was stopped says
  //                                         so; before this the button just became pressable again
  orientationFootprintProgress: 'orientation-footprint-progress', // R48.10 — the whole rail is
  //                                         empty until the footprint lands, which read as a
  //                                         broken step. Indeterminate: a folder walk (R48.9).
  orientationApplyProgress: 'orientation-apply-progress', // "Use this seating" re-runs the ENTIRE
  //                                         recording scan before saving — a job now, with a Stop

  // ── ⭐ R47 · the work frame — picture left, tools right, nothing else scrolls ──
  vmRail: 'vm-rail', //                      the tool rail; the ONE scroller on a picture step
  vmFiles: 'vm-files', //                    opens the outputs drawer (R44's door, asked for)
  outputsDrawer: 'outputs-drawer', //        role=dialog; Escape closes it
  outputsScrim: 'outputs-scrim',
  outputsClose: 'outputs-close',
  outputsPanel: 'outputs-panel', //          R44's browse-and-copy panel, wherever it is mounted
  outputRow: 'output-row', //                data-name; one per file actually on disk
  outputsEmpty: 'outputs-empty', //          ⛔ R48.10: the EMPTY project. Never rendered while the
  //                                         listing is in flight — that is `outputsListing`.
  outputsListing: 'outputs-listing', //      ⏱️ the listing IN FLIGHT (after R48.1's 400 ms grace)
  outputsCopyProgress: 'outputs-copy-progress', // ⏱️ R48 — the copy OUT: bytes, the file in flight,
  //                                         an ETA and a Stop (root; `-bar`/`-pct`/`-eta`/`-stop`)
  outputsCopyError: 'outputs-copy-error', // 🔴 a failed copy must not look like a successful one
  outputsCopied: 'outputs-copied', //        "Copied into …" — only ever after one actually landed

  // ── 4 · Regions — where a fixed-field calcium recording sits (R46) ────────
  // ⭐ The deliverable: a located rectangle NAMES THE ELECTRODES UNDER IT, which is what pairs an
  // MEA channel with the neuron whose calcium trace sits on top of it.
  regionsStep: 'regions-step', //            the step root
  regionsPath: 'regions-path', //            the typeable video path — ⚠️ R38: headless has no native
  regionsBrowse: 'regions-browse', //        picker, so the typed box is the only drivable door
  regionsName: 'regions-name', //            optional label; defaults to the file name
  regionsLocate: 'regions-locate', //        starts the 202 locate job
  regionsPickFiles: 'regions-pick-files', // the native multi-select — several recordings, located
  //                                         one after another through the one lease
  regionsNoDialog: 'regions-no-dialog', //   the one-line "no file dialog in this mode" note (R38)
  regionsQueue: 'regions-queue', //          the whole several-at-once readout: the bar below plus
  //                                         the drain button. Text: "Placing 2 of 6 · 4 waiting —
  //                                         <file>" (R48.6 names the file in the machine at last).
  regionsBatch: 'regions-batch', //          ⏱️ the WHOLE-BATCH `<Progress>` root (R48.3). Its
  //                                         `-eta` is composed CLIENT-SIDE — the median of what is
  //                                         placed × what is waiting — because the server has no
  //                                         concept of a batch and there is no other source for
  //                                         it. Its `-stop` stops the run outright (R48.7).
  //                                         Rendered INSTEAD of `regionsProgress`, never beside it.
  regionsQueueStop: 'regions-queue-stop', // "Stop after this one" — drains what is still waiting;
  //                                         the gentler half, beside the bar's own Stop
  regionsQueueStopped: 'regions-queue-stopped', // 🔴 R48.9 — a run he STOPPED says what it left
  //                                         undone ("2 went through; 3 never started"). Before
  //                                         this, "stopped" and "finished" looked identical.
  regionsQueueFails: 'regions-queue-fails', // ⛔ R46.7 — every refused file with its sentence,
  //                                         verbatim; outlives the queue it happened in
  regionsQueueFail: 'regions-queue-fail', // one refused file's line
  regionsProgress: 'regions-progress', //    ⏱️ ONE recording: locate / re-locate / snap. A
  //                                         `<Progress>` root (R48.2) — bar `-bar`, time `-eta`,
  //                                         Stop `-stop`. ⭐ A SNAP IS INDETERMINATE (R48.9/H9): a
  //                                         ~1 s gesture gets the travelling sliver, never a bar.
  regionsPhase: 'regions-progress', //       the phase now sits in the bar's own row; assert on the
  //                                         root's text (it holds phase AND message)
  regionsEta: 'regions-progress-eta', //     ⭐ R48.4 — NEVER EMPTY. It was an always-`''` `<span>`.
  regionsCancel: 'regions-progress-stop',
  regionsBusy: 'regions-busy', //            ⭐ R48.6 — ONE sentence naming what Camea is busy with,
  //                                         for the eleven controls that grey out together
  regionRunning: 'region-running', //        the chip on the ROW in the machine; the row also
  //                                         carries data-running (R48.6 — identity, not time)
  regionsError: 'regions-error', //          the refusal, VERBATIM (no mosaic / no electrode map /
  //                                         could not be placed) — never trimmed to a code
  regionsLoadError: 'regions-load-error',
  regionsList: 'regions-list', //            one row per located recording
  regionsEmpty: 'regions-empty',
  regionsStale: 'regions-stale', //          live warning: the mosaic was rebuilt (R46.10)
  regionsReplaceStale: 'regions-replace-stale', // walk every stale row through the queue —
  //                                         relocated one at a time, each back to unconfirmed
  regionStale: 'region-stale', //            the per-ROW chip naming which rows went stale (R47.7)
  regionsFieldsToggle: 'regions-fields-toggle', // show every rectangle, or only the selected one
  regionRow: 'region-row', //                data-region-id; data-status
  regionName: 'region-name', //              click to rename
  regionFile: 'region-file', //              the source video's file name — labels are editable, this is not
  regionWhen: 'region-when', //              when it was placed + the search time, quiet on the row
  regionElapsed: 'region-elapsed', //        the search time alone ("1.8 s"), inside region-when
  regionNameInput: 'region-name-input',
  regionStatus: 'region-status', //          unconfirmed | confirmed (R46.6)
  regionConfirm: 'region-confirm', //        ⭐ the human's signature — nothing promotes itself
  regionUnconfirm: 'region-unconfirm',
  regionDelete: 'region-delete',
  regionLocateAgain: 'region-locate-again', // re-run one row's placement from the project's own
  //                                         copy of its video — lands unconfirmed again (R46.6)
  regionPanel: 'region-panel', //            the readout for the selected region (R3: numbers)
  regionRect: 'region-rect', //              the outline on the mosaic; data-region-id, data-selected
  regionGhost: 'region-ghost', //            a runner-up spot, dashed and inert; data-rank
  regionRivals: 'region-rivals', //          "N rival spots drawn" — silent when there are none
  regionDrag: 'region-drag', //              the draggable body of the SELECTED rectangle
  regionDropped: 'region-dropped', //        "dragged, not yet snapped" state
  regionSnap: 'region-snap', //              re-runs the bounded local match at the settled scale
  regionSnapReach: 'region-snap-reach', //   how far Snap searches: nearby (drag-derived default) /
  //                                         wider / far — SCREEN budgets, converted at snap time
  //                                         (R45.7); buttons addressed by data-reach
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
  regionTried: 'region-tried', //            ⭐ R46.5 — the whole `tried` table, order as served
  regionTriedRow: 'region-tried-row', //     one attempt; data-still, data-winner on the one that won
  regionZoom: 'region-zoom', //              the scale
  regionZoomSearched: 'region-zoom-searched', // ⚠️ shown when it was SEARCHED, not measured (R46.2)
  regionPitchRecording: 'region-pitch-recording', // the electrode spacing measured in the recording
  regionPitchMosaic: 'region-pitch-mosaic', //      …and in the mosaic — the evidence behind the zoom
  regionZoomNote: 'region-zoom-note', //     the measurement's own remark, served verbatim
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
