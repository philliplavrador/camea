// Behavioural unit test for the ported voltage panel (the plan-004 viewer on the videomosaic
// side). What is proven here is the panel's own contract, the parts jsdom can reach:
//
//   • opening a pad costs ONE request and shows the whole recording — strip + close-up + nav, no
//     scrubber anywhere. 🔴 The call count is the regression test for the old panel's
//     jumped-as-state double-fetch, which re-ran the arrival effect once per state write.
//   • the three live warnings are on the page, and the did-not-decode one NAMES its scope
//     (`health_scope`) — a percentage whose scope changes as he zooms must say which it is quoting.
//   • envelope missing -> the quiet note + "Read it now", which starts the backfill and polls
//     until the recording is ready, then shows it — and while it runs, ⏱️ **a bar with the read's
//     real percentage and a time on it** (BEHAVIOUR R48), not the bare word `Reading…`.
//   • 🔴 R48.9 — a read that starts NOTHING says so. An ActivityScan stores no continuous trace, so
//     `start_envelope` returns no job and `ready` never comes true; the poller used to stop dead
//     and leave the same button sitting there.
//
// The pixels themselves are not asserted (jsdom has no canvas); the drag/keyboard mechanics live
// in core/trace and carry their own suites (useTimeBrush.test.ts, viewStack.test.ts).

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { ElectrodeTracePayload, MeaRecordingSummary } from '../../api';
import type { VideoMeaEnvelopeStatus } from '../../api';
import { ApiError } from '../../api/client';

vi.mock('../../api', () => ({
  getElectrodeTrace: vi.fn(),
  getMeaEnvelopes: vi.fn(),
  startMeaEnvelopeRead: vi.fn(),
  // ⏱️ R48 — the panel follows the read's JOB for its bar. Stubbed rather than exercised here: the
  // countdown's arithmetic and R8.2's re-anchor rule are proven in `api/jobs.test.ts`, and the bar's
  // ARIA in `design/primitives/Progress.test.tsx`. What this file proves is that the panel WIRES it.
  useJob: () => ({
    job: { said_as: 'reading the recording end to end' },
    state: 'running',
    phase: 'envelope',
    phaseIndex: null,
    nPhases: null,
    pct: 40,
    message: '40% of the recording read',
    etaS: 31,
    etaText: '31 s',
    elapsedS: 20,
    elapsedText: '20 s',
    logTail: [],
    error: null,
    isTerminal: false,
  }),
  useStopJob: () => vi.fn(),
}));

import { getElectrodeTrace, getMeaEnvelopes, startMeaEnvelopeRead } from '../../api';
import { MeaTracePanel } from './MeaTracePanel';

const RUN = '000690';

function rec(): MeaRecordingSummary {
  return {
    run_id: RUN,
    assay: 'Network',
    label: `Network/${RUN}`,
    path: `/mea/Network/${RUN}/data.raw.h5`,
    n_channels: 33,
    n_samples: 60_000,
    sampling_hz: 20_000,
    duration_s: 3,
    lsb_uv: 6.294,
    gain: 512,
    hpf_hz: 300,
    n_spikes: 41,
  };
}

function payload(over: Partial<ElectrodeTracePayload> = {}): ElectrodeTracePayload {
  return {
    electrode: '3-7',
    recorded: true,
    run_id: RUN,
    channel: 12,
    chip_electrode: 424,
    t0_s: 0,
    t1_s: 3,
    sampling_hz: 20_000,
    trace_uv: [],
    health: { n_samples: 60_000, fill_value: 512, fill_fraction: 0.01, distinct_values: 900, flat: false },
    spikes: [],
    n_spikes_total: 41,
    first_spike_s: 0.5,
    duration_s: 3,
    sync_episodes: [],
    orientation: { flip_x: false, flip_y: false, confirmed: false, source: '' },
    resolution: 'envelope',
    min_uv: [-10, -5, -8],
    max_uv: [10, 8, 9],
    max_window_s: 30,
    health_scope: 'recording',
    decode_error: '',
    ...over,
  };
}

/** One envelope-status reply. ⚠️ `ready` and `jobId` are INDEPENDENT: "not ready and nothing
 *  running" is a real state (an ActivityScan), and it is the one R48.9 was written about. */
