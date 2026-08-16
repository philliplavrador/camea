// ─────────────────────────────────────────────────────────────────────────────────────────────
// REGIONS — ⭐ **R46: WHERE THE CALCIUM RECORDING WAS TAKEN**, and the pipeline that walks to it.
//
// This is the destination every earlier ruling was a step towards: a rectangle on the built mosaic
// that NAMES THE ELECTRODES UNDER IT, because that is what lets an MEA channel's voltage be paired
// with the calcium trace of the neuron sitting on top of it.
//
// ⚠️ **EVERY BACKEND ANSWER HERE IS A ROUTE STUB, on purpose** — the same philosophy as
// `electrodes.spec.ts`'s `stubMap`. The committed survey video is deliberately GRIDLESS (nothing in
// a fixture may fake an electrode array), so a REAL project can never reach this screen at all:
// `Map electrodes` refuses on it, and `locate` refuses without an electrode map. The science is
// proven where it can be judged against an answer key — `tests/api/test_regions.py` cuts the
// recording out of the same synthetic world the survey swept, at a chosen crop and magnification,
// and checks the position, the measured zoom, the contiguous electrode block and repeatability.
//
// What is proven HERE is the half of R46 that is a DOM contract, and that only a browser can fail:
// what the pipeline locks, what the machine may claim, what it must flag rather than hide, and what
// only the human may sign.
//
// ⛔ NO `@slow` TWIN. A build → map → locate run over `tests/fixtures/survey.avi` cannot exist: see
// above, its world has no lattice, so the pipeline stops one step short of this screen by design.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { Buffer } from 'node:buffer';
import { test, expect, type Page, type Route } from '@playwright/test';
import { SHORT, VIDEO_FIXTURE } from './fixture';
import { ROUTES, TID, byId } from './pages';

// ─────────────────────────────────────────────────────────────────────────────────────────────
// The crafted project
// ─────────────────────────────────────────────────────────────────────────────────────────────

/** ⚠️ NOT "…-regions": the id is substituted into the region route patterns below, and an id
 *  containing "regions" would let `…/{id}/regions` collide with `…/regions`. */
const ID = 'e2e-pipeline';
const BUILT_AT = '2026-08-11T09:00:00Z';
/** The mosaic's own size — what makes "mosaic px" mean something on screen. */
const CANVAS = { w: 1200, h: 900 };
const JOB_ID = 'e2e-region-job';
const STILL = 'roi-still.png';

/** A 1×1 PNG, so the `<img>`s (the preview and the faded still) genuinely LOAD. */
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC',
  'base64',
);

interface DocOpts {
  /** A survey video is on file — unlocks Mosaic. */
  source?: boolean;
  /** A mosaic has been built (`build.built_at` + canvas) — unlocks Electrodes. */
  built?: boolean;
  /** The lattice has been numbered (`electrodes.built_at`) — unlocks Regions. */
  mapped?: boolean;
}

/** A videomosaic document, exactly as much of one as the pipeline gate reads (R46.1). */
function craftedDoc({ source = true, built = true, mapped = true }: DocOpts = {}) {
  return {
    schema_version: '3',
    app: { name: 'camea', version: 'e2e' },
    id: ID,
    feature: 'videomosaic',
    dataset: 'survey',
    experiment: '',
    data_dir: '',
    dataset_key: 'e2e-videomosaic',
    created: BUILT_AT,
    modified: BUILT_AT,
    provenance: { method: 'videomosaic', independent_of_method: false, history: [] },
    source: source
      ? {
          path: VIDEO_FIXTURE.path,
          name: 'survey.avi',
          width: VIDEO_FIXTURE.width,
          height: VIDEO_FIXTURE.height,
          fps: 20,
          n_frames: 200,
          duration_s: 10,
        }
      : null,
    build: built
      ? { built_at: BUILT_AT, canvas: CANVAS, outputs: {}, stats: { keyframes_placed: 9 } }
      : null,
    keyframes: {},
    electrodes: mapped
      ? { built_at: BUILT_AT, source_stamp: BUILT_AT, cols: 36, rows: 62, pitch_px: 14 }
      : null,
    regions: [],
  };
}

/** The project summary the FeatureGate asks for — its `feature` is what mounts this screen. */
const craftedSummary = () => ({
  analysis_id: ID,
  feature: 'videomosaic',
  name: 'pipeline e2e',
  dataset_key: 'e2e-videomosaic',
  dataset: 'survey',
  path: '',
  folder: '',
  data_dir: '',
  created: BUILT_AT,
  modified: BUILT_AT,
  bytes: 4096,
});

// ─────────────────────────────────────────────────────────────────────────────────────────────
// A located region
// ─────────────────────────────────────────────────────────────────────────────────────────────

interface Region {
  id: string;
  name: string;
  source: null;
  still: string | null;
  x: number;
  y: number;
  w: number;
  h: number;
  still_kind: string;
  zoom: {
    scale: number;
    measured: boolean;
    pitch_recording_px: number | null;
    pitch_mosaic_px: number | null;
    angle_delta_deg: number;
    note: string;
  } | null;
  ncc: number;
  margin: number;
  margin_thin: boolean;
  confident: boolean;
  candidates: unknown[];
  tried: unknown[];
  electrodes: {
    count: number;
    detected: number;
    inferred: number;
    ids: string[];
  } | null;
  status: 'unconfirmed' | 'confirmed';
  placed_by: string;
  located_at: string;
  source_stamp: string;
  moved_px: number | null;
  snap_margin: number | null;
  elapsed_ms: number;
}

