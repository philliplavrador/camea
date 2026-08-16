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
import { meaChannelTrace, meaEnvelopes, startMeaEnvelopes, useJob, useStopJob } from '../../api';
import type { MeaChannelTrace, MeaEnvelopeStatus } from '../../api';
import { ApiError } from '../../api/client';
import { TRACE_PAD, TraceChart } from '../../core/trace/TraceChart';
// ⭐ TraceNav + readout live in core/trace since 2026-08-15 — the videomosaic voltage panel is
// their second consumer, and a feature may not import another feature's files.
import { TraceNav } from '../../core/trace/TraceNav';
import { readout } from '../../core/trace/readout';
import { nextSpike, prevSpike } from '../../core/trace/spikeStep';
import { inPlot, plotRect, timeAtX, useTimeBrush } from '../../core/trace/useTimeBrush';
import * as vs from '../../core/trace/viewStack';
import {
  NOT_READ_YET,
  READING_LABEL,
  READ_NOT_POSSIBLE,
  READ_STOPPED,
} from '../../core/trace/wholeRecording';
import { Button, LiveWarning, Panel, Progress, useDelayedFlag } from '../../design';
import { SILENT_MEANING, formatRate } from './activityScale';
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

/** How often to ask whether the one-off end-to-end read has landed — the shelf's cadence. ⚠️ This
 *  is NOT the bar's cadence: the bar follows the job itself through `useJob` (500 ms + a 1 Hz
 *  countdown), and this only answers "is the envelope on disk yet". */
const ENVELOPE_POLL_MS = 2000;

// ⚠️ **MODULE CONSTANTS, NOT `[]` AT THE CALL SITE.** `TraceChart` keys its paint on prop identity,
// so a fresh array literal in JSX repaints the canvas on every parent render — and `MeaTrace`
// re-renders on every pointermove of a drag. This is the same defect `TraceChart` records having
// fixed for its own `syncEpisodes` default; passing `[]` inline reintroduces it one level up. The
// strip in particular has no business repainting while the close-up is being dragged. (In review.)
const NO_TRACE: number[] = [];
const NO_SPIKES: never[] = [];

export interface MeaTraceProps {
  analysisId: string;
  recordingId: string;
  /** The channel of the pad he clicked, or null when nothing is selected yet. */
  channel: number | null;
  /**
   * ⭐ **The stretch the close-up is actually showing** — the SERVED range, the same one the
   * readout states, so anything built on it (the chip's "colours follow the view" mode) can never
   * disagree with the picture. `null` = the whole recording, or nothing selected. Reported when
   * the data lands, not on the gesture, for the same reason the announcement waits.
   */
  onViewChange?: (window: { t0: number; t1: number } | null) => void;
}

