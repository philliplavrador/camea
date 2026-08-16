// ─────────────────────────────────────────────────────────────────────────────────────────────
// ORIENTATION — ⭐ his ruling 2026-08-15: the chip-seating question is its OWN pipeline step after
// Regions, and the four candidates are PICTURES he can pick from by eye, not just a table.
//
// What is proven here is the DOM contract only a browser can fail, in the same stubbed world as
// `regions.spec.ts` (the committed fixtures have no electrode lattice and no MEA recording that
// pairs with a mosaic, so a real project cannot reach this screen at all):
//   • the fifth step exists, says what it is for, and is LOCKED until the document holds a
//     located region — the gate read off the DOCUMENT, never off clicks;
//   • the four seatings render as candidate cards (pictures), clicking one previews it large;
//   • ⭐ "Use this seating" is a HUMAN act: attachMea with confirmed:true and a provenance that
//     says whether he judged by eye or after the test — nothing is ever auto-applied;
//   • 🔴 the test's caveat is on the page VERBATIM (issue 003 / R47.7), the clock's source and
//     the luck bar are said in plain words, each recording gets its own breakdown rows;
//   • ⭐ "cannot tell" is a real outcome with nothing to press, and "none under it" stays a word;
//   • ⛔ without an attachment / a map, the 409 refusal sentence is shown whole.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { Buffer } from 'node:buffer';
import { test, expect, type Page, type Route } from '@playwright/test';
import { SHORT } from './fixture';
import { ROUTES, TID, byId } from './pages';

// ⚠️ Neither "regions" nor "orientation" may appear in the id: it is substituted into route
// patterns, and `…/{id}/…` must never collide with `…/mea/orientation` or `…/regions`.
const ID = 'e2e-seating';
const BUILT_AT = '2026-08-15T09:00:00Z';
const CANVAS = { w: 1200, h: 900 };
const OJOB = 'e2e-seating-job';

/** A 1×1 PNG, so the preview `<img>`s (stage and card thumbnails) genuinely LOAD. */
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC',
  'base64',
);

// ── the crafted world ────────────────────────────────────────────────────────────────────────

/** A located recording, exactly as much of one as this step reads (a rectangle + identity). */
const craftedRegion = (id: string, name: string, x: number, y: number) => ({
  id,
  name,
  source: null,
  still: null,
  x,
  y,
  w: 300,
  h: 220,
  still_kind: 'median',
  zoom: null,
  ncc: 0.8142,
  margin: 0.134,
  margin_thin: false,
  confident: true,
  candidates: [],
  tried: [],
  electrodes: null,
  status: 'unconfirmed',
  placed_by: 'machine',
  located_at: BUILT_AT,
  source_stamp: BUILT_AT,
  moved_px: null,
  snap_margin: null,
  elapsed_ms: 1840,
});

const REGIONS = [craftedRegion('r-1', 'field A', 180, 140), craftedRegion('r-2', 'field B', 450, 340)];

/** The videomosaic document — the ONLY thing the pipeline gate reads (R46.1). */
function craftedDoc(withRegions: boolean) {
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
    source: {
      path: 'C:/videos/survey.avi',
      name: 'survey.avi',
      width: 480,
      height: 320,
      fps: 20,
      n_frames: 200,
      duration_s: 10,
    },
    build: { built_at: BUILT_AT, canvas: CANVAS, outputs: {}, stats: { keyframes_placed: 9 } },
    keyframes: {},
    electrodes: { built_at: BUILT_AT, source_stamp: BUILT_AT, cols: 10, rows: 8, pitch_px: 40 },
    regions: withRegions ? REGIONS : [],
  };
}

const craftedSummary = () => ({
  analysis_id: ID,
  feature: 'videomosaic',
  name: 'seating e2e',
  dataset_key: 'e2e-videomosaic',
  dataset: 'survey',
  path: '',
  folder: '',
  data_dir: '',
  created: BUILT_AT,
  modified: BUILT_AT,
  bytes: 4096,
});

