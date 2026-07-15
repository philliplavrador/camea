import { test, expect } from '@playwright/test';
import { Wizard, Sweep, TID, byId, enterMosaic, stubScreenPropose } from './pages';
import { SHORT } from './fixture';

/**
 * THE SCREEN STEP IS ONE CONTROL WITH THREE BUTTONS (Keep · Hand place · Exclude), Hand place is the
 * default, choices apply immediately, and — the load-bearing one — the card RE-DERIVES FROM LIVE TILE
 * STATE every time he arrives (R6). The bulk buttons are gone (R6b).
 *
 * ⚠️ The committed synthetic fixture is too small for the real blank scan to determine a threshold (it
 * needs ≥20 pass-1 reference frames; the fixture has ≤11), so `propose` recommends nothing and the grid
 * is empty. We stub the recommendation — flagging one interior run trial — exactly as the R15 specs stub
 * `match/anchor`: it tests the UI's three-way control on deterministic input, not the scan itself. The
 * excluded-frame gap (R2.3) is still computed by the REAL backend gaps route.
 */
test.describe('Screen step — three-way control (R6)', () => {
  const FLAGGED = 15; // an interior run trial: excluding it opens a real gap (14→16) for R2.3.
  test.beforeEach(async ({ page }) => {
    await stubScreenPropose(page, [FLAGGED]);
  });
  const anyCard = (page: import('@playwright/test').Page) => byId(page, TID.screenCard).first();

  test('R6.1: each scanned frame carries exactly three mutually-exclusive buttons, one selected', async ({
    page,
  }) => {
    const wizard = new Wizard(page);
    await enterMosaic(page);
    await wizard.goto('screen');
    const card = anyCard(page);
    await expect(card).toBeVisible({ timeout: SHORT });
    await expect(card.getByTestId(TID.screenKeep)).toHaveCount(1);
    await expect(card.getByTestId(TID.screenHand)).toHaveCount(1);
    await expect(card.getByTestId(TID.screenExclude)).toHaveCount(1);
    // Exactly one is selected (aria-pressed=true), driven off the card's data-choice.
    await expect(card).toHaveAttribute('data-choice', /keep|hand|exclude/);
  });

  test('R6.2: "Hand place" is the DEFAULT on a scanned frame', async ({ page }) => {
    const wizard = new Wizard(page);
    await enterMosaic(page);
    await wizard.goto('screen');
    const card = anyCard(page);
    await expect(card).toHaveAttribute('data-choice', 'hand', { timeout: SHORT });
    await expect(card.getByTestId(TID.screenHand)).toHaveAttribute('aria-pressed', 'true');
  });

  test('R6.5: the choice applies immediately — there is no Apply button on the Screen step', async ({
    page,
  }) => {
    const wizard = new Wizard(page);
    await enterMosaic(page);
    await wizard.goto('screen');
    const card = anyCard(page);
    await expect(card).toBeVisible({ timeout: SHORT });
    await card.getByTestId(TID.screenExclude).click();
    await expect(card).toHaveAttribute('data-choice', 'exclude');
    // No Apply / Save-this-screen affordance; the state IS the choice.
    await expect(byId(page, TID.screenGrid).getByRole('button', { name: /^apply$/i })).toHaveCount(
      0,
    );
  });

  test('R6/R2.3: Exclude on a scanned frame recomputes gaps live; Keep restores them', async ({
    page,
  }) => {
    const wizard = new Wizard(page);
    await enterMosaic(page);
    await wizard.goto('screen');
    const card = byId(page, TID.screenCard).first();
    await expect(card).toBeVisible({ timeout: SHORT });
    const trial = Number(await card.getAttribute('data-trial'));
    await card.getByTestId(TID.screenExclude).click();
    // Excluding an interior frame opens a gap; the Range facts must reflect it (gaps are LIVE).
    await wizard.goto('range');
    await expect(byId(page, TID.factGaps)).not.toHaveText(/none/i, { timeout: SHORT });
    // Put it back with Keep → gaps return to none. (data-trial is on the card element itself.)
    await wizard.goto('screen');
    await page
      .locator(`[data-testid="${TID.screenCard}"][data-trial="${trial}"]`)
      .getByTestId(TID.screenKeep)
      .click();
    await wizard.goto('range');
    await expect(byId(page, TID.factGaps)).toHaveText(/none/i, { timeout: SHORT });
  });

  test('R6.6: 🔴 the card RE-DERIVES from live state — E in the sweep leaves its card reading Exclude', async ({
    page,
  }) => {
    // The measured bug: pressing E on a scanned frame in the sweep left its card still reading
    // "Hand place" for a frame that was by then excluded. The card claims to BE the state.
    const wizard = new Wizard(page);
    await enterMosaic(page);
    await wizard.goto('screen');
    const card = byId(page, TID.screenCard).first();
    await expect(card).toBeVisible({ timeout: SHORT });
    const trial = Number(await card.getAttribute('data-trial'));

    // Go to the sweep, land on that trial, and exclude it with the key.
    await wizard.goto('sweep');
    const sweep = new Sweep(page);
    const chip = sweep.chip(trial);
    if ((await chip.count()) > 0) await chip.click();
    await sweep.focus();
    await sweep.press('e');

    // Return to Screen — the card MUST now read "exclude", not the stale "hand".
    await wizard.goto('screen');
    const back = page.locator(`[data-testid="${TID.screenCard}"][data-trial="${trial}"]`);
    await expect(back).toHaveAttribute('data-choice', 'exclude', { timeout: SHORT });
  });

  test('R6b: the bulk buttons are GONE — no Tick all / Tick none / Exclude the ticked', async ({
    page,
  }) => {
    const wizard = new Wizard(page);
    await enterMosaic(page);
    await wizard.goto('screen');
    await expect(byId(page, TID.screenGrid)).toBeVisible({ timeout: SHORT });
    await expect(byId(page, TID.bulkTickAllFORBIDDEN)).toHaveCount(0);
    await expect(byId(page, TID.bulkTickNoneFORBIDDEN)).toHaveCount(0);
    await expect(byId(page, TID.bulkExcludeTickedFORBIDDEN)).toHaveCount(0);
    // And there is no pre-ticked box under a primary "Exclude" button (a pre-ticked bulk exclude IS
    // an auto-exclude — R6b, the four-anchors-thrown-away regression).
    await expect(page.getByRole('button', { name: /exclude the ticked/i })).toHaveCount(0);
  });

  test('R17/§6.3: NO blur score anywhere on the Screen step (no slider, no sharpness number)', async ({
    page,
  }) => {
    const wizard = new Wizard(page);
    await enterMosaic(page);
    await wizard.goto('screen');
    await expect(byId(page, TID.screenGrid)).toBeVisible({ timeout: SHORT });
    const body = await page.locator('body').innerText();
    expect(body).not.toMatch(/blur|sharpness|laplacian|variance of/i);
    await expect(page.getByRole('slider', { name: /blur|sharp|focus/i })).toHaveCount(0);
  });
});
