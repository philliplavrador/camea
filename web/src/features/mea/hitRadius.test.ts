// THE CHIP MAP'S CLICK TOLERANCE — the rule R45.7 cost an afternoon to learn, pinned numerically.
//
// ⚠️ **THIS EXISTS BECAUSE A REVIEW FOUND NOTHING WAS TESTING IT.** The behaviour-guard pass on plan
// 003 noticed that `ChipMap`'s hit radius differs from `features/electrodes/lookup.ts`'s strict
// 0.30 × pitch, and that no test pinned either the floor or the cap — so a later "tidy" could move
// either without anything going red. The floor difference is deliberate and argued in
// `hitRadiusUm`'s docstring; these tests hold the shape of the rule, not a taste.

import { describe, expect, it } from 'vitest';
import { hitRadiusUm } from './hitRadius';

const PITCH = 17.5; // µm — a real MaxWell pitch, used here only as an arbitrary positive number

describe('hitRadiusUm', () => {
  it('never reaches past the cell circumradius, however far out you zoom', () => {
    // 🔴 **THE SAFETY BOUND.** Nearest-centre within `pitch/√2` can never take a neighbour's
    // ground — that geometric cap is what replaces a tuned threshold, and it is the half of R45.7
    // that must not move.
    const cap = PITCH * Math.SQRT1_2;
    for (const scale of [1e-6, 0.001, 0.01, 0.1, 0.183, 1]) {
      expect(hitRadiusUm(PITCH, scale)).toBeLessThanOrEqual(cap + 1e-9);
    }
  });

  it('grows as you zoom OUT, so a fitted chip is not a sub-pixel target', () => {
    // ⚠️ The failure this prevents: a world-unit radius shrinks on screen as you zoom out, the hit
    // then depends on sub-pixel phase, and the misses come in BANDS — which a user reports as
    // "there are missing patches on my chip", not as "my click missed".
    const zoomedIn = hitRadiusUm(PITCH, 4);
    const zoomedOut = hitRadiusUm(PITCH, 0.05);
    expect(zoomedOut).toBeGreaterThan(zoomedIn);
  });

  it('keeps a usable on-screen target until the cap stops it', () => {
    // At a scale where 6 CSS px is still inside the cap, that is what you get.
    const scale = 0.5; // 6 px / 0.5 = 12 µm, and the cap here is 12.37 µm
    expect(hitRadiusUm(PITCH, scale)).toBeCloseTo(12, 6);
  });

  it('never drops below half a pitch when zoomed right in', () => {
    // The deliberate difference from `features/electrodes/lookup.ts` (0.30 × pitch): this screen is
    // a VIEWER — a click means "read this pad", not "assign this identity" — so it is forgiving
    // between genuinely adjacent pads. See `hitRadiusUm`'s docstring for the full argument.
    expect(hitRadiusUm(PITCH, 1000)).toBeCloseTo(PITCH * 0.5, 6);
  });

  it('⭐ still lets a real GAP select nothing', () => {
    // A missing pad between two routed ones puts the nearest routed pad a whole pitch away. The cap
    // is pitch/√2 ≈ 0.707 × pitch, which is less than that — so a click in the hole hits neither.
    const worst = hitRadiusUm(PITCH, 1e-6); // as generous as the rule ever gets
    expect(worst).toBeLessThan(PITCH);
  });

  it('survives a nonsense pitch or scale rather than returning NaN', () => {
    for (const [pitch, scale] of [[0, 1], [-5, 1], [PITCH, 0], [PITCH, -1]] as const) {
      const r = hitRadiusUm(pitch, scale);
      expect(Number.isFinite(r)).toBe(true);
      expect(r).toBeGreaterThan(0);
    }
  });
});
