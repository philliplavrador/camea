// THE ORIENTATION PANEL — which way is the chip sitting in this mosaic?
//
// The pairing this whole app exists to produce needs one more fact that no file records: which
// corner of the mosaic the chip's own origin landed in. Four seatings are possible; pick wrong and
// every neuron is paired with the wrong electrode, invisibly.
//
// This panel runs the test and shows all four rows. What it must never do is make the answer look
// more settled than it is, so three rules are baked in:
//
//   1. 🔴 **The caveat is always on screen, verbatim, never behind a `?`** (issue 003). The clock
//      alignment leans on the 2P lamp marks and those did not survive checking against the calcium
//      video. He asked for the test built anyway; he did not ask to be lied to about it.
//   2. ⭐ **"Cannot tell" is a real outcome and gets said plainly.** When the seatings are not
//      separated the server sends no winner at all (`decisive: false`, `best: null`), so there is
//      nothing here to apply. Measured: P003693's four seatings land within 0.004 of each other.
//   3. ⭐ **"Untestable" is not a bad score.** A seating with no recorded electrode under the field
//      was never tested; showing it as a low number would rank it against ones that were.
//
// The one genuinely strong result this test can give is `decided_by: 'coverage'` — only one seating
// puts any recorded electrode under the field. That is geometry, and it depends on neither the
// clock alignment nor the raw stream decoding, i.e. on neither of the things issue 003 doubts.

import { useCallback, useState } from 'react';
import { attachMea, testMeaOrientation, useJob } from '../../api';
import type { MeaOrientation, OrientationTestResult } from '../../api';
import { Button, LiveWarning, Panel } from '../../design';
import styles from './MeaOrientationPanel.module.css';

export interface MeaOrientationPanelProps {
  analysisId: string;
  orientation: MeaOrientation;
  /** False when the project has no located region — the test has nothing to score against. */
  hasRegion: boolean;
  onConfirmed: () => void;
}

const seatingName = (flipX: boolean, flipY: boolean): string =>
  !flipX && !flipY ? 'as-is' : `flipped ${[flipX && 'top–bottom', flipY && 'left–right']
    .filter(Boolean)
    .join(' and ')}`;

export function MeaOrientationPanel({
  analysisId,
  orientation,
  hasRegion,
  onConfirmed,
}: MeaOrientationPanelProps): React.JSX.Element {
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);
  const job = useJob(jobId);
  const running = jobId != null && !job.isTerminal;

  const result =
    job.job?.result && job.job.result.kind === 'mea_orientation'
      ? (job.job.result as OrientationTestResult)
      : null;

  const start = useCallback(async () => {
    setError(null);
    try {
      const ref = await testMeaOrientation(analysisId);
      setJobId(ref.job_id);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [analysisId]);

  const apply = useCallback(
    async (o: MeaOrientation) => {
      setApplying(true);
      setError(null);
      try {
        // ⭐ Confirmation is a HUMAN act. The job never sets this; pressing this button is what
        // turns a proposal into the seating the pairing is built on.
        await attachMea(analysisId, {
          confirm: true,
          orientation: { ...o, confirmed: true, source: 'confirmed by you after the seating test' },
        });
        onConfirmed();
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setApplying(false);
      }
    },
    [analysisId, onConfirmed],
  );

  return (
    <Panel
      title="Chip orientation"
      help={
        'Which way round the chip sits in this mosaic. Nothing in the recording files records ' +
        'it, so it has to be worked out or told.\n' +
        '\n' +
        'The test asks, for each of the four possibilities: do the electrodes it puts under your ' +
        'located recording actually fire when that field lights up?'
      }
    >
      <div className={styles.body}>
        {orientation.confirmed ? (
          <p className={styles.settled} data-testid="mea-orientation-settled">
            Settled: <b>{seatingName(orientation.flip_x, orientation.flip_y)}</b>
            {orientation.source ? <span className={styles.sub}> — {orientation.source}</span> : null}
          </p>
        ) : (
          <LiveWarning variant="warn">
            Not established yet, so every electrode identity is provisional.
          </LiveWarning>
        )}

        {error && <LiveWarning variant="loud">{error}</LiveWarning>}

        {!hasRegion ? (
          <p className={styles.sub}>
            The test needs a located recording to score against — place one on the Regions step
            first.
          </p>
        ) : (
          <Button
            size="sm"
            variant={orientation.confirmed ? 'ghost' : 'primary'}
            disabled={running}
            onClick={() => void start()}
            data-testid="mea-test-orientation"
          >
            {running ? (job.job?.message ?? 'Testing…') : 'Test the orientation'}
          </Button>
        )}

        {result && (
          <>
            {/* 🔴 Rule 1 — before the numbers, so nobody reads the table first. */}
            <div data-testid="mea-orientation-caveat">
              <LiveWarning variant="warn">{result.caveat}</LiveWarning>
            </div>

            <table className={styles.table} data-testid="mea-orientation-scores">
              <thead>
                <tr>
                  <th>Seating</th>
                  <th>Electrodes under it</th>
                  <th>Spikes</th>
                  <th>Match</th>
                </tr>
              </thead>
              <tbody>
                {(result.scores ?? []).map((s) => {
                  const isBest =
                    result.best != null &&
                    result.best.flip_x === s.flip_x &&
                    result.best.flip_y === s.flip_y;
                  return (
                    <tr key={`${String(s.flip_x)}-${String(s.flip_y)}`} className={isBest ? styles.best : undefined}>
                      <td>{seatingName(s.flip_x, s.flip_y)}</td>
                      <td className={styles.num}>
                        {s.n_recorded} <span className={styles.sub}>of {s.n_region}</span>
                      </td>
                      <td className={styles.num}>{s.n_spikes.toLocaleString()}</td>
                      {/* Rule 3 — untested is its own word, not a number. */}
                      <td className={styles.num}>
                        {s.correlation == null ? (
                          <span className={styles.sub}>none under it</span>
                        ) : (
                          s.correlation.toFixed(3)
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            {/* Rule 2 — say it, and offer nothing to press. */}
            {!result.decisive || !result.best ? (
              <p className={styles.sub} data-testid="mea-orientation-undecided">
                <b>Cannot tell.</b> The four seatings scored too alike to choose between
                {result.margin != null ? ` (best beats the next by ${result.margin.toFixed(3)})` : ''}
                . Nothing has been applied.
              </p>
            ) : (
              <>
                <p className={styles.sub}>
                  {result.decided_by === 'coverage' ? (
                    <>
                      Only <b>{seatingName(result.best.flip_x, result.best.flip_y)}</b> puts any
                      recorded electrode under your recording — the other three put none. That is
                      geometry, so it does not depend on the timing or on the waveform decoding.
                    </>
                  ) : (
                    <>
                      <b>{seatingName(result.best.flip_x, result.best.flip_y)}</b> matched best, by{' '}
                      {result.margin?.toFixed(3) ?? '—'}.
                    </>
                  )}
                </p>
                <Button
                  size="sm"
                  variant="primary"
                  disabled={applying}
                  onClick={() => void apply(result.best as MeaOrientation)}
                  data-testid="mea-orientation-apply"
                >
                  {applying ? 'Saving…' : 'Use this seating'}
                </Button>
              </>
            )}
          </>
        )}
      </div>
    </Panel>
  );
}