function status(ready: boolean, jobId = ''): VideoMeaEnvelopeStatus {
  return {
    analysis_id: 'A',
    recordings: [{ run_id: RUN, label: `Network/${RUN}`, ready, job_id: jobId, pct: 40 }],
    started: jobId ? [jobId] : [],
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe('MeaTracePanel — the ported whole-recording viewer', () => {
  it('opens on the whole recording with ONE request: strip + close-up + nav, and no scrubber', async () => {
    vi.mocked(getElectrodeTrace).mockResolvedValue(payload());
    render(<MeaTracePanel analysisId="A" electrode="3-7" recordings={[rec()]} />);

    await screen.findByTestId('mea-trace-overview-chart');
    expect(screen.getByTestId('mea-trace-chart')).toBeInTheDocument();
    expect(screen.getByTestId('mea-trace-nav')).toBeInTheDocument();
    // The readout states the served range — the whole recording, on open.
    expect(screen.getByTestId('mea-trace-pos').textContent).toContain('3.00 s wide');
    // ⛔ The scrubber is gone, and the strip must not have grown a handle.
    expect(document.querySelector('input[type="range"]')).toBeNull();
    // ⚠️ #3 — the seating is unconfirmed, so identity is stated as provisional.
    expect(screen.getByTestId('mea-provisional')).toBeInTheDocument();
    // The videomosaic facts survive the port.
    expect(screen.getByText('424')).toBeInTheDocument(); // chip electrode
    expect(screen.getByText('12')).toBeInTheDocument(); // channel

    // 🔴 THE DOUBLE-FETCH IS DEAD. The whole-recording answer doubles as the opening close-up,
    // so a click costs exactly one request — the old panel's jumped-as-state bug fetched twice.
    expect(getElectrodeTrace).toHaveBeenCalledTimes(1);
    expect(getElectrodeTrace).toHaveBeenCalledWith('A', '3-7', {
      runId: RUN,
      t0: 0,
      maxPoints: expect.any(Number),
    });
  });

  it('the did-not-decode warning is on the page and NAMES what its percentage measured', async () => {
    vi.mocked(getElectrodeTrace).mockResolvedValue(
      payload({
        health: { n_samples: 60_000, fill_value: 512, fill_fraction: 0.97, distinct_values: 2, flat: true },
        health_scope: 'recording',
      }),
    );
    render(<MeaTracePanel analysisId="A" electrode="3-7" recordings={[rec()]} />);

    const warn = await screen.findByTestId('mea-flat');
    expect(warn.textContent).toContain('97% of this recording');
    // Still drawn, dimmed — the charts are on the page with the warning, never replaced by it.
    expect(screen.getByTestId('mea-trace-chart')).toBeInTheDocument();
  });

  it('a pad that was never routed reads as a fact, not an error or an empty chart', async () => {
    vi.mocked(getElectrodeTrace).mockResolvedValue(
      payload({ recorded: false, channel: null, t0_s: 0, t1_s: 0 }),
    );
    render(<MeaTracePanel analysisId="A" electrode="9-9" recordings={[rec()]} />);

    await screen.findByTestId('mea-not-recorded');
    expect(screen.queryByTestId('mea-trace-chart')).toBeNull();
  });

  it('envelope missing -> "Read it now" starts the backfill, shows a BAR with a time on it, and then the recording', async () => {
    vi.useFakeTimers();
    vi.mocked(getElectrodeTrace)
      .mockRejectedValueOnce(
        new ApiError(409, { error: { code: 'refused', message: 'not read end to end yet' } }),
      )
      .mockResolvedValue(payload());
    // The look on arrival finds nothing running; the POST is what starts it.
    vi.mocked(getMeaEnvelopes).mockResolvedValueOnce(status(false));
    vi.mocked(startMeaEnvelopeRead).mockResolvedValue(status(false, 'j1'));
    vi.mocked(getMeaEnvelopes).mockResolvedValue(status(true));

    render(<MeaTracePanel analysisId="A" electrode="3-7" recordings={[rec()]} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    // ⭐ A fact and an offer, not an error — and ⛔ it no longer promises a minute (R48).
    const note = screen.getByTestId('mea-trace-needs-envelope');
    expect(note).toBeInTheDocument();
    expect(note.textContent).not.toContain('about a minute');
    fireEvent.click(screen.getByRole('button', { name: 'Read it now' }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(startMeaEnvelopeRead).toHaveBeenCalledWith('A');

    // ⏱️ **R48 — THE BAR, NOT THE WORD.** The POST's own reply carries the job id, so the read's
    // percentage and its ticking countdown are on screen on the next frame rather than a poll later.
    const bar = screen.getByTestId('mea-trace-reading');
    expect(bar.textContent).toContain('40%');
    expect(screen.getByTestId('mea-trace-reading-eta').textContent).toContain('31 s');
    expect(screen.getByTestId('mea-trace-reading-stop')).toBeInTheDocument(); // R48.7 — and wired
    expect(screen.queryByRole('button', { name: 'Reading…' })).toBeNull();

    // One poll later the run reads ready, the arrival fetch re-runs, and the picture appears —
    // the bar must never look finished while the read has barely started.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect(getMeaEnvelopes).toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.queryByTestId('mea-trace-needs-envelope')).toBeNull();
    expect(screen.getByTestId('mea-trace-overview-chart')).toBeInTheDocument();
  });

  it('🔴 R48.9 — a read that starts nothing SAYS so, instead of the poller stopping in silence', async () => {
    vi.useFakeTimers();
    vi.mocked(getElectrodeTrace).mockRejectedValue(
      new ApiError(409, { error: { code: 'refused', message: 'not read end to end yet' } }),
    );
    // The ActivityScan case, exactly as the backend produces it: nothing started, nothing ready,
    // and `ready` is never going to become true because there is no continuous trace to read.
    vi.mocked(getMeaEnvelopes).mockResolvedValue(status(false));
    vi.mocked(startMeaEnvelopeRead).mockResolvedValue(status(false));

    render(<MeaTracePanel analysisId="A" electrode="3-7" recordings={[rec()]} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    fireEvent.click(screen.getByRole('button', { name: 'Read it now' }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    const ended = screen.getByTestId('mea-trace-read-ended');
    expect(ended.textContent).toContain('no continuous trace');
    // ⛔ And no bar counting down to nothing beside it.
    expect(screen.queryByTestId('mea-trace-reading')).toBeNull();
  });
});
