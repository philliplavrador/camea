// ─────────────────────────────────────────────────────────────────────────────────────────────
// ⏱️ **R48 — EVERY WAIT SHOWS A BAR AND SAYS HOW LONG IS LEFT.**
//
// *"everywhere where there's gonna be like some sort of loading or waiting period, make sure there's
// like some sort of progress bar with an ETA, like everywhere in the app."* — him, 2026-08-16. And,
// when offered a way out for waits that cannot be estimated: *"i find it hard you cannot figure out
// an ETA at all, so try."*
//
// ⚠️ **THIS SPEC IS IN THE LIVE LANE, AND THAT IS THE POINT.** R8's only existing proof,
// `place-eta.spec.ts`, sits on `RETIRED_SNAPSHOT_SPECS` and **does not run by default** — it enters
// through the retired snapshot task card. A ruling backed only by a spec nobody runs is a ruling
// backed by nothing. Everything asserted here runs on `npx playwright test` with no env var.
//
// ⚠️ **The backend is REAL but the jobs are STUBBED**, the same philosophy as `regions.spec.ts`. A
// genuine minute-long recording read cannot be driven from a browser test, and the clauses being
// proved are DOM contracts — what the screen does with the numbers, not whether the numbers are
// right. The arithmetic is proved where it can be judged: `tests/unit/test_jobs.py` (the estimator,
// including the pinned-fraction-counts-UP fact behind R48b) and `web/src/api/jobs.test.ts` +
// `Progress.test.tsx` (the countdown's re-anchoring and the never-empty slot).
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { test, expect, type Page } from '@playwright/test';
import { SHORT } from './fixture';
import { TID, byId } from './pages';

/** The strip polls `GET /api/jobs/running`. One place builds its body. */
function runningBody(jobs: Array<Record<string, unknown>>) {
  return { status: 200, contentType: 'application/json', body: JSON.stringify({ jobs }) };
}

/** A live job as `to_brief()` serialises it. */
function liveJob(over: Record<string, unknown> = {}) {
  return {
    job_id: 'e2e-wait',
    kind: 'mea_envelope',
    state: 'running',
    said_as: 'reading the recording end to end',
    phase: 'envelope',
    pct: 31.0,
    message: 'reading block 78 / 249',
    elapsed_s: 18.0,
    eta_s: 42.0,
    cancellable: true,
    ...over,
  };
}

/**
 * Serve `GET /api/jobs/running` from a mutable list the test can swap mid-flight. Returns a setter
 * so a test can start a job, then finish it, without re-registering the route.
 */
async function stubRunning(page: Page) {
  let jobs: Array<Record<string, unknown>> = [];
  await page.route('**/api/jobs/running', (route) => route.fulfill(runningBody(jobs)));
  return (next: Array<Record<string, unknown>>) => {
    jobs = next;
  };
}

test.describe('R48.8 — anything running is visible from anywhere', () => {
  test('the strip is ABSENT when nothing is running — it never becomes permanent chrome', async ({
    page,
  }) => {
    await stubRunning(page);
    await page.goto('/');
    await expect(byId(page, TID.manager)).toBeVisible();
    // Absent, not merely hidden: an idle app must cost no height at all. DESIGN_BRIEF §1.2 — the app
    // is mostly picture, and a persistent empty band is the furniture the brief exists to avoid.
    await expect(byId(page, TID.runningStrip)).toHaveCount(0);
  });

  test('a running job appears in the strip, named in HIS words, with its time', async ({ page }) => {
    const setJobs = await stubRunning(page);
    await page.goto('/');
    await expect(byId(page, TID.manager)).toBeVisible();

    setJobs([liveJob()]);

    const strip = byId(page, TID.runningStrip);
    await expect(strip).toBeVisible({ timeout: SHORT });

    // R48.6 — the label is the backend's own sentence, not a kind string. "mea_envelope" is not
    // something to show a person.
    const said = byId(page, TID.runningSaid);
    await expect(said).toContainText('reading the recording end to end');
    await expect(said).not.toContainText('mea_envelope');

    // R48.4 — a real estimate, rendered as time remaining.
    await expect(byId(page, TID.runningEta)).toContainText('42 s');

    // R48.2 — it is a real progressbar to a screen reader, carrying its value.
    const bar = strip.getByRole('progressbar');
    await expect(bar).toHaveAttribute('aria-valuenow', '31');
    await expect(bar).toHaveAttribute('aria-label', 'reading the recording end to end');
  });

  test('the strip goes away when the work does', async ({ page }) => {
    const setJobs = await stubRunning(page);
    await page.goto('/');
    setJobs([liveJob()]);
    await expect(byId(page, TID.runningStrip)).toBeVisible({ timeout: SHORT });

    setJobs([]); // the job finished
    await expect(byId(page, TID.runningStrip)).toHaveCount(0, { timeout: SHORT });
  });

  test('it follows you off the screen that started the work', async ({ page }) => {
    // The whole reason he asked for a strip as well as an inline bar: start a one-minute read, walk
    // away from the panel, and the read is still on screen with its time on it.
    const setJobs = await stubRunning(page);
    await page.goto('/');
    setJobs([liveJob()]);
    await expect(byId(page, TID.runningStrip)).toBeVisible({ timeout: SHORT });

    await page.goto('/new');
    await expect(byId(page, TID.newProjectFlow)).toBeVisible();
    await expect(byId(page, TID.runningStrip)).toBeVisible({ timeout: SHORT });
    await expect(byId(page, TID.runningSaid)).toContainText('reading the recording end to end');
  });
});

