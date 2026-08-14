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
