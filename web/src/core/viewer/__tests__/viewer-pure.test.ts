// Pure-logic unit tests for the viewer's testable cores: the camera math, the feather ramp, and the
// keyboard map. No canvas required. These pin the rulings that live in the maths — the top-left
// coordinate convention (R19), the feather shape (R10.3), and the §3.4/§6.7 key contract.

import { describe, it, expect } from 'vitest';
import { clamp, fitView, screenToWorld, worldToScreen, zoomToView } from '../camera';
import { featherRamp } from '../feather';
import { mapCameraKey } from '../keymap';
import type { ViewMatrix } from '../types';

describe('camera', () => {
  const view: ViewMatrix = { scale: 2, tx: 30, ty: -10 };

  it('worldToScreen and screenToWorld round-trip', () => {
    const [sx, sy] = worldToScreen(view, 100, 40);
    const [wx, wy] = screenToWorld(view, sx, sy);
    expect(wx).toBeCloseTo(100, 6);
    expect(wy).toBeCloseTo(40, 6);
  });

  it('clamp bounds a value', () => {
    expect(clamp(5, 0, 10)).toBe(5);
    expect(clamp(-1, 0, 10)).toBe(0);
    expect(clamp(99, 0, 10)).toBe(10);
  });

  it('zoomToView keeps the world point under the pivot fixed on screen', () => {
    const [px, py] = [400, 250];
    const [wx, wy] = screenToWorld(view, px, py);
    const zoomed = zoomToView(view, view.scale * 1.5, px, py);
    const [sx, sy] = worldToScreen(zoomed, wx, wy);
    expect(sx).toBeCloseTo(px, 6);
    expect(sy).toBeCloseTo(py, 6);
    expect(zoomed.scale).toBeCloseTo(3, 6);
  });

  it('fitView centres the box in the viewport', () => {
    const box = { x0: 0, y0: 0, x1: 200, y1: 100 };
    const cssW = 800;
    const cssH = 600;
    const v = fitView(box, cssW, cssH, 48);
    const [cx, cy] = worldToScreen(v, (box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2);
    expect(cx).toBeCloseTo(cssW / 2, 6);
    expect(cy).toBeCloseTo(cssH / 2, 6);
  });

  it('fitView respects the SCALE_MAX clamp on a tiny box', () => {
    const v = fitView({ x0: 0, y0: 0, x1: 1, y1: 1 }, 800, 600, 48);
    expect(v.scale).toBeLessThanOrEqual(16);
  });
});

describe('featherRamp (the cosine falloff — R10.3)', () => {
  const size = 512;
  const feather = 40;
  const ramp = featherRamp(size, feather);

  it('has the tile length', () => {
    expect(ramp).toHaveLength(size);
  });

  it('is 0 at both edges and 1 in the interior', () => {
    expect(ramp[0]).toBeCloseTo(0, 6);
    expect(ramp[size - 1]).toBeCloseTo(0, 6);
    expect(ramp[Math.floor(size / 2)]).toBeCloseTo(1, 6);
    expect(ramp[feather]).toBeCloseTo(1, 6); // exactly at the ramp width it is already opaque
  });

  it('is symmetric', () => {
    for (let i = 0; i < size; i++) expect(ramp[i]).toBeCloseTo(ramp[size - 1 - i], 6);
  });

  it('rises monotonically across the ramp', () => {
    for (let i = 1; i <= feather; i++) expect(ramp[i]).toBeGreaterThanOrEqual(ramp[i - 1]);
  });
});

describe('mapCameraKey (§3.4 / §6.7)', () => {
  it('🔴 returns null for Space — it is ADVANCE, never a camera key', () => {
    expect(mapCameraKey({ key: ' ', code: 'Space' })).toBeNull();
    expect(mapCameraKey({ key: 'Spacebar', code: 'Space' })).toBeNull();
  });

  it('returns null for Ctrl/⌘ combinations (they are the feature’s)', () => {
    expect(mapCameraKey({ key: 's', ctrlKey: true })).toBeNull();
    expect(mapCameraKey({ key: 'z', metaKey: true })).toBeNull();
  });

  it('returns null while focus is in a text input', () => {
    const target = { tagName: 'INPUT' } as unknown as EventTarget;
    expect(mapCameraKey({ key: 'd', target })).toBeNull();
    const ta = { tagName: 'TEXTAREA' } as unknown as EventTarget;
    expect(mapCameraKey({ key: 'f', target: ta })).toBeNull();
  });

  it('arrows nudge 1 px, Shift+arrow 10 px, in world coords', () => {
    expect(mapCameraKey({ key: 'ArrowRight' })).toEqual({ kind: 'nudge', dx: 1, dy: 0 });
    expect(mapCameraKey({ key: 'ArrowLeft', shiftKey: true })).toEqual({
      kind: 'nudge',
      dx: -10,
      dy: 0,
    });
    expect(mapCameraKey({ key: 'ArrowUp' })).toEqual({ kind: 'nudge', dx: 0, dy: -1 });
    expect(mapCameraKey({ key: 'ArrowDown', shiftKey: true })).toEqual({
      kind: 'nudge',
      dx: 0,
      dy: 10,
    });
  });

  it('maps the camera letters and 0 (1:1, not an alternatives key — R12.6)', () => {
    expect(mapCameraKey({ key: 'f' })).toEqual({ kind: 'fit' });
    expect(mapCameraKey({ key: 'F' })).toEqual({ kind: 'fit' });
    expect(mapCameraKey({ key: '0' })).toEqual({ kind: 'oneToOne' });
    expect(mapCameraKey({ key: 'd' })).toEqual({ kind: 'difference' });
    expect(mapCameraKey({ key: 'g' })).toEqual({ kind: 'grid' });
    expect(mapCameraKey({ key: 'Escape' })).toEqual({ kind: 'escape' });
  });

  it('maps zoom keys', () => {
    expect(mapCameraKey({ key: '+' })).toEqual({ kind: 'zoom', factor: 1.3 });
    expect(mapCameraKey({ key: '=' })).toEqual({ kind: 'zoom', factor: 1.3 });
    const out = mapCameraKey({ key: '-' });
    expect(out?.kind).toBe('zoom');
    expect(out).toMatchObject({ factor: expect.closeTo(1 / 1.3, 6) });
  });

  it('returns null for an unbound key', () => {
    for (const key of ['q', 'j', 'k', 'z', '1', '9']) {
      // 1..9 are the feature’s jump keys, not the camera’s — the viewer must not claim them.
      expect(mapCameraKey({ key })).toBeNull();
    }
  });
});
