// The drag-a-stretch gesture. Two halves are tested two ways:
//
//   1. the **geometry** (`plotRect` / `timeAtX` / `xAtTime` / `inPlot` / `brushRange`) as pure
//      functions, no DOM at all — which is why they were extracted;
//   2. the **hook**, through vitest's jsdom environment and `renderHook`, by handing its handlers
//      plain event objects. Pointer events are fed by hand rather than through `fireEvent` on a
//      real canvas because jsdom implements neither `PointerEvent` nor `setPointerCapture`, and a
//      test that stubbed both would be testing the stubs.
//
// Literal pixels and seconds are fine here — HARD RULE 3 forbids dataset knowledge in APP code.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { act, cleanup, renderHook } from '@testing-library/react';
import type { PointerEvent as ReactPointerEvent } from 'react';
import {
  CLICK_SLOP_PX,
  brushRange,
  inPlot,
  plotRect,
  timeAtX,
  useTimeBrush,
  xAtTime,
} from './useTimeBrush';
import type { PlotPad } from './useTimeBrush';

afterEach(cleanup);

// TraceChart's own paddings, and a canvas the size of the panel it sits in.
const PAD: PlotPad = { left: 46, right: 8, top: 8, bottom: 18 };
const W = 500;
const H = 150;
const RECT = plotRect(W, H, PAD); // x ∈ [46, 492], y ∈ [8, 132]
const RIGHT = RECT.left + RECT.width;

// The element is deliberately NOT at the page origin: a missing `clientX - rect.left` would pass
// every test if it were.
const OX = 20;
const OY = 30;

function makeElement() {
  const captured = new Set<number>();
  const el = {
    getBoundingClientRect: () =>
      ({
        left: OX,
        top: OY,
        width: W,
        height: H,
        right: OX + W,
        bottom: OY + H,
        x: OX,
        y: OY,
      }) as unknown as DOMRect,
    setPointerCapture: (id: number) => void captured.add(id),
    hasPointerCapture: (id: number) => captured.has(id),
    releasePointerCapture: (id: number) => void captured.delete(id),
  };
  return { el: el as unknown as HTMLElement, captured };
}

/** A pointer event at (x, y) measured from the element's top-left corner. */
function ptr(
  el: HTMLElement,
  x: number,
  y = 60,
  opts: { button?: number; pointerId?: number } = {},
): ReactPointerEvent<HTMLElement> {
  return {
    button: opts.button ?? 0,
    pointerId: opts.pointerId ?? 1,
    clientX: OX + x,
    clientY: OY + y,
    currentTarget: el,
  } as unknown as ReactPointerEvent<HTMLElement>;
}

function mount(minSpanS = 0, t0 = 0, t1 = 100) {
  const onSelect = vi.fn();
  const view = renderHook(() => useTimeBrush({ t0, t1, pad: PAD, minSpanS, onSelect }));
  return { ...view, onSelect, ...makeElement() };
}

/** Press at `xa`, drag to `xb`, release. Returns whatever the hook reported. */
function drag(h: ReturnType<typeof mount>, xa: number, xb: number, y = 60) {
  act(() => h.result.current.handlers.onPointerDown(ptr(h.el, xa, y)));
  act(() => h.result.current.handlers.onPointerMove(ptr(h.el, xb, y)));
  act(() => h.result.current.handlers.onPointerUp(ptr(h.el, xb, y)));
  return h.onSelect.mock.calls[0]?.[0] ?? null;
}

describe('plotRect — the picture inside the padding', () => {
  it('is the element minus the four paddings', () => {
    expect(RECT).toEqual({ left: 46, top: 8, width: 446, height: 124 });
  });

  it('never goes negative on an element narrower than its own gutters', () => {
    const tiny = plotRect(10, 10, PAD);
    expect(tiny.width).toBe(1);
    expect(tiny.height).toBe(1);
  });
});

