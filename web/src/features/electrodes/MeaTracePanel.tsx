// THE MEA TRACE PANEL — click an electrode, see what it recorded.
//
// This is where the two halves of the ground-truth dataset first meet on screen: the mosaic says
// WHERE electrode 21-5 is, this says WHAT it measured. Everything else in the app exists to make
// that join trustworthy, so this panel's job is as much about what it REFUSES to imply as what it
// draws. Three live warnings, none of them dismissible, none behind a `?`:
//
//   1. ⭐ **"never recorded" is the ordinary answer.** ~1k of the chip's 26,400 pads are routed at
//      acquisition, so most clicks land on an electrode with no trace. That must read as a fact
//      about the experiment, not as a failure or an empty chart.
//   2. ⚠️ **the waveform may not have decoded.** MaxWell compresses the raw stream with a
//      proprietary filter; the publicly available decoder does not reconstruct this project's
//      files (measured: 98% of samples come back as one fill value). `health.flat` says so, and a
//      railed window looks EXACTLY like a genuinely silent electrode — which is why this is stated
//      and the trace is dimmed rather than quietly drawn.
//   3. ⚠️ **the chip's seating is not established.** Which corner of the mosaic the chip's own
//      origin landed in is a fact about the microscope that no file records. Until it is
//      confirmed, the electrode's identity is PROVISIONAL and the panel says so.
//
// The spike ticks are the one thing here that is unconditionally trustworthy: MaxWell's on-chip
// detector wrote them at acquisition and they need no proprietary decoder. When the waveform is
// suspect they are still exactly right, which is why they are drawn even then.

import { useCallback, useEffect, useState } from 'react';
import { getElectrodeTrace } from '../../api';
import type { ElectrodeTracePayload, MeaRecordingSummary } from '../../api';
import { Button, LiveWarning, Panel } from '../../design';
import { TraceChart } from './TraceChart';
import styles from './MeaTracePanel.module.css';

/** How much of the recording one view shows. Kept small: the window is fetched, not cached whole. */
const WINDOW_S = 1.0;

export interface MeaTracePanelProps {
  analysisId: string;
  /** The clicked electrode's Camea grid id (`"col-row"`), or null when nothing is selected. */
  electrode: string | null;
  recordings: MeaRecordingSummary[];
}

