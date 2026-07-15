// The instrument's footer readout (BEHAVIOUR §3 structure, R14, R19, R20). It reads the tile under
// judgement: `trial n` (an integer, never "—" — R14) · a state badge · `pass n` (+ blank) ·
// `top-left (x, y)` (TOP-LEFT corners — R19) · a hint · the live `ms/frame · fps` (must read ~6 ms — R20).

import { useSweepStore } from '../../store';
import { Badge } from '../../../../design';
import { fmtXY } from './format';
import styles from './StatusRow.module.css';

export interface StatusRowProps {
  msPerFrame: number;
  fps: number;
}

export function StatusRow({ msPerFrame, fps }: StatusRowProps) {
  const doc = useSweepStore((s) => s.doc);
  const cursor = useSweepStore((s) => s.cursor);
  const tile = cursor != null && doc ? doc.tiles[String(cursor)] : undefined;

  const state = tile?.state ?? 'unplaced';
  const hint = tile?.diverted
    ? 'D to check · A to accept · V for the matcher'
    : tile?.blank
      ? 'hand-place or exclude — the matcher refuses a blank'
      : 'Space next · A anchor · E exclude';

  const hot = msPerFrame > 16;

  return (
    <div className={styles.bar} data-testid="status-bar" role="status">
      <span className={styles.item} data-testid="status-trial">
        trial {cursor ?? '—'}
      </span>
      <span className={styles.item} data-testid="status-state">
        <Badge state={tile?.blank ? 'blank' : state}>{tile?.blank ? 'blank' : state}</Badge>
      </span>
      <span className={styles.item} data-testid="status-pass">
        pass {tile?.pass ?? '—'}
        {tile?.blank ? ' · blank (measured)' : ''}
      </span>
      <span className={styles.item} data-testid="status-topleft">
        top-left {fmtXY(tile?.x, tile?.y)}
      </span>
      <span className={styles.hint} data-testid="status-hint">
        {hint}
      </span>
      <span
        className={styles.perf}
        data-testid="status-msframe"
        data-hot={hot ? 'true' : undefined}
      >
        {msPerFrame.toFixed(1)} ms/frame
      </span>
      <span className={styles.perf} data-testid="status-fps">
        {Math.round(fps)} fps
      </span>
    </div>
  );
}
