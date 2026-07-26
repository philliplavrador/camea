import { test, expect, type Page } from '@playwright/test';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { writeFileSync } from 'node:fs';
import { Sweep, TID, byId, enterSweep, enterMosaic, answerNextPrompt, ROUTES } from './pages';
import { SHORT } from './fixture';

/**
 * THE PROJECT FILE IS THE APP'S ONLY MEMORY (R2). Save → close → load restores exclusions, every
 * placement, which tiles were anchored, and the CURSOR (an integer, never null — R14). The file
 * carries NO EXCLUDED_TRIALS block, and loading an old file that has one deletes it (R2.4). The whole
 * round-trip is drivable only because headless save/load fall back to window.prompt (R38).
 *
 * ⚠️ SUPERSEDED 2026-07-24 (compiles, but stale at runtime — needs a browser-in-loop rewrite). Auto-save
 * is the durable save now and projects persist automatically; "resume" is **opening the project from the
 * manager**, not `Save…`→`Load a project…`. The invariants here (integer cursor, no EXCLUDED_TRIALS,
 * states persist) still hold — but they should be driven through open-project + the durable PUT, and the
 * `Save…`-to-a-file / `Load a project…` assertions belong in a new `export-import.spec.ts` instead.
 */

interface SavedDoc {
  cursor?: unknown;
  tiles?: Record<string, { status?: string; state?: string }>;
  [k: string]: unknown;
}

/** Ctrl+S with the prompt answered; return the doc the client POSTed to /api/documents/save-as. */
async function saveAndCaptureDoc(page: Page, path: string): Promise<SavedDoc> {
  const req = page.waitForRequest(
    (r) => r.url().includes(ROUTES.saveAs) && r.method() === 'POST',
    { timeout: SHORT },
  );
  answerNextPrompt(page, path);
  await page.keyboard.press('Control+s');
  const body = (await req).postDataJSON() as { doc: SavedDoc };
  return body.doc;
}

/** Put the sweep into a known state: origin anchored, one tile excluded. Returns the trials used. */
async function makeKnownState(sweep: Sweep): Promise<{ anchored: number; excluded: number }> {
  const anchored = await sweep.currentTrial();
  await sweep.press('a'); // anchor the origin
  const excluded = await sweep.advance(); // R33: wait for the cursor to commit to the next tile
  await sweep.press('e'); // exclude the next tile
  return { anchored, excluded };
}

test.describe('R2.4 / R14 — what the saved file contains', () => {
  test('R2.4/R14: the saved file has an integer top-level cursor and NO EXCLUDED_TRIALS block', async ({
    page,
  }) => {
    const sweep = await enterSweep(page);
    const { anchored, excluded } = await makeKnownState(sweep);

    const doc = await saveAndCaptureDoc(page, tmpProject());

    // The cursor is an integer, top-level — never null (R14: a resume must not land at the top).
    expect(typeof doc.cursor).toBe('number');
    expect(Number.isInteger(doc.cursor as number)).toBe(true);

    // No EXCLUDED_TRIALS block, ever (R2.4 / §6.1).
    expect(JSON.stringify(doc)).not.toContain('EXCLUDED_TRIALS');

    // The states round-trip: the anchor is on disk as status "anchor", the excluded one as excluded.
    expect(doc.tiles?.[String(anchored)]?.status).toBe('anchor');
    const ex = doc.tiles?.[String(excluded)];
    expect(ex?.status === 'excluded' || ex?.state === 'excluded').toBe(true);
  });

  test('R2.4: loading an old file WITH an EXCLUDED_TRIALS block deletes it on re-save', async ({
    page,
  }) => {
    // Base a tampered file on a REAL saved doc so the loader accepts it, then inject the dead block.
    const sweep = await enterSweep(page);
    await makeKnownState(sweep);
    const realDoc = await saveAndCaptureDoc(page, tmpProject());
    (realDoc as Record<string, unknown>).EXCLUDED_TRIALS = { trials: [999], n: 1, locked: true };
    const tampered = tmpProject();
    writeFileSync(tampered, JSON.stringify(realDoc), 'utf8');

    // Load it back (cold), then re-save and confirm the block is GONE — never resurrected.
    await page.reload();
    const { wizard } = await enterMosaic(page);
    await wizard.goto('load');
    const loaded = page.waitForRequest((r) => r.url().includes(ROUTES.load), { timeout: SHORT });
    answerNextPrompt(page, tampered);
    await byId(page, TID.loadProject).click();
    await loaded;
    // Wait for the load to FINISH adopting the document (the resume toast) before re-saving — otherwise
    // Ctrl+S fires mid-load, against a document still being swapped in. (R2.6 waits the same way.)
    await expect(byId(page, TID.toast)).toContainText(/resumed/i, { timeout: SHORT });

    const resaved = await saveAndCaptureDoc(page, tmpProject());
    expect(JSON.stringify(resaved)).not.toContain('EXCLUDED_TRIALS');
  });
});

test.describe('R2.6 / R38 — save, reload cold, resume', () => {
  test('R2.6: reloading and loading the project restores exclusions, anchors and the CURSOR', async ({
    page,
  }) => {
    const sweep = await enterSweep(page);
    const { anchored, excluded } = await makeKnownState(sweep);
    const cursorBefore = await sweep.currentTrial();

    const path = tmpProject();
    await saveAndCaptureDoc(page, path);

    // Cold client: reload the page, re-open the dataset, and load the project file.
    await page.reload();
    const { wizard } = await enterMosaic(page);
    await wizard.goto('load');
    answerNextPrompt(page, path);
    await byId(page, TID.loadProject).click();

    // The resume toast names both counts (R2.6: "Resumed — N anchored, M excluded.").
    await expect(byId(page, TID.toast)).toContainText(/resumed/i, { timeout: SHORT });
    await expect(byId(page, TID.toast)).toContainText(/anchored/i);
    await expect(byId(page, TID.toast)).toContainText(/excluded/i);

    // The cursor lands back where he was — an integer, not the top of the run.
    await wizard.goto('sweep');
    const resumed = new Sweep(page);
    await expect.poll(() => resumed.currentTrial(), { timeout: SHORT }).toBe(cursorBefore);
    await expect(resumed.chip(anchored)).toHaveAttribute('data-state', 'anchored');
    await expect(resumed.chip(excluded)).toHaveAttribute('data-state', 'excluded');
  });

  test('R38: headless keeps a window.prompt path for BOTH save and load (or none of this is drivable)', async ({
    page,
  }) => {
    // The proof is operational: a save is answerable by a prompt (asserted by the request firing).
    const sweep = await enterSweep(page);
    await sweep.press('a');
    const req = page.waitForRequest((r) => r.url().includes(ROUTES.saveAs), { timeout: SHORT });
    answerNextPrompt(page, tmpProject());
    await page.keyboard.press('Control+s');
    await req; // if the dialog were not window.prompt, Playwright could not answer it and this hangs
  });
});

function tmpProject(): string {
  return join(tmpdir(), `camea-e2e-${Date.now()}-${Math.random().toString(36).slice(2)}.camea.json`);
}
