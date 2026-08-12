// ─────────────────────────────────────────────────────────────────────────────
// Electrodes — the optional post-build mapping + click-to-identify (2026-08-11).
//
// The committed fixture is deliberately GRIDLESS (its texture must never fake an electrode
// array — the API suite asserts mapping it REFUSES), so the map payload here is CRAFTED and
// served by a route stub — the same philosophy as `stubMatchAnchor`/`stubScreenPropose`:
// the UI is tested on deterministic input; the real fit is proven by
// `tests/unit/test_electrodegrid.py` + `tests/api/test_electrodes.py` against planted
// lattices with answer keys, and was audited on the real 120×220 MaxWell mosaics.
//
// Placed tiles come from the app's own durable save route (PUT document), because the
// 10-tile gridless fixture cannot honestly produce placements for this screen any other
// fast way — the UI under test starts at the reload, exactly as a user reopening his
// project would.
// ─────────────────────────────────────────────────────────────────────────────

import { test, expect, type Page } from '@playwright/test';
import { SHORT } from './fixture';
import { ROUTES, TID, Wizard, byId, enterMosaic } from './pages';

const PITCH = 14;
const HIT_RADIUS = 6; // crafted: generous (< half-pitch) so the probe-click below is robust
const PITCH_UM = 17.5; // the MaxWell pitch — the ONE device number the crafted payload mirrors

interface MapOpts {
  stale?: boolean;
  /** R45.8 — what the user declared about the picture; "full" also carries a device + a correction. */
  coverage?: 'full' | 'partial';
  /**
   * ⭐ A MAP WRITTEN BEFORE R45.8 (review finding #4): no `device`, no `um_per_px`, no per-cell µm.
   * The readout must then promise NO pitch and NO scale — the defect was prose that said "only its
   * 17.5 µm pitch, which is what sets the µm scale below" over exactly this payload.
   */
  device?: boolean;
}

/** A crafted ElectrodeMapPayload: an axis-aligned lattice covering the anchored tiles' world. */
function craftedMap({ stale = false, coverage = 'partial', device = true }: MapOpts = {}) {
  const cols = 36;
  const rows = 62;
  const col: number[] = [];
  const row: number[] = [];
  const x: number[] = [];
  const y: number[] = [];
  const kind: number[] = [];
  // R45.8 — the µm are the MEASURED centres carried into the array's own frame (x along columns,
  // y along rows, rotation out, origin at 1-1). This lattice is axis-aligned and exact, so they are
  // exactly (col−1)·17.5; a real fit lands near that and keeps the deviation.
  const x_um: number[] = [];
  const y_um: number[] = [];
  for (let r = 1; r <= rows; r++) {
    for (let c = 1; c <= cols; c++) {
      col.push(c);
      row.push(r);
      x.push(7 + (c - 1) * PITCH);
      y.push(7 + (r - 1) * PITCH);
      kind.push(c === 5 && r === 5 ? 2 : 1); // one inferred cell so data-kind is exercised
      x_um.push(Number(((c - 1) * PITCH_UM).toFixed(2)));
      y_um.push(Number(((r - 1) * PITCH_UM).toFixed(2)));
    }
  }
  return {
    cols,
    rows,
    pitch_px: PITCH,
    angle_deg: 0,
    hit_radius_px: HIT_RADIUS,
    a1: [PITCH, 0],
    a2: [0, PITCH],
    canvas_offset: [0, 0],
    coordinates: null,
    built_at: '2026-08-11T00:00:00Z',
    stale,
    stats: {
      n_detected: cols * rows - 1,
      n_inferred: 1,
      ...(device ? { um_per_px: PITCH_UM / PITCH } : {}),
      // Only a "full" fit is ever enforced, so only it can report a correction — and when it does,
      // the panel MUST say so (a line added OR dropped before column 1 renumbers the whole array).
    },
    // Everything the device supplies is absent together — that is what a pre-R45.8 map looks like,
    // and the readout must degrade to pixels rather than to a remembered pitch.
    ...(device
      ? {
          um_per_px: PITCH_UM / PITCH,
          device: {
            name: 'MaxWell MaxOne/MaxTwo',
            axes: [120, 220],
            pitch_um: PITCH_UM,
            electrodes: 26400,
          },
        }
      : {}),
    array_coverage: coverage,
    cells: device ? { col, row, x, y, kind, x_um, y_um } : { col, row, x, y, kind },
  };
}

