import { describe, it, expect } from 'vitest';
import { mosaicTrials } from './trials';

/**
 * 🔴 THIS TEST EXISTS BECAUSE THE RULE WAS ONCE IMPLEMENTED TWICE (2026-07-25). The new-project flow
 * chose the trials a project was CREATED with; `MosaicFeature` chose the trials it was OPENED with.
 * Correcting one left the other behind, and the symptom was a project whose document held 10 tiles
 * opening onto a Range screen that said "11 snapshots". There is one implementation now, and these
 * are its cases.
 *
 * The numbers below are FIXTURE facts (HARD RULE 3 permits them in tests, never in app code): the
 * committed synthetic acquisition, and the shape of 260620d's log.
 */
describe('mosaicTrials — which snapshots are the mosaic (BEHAVIOUR R2.8)', () => {
  // The committed fixture: square frames 5 + 11–20, an off-shape 9, three snapshot blocks.
  const fixtureShapes = [
    { w: 512, h: 512, n: 11, trials: [5, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20] },
    { w: 512, h: 128, n: 1, trials: [9] },
  ];
  const fixtureBlocks = [
    { lo: 5, hi: 5, n: 1 },
    { lo: 9, hi: 9, n: 1 },
    { lo: 11, hi: 20, n: 10 },
  ];

  it('takes the acquisition the log says is the mosaic, and drops the pre-scan stray', () => {
    expect(mosaicTrials(fixtureShapes, fixtureBlocks)).toEqual([
      11, 12, 13, 14, 15, 16, 17, 18, 19, 20,
    ]);
  });

  it('the result is CONTIGUOUS — which is why Gaps reads none on a fresh open (R2.3)', () => {
    const t = mosaicTrials(fixtureShapes, fixtureBlocks)!;
    expect(t).toEqual(Array.from({ length: t.length }, (_, i) => t[0] + i));
  });

  it('drops the off-shape frame BY SHAPE, never by its number (R2.8)', () => {
    expect(mosaicTrials(fixtureShapes, fixtureBlocks)).not.toContain(9);
  });

  it("260620d's shape: the whole 11-348 run, strays 1 and 5-7 left out (R2.1)", () => {
    const run = Array.from({ length: 338 }, (_, i) => 11 + i); // 11..348
    const trials = mosaicTrials(
      [{ w: 512, h: 512, n: 342, trials: [1, 5, 6, 7, ...run] }],
      [
        { lo: 1, hi: 1, n: 1 },
        { lo: 5, hi: 7, n: 3 },
        { lo: 11, hi: 348, n: 338 },
      ],
    );
    expect(trials).toHaveLength(338);
    expect(trials![0]).toBe(11);
    expect(trials![trials!.length - 1]).toBe(348);
  });

  it('picks the block with the most SQUARE frames, not merely the longest block', () => {
    // A long run this feature cannot place must not win over a shorter run of real tiles.
    const trials = mosaicTrials(
      [
        { w: 512, h: 512, n: 3, trials: [50, 51, 52] },
        { w: 512, h: 128, n: 9, trials: [1, 2, 3, 4, 5, 6, 7, 8, 9] },
      ],
      [
        { lo: 1, hi: 9, n: 9 },
        { lo: 50, hi: 52, n: 3 },
      ],
    );
    expect(trials).toEqual([50, 51, 52]);
  });

  it('is deterministic — findOpenSession matches a live session on this exact list', () => {
    const a = mosaicTrials(fixtureShapes, fixtureBlocks);
    const b = mosaicTrials(fixtureShapes, fixtureBlocks);
    expect(a).toEqual(b);
  });

  it('does not mutate what it is handed', () => {
    const shapes = structuredClone(fixtureShapes);
    const blocks = structuredClone(fixtureBlocks);
    mosaicTrials(shapes, blocks);
    expect(shapes).toEqual(fixtureShapes);
    expect(blocks).toEqual(fixtureBlocks);
  });

  it('falls back to every square frame when the backend reports no blocks', () => {
    expect(mosaicTrials(fixtureShapes, [])).toEqual([
      5, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20,
    ]);
  });

  it('is null when nothing is square — this feature cannot place those frames', () => {
    expect(mosaicTrials([{ w: 512, h: 128, n: 4, trials: [1, 2, 3, 4] }], [])).toBeNull();
    expect(mosaicTrials([], [])).toBeNull();
  });
});
