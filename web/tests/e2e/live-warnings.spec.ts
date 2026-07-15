import { test, expect } from '@playwright/test';
import { Sweep, Wizard, TID, byId, enterMosaic, enterSweep, runBuild } from './pages';
import { SHORT } from './fixture';

/**
 * THE LIVE-WARNING EXCEPTION (§5, R3.8). Eleven warnings fire only when something is actually wrong,
 * they change what he would do, and — unlike a `?` — they STAY ON THE PAGE. A live warning is not an
 * explanation and must never be tidied into a tooltip.
 *
 * Several of the eleven need dataset conditions the clean synthetic fixture cannot produce (a blank
 * frame for W6, a thin-margin alias for W2, a small-aperture pair for W7, an autosave failure for W4).
 * Those are listed in the e2e README as "not expressible on the fixture". The ones below ARE.
 */
test.describe('§5 — live warnings stay on the page', () => {
  test('W10: un-anchoring to zero fires "No anchors left", visible WITHOUT a hover', async ({
    page,
  }) => {
    const sweep = await enterSweep(page);
    await sweep.press('a'); // one anchor
    await sweep.press('a'); // un-anchor → empty set
    const warn = byId(page, TID.warnNoAnchors);
    await expect(warn).toBeVisible({ timeout: SHORT }); // no hover required — it is not a tooltip
    await expect(warn).toContainText(/no anchors left/i);
  });

  test('R3.8: a live warning is NOT a tooltip — Escape does not dismiss it', async ({ page }) => {
    const sweep = await enterSweep(page);
    await sweep.press('a');
    await sweep.press('a');
    const warn = byId(page, TID.warnNoAnchors);
    await expect(warn).toBeVisible({ timeout: SHORT });
    await page.keyboard.press('Escape'); // Escape dismisses a `?` tooltip; a warning must survive it
    await expect(warn).toBeVisible();
  });

  test(
    'W1: excluding a tile AFTER a build fires "THE BUILD IS STALE" with the reason',
    { tag: '@slow' },
    async ({ page }) => {
      await enterMosaic(page);
      await runBuild(page);
      const wizard = new Wizard(page);
      await wizard.goto('sweep');
      const sweep = new Sweep(page);
      await sweep.focus();
      await sweep.press('e'); // exclude a tile → the build's input no longer matches the active set
      await expect(byId(page, TID.warnBuildStale)).toBeVisible({ timeout: SHORT });
      await expect(byId(page, TID.warnBuildStale)).toContainText(/stale/i);
    },
  );

  test(
    'W9: the Place worklist warns that pass-1 tiles have no per-tile confidence',
    { tag: '@slow' },
    async ({ page }) => {
      await enterMosaic(page);
      await runBuild(page);
      const wl = byId(page, TID.placeWorklist);
      await expect(wl).toBeVisible({ timeout: SHORT });
      // The absence of a warning is not a clean bill of health — the panel says so out loud.
      await expect(byId(page, TID.warnPass1NoConfidence)).toBeVisible();
      await expect(byId(page, TID.warnPass1NoConfidence)).toContainText(/no per-tile confidence/i);
    },
  );
});