/** ⭐ THE ANSWER: a contiguous block of the numbered lattice — 6 columns × 7 rows under one field. */
function electrodeBlock() {
  const ids: string[] = [];
  for (let r = 7; r <= 13; r++) for (let c = 12; c <= 17; c++) ids.push(`${c}-${r}`);
  return { count: ids.length, detected: ids.length - 2, inferred: 2, ids };
}
const FIRST_ID = '12-7';
const LAST_ID = '17-13';

interface RegionOpts {
  id?: string;
  name?: string;
  status?: 'unconfirmed' | 'confirmed';
  /** R46.7 — the two halves of "uncertain": below the confidence bar, or a rival nearly as good. */
  confident?: boolean;
  marginThin?: boolean;
  /** R46.2 — false means a LADDER was searched, and the screen must not call that a measurement. */
  measured?: boolean;
  /** R46.11 — rotation is not solved; a turned lattice is a number he can see. */
  angleDelta?: number;
  /** R46.8 — the still Camea built, already at mosaic scale. */
  still?: string | null;
  electrodes?: boolean;
  x?: number;
  y?: number;
}

function craftedRegion(o: RegionOpts = {}): Region {
  return {
    id: o.id ?? 'r-1',
    name: o.name ?? 'field A',
    source: null,
    still: o.still === undefined ? STILL : o.still,
    x: o.x ?? 180,
    y: o.y ?? 140,
    w: 300,
    h: 220,
    still_kind: 'median',
    zoom: {
      scale: 0.42,
      measured: o.measured ?? true,
      pitch_recording_px: 33.3,
      pitch_mosaic_px: 14,
      angle_delta_deg: o.angleDelta ?? 0.2,
      note: '',
    },
    ncc: 0.8142,
    margin: o.marginThin ? 0.012 : 0.134,
    margin_thin: o.marginThin ?? false,
    confident: o.confident ?? true,
    candidates: [],
    tried: [],
    electrodes: (o.electrodes ?? true) ? electrodeBlock() : null,
    status: o.status ?? 'unconfirmed',
    placed_by: 'machine',
    located_at: BUILT_AT,
    source_stamp: BUILT_AT,
    moved_px: null,
    snap_margin: null,
    elapsed_ms: 1840,
  };
}

// ─────────────────────────────────────────────────────────────────────────────────────────────
// The stub — one installer, one mutable state object the tests steer
// ─────────────────────────────────────────────────────────────────────────────────────────────

interface Stub {
  /** The list `GET …/{id}/regions` serves. Tests mutate it and reload. */
  regions: Region[];
  /** R46.10 — the mosaic was rebuilt under these locations. */
  stale: boolean;
  /** While true the locate/snap job stays RUNNING, so the progress block can be observed. */
  hold: boolean;
  /** ⛔ R46.7 — the POST itself refuses with an INSTRUCTION ("build first", "map first"). */
  refuse: string | null;
  /** ⛔ R46.7 — the job runs and cannot place it: a refusal, in a sentence. */
  jobFail: string | null;
  /** What the finished job hands back (set by the locate/snap handlers). */
  jobRegion: Region | null;
  /** Every request body that reached the wire. */
  locates: Record<string, unknown>[];
  snaps: Record<string, unknown>[];
  patches: Record<string, unknown>[];
}

interface OpenOpts {
  doc?: DocOpts;
  regions?: Region[];
  stale?: boolean;
}

const json = (route: Route, body: unknown, status = 200): Promise<void> =>
  route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

/**
 * Serve a whole prepared project — summary, document, outputs, preview bytes, region list — and open
 * it. Every stub is scoped to THIS project id, so an unstubbed call still reaches the real backend
 * and shows up as a failure rather than as silence.
 */
