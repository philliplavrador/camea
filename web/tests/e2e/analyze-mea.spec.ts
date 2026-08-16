// ─────────────────────────────────────────────────────────────────────────────
// ANALYZE MEA — picking your recordings when you make the project, and the shelf they land on.
//
// ⭐ **WHAT THIS FILE EXISTS TO PROVE**, in the order it matters:
//   1. New project → name → Analyze MEA → a **Files step** that takes several `.h5` at once, and
//      **Create** makes the project with those recordings already on the shelf. ONE call.
//   2. **Add recordings** inside the project shows **the same picker** — asserted structurally by
//      the shared `data-testid` island, not by eye.
//   3. Removing a recording deletes **Camea's copy** and leaves **his original** on disk.
//   4. A file that is not a MaxLab recording is refused **BY NAME**, and is still on the list.
//   5. A recording whose original moved says so **on the page**, as a live warning (R3's standing
//      exception), and shows **no numbers** rather than zeros.
//
// It runs against the committed synthetic session (`MEA_FIXTURE`) — two recordings, 19 kB each, so
// the whole file is fast and needs no data mirror. ⛔ The numbers it asserts are FIXTURE facts,
// which HARD RULE 3 permits inside `tests/`; the app knows none of them.
//
// ⚠️ **THE COPY IS TOO FAST TO CATCH ON A 19 kB FILE**, so "copying, N %" is asserted against a
// stubbed response rather than raced for. The real thing was watched by hand on 1.5 GB files from
// the mirror (two independent bars, per recording) — see plan 002's close-out.
// ─────────────────────────────────────────────────────────────────────────────

import { test, expect, type Page } from '@playwright/test';
import { MEA_FIXTURE, SHORT } from './fixture';
import { TID } from './pages';

/** A cold hop into a route this run has not visited pays for the whole feature module's transform
 *  on a dev server shared by two workers. Assertions on a screen already up keep `SHORT`. */
const FIRST_PAINT = 20_000;

async function toFilesStep(page: Page, name: string): Promise<void> {
  await page.goto('/');
  await page.getByTestId(TID.newProject).click();
  await page.getByTestId(TID.npName).fill(name);
  await page.getByTestId(TID.npNext).click();
  await page.locator(`[data-testid="${TID.taskCard}"][data-task="mea"]`).click();
  await expect(page.getByTestId(TID.meaImport)).toBeVisible({ timeout: FIRST_PAINT });
}

/**
 * Drive the FolderPicker to a folder — it walks the tree, so we drive it the way a user does.
 *
 * ⚠️ **Each level is addressed by its NAME SPAN, exactly** — never by index (the contents of
 * `tests/` change) and never by `hasText` on the row (the row's text is the icon glyph, the name
 * and a child count run together, so `^Projects` never matches and a substring would happily open
 * `mea-something-else`).
 */
async function lookIn(page: Page, absolute: string): Promise<void> {
  await page.getByTestId(TID.meaChooseFolder).click();
  const picker = page.getByTestId('folder-picker');
  await expect(picker).toBeVisible({ timeout: SHORT });
  const [drive, ...rest] = absolute.split('/');
  await picker.locator(`[data-testid="folder-picker-entry"]:has-text("${drive}/")`).first().click();
  for (const part of rest) {
    await picker
      .locator('[data-testid="folder-picker-entry"]')
      .filter({ has: page.locator(`span:text-is(${JSON.stringify(part)})`) })
      .first()
      .click();
    await expect(page.getByTestId('folder-picker-path')).toContainText(part, { timeout: SHORT });
  }
  await page.getByTestId('folder-picker-confirm').click();
}

const rowFor = (page: Page, label: string) =>
  page.locator(`[data-testid="${TID.meaRecording}"]`).filter({ hasText: label });

async function deleteProject(page: Page, id: string): Promise<void> {
  await page.request.delete(`/api/projects/${id}`);
}

// =================================================================================================
// 1 · the wizard's Files step
// =================================================================================================

test('the Files step lists every recording under a folder, several at a time', async ({ page }) => {
  await toFilesStep(page, 'files step');
  await expect(page.getByTestId(TID.meaImportStart)).toBeVisible();

  await lookIn(page, MEA_FIXTURE.dir);

  const rows = page.getByTestId(TID.meaImportRow);
  await expect(rows).toHaveCount(MEA_FIXTURE.count, { timeout: SHORT });
  for (const label of MEA_FIXTURE.labels) {
    await expect(rows.filter({ hasText: label })).toHaveCount(1);
  }
  // ⭐ Each row carries the file's OWN facts, read off the header — that is how he tells two
  // recordings called `data.raw.h5` apart before he ticks one.
  await expect(rows.first()).toContainText('channels');
  await expect(rows.first()).toContainText('spikes');

  // Several at a time, in one gesture.
  await page.getByTestId(TID.meaTickAll).check();
  await expect(page.getByTestId(TID.npMeaCount)).toHaveText(`${MEA_FIXTURE.count} chosen`);
});

test('Create makes the project WITH the recordings already on it — one call', async ({ page }) => {
  await toFilesStep(page, 'one call');
  await lookIn(page, MEA_FIXTURE.dir);
  await page.getByTestId(TID.meaTickAll).check();
  await page.getByTestId(TID.npCreate).click();

  await page.waitForURL(/\/project\/[^/]+$/, { timeout: 30_000 });
  const id = page.url().split('/').pop()!;
  try {
    // ⭐ He lands on a shelf that is ALREADY FULL. There is no moment where the project exists with
    // nothing on it, because there was no second call that could have failed.
    await expect(page.getByTestId(TID.meaShelf)).toBeVisible({ timeout: FIRST_PAINT });
    await expect(page.getByTestId(TID.meaRecording)).toHaveCount(MEA_FIXTURE.count);
    await expect(page.getByTestId(TID.meaEmpty)).toHaveCount(0);
    for (const label of MEA_FIXTURE.labels) {
      await expect(rowFor(page, label)).toHaveCount(1);
    }
  } finally {
    await deleteProject(page, id);
  }
});

test('a folder with no recordings says so, and is not an error', async ({ page }) => {
  // He pointed at the wrong folder. That is a fact about the folder — he browses on.
  await toFilesStep(page, 'wrong folder');
  await lookIn(page, MEA_FIXTURE.emptyDir);
  await expect(page.getByTestId(TID.meaImportNone)).toBeVisible({ timeout: SHORT });
  await expect(page.getByTestId(TID.meaImportError)).toHaveCount(0);
  // ...and Create still works, because an empty project is a real project (his ruling 2026-08-14).
  await expect(page.getByTestId(TID.npCreate)).toBeEnabled();
});

// =================================================================================================
// 2 · ONE picker, TWO mount points
// =================================================================================================

test('Add recordings inside the project shows THE SAME picker the wizard showed', async ({
  page,
}) => {
  // ⭐ The structural half of "one component, two mount points". The wizard's step and this dialog
  // render the same testid island — `mea-import`, with the same folder bar and the same tick-list.
  // ⚠️ The real guard is `RecordingShelf.tsx` importing `./ImportRecordings`, which is checked by
  // reading the imports; this asserts they render the same thing so a divergence shows up here too.
  await toFilesStep(page, 'same picker');
  await lookIn(page, MEA_FIXTURE.dir);
  const inWizard = await page.getByTestId(TID.meaImport).innerHTML();
  await page.getByTestId(TID.npCreate).click(); // nothing ticked -> empty project

  await page.waitForURL(/\/project\/[^/]+$/, { timeout: 30_000 });
  const id = page.url().split('/').pop()!;
  try {
    await expect(page.getByTestId(TID.meaEmpty)).toBeVisible({ timeout: FIRST_PAINT });
    await page.getByTestId(TID.meaAddRecordings).click();
    await expect(page.getByTestId(TID.meaAddDialog)).toBeVisible({ timeout: SHORT });

    await lookIn(page, MEA_FIXTURE.dir);
    const inShelf = await page.getByTestId(TID.meaImport).innerHTML();
    expect(inShelf, 'the shelf must mount the wizard picker, not a second one').toBe(inWizard);

    // ...and it works from here: this is the empty-shelf path, which must keep working.
    await page.getByTestId(TID.meaTickAll).check();
    await page.getByTestId(TID.meaAddConfirm).click();
    await expect(page.getByTestId(TID.meaRecording)).toHaveCount(MEA_FIXTURE.count, {
      timeout: SHORT,
    });
  } finally {
    await deleteProject(page, id);
  }
});

// =================================================================================================
// 2b · renaming a row
// =================================================================================================

