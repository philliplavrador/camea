// THE TRACE CHART — one electrode's stored waveform, its spikes, and the lamp episodes, drawn on
// one shared time axis. Canvas, not SVG: a one-second window is 20,000 samples and an SVG path with
// 20k points is a scroll-killer on a panel that redraws on every click.
//
// ⭐ **CORE, NOT A FEATURE** (moved out of `features/electrodes/` on 2026-08-14, plan 003).
// It lived beside `MeaTracePanel` because the video pipeline's electrode panel was the only screen
// that drew a waveform. `Analyze MEA` is the second, and ⛔ **a feature may not import another
// feature** — `app/FeatureGate.tsx` is the only seam allowed to name features, precisely so a task
// can be added or retired without unpicking imports from three other screens. Same argument, and
// the same fix, as `core/picker/FolderPicker` in plan 002.
//
// ⚠️ Nothing about the component changed in the move: same props, same drawing, same testid
// (`mea-trace-chart`). Its two importers ask different questions — one about a pad clicked in a
// mosaic, one about a pad clicked on the chip itself — and this draws for both without knowing
// which, because it draws what it is given and decides nothing (see below).
//
// ⭐ **IT DRAWS A MIN/MAX ENVELOPE, NOT EVERY SAMPLE.** At 20 kHz there are far more samples than
// pixels, so each column shows the range its samples covered. That is the honest reduction for a
// spiky signal: plain decimation would drop the spikes (they are 1-2 samples wide at this zoom) and
// draw a calm line over a burst. Whatever the eye sees here, a spike is never invisible.
//
// ⭐ **AND THE SERVER MAY HAVE DONE THAT REDUCTION ALREADY** (plan 004). Ask for a window wider than
// the API will send as raw samples and it answers with `min_uv`/`max_uv` instead — the identical
// arithmetic, done where the data already is. Pass those as `minUv`/`maxUv` and this draws them
// directly. ⛔ Both paths draw the SAME picture; the only difference is who did the folding.
//
// ⚠️ **THIS COMPONENT NEVER DECIDES WHETHER THE TRACE IS BELIEVABLE.** It draws what it is given.
// The caller reads `health.flat` and says so on the panel — see MeaTracePanel.
//
// ⚠️ **THE OTHER CONSUMER HAS NO TEST COVERAGE.** `features/electrodes/MeaTracePanel` is not
// asserted by any spec — not its chart, not its slider, not its lamp shading. So every prop added
// here is **optional with a default that reproduces the old behaviour exactly**, and the drawing
// path for a caller that passes none of them is byte-for-byte what it was. That is structural
// safety, not carefulness.

import { useCallback, useEffect, useRef } from 'react';
import type { MeaSpike, MeaSyncEpisode } from '../../api';
import styles from './TraceChart.module.css';

/** The gutters around the plot box, in CSS px. Exported because `useTimeBrush` must convert a
 *  pointer x through the SAME geometry — a press in the left number gutter is not a time. */
export const TRACE_PAD = { left: 46, right: 8, top: 8, bottom: 18 } as const;

// ⚠️ A module constant, NOT a `= []` default parameter. As a default it minted a fresh array on
// every render, so the effect's dependency array never matched and the canvas repainted on EVERY
// parent render — cheap when the panel was static, not cheap once a parent re-renders through a
// drag. (Found in review, plan 004.)
const NO_EPISODES: MeaSyncEpisode[] = [];

