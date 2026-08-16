// JOBS — the long-operation lifecycle, and the one piece of client machinery a ruling is written
// about: the Place-screen ETA that COUNTS DOWN EVERY SECOND and never looks frozen (BEHAVIOUR R8).
//
// Every long backend op (open a dataset, build, export, recheck) returns a 202 `JobRef`; the client
// polls `GET /api/jobs/{id}` at 500 ms. `Job.eta_s` is only recomputed by the backend when the child
// process prints a recognised line — so a build can report the SAME `eta_s` for 200 s of silence
// (BEHAVIOUR R8, the `[swim] 12,090 pairs in 205.9s` line). The countdown the user sees is a CLIENT
// clock that ticks between those updates; the server's number only ever RE-ANCHORS it.

import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import { api, ApiError, unwrap } from './client';
import type { Job, JobListResponse, JobCancelResponse, RunningJob } from './types';

/** Job poll cadence (BEHAVIOUR §7 `POLL_MS`). */
export const POLL_MS = 500;
/**
 * The top strip's cadence (BEHAVIOUR R48.8) — slower than a focused job's poll on purpose. The
 * strip is peripheral: it is read while doing something else, and 1 s is well inside the reaction
 * time of somebody who is not looking at it. The bar it draws still glides, because the CSS
 * transition covers the gap.
 */
export const RUNNING_POLL_MS = 1000;
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
 * Every live job, oldest first — what the top strip draws (BEHAVIOUR R48.8).
 *
 * ⚠️ **Not `listJobs()` with a filter.** That route serialises every job in history, and a finished
 * videomosaic/region job's `result` embeds an entire document that is re-validated through the
 * discriminated union on every call. This one is slim by construction. See `Job.to_brief`.
 */
