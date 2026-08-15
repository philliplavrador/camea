// ─────────────────────────────────────────────────────────────────────────────────────────────
// ONE PAD'S TRACE — click a dot on the chip, read the whole of what that electrode recorded.
//
// ⭐ **THE WHOLE RECORDING, AND YOU DRAG A STRETCH TO ZOOM IN** (plan 004). His words, 2026-08-15:
// *"I don't like the slider bar. What I want is the MEA trace … more like the matplotlib, but the
// one where I have the interactive widget, so I have the whole trace, and then I can make a
// rectangle around the area I want to zoom in, then I can go back."* So: two pictures — a strip
// holding the whole recording end to end, and a close-up underneath — with matplotlib's own
// navigation between them. ⛔ **The slider, both step buttons and `WINDOW_S` are gone.** Do not
// reintroduce a scrubber; the strip is not one and must not grow a handle.
//
// 🔴 **WHY TWO PICTURES AND NOT ONE.** He chose it, and the code agrees for a reason worth keeping:
// the *"this waveform did not decode"* warning is driven by `health`, which the server only produces
// for a window it actually read. A panel showing the whole recording with no close-up fetched would
// have `health == null` and would **silently stop warning him his data is unreadable** — an R3.8 /
// R47.7 regression, not a red test. Two pictures means a close-up is always open, so the warning
// always has something to say.
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

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { meaChannelTrace, startMeaEnvelopes } from '../../api';
import type { MeaChannelTrace } from '../../api';
import { ApiError } from '../../api/client';
import { TRACE_PAD, TraceChart } from '../../core/trace/TraceChart';
import { useTimeBrush } from '../../core/trace/useTimeBrush';
import * as vs from '../../core/trace/viewStack';
import { Button, LiveWarning, Panel } from '../../design';
import { SILENT_MEANING, formatRate } from './activityScale';
import { TraceNav } from './TraceNav';
import { readout } from './readout';
import styles from './MeaTrace.module.css';

/**
 * How many min/max columns to ask the server for. A **rendering** choice — roughly a wide canvas,
 * doubled so a resize does not immediately look coarse — and never a fact about a recording (I1).
 * The server folds the window into this many pairs, so a 300 s request costs the same as a 1 s one.
 */
const COLUMNS = 1200;

/** The narrowest stretch worth zooming to, in stored samples. Derived against the file's own
 *  `sampling_hz` at the point of use, so no duration and no rate is ever written down here. */
const MIN_SPAN_SAMPLES = 20;

/** How long to sit still before fetching the view he has landed on. Long enough that walking back
 *  through history with the keyboard does not fire a request per keystroke. */
const SETTLE_MS = 90;

export interface MeaTraceProps {
  analysisId: string;
  recordingId: string;
  /** The channel of the pad he clicked, or null when nothing is selected yet. */
  channel: number | null;
}

