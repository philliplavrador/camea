import { test, expect, type Page } from '@playwright/test';
import { TID, byId, enterSweep } from './pages';

/**
 * DIFFERENCE MODE INVARIANTS (BEHAVIOUR §3.5) and the opacity slider's hands-off rule (R13.4).
 *
 * These are CANVAS PIXEL PROBES: the only way to catch the two bugs the rulings exist for is to read
 * the composited pixels, exactly as the v1 verification did. We force the LIGHT theme first, because
 * that is the dangerous case — the light canvas is ~#eef1f4 (bright), so "clear = theme colour" would
 * make half the difference image a photographic negative. Black is the only correct clear.
 */

/** Force the light theme so the canvas clear colour is a BRIGHT grey — the case §3.5 is about. */
async function forceLightTheme(page: Page) {
  await page.emulateMedia({ colorScheme: 'light' });
  await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'light'));
}

const brightness = ([r, g, b]: number[]) => (r + g + b) / 3;

test.describe('Difference mode — the clear is BLACK, not the theme colour (§3.5)', () => {
  test('§3.5: a background canvas pixel is the theme colour in normal view but BLACK in Difference mode', async ({
    page,
  }) => {
    await forceLightTheme(page);
    const sweep = await enterSweep(page);
    await sweep.press('f'); // fit — centre the one floating tile so a corner is background
    await sweep.settleFade();

    // Probe a corner well away from the centred tile — this is the "no reference here" clear region.
    const corner = await sweep.pixel(6, 6);
    // Normal view, light theme: the clear is the bright canvas colour (NOT black).
    expect(brightness(corner), 'normal-mode clear should be the light theme colour').toBeGreaterThan(
      120,
    );

    await sweep.press('d'); // Difference mode ON
    expect(await sweep.diffOn()).toBe(true);
    await sweep.settleFade();
    const cornerDiff = await sweep.pixel(6, 6);
    // In diff mode the clear MUST be black — |tile − black| where nothing covers = 0 difference.
    expect(brightness(cornerDiff), 'diff-mode clear MUST be black').toBeLessThan(24);
    expect(Math.max(...cornerDiff.slice(0, 3))).toBeLessThan(24);
  });
});

test.describe('R13 — the opacity slider dims the float, but Difference mode ignores it', () => {
  test('R13.2: in NORMAL view the opacity slider dims the floating tile', async ({ page }) => {
    await forceLightTheme(page);
    const sweep = await enterSweep(page);
    await sweep.press('f');
    await sweep.settleFade();
    const { w, h } = await sweep.size();
    const cx = Math.floor(w / 2);
    const cy = Math.floor(h / 2);

    await sweep.setOpacity(100);
    await sweep.settleFade();
    const full = brightness(await sweep.pixel(cx, cy));

    await sweep.setOpacity(15);
    await sweep.settleFade();
    const dim = brightness(await sweep.pixel(cx, cy));

    // Dimming the float toward the light background changes the centre pixel materially.
    expect(Math.abs(full - dim)).toBeGreaterThan(12);
  });

  test('R13.4: 🔴 Difference mode IGNORES the opacity slider (a is forced to 1)', async ({
    page,
  }) => {
    await forceLightTheme(page);
    const sweep = await enterSweep(page);
    await sweep.press('f');
    await sweep.press('d'); // Difference mode ON
    await sweep.settleFade();
    const { w, h } = await sweep.size();
    const cx = Math.floor(w / 2);
    const cy = Math.floor(h / 2);

    await sweep.setOpacity(100);
    await sweep.settleFade();
    const a100 = brightness(await sweep.pixel(cx, cy));

    await sweep.setOpacity(15);
    await sweep.settleFade();
    const a15 = brightness(await sweep.pixel(cx, cy));

    // Scaling alpha would drag the difference toward the background and weaken the doubling signal.
    // The measured contract: the diff-mode centre is the SAME at 15 % and 100 %.
    expect(Math.abs(a100 - a15)).toBeLessThan(8);
  });

  test('R13.1: the opacity slider ranges 15–100, step 5, default 100', async ({ page }) => {
    const sweep = await enterSweep(page);
    const slider = byId(page, TID.opacitySlider);
    await expect(slider).toBeVisible();
    await expect(slider).toHaveAttribute('min', '15');
    await expect(slider).toHaveAttribute('max', '100');
    await expect(slider).toHaveAttribute('step', '5');
    expect(await sweep.floatAlpha()).toBeCloseTo(1, 2); // default 100 %
  });
});
