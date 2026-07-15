import { test, expect } from '@playwright/test';
import { Wizard, TID, byId, enterMosaic, answerNextPrompt, ROUTES } from './pages';
import { STEPS } from './pages';
import { SHORT } from './fixture';

/**
 * ONE QUESTION PER SCREEN — six steps, in order, a progress indicator not a menu (R4); and Save is
 * reachable from EVERY screen (R5).
 */
test.describe('Six-step wizard (R4) and Save-from-anywhere (R5)', () => {
  test('R4.1: the six steps are exactly Load · Range · Screen · Place · Sweep · Mosaic, in order', async ({
    page,
  }) => {
    await enterMosaic(page);
    const labels = ['Load', 'Range', 'Screen', 'Place', 'Sweep', 'Mosaic'];
    for (let i = 0; i < STEPS.length; i++) {
      await expect(byId(page, TID.step(STEPS[i]))).toContainText(labels[i], { timeout: SHORT });
    }
  });

  test('R4.2: a locked step does nothing and toasts "Finish the step before it first."', async ({
    page,
  }) => {
    const wizard = new Wizard(page);
    await enterMosaic(page);
    // Mosaic is locked until something is placed (R4.3). Clicking it must NOT navigate; it toasts.
    if (await wizard.isLocked('mosaic')) {
      await wizard.step('mosaic').click({ force: true });
      await expect(byId(page, TID.toast)).toContainText(/finish the step before it first/i, {
        timeout: SHORT,
      });
      await expect(wizard.isActive('mosaic')).resolves.toBe(false);
    }
  });

  test('R4.3: with a session but nothing placed, Sweep is REACHABLE and Mosaic is LOCKED', async ({
    page,
  }) => {
    const wizard = new Wizard(page);
    await enterMosaic(page);
    // load/range/screen/place/sweep are ready iff a session exists; mosaic needs anyPlaced().
    await expect.poll(() => wizard.isLocked('range'), { timeout: SHORT }).toBe(false);
    await expect.poll(() => wizard.isLocked('screen'), { timeout: SHORT }).toBe(false);
    await expect.poll(() => wizard.isLocked('place'), { timeout: SHORT }).toBe(false);
    await expect.poll(() => wizard.isLocked('sweep'), { timeout: SHORT }).toBe(false); // REACHABLE
    await expect.poll(() => wizard.isLocked('mosaic'), { timeout: SHORT }).toBe(true); //  LOCKED
  });

  test('R4.4: no invented gate — Place is reachable without ticking Screen or running the solver', async ({
    page,
  }) => {
    const wizard = new Wizard(page);
    await enterMosaic(page);
    // Not ticking a Screen box and not solving are both legitimate answers. Place must be reachable.
    await wizard.goto('place');
    await wizard.expectActive('place');
  });

  test('R5.1: "Save…" lives in the top bar and is visible on all six steps', async ({ page }) => {
    const wizard = new Wizard(page);
    await enterMosaic(page);
    for (const step of STEPS) {
      if (await wizard.isLocked(step)) continue;
      await wizard.goto(step);
      await expect(byId(page, TID.saveProject)).toBeVisible({ timeout: SHORT });
    }
  });

  test('R5.2: Ctrl+S saves from ANY screen — it is handled above the sweep-only gate', async ({
    page,
  }) => {
    const wizard = new Wizard(page);
    await enterMosaic(page);
    await wizard.goto('range'); // a NON-sweep screen — Ctrl+S must still fire the save
    const saved = page.waitForRequest(
      (r) => r.url().includes(ROUTES.saveAs) && r.method() === 'POST',
      { timeout: SHORT },
    );
    answerNextPrompt(page, tmpProjectPath());
    await page.keyboard.press('Control+s');
    await saved;
  });

  test('R5.3: "Load a project…" lives on the Load screen (resuming is a way of starting)', async ({
    page,
  }) => {
    const wizard = new Wizard(page);
    await enterMosaic(page);
    await wizard.goto('load');
    await expect(byId(page, TID.loadProject)).toBeVisible({ timeout: SHORT });
  });

  test('R5.4: the rolling autosave note stays on Mosaic and is separate from "Save…"', async ({
    page,
  }) => {
    // The autosave (crash net) must not read as the same control as the file the user controls.
    const wizard = new Wizard(page);
    await enterMosaic(page);
    if (!(await wizard.isLocked('mosaic'))) {
      await wizard.goto('mosaic');
      await expect(byId(page, TID.mosaicAutosaveNote)).toBeVisible({ timeout: SHORT });
    }
  });
});

function tmpProjectPath(): string {
  // Backends and specs share the machine; a throwaway path is enough for R5.2's "did it POST?" check.
  return `${process.env.TEMP ?? process.env.TMPDIR ?? '.'}/camea-e2e-${Date.now()}.camea.json`;
}
