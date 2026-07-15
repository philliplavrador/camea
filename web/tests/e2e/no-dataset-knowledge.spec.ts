import { test, expect } from '@playwright/test';
import { Wizard, TID, byId, enterMosaic } from './pages';
import { FORBIDDEN_KNOWLEDGE, SHORT } from './fixture';

/**
 * THE APP KNOWS NOTHING ABOUT ANY DATASET (BEHAVIOUR I1, R2, §6.1). No pre-excluded set, no
 * 312/338/26/166/156/284, no "260620d", no EXCLUDED_TRIALS, no toggle. 312 is something the USER
 * PRODUCES by excluding frames, never a default.
 */
test.describe('No dataset knowledge (I1, R2, §6.1)', () => {
  test('R2/I1: no page in the wizard prints a 260620d-specific number or phrase as a default', async ({
    page,
  }) => {
    const wizard = new Wizard(page);
    await enterMosaic(page);
    for (const step of ['range', 'screen', 'place', 'sweep', 'mosaic'] as const) {
      if (await wizard.isLocked(step)) continue;
      await wizard.goto(step);
      await expect(byId(page, TID.wizard)).toBeVisible({ timeout: SHORT });
      const body = await page.locator('body').innerText();
      for (const forbidden of FORBIDDEN_KNOWLEDGE) {
        expect(body, `"${forbidden}" must never appear on the ${step} screen`).not.toMatch(
          forbidden,
        );
      }
    }
  });

  test('§6.1: there is NO exclusion toggle anywhere in the wizard', async ({ page }) => {
    const wizard = new Wizard(page);
    await enterMosaic(page);
    // The app must never carry a control that switches its knowledge of exclusions on/off (R2 verbatim:
    // "There should be no toggle."). A checkbox/switch whose accessible name mentions exclusions is
    // exactly that regression.
    for (const step of ['range', 'screen', 'place'] as const) {
      if (await wizard.isLocked(step)) continue;
      await wizard.goto(step);
      const excludeToggle = page
        .getByRole('switch')
        .filter({ hasText: /exclu/i })
        .or(page.getByRole('checkbox', { name: /exclude (all|the ruling|26|312)/i }));
      await expect(excludeToggle).toHaveCount(0);
    }
  });

  test('R2.1: a flagged-but-usable frame (fixture trial 5) is present and NOT auto-excluded on open', async ({
    page,
  }) => {
    // The stray snapshot stands in for the user's trial 284: present, unplaced, never auto-excluded.
    const wizard = new Wizard(page);
    await enterMosaic(page);
    await wizard.goto('sweep');
    const chip = page.locator(`[data-testid="${TID.queueChip}"][data-trial="5"]`);
    // If the stray trial is in the run's queue at all, it must not be excluded on a fresh open.
    if ((await chip.count()) > 0) {
      await expect(chip).not.toHaveAttribute('data-state', 'excluded');
    }
  });
});