export async function listRunningJobs(): Promise<RunningJob[]> {
  const res = await unwrap(await api.GET('/api/jobs/running'));
  return res.jobs ?? [];
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
 * What a submit-then-wait wrapper takes so its caller can draw a bar (BEHAVIOUR R48).
 *
 * ⚠️ `signal` aborts the **waiting**, not the work: the job keeps running server-side. Stopping the
 * work is `cancelJob(job.job_id)` (R48.7), and the id arrives on the first `onProgress`.
 */
export interface JobWatch {
  /** Fires on every poll (500 ms) with the whole `Job` — pct, phase, eta_s, said_as, log_tail. */
  onProgress?: (job: Job) => void;
  /** Abort the wait. See the caveat above. */
  signal?: AbortSignal;
}

/**
 * A job's failure, as a SENTENCE (BEHAVIOUR R48.9 — a wait that ends badly must still say so, in
 * words). The registry writes `f"{type(e).__name__}: {e}"` into `error.message` so the log keeps the
 * exception class beside its traceback; the user does not need to read
 * *"RuntimeError: no MaxWell recordings found near this project's data folder"* to learn there are
 * no recordings. Strips exactly one leading CapWords identifier + `": "` — the shape Python's
 * `type(e).__name__` produces and nothing a hand-written message looks like.
 *
 * ⛔ This is the ONE place the prefix is dropped: both readers of `error` (this module's
 * `pollJobUntilDone` and `useJob`'s `deriveProgress`) go through it, so no screen has to remember to.
 * The traceback on the wire is untouched.
 */
export function jobErrorSentence(message: string | null | undefined): string | null {
  if (message == null) return null;
  const m = /^[A-Z][A-Za-z0-9_]{2,}: (?=\S)/.exec(message);
  return m ? message.slice(m[0].length) : message;
}

/**
 * 🔴 **THE RESULT IS CACHED ON THE RAW ERROR, AND THAT IS NOT AN OPTIMISATION.** `deriveProgress`
 * runs on EVERY render, so returning a fresh `{...error}` each time would hand `useJob` a `error`
 * whose identity changes on every render — and eight screens carry `job.error` in a `useEffect`
 * dependency array (`OrientationStep`, `VideoMosaicFeature`, `ElectrodesStep`, `MosaicStep`,
 * `PlaceStep`, `RecomputePanel`, `RightRail`). Those effects would re-run on every unrelated render
 * of their screen, and the one that does not clear its job id (`OrientationStep`) would re-set the
 * failure it already reported — putting a dismissed error back on screen mid-retry. The `Job` object
 * a poll returns is stable between polls, so keying on it keeps the identity stable too.
 */
const SENTENCED = new WeakMap<NonNullable<Job['error']>, Job['error']>();

function sentencedError(error: Job['error']): Job['error'] {
  if (!error?.message) return error ?? null;
  const cached = SENTENCED.get(error);
  if (cached !== undefined) return cached;
  const clean = jobErrorSentence(error.message);
  const out = clean === error.message ? error : { ...error, message: clean ?? error.message };
  SENTENCED.set(error, out);
  return out;
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
        error: {
          code: job.error?.code ?? 'job_failed',
          message: jobErrorSentence(job.error?.message) ?? 'job failed',
        },
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

/**
 * How long it has been running, for the slot beside "working out how long this will take…"
 * (BEHAVIOUR R48.4).
 *
 * ⭐ **This is what makes R48.4 satisfiable WITHOUT the forbidden server-side heartbeat (R48b).**
 * During a genuinely silent phase — the CPU build's 3m 40s stretch — `eta_s` is null and pinning a
 * fabricated countdown there would make it count *up*. An elapsed clock counts up because that is
 * what elapsed does, and it is true. It gives the screen a number that moves without inventing one.
 *
 * Unlike `formatEta` this never says "almost there…" — 0 s elapsed is just `0 s`.
 */
export function formatElapsed(seconds: number | null): string | null {
  if (seconds == null || !Number.isFinite(seconds)) return null;
  const total = Math.max(0, Math.round(seconds));
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
  /**
   * ⏱️ Seconds since the job started — the server's `elapsed_s`, which `Job.to_json` recomputes LIVE
   * on every poll while running (never frozen at the last progress message). Ticks on the same 1 Hz
   * clock as the countdown, so it moves between polls too.
   *
   * R48.4 — this is what fills the time slot while there is no estimate yet. It was on the wire the
   * whole time and nothing rendered it.
   */
  elapsedS: number | null;
  /** `elapsedS` run through `formatElapsed`. */
  elapsedText: string | null;
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

/** The same anchor, for the clock that counts UP (R48.4). See `reanchorElapsed`. */
interface ElapsedAnchor {
  elapsedS: number;
  at: number;
}

/**
 * Re-anchor the elapsed clock **only when the server's raw number actually changed** — R8.2's
 * discipline, applied to the clock that counts up (BEHAVIOUR R48.4).
 *
 * 🔴 The first version of this re-anchored unconditionally, reasoning that `Job.to_json` recomputes
 * `elapsed_s` live on every poll so it always differs. That is true of a healthy server and it is
 * exactly the reasoning that produced R8.2's bug: **when the number does repeat, re-anchoring resets
 * the local clock every poll and the display freezes.** Caught by `progress-eta.spec.ts`, which held
 * `elapsed_s` still and watched "1m 40s" sit there for 2.5 s while the ticker dutifully re-rendered.
 * A stalled poll, a slow answer, or a server that rounds to the same tenth all reproduce it.
 *
 * Anchoring only on a genuine change means the client keeps counting through a gap of any length and
 * simply re-syncs when a new number arrives.
 */
export function reanchorElapsed(
  raw: number,
  ref: { current: ElapsedAnchor | null },
): void {
  if (ref.current?.elapsedS !== raw) ref.current = { elapsedS: raw, at: Date.now() };
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
  // The anchor the elapsed clock counts UP from (R48.4).
  const elapsedRef = useRef<ElapsedAnchor | null>(null);

  // Reset all per-job state the instant the job id changes.
  useEffect(() => {
    setJob(null);
    lastRawRef.current = null;
    anchorRef.current = null;
    elapsedRef.current = null;
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
        reanchorElapsed(next.elapsed_s ?? 0, elapsedRef);
        if (isTerminalState(next.state)) {
          // The run is over: drop the countdown so no stale ETA lingers. The elapsed anchor goes too
          // — a finished job reports the server's final `elapsed_s`, which must not keep climbing.
          anchorRef.current = null;
          elapsedRef.current = null;
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

  return deriveProgress(jobId, job, anchorRef.current, elapsedRef.current);
}

// ── The top strip: everything running, from anywhere (R48.8) ───────────────────

/** One live job as the strip renders it — the wire row plus the two derived display strings. */
export interface RunningJobView extends RunningJob {
  /** DISPLAY seconds remaining, ticking down on the client's 1 Hz clock. Null before an anchor. */
  etaS: number | null;
  etaText: string | null;
  elapsedS: number | null;
  elapsedText: string | null;
}

/**
 * ⏱️ **Poll everything that is running (BEHAVIOUR R48.8)** — so the strip under the top bar can
 * report work the user has walked away from.
 *
 * 🔴 **The per-job countdown discipline of R8.2 applies here too, per job.** The strip polls at 1 s
 * while `eta_s` is only recomputed when a job's worker actually advances, so the same raw number
 * arrives over and over; re-anchoring on each poll would freeze every countdown in the strip, which
 * is the exact bug R8.2 exists for, reproduced one layer out. The anchors are held in a Map keyed by
 * `job_id`, and a job that disappears takes its anchor with it.
 *
 * ⛔ **The strip must never compute its own estimate.** R48.8 — same numbers as the inline bar, or
 * the user is reading two different answers to one question.
 */
export function useRunningJobs(): RunningJobView[] {
  const [rows, setRows] = useState<RunningJob[]>([]);
  const [, tick] = useReducer((n: number) => (n + 1) % 1_000_000, 0);

  const lastRawRef = useRef<Map<string, number | null>>(new Map());
  const anchorRef = useRef<Map<string, EtaAnchor>>(new Map());
  const elapsedRef = useRef<Map<string, ElapsedAnchor>>(new Map());

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = async () => {
      let next: RunningJob[] | null = null;
      try {
        next = await listRunningJobs();
      } catch {
        // A transient failure must not kill the strip — and must not blank it either. Keep the last
        // known rows; the next poll corrects them.
      }
      if (!alive) return;
      if (next) {
        const now = Date.now();
        const live = new Set(next.map((j) => j.job_id));
        for (const j of next) {
          const raw = j.eta_s ?? null;
          // R8.2 — a NEW number re-anchors; a repeat does not.
          if (raw != null && raw !== lastRawRef.current.get(j.job_id)) {
            anchorRef.current.set(j.job_id, { etaS: raw, at: now });
          }
          lastRawRef.current.set(j.job_id, raw);
          // R48.4 + R8.2 — only on a genuine change, or the local clock resets every poll and the
          // display freezes. Same reasoning as the ETA anchor above; see `reanchorElapsed`.
          const rawElapsed = j.elapsed_s ?? 0;
          if (elapsedRef.current.get(j.job_id)?.elapsedS !== rawElapsed) {
            elapsedRef.current.set(j.job_id, { elapsedS: rawElapsed, at: now });
          }
        }
        // Drop the anchors of jobs that have finished, or the map grows for the whole session.
        for (const m of [lastRawRef.current, anchorRef.current, elapsedRef.current]) {
          for (const id of m.keys()) if (!live.has(id)) m.delete(id);
        }
        setRows(next);
      }
      timer = setTimeout(() => void poll(), RUNNING_POLL_MS);
    };
    void poll();

    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, []);

  // The 1 s clock, armed only while something is actually running — an idle app does no work.
  const anyRunning = rows.length > 0;
  useEffect(() => {
    if (!anyRunning) return;
    const id = setInterval(() => tick(), TICK_MS);
    return () => clearInterval(id);
  }, [anyRunning]);

  const now = Date.now();
  return rows.map((j) => {
    const a = anchorRef.current.get(j.job_id);
    const etaS = a ? Math.max(0, a.etaS - (now - a.at) / 1000) : null; // clamp ≥ 0 (R8.3)
    const e = elapsedRef.current.get(j.job_id);
    const elapsedS = e ? e.elapsedS + (now - e.at) / 1000 : (j.elapsed_s ?? null);
    return {
      ...j,
      etaS,
      etaText: formatEta(etaS),
      elapsedS,
      elapsedText: formatElapsed(elapsedS),
    };
  });
}

/**
 * `cancelJob`, but swallowing the 409 a job that finished between the click and the request answers
 * with (BEHAVIOUR R48.7 — a Stop that races the end of the work is not an error to shout about; R8's
 * `cancelJob` docstring makes the same point). Rethrows anything else.
 */
export function useStopJob(): (jobId: string) => Promise<void> {
  return useCallback(async (jobId: string) => {
    try {
      await cancelJob(jobId);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 409 || e.status === 404)) return;
      throw e;
    }
  }, []);
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

function deriveProgress(
  jobId: string | null,
  job: Job | null,
  anchor: EtaAnchor | null,
  elapsedAnchor: ElapsedAnchor | null,
): JobProgress {
  const state: Job['state'] | 'idle' = jobId == null ? 'idle' : (job?.state ?? 'queued');
  const isTerminal = job != null && isTerminalState(job.state);

  let etaS: number | null = null;
  if (anchor && !isTerminal) {
    const elapsed = (Date.now() - anchor.at) / 1000;
    etaS = Math.max(0, anchor.etaS - elapsed); // clamp ≥ 0 (R8.3) — never negative
  }

  // R48.4 — the elapsed clock runs on the same 1 Hz tick as the countdown, extrapolated from the
  // last poll so it advances between them. Once terminal it freezes at the server's final number:
  // a finished job's elapsed is a fact, not a clock.
  let elapsedS: number | null = job?.elapsed_s ?? null;
  if (elapsedAnchor && !isTerminal) {
    elapsedS = elapsedAnchor.elapsedS + (Date.now() - elapsedAnchor.at) / 1000;
  }

  const logTail = (job?.log_tail ?? []).slice(-LOG_TAIL_LINES);

  return {
    job,
    state,
    phase: job?.phase ?? null,
    phaseIndex: job?.phase_index ?? null,
    nPhases: job?.n_phases ?? null,
    // ⚠️ **`0`, NOT `null`, while a job is armed but has not answered yet (R48.9).** `pct: null` is
    // `<Progress>`'s signal for *"this work has no denominator"* — the travelling sliver, reserved
    // for the four cases in R48.9. "The first poll has not landed" is a different thing entirely,
    // and returning null for it made every determinate bar in the app open as a sliver for up to
    // 500 ms: a visible flicker, and — because the sliver sets `transition: none` — it also broke
    // R8.5's "the bar glides" for that window, which `place-eta.spec.ts:103` asserts on.
    // A submitted job is 0 % done. That is true, and `Progress` floors it at a 2 % sliver so it
    // still reads as started rather than as broken. (Caught in the R48 verify pass.)
    pct: job?.pct ?? (jobId != null ? 0 : null),
    message: job?.message ?? null,
    etaS,
    etaText: formatEta(etaS),
    elapsedS,
    elapsedText: formatElapsed(elapsedS),
    logTail,
    error: sentencedError(job?.error ?? null),
    isTerminal,
  };
}
