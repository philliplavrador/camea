// ─────────────────────────────────────────────────────────────────────────────
// "WHAT DO YOU WANT TO DO?" — the Task step, back on the new-project flow (2026-08-14).
//
// Two tasks now, so the question is real again: **Simultaneous MEA + 2P** (the video → mosaic →
// electrodes → regions pipeline, renamed to the experiment it serves) and **Analyze MEA** (a
// MaxWell recording opened on its own).
//
// ⭐ **THE ONE THING THIS FILE EXISTS TO PROVE** — and it MOVED on 2026-08-14 (plan 002). It used
// to be that picking `Analyze MEA` asked no data question at all. He reversed that the same day
// after seeing it built: *"you create the project then you select what you want to do in this
// project ... then after that it asks you to upload the files you need for that task."* So the
// claim now is the opposite one, and it is the stronger one: **every task asks for its data at
// creation, and asks exactly one data question** — R41 and R44.2, restored rather than excepted.
//
// ⚠️ What has NOT changed, and what this file still guards: the one question is about the data he
// is bringing IN. There is still no save folder, no "where should this go", nowhere to browse to a
// project. If a future change reintroduces one of those, this spec is what says so.
//
// The Files step's own behaviour — the tick-list, the copy, the refusals — is `analyze-mea.spec.ts`.
// This file only checks that the wizard reaches it and comes out the other side with a project.
//
// The video task's own journey is `videomosaic.spec.ts`; this only checks that its card is the
// door to it. ⛔ The retired snapshot task is deliberately NOT offered here — see
// `playwright.config.ts :: RETIRED_SNAPSHOT_SPECS`.
// ─────────────────────────────────────────────────────────────────────────────

import { test, expect, type Page } from '@playwright/test';
import { SHORT } from './fixture';
import { TID } from './pages';

/**
 * ⚠️ Longer than `SHORT` (4 s) on purpose, and only where a step follows a **navigation into a
 * route this run has not visited yet**. On a cold Vite dev server that first hop pays for the
 * transform of the whole feature module, and with two workers sharing one backend it measured well
 * past 4 s — a load flake, not a bug (`playwright.config.ts` says the same thing about the worker
 * ceiling). Assertions on a screen that is already up keep `SHORT`, where a real regression shows.
 */
const FIRST_PAINT = 20_000;

/** Home → New project → type a name → Next. Lands on the Task step. */
async function toTaskStep(page: Page, name: string): Promise<void> {
  await page.goto('/');
  await page.getByTestId(TID.newProject).click();
  await expect(page).toHaveURL(/\/new(\/|$)/);
  await page.getByTestId(TID.npName).fill(name);
  await page.getByTestId(TID.npNext).click();
  await expect(page.getByTestId(TID.taskCard).first()).toBeVisible({ timeout: SHORT });
}

const taskCard = (page: Page, task: string) =>
  page.locator(`[data-testid="${TID.taskCard}"][data-task="${task}"]`);

/**
 * Pick `Analyze MEA`, take the Files step with nothing ticked, and land in the project.
 * -> its analysis id.
 *
 * ⭐ **Create with an empty tick-list is deliberate and is his ruling** (2026-08-14, asked with
 * side-by-side mockups): an empty project is a state the app can already reach — it is what he is
 * left with the moment he removes his last recording — so the wizard must be able to produce one.
 */
async function createMeaProject(page: Page, name: string): Promise<string> {
  await toTaskStep(page, name);
  await taskCard(page, 'mea').click();
  await expect(page.getByTestId(TID.meaImport)).toBeVisible({ timeout: FIRST_PAINT });
  await page.getByTestId(TID.npCreate).click();
  await page.waitForURL(/\/project\/[^/]+$/, { timeout: 30_000 });
  return page.url().split('/').pop()!;
}

async function deleteProject(page: Page, id: string): Promise<void> {
  await page.request.delete(`/api/projects/${id}`);
}

test('Next lands on exactly two tasks, named the way he names them', async ({ page }) => {
  await toTaskStep(page, 'chooser');

  await expect(page.getByTestId(TID.taskCard)).toHaveCount(2);
  await expect(taskCard(page, 'videomosaic')).toContainText('Simultaneous MEA + 2P');
  await expect(taskCard(page, 'mea')).toContainText('Analyze MEA');

  // ⛔ The retired snapshot builder is not one of them. It still OPENS (the FeatureGate keeps its
  // arm); it is simply not offered to a new project.
  await expect(taskCard(page, 'mosaic')).toHaveCount(0);
});

