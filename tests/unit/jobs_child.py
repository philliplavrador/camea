"""Spawn targets for `tests/unit/test_jobs.py`. **A real child process, not a fake.**

`submit_process` exists for exactly one reason — the work it runs cannot be cancelled cooperatively,
so cancel is `proc.terminate()` — and a mock cannot test that. So these are genuine module-level
functions, imported by dotted path in a fresh `spawn` interpreter, exactly as
`camea.features.mosaic.solve.build_worker` will be.

⚠️ Module-level and side-effect-free: `spawn` re-imports this module in the child.
"""
from __future__ import annotations

import os
import time


def ok_worker(queue, n: int = 3, result=None) -> None:
    """Narrate, then finish. The happy path of the child→parent protocol."""
    for i in range(n):
        queue.put({"type": "progress", "phase": "work", "phase_index": i + 1, "n_phases": n,
                   "pct": 100.0 * (i + 1) / n, "message": f"step {i + 1}", "eta_s": float(n - i - 1)})
        queue.put({"type": "log", "line": f"[child] step {i + 1}"})
    queue.put({"type": "done", "result": result if result is not None else {"n": n}})


def forever_worker(queue) -> None:
    """Uninterruptible by design — nothing in here checks a flag. `t33.place`, in miniature.
    The ONLY way to stop it is `terminate()`."""
    queue.put({"type": "progress", "phase": "work", "pct": 1.0, "message": "started"})
    while True:
        time.sleep(0.05)


def crash_worker(queue) -> None:
    """Raises. `_process_entry` must still get an `error` message back to the parent."""
    raise ValueError("the child blew up")


def native_fastfail_worker(queue, code: int = 0xC06D007F) -> None:
    """Dies with NO Python exception and NO message on the queue — a native fast-fail.

    This is what numpy's delay-loaded BLAS does when its DLLs are not on the search path
    (0xC06D007F, STATUS_DELAY_LOAD_FAILED). The registry must diagnose it from the exit code alone.

    ⚠️ `os._exit` takes a **C int**, so the code goes in SIGNED (`-1066598273`) — while
    `Process.exitcode` hands the parent back the **unsigned** 3228369023. That is exactly the
    signedness trap the registry's comment carries both forms for; here it is, live.
    """
    queue.put({"type": "log", "line": "[child] about to die natively"})
    time.sleep(0.2)                       # let the parent drain that line first
    signed = code - 0x100000000 if code > 0x7FFFFFFF else code
    os._exit(signed)
