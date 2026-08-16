// ─────────────────────────────────────────────────────────────────────────────────────────────
// HOW BUSY A PAD WAS → WHAT COLOUR IT IS. **The one place that decides, and deliberately the
// only one.** `ChipMap` draws what this says and holds no opinion of its own; the legend below
// is generated from the same object that colours the dots, so the two cannot drift apart.
//
// ═════════════════════════════════════════════════════════════════════════════════════════════
// ⭐ **SETTLED 2026-08-14: THE RANK RAMP, AND HE CHOSE IT ON THE EVIDENCE.**
// ═════════════════════════════════════════════════════════════════════════════════════════════
// He was shown three ways of handing out the colours and picked none of them — he corrected the
// premise instead (see THE CORRECTION below) and asked for research first. That research is
// `docs/MAXWELL.md`; it measured all four candidates across **33 recordings, 57 configurations
// and 4 chips**, and he was then re-asked with the result. He kept the rank ramp, and declined
// a histogram beside the chip.
//
// ⭐ **RE-CONFIRMED 2026-08-15, WITH THE TOOL: keep the rank ramp exactly as it is.** The hedges
// that called this mapping "provisional" or "held pending MAXWELL.md" are gone with that answer —
// nothing about the ramp is pending. If it is ever revisited, that is a NEW question for him.
// (The declined histogram was ALSO re-put that day, with §7.2's evidence, and he said yes — it
// ships as the spread chart, `spread.ts` / `SpreadChart.tsx`, banded on this legend's own stops.)
//
// ⚠️ **This is still the only file that knows how a rate becomes a colour, and it must stay that
// way.** `ChipMap` asks `position()` for a number between 0 and 1, or `null`, and draws that. If
// the scale is ever revisited, this is again the only edit.
//
// The four candidates, and why the corpus killed three of them (`docs/MAXWELL.md` § 7.2):
//
//   1. "Straight"       — busiest pad sets the top, everything a straight fraction of it.
//                         ⛔ MEASURED: **72–99 % of live pads land in the darkest tenth** —
//                         000688 **72 %**, 000689 99 %, 000690 99 %, 000691 90 %, 000692 96 %.
//                         Even at the 72 % end the picture is very nearly one flat colour, which
//                         hides the structure the screen exists to show.
//                         ⚠️ An earlier revision of this header said "90–99 % on every one of his
//                         recordings". That was wrong — it read past the 72 % row in the source
//                         note. The argument is untouched; the number was not.
//   2. "Halfway"        — square root. Better, but recording-dependent: still 96 % in the
//                         darkest tenth on 000690, while 000692 comes out well (41 %). A ramp
//                         that fixes some files and not others is not a fix.
//   3. "Log"            — ⛔ tempting and wrong: log-normality holds on the BUSY recordings only
//                         (log-skew 0.078–0.554 on four files, but 1.591 on 000689 and 2.316 on
//                         000690). Never pick a ramp whose assumption breaks on a third of the
//                         corpus.
//   4. "Spread them out"— every live pad's colour is its POSITION IN THE ORDER, so the picture
//                         always uses the full range whatever the recording. ⭐ **THE CHOICE.**
//                         It is the only one of the four that measured well on every recording,
//                         and it is the ASSUMPTION-FREE one precisely because the distribution
//                         family is not stable: mean rate spans 171× across the corpus and 113×
//                         between two runs of the SAME PLATE. The cost is real and stays stated
//                         in the legend: equal colour steps are NOT equal rate steps.
//
// ═════════════════════════════════════════════════════════════════════════════════════════════
// ⭐ **THE CORRECTION — HIS WORDS, 2026-08-14, AND THIS PART IS NOT PENDING ANYTHING**
// ═════════════════════════════════════════════════════════════════════════════════════════════
// > *"not all electrodes can be used at the same time on an MEA chip. of the neurons that are
// >  being used not all of them are near neurons."*
//
// Two facts about the hardware and the biology, and the second one changes the WORDING here:
//
//   * the chip cannot record every pad at once — a configuration routes a subset, chosen at
//     acquisition. That is why the map draws only routed pads.
//   * ⭐ **among the pads that WERE routed, many are not near a neuron at all.** So a routed pad
//     with zero spikes is the **ordinary, expected** case. ⛔ It is **not** a dead electrode, not
//     a fault, and not evidence of a quiet culture — it usually means there was simply no cell
//     there.
//
// ⛔ So nothing in this file, in `ChipMap`, or in the trace panel may call such a pad "dead",
// "silent", "failed" or "flat". The hollow ring reads *"nothing was here"*, never *"this one
// broke"*. `SILENT_MEANING` below is the single sentence, so it cannot drift between the legend
// and the hover.
//
// ⛔ **AND NO DATASET KNOWLEDGE** (I1). There is no constant here describing how active a chip
// should be — no expected rate, no "healthy" threshold, no fixed maximum. Every number the scale
// uses is computed from the recording in front of it, every time. That is a `Done when` box.
// ─────────────────────────────────────────────────────────────────────────────────────────────

/**
 * ⭐ **What a pad with no spikes actually means**, in one place so the legend and the hover say
 * the same thing. His correction, 2026-08-14 — see the header.
 */
export const SILENT_MEANING = 'no spikes — most likely no neuron near this pad';

/**
 * ⭐ **Why equal colour steps are not equal rate steps**, stated on the legend rather than left
 * for him to infer. Tied to the rank scale below; it changes with it.
 */
export const SCALE_CAVEAT =
  'Colours are shared out evenly across the pads that fired, so the busiest and quietest parts ' +
  'of the chip stay apart. Equal steps of colour are not equal steps of rate — read the numbers.';

