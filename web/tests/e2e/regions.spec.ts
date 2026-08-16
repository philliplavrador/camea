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
  source: { path: string; name: string } | null;
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
  candidates: { rank: number; x: number; y: number; ncc: number; npix: number; subpixel: boolean }[];
  /** R46.5 — every still × scale the search attempted, in the order it tried them. */
  tried: {
    still_kind: string;
    scale: number;
    ncc: number | null;
    margin: number | null;
    refused: string | null;
  }[];
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
  /** R46.10 per row — derived by the server from `source_stamp` vs the current build. */
  stale: boolean;
  moved_px: number | null;
  snap_margin: number | null;
  /** What the last snap ACTUALLY searched — the server's clamped number, quoted in the banner. */
  snap_radius_px: number | null;
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
  /** The video FILE behind the row — the label is editable, this is not. */
  sourceName?: string;
  /** The whole ranked list the search kept — candidates[0] is the winner, the rest are rivals. */
  candidates?: Region['candidates'];
  /** R46.10 — this row was placed against an earlier build (the server derives it per row). */
  stale?: boolean;
  /** R46.5 — the whole attempt table; defaulted to three stills, one refused. */
  tried?: Region['tried'];
  /** The zoom's own caveat sentence, when the measurement had one. */
  zoomNote?: string;
}

