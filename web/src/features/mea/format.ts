// The two little formatters every MEA surface needs. One module, because three private copies of
// `formatSeconds` had already grown inside this feature (the shelf, the open header, the import
// list) before anything shared them — this is where they now live.
//
// (`features/outputs/OutputsPanel.tsx` still carries its own `formatBytes`; that is another
// feature's copy and is deliberately left alone.)

/** `3.0 s` · `42 s` · `5m 0s` — the grammar the shelf and the open-recording header always used. */
export function formatSeconds(s: number): string {
  if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)} s`;
  const m = Math.floor(s / 60);
  return `${m}m ${Math.round(s - m * 60)}s`;
}

/** `19 kB` · `1.1 GB` — binary steps, one decimal past MB. */
export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} kB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}
