// R9 — the sweep draws only the certified field + the one tile under judgement. `viewerTileFor` is the
// pure mapping that enforces it: anchored → the drawn `anchor` layer (feathered), unverified → the
// maintained-but-hidden `unverified` layer, and unplaced/excluded → nothing at all.

import { describe, expect, it } from 'vitest';
import { viewerTileFor } from './viewerSync';
import { fmtNcc, fmtMargin, fmtInt, fmtXY } from './format';
import type { MosaicDocument } from '../../../../api';

type Tile = MosaicDocument['tiles'][string];

const base: Tile = {
  status: 'unplaced',
  state: 'unplaced',
  blank: false,
  human: false,
  stale: false,
  diverted: false,
};

describe('viewerTileFor — R9 layer mapping', () => {
  it('anchored → the anchor layer, feathered (the certified field, the Difference reference)', () => {
    const vt = viewerTileFor({ ...base, status: 'anchor', state: 'anchored', x: 10, y: 20 }, 'url');
    expect(vt).toEqual({ x: 10, y: 20, src: 'url', layer: 'anchor', feather: true, outline: null });
  });

  it('unverified → the unverified layer, NOT feathered (maintained but not drawn)', () => {
    const vt = viewerTileFor({ ...base, state: 'unverified', x: 1, y: 2 }, 'url');
    expect(vt?.layer).toBe('unverified');
    expect(vt?.feather).toBe(false);
  });

  it('unplaced → null (nothing is drawn for it — it is in the rescue queue)', () => {
    expect(viewerTileFor({ ...base }, 'url')).toBeNull();
  });

  it('excluded → null (not drawn, not matched, not rendered)', () => {
    expect(viewerTileFor({ ...base, state: 'excluded', x: 5, y: 5 }, 'url')).toBeNull();
  });
});

describe('format — a missing measurement is an em dash, never a fabricated 0', () => {
  it('nulls / undefined render as —', () => {
    expect(fmtNcc(null)).toBe('—');
    expect(fmtMargin(undefined)).toBe('—');
    expect(fmtInt(null)).toBe('—');
    expect(fmtXY(null, 3)).toBe('(—, —)');
  });

  it('a top-left corner rounds to integers (R19)', () => {
    expect(fmtXY(1.4, -2.6)).toBe('(1, -3)');
    expect(fmtNcc(0.90741)).toBe('0.9074');
  });
});