/** The mapped lattice: a 10 × 8 grid, 40 px pitch, origin (100,100) — where every `col-row`
 *  the footprint names must resolve to a mosaic-px centre. */
function craftedEmap() {
  const col: number[] = [];
  const row: number[] = [];
  const x: number[] = [];
  const y: number[] = [];
  const kind: number[] = [];
  for (let r = 1; r <= 8; r++) {
    for (let c = 1; c <= 10; c++) {
      col.push(c);
      row.push(r);
      x.push(100 + (c - 1) * 40);
      y.push(100 + (r - 1) * 40);
      kind.push(1);
    }
  }
  return {
    cols: 10,
    rows: 8,
    pitch_px: 40,
    angle_deg: 0,
    hit_radius_px: 12,
    a1: [40, 0],
    a2: [0, 40],
    canvas_offset: [0, 0],
    coordinates: 'canvas',
    built_at: BUILT_AT,
    stale: false,
    stats: {},
    um_per_px: null,
    device: null,
    array_coverage: 'partial',
    cells: { col, row, x, y, kind },
  };
}

/** The four seatings' footprints — GEOMETRY only, exactly what the new GET serves. */
function craftedFootprint() {
  const region = (covered: [number, number]) => [
    { region_id: 'r-1', region_name: 'field A', n_region: 12, n_covered: covered[0] },
    { region_id: 'r-2', region_name: 'field B', n_region: 9, n_covered: covered[1] },
  ];
  return {
    analysis_id: ID,
    run_id: '000690',
    cols: 10,
    rows: 8,
    stride: 220,
    n_routed: 6,
    orientation: { flip_x: false, flip_y: false, confirmed: false, source: '' },
    seatings: [
      {
        flip_x: false,
        flip_y: false,
        electrodes: ['3-2', '4-2', '5-2', '3-3', '4-3', '5-3'],
        n_recorded: 6,
        regions: region([6, 3]),
      },
      {
        flip_x: true,
        flip_y: false,
        electrodes: ['3-6', '4-6', '5-6'],
        n_recorded: 3,
        regions: region([0, 0]),
      },
      {
        flip_x: false,
        flip_y: true,
        electrodes: ['6-2', '7-2', '8-2'],
        n_recorded: 3,
        regions: region([0, 0]),
      },
      {
        flip_x: true,
        flip_y: true,
        electrodes: ['6-6', '7-6', '8-6'],
        n_recorded: 3,
        regions: region([0, 0]),
      },
    ],
  };
}

// ── the test results the job can come back with ──────────────────────────────────────────────

const CAVEAT_TTL =
  'This ranking rests on a clock alignment that has not been validated end to end — ' +
  'read it as evidence to weigh, never as a verdict.';
const CAVEAT_LAMP =
  'The clock alignment leans on the 2P-lamp marks, and those did not survive checking ' +
  'against the calcium video — the correlations below cannot be taken at face value.';

const seatingRows = (correlations: (number | null)[]) =>
  [
    { flip_x: false, flip_y: false },
    { flip_x: true, flip_y: false },
    { flip_x: false, flip_y: true },
    { flip_x: true, flip_y: true },
  ].map((f, i) => ({ ...f, correlation: correlations[i] }));

