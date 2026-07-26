import { test, expect } from '@playwright/test';
import { Wizard, TID, byId, enterMosaic } from './pages';
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

  // R5 is reframed (2026-07-24): auto-save IS the save, so there is no manual Save button — a quiet
  // "Saved" indicator instead, and Ctrl+S FORCES the durable save (a PUT), from any screen.
  test('R5.1 (reframed): the "Saved" indicator is visible on every step while a project is open', async ({
    page,
  }) => {
    const wizard = new Wizard(page);
    await enterMosaic(page);
    for (const step of STEPS) {
      if (await wizard.isLocked(step)) continue;
      await wizard.goto(step);
      await expect(byId(page, TID.saveIndicator)).toBeVisible({ timeout: SHORT });
    }
  });

  test('R5.2 (reframed): there is NO manual Save button anywhere — auto-save is the save', async ({
    page,
  }) => {
    await enterMosaic(page);
    await expect(page.getByTestId('save-project')).toHaveCount(0);
  });

  test('R5.3 (reframed): Ctrl+S from ANY screen forces the durable save now (a PUT, not a save-as)', async ({
    page,
  }) => {
    const wizard = new Wizard(page);
    await enterMosaic(page);
    await wizard.goto('range'); // a NON-sweep screen — Ctrl+S must still flush from anywhere
    const saved = page.waitForRequest(
      (r) => r.url().includes('/document') && r.method() === 'PUT',
      { timeout: SHORT },
    );
    await page.keyboard.press('Control+s');
    await saved;
  });
});
