import { test, expect } from '@playwright/test';
import { Wizard, TID, byId, enterMosaic } from './pages';
import { FIXTURE, SHORT } from './fixture';

/**
 * R2.7 — ⭐ **THE CONTACT SHEET SAYS WHICH SNAPSHOTS ARE NOT TILES OF THIS MOSAIC**, and `Apply` makes
 * the answer stick (his ask, 2026-07-24).
 *
 * A project opens on every square snapshot the dataset holds. A real acquisition carries snapshots taken
 * before the mosaic scan started — the fixture's stray trial 5 (and the off-shape 9), standing in for
 * 260620d's `1` and `5-7`. They were drawn exactly like the tiles, so the sheet claimed 12 tiles for a
 * 10-tile mosaic, and they were swept, solved and exported as if they belonged.
 *
 * ⛔ **RED IS NOT EXCLUDED.** Nothing on this screen excludes anything: `excluded` stays **0** through
 * the whole flow. Excluding is `E`, in the sweep, and it is his (R2.1/R2.2/R6).
 * ⛔ And no number here is the app's: the run comes from `log.txt` + the per-trial XML shape, measured
 * by the backend, and the range is whatever he types.
 */
test.describe('Range — what is, and is not, a tile of this mosaic (R2.7)', () => {
  const cellByTrial = (page: import('@playwright/test').Page, trial: number) =>
    page.locator(`[data-testid="${TID.contactCell}"][data-trial="${trial}"]`);

  test('the snapshots outside the run are framed; every tile of the run is not', async ({
    page,
  }) => {
    await enterMosaic(page);
    const wizard = new Wizard(page);
    await wizard.goto('range');
    await expect(byId(page, TID.contactSheet)).toBeVisible({ timeout: SHORT });

    // The stray block and the off-shape frame: real data, not tiles of THIS mosaic.
    await expect(cellByTrial(page, FIXTURE.strayTrial)).toHaveAttribute('data-out', 'true', {
      timeout: SHORT,
    });
    await expect(cellByTrial(page, FIXTURE.offShapeTrial)).toHaveAttribute('data-out', 'true');
    // …and every trial of the run is untouched.
    for (let t = FIXTURE.runLo; t <= FIXTURE.runHi; t++) {
      await expect(cellByTrial(page, t)).not.toHaveAttribute('data-out', 'true');
    }
    await expect(byId(page, TID.sheetNOut)).toHaveText(
      String(FIXTURE.snapshots - FIXTURE.runCount),
    );
  });

  test('a framed cell says WHY, and is not a way into the sweep', async ({ page }) => {
    await enterMosaic(page);
    const wizard = new Wizard(page);
    await wizard.goto('range');
    const stray = cellByTrial(page, FIXTURE.strayTrial);
    await expect(stray).toHaveAttribute('data-out', 'true', { timeout: SHORT });
    await expect(stray).toHaveAttribute('title', /outside the range|not a tile/);
    await expect(stray).toBeDisabled();
  });

  test('the framing is LIVE against the range he is typing', async ({ page }) => {
    await enterMosaic(page);
    const wizard = new Wizard(page);
    await wizard.goto('range');
    const stray = cellByTrial(page, FIXTURE.strayTrial);
    await expect(stray).toHaveAttribute('data-out', 'true', { timeout: SHORT });

    // Widen `lo` past the stray — WITHOUT applying. The sheet must answer the number under his cursor.
    await byId(page, TID.rangeLo).fill(String(FIXTURE.strayTrial));
    await expect(stray).not.toHaveAttribute('data-out', 'true', { timeout: SHORT });
    // The off-shape frame stays framed: its FRAME is the wrong shape, and no range can fix that.
    await expect(cellByTrial(page, FIXTURE.offShapeTrial)).toHaveAttribute('data-out', 'true');
  });

  test('Apply re-scopes the project to the range — and excludes NOTHING', async ({ page }) => {
    await enterMosaic(page);
    const wizard = new Wizard(page);
    await wizard.goto('range');
    await expect(byId(page, TID.contactSheet)).toBeVisible({ timeout: SHORT });

    await byId(page, TID.rangeLo).fill(String(FIXTURE.runLo));
    await byId(page, TID.rangeHi).fill(String(FIXTURE.runHi));
    await byId(page, TID.rangeApply).click();

    // The document now holds exactly the run…
    await wizard.goto('load');
    await expect(page.getByTestId(TID.loadOpenDataset)).toBeVisible({ timeout: SHORT });
    const facts = page.getByTestId(TID.loadOpenDataset).locator('..');
    await expect(facts).toContainText(`${FIXTURE.runCount} trials`);
    // ⛔ …and the trials that left are NOT exclusions. Zero, as on a fresh open (R2.1/R2.2).
    await expect(facts).toContainText(`${FIXTURE.excludedOnFreshOpen} excluded`);
  });
});
