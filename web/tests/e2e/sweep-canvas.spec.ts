import { test, expect } from '@playwright/test';
import { TID, byId, enterSweep } from './pages';
import { SHORT } from './fixture';

/**
 * THE SWEEP DRAWS ONLY WHAT HE HAS CERTIFIED. The canvas starts EMPTY, an A bakes the tile into the
 * anchor layer, and the unverified layer is maintained but never drawn (R9). The certified field
 * blends into a continuous strip while the floating candidate stays crisp (R10).
 */
test.describe('R9 — the canvas starts empty and grows only by certification', () => {
  test('R9.1: with 0 anchored, the anchor layer draws nothing (no yellow cage)', async ({
    page,
  }) => {
    const sweep = await enterSweep(page);
    await expect(byId(page, TID.canvas)).toBeVisible({ timeout: SHORT });
    expect(await sweep.anchorLayerCount()).toBe(0);
    // The header agrees with the picture — the old bug was "0 anchored" over a canvas of 338 tiles.
    expect(await sweep.headerCount(TID.headerAnchored)).toBe(0);
  });

  test('R9.2: A bakes the tile into the anchor layer; the next tile fades in on top', async ({
    page,
  }) => {
    const sweep = await enterSweep(page);
    expect(await sweep.anchorLayerCount()).toBe(0);
    await sweep.press('a'); // certify the origin
    await expect.poll(() => sweep.anchorLayerCount(), { timeout: SHORT }).toBe(1);
    await sweep.press('Space'); // next tile fades in on top of {origin}
    await sweep.press('a'); // certify it too
    await expect.poll(() => sweep.anchorLayerCount(), { timeout: SHORT }).toBe(2);
  });

  test('R9.3/R9.4: the unverified layer is maintained but NOT drawn in the sweep', async ({
    page,
  }) => {
    const sweep = await enterSweep(page);
    await sweep.press('a');
    await sweep.press('Space'); // now there is an unverified tile in the field
    expect(await sweep.unverifiedDrawn()).toBe(false); // the flag is default-OFF for the sweep
  });

  test('R9b: Space defers a tile — it keeps its position (unverified) but is NOT drawn', async ({
    page,
  }) => {
    const sweep = await enterSweep(page);
    await sweep.press('a'); // origin
    const t = await sweep.advance(); // land trial 12 (R33: wait for the cursor to commit)
    await sweep.press('Space'); // DEFER 12 (do not anchor); advance
    // 12 keeps its machine position (chip is unverified/placed), and the anchor layer did not grow.
    await expect(sweep.chip(t)).toHaveAttribute('data-state', 'unverified', { timeout: SHORT });
    expect(await sweep.anchorLayerCount()).toBe(1); // only the origin is certified/drawn
  });
});

test.describe('R11 — A is a TOGGLE (certification, not position)', () => {
  test('R11.1: A on an anchored tile → unverified, KEEPS its position, and vanishes from the field', async ({
    page,
  }) => {
    const sweep = await enterSweep(page);
    const t = await sweep.currentTrial();
    await sweep.press('a'); // anchor
    await expect(sweep.chip(t)).toHaveAttribute('data-state', 'anchored', { timeout: SHORT });
    expect(await sweep.anchorLayerCount()).toBe(1);
    await sweep.press('a'); // toggle back
    // Not unplaced — un-certifying must never throw away a position.
    await expect(sweep.chip(t)).toHaveAttribute('data-state', 'unverified', { timeout: SHORT });
    // R11.2 — it vanishes from the drawn field (the canvas draws only the certified set).
    await expect.poll(() => sweep.anchorLayerCount(), { timeout: SHORT }).toBe(0);
  });

  test('R11.3/R11.4: un-anchoring to zero fires the "No anchors left" live warning (W10)', async ({
    page,
  }) => {
    const sweep = await enterSweep(page);
    await sweep.press('a'); // one anchor (the origin)
    await sweep.press('a'); // un-anchor → the set is now empty
    await expect(byId(page, TID.warnNoAnchors)).toBeVisible({ timeout: SHORT });
    await expect(byId(page, TID.warnNoAnchors)).toContainText(/no anchors left/i);
  });
});

test.describe('R12 — 1–9 jump to the Nth-best computed position', () => {
  test('R12.8: a digit with no prior V matches first, then jumps (no need to press V)', async ({
    page,
  }) => {
    const sweep = await enterSweep(page);
    await sweep.press('a'); // certify origin so a composite exists
    await sweep.press('Space'); // land a tile with candidates
    const before = await byId(page, TID.statusTopleft).textContent();
    await sweep.press('2'); // jump to the runner-up peak — matches first if needed
    await expect(byId(page, TID.statusTopleft)).not.toHaveText(before ?? '', { timeout: SHORT });
    await sweep.press('1'); // 1 restores the best peak
  });

  test('R12.3: the alternatives rail prints #1..#9 (display = rank+1), not #0..#8', async ({
    page,
  }) => {
    const sweep = await enterSweep(page);
    await sweep.press('a');
    await sweep.press('Space');
    await sweep.press('v');
    const list = byId(page, TID.alternativesList);
    await expect(list).toBeVisible({ timeout: SHORT });
    // The number he READS and the number he PRESSES must agree: the best alternative reads "#1".
    await expect(list).toContainText('#1');
    await expect(list).not.toContainText('#0');
  });

  test('R12.10: a jump is a human move — it does NOT anchor', async ({ page }) => {
    const sweep = await enterSweep(page);
    await sweep.press('a');
    const t = await sweep.advance(); // land a tile (R33: wait for the cursor to commit)
    await sweep.press('1');
    // Still not anchored — he must press A himself.
    await expect(sweep.chip(t)).not.toHaveAttribute('data-state', 'anchored');
  });
});
