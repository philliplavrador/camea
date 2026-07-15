// Engine contract tests. jsdom has no real 2-D canvas, so we stub a no-op CanvasRenderingContext2D
// (the paint calls become no-ops) and exercise the MODEL bookkeeping and the keyboard/attribute
// contract — which is where the rulings live, not in the pixels (those are Playwright's, §3.5).

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { ViewerEngine } from '../engine';
import type { ViewerCallbacks } from '../types';

/** A no-op 2-D context good enough for the engine's paint calls (nothing reads pixels here). */
function fakeCtx(): CanvasRenderingContext2D {
  const noop = (): void => {};
  const ctx: Record<string, unknown> = {
    save: noop,
    restore: noop,
    setTransform: noop,
    fillRect: noop,
    clearRect: noop,
    drawImage: noop,
    beginPath: noop,
    arc: noop,
    rect: noop,
    clip: noop,
    stroke: noop,
    strokeRect: noop,
    fill: noop,
    moveTo: noop,
    lineTo: noop,
    setLineDash: noop,
    fillText: noop,
    measureText: () => ({ width: 0 }),
    createImageData: (w: number, h: number) => ({
      data: new Uint8ClampedArray(w * h * 4),
      width: w,
      height: h,
    }),
    putImageData: noop,
    getImageData: (_x: number, _y: number, w: number, h: number) => ({
      data: new Uint8ClampedArray(w * h * 4),
      width: w,
      height: h,
    }),
    globalAlpha: 1,
    globalCompositeOperation: 'source-over',
    fillStyle: '',
    strokeStyle: '',
    lineWidth: 1,
    font: '',
    textBaseline: 'alphabetic',
    textAlign: 'left',
    imageSmoothingEnabled: true,
  };
  return ctx as unknown as CanvasRenderingContext2D;
}

function makeEngine(cb: ViewerCallbacks = {}) {
  const canvas = document.createElement('canvas');
  document.body.appendChild(canvas);
  const engine = new ViewerEngine(canvas, {
    layers: [
      { key: 'anchor', reference: true },
      { key: 'unverified', visible: false },
    ],
    cb,
  });
  return { engine, canvas };
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.reject(new Error('no-net'))),
  );
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(
    () => fakeCtx() as unknown as ReturnType<HTMLCanvasElement['getContext']>,
  );
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('reflected attributes the viewer owns', () => {
  it('stamps data-diff="false" and data-float-alpha="1" on mount', () => {
    const { canvas, engine } = makeEngine();
    expect(canvas.getAttribute('data-diff')).toBe('false');
    expect(canvas.getAttribute('data-float-alpha')).toBe('1');
    engine.destroy();
  });

  it('setDifference flips data-diff and fires onDifference (§3.5 / R-D)', () => {
    const onDifference = vi.fn();
    const { canvas, engine } = makeEngine({ onDifference });
    engine.setDifference(true);
    expect(engine.isDifference()).toBe(true);
    expect(canvas.getAttribute('data-diff')).toBe('true');
    expect(onDifference).toHaveBeenCalledWith(true);
    engine.destroy();
  });

  it('setFloatAlpha reflects and clamps to [0,1] (R13)', () => {
    const { canvas, engine } = makeEngine();
    engine.setFloatAlpha(0.15);
    expect(engine.getFloatAlpha()).toBeCloseTo(0.15, 6);
    expect(canvas.getAttribute('data-float-alpha')).toBe('0.15');
    engine.setFloatAlpha(2);
    expect(engine.getFloatAlpha()).toBe(1);
    engine.destroy();
  });
});

