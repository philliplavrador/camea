import { test, expect } from '@playwright/test';
import { Wizard, TID, byId, enterMosaic } from './pages';
import { FIXTURE, SHORT } from './fixture';

/**
 * R2.7 — ⭐ **THE CONTACT SHEET SAYS WHICH SNAPSHOTS ARE NOT TILES OF THIS MOSAIC**, and `Apply` makes
 * the answer stick (his ask, 2026-07-24).
 *
 * ⭐ **UPDATED 2026-07-25 (R2.8).** A project used to open on every square snapshot the dataset held, so
 * the snapshots taken before the mosaic scan started — the fixture's stray trial 5 (and the off-shape 9),
 * standing in for 260620d's `1` and `5-7` — came in with it. They were drawn exactly like the tiles, so
 * the sheet claimed 12 tiles for a 10-tile mosaic, and they were swept, solved and exported as if they
 * belonged. **They are now never in the project**: `log.txt` says which acquisition is the mosaic, and
 * only that one is opened. The sheet therefore opens with NOTHING framed — and frames live the moment he
 * narrows the range, which is the guarantee this ruling actually protects.
 *
 * ⛔ **RED IS NOT EXCLUDED.** Nothing on this screen excludes anything: `excluded` stays **0** through
 * the whole flow. Excluding is `E`, in the sweep, and it is his (R2.1/R2.2/R6).
 * ⛔ And no number here is the app's: the run comes from `log.txt` + the per-trial XML shape, measured
 * by the backend, and the range is whatever he types.
 */
test.describe('Range — what is, and is not, a tile of this mosaic (R2.7)', () => {
  const cellByTrial = (page: import('@playwright/test').Page, trial: number) =>
    page.locator(`[data-testid="${TID.contactCell}"][data-trial="${trial}"]`);

  test('the project opens on exactly the mosaic run — every cell is a tile, none framed', async ({
    page,
  }) => {
    // ⭐ REWRITTEN 2026-07-25 (his ruling): a project now opens on the acquisition `log.txt` says is
    // the mosaic — the ONE uninterrupted run of Snapshot trials — so the snapshots taken before the
    // scan started are not in it at all. Nothing is framed on open, because everything here IS a tile.
    // (The framing this ruling protects is exercised below, by narrowing the range.)
    await enterMosaic(page);
    const wizard = new Wizard(page);
    await wizard.goto('range');
    await expect(byId(page, TID.contactSheet)).toBeVisible({ timeout: SHORT });

    for (let t = FIXTURE.runLo; t <= FIXTURE.runHi; t++) {
      await expect(cellByTrial(page, t)).not.toHaveAttribute('data-out', 'true');
    }
    // The legend says so in words — there is no "N are not tiles" count to render at all.
    await expect(byId(page, TID.sheetNOut)).toHaveCount(0);
    await expect(byId(page, TID.sheetLegend)).toContainText(/every loaded snapshot is a tile/i);

    // ⛔ The stray block and the off-shape frame are not tiles of this mosaic, so they have no cell.
    await expect(cellByTrial(page, FIXTURE.strayTrial)).toHaveCount(0);
    await expect(cellByTrial(page, FIXTURE.offShapeTrial)).toHaveCount(0);
  });

  test('a framed cell says WHY, and is not a way into the sweep', async ({ page }) => {
    await enterMosaic(page);
    const wizard = new Wizard(page);
    await wizard.goto('range');
    await expect(byId(page, TID.contactSheet)).toBeVisible({ timeout: SHORT });

    // Narrow `lo` by one — the first tile of the run leaves the mosaic and must say so.
    await byId(page, TID.rangeLo).fill(String(FIXTURE.runLo + 1));
    const dropped = cellByTrial(page, FIXTURE.runLo);
    await expect(dropped).toHaveAttribute('data-out', 'true', { timeout: SHORT });
    await expect(dropped).toHaveAttribute('title', /outside the range|not a tile/);
    await expect(dropped).toBeDisabled();
  });

  test('the framing is LIVE against the range he is typing', async ({ page }) => {
    await enterMosaic(page);
    const wizard = new Wizard(page);
    await wizard.goto('range');
    await expect(byId(page, TID.contactSheet)).toBeVisible({ timeout: SHORT });

    const first = cellByTrial(page, FIXTURE.runLo);
    await expect(first).not.toHaveAttribute('data-out', 'true');

    // Narrow, then widen back — WITHOUT applying. The sheet answers the number under his cursor.
    await byId(page, TID.rangeLo).fill(String(FIXTURE.runLo + 1));
    await expect(first).toHaveAttribute('data-out', 'true', { timeout: SHORT });
    await byId(page, TID.rangeLo).fill(String(FIXTURE.runLo));
    await expect(first).not.toHaveAttribute('data-out', 'true', { timeout: SHORT });
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
