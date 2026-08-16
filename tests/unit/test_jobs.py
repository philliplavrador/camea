"""The job runner. start -> job id -> poll -> cancel.

The assertions that matter, and the bug each one pins:

  * **A cancelled job says `cancelled`, not `failed`.** v1 had TWO `Cancelled` classes (§6.1 of
    docs/SPLIT.md): `loader.Cancelled` was raised and `jobs.Cancelled` was caught, so every cancelled
    `open` was reported as a crash, with a traceback. There is now exactly one.
  * **The lease, not the kind.** v1's registry hard-coded "one *build* at a time" — a feature's word
    in the core runner — and applied it to thread jobs too, so `open` and `export` were refused
    outright while a build ran. A job takes a named lease or it competes with nothing.
  * **A terminal state is final.** A late queue message must never resurrect a cancelled job.
  * **`elapsed_s` is live and `eta_s` is raw.** That pair is the whole backend half of "the ETA must
    count down every second" (FIXES.md #8). There is deliberately NO server-side heartbeat: with a
    global-linear estimator, re-emitting during a silent phase makes the ETA count *UP*.
  * **Cancel really kills a child process.** Tested against a worker that checks no flag at all.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

from camea.core import jobs
from camea.core.jobs import (
    JOBS,
    Busy,
    Cancelled,
    Job,
    JobRegistry,
    NotCancellable,
    Progress,
    check_cancelled,
    is_cancelled,
    phase_reporter,
    report_adapter,
)

WIN = sys.platform == "win32"


@pytest.fixture()
def reg() -> JobRegistry:
    """A private registry. Never the module-level `JOBS` — a test must not leave state in it."""
    return JobRegistry()


def wait(job: Job, *states: str, timeout: float = 20.0) -> Job:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if job.state in states:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job.job_id} stuck in {job.state!r} (wanted {states}); "
                         f"log={job.log_tail[-4:]} error={job.error}")


# =============================================================================
# Thread jobs
# =============================================================================
def test_thread_job_runs_reports_and_returns_its_result(reg: JobRegistry) -> None:
    def fn(report, cancel):
        report(Progress(phase="a", phase_index=1, n_phases=2, pct=50.0, message="halfway"))
        return {"answer": 42}

    job = wait(reg.submit_thread("open", fn), "done")
    assert job.result == {"answer": 42}
    assert job.progress.pct == 100.0            # the runner stamps a 100 % `done` phase
    assert "halfway" in job.log_tail            # a progress MESSAGE is also a log line


def test_a_cancelled_thread_job_is_cancelled_not_failed(reg: JobRegistry) -> None:
    """🔴 THE §6.1 BUG. Two `Cancelled` classes meant a cancel was reported as a crash."""
    started = threading.Event()

    def fn(report, cancel):
        started.set()
        while True:                             # polls the flag, as a thread job must
            check_cancelled(cancel, "open")
            time.sleep(0.01)

    job = reg.submit_thread("open", fn)
    assert started.wait(5)
    reg.cancel(job.job_id)
    wait(job, "cancelled")
    assert job.state == "cancelled"
    assert job.error is None                    # NOT a traceback
    assert job.cancellable is False


def test_check_cancelled_raises_the_one_cancelled(reg: JobRegistry) -> None:
    ev = threading.Event()
    assert is_cancelled(ev) is False
    check_cancelled(ev)                         # not set: no-op
    ev.set()
    assert is_cancelled(ev) is True
    with pytest.raises(Cancelled):
        check_cancelled(ev)
    # it must be THIS class — `submit_thread` catches this one and nothing else
    assert Cancelled is jobs.Cancelled
    # and it tolerates a plain callable, and None (a job run outside the registry)
    assert is_cancelled(lambda: True) is True
    assert is_cancelled(None) is False


def test_a_thread_job_that_raises_is_failed_with_a_traceback(reg: JobRegistry) -> None:
    def fn(report, cancel):
        raise RuntimeError("boom")

    job = wait(reg.submit_thread("export", fn), "failed")
    assert job.error["code"] == "job_failed"
    assert "RuntimeError: boom" in job.error["message"]
    assert "boom" in job.error["traceback"]
    assert job.result is None


# =============================================================================
# The exclusive lease — what replaced `_guard_build`
# =============================================================================
def _block(ev: threading.Event):
    def fn(report, cancel):
        ev.wait(10)
        return "ok"
    return fn


def test_one_lease_holder_at_a_time(reg: JobRegistry) -> None:
    ev = threading.Event()
    held = reg.submit_thread("build", _block(ev), exclusive="gpu")
    wait(held, "running")

    with pytest.raises(Busy):
        reg.submit_thread("build", _block(ev), exclusive="gpu")
    with pytest.raises(Busy):                   # a DIFFERENT kind, same card: still refused
        reg.submit_process("segment", "jobs_child.ok_worker", {}, exclusive="gpu")

    assert reg.holder("gpu") is held
    ev.set()
    wait(held, "done")
    assert reg.holder("gpu") is None            # the lease is released by finishing. Nothing to call.
    reg.submit_thread("build", _block(threading.Event()), exclusive="gpu")   # and now it is free


def test_a_lease_only_blocks_the_same_resource(reg: JobRegistry) -> None:
    ev = threading.Event()
    gpu = reg.submit_thread("build", _block(ev), exclusive="gpu")
    wait(gpu, "running")
    other = reg.submit_thread("segment", _block(ev), exclusive="tpu")     # a different resource
    assert other.state in ("queued", "running")
    assert reg.holder("tpu") is other
    ev.set()


def test_an_unleased_job_runs_alongside_a_leased_one(reg: JobRegistry) -> None:
    """v1 refused `open` and `export` outright while a build ran — the guard was on the KIND."""
    ev = threading.Event()
    build = reg.submit_thread("build", _block(ev), exclusive="gpu")
    wait(build, "running")

    opened = wait(reg.submit_thread("open", lambda r, c: "loaded"), "done")
    assert opened.result == "loaded"            # not Busy, not queued behind the build
    assert build.state == "running"
    ev.set()


def test_kind_is_a_free_string(reg: JobRegistry) -> None:
    """🔶 v1 hard-coded `Literal["open","build","export"]`. A feature registers its own kinds."""
    job = wait(reg.submit_thread("segmentation:train", lambda r, c: None), "done")
    assert job.kind == "segmentation:train"
    assert job.to_json()["kind"] == "segmentation:train"


def test_a_labelled_holder_is_named_in_plain_words_by_the_busy_message(reg: JobRegistry) -> None:
    """⭐ 2026-08-16: a submit may carry a plain-words label, and a refusal then names the running
    job with it — "…while copying a recording in" beats a kind string he cannot read."""
    ev = threading.Event()
    held = reg.submit_thread("mea_copy", _block(ev), exclusive="disk",
                             label="copying a recording in")
    wait(held, "running")
    assert held.label == "copying a recording in"
    assert held.said_as == "copying a recording in"

    with pytest.raises(Busy, match="while copying a recording in") as e:
        reg.submit_thread("export", _block(ev), exclusive="disk")
    assert held.job_id in str(e.value)          # the id still rides along for a debugger
    ev.set()


def test_an_unlabelled_holder_keeps_the_old_busy_message_byte_for_byte(reg: JobRegistry) -> None:
    """⚠️ The videomosaic submit sites have not opted in, and their 409 bodies must not move under
    them from a core change. This is the byte-compat promise, pinned."""
    ev = threading.Event()
    held = reg.submit_thread("build", _block(ev), exclusive="gpu")
    wait(held, "running")

    with pytest.raises(Busy) as e:
        reg.submit_thread("build", _block(ev), exclusive="gpu")
    assert str(e.value) == f"job {held.job_id} (build) holds the 'gpu' lease"
    ev.set()


def test_said_as_falls_back_to_a_humanized_kind() -> None:
    """The default for any surface that must name an unlabelled job in a sentence."""
    j = Job(job_id="job_x", kind="mea_envelope")
    assert j.said_as == "running a mea envelope job"


# =============================================================================
# The Job object
# =============================================================================
def test_a_terminal_state_is_final(reg: JobRegistry) -> None:
    """A late message off the child's queue must never resurrect a cancelled job."""
    job = reg._new_job("build", cancellable=True, exclusive=None)
    job._finish("cancelled")
    reg._apply(job, {"type": "done", "result": {"positions": {}}})
    reg._apply(job, {"type": "error", "error": {"code": "x", "message": "y"}})
    assert job.state == "cancelled"
    assert job.result is None
    assert job.error is None