describe('the model + the anchor-layer count (R9)', () => {
  it('setTile adds to its layer; layerPlacedCount and onModelChange agree', () => {
    const onModelChange = vi.fn();
    const { engine } = makeEngine({ onModelChange });
    expect(engine.layerPlacedCount('anchor')).toBe(0);
    engine.setTile(11, { x: 0, y: 0, src: 'a.png', layer: 'anchor', feather: true });
    expect(engine.layerPlacedCount('anchor')).toBe(1);
    const info = onModelChange.mock.calls.at(-1)?.[0];
    expect(info.layers.anchor.placed).toBe(1);
    expect(info.layers.anchor.reference).toBe(true);
    // The unverified layer is maintained but NOT drawn in the sweep (data-unverified-drawn=false).
    expect(info.layers.unverified.visible).toBe(false);
    engine.destroy();
  });

  it('the count includes a floating cursor tile (A certifies at once — R9.2)', () => {
    const { engine } = makeEngine();
    engine.setTile(11, { x: 0, y: 0, src: 'a.png', layer: 'anchor' });
    engine.setCursor(11); // 11 now floats as the cursor …
    expect(engine.getCursor()).toBe(11);
    expect(engine.layerPlacedCount('anchor')).toBe(1); // … but still counts as certified
    engine.destroy();
  });

  it('normalises numeric string ids so {11} and 11 address one tile', () => {
    const { engine } = makeEngine();
    engine.setTiles({ '11': { x: 0, y: 0, src: 'a.png', layer: 'anchor' } });
    expect(engine.getTile(11)?.id).toBe(11);
    engine.setTile(11, { x: 5, y: 5, src: 'a.png', layer: 'anchor' });
    expect(engine.layerPlacedCount('anchor')).toBe(1);
    expect(engine.getTile('11')?.x).toBe(5);
    engine.destroy();
  });

  it('setTile(id, null) removes the tile and drops it as cursor', () => {
    const { engine } = makeEngine();
    engine.setTile(11, { x: 0, y: 0, src: 'a.png', layer: 'anchor' });
    engine.setCursor(11);
    engine.setTile(11, null);
    expect(engine.getTile(11)).toBeNull();
    expect(engine.getCursor()).toBeNull();
    expect(engine.layerPlacedCount('anchor')).toBe(0);
    engine.destroy();
  });
});

describe('handleKey — the camera half only', () => {
  const key = (init: KeyboardEventInit): KeyboardEvent => new KeyboardEvent('keydown', init);

  it('🔴 returns false for Space (it is the feature’s ADVANCE — §6.7)', () => {
    const { engine } = makeEngine();
    expect(engine.handleKey(key({ key: ' ', code: 'Space' }))).toBe(false);
    engine.destroy();
  });

  it('D toggles Difference mode and consumes the key', () => {
    const { engine } = makeEngine();
    expect(engine.handleKey(key({ key: 'd' }))).toBe(true);
    expect(engine.isDifference()).toBe(true);
    engine.handleKey(key({ key: 'd' }));
    expect(engine.isDifference()).toBe(false);
    engine.destroy();
  });

  it('arrows nudge the cursor tile 1 px; Shift = 10 px (§3.4, top-left world coords)', () => {
    const { engine } = makeEngine();
    engine.setTile(11, { x: 5, y: 5, src: 'a.png', layer: 'anchor' });
    engine.setCursor(11);
    engine.handleKey(key({ key: 'ArrowRight' }));
    expect(engine.getTile(11)?.x).toBe(6);
    engine.handleKey(key({ key: 'ArrowRight', shiftKey: true }));
    expect(engine.getTile(11)?.x).toBe(16);
    engine.handleKey(key({ key: 'ArrowDown' }));
    expect(engine.getTile(11)?.y).toBe(6);
    engine.destroy();
  });

  it('🔴 R14: Escape clears the selection but MUST NOT touch the cursor', () => {
    const onSelect = vi.fn();
    const { engine } = makeEngine({ onSelect });
    engine.setTile(11, { x: 0, y: 0, src: 'a.png', layer: 'anchor' });
    engine.setCursor(11);
    engine.setSelection([11]);
    engine.handleKey(key({ key: 'Escape' }));
    expect(engine.getSelection()).toEqual([]);
    expect(engine.getCursor()).toBe(11); // the tile under judgement stays put
    expect(onSelect).toHaveBeenLastCalledWith(null);
    engine.destroy();
  });
});
