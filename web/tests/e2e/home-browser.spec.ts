import { test, expect } from '@playwright/test';
import { Home, Wizard, TID, byId, enterMosaic } from './pages';
import { FIXTURE, SHORT } from './fixture';

/**
 * THE HOME IS A PROJECT MANAGER (2026-07-24 reframe — R41), and opening a project excludes nothing.
 * Covers BEHAVIOUR I1, R2.1–R2.3, R4.5, R41.
 *
 * ⚠️ HARNESS DEPENDENCY: these assume the app-managed store is already chosen and the fixture root is
 * registered (the e2e global-setup should `PUT /api/workspace` + scan the fixture root). Without that,
 * the home shows the first-run store prompt instead of the greeting/cards.
 */
test.describe('Home is a project manager (I1, R41)', () => {
  test('R41: the home screen is the project manager, greeting and a New project action', async ({
    page,
  }) => {
    const home = new Home(page);
    await home.open();
    await expect(page.getByRole('heading', { name: /what do you want to do today/i })).toBeVisible();
    await expect(byId(page, TID.newProject)).toBeVisible();
  });

  test('R2.1: opening a project loads N-of-whatever-is-on-disk with 0 excluded', async ({ page }) => {
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

  test('R4.5: opening a project navigates to Range — there is no in-place #load-result block', async ({
    page,
  }) => {
    await enterMosaic(page);
    const wizard = new Wizard(page);
    await wizard.expectActive('range');
    // The deleted DOM (§6.6): opening a project NAVIGATES, it does not reveal a result in place.
    await expect(byId(page, TID.loadResultFORBIDDEN)).toHaveCount(0);
  });

  test('R-shape: the off-shape frame is refused BY SHAPE — the picker card states a shape, not a number', async ({
    page,
  }) => {
    // The fixture plants a 512×128 frame (trial 9). It is real data the shape-gate must refuse by
    // SHAPE — never by a hard-coded trial number (HARD RULE 3). The dataset card (in the new-project
    // attach-dataset step) advertises its shape groups.
    const home = new Home(page);
    await home.open();
    await byId(page, TID.newProject).click();
    await byId(page, TID.npName).fill('shape check');
    await byId(page, TID.npNext).click();
    await page.getByTestId(TID.taskCard).first().click();
    await expect(home.card().getByTestId(TID.cardShapes)).toContainText(
      `${FIXTURE.tile}×${FIXTURE.tile}`,
    );
  });
});