/** Create a fixture project, anchor 4 tiles at the truth offsets via the durable save, reload. */
async function projectWithAnchors(page: Page): Promise<Wizard> {
  const { wizard } = await enterMosaic(page);
  await expect
    .poll(() => wizard.isLocked('electrodes'), { timeout: SHORT })
    .toBe(true); // gated until something is placed — same gate as Mosaic

  const m = /\/project\/([^/?#]+)/.exec(page.url());
  if (!m) throw new Error(`not in a project URL: ${page.url()}`);
  const id = m[1];

  const got = await page.request.get(`/api/analyses/${id}/document`);
  expect(got.ok()).toBeTruthy();
  const doc = (await got.json()).doc;
  for (let i = 0; i < 4; i++) {
    const trial = String(11 + i);
    doc.tiles[trial] = {
      ...doc.tiles[trial],
      state: 'anchored',
      status: 'anchor',
      x: 0,
      y: i * 128, // the fixture's own serpentine step
      human: true,
    };
  }
  const put = await page.request.put(`/api/analyses/${id}/document`, { data: { doc } });
  expect(put.ok()).toBeTruthy();

  await page.goto(`/project/${id}`);
  const w = new Wizard(page);
  await expect(byId(page, TID.wizard)).toBeVisible({ timeout: 15_000 });
  await expect.poll(() => w.isLocked('electrodes'), { timeout: 15_000 }).toBe(false);
  return w;
}

// ─────────────────────────────────────────────────────────────────────────────
// ⭐ THE DEVICE COMES OFF THE WIRE (`GET /api/electrodes/device`), so the UI cannot hold a second,
// drifting copy of the numbers the FITTER enforces (the 2026-08-11 review, finding #1).
//
// The stub below is DELIBERATELY NOT MaxWell. If the coverage question still says "220 × 120 =
// 26,400" while the served spec says 7 × 5 = 35, the numbers were retyped in TypeScript and the test
// is doing its job — that is exactly the drift this endpoint exists to close.
// ─────────────────────────────────────────────────────────────────────────────
const FAKE_DEVICE = {
  name: 'Bench Rig MicroArray',
  axes: [5, 7], //      ORIENTATION-FREE by contract; the UI reads it long side first → "7 × 5"
  pitch_um: 3.5,
  electrodes: 35,
} as const;

/** Serve a device spec — or, with `null`, make the endpoint FAIL (the choice must still work). */
async function stubDevice(page: Page, spec: typeof FAKE_DEVICE | null) {
  await page.route(`**${ROUTES.electrodeDevice}`, async (route) => {
    if (spec == null) {
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ error: { code: 'unavailable', message: 'no spec today' } }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(spec),
    });
  });
}

async function stubMap(page: Page, opts: MapOpts = {}) {
  await page.route(`**${ROUTES.electrodes}/*`, async (route, req) => {
    if (req.method() !== 'GET') return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(craftedMap(opts)),
    });
  });
}

/** Click around `at` on a small probe grid until an electrode is selected (a blind single
 *  click can honestly land in a gap — the gap MUST miss, that is the click rule). */
async function clickUntilSelected(page: Page, cx: number, cy: number): Promise<string> {
  const canvas = byId(page, TID.electrodesCanvas);
  for (let dy = 0; dy <= 12; dy += 4) {
    for (let dx = 0; dx <= 12; dx += 4) {
      await canvas.click({ position: { x: cx + dx, y: cy + dy } });
      try {
        await expect(byId(page, TID.electrodeId)).toBeVisible({ timeout: 250 });
        return (await byId(page, TID.electrodeId).innerText()).trim();
      } catch {
        /* a gap — probe on */
      }
    }
  }
  throw new Error('no electrode selected on a 4x4 probe grid — lookup or overlay broken');
}