// R44: a rename rewrites the row's name in the project's own document. No file on any disk is
// moved or renamed, and he is never asked where anything lives — the store owns the data.
test('clicking a recording’s name renames it in place — and only the name changes', async ({
  page,
}) => {
  await toFilesStep(page, 'rename row');
  await lookIn(page, MEA_FIXTURE.dir);
  await page.getByTestId(TID.meaTickAll).check();
  await page.getByTestId(TID.npCreate).click();
  await page.waitForURL(/\/project\/[^/]+$/, { timeout: 30_000 });
  const id = page.url().split('/').pop()!;
  try {
    const row = rowFor(page, MEA_FIXTURE.labels[0]);
    await expect(row).toBeVisible({ timeout: FIRST_PAINT });

    // Click the name, type a new one, Enter.
    await row.getByTestId(TID.meaRecordingLabel).click();
    const input = page.getByTestId(TID.meaRenameInput);
    await expect(input).toBeVisible({ timeout: SHORT });
    await input.fill('chip 3693 day 12');
    await input.press('Enter');

    const renamed = rowFor(page, 'chip 3693 day 12');
    await expect(renamed.getByTestId(TID.meaRecordingLabel)).toHaveText('chip 3693 day 12', {
      timeout: SHORT,
    });
    // ⭐ Only the NAME moved — the numbers and the copy state are the same recording's.
    await expect(renamed.getByTestId(TID.meaRecordingFacts)).toContainText('spikes');

    // ...and it holds across a reload: the rename is in the document, not in this tab.
    await page.reload();
    await expect(rowFor(page, 'chip 3693 day 12')).toBeVisible({ timeout: FIRST_PAINT });

    // Esc is "never mind" — the name stays what it was.
    await rowFor(page, 'chip 3693 day 12').getByTestId(TID.meaRecordingLabel).click();
    await page.getByTestId(TID.meaRenameInput).fill('typo I regret');
    await page.getByTestId(TID.meaRenameInput).press('Escape');
    await expect(rowFor(page, 'chip 3693 day 12')).toBeVisible({ timeout: SHORT });
    await expect(page.getByTestId(TID.meaRenameInput)).toHaveCount(0);

    // ⭐ ...and focus comes back to the name he was editing, so a keyboard user is not dropped at
    // the top of the page every time he renames a row.
    await expect(
      rowFor(page, 'chip 3693 day 12').getByTestId(TID.meaRecordingLabel),
    ).toBeFocused();
  } finally {
    await deleteProject(page, id);
  }
});

// =================================================================================================
// 3 · what the shelf says
// =================================================================================================

test('a row carries the file’s own numbers, and says where Camea reads it from', async ({
  page,
}) => {
  await toFilesStep(page, 'shelf facts');
  await lookIn(page, MEA_FIXTURE.dir);
  await page.getByTestId(TID.meaTickAll).check();
  await page.getByTestId(TID.npCreate).click();
  await page.waitForURL(/\/project\/[^/]+$/, { timeout: 30_000 });
  const id = page.url().split('/').pop()!;
  try {
    const row = rowFor(page, MEA_FIXTURE.labels[0]);
    await expect(row).toBeVisible({ timeout: FIRST_PAINT });
    await expect(row.getByTestId(TID.meaRecordingFacts)).toContainText('channels');
    await expect(row.getByTestId(TID.meaRecordingFacts)).toContainText('spikes');

    // ⭐ **PLAIN ENGLISH, NOT THE WIRE'S VOCABULARY.** The document says `referenced`/`stored`; he
    // is a biologist and needs to know which disk it is coming off.
    const copy = row.getByTestId(TID.meaRecordingCopy);
    await expect(copy).toHaveText(/In the project|In your folder/, { timeout: SHORT });
    await expect(copy).not.toContainText('referenced');
    await expect(copy).not.toContainText('stored');
  } finally {
    await deleteProject(page, id);
  }
});

test('while a copy runs the row says so, with its own percentage', async ({ page }) => {
  // ⚠️ Stubbed, and the reason is honest: the fixture is 19 kB and lands before the first paint.
  // What is asserted is the RENDERING of a state the backend really produces — watched by hand on
  // 1.5 GB files from the mirror, two recordings copying at two different percentages at once.
  await page.route('**/api/mea/*/recordings', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        analysis_id: 'x',
        recordings: [
          {
            id: 'rec_a',
            label: 'Network/000690',
            run_id: '000690',
            assay: 'Network',
            source_path: 'D:/somewhere/data.raw.h5',
            stored_path: '',
            copy_state: 'copying',
            copy_pct: 42.4,
            copy_error: '',
            added: '2026-08-14T00:00:00Z',
            bytes: 1_195_443_551,
            missing: false,
            source_present: true,
            duration_s: 300,
            n_channels: 726,
            n_samples: 6_000_000,
            n_spikes: 22_367,
          },
        ],
      }),
    });
  });

  await toFilesStep(page, 'copying');
  await page.getByTestId(TID.npCreate).click();
  await page.waitForURL(/\/project\/[^/]+$/, { timeout: 30_000 });
  const id = page.url().split('/').pop()!;
  try {
    const row = page.getByTestId(TID.meaRecording).first();
    await expect(row).toBeVisible({ timeout: FIRST_PAINT });
    await expect(row).toHaveAttribute('data-copy', 'copying');
    await expect(row.getByTestId(TID.meaRecordingCopy)).toContainText('42%');
    // ⭐ **AND IT IS USABLE WHILE IT COPIES** — the numbers are there, read from the original.
    await expect(row.getByTestId(TID.meaRecordingFacts)).toContainText('22,367 spikes');
  } finally {
    await page.unrouteAll();
    await deleteProject(page, id);
  }
});

test('a recording whose original moved says so ON THE PAGE, and shows no numbers', async ({
  page,
}) => {
  // 🔴 R3's standing exception (W1–W11): a fact about HIS DATA, right now. ⛔ It must not be behind
  // the `?` — that is for facts about the app. And ⛔ no zeros: a row of zeros reads as a silent
  // chip, which is a lie.
  await page.route('**/api/mea/*/recordings', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        analysis_id: 'x',
        recordings: [
          {
            id: 'rec_gone',
            label: 'Network/000690',
            run_id: '000690',
            assay: 'Network',
            source_path: 'D:/where/it/used/to/be/data.raw.h5',
            stored_path: '',
            copy_state: 'referenced',
            copy_pct: 0,
            copy_error: '',
            added: '2026-08-14T00:00:00Z',
            bytes: 0,
            missing: true,
            source_present: false,
            duration_s: null,
            n_channels: null,
            n_samples: null,
            n_spikes: null,
          },
        ],
      }),
    });
  });

  await toFilesStep(page, 'moved');
  await page.getByTestId(TID.npCreate).click();
  await page.waitForURL(/\/project\/[^/]+$/, { timeout: 30_000 });
  const id = page.url().split('/').pop()!;
  try {
    const row = page.getByTestId(TID.meaRecording).first();
    await expect(row).toBeVisible({ timeout: FIRST_PAINT });
    await expect(row).toHaveAttribute('data-missing', 'true');

    const warning = row.getByTestId(TID.meaRecordingMissing);
    await expect(warning).toBeVisible();
    await expect(warning).toContainText('no longer where you left it');
    await expect(warning).toContainText('D:/where/it/used/to/be/data.raw.h5');
    // ⛔ On the page, not behind a `?` — and it is a live region, so it is announced.
    await expect(row.getByTestId(TID.help)).toHaveCount(0);
    await expect(row.locator('[role="status"], [role="alert"]')).toHaveCount(1);
    // ⛔ NO NUMBERS. Not "0 spikes" — nothing.
    await expect(row.getByTestId(TID.meaRecordingFacts)).toHaveCount(0);
  } finally {
    await page.unrouteAll();
    await deleteProject(page, id);
  }
});

// =================================================================================================
// 4 · the refusal, by name
// =================================================================================================

