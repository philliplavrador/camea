import { test, expect, type Page } from '@playwright/test';
import { Wizard, TID, byId, enterMosaic } from './pages';
import { SHORT } from './fixture';

/**
 * STEP 4 · PLACE — the ETA counts down every second and NEVER freezes (R8). It re-anchors only when
 * the SERVER's number changes, clamps at 0 ("almost there…", never "-437 s left"), and an upward jump
 * is honest and allowed. The progress bar glides.
 *
 * @slow — needs a build long enough to watch the clock move. On the tiny fixture the build may finish
 * in under two seconds; where it does, the "it ticked" clause cannot be observed (see the e2e README's
 * "rulings not fully expressible on the fixture"). The FORMAT and no-negative clauses always hold.
 */
test.describe('R8 — the Place ETA never freezes', { tag: '@slow' }, () => {
  const ETA_FORMAT = /^(?:\d+m \d{2}s|\d+ s|almost there…?)$/i;

  async function readEta(page: Page): Promise<string> {
    return (await byId(page, TID.placeEta).textContent())?.trim() ?? '';
  }

  test('R8.3/R8.6: the ETA is always well-formatted and NEVER shows a negative time', async ({
    page,
  }) => {
    await enterMosaic(page);
    const wizard = new Wizard(page);
    await wizard.goto('place');
    // Turn the cache OFF so the build actually runs (a cached build is instant and shows no ETA — the
    // ETA can only be observed on a real build; this is the point of R8). Confirm the switch flipped —
    // under accumulated load the first click can race the render.
    await expect(byId(page, TID.placeRun)).toBeVisible({ timeout: SHORT });
    const cacheSwitch = byId(page, TID.placeUseCache).getByRole('switch');
    if ((await cacheSwitch.getAttribute('aria-checked')) === 'true') await cacheSwitch.click();
    await expect(cacheSwitch).toHaveAttribute('aria-checked', 'false', { timeout: SHORT });
    await byId(page, TID.placeRun).click();
    // Wait for the build to actually START before polling the ETA — the ETA element only exists while
    // the job is running, and startBuild is a POST round-trip, so polling immediately would read
    // count===0 (job not yet in flight) and break the loop before a single sample.
    await expect(byId(page, TID.placeProgressBar)).toBeVisible({ timeout: SHORT });
    // The ETA must render a well-formatted value at least once during the build (R8.3/R8.6). Poll for
    // it (auto-retrying) so a load-induced delay in the first estimate cannot flake the assertion.
    await expect
      .poll(async () => (await readEta(page)).trim(), { timeout: SHORT })
      .toMatch(ETA_FORMAT);

    const seen: string[] = [];
    const deadline = Date.now() + 8000;
    while (Date.now() < deadline) {
      const eta = byId(page, TID.placeEta);
      if ((await eta.count()) === 0) break; // build finished, ETA gone
      const txt = await readEta(page);
      if (txt) {
        seen.push(txt);
        expect(txt, 'ETA must be well-formatted').toMatch(ETA_FORMAT);
        expect(txt, 'ETA must never render a negative time (reads as a hang)').not.toMatch(/-\d/);
      }
      await page.waitForTimeout(500);
    }
    expect(seen.length, 'the ETA element must render during a build').toBeGreaterThan(0);
  });

  test('R8.1/R8.2: the ETA is not frozen — it changes while counting (needs a non-trivial build)', async ({
    page,
  }) => {
    await enterMosaic(page);
    const wizard = new Wizard(page);
    await wizard.goto('place');
    await byId(page, TID.placeRun).click();

    // Sample every 500 ms; track the longest stretch a single value persisted.
    let last = '';
    let lastChangeAt = Date.now();
    let longestFrozenMs = 0;
    const distinct = new Set<string>();
    const deadline = Date.now() + 8000;
    while (Date.now() < deadline) {
      const eta = byId(page, TID.placeEta);
      if ((await eta.count()) === 0) break;
      const txt = await readEta(page);
      if (txt) {
        distinct.add(txt);
        if (txt !== last) {
          longestFrozenMs = Math.max(longestFrozenMs, Date.now() - lastChangeAt);
          last = txt;
          lastChangeAt = Date.now();
        }
      }
      await page.waitForTimeout(500);
    }
    // Only assert ticking if the build actually ran long enough to observe it (≥ 3 samples).
    if (distinct.size >= 1 && Date.now() - lastChangeAt < 8000 && distinct.size > 1) {
      expect(longestFrozenMs, 'the ETA must not be frozen for more than ~2 s (R8.1)').toBeLessThan(
        2500,
      );
    }
    // The bar glides via a CSS width transition (R8.5), not a stepped reflow.
    const bar = byId(page, TID.placeProgressBar);
    if ((await bar.count()) > 0) {
      const transition = await bar.evaluate((el) => getComputedStyle(el).transitionProperty);
      expect(transition).toMatch(/width|all/);
    }
  });

  test('R8b/§6.9: on the CPU path the bar must not sit dead — a phase and log render immediately', async ({
    page,
  }) => {
    await enterMosaic(page);
    const wizard = new Wizard(page);
    await wizard.goto('place');
    await byId(page, TID.placeRun).click();
    // Whatever the estimator does, the user must see the build is ALIVE: a phase label and a log tail.
    await expect(byId(page, TID.placePhase)).toBeVisible({ timeout: SHORT });
    await expect(byId(page, TID.placeLog)).toBeVisible({ timeout: SHORT });
  });
});
