// The activity colour scale — the one place a rate becomes a colour.
//
// ⛔ **These tests pin the PROPERTIES, not the current mapping.** The scale itself is HELD pending
// `docs/MAXWELL.md` (see `activityScale.ts`), so a test that asserted "0.5 spikes/s is exactly this
// colour" would have to be rewritten the moment he answers, and would be protecting nothing. What
// must survive any answer is asserted below: a pad that heard nothing is never a position on the
// ramp, the mapping is a pure function of the rate, and the scale comes from the recording.

import { describe, expect, it } from 'vitest';
import { SILENT_MEANING, activityScale, formatRate, rampColour } from './activityScale';

describe('activityScale', () => {
  it('gives a pad that recorded no spikes NO position on the ramp', () => {
    // 🔴 The one that matters most. `null` is what makes `ChipMap` draw a hollow ring instead of a
    // colour — a different SHAPE, so it can never be misread as "a bit dim". His call, 2026-08-14.
    const s = activityScale([0, 0.5, 2, 9]);
    expect(s.position(0)).toBeNull();
    expect(s.position(0.5)).not.toBeNull();
  });

  it('does not let silent pads squash the range the live ones use', () => {
    // ⭐ Most of a real chip hears nothing — measured 23–62% of routed pads across his recordings —
    // and, per his correction, usually because no neuron is near that pad rather than because
    // anything is wrong. Including them in the ramp would compress every live pad into the top.
    const withSilent = activityScale([0, 0, 0, 0, 0, 1, 2, 3]);
    const without = activityScale([1, 2, 3]);
    expect(withSilent.position(1)).toBe(without.position(1));
    expect(withSilent.position(3)).toBe(without.position(3));
  });

  it('counts the silent and the live pads separately', () => {
    const s = activityScale([0, 0, 1, 2, 3]);
    expect(s.nSilent).toBe(2);
    expect(s.nLive).toBe(3);
  });

  it('is a pure function of the rate — equal rates get equal colours', () => {
    // Two pads that fired the same number of times must not come out different colours because of
    // where they sat in the array.
    const s = activityScale([1, 5, 5, 5, 9]);
    expect(s.position(5)).toBe(s.position(5));
    const shuffled = activityScale([5, 9, 5, 1, 5]);
    expect(shuffled.position(5)).toBe(s.position(5));
  });

  it('is monotone — busier is never further down the ramp', () => {
    const s = activityScale([0.1, 0.2, 0.5, 1, 4, 30]);
    const seen = [0.1, 0.2, 0.5, 1, 4, 30].map((r) => s.position(r)!);
    for (let i = 1; i < seen.length; i++) expect(seen[i]!).toBeGreaterThanOrEqual(seen[i - 1]!);
  });

  it('always stays inside the ramp', () => {
    const s = activityScale([0.001, 12345]);
    for (const r of [0.001, 1, 12345, 1e9]) {
      const t = s.position(r)!;
      expect(t).toBeGreaterThanOrEqual(0);
      expect(t).toBeLessThanOrEqual(1);
    }
  });

  it('takes its maximum from THIS recording and nothing else', () => {
    // ⛔ I1 — the `Done when` box. Two recordings, two scales; nothing declares how busy a chip
    // should be, so these must disagree.
    expect(activityScale([1, 2, 3]).maxRateHz).toBe(3);
    expect(activityScale([10, 200]).maxRateHz).toBe(200);
  });

  it('gives a legend in real units, dim to busy', () => {
    const s = activityScale([0, 0.1, 0.4, 1, 3, 20]);
    expect(s.legend.length).toBeGreaterThan(1);
    expect(s.legend[0]!.t).toBe(0);
    expect(s.legend[s.legend.length - 1]!.t).toBe(1);
    // The busiest swatch names the busiest pad, so the legend cannot promise a rate nothing reached.
    expect(s.legend[s.legend.length - 1]!.rateHz).toBe(20);
    for (let i = 1; i < s.legend.length; i++) {
      expect(s.legend[i]!.rateHz).toBeGreaterThanOrEqual(s.legend[i - 1]!.rateHz);
    }
  });

  it('survives a recording where nothing fired at all', () => {
    const s = activityScale([0, 0, 0]);
    expect(s.position(0)).toBeNull();
    expect(s.nLive).toBe(0);
    expect(s.maxRateHz).toBe(0);
    expect(s.legend.every((l) => l.rateHz === 0)).toBe(true);
  });

  it('survives an empty recording', () => {
    const s = activityScale([]);
    expect(s.nLive).toBe(0);
    expect(s.nSilent).toBe(0);
    expect(s.maxRateHz).toBe(0);
  });

  it('survives a recording where exactly one pad fired', () => {
    const s = activityScale([0, 0, 7]);
    expect(s.position(7)).not.toBeNull();
    expect(s.maxRateHz).toBe(7);
  });
});

describe('the words', () => {
  it('never calls a pad with no spikes dead, failed or broken', () => {
    // ⭐ **His correction, 2026-08-14**: among the pads that were routed, many are not near a
    // neuron at all, so zero spikes is the ORDINARY case. If someone later "tidies" this sentence
    // into "dead electrode", this goes red.
    expect(SILENT_MEANING).toMatch(/no neuron/i);
    for (const banned of ['dead', 'fail', 'broken', 'faulty', 'bad']) {
      expect(SILENT_MEANING.toLowerCase()).not.toContain(banned);
    }
  });
});

describe('rampColour', () => {
  it('is ordered dark to bright and clamps outside 0..1', () => {
    expect(rampColour(0)).toMatch(/^rgb\(/);
    expect(rampColour(-5)).toBe(rampColour(0));
    expect(rampColour(5)).toBe(rampColour(1));
    expect(rampColour(0)).not.toBe(rampColour(1));
  });
});

describe('formatRate', () => {
  it('stays readable at every magnitude he actually sees', () => {
    expect(formatRate(0)).toBe('0 spikes/s');
    expect(formatRate(0.42)).toBe('0.42 spikes/s');
    expect(formatRate(3.5)).toBe('3.5 spikes/s');
    expect(formatRate(860)).toBe('860 spikes/s');
  });

  it('never puts scientific notation in front of him', () => {
    // ⚠️ Seen on his own data: the quiet end of a real recording lands near 0.0033 spikes/s, and
    // `3.3e-3` on a legend is a maths notation a biologist has to decode.
    for (const r of [0.0033, 0.00001, 0.5, 12345]) {
      expect(formatRate(r)).not.toMatch(/e[+-]/);
    }
    expect(formatRate(0.0033)).toBe('0.003 spikes/s');
  });
});
