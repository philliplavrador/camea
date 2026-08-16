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
//      proprietary filter, and on SOME of this project's recordings the publicly available decoder
//      returns a rail (~98% of samples one fill value). `health.flat` says so, and a railed window
//      looks EXACTLY like a genuinely silent electrode — which is why this is stated and the trace
//      is dimmed rather than quietly drawn. ⚠️ The percentage NAMES WHAT IT MEASURED
//      (`health_scope`): a narrow window is read live and carries its own figure; a wide view
//      comes from the cache and carries the whole recording's. The rail fraction genuinely
//      differs with window length, so a number quoted without its scope changes as he zooms with
//      nothing on screen to explain it.
//      ⛔ **NOT "the decoder is broken" — corrected 2026-08-15.** Measured exactly over the whole
//      of all five recordings in his project: 000690/691/692 rail (94-100%), but **000688 and
//      000689 decode cleanly** (1.1% and 4.4%). It is those recordings, not the decoder. Read
//      `health`; never assume.
//   3. ⚠️ **the chip's seating is not established.** Which corner of the mosaic the chip's own
//      origin landed in is a fact about the microscope that no file records. Until it is
//      confirmed, the electrode's identity is PROVISIONAL and the panel says so.
//
// The spike ticks are the one thing here that is unconditionally trustworthy: MaxWell's on-chip
// detector wrote them at acquisition and they need no proprietary decoder. When the waveform is
// suspect they are still exactly right, which is why they are drawn even then.
//
// ⭐ **THE WHOLE RECORDING, AND YOU DRAG A STRETCH TO ZOOM IN** (the plan-004 viewer, ported here
// 2026-08-15). Two pictures — a 56 px strip holding the whole recording end to end, and a close-up
// underneath — with matplotlib's navigation between them: drag sideways on either to zoom,
// Back / Forward / Whole recording, ←/→ pan, +/− zoom, Backspace back, Home home, Ctrl+wheel about
// the pointer. ⛔ **The 1 s window, the scrubber and both step buttons are gone.** Do not
// reintroduce a scrubber; the strip is not one and must not grow a handle. ⛔ The BARE wheel is
// deliberately not bound (R47.1 — the rail is the only scroller, and a chart must not steal it).
//
// 🔴 **THE OLD PANEL'S DOUBLE-FETCH IS DEAD BY CONSTRUCTION.** It recorded "have I jumped to the
// first spike yet" in STATE (`jumped`), so the arrival effect re-ran once per state write and the
// same window was fetched twice. This panel opens on the whole recording — his 2026-08-15 ruling:
// no jump to the first spike — so there is no one-shot flag at all, and the only refs here
// (`ticket`) exist to DROP stale replies, not to schedule work.
//
// ⭐ **SHARING `core/trace/*` — NOT `features/mea/MeaTrace` REUSED.** The two panels diverge on the
// identity question: this one works from a mosaic whose chip seating is unresolved and must say
// so (warning 3); that one works in the chip's own frame where doubt would be a lie. A shared
// panel would need a flag meaning "am I allowed to be certain", and a component that can be told
// to doubt its own subject is the wrong shape. The pieces that agree — chart, brush, view stack,
// nav row — are core, and both mount them.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { getElectrodeTrace, getMeaEnvelopes, startMeaEnvelopeRead } from '../../api';
import type { ElectrodeTracePayload, MeaRecordingSummary, MeaSyncEpisode } from '../../api';
import { ApiError } from '../../api/client';
import { TRACE_PAD, TraceChart } from '../../core/trace/TraceChart';
import { TraceNav } from '../../core/trace/TraceNav';
import { readout } from '../../core/trace/readout';
import { nextSpike, prevSpike } from '../../core/trace/spikeStep';
import { inPlot, plotRect, timeAtX, useTimeBrush } from '../../core/trace/useTimeBrush';
import * as vs from '../../core/trace/viewStack';
import { Button, LiveWarning, Panel } from '../../design';
import styles from './MeaTracePanel.module.css';

/**
 * How many min/max columns to ask the server for. A **rendering** choice — roughly a wide canvas,
 * doubled so a resize does not immediately look coarse — never a fact about a recording (I1).
 */
const COLUMNS = 1200;

/** The narrowest stretch worth zooming to, in stored samples. Derived against the file's own
 *  `sampling_hz` at the point of use, so no duration and no rate is ever written down here. */
const MIN_SPAN_SAMPLES = 20;

