// ─────────────────────────────────────────────────────────────────────────────
// VIDEO MOSAIC — the second task, end to end against the committed survey video.
//
// The contract under test is the feature's whole point: point Camea at a video and get a
// mosaic with ZERO manual placement — no frame choosing, no keyframe picking, no positioning.
//
// ⭐ **AND ONE FOLDER QUESTION, ASKED LAST** (R43). New project asks only for the video; the build
// starts on Create; the single "where does this go?" comes on the finished screen, and the folder
// he names holds the project AND the mosaic, named after the project. The fast test covers the
// create step's receipts and refusals (and that there is no folder box there any more); the @slow
// test runs the real build through progress → preview → stats → save.
// ─────────────────────────────────────────────────────────────────────────────

import { existsSync } from 'node:fs';
import { test, expect, type Page } from '@playwright/test';
import { PATHS, VIDEO_FIXTURE, freshSaveFolder, SHORT } from './fixture';

/** Through name + task, up to the Video step. */
async function toVideoStep(page: Page, name: string): Promise<void> {
  await page.goto('/');
  await page.getByTestId('new-project').click();
  await page.getByTestId('np-name').fill(name);
  await page.getByTestId('np-name').press('Enter');
  // ⭐ **THE TASK STEP IS REAL AGAIN** (2026-08-14): `Analyze MEA` joined `NewProjectFlow.TASKS`,
  // so "what do you want to do?" has two answers and this flow goes through it. Addressed by
  // `data-task`, never by position — the card order is a design choice and must stay free to move.
  // (This used to click the card only `if ((await card.count()) > 0)`, which was right while the
  // step was skipped and is a race now that it always renders: `count()` does not auto-wait.)
  await page.locator('[data-testid="task-card"][data-task="videomosaic"]').click();
  await expect(page.getByTestId('np-video-path')).toBeVisible({ timeout: SHORT });
}

/** Probe the fixture and create — resolves to the analysis id. No folder is asked for (R43). */
async function createVideoProject(page: Page, name: string): Promise<string> {
  await toVideoStep(page, name);
  const input = page.getByTestId('np-video-path');
  await input.fill(VIDEO_FIXTURE.path);
  await input.press('Enter');
  await expect(page.getByTestId('video-receipt')).toBeVisible({ timeout: SHORT });

  await page.getByTestId('np-create').click();
  await page.waitForURL(/\/project\/[^/]+$/, { timeout: 30_000 });
  return page.url().split('/').pop()!;
}

async function deleteProject(page: Page, id: string): Promise<void> {
  // ⭐ R44: one DELETE, and it takes the whole project. `delete_files` is gone with R42.8.
  await page.request.delete(`/api/projects/${id}`);
}

test('video task: receipt states what the video is; a non-video is refused with the text kept', async ({
  page,
}) => {
  await toVideoStep(page, 'vm receipts');

  // ⭐ R44 — one path, and there is no second one to defer. The app owns where the project goes.
  await expect(page.getByTestId('into-field')).toHaveCount(0);

  // a real file that is not a video: the backend's own refusal, inline, typed text intact (R42.5)
  const junk = `${PATHS.dataParent}/make_synthetic_video.py`;
  const input = page.getByTestId('np-video-path');
  await input.fill(junk);
  await input.press('Enter');
  await expect(page.getByTestId('video-probe-error')).toBeVisible({ timeout: SHORT });
  await expect(input).toHaveValue(/make_synthetic_video\.py$/);

  // the committed survey video probes into a receipt with the video's own measured facts
  await input.fill(VIDEO_FIXTURE.path);
  await input.press('Enter');
  const receipt = page.getByTestId('video-receipt');
  await expect(receipt).toBeVisible({ timeout: SHORT });
  await expect(receipt).toContainText(`${VIDEO_FIXTURE.width}×${VIDEO_FIXTURE.height}`);
  await expect(receipt).toContainText('survey.avi');
});

test('@slow video build: zero manual placement, and NO folder question at all', async ({ page }) => {
  // ⚠️ The delete confirm at the end is a `window.confirm` (R38).
  page.on('dialog', (d) => void d.accept());

  const id = await createVideoProject(page, 'vm build');
  try {
    // Create started the build: he lands on progress with nothing left to decide (R43.2).
    await expect(page.getByTestId('vm-progress')).toBeVisible({ timeout: 30_000 });

    // done: the preview renders. ⚠️ A finished build LANDS ON ELECTRODES — the pipeline opens on
    // the furthest step the document has earned (R46.1), so the mosaic's own controls are one
    // click back. (This assertion used to sit here bare and had been red since the pipeline shell
    // landed; the build screen is reached, not arrived at.)
    await expect(page.getByTestId('vm-preview')).toBeVisible({ timeout: 240_000 });
    await page.getByTestId('pipeline-step-mosaic').click();

    // stats strip + preview render; every keyframe was placed by the machine
    await expect(page.getByTestId('vm-rebuild')).toBeVisible({ timeout: SHORT });
    await expect(page.getByTestId('vm-stats')).toBeVisible();
    await expect(page.getByTestId('vm-preview')).toBeVisible();
    await expect
      .poll(() =>
        page
          .getByTestId('vm-preview')
          .evaluate((el) => (el as HTMLImageElement).naturalWidth),
      )
      .toBeGreaterThan(0);

    // ⛔ **NO SAVE STEP** (R44 retires R43): the project has been in Camea's store since Create,
    // and its artifacts are in that project's own outputs/.
    await expect(page.getByTestId('into-field')).toHaveCount(0);
    await expect(page.getByTestId('vm-save')).toHaveCount(0);
    await expect(page.getByTestId('vm-open-folder')).toHaveCount(0);

    // ⭐ **BROWSE YOUR OUTPUTS** — still the only door to a project's files (R44), now opened by
    // asking rather than stacked under every step (R47).
    await expect(page.getByTestId('outputs-panel')).toHaveCount(0);
    await page.getByTestId('vm-files').click();
    const panel = page.getByTestId('outputs-panel');
    await expect(panel).toBeVisible({ timeout: SHORT });
    const rows = panel.getByTestId('output-row');
    await expect(rows).toHaveCount(4);
    await expect(panel.getByTestId('output-row').filter({ hasText: 'vm build.png' })).toBeVisible();

    // ⭐ **PICK ONE, NAME A FOLDER, TAKE A COPY** — the one way work leaves Camea.
    const dir = freshSaveFolder('vm-copy');
    await panel
      .getByTestId('output-row')
      .filter({ hasText: 'vm build.png' })
      .getByTestId('output-pick')
      .check();
    const dest = panel.getByTestId('copy-into-field').getByTestId('path-input');
    await dest.fill(dir);
    await dest.press('Enter');
    await expect(panel.getByTestId('outputs-copied')).toBeVisible({ timeout: SHORT });
    await expect.poll(() => existsSync(`${dir}/vm build.png`), { timeout: SHORT }).toBe(true);
    // ⛔ A copy, not a move — and only what he ticked.
    expect(existsSync(`${dir}/vm build-positions.csv`)).toBe(false);
    await expect(rows).toHaveCount(4);

    // it was an ordinary, listed project the whole time — never a draft to be saved
    await page.goto('/');
    await expect(page.getByText('vm build', { exact: true }).first()).toBeVisible({
      timeout: SHORT,
    });
  } finally {
    await deleteProject(page, id);
  }
});