test('a file that is not a MaxLab recording is refused BY NAME, and stays on the list', async ({
  page,
}) => {
  // ⛔ Never silently dropped: a file missing from the list makes the folder look emptier than it
  // is, and the one thing worse than a refusal is one he never saw.
  await page.route('**/api/mea/browse**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        path: 'D:/his/folder',
        truncated: false,
        recordings: [
          {
            path: 'D:/his/folder/Network/000690/data.raw.h5',
            label: 'Network/000690',
            run_id: '000690',
            assay: 'Network',
            bytes: 100,
            duration_s: 300,
            n_channels: 726,
            n_spikes: 22_367,
            readable: true,
            problem: '',
          },
          {
            path: 'D:/his/folder/ActivityScan/000687/data.raw.h5',
            label: '000687',
            run_id: '',
            assay: '',
            bytes: 100,
            duration_s: null,
            n_channels: null,
            n_spikes: null,
            readable: false,
            problem: 'KeyError: component not found',
          },
        ],
      }),
    });
  });

  await toFilesStep(page, 'refused');
  await lookIn(page, MEA_FIXTURE.dir);

  const rows = page.getByTestId(TID.meaImportRow);
  await expect(rows).toHaveCount(2, { timeout: SHORT });
  const bad = rows.filter({ hasText: '000687' });
  await expect(bad).toHaveAttribute('data-readable', 'false');
  await expect(bad.getByTestId(TID.meaImportRefused)).toContainText('not a MaxLab recording');
  // ⛔ ...and it cannot be ticked, so it can never reach the create call.
  await expect(bad.getByTestId(TID.meaImportTick)).toBeDisabled();

  // Tick-all takes the good one only.
  await page.getByTestId(TID.meaTickAll).check();
  await expect(page.getByTestId(TID.npMeaCount)).toHaveText('1 chosen');
  await page.unrouteAll();
});

test('a refusal at Create keeps him on the step, with his ticks', async ({ page }) => {
  // ⭐ Inline, never a toast — the tick-list is right there and unticking the named file is the
  // whole repair. And ⛔ NO PROJECT is created, so there is nothing to clean up first.
  await page.route('**/api/mea/projects', async (route) =>
    route.fulfill({
      status: 400,
      contentType: 'application/json',
      body: JSON.stringify({
        error: {
          code: 'bad_request',
          message: '000687/data.raw.h5 is not a MaxLab recording',
        },
      }),
    }),
  );

  await toFilesStep(page, 'refused create');
  await lookIn(page, MEA_FIXTURE.dir);
  await page.getByTestId(TID.meaTickAll).check();
  await page.getByTestId(TID.npCreate).click();

  await expect(page.getByTestId(TID.npMeaError)).toContainText('000687/data.raw.h5', {
    timeout: SHORT,
  });
  await expect(page).toHaveURL(/\/new(\/|$)/, { timeout: SHORT });
  // His ticks survived the refusal — the picker was hidden, never remounted.
  await expect(page.getByTestId(TID.npMeaCount)).toHaveText(`${MEA_FIXTURE.count} chosen`);
  await page.unrouteAll();
});

// =================================================================================================
// 5 · removing one
// =================================================================================================

test('removing a recording takes Camea’s copy and leaves the original alone', async ({ page }) => {
  // 🔴 The one that must never regress. The bytes half is asserted in `tests/api/test_mea_feature.py`
  // (his file is still on disk afterwards); this is the screen half — one click, no box, the row
  // goes, and the OTHER recording is untouched.
  await toFilesStep(page, 'removing');
  await lookIn(page, MEA_FIXTURE.dir);
  await page.getByTestId(TID.meaTickAll).check();
  await page.getByTestId(TID.npCreate).click();
  await page.waitForURL(/\/project\/[^/]+$/, { timeout: 30_000 });
  const id = page.url().split('/').pop()!;
  try {
    await expect(page.getByTestId(TID.meaRecording)).toHaveCount(MEA_FIXTURE.count, {
      timeout: FIRST_PAINT,
    });

    await rowFor(page, MEA_FIXTURE.labels[0]).getByTestId(TID.meaRemove).click();

    // ⛔ **NO CONFIRM BOX.** His ruling, twice: there is nothing of his to lose, because the only
    // thing deleted is a copy Camea made itself and his own file is still there.
    await expect(page.getByTestId(TID.meaRemoveConfirm)).toHaveCount(0);
    await expect(page.getByTestId(TID.meaRecording)).toHaveCount(MEA_FIXTURE.count - 1, {
      timeout: SHORT,
    });
    await expect(rowFor(page, MEA_FIXTURE.labels[1])).toHaveCount(1);

    // Removing the last one gives him 001's empty state back, with a working Add button.
    await rowFor(page, MEA_FIXTURE.labels[1]).getByTestId(TID.meaRemove).click();
    await expect(page.getByTestId(TID.meaEmpty)).toBeVisible({ timeout: SHORT });
    await expect(page.getByTestId(TID.meaAddRecordings)).toBeEnabled();
  } finally {
    await deleteProject(page, id);
  }
});

test('removing the LAST copy of a recording asks first — and only then', async ({ page }) => {
  // ⭐ **THE ONE EXCEPTION** (his ruling, 2026-08-14, asked once the gap was noticed). "No confirm
  // box" assumes there is always his own copy to fall back on. When our copy exists AND his
  // original has gone, ours is the last one, and removing it is the only unrecoverable act here.
  //
  // ⚠️ The condition is `stored` AND the source gone. The second row below is `referenced` with its
  // source gone — it has NO copy, so removing it destroys nothing and must NOT ask. Getting these
  // the wrong way round puts a box in front of the harmless case and none in front of the harmful
  // one, which is why both are in this test.
  const row = (over: Record<string, unknown>) => ({
    id: 'rec_x',
    label: 'Network/000690',
    run_id: '000690',
    assay: 'Network',
    source_path: 'D:/gone/data.raw.h5',
    stored_path: '',
    copy_state: 'stored',
    copy_pct: 0,
    copy_error: '',
    added: '2026-08-14T00:00:00Z',
    bytes: 10,
    missing: false,
    source_present: false,
    duration_s: 300,
    n_channels: 726,
    n_samples: 10,
    n_spikes: 22_367,
    ...over,
  });

  await page.route('**/api/mea/*/recordings', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        analysis_id: 'x',
        recordings: [
          // our copy is the last one left  -> ASKS
          row({ id: 'rec_last', stored_path: 'recordings/rec_last/data.raw.h5' }),
          // referenced, source gone: no copy at all -> does NOT ask
          row({
            id: 'rec_none',
            label: 'Network/000691',
            copy_state: 'referenced',
            missing: true,
            duration_s: null,
            n_channels: null,
            n_samples: null,
            n_spikes: null,
          }),
        ],
      }),
    });
  });

  await toFilesStep(page, 'last copy');
  await page.getByTestId(TID.npCreate).click();
  await page.waitForURL(/\/project\/[^/]+$/, { timeout: 30_000 });
  const id = page.url().split('/').pop()!;
  try {
    await expect(page.getByTestId(TID.meaRecording)).toHaveCount(2, { timeout: FIRST_PAINT });

    // The harmless one: no box.
    await rowFor(page, 'Network/000691').getByTestId(TID.meaRemove).click();
    await expect(page.getByTestId(TID.meaRemoveConfirm)).toHaveCount(0, { timeout: SHORT });

    // The unrecoverable one: it asks, and it says why in his words.
    await rowFor(page, 'Network/000690').getByTestId(TID.meaRemove).click();
    const confirm = page.getByTestId(TID.meaRemoveConfirm);
    await expect(confirm).toBeVisible({ timeout: SHORT });
    await expect(confirm).toContainText('the only one left');
    await expect(confirm).toHaveAttribute('role', 'alertdialog');
    await expect(confirm.getByTestId(TID.meaRemoveAnyway)).toBeVisible();

    // Cancel leaves it exactly where it was.
    await confirm.getByRole('button', { name: 'Cancel' }).click();
    await expect(page.getByTestId(TID.meaRemoveConfirm)).toHaveCount(0);
    await expect(page.getByTestId(TID.meaRecording)).toHaveCount(2);
  } finally {
    await page.unrouteAll();
    await deleteProject(page, id);
  }
});

// =================================================================================================
// 5 · opening one recording — the chip, and one pad's trace (plan 003)
// =================================================================================================
//
// ⭐ **THE FIXTURE IS BUILT FOR THIS.** 21 routed pads of a 13 × 5 chip, channel 0 the busiest and
// the last routed channel deliberately SILENT — so the live end of the ramp and the hollow ring are
// both real on a 19 kB file, and a broken colour scale cannot pass.
//
// ⛔ **AND ITS RAW STREAM IS DECLARED AND NEVER WRITTEN**, which is exactly what the real
// recordings look like through the published MaxWell decoder. So the "the waveform did not decode"
// assertion below is testing the real failure, not a mock of it.

