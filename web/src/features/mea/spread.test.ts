// The spread chart's arithmetic. What must hold whatever the recording: the bands are the
// legend's own values, every live pad lands in exactly one band, and the no-spike pads are their
// own bar — never a position on the ramp.

import { describe, expect, it } from 'vitest';
import { activityScale } from './activityScale';
import { bandHolds, spreadBands } from './spread';

describe('spreadBands', () => {
  it('puts every live pad in exactly one band — the counts sum to nLive', () => {
    const rates = [0, 0, 0.1, 0.1, 0.4, 0.9, 2, 2, 5, 30];
    const scale = activityScale(rates);
    const bands = spreadBands(scale, rates);
    const live = bands.filter((b) => !b.silent);
    expect(live.reduce((n, b) => n + b.count, 0)).toBe(scale.nLive);
    // ...and exactly one band claims each rate, so a pad can never be highlighted twice.
    for (const r of rates.filter((x) => x > 0)) {
      expect(live.filter((b) => bandHolds(b, r)).length).toBe(1);
    }
  });

  it('keeps the no-spike pads as their own bar, outside the ramp', () => {
    const rates = [0, 0, 0, 1, 2];
    const bands = spreadBands(activityScale(rates), rates);
    expect(bands[0]!.silent).toBe(true);
    expect(bands[0]!.count).toBe(3);
    expect(bands[0]!.colour).toBe('');
    expect(bandHolds(bands[0]!, 0)).toBe(true);
    expect(bandHolds(bands[0]!, 1)).toBe(false);
  });

  it('runs its bands between the legend stops, so the two cannot disagree', () => {
    const rates = [0.2, 0.5, 1, 3, 9];
    const scale = activityScale(rates);
    const live = spreadBands(scale, rates).filter((b) => !b.silent);
    expect(live.length).toBe(scale.legend.length - 1);
    for (let i = 0; i < live.length; i++) {
      expect(live[i]!.lo).toBe(scale.legend[i]!.rateHz);
      expect(live[i]!.hi).toBe(scale.legend[i + 1]!.rateHz);
    }
    // The busiest band owns the maximum — a bar chart that lost the busiest pad would be a lie.
    expect(bandHolds(live[live.length - 1]!, scale.maxRateHz)).toBe(true);
  });

  it('survives ties spanning a whole band', () => {
    // Ties collapse legend stops to equal rates; the empty [x, x) band simply counts nothing,
    // and the tied pads land once, further up.
    const rates = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 2];
    const scale = activityScale(rates);
    const live = spreadBands(scale, rates).filter((b) => !b.silent);
    expect(live.reduce((n, b) => n + b.count, 0)).toBe(scale.nLive);
  });

  it('survives a recording where nothing fired, and an empty one', () => {
    const silent = spreadBands(activityScale([0, 0]), [0, 0]);
    expect(silent.length).toBe(1);
    expect(silent[0]!.silent).toBe(true);
    expect(silent[0]!.count).toBe(2);
    const empty = spreadBands(activityScale([]), []);
    expect(empty.length).toBe(1);
    expect(empty[0]!.count).toBe(0);
  });
});
