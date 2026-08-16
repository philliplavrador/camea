import { Button, cx } from '../design';
import { useRunningJobs, useStopJob } from '../api/jobs';
import styles from './RunningStrip.module.css';

/**
 * ⏱️ **ANYTHING RUNNING, VISIBLE FROM ANYWHERE (BEHAVIOUR R48.8).**
 *
 * He asked for the bar both *"where you clicked"* and in a strip he cannot walk away from: start a
 * one-minute recording read on the trace panel, go back to the shelf, and the read is still on
 * screen with its time on it.
 *
 * ⛔ **It renders NOTHING when nothing is running.** The strip must not become permanent chrome —
 * DESIGN_BRIEF §1.2, the app is mostly picture, and a persistent empty band is exactly the kind of
 * furniture this design brief spends its budget avoiding.
 *
 * ⛔ **It does not compute anything.** Every number here comes off the same job the inline bar is
 * reading (R48.8) — two surfaces, one estimate. If the strip ever disagrees with the panel, the
 * disagreement is the bug, not the rounding.
 *
 * ⚠️ It deliberately does NOT use `<Progress>`. That primitive is a block that owns its own line,
 * with a label, a message and a log tail; this is a 30 px row that has to stay out of the way. They
 * share the tokens and the R8/R48 arithmetic, which is where the duplication that matters would be.
 */
export function RunningStrip() {
  const jobs = useRunningJobs();
  const stop = useStopJob();

  // R48.8 — nothing running, nothing rendered. No band, no reserved height, no layout shift beyond
  // the one the appearing strip itself causes.
  if (jobs.length === 0) return null;

  return (
    <div className={styles.strip} data-testid="running-strip" role="status" aria-live="polite">
      {jobs.map((j) => {
        const determinate = j.pct != null && Number.isFinite(j.pct) && j.pct > 0;
        return (
          <div
            key={j.job_id}
            className={cx(styles.row, !determinate && styles.indeterminate)}
            data-testid={`running-${j.job_id}`}
          >
            <div
              className={styles.well}
              role="progressbar"
              aria-label={j.said_as}
              aria-busy={true}
              aria-valuenow={determinate ? Math.round(j.pct as number) : undefined}
              aria-valuemin={determinate ? 0 : undefined}
              aria-valuemax={determinate ? 100 : undefined}
            >
              <div
                className={styles.bar}
                style={determinate ? { width: `${Math.max(2, Math.min(100, j.pct as number))}%` } : undefined}
              />
            </div>

            {/* R48.6 — the label is the backend's own sentence, so the strip and any busy refusal
                elsewhere name the same work with the same words. */}
            <span className={styles.said} data-testid="running-said">
              {j.said_as}
              {determinate ? ` · ${Math.round(j.pct as number)}%` : ''}
            </span>

            {/* R48.4 — never an empty slot. */}
            {j.etaText ? (
              <span className={styles.time} data-testid="running-eta">
                {j.etaText} left
              </span>
            ) : (
              <span className={styles.estimating} data-testid="running-eta">
                working out how long{j.elapsedText ? ` · ${j.elapsedText}` : ''}
              </span>
            )}

            {/* R48.7 — only where stopping is real. `cancellable` is the server's own answer. */}
            {j.cancellable ? (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => void stop(j.job_id)}
                data-testid="running-stop"
              >
                Stop
              </Button>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