/** Create a project holding the fixture recordings and open the first one. -> the project id. */
async function openFirstRecording(page: Page, name: string): Promise<string> {
  await toFilesStep(page, name);
  await lookIn(page, MEA_FIXTURE.dir);
  await page.getByTestId(TID.meaTickAll).check();
  await page.getByTestId(TID.npCreate).click();
  await page.waitForURL(/\/project\/[^/]+$/, { timeout: 30_000 });
  const id = page.url().split('/').pop()!;
  await expect(page.getByTestId(TID.meaRecording)).toHaveCount(MEA_FIXTURE.count, {
    timeout: FIRST_PAINT,
  });
  await rowFor(page, MEA_FIXTURE.labels[0]).getByTestId(TID.meaOpenButton).click();
  await expect(page.getByTestId(TID.meaChipMap)).toBeVisible({ timeout: FIRST_PAINT });
  return id;
}

/**
 * Select the first routed pad, by keyboard — the same gesture the "clicking a pad reads it" test
 * uses, and deliberately not a canvas click: a canvas is the easiest thing in the app to leave
 * keyboard-dead.
 *
 * ⚠️ The `[role="application"]` locator is scoped INSIDE the chip map on purpose. Since 004 the
 * close-up chart is a second `role="application"` on the same screen, and an unscoped one would be
 * ambiguous.
 */
async function pickFirstPad(page: Page): Promise<void> {
  await page.getByTestId(TID.meaChipMap).locator('[role="application"]').focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByTestId(TID.meaTraceFacts)).toBeVisible({ timeout: SHORT });
  await expect(page.getByTestId(TID.meaTracePos)).toBeVisible({ timeout: SHORT });
}

test('picking a recording draws the chip, and the whole chip is in the picture', async ({
  page,
}) => {
  const id = await openFirstRecording(page, 'chip map');
  try {
    await expect(page.getByTestId(TID.meaOpenLabel)).toHaveText(MEA_FIXTURE.labels[0]);
    await expect(page.getByTestId(TID.meaChipCanvas)).toBeVisible();

    // ⭐ **THE WHOLE CHIP, NOT JUST THE RECORDED BLOCK** (his answer, 2026-08-14). The line names
    // both numbers: how big the chip is, and how much of it this recording used.
    const extent = page.getByTestId(TID.meaChipExtent);
    await expect(extent).toContainText('13 × 5');
    await expect(extent).toContainText('21');
    await expect(extent).toContainText('wired up for this recording');
  } finally {
    await deleteProject(page, id);
  }
});

test('spikes the chip cannot place are said in the header — and only when there are any', async ({
  page,
}) => {
  // 🔴 MAXWELL §7.6: the header's file total and the chip's coloured tally genuinely differ on real
  // files (22,367 vs 15,688 on one of his) because the detector logs spikes on channels outside the
  // routed mapping. The difference must be SAID beside the total — and ⛔ never "fixed" by printing
  // only the placed total. The fixture places every spike, so first: no line on an honest zero.
  const id = await openFirstRecording(page, 'unplaced spikes');
  try {
    await expect(page.getByTestId(TID.meaOpenFacts)).toContainText('spikes');
    await expect(page.getByTestId(TID.meaOpenUnplaced)).toHaveCount(0);
  } finally {
    await deleteProject(page, id);
  }

  // Now the same screen with a file that HAS unplaced spikes — the real payload, with only the
  // derived count raised, so the assertion is about the rendering of a state the backend produces.
  await page.route('**/api/mea/*/recordings/*/activity**', async (route) => {
    const real = await route.fetch();
    const body = await real.json();
    body.n_spikes_unplaced = 6679;
    await route.fulfill({ response: real, json: body });
  });
  const id2 = await openFirstRecording(page, 'unplaced spikes said');
  try {
    const line = page.getByTestId(TID.meaOpenUnplaced);
    await expect(line).toBeVisible({ timeout: SHORT });
    await expect(line).toContainText('6,679');
    await expect(line).toContainText('could not be placed on the chip');
    // ⛔ The file total is still the file's own — the mismatch is stated, not reconciled away.
    await expect(page.getByTestId(TID.meaOpenFacts)).toContainText('spikes');
    await expect(line).not.toContainText(/dead|failed|broken|inactive/i);
  } finally {
    await page.unrouteAll();
    await deleteProject(page, id2);
  }
});

test('the legend names the colours in real units, and says what a ring means', async ({ page }) => {
  const id = await openFirstRecording(page, 'legend');
  try {
    const legend = page.getByTestId(TID.meaChipLegend);
    await expect(legend).toBeVisible();
    // ⭐ Real units. The ramp is the settled rank scale (re-confirmed 2026-08-15), and this still
    // asserts only that the legend is in spikes/s and ordered — a particular colour for a
    // particular rate would pin a taste, not a rule.
    await expect(legend).toContainText('spikes/s');
    await expect(legend).toContainText('quiet');
    await expect(legend).toContainText('busy');

    // 🔴 **A PAD WITH NO SPIKES IS A RING, AND THE LEGEND SAYS WHAT THAT MEANS.** His correction,
    // 2026-08-14: among the pads that WERE wired up, many have no neuron near them — so this is the
    // ordinary case and must never be worded as a fault. If someone later "tidies" this into "dead
    // electrode", this goes red.
    const silent = page.getByTestId(TID.meaChipLegendSilent);
    await expect(silent).toContainText('no neuron');
    await expect(silent).not.toContainText(/dead|failed|broken|faulty/i);
  } finally {
    await deleteProject(page, id);
  }
});

test('clicking a pad reads it — the electrode is NAMED, and the spikes are drawn', async ({
  page,
}) => {
  const id = await openFirstRecording(page, 'click a pad');
  try {
    await expect(page.getByTestId(TID.meaTraceIdle)).toBeVisible();

    // Keyboard, deliberately: a canvas is the easiest place in the app to leave keyboard-dead, and
    // 001 shipped exactly that bug on this feature's first screen. Arrow keys pick the first pad.
    await page.getByTestId(TID.meaChipMap).locator('[role="application"]').focus();
    await page.keyboard.press('ArrowRight');

    const facts = page.getByTestId(TID.meaTraceFacts);
    await expect(facts).toBeVisible({ timeout: SHORT });
    // ⭐ It NAMES the electrode — MaxWell's own id, exact, because the file states it.
    await expect(facts).toContainText('ELECTRODE', { ignoreCase: true });
    await expect(facts).toContainText('CHANNEL', { ignoreCase: true });
    // ⚠️ Scoped to the close-up deliberately. `mea-trace-chart` IS unique again (the strip carries
    // `mea-trace-overview-chart`), so a bare locator would pass — but this asserts MORE than the old
    // line did, not less, and it stays correct if a third chart ever appears on this screen.
    await expect(page.getByTestId(TID.meaTraceDetail).getByTestId(TID.meaTraceChart)).toBeVisible();
    // ⛔ **THE SLIDER IS GONE** (004). What sits where the scrubber was is the whole recording on a
    // strip, and a Back button with nowhere to go yet — disabled, never hidden.
    await expect(page.getByTestId(TID.meaTraceOverview)).toBeVisible();
    await expect(page.getByTestId(TID.meaTraceBack)).toBeVisible();
    await expect(page.getByTestId(TID.meaTraceBack)).toBeDisabled();
  } finally {
    await deleteProject(page, id);
  }
});

test('🔴 with no decoder the waveform SAYS SO — and the spike ticks are drawn anyway', async ({
  page,
}) => {
  // 🔴 **THE POINT OF THE WHOLE SCREEN.** A railed window looks EXACTLY like a genuinely silent
  // electrode, so drawing it unlabelled would be a laundered answer. The fixture's raw stream is
  // declared and never written — the real files' behaviour through the published decoder — so this
  // exercises the real failure.
  const id = await openFirstRecording(page, 'no decoder');
  try {
    await page.getByTestId(TID.meaChipMap).locator('[role="application"]').focus();
    await page.keyboard.press('ArrowRight');
    await expect(page.getByTestId(TID.meaTraceFacts)).toBeVisible({ timeout: SHORT });

    const flat = page.getByTestId(TID.meaTraceFlat);
    await expect(flat).toBeVisible({ timeout: SHORT });
    await expect(flat).toContainText('did not decode');
    // ⭐ And it says the ticks are still good, so he does not throw the whole panel away.
    await expect(flat).toContainText(/unaffected|correct/i);

    // 🔴 **ON THE PAGE, AS A LIVE REGION — ⛔ NEVER BEHIND THE `?`.** 001 moved prose behind the `?`
    // on his instruction; that was a fact about the APP. This is a fact about HIS DATA right now,
    // which is R3's standing exception. A fact he must not be able to miss cannot live somewhere he
    // has to hover to find.
    // It is announced, not merely present: `LiveWarning` renders a `role="status"` region, so a
    // reader who is not looking at that corner of the screen is still told.
    await expect(flat.locator('[role="status"]')).toBeVisible();
    // ⛔ And it is NOT inside a `?` disclosure — the whole point. `Help` renders a button; there
    // must not be one wrapping this warning.
    await expect(flat.getByRole('button')).toHaveCount(0);

    // The chart is still there, with the ticks on it. (Scoped to the close-up for the same reason
    // as above — 004 mounts `TraceChart`, and its hard-coded testid, twice on this screen.)
    await expect(page.getByTestId(TID.meaTraceDetail).getByTestId(TID.meaTraceChart)).toBeVisible();
  } finally {
    await deleteProject(page, id);
  }
});

