import { test, expect, type Page } from '@playwright/test';
import { TID, byId, enterSweep, recordMatchAnchor, ROUTES } from './pages';
import { SHORT } from './fixture';

/**
 * THE KEYBOARD MAP (BEHAVIOUR §3) — every bound key works; the deliberately-unbound keys do nothing.
 * The centrepiece is R14: Esc must NOT kill the sweep.
 */

async function topLeft(page: Page): Promise<[number, number]> {
  const txt = (await byId(page, TID.statusTopleft).textContent()) ?? '';
  const nums = txt.match(/-?\d+/g)?.map(Number) ?? [];
  return [nums[0] ?? NaN, nums[1] ?? NaN];
}

test.describe('R14 — Esc must NOT kill the sweep', () => {
  test('R14: Escape leaves the cursor put; Space, A and E still work afterwards', async ({
    page,
  }) => {
    const sweep = await enterSweep(page);
    const before = await sweep.currentTrial();
    expect(Number.isFinite(before)).toBe(true);

    await sweep.press('Escape');
    // The footer still reads an integer trial — never "trial —" (the frozen-sweep regression).
    await expect(byId(page, TID.statusTrial)).not.toHaveText(/—|trial\s*$/i);
    expect(await sweep.currentTrial()).toBe(before);

    // Space advances, A anchors, E excludes — all three survive the Esc.
    await sweep.press('Space');
    await expect
      .poll(() => sweep.currentTrial(), { timeout: SHORT })
      .not.toBe(before);
    const afterSpace = await sweep.currentTrial();

    await sweep.press('a');
    await expect(sweep.chip(afterSpace)).toHaveAttribute('data-state', 'anchored', {
      timeout: SHORT,
    });

    await sweep.press('Space');
    // R33: the cursor commits only at DISPLAY (after the async match), exactly like the first Space
    // above — so poll for it to settle before capturing the tile, or we read the PRE-advance cursor
    // (the anchored tile) and assert E on the wrong trial. (Mirrors the poll on lines 31-34; the
    // ruling under test is R14 — that E still excludes after an Esc — not the commit timing.)
    await expect.poll(() => sweep.currentTrial(), { timeout: SHORT }).not.toBe(afterSpace);
    const toExclude = await sweep.currentTrial();
    await sweep.press('e');
    await expect(sweep.chip(toExclude)).toHaveAttribute('data-state', 'excluded', {
      timeout: SHORT,
    });
  });

  test('R14/R3.2: Escape also dismisses the help tooltip, but does not touch the cursor', async ({
    page,
  }) => {
    const sweep = await enterSweep(page);
    const t = await sweep.currentTrial();
    const help = byId(page, TID.help).first();
    if ((await help.count()) > 0) {
      await help.hover();
      await expect(byId(page, TID.helpTooltip)).toBeVisible({ timeout: SHORT });
      await page.keyboard.press('Escape');
      await expect(byId(page, TID.helpTooltip)).toBeHidden();
    }
    expect(await sweep.currentTrial()).toBe(t); // cursor untouched
  });
});

