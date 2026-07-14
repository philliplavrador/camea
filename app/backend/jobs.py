"""The async job registry — start, poll, cancel.

OWNER: agent 2 (engine). Nobody else edits this file; everybody imports `JOBS` from it.

WHY THIS EXISTS
---------------
`t33.place` runs **25 s - 10 min SYNCHRONOUSLY** and has **no progress callback of any kind** — its
only signal is a `print` behind `cfg.verbose` (t33.py:737). It cannot be interrupted cooperatively,
because there is nothing in it that checks a flag. So:

  * every long operation is **start -> job id -> poll** (API.md §8);
  * the **build** job runs in a CHILD PROCESS (`multiprocessing`, `spawn`) so that CANCEL CAN
    ACTUALLY WORK — cancel is `proc.terminate()`. There is no other way.
  * `open` and `export` jobs run on a **thread**: they are seconds, and they poll a flag.

The child re-loads the frames itself from `data_dir` — **0.12 s for 312 frames** with the numpy
reader. Do NOT build a shared-memory apparatus to avoid a tenth of a second.

⚠️ TWO CUDA CONTEXTS. The parent may already hold one (from interactive matching) when a build
child starts. Mitigation, and it is mandatory: `server.py` returns **409 busy** on `/api/match/*`
while a build is running, and the parent calls `engine.release_gpu()` before spawning. On a 4 GB
card, a 312-tile build's device peak is ~2.0 GB and this is tight. Report an OOM honestly; do not
retry silently on the CPU without saying so.

⚠️ SPAWN + sys.path. The child is a FRESH interpreter. It must be able to `import app.backend.engine`
by dotted path, which means the REPO ROOT must be on its `sys.path`. `multiprocessing.spawn` copies
the parent's `sys.path` into the child's preparation data, but only if the parent's `sys.path`
actually contains the repo root — `main.py` puts it there. We ALSO pass it explicitly in `kwargs`
and re-insert it in the child, because relying on the implicit copy is exactly the kind of thing
that works on the dev box and fails in a frozen build.
"""
from __future__ import annotations

import importlib
import itertools
import multiprocessing as mp
import queue as _queue
import sys
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

JobState = Literal["queued", "running", "done", "failed", "cancelled"]
JobKind = Literal["open", "build", "export"]

#: how many raw stdout lines we keep (API.md §8.3 — the UI shows the last ~8 in a drawer)
LOG_TAIL_MAX = 200


def _iso(t: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t if t is not None else time.time()))


@dataclass
class Progress:
    """One progress snapshot. Everything here is optional except `phase`.

    Overall `pct` is a FIXED WEIGHTING of the phases, because they are wildly unequal on a cold
    cache (measured: 230 s total, of which the anchor loop is ~150 s):

        pass1 0.20 | backbone 0.08 | composite 0.02 | anchors 0.55 | recut 0.01 | runs 0.14

    On a WARM cache the whole build is ~25 s and the first four phases are skipped, so the job
    jumps straight to `runs`. That is correct. Do not "smooth" it — a smoothed bar that lies about
    a 25 s job is worse than an honest one that jumps.
    """
    phase: str = "queued"
    phase_index: int = 0
    n_phases: int = 1
    pct: float = 0.0
    message: str = ""
    eta_s: float | None = None