/**
 * A perceptually ordered ramp, dark → bright. Stops are sampled from viridis, which is ordered
 * in lightness (so it survives greyscale and the common colour-blindnesses) and has no false
 * bright band in the middle the way a rainbow does.
 *
 * ⛔ These are ramp colours, not theme colours: they must mean the same thing in light mode and
 * dark mode, so they are literal and do not come from the token set.
 */
const RAMP: readonly (readonly [number, number, number])[] = [
  [68, 1, 84],
  [72, 40, 120],
  [62, 74, 137],
  [49, 104, 142],
  [38, 130, 142],
  [31, 158, 137],
  [53, 183, 121],
  [109, 205, 89],
  [180, 222, 44],
  [253, 231, 37],
];

/** The ramp colour at `t` (0..1), linearly interpolated between stops. -> `rgb(...)`. */
export function rampColour(t: number): string {
  const u = Math.max(0, Math.min(1, t)) * (RAMP.length - 1);
  const i = Math.min(RAMP.length - 2, Math.floor(u));
  const f = u - i;
  const a = RAMP[i]!;
  const b = RAMP[i + 1]!;
  const mix = (j: number): number => Math.round(a[j]! + (b[j]! - a[j]!) * f);
  return `rgb(${mix(0)}, ${mix(1)}, ${mix(2)})`;
}

export interface LegendStop {
  /** Where on the ramp, 0..1. */
  t: number;
  /** The real rate this colour stands for, in spikes per second. */
  rateHz: number;
  colour: string;
}

export interface ActivityScale {
  /**
   * Where this pad sits on the ramp, 0..1 — or **`null` when it recorded no spikes at all**,
   * which is not a position on the ramp and must not be drawn as one. `ChipMap` draws those as a
   * hollow ring (his call, 2026-08-14): a different *shape*, so it can never be misread as a dim
   * colour, and it survives being printed in black and white.
   */
  position(rateHz: number): number | null;
  /** Swatches for the legend, dim → busy, each naming the real rate it stands for. */
  legend: LegendStop[];
  /** The busiest pad **in this recording**. ⛔ Derived every time; never a constant. */
  maxRateHz: number;
  /** Pads that were listened to and heard nothing. ⭐ Ordinary — see `SILENT_MEANING`. */
  nSilent: number;
  /** Pads that fired at least once. */
  nLive: number;
}

/** How many swatches the legend shows. A display choice, not a fact about any chip. */
const LEGEND_STOPS = 5;

/**
 * Build the colour scale for **one recording**, from that recording's own numbers.
 *
 * ⛔ **THE WHOLE SCALE IS DERIVED FROM `rates`, EVERY TIME.** Nothing is remembered between
 * recordings and nothing is declared in advance — open a different file and you get a different
 * scale, because the two chips were not equally busy. See the header for why that matters.
 *
 * @param rates spikes-per-second for every **routed** pad, including the ones that heard nothing.
 */
export function activityScale(rates: readonly number[]): ActivityScale {
  // Only the pads that actually fired take part in the ramp. A pad that heard nothing is drawn as
  // a ring, so including it would squash the live range for no benefit — and, more to the point,
  // it is not a low rate, it is the absence of a neuron.
  const live = rates.filter((r) => r > 0).sort((a, b) => a - b);
  const n = live.length;
  const maxRateHz = n > 0 ? live[n - 1]! : 0;

  // ── THE RANK RAMP — settled (see the header). Each live pad's position is its place in the order, so the
  // picture uses the full ramp whatever the recording. Ties share a colour (the midpoint of their
  // block), which keeps the mapping a pure function of the rate — two pads with the same rate must
  // never come out different colours just because of their order in the array.
  const positionOf = (rateHz: number): number => {
    if (n <= 1) return 1;
    const lo = lowerBound(live, rateHz);
    const hi = upperBound(live, rateHz);
    return Math.max(0, Math.min(1, ((lo + hi) / 2) / n));
  };

  const legend: LegendStop[] = [];
  for (let i = 0; i < LEGEND_STOPS; i++) {
    const t = i / (LEGEND_STOPS - 1);
    // The inverse of the mapping above: which rate lands at this colour. That is what lets the
    // legend name real units even though the steps between them are uneven.
    const idx = Math.max(0, Math.min(n - 1, Math.round(t * (n - 1))));
    legend.push({ t, rateHz: n > 0 ? live[idx]! : 0, colour: rampColour(t) });
  }

  return {
    position: (rateHz: number) => (rateHz > 0 ? positionOf(rateHz) : null),
    legend,
    maxRateHz,
    nSilent: rates.length - n,
    nLive: n,
  };
}

function lowerBound(sorted: readonly number[], v: number): number {
  let lo = 0;
  let hi = sorted.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (sorted[mid]! < v) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

function upperBound(sorted: readonly number[], v: number): number {
  let lo = 0;
  let hi = sorted.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (sorted[mid]! <= v) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/**
 * `0.003 spikes/s`, `0.42 spikes/s`, `860 spikes/s` — readable at every magnitude he actually sees.
 *
 * ⚠️ **Plain decimals all the way down, never scientific notation.** Seen on his own data: the
 * quiet end of a real recording lands around 0.0033 spikes/s, and `3.3e-3 spikes/s` on a legend is
 * a maths notation in front of a biologist. `0.003` says the same thing and needs no decoding.
 */
export function formatRate(rateHz: number): string {
  if (rateHz === 0) return '0 spikes/s';
  if (rateHz < 0.001) return '<0.001 spikes/s';
  if (rateHz < 0.1) return `${rateHz.toFixed(3)} spikes/s`;
  if (rateHz < 1) return `${rateHz.toFixed(2)} spikes/s`;
  if (rateHz < 10) return `${rateHz.toFixed(1)} spikes/s`;
  return `${Math.round(rateHz)} spikes/s`;
}
