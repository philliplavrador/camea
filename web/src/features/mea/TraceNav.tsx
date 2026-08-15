// ─────────────────────────────────────────────────────────────────────────────────────────────
// THE NAVIGATION ROW — Home / ← Back / Forward →, and the readout, where the slider used to be.
//
// ⭐ **HIS REQUEST, IN HIS WORDS** (2026-08-15): *"I don't like the slider bar … I have the whole
// trace, and then I can make a rectangle around the area I want to zoom in, then I can go back."*
// The going back is the feature, so it is three visible buttons rather than a gesture — a hidden
// gesture is not something he can see he has.
//
// ⚠️ **THE BUTTONS ARE DISABLED, NOT HIDDEN, WHEN THERE IS NOWHERE TO GO.** Controls that appear
// and vanish make a panel jump under the pointer; `canBack`/`canForward` are Qt's exact rule.
//
// The readout is the same mono/tabular grammar as the rest of the screen (R3: numbers, not prose),
// and it states the **width** beside the spike count deliberately — a count without the window it
// was counted over is not a number anybody can use (MAXWELL §7.3).
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { Button } from '../../design';
import { readout } from './readout';
import styles from './MeaTrace.module.css';

export interface TraceNavProps {
  t0: number;
  t1: number;
  duration: number;
  nSpikes: number;
  canBack: boolean;
  canForward: boolean;
  onHome: () => void;
  onBack: () => void;
  onForward: () => void;
}

export function TraceNav({
  t0,
  t1,
  duration,
  nSpikes,
  canBack,
  canForward,
  onHome,
  onBack,
  onForward,
}: TraceNavProps): React.JSX.Element {
  return (
    <div className={styles.controls} data-testid="mea-trace-nav">
      <Button size="sm" variant="ghost" onClick={onHome} data-testid="mea-trace-home">
        Whole recording
      </Button>
      <Button
        size="sm"
        variant="ghost"
        onClick={onBack}
        disabled={!canBack}
        data-testid="mea-trace-back"
      >
        ← Back
      </Button>
      <span className={styles.pos} data-testid="mea-trace-pos">
        {readout(t0, t1, duration, nSpikes)}
      </span>
      <Button
        size="sm"
        variant="ghost"
        onClick={onForward}
        disabled={!canForward}
        data-testid="mea-trace-forward"
      >
        Forward →
      </Button>
    </div>
  );
}