def test_log_tail_is_capped(reg: JobRegistry) -> None:
    job = reg._new_job("build", cancellable=True, exclusive=None)
    for i in range(jobs.LOG_TAIL_MAX + 50):
        job._log(f"line {i}")
    assert len(job.log_tail) == jobs.LOG_TAIL_MAX
    assert job.log_tail[-1] == f"line {jobs.LOG_TAIL_MAX + 49}"      # the LAST 200, not the first
    assert len(job.to_json()["log_tail"]) == jobs.LOG_TAIL_MAX       # the wire carries all of them


def test_elapsed_is_live_and_eta_is_raw(reg: JobRegistry) -> None:
    """⏱️ FIXES.md #8, the backend half. The front end ticks the countdown down locally between
    polls from `(eta_s, elapsed_s)`, and re-anchors ONLY when the raw `eta_s` changes.

    ⛔ So `eta_s` must be handed back EXACTLY as the job reported it, and there must be no
    server-side heartbeat: with `eta = elapsed * (100 - pct) / pct`, re-emitting during a silent
    phase (where `pct` is pinned) makes the ETA count *UP*.
    """
    ev = threading.Event()

    def fn(report, cancel):
        report(Progress(phase="anchors", phase_index=4, n_phases=6, pct=45.0, eta_s=126.0))
        ev.wait(10)

    job = reg.submit_thread("build", fn)
    wait(job, "running")
    while job.progress.eta_s is None:
        time.sleep(0.01)

    a = job.to_json()
    time.sleep(1.1)
    b = job.to_json()

    assert b["elapsed_s"] > a["elapsed_s"]      # LIVE: it moves without the job saying anything
    assert a["eta_s"] == b["eta_s"] == 126.0    # RAW: the silent phase does not re-estimate
    ev.set()


