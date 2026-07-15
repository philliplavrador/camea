import { describe, it, expect } from 'vitest';
import { mapSweepKey, UNBOUND_SWEEP_KEYS, type Screen } from './keys';

function ev(
  over: Partial<Parameters<typeof mapSweepKey>[0]> = {},
): Parameters<typeof mapSweepKey>[0] {
  return { key: '', ...over };
}

describe('the global guard (§3.1)', () => {
  it('1 — focus in an editable → nothing fires (this is why digits do not fight the tone/range fields)', () => {
    const target = { tagName: 'INPUT', isContentEditable: false } as unknown as EventTarget;
    expect(mapSweepKey(ev({ key: '1', target }), 'sweep')).toBeNull();
    expect(mapSweepKey(ev({ key: 'a', target }), 'sweep')).toBeNull();
    // even Ctrl+S is blocked while typing (§3.1 point 1 runs first)
    expect(mapSweepKey(ev({ key: 's', ctrlKey: true, target }), 'sweep')).toBeNull();
  });

  it('2 — Ctrl/⌘ + S/Z/Y fire on EVERY screen (R5.2)', () => {
    for (const screen of ['load', 'range', 'mosaic', 'sweep'] as Screen[]) {
      expect(mapSweepKey(ev({ key: 's', ctrlKey: true }), screen)).toEqual({ kind: 'save' });
      expect(mapSweepKey(ev({ key: 'z', metaKey: true }), screen)).toEqual({ kind: 'undo' });
      expect(mapSweepKey(ev({ key: 'y', ctrlKey: true }), screen)).toEqual({ kind: 'redo' });
    }
  });

  it('3 — any other Ctrl/⌘/Alt combination is ignored', () => {
    expect(mapSweepKey(ev({ key: 'a', ctrlKey: true }), 'sweep')).toBeNull();
    expect(mapSweepKey(ev({ key: 'd', metaKey: true }), 'sweep')).toBeNull();
    expect(mapSweepKey(ev({ key: 'a', altKey: true }), 'sweep')).toBeNull();
  });

  it('4 — the sweep keys do NOT fire off the sweep', () => {
    expect(mapSweepKey(ev({ key: 'a' }), 'range')).toBeNull();
    expect(mapSweepKey(ev({ key: ' ' }), 'load')).toBeNull();
    expect(mapSweepKey(ev({ key: '1' }), 'place')).toBeNull();
  });
});

describe('the sweep keys (§3.3)', () => {
  it('Space → advance (by code and by key)', () => {
    expect(mapSweepKey(ev({ key: ' ' }), 'sweep')).toEqual({ kind: 'advance' });
    expect(mapSweepKey(ev({ key: 'Spacebar', code: 'Space' }), 'sweep')).toEqual({
      kind: 'advance',
    });
  });
  it('A/E/R/V/S map to their actions, case-insensitively', () => {
    expect(mapSweepKey(ev({ key: 'a' }), 'sweep')).toEqual({ kind: 'anchor' });
    expect(mapSweepKey(ev({ key: 'A' }), 'sweep')).toEqual({ kind: 'anchor' });
    expect(mapSweepKey(ev({ key: 'E' }), 'sweep')).toEqual({ kind: 'exclude' });
    expect(mapSweepKey(ev({ key: 'r' }), 'sweep')).toEqual({ kind: 'replay' });
    expect(mapSweepKey(ev({ key: 'V' }), 'sweep')).toEqual({ kind: 'alternatives' });
    expect(mapSweepKey(ev({ key: 's' }), 'sweep')).toEqual({ kind: 'snap' });
  });

  it('1–9 jump to a 0-indexed rank (digit − 1); the display reads rank + 1', () => {
    expect(mapSweepKey(ev({ key: '1' }), 'sweep')).toEqual({ kind: 'jump', rank: 0 });
    expect(mapSweepKey(ev({ key: '2' }), 'sweep')).toEqual({ kind: 'jump', rank: 1 });
    expect(mapSweepKey(ev({ key: '9' }), 'sweep')).toEqual({ kind: 'jump', rank: 8 });
  });
});

describe('⛔ the deliberately-unbound keys stay unbound', () => {
  it('0 is the viewer 1:1 zoom, NOT a jump (R12.6)', () => {
    expect(mapSweepKey(ev({ key: '0' }), 'sweep')).toBeNull();
  });
  it('[ and ] are not bound (the opacity step was never shipped — R13.7)', () => {
    expect(mapSweepKey(ev({ key: '[' }), 'sweep')).toBeNull();
    expect(mapSweepKey(ev({ key: ']' }), 'sweep')).toBeNull();
  });
  it('+/-/= belong to the viewer zoom (R13.7)', () => {
    for (const key of ['+', '=', '-', '_']) expect(mapSweepKey(ev({ key }), 'sweep')).toBeNull();
  });
  it('camera keys (F/D/G/Escape/arrows) fall through to the camera map', () => {
    for (const key of ['f', 'd', 'g', 'Escape', 'ArrowLeft', 'ArrowUp']) {
      expect(mapSweepKey(ev({ key }), 'sweep')).toBeNull();
    }
  });
  it('every listed UNBOUND key resolves to null', () => {
    for (const key of UNBOUND_SWEEP_KEYS) expect(mapSweepKey(ev({ key }), 'sweep')).toBeNull();
  });
});