export interface TraceChartProps {
  /** The waveform in microvolts, evenly spaced across [t0, t1]. */
  trace: number[];
  t0: number;
  t1: number;
  spikes: MeaSpike[];
  /** Server-reduced envelope: the lowest/highest µV per column, evenly spaced across [t0, t1].
   *  When both are present and non-empty they are drawn INSTEAD of `trace`. */
  minUv?: number[];
  maxUv?: number[];
  /** 2P lamp artefacts — the deliberate sync marks. Shaded, never removed. */
  syncEpisodes?: MeaSyncEpisode[];
  /** Dim the waveform because it did not decode (the caller's `health.flat`). */
  suspect?: boolean;
  height?: number;
  /** A time range to shade, in seconds — the drag in progress, or (on the overview strip) the
   *  stretch the close-up is currently showing. Full height, x only. */
  band?: { t0: number; t1: number } | null;
  /** Floor for the band's drawn width, in CSS px. The overview's "you are here" box must never
   *  become invisible at deep zoom; a drag in progress wants no floor. */
  bandMinPx?: number;
  /** Drawn instead of the waveform when there is nothing to draw — e.g. "still reading". */
  placeholder?: string;
}

export function TraceChart({
  trace,
  t0,
  t1,
  spikes,
  minUv,
  maxUv,
  syncEpisodes = NO_EPISODES,
  suspect = false,
  height = 150,
  band = null,
  bandMinPx = 0,
  placeholder = '',
}: TraceChartProps): React.JSX.Element {
  const ref = useRef<HTMLCanvasElement | null>(null);

  const draw = useCallback(() => {
    const cv = ref.current;
    if (!cv) return;
    const dpr = window.devicePixelRatio || 1;
    const cssW = cv.clientWidth || 480;
    cv.width = Math.round(cssW * dpr);
    cv.height = Math.round(height * dpr);
    const g = cv.getContext('2d');
    if (!g) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, cssW, height);

    const css = getComputedStyle(cv);
    const ink = css.getPropertyValue('--trace-ink').trim() || '#2a6fb0';
    const axis = css.getPropertyValue('--trace-axis').trim() || '#8a8f98';
    const spikeCol = css.getPropertyValue('--trace-spike').trim() || '#c0392b';
    const lampCol = css.getPropertyValue('--trace-lamp').trim() || 'rgba(240,160,32,.30)';
    const bandFill = css.getPropertyValue('--trace-band').trim() || 'rgba(90,150,255,.22)';
    const bandEdge = css.getPropertyValue('--trace-band-edge').trim() || 'rgba(90,150,255,.85)';

    const w = Math.max(1, cssW - TRACE_PAD.left - TRACE_PAD.right);
    const h = Math.max(1, height - TRACE_PAD.top - TRACE_PAD.bottom);
    const span = Math.max(1e-9, t1 - t0);
    const xOf = (t: number): number => TRACE_PAD.left + ((t - t0) / span) * w;

    // ── the lamp episodes go down first: they are context behind the signal ──────────────────
    g.fillStyle = lampCol;
    for (const e of syncEpisodes) {
      const a = Math.max(TRACE_PAD.left, xOf(e.start_s));
      const b = Math.min(TRACE_PAD.left + w, xOf(e.end_s));
      if (b > a) g.fillRect(a, TRACE_PAD.top, b - a, h);
    }

    // ── axes ────────────────────────────────────────────────────────────────────────────────
    g.strokeStyle = axis;
    g.lineWidth = 1;
    g.beginPath();
    g.moveTo(TRACE_PAD.left, TRACE_PAD.top);
    g.lineTo(TRACE_PAD.left, TRACE_PAD.top + h);
    g.lineTo(TRACE_PAD.left + w, TRACE_PAD.top + h);
    g.stroke();

    // Server-reduced columns take precedence: they ARE the trace at this width.
    const envLo = minUv && maxUv && minUv.length > 0 && minUv.length === maxUv.length ? minUv : null;
    const envHi = envLo ? maxUv! : null;
    const haveSignal = envLo !== null || trace.length > 0;

    if (haveSignal) {
      let lo = Infinity;
      let hi = -Infinity;
      if (envLo && envHi) {
        for (const v of envLo) if (v < lo) lo = v;
        for (const v of envHi) if (v > hi) hi = v;
      } else {
        for (const v of trace) {
          if (v < lo) lo = v;
          if (v > hi) hi = v;
        }
      }
      if (!(hi > lo)) {
        hi = lo + 1;
        lo -= 1;
      }
      const pad = (hi - lo) * 0.06;
      lo -= pad;
      hi += pad;
      const yOf = (v: number): number => TRACE_PAD.top + h - ((v - lo) / (hi - lo)) * h;

      // y labels in mV — µV would read as five-digit noise on a railed window
      g.fillStyle = axis;
      g.font = '10px system-ui, sans-serif';
      g.textAlign = 'right';
      g.textBaseline = 'middle';
      for (const v of [lo, (lo + hi) / 2, hi]) {
        g.fillText((v / 1000).toFixed(2), TRACE_PAD.left - 5, yOf(v));
      }

      // ── the min/max envelope ──────────────────────────────────────────────────────────────
      g.strokeStyle = ink;
      g.globalAlpha = suspect ? 0.45 : 1;
      g.lineWidth = 1;
      g.beginPath();
      if (envLo && envHi) {
        // Already one pair per column. Spread them across the plot box as they came.
        const cols = envLo.length;
        for (let c = 0; c < cols; c++) {
          const x = TRACE_PAD.left + ((c + 0.5) / cols) * w;
          g.moveTo(x, yOf(envLo[c]!));
          g.lineTo(x, yOf(envHi[c]!));
        }
        // ⭐ **CONNECT THEM ONCE THERE ARE FEWER COLUMNS THAN PIXELS.** Zoomed in far enough that
        // each column is one stored sample, `lo === hi` and the loop above draws zero-height ticks
        // — i.e. a scatter of dots where he expects a waveform. Below ~2 samples per pixel the
        // honest picture is the real polyline, which is pyqtgraph's rule for exactly this reason
        // ("stop decimating below ~2 samples per pixel", `autoDownsampleFactor`). Above it the test
        // never fires and nothing is connected that should not be.
        if (cols * 2 <= w) {
          for (let c = 0; c < cols; c++) {
            const x = TRACE_PAD.left + ((c + 0.5) / cols) * w;
            const y = yOf((envLo[c]! + envHi[c]!) / 2);
            if (c === 0) g.moveTo(x, y);
            else g.lineTo(x, y);
          }
        }
      } else {
        const cols = Math.min(w, trace.length);
        const per = trace.length / cols;
        for (let c = 0; c < cols; c++) {
          const a = Math.floor(c * per);
          const b = Math.min(trace.length, Math.max(a + 1, Math.floor((c + 1) * per)));
          let mn = Infinity;
          let mx = -Infinity;
          for (let i = a; i < b; i++) {
            const v = trace[i]!;
            if (v < mn) mn = v;
            if (v > mx) mx = v;
          }
          const x = TRACE_PAD.left + (c / cols) * w + 0.5;
          g.moveTo(x, yOf(mn));
          g.lineTo(x, yOf(mx));
        }
      }
      g.stroke();
      g.globalAlpha = 1;
    } else if (placeholder) {
      g.fillStyle = axis;
      g.font = '11px system-ui, sans-serif';
      g.textAlign = 'center';
      g.textBaseline = 'middle';
      g.fillText(placeholder, TRACE_PAD.left + w / 2, TRACE_PAD.top + h / 2);
    }

    // ── spikes last, as ticks under the axis: they are TRUSTWORTHY even when the trace is not ──
    // ⭐ **AND ONCE THERE ARE MORE OF THEM THAN PIXELS, THE ROW BECOMES A DENSITY.** A busy pad over
    // a whole recording is thousands of ticks across a few hundred pixels, and drawn at full
    // strength they merge into a solid bar that reads as a rule under the axis rather than as data
    // — it says only "there were spikes", which he already knows. Stroked separately at low alpha
    // instead, they accumulate: the busy stretches darken and the quiet ones stay pale, so the row
    // answers "when was this pad busy" at a glance. ⛔ No spike is ever dropped, at any zoom.
    g.strokeStyle = spikeCol;
    g.lineWidth = 1.5;
    const dense = spikes.length > w;
    if (dense) {
      g.globalAlpha = 0.28;
      for (const s of spikes) {
        const x = xOf(s.t_s);
        if (x < TRACE_PAD.left || x > TRACE_PAD.left + w) continue;
        g.beginPath();
        g.moveTo(x, TRACE_PAD.top + h);
        g.lineTo(x, TRACE_PAD.top + h + 5);
        g.stroke();
      }
      g.globalAlpha = 1;
    } else {
      g.beginPath();
      for (const s of spikes) {
        const x = xOf(s.t_s);
        if (x < TRACE_PAD.left || x > TRACE_PAD.left + w) continue;
        g.moveTo(x, TRACE_PAD.top + h);
        g.lineTo(x, TRACE_PAD.top + h + 5);
      }
      g.stroke();
    }

    // ── the band: where you are, or where you are dragging ──────────────────────────────────
    if (band) {
      const a = Math.max(TRACE_PAD.left, Math.min(TRACE_PAD.left + w, xOf(band.t0)));
      const b = Math.max(TRACE_PAD.left, Math.min(TRACE_PAD.left + w, xOf(band.t1)));
      // ⚠️ A floor on the DRAWN width, never on the range itself. Zoomed deep into a 300 s
      // recording the box is a fraction of a pixel wide, and a "you are here" marker you cannot
      // see is the same as not having one.
      let x0 = Math.min(a, b);
      let x1 = Math.max(a, b);
      if (bandMinPx > 0 && x1 - x0 < bandMinPx) {
        const mid = (x0 + x1) / 2;
        x0 = Math.max(TRACE_PAD.left, mid - bandMinPx / 2);
        x1 = Math.min(TRACE_PAD.left + w, x0 + bandMinPx);
      }
      g.fillStyle = bandFill;
      g.fillRect(x0, TRACE_PAD.top, Math.max(1, x1 - x0), h);
      g.strokeStyle = bandEdge;
      g.lineWidth = 1;
      g.beginPath();
      g.moveTo(x0 + 0.5, TRACE_PAD.top);
      g.lineTo(x0 + 0.5, TRACE_PAD.top + h);
      g.moveTo(x1 - 0.5, TRACE_PAD.top);
      g.lineTo(x1 - 0.5, TRACE_PAD.top + h);
      g.stroke();
    }

    // ── time labels ─────────────────────────────────────────────────────────────────────────
    g.fillStyle = axis;
    g.font = '10px system-ui, sans-serif';
    g.textBaseline = 'top';
    g.textAlign = 'left';
    g.fillText(`${t0.toFixed(2)} s`, TRACE_PAD.left, TRACE_PAD.top + h + 6);
    g.textAlign = 'right';
    g.fillText(`${t1.toFixed(2)} s`, TRACE_PAD.left + w, TRACE_PAD.top + h + 6);
  }, [
    trace,
    t0,
    t1,
    spikes,
    minUv,
    maxUv,
    syncEpisodes,
    suspect,
    height,
    band,
    bandMinPx,
    placeholder,
  ]);

  useEffect(() => {
    draw();
  }, [draw]);

  // ⚠️ `clientWidth` is read inside the paint, so a container that changes width leaves the picture
  // stretched AND — now that a pointer x is converted back into a time through the same geometry —
  // leaves every drag landing on the wrong second. Repaint on resize. (Plan 004; the chart never
  // had one, which was invisible while nothing converted pixels back into data.)
  useEffect(() => {
    const cv = ref.current;
    if (!cv || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => draw());
    ro.observe(cv);
    return () => ro.disconnect();
  }, [draw]);

  return (
    <canvas
      ref={ref}
      className={styles.canvas}
      style={{ height }}
      data-testid="mea-trace-chart"
      role="img"
      aria-label={`Voltage trace from ${t0.toFixed(2)} to ${t1.toFixed(2)} seconds, ${spikes.length} spikes`}
    />
  );
}