def test_to_json_satisfies_the_api_contract(reg: JobRegistry) -> None:
    from camea.api import schemas

    ev = threading.Event()
    job = reg.submit_thread("build", lambda r, c: ev.wait(5), exclusive="gpu")
    wait(job, "running")
    m = schemas.Job.model_validate(job.to_json())    # the contract, not a hand-written dict shape
    assert m.state == "running"
    assert m.exclusive == "gpu"
    assert m.cancellable is True
    assert m.result is None                          # null until state == "done"
    ev.set()


def test_cancel_is_idempotent_and_refuses_a_finished_job(reg: JobRegistry) -> None:
    job = wait(reg.submit_thread("open", lambda r, c: 1), "done")
    with pytest.raises(NotCancellable):
        reg.cancel(job.job_id)
    with pytest.raises(NotCancellable):
        reg.cancel("job_nope")

    ev = threading.Event()
    live = reg.submit_thread("open", _block(ev))
    wait(live, "running")
    reg.cancel(live.job_id)
    ev.set()
    wait(live, "cancelled")
    assert reg.cancel(live.job_id).state == "cancelled"       # idempotent


def test_history_evicts_finished_jobs_but_never_a_running_one() -> None:
    reg = JobRegistry(max_history=4)
    ev = threading.Event()
    live = reg.submit_thread("build", _block(ev))
    wait(live, "running")
    for _ in range(10):
        wait(reg.submit_thread("open", lambda r, c: None), "done")
    ids = [j.job_id for j in reg.list()]
    assert len(ids) == 4
    assert live.job_id in ids                    # the running job survived the cap
    assert reg.get(live.job_id) is live
    ev.set()


def test_list_is_newest_first(reg: JobRegistry) -> None:
    a = wait(reg.submit_thread("open", lambda r, c: None), "done")
    b = wait(reg.submit_thread("open", lambda r, c: None), "done")
    assert [j.job_id for j in reg.list()][:2] == [b.job_id, a.job_id]


def test_jobs_is_the_module_level_singleton() -> None:
    assert isinstance(JOBS, JobRegistry)
    assert jobs.JOBS is JOBS


# =============================================================================
# The progress adapters
# =============================================================================
def test_phase_reporter_counts_the_index_for_you() -> None:
    seen: list[Progress] = []
    emit = phase_reporter(seen.append, jobs.OPEN_PHASES)
    emit("load_frames", 40.0, "reading 312 frames")
    p = seen[-1]
    assert (p.phase, p.phase_index, p.n_phases) == ("load_frames", 3, len(jobs.OPEN_PHASES))
    assert p.pct == 40.0 and p.message == "reading 312 frames"
    emit("done", 100.0)
    assert seen[-1].phase_index == len(jobs.OPEN_PHASES)


