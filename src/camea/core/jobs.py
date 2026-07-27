"""jobs.py — the job runner. **start → job id → poll → cancel.** CORE. Feature-agnostic.

Ported from `archive/app-v1/backend/jobs.py`, and **generalised off t33**: a job here is *any slow
callable*, not "the build". `kind` is a free string and features register their own.

WHY THIS EXISTS
---------------
The app's slow work is *uninterruptible*. The mosaic solver is the specimen that proved it:
`t33.place` runs **25 s – 10 min SYNCHRONOUSLY**, has **no progress callback of any kind** (its only
signal is a `print` behind `cfg.verbose`), and **there is nothing inside it that checks a flag** — so
there is no cooperative cancel to hook. That is not a mosaic fact; it is what a scientific kernel you
did not write looks like. So:

  * every long operation is **start → job id → poll**. Nothing blocks a request;
  * a job whose callable cannot be interrupted runs in a **CHILD PROCESS**
    (`multiprocessing`, `spawn`), because **`proc.terminate()` is then the only way cancel can
    actually work.** There is no other way. `submit_process`.
  * a job that *can* poll a flag runs on a **thread** (`open`, `export` — seconds, and they check
    `cancel.is_set()` at every natural boundary). `submit_thread`.

The child re-loads whatever it needs from disk — **0.12 s for 312 frames** with the numpy reader. Do
NOT build a shared-memory apparatus to avoid a tenth of a second.

⚠️ **TWO GPU CONTEXTS.** The parent may already hold one (from interactive matching) when a compute
child starts. That is what `exclusive=` is for: a job may take a named **lease** on a resource, and
while it is held **no other job wanting that lease may start** (`Busy` → HTTP 409). On a 4 GB card a
312-tile build's device peak is ~2.0 GB and this is tight; the parent should also release its own
context before spawning. Report an OOM honestly; never retry silently on the CPU without saying so.

🔶 **This replaces v1's `_guard_build`,** which hard-coded "one *build* at a time; it owns the GPU"
into the registry — and applied it to *thread* jobs too, which is why `open` and `export` were
refused outright while a build ran. A lease is the same protection without the feature knowledge:
a future segmentation GPU job takes `exclusive="gpu"` and cannot OOM a card a mosaic build is on.

⚠️ **SPAWN + sys.path.** The child is a FRESH interpreter. It must be able to import `target` by
dotted path. `multiprocessing.spawn` copies the parent's `sys.path` into the child's preparation
data, but we ALSO pass it explicitly and re-insert it in the child, because relying on the implicit
copy is exactly the kind of thing that works on the dev box and fails in a frozen build.

⏱️ **THE ETA — AND THE HEARTBEAT THAT MUST NOT BE ADDED HERE.**
`to_json` returns **`eta_s` *and* a live `elapsed_s`**, and that pair is the whole backend half of the
"the ETA must count down every second and never look frozen" ruling (FIXES.md #8). `eta_s` is
recomputed **only when the job's child prints a recognised line** — which on the CPU path can be one
line after 205.9 s of silence — so **the ticking is the front end's**: it stores `(eta_s, received_at)`
and runs a 1 Hz local ticker, re-anchoring **only when this raw number actually changes**.

⛔ **DO NOT ADD A SERVER-SIDE ETA HEARTBEAT.** It looks like the obvious fix and it makes the bug
worse: the estimator is `eta = elapsed * (100 - pct) / pct`, so during a silent phase `pct` is pinned
and re-emitting with a growing `elapsed` makes the ETA **count UP**. It is only safe once the global
linear extrapolation is replaced by a phase-weighted one. (FIXES.md 8(b), deliberately not done.)
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
from typing import Any, Callable, Iterable, Literal

JobState = Literal["queued", "running", "done", "failed", "cancelled"]

#: 🔶 **A FREE STRING, NOT A `Literal`.** v1 hard-coded `Literal["open","build","export"]` into the
#: core registry — "build" is the *mosaic feature's* word, sitting in the runner every feature shares.
#: Features name their own kinds; the API layer discriminates `Job.result` on them
#: (`camea.api.schemas.JobResult`). Core knows none of them.
JobKind = str

#: how many raw stdout lines we keep. The wire carries all of them; the UI drawer shows the last ~8.
LOG_TAIL_MAX = 200

#: The phases of a core `open` job, in order. A plain list of names — `phase_reporter` turns it into
#: `phase_index` / `n_phases` so no caller has to count. (From `loader._OPEN_PHASES`.)
OPEN_PHASES: list[str] = [
    "scan_dir", "parse_log", "load_frames", "flat_field", "tone", "texture", "done",
]


def _iso(t: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t if t is not None else time.time()))


@dataclass
class Progress:
    """One progress snapshot. Everything here is optional except `phase`.

    `pct` is **overall**, and a job with wildly unequal phases is expected to weight them itself —
    the weighting is the job's knowledge, not the registry's. (The mosaic build's tables live in
    `features/mosaic/solve.py`, and there are *two* of them, because on CPU pass1+backbone is 75 % of
    the build while on GPU the anchor loop is 53 %: one GPU-calibrated table told a CPU user
    "873 s left" when 368 s remained.)

    `eta_s` is whatever the job last said. It may be `None` (a silent phase) and **it may jump UP** —
    an honest revision beats a smooth lie. See the module docstring: do not smooth it here.
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
    #: the exclusive-resource lease this job holds while it is queued/running, e.g. `"gpu"`. `None` =
    #: it competes with nothing.
    exclusive: str | None = None
    progress: Progress = field(default_factory=Progress)
    started_at: str = ""
    finished_at: str | None = None
    elapsed_s: float = 0.0
    #: the last `LOG_TAIL_MAX` raw log lines
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
        """The exact shape of `GET /api/jobs/{job_id}` (`api.schemas.Job`). Must be JSON-safe.

        ⚠️ `result` may hold something that is **NOT JSON-serializable** — a mosaic build's `info`
        carries a nested `t27.Config` and `json.dumps` CRASHES on it. It must already have been made
        safe by the job (the mosaic child does exactly that before it puts it on the queue), because
        the registry will not coerce what it cannot know the shape of.

        ⏱️ `elapsed_s` is **LIVE while the job runs** — recomputed from `_t0` on every poll, not
        frozen at the last progress message. The front end's 1 Hz countdown is built on this pair
        (`eta_s`, `elapsed_s`); see the module docstring.
        """
        with self._lock:
            p = self.progress
            elapsed = self.elapsed_s if self.state in ("done", "failed", "cancelled") \
                else (time.time() - self._t0 if self._t0 else 0.0)
            return {
                "job_id": self.job_id,
                "kind": self.kind,
                "state": self.state,
                "exclusive": self.exclusive,
                "phase": p.phase,
                "phase_index": int(p.phase_index),
                "n_phases": int(p.n_phases),
                "pct": round(float(p.pct), 1),
                "message": p.message,
                "started_at": self.started_at,
                "elapsed_s": round(float(elapsed), 1),
                "eta_s": (None if p.eta_s is None else round(float(p.eta_s), 1)),
                # the WHOLE tail (up to LOG_TAIL_MAX). v1 truncated to 8 here and the schema says
                # 200 — the "show ~8" is the drawer's decision, not the wire's.
                "log_tail": list(self.log_tail),
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
    """Raised by a thread job's `fn` when it sees its cancel event.

    ⛔ **THERE IS EXACTLY ONE OF THESE, AND IT IS THIS ONE.** v1 had a second `loader.Cancelled`;
    `open_session` raised *that* one and `submit_thread` caught *this* one, so cancelling an `open`
    fell through to `except BaseException` and the job was marked **`failed`, with a traceback**,
    instead of `cancelled`. Never define another. Import it from here.
    """


class Busy(Exception):
    """Another job holds the exclusive lease this one wants. -> HTTP 409 `{"error": {"code": "busy"}}`"""


class NotCancellable(Exception):
    """The job already finished. -> HTTP 409."""


# =============================================================================
# Cancellation + progress helpers — the plumbing every job needs
# =============================================================================
def is_cancelled(cancel: Any) -> bool:
    """`cancel` is the `threading.Event` `submit_thread` hands to `fn` — but tolerate a plain
    callable, and `None` (a job run outside the registry, e.g. in a test)."""
    if cancel is None:
        return False
    if hasattr(cancel, "is_set"):
        return bool(cancel.is_set())
    if callable(cancel):
        return bool(cancel())
    return False


def check_cancelled(cancel: Any, what: str = "job") -> None:
    """Raise `Cancelled` if the flag is set. **A thread job MUST call this at every natural
    boundary** (per frame loaded, per tile rendered). A job that ignores its cancel event is a job
    the user cannot stop."""
    if is_cancelled(cancel):
        raise Cancelled(f"{what} cancelled")


def say(report: Callable[[Progress], None] | None, phase: str, idx: int, n: int,
        pct: float, message: str = "", eta_s: float | None = None) -> None:
    """Emit one `Progress`. Clamps `pct` to [0, 100] and tolerates `report=None`."""
    if report is None:
        return
    report(Progress(phase=phase, phase_index=int(idx), n_phases=int(n),
                    pct=min(100.0, max(0.0, float(pct))), message=message, eta_s=eta_s))


def phase_reporter(report: Callable[[Progress], None] | None,
                   phases: Iterable[str]) -> Callable[..., None]:
    """`report` + a phase LIST -> `emit(phase, pct, message="")`, which counts the index for you.

    A job that knows its phases up front should not also have to know its own `phase_index` at every
    call site. `emit("tone", 60.0, "windowing")` is all a caller needs.

    (This is v1's `loader._reporter`, minus the reason it existed: it built the `Progress` through a
    lazy `try: from .jobs import Progress` because a *different agent owned jobs.py*. That reason is
    gone. Import `Progress` directly.)
    """
    names = list(phases)

    def emit(phase: str, pct: float, message: str = "", eta_s: float | None = None) -> None:
        idx = (names.index(phase) + 1) if phase in names else 0
        say(report, phase, idx, len(names), pct, message, eta_s)

    return emit


def report_adapter(report: Callable[[Progress], None] | None) -> Callable[..., None]:
    """Wrap a raw `report` so it accepts a `Progress`, a kwargs bag, a dict, or `(phase, pct,
    message)` positionally — **and never raises into the worker.**

    Deliberately tolerant, and it stays that way: progress reporting must never be able to fail a job
    that is otherwise succeeding. (v1 had two copies of this, `loader._reporter` and
    `server._report_adapter`. One.)
    """
    def r(*a, **kw) -> None:
        if report is None:
            return
        try:
            if a and isinstance(a[0], Progress):
                report(a[0])
                return
            if a and isinstance(a[0], dict):
                kw = {**a[0], **kw}
                a = ()
            if a:
                for key, val in zip(("phase", "pct", "message"), a):
                    kw.setdefault(key, val)
            report(Progress(
                phase=str(kw.get("phase", "")),
                phase_index=int(kw.get("phase_index", 0) or 0),
                n_phases=int(kw.get("n_phases", 1) or 1),
                pct=float(kw.get("pct", 0.0) or 0.0),
                message=str(kw.get("message", "") or ""),
                eta_s=kw.get("eta_s"),
            ))
        except Exception:  # noqa: BLE001 — progress must never break a job
            pass
    return r


# =============================================================================
# The child-process entry point
# =============================================================================
def _process_entry(target: str, kwargs: dict, q, sys_path: list[str]) -> None:
    """Runs in the SPAWNED CHILD. Re-establishes `sys.path`, imports `target` by dotted path,
    and calls it with `queue=q`.

    Must be module-level (spawn pickles it by qualified name) and must not close over anything.

    ⚠️ The `sys_path` re-insert is **on purpose** — do not "simplify" it away. It is what makes a
    frozen build work.
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


def _child_sys_path() -> list[str]:
    """The `sys.path` the child gets: **the parent's, as-is, plus the directory that contains the
    `camea` package.**

    ⚠️ v1 computed a `repo_root` and prepended it, which is wrong for a `src/` layout — under `uv`
    the package is *installed* and the repo root contains no importable package at all. The dir that
    contains `camea/` is `src/` in a dev checkout and `site-packages/` in an installed one; in the
    second case it is already on `sys.path` and prepending it is a harmless no-op.
    """
    pkg_parent = str(Path(__file__).resolve().parents[2])   # .../src   (…/core/jobs.py → camea → src)
    out = [pkg_parent]
    for p in sys.path:
        if p and p not in out:
            out.append(p)
    return out


# =============================================================================
# The registry
# =============================================================================
class JobRegistry:
    """Thread-safe job table. One instance, module-level: `JOBS`.

    Concurrency rules, and they are part of the contract:
      * **Jobs run concurrently by default.** The registry imposes no serialisation of its own.
      * **An EXCLUSIVE LEASE serialises the jobs that need it.** `submit_*(..., exclusive="gpu")`
        raises `Busy` if another queued/running job already holds `"gpu"`; the API turns that into
        `409 {"error": {"code": "busy"}}`. The lease is released when the job reaches a terminal
        state — there is nothing to remember to call.
      * Interactive work (a ~1 s match) does NOT go through this registry — it runs on the server's
        thread pool. The API refuses it with 409 while a lease it would fight over is held
        (`JOBS.holder("gpu")`).
    """

    def __init__(self, max_history: int = 32) -> None:
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []           # oldest -> newest
        #: RLock, not Lock: `_claim` checks the lease and creates the job as ONE atomic step, and the
        #: check calls `holder()`, which takes the lock itself. Two simultaneous submits must not
        #: both pass a lease guard.
        self._lock = threading.RLock()
        self._max_history = int(max_history)
        self._ids = itertools.count(1)

    # --- internals ----------------------------------------------------------------------
    def _new_job(self, kind: JobKind, cancellable: bool, exclusive: str | None) -> Job:
        job_id = f"job_{uuid.uuid4().hex[:6]}"
        j = Job(job_id=job_id, kind=str(kind), state="queued", started_at=_iso(),
                cancellable=cancellable, exclusive=exclusive)
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

    def _claim(self, kind: JobKind, cancellable: bool, exclusive: str | None) -> Job:
        """Take the lease (if any) and create the job, atomically. -> `Busy` if it is held."""
        with self._lock:
            if exclusive:
                held = self.holder(exclusive)
                if held is not None:
                    raise Busy(f"job {held.job_id} ({held.kind}) holds the {exclusive!r} lease")
            return self._new_job(kind, cancellable, exclusive)

    # --- submitting ---------------------------------------------------------------------
    def submit_thread(
        self,
        kind: JobKind,
        fn: Callable[[Callable[[Progress], None], threading.Event], Any],
        cancellable: bool = True,
        exclusive: str | None = None,
    ) -> Job:
        """Run `fn(report, cancel_event)` on a worker thread. For work that CAN be interrupted
        cooperatively — `open`, `export`: seconds, and they poll a flag.

        `fn` receives:
          * `report(Progress)` — call it as often as you like; it is cheap and it is what the UI polls.
          * `cancel_event` — a `threading.Event`. **`fn` MUST poll it** at every natural boundary
            (per frame loaded, per tile rendered) and raise `Cancelled` — use `check_cancelled()`.
            A job that ignores it is a job the user cannot stop.

        Whatever `fn` returns becomes `job.result` (it MUST be JSON-safe).
        """
        job = self._claim(kind, cancellable, exclusive)
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
        exclusive: str | None = None,
    ) -> Job:
        """Run a job in a CHILD PROCESS. **This is how uninterruptible work runs, and it is why
        cancel works at all**: cancel is `proc.terminate()`, and there is no cooperative path
        because the kernel inside (t33, and its kind) has no flag to check.

        `target` — a dotted path to a module-level function, e.g.
                   `"camea.features.mosaic.solve.build_worker"`. It MUST be importable in a fresh
                   `spawn` interpreter and every value in `kwargs` MUST be picklable (paths, ints,
                   dicts — never a numpy stack, never an open file, never a CuPy array).
        `exclusive` — a resource lease, e.g. `"gpu"`. See the class docstring.

        The child streams `Progress` objects and raw log lines back over an `mp.Queue`; the registry
        drains that queue on a reader thread and updates the `Job`. Protocol: `_apply`.
        """
        job = self._claim(kind, cancellable=True, exclusive=exclusive)

        ctx = mp.get_context("spawn")
        q = ctx.Queue()
        sys_path = _child_sys_path()

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
                        # environment was never ACTIVATED. A native fast-fail: no Python exception,
                        # no traceback, nothing to catch. `camea.engine.dll.predance()` runs at the
                        # module scope of `camea/engine/__init__.py` — which the spawned child
                        # re-imports — to put the DLL directories on the search path and prevent it.
                        # If you see this again, that pre-dance is not reaching the child — do not
                        # chase the GPU.
                        hint = ("a native fast-fail (STATUS_DELAY_LOAD_FAILED, 0xC06D007F — or "
                                "0xC0000409). This is NOT a CUDA OOM. It is what a delay-loaded "
                                "native DLL does when it is not on the search path — classically "
                                "numpy's BLAS when the app was launched from an UNACTIVATED "
                                "environment and camea.engine.dll.predance() did not reach the child")
                    job._finish("failed", error={
                        "code": "job_failed",
                        "message": (f"the {job.kind} job's child process exited with code {code} "
                                    f"without reporting a result ({hint})"),
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
        """One message off the child's queue. **The child→parent protocol, in full:**

            {"type": "progress", "phase", "phase_index", "n_phases", "pct", "message", "eta_s"}
            {"type": "log",      "line"}
            {"type": "done",     "result"}      <- MUST already be JSON-safe
            {"type": "error",    "error": {"code", "message", "traceback"}}

        Anything else is ignored. A message that arrives after a terminal state is dropped by
        `Job._finish`.
        """
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

    def forget_finished(self) -> None:
        """Drop every job in a terminal state. ⚠️ **For test isolation only.**

        `JOBS` is process-level, so a test that submits into it leaks into every later test in the
        same process — and a leaked job with a result the API's discriminated union cannot serialise
        makes `GET /api/jobs` 500 in a *different* test file. A running job is left alone: forgetting
        one would lose the only handle on it.
        """
        with self._lock:
            for jid in list(self._order):
                j = self._jobs.get(jid)
                if j is None or j.state in ("done", "failed", "cancelled"):
                    self._jobs.pop(jid, None)
                    self._order.remove(jid)

    def cancel(self, job_id: str) -> Job:
        """Idempotent. A `done`/`failed` job raises `NotCancellable` -> the API returns 409.

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
        """The newest queued/running job, of this `kind` if one is named."""
        with self._lock:
            for jid in reversed(self._order):
                j = self._jobs.get(jid)
                if j is None:
                    continue
                if j.state in ("queued", "running") and (kind is None or j.kind == kind):
                    return j
        return None

    def holder(self, resource: str) -> Job | None:
        """The job currently holding the `resource` lease, if any.

        This is what the API asks before it runs interactive work that would fight over the same
        card: `if JOBS.holder("gpu"): 409 busy`. ⚠️ Ask about the **lease**, never about a *kind* —
        "is a `build` running" is a feature's word in a core check, and it is the thing that made
        v1's registry refuse an `open` while a build ran.
        """
        with self._lock:
            for jid in reversed(self._order):
                j = self._jobs.get(jid)
                if j is None:
                    continue
                if j.state in ("queued", "running") and j.exclusive == resource:
                    return j
        return None


#: THE registry. Import this, do not construct another.
JOBS: JobRegistry = JobRegistry()