test.describe('R48.4 — the time slot is NEVER empty', () => {
  test('with no estimate yet it says it is working the time out, and counts up beside it', async ({
    page,
  }) => {
    // The bug this ruling was written against: four screens rendered an ETA <span> that was always
    // ''. An empty slot is indistinguishable from a hang.
    const setJobs = await stubRunning(page);
    await page.goto('/');
    setJobs([liveJob({ eta_s: null, pct: 4.0, elapsed_s: 221 })]);

    const eta = byId(page, TID.runningEta);
    await expect(eta).toBeVisible({ timeout: SHORT });
    await expect(eta).toContainText('working out how long');
    await expect(eta).toContainText('3m 41s'); // the elapsed clock — a number that moves, honestly
    await expect(eta).not.toHaveText(/^\s*$/);
  });

  test('a silent phase still shows a moving number — without the forbidden heartbeat (R48b)', async ({
    page,
  }) => {
    // The CPU build's 3m 40s silent stretch. `eta_s` stays null the whole time and pinning a
    // countdown there would make it count UP (`eta = elapsed·(100−pct)/pct` with pct pinned). The
    // elapsed clock counts up because that is what elapsed does, and it is true.
    const setJobs = await stubRunning(page);
    await page.goto('/');
    setJobs([liveJob({ eta_s: null, pct: 4.0, elapsed_s: 100 })]);
    await expect(byId(page, TID.runningEta)).toContainText('1m 40s', { timeout: SHORT });

    // Two seconds later the SERVER's number has not changed at all…
    await page.waitForTimeout(2_500);
    // …and the screen has still moved, because the client is ticking it.
    await expect(byId(page, TID.runningEta)).not.toContainText('1m 40s');
  });
});

test.describe('R48.9 — an unknown length must not look like a stalled bar', () => {
  test('no denominator means the travelling sliver and NO percentage — never a bar parked at 2%', async ({
    page,
  }) => {
    // The four accepted cases (an unbounded directory walk, an rmtree, a human, a silent kernel
    // phase) send `pct: null`. A bar sitting at the 2% floor for a thirty-second walk reads as a
    // hang, which is the failure this whole ruling exists to prevent.
    const setJobs = await stubRunning(page);
    await page.goto('/');
    setJobs([
      liveJob({
        kind: 'dataset_scan',
        said_as: 'looking through that folder for datasets',
        pct: null,
        eta_s: null,
        message: '14 dataset(s) so far',
      }),
    ]);

    const strip = byId(page, TID.runningStrip);
    await expect(strip).toBeVisible({ timeout: SHORT });

    // A progressbar with NO value is how "running, length unknown" is said to a screen reader.
    const bar = strip.getByRole('progressbar');
    await expect(bar).toHaveAttribute('aria-busy', 'true');
    await expect(bar).not.toHaveAttribute('aria-valuenow', /.*/);

    // And no invented percentage on screen.
    await expect(byId(page, TID.runningSaid)).not.toContainText('%');
  });
});

test.describe('R48.7 — never render a Stop that is not wired', () => {
  test('a stoppable job offers Stop, and pressing it cancels THAT job', async ({ page }) => {
    const setJobs = await stubRunning(page);
    let cancelled: string | null = null;
    await page.route('**/api/jobs/*/cancel', async (route) => {
      cancelled = new URL(route.request().url()).pathname.split('/').slice(-2)[0];
      await route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({ job_id: cancelled, state: 'cancelled' }),
      });
    });

    await page.goto('/');
    setJobs([liveJob({ job_id: 'e2e-stoppable', cancellable: true })]);

    const stop = byId(page, TID.runningStop);
    await expect(stop).toBeVisible({ timeout: SHORT });
    await stop.click();
    await expect.poll(() => cancelled, { timeout: SHORT }).toBe('e2e-stoppable');
  });

  test('an unstoppable job offers NO button — the server decides, not the component', async ({
    page,
  }) => {
    const setJobs = await stubRunning(page);
    await page.goto('/');
    setJobs([liveJob({ cancellable: false })]);

    await expect(byId(page, TID.runningStrip)).toBeVisible({ timeout: SHORT });
    await expect(byId(page, TID.runningStop)).toHaveCount(0);
  });
});

test.describe('R48.10 — never state a falsehood while loading', () => {
  test('a project list in flight does not claim the store is empty', async ({ page }) => {
    // The shape of the bug this clause names: `RecordingShelf` rendered the heading "0 recordings"
    // for the whole time its list was in flight — a confident, wrong count that then swapped. An
    // in-flight fetch and an empty result are different states and must look different.
    await stubRunning(page);
    let release: (() => void) | null = null;
    const held = new Promise<void>((r) => {
      release = r;
    });
    await page.route('**/api/projects', async (route) => {
      await held;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ analyses: [], unreadable: [] }),
      });
    });

    await page.goto('/');
    // While the answer is held, nothing on screen may assert what the answer is.
    const body = page.locator('body');
    await expect(body).not.toContainText('No projects yet', { timeout: 1_500 });

    release?.();
    // Once it lands, the empty state is allowed to say so.
    await expect(byId(page, TID.manager)).toBeVisible({ timeout: SHORT });
  });
});