test('Analyze MEA: one data question, and it is about the recordings he is bringing in', async ({
  page,
}) => {
  await toTaskStep(page, 'mea flow');
  await taskCard(page, 'mea').click();

  // ⭐ The Files step. It asks for his recordings — and for nothing else. ⛔ No path box to type a
  // save folder into, no "where should this go": R44 answers that itself, and R44.2 says creation
  // asks exactly ONE data question.
  await expect(page.getByTestId(TID.meaImport)).toBeVisible({ timeout: FIRST_PAINT });
  await expect(page.getByTestId(TID.pathInput)).toHaveCount(0);
  await expect(page.getByTestId('into-field')).toHaveCount(0);
  // The stepper names it, and names it for THIS task.
  await expect(page.getByTestId(TID.newProjectFlow)).toContainText('Files');

  // ⭐ Create works with nothing ticked (his ruling, 2026-08-14) and says what it will do.
  await expect(page.getByTestId(TID.npCreate)).toBeEnabled();
  await expect(page.getByTestId(TID.npMeaCount)).toContainText('None chosen');

  await page.getByTestId(TID.npCreate).click();
  await page.waitForURL(/\/project\/[^/]+$/, { timeout: 30_000 });
  const id = page.url().split('/').pop()!;
  try {
    await expect(page.getByTestId(TID.meaFeature)).toBeVisible({ timeout: FIRST_PAINT });
    await expect(page.getByTestId(TID.meaProjectName)).toHaveText('mea flow');
    await expect(page.getByTestId(TID.meaEmpty)).toBeVisible();
    // ⭐ **AND THE BUTTON WORKS NOW.** It was disabled in 001 because the import did not exist; an
    // enabled button is what makes the `?` beside it stop being a lie.
    await expect(page.getByTestId(TID.meaAddRecordings)).toBeEnabled();

    // ⭐ R3 (his ruling, 2026-08-14): what the button does lives behind the `?`, not on the page.
    const empty = page.getByTestId(TID.meaEmpty);
    const longParas = await empty
      .locator('p')
      .evaluateAll((ps) => ps.filter((p) => (p.textContent ?? '').trim().length > 80).length);
    expect(longParas, 'the empty state must not carry an explanatory paragraph').toBe(0);

    // ⛔ And none of the video pipeline came with it: no stepper, no mosaic, no regions.
    await expect(page.getByTestId(TID.pipelineSteps)).toHaveCount(0);
  } finally {
    await deleteProject(page, id);
  }
});

test('Back from the Files step puts the task question back, and the third step goes neutral', async ({
  page,
}) => {
  // ⚠️ The invariant `stepsFor` exists for: until he has answered "what do you want to do?", the
  // third step must not be captioned with a guess. Back unmakes his answer, so the caption has to
  // go back to being neutral too — this is the same machinery the video task uses, now exercised
  // from the second task as well.
  await toTaskStep(page, 'back out');
  await taskCard(page, 'mea').click();
  await expect(page.getByTestId(TID.meaImport)).toBeVisible({ timeout: FIRST_PAINT });
  await expect(page.getByTestId(TID.newProjectFlow)).toContainText('Files');

  await page.getByTestId(TID.npBack).click();
  await expect(page.getByTestId(TID.taskCard).first()).toBeVisible({ timeout: SHORT });
  await expect(page.getByTestId(TID.newProjectFlow)).not.toContainText('Files');
  await expect(page.getByTestId(TID.newProjectFlow)).toContainText('Data');

  // ...and the other card is still reachable from there, so Back is not a dead end.
  await taskCard(page, 'videomosaic').click();
  await expect(page.getByTestId('np-video-path')).toBeVisible({ timeout: SHORT });
});