test('a missing decoder is said ONCE, on opening — before any pad is clicked', async ({ page }) => {
  // ⭐ Item R3.8: the app can know at open time whether the MaxLab waveform decoder is on this
  // machine, so it says so up front instead of springing it per trace. Both states are driven from
  // the REAL layout payload with only the flag flipped, so this holds on any machine — with or
  // without MaxLab Live installed.
  let present = false;
  await page.route('**/api/mea/*/recordings/*/layout**', async (route) => {
    const real = await route.fetch();
    const body = await real.json();
    body.decoder_present = present;
    await route.fulfill({ response: real, json: body });
  });

  const id = await openFirstRecording(page, 'decoder said early');
  try {
    const note = page.getByTestId(TID.meaOpenNoDecoder);
    await expect(note).toBeVisible({ timeout: SHORT });
    // No pad has been clicked — the fact is already on the page, in MeaTrace's own vocabulary.
    await expect(page.getByTestId(TID.meaTraceIdle)).toBeVisible();
    await expect(note).toContainText('part of MaxLab Live');
    await expect(note).toContainText('not installed on this machine');
    await expect(note).toContainText(/unaffected/i);
    // ⛔ Quiet and on the page — never behind a `?`, and never a fault word (§7.5).
    await expect(note.getByTestId(TID.help)).toHaveCount(0);
    await expect(note).not.toContainText(/dead|failed|broken|flat|inactive/i);

    // ...and with the decoder present, the screen says nothing about it.
    present = true;
    await page.getByTestId(TID.meaCloseRecording).click();
    await rowFor(page, MEA_FIXTURE.labels[0]).getByTestId(TID.meaOpenButton).click();
    await expect(page.getByTestId(TID.meaChipMap)).toBeVisible({ timeout: FIRST_PAINT });
    await expect(page.getByTestId(TID.meaOpenNoDecoder)).toHaveCount(0);
  } finally {
    await page.unrouteAll();
    await deleteProject(page, id);
  }
});

test('⛔ there is NO chip-seating warning anywhere on this screen', async ({ page }) => {
  // ⛔ **NOT AN OMISSION — A REQUIREMENT.** `features/electrodes/MeaTracePanel` says the chip's
  // seating is provisional because it works from a mosaic and nobody has established which corner
  // the chip's origin landed in. This screen works in the chip's OWN frame: the file states its
  // `electrode`/`x_um`/`y_um`, so every id is exact. Importing that doubt would make the screen lie.
  const id = await openFirstRecording(page, 'no seating doubt');
  try {
    await page.getByTestId(TID.meaChipMap).locator('[role="application"]').focus();
    await page.keyboard.press('ArrowRight');
    await expect(page.getByTestId(TID.meaTraceFacts)).toBeVisible({ timeout: SHORT });

    const screen = page.getByTestId(TID.meaOpen);
    await expect(screen).not.toContainText(/provisional/i);
    await expect(screen).not.toContainText(/which way the chip sits/i);
    await expect(screen).not.toContainText(/seating/i);
    await expect(page.getByTestId('mea-provisional')).toHaveCount(0);
  } finally {
    await deleteProject(page, id);
  }
});

test('the colour scale comes from the recording in front of it, not from a constant', async ({
  page,
}) => {
  // ⛔ **I1 — a `Done when` box.** The two fixture recordings have different spike tables (different
  // seeds), so their legends must differ. If anything had baked a maximum in, they would agree.
  await toFilesStep(page, 'two scales');
  await lookIn(page, MEA_FIXTURE.dir);
  await page.getByTestId(TID.meaTickAll).check();
  await page.getByTestId(TID.npCreate).click();
  await page.waitForURL(/\/project\/[^/]+$/, { timeout: 30_000 });
  const id = page.url().split('/').pop()!;
  try {
    await expect(page.getByTestId(TID.meaRecording)).toHaveCount(MEA_FIXTURE.count, {
      timeout: FIRST_PAINT,
    });

    await rowFor(page, MEA_FIXTURE.labels[0]).getByTestId(TID.meaOpenButton).click();
    await expect(page.getByTestId(TID.meaChipLegend)).toBeVisible({ timeout: FIRST_PAINT });
    const first = await page.getByTestId(TID.meaChipLegend).innerText();

    await page.getByTestId(TID.meaCloseRecording).click();
    await rowFor(page, MEA_FIXTURE.labels[1]).getByTestId(TID.meaOpenButton).click();
    await expect(page.getByTestId(TID.meaChipLegend)).toBeVisible({ timeout: FIRST_PAINT });
    const second = await page.getByTestId(TID.meaChipLegend).innerText();

    expect(first).not.toBe(second);
  } finally {
    await deleteProject(page, id);
  }
});

test('one recording at a time — opening one replaces the shelf, and Back returns', async ({
  page,
}) => {
  // *"You pick one to load, and it opens it up."* ⛔ Comparing recordings side by side was
  // explicitly rejected.
  const id = await openFirstRecording(page, 'one at a time');
  try {
    await expect(page.getByTestId(TID.meaShelf)).toHaveCount(0);
    await page.getByTestId(TID.meaCloseRecording).click();
    await expect(page.getByTestId(TID.meaShelf)).toBeVisible({ timeout: SHORT });
    await expect(page.getByTestId(TID.meaRecording)).toHaveCount(MEA_FIXTURE.count);
    await expect(page.getByTestId(TID.meaChipMap)).toHaveCount(0);
  } finally {
    await deleteProject(page, id);
  }
});

// =================================================================================================
// 6 · the whole recording, and dragging a stretch to zoom into it (plan 004)
// =================================================================================================
//
// ⭐ **HIS WORDS, 2026-08-15:** *"I don't like the slider bar. What I want is the MEA trace … more
// like the matplotlib … so I have the whole trace, and then I can make a rectangle around the area
// I want to zoom in, then I can go back."* So the slider went, and what replaced it is two pictures
// — a strip holding the whole recording, and the close-up under it — with matplotlib's own
// home/back/forward between them.
//
// ⛔ **THE FIXTURE NEVER SHOWS `mea-trace-needs-envelope`, AND THAT IS CORRECT.** The synthetic
// recording is 60,000 samples at 20 kHz = 3.0 s, so the *whole* recording is well inside the route's
// live-read budget (`LIVE_READ_MAX_SAMPLES = 200_000`) and is folded to min/max columns straight off
// the file. The precomputed envelope is what his 300 s recordings need, and there is nothing on a
// 19 kB fixture that could honestly exercise it. The testid is registered and asserted ABSENT here;
// the cache path itself belongs to `tests/api/`, where the file can be made big enough to mean it.
//
// ⚠️ **THE READOUT IS THE INSTRUMENT.** Every assertion below reads `mea-trace-pos`, which states the
// range the SERVER ACTUALLY SERVED. Comparing the readout before and after a gesture is the only way
// to see a zoom from outside a canvas — and it is also the thing he reads, so a test that passes on
// it is a test of what he can see.

/** The close-up's readout: `0.00–3.00 s of 3 s · 3.00 s wide · 42 spikes in view`. */
async function posText(page: Page): Promise<string> {
  return ((await page.getByTestId(TID.meaTracePos).textContent()) ?? '').trim();
}

/** The `N s wide` out of a readout. Throws rather than returning NaN — a silently-NaN comparison
 *  passes every `<` it is put in, which is the one way this whole section could pass while broken. */
function widthOf(readout: string): number {
  const m = readout.match(/·\s*([\d.]+)\s*s wide/);
  if (!m) throw new Error(`no width in the readout: ${JSON.stringify(readout)}`);
  return Number(m[1]);
}

/** The `of N s` — the recording's own duration, as the panel states it. */
function durationOf(readout: string): number {
  const m = readout.match(/\bof\s+([\d.]+)\s*s\b/);
  if (!m) throw new Error(`no duration in the readout: ${JSON.stringify(readout)}`);
  return Number(m[1]);
}

