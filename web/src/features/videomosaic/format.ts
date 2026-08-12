// Pure receipt formatters for the videomosaic feature — display only, unit-free of any dataset.
// (The container's fps/n_frames are CLAIMS, good for a receipt, never for arithmetic — VideoSource.)

/** `83.4 → "1m 23s"` · `47 → "47 s"` · `4000 → "1h 06m"`. Clamped at zero. */
export function fmtDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`;
  return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}m`;
}

/** `242221056 → "231.0 MB"`. */
export function fmtBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '—';
  if (bytes < 1024) return `${Math.round(bytes)} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let v = bytes;
  let u = -1;
  do {
    v /= 1024;
    u += 1;
  } while (v >= 1024 && u < units.length - 1);
  return `${v >= 100 ? Math.round(v) : v.toFixed(1)} ${units[u]}`;
}

/** `30.0 → "30"` · `29.97 → "29.97"`. */
export function fmtFps(fps: number): string {
  if (!Number.isFinite(fps)) return '—';
  return Number.isInteger(fps) ? String(fps) : fps.toFixed(2).replace(/0+$/, '').replace(/\.$/, '');
}