/** How long to sit still before fetching the view he has landed on. Long enough that walking back
 *  through history with the keyboard does not fire a request per keystroke. */
const SETTLE_MS = 90;

/** How often to ask whether the one-off read has finished, while it runs. */
const POLL_MS = 2000;

// ⚠️ **MODULE CONSTANTS, NOT `[]` AT THE CALL SITE.** `TraceChart` keys its paint on prop
// identity, so a fresh array literal in JSX repaints the canvas on every parent render — and this
// panel re-renders on every pointermove of a drag. The strip has no business repainting while the
// close-up is being dragged.
const NO_TRACE: number[] = [];
const NO_SPIKES: never[] = [];
const NO_EPISODES: MeaSyncEpisode[] = [];

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
  // The whole recording, fetched once per selection: the strip's picture and the opening close-up.
  const [whole, setWhole] = useState<ElectrodeTracePayload | null>(null);
  // The close-up. Always present whenever `whole` is — the "did not decode" warning is driven by
  // the close-up's `health`, so a panel with no close-up open would silently stop warning (R3.8).
  const [data, setData] = useState<ElectrodeTracePayload | null>(null);
  const [stack, setStack] = useState<vs.ViewStack>(vs.EMPTY_STACK);
  const [error, setError] = useState<string | null>(null);
  /** True while the close-up on screen is a PREVIOUS stretch — its fetch is still out. */
  const [pending, setPending] = useState(false);
  const [needsEnvelope, setNeedsEnvelope] = useState(false);
  const [building, setBuilding] = useState(false);
  // Bumped when the backfill finishes, purely to re-run the arrival fetch — without it the panel
  // keeps saying "not read yet" after the job it started has finished.
  const [reload, setReload] = useState(0);
  const [said, setSaid] = useState('');
  /** The moment the cursor is over on the close-up, or null when it is off the picture. */
  const [pointerT, setPointerT] = useState<number | null>(null);
  const boxRef = useRef<HTMLDivElement | null>(null);
  // Every close-up fetch carries a ticket; a late reply holding a stale one is dropped. A ref,
  // not state: it schedules nothing and must not re-render anything.
  const ticket = useRef(0);

  const active = runId ?? recordings[0]?.run_id ?? null;
  const current = recordings.find((r) => r.run_id === active) ?? recordings[0];

  const view = vs.current(stack);
  const duration = whole?.duration_s ?? 0;
  const samplingHz = whole?.sampling_hz ?? 0;
  const minSpanS = samplingHz > 0 ? MIN_SPAN_SAMPLES / samplingHz : 0;

  // ── arrival: the whole recording, in one request ──────────────────────────────────────────
  // ⭐ `maxPoints` with no `t1` is the server's way of saying "all of it, folded to this many
  // columns". It doubles as the opening close-up, so a click costs ONE request — and there is no
  // jump-to-first-spike step to schedule, so nothing here can fetch twice.
  useEffect(() => {
    if (!electrode || !active) {
      setWhole(null);
      setData(null);
      setStack(vs.EMPTY_STACK);
      setPending(false);
      return;
    }
    let cancelled = false;
    setError(null);
    setNeedsEnvelope(false);
    setWhole(null);
    setData(null);
    setStack(vs.EMPTY_STACK);
    setPending(false);
    void getElectrodeTrace(analysisId, electrode, { runId: active, t0: 0, maxPoints: COLUMNS })
      .then((d) => {
        if (cancelled) return;
        setWhole(d);
        setData(d);
        // ⚠️ Home is what the SERVER returned, not what we asked for — the envelope snaps to its
        // stored bucket edges, and an axis labelled from the request would be a lie.
        setStack(vs.stackOf({ t0: d.t0_s ?? 0, t1: d.t1_s ?? 0 }));
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 409) {
          // The one-off read has not been done for this recording yet. A fact and an offer, not
          // an error: the button below starts the job.
          setNeedsEnvelope(true);
          setError(e.message);
          return;
        }
        setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [analysisId, electrode, active, reload]);

  // ⚠️ **WAIT FOR THE BACKFILL AND THEN SHOW THE RECORDING.** Starting the job is not the feature;
  // seeing the trace afterwards is. Polls until this run's row reads `ready`, then re-runs the
  // arrival fetch. Stops (without pretending success) when nothing is running any more.
  useEffect(() => {
    if (!building) return;
    let stop = false;
    const tick = () => {
      void getMeaEnvelopes(analysisId)
        .then((s) => {
          if (stop) return;
          const rows = s.recordings ?? [];
          const mine = rows.find((r) => r.run_id === active);
          const running = rows.some((r) => r.job_id);
          if (mine?.ready) {
            setBuilding(false);
            setNeedsEnvelope(false);
            setError(null);
            setSaid('The whole recording is ready.');
            setReload((n) => n + 1);
          } else if (!running) {
            // Nothing is running and it still is not ready — the job failed or refused. Stop
            // polling and leave the panel saying so rather than spinning for ever.
            setBuilding(false);
          }
        })
        .catch(() => setBuilding(false));
    };
    const timer = setInterval(tick, POLL_MS);
    return () => {
      stop = true;
      clearInterval(timer);
    };
  }, [analysisId, active, building]);

  // ── the close-up follows the view he is standing on ───────────────────────────────────────
  useEffect(() => {
    if (!electrode || !active || view == null || whole == null) return;
    // The opening view IS the whole recording, which we already hold. Do not re-fetch it.
    if (view.t0 === whole.t0_s && view.t1 === whole.t1_s) {
      setData(whole);
      setPending(false);
      return;
    }
    let cancelled = false;
    const mine = ++ticket.current;
    // ⭐ The previous chart stays up while this fetch is out — dimmed and badged "previous",
    // never blanked and never left claiming to be current. (Same rule as MeaTrace, 2026-08-16.)
    setPending(true);
    const timer = setTimeout(() => {
      void getElectrodeTrace(analysisId, electrode, {
        runId: active,
        t0: view.t0,
        t1: view.t1,
        maxPoints: COLUMNS,
      })
        .then((d) => {
          if (cancelled || mine !== ticket.current) return;
          setData(d);
          setError(null); // an earlier failed stretch is no longer the current state
          setPending(false);
        })
        .catch((e: unknown) => {
          if (cancelled || mine !== ticket.current) return;
          setError(e instanceof Error ? e.message : String(e));
          // ⛔ Blank, never stale charts under a warning — a picture of the stretch he left,
          // drawn under the failure line, reads as the stretch that failed.
          setData(null);
          setPending(false);
        });
    }, SETTLE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // ⚠️ `view` is safe as a dependency: `vs.current` hands back the entry object itself, whose
    // identity only changes when a genuinely new view is pushed.
  }, [analysisId, electrode, active, view, whole]);

  // ── navigation ────────────────────────────────────────────────────────────────────────────
  const go = useCallback((next: vs.ViewStack) => setStack(next), []);

  // ⚠️ The announcement waits for the DATA — announcing at the moment of navigation would state a
  // spike count that is not known yet (the MeaTrace lesson, kept).
  useEffect(() => {
    if (!data?.recorded) return;
    setSaid(readout(data.t0_s ?? 0, data.t1_s ?? 0, data.duration_s ?? 0,
                    data.spikes?.length ?? 0));
  }, [data]);

  const onSelect = useCallback((v: vs.TimeView) => go(vs.push(stack, v)), [go, stack]);

  /** One clamp shared by the keys and spike stepping, so they cannot disagree. */
  const clampTo = useCallback(
    (t0: number, t1: number): vs.TimeView => {
      const w0 = whole?.t0_s ?? 0;
      const w1 = whole?.t1_s ?? 0;
      const w = Math.min(Math.max(t1 - t0, minSpanS), w1 - w0);
      const a = Math.min(Math.max(t0, w0), w1 - w);
      return { t0: a, t1: a + w };
    },
    [whole, minSpanS],
  );

  // ── spike to spike — same behaviour as the Analyze MEA viewer, same core helper ────────────
  // ⭐ Steps against the WHOLE recording's spike list (`whole.spikes` covers the full served
  // range), so a jump lands far beyond the loaded close-up. A jump is a push; Back undoes it.
  const allSpikes = useMemo(() => whole?.spikes ?? [], [whole]);
  const stepSpike = useCallback(
    (dir: 1 | -1) => {
      if (!view || !whole) return;
      const span = view.t1 - view.t0;
      const mid = (view.t0 + view.t1) / 2;
      const eps = Math.max(1e-9, span * 1e-6);
      const t = dir > 0 ? nextSpike(allSpikes, mid, eps) : prevSpike(allSpikes, mid, eps);
      if (t == null) return;
      const v = clampTo(t - span / 2, t + span / 2);
      if (v.t0 === view.t0 && v.t1 === view.t1) return;
      go(vs.push(stack, v));
    },
    [allSpikes, clampTo, go, stack, view, whole],
  );
  const spikeSteps = useMemo(() => {
    if (!view) return { prev: false, next: false };
    const mid = (view.t0 + view.t1) / 2;
    const eps = Math.max(1e-9, (view.t1 - view.t0) * 1e-6);
    return {
      prev: prevSpike(allSpikes, mid, eps) != null,
      next: nextSpike(allSpikes, mid, eps) != null,
    };
  }, [allSpikes, view]);

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
  // Same bindings as the Analyze MEA viewer: ←/→ pan half a screen, +/− zoom, Backspace back,
  // Home home. `0` stays untouched (R12.6/R13.7). Esc belongs to the drag in flight (inside
  // `useTimeBrush`) and to nothing else — R14 and R45.3 are untouched.
  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (!view || !whole) return;
      const span = view.t1 - view.t0;
      // ⭐ `n`/`p` step spike to spike — the same two keys as the Analyze MEA viewer. Scoped to
      // the focused close-up, so R45.3's arrow keys and R47.3's Space on the surrounding screens
      // are untouched; `0` stays free (R12.6) and Esc still belongs to the drag (R14).
      if (e.key === 'n' || e.key === 'N' || e.key === 'p' || e.key === 'P') {
        e.preventDefault();
        stepSpike(e.key === 'n' || e.key === 'N' ? 1 : -1);
        return;
      }
      // ⚠️ **A KEY THAT CANNOT MOVE MUST PUSH NOTHING** — at a boundary `clampTo` returns the view
      // he is already on, and pushing it would light up Back and bury real history in duplicates.
      const moved = (v: vs.TimeView): vs.ViewStack | null =>
        v.t0 === view.t0 && v.t1 === view.t1 ? null : vs.push(stack, v);

      let next: vs.ViewStack | null = null;
      if (e.key === 'ArrowLeft') next = moved(clampTo(view.t0 - span / 2, view.t1 - span / 2));
      else if (e.key === 'ArrowRight') next = moved(clampTo(view.t0 + span / 2, view.t1 + span / 2));
      else if (e.key === '+' || e.key === '=') {
        const mid = (view.t0 + view.t1) / 2;
        next = moved(clampTo(mid - span / 4, mid + span / 4));
      } else if (e.key === '-' || e.key === '_') {
        const mid = (view.t0 + view.t1) / 2;
        next = moved(clampTo(mid - span, mid + span));
      } else if (e.key === 'Backspace') next = vs.back(stack);
      else if (e.key === 'Home') next = vs.home(stack);
      // ⛔ `Home` is exempt from the identity test on purpose: pressing it while already home is a
      // real push in matplotlib, and it is undoable with one Back.
      if (next && next !== stack) {
        e.preventDefault();
        go(next);
      }
    },
    [clampTo, go, stack, stepSpike, view, whole],
  );

  // ── Ctrl+wheel zooms about the pointer ────────────────────────────────────────────────────
  // ⛔ The BARE wheel is deliberately not bound (R47.1): the rail is the only scroller on the
  // screen, and stealing his scroll whenever the pointer crosses a chart is exactly the
  // complaint R47 exists for.
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey || !view || !whole) return;
      e.preventDefault();
      const w0 = whole.t0_s ?? 0;
      const w1 = whole.t1_s ?? 0;
      const rect = el.getBoundingClientRect();
      const w = Math.max(1, rect.width - TRACE_PAD.left - TRACE_PAD.right);
      const f = Math.min(1, Math.max(0, (e.clientX - rect.left - TRACE_PAD.left) / w));
      const at = view.t0 + f * (view.t1 - view.t0);
      const k = e.deltaY > 0 ? 1.25 : 0.8;
      const span = Math.min(Math.max((view.t1 - view.t0) * k, minSpanS), w1 - w0);
      const t0 = Math.min(Math.max(at - f * span, w0), w1 - span);
      go(vs.push(stack, { t0, t1: t0 + span }));
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [go, minSpanS, stack, view, whole]);

  const buildEnvelopes = useCallback(() => {
    setBuilding(true);
    setSaid('Reading the recording end to end. This takes about a minute.');
    void startMeaEnvelopeRead(analysisId).catch((e: unknown) => {
      setError(e instanceof Error ? e.message : String(e));
      setBuilding(false);
    });
    // ⛔ No `finally` clearing `building` — the POST returns the moment the job is SUBMITTED. The
    // polling effect above owns the flag, and it is what ends it.
  }, [analysisId]);

  // ── the time under the pointer — same rules as the Analyze MEA viewer ──────────────────────
  // ⭐ Measured against the range the picture is DRAWN from (`data`'s served range), and ⛔ time
  // only, no voltage: MAXWELL §7.6 leaves the amplitude unit deliberately unsettled.
  const trackPointer = useCallback(
    (e: React.PointerEvent<HTMLElement>) => {
      if (!data?.recorded) return;
      const r = e.currentTarget.getBoundingClientRect();
      const rect = plotRect(r.width, r.height, TRACE_PAD);
      const x = e.clientX - r.left;
      const y = e.clientY - r.top;
      setPointerT(inPlot(x, y, rect) ? timeAtX(x, rect, data.t0_s ?? 0, data.t1_s ?? 0) : null);
    },
    [data],
  );

  const flat = data?.health?.flat ?? false;
  const undecodable = Boolean(data?.decode_error);
  const provisional = whole?.recorded ? !(whole.orientation?.confirmed ?? false) : false;
  const spikes = useMemo(() => data?.spikes ?? [], [data]);
  // ⚠️ Memoised for prop identity, like the arrays above — `?? []` inline would repaint both
  // charts on every render of a drag.
  const wholeEpisodes = useMemo(() => whole?.sync_episodes ?? NO_EPISODES, [whole]);
  const dataEpisodes = useMemo(() => data?.sync_episodes ?? NO_EPISODES, [data]);
  const bandFromDrag = useMemo(() => {
    if (!brush.dragging || !view || !boxRef.current) return null;
    const w = Math.max(1, boxRef.current.clientWidth - TRACE_PAD.left - TRACE_PAD.right);
    const f = (x: number) => (x - TRACE_PAD.left) / w;
    return {
      t0: view.t0 + f(brush.x0) * (view.t1 - view.t0),
      t1: view.t0 + f(brush.x1) * (view.t1 - view.t0),
    };
  }, [brush.dragging, brush.x0, brush.x1, view]);

  if (recordings.length === 0) return null;

  return (
    <Panel
      title="Voltage"
      help={
        'The voltage this electrode recorded on the MEA, across the whole session, with the ' +
        'spikes MaxWell detected marked underneath.\n' +
        '\n' +
        'The strip on top always shows the whole recording, with a box marking the stretch you ' +
        'are looking at closely. Drag sideways across either picture to zoom into that stretch; ' +
        'Back walks you out again, like the back button in a browser. Arrow keys move by half a ' +
        'screen, + and - zoom, Backspace goes back, and holding Ctrl while you scroll zooms ' +
        'about the pointer. Prev spike and Next spike jump the view to the nearest detected ' +
        'spike on either side, anywhere in the recording, without changing the zoom — N and P ' +
        'do the same from the keyboard, and Back undoes a jump.\n' +
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
                onClick={() => setRunId(r.run_id)}
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

        {electrode && error && !needsEnvelope && (
          <LiveWarning variant="loud">Could not read the recording: {error}</LiveWarning>
        )}

        {/* ⭐ Not an error: the one-off read has not happened for this recording. Say what is
            missing and offer to do it, rather than showing a broken chart. */}
        {electrode && needsEnvelope && (
          <div data-testid="mea-trace-needs-envelope">
            <LiveWarning variant="warn">
              Camea has not read this recording end to end yet, so it cannot show you the whole of
              it at once. It is a one-off job of about a minute per recording.{' '}
              <Button size="sm" variant="ghost" onClick={buildEnvelopes} disabled={building}>
                {building ? 'Reading…' : 'Read it now'}
              </Button>
            </LiveWarning>
          </div>
        )}

        {electrode && whole && !whole.recorded && (
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

        {electrode && whole?.recorded && data && view && (
          <>
            {/* ⚠️ #3 — identity before signal: if the seating is unconfirmed, which electrode this
                IS has not been established, and that outranks anything about the waveform. */}
            {provisional && (
              <div data-testid="mea-provisional"><LiveWarning variant="warn">
                Provisional pairing. Which way the chip sits in this mosaic has not been confirmed,
                so this trace may belong to a different electrode.
              </LiveWarning></div>
            )}

            {/* ⚠️ #2a — the raw stream could not be read at all (no decoder on this machine). */}
            {undecodable && (
              <div data-testid="mea-undecodable"><LiveWarning variant="warn">
                The waveform could not be read at all. MaxWell compresses the raw recording with
                its own method, and the software that unpacks it (part of MaxLab Live) is not
                installed on this machine. The spike marks below come from the chip&rsquo;s own
                detector and are unaffected.
              </LiveWarning></div>
            )}

            {/* ⚠️ #2 — say it before they read the picture as a silent electrode, and NAME the
                scope of the percentage: it genuinely changes between a live-read stretch and the
                cached whole-recording figure. */}
            {!undecodable && flat && (
              <div data-testid="mea-flat"><LiveWarning variant="warn">
                The waveform did not decode.{' '}
                {Math.round((data.health?.fill_fraction ?? 0) * 100)}% of{' '}
                {data.health_scope === 'recording' ? 'this recording' : 'the stretch shown'} is a
                single repeated value, which no live electrode produces — MaxWell&rsquo;s own
                decoder (part of MaxLab Live) is needed to read it properly. The spike marks below
                are unaffected and remain correct.
              </LiveWarning></div>
            )}

            {/* ── the whole recording, always ─────────────────────────────────────────────── */}
            <div
              className={styles.strip}
              data-testid="mea-trace-overview"
              {...stripBrush.handlers}
            >
              <TraceChart
                trace={NO_TRACE}
                minUv={whole.min_uv}
                maxUv={whole.max_uv}
                t0={whole.t0_s ?? 0}
                t1={whole.t1_s ?? 0}
                spikes={NO_SPIKES}
                syncEpisodes={wholeEpisodes}
                suspect={whole.health?.flat ?? false}
                height={56}
                testId="mea-trace-overview-chart"
                // ⚠️ Its own label: the default announces the spike count, and this chart is given
                // none because it draws none — "0 spikes" here would launder *unreadable* into
                // *silent*, the exact lie this panel exists to refuse.
                ariaLabel={
                  `The whole recording, 0 to ${(whole.t1_s ?? 0).toFixed(0)} seconds. ` +
                  `The stretch shown below is ${view.t0.toFixed(2)} to ${view.t1.toFixed(2)} seconds.`
                }
                band={view}
                bandMinPx={2}
              />
            </div>

            {/* ── the close-up ────────────────────────────────────────────────────────────── */}
            <div
              ref={boxRef}
              className={pending ? `${styles.detail} ${styles.stale}` : styles.detail}
              data-testid="mea-trace-detail"
              tabIndex={0}
              role="application"
              aria-label="The stretch of the recording you are looking at. Drag sideways to zoom in."
              onKeyDown={onKeyDown}
              {...brush.handlers}
              onPointerMove={(e) => {
                brush.handlers.onPointerMove(e);
                trackPointer(e);
              }}
              onPointerLeave={() => setPointerT(null)}
            >
              <TraceChart
                trace={data.trace_uv ?? NO_TRACE}
                minUv={data.min_uv}
                maxUv={data.max_uv}
                t0={data.t0_s ?? 0}
                t1={data.t1_s ?? 0}
                spikes={spikes}
                syncEpisodes={dataEpisodes}
                suspect={flat || undecodable}
                band={bandFromDrag}
              />
              {/* One word, on the dimmed picture: what is on screen is the stretch he just left. */}
              {pending && (
                <span className={styles.staleBadge} data-testid="mea-trace-stale">
                  previous
                </span>
              )}
            </div>

            {/* ⚠️ The readout states the range the server ACTUALLY SERVED — the same range the
                picture above is drawn from. */}
            <TraceNav
              t0={data.t0_s ?? 0}
              t1={data.t1_s ?? 0}
              duration={duration}
              nSpikes={spikes.length}
              canBack={vs.canBack(stack)}
              canForward={vs.canForward(stack)}
              onHome={() => go(vs.home(stack))}
              onBack={() => go(vs.back(stack))}
              onForward={() => go(vs.forward(stack))}
              onPrevSpike={() => stepSpike(-1)}
              onNextSpike={() => stepSpike(1)}
              canPrevSpike={spikeSteps.prev}
              canNextSpike={spikeSteps.next}
              pointerT={pointerT}
            />

            <dl className={styles.facts}>
              <Fact label="Channel" value={String(whole.channel ?? '—')} />
              <Fact label="Chip electrode" value={String(whole.chip_electrode ?? '—')} />
              <Fact
                label="Spikes total"
                value={(whole.n_spikes_total ?? 0).toLocaleString()}
                hint="across the whole recording"
              />
            </dl>

            {/* A canvas that takes the keyboard must say what it did — announced, seen by nobody. */}
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
