// HOW THE SHELF IS ORDERED — the sort and the type filter, as pure functions of the rows.
//
// ⭐ **A VIEW, NEVER A WRITE** (R44: this feature writes no files, and the document's own order is
// untouched). The component derives the visible order on every render from whatever the last read
// returned, so the 700 ms copy-poll — which replaces `rows` wholesale — cannot fight the sort:
// the poll brings facts, this arranges them, and row identity stays the minted `id`.
//
// Its own module for the reason `hitRadius.ts` is: the ordering rules are the part worth testing
// on their own, and a component file that exports helpers breaks fast refresh.

import type { MeaShelfEntry } from '../../api';

/** The sorts the shelf offers, in menu order, with the words the control shows. */
export const SHELF_SORTS = [
  ['as-added', 'As added'],
  ['name', 'Name'],
  ['length', 'Length'],
  ['spikes', 'Spikes'],
  ['size', 'Size'],
  ['date', 'Date added'],
] as const;

export type ShelfSort = (typeof SHELF_SORTS)[number][0];

/** What a row is called on screen — the same fallback chain the label button renders. */
export function shelfLabel(r: MeaShelfEntry): string {
  return r.label || r.run_id || r.id;
}

/** The assay values a filter can offer: distinct, non-empty, in first-seen order. */
export function shelfAssays(rows: readonly MeaShelfEntry[]): string[] {
  const seen: string[] = [];
  for (const r of rows) {
    if (r.assay && !seen.includes(r.assay)) seen.push(r.assay);
  }
  return seen;
}

/** Descending, with unknowns LAST — a row that lost its file shows no numbers (I1), and a shelf
 *  sort must not promote it to the top as if "no number" outranked every real one. */
function numDesc(a: number | null, b: number | null): number {
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  return b - a;
}

function addedMs(r: MeaShelfEntry): number | null {
  const t = Date.parse(r.added ?? '');
  return Number.isFinite(t) ? t : null;
}

/**
 * The rows as the shelf shows them: filtered to one assay (or all, `''`), then sorted.
 * `as-added` is the document's own order — the default, and exactly what the shelf always was.
 * Ties keep the document order (`Array.prototype.sort` is stable).
 */
export function orderShelf(
  rows: readonly MeaShelfEntry[],
  sort: ShelfSort,
  assay: string,
): MeaShelfEntry[] {
  const kept = assay ? rows.filter((r) => r.assay === assay) : [...rows];
  switch (sort) {
    case 'as-added':
      return kept;
    case 'name':
      return kept.sort((x, y) =>
        shelfLabel(x).localeCompare(shelfLabel(y), undefined, { numeric: true, sensitivity: 'base' }),
      );
    case 'length':
      return kept.sort((x, y) => numDesc(x.duration_s ?? null, y.duration_s ?? null));
    case 'spikes':
      return kept.sort((x, y) => numDesc(x.n_spikes ?? null, y.n_spikes ?? null));
    case 'size':
      // `bytes` defaults to 0 on a row whose file is gone — that is "unknown", not a small file.
      return kept.sort((x, y) => numDesc(x.bytes || null, y.bytes || null));
    case 'date':
      return kept.sort((x, y) => numDesc(addedMs(x), addedMs(y)));
  }
}