async function openPipeline(page: Page, opts: OpenOpts = {}): Promise<Stub> {
  const stub: Stub = {
    regions: opts.regions ?? [],
    stale: opts.stale ?? false,
    hold: false,
    refuse: null,
    jobFail: null,
    jobRegion: null,
    locates: [],
    snaps: [],
    patches: [],
  };
  const doc = craftedDoc(opts.doc);
  const vm = ROUTES.videomosaic;

  // the FeatureGate's one question: which feature owns this id?
  await page.route(new RegExp(`${ROUTES.projects}/${ID}$`), (r) => json(r, craftedSummary()));
  // the document — ⭐ the ONLY thing the pipeline gate reads (R46.1)
  await page.route(new RegExp(`${ROUTES.document}/${ID}/document$`), (r) => json(r, { doc }));
  // R44's Outputs panel: an empty project folder is a normal answer, never an error
  await page.route(new RegExp(`${ROUTES.projects}/${ID}/outputs$`), (r) =>
    json(r, { outputs: [] }),
  );
  // the bytes behind an <img>: the region still (`/api/projects/…`) and the mosaic (`/api/videomosaic/…`)
  const png = (r: Route): Promise<void> => r.fulfill({ contentType: 'image/png', body: PNG });
  await page.route(new RegExp(`${ROUTES.projects}/${ID}/outputs/[^/]+`), png);
  await page.route(new RegExp(`${vm}/${ID}/outputs/[^/]+`), png);
  // no ATTACHED job from another spec may hijack this screen (it re-attaches to a running build)
  await page.route(new RegExp(`${ROUTES.jobs}$`), (r) => json(r, { jobs: [] }));
  // the electrode MAP payload is not what this screen reads — the document's `electrodes` block is.
  await page.route(new RegExp(`${vm}/${ID}/electrodes$`), (r) =>
    json(r, { error: { code: 'no_map', message: 'not mapped' } }, 404),
  );

  // ⭐ THE REGION LIST — the fast lane's whole point: the DOM contract with no video decoded.
  await page.route(new RegExp(`${vm}/${ID}/regions$`), (r) =>
    json(r, {
      analysis_id: ID,
      regions: stub.regions,
      built_from: BUILT_AT,
      stale: stub.stale,
      outputs: { regions: 'pipeline-regions.json', csv: 'pipeline-regions.csv' },
    }),
  );

  // locate + snap: 202 → the job below. Both are `locate_region`; one lease, one job.
  await page.route(new RegExp(`${ROUTES.regions}/locate$`), async (route, req) => {
    const body = req.postDataJSON() as { path: string; name?: string };
    stub.locates.push(body as unknown as Record<string, unknown>);
    if (stub.refuse) {
      // The backend's own sentence, in the 4xx envelope the client turns into an ApiError message.
      await json(route, { error: { code: 'refused', message: stub.refuse } }, 409);
      return;
    }
    stub.jobRegion = craftedRegion({
      id: `r-${stub.regions.length + 1}`,
      name: body.name?.trim() || 'survey.avi',
    });
    await json(route, { job_id: JOB_ID, kind: 'locate_region', state: 'queued' }, 202);
  });
  await page.route(new RegExp(`${ROUTES.regions}/snap$`), async (route, req) => {
    const body = req.postDataJSON() as { region_id: string; x: number; y: number };
    stub.snaps.push(body as unknown as Record<string, unknown>);
    const was = stub.regions.find((g) => g.id === body.region_id) ?? craftedRegion();
    // The COMMITTED number is the server's, never the browser's drop (R23): it lands a little off
    // the dropped corner, and says how far.
    stub.jobRegion = {
      ...was,
      x: body.x - 1.5,
      y: body.y + 2,
      placed_by: 'hand+snap',
      status: 'unconfirmed',
      moved_px: 2.5,
      snap_margin: 0.087,
    };
    await json(route, { job_id: JOB_ID, kind: 'locate_region', state: 'queued' }, 202);
  });

  await page.route(new RegExp(`${ROUTES.jobs}/${JOB_ID}$`), async (route) => {
    if (stub.jobFail) {
      await json(route, {
        job_id: JOB_ID,
        kind: 'locate_region',
        state: 'failed',
        error: { code: 'no_placement', message: stub.jobFail },
      });
      return;
    }
    if (stub.hold || !stub.jobRegion) {
      await json(route, {
        job_id: JOB_ID,
        kind: 'locate_region',
        state: 'running',
        pct: 45,
        phase: 'matching the stills',
        eta_s: 4,
      });
      return;
    }
    const region = stub.jobRegion;
    const i = stub.regions.findIndex((g) => g.id === region.id);
    if (i < 0) stub.regions.push(region);
    else stub.regions[i] = region;
    await json(route, {
      job_id: JOB_ID,
      kind: 'locate_region',
      state: 'done',
      pct: 100,
      result: { kind: 'locate_region', analysis_id: ID, region, doc: null },
    });
  });

  // ⭐ the user's word — rename and CONFIRM, synchronous because there is nothing to compute
  await page.route(new RegExp(`${ROUTES.regions}$`), async (route, req) => {
    if (req.method() !== 'PATCH') return route.fallback();
    const body = req.postDataJSON() as {
      region_id: string;
      status?: Region['status'];
      name?: string;
    };
    stub.patches.push(body as unknown as Record<string, unknown>);
    const i = stub.regions.findIndex((g) => g.id === body.region_id);
    const updated: Region = {
      ...(stub.regions[i] ?? craftedRegion()),
      ...(body.status ? { status: body.status } : {}),
      ...(body.name ? { name: body.name } : {}),
    };
    if (i >= 0) stub.regions[i] = updated;
    await json(route, updated);
  });

  await page.goto(`/project/${ID}`);
  await expect(byId(page, TID.pipelineSteps)).toBeVisible({ timeout: 15_000 });
  return stub;
}

/** The Regions screen, open, with the selected region's readout on show. */
async function openRegions(page: Page, opts: OpenOpts = {}): Promise<Stub> {
  const stub = await openPipeline(page, opts);
  await expect(byId(page, TID.regionsStep)).toBeVisible({ timeout: SHORT });
  return stub;
}

const stepBtn = (page: Page, n: 'survey' | 'mosaic' | 'electrodes' | 'regions') =>
  byId(page, TID.pipelineStep(n));

const rowOf = (page: Page, id: string) =>
  page.locator(`[data-testid="${TID.regionRow}"][data-region-id="${id}"]`);

/** Set a React-controlled range input (a plain `.value =` is swallowed by the value tracker). */
async function setRange(page: Page, testid: string, value: number): Promise<void> {
  await byId(page, testid).evaluate((el, v) => {
    const input = el as HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
    setter?.call(input, String(v));
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }, value);
}

