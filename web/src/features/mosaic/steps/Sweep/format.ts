// Small display formatters for the sweep readouts. Numbers are mono and tabular; a missing value is an
// em dash, never a fabricated 0 (an NCC of null means "not measurable", not "no correlation").

export function fmtNcc(n: number | null | undefined): string {
  return n == null || !Number.isFinite(n) ? '—' : n.toFixed(4);
}

export function fmtMargin(n: number | null | undefined): string {
  return n == null || !Number.isFinite(n) ? '—' : n.toFixed(3);
}

export function fmtInt(n: number | null | undefined): string {
  return n == null || !Number.isFinite(n) ? '—' : String(Math.round(n));
}

/** A top-left corner, `(x, y)` — positions in Camea are TOP-LEFT, never centres (R19). */
export function fmtXY(x: number | null | undefined, y: number | null | undefined): string {
  if (x == null || y == null || !Number.isFinite(x) || !Number.isFinite(y)) return '(—, —)';
  return `(${Math.round(x)}, ${Math.round(y)})`;
}
