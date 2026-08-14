// ─────────────────────────────────────────────────────────────────────────────────────────────
// ONE PAD'S TRACE — click a dot on the chip, read what that electrode recorded.
//
// ⭐ **A SECOND PANEL, SHARING `core/trace/TraceChart` — NOT `MeaTracePanel` REUSED.** Plan 003
// § Approach called this a judgement call and named this as the expected answer, and reading the
// two side by side settles it: they diverge on **the identity question**, which is the whole
// reason that panel exists. `features/electrodes/MeaTracePanel` must say *"which electrode this is
// has not been established"*, because it works from a mosaic and the chip's seating under the
// microscope is unresolved. This screen works in the chip's own frame, where the file states its
// own `electrode`/`x_um`/`y_um`. A shared panel would need a flag meaning "am I allowed to be
// certain", and a component that can be told to doubt its own subject is the wrong shape.
//
// 🔴 **SO THERE IS NO SEATING WARNING HERE, AND ADDING ONE WOULD BE A BUG.** Not an omission, not
// something to "make consistent" later: importing that doubt would teach a doubt that does not
// exist and would make the screen lie about his data.
//
// 🔴 **THE ONE WARNING THAT DOES BELONG IS ON THE PAGE, AS A `LiveWarning`, NEVER BEHIND THE `?`.**
// 001 moved a line of prose behind the `?` on his instruction and it would be easy to read that as
// *"explanations go behind the `?` on this screen"*. It is the opposite instruction. What went
// behind the `?` was "this part of Camea is not written yet" — a fact about the **app**. This is a
// fact about **his data, right now**: the waveform he is looking at did not decode. That is R3's
// standing exception (W1–W11), and a fact he must not be able to miss cannot live somewhere he has
// to hover to find. The distinction is written into `MeaFeature.tsx :: WHAT_ADD_DOES`; keep it true.
//
// ⭐ **THE SPIKE TICKS ARE THE TRUSTWORTHY HALF AND ARE DRAWN EVEN WHEN THE WAVEFORM IS NOT.**
// MaxWell's on-chip detector wrote them at acquisition, uncompressed, so they need no proprietary
// decoder. A railed window looks EXACTLY like a genuinely silent electrode, which is why the
// waveform is dimmed and captioned rather than quietly drawn.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { useCallback, useEffect, useRef, useState } from 'react';
import { meaChannelTrace } from '../../api';
import type { MeaChannelTrace } from '../../api';
import { TraceChart } from '../../core/trace/TraceChart';
import { Button, LiveWarning, Panel } from '../../design';
import { SILENT_MEANING, formatRate } from './activityScale';
import styles from './MeaTrace.module.css';

/** How much of the recording one view shows. The window is fetched, never the whole recording. */
const WINDOW_S = 1.0;

export interface MeaTraceProps {
  analysisId: string;
  recordingId: string;
  /** The channel of the pad he clicked, or null when nothing is selected yet. */
  channel: number | null;
}