@dataclass
class Job:
    job_id: str
    kind: JobKind
    state: JobState = "queued"
    progress: Progress = field(default_factory=Progress)
    started_at: str = ""
    finished_at: str | None = None
    elapsed_s: float = 0.0
    #: the last 200 raw log lines (the UI shows the last ~8 in a drawer)
    log_tail: list[str] = field(default_factory=list)
    result: Any = None
    error: dict | None = None          # {"code", "message", "traceback"}
    cancellable: bool = True

    # -- internals; never serialized -------------------------------------------------------
    _t0: float = 0.0
    _cancel: threading.Event | None = None
    _proc: Any = None                  # mp.Process for a process job
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def to_json(self) -> dict:
        """The exact shape of `GET /api/jobs/{job_id}` (API.md §8.1). Must be JSON-safe.

        ⚠️ `result` for a build contains t33's `info`, which is **NOT JSON-serializable** — it holds
        a nested `t27.Config` object and `json.dumps` CRASHES on it. It must already have been made
        safe by `engine.jsonable()` before it lands here. The child does exactly that
        (`engine.build_result` -> `jsonable(info)`), so what arrives over the queue is already safe.
        """
        with self._lock:
            p = self.progress
            elapsed = self.elapsed_s if self.state in ("done", "failed", "cancelled") \
                else (time.time() - self._t0 if self._t0 else 0.0)
            return {
                "job_id": self.job_id,
                "kind": self.kind,
                "state": self.state,
                "phase": p.phase,
                "phase_index": int(p.phase_index),
                "n_phases": int(p.n_phases),
                "pct": round(float(p.pct), 1),
                "message": p.message,
                "started_at": self.started_at,
                "elapsed_s": round(float(elapsed), 1),
                "eta_s": (None if p.eta_s is None else round(float(p.eta_s), 1)),
                "log_tail": list(self.log_tail[-8:]),
                "result": self.result if self.state == "done" else None,
                "error": self.error,
                "cancellable": bool(self.cancellable and self.state in ("queued", "running")),
            }

    # -- mutation, always under the lock ---------------------------------------------------
    def _set(self, **kw) -> None:
        with self._lock:
            for k, v in kw.items():
                setattr(self, k, v)

    def _log(self, line: str) -> None:
        with self._lock:
            self.log_tail.append(line)
            if len(self.log_tail) > LOG_TAIL_MAX:
                del self.log_tail[:-LOG_TAIL_MAX]

    def _finish(self, state: JobState, result: Any = None, error: dict | None = None) -> None:
        with self._lock:
            # a terminal state is final — a late queue message must never resurrect a cancelled job
            if self.state in ("done", "failed", "cancelled"):
                return
            self.state = state
            self.result = result
            self.error = error
            self.elapsed_s = time.time() - self._t0 if self._t0 else 0.0
            self.finished_at = _iso()
            self.cancellable = False


class Cancelled(Exception):
    """Raised by a thread job's `fn` when it sees its cancel event."""


class Busy(Exception):
    """A build is already running. -> HTTP 409 {"error": {"code": "busy"}}"""


class NotCancellable(Exception):
    """The job already finished. -> HTTP 409."""


# =============================================================================
# The child-process entry point
# =============================================================================
def _process_entry(target: str, kwargs: dict, q, sys_path: list[str]) -> None:
    """Runs in the SPAWNED CHILD. Re-establishes `sys.path`, imports `target` by dotted path,
    and calls it with `queue=q`.

    Must be module-level (spawn pickles it by qualified name) and must not close over anything.
    """
    try:
        for p in reversed(sys_path):
            if p and p not in sys.path:
                sys.path.insert(0, p)
        mod_name, _, fn_name = target.rpartition(".")
        fn = getattr(importlib.import_module(mod_name), fn_name)
        fn(queue=q, **kwargs)
    except BaseException as e:                       # noqa: BLE001 — a bare crash must still report
        try:
            q.put({"type": "error", "error": {
                "code": "job_failed",
                "message": f"{type(e).__name__}: {e}",
                "traceback": traceback.format_exc(),
            }})
        except Exception:                            # noqa: BLE001
            pass