const parseId = (s: string): [number, number] => {
  const m = /(\d+)-(\d+)/.exec(s);
  if (!m) throw new Error(`not an electrode id: "${s}"`);
  return [Number(m[1]), Number(m[2])];
};

test.describe('electrodes — click-to-identify', () => {
  test('click selects, arrows step the grid, Esc clears, gaps miss', async ({ page }) => {
    const wizard = await projectWithAnchors(page);
    await stubMap(page);
    await wizard.goto('electrodes');
    await expect(byId(page, TID.electrodesViewer)).toBeVisible({ timeout: SHORT });
    await expect(byId(page, TID.electrodePanel)).toBeVisible({ timeout: SHORT });

    const canvas = byId(page, TID.electrodesCanvas);
    const box = await canvas.boundingBox();
    if (!box) throw new Error('electrodes canvas has no box');

    // 1 · a click near the middle selects an electrode; readout + marker agree
    const id0 = await clickUntilSelected(page, box.width / 2, box.height / 2);
    const [c0, r0] = parseId(id0);
    expect(c0).toBeGreaterThanOrEqual(1);
    expect(r0).toBeGreaterThanOrEqual(1);
    const marker = byId(page, TID.electrodeMarker);
    await expect(marker).toBeVisible();
    expect(await marker.getAttribute('data-electrode')).toBe(`${c0}-${r0}`);

    // 2 · arrow keys step along the GRID (his misclick-recovery rule)
    const m0 = await marker.boundingBox();
    await page.keyboard.press('ArrowRight');
    await expect(byId(page, TID.electrodeId)).toHaveText(new RegExp(`\\b${c0 + 1}-${r0}\\b`));
    const m1 = await marker.boundingBox();
    await page.keyboard.press('ArrowDown');
    await expect(byId(page, TID.electrodeId)).toHaveText(new RegExp(`\\b${c0 + 1}-${r0 + 1}\\b`));
    await page.keyboard.press('ArrowLeft');
    await page.keyboard.press('ArrowUp');
    await expect(byId(page, TID.electrodeId)).toHaveText(new RegExp(`\\b${c0}-${r0}\\b`));

    // 3 · a click on the four-corner point between pads selects NOTHING (deselects)
    if (!m0 || !m1) throw new Error('marker box missing');
    const scaledPitch = m1.x + m1.width / 2 - (m0.x + m0.width / 2); // one grid step on screen
    expect(scaledPitch).toBeGreaterThan(3);
    const mNow = await marker.boundingBox();
    if (!mNow) throw new Error('marker box missing');
    await canvas.click({
      position: {
        x: mNow.x + mNow.width / 2 - box.x + scaledPitch / 2,
        y: mNow.y + mNow.height / 2 - box.y + scaledPitch / 2,
      },
    });
    await expect(marker).toBeHidden();

    // 4 · Esc after a fresh selection clears it (NOT the sweep's Esc — R14 untouched)
    await clickUntilSelected(page, box.width / 2, box.height / 2);
    await page.keyboard.press('Escape');
    await expect(marker).toBeHidden();

    // 5 · the IDs overlay is a toggle, off by default
    const toggle = byId(page, TID.electrodeIdsToggle);
    await expect(toggle).toHaveAttribute('aria-checked', 'false');
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-checked', 'true');
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-checked', 'false');
  });

  // R45.7 — the tolerance is a distance ON SCREEN. Zoomed out, an electrode is a couple of pixels
  // and his strict pad+margin disc is sub-pixel: measured on his real 120×220 map at fit, only 24 %
  // of clicks resolved, and because the miss depends on sub-pixel phase it failed in BANDS ("there
  // are missing patches"). So the radius grows as the camera pulls back — never past the cell, so
  // the answer is still the electrode pointed at, never its neighbour.
  test('R45.7: zoomed out a click still lands; at 1:1 the gaps still select nothing', async ({
    page,
  }) => {
    const wizard = await projectWithAnchors(page);
    await stubMap(page);
    await wizard.goto('electrodes');
    const canvas = byId(page, TID.electrodesCanvas);
    const box = await canvas.boundingBox();
    if (!box) throw new Error('electrodes canvas has no box');
    const marker = byId(page, TID.electrodeMarker);

    /** The midpoint between the selected pad and its right-hand neighbour, in page coords. */
    const gapPoint = async (): Promise<{ x: number; y: number }> => {
      await clickUntilSelected(page, box.width / 2, box.height / 2);
      const a = await marker.boundingBox();
      await page.keyboard.press('ArrowRight');
      const b = await marker.boundingBox();
      if (!a || !b) throw new Error('marker box missing');
      return {
        x: (a.x + a.width / 2 + b.x + b.width / 2) / 2 - box.x,
        y: (a.y + a.height / 2 + b.y + b.height / 2) / 2 - box.y,
      };
    };

    // 1:1 — half a pitch from either centre is a gap, and a gap selects NOTHING (his rule intact).
    await page.keyboard.press('0');
    const gap = await gapPoint();
    await canvas.click({ position: gap });
    await expect(marker).toBeHidden();

    // Pulled back far enough that a pad is a few pixels across, the SAME point resolves — to one of
    // the two pads it sits between, never a third.
    for (let i = 0; i < 6; i++) await page.keyboard.press('-');
    const far = await gapPoint();
    const idBefore = (await byId(page, TID.electrodeId).innerText()).trim();
    const [c1, r1] = parseId(idBefore); // the ArrowRight neighbour
    await canvas.click({ position: far });
    await expect(marker).toBeVisible();
    const got = await marker.getAttribute('data-electrode');
    expect([`${c1}-${r1}`, `${c1 - 1}-${r1}`]).toContain(got);
  });

  test('a stale map says so', async ({ page }) => {
    const wizard = await projectWithAnchors(page);
    await stubMap(page, { stale: true });
    await wizard.goto('electrodes');
    await expect(byId(page, TID.electrodesViewer)).toBeVisible({ timeout: SHORT });
    await expect(byId(page, TID.electrodeStale)).toBeVisible({ timeout: SHORT });
    // the affordance to fix it is right there
    await expect(byId(page, TID.electrodesMap)).toBeVisible();
  });

  test('without a map, the step offers Map electrodes and no readout', async ({ page }) => {
    const wizard = await projectWithAnchors(page);
    // no stub: the real backend answers 404 (this project has no map)
    await wizard.goto('electrodes');
    await expect(byId(page, TID.electrodesViewer)).toBeVisible({ timeout: SHORT });
    await expect(byId(page, TID.electrodesMap)).toBeVisible({ timeout: SHORT });
    // ⭐ R45.8 — VISIBLE BUT DEAD until he says what the picture contains.
    await expect(byId(page, TID.electrodesMap)).toBeDisabled();
    await expect(byId(page, TID.electrodeId)).toBeHidden();
  });

  // ─────────────────────────────────────────────────────────────────────────────
  // R45.8 — THE DEVICE SPEC, AND WHETHER THE WHOLE CHIP IS IN FRAME (2026-08-11).
  //
  //   "the standard MaxOne/MaxTwo sensor area is 26,400 electrodes = 220 x 120, with 17.5 um pitch"
  //   "Allow the user to select if it's a partially imaged or fully imaged before allowing them to
  //    map electrodes."
  //
  // The app now carries DEVICE knowledge — but only because HE supplies it by declaring the whole
  // chip imaged. The lattice is still measured from the pixels; the spec only checks and completes
  // the result. So the question must be asked, it must have no default, and both its answers must
  // reach the wire.
  // ─────────────────────────────────────────────────────────────────────────────

  test('R45.8: Map electrodes is dead until the coverage question is answered, and the answer travels', async ({
    page,
  }) => {
    const wizard = await projectWithAnchors(page);
    await wizard.goto('electrodes');
    await expect(byId(page, TID.electrodesViewer)).toBeVisible({ timeout: SHORT });

    const mapBtn = byId(page, TID.electrodesMap);
    const full = byId(page, TID.electrodeCoverageFull);
    const partial = byId(page, TID.electrodeCoveragePartial);

    // 1 · the question is on the page, unanswered — NEITHER option is pressed, and the button is dead
    await expect(byId(page, TID.electrodeCoverage)).toBeVisible({ timeout: SHORT });
    await expect(full).toHaveAttribute('aria-pressed', 'false');
    await expect(partial).toHaveAttribute('aria-pressed', 'false');
    await expect(mapBtn).toBeDisabled();

    // 2 · answering enables it, and exactly one segment reads pressed
    await full.click();
    await expect(full).toHaveAttribute('aria-pressed', 'true');
    await expect(partial).toHaveAttribute('aria-pressed', 'false');
    await expect(mapBtn).toBeEnabled();

    // 3 · the answer is what reaches the backend — `array_coverage` on the map request. The POST is
    //     answered 409 (the honest "gpu lease is busy" refusal) so no real fit is started here.
    const bodies: Array<Record<string, unknown>> = [];
    await page.route(`**${ROUTES.electrodes}/map`, async (route, req) => {
      bodies.push(req.postDataJSON() as Record<string, unknown>);
      await route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({ error: { code: 'busy', message: 'the gpu lease is held' } }),
      });
    });
    await mapBtn.click();
    await expect.poll(() => bodies.length, { timeout: SHORT }).toBe(1);
    expect(bodies[0].array_coverage).toBe('full');

    // 4 · the other answer travels too — and re-answering swaps the pressed segment
    await partial.click();
    await expect(full).toHaveAttribute('aria-pressed', 'false');
    await expect(partial).toHaveAttribute('aria-pressed', 'true');
    await mapBtn.click();
    await expect.poll(() => bodies.length, { timeout: SHORT }).toBe(2);
    expect(bodies[1].array_coverage).toBe('partial');
  });

  test('R45.8: the readout carries µm, the scale, the mode — and a partial map says whose 1-1 it is', async ({
    page,
  }) => {
    const wizard = await projectWithAnchors(page);
    await stubMap(page); // partial — the safe declaration
    await wizard.goto('electrodes');
    await expect(byId(page, TID.electrodePanel)).toBeVisible({ timeout: SHORT });

    // The grid facts carry the MEASURED scale, the device that supplied it, and the mode.
    await expect(byId(page, TID.electrodeUmPerPx)).toHaveText(String((PITCH_UM / PITCH).toFixed(4)));
    await expect(byId(page, TID.electrodeDevice)).toContainText('MaxWell');
    await expect(byId(page, TID.electrodeCoverageMode)).toHaveAttribute('data-coverage', 'partial');

    // ⭐ A PARTIAL MAP MUST SAY WHOSE TOP-LEFT 1-1 IS — on the page, never behind a `?` (§5/R3.8).
    await expect(byId(page, TID.electrodePartialNote)).toBeVisible();
    await expect(byId(page, TID.electrodePartialNote)).toContainText('imaged region');

    // A selection reads its position in µm beside the pixels — (col−1)·17.5, (row−1)·17.5 here.
    const canvas = byId(page, TID.electrodesCanvas);
    const box = await canvas.boundingBox();
    if (!box) throw new Error('electrodes canvas has no box');
    const [c, r] = parseId(await clickUntilSelected(page, box.width / 2, box.height / 2));
    await expect(byId(page, TID.electrodeUm)).toHaveText(
      `${((c - 1) * PITCH_UM).toFixed(1)}, ${((r - 1) * PITCH_UM).toFixed(1)}`,
    );
  });

  // ⛔ R45.8 · THERE IS NO "SHAPE CORRECTED" WARNING, BECAUSE THERE IS NO CORRECTION. A full map
  // used to be repairable — a near miss had an edge line added or dropped and this panel said so.
  // Two repair rules were built and both were caught renumbering the whole array while reporting
  // the right shape, so the repair is gone: under "whole chip imaged" the fit either IS the device
  // (registered where the pixels put the array's edge) or the job REFUSES, and the refusal is what
  // he reads. The declaration itself must still show on a full map.
  test('R45.8: a full map declares itself, and claims no correction', async ({ page }) => {
    const wizard = await projectWithAnchors(page);
    await stubMap(page, { coverage: 'full' });
    await wizard.goto('electrodes');
    await expect(byId(page, TID.electrodePanel)).toBeVisible({ timeout: SHORT });

    await expect(byId(page, TID.electrodeCoverageMode)).toHaveAttribute('data-coverage', 'full');
    // Declaring the whole chip imaged is the opposite of the partial caveat — it must NOT fire.
    await expect(byId(page, TID.electrodePartialNote)).toBeHidden();
    // …and nothing anywhere may claim the shape was adjusted.
    await expect(page.getByTestId('electrode-shape-corrected')).toHaveCount(0);
  });

  // ⭐ R45.8 · NEVER A DEVICE NUMBER THE PAYLOAD DID NOT CARRY (review finding #4). A map written
  // before R45.8 has no device and no µm scale, and the partial note used to promise "only its
  // 17.5 µm pitch, which is what sets the µm scale below" over exactly that payload — a number
  // nobody measured, describing a scale that is not on the page.
  test('R45.8: a map with no device promises no pitch and no µm scale', async ({ page }) => {
    const wizard = await projectWithAnchors(page);
    await stubMap(page, { device: false });
    await wizard.goto('electrodes');
    await expect(byId(page, TID.electrodePanel)).toBeVisible({ timeout: SHORT });

    // The caveat still fires — it is about the NUMBERING, which stands with or without a device.
    const note = byId(page, TID.electrodePartialNote);
    await expect(note).toBeVisible();
    await expect(note).toContainText('imaged region');

    // …but nothing on this screen names a pitch or a scale, because this payload carries neither.
    await expect(byId(page, TID.electrodeUmPerPx)).toBeHidden();
    await expect(byId(page, TID.electrodeDevice)).toBeHidden();
    await page.getByLabel('Why this warning').hover();
    const tip = byId(page, TID.helpTooltip);
    await expect(tip).toBeVisible({ timeout: SHORT });
    await expect(tip).toContainText('pixels only');
    await expect(tip).not.toContainText('17.5');

    // A selection reads its centre in px alone — the µm fact is ABSENT, never zero (R45.8).
    const canvas = byId(page, TID.electrodesCanvas);
    const box = await canvas.boundingBox();
    if (!box) throw new Error('electrodes canvas has no box');
    await clickUntilSelected(page, box.width / 2, box.height / 2);
    await expect(byId(page, TID.electrodeUm)).toBeHidden();
  });

  // ─────────────────────────────────────────────────────────────────────────────
  // R45.8 · THE DEVICE IS READ, NEVER RETYPED (the 2026-08-11 review, finding #1).
  //
  // Every device number lives in ONE place — the backend `DeviceSpec`/`MAXWELL`, which is also the
  // thing that ENFORCES it. The coverage question wrote them out a second time as button prose, and
  // a second copy of a rule is a copy that will one day disagree with it: change `DeviceSpec.axes`
  // and the panel goes on promising the old array while the fitter refuses fits against the new one.
  // These two tests are the teeth — the served spec is fabricated, so a retyped number cannot pass.
  // ─────────────────────────────────────────────────────────────────────────────

  test('R45.8: the coverage question READS the device off the wire — it does not retype it', async ({
    page,
  }) => {
    await stubDevice(page, FAKE_DEVICE);
    const wizard = await projectWithAnchors(page);
    await wizard.goto('electrodes');
    await expect(byId(page, TID.electrodesViewer)).toBeVisible({ timeout: SHORT });

    // 1 · the blurb is the SERVED spec, formatted here — long side first, digits grouped
    const full = byId(page, TID.electrodeCoverageFull);
    await expect(full).toContainText('7 × 5 = 35 electrodes', { timeout: SHORT });
    // …and NOT the real chip's numbers, which is the whole point: nothing in web/ knows them.
    await expect(full).not.toContainText('220');
    await expect(full).not.toContainText('26,400');

    // 2 · the `?` behind the question names the served device — its name AND its pitch
    await page.getByLabel('What the coverage answer changes').hover();
    const tip = byId(page, TID.helpTooltip);
    await expect(tip).toBeVisible({ timeout: SHORT });
    await expect(tip).toContainText('Bench Rig MicroArray');
    await expect(tip).toContainText('3.5 µm');
    await expect(tip).not.toContainText('17.5 µm');
  });

  test('R45.8: with no device spec the choice still works, and names NO numbers rather than stale ones', async ({
    page,
  }) => {
    await stubDevice(page, null); // the endpoint is down — an answer he can give must not depend on it
    const wizard = await projectWithAnchors(page);
    await wizard.goto('electrodes');
    await expect(byId(page, TID.electrodesViewer)).toBeVisible({ timeout: SHORT });

    const full = byId(page, TID.electrodeCoverageFull);
    const mapBtn = byId(page, TID.electrodesMap);
    await expect(full).toBeVisible({ timeout: SHORT });

    // ⛔ A REMEMBERED NUMBER IS WORSE THAN NONE — it reads exactly like a true one. The segment says
    // what is true ("enforces the device's full array") and nothing numeric at all.
    expect(await full.innerText()).not.toMatch(/\d/);

    // …and the question is still fully answerable: the server enforces the same rule either way.
    await expect(mapBtn).toBeDisabled();
    await full.click();
    await expect(full).toHaveAttribute('aria-pressed', 'true');
    await expect(mapBtn).toBeEnabled();

    // The `?` withholds the numbers too — LAST, because an open tooltip covers the control below it.
    await page.getByLabel('What the coverage answer changes').hover();
    const tip = byId(page, TID.helpTooltip);
    await expect(tip).toBeVisible({ timeout: SHORT });
    for (const stale of ['220', '120', '26,400', '17.5']) {
      await expect(tip).not.toContainText(stale);
    }
  });

  // ─────────────────────────────────────────────────────────────────────────────
  // ⭐ R45.8 STRICT — *"if the user select full imaging then I want the rules to be strictly
  // enforced"* (his words, 2026-08-11). The run ends in EXACTLY ONE of two states: the device's
  // shape with every position numbered, or a REFUSAL. The refusal is the useful half — it names the
  // shape it found, the shape the device wants, and tells him what to answer instead — so it must
  // reach the screen WHOLE, with the question it tells him to change still on the page.
  // ─────────────────────────────────────────────────────────────────────────────

  test('R45.8 strict: a refusal is shown whole, and the coverage question is still there to change', async ({
    page,
  }) => {
    const wizard = await projectWithAnchors(page);
    await wizard.goto('electrodes');
    await expect(byId(page, TID.electrodesViewer)).toBeVisible({ timeout: SHORT });
    // no GET stub: the real backend answers 404, so the Map panel (question + button) is on screen

    // The core's own refusal shape (`_shape_refusal` in core/electrodegrid.py): both shapes named,
    // and the answer he should give instead. It is long — that is exactly why it must not be trimmed.
    const REFUSAL =
      'the whole array was declared imaged, but the fit found 24 x 16, not 220 x 120 — ' +
      "if this mosaic shows only part of the chip, choose 'partially imaged'";

    const JOB_ID = 'e2e-refusal-job';
    await page.route(`**${ROUTES.electrodes}/map`, async (route) => {
      await route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({ job_id: JOB_ID, kind: 'electrode_map', state: 'queued' }),
      });
    });
    await page.route(`**${ROUTES.jobs}/${JOB_ID}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          job_id: JOB_ID,
          kind: 'electrode_map',
          state: 'failed',
          error: { code: 'no_grid', message: REFUSAL },
        }),
      });
    });

    await byId(page, TID.electrodeCoverageFull).click();
    await byId(page, TID.electrodesMap).click();

    // 1 · the refusal, VERBATIM — every clause, not a code and not "mapping failed"
    const err = byId(page, TID.electrodesMapError);
    await expect(err).toBeVisible({ timeout: SHORT });
    await expect(err).toContainText(REFUSAL);

    // 2 · the fix it tells him to make is one click away: the question is still on the page, still
    //     carrying his answer, and re-runnable the moment he changes it.
    await expect(byId(page, TID.electrodeCoverage)).toBeVisible();
    await expect(byId(page, TID.electrodeCoverageFull)).toHaveAttribute('aria-pressed', 'true');
    await byId(page, TID.electrodeCoveragePartial).click();
    await expect(byId(page, TID.electrodeCoveragePartial)).toHaveAttribute('aria-pressed', 'true');
    await expect(byId(page, TID.electrodesMap)).toBeEnabled();
  });
});
