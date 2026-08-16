import type { ReactNode } from 'react';
import { cx } from '../cx';
import { Button } from './Button';
import styles from './Progress.module.css';

/**
 * ⏱️ **THE ONE PROGRESS BAR (BEHAVIOUR R48).**
 *
 * *"everywhere where there's gonna be like some sort of loading or waiting period, make sure
 * there's like some sort of progress bar with an ETA, like everywhere in the app."* — him,
 * 2026-08-16.
 *
 * Every wait longer than `WAIT_GRACE_MS` renders one of these (R48.1). It is the ONLY progress bar
 * in the app (R48.2): five hand-rolled copies across four stylesheets, three heights and two
 * animation properties were deleted to make that true, and one of their own CSS comments admitted
 * the drift before it was.
 *
 * **The time slot is never empty (R48.4).** Pass `etaText={null}` while the job has not yet said
 * anything and this renders *"working out how long this will take…"* — not an empty `<span>`, which
 * is the exact bug the ruling was written against (four screens had one).
 *
 * **The bar is honest about what it does not know (R48.9).** `pct={null}` gives the travelling
 * sliver, not a bar parked at 2 % — reserved for the four accepted cases (an unbounded directory
 * walk, an `rmtree`, a human, a genuinely silent phase). Everything else owes a real number.
 */
export interface ProgressProps {
  /**
   * ⭐ **What is being waited for, in his words** (R48.6) — *"reading the recording end to end"*,
   * not `mea_envelope`. On a job this is `Job.label` / `Job.said_as`; the backend carries it so a
   * refusal elsewhere can name the same thing the same way.
   */
  label: ReactNode;
  /**
   * 0–100, OVERALL across the whole job (R48.5). `null` = indeterminate: the travelling sliver, no
   * percentage. A phase-local number that snaps back to zero at each boundary is a bug — weight the
   * phases first (`pipeline._SPAN` is the worked example).
   */
  pct?: number | null;
  /**
   * The countdown, already formatted by `formatEta` and already ticking on the client's 1 Hz clock
   * (R8 — the ticking is the caller's, via `useJob`; this component only renders what it is given).
   * `null` renders the "working out…" sentence instead.
   */
  etaText?: string | null;
  /**
   * How long it has been running, formatted. Shown when there is no ETA yet, so a silent phase still
   * has a number that moves (R48.4 — this is what satisfies the rule without the forbidden
   * server-side heartbeat, R48b).
   */
  elapsedText?: string | null;
  /** The job's phase, lowercase, e.g. `register` — with `n/total` already appended if it has one. */
  phase?: string | null;
  /** The job's current narration line, e.g. `registering frames: 210 / 611`. */
  message?: string | null;
  /**
   * ⭐ Wired to a real cancel (R48.7). Omit ONLY when the work genuinely cannot be stopped — and
   * then pass `unstoppableWhy`, because a missing button with no explanation reads as an oversight.
   * ⛔ Never pass a no-op here to make the layout consistent.
   */
  onStop?: () => void;
  /** Label for the stop control. Defaults to `Stop`. */
  stopLabel?: string;
  /**
   * Why this particular wait has no Stop — *"a delete cannot be stopped once it starts"*. Rendered
   * where the button would be. Ignored when `onStop` is given.
   */
  unstoppableWhy?: string;
  /** The job's last few narration lines (R8.7 shows 8 on the build screen). Omit for a quiet bar. */
  logTail?: string[];
  /** One line, thinner bar — for a table row or a shelf item rather than a panel. */
  compact?: boolean;
  /** Test hook. The bar itself gets `${testId}-bar`, the time `${testId}-eta`. */
  'data-testid'?: string;
  className?: string;
}

/** R48.4 — the sentence that occupies the time slot before there is an estimate. */
export const ESTIMATING_TEXT = 'working out how long this will take…';

export function Progress({
  label,
  pct = null,
  etaText = null,
  elapsedText = null,
  phase = null,
  message = null,
  onStop,
  stopLabel = 'Stop',
  unstoppableWhy,
  logTail,
  compact = false,
  'data-testid': testId,
  className,
}: ProgressProps) {
  const determinate = pct != null && Number.isFinite(pct);
  // A determinate bar shows a 2 % sliver at 0 so it reads as "started", never as "broken". An
  // INDETERMINATE bar must not do this — a bar parked at 2 % is exactly what R48.9 forbids, which is
  // why the floor lives here and not in the CSS.
  const width = determinate ? Math.max(2, Math.min(100, pct as number)) : undefined;

  return (
    <div
      className={cx(styles.root, compact && styles.compact, !determinate && styles.indeterminate, className)}
      data-testid={testId}
    >
      <div
        className={styles.well}
        role="progressbar"
        aria-label={typeof label === 'string' ? label : undefined}
        aria-busy={true}
        // R48.2 — determinate bars carry their value; an indeterminate one carries none at all,
        // which is how a screen reader is told "running, length unknown".
        aria-valuenow={determinate ? Math.round(pct as number) : undefined}
        aria-valuemin={determinate ? 0 : undefined}
        aria-valuemax={determinate ? 100 : undefined}
      >
        <div
          className={styles.bar}
          data-testid={testId ? `${testId}-bar` : undefined}
          style={determinate ? { width: `${width}%` } : undefined}
        />
      </div>

      <div className={styles.row}>
        <span className={styles.label}>{label}</span>

        {/* The readouts travel as ONE group so they wrap together instead of overlapping a label
            that has taken a second line. See the `.row` comment — this was a real overlap. */}
        <span className={styles.meta}>
          {phase ? <span className={styles.phase}>{phase}</span> : null}

          {determinate ? (
            <span className={styles.pct} data-testid={testId ? `${testId}-pct` : undefined}>
              {Math.round(pct as number)}%
            </span>
          ) : null}

          {/* R48.4 — THE SLOT IS NEVER EMPTY. Either a time, or the sentence + the elapsed clock. */}
          {etaText ? (
            <span className={styles.eta} data-testid={testId ? `${testId}-eta` : undefined}>
              {etaText} left
            </span>
          ) : (
            <span className={styles.estimating} data-testid={testId ? `${testId}-eta` : undefined}>
              {ESTIMATING_TEXT}
              {elapsedText ? ` · ${elapsedText} so far` : ''}
            </span>
          )}

          {onStop ? (
            <Button
              size="sm"
              variant="ghost"
              onClick={onStop}
              data-testid={testId ? `${testId}-stop` : undefined}
            >
              {stopLabel}
            </Button>
          ) : unstoppableWhy ? (
            // R48.7 — say why, rather than render a button that does nothing.
            <span className={styles.unstoppable}>{unstoppableWhy}</span>
          ) : null}
        </span>
      </div>

      {message ? <div className={styles.msg}>{message}</div> : null}

      {logTail && logTail.length ? (
        <pre className={styles.log} data-testid={testId ? `${testId}-log` : undefined}>
          {logTail.join('\n')}
        </pre>
      ) : null}
    </div>
  );
}