describe('inPlot — the gutters are not part of the picture', () => {
  it('accepts the interior and both x edges', () => {
    expect(inPlot(200, 60, RECT)).toBe(true);
    expect(inPlot(RECT.left, 60, RECT)).toBe(true);
    expect(inPlot(RIGHT, 60, RECT)).toBe(true);
  });

  it('🔴 rejects the LEFT NUMBER GUTTER — that x is not a time', () => {
    expect(inPlot(0, 60, RECT)).toBe(false);
    expect(inPlot(RECT.left - 0.5, 60, RECT)).toBe(false);
  });

  it('rejects the right margin and the top/bottom padding (where the time labels live)', () => {
    expect(inPlot(RIGHT + 1, 60, RECT)).toBe(false);
    expect(inPlot(200, 0, RECT)).toBe(false);
    expect(inPlot(200, H - 1, RECT)).toBe(false);
  });
});

describe('timeAtX / xAtTime', () => {
  const t0 = 10;
  const t1 = 40;

  it('round-trips for every x across the picture', () => {
    for (const x of [RECT.left, 100, 269.5, 400, RIGHT]) {
      expect(xAtTime(timeAtX(x, RECT, t0, t1), RECT, t0, t1)).toBeCloseTo(x, 6);
    }
  });

  it('reads the two edges as the two ends of the range', () => {
    expect(timeAtX(RECT.left, RECT, t0, t1)).toBeCloseTo(t0, 9);
    expect(timeAtX(RIGHT, RECT, t0, t1)).toBeCloseTo(t1, 9);
    expect(timeAtX(RECT.left + RECT.width / 2, RECT, t0, t1)).toBeCloseTo(25, 9);
  });

  it('🔴 CLIPS AT BOTH GUTTERS — a drag off the edge selects to the edge, never past it', () => {
    expect(timeAtX(0, RECT, t0, t1)).toBe(t0);
    expect(timeAtX(-9999, RECT, t0, t1)).toBe(t0);
    expect(timeAtX(RECT.left - 0.001, RECT, t0, t1)).toBe(t0);
    expect(timeAtX(9999, RECT, t0, t1)).toBe(t1);
    expect(timeAtX(RIGHT + 0.001, RECT, t0, t1)).toBe(t1);
  });

  it('survives a zero-width axis instead of dividing by it', () => {
    expect(timeAtX(200, RECT, 5, 5)).toBe(5);
    expect(Number.isFinite(xAtTime(5, RECT, 5, 5))).toBe(true);
  });
});

describe('brushRange — what a drag chose, or nothing at all', () => {
  it('reports the range between the two x positions', () => {
    const r = brushRange(100, 300, RECT, 0, 100, 0);
    expect(r?.t0).toBeCloseTo(((100 - 46) / 446) * 100, 9);
    expect(r?.t1).toBeCloseTo(((300 - 46) / 446) * 100, 9);
  });

  it('🔴 a release within 5 px of the press is a CLICK — nothing to report, nothing to push', () => {
    expect(CLICK_SLOP_PX).toBe(5);
    expect(brushRange(200, 200, RECT, 0, 100, 0)).toBeNull();
    expect(brushRange(200, 204, RECT, 0, 100, 0)).toBeNull();
    expect(brushRange(200, 196, RECT, 0, 100, 0)).toBeNull();
    expect(brushRange(200, 204.9, RECT, 0, 100, 0)).toBeNull();
  });

  it('accepts exactly 5 px — matplotlib’s test is “< 5”, not “<= 5”', () => {
    expect(brushRange(200, 205, RECT, 0, 100, 0)).not.toBeNull();
  });

  it('right-to-left is identical to left-to-right', () => {
    expect(brushRange(300, 100, RECT, 0, 100, 0)).toEqual(brushRange(100, 300, RECT, 0, 100, 0));
  });

  it('refuses a range narrower than the floor the caller set, exactly like a click', () => {
    // 10 px of a 446 px picture showing 100 s ≈ 2.24 s.
    expect(brushRange(100, 110, RECT, 0, 100, 5)).toBeNull();
    expect(brushRange(100, 140, RECT, 0, 100, 5)).not.toBeNull();
  });

  it('refuses a long drag that clips to a single point (both ends in the same gutter)', () => {
    expect(brushRange(RECT.left, -200, RECT, 0, 100, 0)).toBeNull();
    expect(brushRange(RIGHT, RIGHT + 200, RECT, 0, 100, 0)).toBeNull();
  });

  it('refuses rather than propagating a NaN', () => {
    expect(brushRange(100, 300, RECT, 0, Number.NaN, 0)).toBeNull();
  });
});