/**
 * `TraceChart`'s gutters, in CSS px (`TRACE_PAD` in `web/src/core/trace/TraceChart.tsx`). They are
 * copied rather than imported because importing the component would drag React and a CSS module
 * into the test runner. ⚠️ A press inside the left gutter is NOT a time and the brush ignores it
 * outright, so a drag aimed at the raw element box would silently do nothing.
 */
const PAD_L = 46;
const PAD_R = 8;

/**
 * Drag sideways across one of the two pictures, from `fromFrac` to `toFrac` of its PLOT area.
 * Real pointer events, moved in steps — the brush watches pointermove, and a single jump is not a
 * gesture a hand ever makes.
 */
async function dragAcross(
  page: Page,
  testid: string,
  fromFrac: number,
  toFrac: number,
): Promise<void> {
  const el = page.getByTestId(testid);
  await el.scrollIntoViewIfNeeded();
  const box = await el.boundingBox();
  if (!box) throw new Error(`${testid} has no box to drag across`);
  const plotX = box.x + PAD_L;
  const plotW = box.width - PAD_L - PAD_R;
  const y = box.y + box.height / 2;
  await page.mouse.move(plotX + plotW * fromFrac, y);
  await page.mouse.down();
  await page.mouse.move(plotX + plotW * (fromFrac + (toFrac - fromFrac) / 2), y, { steps: 5 });
  await page.mouse.move(plotX + plotW * toFrac, y, { steps: 5 });
  await page.mouse.up();
}

/** Wait until the readout is no longer `from` — the view he asked for has been fetched and drawn.
 *  ⚠️ The close-up refetches on a 90 ms settle, so nothing here may assert synchronously. */
async function posChangedFrom(page: Page, from: string): Promise<string> {
  await expect
    .poll(() => posText(page), { timeout: SHORT, message: 'the view should have changed' })
    .not.toBe(from);
  return posText(page);
}

test('the strip shows the WHOLE recording, and that is where he opens', async ({ page }) => {
  // ⭐ *"I have the whole trace"* — the first thing on the panel is the whole session, not a keyhole
  // into it, and the close-up starts showing all of it too. His answer on the opening view was
  // **open at the start**: no jump to the first spike.
  const id = await openFirstRecording(page, 'whole recording');
  try {
    await pickFirstPad(page);

    const strip = page.getByTestId(TID.meaTraceOverview);
    await expect(strip).toBeVisible();
    await expect(strip.getByTestId(TID.meaTraceOverviewChart)).toBeVisible();
    await expect(page.getByTestId(TID.meaTraceDetail)).toBeVisible();
    await expect(page.getByTestId(TID.meaTraceNav)).toBeVisible();

    // ⛔ It is showing the recording, not an apology for not having read it — see the section note.
    await expect(page.getByTestId(TID.meaTraceNeedsEnvelope)).toHaveCount(0);
    await expect(page.getByTestId(TID.meaTraceError)).toHaveCount(0);

    const pos = await posText(page);
    // ⭐ The view IS the whole recording: its width is the recording's own duration. Half a second
    // of slack because the readout prints the duration to whole seconds (`toFixed(0)`).
    expect(Math.abs(widthOf(pos) - durationOf(pos))).toBeLessThanOrEqual(0.5);
    // ...and it starts at the beginning. ⛔ The auto-jump to the first spike was deleted.
    expect(pos).toMatch(/^0\.00[–-]/);

    // Nowhere to go back to yet, and the button says so by being disabled rather than absent.
    await expect(page.getByTestId(TID.meaTraceBack)).toBeDisabled();
    await expect(page.getByTestId(TID.meaTraceForward)).toBeDisabled();
    await expect(page.getByTestId(TID.meaTraceHome)).toBeEnabled();
  } finally {
    await deleteProject(page, id);
  }
});

test('dragging a stretch of the close-up zooms into it', async ({ page }) => {
  // ⭐ *"I can make a rectangle around the area I want to zoom in"* — the gesture IS the feature.
  const id = await openFirstRecording(page, 'drag to zoom');
  try {
    await pickFirstPad(page);
    const before = await posText(page);

    await dragAcross(page, TID.meaTraceDetail, 0.2, 0.7);

    const after = await posChangedFrom(page, before);
    // 🔴 Strictly narrower — the whole point. A drag that widened, or that snapped to something
    // fixed, would still "change" the readout, so the comparison is on the width itself.
    expect(widthOf(after)).toBeLessThan(widthOf(before));
    // ⛔ And the recording did not change under him: the denominator is the same.
    expect(durationOf(after)).toBe(durationOf(before));
    // The strip stays on the WHOLE recording — it is a place-finder, not a second close-up.
    // ⛔ And it does NOT claim a spike count. It is given no spikes because it draws none, so the
    // chart's default label would announce "0 spikes" for a pad that fired thousands of times —
    // laundering *unreadable* into *silent* on the one screen built to refuse exactly that.
    const stripLabel = page
      .getByTestId(TID.meaTraceOverview)
      .getByTestId(TID.meaTraceOverviewChart);
    await expect(stripLabel).toHaveAttribute(
      'aria-label',
      new RegExp(`whole recording, 0 to ${durationOf(before).toFixed(0)} seconds`, 'i'),
    );
    await expect(stripLabel).not.toHaveAttribute('aria-label', /\bspikes\b/);
  } finally {
    await deleteProject(page, id);
  }
});

test('Back returns exactly where he was, and only then does Forward light up', async ({ page }) => {
  // ⭐ *"then I can go back"*. matplotlib's history, ported — `back`/`forward` clamp and never wrap,
  // and the buttons are DISABLED rather than hidden so the panel does not jump under the pointer.
  const id = await openFirstRecording(page, 'back and forward');
  try {
    await pickFirstPad(page);
    const back = page.getByTestId(TID.meaTraceBack);
    const forward = page.getByTestId(TID.meaTraceForward);
    const whole = await posText(page);

    await dragAcross(page, TID.meaTraceDetail, 0.15, 0.6);
    const zoomed = await posChangedFrom(page, whole);
    await expect(back).toBeEnabled();
    await expect(forward).toBeDisabled();

    await back.click();
    // 🔴 EXACTLY where he was — the same string, not merely a wider view.
    await expect
      .poll(() => posText(page), { timeout: SHORT })
      .toBe(whole);
    await expect(forward).toBeEnabled();
    await expect(back).toBeDisabled();

    // ...and Forward is the other half of the same promise.
    await forward.click();
    await expect
      .poll(() => posText(page), { timeout: SHORT })
      .toBe(zoomed);
    await expect(forward).toBeDisabled();
  } finally {
    await deleteProject(page, id);
  }
});

test('a keyboard-only zoom says what it did', async ({ page }) => {
  // ⚠️ **THIS APP HAS SHIPPED A KEYBOARD-DEAD CANVAS ONCE.** The close-up takes focus and `+`/`-`
  // zoom (R12.6 / R13.7 — the house meanings, not a third vocabulary), and because a canvas tells a
  // screen reader nothing, each new range is announced in a visually hidden `role="status"`.
  //
  // ⚠️ The announcement is made when the DATA LANDS, not on the keystroke: the spike count is not
  // known until the server answers, and announcing early said "0 spikes in view" every time — false
  // in exactly the place a sighted user reads it straight off the picture. So this waits.
  const id = await openFirstRecording(page, 'keyboard zoom');
  try {
    await pickFirstPad(page);
    const said = page.getByTestId(TID.meaTraceSaid);
    await expect(said).toHaveAttribute('role', 'status');
    const before = ((await said.textContent()) ?? '').trim();

    await page.getByTestId(TID.meaTraceDetail).focus();
    await expect(page.getByTestId(TID.meaTraceDetail)).toBeFocused();
    await page.keyboard.press('+');

    await expect
      .poll(() => said.textContent().then((t) => (t ?? '').trim()), {
        timeout: SHORT,
        message: 'the new range should be announced once its data lands',
      })
      .not.toBe(before);
    const now = ((await said.textContent()) ?? '').trim();
    expect(now).not.toBe('');
    expect(now).toContain('spikes in view');
    // It announces the view he is actually on — the same range the readout states.
    expect(now).toBe(await posText(page));
    // ...and `+` meant zoom IN.
    expect(widthOf(now)).toBeLessThan(widthOf(before));
  } finally {
    await deleteProject(page, id);
  }
});

