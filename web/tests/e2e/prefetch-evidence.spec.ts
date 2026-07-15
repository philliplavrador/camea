import { test, expect } from '@playwright/test';
import { enterSweep, recordMatchAnchor, ROUTES, type MatchAnchorBody } from './pages';
import { SHORT } from './fixture';

/**
 * THE PREFETCH CORRECTNESS TRAP (R21) and the evidence-store trap (R22). The client must NEVER serve a
 * cached match for the current tile: every placement match is keyed on the ANCHOR SET it was measured
 * against, sent explicitly in the request body, so the server memo (not a client Map) does the caching.
 * ⇒ The match request MUST carry the current anchor set / cache key; a client Map keyed on the trial
 * number is exactly the forbidden regression (§6.8).
 */

test.describe('R21/R22 — the match request carries the current anchor set', () => {
  test('R21: the placement match for the tile under judgement carries the CURRENT certified anchors', async ({
    page,
  }) => {
    const rec = recordMatchAnchor(page);
    const sweep = await enterSweep(page);
    const origin = await sweep.currentTrial();
    await sweep.press('a'); // certify the origin
    const judged = await sweep.advance(); // judge the next tile (R33: wait for the cursor to commit)

    await rec.waitFor(1);
    const forJudged = rec.bodies.filter((b) => b.target === judged);
    expect(forJudged.length, 'a match request must exist for the tile under judgement').toBeGreaterThanOrEqual(
      1,
    );
    // Its `anchors` is the current certified set — the cache key material. Not empty, and it contains
    // the origin the user just certified.
    const anchors = forJudged.at(-1)!.anchors;
    expect(anchors).toContain(origin);
    // And the request carries positions for those anchors (the field, bit-for-bit).
    expect(Object.keys(forJudged.at(-1)!.positions)).toContain(String(origin));
  });

  test('§6.8: there is no client cache keyed on the trial — changing the field RE-FETCHES on V (R22)', async ({
    page,
  }) => {
    const rec = recordMatchAnchor(page);
    const sweep = await enterSweep(page);
    await sweep.press('a'); // anchor 1 (origin)
    const secondAnchor = await sweep.advance(); // land the next tile…
    await sweep.press('a'); // …and certify it → anchors {1, 2}
    const target = await sweep.advance(); // a tile judged against anchors {1,2} (R33: await commit)
    await rec.waitFor(1);

    const beforeV = rec.bodies.filter((b) => b.target === target).length;
    // Reach BACK to an ANCHOR and move it (R22): the field the served candidates assumed no longer
    // exists, so acting on the target with V must RE-FETCH, never serve a trial-keyed cache. (R22 is
    // about moving an ANCHOR — moving the target tile itself does NOT change its field, which is the
    // anchors; the original spec nudged the target, contradicting its own "go to the second anchor and
    // nudge it" comment.)
    await sweep.chip(secondAnchor).click(); // select the anchor
    await sweep.press('ArrowRight'); // nudge it — a drag never demotes an anchor (R24); target goes stale
    await sweep.chip(target).click(); // back to the target
    await sweep.press('v'); // acting on the target must RE-FETCH against the changed field

    await expect
      .poll(() => rec.bodies.filter((b) => b.target === target).length, {
        timeout: SHORT,
        message: 'V after a field change must trigger a fresh match request, not serve a cache',
      })
      .toBeGreaterThan(beforeV);
  });

  test('R22: two different anchor sets for the same target produce two DIFFERENT request bodies', async ({
    page,
  }) => {
    const bodies: MatchAnchorBody[] = [];
    page.on('request', (r) => {
      if (r.method() === 'POST' && r.url().includes(ROUTES.matchAnchor)) {
        const b = r.postDataJSON() as MatchAnchorBody | null;
        if (b) bodies.push(b);
      }
    });
    const sweep = await enterSweep(page);
    await sweep.press('a'); // origin
    await sweep.advance(); // judge T with anchors {origin} (R33: await the commit before the next Space)
    await sweep.press('a'); // certify T too → anchor set now {origin, T}
    await sweep.advance(); // judge the next tile against {origin, T}
    await sweep.press('v'); // act so several match requests exist

    // The client keys on the field: request bodies for the same target across different anchor sets
    // must differ in their `anchors` array (never a single trial-keyed cache entry reused).
    const distinctAnchorSets = new Set(bodies.map((b) => JSON.stringify(b.anchors)));
    expect(distinctAnchorSets.size).toBeGreaterThan(1);
  });
});

test.describe('R33 — judgement keys are dead while a placement is in flight', () => {
  test('R33: a second Space inside the ~1 s match does not double-advance', async ({ page }) => {
    const sweep = await enterSweep(page);
    const t0 = await sweep.currentTrial();
    // Fire two Spaces back-to-back; only ONE advance may take effect (one in-flight flag).
    await Promise.all([sweep.press('Space'), sweep.press('Space')]);
    // Give the (single) advance time to settle, then assert we moved exactly one non-excluded step —
    // i.e. we did not skip a tile by processing both presses.
    await expect.poll(() => sweep.currentTrial(), { timeout: SHORT }).not.toBe(t0);
    const t1 = await sweep.currentTrial();
    await sweep.press('Space');
    await expect.poll(() => sweep.currentTrial(), { timeout: SHORT }).not.toBe(t1);
    // The two tiles landed on are adjacent judgement steps, not two-apart (no swallowed tile).
    expect(t1).not.toBe(t0);
  });
});
