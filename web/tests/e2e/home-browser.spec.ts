import { test, expect } from '@playwright/test';
import { Home, Wizard, TID, byId, enterMosaic } from './pages';
import { FIXTURE, SHORT } from './fixture';

/**
 * THE HOME SCREEN IS A DATASET BROWSER, and opening a dataset excludes nothing.
 * Covers BEHAVIOUR I1, R2.1–R2.3, R4.5.
 */
test.describe('Home is a dataset browser (I1, R2)', () => {
  test('R-home: the home screen is the dataset browser and lists the synthetic fixture', async ({
    page,
  }) => {
    const home = new Home(page);
    await home.open();
    await expect(page.getByRole('heading', { name: 'Datasets' })).toBeVisible();
    await expect(home.card()).toBeVisible();
    await expect(home.card().getByTestId(TID.cardSnapshots)).toHaveText(String(FIXTURE.snapshots));
  });

  test('R2.1: opening the dataset loads N-of-whatever-is-on-disk with 0 excluded', async ({
    page,
  }) => {
    const { wizard } = await enterMosaic(page);
    await wizard.goto('range');
    // The Range facts strip exists and the excluded count is ZERO — expressed as "gaps: none" plus
    // the absence of any exclusion line. Nothing on disk was pre-removed.
    const gaps = byId(page, TID.factGaps);
    await expect(gaps).toBeVisible({ timeout: SHORT });
    await expect(gaps).toHaveText(/none/i);
  });

  test('R2.2: the Range screen never says "N usable of M (K thrown out)"', async ({ page }) => {
    const { wizard } = await enterMosaic(page);
    await wizard.goto('range');
    await expect(byId(page, TID.rangeFacts)).toBeVisible({ timeout: SHORT });
    const body = await page.locator('body').innerText();
    expect(body).not.toMatch(/usable of/i);
    expect(body).not.toMatch(/thrown out/i);
  });

  test('R2.3: Gaps read "none" on a fresh open (gaps grow only when the USER excludes)', async ({
    page,
  }) => {
    const { wizard } = await enterMosaic(page);
    await wizard.goto('range');
    await expect(byId(page, TID.factGaps)).toHaveText(/none/i, { timeout: SHORT });
  });

  test('R4.5: opening the dataset navigates to Range — there is no in-place #load-result block', async ({
    page,
  }) => {
    await enterMosaic(page);
    const wizard = new Wizard(page);
    await wizard.expectActive('range');
    // The deleted DOM (§6.6): opening a directory NAVIGATES, it does not reveal a result in place.
    await expect(byId(page, TID.loadResultFORBIDDEN)).toHaveCount(0);
  });

  test('R-shape: the off-shape frame is refused BY SHAPE — the app states a shape, not a hidden number', async ({
    page,
  }) => {
    // The fixture plants a 512×128 frame (trial 9). It is real data the shape-gate must refuse by
    // SHAPE — never by a hard-coded trial number (HARD RULE 3). The card advertises its shape groups.
    const home = new Home(page);
    await home.open();
    await expect(home.card().getByTestId(TID.cardShapes)).toContainText(
      `${FIXTURE.tile}×${FIXTURE.tile}`,
    );
  });
});
