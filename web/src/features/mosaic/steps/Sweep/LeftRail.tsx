// The sweep's LEFT rail (BEHAVIOUR §2 Sweep): the Queue (every trial as a state-coloured chip), the
// Rescue list (every unplaced tile), the Opacity slider (R13), the Tone window (R18 — display only), and
// the keyboard cheat-sheet. All of it is chrome; the canvas is the hero, so this recedes.

import { memo, useMemo, useState } from 'react';
import { useSweepStore, prevTrial } from '../../store';
import type { TileState } from '../../store';
import { Panel, Toggle } from '../../../../design';
import styles from './LeftRail.module.css';

/** Optional global tone controls, owned by the session (display only — R18). */
export interface ToneControl {
  lo: number;
  hi: number;
  auto: boolean;
  apply: (lo: number, hi: number) => void;
  setAuto: (auto: boolean) => void;
}

export interface LeftRailProps {
  tone?: ToneControl;
  onGoToTrial: (trial: number) => void;
}

const QueueChip = memo(function QueueChip({
  trial,
  state,
  cursor,
  stale,
  onClick,
}: {
  trial: number;
  state: TileState;
  cursor: boolean;
  stale: boolean;
  onClick: (t: number) => void;
}) {
  return (
    <button
      type="button"
      className={styles.chip}
      data-testid="queue-chip"
      data-trial={trial}
      data-state={state}
      data-cursor={cursor ? 'true' : undefined}
      data-stale={stale ? 'true' : undefined}
      onClick={() => onClick(trial)}
      title={`trial ${trial} · ${state}`}
    >
      {trial}
    </button>
  );
});

export function LeftRail({ tone, onGoToTrial }: LeftRailProps) {
  const doc = useSweepStore((s) => s.doc);
  const order = useSweepStore((s) => s.order);
  const cursor = useSweepStore((s) => s.cursor);
  const floatAlpha = useSweepStore((s) => s.floatAlpha);

  const [outstandingOnly, setOutstandingOnly] = useState(false);

  const chips = useMemo(() => {
    const tiles = doc?.tiles ?? {};
    return order.map((t) => {
      const tl = tiles[String(t)];
      return {
        trial: t,
        state: (tl?.state ?? 'unplaced') as TileState,
        stale: !!tl?.stale,
      };
    });
  }, [order, doc]);

  const shown = outstandingOnly
    ? chips.filter((ch) => ch.state === 'unverified' || ch.state === 'unplaced')
    : chips;

  const unplaced = chips.filter((ch) => ch.state === 'unplaced');

  const [lo, setLo] = useState(tone?.lo ?? 0);
  const [hi, setHi] = useState(tone?.hi ?? 255);

  function back(): void {
    if (!doc || cursor == null) return;
    const p = prevTrial(order, doc.tiles, cursor);
    if (p != null) onGoToTrial(p);
  }

  return (
    <aside className={styles.rail} data-testid="left-rail">
      <Panel
        title="Queue"
        className={styles.panel}
        actions={
          <span className={styles.count} data-testid="queue-count">
            {shown.length}/{order.length}
          </span>
        }
      >
        <div className={styles.queueHead}>
          <button type="button" className={styles.smallBtn} data-testid="queue-back" onClick={back}>
            ◀ back
          </button>
          <Toggle checked={outstandingOnly} onChange={setOutstandingOnly}>
            <span data-testid="queue-filter-outstanding">outstanding only</span>
          </Toggle>
        </div>
        <div className={styles.queue} data-testid="queue">
          {shown.map((ch) => (
            <QueueChip
              key={ch.trial}
              trial={ch.trial}
              state={ch.state}
              cursor={ch.trial === cursor}
              stale={ch.stale}
              onClick={onGoToTrial}
            />
          ))}
        </div>
      </Panel>

      <Panel
        title="Rescue"
        help="Every tile with no position yet. Rescue places it against the anchor composite (or the solver's answer). A rescue is a placement, never a judgement."
        className={styles.panel}
      >
        <div className={styles.rescue} data-testid="rescue">
          {unplaced.length === 0 && <span className={styles.empty}>Nothing to rescue.</span>}
          {unplaced.map((ch) => (
            <div
              key={ch.trial}
              className={styles.rescueRow}
              data-testid="rescue-item"
              data-trial={ch.trial}
            >
              <span className={styles.rescueTrial}>#{ch.trial}</span>
              <button
                type="button"
                className={styles.smallBtn}
                data-testid="rescue-btn"
                onClick={() => void useSweepStore.getState().rescue(ch.trial)}
              >
                Rescue
              </button>
            </div>
          ))}
        </div>
      </Panel>

      <Panel
        title="Opacity"
        help="The floating tile's opacity while you line it up. Display only — it never touches the data, and Difference mode ignores it."
        className={styles.panel}
      >
        <div className={styles.sliderRow}>
          <input
            type="range"
            min={15}
            max={100}
            step={5}
            value={Math.round(floatAlpha * 100)}
            data-testid="opacity-slider"
            onChange={(e) => useSweepStore.getState().setFloatAlpha(Number(e.target.value) / 100)}
            className={styles.slider}
          />
          <span className={styles.sliderVal}>{Math.round(floatAlpha * 100)}%</span>
        </div>
      </Panel>

      <Panel
        title="Tone"
        help="The global display window. It never touches the matcher (which sees band-passed pixels) and never touches the exported TIFF. Global, never per-tile."
        className={styles.panel}
      >
        <div className={styles.tone}>
          <label className={styles.toneField}>
            lo
            <input
              type="number"
              className={styles.toneInput}
              data-testid="tone-lo"
              value={lo}
              onChange={(e) => setLo(Number(e.target.value))}
            />
          </label>
          <label className={styles.toneField}>
            hi
            <input
              type="number"
              className={styles.toneInput}
              data-testid="tone-hi"
              value={hi}
              onChange={(e) => setHi(Number(e.target.value))}
            />
          </label>
          <button
            type="button"
            className={styles.smallBtn}
            data-testid="tone-apply"
            onClick={() => tone?.apply(lo, hi)}
          >
            Apply
          </button>
          <Toggle checked={tone?.auto ?? true} onChange={(v) => tone?.setAuto(v)}>
            <span data-testid="tone-auto">auto</span>
          </Toggle>
        </div>
      </Panel>

      {/* Keys — ONE quiet, off-stage affordance (docs/DESIGN_BRIEF §0/§4). The full map lives behind the
          header `?`; the action controls on the canvas already show every keycap, so a second on-rail
          legend would be the same chrome twice. Every key stays reachable — this removes duplication,
          not capability. */}
      <Panel
        title="Keys"
        help="Space advances · A anchors (toggle) · E excludes · R replays the fade · D Difference · V alternatives · S snaps · 1–9 jump to the Nth peak · arrows nudge (Shift ×10) · F fit · 0 is 1:1 · Ctrl+Z/Y undo/redo · Ctrl+S save."
        className={styles.panel}
      >
        <span className={styles.keysHint} data-testid="keys-cheatsheet">
          Keyboard-first — every action is a key. Hover the ? for the full map.
        </span>
      </Panel>
    </aside>
  );
}