/** Decided by coverage: only as-is puts recorded pads under the fields (the strong, geometric case). */
function decisiveResult() {
  const corr = [0.412, null, null, null];
  return {
    kind: 'mea_orientation',
    analysis_id: ID,
    run_id: '000690',
    region_id: '',
    region_name: '',
    scores: seatingRows(corr).map((s, i) => ({
      ...s,
      n_recorded: i === 0 ? 9 : 0,
      n_region: 21,
      coverage: i === 0 ? 0.43 : 0,
      n_spikes: i === 0 ? 5231 : 0,
      scorable: i === 0,
    })),
    regions: [
      {
        region_id: 'r-1',
        region_name: 'field A',
        n_region: 12,
        offset_s: 11.7,
        alignment_quality: 0.65,
        seatings: seatingRows([0.412, null, null, null]).map((s, i) => ({
          ...s,
          n_recorded: i === 0 ? 6 : 0,
        })),
      },
      {
        region_id: 'r-2',
        region_name: 'field B',
        n_region: 9,
        offset_s: 11.9,
        alignment_quality: 0.61,
        seatings: seatingRows([0.388, null, null, null]).map((s, i) => ({
          ...s,
          n_recorded: i === 0 ? 3 : 0,
        })),
      },
    ],
    best: { flip_x: false, flip_y: false, confirmed: false, source: '' },
    decisive: true,
    decided_by: 'coverage',
    margin: null,
    chance_level: 0.213,
    beats_chance: true,
    offset_s: 11.7,
    alignment_quality: 0.65,
    alignment_source: 'ttl',
    caveat: CAVEAT_TTL,
  };
}

/** The P003693 shape: every seating testable, all four within noise — no winner exists. */
function cannotTellResult() {
  const corr = [0.414, 0.412, 0.411, 0.41];
  return {
    ...decisiveResult(),
    scores: seatingRows(corr).map((s) => ({
      ...s,
      n_recorded: 21,
      n_region: 21,
      coverage: 1,
      n_spikes: 5231,
      scorable: true,
    })),
    regions: [],
    best: null,
    decisive: false,
    decided_by: '',
    margin: 0.002,
    chance_level: 0.31,
    beats_chance: false,
    alignment_source: 'lamp',
    caveat: CAVEAT_LAMP,
  };
}

// ── the stub ─────────────────────────────────────────────────────────────────────────────────

interface Stub {
  /** The saved attachment's orientation — a Use click round-trips through here. */
  orientation: { flip_x: boolean; flip_y: boolean; confirmed: boolean; source: string };
  /** ⛔ When set, the footprint GET refuses with this sentence (409) — no MEA / no map. */
  refuse: string | null;
  /** What the orientation job's terminal poll serves. */
  result: Record<string, unknown>;
  /** Every attach body that reached the wire — the human confirms under test. */
  attaches: Record<string, unknown>[];
}

interface OpenOpts {
  withRegions?: boolean;
  refuse?: string | null;
}

const json = (route: Route, body: unknown, status = 200): Promise<void> =>
  route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

async function openPipeline(page: Page, opts: OpenOpts = {}): Promise<Stub> {
  const stub: Stub = {
    orientation: { flip_x: false, flip_y: false, confirmed: false, source: '' },
    refuse: opts.refuse ?? null,
    result: decisiveResult(),
    attaches: [],
  };
  const doc = craftedDoc(opts.withRegions ?? true);
  const vm = ROUTES.videomosaic;

  const attachment = () => ({
    attached: true,
    mea_dir: 'C:/mea',
    recordings: [
      { run_id: '000690', assay: 'Network', label: 'Network/000690', path: 'C:/mea/Network/000690' },
    ],
    stride: 220,
    pitch_um: 17.5,
    orientation: stub.orientation,
    decoder_present: false,
  });

  await page.route(new RegExp(`${ROUTES.projects}/${ID}$`), (r) => json(r, craftedSummary()));
  await page.route(new RegExp(`${ROUTES.document}/${ID}/document$`), (r) => json(r, { doc }));
  await page.route(new RegExp(`${ROUTES.projects}/${ID}/outputs$`), (r) => json(r, { outputs: [] }));
  const png = (r: Route): Promise<void> => r.fulfill({ contentType: 'image/png', body: PNG });
  await page.route(new RegExp(`${ROUTES.projects}/${ID}/outputs/[^/]+`), png);
  await page.route(new RegExp(`${vm}/${ID}/outputs/[^/]+`), png);
  await page.route(new RegExp(`${ROUTES.jobs}$`), (r) => json(r, { jobs: [] }));
  await page.route(new RegExp(`${vm}/${ID}/electrodes$`), (r) => json(r, craftedEmap()));
  await page.route(new RegExp(`${vm}/${ID}/regions$`), (r) =>
    json(r, {
      analysis_id: ID,
      regions: doc.regions,
      built_from: BUILT_AT,
      stale: false,
      outputs: {},
    }),
  );

  // the electrical half: the attachment, the footprint, the confirm, the test job
  await page.route(new RegExp(`${vm}/${ID}/mea$`), (r) => json(r, attachment()));

  await page.route(new RegExp(`${vm}/mea/footprint`), async (route) => {
    if (stub.refuse) {
      await json(route, { error: { code: 'refused', message: stub.refuse } }, 409);
      return;
    }
    await json(route, craftedFootprint());
  });

  await page.route(new RegExp(`${vm}/mea/attach$`), async (route, req) => {
    const body = req.postDataJSON() as {
      orientation?: Stub['orientation'] | null;
    };
    stub.attaches.push(body as unknown as Record<string, unknown>);
    if (body.orientation) stub.orientation = body.orientation;
    await json(route, attachment());
  });

  await page.route(new RegExp(`${vm}/mea/orientation$`), (r) =>
    json(r, { job_id: OJOB, kind: 'mea_orientation', state: 'queued' }, 202),
  );
  await page.route(new RegExp(`${ROUTES.jobs}/${OJOB}$`), (r) =>
    json(r, {
      job_id: OJOB,
      kind: 'mea_orientation',
      state: 'done',
      pct: 100,
      result: stub.result,
    }),
  );

  await page.goto(`/project/${ID}`);
  await expect(byId(page, TID.pipelineSteps)).toBeVisible({ timeout: 15_000 });
  return stub;
}

