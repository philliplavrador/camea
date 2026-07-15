// JOBS — the long-operation lifecycle, and the one piece of client machinery a ruling is written
// about: the Place-screen ETA that COUNTS DOWN EVERY SECOND and never looks frozen (BEHAVIOUR R8).
//
// Every long backend op (open a dataset, build, export, recheck) returns a 202 `JobRef`; the client
// polls `GET /api/jobs/{id}` at 500 ms. `Job.eta_s` is only recomputed by the backend when the child
// process prints a recognised line — so a build can report the SAME `eta_s` for 200 s of silence
// (BEHAVIOUR R8, the `[swim] 12,090 pairs in 205.9s` line). The countdown the user sees is a CLIENT
// clock that ticks between those updates; the server's number only ever RE-ANCHORS it.

import { useEffect, useReducer, useRef, useState } from 'react';
import { api, ApiError, unwrap } from './client';
import type { Job, JobListResponse, JobCancelResponse } from './types';

/** Job poll cadence (BEHAVIOUR §7 `POLL_MS`). */
export const POLL_MS = 500;
/** The ETA countdown ticks once a second (BEHAVIOUR R8.1). */
const TICK_MS = 1000;
/** The log tail shown to the user (BEHAVIOUR R8.7). */
const LOG_TAIL_LINES = 8;

const TERMINAL: ReadonlySet<Job['state']> = new Set(['done', 'failed', 'cancelled']);
export function isTerminalState(state: Job['state']): boolean {
  return TERMINAL.has(state);
}

// ── Plain request functions ────────────────────────────────────────────────────

export async function getJob(jobId: string): Promise<Job> {
  return unwrap(await api.GET('/api/jobs/{job_id}', { params: { path: { job_id: jobId } } }));
}

export async function listJobs(): Promise<JobListResponse> {
  return unwrap(await api.GET('/api/jobs'));
}

/**
 * Cancel a job. Idempotent on the server; a FINISHED job answers 409, which surfaces here as an
 * `ApiError` the caller can ignore — cancelling a build that already produced 312/312 is a no-op, not
 * an error to shout about.
 */
export async function cancelJob(jobId: string): Promise<JobCancelResponse> {
  return unwrap(await api.POST('/api/jobs/{job_id}/cancel', { params: { path: { job_id: jobId } } }));
}

/**
 * Poll a job to a terminal state — the imperative path for flows that only need the RESULT (opening a
 * dataset, a rescue recheck) and do not paint a live ETA. Resolves with the finished `Job` on `done`;
 * REJECTS on `failed`/`cancelled` so the caller's `try/catch` sees it. `onUpdate` fires on every poll.
 */
export async function pollJobUntilDone(
  jobId: string,
  opts: { onUpdate?: (job: Job) => void; signal?: AbortSignal; pollMs?: number } = {},
): Promise<Job> {
  const pollMs = opts.pollMs ?? POLL_MS;
  for (;;) {
    if (opts.signal?.aborted) throw new DOMException('aborted', 'AbortError');
    const job = await getJob(jobId);
    opts.onUpdate?.(job);
    if (job.state === 'done') return job;
    if (job.state === 'failed') {
      throw new ApiError(500, {
        error: { code: job.error?.code ?? 'job_failed', message: job.error?.message ?? 'job failed' },
      });
    }
    if (job.state === 'cancelled') {
      throw new ApiError(499, { error: { code: 'cancelled', message: 'job cancelled' } });
    }
    await sleep(pollMs, opts.signal);
  }
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const id = setTimeout(resolve, ms);
    signal?.addEventListener(
      'abort',
      () => {
        clearTimeout(id);
        reject(new DOMException('aborted', 'AbortError'));
      },
      { once: true },
    );
  });
}

// ── The ETA formatter (BEHAVIOUR R8.6) ─────────────────────────────────────────

/**
 * Format seconds-remaining exactly as the Place screen shows it (BEHAVIOUR R8.6):
 *   901 → "15m 01s"   ·   47 → "47 s"   ·   < 1 s → "almost there…"   ·   null → null
 * Clamped at zero (R8.3): it NEVER renders a negative time, which reads as a hang — the exact failure
 * this whole mechanism exists to prevent.
 */
