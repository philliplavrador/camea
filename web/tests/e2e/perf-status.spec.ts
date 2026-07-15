import { test, expect } from '@playwright/test';
import { TID, byId, enterSweep } from './pages';
import { SHORT } from './fixture';

/**
 * LAYERED CANVAS IS MANDATORY (R20). The status bar carries a live ms/frame readout that MUST read
 * ~6 ms during a sweep. ~90 ms means the background is being rebaked every frame — the exact bug the
 * layered architecture exists to prevent. The assertion is soft (per the task) but it must exist.
 */
test.describe('R20 — the render budget', () => {
  test('R20: the status bar exposes ms/frame and fps readouts', async ({ page }) => {
    await enterSweep(page);
    await expect(byId(page, TID.statusMsFrame)).toBeVisible({ timeout: SHORT });
    await expect(byId(page, TID.statusFps)).toBeVisible();
  });

  test('R20: ms/frame reads ~6 ms during a sweep, not ~90 ms (soft assert)', async ({ page }) => {
    const sweep = await enterSweep(page);
    // Bake a few tiles into the anchor layer and drive a fade so the render loop is genuinely running.
    await sweep.press('a');
    await sweep.press('Space');
    await sweep.press('a');
    await sweep.press('Space');
    await sweep.press('r'); // replay the fade → the loop ticks

    const readout = byId(page, TID.statusMsFrame);
    await expect(readout).toBeVisible({ timeout: SHORT });

    // Sample the lowest ms/frame we see over ~1.5 s (the loop should settle to the layered budget).
    let best = Infinity;
    for (let i = 0; i < 6; i++) {
      const ms = Number((await readout.textContent())?.match(/[\d.]+/)?.[0] ?? 'NaN');
      if (Number.isFinite(ms)) best = Math.min(best, ms);
      await page.waitForTimeout(250);
    }
    expect(Number.isFinite(best), 'ms/frame must be a number').toBe(true);
    // SOFT: ~90 ms = rebaking every frame (the R20 bug). ~6 ms = the layered path. 33 ms is the line.
    expect.soft(best, 'ms/frame should be ~6 ms (layered), not ~90 ms (rebaked)').toBeLessThan(33);
  });
});