export function MeaTrace({ analysisId, recordingId, channel }: MeaTraceProps) {
  const [t0, setT0] = useState(0);
  const [data, setData] = useState<MeaChannelTrace | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // ⭐ Which pad we have already jumped to the activity for. A 300 s recording opened at t=0
  // usually shows a dead window, and stepping a second at a time would take 200 clicks to reach
  // the spikes — so the FIRST view of a pad lands where it actually fired. Recorded per selection,
  // so the jump happens once and never fights his own scrubbing.
  //
  // ⚠️ **A `useRef`, NOT `useState`, AND THAT IS A BUG FIX.** As state it was both written by the
  // fetch effect and listed in that effect's dependencies, so every pad click fetched the window
  // **twice**: run once → `setJumped` → dependency changed → run again. It is never read during
  // render, so it was never state's job. (Found in review.)
  const jumped = useRef<string | null>(null);

  useEffect(() => {
    setT0(0);
    jumped.current = null;
  }, [channel, recordingId]);

  useEffect(() => {
    if (channel == null) {
      setData(null);
      return;
    }
    let cancelled = false;
    setBusy(true);
    setError(null);
    void meaChannelTrace(analysisId, recordingId, channel, { t0, t1: t0 + WINDOW_S })
      .then((d) => {
        if (cancelled) return;
        setData(d);
        const key = `${recordingId}:${channel}`;
        if (jumped.current !== key) {
          jumped.current = key;
          const first = d.first_spike_s;
          if (first != null && (d.spikes?.length ?? 0) === 0) {
            setT0(Math.max(0, Math.floor(first * 10) / 10));
          }
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
  }, [analysisId, recordingId, channel, t0]);

  const duration = data?.duration_s ?? 0;
  const step = useCallback(
    (dir: number) => {
      setT0((v) => Math.max(0, Math.min(Math.max(0, duration - WINDOW_S), v + dir * WINDOW_S)));
    },
    [duration],
  );

  const flat = data?.health?.flat ?? false;
  const spikes = data?.spikes ?? [];
  const undecodable = Boolean(data?.decode_error);

  return (
    <Panel
      title="What this pad recorded"
      help={
        'The voltage this electrode recorded, over a one-second window, with the spikes MaxWell ' +
        'detected marked underneath.\n' +
        '\n' +
        'Use the slider to move through the recording. The first time you click a pad, Camea ' +
        'jumps to where that pad first fired, so you are not looking at an empty stretch.'
      }
    >
      <div className={styles.body}>
        {channel == null && (
          <p className={styles.hint} data-testid="mea-trace-idle">
            Click a pad on the chip to read it.
          </p>
        )}

        {channel != null && error && (
          <LiveWarning variant="loud">
            <span data-testid="mea-trace-error">Could not read the recording: {error}</span>
          </LiveWarning>
        )}

        {/* ⭐ A pad that was never wired up. On this screen the map only draws routed pads, so a
            click cannot normally land here — but it must read as a fact about the experiment
            rather than as an error if it ever does. */}
        {channel != null && data && !data.recorded && (
          <p className={styles.hint} data-testid="mea-trace-unrouted">
            Channel <b>{channel}</b> was not wired up for this recording, so nothing was measured
            on it. Only some of the chip&rsquo;s pads can be recorded at once.
          </p>
        )}

        {channel != null && data?.recorded && (
          <>
            <dl className={styles.facts} data-testid="mea-trace-facts">
              <Fact label="Electrode" value={String(data.electrode ?? '—')} />
              <Fact label="Channel" value={String(data.channel)} />
              <Fact
                label="Position"
                value={
                  data.x_um != null && data.y_um != null
                    ? `${Math.round(data.x_um)}, ${Math.round(data.y_um)} µm`
                    : '—'
                }
              />
              <Fact
                label="Spikes here"
                value={(data.n_spikes_total ?? 0).toLocaleString()}
                hint={
                  duration > 0
                    ? formatRate((data.n_spikes_total ?? 0) / duration)
                    : 'across the recording'
                }
              />
            </dl>

            {/* ⭐ **HIS CORRECTION, 2026-08-14.** Among the pads that WERE wired up, many are not
                near a neuron at all — so a pad that never fired is the ordinary answer, and this
                must not read as a broken electrode. Stated as a plain fact, deliberately NOT a
                LiveWarning: nothing is wrong. */}
            {(data.n_spikes_total ?? 0) === 0 && (
              <p className={styles.quiet} data-testid="mea-trace-no-spikes">
                This pad was recorded for the whole session and detected nothing — {SILENT_MEANING}.
              </p>
            )}

            {/* 🔴 #1 — say it BEFORE he reads the picture as a silent electrode. On the page, as a
                LiveWarning, never behind the `?`. See the header. */}
            {undecodable && (
              <div data-testid="mea-trace-undecodable">
                <LiveWarning variant="warn">
                  The waveform could not be read at all. MaxWell compresses the raw recording with
                  its own method, and the software that unpacks it (part of MaxLab Live) is not
                  installed on this machine. The spike marks below come from the chip&rsquo;s own
                  detector and are unaffected.
                </LiveWarning>
              </div>
            )}
            {!undecodable && flat && (
              <div data-testid="mea-trace-flat">
                <LiveWarning variant="warn">
                  The waveform did not decode.{' '}
                  {Math.round((data.health?.fill_fraction ?? 0) * 100)}% of this window is a single
                  repeated value, which no live electrode produces — MaxWell&rsquo;s own decoder
                  (part of MaxLab Live) is needed to read it properly. The spike marks below are
                  unaffected and remain correct.
                </LiveWarning>
              </div>
            )}

            <TraceChart
              trace={data.trace_uv ?? []}
              t0={data.t0_s ?? 0}
              t1={data.t1_s ?? 0}
              spikes={spikes}
              suspect={flat || undecodable}
            />

            {/* ⭐ A SCRUBBER, not just step buttons: the window is one second of up to three
                hundred, and reaching the far end would otherwise be 300 clicks. */}
            <input
              className={styles.scrub}
              type="range"
              min={0}
              max={Math.max(0, duration - WINDOW_S)}
              step={0.1}
              value={t0}
              onChange={(e) => setT0(Number(e.target.value))}
              aria-label="Position in the recording"
              data-testid="mea-trace-scrub"
            />

            <div className={styles.controls}>
              <Button size="sm" variant="ghost" onClick={() => step(-1)} disabled={t0 <= 0 || busy}>
                ← earlier
              </Button>
              <span className={styles.pos}>
                {(data.t0_s ?? 0).toFixed(1)}–{(data.t1_s ?? 0).toFixed(1)} s of{' '}
                {duration.toFixed(0)} s · {spikes.length} spike{spikes.length === 1 ? '' : 's'} in
                view
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
          </>
        )}
      </div>
    </Panel>
  );
}

function Fact({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className={styles.fact}>
      <dt className={styles.factLabel}>{label}</dt>
      <dd className={styles.factValue}>{value}</dd>
      {hint && <span className={styles.factHint}>{hint}</span>}
    </div>
  );
}
