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
import { FIXTURE, SHORT } from './fixture';

export const STEPS = ['load', 'range', 'screen', 'place', 'sweep', 'mosaic'] as const;
export type StepName = (typeof STEPS)[number];

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
  workspace: '/api/workspace', //        the app-managed store (picked once — R41.2)
  projects: '/api/workspace/analyses', // a "project" IS an analysis (list/create/delete/PATCH rename)
  document: '/api/analyses', //          PUT /api/analyses/{id}/document — the durable auto-save (R29)
} as const;

/** THE TESTID REGISTRY. Grouped by screen; see README.md for the human-readable table. */
export const TID = {
  // ── Home / shell (2026-07-24: the home is a PROJECT MANAGER — R41) ─────────────
  manager: 'project-manager', //            the home
  firstRunStore: 'first-run-store', //      R41.2 — the pick-a-folder-once prompt
  chooseStore: 'choose-store',
  newProject: 'new-project', //             the "New project" CTA
  projectCard: 'project-card', //           data-project-id; the card is the Open affordance
  projectName: 'project-name',
  projectRename: 'project-rename',
  projectExport: 'project-export',
  projectDelete: 'project-delete',
  projectGrid: 'project-grid',
  // the new-project flow (/new): name → task → dataset
  newProjectFlow: 'new-project-flow',
  npName: 'np-name',
  npNext: 'np-next',
  npBack: 'np-back',
  npCancel: 'np-cancel',
  taskCard: 'task-card', //                 data-task=mosaic
  // the attach-dataset picker (the ex-home dataset browser)
  browser: 'dataset-browser',
  card: 'dataset-card',
  cardName: 'dataset-name',
  cardSnapshots: 'dataset-snapshots',
  cardShapes: 'dataset-shapes',
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
  mosaicDir: 'mosaic-dir',
  mosaicBrowse: 'mosaic-browse',
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

/** The synthetic dataset's card on the home screen. */
export const fixtureCard = (page: Page): Locator =>
  page.getByTestId(TID.card).filter({ hasText: FIXTURE.name });

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
   * Create a project on the fixture via the new-project flow (name → task → dataset) → enters the Mosaic
   * feature at `/project/:id` (R41.3; R4.5 lands it on Range).
   *
   * ⚠️ HARNESS DEPENDENCY: assumes the app-managed store folder is already chosen and the fixture's data
   * root is registered (the e2e global-setup should `PUT /api/workspace` + scan the fixture root, mirroring
   * the python `workspace` fixture). If `first-run-store` shows instead, that setup is missing.
   */
  async openFixture(name = 'e2e project') {
    await byId(this.page, TID.newProject).click();
    await expect(this.page).toHaveURL(/\/new(\/|$)/);
    await byId(this.page, TID.npName).fill(name);
    await byId(this.page, TID.npNext).click();
    await this.page.getByTestId(TID.taskCard).first().click();
    await this.card().click();
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
