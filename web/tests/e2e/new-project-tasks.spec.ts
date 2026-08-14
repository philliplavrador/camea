// ─────────────────────────────────────────────────────────────────────────────
// "WHAT DO YOU WANT TO DO?" — the Task step, back on the new-project flow (2026-08-14).
//
// Two tasks now, so the question is real again: **Simultaneous MEA + 2P** (the video → mosaic →
// electrodes → regions pipeline, renamed to the experiment it serves) and **Analyze MEA** (a
// MaxWell recording opened on its own).
//
// ⭐ **THE ONE THING THIS FILE EXISTS TO PROVE:** picking `Analyze MEA` asks **no path question of
// any kind** — no dataset folder, no file, no save folder (R44 and then some) — and lands him
// inside the project. Every other way to make a project in Camea names something on disk; if a
// future change reintroduces a box here, this spec is what says so.
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

/** Pick `Analyze MEA` and land in the project. -> its analysis id. */
async function createMeaProject(page: Page, name: string): Promise<string> {
  await toTaskStep(page, name);
  await taskCard(page, 'mea').click();
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

test('Analyze MEA: no path box anywhere, and the click IS the create', async ({ page }) => {
  await toTaskStep(page, 'mea flow');

  // ⭐ There is nothing to type on this step, and there is nothing after it.
  await expect(page.getByTestId(TID.pathInput)).toHaveCount(0);
  await expect(page.getByTestId(TID.npCreate)).toHaveCount(0);

  await taskCard(page, 'mea').click();
  await page.waitForURL(/\/project\/[^/]+$/, { timeout: 30_000 });
  const id = page.url().split('/').pop()!;
  try {
    // He is in the project, and it says what it is and what is not there yet.
    await expect(page.getByTestId(TID.meaFeature)).toBeVisible({ timeout: FIRST_PAINT });
    await expect(page.getByTestId(TID.meaProjectName)).toHaveText('mea flow');
    await expect(page.getByTestId(TID.meaEmpty)).toBeVisible();
    // ⚠️ The import is plan 002. The button is present and OFF — the shape of the screen is the
    // promise, and a screen that grows a control later reads as a different screen.
    await expect(page.getByTestId(TID.meaAddRecordings)).toBeDisabled();

    // ⭐ R3 (his ruling, 2026-08-14): the reason the button is off lives behind the `?`, not on the
    // page. Nothing on this screen explains itself in prose.
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

    // 🔴 The button beside it is DISABLED, so it takes no focus at all: the `?` is the only thing
    // on this screen a Tab can land on, and it is the only route to the reason. Driven by keyboard
    // alone — focus is what opens it (R3.2), so Tab is enough.
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

  await page.waitForURL(/\/project\/[^/]+$/, { timeout: 30_000 });
  const id = page.url().split('/').pop()!;
  try {
    await expect(page.getByTestId(TID.meaFeature)).toBeVisible({ timeout: FIRST_PAINT });
  } finally {
    await deleteProject(page, id);
  }
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