export function MeaTrace({ analysisId, recordingId, channel }: MeaTraceProps) {
  // The whole recording, fetched once per pad: the strip's picture, and the source of `duration_s`.
  const [whole, setWhole] = useState<MeaChannelTrace | null>(null);
  // The close-up. Always present whenever `whole` is — see the header on why.
  const [data, setData] = useState<MeaChannelTrace | null>(null);
  const [stack, setStack] = useState<vs.ViewStack>(vs.EMPTY_STACK);
  const [error, setError] = useState<string | null>(null);
  const [needsEnvelope, setNeedsEnvelope] = useState(false);
  const [building, setBuilding] = useState(false);
  const [said, setSaid] = useState('');
  const boxRef = useRef<HTMLDivElement | null>(null);
  // Every detail fetch carries a ticket; a late reply holding a stale one is dropped. Without it a
  // slow wide request can land after a fast narrow one and redraw the view he already left.
  const ticket = useRef(0);

  const view = vs.current(stack);
  const duration = whole?.duration_s ?? 0;
  const samplingHz = whole?.sampling_hz ?? 0;
  const minSpanS = samplingHz > 0 ? MIN_SPAN_SAMPLES / samplingHz : 0;

  // ── arrival: the whole recording, in one request ──────────────────────────────────────────
  // ⭐ Asked for with no `t1` and a `max_points`, which is the server's way of saying "all of it,
  // folded to this many columns". It doubles as the opening close-up, so a pad costs ONE request.
  useEffect(() => {
    if (channel == null) {
      setWhole(null);
      setData(null);
      setStack(vs.EMPTY_STACK);
      return;
    }
    let cancelled = false;
    setError(null);
    setNeedsEnvelope(false);
    setWhole(null);
    setData(null);
    setStack(vs.EMPTY_STACK);
    void meaChannelTrace(analysisId, recordingId, channel, { t0: 0, maxPoints: COLUMNS })
      .then((d) => {
        if (cancelled) return;
        setWhole(d);
        setData(d);
        // ⚠️ Home is what the SERVER returned, not what we asked for — the envelope snaps to its
        // stored bucket edges, and an axis labelled from the request would be a lie.
        setStack(vs.stackOf({ t0: d.t0_s, t1: d.t1_s }));
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 409) {
          // The one-off read has not been done for this recording yet. A fact and an offer, not an
          // error: narrow windows still work, and the button starts the job.
          setNeedsEnvelope(true);
          setError(e.message);
          return;
        }
        setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [analysisId, recordingId, channel]);

  // ── the close-up follows the view he is standing on ───────────────────────────────────────
  useEffect(() => {
    if (channel == null || view == null || whole == null) return;
    // The opening view IS the whole recording, which we already hold. Do not re-fetch it.
    if (view.t0 === whole.t0_s && view.t1 === whole.t1_s) {
      setData(whole);
      return;
    }
    let cancelled = false;
    const mine = ++ticket.current;
    const timer = setTimeout(() => {
      void meaChannelTrace(analysisId, recordingId, channel, {
        t0: view.t0,
        t1: view.t1,
        maxPoints: COLUMNS,
      })
        .then((d) => {
          if (cancelled || mine !== ticket.current) return;
          setData(d);
        })
        .catch((e: unknown) => {
          if (cancelled || mine !== ticket.current) return;
          setError(e instanceof Error ? e.message : String(e));
        });
    }, SETTLE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // ⚠️ `view` is safe as a dependency: `vs.current` hands back the entry object itself, whose
    // identity only changes when a genuinely new view is pushed. Comparing `t0`/`t1` instead would
    // silently miss a re-fetch after Back landed on an equal-but-distinct range.
  }, [analysisId, recordingId, channel, view, whole]);

  // ── navigation ─────────────────────────────────────────────────────────────────────────────
  const announce = useCallback(
    (v: vs.TimeView, n: number) => setSaid(readout(v.t0, v.t1, duration, n)),
    [duration],
  );

  const go = useCallback(
    (next: vs.ViewStack) => {
      setStack(next);
      const v = vs.current(next);
      if (v) announce(v, 0);
    },
    [announce],
  );

  const onSelect = useCallback(
    (v: vs.TimeView) => go(vs.push(stack, v)),
    [go, stack],
  );

  const brush = useTimeBrush({
    t0: view?.t0 ?? 0,
    t1: view?.t1 ?? 0,
    pad: TRACE_PAD,
    minSpanS,
    onSelect,
  });

  // The strip's axis is ALWAYS the whole recording, so it needs its own brush against that axis.
  const stripBrush = useTimeBrush({
    t0: whole?.t0_s ?? 0,
    t1: whole?.t1_s ?? 0,
    pad: TRACE_PAD,
    minSpanS,
    onSelect,
  });

  // ── keyboard, and it is not optional ──────────────────────────────────────────────────────
  // ⚠️ This app has shipped a keyboard-dead canvas once and review caught a second. `+`/`-` mean
  // zoom and `0` is left alone because it means 1:1 in the viewer and 1:1 has no meaning on a time
  // axis (R12.6 / R13.7). Esc belongs to the drag in flight and to nothing else — R14 is untouched.
  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (!view || !whole) return;
      const span = view.t1 - view.t0;
      const clampTo = (t0: number, t1: number): vs.TimeView => {
        const w = Math.min(Math.max(t1 - t0, minSpanS), whole.t1_s - whole.t0_s);
        const a = Math.min(Math.max(t0, whole.t0_s), whole.t1_s - w);
        return { t0: a, t1: a + w };
      };
      let next: vs.ViewStack | null = null;
      if (e.key === 'ArrowLeft') next = vs.push(stack, clampTo(view.t0 - span / 2, view.t1 - span / 2));
      else if (e.key === 'ArrowRight') next = vs.push(stack, clampTo(view.t0 + span / 2, view.t1 + span / 2));
      else if (e.key === '+' || e.key === '=') {
        const mid = (view.t0 + view.t1) / 2;
        next = vs.push(stack, clampTo(mid - span / 4, mid + span / 4));
      } else if (e.key === '-' || e.key === '_') {
        const mid = (view.t0 + view.t1) / 2;
        next = vs.push(stack, clampTo(mid - span, mid + span));
      } else if (e.key === 'Backspace') next = vs.back(stack);
      else if (e.key === 'Home') next = vs.home(stack);
      if (next && next !== stack) {
        e.preventDefault();
        go(next);
      }
    },
    [go, minSpanS, stack, view, whole],
  );

  // ── Ctrl+wheel zooms about the pointer ────────────────────────────────────────────────────
  // ⛔ The BARE wheel is deliberately not bound. This panel lives in the right rail, which under
  // R47.1 is the only scroller on the screen, and stealing his scroll whenever the pointer crosses
  // a chart is exactly the complaint R47 exists for. matplotlib refused to bind the naked wheel
  // until 3.11 and then gated it behind Ctrl; Plotly ships `scrollZoom` off for cartesian charts.
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey || !view || !whole) return;
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const w = Math.max(1, rect.width - TRACE_PAD.left - TRACE_PAD.right);
      const f = Math.min(1, Math.max(0, (e.clientX - rect.left - TRACE_PAD.left) / w));
      const at = view.t0 + f * (view.t1 - view.t0);
      const k = e.deltaY > 0 ? 1.25 : 0.8;
      const span = Math.min(
        Math.max((view.t1 - view.t0) * k, minSpanS),
        whole.t1_s - whole.t0_s,
      );
      const t0 = Math.min(Math.max(at - f * span, whole.t0_s), whole.t1_s - span);
      go(vs.push(stack, { t0, t1: t0 + span }));
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [go, minSpanS, stack, view, whole]);

  const buildEnvelopes = useCallback(() => {
    setBuilding(true);
    void startMeaEnvelopes(analysisId)
      .then(() => setSaid('Reading the recordings end to end. This takes about a minute each.'))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setBuilding(false));
  }, [analysisId]);

  const flat = data?.health?.flat ?? false;
  const spikes = useMemo(() => data?.spikes ?? [], [data]);
  const undecodable = Boolean(data?.decode_error);
  const bandFromDrag = useMemo(() => {
    if (!brush.dragging || !view || !boxRef.current) return null;
    const w = Math.max(1, boxRef.current.clientWidth - TRACE_PAD.left - TRACE_PAD.right);
    const f = (x: number) => (x - TRACE_PAD.left) / w;
    return { t0: view.t0 + f(brush.x0) * (view.t1 - view.t0), t1: view.t0 + f(brush.x1) * (view.t1 - view.t0) };
  }, [brush.dragging, brush.x0, brush.x1, view]);

  return (
    <Panel
      title="What this pad recorded"
      help={
        'The voltage this electrode recorded across the whole session, with the spikes MaxWell ' +
        'detected marked underneath.\n' +
        '\n' +
        'The strip on top always shows the whole recording, with a box marking the stretch you ' +
        'are looking at closely. Drag sideways across either picture to zoom into that stretch; ' +
        'Back walks you out again, like the back button in a browser. A plain click does nothing, ' +
        'so you cannot zoom by accident.\n' +
        '\n' +
        'Arrow keys move by half a screen, + and - zoom, Backspace goes back, and holding Ctrl ' +
        'while you scroll zooms about the pointer.'
      }
    >
      <div className={styles.body}>
        {channel == null && (
          <p className={styles.hint} data-testid="mea-trace-idle">
            Click a pad on the chip to read it.
          </p>
        )}

        {channel != null && error && !needsEnvelope && (
          <LiveWarning variant="loud">
            <span data-testid="mea-trace-error">Could not read the recording: {error}</span>
          </LiveWarning>
        )}

        {/* ⭐ Not an error: the one-off read has not happened for this recording. Say what is
            missing and offer to do it, rather than showing a broken chart. */}
        {channel != null && needsEnvelope && (
          <div data-testid="mea-trace-needs-envelope">
            <LiveWarning variant="warn">
              Camea has not read this recording end to end yet, so it cannot show you the whole of
              it at once. It is a one-off job of about a minute per recording.{' '}
              <Button size="sm" variant="ghost" onClick={buildEnvelopes} disabled={building}>
                {building ? 'Starting…' : 'Read it now'}
              </Button>
            </LiveWarning>
          </div>
        )}

        {/* ⭐ A pad that was never wired up. On this screen the map only draws routed pads, so a
            click cannot normally land here — but it must read as a fact about the experiment
            rather than as an error if it ever does. */}
        {channel != null && whole && !whole.recorded && (
          <p className={styles.hint} data-testid="mea-trace-unrouted">
            Channel <b>{channel}</b> was not wired up for this recording, so nothing was measured
            on it. Only some of the chip&rsquo;s pads can be recorded at once.
          </p>
        )}

        {channel != null && whole?.recorded && data && view && (
          <>
            <dl className={styles.facts} data-testid="mea-trace-facts">
              <Fact label="Electrode" value={String(whole.electrode ?? '—')} />
              <Fact label="Channel" value={String(whole.channel)} />
              <Fact
                label="Position"
                value={
                  whole.x_um != null && whole.y_um != null
                    ? `${Math.round(whole.x_um)}, ${Math.round(whole.y_um)} µm`
                    : '—'
                }
              />
              <Fact
                label="Spikes here"
                value={(whole.n_spikes_total ?? 0).toLocaleString()}
                hint={
                  duration > 0
                    ? formatRate((whole.n_spikes_total ?? 0) / duration)
                    : 'across the recording'
                }
              />
            </dl>

            {/* ⭐ **HIS CORRECTION, 2026-08-14.** Among the pads that WERE wired up, many are not
                near a neuron at all — so a pad that never fired is the ordinary answer, and this
                must not read as a broken electrode. Stated as a plain fact, deliberately NOT a
                LiveWarning: nothing is wrong. */}
            {(whole.n_spikes_total ?? 0) === 0 && (
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
                  {Math.round((data.health?.fill_fraction ?? 0) * 100)}% of this recording is a
                  single repeated value, which no live electrode produces — MaxWell&rsquo;s own
                  decoder (part of MaxLab Live) is needed to read it properly. The spike marks below
                  are unaffected and remain correct.
                </LiveWarning>
              </div>
            )}

            {/* ── the whole recording, always ─────────────────────────────────────────────── */}
            <div
              className={styles.strip}
              data-testid="mea-trace-overview"
              {...stripBrush.handlers}
            >
              <TraceChart
                trace={[]}
                minUv={whole.min_uv}
                maxUv={whole.max_uv}
                t0={whole.t0_s}
                t1={whole.t1_s}
                spikes={[]}
                suspect={whole.health?.flat ?? false}
                height={56}
                band={{ t0: view.t0, t1: view.t1 }}
                // ⚠️ Zoomed deep into a 300 s recording the box is a fraction of a pixel wide. A
                // "you are here" marker you cannot see is the same as not having one.
                bandMinPx={2}
              />
            </div>

            {/* ── the close-up ────────────────────────────────────────────────────────────── */}
            <div
              ref={boxRef}
              className={styles.detail}
              tabIndex={0}
              role="application"
              aria-label="The stretch of the recording you are looking at. Drag sideways to zoom in."
              onKeyDown={onKeyDown}
              {...brush.handlers}
            >
              <TraceChart
                trace={data.trace_uv ?? []}
                minUv={data.min_uv}
                maxUv={data.max_uv}
                t0={data.t0_s}
                t1={data.t1_s}
                spikes={spikes}
                suspect={flat || undecodable}
                band={bandFromDrag}
              />
            </div>

            <TraceNav
              t0={view.t0}
              t1={view.t1}
              duration={duration}
              nSpikes={spikes.length}
              canBack={vs.canBack(stack)}
              canForward={vs.canForward(stack)}
              onHome={() => go(vs.home(stack))}
              onBack={() => go(vs.back(stack))}
              onForward={() => go(vs.forward(stack))}
            />

            {/* Where the keystroke happened, so a keyboard-only zoom is announced. The obligation
                `ChipMap` established in review — a canvas that takes the keyboard must say what it
                did. */}
            <span className={styles.said} role="status" aria-live="polite"
                  data-testid="mea-trace-said">
              {said}
            </span>
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
