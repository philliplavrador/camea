// The scale bar's arithmetic. What matters: the number is round, the bar stays readable at any
// zoom the viewer can reach, and no state means no bar — never `NaN µm` in the corner.

import { describe, expect, it } from 'vitest';
import { scaleBar } from './scalebar';

describe('scaleBar', () => {
  it('always picks a round 1-2-5 number of µm', () => {
    for (const scale of [0.013, 0.05, 0.2, 1, 3.7, 12, 264]) {
      const bar = scaleBar(scale);
      expect(bar).not.toBeNull();
      const mantissa = bar!.um / Math.pow(10, Math.floor(Math.log10(bar!.um)));
      expect([1, 2, 5]).toContainEqual(Math.round(mantissa * 1e6) / 1e6);
    }
  });

  it('keeps the bar readable — never longer than the target, never a sliver', () => {
    // The 1-2-5 ladder's worst gap is ×2.5, so the bar can never fall below target/2.5.
    for (const scale of [0.013, 0.05, 0.2, 1, 3.7, 12, 264]) {
      const bar = scaleBar(scale)!;
      expect(bar.px).toBeLessThanOrEqual(90 + 1e-9);
      expect(bar.px).toBeGreaterThanOrEqual(90 / 2.6);
    }
  });

  it('draws nothing when there is no view yet', () => {
    expect(scaleBar(0)).toBeNull();
    expect(scaleBar(-1)).toBeNull();
    expect(scaleBar(Number.NaN)).toBeNull();
  });

  it('labels in plain decimals, never scientific notation', () => {
    for (const scale of [0.013, 1, 264]) {
      const label = scaleBar(scale)!.label;
      expect(label).toMatch(/µm$/);
      expect(label).not.toMatch(/e[+-]/i);
    }
    // A deep zoom lands under 1 µm and still reads as a decimal.
    expect(scaleBar(450)!.label).toBe('0.2 µm');
  });
});
