// The shelf's ordering rules. What must hold: "As added" is exactly the document's order, every
// sort puts the unknowable rows LAST (a row that lost its file shows no numbers — it must not
// outrank real ones), and the filter never invents or drops a row it was not asked about.

import { describe, expect, it } from 'vitest';
import type { MeaShelfEntry } from '../../api';
import { orderShelf, shelfAssays, shelfLabel } from './shelfOrder';

/** A minimal shelf row; only the fields the ordering reads are meaningful here. */
function row(over: Partial<MeaShelfEntry>): MeaShelfEntry {
  return {
    id: 'rec',
    label: '',
    run_id: '',
    assay: '',
    source_path: 'D:/x/data.raw.h5',
    stored_path: '',
    copy_state: 'stored',
    copy_pct: 0,
    copy_error: '',
    added: '',
    bytes: 0,
    missing: false,
    source_present: true,
    ...over,
  };
}

const shelf = [
  row({ id: 'a', label: 'beta', assay: 'Network', duration_s: 300, n_spikes: 10, bytes: 50,
    added: '2026-08-01T10:00:00Z' }),
  row({ id: 'b', label: 'alpha', assay: 'ActivityScan', duration_s: 30, n_spikes: 999, bytes: 900,
    added: '2026-08-10T10:00:00Z' }),
  // A row that lost its file: no numbers at all (I1 — never zeros).
  row({ id: 'c', label: 'gone', assay: 'Network', missing: true,
    duration_s: null, n_spikes: null, bytes: 0, added: '2026-08-05T10:00:00Z' }),
];

const ids = (rows: MeaShelfEntry[]): string[] => rows.map((r) => r.id);

describe('orderShelf', () => {
  it('keeps the document order under "As added" — the default is exactly what the shelf was', () => {
    expect(ids(orderShelf(shelf, 'as-added', ''))).toEqual(['a', 'b', 'c']);
  });

  it('sorts by name ascending, by the same fallback chain the row displays', () => {
    expect(ids(orderShelf(shelf, 'name', ''))).toEqual(['b', 'a', 'c']);
    expect(shelfLabel(row({ id: 'x', label: '', run_id: '000690' }))).toBe('000690');
  });

  it('sorts numbers descending, and the row with no numbers goes LAST, not first', () => {
    expect(ids(orderShelf(shelf, 'length', ''))).toEqual(['a', 'b', 'c']);
    expect(ids(orderShelf(shelf, 'spikes', ''))).toEqual(['b', 'a', 'c']);
    expect(ids(orderShelf(shelf, 'size', ''))).toEqual(['b', 'a', 'c']);
  });

  it('sorts by date added, newest first, unknown dates last', () => {
    expect(ids(orderShelf(shelf, 'date', ''))).toEqual(['b', 'c', 'a']);
    const undated = shelf.map((r) => (r.id === 'c' ? { ...r, added: '' } : r));
    expect(ids(orderShelf(undated, 'date', ''))).toEqual(['b', 'a', 'c']);
  });

  it('filters to one assay and never touches the rest', () => {
    expect(ids(orderShelf(shelf, 'as-added', 'Network'))).toEqual(['a', 'c']);
    expect(ids(orderShelf(shelf, 'as-added', 'ActivityScan'))).toEqual(['b']);
    // The input is never mutated — the component re-derives this on every render.
    expect(ids([...shelf])).toEqual(['a', 'b', 'c']);
  });
});

describe('shelfAssays', () => {
  it('offers each assay once, in first-seen order, and skips blanks', () => {
    expect(shelfAssays(shelf)).toEqual(['Network', 'ActivityScan']);
    expect(shelfAssays([row({ assay: '' })])).toEqual([]);
  });
});