test('a plain click is not a zoom, and leaves no history behind it', async ({ page }) => {
  // 🔴 matplotlib's threshold and matplotlib's reason: a release within 5 px of the press is a
  // click, refused outright. Without it every stray click would bury the place he was in a pile of
  // identical history entries — and the Back button would stop meaning anything.
  const id = await openFirstRecording(page, 'click is not a zoom');
  try {
    await pickFirstPad(page);
    const before = await posText(page);

    const el = page.getByTestId(TID.meaTraceDetail);
    await el.scrollIntoViewIfNeeded();
    const box = await el.boundingBox();
    if (!box) throw new Error('the close-up has no box to click');
    // Mid-plot, well clear of the left number gutter — a press THERE is ignored for a different
    // reason, and would pass this test without proving anything.
    await page.mouse.click(box.x + PAD_L + (box.width - PAD_L - PAD_R) / 2, box.y + box.height / 2);

    // Longer than the close-up's 90 ms settle: if a fetch had been queued it would have landed.
    await page.waitForTimeout(500);
    expect(await posText(page)).toBe(before);
    // ⛔ And nothing was PUSHED — a history entry that merely looked identical would still light
    // Back up, and this is the assertion that can tell those two apart.
    await expect(page.getByTestId(TID.meaTraceBack)).toBeDisabled();
    await expect(page.getByTestId(TID.meaTraceForward)).toBeDisabled();
  } finally {
    await deleteProject(page, id);
  }
});

test('Next spike recenters the view at the same width — and Back undoes the jump', async ({
  page,
}) => {
  // ⭐ Spike stepping (2026-08-16). The step consults the WHOLE recording's spike list (the same
  // one the strip's density row draws), so a jump works beyond the loaded close-up; the view
  // recenters on the target at its current width and pushes history like any other move.
  const id = await openFirstRecording(page, 'spike stepping');
  try {
    await pickFirstPad(page); // channel 0 — the fixture's busiest pad, so spikes exist (a
    //                           FIXTURE fact, permitted in tests/)
    const whole = await posText(page);

    // Zoom in first: on the opening view the centre is mid-recording and a whole-width window
    // cannot recenter, so the honest starting point is a narrow one.
    await dragAcross(page, TID.meaTraceDetail, 0.05, 0.25);
    const zoomed = await posChangedFrom(page, whole);

    const next = page.getByTestId(TID.meaTraceNextSpike);
    await expect(next).toBeEnabled();
    await next.click();
    const jumped = await posChangedFrom(page, zoomed);
    // 🔴 The width did NOT change — a jump is a recentring, never a zoom.
    expect(widthOf(jumped)).toBeCloseTo(widthOf(zoomed), 2);

    // Back undoes the jump exactly, like any other move.
    await page.getByTestId(TID.meaTraceBack).click();
    await expect.poll(() => posText(page), { timeout: SHORT }).toBe(zoomed);

    // ...and the keyboard spells the same gesture: N forward, P back again.
    await page.getByTestId(TID.meaTraceDetail).focus();
    await page.keyboard.press('n');
    const byKey = await posChangedFrom(page, zoomed);
    expect(widthOf(byKey)).toBeCloseTo(widthOf(zoomed), 2);
    await page.keyboard.press('p');
    await expect
      .poll(() => posText(page).then(widthOf), { timeout: SHORT })
      .toBeCloseTo(widthOf(zoomed), 2);
  } finally {
    await deleteProject(page, id);
  }
});

// =================================================================================================
// 7 · the chip-map quality-of-life bundle (2026-08-15)
// =================================================================================================

test('clicking a busiest-pads row selects that pad, with the same announcement a click gets', async ({
  page,
}) => {
  // ⭐ The list is ranked from the same joined pads the map draws. The fixture routes channel 0 as
  // the busiest pad on purpose (a FIXTURE fact, permitted in tests/), so the top row is knowable.
  const id = await openFirstRecording(page, 'busiest pads');
  try {
    const list = page.getByTestId(TID.meaChipBusiest);
    await expect(list).toBeVisible();
    const first = list.getByTestId(TID.meaChipBusiestPad).first();
    await expect(first).toHaveAttribute('data-channel', '0');

    // Nothing selected yet: the frame control is DISABLED (never hidden), and the zoom readout
    // states Fit as 100% (R7.6 — these say what they do, no `?`).
    await expect(page.getByTestId(TID.meaChipFrameSelected)).toBeDisabled();
    await expect(page.getByTestId(TID.meaChipZoomLevel)).toHaveText(/%$/);

    await first.click();
    // The row shows selected, the live region announces it, and the trace panel starts reading it —
    // exactly what a canvas click produces. One selection mechanism, two doors.
    await expect(first).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByTestId(TID.meaChipSaid)).toContainText('Electrode', { timeout: SHORT });
    await expect(page.getByTestId(TID.meaTraceFacts)).toBeVisible({ timeout: SHORT });
    await expect(page.getByTestId(TID.meaChipFrameSelected)).toBeEnabled();
  } finally {
    await deleteProject(page, id);
  }
});

test('the shelf carries a one-line summary — count, total length, total size', async ({ page }) => {
  await toFilesStep(page, 'shelf summary');
  await lookIn(page, MEA_FIXTURE.dir);
  await page.getByTestId(TID.meaTickAll).check();
  await page.getByTestId(TID.npCreate).click();
  await page.waitForURL(/\/project\/[^/]+$/, { timeout: 30_000 });
  const id = page.url().split('/').pop()!;
  try {
    const summary = page.getByTestId(TID.meaShelfSummary);
    await expect(summary).toBeVisible({ timeout: FIRST_PAINT });
    await expect(summary).toContainText(`${MEA_FIXTURE.count} recordings`);
    // The totals, in the shelf's own grammar: a duration and a size, joined with ·. (The copying
    // part is only there while a copy runs, which a 19 kB fixture finishes too fast to pin.)
    await expect(summary).toContainText(/\d[\d.]*\s?s\b/);
    await expect(summary).toContainText(/\d[\d.]*\s?(B|kB|MB|GB)\b/);
    await expect(summary).toContainText('·');
  } finally {
    await deleteProject(page, id);
  }
});

test('the shelf sorts and filters as a view — "As added" is the default, renaming keeps working', async ({
  page,
}) => {
  // ⚠️ Stubbed, deterministically: the two fixture recordings share an assay and near-identical
  // facts, so a real shelf cannot show a filter or prove an order flipped. The stub is the same
  // wire shape the earlier copy/missing tests use.
  const row = (over: Record<string, unknown>) => ({
    id: 'rec',
    label: '',
    run_id: '',
    assay: '',
    source_path: 'D:/his/data.raw.h5',
    stored_path: 'recordings/rec/data.raw.h5',
    copy_state: 'stored',
    copy_pct: 0,
    copy_error: '',
    added: '',
    bytes: 0,
    missing: false,
    source_present: true,
    duration_s: 300,
    n_channels: 726,
    n_samples: 10,
    n_spikes: 0,
    ...over,
  });
  await page.route('**/api/mea/*/recordings', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        analysis_id: 'x',
        recordings: [
          row({ id: 'rec_a', label: 'zzz quiet', assay: 'Network', n_spikes: 10,
            added: '2026-08-01T10:00:00Z' }),
          row({ id: 'rec_b', label: 'aaa busy', assay: 'ActivityScan', n_spikes: 999,
            added: '2026-08-10T10:00:00Z' }),
        ],
      }),
    });
  });

  await toFilesStep(page, 'shelf sort');
  await page.getByTestId(TID.npCreate).click();
  await page.waitForURL(/\/project\/[^/]+$/, { timeout: 30_000 });
  const id = page.url().split('/').pop()!;
  try {
    const labels = page.getByTestId(TID.meaRecordingLabel);
    await expect(page.getByTestId(TID.meaRecording)).toHaveCount(2, { timeout: FIRST_PAINT });

    // Default = the document's own order, exactly what the shelf always was.
    await expect(page.getByTestId(TID.meaShelfSort)).toHaveValue('as-added');
    await expect(labels.first()).toHaveText('zzz quiet');

    // Sort by spikes: the busier row rises. Client-side — no request leaves the page.
    await page.getByTestId(TID.meaShelfSort).selectOption('spikes');
    await expect(labels.first()).toHaveText('aaa busy');

    // ...and by name.
    await page.getByTestId(TID.meaShelfSort).selectOption('name');
    await expect(labels.first()).toHaveText('aaa busy');

    // Filter by type: two assays on the shelf, so the control is there; one type stays visible.
    await page.getByTestId(TID.meaShelfFilter).selectOption('Network');
    await expect(page.getByTestId(TID.meaRecording)).toHaveCount(1);
    await expect(labels.first()).toHaveText('zzz quiet');

    // Renaming still works on a sorted, filtered view (the row keeps its minted id).
    await labels.first().click();
    await expect(page.getByTestId(TID.meaRenameInput)).toBeVisible({ timeout: SHORT });
    await page.getByTestId(TID.meaRenameInput).press('Escape');
    await expect(page.getByTestId(TID.meaRenameInput)).toHaveCount(0);
  } finally {
    await page.unrouteAll();
    await deleteProject(page, id);
  }
});

