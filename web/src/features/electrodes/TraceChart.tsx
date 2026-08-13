// THE TRACE CHART — one electrode's stored waveform, its spikes, and the lamp episodes, drawn on
// one shared time axis. Canvas, not SVG: a one-second window is 20,000 samples and an SVG path with
// 20k points is a scroll-killer on a panel that redraws on every click.
//
// ⭐ **IT DRAWS A MIN/MAX ENVELOPE, NOT EVERY SAMPLE.** At 20 kHz there are far more samples than
// pixels, so each column shows the range its samples covered. That is the honest reduction for a
// spiky signal: plain decimation would drop the spikes (they are 1-2 samples wide at this zoom) and
// draw a calm line over a burst. Whatever the eye sees here, a spike is never invisible.
//
// ⚠️ **THIS COMPONENT NEVER DECIDES WHETHER THE TRACE IS BELIEVABLE.** It draws what it is given.
// The caller reads `health.flat` and says so on the panel — see MeaTracePanel.

import { useEffect, useRef } from 'react';
import type { MeaSpike, MeaSyncEpisode } from '../../api';
import styles from './TraceChart.module.css';

export interface TraceChartProps {
  /** The waveform in microvolts, evenly spaced across [t0, t1]. */
  trace: number[];
  t0: number;
  t1: number;
  spikes: MeaSpike[];
  /** 2P lamp artefacts — the deliberate sync marks. Shaded, never removed. */
  syncEpisodes?: MeaSyncEpisode[];
  /** Dim the waveform because it did not decode (the caller's `health.flat`). */
  suspect?: boolean;
  height?: number;
}

const PAD_L = 46;
const PAD_R = 8;
const PAD_T = 8;
const PAD_B = 18;

export function TraceChart({
  trace,
  t0,
  t1,
  spikes,
  syncEpisodes = [],
  suspect = false,
  height = 150,
}: TraceChartProps): React.JSX.Element {
  const ref = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
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

    const w = Math.max(1, cssW - PAD_L - PAD_R);
    const h = Math.max(1, height - PAD_T - PAD_B);
    const span = Math.max(1e-9, t1 - t0);
    const xOf = (t: number): number => PAD_L + ((t - t0) / span) * w;

    // ── the lamp episodes go down first: they are context behind the signal ──────────────────
    g.fillStyle = lampCol;
    for (const e of syncEpisodes) {
      const a = Math.max(PAD_L, xOf(e.start_s));
      const b = Math.min(PAD_L + w, xOf(e.end_s));
      if (b > a) g.fillRect(a, PAD_T, b - a, h);
    }

    // ── axes ────────────────────────────────────────────────────────────────────────────────
    g.strokeStyle = axis;
    g.lineWidth = 1;
    g.beginPath();
    g.moveTo(PAD_L, PAD_T);
    g.lineTo(PAD_L, PAD_T + h);
    g.lineTo(PAD_L + w, PAD_T + h);
    g.stroke();

    if (trace.length > 0) {
      let lo = Infinity;
      let hi = -Infinity;
      for (const v of trace) {
        if (v < lo) lo = v;
        if (v > hi) hi = v;
      }
      if (!(hi > lo)) {
        hi = lo + 1;
        lo -= 1;
      }
      const pad = (hi - lo) * 0.06;
      lo -= pad;
      hi += pad;
      const yOf = (v: number): number => PAD_T + h - ((v - lo) / (hi - lo)) * h;

      // y labels in mV — µV would read as five-digit noise on a railed window
      g.fillStyle = axis;
      g.font = '10px system-ui, sans-serif';
      g.textAlign = 'right';
      g.textBaseline = 'middle';
      for (const v of [lo, (lo + hi) / 2, hi]) {
        g.fillText((v / 1000).toFixed(2), PAD_L - 5, yOf(v));
      }

      // ── the min/max envelope ──────────────────────────────────────────────────────────────
      g.strokeStyle = ink;
      g.globalAlpha = suspect ? 0.45 : 1;
      g.lineWidth = 1;
      g.beginPath();
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
        const x = PAD_L + (c / cols) * w + 0.5;
        g.moveTo(x, yOf(mn));
        g.lineTo(x, yOf(mx));
      }
      g.stroke();
      g.globalAlpha = 1;
    }

    // ── spikes last, as ticks under the axis: they are TRUSTWORTHY even when the trace is not ──
    g.strokeStyle = spikeCol;
    g.lineWidth = 1.5;
    g.beginPath();
    for (const s of spikes) {
      const x = xOf(s.t_s);
      if (x < PAD_L || x > PAD_L + w) continue;
      g.moveTo(x, PAD_T + h);
      g.lineTo(x, PAD_T + h + 5);
    }
    g.stroke();

    // ── time labels ─────────────────────────────────────────────────────────────────────────
    g.fillStyle = axis;
    g.font = '10px system-ui, sans-serif';
    g.textBaseline = 'top';
    g.textAlign = 'left';
    g.fillText(`${t0.toFixed(2)} s`, PAD_L, PAD_T + h + 6);
    g.textAlign = 'right';
    g.fillText(`${t1.toFixed(2)} s`, PAD_L + w, PAD_T + h + 6);
  }, [trace, t0, t1, spikes, syncEpisodes, suspect, height]);

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