test('the empty state explains itself only behind the `?`, and the `?` answers the keyboard', async ({
  page,
}) => {
  const id = await createMeaProject(page, 'help mark');
  try {
    await expect(page.getByTestId(TID.meaFeature)).toBeVisible({ timeout: FIRST_PAINT });
    const mark = page.getByTestId(TID.help);
    await expect(mark).toHaveCount(1);

    // ⛔ **A SIBLING OF THE BUTTON, NEVER A CHILD.** A `Help` trigger is itself a <button>, and a
    // button inside a button is invalid markup no keyboard can reach — the trap PipelineNav
    // documents. Asserted structurally so it cannot come back as a nesting.
    await expect(
      page.locator(`[data-testid="${TID.meaAddRecordings}"] [data-testid="${TID.help}"]`),
    ).toHaveCount(0);

    // Driven by keyboard alone — focus is what opens it (R3.2), so Tab is enough. (In 001 this
    // mattered more: the button beside it was disabled and took no focus, so the `?` was the only
    // thing on the screen a Tab could reach. The button works now; the `?` must still answer.)
    await expect(page.getByTestId(TID.helpTooltip)).toHaveCount(0);
    await mark.focus();
    await expect(mark).toBeFocused();
    const tip = page.getByTestId(TID.helpTooltip);
    await expect(tip).toBeVisible({ timeout: SHORT });
    await expect(tip).toContainText('.h5');

    // Enter on a focused `?` must not slam it shut — it stays readable while he holds focus.
    await page.keyboard.press('Enter');
    await expect(tip).toBeVisible();
    // ...and Escape dismisses it (R3.2), the app's one way out of a tooltip.
    await page.keyboard.press('Escape');
    await expect(tip).toBeHidden();
  } finally {
    await deleteProject(page, id);
  }
});

test('the task cards answer the keyboard — Tab to one, press Enter', async ({ page }) => {
  // 🔴 The cards are `<div>`s under the hood. Without role/tabIndex/onKeyDown a keyboard-only user
  // cannot get past step 2 AT ALL, because this step is the only door to either task. Driven the
  // way he would drive it: no click anywhere.
  await toTaskStep(page, 'keyboard');

  const mea = taskCard(page, 'mea');
  await expect(mea).toHaveAttribute('role', 'button');
  await mea.focus();
  await expect(mea).toBeFocused();
  await page.keyboard.press('Enter');

  // Enter reaches the Files step (it reached the project itself in 001 — the card was the create).
  await expect(page.getByTestId(TID.meaImport)).toBeVisible({ timeout: FIRST_PAINT });
});

test('Simultaneous MEA + 2P is still the door to the video pipeline', async ({ page }) => {
  await toTaskStep(page, 'video flow');
  await taskCard(page, 'videomosaic').click();
  // The Video step, unchanged — one path box and no folder question (R44).
  await expect(page.getByTestId('np-video-path')).toBeVisible({ timeout: SHORT });
  await expect(page.getByTestId('into-field')).toHaveCount(0);
});

test('an Analyze MEA project is an ordinary card: it lists, renames, reopens and deletes', async ({
  page,
}) => {
  const id = await createMeaProject(page, 'chip on the shelf');
  let deleted = false;
  try {
    await page.goto('/');
    const card = page.locator(`[data-testid="${TID.projectCard}"][data-project-id="${id}"]`);
    await expect(card).toBeVisible({ timeout: FIRST_PAINT });
    await expect(card).toContainText('Analyze MEA');
    // ⭐ Where a video's filename would sit, an honest line instead of a blank one.
    await expect(card.getByTestId(TID.projectNoInput)).toHaveText('No recordings yet');

    // rename — a `window.prompt` on purpose (R38: Playwright can answer one)
    page.once('dialog', (d) => void d.accept('chip, renamed'));
    await card.locator('..').getByTestId(TID.projectRename).click();
    await expect(card).toContainText('chip, renamed', { timeout: SHORT });

    // reopen — the gate mounts the same screen from the id alone
    await card.click();
    await page.waitForURL(/\/project\/[^/]+$/, { timeout: FIRST_PAINT });
    await expect(page.getByTestId(TID.meaProjectName)).toHaveText('chip, renamed', {
      timeout: FIRST_PAINT,
    });

    // delete — the confirm is a `window.confirm`, and delete means delete (R44)
    await page.goto('/');
    page.once('dialog', (d) => void d.accept());
    await page
      .locator(`[data-testid="${TID.projectCard}"][data-project-id="${id}"]`)
      .locator('..')
      .getByTestId(TID.projectDelete)
      .click();
    await expect(
      page.locator(`[data-testid="${TID.projectCard}"][data-project-id="${id}"]`),
    ).toHaveCount(0, { timeout: SHORT });
    deleted = true;
  } finally {
    if (!deleted) await deleteProject(page, id);
  }
});
