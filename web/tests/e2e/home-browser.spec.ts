import { test, expect } from '@playwright/test';
import { Home, Wizard, TID, byId, enterMosaic, fillPath } from './pages';
import { randomUUID } from 'node:crypto';

import { FIXTURE, PATHS, SHORT } from './fixture';

/**
 * THE HOME IS A PROJECT MANAGER (2026-07-24 reframe — R41), and opening a project excludes nothing.
 * Covers BEHAVIOUR I1, R2.1–R2.3, R4.5, R41.
 *
 * ⭐ **THE OLD HARNESS DEPENDENCY IS GONE** (2026-07-25). These used to assume a store had been
 * chosen and a data root registered — neither setup existed, so the note here warned the home would
 * show a first-run prompt instead. There is no store and no root registry now: the new-project flow
 * asks for both paths outright and the tests type them.
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

  test('R-shape: the off-shape frame is refused BY SHAPE — the receipt states a shape, not a number', async ({
    page,
  }) => {
    // The fixture plants a 512×128 frame (trial 9). It is real data the shape-gate must refuse by
    // SHAPE — never by a hard-coded trial number (HARD RULE 3). The receipt for the folder the user
    // typed advertises its shape groups.
    const home = new Home(page);
    await home.open();
    await byId(page, TID.newProject).click();
    await byId(page, TID.npName).fill('shape check');
    await byId(page, TID.npNext).click();
    await page.getByTestId(TID.taskCard).first().click();
    await fillPath(page, TID.fromField, PATHS.data);
    await expect(home.card().getByTestId(TID.cardShapes)).toContainText(
      `${FIXTURE.tile}×${FIXTURE.tile}`,
    );
  });
});

/**
 * WHERE FROM, WHERE TO — his ruling of 2026-07-25. Two path boxes, no root registry, no browse grid.
 */
test.describe('The new-project flow asks for two paths (R41.3)', () => {
  test('there is no first-run "choose a store" prompt — the home renders straight away', async ({
    page,
  }) => {
    await new Home(page).open();
    await expect(page.getByRole('heading', { name: /what do you want to do today/i })).toBeVisible();
    // The deleted screen. Nothing must have to be picked before he can start.
    await expect(page.getByTestId('first-run-store')).toHaveCount(0);
    await expect(page.getByTestId('choose-store')).toHaveCount(0);
  });

  test('⭐ R44: the dataset step is ONE path box — the app never asks where to save', async ({
    page,
  }) => {
    const home = new Home(page);
    await home.open();
    await byId(page, TID.newProject).click();
    await byId(page, TID.npName).fill('one path');
    await byId(page, TID.npNext).click();
    await page.getByTestId(TID.taskCard).first().click();

    await expect(byId(page, TID.paths)).toBeVisible();
    await expect(byId(page, TID.fromField)).toBeVisible();

    // ⛔ **THE SAVE-FOLDER BOX IS GONE** (R44 reverses R42.1). Not hidden — absent.
    await expect(page.getByTestId('into-field')).toHaveCount(0);
    const body = await page.locator('body').innerText();
    expect(body).not.toMatch(/save into/i);

    // ⛔ …and the registry UI R42 removed stays removed: no root chips, no "N under M roots", and
    // no grid of datasets the app went looking for.
    expect(body).not.toMatch(/data root/i);
    expect(body).not.toMatch(/under \d+ roots?/i);
    await expect(page.getByTestId(TID.card)).toHaveCount(0);

    // Create is refused until the ONE path is given — and enabled the moment it is.
    await expect(byId(page, TID.npCreate)).toBeDisabled();
    await fillPath(page, TID.fromField, PATHS.data);
    await expect(byId(page, TID.npCreate)).toBeEnabled();
  });

  test('the receipt states what is in the folder he typed — every number off the response', async ({
    page,
  }) => {
    const home = new Home(page);
    await home.open();
    await byId(page, TID.newProject).click();
    await byId(page, TID.npName).fill('receipt');
    await byId(page, TID.npNext).click();
    await page.getByTestId(TID.taskCard).first().click();
    await fillPath(page, TID.fromField, PATHS.data);

    await expect(home.card().getByTestId(TID.cardName)).toHaveText(FIXTURE.name);
    await expect(home.card().getByTestId(TID.cardSnapshots)).toHaveText(String(FIXTURE.snapshots));
  });

  test('a folder with no dataset in it fails INLINE and keeps what he typed', async ({ page }) => {
    const home = new Home(page);
    await home.open();
    await byId(page, TID.newProject).click();
    await byId(page, TID.npName).fill('bad path');
    await byId(page, TID.npNext).click();
    await page.getByTestId(TID.taskCard).first().click();

    const typed = `${PATHS.saveRoot}/definitely-not-a-dataset`;
    await fillPath(page, TID.fromField, typed);

    const field = byId(page, TID.fromField);
    await expect(field.getByTestId(TID.pathError)).toBeVisible({ timeout: SHORT });
    // 🔴 The text SURVIVES. The old modal threw it away and made him type the whole path again.
    await expect(field.getByTestId(TID.pathInput)).toHaveValue(typed);
  });

  test('the project card shows where its DATA came from — the one path he named', async ({
    page,
  }) => {
    // ⚠️ Unique per run: the state dir persists between local runs, so a fixed name would match the
    // cards left by every previous run and trip Playwright's strict mode.
    const name = `data on the card ${randomUUID().slice(0, 8)}`;
    const home = new Home(page);
    await home.open();
    await home.openFixture(name);

    await home.open();
    const card = page.getByTestId(TID.projectCard).filter({ hasText: name });
    // ⭐ R44: the card advertises the DATA folder, never the project's own — that one is Camea's and
    // is not somewhere to go. Its files are browsed in the app.
    await expect(card.getByTestId(TID.projectDataDir)).toContainText('synthetic');
    await expect(card.getByTestId('project-folder')).toHaveCount(0);
  });

  test('⛔ R44: there is no "Remove" that leaves the files — delete means delete', async ({
    page,
  }) => {
    const name = `delete means delete ${randomUUID().slice(0, 8)}`;
    const home = new Home(page);
    await home.open();
    await home.openFixture(name);
    await home.open();

    const card = page.getByTestId(TID.projectCard).filter({ hasText: name });
    await expect(card).toBeVisible();
    // R42.8's second action is gone with the user-named folder it protected.
    await expect(page.getByTestId('project-forget')).toHaveCount(0);

    // `window.confirm` on purpose (R38): Playwright can answer it, a custom modal it cannot.
    page.once('dialog', (d) => {
      expect(d.message()).toMatch(/cannot be undone/i);
      void d.accept();
    });
    await card
      .locator('xpath=../..')
      .getByTestId(TID.projectDelete)
      .or(page.getByTestId(TID.projectDelete).first())
      .first()
      .click();
    await expect(page.getByTestId(TID.projectCard).filter({ hasText: name })).toHaveCount(0);
  });
});
