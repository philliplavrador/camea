// The navigation history, pinned to matplotlib's behaviour rather than to ours. The three tests
// that matter are the forward-branch truncation, the clamps, and 🔴 `home` being a PUSH — the last
// one is what guarantees no key press can lose a place he had found by hand.

import { describe, it, expect } from 'vitest';
import {
  EMPTY_STACK,
  back,
  canBack,
  canForward,
  current,
  forward,
  home,
  push,
  stackOf,
} from './viewStack';
import type { TimeView } from './viewStack';

// Literal seconds are fine in a test — HARD RULE 3 forbids dataset knowledge in APP code.
const v = (t0: number, t1: number): TimeView => ({ t0, t1 });
const seen = (s: { entries: readonly TimeView[] }): string =>
  s.entries.map((e) => `${e.t0}-${e.t1}`).join(' ');

describe('viewStack — push', () => {
  it('stands on the entry it just pushed', () => {
    const s = push(stackOf(v(0, 100)), v(10, 20));
    expect(s.at).toBe(1);
    expect(current(s)).toEqual(v(10, 20));
  });

  it('🔴 TRUNCATES THE FORWARD BRANCH — zooming after a Back destroys what was ahead', () => {
    let s = stackOf(v(0, 100));
    s = push(s, v(10, 20));
    s = push(s, v(12, 14));
    s = back(s); // standing on 10-20, with 12-14 ahead
    expect(canForward(s)).toBe(true);

    s = push(s, v(30, 40)); // a new zoom from here
    expect(seen(s)).toBe('0-100 10-20 30-40'); // 12-14 is gone
    expect(canForward(s)).toBe(false);
    expect(current(s)).toEqual(v(30, 40));
  });

  it('does not de-duplicate: pushing the current view is a real entry (matplotlib does too)', () => {
    const s = push(stackOf(v(0, 100)), v(0, 100));
    expect(s.entries).toHaveLength(2);
    expect(canBack(s)).toBe(true);
  });

  it('works on an empty stack — the first push is just the first entry', () => {
    const s = push(EMPTY_STACK, v(0, 100));
    expect(seen(s)).toBe('0-100');
    expect(s.at).toBe(0);
  });
});

describe('viewStack — back / forward clamp, never wrap, never throw', () => {
  it('an EMPTY stack survives both, and stays empty', () => {
    expect(() => back(EMPTY_STACK)).not.toThrow();
    expect(() => forward(EMPTY_STACK)).not.toThrow();
    expect(current(back(EMPTY_STACK))).toBeNull();
    expect(current(forward(EMPTY_STACK))).toBeNull();
    expect(back(EMPTY_STACK).at).toBe(0);
    expect(forward(EMPTY_STACK).at).toBe(0);
  });

  it('a stack of ONE survives both and does not move', () => {
    const one = stackOf(v(0, 100));
    expect(current(back(one))).toEqual(v(0, 100));
    expect(current(forward(one))).toEqual(v(0, 100));
    expect(back(one).at).toBe(0);
    expect(forward(one).at).toBe(0);
  });

  it('clamps at the start rather than wrapping to the end', () => {
    let s = push(stackOf(v(0, 100)), v(10, 20));
    s = back(back(back(s)));
    expect(s.at).toBe(0);
    expect(current(s)).toEqual(v(0, 100));
  });

  it('clamps at the end rather than wrapping to the start', () => {
    let s = push(stackOf(v(0, 100)), v(10, 20));
    s = forward(forward(forward(s)));
    expect(s.at).toBe(1);
    expect(current(s)).toEqual(v(10, 20));
  });

  it('a clamped step returns the SAME object, so it cannot trigger a repaint', () => {
    const one = stackOf(v(0, 100));
    expect(back(one)).toBe(one);
    expect(forward(one)).toBe(one);
    expect(back(EMPTY_STACK)).toBe(EMPTY_STACK);
    expect(forward(EMPTY_STACK)).toBe(EMPTY_STACK);
  });

  it('back then forward returns to where it started', () => {
    const s = push(stackOf(v(0, 100)), v(10, 20));
    expect(current(forward(back(s)))).toEqual(v(10, 20));
  });
});

describe('viewStack — home', () => {
  it('🔴 IS A PUSH, NOT A REWIND: ONE back undoes it', () => {
    let s = stackOf(v(0, 100));
    s = push(s, v(10, 20));
    s = push(s, v(12, 14)); // the stretch he found by hand

    s = home(s);
    expect(current(s)).toEqual(v(0, 100)); // he is looking at the whole recording
    expect(seen(s)).toBe('0-100 10-20 12-14 0-100'); // and it was APPENDED, not rewound to

    s = back(s);
    expect(current(s)).toEqual(v(12, 14)); // one Back and he has his stretch again
  });

  it('leaves the earlier history intact, so Back still walks all the way out', () => {
    let s = home(push(push(stackOf(v(0, 100)), v(10, 20)), v(12, 14)));
    s = back(back(back(s)));
    expect(current(s)).toEqual(v(0, 100));
    expect(canBack(s)).toBe(false);
  });

  it('is a no-op on an empty stack', () => {
    expect(home(EMPTY_STACK)).toBe(EMPTY_STACK);
    expect(current(home(EMPTY_STACK))).toBeNull();
  });

  it('pressed twice, pushes twice — verbatim matplotlib, and still one Back per press', () => {
    const s = home(home(push(stackOf(v(0, 100)), v(10, 20))));
    expect(seen(s)).toBe('0-100 10-20 0-100 0-100');
  });
});

describe('viewStack — the enablement predicates (Qt’s set_history_buttons)', () => {
  it('an empty stack enables neither button', () => {
    expect(canBack(EMPTY_STACK)).toBe(false);
    expect(canForward(EMPTY_STACK)).toBe(false);
  });

  it('a stack of one enables neither button', () => {
    const one = stackOf(v(0, 100));
    expect(canBack(one)).toBe(false);
    expect(canForward(one)).toBe(false);
  });

  it('at the END of history: back yes, forward no', () => {
    const s = push(stackOf(v(0, 100)), v(10, 20));
    expect(canBack(s)).toBe(true);
    expect(canForward(s)).toBe(false);
  });

  it('in the MIDDLE of history: both', () => {
    const s = back(push(push(stackOf(v(0, 100)), v(10, 20)), v(12, 14)));
    expect(canBack(s)).toBe(true);
    expect(canForward(s)).toBe(true);
  });

  it('at the START of history: forward yes, back no', () => {
    const s = back(back(push(push(stackOf(v(0, 100)), v(10, 20)), v(12, 14))));
    expect(canBack(s)).toBe(false);
    expect(canForward(s)).toBe(true);
  });
});

describe('viewStack — current', () => {
  it('is null when there is no history at all', () => {
    expect(current(EMPTY_STACK)).toBeNull();
  });

  it('is the entry at the position, not the last one pushed', () => {
    const s = back(push(stackOf(v(0, 100)), v(10, 20)));
    expect(current(s)).toEqual(v(0, 100));
  });
});
