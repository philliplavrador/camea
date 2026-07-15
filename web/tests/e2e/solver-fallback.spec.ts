import { test, expect } from '@playwright/test';
import {
  Sweep,
  Wizard,
  TID,
  byId,
  enterMosaic,
  enterSweep,
  stubMatchAnchor,
  lowConfidenceMatch,
  confidentMatch,
  runBuild,
} from './pages';
import { SHORT } from './fixture';

/**
 * SPACE ALWAYS PLACES, and HOW it places is the solver-fallback rule (R15, decidePlacement):
 *   1. Match CONFIDENT           → use the match.
 *   2. Match NOT confident AND disagrees with the solver by > 10 px → take the SOLVER's position,
 *      fade in, and SAY SO loudly (magenta + banner + header count). Never auto-anchored.
 *   3. Match NOT confident but AGREES with the solver → no-op; the match stands.
 *   4. No solver position at all  → use the match anyway and say so.
 * ⛔ NOTHING IS EVER AUTO-ANCHORED (I3): every diverted/placed tile lands `unverified`.
 */

test.describe('R15 — solver fallback', () => {
  test('R15 (1): a CONFIDENT match is used as-is — no divert banner, tile not magenta', async ({
    page,
  }) => {
    // On the clean fixture the natural match is confident; placing must NOT divert.
    const sweep = await enterSweep(page);
    await sweep.press('a'); // certify origin
    const t = await sweep.advance(); // place the next tile at its confident match (R33: await commit)
    await expect(sweep.chip(t)).toHaveAttribute('data-state', 'unverified', { timeout: SHORT });
    await expect(byId(page, TID.warnDivert)).toHaveCount(0); // no divert
    expect(await sweep.headerCount(TID.headerDiverted)).toBe(0);
  });

  test('R15 (4)/I3: NO solver position → the match is used and SAID SO, and it is NOT auto-anchored', async ({
    page,
  }) => {
    // No build has run, so there is no solver position. Stub a low-confidence match; the app must use
    // it anyway (a tile with no position is useless), announce it, and leave it UNVERIFIED.
    await stubMatchAnchor(page, (target) => lowConfidenceMatch(target, [900, 120]));
    const sweep = await enterSweep(page);
    await sweep.press('a'); // origin
    const t = await sweep.advance(); // place the low-confidence tile (R33: await commit)
    await expect(sweep.chip(t)).toHaveAttribute('data-state', 'unverified', { timeout: SHORT }); // I3
    await expect(byId(page, TID.banner)).toBeVisible(); // it says so
  });

  test(
    'R15 (2)/W3: a low-confidence match that DISAGREES with the solver takes the SOLVER position, loudly',
    { tag: '@slow' },
    async ({ page }) => {
      await enterMosaic(page);
      await runBuild(page); // gives every tile a solver (machine) position
      // Now force the matcher to be wrong: low confidence, far from wherever the solver put the tile.
      await stubMatchAnchor(page, (target) => lowConfidenceMatch(target, [9000, 9000]));
      const wizard = new Wizard(page);
      await wizard.goto('sweep');
      const sweep = new Sweep(page);
      await sweep.focus();
      await sweep.press('a'); // certify origin so a composite exists
      const t = await sweep.advance(); // judge the next tile → should DIVERT (R33: await commit)

      await expect(byId(page, TID.warnDivert)).toBeVisible({ timeout: SHORT }); // W3
      expect(await sweep.headerCount(TID.headerDiverted)).toBeGreaterThanOrEqual(1);
      // Never auto-anchored (I3) — a diverted tile lands unverified.
      await expect(sweep.chip(t)).not.toHaveAttribute('data-state', 'anchored');
      // The block names the matcher's rejected answer / px gap — proof the app REFUSED the matcher.
      await expect(byId(page, TID.warnDivert)).toContainText(/px|matcher wanted/i);
    },
  );

  test(
    'R15 (3): a low-confidence match that AGREES with the solver does not divert',
    { tag: '@slow' },
    async ({ page }) => {
      // "AGREES with the solver" means the match lands ≤ SOLVER_DISAGREE_PX (10 px) of THIS tile's own
      // solver position — `tile.machine`, which is what `classifyPlacement` compares a divert against.
      // The match request deliberately does NOT carry the target's position (a tile is never an anchor
      // for its OWN match — field.ts), so the stub must learn each tile's solver position elsewhere: the
      // build's `seed` response is the seeded document, and every `tile.machine` in it IS that position.
      // Capture it, then stub a low-confidence match 2 px away — genuine agreement (R15: "match not
      // confident but agrees with the solver → no-op; the match stands").
      const solver: Record<number, [number, number]> = {};
      page.on('response', async (resp) => {
        if (resp.request().method() !== 'POST' || !resp.url().includes('/api/mosaic/seed')) return;
        try {
          const body = (await resp.json()) as { doc?: { tiles?: Record<string, { machine?: unknown }> } };
          for (const [k, tile] of Object.entries(body.doc?.tiles ?? {})) {
            const m = tile?.machine;
            if (Array.isArray(m) && m.length === 2) solver[Number(k)] = [Number(m[0]), Number(m[1])];
          }
        } catch {
          /* a non-JSON / superseded seed response is not the one we need */
        }
      });

      await enterMosaic(page);
      await runBuild(page); // seeds every tile a `machine` position; the listener above records them
      // The response listener parses JSON asynchronously, so poll until the seed has been recorded.
      await expect
        .poll(() => Object.keys(solver).length, {
          timeout: SHORT,
          message: 'the seed response must expose tile.machine',
        })
        .toBeGreaterThan(0);

      await stubMatchAnchor(page, (target) => {
        const p = solver[target] ?? [0, 0];
        return lowConfidenceMatch(target, [p[0] + 2, p[1] + 2]); // 2.8 px from the solver — agreement
      });
      const wizard = new Wizard(page);
      await wizard.goto('sweep');
      const sweep = new Sweep(page);
      await sweep.focus();
      await sweep.press('a'); // certify origin so a composite exists
      await sweep.advance(); // judge the next tile and WAIT for the commit (R33) before reading divert
      await expect(byId(page, TID.warnDivert)).toHaveCount(0, { timeout: SHORT });
      expect(await sweep.headerCount(TID.headerDiverted)).toBe(0);
    },
  );

  test(
    'W11: a CONFIDENT match that lands > 20 px from the solver keeps the match but WARNS (field wins)',
    { tag: '@slow' },
    async ({ page }) => {
      await enterMosaic(page);
      await runBuild(page);
      await stubMatchAnchor(page, (target) => confidentMatch(target, [4000, 4000]));
      const wizard = new Wizard(page);
      await wizard.goto('sweep');
      const sweep = new Sweep(page);
      await sweep.focus();
      await sweep.press('a');
      await sweep.press('Space');
      // The confident match wins over the solver, but the app tells him it chose (W11).
      await expect(byId(page, TID.warnConfidentDisagree)).toBeVisible({ timeout: SHORT });
      // It is the MATCH that was used here (not a divert): no divert warning.
      await expect(byId(page, TID.warnDivert)).toHaveCount(0);
    },
  );
});
