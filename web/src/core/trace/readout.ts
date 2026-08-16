// The one sentence under the close-up, and the one a screen reader hears after a keyboard zoom.
// Its own module so both `TraceNav` and `MeaTrace` can use it without either importing a component
// from the other (and so fast refresh keeps working on the component file).
//
// ⭐ **THE WIDTH SITS BESIDE THE COUNT DELIBERATELY.** "7 spikes" is not a number anybody can use
// without the stretch it was counted over — see `docs/MAXWELL.md` §7.3. R3: numbers, not prose.

/** `12.480–13.480 s of 300 s · 1.00 s wide · 7 spikes in view` */
export function readout(t0: number, t1: number, duration: number, nSpikes: number): string {
  const width = Math.max(0, t1 - t0);
  // Enough decimals to tell two adjacent views apart at whatever depth he has reached — a fixed
  // 2 dp reads "0.00 s wide" once he is zoomed inside a single spike.
  const dp = width >= 1 ? 2 : width >= 0.01 ? 4 : 6;
  return (
    `${t0.toFixed(dp)}–${t1.toFixed(dp)} s of ${duration.toFixed(0)} s · ` +
    `${width.toFixed(dp)} s wide · ${nSpikes} spike${nSpikes === 1 ? '' : 's'} in view`
  );
}
