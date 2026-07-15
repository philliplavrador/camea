import { test, expect } from '@playwright/test';
import { Wizard, TID, byId, enterMosaic, enterSweep } from './pages';
import { SHORT } from './fixture';

/**
 * STRIP THE PROSE — explanations live behind ONE reusable hover `?` (R3), and every non-self-evident
 * control carries its OWN `?` (R7). No screen renders an explanatory paragraph.
 */
test.describe('R3 — the help `?` component', () => {
  test('R3.1: no wizard screen renders a long explanatory paragraph', async ({ page }) => {
    const wizard = new Wizard(page);
    await enterMosaic(page);
    for (const step of ['range', 'screen', 'place'] as const) {
      if (await wizard.isLocked(step)) continue;
      await wizard.goto(step);
      await expect(byId(page, TID.wizard)).toBeVisible({ timeout: SHORT });
      // A "tool, not an explainer": no <p> longer than a short sentence lives in the pane body.
      const longParas = await page
        .locator(`[data-testid="${TID.wizard}"] p`)
        .evaluateAll((ps) => ps.filter((p) => (p.textContent ?? '').trim().length > 160).length);
      expect(longParas, `the ${step} screen must not carry an explanatory paragraph`).toBe(0);
    }
  });

  test('R3.2/R3.4: the `?` opens a body-level, position:fixed tooltip and is keyboard-focusable', async ({
    page,
  }) => {
    const wizard = new Wizard(page);
    await enterMosaic(page);
    await wizard.goto('range');
    const mark = byId(page, TID.help).first();
    await expect(mark).toBeVisible({ timeout: SHORT });
    await expect(mark).toHaveAttribute('tabindex', '0'); // focusable (R3.2)
    await mark.hover();
    const tip = byId(page, TID.helpTooltip);
    await expect(tip).toBeVisible();
    // Body-level and fixed, or it is clipped inside an overflow:auto pane (R3.4).
    const position = await tip.evaluate((el) => getComputedStyle(el).position);
    expect(position).toBe('fixed');
  });

  test('R3.2: the tooltip is dismissed on Escape', async ({ page }) => {
    const wizard = new Wizard(page);
    await enterMosaic(page);
    await wizard.goto('range');
    const mark = byId(page, TID.help).first();
    await mark.hover();
    await expect(byId(page, TID.helpTooltip)).toBeVisible({ timeout: SHORT });
    await page.keyboard.press('Escape');
    await expect(byId(page, TID.helpTooltip)).toBeHidden();
  });

  test('R3.3: a `?` with an EMPTY body hides itself (never promises an explanation it lacks)', async ({
    page,
  }) => {
    // Any rendered help mark must not be empty: an empty one carries data-empty and is not displayed.
    const wizard = new Wizard(page);
    await enterMosaic(page);
    await wizard.goto('range');
    const emptyVisible = await byId(page, TID.help)
      .filter({ has: page.locator('[data-empty="true"]') })
      .count();
    // If any help marks are flagged empty, none of them may be visible.
    for (let i = 0; i < emptyVisible; i++) {
      await expect(
        byId(page, TID.help).filter({ has: page.locator('[data-empty="true"]') }).nth(i),
      ).toBeHidden();
    }
  });
});

test.describe('R7 — every non-self-evident control carries its own `?`', () => {
  test('R7.1: all seven sweep action buttons carry a `?`', async ({ page }) => {
    await enterSweep(page);
    const actions = [
      TID.actAnchor,
      TID.actExclude,
      TID.actNext,
      TID.actReplay,
      TID.actDifference,
      TID.actAlternatives,
      TID.actSnap,
    ];
    for (const id of actions) {
      const btn = byId(page, id);
      await expect(btn, `${id} must exist`).toBeVisible({ timeout: SHORT });
      // Its OWN `?` — check within the control's group, not merely "nearby" (R7.5 false-pass trap).
      const help = btn.locator('xpath=ancestor-or-self::*[1]//*[@data-testid="help"]').first();
      await expect(help, `${id} must carry its own help ?`).toHaveCount(1);
    }
  });

  test('R7.4: the Advanced drawer says it is off the validated path', async ({ page }) => {
    const wizard = new Wizard(page);
    await enterMosaic(page);
    await wizard.goto('place');
    const drawer = byId(page, TID.placeAdvanced);
    await expect(drawer).toBeVisible({ timeout: SHORT });
    await drawer.click(); // open the <details>
    await expect(drawer).toContainText(/off the validated path|shipped 312\/312 build used the defaults/i);
  });
});
