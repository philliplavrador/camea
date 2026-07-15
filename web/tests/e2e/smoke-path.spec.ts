import { test, expect, type Page } from '@playwright/test';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Home, Sweep, Wizard, TID, byId, answerNextPrompt, ROUTES } from './pages';
import { FIXTURE, SHORT } from './fixture';

/**
 * BEHAVIOUR §8 — the smoke path the v1 verification ran, adapted to the committed synthetic fixture.
 * It touches most of the contract in one flow. Two of §8's steps are NOT reproduced here and are
 * covered elsewhere:
 *   • step 5 (run the solver + watch the ETA) — needs a build → place-eta.spec.ts / solver-fallback (@slow).
 *   • step 12 (KILL the server, cold-load) — Playwright manages the backend as a shared webServer and
 *     cannot kill it mid-test; the client-side round-trip is proven in save-resume.spec.ts instead.
 *
 * This lean smoke stays in the fast lane (no build) and asserts the load-bearing invariants in order.
 */
test('§8 smoke: open → screen → sweep → esc → toggle → jump → opacity/diff → save', async ({
  page,
}) => {
  // 1 — open the fixture: it lists, opens, and excludes NOTHING (R2).
  const home = new Home(page);
  await home.open();
  await expect(home.card().getByTestId(TID.cardSnapshots)).toHaveText(String(FIXTURE.snapshots));
  await home.openFixture();
  const wizard = new Wizard(page);
  await wizard.expectActive('range');
  await expect(byId(page, TID.factGaps)).toHaveText(/none/i, { timeout: SHORT }); // 0 excluded

  // 2 — hover a `?`: the tooltip appears, is not clipped, and Escape dismisses it (R3).
  const help = byId(page, TID.help).first();
  if ((await help.count()) > 0) {
    await help.hover();
    await expect(byId(page, TID.helpTooltip)).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(byId(page, TID.helpTooltip)).toBeHidden();
  }

  // 3 & 4 — Screen: cards each with three buttons, exactly one selected, default Hand place (R6);
  // Exclude opens a gap, Keep closes it (R2.3). ⚠️ The committed synthetic fixture is too small for the
  // blank scan to determine a threshold (it needs ≥20 pass-1 reference frames; the fixture has ≤11), so
  // it proposes nothing and the grid is legitimately empty — the three-way control is covered by
  // screen-step.spec. Where a card exists, exercise it (mirrors step 2's own `count>0` guard).
  await wizard.goto('screen');
  const card = byId(page, TID.screenCard).first();
  if ((await card.count()) > 0) {
    await expect(card).toBeVisible({ timeout: SHORT });
    await expect(card).toHaveAttribute('data-choice', 'hand');
    const trial = Number(await card.getAttribute('data-trial'));
    await card.getByTestId(TID.screenExclude).click();
    await wizard.goto('range');
    await expect(byId(page, TID.factGaps)).not.toHaveText(/none/i, { timeout: SHORT });
    await wizard.goto('screen');
    await page
      .locator(`[data-testid="${TID.screenCard}"][data-trial="${trial}"]`)
      .getByTestId(TID.screenKeep)
      .click();
  }

  // 6 — Sweep: canvas is EMPTY (R9). A on the origin; Space fades the next in ON TOP (R9/R10).
  await wizard.goto('sweep');
  const sweep = new Sweep(page);
  await expect(sweep.canvas()).toBeVisible({ timeout: SHORT });
  expect(await sweep.anchorLayerCount()).toBe(0);
  await sweep.focus();
  await sweep.press('a');
  await expect.poll(() => sweep.anchorLayerCount(), { timeout: SHORT }).toBe(1);
  // Space fades the next tile in (R33: await the cursor commit before reading the landed trial).
  const t = await sweep.advance();

  // 7 — Escape: footer still reads a trial; Space/A/E all survive (R14).
  await sweep.press('Escape');
  expect(await sweep.currentTrial()).toBe(t);
  await sweep.press('a'); // anchor the tile Space landed on
  await expect(sweep.chip(t)).toHaveAttribute('data-state', 'anchored', { timeout: SHORT });

  // 8 — A on an already-anchored tile un-anchors it, KEEPING its position (R11).
  await sweep.press('a');
  await expect(sweep.chip(t)).toHaveAttribute('data-state', 'unverified', { timeout: SHORT });

  // 9 — a digit jump moves the tile without anchoring (R12).
  await sweep.press('2');
  await expect(sweep.chip(t)).not.toHaveAttribute('data-state', 'anchored');

  // 10 — opacity dims the float; Difference mode ignores it (R13.4) — asserted in difference-mode.spec.
  await sweep.setOpacity(15);
  expect(await sweep.floatAlpha()).toBeCloseTo(0.15, 2);

  // 11 — Ctrl+S: the file has an integer cursor and NO EXCLUDED_TRIALS block (R2.4, R14).
  const saved = captureSaveDoc(page);
  answerNextPrompt(page, join(tmpdir(), `camea-smoke-${Date.now()}.camea.json`));
  await page.keyboard.press('Control+s');
  const doc = await saved;
  expect(typeof doc.cursor).toBe('number');
  expect(JSON.stringify(doc)).not.toContain('EXCLUDED_TRIALS');
});

function captureSaveDoc(page: Page): Promise<{ cursor?: unknown; [k: string]: unknown }> {
  return page
    .waitForRequest((r) => r.url().includes(ROUTES.saveAs) && r.method() === 'POST', {
      timeout: SHORT,
    })
    .then((r) => (r.postDataJSON() as { doc: { cursor?: unknown } }).doc);
}