test('each row says whether the end-to-end read is done, offers it, and names a same-file twin', async ({
  page,
}) => {
  // ⚠️ Stubbed: the envelope states this exercises (one ready, one not, a POST that finishes)
  // need controlled ids, so both the shelf GET and the envelopes routes are served here. The
  // wording mirrors MeaTrace's — same one-off read, same sentence.
  const row = (over: Record<string, unknown>) => ({
    id: 'rec',
    label: '',
    run_id: '000690',
    assay: 'Network',
    source_path: 'D:/his/Network/000690/data.raw.h5',
    stored_path: 'recordings/rec/data.raw.h5',
    copy_state: 'stored',
    copy_pct: 0,
    copy_error: '',
    added: '2026-08-14T00:00:00Z',
    bytes: 100,
    missing: false,
    source_present: true,
    duration_s: 300,
    n_channels: 726,
    n_samples: 10,
    n_spikes: 22_367,
    ...over,
  });
  await page.route('**/api/mea/*/recordings', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        analysis_id: 'x',
        recordings: [
          row({ id: 'rec_a', label: 'Network/000690' }),
          // ⭐ The SAME source file, added twice — the duplicate note's case.
          row({ id: 'rec_b', label: 'the same run again' }),
        ],
      }),
    });
  });
  let posted = false;
  await page.route('**/api/mea/*/recordings/envelopes', async (route) => {
    if (route.request().method() === 'POST') posted = true;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        analysis_id: 'x',
        recordings: [
          { recording_id: 'rec_a', label: 'Network/000690', ready: true, job_id: '', pct: 0 },
          // Not read yet — until the backfill POST lands, after which it reports ready.
          { recording_id: 'rec_b', label: 'the same run again', ready: posted, job_id: '', pct: 0 },
        ],
        started: posted ? ['job_x'] : [],
      }),
    });
  });

  await toFilesStep(page, 'ready column');
  await page.getByTestId(TID.npCreate).click();
  await page.waitForURL(/\/project\/[^/]+$/, { timeout: 30_000 });
  const id = page.url().split('/').pop()!;
  try {
    const readyRow = rowFor(page, 'Network/000690');
    const unreadRow = rowFor(page, 'the same run again');
    await expect(page.getByTestId(TID.meaRecording)).toHaveCount(2, { timeout: FIRST_PAINT });

    // One is done and says so quietly; the other offers the read, in MeaTrace's own words.
    await expect(readyRow.getByTestId(TID.meaRecordingReady)).toHaveText('Whole recording ready', {
      timeout: SHORT,
    });
    const readNow = unreadRow.getByTestId(TID.meaReadNow);
    await expect(readNow).toBeVisible();
    await expect(readNow).toHaveText('Read it now');

    // ⭐ Both rows carry the same-file note, each naming the OTHER row. (The quotes around the
    // name are typographic, so the assertions match on the words.)
    await expect(readyRow.getByTestId(TID.meaRecordingDuplicate)).toContainText(
      /same file as .the same run again./,
    );
    await expect(unreadRow.getByTestId(TID.meaRecordingDuplicate)).toContainText(
      /same file as .Network\/000690./,
    );

    // Clicking fires the EXISTING backfill POST (no new endpoint), and the row lands on ready.
    await readNow.click();
    await expect(unreadRow.getByTestId(TID.meaRecordingReady)).toHaveText(
      'Whole recording ready',
      { timeout: SHORT },
    );
    expect(posted, 'the click must reach POST …/recordings/envelopes').toBe(true);
  } finally {
    await page.unrouteAll();
    await deleteProject(page, id);
  }
});

test('the spread chart counts pads per legend band, and a click highlights the band', async ({
  page,
}) => {
  // ⭐ Accepted 2026-08-15 (re-asked with MAXWELL §7.2's evidence). The fixture routes one pad with
  // deliberately no spikes, so the no-spike bar is real on a 19 kB file.
  const id = await openFirstRecording(page, 'spread chart');
  try {
    const chart = page.getByTestId(TID.meaChipSpread);
    await expect(chart).toBeVisible();

    // 🔴 The no-spike bar exists, counts at least the fixture's silent pad, and speaks the
    // approved vocabulary — never a fault word.
    const silentBar = chart.locator(`[data-testid="${TID.meaChipSpreadBar}"][data-band="silent"]`);
    await expect(silentBar).toBeVisible();
    const n = Number(await silentBar.getAttribute('data-count'));
    expect(n).toBeGreaterThanOrEqual(1);
    await expect(chart).not.toContainText(/dead|failed|broken|inactive/i);

    // ⭐ MAXWELL §7.3 — the recording's length sits beside the silent count, in the legend row of
    // this same block. A silent tally without its window is not a number anybody can use.
    await expect(page.getByTestId(TID.meaChipLegendSilent)).toContainText(/in this .* recording/);

    // Click to highlight, click again to clear.
    await silentBar.click();
    await expect(silentBar).toHaveAttribute('aria-pressed', 'true');
    await silentBar.click();
    await expect(silentBar).toHaveAttribute('aria-pressed', 'false');
  } finally {
    await deleteProject(page, id);
  }
});

test('Colors follow the view: off by default, and the window length stays honest when on', async ({
  page,
}) => {
  // ⭐ The mode (2026-08-16): zoom the trace and the chip re-colours by who fired in that stretch.
  // What a canvas test CAN honestly pin is the words: MAXWELL §7.3 says the length beside the
  // no-spikes count must be the length the tally was actually counted over — so when the mode is
  // on and he zooms, "in this 3.0 s recording" must become "in the … stretch shown", in both the
  // legend and the spread chart, and revert when the tally is the whole recording again.
  const id = await openFirstRecording(page, 'follow the view');
  try {
    const row = page.getByTestId(TID.meaFollowView);
    const tick = page.getByTestId(TID.meaFollowViewTick);
    await expect(row).toBeVisible();
    await expect(tick).not.toBeChecked(); // default OFF — the whole recording is the settled default
    // R7: a mode control earns a `?`.
    await expect(row.getByTestId(TID.help)).toBeVisible();

    const silentLine = page.getByTestId(TID.meaChipLegendSilent);
    await expect(silentLine).toContainText(/in this .* recording/);

    await pickFirstPad(page);
    await tick.check();
    // On, but still showing the whole recording: the tally (and its words) must not pretend a
    // window exists where there is none.
    await expect(silentLine).toContainText(/in this .* recording/);

    await dragAcross(page, TID.meaTraceDetail, 0.2, 0.7);
    await expect(silentLine).toContainText(/in the .* stretch shown/, { timeout: SHORT });
    await expect(silentLine).not.toContainText('recording');
    // The spread chart re-words from the same payload, so the two blocks cannot disagree.
    const silentBar = page
      .getByTestId(TID.meaChipSpread)
      .locator(`[data-testid="${TID.meaChipSpreadBar}"][data-band="silent"]`);
    await expect(silentBar).toHaveAttribute('aria-label', /stretch shown/);

    // Off again: the whole-recording tally and its wording come straight back.
    await tick.uncheck();
    await expect(silentLine).toContainText(/in this .* recording/, { timeout: SHORT });
  } finally {
    await deleteProject(page, id);
  }
});

test('Home is itself undoable — one Back and he has his stretch again', async ({ page }) => {
  // 🔴 **THE ONE THAT LOOKS LIKE A BUG AND IS NOT.** `home` PUSHES the first view rather than
  // rewinding to it (matplotlib's `_Stack.home`), so a mis-aimed "Whole recording" never costs him
  // the stretch he spent time finding. It is the single most important property of the view stack.
  const id = await openFirstRecording(page, 'home is undoable');
  try {
    await pickFirstPad(page);
    const whole = await posText(page);

    await dragAcross(page, TID.meaTraceDetail, 0.25, 0.75);
    const zoomed = await posChangedFrom(page, whole);

    await page.getByTestId(TID.meaTraceHome).click();
    await expect
      .poll(() => posText(page), { timeout: SHORT })
      .toBe(whole);

    await page.getByTestId(TID.meaTraceBack).click();
    await expect
      .poll(() => posText(page), { timeout: SHORT, message: 'Home must be undoable with one Back' })
      .toBe(zoomed);
  } finally {
    await deleteProject(page, id);
  }
});
