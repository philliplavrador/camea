// ─────────────────────────────────────────────────────────────────────────────────────────────
// THE BUSIEST PADS — a short ranked list beside the legend: the top handful of pads by spikes
// per second, each a button that selects the pad and takes the view to it.
//
// ⭐ **RANKED FROM THE SAME JOINED PADS THE MAP DRAWS**, so the list and the picture cannot
// disagree — `ChipMap` hands its own array down and this component computes nothing new, it only
// orders what is already on screen.
//
// ⛔ **"TOP 8" IS A DISPLAY CHOICE, NEVER A FACT ABOUT A CHIP** (I1). It is how many rows sit
// comfortably beside the legend — the same standing as `LEGEND_STOPS`. Nothing here knows how
// busy a pad "should" be.
//
// ⭐ Clicking a row goes through the SAME `onPick` path a canvas click ends in, so the selection
// ring, the live-region announcement and the trace panel all follow exactly as if he had clicked
// the dot itself — this list is a shortcut to a pad, not a second selection mechanism.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { formatRate } from './activityScale';
import styles from './ChipMap.module.css';

/** How many rows the list shows at most. A display choice — see the header. */
const TOP_N = 8;

/** The slice of a pad this list needs. `ChipMap`'s own pads satisfy it structurally. */
export interface BusyPad {
  channel: number;
  electrode: number;
  rateHz: number;
}

export interface BusiestPadsProps {
  pads: readonly BusyPad[];
  /** The channel currently being read, or null — the matching row shows pressed. */
  selected: number | null;
  /** Select this channel and fly the view to it. `ChipMap` owns both halves. */
  onPick: (channel: number) => void;
}

export function BusiestPads({ pads, selected, onPick }: BusiestPadsProps) {
  // Only pads that fired can be "busiest" — a list padded out with no-spike rows would rank
  // silence, which is not a rate. Fewer than TOP_N live pads → a shorter list; none → no list.
  const top = pads
    .filter((p) => p.rateHz > 0)
    .sort((a, b) => b.rateHz - a.rateHz)
    .slice(0, TOP_N);
  if (top.length === 0) return null;

  return (
    <div className={styles.busiest} data-testid="mea-chip-busiest">
      <h3 className={styles.busiestTitle}>Busiest pads</h3>
      <ol className={styles.busiestList}>
        {top.map((p, i) => (
          <li key={p.channel}>
            <button
              type="button"
              className={styles.busiestRow}
              data-testid="mea-chip-busiest-pad"
              data-channel={p.channel}
              aria-pressed={p.channel === selected}
              title="Select this pad and centre the view on it"
              onClick={() => onPick(p.channel)}
            >
              <span className={styles.busiestRank} aria-hidden="true">
                {i + 1}
              </span>
              <span className={styles.busiestName}>electrode {p.electrode}</span>
              <span className={styles.busiestRate}>{formatRate(p.rateHz)}</span>
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}
