import { test, expect, type Page } from '@playwright/test';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { TID, byId, enterSweep, answerNextPrompt, ROUTES } from './pages';
import { SHORT } from './fixture';

/**
 * ⭐ **EXPORTING A PROJECT TO A FILE** — split out of `save-resume.spec.ts` on 2026-07-25, which is
 * where that file's own header said this belonged once auto-save became the durable write. Auto-save
 * persists your work (see `save-resume.spec.ts`); *this* is the separate act of writing a
 * `.camea.json` you can hand to someone.
 *
 * ⚠️ **R38 IS WHY THIS IS TESTABLE AT ALL.** Headless has no pywebview, so `/api/dialog/*` returns 501
 * and the save falls back to `window.prompt()` — which Playwright can answer. Keep a
 * headless-answerable path for the dialog, or this goes dark.
 *
 * ⛔ **THE IMPORT HALF IS NOT TESTED HERE, AND DELIBERATELY SO.** R2.4 ("loading an old file with an
 * `EXCLUDED_TRIALS` block deletes it") has **no UI to drive**: `LoadStep`'s *"Load a project…"* button
 * takes an `onLoadProject` prop that nothing has passed since the 2026-07-24 project-manager reframe,
 * so it only raises a toast. The rule itself is alive and guarded at the layer that owns it —
 * `core/document.migrate()`, pinned by `tests/unit/test_mosaic_document.py` (the block is dropped, a
 * warning is emitted, and the re-saved file does not contain it). Re-testing it through a button that
 * does nothing would assert nothing. **If file-import is ever wired up, add the round-trip here.**
 */

interface SavedDoc {
  cursor?: unknown;
  [k: string]: unknown;
}

function tmpProject(): string {
  return join(tmpdir(), `camea-e2e-${Date.now()}-${Math.random().toString(36).slice(2)}.camea.json`);
}

function analysisId(page: Page): string {
  const m = /\/project\/([^/?#]+)/.exec(page.url());
  if (!m) throw new Error(`not on a project URL: ${page.url()}`);
  return m[1];
}

/**
 * Export ONE project to `path` via its own card's Export (native dialog → prompt, R38).
 *
 * ⚠️ Addressed by `data-project-id`, never `.first()`: projects accumulate across tests in a run, so
 * "the first card" is whichever the sort happened to put on top — a different project's document.
 */
async function exportTo(page: Page, id: string, path: string): Promise<SavedDoc> {
  const card = page.locator(`[data-testid="${TID.projectCard}"][data-project-id="${id}"]`);
  await expect(card).toBeVisible({ timeout: SHORT });
  const req = page.waitForRequest(
    (r) => r.url().includes(ROUTES.saveAs) && r.method() === 'POST',
    { timeout: SHORT },
  );
  answerNextPrompt(page, path);
  await card.locator('..').getByTestId(TID.projectExport).click();
  const body = (await req).postDataJSON() as { doc: SavedDoc };
  return body.doc;
}

test.describe('R38 — headless keeps a window.prompt path, or none of this is drivable', () => {
  test('R38: Export answers through window.prompt and POSTs the project document', async ({
    page,
  }) => {
    const sweep = await enterSweep(page);
    await sweep.press('a');
    await expect(byId(page, TID.saveIndicator)).toHaveAttribute('data-state', 'saved', {
      timeout: SHORT,
    });
    const id = analysisId(page);

    await page.goto('/');
    await expect(byId(page, TID.manager)).toBeVisible();

    // If the dialog were not window.prompt, Playwright could not answer it and this would hang.
    const doc = await exportTo(page, id, tmpProject());

    // It exported THIS project's real document — an integer cursor (R14), and no dataset knowledge.
    expect(typeof doc.cursor).toBe('number');
    expect(JSON.stringify(doc)).not.toContain('EXCLUDED_TRIALS');
  });
});
