// ⭐ **THE DEVICE IS READ, NEVER RETYPED** (R45.8 + the 2026-08-11 review, finding #1).
//
// The formatters below are the whole surface between the served `DeviceSpec` and the prose the user
// reads before he declares "whole chip imaged". Two things must hold, and neither is obvious enough
// to leave to a Playwright run alone:
//
//   1 · every number rendered comes from the ARGUMENT, so changing `DeviceSpec` in Python changes
//       the UI with no TypeScript edit at all; and
//   2 · with NO spec (in flight, or the fetch failed) the prose names NO DEVICE NUMBERS. A
//       remembered "220 × 120" reads exactly like a true one — which is precisely why the UI must
//       not be the second place that knows it.
//
// ⛔ The fixtures here are deliberately NOT MaxWell. A test that asserted "220 × 120" would be the
// duplication it was written to catch.

import { describe, expect, it } from 'vitest';
import type { ElectrodeDevice } from '../../api';
import { coverageHelp, deviceCount, devicePitch, deviceShape } from './device';

const RIG: ElectrodeDevice = {
  name: 'Bench Rig MicroArray',
  axes: [5, 7],
  pitch_um: 3.5,
  electrodes: 35,
};

/** The numbers of the REAL chip — none of them may appear in prose built from a spec, or from none. */
const MAXWELL_NUMBERS = ['220', '120', '26,400', '26400', '17.5'];

describe('the served device spec, formatted', () => {
  it('reads the two axes long side first — the order is a reading choice, not a claim', () => {
    // `axes` is ORIENTATION-FREE by contract: the chip can sit portrait or landscape in a mosaic,
    // so the same spec must read the same way whichever order the wire happens to carry.
    expect(deviceShape(RIG)).toBe('7 × 5');
    expect(deviceShape({ ...RIG, axes: [7, 5] })).toBe('7 × 5');
  });

  it('groups the digits of the served count and never recomputes it', () => {
    expect(deviceCount(RIG)).toBe('35');
    // 26,400 grouped — but only because the SPEC said 26400; nothing here multiplies the axes.
    expect(deviceCount({ ...RIG, electrodes: 26_400 })).toBe('26,400');
    expect(deviceCount({ ...RIG, axes: [2, 2], electrodes: 999 })).toBe('999');
  });

  it('trims float noise and trailing zeros off the pitch', () => {
    expect(devicePitch(RIG)).toBe('3.5 µm');
    expect(devicePitch({ ...RIG, pitch_um: 17.5 })).toBe('17.5 µm');
    expect(devicePitch({ ...RIG, pitch_um: 20 })).toBe('20 µm');
    expect(devicePitch({ ...RIG, pitch_um: 17.500000000000004 })).toBe('17.5 µm');
  });
});

describe('the coverage prose', () => {
  it('quotes the spec it was given — shape, count, pitch and name', () => {
    const text = coverageHelp(RIG);
    expect(text).toContain('Bench Rig MicroArray');
    expect(text).toContain('7 × 5 = 35 electrodes');
    expect(text).toContain('3.5 µm');
    for (const stale of MAXWELL_NUMBERS) expect(text).not.toContain(stale);
  });

  it('names NO device numbers when there is no spec — and still says what both answers do', () => {
    const text = coverageHelp(null);
    for (const stale of MAXWELL_NUMBERS) expect(text).not.toContain(stale);
    // The two answers are still fully explained; only the numbers are withheld.
    expect(text).toContain('Whole chip imaged');
    expect(text).toContain('Part of the chip');
    expect(text).toContain("the device's pitch");
    expect(text).toContain('1-1 is the top-left of the imaged region');
  });

  it('says that a whole-chip fit is STRICT — the exact shape, or a refusal', () => {
    // His word, 2026-08-11: *"if the user select full imaging then I want the rules to be strictly
    // enforced"*. The prose must not promise a best-effort correction it will not get.
    for (const text of [coverageHelp(RIG), coverageHelp(null)]) {
      expect(text).toContain('strictly');
      expect(text).toContain('refused');
      expect(text).toContain('every one of its positions numbered');
    }
  });
});