test.describe('The sweep keys all fire (§3.3)', () => {
  test('R9b/R15: Space ALWAYS advances and places — the rhythm never stalls', async ({ page }) => {
    const sweep = await enterSweep(page);
    const t0 = await sweep.currentTrial();
    await sweep.press('Space');
    await expect.poll(() => sweep.currentTrial(), { timeout: SHORT }).not.toBe(t0);
  });

  test('R-anchor: A anchors the cursor tile (chip → anchored, header count rises)', async ({
    page,
  }) => {
    const sweep = await enterSweep(page);
    const t = await sweep.currentTrial();
    await sweep.press('a');
    await expect(sweep.chip(t)).toHaveAttribute('data-state', 'anchored', { timeout: SHORT });
    expect(await sweep.headerCount(TID.headerAnchored)).toBeGreaterThanOrEqual(1);
  });

  test('R-exclude: E excludes the cursor tile (chip → excluded)', async ({ page }) => {
    const sweep = await enterSweep(page);
    const t = await sweep.currentTrial();
    await sweep.press('e');
    await expect(sweep.chip(t)).toHaveAttribute('data-state', 'excluded', { timeout: SHORT });
  });

  test('R-difference: D toggles Difference mode (aria-pressed flips, and back)', async ({ page }) => {
    const sweep = await enterSweep(page);
    const btn = byId(page, TID.actDifference);
    await expect(btn).toHaveAttribute('aria-pressed', 'false', { timeout: SHORT });
    await sweep.press('d');
    await expect(btn).toHaveAttribute('aria-pressed', 'true');
    await sweep.press('d');
    await expect(btn).toHaveAttribute('aria-pressed', 'false');
  });

  test('R-alternatives: V toggles the ranked alternatives list', async ({ page }) => {
    const sweep = await enterSweep(page);
    await sweep.press('a'); // one anchor so the tile has a field to have alternatives against
    await sweep.press('Space');
    await sweep.press('v');
    await expect(byId(page, TID.alternativesList)).toBeVisible({ timeout: SHORT });
  });

  test('R23: S snaps via a SERVER match request (the committed number is the server’s)', async ({
    page,
  }) => {
    const sweep = await enterSweep(page);
    await sweep.press('a'); // origin
    await sweep.press('Space'); // land a tile to snap
    const snapped = page.waitForRequest(
      (r) =>
        r.method() === 'POST' &&
        (r.url().includes(ROUTES.matchAnchor) || r.url().includes(ROUTES.matchScore)),
      { timeout: SHORT },
    );
    await sweep.press('s');
    await snapped; // the snap is the server's answer, not a browser-side NCC
  });

  test('§3.4: arrow keys nudge the tile 1 px; Shift+arrow nudges 10 px (world coords)', async ({
    page,
  }) => {
    const sweep = await enterSweep(page);
    await sweep.press('a'); // anchor the origin at (0,0) so the cursor tile has a position
    const [x0, y0] = await topLeft(page);
    await sweep.press('ArrowRight');
    const [x1] = await topLeft(page);
    expect(x1 - x0).toBe(1);
    await sweep.press('Shift+ArrowRight');
    const [x2] = await topLeft(page);
    expect(x2 - x1).toBe(10);
    await sweep.press('ArrowDown');
    const [, y1] = await topLeft(page);
    expect(y1 - y0).toBe(1);
  });

  test('R19: the status bar names positions as TOP-LEFT corners', async ({ page }) => {
    await enterSweep(page);
    await expect(byId(page, TID.statusTopleft)).toContainText(/top-left/i, { timeout: SHORT });
  });
});

test.describe('The deliberately-unbound keys do NOTHING (§3, §6.7)', () => {
  test('R12.6: 0 is 1:1 zoom, NOT an alternatives key — it must not move the tile', async ({
    page,
  }) => {
    const sweep = await enterSweep(page);
    await sweep.press('a'); // position the cursor tile at (0,0)
    const before = await topLeft(page);
    await sweep.press('0'); // 1:1 zoom — camera only, never a jump-to-candidate
    const after = await topLeft(page);
    expect(after).toEqual(before);
  });

  test('§6.7: Space is ADVANCE, never a pan modifier — no spaceDown drag trap', async ({ page }) => {
    const sweep = await enterSweep(page);
    const t0 = await sweep.currentTrial();
    // A single Space advances exactly once (it is not a held pan modifier).
    await sweep.press('Space');
    const t1 = await sweep.currentTrial();
    expect(t1).not.toBe(t0);
  });

  test('R-unbound: an unbound letter key (q/j/k) changes no tile state', async ({ page }) => {
    const sweep = await enterSweep(page);
    const t = await sweep.currentTrial();
    const anchored = await sweep.headerCount(TID.headerAnchored);
    const rec = recordMatchAnchor(page);
    for (const k of ['q', 'j', 'k', 'z']) await sweep.press(k);
    expect(await sweep.currentTrial()).toBe(t);
    expect(await sweep.headerCount(TID.headerAnchored)).toBe(anchored);
    expect(rec.bodies.length).toBe(0); // no placement/match was triggered
  });
});
