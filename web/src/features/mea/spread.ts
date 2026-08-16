// PADS PER FIRING-RATE BAND — the arithmetic behind the small bar chart beside the legend.
//
// ⭐ **RE-PUT TO HIM AND ACCEPTED, 2026-08-15.** A histogram beside the chip was declined on
// 2026-08-14; `docs/MAXWELL.md` §7.2 then argued the case from the corpus — the colour answers
// *where*, the distribution answers *how much, really* — and, re-asked with that evidence, he
// said yes.
//
// ⭐ **THE BANDS ARE THE LEGEND'S OWN VALUES.** Each live band runs between two adjacent legend
// stops, so the chart and the swatches cannot disagree about what a colour stands for. On the
// rank ramp that makes the live bars roughly even by construction — the legend's own caveat made
// visible — while ties, and the no-spike pads, are where the real differences show.
//
// 🔴 The no-spike pads are their own bar, never a position on the ramp, and its vocabulary is the
// approved sentence's (`SILENT_MEANING`) — same rule as the hollow ring it stands beside.

import type { ActivityScale } from './activityScale';
import { rampColour } from './activityScale';

export interface SpreadBand {
  /** True for the no-spikes bar — drawn hollow, like the ring it stands for. */
  silent: boolean;
  /** Live bands: the rate range counted, in spikes/s. Zero on the silent bar. */
  lo: number;
  hi: number;
  /** Whether `hi` is counted in (true only on the busiest band, which owns the maximum). */
  hiInclusive: boolean;
  count: number;
  /** The ramp colour at the band's midpoint; empty on the silent bar. */
  colour: string;
}

/** Does this band hold a pad firing at `rateHz`? The drawing and the counting share this rule. */
export function bandHolds(b: SpreadBand, rateHz: number): boolean {
  if (b.silent) return rateHz === 0;
  if (!(rateHz > 0)) return false;
  return rateHz >= b.lo && (b.hiInclusive ? rateHz <= b.hi : rateHz < b.hi);
}

/**
 * The bars: the silent bar first (it sits at the quiet end), then one band between each pair of
 * adjacent legend stops. Every live pad lands in exactly one band, so the live counts always sum
 * to `scale.nLive` — the invariant the unit test pins.
 */
export function spreadBands(scale: ActivityScale, rates: readonly number[]): SpreadBand[] {
  const bands: SpreadBand[] = [
    { silent: true, lo: 0, hi: 0, hiInclusive: false, count: scale.nSilent, colour: '' },
  ];
  const stops = scale.legend;
  if (scale.nLive > 0 && stops.length >= 2) {
    for (let i = 0; i < stops.length - 1; i++) {
      const band: SpreadBand = {
        silent: false,
        lo: stops[i]!.rateHz,
        hi: stops[i + 1]!.rateHz,
        hiInclusive: i === stops.length - 2,
        count: 0,
        colour: rampColour((stops[i]!.t + stops[i + 1]!.t) / 2),
      };
      band.count = rates.filter((r) => bandHolds(band, r)).length;
      bands.push(band);
    }
  }
  return bands;
}