function craftedRegion(o: RegionOpts = {}): Region {
  return {
    id: o.id ?? 'r-1',
    name: o.name ?? 'field A',
    source: o.sourceName
      ? { path: `C:/recordings/session-1/${o.sourceName}`, name: o.sourceName }
      : null,
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
      note: o.zoomNote ?? '',
    },
    ncc: 0.8142,
    margin: o.marginThin ? 0.012 : 0.134,
    margin_thin: o.marginThin ?? false,
    confident: o.confident ?? true,
    candidates: o.candidates ?? [],
    // R46.5 — served in the order tried; the winner is the median row (the record's still_kind).
    tried: o.tried ?? [
      { still_kind: 'median', scale: 0.42, ncc: 0.8142, margin: 0.134, refused: null },
      { still_kind: 'max', scale: 0.42, ncc: 0.7011, margin: 0.052, refused: null },
      {
        still_kind: 'std',
        scale: 0.42,
        ncc: null,
        margin: null,
        refused: 'nothing measurable in this picture',
      },
    ],
    electrodes: (o.electrodes ?? true) ? electrodeBlock() : null,
    status: o.status ?? 'unconfirmed',
    placed_by: 'machine',
    located_at: BUILT_AT,
    source_stamp: BUILT_AT,
    stale: o.stale ?? false,
    moved_px: null,
    snap_margin: null,
    snap_radius_px: null,
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
  /** Per-path refusals for a several-at-once run: exact path → the sentence it gets. */
  refuseFor: Record<string, string>;
  /** ⛔ R46.7 — the job runs and cannot place it: a refusal, in a sentence. */
  jobFail: string | null;
  /** What the finished job hands back (set by the locate/snap handlers). */
  jobRegion: Region | null;
  /** Every request body that reached the wire. */
  locates: Record<string, unknown>[];
  snaps: Record<string, unknown>[];
  relocates: Record<string, unknown>[];
  patches: Record<string, unknown>[];
  /** Region ids DELETEd — the keyboard's Delete must travel the same wire as the button's. */
  deletes: string[];
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
    refuseFor: {},
    jobFail: null,
    jobRegion: null,
    locates: [],
    snaps: [],
    relocates: [],
    patches: [],
    deletes: [],
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

  // forget a region — the ONE wire, whether the row's button or the Delete key asked
  await page.route(new RegExp(`${vm}/${ID}/regions/[^/]+$`), async (route, req) => {
    if (req.method() !== 'DELETE') return route.fallback();
    const rid = req.url().split('/').pop() ?? '';
    stub.deletes.push(rid);
    stub.regions = stub.regions.filter((g) => g.id !== rid);
    await json(route, {
      analysis_id: ID,
      regions: stub.regions,
      built_from: BUILT_AT,
      stale: stub.stale,
      outputs: {},
    });
  });

  // locate + snap: 202 → the job below. Both are `locate_region`; one lease, one job.
  await page.route(new RegExp(`${ROUTES.regions}/locate$`), async (route, req) => {
    const body = req.postDataJSON() as { path: string; name?: string };
    stub.locates.push(body as unknown as Record<string, unknown>);
    const perFile = stub.refuseFor[body.path];
    if (stub.refuse || perFile) {
      // The backend's own sentence, in the 4xx envelope the client turns into an ApiError message.
      await json(route, { error: { code: 'refused', message: stub.refuse ?? perFile } }, 409);
      return;
    }
    stub.jobRegion = craftedRegion({
      id: `r-${stub.regions.length + 1}`,
      name: body.name?.trim() || body.path.split(/[\\/]/).pop() || 'survey.avi',
    });
    await json(route, { job_id: JOB_ID, kind: 'locate_region', state: 'queued' }, 202);
  });
  // "Locate again" — the server re-runs the placement from the project's OWN copy of the video.
  // The result is machine-proposed again (R46.6): unconfirmed, `machine`, fresh evidence.
  await page.route(new RegExp(`${ROUTES.regions}/relocate$`), async (route, req) => {
    const body = req.postDataJSON() as { region_id: string };
    stub.relocates.push(body as unknown as Record<string, unknown>);
    const was = stub.regions.find((g) => g.id === body.region_id) ?? craftedRegion();
    stub.jobRegion = {
      ...was,
      status: 'unconfirmed',
      placed_by: 'machine',
      ncc: 0.9012,
      margin: 0.201,
      located_at: '2026-08-16T10:00:00Z',
      source_stamp: BUILT_AT,
      stale: false, // re-placed against the current build — the row's chip clears
    };
    await json(route, { job_id: JOB_ID, kind: 'locate_region', state: 'queued' }, 202);
  });
  await page.route(new RegExp(`${ROUTES.regions}/snap$`), async (route, req) => {
    const body = req.postDataJSON() as { region_id: string; x: number; y: number; radius?: number };
    stub.snaps.push(body as unknown as Record<string, unknown>);
    const was = stub.regions.find((g) => g.id === body.region_id) ?? craftedRegion();
    // The COMMITTED number is the server's, never the browser's drop (R23): it lands a little off
    // the dropped corner, and says how far. `snap_radius_px` is what was ACTUALLY searched —
    // the ask through the server's clamp, or the drag-derived default.
    stub.jobRegion = {
      ...was,
      x: body.x - 1.5,
      y: body.y + 2,
      placed_by: 'hand+snap',
      status: 'unconfirmed',
      moved_px: 2.5,
      snap_margin: 0.087,
      snap_radius_px: body.radius != null ? Math.min(body.radius, 768) : 102,
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

const stepBtn = (page: Page, n: 'survey' | 'mosaic' | 'electrodes' | 'regions' | 'orientation') =>
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

    // 1 · the pipeline is the experiment's own order, all five of it (Orientation joined 2026-08-15)
    const nav = byId(page, TID.pipelineSteps);
    await expect(nav).toBeVisible();
    for (const label of ['Survey', 'Mosaic', 'Electrodes', 'Regions', 'Orientation']) {
      await expect(nav).toContainText(label);
    }

    // 2 · the gate is the DOCUMENT: source + build reach Electrodes, and no further
    await expect(stepBtn(page, 'survey')).toHaveAttribute('data-locked', 'false');
    await expect(stepBtn(page, 'mosaic')).toHaveAttribute('data-locked', 'false');
    await expect(stepBtn(page, 'electrodes')).toHaveAttribute('data-locked', 'false');
    await expect(stepBtn(page, 'regions')).toHaveAttribute('data-locked', 'true');
    await expect(stepBtn(page, 'orientation')).toHaveAttribute('data-locked', 'true');
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
    await expect(stepBtn(page, 'orientation')).toHaveAttribute('data-locked', 'true');

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

  test('R46.6: "Locate again" re-runs a row from the project’s own copy — and lands unconfirmed again', async ({
    page,
  }) => {
    // Confirmed on purpose: the re-run must take the signature back, because the placement is the
    // machine's proposal again (R46.6 — no are-you-sure; Confirm IS the confirm step).
    const stub = await openRegions(page, { regions: [craftedRegion({ status: 'confirmed' })] });
    await expect(byId(page, TID.regionStatus)).toHaveText('confirmed');

    // 1 · the row's own action, and the wire carries the region id — NO path: the server already
    //     holds the project's copy of the recording
    await rowOf(page, 'r-1').getByTestId(TID.regionLocateAgain).click();
    await expect.poll(() => stub.relocates.length, { timeout: SHORT }).toBe(1);
    expect(stub.relocates[0]).toMatchObject({ region_id: 'r-1' });
    expect(stub.relocates[0].path).toBeUndefined();
    await expect(byId(page, TID.regionsPath)).toHaveValue('');

    // 2 · the job lands: SAME row (replaced, never duplicated), back to unconfirmed, fresh numbers
    await expect(rowOf(page, 'r-1')).toHaveAttribute('data-status', 'unconfirmed', {
      timeout: SHORT,
    });
    await expect(byId(page, TID.regionStatus)).toHaveText('unconfirmed');
    await expect(byId(page, TID.regionPlacedBy)).toHaveText('machine');
    await expect(rowOf(page, 'r-1').getByTestId(TID.regionNcc)).toHaveText('0.9012');
    await expect(byId(page, TID.regionRow)).toHaveCount(1);

    // 3 · disabled while any job runs — locate, snap and locate-again share the one lease
    stub.hold = true;
    await rowOf(page, 'r-1').getByTestId(TID.regionLocateAgain).click();
    await expect.poll(() => stub.relocates.length, { timeout: SHORT }).toBe(2);
    await expect(byId(page, TID.regionsProgress)).toBeVisible({ timeout: SHORT });
    await expect(rowOf(page, 'r-1').getByTestId(TID.regionLocateAgain)).toBeDisabled();
    stub.hold = false;
    await expect(byId(page, TID.regionsProgress)).toHaveCount(0, { timeout: SHORT });
  });

  // ───────────────────────────────────────────────────────────────────────────────────────────
  // ⭐ SEVERAL AT ONCE (2026-08-16). The native multi-select feeds a client-driven queue through
  // the one lease: a visible readout, per-file refusals that do NOT kill the queue, and a
  // "Stop after this one". The single-path box stays exactly as it was (R38).
  // ───────────────────────────────────────────────────────────────────────────────────────────

  test('several at once: the queue reads out, a refused file keeps its sentence, and the rest still land', async ({
    page,
  }) => {
    const stub = await openRegions(page);
    const SENTENCE =
      'no confident placement: the best score was 0.21 — the recording may not overlap this mosaic';
    stub.refuseFor['C:/recordings/two.avi'] = SENTENCE;
    // the native dialog, stubbed: three files in one gesture
    await page.route(/\/api\/dialog\/open-file$/, (r) =>
      json(r, {
        path: null,
        paths: ['C:/recordings/one.avi', 'C:/recordings/two.avi', 'C:/recordings/three.avi'],
      }),
    );

    // 1 · the first locate is held RUNNING so the readout is observable: 1 placing, 2 waiting
    stub.hold = true;
    await byId(page, TID.regionsPickFiles).click();
    await expect(byId(page, TID.regionsQueue)).toBeVisible({ timeout: SHORT });
    await expect(byId(page, TID.regionsQueue)).toContainText('Placing 1 of 3');
    await expect(byId(page, TID.regionsQueue)).toContainText('2 waiting');
    await expect(byId(page, TID.regionsProgress)).toBeVisible();
    expect(stub.locates).toHaveLength(1);
    expect(String(stub.locates[0].path)).toMatch(/one\.avi$/);

    // 2 · release: one lands; two REFUSES with its sentence; three still runs and lands.
    stub.hold = false;
    await expect(byId(page, TID.regionsQueue)).toHaveCount(0, { timeout: 15_000 });
    await expect(byId(page, TID.regionRow)).toHaveCount(2);
    await expect(rowOf(page, 'r-1')).toContainText('one.avi');
    await expect(rowOf(page, 'r-2')).toContainText('three.avi');
    expect(stub.locates).toHaveLength(3);

    // ⛔ R46.7 — the refused file stays LISTED with the backend's sentence, verbatim, after the
    // queue is gone; and the queue was not killed by it.
    const fails = byId(page, TID.regionsQueueFails);
    await expect(fails).toBeVisible();
    await expect(fails).toContainText('two.avi');
    await expect(fails).toContainText(SENTENCE);
    await expect(byId(page, TID.regionsQueueFail)).toHaveCount(1);

    // 3 · the single-path flow is untouched (R38): the box is back, typeable, and Browse remains
    await expect(byId(page, TID.regionsPath)).toBeEnabled();
    await expect(byId(page, TID.regionsBrowse)).toBeEnabled();

    // 4 · "Stop after this one": a fresh run, stopped during its first job — the rest are drained
    stub.hold = true;
    await byId(page, TID.regionsPickFiles).click();
    await expect(byId(page, TID.regionsQueue)).toContainText('Placing 1 of 3', { timeout: SHORT });
    const posted = stub.locates.length;
    await byId(page, TID.regionsQueueStop).click();
    await expect(byId(page, TID.regionsQueueStop)).toContainText(/stopping/i);
    stub.hold = false;
    await expect(byId(page, TID.regionsQueue)).toHaveCount(0, { timeout: SHORT });
    expect(stub.locates).toHaveLength(posted); // nothing more went to the wire after the stop
    await expect(byId(page, TID.regionRow)).toHaveCount(3); // the one already placing still landed
  });

  test('Pick files says so in one line when there is no dialog — the typed box stays the door (R38)', async ({
    page,
  }) => {
    await openRegions(page);
    // headless: the dialog route answers 501, and pickOpenFilePaths deliberately has NO prompt
    // fallback (a prompt carries one path, not a list)
    await page.route(/\/api\/dialog\/open-file$/, (r) =>
      json(r, { error: { code: 'unsupported', message: 'no window' } }, 501),
    );
    await byId(page, TID.regionsPickFiles).click();
    const note = byId(page, TID.regionsNoDialog);
    await expect(note).toBeVisible({ timeout: SHORT });
    await expect(note).toContainText(/paste/i);
    await expect(byId(page, TID.regionsQueue)).toHaveCount(0);
    await expect(byId(page, TID.regionsPath)).toBeEnabled();
  });

  // ───────────────────────────────────────────────────────────────────────────────────────────
  // ⭐ R45.7 — WIDER SNAP ON REQUEST. The search width is chosen in plain words and measured on
  // the SCREEN; the default stays exactly what it was (derived from the drag, nothing sent).
  // ───────────────────────────────────────────────────────────────────────────────────────────

  test('R45.7: the snap search is chosen in screen terms — sent only when chosen, and quoted back', async ({
    page,
  }) => {
    const stub = await openRegions(page, { regions: [craftedRegion()] });

    // 1 · default ("nearby"): NO radius rides the wire — the server derives it from the drag —
    //     and the banner says nothing about a width nobody chose
    await byId(page, TID.regionSnap).click();
    await expect.poll(() => stub.snaps.length, { timeout: SHORT }).toBe(1);
    expect((stub.snaps[0] as { radius?: number }).radius ?? null).toBeNull();
    await expect(byId(page, TID.regionSnapBanner)).toContainText('Snapped', { timeout: SHORT });
    await expect(byId(page, TID.regionSnapBanner)).not.toContainText(/searched/i);

    // 2 · "wider": a number goes to the wire — mosaic px, converted from the screen budget at
    //     the current zoom, so the same word means the same gesture at any zoom
    const reach = byId(page, TID.regionSnapReach);
    await expect(reach.locator('[data-reach="nearby"]')).toHaveAttribute('aria-checked', 'true');
    await reach.locator('[data-reach="wider"]').click();
    await expect(reach.locator('[data-reach="wider"]')).toHaveAttribute('aria-checked', 'true');
    await byId(page, TID.regionSnap).click();
    await expect.poll(() => stub.snaps.length, { timeout: SHORT }).toBe(2);
    const wider = (stub.snaps[1] as { radius?: number }).radius;
    expect(typeof wider).toBe('number');
    expect(wider!).toBeGreaterThan(0);

    // …and the banner now quotes the width that was ACTUALLY searched — the server's number
    const echoed = Math.min(wider!, 768);
    await expect(byId(page, TID.regionSnapBanner)).toContainText(`±${echoed} px`, {
      timeout: SHORT,
    });

    // 3 · "far" reaches further than "wider" at the same zoom
    await reach.locator('[data-reach="far"]').click();
    await byId(page, TID.regionSnap).click();
    await expect.poll(() => stub.snaps.length, { timeout: SHORT }).toBe(3);
    const far = (stub.snaps[2] as { radius?: number }).radius;
    expect(far!).toBeGreaterThan(wider!);
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

  test('R46.2: the two measured spacings sit beside the zoom — the evidence, and the note verbatim', async ({
    page,
  }) => {
    await openRegions(page, {
      regions: [craftedRegion({ zoomNote: 'pitch agreed across two stills' })],
    });
    await byId(page, TID.regionEvidenceToggle).click();

    // the actual evidence behind the ratio: the same electrode spacing, in each picture (px, 2 dp)
    await expect(byId(page, TID.regionPitchRecording)).toHaveText('33.30 px');
    await expect(byId(page, TID.regionPitchMosaic)).toHaveText('14.00 px');
    // …and the measurement's own remark, served verbatim
    await expect(byId(page, TID.regionZoomNote)).toHaveText('pitch agreed across two stills');
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

  test('R46.10: stale is said per ROW — a chip on the rows it names, and "Re-place all stale" queues exactly those', async ({
    page,
  }) => {
    const stub = await openRegions(page, {
      stale: true,
      regions: [
        craftedRegion({ id: 'r-1', name: 'field A', stale: true }),
        craftedRegion({ id: 'r-2', name: 'field B', x: 450, y: 340 }),
        craftedRegion({
          id: 'r-3',
          name: 'field C',
          x: 700,
          y: 500,
          stale: true,
          status: 'confirmed',
        }),
      ],
    });

    // 1 · the global banner stays, and the chip names EXACTLY the stale rows — a current-state
    //     warning, on the page (R47.7), not behind a hover
    await expect(byId(page, TID.regionsStale)).toBeVisible();
    await expect(rowOf(page, 'r-1').getByTestId(TID.regionStale)).toBeVisible();
    await expect(rowOf(page, 'r-2').getByTestId(TID.regionStale)).toHaveCount(0);
    await expect(rowOf(page, 'r-3').getByTestId(TID.regionStale)).toBeVisible();

    // 2 · Re-place all stale — the same queue as the multi-add, walking ONLY the stale rows, in
    //     list order, as relocates (no path ever rides: the project owns the videos)
    await expect(byId(page, TID.regionsReplaceStale)).toContainText('(2)');
    await byId(page, TID.regionsReplaceStale).click();
    await expect.poll(() => stub.relocates.length, { timeout: 15_000 }).toBe(2);
    expect(stub.relocates.map((b) => b.region_id)).toEqual(['r-1', 'r-3']);
    expect(stub.locates).toHaveLength(0);

    // 3 · each re-placed row is machine-proposed AGAIN (R46.6) — r-3's confirmation is taken
    //     back — and its chip clears; the row that was never stale is untouched
    await expect(rowOf(page, 'r-1')).toHaveAttribute('data-status', 'unconfirmed', {
      timeout: SHORT,
    });
    await expect(rowOf(page, 'r-3')).toHaveAttribute('data-status', 'unconfirmed');
    await expect(rowOf(page, 'r-1').getByTestId(TID.regionStale)).toHaveCount(0);
    await expect(rowOf(page, 'r-3').getByTestId(TID.regionStale)).toHaveCount(0);
    await expect(byId(page, TID.regionsQueue)).toHaveCount(0);
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

  test('R46.5: the whole tried table is in the fold — order as served, the winner named, a refusal verbatim', async ({
    page,
  }) => {
    await openRegions(page, { regions: [craftedRegion()] });
    await byId(page, TID.regionEvidenceToggle).click();

    // one row per attempt, exactly as served (never re-ranked client-side)
    const rows = byId(page, TID.regionTriedRow);
    await expect(rows).toHaveCount(3);
    await expect(rows.nth(0)).toHaveAttribute('data-still', 'median');
    await expect(rows.nth(1)).toHaveAttribute('data-still', 'max');
    await expect(rows.nth(2)).toHaveAttribute('data-still', 'std');

    // the winner is the record's own still, marked on its row — and only on its row
    await expect(rows.nth(0)).toHaveAttribute('data-winner', 'true');
    await expect(rows.nth(0)).toContainText('won');
    await expect(page.locator(`[data-testid="${TID.regionTriedRow}"][data-winner]`)).toHaveCount(1);

    // scores in the repo's numeric style; the size each attempt ran at
    await expect(rows.nth(0)).toContainText('0.420×');
    await expect(rows.nth(0)).toContainText('0.814');
    await expect(rows.nth(0)).toContainText('0.134');
    await expect(rows.nth(1)).toContainText('0.701');

    // ⛔ a refused attempt keeps the server's sentence, verbatim — that is what the table is FOR
    await expect(rows.nth(2)).toContainText('nothing measurable in this picture');

    // R47.1 — the table scrolls inside the rail; the page itself never grows a horizontal bar
    const noPageScroll = await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    );
    expect(noPageScroll).toBe(true);
  });

  test('R47.4: the pipeline bar says what each step is for', async ({ page }) => {
    await openRegions(page);
    for (const [step, says] of [
      ['survey', /check the video/i],
      ['mosaic', /build the picture/i],
      ['electrodes', /number the pads/i],
      ['regions', /place your recordings/i],
      ['orientation', /settle the chip/i],
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

  test('arrow keys walk the list — no wrap — and Delete asks the row’s own question', async ({
    page,
  }) => {
    const stub = await openRegions(page, {
      regions: [
        craftedRegion({ id: 'r-1', name: 'field A' }),
        craftedRegion({ id: 'r-2', name: 'field B', x: 450, y: 340 }),
      ],
    });

    // 1 · r-1 came auto-selected; ↓ moves to r-2 — a real selection change, so the camera frames
    await expect(rowOf(page, 'r-1')).toHaveAttribute('data-selected', 'true');
    await page.keyboard.press('ArrowDown');
    await expect(rowOf(page, 'r-2')).toHaveAttribute('data-selected', 'true');
    await expect(byId(page, TID.vmViewer)).not.toHaveAttribute('data-fit', 'true');

    // 2 · no wrap at either end
    await page.keyboard.press('ArrowDown');
    await expect(rowOf(page, 'r-2')).toHaveAttribute('data-selected', 'true');
    await page.keyboard.press('ArrowUp');
    await expect(rowOf(page, 'r-1')).toHaveAttribute('data-selected', 'true');
    await page.keyboard.press('ArrowUp');
    await expect(rowOf(page, 'r-1')).toHaveAttribute('data-selected', 'true');

    // 3 · a box that has focus keeps its own arrows — the list must not move underneath typing
    await byId(page, TID.regionsPath).click();
    await page.keyboard.press('ArrowDown');
    await expect(rowOf(page, 'r-1')).toHaveAttribute('data-selected', 'true');
    await byId(page, TID.regionsPath).blur();

    // 4 · Delete asks the SAME question the row's button does — dismissing keeps everything
    let asked = '';
    page.once('dialog', (d) => {
      asked = d.message();
      void d.dismiss();
    });
    await page.keyboard.press('Delete');
    await expect.poll(() => asked, { timeout: SHORT }).toContain('Delete "field A"');
    expect(asked).toContain('cannot be undone');
    await expect(rowOf(page, 'r-1')).toBeVisible();
    expect(stub.deletes).toHaveLength(0);

    // 5 · …and accepting removes it through the same wire as the button
    page.once('dialog', (d) => void d.accept());
    await page.keyboard.press('Delete');
    await expect(rowOf(page, 'r-1')).toHaveCount(0, { timeout: SHORT });
    await expect(byId(page, TID.regionRow)).toHaveCount(1);
    expect(stub.deletes).toEqual(['r-1']);

    // 6 · a long list: the rail (the one scroller, R47.1) keeps the walked-to row visible
    stub.regions = Array.from({ length: 12 }, (_, i) =>
      craftedRegion({ id: `q-${i + 1}`, name: `field ${i + 1}` }),
    );
    await page.reload();
    await expect(byId(page, TID.regionsList)).toBeVisible({ timeout: 15_000 });
    for (let i = 0; i < 11; i++) await page.keyboard.press('ArrowDown');
    await expect(rowOf(page, 'q-12')).toHaveAttribute('data-selected', 'true');
    await expect(rowOf(page, 'q-12')).toBeInViewport();
  });

  test('each row names its file — two recordings renamed alike stay tellable-apart', async ({
    page,
  }) => {
    await openRegions(page, {
      regions: [
        // ⭐ the collision the file name exists to survive: BOTH rows renamed "activity"
        craftedRegion({ id: 'r-1', name: 'activity', sourceName: 'fieldA.avi' }),
        craftedRegion({ id: 'r-2', name: 'activity', sourceName: 'fieldB.avi', x: 450, y: 340 }),
        // an old record with no source block says nothing rather than inventing a name
        craftedRegion({ id: 'r-3', name: 'field C' }),
      ],
    });

    const fileOf = (id: string) => rowOf(page, id).getByTestId(TID.regionFile);
    await expect(fileOf('r-1')).toHaveText('fieldA.avi');
    await expect(fileOf('r-2')).toHaveText('fieldB.avi');
    // the full path waits on hover, so a truncated print is still recoverable
    await expect(fileOf('r-1')).toHaveAttribute('title', 'C:/recordings/session-1/fieldA.avi');
    await expect(fileOf('r-3')).toHaveCount(0);
  });

  test('the runner-up spots are dashed ghosts — for the selected region only, and never the answer', async ({
    page,
  }) => {
    // rank 1 sits exactly at the region's own corner — it IS the placement and must not ghost
    const candidates = [
      { rank: 1, x: 180, y: 140, ncc: 0.8142, npix: 60000, subpixel: true },
      { rank: 2, x: 600, y: 400, ncc: 0.702, npix: 60000, subpixel: false },
      { rank: 3, x: 860, y: 610, ncc: 0.655, npix: 60000, subpixel: false },
    ];
    await openRegions(page, {
      regions: [
        craftedRegion({ id: 'r-1', name: 'field A', candidates }),
        craftedRegion({ id: 'r-2', name: 'field B', x: 450, y: 340 }),
      ],
    });

    // 1 · two ghosts (the winner is not a rival to itself), inert and unmistakable
    const ghosts = byId(page, TID.regionGhost);
    await expect(ghosts).toHaveCount(2);
    await expect(ghosts.first()).toHaveCSS('pointer-events', 'none');
    await expect(ghosts.first()).toContainText('0.702'); // the score, at a zoom with room for it
    await expect(byId(page, TID.regionDrag)).toHaveCount(1); // no ghost grew a drag handle

    // …and the panel says so, in one quiet line
    await expect(byId(page, TID.regionRivals)).toHaveText(/2 rival spots drawn/);

    // 2 · the Fields switch takes the ghosts with everything else
    await byId(page, TID.regionsFieldsToggle).click();
    await expect(ghosts).toHaveCount(0);
    await byId(page, TID.regionsFieldsToggle).click();
    await expect(ghosts).toHaveCount(2);

    // 3 · they belong to the SELECTED region: r-2 has no candidates, so selecting it clears the
    //     stage AND the line — silence, not "no rivals recorded"
    await rowOf(page, 'r-2').click();
    await expect(rowOf(page, 'r-2')).toHaveAttribute('data-selected', 'true');
    await expect(ghosts).toHaveCount(0);
    await expect(byId(page, TID.regionRivals)).toHaveCount(0);
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