describe('useTimeBrush — the gesture', () => {
  it('reports the stretch dragged, read against the picture’s own axis', () => {
    const h = mount();
    const chosen = drag(h, 100, 300);
    expect(h.onSelect).toHaveBeenCalledTimes(1);
    expect(chosen?.t0).toBeCloseTo(timeAtX(100, RECT, 0, 100), 9);
    expect(chosen?.t1).toBeCloseTo(timeAtX(300, RECT, 0, 100), 9);
  });

  it('reports the same stretch when dragged right-to-left', () => {
    const rtl = mount();
    const ltr = mount();
    expect(drag(rtl, 300, 100)).toEqual(drag(ltr, 100, 300));
  });

  it('🔴 a click (release < 5 px from the press) reports NOTHING', () => {
    const h = mount();
    expect(drag(h, 200, 203)).toBeNull();
    expect(h.onSelect).not.toHaveBeenCalled();
    expect(h.result.current.dragging).toBe(false);
  });

  it('refuses a stretch narrower than the caller’s floor, and reports nothing', () => {
    const h = mount(5);
    expect(drag(h, 100, 110)).toBeNull();
    expect(h.onSelect).not.toHaveBeenCalled();
  });

  it('🔴 IGNORES A PRESS IN THE LEFT NUMBER GUTTER outright — no drag, no capture, no report', () => {
    const h = mount();
    act(() => h.result.current.handlers.onPointerDown(ptr(h.el, 20)));
    expect(h.result.current.dragging).toBe(false);
    expect(h.captured.size).toBe(0);
    act(() => h.result.current.handlers.onPointerMove(ptr(h.el, 300)));
    act(() => h.result.current.handlers.onPointerUp(ptr(h.el, 300)));
    expect(h.onSelect).not.toHaveBeenCalled();
  });

  it('ignores a press in the bottom padding, where the time labels are drawn', () => {
    const h = mount();
    act(() => h.result.current.handlers.onPointerDown(ptr(h.el, 200, H - 2)));
    expect(h.result.current.dragging).toBe(false);
  });

  it('ignores a non-primary button (a right-click is a menu, not a zoom)', () => {
    const h = mount();
    act(() => h.result.current.handlers.onPointerDown(ptr(h.el, 200, 60, { button: 2 })));
    expect(h.result.current.dragging).toBe(false);
    expect(h.captured.size).toBe(0);
  });

  it('exposes a normalised, gutter-clipped band while dragging, and clears it on release', () => {
    const h = mount();
    act(() => h.result.current.handlers.onPointerDown(ptr(h.el, 300)));
    expect(h.result.current.dragging).toBe(true);
    act(() => h.result.current.handlers.onPointerMove(ptr(h.el, 100)));
    expect(h.result.current.x0).toBe(100); // normalised: x0 <= x1 even dragging leftwards
    expect(h.result.current.x1).toBe(300);
    act(() => h.result.current.handlers.onPointerMove(ptr(h.el, -500)));
    expect(h.result.current.x0).toBe(RECT.left); // clipped: never paints over the gutter
    act(() => h.result.current.handlers.onPointerUp(ptr(h.el, -500)));
    expect(h.result.current.dragging).toBe(false);
  });

  it('takes pointer capture on press and gives it back on release, so a drag that leaves the canvas still completes', () => {
    const h = mount();
    act(() => h.result.current.handlers.onPointerDown(ptr(h.el, 100)));
    expect(h.captured.has(1)).toBe(true);
    act(() => h.result.current.handlers.onPointerUp(ptr(h.el, W + 400)));
    expect(h.captured.size).toBe(0);
    // Released far to the right of the element: the range ends at the end of the picture.
    expect(h.onSelect.mock.calls[0]?.[0]?.t1).toBeCloseTo(100, 9);
  });

  it('🔴 Esc cancels a drag in flight: the band goes, the capture goes, and nothing is reported', () => {
    const h = mount();
    act(() => h.result.current.handlers.onPointerDown(ptr(h.el, 100)));
    act(() => h.result.current.handlers.onPointerMove(ptr(h.el, 300)));
    expect(h.result.current.dragging).toBe(true);

    act(() => void window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })));
    expect(h.result.current.dragging).toBe(false);
    expect(h.captured.size).toBe(0);

    act(() => h.result.current.handlers.onPointerUp(ptr(h.el, 300)));
    expect(h.onSelect).not.toHaveBeenCalled();
  });

  it('binds Esc ONLY while a drag is in flight — no standing global handler', () => {
    const add = vi.spyOn(window, 'addEventListener');
    const remove = vi.spyOn(window, 'removeEventListener');
    const h = mount();
    expect(add).not.toHaveBeenCalledWith('keydown', expect.anything(), true);

    act(() => h.result.current.handlers.onPointerDown(ptr(h.el, 100)));
    expect(add).toHaveBeenCalledWith('keydown', expect.anything(), true);
    act(() => h.result.current.handlers.onPointerUp(ptr(h.el, 300)));
    expect(remove).toHaveBeenCalledWith('keydown', expect.anything(), true);
    add.mockRestore();
    remove.mockRestore();
  });

  it('a cancelled pointer (the OS took it) ends the drag without reporting', () => {
    const h = mount();
    act(() => h.result.current.handlers.onPointerDown(ptr(h.el, 100)));
    act(() => h.result.current.handlers.onPointerMove(ptr(h.el, 300)));
    act(() => h.result.current.handlers.onPointerCancel(ptr(h.el, 300)));
    expect(h.result.current.dragging).toBe(false);
    expect(h.captured.size).toBe(0);
    expect(h.onSelect).not.toHaveBeenCalled();
  });

  it('ignores a second pointer while one drag is already in flight', () => {
    const h = mount();
    act(() => h.result.current.handlers.onPointerDown(ptr(h.el, 100)));
    act(() => h.result.current.handlers.onPointerDown(ptr(h.el, 400, 60, { pointerId: 2 })));
    act(() => h.result.current.handlers.onPointerUp(ptr(h.el, 400, 60, { pointerId: 2 })));
    expect(h.onSelect).not.toHaveBeenCalled(); // the second pointer's release is not the first's
    expect(h.result.current.dragging).toBe(true);
    expect(h.captured.has(1)).toBe(true); // and it did not steal the first pointer's capture
    act(() => h.result.current.handlers.onPointerUp(ptr(h.el, 300)));
    expect(h.onSelect).toHaveBeenCalledTimes(1);
  });

  it('reads the axis it was pressed on, so a range arriving mid-drag cannot move it', () => {
    const onSelect = vi.fn();
    const { el } = makeElement();
    const { result, rerender } = renderHook(
      (p: { t0: number; t1: number }) =>
        useTimeBrush({ t0: p.t0, t1: p.t1, pad: PAD, minSpanS: 0, onSelect }),
      { initialProps: { t0: 0, t1: 100 } },
    );
    act(() => result.current.handlers.onPointerDown(ptr(el, 100)));
    rerender({ t0: 0, t1: 1000 }); // a wider fetch lands under his hand
    act(() => result.current.handlers.onPointerUp(ptr(el, 300)));
    expect(onSelect.mock.calls[0]?.[0]?.t1).toBeCloseTo(timeAtX(300, RECT, 0, 100), 9);
  });
});
