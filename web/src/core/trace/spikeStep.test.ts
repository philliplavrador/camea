// Spike stepping — two pure searches, so the tests are about the edges: the epsilon that stops a
// centered view re-finding the spike under its own feet, order-independence, and the honest nulls.

import { describe, it, expect } from 'vitest';
import { nextSpike, prevSpike } from './spikeStep';

// Literal seconds are fine in a test — HARD RULE 3 forbids dataset knowledge in APP code.
const spikes = [0.5, 1.25, 2.0, 2.75].map((t_s) => ({ t_s }));

describe('spikeStep — nextSpike', () => {
  it('finds the earliest spike after the reference', () => {
    expect(nextSpike(spikes, 1.0)).toBe(1.25);
    expect(nextSpike(spikes, 0.0)).toBe(0.5);
  });

  it('is strict: a spike AT the reference is not "after" it', () => {
    expect(nextSpike(spikes, 1.25)).toBe(2.0);
  });

  it('⭐ the epsilon skips a spike a hair past the reference — the recentered view cannot stick', () => {
    // A view centered on 1.25 whose recomputed centre came back an ulp LOW would otherwise
    // re-find 1.25 for ever and the button would do nothing.
    expect(nextSpike(spikes, 1.25 - 1e-9, 1e-6)).toBe(2.0);
  });

  it('does not assume the list is sorted — the server order is not part of its contract', () => {
    const shuffled = [2.75, 0.5, 2.0, 1.25].map((t_s) => ({ t_s }));
    expect(nextSpike(shuffled, 1.0)).toBe(1.25);
    expect(prevSpike(shuffled, 2.5)).toBe(2.0);
  });

  it('null when nothing lies beyond, and on an empty list', () => {
    expect(nextSpike(spikes, 2.75)).toBeNull();
    expect(nextSpike([], 0)).toBeNull();
  });
});

describe('spikeStep — prevSpike', () => {
  it('finds the latest spike before the reference, strictly', () => {
    expect(prevSpike(spikes, 2.5)).toBe(2.0);
    expect(prevSpike(spikes, 2.0)).toBe(1.25);
  });

  it('the epsilon works on this side too', () => {
    expect(prevSpike(spikes, 2.0 + 1e-9, 1e-6)).toBe(1.25);
  });

  it('null before the first spike', () => {
    expect(prevSpike(spikes, 0.5)).toBeNull();
    expect(prevSpike([], 5)).toBeNull();
  });
});