export function MeaTrace({ analysisId, recordingId, channel, onViewChange }: MeaTraceProps) {
  // The whole recording, fetched once per pad: the strip's picture, and the source of `duration_s`.
  const [whole, setWhole] = useState<MeaChannelTrace | null>(null);
  // The close-up. Always present whenever `whole` is — see the header on why.
  const [data, setData] = useState<MeaChannelTrace | null>(null);
  const [stack, setStack] = useState<vs.ViewStack>(vs.EMPTY_STACK);
  const [error, setError] = useState<string | null>(null);
  /** True while the close-up on screen is a PREVIOUS stretch — its fetch is still out. */
  const [pending, setPending] = useState(false);
  const [needsEnvelope, setNeedsEnvelope] = useState(false);
  /** The POST that asks for the read is in flight. ⚠️ NOT "a read is running" — that is `envJobId`,
   *  which the POST's own reply already carries, so the bar appears without waiting for a poll. */
  const [building, setBuilding] = useState(false);
  /** The end-to-end read running for THIS recording, or '' — the job the bar follows (R48). */
  const [envJobId, setEnvJobId] = useState('');
  /** 🔴 R48.9 — what to say once the wait has ended and the recording still cannot be shown whole. */
  const [readEnded, setReadEnded] = useState<string | null>(null);
  /** A read for this recording has been seen running during this wait. Refs, not state: they steer
   *  which sentence R48.9 owes him, and neither should render anything by changing. */
  const sawJob = useRef(false);
  /** The wait is ours to report on — he asked for it, or the panel found one already going. */
  const watching = useRef(false);
  // Bumped when a backfill finishes, purely to re-run the arrival fetch. Without it the panel keeps
  // showing "not read yet" after the job it started has finished — see the effect below.
  const [reload, setReload] = useState(0);
  const [said, setSaid] = useState('');
  /** The moment the cursor is over on the close-up, or null when it is off the picture. */
  const [pointerT, setPointerT] = useState<number | null>(null);
  const boxRef = useRef<HTMLDivElement | null>(null);
  // Every detail fetch carries a ticket; a late reply holding a stale one is dropped. Without it a
  // slow wide request can land after a fast narrow one and redraw the view he already left.
  const ticket = useRef(0);

  const view = vs.current(stack);
  const duration = whole?.duration_s ?? 0;
  const samplingHz = whole?.sampling_hz ?? 0;
  const minSpanS = samplingHz > 0 ? MIN_SPAN_SAMPLES / samplingHz : 0;

  // ⏱️ **THE READ'S OWN NUMBERS (BEHAVIOUR R48).** `useJob` owns the ticking countdown and R8.2's
  // re-anchor discipline; this panel only renders what it hands back. ⛔ Never re-time it here.
  const readJob = useJob(envJobId || null);
  const stopJob = useStopJob();
  // R48.1 — a pad read is ~50 ms, so the *word* waits 400 ms. The empty chart below does not: it
  // holds the panel's shape from the first frame, which is what R48.10 is actually about here.
  const padWait = useDelayedFlag(channel != null && whole == null && !error && !needsEnvelope);

  // ── arrival: the whole recording, in one request ──────────────────────────────────────────
  // ⭐ Asked for with no `t1` and a `max_points`, which is the server's way of saying "all of it,
  // folded to this many columns". It doubles as the opening close-up, so a pad costs ONE request.
  useEffect(() => {
    if (channel == null) {
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
  }, [analysisId, recordingId, channel, reload]);

  /**
   * Fold one envelope-status reply into this panel. ⭐ **EVERY OUTCOME IS SAID (R48.9).** There are
   * exactly three, and the one that used to be silent is the one that happens for real:
   *
   *   • ready → re-run the arrival fetch and show the recording;
   *   • a job → follow it, and the bar carries pct / ETA / Stop;
   *   • neither, once we were watching → **the wait is over and it did not work**, which an
   *     ActivityScan reaches every time (no continuous trace ⇒ nothing to read ⇒ `ready` never
   *     comes). This used to `setBuilding(false)` and leave the panel offering the same button.
   */
  const applyStatus = useCallback(
    (s: MeaEnvelopeStatus) => {
      const mine = (s.recordings ?? []).find((r) => r.recording_id === recordingId) ?? null;
      const jid = mine?.job_id ?? '';
      setEnvJobId(jid);
      if (jid) {
        sawJob.current = true;
        watching.current = true;
        setReadEnded(null);
      }
      if (mine?.ready) {
        sawJob.current = false;
        watching.current = false;
        setBuilding(false);
        setNeedsEnvelope(false);
        setError(null);
        setReadEnded(null);
        setSaid('The whole recording is ready.');
        setReload((n) => n + 1);
        return;
      }
      if (!jid && watching.current) {
        // 🔴 R48.9 — a countdown that reaches zero and vanishes with no sentence is WORSE than the
        // bare "Reading…" it replaced. Which sentence depends on whether a job ever ran, which is
        // the only thing the wire tells these two cases apart by.
        setBuilding(false);
        setReadEnded(sawJob.current ? READ_STOPPED : READ_NOT_POSSIBLE);
        sawJob.current = false;
        watching.current = false;
      }
    },
    [recordingId],
  );

  // ⭐ **ONE LOOK THE MOMENT THE RECORDING CANNOT BE SHOWN WHOLE.** A read may already be running —
  // every import starts one — and he must meet its bar rather than a button offering to start what
  // is already going. ⛔ Not a poll: this fires once per refusal.
  useEffect(() => {
    if (!needsEnvelope) {
      setEnvJobId('');
      setReadEnded(null);
      sawJob.current = false;
      watching.current = false;
      return;
    }
    let stop = false;
    void meaEnvelopes(analysisId)
      .then((s) => {
        if (!stop) applyStatus(s);
      })
      .catch(() => {
        // Quiet: not being able to ask about the read is not his data going missing, and the offer
        // below still works.
      });
    return () => {
      stop = true;
    };
  }, [analysisId, needsEnvelope, applyStatus]);

  // ⚠️ **WAIT FOR THE READ AND THEN SHOW THE RECORDING.** Starting the job is not the feature;
  // seeing the trace afterwards is. Without this the job finishes and the panel is still showing
  // "Camea has not read this recording end to end yet", and the only way out is to click a
  // different pad and come back — a button that appears to do nothing. (Caught in review.)
  // ⛔ Armed only while there is something to wait FOR: a screen that polls forever keeps a
  // laptop's fan on for no reason, and R48.9's ending is what takes the arm away.
  useEffect(() => {
    if (!needsEnvelope || !(building || envJobId)) return;
    let stop = false;
    const timer = setInterval(() => {
      void meaEnvelopes(analysisId)
        .then((s) => {
          if (!stop) applyStatus(s);
        })
        .catch(() => {});
    }, ENVELOPE_POLL_MS);
    return () => {
      stop = true;
      clearInterval(timer);
    };
  }, [analysisId, needsEnvelope, building, envJobId, applyStatus]);

  // ── the close-up follows the view he is standing on ───────────────────────────────────────
  useEffect(() => {
    if (channel == null || view == null || whole == null) return;
    // The opening view IS the whole recording, which we already hold. Do not re-fetch it.
    if (view.t0 === whole.t0_s && view.t1 === whole.t1_s) {
      setData(whole);
      setPending(false);
      return;
    }
    let cancelled = false;
    const mine = ++ticket.current;
    // ⭐ **THE PREVIOUS CHART STAYS UP, AND SAYS SO** (2026-08-16). While this fetch is out the
    // picture on screen is the stretch he just left — it is dimmed and badged rather than blanked,
    // because a blink on every zoom is worse than an honest "previous".
    setPending(true);
    const timer = setTimeout(() => {
      void meaChannelTrace(analysisId, recordingId, channel, {
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
          // ⛔ **BLANK, NEVER STALE CHARTS UNDER A WARNING.** A picture of the stretch he left,
          // drawn under "could not read the recording", reads as the stretch that failed.
          setData(null);
          setPending(false);
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
  const go = useCallback((next: vs.ViewStack) => setStack(next), []);

  // ⚠️ **THE ANNOUNCEMENT WAITS FOR THE DATA, AND THAT IS THE POINT.** Announcing at the moment of
  // navigation is a keystroke earlier but the spike count is not known yet, so every keyboard zoom
  // said "0 spikes in view" — false, and false in exactly the place a sighted user reads off the
  // picture. It says what actually arrived, from the range the server actually served.
  useEffect(() => {
    if (!data?.recorded) return;
    setSaid(readout(data.t0_s, data.t1_s, data.duration_s, data.spikes?.length ?? 0));
  }, [data]);

  // ⭐ Report the stretch actually being shown, when its data lands. `data === whole` is the
  // whole-recording view by construction (the arrival fetch and Home both hand the same object
  // back), so the identity test is exact and costs nothing.
  useEffect(() => {
    if (!onViewChange) return;
    if (channel == null || data == null || whole == null || !data.recorded || data === whole) {
      onViewChange(null);
      return;
    }
    onViewChange({ t0: data.t0_s, t1: data.t1_s });
  }, [channel, data, whole, onViewChange]);

  const onSelect = useCallback(
    (v: vs.TimeView) => go(vs.push(stack, v)),
    [go, stack],
  );

  /** A candidate range, clamped to the recording and the zoom floor. Shared by the keys, the
   *  wheel could use it too, and spike stepping — one clamp, so they cannot disagree. */
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

  // ── spike to spike ─────────────────────────────────────────────────────────────────────────
  // ⭐ Steps against the WHOLE recording's spike list (`whole.spikes` covers the full served
  // range), so a jump lands far beyond the loaded close-up. The view recenters on the target at
  // its current width and PUSHES — Back undoes a jump like any other move.
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
      // Pinned at an edge the jump may resolve to the view he is already on — push nothing.
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
  // ⚠️ This app has shipped a keyboard-dead canvas once and review caught a second. `+`/`-` mean
  // zoom and `0` is left alone because it means 1:1 in the viewer and 1:1 has no meaning on a time
  // axis (R12.6 / R13.7). Esc belongs to the drag in flight and to nothing else — R14 is untouched.
  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (!view || !whole) return;
      const span = view.t1 - view.t0;
      // ⭐ `n`/`p` step spike to spike (2026-08-16). Free keys on this panel: arrows pan, +/− zoom,
      // Backspace/Home are history, `0` is untouchable (R12.6) and Esc belongs to the drag (R14).
      if (e.key === 'n' || e.key === 'N' || e.key === 'p' || e.key === 'P') {
        e.preventDefault();
        stepSpike(e.key === 'n' || e.key === 'N' ? 1 : -1);
        return;
      }
      // ⚠️ **A KEY THAT CANNOT MOVE MUST PUSH NOTHING.** `vs.push` always returns a new stack, so
      // `next !== stack` never catches a no-op — and at a boundary `clampTo` returns the view he is
      // already on. Pressing ArrowLeft on the opening view (which spans the whole recording, i.e.
      // sits at both edges at once) would light up Back, fire a fetch for the identical window, and
      // bury real history under duplicates he then has to step through. The view stack states that
      // refusing a no-op is the caller's job — `useTimeBrush` does it for a click; this does it for
      // a key. (Caught in review.)
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
      // real push in matplotlib, and the view stack pins that. It is undoable with one Back.
      if (next && next !== stack) {
        e.preventDefault();
        go(next);
      }
    },
    [clampTo, go, stack, stepSpike, view, whole],
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
    setReadEnded(null);
    watching.current = true;
    // ⛔ No "this takes about a minute": one recording alone does, five queued behind each other do
    // not, and the bar says which this is (R48).
    setSaid('Reading the recording end to end.');
    // ⭐ The POST's own reply already carries this recording's job id, so the bar is up on the next
    // frame rather than up to one poll later. `building` therefore clears here — it means "the
    // request is out", and what replaces it is the job, not a disabled button.
    void startMeaEnvelopes(analysisId)
      .then((s) => {
        applyStatus(s);
        setBuilding(false);
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : String(e));
        setBuilding(false);
        watching.current = false;
      });
  }, [analysisId, applyStatus]);

  // ── the time under the pointer ─────────────────────────────────────────────────────────────
  // ⭐ Measured against the range the picture is actually DRAWN from (`data`'s served range, the
  // same one the readout states), not the view in flight — during a load the old picture is still
  // on screen and a time read off the new axis would point at the wrong sample. ⛔ Time only, no
  // voltage: MAXWELL §7.6 leaves the amplitude unit deliberately unsettled.
  const trackPointer = useCallback(
    (e: React.PointerEvent<HTMLElement>) => {
      if (!data?.recorded) return;
      const r = e.currentTarget.getBoundingClientRect();
      const rect = plotRect(r.width, r.height, TRACE_PAD);
      const x = e.clientX - r.left;
      const y = e.clientY - r.top;
      setPointerT(inPlot(x, y, rect) ? timeAtX(x, rect, data.t0_s, data.t1_s) : null);
    },
    [data],
  );

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
        'while you scroll zooms about the pointer.\n' +
        '\n' +
        'Prev spike and Next spike jump the view to the nearest detected spike on either side, ' +
        'anywhere in the recording, without changing the zoom — N and P do the same from the ' +
        'keyboard, and Back undoes a jump.'
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
            {envJobId ? (
              // ⏱️ **THE SCREEN HE COMPLAINED ABOUT (R48).** This said the single word `Reading…`
              // while the percentage was already on the wire, already fetched every 2 s, and thrown
              // away. It follows the JOB now, so the countdown ticks between polls (R8.2) and the
              // turnstile's own message — "waiting for 3 recordings in front of it to be read" —
              // arrives with a real ETA rather than as silence.
              <Progress
                label={readJob.job?.said_as || READING_LABEL}
                pct={readJob.pct}
                etaText={readJob.etaText}
                elapsedText={readJob.elapsedText}
                phase={readJob.phase}
                message={readJob.message}
                // R48.7 — wired, never decorative. A Stop that races the end of the read is not an
                // error to shout about (`useStopJob` swallows that 409), and anything else shows up
                // on the next poll: the job either stops or it does not, and the bar keeps saying so.
                onStop={() => void stopJob(envJobId).catch(() => {})}
                data-testid="mea-trace-reading"
              />
            ) : (
              <LiveWarning variant="warn">
                {NOT_READ_YET}{' '}
                <Button size="sm" variant="ghost" onClick={buildEnvelopes} disabled={building}>
                  {building ? 'Reading…' : 'Read it now'}
                </Button>
              </LiveWarning>
            )}
            {/* 🔴 R48.9 — the wait ended and the recording still cannot be shown whole. SAY it. */}
            {readEnded && (
              <LiveWarning variant="warn">
                <span data-testid="mea-trace-read-ended">{readEnded}</span>
              </LiveWarning>
            )}
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

        {/* ⭐ **R48.10 — A PAD CLICK MUST NOT EMPTY THE PANEL.** The arrival effect clears `whole`
            and `data`, and the idle hint is gated on "nothing selected", so between the click and
            the reply this panel had NOTHING in it at all — not even the box the chart is about to
            fill. `TraceChart`'s `placeholder` was built for exactly this and neither consumer
            passed it. ⛔ Not a `<Progress>`: a ~50 ms pad read is the sub-second interactive read
            R48 explicitly says to answer with the picture. The empty axes go up on the first frame
            so nothing jumps; the word waits out R48.1's grace. */}
        {channel != null && !error && !needsEnvelope && whole == null && (
          <div data-testid="mea-trace-loading">
            <TraceChart
              trace={NO_TRACE}
              spikes={NO_SPIKES}
              t0={0}
              t1={0}
              placeholder={padWait ? 'Reading this pad…' : ''}
              // ⚠️ Its own testid: sharing `mea-trace-chart` would let a test asserting the chart
              // is up pass against an empty frame.
              testId="mea-trace-placeholder-chart"
              ariaLabel="Reading this pad."
            />
          </div>
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
            {/* ⚠️ **THE PERCENTAGE NAMES WHAT IT MEASURED.** A narrow window is read live and its
                health is that window's; a wide one comes from the cache and carries the whole
                recording's. The rail fraction really does differ with window length (1.000 over 1 s
                vs 0.827 over 30 s on one of his), so this number changes as he zooms — and a number
                that changes while the sentence around it claims a fixed scope is a number he cannot
                trust. `health_scope` says which; say it. (Caught in review.) */}
            {!undecodable && flat && (
              <div data-testid="mea-trace-flat">
                <LiveWarning variant="warn">
                  The waveform did not decode.{' '}
                  {Math.round((data.health?.fill_fraction ?? 0) * 100)}% of{' '}
                  {data.health_scope === 'recording' ? 'this recording' : 'the stretch shown'} is a
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
                trace={NO_TRACE}
                minUv={whole.min_uv}
                maxUv={whole.max_uv}
                t0={whole.t0_s}
                t1={whole.t1_s}
                spikes={NO_SPIKES}
                suspect={whole.health?.flat ?? false}
                height={56}
                // ⚠️ Its own testid: two charts on one screen sharing one makes every bare
                // `getByTestId('mea-trace-chart')` a strict-mode failure.
                testId="mea-trace-overview-chart"
                // ⚠️ And its own label. The default states the spike count, and this chart is
                // given none because it draws none — so the default would announce "0 spikes" for
                // a pad that fired thousands of times. On this screen of all screens, that is the
                // laundering of *unreadable* into *silent* the whole panel exists to refuse.
                ariaLabel={
                  `The whole recording, 0 to ${whole.t1_s.toFixed(0)} seconds. ` +
                  `The stretch shown below is ${view.t0.toFixed(2)} to ${view.t1.toFixed(2)} seconds.`
                }
                // ⚠️ `view` itself, not a fresh `{t0, t1}` literal: it is the entry object out of the
                // view stack, whose identity only changes when a genuinely new view is pushed, so
                // the strip does not repaint through a drag on the close-up.
                band={view}
                // ⚠️ Zoomed deep into a 300 s recording the box is a fraction of a pixel wide. A
                // "you are here" marker you cannot see is the same as not having one.
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
                t0={data.t0_s}
                t1={data.t1_s}
                spikes={spikes}
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

            {/* ⚠️ The readout states the range the server ACTUALLY SERVED, not the one that was
                asked for — the same range the picture above is drawn from. They differ by up to
                one stored bucket when a wide view comes from the cache, and a caption that
                disagreed with its own chart would be the worst kind of small lie. */}
            <TraceNav
              t0={data.t0_s}
              t1={data.t1_s}
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