# =============================================================================
# The registry
# =============================================================================
class JobRegistry:
    """Thread-safe job table. One instance, module-level: `JOBS`.

    Concurrency rules, and they are part of the contract:
      * **At most one `build` job may be `running` at a time.** `submit_process` raises `Busy` if
        one already is; `server.py` turns that into `409 {"error": {"code": "busy"}}`.
      * `open` and `export` may run concurrently with each other but not with a build.
      * Interactive matches (`/api/match/*`) do NOT go through this registry — they are ~1 s and run
        on the server's thread pool. They are rejected with 409 while a build runs.
    """

    def __init__(self, max_history: int = 32) -> None:
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []           # oldest -> newest
        self._lock = threading.Lock()
        self._max_history = int(max_history)
        self._ids = itertools.count(1)

    # --- internals ----------------------------------------------------------------------
    def _new_job(self, kind: JobKind, cancellable: bool) -> Job:
        job_id = f"job_{uuid.uuid4().hex[:6]}"
        j = Job(job_id=job_id, kind=kind, state="queued", started_at=_iso(),
                cancellable=cancellable)
        j._t0 = time.time()
        with self._lock:
            self._jobs[job_id] = j
            self._order.append(job_id)
            # evict finished history beyond the cap (never evict something still running)
            while len(self._order) > self._max_history:
                for i, jid in enumerate(self._order):
                    if self._jobs[jid].state in ("done", "failed", "cancelled"):
                        del self._order[i]
                        self._jobs.pop(jid, None)
                        break
                else:
                    break
        return j

    def _guard_build(self, kind: JobKind) -> None:
        """One build at a time. It owns the GPU."""
        if self.running("build") is not None:
            raise Busy("a build is already running")

    # --- submitting ---------------------------------------------------------------------
    def submit_thread(
        self,
        kind: JobKind,
        fn: Callable[[Callable[[Progress], None], threading.Event], Any],
        cancellable: bool = True,
    ) -> Job:
        """Run `fn(report, cancel_event)` on a worker thread. Used by `open` and `export`.

        `fn` receives:
          * `report(Progress)` — call it as often as you like; it is cheap and it is what the UI polls.
          * `cancel_event` — a `threading.Event`. **`fn` MUST poll it** at every natural boundary
            (per frame loaded, per tile rendered) and raise `Cancelled` when it is set. A job that
            ignores it is a job the user cannot stop.

        Whatever `fn` returns becomes `job.result` (it MUST be JSON-safe).
        """
        self._guard_build(kind)
        job = self._new_job(kind, cancellable)
        job._cancel = threading.Event()

        def report(p: Progress) -> None:
            if isinstance(p, Progress):
                job._set(progress=p)
                if p.message:
                    job._log(p.message)

        def run() -> None:
            job._set(state="running")
            try:
                result = fn(report, job._cancel)
            except Cancelled:
                job._finish("cancelled")
                return
            except BaseException as e:                    # noqa: BLE001
                job._finish("failed", error={
                    "code": "job_failed",
                    "message": f"{type(e).__name__}: {e}",
                    "traceback": traceback.format_exc(),
                })
                return
            if job._cancel is not None and job._cancel.is_set():
                job._finish("cancelled")
                return
            job._set(progress=Progress(phase="done", phase_index=1, n_phases=1, pct=100.0,
                                       message="done", eta_s=0.0))
            job._finish("done", result=result)

        threading.Thread(target=run, name=f"camea-{kind}-{job.job_id}", daemon=True).start()
        return job

    def submit_process(
        self,
        kind: JobKind,
        target: str,
        kwargs: dict,
    ) -> Job:
        """Run a job in a CHILD PROCESS. This is how `build` runs, and why cancel works.

        `target` — a dotted path to a module-level function in this package, e.g.
                   `"app.backend.engine.build_worker"`. It MUST be importable in a fresh `spawn`
                   interpreter and every value in `kwargs` MUST be picklable (paths, ints, dicts —
                   never a numpy stack, never an open file, never a CuPy array).
        The child streams `Progress` objects and raw log lines back over an `mp.Queue`; the registry
        drains that queue on a reader thread and updates the `Job`.

        Cancel = `proc.terminate()`. There is no cooperative path: t33 has no check to hook.
        """
        self._guard_build(kind)
        job = self._new_job(kind, cancellable=True)

        ctx = mp.get_context("spawn")
        q = ctx.Queue()

        # The repo root — the directory that CONTAINS `app/`. The child needs it on sys.path to
        # `import app.backend.engine`. Derived from this file, not from cwd (which the child does
        # not inherit reliably) and not from sys.path[0] (which is uvicorn's under a server).
        repo_root = str(Path(__file__).resolve().parents[2])
        sys_path = [repo_root] + [p for p in sys.path if p]

        proc = ctx.Process(
            target=_process_entry,
            args=(target, dict(kwargs), q, sys_path),
            name=f"camea-{kind}-{job.job_id}",
            daemon=True,
        )
        job._proc = proc
        proc.start()
        job._set(state="running")

        def drain() -> None:
            try:
                while True:
                    try:
                        msg = q.get(timeout=0.25)
                    except _queue.Empty:
                        if not proc.is_alive():
                            break                       # child gone; one last non-blocking sweep
                        continue
                    except (EOFError, OSError):
                        break
                    self._apply(job, msg)
                    if job.state in ("done", "failed", "cancelled"):
                        break

                # final sweep — messages queued right before exit
                while job.state not in ("done", "failed", "cancelled"):
                    try:
                        self._apply(job, q.get_nowait())
                    except (_queue.Empty, EOFError, OSError):
                        break

                proc.join(timeout=5)
                if job.state not in ("done", "failed", "cancelled"):
                    # The child died without a `done` or an `error`. terminate() lands here too —
                    # `cancel()` has already marked it cancelled, so this is the genuinely-crashed
                    # case (an OOM kill, a segfault in CUDA). Say so; never call it "done".
                    code = proc.exitcode
                    hint = "killed, or it crashed — check for a CUDA OOM"
                    # ⚠️ THE NUMBER AND THE NAME MUST AGREE, OR THE NEXT DEBUGGER CHASES THE WRONG
                    # BUG. This tuple used to be `(3228369023, -1073740791)` labelled
                    # "0xC0000409 STATUS_STACK_BUFFER_OVERRUN" — but 3228369023 is **0xC06D007F,
                    # STATUS_DELAY_LOAD_FAILED**, which is a different code entirely, and the
                    # SIGNED form of the delay-load code (-1066598273 — what `Process.exitcode`
                    # actually reports, since multiprocessing hands back a signed int) was MISSING.
                    # Reproduced 2026-07-12: a bare `python.exe -s` with conda's PATH stripped,
                    # running `np.linalg.solve`, dies with 0xC06D007F. So: carry BOTH codes in BOTH
                    # signednesses, and name them correctly.
                    #   0xC06D007F / 3228369023 / -1066598273  STATUS_DELAY_LOAD_FAILED  <- the real one
                    #   0xC0000409 / 3221226505 / -1073740791  STATUS_STACK_BUFFER_OVERRUN
                    if code in (3228369023, -1066598273, 3221226505, -1073740791):
                        # MEASURED 2026-07-12: this is what you get when numpy's delay-loaded BLAS
                        # cannot find its DLLs — i.e. the app was launched from a python.exe whose
                        # conda env was never ACTIVATED. A native fast-fail: no Python exception, no
                        # traceback, nothing to catch. `engine._predance_env_dlls()` puts
                        # <sys.prefix>/Library/bin on the search path to prevent it. If you see this
                        # again, that pre-dance is not reaching the child — do not chase the GPU.
                        hint = ("a native fast-fail (STATUS_DELAY_LOAD_FAILED, 0xC06D007F — or "
                                "0xC0000409). This is NOT a CUDA OOM. It is what a delay-loaded "
                                "native DLL does when it is not on the search path — classically "
                                "numpy's BLAS when the app was launched from an UNACTIVATED "
                                "environment and engine._predance_env_dlls() did not reach the child")
                    job._finish("failed", error={
                        "code": "job_failed",
                        "message": (f"the build process exited with code {code} without reporting a "
                                    f"result ({hint})"),
                        "traceback": "",
                    })
            finally:
                try:
                    q.close()
                except Exception:                       # noqa: BLE001
                    pass

        threading.Thread(target=drain, name=f"camea-drain-{job.job_id}", daemon=True).start()
        return job

    def _apply(self, job: Job, msg: Any) -> None:
        """One message off the child's queue (protocol in `engine.build_worker`'s docstring)."""
        if not isinstance(msg, dict):
            return
        kind = msg.get("type")
        if kind == "progress":
            job._set(progress=Progress(
                phase=str(msg.get("phase", "")),
                phase_index=int(msg.get("phase_index", 0) or 0),
                n_phases=int(msg.get("n_phases", 1) or 1),
                pct=float(msg.get("pct", 0.0) or 0.0),
                message=str(msg.get("message", "") or ""),
                eta_s=msg.get("eta_s"),
            ))
        elif kind == "log":
            line = str(msg.get("line", "")).rstrip()
            if line:
                job._log(line)
        elif kind == "done":
            job._finish("done", result=msg.get("result"))
        elif kind == "error":
            job._finish("failed", error=msg.get("error") or {"code": "job_failed", "message": "?"})

    # --- querying / controlling ---------------------------------------------------------
    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        """Newest first."""
        with self._lock:
            return [self._jobs[j] for j in reversed(self._order) if j in self._jobs]

    def cancel(self, job_id: str) -> Job:
        """Idempotent. A `done` job raises `NotCancellable` -> the server returns 409.

        Thread jobs: set the cancel event and return immediately (`state = "cancelled"` only once
        `fn` actually unwinds). Process jobs: `terminate()`, then `join(timeout=5)`, then `kill()`.
        """
        j = self.get(job_id)
        if j is None:
            raise NotCancellable(f"no such job: {job_id}")
        if j.state in ("done", "failed"):
            raise NotCancellable(f"job {job_id} has already finished ({j.state})")
        if j.state == "cancelled":
            return j                                     # idempotent

        if j._proc is not None:
            proc = j._proc
            # Mark it cancelled FIRST: the drain thread must not race in and call this a crash.
            j._finish("cancelled")
            try:
                if proc.is_alive():
                    proc.terminate()
                    proc.join(timeout=5)
                if proc.is_alive():
                    proc.kill()
                    proc.join(timeout=5)
            except Exception:                            # noqa: BLE001
                pass
        elif j._cancel is not None:
            j._cancel.set()                              # `fn` unwinds and the runner marks it
        return j

    def running(self, kind: JobKind | None = None) -> Job | None:
        """The currently-running job of this kind, if any. `server.py` uses
        `JOBS.running("build")` to decide whether `/api/match/*` must return 409."""
        with self._lock:
            for jid in reversed(self._order):
                j = self._jobs.get(jid)
                if j is None:
                    continue
                if j.state in ("queued", "running") and (kind is None or j.kind == kind):
                    return j
        return None


#: THE registry. Import this, do not construct another.
JOBS: JobRegistry = JobRegistry()