// ─────────────────────────────────────────────────────────────────────────────────────────────
test.describe('regions — the pipeline, and where the recording was taken (R46)', () => {
  // ───────────────────────────────────────────────────────────────────────────────────────────
  // R46.1 ⭐ IT IS ONE PIPELINE, WALKED STEP BY STEP.
  // "they go through step by step, building the mosaic, mapping the electrodes, and then finding
  // the region of the non-moving calcium recording. So it should be all one pipeline with a
  // progress bar at the top."
  // ───────────────────────────────────────────────────────────────────────────────────────────

  test('R46.1: the four steps are shown, and a step beyond the document is LOCKED and does not navigate', async ({
    page,
  }) => {
    // A built mosaic, no electrode map: Regions is one step further than this document supports.
    await openPipeline(page, { doc: { mapped: false } });

    // 1 · the pipeline is the experiment's own order, all four of it
    const nav = byId(page, TID.pipelineSteps);
    await expect(nav).toBeVisible();
    for (const label of ['Survey', 'Mosaic', 'Electrodes', 'Regions']) {
      await expect(nav).toContainText(label);
    }

    // 2 · the gate is the DOCUMENT: source + build reach Electrodes, and no further
    await expect(stepBtn(page, 'survey')).toHaveAttribute('data-locked', 'false');
    await expect(stepBtn(page, 'mosaic')).toHaveAttribute('data-locked', 'false');
    await expect(stepBtn(page, 'electrodes')).toHaveAttribute('data-locked', 'false');
    await expect(stepBtn(page, 'regions')).toHaveAttribute('data-locked', 'true');
    // …and it opened on the furthest READY step, not on the first one
    await expect(stepBtn(page, 'electrodes')).toHaveAttribute('data-active', 'true');

    // 3 · ⛔ clicking the locked step does NOT navigate — it says why, and the screen stays put.
    // ⚠️ `force` on purpose: a locked step is `aria-disabled` (assistive tech is told) but NOT
    // `disabled`, so a real browser dispatches the click and the app must answer it. Playwright's
    // actionability guard reads aria-disabled as "not enabled", which would test the guard, not the
    // ruling — the nudge only exists because the control is still clickable.
    await expect(stepBtn(page, 'regions')).toHaveAttribute('aria-disabled', 'true');
    await stepBtn(page, 'regions').click({ force: true });
    await expect(byId(page, TID.toast)).toContainText(/finish the step/i, { timeout: SHORT });
    await expect(byId(page, TID.regionsStep)).toHaveCount(0);
    await expect(stepBtn(page, 'electrodes')).toHaveAttribute('data-active', 'true');
    await expect(stepBtn(page, 'regions')).toHaveAttribute('data-active', 'false');
  });

  test('R46.1: the gate is read off the document — with no build, Electrodes AND Regions are locked', async ({
    page,
  }) => {
    await openPipeline(page, { doc: { built: false, mapped: false } });

    await expect(stepBtn(page, 'mosaic')).toHaveAttribute('data-locked', 'false');
    await expect(stepBtn(page, 'mosaic')).toHaveAttribute('data-active', 'true');
    await expect(stepBtn(page, 'electrodes')).toHaveAttribute('data-locked', 'true');
    await expect(stepBtn(page, 'regions')).toHaveAttribute('data-locked', 'true');

    await stepBtn(page, 'regions').click({ force: true }); // see the note above — aria-disabled, not disabled
    await expect(byId(page, TID.regionsStep)).toHaveCount(0);
    await expect(stepBtn(page, 'mosaic')).toHaveAttribute('data-active', 'true');
  });

  test('R46.1: a prepared project OPENS on Regions — the work is where he left it', async ({
    page,
  }) => {
    await openRegions(page, { regions: [craftedRegion()] });

    await expect(stepBtn(page, 'regions')).toHaveAttribute('data-locked', 'false');
    await expect(stepBtn(page, 'regions')).toHaveAttribute('data-active', 'true');
    await expect(stepBtn(page, 'regions')).toHaveAttribute('aria-current', 'step');

    // the located field is on the list AND drawn on the mosaic
    await expect(byId(page, TID.regionsList)).toBeVisible();
    await expect(rowOf(page, 'r-1')).toContainText('field A');
    await expect(byId(page, TID.regionRect)).toBeVisible();
    await expect(byId(page, TID.regionPanel)).toBeVisible();
  });

  // ───────────────────────────────────────────────────────────────────────────────────────────
  // R46.6 ⭐ THE MACHINE PROPOSES, HE DISPOSES. I3 applied to a rectangle instead of a tile.
  // ───────────────────────────────────────────────────────────────────────────────────────────

  test('R46.6: a located region lands unconfirmed, and only his click promotes it', async ({
    page,
  }) => {
    // Every reason a machine might promote it for him is present: high NCC, fat margin, confident.
    const stub = await openRegions(page, { regions: [craftedRegion({ confident: true })] });

    // 1 · born UNCONFIRMED — on the row, on the rectangle, and in the readout's own chip
    await expect(byId(page, TID.regionStatus)).toHaveText('unconfirmed');
    await expect(rowOf(page, 'r-1')).toHaveAttribute('data-status', 'unconfirmed');
    await expect(byId(page, TID.regionRect)).toHaveAttribute('data-status', 'unconfirmed');
    await expect(byId(page, TID.regionConfirm)).toBeVisible();
    await expect(byId(page, TID.regionUnconfirm)).toHaveCount(0);

    // 2 · the evidence is on show beside the signature, never instead of it (R3 — numbers)
    await expect(byId(page, TID.regionDetailNcc)).toHaveText('0.8142');
    await expect(byId(page, TID.regionDetailMargin)).toHaveText('0.134');
    await expect(byId(page, TID.regionStillKind)).toHaveText('median');
    await expect(byId(page, TID.regionPlacedBy)).toHaveText('machine');

    // 3 · ⭐ HIS CLICK IS THE PROMOTION — and it travels as the user's word, not as a re-derivation
    await byId(page, TID.regionConfirm).click();
    await expect(byId(page, TID.regionStatus)).toHaveText('confirmed', { timeout: SHORT });
    await expect(byId(page, TID.regionRect)).toHaveAttribute('data-status', 'confirmed');
    await expect(rowOf(page, 'r-1')).toHaveAttribute('data-status', 'confirmed');
    await expect(byId(page, TID.regionUnconfirm)).toBeVisible();
    expect(stub.patches).toHaveLength(1);
    expect(stub.patches[0]).toMatchObject({ region_id: 'r-1', status: 'confirmed' });

    // 4 · …and it is reversible: a signature he can withdraw is a signature worth having
    await byId(page, TID.regionUnconfirm).click();
    await expect(byId(page, TID.regionStatus)).toHaveText('unconfirmed', { timeout: SHORT });
    expect(stub.patches[1]).toMatchObject({ region_id: 'r-1', status: 'unconfirmed' });
  });

  test('R46.6: a drop is NOT a commit — dragging arms Snap, and the server gets the dropped corner', async ({
    page,
  }) => {
    const stub = await openRegions(page, { regions: [craftedRegion()] });
    const dropped = byId(page, TID.regionDropped);
    await expect(dropped).not.toHaveAttribute('data-pending', 'true');

    // Drag the selected rectangle by its grab box (R45.7 — a handle is a SCREEN distance).
    const grab = byId(page, TID.regionDrag);
    const box = await grab.boundingBox();
    if (!box) throw new Error('the selected rectangle has no drag handle');
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 + 60, box.y + box.height / 2 + 40, { steps: 8 });
    await page.mouse.up();

    // 1 · it moved on SCREEN only — nothing was written, and the panel says exactly that
    await expect(dropped).toHaveAttribute('data-pending', 'true', { timeout: SHORT });
    await expect(dropped).toContainText('not saved yet');
    expect(stub.snaps).toHaveLength(0);

    // 2 · Snap posts the corner he dropped it on — down and to the right of where it was (R19:
    //     positions are TOP-LEFT corners, never centres)
    await byId(page, TID.regionSnap).click();
    await expect.poll(() => stub.snaps.length, { timeout: SHORT }).toBe(1);
    const posted = stub.snaps[0] as { region_id: string; x: number; y: number };
    expect(posted.region_id).toBe('r-1');
    expect(posted.x).toBeGreaterThan(180);
    expect(posted.y).toBeGreaterThan(140);

    // 3 · the committed number is the SERVER's (R23) — it reports how far the snap pulled it, and
    //     the region is back to `unconfirmed`, placed by hand+snap
    await expect(byId(page, TID.regionSnapBanner)).toContainText('Snapped', { timeout: SHORT });
    await expect(byId(page, TID.regionMoved)).toHaveText('2.50 px');
    await expect(byId(page, TID.regionSnapMargin)).toHaveText('0.087');
    await expect(byId(page, TID.regionPlacedBy)).toHaveText('hand+snap');
    await expect(byId(page, TID.regionStatus)).toHaveText('unconfirmed');
  });

  // ───────────────────────────────────────────────────────────────────────────────────────────
  // R46.7 — AN UNCERTAIN PLACEMENT IS SHOWN, FLAGGED — NOT HIDDEN. A roughly-right start is what
  // makes drag-and-snap worth having; hiding it would leave him nothing to correct.
  // ───────────────────────────────────────────────────────────────────────────────────────────

  test('R46.7: a thin margin FLAGS the rectangle — and the rectangle is still drawn', async ({
    page,
  }) => {
    await openRegions(page, {
      regions: [craftedRegion({ confident: false, marginThin: true, angleDelta: 4.25 })],
    });

    // 1 · the warning stays ON THE PAGE (§5 — never a tooltip), and names the thin-margin case
    const warn = byId(page, TID.regionUncertain);
    await expect(warn).toBeVisible();
    await expect(warn).toContainText(/uncertain/i);
    await expect(warn).toContainText(/rival/i);

    // 2 · ⛔ NOT HIDDEN: the outline is on the mosaic, the row is in the list, and Snap is reachable
    await expect(byId(page, TID.regionRect)).toBeVisible();
    await expect(byId(page, TID.regionRect)).toHaveAttribute('data-status', 'unconfirmed');
    await expect(rowOf(page, 'r-1')).toBeVisible();
    await expect(byId(page, TID.regionSnap)).toBeEnabled();
    await expect(byId(page, TID.regionMargin)).toHaveAttribute('data-thin', 'true');

    // 3 · R46.11 — rotation is NOT solved, and that is said out loud rather than silently mis-placed
    const angle = byId(page, TID.regionAngleWarning);
    await expect(angle).toBeVisible();
    await expect(angle).toContainText('4.25');
    await expect(angle).toContainText(/not corrected/i);
  });

  // ⛔ R46.7's other half — A PLACEMENT THAT COULD NOT BE MADE **REFUSES WITH A SENTENCE**. A
  // hallucinated location names the wrong electrodes, which is far more expensive than saying so; and
  // the sentence is usually an INSTRUCTION, so it reaches the screen whole rather than as a code.
  test('R46.7 ⛔: a refusal is shown whole — the typed path is kept, and no region is invented', async ({
    page,
  }) => {
    const stub = await openRegions(page);

    // 1 · the pipeline's own precondition, refused at the door (the POST never becomes a job)
    const FIRST = 'map the electrodes first — a region cannot name what is under it without them';
    stub.refuse = FIRST;
    await byId(page, TID.regionsPath).fill(VIDEO_FIXTURE.path);
    await byId(page, TID.regionsLocate).click();

    const err = byId(page, TID.regionsError);
    await expect(err).toBeVisible({ timeout: SHORT });
    await expect(err).toContainText(FIRST);
    // ⭐ R42.5 — the text he typed STAYS in the box, so the fix is an edit and not a retype
    await expect(byId(page, TID.regionsPath)).toHaveValue(VIDEO_FIXTURE.path);
    await expect(byId(page, TID.regionsEmpty)).toBeVisible();
    await expect(byId(page, TID.regionRow)).toHaveCount(0);

    // 2 · and the same again when the job RAN and could not place it: a sentence, not a rectangle
    const SECOND =
      'no confident placement: the best score was 0.21 and its runner-up was 0.20 — the ' +
      'recording may not overlap this mosaic';
    stub.refuse = null;
    stub.jobFail = SECOND;
    await byId(page, TID.regionsLocate).click();
    await expect(err).toContainText(SECOND, { timeout: SHORT });
    await expect(byId(page, TID.regionsProgress)).toHaveCount(0);
    await expect(byId(page, TID.regionRow)).toHaveCount(0);
    await expect(byId(page, TID.regionRect)).toHaveCount(0);
    await expect(byId(page, TID.regionPanel)).toHaveCount(0);
  });

  // ───────────────────────────────────────────────────────────────────────────────────────────
  // R46.2 ⭐ THE ZOOM IS MEASURED, NEVER SEARCHED — and when the fallback ladder IS used, the
  // record says so. ⛔ A search must never be presented as a measurement.
  // ───────────────────────────────────────────────────────────────────────────────────────────

  test('R46.2: a searched zoom is flagged as searched; a measured one carries no such warning', async ({
    page,
  }) => {
    const stub = await openRegions(page, { regions: [craftedRegion({ measured: false })] });

    const searched = byId(page, TID.regionZoomSearched);
    await expect(searched).toBeVisible();
    await expect(searched).toContainText(/searched, not measured/i);
    await expect(byId(page, TID.regionZoom)).toContainText('searched');
    await expect(byId(page, TID.regionZoom)).not.toHaveAttribute('data-measured', 'true');

    // The same screen over a MEASURED zoom says nothing of the kind — the warning is about this
    // record's own flag, not decoration.
    stub.regions = [craftedRegion({ measured: true })];
    await page.reload();
    await expect(byId(page, TID.regionPanel)).toBeVisible({ timeout: 15_000 });
    await expect(byId(page, TID.regionZoomSearched)).toHaveCount(0);
    await expect(byId(page, TID.regionZoom)).toContainText('measured');
    await expect(byId(page, TID.regionZoom)).toHaveAttribute('data-measured', 'true');
  });

  // ───────────────────────────────────────────────────────────────────────────────────────────
  // R46.8 — THE RECORDING'S OWN PICTURE FADES INTO THE RECTANGLE, with an opacity slider (his
  // explicit ask). Whether the tissue lines up is a question the eye answers better than an NCC.
  // ───────────────────────────────────────────────────────────────────────────────────────────

  test('R46.8: the recording’s still is drawn in the rectangle, and the slider fades it', async ({
    page,
  }) => {
    await openRegions(page, { regions: [craftedRegion()] });

    const still = byId(page, TID.regionStill);
    await expect(still).toBeVisible();
    // it is the PROJECT's own file, served out of outputs/ (R44) — and it really loaded
    await expect(still).toHaveAttribute('src', new RegExp(`outputs/${STILL}`));
    await expect
      .poll(() => still.evaluate((el) => (el as HTMLImageElement).naturalWidth), { timeout: SHORT })
      .toBeGreaterThan(0);

    const opacity = () => still.evaluate((el) => getComputedStyle(el).opacity);
    const first = Number(await opacity());
    expect(first).toBeGreaterThan(0);
    expect(first).toBeLessThan(1);

    await setRange(page, TID.regionFade, 100);
    await expect.poll(opacity, { timeout: SHORT }).toBe('1');
    await setRange(page, TID.regionFade, 25);
    await expect.poll(opacity, { timeout: SHORT }).toBe('0.25');

    // …all the way off: nothing is left over the mosaic, which is half of what the slider is for
    await setRange(page, TID.regionFade, 0);
    await expect(byId(page, TID.regionStill)).toHaveCount(0);
    // ⭐ and the RECTANGLE stays — the fade takes the picture, never the location
    await expect(byId(page, TID.regionRect)).toBeVisible();
  });

  // ───────────────────────────────────────────────────────────────────────────────────────────
  // R46.10 — A REBUILD STALES EVERY LOCATION. Nothing silently drifts onto new pixels.
  // ───────────────────────────────────────────────────────────────────────────────────────────

  test('R46.10: a rebuilt mosaic stales every location, and says so on the page', async ({
    page,
  }) => {
    const stub = await openRegions(page, { regions: [craftedRegion()], stale: true });

    const warn = byId(page, TID.regionsStale);
    await expect(warn).toBeVisible();
    await expect(warn).toContainText(/rebuilt/i);
    // ⛔ Reported, never repaired: the location is still there to re-snap, not deleted or moved.
    await expect(byId(page, TID.regionRect)).toBeVisible();
    await expect(byId(page, TID.regionSnap)).toBeEnabled();

    // A list that is NOT stale says nothing — the warning tracks the payload, not the screen.
    stub.stale = false;
    await page.reload();
    await expect(byId(page, TID.regionsList)).toBeVisible({ timeout: 15_000 });
    await expect(byId(page, TID.regionsStale)).toHaveCount(0);
  });

  // ───────────────────────────────────────────────────────────────────────────────────────────
  // ⭐ THE ELECTRODES UNDERNEATH ARE THE ANSWER — *"this lets us basically pair up the MEA
  // recording of the electrodes with the traces of the neurons from the calcium imaging"*.
  // ───────────────────────────────────────────────────────────────────────────────────────────

  test('the electrodes under the rectangle are the answer — counted, ranged, listed; "none" when there are none', async ({
    page,
  }) => {
    await openRegions(page, {
      regions: [
        craftedRegion({ id: 'r-1', name: 'field A' }),
        craftedRegion({ id: 'r-2', name: 'field B', electrodes: false }),
      ],
    });

    // 1 · the count, the span of ids, and the honest split between seen and inferred pads
    await expect(byId(page, TID.regionElectrodeCount)).toHaveText('42');
    await expect(byId(page, TID.regionElectrodeRange)).toHaveText(
      new RegExp(`${FIRST_ID}\\s*…\\s*${LAST_ID}`),
    );
    await expect(byId(page, TID.regionElectrodeSplit)).toContainText('40 detected');
    await expect(byId(page, TID.regionElectrodeSplit)).toContainText('2 inferred');
    // the row carries the same count, so the list answers "which field, how many" at a glance
    await expect(rowOf(page, 'r-1').getByTestId(TID.regionElectrodes)).toHaveText('42');

    // 2 · every id is available, behind a disclosure rather than dumped on the page
    const list = byId(page, TID.regionElectrodeList);
    await expect(list).toBeHidden();
    await byId(page, TID.regionElectrodeListToggle).click();
    await expect(list).toBeVisible();
    await expect(list).toContainText(FIRST_ID);
    await expect(list).toContainText(LAST_ID);

    // 3 · ⛔ A REGION WITH NO ELECTRODES SAYS SO — a fabricated block would name the wrong channels
    await rowOf(page, 'r-2').getByTestId(TID.regionStatus).click();
    await expect(byId(page, TID.regionElectrodesNone)).toBeVisible({ timeout: SHORT });
    await expect(byId(page, TID.regionElectrodeCount)).toHaveCount(0);
    await expect(byId(page, TID.regionElectrodeRange)).toHaveCount(0);
  });

  // ───────────────────────────────────────────────────────────────────────────────────────────
  // R38 — HEADLESS STAYS DRIVABLE. There is no native file dialog here, so the typed box is the
  // only door: the whole locate flow must work through it. (R46.9: the path asked for is where the
  // recording came FROM — the one path question allowed inside a project.)
  // ───────────────────────────────────────────────────────────────────────────────────────────

  test('R38: the recording path is a typeable box — locate runs, shows progress, and lands a region', async ({
    page,
  }) => {
    const stub = await openRegions(page);
    await expect(byId(page, TID.regionsEmpty)).toBeVisible();

    // 1 · nothing typed, nothing to locate; Browse… exists but is not the only way in
    await expect(byId(page, TID.regionsLocate)).toBeDisabled();
    await expect(byId(page, TID.regionsBrowse)).toBeVisible();

    stub.hold = true; // keep the job running so the progress block can be observed
    await byId(page, TID.regionsPath).fill(VIDEO_FIXTURE.path);
    await byId(page, TID.regionsName).fill('field C');
    await expect(byId(page, TID.regionsLocate)).toBeEnabled();
    await byId(page, TID.regionsLocate).click();

    // 2 · the typed path is what reached the wire — with the label, and nothing about where to SAVE
    await expect.poll(() => stub.locates.length, { timeout: SHORT }).toBe(1);
    expect(String(stub.locates[0].path)).toMatch(/survey\.avi$/);
    expect(stub.locates[0].name).toBe('field C');

    // 3 · a long op reports itself and is cancellable (R8)
    await expect(byId(page, TID.regionsProgress)).toBeVisible({ timeout: SHORT });
    await expect(byId(page, TID.regionsPhase)).toContainText('matching the stills');
    await expect(byId(page, TID.regionsCancel)).toBeVisible();

    // 4 · …and the finished job's region is adopted, unconfirmed, selected, with its electrodes
    stub.hold = false;
    await expect(rowOf(page, 'r-1')).toBeVisible({ timeout: 15_000 });
    await expect(rowOf(page, 'r-1')).toContainText('field C');
    await expect(rowOf(page, 'r-1')).toHaveAttribute('data-status', 'unconfirmed');
    await expect(byId(page, TID.regionsProgress)).toHaveCount(0);
    await expect(byId(page, TID.regionsEmpty)).toHaveCount(0);
    await expect(byId(page, TID.regionElectrodeCount)).toHaveText('42');
  });

  // ─────────────────────────────────────────────────────────────────────────────────────────────
  // ⭐ R47 — THE TOOLS LIVE BESIDE THE PICTURE.
  //
  // His complaint, 2026-08-12: *"it's hard to check whether the region placed correctly because the
  // opacity slider is hard to access — the user has to scroll all the way down. I need all the
  // tools to be accessible while the user is looking at the image."*
  //
  // These live here rather than in a spec of their own because the pipeline stub above IS the
  // harness they need — a built mosaic, a numbered lattice and a located region.
  // ─────────────────────────────────────────────────────────────────────────────────────────────

  test('R47.1: the tools are beside the picture — reachable with the page never scrolled', async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await openRegions(page, { regions: [craftedRegion({ id: 'r-1', name: 'activity' })] });

    // 1 · the frame exists, and the RAIL is the only thing that scrolls
    await expect(byId(page, TID.regionsWork)).toBeVisible({ timeout: SHORT });
    await expect(byId(page, TID.vmRail)).toBeVisible();

    // 2 · ⭐ THE POINT — every tool he named is in the viewport with nothing scrolled anywhere.
    for (const id of [TID.regionFade, TID.regionSnap, TID.regionConfirm, TID.regionsList]) {
      await expect(byId(page, id)).toBeInViewport();
    }

    // 3 · the page itself does not scroll. Not "is scrolled to the top" — has NO scroll to do, so
    // a tool cannot be scrolled away from in the first place.
    const overflow = await page.evaluate(() => {
      const d = document.documentElement;
      return { docScroll: d.scrollHeight - d.clientHeight, y: window.scrollY };
    });
    expect(overflow.docScroll).toBeLessThanOrEqual(0);
    expect(overflow.y).toBe(0);

    // 4 · and the picture got the room: the stage is the wider half of the frame.
    const stage = await byId(page, TID.vmViewer).boundingBox();
    const rail = await byId(page, TID.vmRail).boundingBox();
    expect(stage!.width).toBeGreaterThan(rail!.width);
    expect(stage!.height).toBeGreaterThan(400);
  });

  test('R47.2: hold Space to swap the two pictures; releasing puts it back', async ({ page }) => {
    await openRegions(page, { regions: [craftedRegion({ id: 'r-1', name: 'activity' })] });
    const still = byId(page, TID.regionStill);
    const opacity = () => still.evaluate((el) => Number(getComputedStyle(el).opacity));

    // the slider starts LOW, so the flash goes to the recording — full overlay
    await setRange(page, TID.regionFade, 10);
    await expect.poll(opacity, { timeout: SHORT }).toBeCloseTo(0.1, 2);

    await page.keyboard.down(' ');
    await expect(byId(page, TID.regionFadeValue)).toHaveText('100%');
    await expect.poll(opacity, { timeout: SHORT }).toBeCloseTo(1, 2);

    // ⛔ RELEASING RESTORES. The slider is where it was — a hold is not an edit.
    await page.keyboard.up(' ');
    await expect(byId(page, TID.regionFadeValue)).toHaveText('10%');
    await expect(byId(page, TID.regionFade)).toHaveValue('10');
    await expect.poll(opacity, { timeout: SHORT }).toBeCloseTo(0.1, 2);

    // ⭐ AND IT SWAPS THE OTHER WAY. With the overlay already up, the flash shows the MOSAIC —
    // a key that always went to 100% would do nothing exactly when he is looking hardest.
    await setRange(page, TID.regionFade, 90);
    await page.keyboard.down(' ');
    await expect(byId(page, TID.regionFadeValue)).toHaveText('0%');
    await expect(still).toHaveCount(0); // nothing drawn at all, not a 0-opacity ghost
    await page.keyboard.up(' ');
    await expect(byId(page, TID.regionFadeValue)).toHaveText('90%');

    // [ and ] nudge it by 10 without touching the mouse
    await page.keyboard.press('[');
    await expect(byId(page, TID.regionFade)).toHaveValue('80');
    await page.keyboard.press(']');
    await expect(byId(page, TID.regionFade)).toHaveValue('90');
  });

  test('R47.3: the evidence is one line until asked; nothing is deleted behind the fold', async ({
    page,
  }) => {
    await openRegions(page, { regions: [craftedRegion({ id: 'r-1' })] });

    // the two numbers that decide a placement read on the rail…
    await expect(byId(page, TID.regionDetailNcc)).toBeVisible();
    await expect(byId(page, TID.regionDetailMargin)).toBeVisible();

    // …and the working is folded, not gone
    const zoom = byId(page, TID.regionZoom);
    await expect(zoom).toBeHidden();
    await byId(page, TID.regionEvidenceToggle).click();
    await expect(zoom).toBeVisible();
    await expect(byId(page, TID.regionStillKind)).toBeVisible();
    await expect(byId(page, TID.regionPlacedBy)).toBeVisible();
  });

  test('R47.4: the pipeline bar says what each step is for', async ({ page }) => {
    await openRegions(page);
    for (const [step, says] of [
      ['survey', /check the video/i],
      ['mosaic', /build the picture/i],
      ['electrodes', /number the pads/i],
      ['regions', /place your recordings/i],
    ] as const) {
      await expect(byId(page, TID.pipelineAction(step))).toHaveText(says);
    }
  });

  // ───────────────────────────────────────────────────────────────────────────────────────────
  // ⭐ QUALITY OF LIFE (2026-08-15). The camera goes to the recording he picks; the keyboard
  // walks the list; each row names its file; the runner-up spots are drawn as ghosts.
  // ───────────────────────────────────────────────────────────────────────────────────────────

  test('selecting a recording frames it — and a re-render or a re-click never moves the camera', async ({
    page,
  }) => {
    // r-2 sits at the CANVAS CENTRE on purpose: whether the framed view is clamped or centred by
    // the stage, a centre-of-canvas rectangle lands at the centre of the stage either way, so the
    // "centred" assertion below holds without knowing the stage's size.
    await openRegions(page, {
      regions: [
        craftedRegion({ id: 'r-1', name: 'field A' }),
        craftedRegion({ id: 'r-2', name: 'field B', x: 450, y: 340 }),
      ],
    });

    // 1 · at open the camera sits at FIT — the auto-selected first row must not have moved it
    const zoom = byId(page, TID.vmZoomLevel);
    await expect(byId(page, TID.vmViewer)).toHaveAttribute('data-fit', 'true');
    const atFit = (await zoom.textContent()) ?? '';

    // 2 · clicking the other row frames its rectangle: zoomed past fit…
    await rowOf(page, 'r-2').click();
    await expect(rowOf(page, 'r-2')).toHaveAttribute('data-selected', 'true');
    await expect(zoom).not.toHaveText(atFit, { timeout: SHORT });
    await expect(byId(page, TID.vmViewer)).not.toHaveAttribute('data-fit', 'true');

    // …and centred on the stage
    const stage = await byId(page, TID.vmViewer).boundingBox();
    const rect = await page
      .locator(`[data-testid="${TID.regionRect}"][data-region-id="r-2"]`)
      .boundingBox();
    expect(Math.abs(rect!.x + rect!.width / 2 - (stage!.x + stage!.width / 2))).toBeLessThan(10);
    expect(Math.abs(rect!.y + rect!.height / 2 - (stage!.y + stage!.height / 2))).toBeLessThan(10);

    // 3 · re-clicking the row he is already on is NOT a selection change — the camera stays put
    const framedAt = (await zoom.textContent()) ?? '';
    await rowOf(page, 'r-2').click();
    await page.waitForTimeout(150); // long enough for a wrong re-frame to have painted
    await expect(zoom).toHaveText(framedAt);
  });

  test('R47.5: Files is ONE door, opened by asking — and Escape closes it (R44 intact)', async ({
    page,
  }) => {
    await openRegions(page);

    // ⛔ not stacked under the step any more
    await expect(byId(page, TID.outputsPanel)).toHaveCount(0);

    await byId(page, TID.vmFiles).click();
    await expect(byId(page, TID.outputsDrawer)).toBeVisible({ timeout: SHORT });
    await expect(byId(page, TID.outputsPanel)).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(byId(page, TID.outputsDrawer)).toHaveCount(0);
    await expect(byId(page, TID.outputsPanel)).toHaveCount(0);
  });
});