def test_say_clamps_pct() -> None:
    seen: list[Progress] = []
    jobs.say(seen.append, "x", 1, 2, 140.0)
    jobs.say(seen.append, "x", 1, 2, -3.0)
    assert [p.pct for p in seen] == [100.0, 0.0]
    jobs.say(None, "x", 1, 2, 50.0)              # report=None is a no-op, never a crash


def test_report_adapter_accepts_anything_and_never_raises() -> None:
    seen: list[Progress] = []
    r = report_adapter(seen.append)
    r(Progress(phase="a", pct=1.0))
    r({"phase": "b", "pct": 2.0, "eta_s": 5.0})
    r("c", 3.0, "positional")
    assert [p.phase for p in seen] == ["a", "b", "c"]
    assert seen[1].eta_s == 5.0
    assert seen[2].message == "positional"

    def explode(_p):
        raise RuntimeError("the UI adapter died")

    report_adapter(explode)(Progress(phase="x"))   # progress must NEVER break a job
    report_adapter(None)(Progress(phase="x"))


# =============================================================================
# Process jobs — the reason this module exists
# =============================================================================
def test_child_sys_path_starts_with_the_dir_that_holds_the_package() -> None:
    """v1 prepended a computed `repo_root`, which is wrong for a `src/` layout: the repo root holds
    no importable package at all."""
    import camea

    assert jobs._child_sys_path()[0] == str(Path(camea.__file__).resolve().parents[1])


@pytest.mark.skipif(not WIN, reason="spawn semantics are measured on Windows, which is what ships")
def test_a_process_job_streams_progress_and_finishes(reg: JobRegistry) -> None:
    job = wait(reg.submit_process("build", "jobs_child.ok_worker", {"n": 3}), "done", timeout=60)
    assert job.result == {"n": 3}
    assert job.progress.phase == "work"
    assert job.progress.pct == 100.0
    assert any("step 3" in line for line in job.log_tail)
    assert job.to_json()["eta_s"] == 0.0


@pytest.mark.skipif(not WIN, reason="spawn semantics are measured on Windows, which is what ships")
def test_cancel_terminates_a_child_that_checks_no_flag(reg: JobRegistry) -> None:
    """⭐ THE WHOLE POINT OF `submit_process`. `forever_worker` polls nothing — exactly like
    `t33.place`, which has no cancel check anywhere in it. `terminate()` is the only way."""
    job = reg.submit_process("build", "jobs_child.forever_worker", {}, exclusive="gpu")
    wait(job, "running")
    while not job.log_tail and job.progress.pct == 0.0:
        time.sleep(0.05)                         # it is genuinely up and working

    reg.cancel(job.job_id)
    assert job.state == "cancelled"              # marked BEFORE terminate(), so drain cannot call
    assert job.error is None                     # it a crash
    assert not job._proc.is_alive()

    deadline = time.time() + 10
    while reg.holder("gpu") is not None and time.time() < deadline:
        time.sleep(0.05)
    assert reg.holder("gpu") is None             # and the lease came back
    assert job.state == "cancelled"              # the drain thread did NOT overwrite it with failed
    time.sleep(1.0)
    assert job.state == "cancelled"


@pytest.mark.skipif(not WIN, reason="spawn semantics are measured on Windows, which is what ships")
def test_a_crashing_child_reports_its_traceback(reg: JobRegistry) -> None:
    job = wait(reg.submit_process("build", "jobs_child.crash_worker", {}), "failed", timeout=60)
    assert job.error["code"] == "job_failed"
    assert "ValueError: the child blew up" in job.error["message"]
    assert "crash_worker" in job.error["traceback"]


@pytest.mark.skipif(not WIN, reason="the exit codes are Windows NTSTATUS values")
def test_a_native_fastfail_is_diagnosed_not_called_a_cuda_oom(reg: JobRegistry) -> None:
    """🔴 The child can die with NO Python exception: a delay-loaded DLL that is not on the search
    path fast-fails the process. The hint must name STATUS_DELAY_LOAD_FAILED and must say it is NOT
    a CUDA OOM — the whole reason the comment carries both codes in both signednesses is that the
    old label sent a debugger after the wrong bug.
    """
    job = wait(reg.submit_process("build", "jobs_child.native_fastfail_worker", {}),
               "failed", timeout=60)
    msg = job.error["message"]
    assert "child process exited with code" in msg
    assert "STATUS_DELAY_LOAD_FAILED" in msg
    assert "NOT a CUDA OOM" in msg
    assert "predance" in msg                     # and it names the thing that prevents it