export function formatEta(seconds: number | null): string | null {
  if (seconds == null) return null;
  if (seconds < 1) return 'almost there…';
  const total = Math.round(seconds);
  if (total < 60) return `${total} s`;
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}m ${String(s).padStart(2, '0')}s`;
}

// ── The reactive hook, with the ticking ETA ─────────────────────────────────────

export interface JobProgress {
  /** The last polled job, or null before the first poll. */
  job: Job | null;
  /** `idle` before a job id is given; otherwise the server's lifecycle state. */
  state: Job['state'] | 'idle';
  phase: string | null;
  phaseIndex: number | null;
  nPhases: number | null;
  /** 0–100 for the gliding progress bar (the CSS `transition: width` is the UI's, BEHAVIOUR R8.5). */
  pct: number | null;
  message: string | null;
  /** DISPLAY seconds remaining: clamped ≥ 0, ticking down each second between server updates. */
  etaS: number | null;
  /** `etaS` run through `formatEta`. null when there is no ETA to show (a silent phase before any). */
  etaText: string | null;
  /** The last 8 narration lines (BEHAVIOUR R8.7). */
  logTail: string[];
  error: Job['error'] | null;
  isTerminal: boolean;
}

interface EtaAnchor {
  /** The server `eta_s` this countdown is anchored on. */
  etaS: number;
  /** `Date.now()` when we anchored (or last re-anchored) on it. */
  at: number;
}

/**
 * Poll a job and expose its progress with a TICKING ETA (BEHAVIOUR R8).
 *
 * 🔴 R8.2 — the whole subtlety: re-anchor the countdown **only when the server's raw `eta_s` actually
 * changes.** The poll fires every 500 ms carrying the *last* `eta_s` over and over until the child next
 * prints. Re-anchoring on every tick resets the clock and the countdown never moves — the bug that was
 * introduced *while fixing* the original freeze. So we remember the last RAW server value and only
 * re-anchor on a genuine change; the display counts down from that anchor on its own 1 s clock.
 *
 * R8.4 — an upward jump is honest: when a long-silent phase finally reports a worse estimate we take
 * the server's number. A visible correction beats a smooth lie.
 *
 * Pass `null` to disarm (no job in flight).
 */
export function useJob(jobId: string | null): JobProgress {
  const [job, setJob] = useState<Job | null>(null);
  // A once-a-second re-render so the derived countdown recomputes against the wall clock.
  const [, tick] = useReducer((n: number) => (n + 1) % 1_000_000, 0);

  // The last RAW server value we observed (number or null). Compared to detect a genuine change.
  const lastRawRef = useRef<number | null>(null);
  // The anchor the client clock counts down from.
  const anchorRef = useRef<EtaAnchor | null>(null);

  // Reset all per-job state the instant the job id changes.
  useEffect(() => {
    setJob(null);
    lastRawRef.current = null;
    anchorRef.current = null;
  }, [jobId]);

  // Poll loop.
  useEffect(() => {
    if (jobId == null) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = async () => {
      let next: Job | null = null;
      try {
        next = await getJob(jobId);
      } catch {
        // A transient poll failure must not kill the loop — try again next tick.
      }
      if (!alive) return;
      if (next) {
        setJob(next);
        reanchorEta(next, lastRawRef, anchorRef);
        if (isTerminalState(next.state)) {
          // The run is over: drop the countdown so no stale ETA lingers.
          anchorRef.current = null;
          return; // stop polling
        }
      }
      timer = setTimeout(() => void poll(), POLL_MS);
    };
    void poll();

    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [jobId]);

  // The 1 s countdown clock — runs only while a job is live and armed with an anchor.
  const running = job != null && !isTerminalState(job.state);
  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => tick(), TICK_MS);
    return () => clearInterval(id);
  }, [running]);

  return deriveProgress(jobId, job, anchorRef.current);
}

/**
 * Re-anchor the countdown iff the server's RAW `eta_s` genuinely changed (BEHAVIOUR R8.2). Exported so
 * the load-bearing decision — "the same number repeated does NOT reset the clock" — is unit-tested
 * without the React/polling plumbing (the rendered countdown is covered by the e2e place-eta spec).
 */
export function reanchorEta(
  job: Job,
  lastRawRef: { current: number | null },
  anchorRef: { current: EtaAnchor | null },
): void {
  const raw = job.eta_s ?? null;
  // A NEW number (including an honest upward jump, R8.4) re-anchors. A repeat of the same number, or a
  // silent-phase null, does NOT — the client clock keeps counting down from where it was.
  if (raw != null && raw !== lastRawRef.current) {
    anchorRef.current = { etaS: raw, at: Date.now() };
  }
  lastRawRef.current = raw;
}

function deriveProgress(jobId: string | null, job: Job | null, anchor: EtaAnchor | null): JobProgress {
  const state: Job['state'] | 'idle' = jobId == null ? 'idle' : (job?.state ?? 'queued');
  const isTerminal = job != null && isTerminalState(job.state);

  let etaS: number | null = null;
  if (anchor && !isTerminal) {
    const elapsed = (Date.now() - anchor.at) / 1000;
    etaS = Math.max(0, anchor.etaS - elapsed); // clamp ≥ 0 (R8.3) — never negative
  }

  const logTail = (job?.log_tail ?? []).slice(-LOG_TAIL_LINES);

  return {
    job,
    state,
    phase: job?.phase ?? null,
    phaseIndex: job?.phase_index ?? null,
    nPhases: job?.n_phases ?? null,
    pct: job?.pct ?? null,
    message: job?.message ?? null,
    etaS,
    etaText: formatEta(etaS),
    logTail,
    error: job?.error ?? null,
    isTerminal,
  };
}
