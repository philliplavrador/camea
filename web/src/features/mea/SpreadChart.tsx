// ─────────────────────────────────────────────────────────────────────────────────────────────
// THE SPREAD — how many pads sit in each stretch of the legend, as a small bar chart beside it.
//
// ⭐ **HE SAID YES TO THIS ON 2026-08-15**, re-asked with `docs/MAXWELL.md` §7.2's evidence after
// declining it once: the colour answers *where*, the distribution answers *how much, really*.
// The bands are the legend's own values (`spread.ts`), so the two cannot disagree.
//
// ⭐ Clicking a bar highlights that band's pads on the map — the others dim — and clicking it
// again clears. One band at a time: the question this answers is "where are THESE", and two
// highlights at once answer nothing.
//
// 🔴 The no-spike bar is drawn HOLLOW, like the ring it stands for, and speaks only the approved
// sentence's vocabulary. ⭐ And MAXWELL §7.3: a silent count may not appear without the window it
// was counted over — the recording's length is in this bar's own label.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { SILENT_MEANING, formatRate } from './activityScale';
import { formatSeconds } from './format';
import type { SpreadBand } from './spread';
import styles from './ChipMap.module.css';

/** The tallest bar, CSS px. A display choice. */
const BAR_MAX_PX = 52;

export interface SpreadChartProps {
  bands: readonly SpreadBand[];
  /** Index of the highlighted band, or null. */
  selected: number | null;
  onToggle: (index: number) => void;
  /** The tally's own length, seconds — MAXWELL §7.3 says it sits beside the silent count. */
  durationS: number;
  /** ⭐ True when the tally covers a stretch of the trace, not the whole recording ("colours
   *  follow the view"). Same source as the legend's flag — the activity payload's own `t0_s` —
   *  so the two blocks re-band and re-word together and can never disagree. */
  windowed: boolean;
}

export function SpreadChart({ bands, selected, onToggle, durationS, windowed }: SpreadChartProps) {
  if (bands.every((b) => b.count === 0)) return null;
  const tallest = Math.max(...bands.map((b) => b.count));
  const inThis =
    durationS > 0
      ? windowed
        ? ` in the ${formatSeconds(durationS)} stretch shown`
        : ` in this ${formatSeconds(durationS)} recording`
      : '';

  return (
    <div className={styles.spread} data-testid="mea-chip-spread">
      <h3 className={styles.busiestTitle}>Pads per band</h3>
      <div className={styles.spreadBars} role="group" aria-label="Pads per firing-rate band">
        {bands.map((b, i) => {
          const words = b.silent
            ? `${b.count.toLocaleString()} pads — ${SILENT_MEANING}${inThis}`
            : `${b.count.toLocaleString()} pads at ${formatRate(b.lo)} to ${formatRate(b.hi)}`;
          return (
            <button
              key={i}
              type="button"
              className={styles.spreadCol}
              data-testid="mea-chip-spread-bar"
              data-band={b.silent ? 'silent' : i - 1}
              data-count={b.count}
              aria-pressed={selected === i}
              aria-label={`${words}. Highlight them on the map.`}
              title={`${words} — click to highlight them on the map`}
              // An empty band has nothing to highlight; off, never hidden, so the chart's shape
              // stays comparable between recordings.
              disabled={b.count === 0}
              onClick={() => onToggle(i)}
            >
              <span className={styles.spreadCount}>{b.count.toLocaleString()}</span>
              <span
                className={b.silent ? styles.spreadBarSilent : styles.spreadBar}
                style={{
                  height: b.count === 0 ? 1 : Math.max(3, (b.count / tallest) * BAR_MAX_PX),
                  background: b.silent ? undefined : b.colour,
                }}
              />
              {/* Only the silent bar carries words of its own — the live bars' colours already
                  point into the legend right beside this chart. */}
              <span className={styles.spreadLabel}>{b.silent ? 'no spikes' : ' '}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