export function MeaTracePanel({
  analysisId,
  electrode,
  recordings,
}: MeaTracePanelProps): React.JSX.Element | null {
  const [runId, setRunId] = useState<string | null>(null);
  const [t0, setT0] = useState(0);
  const [data, setData] = useState<ElectrodeTracePayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // ⭐ Which (electrode, run) we have already jumped to the activity for. A 300 s recording opened
  // at t=0 usually shows a dead window, and stepping a second at a time would take 200 clicks to
  // reach the spikes — so the FIRST view of an electrode lands where it actually fired. Recorded
  // per selection so the jump happens once and never fights the user's own scrubbing.
  const [jumped, setJumped] = useState<string | null>(null);

  const active = runId ?? recordings[0]?.run_id ?? null;
  const current = recordings.find((r) => r.run_id === active) ?? recordings[0];
  const duration = current?.duration_s ?? 0;

  useEffect(() => {
    if (!electrode || !active) {
      setData(null);
      return;
    }
    let cancelled = false;
    setBusy(true);
    setError(null);
    void getElectrodeTrace(analysisId, electrode, { runId: active, t0, t1: t0 + WINDOW_S })
      .then((d) => {
        if (cancelled) return;
        setData(d);
        const key = `${electrode}@${active}`;
        const first = d.first_spike_s;
        if (jumped !== key && first != null && (d.spikes?.length ?? 0) === 0) {
          setJumped(key);
          setT0(Math.max(0, Math.floor(first * 10) / 10));
        } else if (jumped !== key) {
          setJumped(key);
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setBusy(false);
      });
    return () => {
      cancelled = true;
    };
  }, [analysisId, electrode, active, t0, jumped]);

  // A new selection re-arms the jump: each electrode gets shown where IT fired.
  useEffect(() => {
    setT0(0);
    setJumped(null);
  }, [electrode, active]);

  const step = useCallback(
    (dir: number) => {
      setT0((v) => Math.max(0, Math.min(Math.max(0, duration - WINDOW_S), v + dir * WINDOW_S)));
    },
    [duration],
  );

  if (recordings.length === 0) return null;

  const flat = data?.health?.flat ?? false;
  const provisional = data ? !(data.orientation?.confirmed ?? false) : false;
  const spikes = data?.spikes ?? [];

  return (
    <Panel
      title="Voltage"
      help={
        'The trace this electrode recorded on the MEA, over a one-second window, with the ' +
        'spikes MaxWell detected marked underneath.\n' +
        '\n' +
        'Only the electrodes that were wired up during the recording have a trace — a few ' +
        'hundred out of the many thousands on the chip. Clicking any of the others correctly ' +
        'says nothing was measured there.'
      }
      actions={
        recordings.length > 1 ? (
          <div className={styles.runs} role="group" aria-label="Recording">
            {recordings.map((r) => (
              <Button
                key={r.run_id}
                size="sm"
                variant={r.run_id === active ? 'primary' : 'ghost'}
                onClick={() => {
                  setRunId(r.run_id);
                  setT0(0);
                }}
                data-testid={`mea-run-${r.run_id}`}
              >
                {r.label}
              </Button>
            ))}
          </div>
        ) : undefined
      }
    >
      <div className={styles.body}>
        {!electrode && <p className={styles.hint}>Click an electrode in the mosaic.</p>}

        {electrode && error && (
          <LiveWarning variant="loud">Could not read the recording: {error}</LiveWarning>
        )}

        {electrode && data && !data.recorded && (
          <>
            <p className={styles.hint} data-testid="mea-not-recorded">
              Electrode <b>{electrode}</b> was not recorded.
            </p>
            <p className={styles.sub}>
              The chip has far more pads than the amplifier can read at once, so only{' '}
              {current?.n_channels.toLocaleString()} of them were wired up for {current?.label}.
              Nothing was measured here.
            </p>
          </>
        )}

        {electrode && data?.recorded && (
          <>
            {/* ⚠️ #3 — identity before signal: if the seating is unconfirmed, which electrode this
                IS has not been established, and that outranks anything about the waveform. */}
            {provisional && (
              <div data-testid="mea-provisional"><LiveWarning variant="warn">
                Provisional pairing. Which way the chip sits in this mosaic has not been confirmed,
                so this trace may belong to a different electrode.
              </LiveWarning></div>
            )}

            {/* ⚠️ #2 — say it before they read the picture as a silent electrode. */}
            {flat && (
              <div data-testid="mea-flat"><LiveWarning variant="warn">
                The waveform did not decode. {Math.round((data.health?.fill_fraction ?? 0) * 100)}%
                of this window is a single repeated value, which no live electrode produces —
                MaxWell&rsquo;s own decoder (part of MaxLab Live) is needed to read it properly. The
                spike marks below are unaffected and remain correct.
              </LiveWarning></div>
            )}

            <TraceChart
              trace={data.trace_uv ?? []}
              t0={data.t0_s ?? 0}
              t1={data.t1_s ?? 0}
              spikes={spikes}
              syncEpisodes={data.sync_episodes ?? []}
              suspect={flat}
            />

            {/* ⭐ A SCRUBBER, not just step buttons. The window is one second of three hundred;
                without this, reaching the far end is 300 clicks. */}
            <input
              className={styles.scrub}
              type="range"
              min={0}
              max={Math.max(0, duration - WINDOW_S)}
              step={0.1}
              value={t0}
              onChange={(e) => setT0(Number(e.target.value))}
              aria-label="Position in the recording"
              data-testid="mea-scrub"
            />

            <div className={styles.controls}>
              <Button size="sm" variant="ghost" onClick={() => step(-1)} disabled={t0 <= 0 || busy}>
                ← earlier
              </Button>
              <span className={styles.pos}>
                {(data.t0_s ?? 0).toFixed(1)}–{(data.t1_s ?? 0).toFixed(1)} s of {duration.toFixed(0)} s
              </span>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => step(1)}
                disabled={t0 + WINDOW_S >= duration || busy}
              >
                later →
              </Button>
            </div>

            <dl className={styles.facts}>
              <Fact label="Channel" value={String(data.channel)} />
              <Fact label="Chip electrode" value={String(data.chip_electrode)} />
              <Fact label="Spikes here" value={String(spikes.length)} />
              <Fact
                label="Spikes total"
                value={(data.n_spikes_total ?? 0).toLocaleString()}
                hint="across the whole recording"
              />
            </dl>
          </>
        )}
      </div>
    </Panel>
  );
}

function Fact({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}): React.JSX.Element {
  return (
    <div className={styles.fact}>
      <dt className={styles.factLabel}>{label}</dt>
      <dd className={styles.factValue}>{value}</dd>
      {hint && <span className={styles.factHint}>{hint}</span>}
    </div>
  );
}
