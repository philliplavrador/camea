// The one sentence under the close-up, and the one a screen reader hears after a keyboard zoom.
// Its own module so both `TraceNav` and `MeaTrace` can use it without either importing a component
// from the other (and so fast refresh keeps working on the component file).
//
// ⭐ **THE WIDTH SITS BESIDE THE COUNT DELIBERATELY.** "7 spikes" is not a number anybody can use
// without the stretch it was counted over — see `docs/MAXWELL.md` §7.3. R3: numbers, not prose.

/**
 * How many decimals a time needs at this view width — enough to tell two adjacent views apart at
 * whatever depth he has reached. A fixed 2 dp reads "0.00 s wide" once he is zoomed inside a
 * single spike. Shared by the range readout and the pointer-time readout, so the two can never
 * print the same moment at two precisions.
 */
export function timeDp(width: number): number {
  return width >= 1 ? 2 : width >= 0.01 ? 4 : 6;
}

/** `12.480–13.480 s of 300 s · 1.00 s wide · 7 spikes in view` */
export function readout(t0: number, t1: number, duration: number, nSpikes: number): string {
  const width = Math.max(0, t1 - t0);
  const dp = timeDp(width);
  return (
    `${t0.toFixed(dp)}–${t1.toFixed(dp)} s of ${duration.toFixed(0)} s · ` +
    `${width.toFixed(dp)} s wide · ${nSpikes} spike${nSpikes === 1 ? '' : 's'} in view`
  );
}
