import { test, expect, type Page } from '@playwright/test';
import { Sweep, Wizard, TID, byId, enterSweep, enterMosaic } from './pages';
import { SHORT } from './fixture';

/**
 * ⭐ **AUTO-SAVE IS THE DURABLE SAVE, AND OPENING THE PROJECT IS THE RESUME** (R29 / R41.4).
 *
 * ⚠️ REWRITTEN 2026-07-25. The previous version drove `Ctrl+S` → `POST /api/documents/save-as` and had
 * been dead at runtime since the 2026-07-24 reframe: **nothing registers a saver any more**, so the
 * keystroke fires into a no-op and every assertion timed out waiting for a request that is never made.
 * Its own header said so and named the fix — drive the round-trip through **open-project + the durable
 * PUT**, and move the `Save…`-to-a-file / `Load a project…` assertions to `export-import.spec.ts`. That
 * is what this file now does.
 *
 * The invariants are unchanged and still his: the persisted document carries an **integer top-level
 * cursor** (R14 — a resume must not land at the top), **no `EXCLUDED_TRIALS` block** (R2.4), and a cold
 * reopen restores **exclusions, anchors and the cursor** (R2.6).
 */

interface SavedDoc {
  cursor?: unknown;
  tiles?: Record<string, { status?: string; state?: string }>;
  [k: string]: unknown;
}

/** The `analysis_id` in the URL — the autosave slot key and the document's own `id`. */
function analysisId(page: Page): string {
  const m = /\/project\/([^/?#]+)/.exec(page.url());
  if (!m) throw new Error(`not on a project URL: ${page.url()}`);
  return m[1];
}

/**
 * The document **as the server has it** — what auto-save actually persisted, not what the client
 * happens to hold. Waits for the indicator to settle first: reading mid-write would race the debounce.
 */
async function persistedDoc(page: Page): Promise<SavedDoc> {
  await expect(byId(page, TID.saveIndicator)).toHaveAttribute('data-state', 'saved', {
    timeout: SHORT,
  });
  const r = await page.request.get(`/api/analyses/${analysisId(page)}/document`);
  expect(r.ok(), `GET document failed: ${r.status()}`).toBe(true);
  return ((await r.json()) as { doc: SavedDoc }).doc;
}

/** Put the sweep into a known state: origin anchored, the next tile excluded. */
async function makeKnownState(sweep: Sweep): Promise<{ anchored: number; excluded: number }> {
  const anchored = await sweep.currentTrial();
  await sweep.press('a'); // anchor the origin
  const excluded = await sweep.advance(); // R33: wait for the cursor to commit to the next tile
  await sweep.press('e'); // exclude the next tile
  return { anchored, excluded };
}

test.describe('R2.4 / R14 — what the durable document contains', () => {
  test('R2.4/R14: the persisted document has an integer top-level cursor and NO EXCLUDED_TRIALS block', async ({
    page,
  }) => {
    const sweep = await enterSweep(page);
    const { anchored, excluded } = await makeKnownState(sweep);

    const doc = await persistedDoc(page);

    // The cursor is an integer, top-level — never null (R14: a resume must not land at the top).
    expect(typeof doc.cursor).toBe('number');
    expect(Number.isInteger(doc.cursor as number)).toBe(true);

    // No EXCLUDED_TRIALS block, ever (R2.4 / §6.1).
    expect(JSON.stringify(doc)).not.toContain('EXCLUDED_TRIALS');

    // The states round-trip: the anchor is on disk as "anchor", the excluded one as excluded.
    expect(doc.tiles?.[String(anchored)]?.status).toBe('anchor');
    const ex = doc.tiles?.[String(excluded)];
    expect(ex?.status === 'excluded' || ex?.state === 'excluded').toBe(true);
  });

  test('🔴 A and E persist UNCONDITIONALLY — the crash net does not wait for the debounce', async ({
    page,
  }) => {
    // W4/R29: every A/E autosaves immediately. An hour of sweeping that only ever autosaved is still
    // an hour of work, and it must be on disk the instant he judges a tile.
    const sweep = await enterSweep(page);
    const anchored = await sweep.currentTrial();
    await sweep.press('a');

    await expect
      .poll(async () => (await persistedDoc(page)).tiles?.[String(anchored)]?.status, {
        timeout: SHORT,
      })
      .toBe('anchor');
  });
});

test.describe('R2.6 / R41.4 — reopen the project cold and resume', () => {
  test('R2.6: a cold reopen restores exclusions, anchors and the CURSOR', async ({ page }) => {
    const sweep = await enterSweep(page);
    const { anchored, excluded } = await makeKnownState(sweep);
    const cursorBefore = await sweep.currentTrial();
    await persistedDoc(page); // durable before we throw the client away
    const id = analysisId(page);

    // ⭐ COLD CLIENT: drop everything the browser holds and open the project from its URL, exactly as
    // the project manager does. Nothing survives in memory; the document on disk is the only memory.
    await page.goto('/');
    await expect(byId(page, TID.manager)).toBeVisible();
    await page.goto(`/project/${id}`);

    // R4.5: opening a project lands on Range. Walk to the sweep to read the restored cursor.
    await expect(byId(page, TID.wizard)).toBeVisible({ timeout: SHORT });
    await new Wizard(page).goto('sweep');
    const resumed = new Sweep(page);
    await expect(resumed.canvas()).toBeVisible({ timeout: SHORT });
    await expect.poll(() => resumed.currentTrial(), { timeout: SHORT }).toBe(cursorBefore);
    await expect(resumed.chip(anchored)).toHaveAttribute('data-state', 'anchored');
    await expect(resumed.chip(excluded)).toHaveAttribute('data-state', 'excluded');
  });

  test('R41.4: the project opens ITS OWN document — no adopt-latest', async ({ page }) => {
    // Two projects on the same dataset. Opening the first must not show the second's work, which is
    // exactly what an "adopt the newest document" shortcut would do.
    const first = await enterSweep(page);
    const anchored = await first.currentTrial();
    await first.press('a');
    await persistedDoc(page);
    const firstId = analysisId(page);

    await page.goto('/');
    await enterMosaic(page); // a second, untouched project
    const secondId = analysisId(page);
    expect(secondId).not.toBe(firstId);

    const secondDoc = await persistedDoc(page);
    expect(secondDoc.tiles?.[String(anchored)]?.status).not.toBe('anchor');

    // ...and the first still has its anchor.
    await page.goto(`/project/${firstId}`);
    await expect
      .poll(async () => (await persistedDoc(page)).tiles?.[String(anchored)]?.status, {
        timeout: SHORT,
      })
      .toBe('anchor');
  });
});