const cardOf = (page: Page, flipX: boolean, flipY: boolean) =>
  page.locator(
    `[data-testid="${TID.orientationCard}"][data-flip-x="${flipX}"][data-flip-y="${flipY}"]`,
  );

// ─────────────────────────────────────────────────────────────────────────────────────────────
test.describe('orientation — the chip-seating step (his ruling 2026-08-15)', () => {
  test('the fifth step is LOCKED until the document holds a located region — and says what it is for', async ({
    page,
  }) => {
    await openPipeline(page, { withRegions: false });

    // the gate is the DOCUMENT: everything up to Regions is earned, Orientation is not
    const btn = byId(page, TID.pipelineStep('orientation'));
    await expect(btn).toHaveAttribute('data-locked', 'true');
    await expect(byId(page, TID.pipelineAction('orientation'))).toHaveText(/settle the chip/i);

    // ⛔ clicking the locked step does NOT navigate (force: aria-disabled, not disabled — see
    // regions.spec.ts for why the click must really dispatch)
    await btn.click({ force: true });
    await expect(byId(page, TID.toast)).toContainText(/finish the step/i, { timeout: SHORT });
    await expect(byId(page, TID.orientationStep)).toHaveCount(0);

    // …and the Regions rail offers no way on either: the button tracks the same gate
    await expect(byId(page, TID.vmToOrientation)).toHaveCount(0);
  });

  test('with a region on file it OPENS on Orientation: four candidates, as pictures', async ({
    page,
  }) => {
    await openPipeline(page);

    // the furthest earned step is this one
    await expect(byId(page, TID.orientationStep)).toBeVisible({ timeout: SHORT });
    await expect(byId(page, TID.pipelineStep('orientation'))).toHaveAttribute(
      'data-active',
      'true',
    );

    // ⭐ four cards, each a PICTURE (the mosaic thumbnail really loads under the dots)
    const cards = byId(page, TID.orientationCard);
    await expect(cards).toHaveCount(4);
    for (const name of ['as-is', 'flipped top–bottom', 'flipped left–right']) {
      await expect(byId(page, TID.orientationCards)).toContainText(name);
    }
    const thumb = cards.first().locator('img');
    await expect
      .poll(() => thumb.evaluate((el) => (el as HTMLImageElement).naturalWidth), {
        timeout: SHORT,
      })
      .toBeGreaterThan(0);

    // the per-recording coverage is geometry, and ZERO is a word, not a number
    await expect(cardOf(page, false, false)).toContainText('field A: 6 of 12 pads');
    await expect(cardOf(page, true, false)).toContainText('field A: none of 12 pads');

    // before any click the big picture previews as-is, and says so
    await expect(cardOf(page, false, false)).toHaveAttribute('data-previewed', 'true');
    await expect(byId(page, TID.orientationFootprint)).toHaveAttribute('data-flip-x', 'false');
    await expect(byId(page, TID.orientationFootprint)).toHaveAttribute('data-flip-y', 'false');

    // nothing is settled, so identity is declared provisional (not silently fine)
    await expect(byId(page, TID.orientationSettled)).toHaveCount(0);

    // …and the pipeline is WALKED, not only clicked: the Regions rail offers the way on
    await byId(page, TID.pipelineStep('regions')).click();
    await expect(byId(page, TID.regionsStep)).toBeVisible({ timeout: SHORT });
    await byId(page, TID.vmToOrientation).click();
    await expect(byId(page, TID.orientationStep)).toBeVisible({ timeout: SHORT });
  });

  test('clicking a card previews THAT seating on the big picture', async ({ page }) => {
    await openPipeline(page);
    await expect(byId(page, TID.orientationCard)).toHaveCount(4);

    await cardOf(page, true, false).click();
    await expect(cardOf(page, true, false)).toHaveAttribute('data-previewed', 'true');
    await expect(cardOf(page, false, false)).not.toHaveAttribute('data-previewed', 'true');
    await expect(byId(page, TID.orientationFootprint)).toHaveAttribute('data-flip-x', 'true');
    await expect(byId(page, TID.orientationFootprint)).toHaveAttribute('data-flip-y', 'false');
  });

  test('⭐ Use this seating is the HUMAN confirm — by eye, provenance and all, and reversible', async ({
    page,
  }) => {
    const stub = await openPipeline(page);
    await expect(byId(page, TID.orientationCard)).toHaveCount(4);

    // 1 · his click, and exactly what it must carry: confirmed BY HIM, from the pictures
    await cardOf(page, true, false).getByTestId(TID.orientationUse).click();
    await expect.poll(() => stub.attaches.length, { timeout: SHORT }).toBe(1);
    expect(stub.attaches[0]).toMatchObject({
      analysis_id: ID,
      confirm: true,
      orientation: {
        flip_x: true,
        flip_y: false,
        confirmed: true,
        source: 'chosen by you by eye from the pictures',
      },
    });

    // 2 · the settled state is shown, with its provenance, and the card wears the badge
    const settled = byId(page, TID.orientationSettled);
    await expect(settled).toBeVisible({ timeout: SHORT });
    await expect(settled).toContainText('flipped top–bottom');
    await expect(settled).toContainText('chosen by you by eye from the pictures');
    await expect(cardOf(page, true, false).getByTestId(TID.orientationSettledBadge)).toBeVisible();

    // 3 · ⭐ he can change his mind — picking another card RE-confirms with the new seating
    await cardOf(page, false, false).getByTestId(TID.orientationUse).click();
    await expect.poll(() => stub.attaches.length, { timeout: SHORT }).toBe(2);
    expect(stub.attaches[1]).toMatchObject({
      confirm: true,
      orientation: { flip_x: false, flip_y: false, confirmed: true },
    });
    await expect(settled).toContainText('as-is');
  });

  test('🔴 the test: caveat VERBATIM on the page, the clock and the luck bar in plain words, each recording alone', async ({
    page,
  }) => {
    const stub = await openPipeline(page);
    await expect(byId(page, TID.orientationCard)).toHaveCount(4);

    await byId(page, TID.orientationTest).click();

    // 1 · the caveat — whole, on the page, never behind a `?` (issue 003 / R47.7)
    const caveat = byId(page, TID.orientationCaveat);
    await expect(caveat).toBeVisible({ timeout: SHORT });
    await expect(caveat).toContainText(CAVEAT_TTL);

    // 2 · what the clock rested on, and what luck alone can score — plain words, real numbers
    await expect(byId(page, TID.orientationAlignment)).toContainText(/rig.s own time-stamp/i);
    const chance = byId(page, TID.orientationChance);
    await expect(chance).toContainText('0.213');
    await expect(chance).toContainText(/luck/i);
    await expect(chance).toContainText(/5%/);

    // 3 · the table: the winner highlighted, the untestable seatings a WORD, never a number
    const scores = byId(page, TID.orientationScores);
    await expect(scores).toBeVisible();
    await expect(scores).toContainText('0.412');
    await expect(scores).toContainText('none under it');

    // 4 · ⭐ each recording alone — two blocks, each naming its field with its own four rows
    const rows = byId(page, TID.orientationRegionRows);
    await expect(rows).toHaveCount(2);
    await expect(rows.first()).toContainText('field A');
    await expect(rows.last()).toContainText('field B');
    await expect(rows.last()).toContainText('0.388');

    // 5 · the verdict is geometry, said so — and the winner's card wears a QUIET badge
    await expect(byId(page, TID.orientationVerdict)).toContainText(/geometry/i);
    await expect(
      cardOf(page, false, false).getByTestId(TID.orientationWinnerBadge),
    ).toBeVisible();
    await expect(byId(page, TID.orientationWinnerBadge)).toHaveCount(1);

    // 6 · applying the test's winner is the SAME human click, with the test's provenance
    await cardOf(page, false, false).getByTestId(TID.orientationUse).click();
    await expect.poll(() => stub.attaches.length, { timeout: SHORT }).toBe(1);
    expect(stub.attaches[0]).toMatchObject({
      confirm: true,
      orientation: {
        flip_x: false,
        flip_y: false,
        confirmed: true,
        source: 'confirmed by you after the seating test',
      },
    });
  });

  test('⭐ cannot tell is a real outcome — said plainly, with nothing to press', async ({
    page,
  }) => {
    const stub = await openPipeline(page);
    stub.result = cannotTellResult();
    await expect(byId(page, TID.orientationCard)).toHaveCount(4);

    await byId(page, TID.orientationTest).click();

    const undecided = byId(page, TID.orientationUndecided);
    await expect(undecided).toBeVisible({ timeout: SHORT });
    await expect(undecided).toContainText(/cannot tell/i);
    await expect(undecided).toContainText(/nothing has been applied/i);

    // the caveat still stands over the numbers — the lamp wording this time
    await expect(byId(page, TID.orientationCaveat)).toContainText(CAVEAT_LAMP);
    // …and the luck bar reports the winner does NOT clear it
    await expect(byId(page, TID.orientationChance)).toContainText(/NOT above/);

    // ⛔ no winner is crowned anywhere: no badge, no verdict
    await expect(byId(page, TID.orientationWinnerBadge)).toHaveCount(0);
    await expect(byId(page, TID.orientationVerdict)).toHaveCount(0);
    // (the by-eye cards stay — they are HIS judgement, not the test's)
    await expect(byId(page, TID.orientationUse)).toHaveCount(4);
  });

  test('⛔ without the electrical half the refusal is shown whole — an instruction, not a code', async ({
    page,
  }) => {
    const SENTENCE =
      'attach the MEA recording first — without it there is nothing to say which electrodes were recorded';
    await openPipeline(page, { refuse: SENTENCE });

    await expect(byId(page, TID.orientationStep)).toBeVisible({ timeout: SHORT });
    const refusal = byId(page, TID.orientationRefusal);
    await expect(refusal).toBeVisible({ timeout: SHORT });
    await expect(refusal).toContainText(SENTENCE);

    // no cards and no test to press — the sentence IS the screen's instruction
    await expect(byId(page, TID.orientationCard)).toHaveCount(0);
    await expect(byId(page, TID.orientationTest)).toHaveCount(0);
  });
});
