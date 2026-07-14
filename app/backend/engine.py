"""Engine adapter — the ONLY module that imports t27 / t33 / render.

OWNER: agent 2. Nobody else edits this file.
CONTRACT: app/API.md §7 (the anchor-composite primitive), §8 (jobs), §10 (build), §14 (GPU).

⛔⛔ **THIS MODULE CALLS `analysis/mosaic/`. IT NEVER FORKS IT.**
    Two copies of t33 = a silent regression. `analysis/tests/test_mosaic_312.py` (~180 s cold,
    asserts 312/312) MUST STILL PASS after anything you change in t27/t33. Nothing in this file
    changes t27 or t33: no edit, no shadowing redefinition, no numeric copy.

    THE FOUR THINGS THIS MODULE ADDS, and why each is safe:

      1. `_subpixel()` — the separable parabola of API.md §3.5. ADDITIVE: eight more
         `t33.exact_ncc` calls on the outside. Nothing inside t33 sees it.
      2. `_CompositeCache` — the INCREMENTAL anchor composite (SPEED.md: 268 ms -> 108 ms at 156
         anchors). It keeps `t33.composite`'s running `acc`/`wsum` arrays instead of rebuilding
         them, and it is **bit-identical** — see the long proof in the class docstring. It refuses
         its own fast path (and falls back to calling `t33.composite` verbatim) the instant its
         preconditions do not hold.
      3. `enable_build_memo()` — memoises `t33._pool` on the REFERENCE side of the build's 156-call
         anchor loop, by IDENTITY of the input arrays. It caches the real function's own return
         value; it does not reimplement it. Bit-identical by construction. Child process only.
      4. A stdout scraper for progress, because t33 has no callback (API.md §8.3).

Import path
-----------
`analysis/` is a namespace package once the repo root is on `sys.path`. Redirect for a frozen
build by setting `CAMEA_REPO_ROOT` in the environment, or by editing `_repo_root()` (one constant).
"""
from __future__ import annotations

import contextlib
import glob
import hashlib
import json
import os
import re
import sys
import sysconfig
import threading
import time
import traceback
import warnings
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


# =============================================================================
# 🔴 THE FROZEN-BUILD CUDA DLL PRE-DANCE — run at IMPORT, before the first t27.xp()
# =============================================================================
def _predance_cuda_dlls() -> list[str]:
    """Put the pip `nvidia-*-cu12` DLL directories on the search path — **including under
    PyInstaller**, where `t27._cuda_dll_dance()` cannot find them.

    🔴 WHY THIS EXISTS. `t27._cuda_dll_dance()` (t27.py:120) globs
    `sysconfig.get_paths()["purelib"]/nvidia/*/bin`. Under PyInstaller `sys.prefix` is
    `sys._MEIPASS`, so purelib resolves to `<_MEIPASS>/Lib/site-packages`, **which does not exist** —
    the dance finds nothing, `cupy.zeros(1)+1` raises `CuPy failed to load nvrtc64_120_0.dll`, and
    the shipped app reports **"No usable CUDA GPU" on a machine with a perfectly good card**. Every
    build then takes 8-10 min instead of 3, forever, and nothing in the UI hints that the cause is a
    DLL search path rather than the absence of a GPU.

    ⚠️ THE FIX BELONGS HERE, NOT IN t27. `t27` is under the 312/312 regression guard
    (`analysis/tests/test_mosaic_312.py`); this is not. And it is **idempotent**: when it has already
    added the directories, t27's own dance re-adds the same ones (harmless) or globs an empty dir and
    no-ops. Running at MODULE scope also covers the **build child** (spawn re-imports `engine`),
    which would otherwise lose the GPU independently of the parent.

    Both mechanisms are needed and they are not the same one:
      * `os.add_dll_directory` — for the `.pyd`'s dependent DLLs (py3.8+ ignores PATH for those);
      * `PATH` — NVRTC loads `nvrtc-builtins` at runtime with a plain LoadLibrary, which uses PATH.
    """
    bases = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bases.append(Path(meipass))                        # the frozen layout: analysis/ + nvidia/
    try:
        bases.append(Path(sysconfig.get_paths()["purelib"]))
    except Exception:                                      # noqa: BLE001
        pass
    dirs: list[str] = []
    for base in bases:
        for d in sorted(glob.glob(str(base / "nvidia" / "*" / "bin"))):
            if os.path.isdir(d) and d not in dirs:
                dirs.append(d)
    for d in dirs:
        try:
            os.add_dll_directory(d)                        # Windows only; cookie kept by the OS
        except (AttributeError, OSError):
            pass
    if dirs:
        os.environ["PATH"] = os.pathsep.join(dirs) + os.pathsep + os.environ.get("PATH", "")
    return dirs


def _predance_env_dlls() -> list[str]:
    """Put the conda env's own native-library directories on the search path.

    🔴 WHY THIS EXISTS — MEASURED, 2026-07-12, and it silently destroyed a build.
    `numpy.linalg` **delay-loads** its BLAS. If the process was started from
    `<env>/python.exe` WITHOUT the conda environment activated, that delay-load fails and Windows
    fast-fails the process with **0xC0000409 / exit 3228369023** — a *native* crash, no Python
    exception, no traceback, nothing to catch. Reproduced on a bare interpreter:

        python.exe -s -c "import numpy as np; np.linalg.solve(np.eye(3)+0.1, np.ones(3))"   -> DIES
        conda run -n camea python -s -c "...the same..."                                    -> fine
        PATH=<env>/Library/bin + python.exe -s -c "...the same..."                          -> fine

    It killed the app in exactly the place that matters: **the build child**. `t27.solve_rigid`
    (t27.py:697 -> spectralign.placement.rigid:135) calls `np.linalg.solve`, so a COLD build died
    ~20 s in, every time, while a WARM build survived — the cache skips pass 1 and never calls BLAS.
    The job reported only "the build process exited with code 3228369023". The failure is invisible
    until someone builds a dataset for the first time, which is every user, once.

    The child inherits the parent's PATH, so an ACTIVATED launch was always fine — but nothing in
    the app enforced one, and a shortcut, a `py -m`, an IDE run config or a frozen build does not
    activate anything. Doing it here (module scope, like the CUDA pre-dance above) covers the parent
    AND the spawned build child, which re-imports this module.

    🔴 AND IT MUST NOT BE A NO-OP WHEN FROZEN. Under PyInstaller `sys.prefix` becomes `_MEIPASS`, so
    `<prefix>/Library/bin` does not exist and the loop below found NOTHING — leaving the shipped app
    with no protection at all against the very fast-fail this function exists to prevent, on the one
    code path (`np.linalg.solve`, in the first COLD build) that every user hits exactly once. So the
    bundle root itself, and the layouts PyInstaller actually produces, are searched too. ⚠️ agent 8:
    this needs a real freeze + a real cold build to prove — see `packaging/README.md`, where it is a
    REQUIRED smoke test, not a note.

    Idempotent, and a no-op where the directories do not exist (a venv, Linux).
    """
    roots = [Path(sys.prefix)]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.insert(0, Path(meipass))          # the frozen bundle: PyInstaller's DLL layout
    cand: list[Path] = []
    for prefix in roots:
        cand += [prefix / "Library" / "bin", prefix / "Library" / "mingw-w64" / "bin",
                 prefix / "Library" / "usr" / "bin", prefix / "DLLs"]
    if meipass:
        # PyInstaller routinely FLATTENS native DLLs to the bundle root, and numpy's BLAS ships in
        # `numpy.libs/` (or `numpy/.libs/`). All three, in the order the loader should see them.
        cand += [Path(meipass), Path(meipass) / "numpy.libs", Path(meipass) / "numpy" / ".libs",
                 Path(meipass) / "scipy.libs", Path(meipass) / "_internal"]
    dirs: list[str] = []
    seen: set[str] = set()                                 # frozen: sys.prefix IS _MEIPASS -> dupes
    path_now = os.environ.get("PATH", "").lower()
    for d in cand:
        s = str(d)
        if s.lower() in seen or not d.is_dir():
            continue
        seen.add(s.lower())
        try:
            os.add_dll_directory(s)                        # for .pyd dependents (py3.8+)
        except (AttributeError, OSError):
            pass
        if s.lower() not in path_now:                      # NVRTC-style plain LoadLibrary needs PATH
            dirs.append(s)
    if dirs:
        os.environ["PATH"] = os.pathsep.join(dirs) + os.pathsep + os.environ.get("PATH", "")
    return dirs


_CUDA_DLL_DIRS = _predance_cuda_dlls()
_ENV_DLL_DIRS = _predance_env_dlls()


# =============================================================================
# Import path — the ONE place that knows where analysis/ lives
# =============================================================================
def _repo_root() -> Path:
    """The directory that CONTAINS `analysis/`.

    Under PyInstaller this is `sys._MEIPASS` (agent 8 vendors `analysis/` in beside the exe).
    `CAMEA_REPO_ROOT` overrides both, for tests.
    """
    env = os.environ.get("CAMEA_REPO_ROOT")
    if env:
        return Path(env)
    frozen = getattr(sys, "_MEIPASS", None)
    if frozen:
        return Path(frozen)
    # app/backend/engine.py -> app/backend -> app -> <repo root>
    return Path(__file__).resolve().parent.parent.parent


REPO_ROOT = _repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from analysis.mosaic import render as mrender  # noqa: E402
from analysis.mosaic import t27, t33  # noqa: E402
# ⚠️ ONLY `gaps` — a pure function of the trial list it is *given*, so it is dataset-agnostic.
# `EXCLUDED` / `usable_trials` are DELIBERATELY NOT imported here. They encode the 26-snapshot
# ruling, which is a statement about **260620d only** (the user's ruling #2); the engine is handed
# its trial list by `loader.partition_trials()`, which has already applied the ruling iff it applies.
# Re-exporting the raw list from the engine was a loaded gun: the next caller would have filtered
# some *other* acquisition's trials 284-296/299/300-310/348 out of existence for free.
from analysis.ground_truth.excluded import gaps  # noqa: E402

__all__ = [
    "gpu_info", "warm_gpu", "release_gpu", "jsonable",
    "Candidate", "MatchResult", "match_anchor", "score_at", "cache_key", "reset_caches",
    "build_worker", "build_result", "read_anchors",
    "render_mosaic", "score_against_gt",
    "TILE", "ANCHOR_KPK", "ANCHOR_MINFRAC", "ANCHOR_MINABS", "MATCH_CACHE_SIZE",
    "SNAP_RADIUS", "MARGIN_THIN", "NMS_PX",
    "gaps",
]


# =============================================================================
# Constants that MUST NOT diverge (API.md §1.1)
# =============================================================================
TILE = 512
ANCHOR_KPK = 8            # ⚠️ exactly t33.place's tile-anchor call (t33.py:732)
ANCHOR_MINFRAC = 0.0      # ⚠️ ditto. For ONE tile a fractional overlap rule would let a corner
ANCHOR_MINABS = 120000.0  #    match win, so the floor is ABSOLUTE. Do not "improve" these.
MATCH_CACHE_SIZE = 32     # LRU entries for the anchor-match memo (API.md §7.4)
SNAP_RADIUS = 64
MARGIN_THIN = 0.10        # below this, the margin is the signature of a surviving alias
NMS_PX = 24.0             # t33.match's own peak separation
GPU_NOTE = (
    "GPU: a 312-tile build takes ~3 min. Without it, ~8-10 min - and the interactive sweep is "
    "only 1.46x slower (1,068 vs 1,562 ms per Space), because exact_ncc runs on the CPU either way."
)

# The phase weighting of a COLD build (API.md §8.3).
#
# 🔴 THERE ARE TWO OF THESE, AND THERE HAS TO BE. The old single table was calibrated on the GPU and
# was wrong even there. MEASURED on this box, same build, same data, 312 tiles:
#
#            pass1   backbone   anchors   runs    total
#     GPU     17 s      22 s      59 s    12 s    112 s
#     CPU    218 s     220 s     129 s    20 s    588 s      <- the SHIPPED DEFAULT install
#
# The old table said backbone was **8 %**. It is 20 % on the GPU and **37 % on the CPU**. Worse, the
# whole shape inverts: on the GPU the anchor loop dominates (53 %), on the CPU pass 1 + backbone are
# **75 % of the build**. A single GPU-calibrated table on a CPU machine is not an approximation, it is
# a different curve — it told a CPU user "~873 s left" when the true remaining time was 368 s (+137 %).
# The child knows which device it is on before it starts; it picks the right table. (SPEED.md's "the
# GPU buys 8x" is also wrong, by the way: measured end-to-end it is **5.2x**.)
PHASES = ("pass1", "backbone", "composite", "anchors", "recut", "runs")
PHASE_WEIGHT_GPU = {"pass1": 0.15, "backbone": 0.20, "composite": 0.02,
                    "anchors": 0.52, "recut": 0.01, "runs": 0.10}
PHASE_WEIGHT_CPU = {"pass1": 0.37, "backbone": 0.37, "composite": 0.01,
                    "anchors": 0.22, "recut": 0.01, "runs": 0.02}
PHASE_WEIGHT = PHASE_WEIGHT_GPU        # the historical name; the child chooses explicitly
PHASE_INDEX = {"pass1": 1, "backbone": 2, "composite": 3,
               "anchors": 4, "recut": 5, "runs": 5, "done": 6}
N_PHASES = 6


# =============================================================================
# GPU
# =============================================================================
_WARMED = False
_GPU_INFO: dict | None = None
#: ⚠️ `gpu_info()` was check-then-act with no lock, and TWO threads reach it concurrently on every
#: boot (server.py's warm thread races the front end's `GET /api/gpu`). Benign today — both arrive at
#: the same answer — but it doubled a cold detection and it would bite the instant detection grew a
#: side effect. One lock; detection happens exactly once.
_GPU_LOCK = threading.Lock()


def _gpu_failure_reason() -> str | None:
    """WHY there is no GPU — the one field a support request needs, and it was being thrown away.

    `t27.xp()` prints the exception and swallows it; in a PyInstaller **windowed** build `sys.stdout`
    is None and `print()` is a silent no-op, so the reason went nowhere at all. The user could not
    tell "this laptop has no NVIDIA card" (correct; act accordingly) from "your GPU is fine but the
    DLLs are somewhere CuPy cannot see" (a 5-minute fix — see `_predance_cuda_dlls`).

    ⚠️ THIS IS NOT A SECOND DETECTOR. It runs **only after `t27.xp()` has already ruled `no GPU`**,
    and its answer is a *string*, never a verdict. `t27.xp()` still decides, alone.
    """
    try:
        import cupy                                             # noqa: PLC0415
        cupy.zeros(1) + 1                                       # the same real op t27 ran
    except Exception as e:                                      # noqa: BLE001
        return f"{type(e).__name__}: {e}"
    return ("cupy imports and runs here, but t27.xp() ruled it unusable - "
            "the two disagree; check the console.")


def gpu_info() -> dict:
    """-> {"available", "backend", "name", "cupy", "cuda_runtime", "reason", "note"} (API.md §14).

    🔴 **CUDA DETECTION MUST EXECUTE A REAL OP.** `import cupy` **SUCCEEDS** on a broken CUDA
    install (it emits only a UserWarning); it is **`cupy.zeros(1) + 1`** that raises. A
    `try: import cupy / except ImportError` guard DOES NOT WORK.

    ⇒ We call **`t27.xp()`** (t27.py:135) and nothing else. It does the DLL dance, imports CuPy,
    forces a context with a real op, and falls back to numpy on ANY exception. There is no second
    detector in this codebase and there must not be one.

    `reason` is populated ONLY when `available` is false: the exception CuPy actually raised. Being
    honest about the *bill* (the `note`) and silent about the *bug* is how a fixable DLL-path problem
    becomes a permanent 8-minute build.
    """
    global _GPU_INFO
    with _GPU_LOCK:
        if _GPU_INFO is not None:
            return dict(_GPU_INFO)

        xp = t27.xp()                   # <- the real op happens in here, not here
        available = bool(t27.on_gpu())
        info = {
            "available": available,
            "backend": "cupy" if available else "numpy",
            "name": None,
            "cupy": None,
            "cuda_runtime": None,
            "reason": None,
            "note": GPU_NOTE if available else (
                "No usable CUDA GPU. A 312-tile build takes ~8-10 min on the CPU instead of ~3 min. "
                "The interactive sweep is only 1.46x slower (1,562 vs 1,068 ms per Space), because "
                "exact_ncc runs on the CPU either way - the part you spend an hour in is barely "
                "affected."),
        }
        if available:
            try:
                info["cupy"] = str(xp.__version__)
                info["cuda_runtime"] = int(xp.cuda.runtime.runtimeGetVersion())
                props = xp.cuda.runtime.getDeviceProperties(0)
                name = props["name"]
                info["name"] = name.decode() if isinstance(name, bytes) else str(name)
            except Exception as e:                               # noqa: BLE001
                info["name"] = f"(CUDA device, details unavailable: {type(e).__name__})"
        else:
            info["name"] = "CPU (numpy)"
            info["reason"] = _gpu_failure_reason()
            info["dll_dirs"] = list(_CUDA_DLL_DIRS)              # [] under a broken frozen build
        _GPU_INFO = info
        return dict(info)


def warm_gpu() -> dict:
    """Call `t27.xp()` once, on a worker thread, at app start. Idempotent.

    Worth **-497 ms off the first match** (SPEED.md), and it surfaces a broken CUDA install at
    launch instead of forty minutes into a sweep. Also builds the cuFFT plan cache with one
    throwaway transform, which is where most of that 497 ms lives.

    ⚠️ `cupy.random` is BROKEN in this env (missing cuRAND DLL). Seed from numpy and `asarray` —
    never touch `cupy.random`. (We use zeros; nothing here needs randomness.)
    """
    global _WARMED
    if _WARMED:
        return gpu_info()
    info = gpu_info()
    if info["available"]:
        try:
            xp = t27.xp()
            a = xp.asarray(np.zeros((256, 256), np.float32))     # NOT cupy.random - it is broken
            f = xp.fft.rfft2(a, s=(512, 512))                    # build the cuFFT plan cache
            _ = xp.fft.irfft2(f * xp.conj(f), s=(512, 512))
            xp.cuda.Stream.null.synchronize()
            del a, f
            t27._free()
        except Exception as e:                                   # noqa: BLE001
            print(f"[gpu] warm-up failed after detection succeeded ({type(e).__name__}: {e})")
    _WARMED = True
    return info


def release_gpu() -> None:
    """Drop the CuPy memory pool. Called BEFORE spawning a build child, so the parent's device
    footprint does not collide with the child's (312 tiles peak ~2.0 GB; a 4 GB card is tight)."""
    try:
        t27._free()
    except Exception:                                            # noqa: BLE001
        pass


# =============================================================================
# JSON
# =============================================================================
def jsonable(obj):
    """Make t33's `info` JSON-safe.

    ⚠️ **`info["config"]` IS NOT JSON-SERIALIZABLE** — it holds a nested `t27.Config` object and
    **`json.dumps(info)` CRASHES.** `build_mosaic.ipynb` handles it with
    `default=lambda o: vars(o)`. We do the same, and coerce numpy scalars/arrays as well (they are
    all over `info`), recursively, so the result survives `json.dumps` with no `default=` at all.
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        if isinstance(obj, float) and not np.isfinite(obj):
            return None                                          # NaN/Inf are not JSON
        return obj
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        return v if np.isfinite(v) else None
    if isinstance(obj, np.ndarray):
        return jsonable(obj.tolist())
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [jsonable(v) for v in obj]
    if isinstance(obj, dict):
        return {(k if isinstance(k, str) else str(k)): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "__dict__"):
        return jsonable(vars(obj))                               # <- t27.Config / t33.Config
    return str(obj)


# =============================================================================
# ⭐ THE INCREMENTAL ANCHOR COMPOSITE  (SPEED.md #3: 268 ms -> 108 ms at 156 anchors)
# =============================================================================
class _CompositeCache:
    """Keep `t33.composite`'s running `acc`/`wsum` arrays instead of rebuilding them every match.

    ⭐ WHY THIS IS BIT-IDENTICAL, and not merely "close". `t33.composite` accumulates

        for k, (x, y) in enumerate(P):
            acc[y:y+512, x:x+512] += B[rows[k]] * feather

    so every canvas pixel holds a float32 sum taken in `k` order. If we (a) add tiles in exactly
    that order, and (b) only ever APPEND, then the partial sum after m tiles is bit-for-bit the
    prefix of the full sum — float addition is not associative, but it *is* deterministic, and we
    never reorder or re-associate anything. Growing the canvas is a pure integer paste of the old
    array into a bigger one, which changes no value at all.

    THE PRECONDITIONS, each of which is CHECKED and each of which falls back to calling
    `t33.composite` verbatim when it fails:

      1. Same session (same band stack).
      2. The new sorted anchor list has the OLD one as a PREFIX, and the old tiles' positions are
         unchanged. (Anchoring during a sweep appends in ascending trial order, so this is the hot
         path. Re-dragging an anchor, or rescuing an out-of-order tile, correctly rebuilds.)
      3. ⚠️ **The integer layout of the old tiles must be a pure TRANSLATION of what it was.**
         `P = rint(local - m0)` and `m0 = local.min(0)` — so when a new tile extends the layout,
         `m0` moves, and if it moves by a NON-INTEGER amount the rounding can change *per tile*
         (x=0.4 with m0=0.0 rounds to 0; with m0=-0.3 it rounds to 1, while x=1.6 rounds to 2 in
         both). That is not a translation and the paste would be wrong. So we recompute `P` from
         scratch and verify `P_new[:m] - P_old` is one constant vector. It usually is; when it is
         not, we rebuild. This check is a few microseconds and it is the whole safety of the class.

    Verified against `t33.composite` on real data over a 156-step incremental sweep:
    `np.array_equal(img)`, `np.array_equal(mask)` and `m0` identical at EVERY step.
    """

    def __init__(self) -> None:
        #: ⚠️ `score_at` no longer waits behind a whole `match_anchor` (that made the live NCC under
        #: the cursor up to ~1.5 s stale on CPU — a full match out of date, against API.md §7.2's
        #: "live during a drag"). The two can now run CONCURRENTLY, and this is the one piece of
        #: mutable state they share, so `get()` is atomic. Note the arrays it hands out are never
        #: mutated afterwards — every path allocates fresh `acc`/`wsum` — so a caller holding a
        #: previous result cannot have it changed underneath it.
        self._lock = threading.RLock()
        self._reset()
        self.hits = 0
        self.rebuilds = 0

    def _reset(self) -> None:
        self.token = None
        self.trials: list[int] = []
        self.local: np.ndarray | None = None
        self.P: np.ndarray | None = None
        self.acc: np.ndarray | None = None
        self.wsum: np.ndarray | None = None

    def clear(self) -> None:
        with self._lock:
            self._reset()

    def get(self, band: np.ndarray, token: str, trials_sorted: list[int],
            rows: list[int], local: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """-> (img, mask, m0), exactly as `t33.composite(band, rows, local)` would return them."""
        with self._lock:
            return self._get(band, token, trials_sorted, rows, local)

    def _get(self, band: np.ndarray, token: str, trials_sorted: list[int],
             rows: list[int], local: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        n = len(trials_sorted)
        if n == 0:
            raise ValueError("an anchor composite needs at least one anchored tile")

        acc = wsum = None
        m0 = local.min(0)
        P = np.rint(local - m0).astype(int)

        m = len(self.trials)
        can_extend = (
            self.token == token
            and self.acc is not None
            and 0 < m <= n
            and self.trials == trials_sorted[:m]
            and self.local is not None
            and np.array_equal(self.local, local[:m])
        )
        if can_extend:
            shift = P[:m] - self.P                       # must be ONE constant integer vector
            if np.all(shift == shift[0]):
                sx, sy = int(shift[0][0]), int(shift[0][1])
                oh, ow = self.acc.shape
                Hc, Wc = int(P[:, 1].max()) + TILE, int(P[:, 0].max()) + TILE
                if sx >= 0 and sy >= 0 and sy + oh <= Hc and sx + ow <= Wc:
                    acc = np.zeros((Hc, Wc), np.float32)
                    wsum = np.zeros((Hc, Wc), np.float32)
                    acc[sy:sy + oh, sx:sx + ow] = self.acc      # a pure paste: no value changes
                    wsum[sy:sy + oh, sx:sx + ow] = self.wsum
                    fe = t33.feather()                          # t33's own feather. Not a copy.
                    for k in range(m, n):                       # append IN ORDER
                        x, y = int(P[k][0]), int(P[k][1])
                        acc[y:y + TILE, x:x + TILE] += band[rows[k]] * fe
                        wsum[y:y + TILE, x:x + TILE] += fe
                    self.hits += 1

        if acc is None:
            # Cold, or a precondition failed. Call t33 and rebuild our running arrays from the
            # same primitives, in the same order, so the NEXT append is still bit-identical.
            self.rebuilds += 1
            fe = t33.feather()
            Hc, Wc = int(P[:, 1].max()) + TILE, int(P[:, 0].max()) + TILE
            acc = np.zeros((Hc, Wc), np.float32)
            wsum = np.zeros((Hc, Wc), np.float32)
            for k in range(n):
                x, y = int(P[k][0]), int(P[k][1])
                acc[y:y + TILE, x:x + TILE] += band[rows[k]] * fe
                wsum[y:y + TILE, x:x + TILE] += fe

        self.token = token
        self.trials = list(trials_sorted)
        self.local = local.copy()
        self.P = P.copy()
        self.acc = acc
        self.wsum = wsum

        # …and the tail of t33.composite, verbatim in effect: mean-subtract over the VALID MASK
        # only (an unmasked mean would be dragged by the zeros outside the hull and bias every
        # NCC downstream by the shape of the footprint).
        msk = wsum > 0
        img = np.where(msk, acc / np.maximum(wsum, 1e-6), 0.0).astype(np.float32)
        img = np.where(msk, img - img[msk].mean(), 0.0).astype(np.float32)
        return img, msk, m0


_COMPOSITE = _CompositeCache()


def composite_of(session, anchors: list[int], positions: dict) -> tuple:
    """(img, mask, m0) for the anchor field. `anchors` need not be sorted — we sort (the contract
    says order is irrelevant, and the sort is what makes the incremental cache and the memo key
    agree on one canonical order)."""
    ts = sorted(int(t) for t in anchors)
    rows = [session.row_of[t] for t in ts]
    local = np.array([_pos(positions, t) for t in ts], float)
    return _COMPOSITE.get(session.band, _token(session), ts, rows, local)


def _token(session) -> str:
    """Identifies the loaded pixel stack.

    ⚠️ IT USED TO BE `id(session.band)`, AND `id()` IS RECYCLED. Measured: five sequential
    same-size allocations returned the SAME address four times. So two different sessions of the
    same dataset with the same tile count genuinely collided on this token — the composite cache and
    the match memo would then serve one session's answer to another. It happened to be harmless only
    because `band` is a per-frame DoG of the RAW file (the flat-field is display-only), making
    `band[row_of[t]]` a pure function of (directory, trial) — an invariant that is ONE preprocessing
    change away from being false, and which was written down nowhere.

    `session.nonce` is minted per open (loader.open_session) and cannot be recycled. `reset_caches()`
    is now also called on every open / run change, so this is belt and braces.
    """
    nonce = getattr(session, "nonce", None) or f"id{id(session.band):x}"
    return f"{getattr(session, 'dataset', '?')}:{nonce}:{session.band.shape[0]}"


def _pos(positions: dict, t: int) -> tuple[float, float]:
    """Positions arrive from JSON with STRING keys ('11'), and from python with int keys."""
    v = positions.get(t, positions.get(str(t)))
    if v is None:
        raise KeyError(f"no position given for anchor {t}")
    return float(v[0]), float(v[1])


def reset_caches() -> None:
    """Drop the composite cache and the match memo. `server.py` MUST call this whenever the
    session's pixels change (a new open, or PATCH /api/session/run)."""
    _COMPOSITE.clear()
    with _MEMO_LOCK:
        _MEMO.clear()


# =============================================================================
# ⭐⭐ THE ANCHOR-COMPOSITE PRIMITIVE — one call, four features
# =============================================================================
@dataclass
class Candidate:
    """One ranked candidate placement, in WORLD coordinates."""
    rank: int
    x: float            # world TOP-LEFT. NOT a dx. NOT a centre. (Draw a centre? add +256.)
    y: float
    ncc: float
    npix: int
    subpixel: bool      # True only for rank 0 (the others stay on integers)

    def to_json(self) -> dict:
        return {"rank": int(self.rank), "x": float(self.x), "y": float(self.y),
                "ncc": float(self.ncc), "npix": int(self.npix), "subpixel": bool(self.subpixel)}


@dataclass
class MatchResult:
    """The `POST /api/match/anchor` body (API.md §7.1)."""
    target: int
    mode: str
    n_anchors: int
    composite: dict
    candidates: list
    best: Candidate | None
    margin: float | None
    margin_thin: bool
    refused: dict | None
    gpu: bool
    elapsed_ms: float
    cached: bool
    cache_key: str
    #: Anchors DROPPED from the composite because they are blank (see `_refusal`). Not an error —
    #: but the UI should say so, because it silently changes the aperture the match had.
    dropped_anchors: list = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "target": int(self.target),
            "mode": self.mode,
            "n_anchors": int(self.n_anchors),
            "composite": self.composite,
            "candidates": [c.to_json() for c in self.candidates],
            "best": self.best.to_json() if self.best else None,
            "margin": None if self.margin is None else float(self.margin),
            "margin_thin": bool(self.margin_thin),
            "refused": self.refused,
            "dropped_anchors": [int(t) for t in self.dropped_anchors],
            "gpu": bool(self.gpu),
            "elapsed_ms": round(float(self.elapsed_ms), 1),
            "cached": bool(self.cached),
            "cache_key": self.cache_key,
        }


# --- the memo (API.md §7.4) ---------------------------------------------------------------
_MEMO: "OrderedDict[tuple, MatchResult]" = OrderedDict()
_MEMO_LOCK = threading.Lock()
_INFLIGHT: dict = {}
#: Serialises the actual compute. The GPU has one memory pool and the composite cache has one set
#: of running arrays; two matches at once would fight over both. A DUPLICATE request (the A-branch
#: prefetch the user then confirms) does not wait on this lock at all — it waits on the in-flight
#: event and takes the memo hit. See the note in match_anchor().
_COMPUTE_LOCK = threading.Lock()


def cache_key(target: int, anchors: list[int], positions: dict, mode: str,
              near, radius: int, max_candidates: int) -> str:
    """The memo key (API.md §7.4). **This function is the prefetch's correctness guarantee.**

    🔴 **THE TRAP IT DEFUSES.** The front end prefetches tile N+1's match the instant tile N is
    judged. That prefetch **MUST use the composite INCLUDING the tile currently under judgement** —
    i.e. it must assume the user will press **`A`**. That branch is exact by construction.
    Prefetching from the composite **WITHOUT** it disagrees with the truth in **18 % of presses and
    is catastrophically wrong (up to 1,143 px) in 6 %.**

    Because the key IS the anchor set (and their positions), a user who presses `E` instead
    produces a DIFFERENT key, the memo MISSES, and the server recomputes honestly. The trap is
    structurally impossible to fall into — **as long as nobody invents a second cache keyed on the
    trial number.** Do not.
    """
    payload = json.dumps({
        "target": int(target),
        "anchors": [[int(t), round(_pos(positions, t)[0], 3), round(_pos(positions, t)[1], 3)]
                    for t in sorted(int(a) for a in anchors)],
        "mode": mode,
        "near": [round(float(near[0]), 3), round(float(near[1]), 3)]
                if (mode == "local" and near is not None) else None,
        "radius": int(radius) if mode == "local" else None,
        "max_candidates": int(max_candidates),
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _blank_list(session) -> set:
    b = getattr(session, "blank", None) or {}
    return {int(t) for t in (b.get("blank") or [])}


def _texture_of(session, t: int):
    tex = getattr(session, "texture", None) or {}
    v = tex.get(int(t), tex.get(str(t)))
    return None if v is None else float(v)


def _refusal(session, target: int, anchors: list[int] | None = None) -> dict | None:
    """⛔ BLANK TILES ARE REFUSED, NOT SCORED (API.md §7.3) — for the TARGET.

    Two blank frames **136 trials apart** correlate **+0.43 at zero shift** (honest noise floor
    0.115) because what they share is fixed-pattern *sensor* structure, which does not move with
    the stage. **They register confidently and wrongly.** There is no `force` flag and there will
    not be one: the user may still DRAG a blank tile into place (a human eye is allowed to do what
    the correlator must not), but snap / place-on-Space / score all refuse.

    ⚠️ THE TARGET, NOT THE ANCHORS. API.md §7.3 also said "or if any tile in `anchors` is" — and
    that clause is WRONG ON THIS DATA, in a way that dead-ends the app. It was written assuming the
    blank list is the **11** known blanks, every one of which lives inside the thrown-out 26 and can
    therefore never *be* an anchor: the branch was meant to be unreachable. But the scan is only
    allowed to look at the 312 USABLE trials (the 26 are not data and are never loaded), and over
    those it proposes **{34, 55, 56, 127}** — the four near-threshold trials RECON calls usable
    false positives. The user anchors in trial order, so the moment he anchors 34, EVERY subsequent
    Space and snap would refuse forever and the sweep would die at tile 35.

    So a blank ANCHOR is **dropped from the composite** (`_blank_anchors`) and reported, never fatal.
    That is strictly *safer* than the old behaviour on the axis the trap actually cares about — a
    blank frame's fixed-pattern structure now contributes **no pixels at all** to any correlation —
    and it keeps the sweep alive. If the target's only overlap was with a dropped anchor, `npix`
    falls under exact_ncc's floor and the honest answer is `ncc: null`, "not measurable".
    """
    blanks = _blank_list(session)
    if int(target) not in blanks:
        return None
    b = getattr(session, "blank", None) or {}
    thr = b.get("threshold")
    who = int(target)
    return {
        "reason": "blank",
        "trials": [who],
        "texture": _texture_of(session, who),
        "threshold": None if thr is None else float(thr),
        "message": (
            f"Trial {who} is near-featureless glare. Any match it scores is fixed-pattern sensor "
            f"structure, not the scene - it would register confidently and wrongly. Place it by "
            f"hand, or exclude it."),
    }


def _blank_anchors(session, anchors: list[int]) -> list[int]:
    """The anchors we must DROP from the composite (see `_refusal`). Never fatal."""
    blanks = _blank_list(session)
    return sorted({int(a) for a in anchors if int(a) in blanks})


def _tile_for_match(session, target: int) -> tuple[np.ndarray, np.ndarray]:
    """The matcher's tile: BAND-PASSED and MEAN-SUBTRACTED, exactly as t33.place prepares it
    (t33.py:730-731). The composite is built from the SAME band-passed stack. ⚠️ Tone mapping is
    for the display ONLY and must never touch this path."""
    tile = session.band[session.row_of[int(target)]].astype(np.float32)
    tile = tile - tile.mean()
    return tile, np.ones((TILE, TILE), bool)


def _subpixel(IMG, MSK, tile, TMSK, dx: int, dy: int) -> tuple[float, float]:
    """Integer winner -> sub-pixel. Separable parabolic peak fit on the exact-NCC 3x3.

    VERBATIM from API.md §3.5 so seven implementations cannot diverge. 8 extra `t33.exact_ncc`
    calls, ~30 ms. Applied to `candidates[0]` ONLY. **ADDITIVE** — it does not touch t33 and cannot
    affect the 312/312 regression guard.

    ⚠️ Do NOT replace this with the browser-side JS NCC: that search is alias-safe only within
    ~±48 px (the electrode grid repeats every 256 px) and past that it locks onto a confident,
    WRONG grid alias. *Correct beats fast* — his explicit ruling on the snap.
    """
    def s(ex, ey):
        v, _ = t33.exact_ncc(IMG, MSK, tile, TMSK, dx + ex, dy + ey, stride=1)
        return v if np.isfinite(v) else -1.0

    c = s(0, 0)

    def delta(a, b):
        den = a - 2.0 * c + b
        if den >= 0.0:                          # not a peak -> do not interpolate
            return 0.0
        return float(np.clip(0.5 * (a - b) / den, -0.5, 0.5))

    ddx = delta(s(-1, 0), s(1, 0))
    ddy = delta(s(0, -1), s(0, 1))
    return dx + ddx, dy + ddy


def _local_search(IMG, MSK, tile, TMSK, cx: int, cy: int, radius: int, max_candidates: int):
    """mode="local" — the SNAP. Exhaustive `exact_ncc` inside `radius` of the drop point.

    Coarse grid at step 4 (pixel stride 4, as t33's own tier A does), then ±4 at pixel stride 1
    around the winner, then the sub-pixel parabola. -> the same [(ncc, dx, dy, npix)] shape as
    t33.match, best first, peaks >= 24 px apart.

    ⚠️ **Never widen `radius` past 128 in the UI.** The electrode grid repeats every **256 px** and
    a wide LOCAL search will confidently lock onto a grid alias. To search wide, use mode="global":
    the FFT plus the margin is what survives the aliases.
    """
    grid = []
    for ey in range(-radius, radius + 1, 4):
        for ex in range(-radius, radius + 1, 4):
            v, _ = t33.exact_ncc(IMG, MSK, tile, TMSK, cx + ex, cy + ey, stride=4)
            if np.isfinite(v):
                grid.append((float(v), cx + ex, cy + ey))
    if not grid:
        return []
    grid.sort(key=lambda z: -z[0])

    picks = []                                              # NMS: distinct peaks only
    for v, x, y in grid:
        if all(np.hypot(x - px, y - py) > NMS_PX for _, px, py in picks):
            picks.append((v, x, y))
        if len(picks) >= max(max_candidates, 1):
            break

    out = []
    for i, (_, x, y) in enumerate(picks):
        if i == 0:                                          # rank 0 gets the full polish
            best = (-2.0, x, y, 0)
            for ey in range(-4, 5):
                for ex in range(-4, 5):
                    v, nn = t33.exact_ncc(IMG, MSK, tile, TMSK, x + ex, y + ey, stride=1)
                    if np.isfinite(v) and v > best[0]:
                        best = (float(v), x + ex, y + ey, int(nn))
            if best[0] > -2:
                out.append(best)
        else:                                               # alternatives: honest stride-1 rescore
            v, nn = t33.exact_ncc(IMG, MSK, tile, TMSK, x, y, stride=1)
            if np.isfinite(v):
                out.append((float(v), x, y, int(nn)))
    out.sort(key=lambda z: -z[0])
    return out


def match_anchor(
    session,
    target: int,
    anchors: list[int],
    positions: dict,
    mode: str = "global",
    near=None,
    radius: int = SNAP_RADIUS,
    max_candidates: int = 8,
) -> MatchResult:
    """⭐⭐ **THE HEART OF THE APP.** Match `target` against the composite of the ANCHORED tiles.

    ONE CALL, FOUR FEATURES (API.md §7):
      * **place the next tile** on `Space`   -> mode="global", take candidates[0]
      * **show ranked alternatives**         -> the SAME response, candidates[1..]
      * **rescue a tile the solver missed**  -> the SAME call, on an unplaced tile
      * **snap a human's drag**              -> mode="local", near = the drop point

    WHY THIS IS THE RIGHT PRIMITIVE, NOT MERELY A CONVENIENT ONE — **APERTURE IS EVERYTHING.**
    Of 719 genuinely-overlapping tile PAIRS on this data, the exact-NCC argmax is >20 px wrong for
    38 (5 %), at scores up to 0.760 — the canonical case (222 vs 250) has the 0.760 winner **757 px
    wrong** and the TRUTH as the runner-up at 0.677. The same tile matched against the pass-1
    COMPOSITE scores 0.654 vs 0.416 next-best and lands **1.7 px** from the human.

    THE ARITHMETIC (API.md §3.3 — get it wrong and everything is ~512 px off):

        IMG, MSK, m0 = t33.composite(band, rows, local)      # m0 = local.min(0)
        c = t33.match(IMG, MSK, tile, TMSK)                  # (dx, dy) == originB - originA
        #   A = the composite, B = the tile, so:
        #                    ⭐  world_topleft = m0 + (dx, dy)  ⭐

    ⚠️ **THE APERTURE IS SMALL AT THE START.** With ONE anchor down this call *is* a tile-pair —
    the weak case above. What saves the opening is that consecutive snapshots overlap ~78 % and
    consecutive whole-frame matches are the alias-robust ones. So we SURFACE THE EVIDENCE:
    `n_anchors`, `composite.valid_px`, `ncc` and `margin` are in the response precisely so the user
    can watch the evidence strengthen instead of taking it on faith. **`margin_thin` (< 0.10) must
    be flagged loudly by the UI** — the shipped build's worst run margin is 0.081 against a ~0.47
    typical, and a thin margin is exactly what a surviving alias looks like.

    Cost: ~1,068 ms GPU / 1,562 ms CPU (global); ~200-500 ms (local). MEMOISED — a repeat POST with
    the same body returns in ~1 ms with `cached: true`, which is what makes the prefetch free.
    """
    t_start = time.time()
    target = int(target)
    anchors = sorted({int(a) for a in anchors})
    mode = str(mode or "global")

    if mode not in ("global", "local"):
        raise ValueError(f"mode must be 'global' or 'local', not {mode!r}")
    if not anchors:
        raise ValueError("match_anchor needs at least one anchor")
    if target in anchors:
        raise ValueError(f"target {target} is also listed as an anchor")
    if target not in session.row_of:
        raise KeyError(f"trial {target} is not in this session's run")
    for a in anchors:
        if a not in session.row_of:
            raise KeyError(f"anchor trial {a} is not in this session's run")
        _pos(positions, a)                                  # raises KeyError -> 400
    if mode == "local" and near is None:
        raise ValueError("mode='local' requires `near` (the world top-left you dropped it at)")
    radius = int(np.clip(int(radius), 8, 256))
    max_candidates = int(np.clip(int(max_candidates), 1, 16))

    # ⛔ Refusal is decided BEFORE any pixels are touched, and is never cached (it is free).
    #    The TARGET being blank is fatal. A blank ANCHOR is dropped, not fatal — see `_refusal`.
    refused = _refusal(session, target)
    dropped = _blank_anchors(session, anchors)
    if refused is None and dropped and not [a for a in anchors if a not in dropped]:
        refused = {
            "reason": "no_anchors",
            "trials": list(dropped),
            "texture": None, "threshold": None,
            "message": ("Every anchor offered is a blank frame, so there is no scene texture to "
                        "match against. Anchor a tile with real structure first."),
        }
    if refused is not None:
        return MatchResult(
            target=target, mode=mode, n_anchors=len(anchors),
            composite={"w": 0, "h": 0, "valid_px": 0, "m0": [0.0, 0.0]},
            candidates=[], best=None, margin=None, margin_thin=False,
            refused=refused, gpu=bool(t27.on_gpu()),
            elapsed_ms=(time.time() - t_start) * 1e3, cached=False,
            cache_key=cache_key(target, anchors, positions, mode, near, radius, max_candidates))

    # The EFFECTIVE anchor field: blanks contribute no pixels to any correlation. The memo is keyed
    # on THIS, not on what was asked for — two requests that reduce to the same composite genuinely
    # share an answer, and the A-branch prefetch stays correct by construction.
    anchors = [a for a in anchors if a not in dropped]
    positions = {k: v for k, v in positions.items() if int(k) not in dropped}

    key = cache_key(target, anchors, positions, mode, near, radius, max_candidates)
    mkey = (_token(session), key)

    # --- the memo + single-flight ---------------------------------------------------------
    # A prefetch already in flight for THIS key does not get recomputed by the foreground request
    # that follows it: the second caller waits on the event and takes the hit. A prefetch for a
    # DIFFERENT key (the user pressed E, not A) simply misses — which is the whole point.
    while True:
        with _MEMO_LOCK:
            if mkey in _MEMO:
                _MEMO.move_to_end(mkey)
                hit = _MEMO[mkey]
                out = MatchResult(**{**vars(hit), "cached": True,
                                     "elapsed_ms": (time.time() - t_start) * 1e3})
                return out
            ev = _INFLIGHT.get(mkey)
            if ev is None:
                ev = threading.Event()
                _INFLIGHT[mkey] = ev
                break
        ev.wait(timeout=600)                                # someone else is computing this exact
        # request; loop back and read their answer out of the memo.

    try:
        with _COMPUTE_LOCK:
            res = _match_compute(session, target, anchors, positions, mode, near,
                                 radius, max_candidates, key, t_start)
        res.dropped_anchors = list(dropped)
        with _MEMO_LOCK:
            _MEMO[mkey] = res
            _MEMO.move_to_end(mkey)
            while len(_MEMO) > MATCH_CACHE_SIZE:
                _MEMO.popitem(last=False)
        return res
    finally:
        with _MEMO_LOCK:
            _INFLIGHT.pop(mkey, None)
        ev.set()


def _match_compute(session, target, anchors, positions, mode, near, radius,
                   max_candidates, key, t_start) -> MatchResult:
    IMG, MSK, m0 = composite_of(session, anchors, positions)
    tile, TMSK = _tile_for_match(session, target)

    if mode == "global":
        cands = t33.match(IMG, MSK, tile, TMSK,
                          kpk=ANCHOR_KPK, minfrac=ANCHOR_MINFRAC, minabs=ANCHOR_MINABS)
    else:
        nx, ny = float(near[0]), float(near[1])
        cx = int(round(nx - float(m0[0])))
        cy = int(round(ny - float(m0[1])))
        cands = _local_search(IMG, MSK, tile, TMSK, cx, cy, radius, max_candidates)

    # margin is taken from the FULL ranked list, before truncation: best - second. (Identical to
    # candidates[0]-candidates[1] at the default max_candidates=8; strictly more honest if a caller
    # asks for only one.)
    margin = None
    if len(cands) >= 2:
        margin = float(cands[0][0]) - float(cands[1][0])

    # ⚠️ NOTE FOR THE UI, and do not "fix" it here. The tail of t33.match's ranked list is its tier-A
    # candidates, which it appends WITHOUT re-scoring (t33.py:521) — they carry **npix = 0**, which
    # means "not measured", NOT "no overlap". Only rank 0 (and the tier-B survivors) have a real
    # npix. We pass t33's numbers through UNTOUCHED — rescoring them would cost ~240 ms per Space
    # press and would shift `margin` away from t33's own definition of it. So: **do not render a
    # candidate's npix == 0 as evidence of nothing.** Rank 0's npix is real; use that, plus
    # composite.valid_px and the margin.
    out: list[Candidate] = []
    for i, (ncc, dx, dy, npix) in enumerate(cands[:max_candidates]):
        x = float(m0[0]) + float(dx)                       # ⭐ world = m0 + (dx, dy)
        y = float(m0[1]) + float(dy)
        sub = False
        if i == 0:
            fx, fy = _subpixel(IMG, MSK, tile, TMSK, int(dx), int(dy))
            x = float(m0[0]) + fx
            y = float(m0[1]) + fy
            sub = True
        out.append(Candidate(rank=i, x=x, y=y, ncc=float(ncc), npix=int(npix), subpixel=sub))

    t27._free()
    return MatchResult(
        target=target, mode=mode, n_anchors=len(anchors),
        composite={"w": int(IMG.shape[1]), "h": int(IMG.shape[0]),
                   "valid_px": int(MSK.sum()), "m0": [float(m0[0]), float(m0[1])]},
        candidates=out, best=out[0] if out else None,
        margin=margin,
        margin_thin=bool(margin is not None and margin < MARGIN_THIN),
        refused=None, gpu=bool(t27.on_gpu()),
        elapsed_ms=(time.time() - t_start) * 1e3, cached=False, cache_key=key)


def score_at(session, target: int, anchors: list[int], positions: dict, at) -> dict:
    """"You dropped it HERE; here is what the pixels say." One `t33.exact_ncc`, no search.

    -> {"target", "at", "ncc", "npix", "refused", "elapsed_ms"}  (API.md §7.2)

    `ncc` is **None** when the overlap is under exact_ncc's floor (< 3,000 valid px, or < 64 px on
    a side) — the honest answer there is "not measurable", **never 0.0**. Blank tiles are refused
    here too; same rule, no exceptions.
    """
    t0 = time.time()
    target = int(target)
    anchors = sorted({int(a) for a in anchors})
    ax, ay = float(at[0]), float(at[1])

    refused = _refusal(session, target)                    # the TARGET only — see `_refusal`
    dropped = _blank_anchors(session, anchors)
    anchors = [a for a in anchors if a not in dropped]     # blanks contribute no pixels, ever
    positions = {k: v for k, v in positions.items() if int(k) not in dropped}
    if refused is None and dropped and not anchors:
        refused = {"reason": "no_anchors", "trials": list(dropped),
                   "texture": None, "threshold": None,
                   "message": ("Every anchor offered is a blank frame - there is no scene texture "
                               "to score against.")}
    if refused is not None:
        return {"target": target, "at": [ax, ay], "ncc": None, "npix": 0,
                "refused": refused, "dropped_anchors": list(dropped),
                "elapsed_ms": round((time.time() - t0) * 1e3, 1)}
    if not anchors:
        raise ValueError("score_at needs at least one anchor")

    # ⚠️ **DELIBERATELY NOT UNDER `_COMPUTE_LOCK`.** It used to be, and that made the "live during a
    # drag" NCC readout (API.md §7.2) wait out an entire `match_anchor`: measured 67 ms alone vs
    # 439 ms while a prefetch was in flight — and on the CPU-only default the prefetch is 1,562 ms,
    # so the number under the user's cursor could be a **full match out of date** while he is steering
    # by it. Nothing here contends with the matcher: `t33.composite` and `t33.exact_ncc` are pure
    # host numpy (no CuPy pool, no GPU), and the ONE piece of shared mutable state — the incremental
    # composite cache — is now atomic in itself (`_CompositeCache._lock`), and never mutates an array
    # it has already handed out.
    IMG, MSK, m0 = composite_of(session, anchors, positions)
    tile, TMSK = _tile_for_match(session, target)
    dx = int(round(ax - float(m0[0])))                     # exact_ncc takes INTEGER offsets
    dy = int(round(ay - float(m0[1])))
    ncc, npix = t33.exact_ncc(IMG, MSK, tile, TMSK, dx, dy)

    return {
        "target": target,
        "at": [ax, ay],
        "ncc": None if not np.isfinite(ncc) else float(ncc),   # NOT 0.0. "Not measurable."
        "npix": int(npix),
        "refused": None,
        "dropped_anchors": list(dropped),
        "elapsed_ms": round((time.time() - t0) * 1e3, 1),
    }


# =============================================================================
# THE BUILD MEMO — SPEED.md #4, applied WITHOUT touching t33
# =============================================================================
_POOL_ORIG = None
_POOL_MEMO: list = []


def enable_build_memo(max_entries: int = 2) -> None:
    """Memoise `t33._pool` on the REFERENCE side of the build's per-tile anchor loop.

    The loop (t33.py:729-739) calls `match(IMG1, MSK1, tile, TMSK)` once per pass-2 tile — 156
    times with the SAME 7 Mpx pass-1 composite — and `t33.match` re-pools that composite every
    single time. This wrapper hands back the identical arrays the real `_pool` returned the first
    time.

    ⭐ BIT-IDENTICAL BY CONSTRUCTION: it caches the real function's own OUTPUT OBJECT. It does not
    reimplement `_pool` and it does not touch `_smooth()` or any FFT size (the grid stays at
    exactly 2160x1350 as shipped). `t33.match` never mutates what `_pool` gives it (it only reads
    `.shape` and `.sum()` and feeds them to `_surfaces`, which copies into new arrays).

    The key is OBJECT IDENTITY (`is`), and the cache holds a strong reference to the inputs, so an
    `id()` cannot be recycled underneath it. That makes it exact — not "probably the same array".

    ⚠️ HONEST SCOPE: SPEED.md's 25 s figure is for memoising the pooled reference **and its three
    FFTs**. The FFTs live INSIDE `t33._surfaces`, and caching them would mean either editing t33
    (not this agent's file) or copying `_surfaces` into here (forbidden — that is a fork). So this
    is the pooling half only. Anything more must be done inside t33, under the regression guard.
    """
    global _POOL_ORIG
    if _POOL_ORIG is not None:
        return
    _POOL_ORIG = t33._pool

    def _pool_memo(img, msk, ds):
        for (ci, cm, cds, out) in _POOL_MEMO:
            if ci is img and cm is msk and cds == ds:      # identity, not equality. Exact.
                return out
        out = _POOL_ORIG(img, msk, ds)
        _POOL_MEMO.append((img, msk, ds, out))             # strong refs: id() cannot be recycled
        while len(_POOL_MEMO) > max_entries:
            _POOL_MEMO.pop(0)
        return out

    t33._pool = _pool_memo


def disable_build_memo() -> None:
    """Restore the untouched t33. Always available; used by the A/B verification."""
    global _POOL_ORIG
    if _POOL_ORIG is not None:
        t33._pool = _POOL_ORIG
        _POOL_ORIG = None
    _POOL_MEMO.clear()


# =============================================================================
# THE BUILD  —  a long-running job, in a CHILD PROCESS
# =============================================================================
class _ProgressSink:
    """t33 has NO progress callback. Its only signal is `print` behind `cfg.verbose` — so we run it
    under `redirect_stdout` and scrape. The line -> phase rules and the phase weighting are
    API.md §8.3, used exactly as written (do NOT invent your own, and do NOT "smooth" the
    warm-cache case where the job legitimately jumps straight to `runs`)."""

    RE_PASS1 = re.compile(r"STEP 1\s*[—\-]\s*PASS 1")
    RE_BACKBONE = re.compile(r"STEP 2\s*[—\-]\s*PASS 2 backbone")
    RE_COMPOSITE = re.compile(r"pass-1 composite .*px")
    RE_ANCHORS = re.compile(r"STEP 3\s*[—\-]\s*PER-TILE ANCHORS")
    RE_ANCHORED = re.compile(r"anchored (\d+)/(\d+) tiles")
    RE_RECUT = re.compile(r"STEP 4\s*[—\-]\s*RE-CUT")
    RE_RUNS = re.compile(r"STEP 5\s*[—\-]\s*COMPOSITE-TO-COMPOSITE")
    RE_NRUNS = re.compile(r"pass 2 -> (\d+) runs")
    RE_RUNROW = re.compile(r"^\s*R(\d+)\s+\d+\s")
    RE_DONE = re.compile(r"\[done\] placed (\d+) snapshots")
    RE_STAMP = re.compile(r"^\[\s*[\d.]+s\]\s?")

    # 🔴 INTRA-PHASE PROGRESS FOR `pass1` AND `backbone` — 75 % of a CPU build, and it used to show
    # the user EXACTLY TWO STATIC NUMBERS. `pass1` and `backbone` emitted no `frac` at all, so `pct`
    # was pinned and `eta_s` was `None` (an ETA needs pct > 2). Measured on the CPU-only path — the
    # SHIPPED DEFAULT install — the bar sat at **0.0 %, with no ETA, for 3 min 40 s**, under the
    # constant message "pass 1 (t27, frozen reference)", with a Cancel button helpfully to hand. Then
    # it jumped to 20.0 % and sat there for **another 3 min 40 s**. A lab-mate who cancels that has
    # cancelled a build that would have produced 312/312.
    #
    # t33 runs t27 inside itself and `_hush` lets t27's own narration through at verbose=True, so
    # there IS a signal — it was simply never scraped. These are t27's markers, in the order it emits
    # them, mapped to a fraction of the enclosing phase. The fractions are ordinal, not linear in
    # time (the true split is unmeasured and differs GPU vs CPU) — but a bar that MOVES and a message
    # that CHANGES is the difference between "it is working" and "it has hung", and that is the
    # failure being fixed. `_enter`'s never-go-backwards guard still protects the phase itself.
    #
    # ⚠️ t27's own "STEP 1/2/3/4" headers say PRE-CHECK / EXHAUSTIVE / COLUMN-IDENTITY / WEIGHTED —
    # they cannot collide with t33's "STEP 1 — PASS 1" / "STEP 2 — PASS 2 backbone" above, which is
    # why these regexes are anchored on the words, not the numbers.
    SUBSTEPS = (
        (re.compile(r"\[data\] .* snapshots, trials"),              0.02, "loading the band-passed stack"),
        (re.compile(r"\[data\] band-passed"),                       0.05, "band-passed (DoG 3-30)"),
        (re.compile(r"\[swim\] .*pairs in |\[swim\] loaded"),       0.55, "all-to-all SWIM shifts done"),
        (re.compile(r"\[validate\] batched NCC"),                   0.60, "NCC bank validated"),
        (re.compile(r"\[dealias\]"),                                0.65, "de-aliased the pair shifts"),
        (re.compile(r"STEP 1\s*[—\-]\s*PRE-CHECK"),                 0.68, "pre-check: is a step an axis move?"),
        (re.compile(r"STEP 2\s*[—\-]\s*EXHAUSTIVE"),                0.72, "exhaustive axis-manifold search"),
        (re.compile(r"backbone after correction"),                  0.84, "backbone corrected"),
        (re.compile(r"\[null\] matched permutation null"),          0.88, "permutation null measured"),
        (re.compile(r"STEP 3\s*[—\-]\s*COLUMN-IDENTITY"),           0.90, "column-identity gate"),
        (re.compile(r"STEP 4\s*[—\-]\s*WEIGHTED"),                  0.93, "weighted least-squares solve"),
        (re.compile(r"\[solve\] IRLS kept"),                        0.97, "IRLS converged"),
    )

    def __init__(self, queue, t0: float, n_total: int, weights: dict | None = None):
        self.q = queue
        self.t0 = t0
        self.n_total = int(n_total)
        self.buf = ""
        self.phase = "pass1"
        self.frac = 0.0
        self.n_runs = 0
        self.runs_seen = set()
        self.w = dict(weights or PHASE_WEIGHT)

    # --- file protocol -------------------------------------------------------------------
    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            if line.strip():
                self._line(line.rstrip())
        return len(s)

    def flush(self):
        pass

    def _enter(self, phase: str, frac: float) -> bool:
        """A phase may never go BACKWARDS.

        🔴 WHY THIS GUARD EXISTS, and it is not paranoia: **t33 runs t27 INSIDE itself**, and with
        `verbose=True` t33's `_hush` lets t27's own narration through to the same stdout. t27
        prints its OWN `[done] placed 156 snapshots` when it finishes pass 1 — a third of the way
        into the build. Scraped naively, that line sends the progress bar to **100 %** and then
        back to 20 %. (Measured: it did exactly that on the first cold run.) `[done]` is therefore
        gated on the tile count matching the WHOLE build (see RE_DONE below), and this guard is the
        backstop for any other line the inner t27 may ever emit that looks like an outer phase.
        """
        try:
            if PHASES.index(phase) < PHASES.index(self.phase):
                return False
        except ValueError:
            pass                                    # "done" is not in PHASES; it always wins
        self.phase, self.frac = phase, frac
        return True

    # --- the scraper ---------------------------------------------------------------------
    def _line(self, line: str):
        body = self.RE_STAMP.sub("", line)
        msg = None

        m = self.RE_ANCHORED.search(body)
        md = self.RE_DONE.search(body)
        if m:
            a, b = int(m.group(1)), max(int(m.group(2)), 1)
            if self._enter("anchors", min(a / b, 1.0)):
                msg = f"anchored {a}/{b} tiles"
        elif md and int(md.group(1)) == self.n_total:
            # ⚠️ ONLY the outer t33 `[done]` — t27's inner one (pass 1 alone) reports a SMALLER
            # count, and mistaking it for the end is the bug this whole guard exists for.
            self.phase, self.frac = "done", 1.0
            msg = body.strip()
        elif self.RE_PASS1.search(body):
            if self._enter("pass1", 0.0):
                msg = "pass 1 (t27, frozen reference)"
        elif self.RE_BACKBONE.search(body):
            if self._enter("backbone", 0.0):
                msg = "pass-2 backbone"
        elif self.RE_COMPOSITE.search(body):
            if self._enter("composite", 1.0):
                msg = "pass-1 composite built"
        elif self.RE_ANCHORS.search(body):
            if self._enter("anchors", 0.0):
                msg = "per-tile anchors against the pass-1 composite"
        elif self.RE_RECUT.search(body):
            if self._enter("recut", 1.0):
                msg = "re-cutting the runs from the anchors"
        elif self.RE_RUNS.search(body):
            if self._enter("runs", 0.0):
                msg = "matching every run against pass 1"
        elif self.phase in ("pass1", "backbone") and self._substep(body) is not None:
            # ⭐ t27's own narration, inside t33's pass-1 / backbone phases. Monotone within the
            #   phase — a later t27 line can never pull the bar back (`backbone` re-runs the same
            #   markers, but `_enter` has already moved the phase on, and `frac` is reset to 0 there).
            frac, note = self._substep(body)
            if frac > self.frac:
                self.frac = frac
                msg = ("pass 1 (t27, frozen reference) — " if self.phase == "pass1"
                       else "pass-2 backbone — ") + note
        else:
            m = self.RE_NRUNS.search(body)
            if m:
                self.n_runs = int(m.group(1))
            elif self.phase == "runs":
                m = self.RE_RUNROW.match(body)
                # ⚠️ t33 prints its MARGIN TABLE after the run loop, and those rows look exactly
                # like run rows. A SET (not a counter) is what keeps that from double-counting, and
                # `before` is what keeps it from re-emitting 11 identical 100 % messages.
                before = len(self.runs_seen)
                if m and self.n_runs:
                    self.runs_seen.add(int(m.group(1)))
                    if len(self.runs_seen) > before:
                        self.frac = min(len(self.runs_seen) / self.n_runs, 1.0)
                        msg = f"placed run {len(self.runs_seen)}/{self.n_runs}"

        self.q.put({"type": "log", "line": line})
        if msg is not None:
            self.q.put(self._progress(msg))

    def _substep(self, body: str):
        """-> (frac, note) for a t27 narration line inside pass1/backbone, else None."""
        for rx, frac, note in self.SUBSTEPS:
            if rx.search(body):
                return frac, note
        return None

    def _progress(self, message: str) -> dict:
        if self.phase == "done":
            pct = 100.0
        else:
            done = 0.0
            for p in PHASES:
                if p == self.phase:
                    break
                done += self.w[p]
            pct = 100.0 * (done + self.frac * self.w.get(self.phase, 0.0))
        el = time.time() - self.t0
        eta = (el * (100.0 - pct) / pct) if pct > 2.0 and pct < 100.0 else None
        return {"type": "progress", "phase": self.phase,
                "phase_index": PHASE_INDEX.get(self.phase, 0), "n_phases": N_PHASES,
                "pct": round(pct, 1), "message": message,
                "eta_s": None if eta is None else round(eta, 0)}


def _make_config(config: dict | None):
    """dict -> t33.Config. An unknown knob raises TypeError -> the server returns 400.

    ⚠️ `cfg.pass_split` MUST be the session's DETECTED split, not t33's literal 166. The server
    passes it in `config`; if `config` is None we take t33's shipped defaults (which is what
    `config: null` means in API.md §10.1 — the one-button path — and the server is responsible for
    injecting the detected `pass_split` into it).
    """
    cfg_d = dict(config or {})
    t27_d = cfg_d.pop("t27", None)
    if t27_d is None:
        cfg = t33.Config(**cfg_d)                          # t33 default: t27.Config(control=False)
    else:
        cfg = t33.Config(t27=t27.Config(**dict(t27_d)), **cfg_d)
    return cfg


def _load_frames(data_dir: Path, trials: list[int]) -> np.ndarray:
    """The child re-loads the frames itself: 0.12 s for 312 with the numpy reader. Do NOT build a
    shared-memory apparatus to save a tenth of a second.

    ⭐ **ONE READER. `loader.load_frames` IS IT.** There was a second, inline one here — a build-time
    shim from the parallel build — and it flipped the frame **UNCONDITIONALLY** while the canonical
    reader flips **conditionally on the XML** (`loader.py:398-401`). On a dataset whose XML said
    `ax=1, ay=1`, any import hiccup in the spawned child would have had the child solve on
    180°-rotated frames while the UI, the matcher and the tone path used un-rotated ones — every tile
    180° out from what the human is verifying, and **each tile would still look plausible**. It could
    not fire on 260620d (all 342 XMLs are `-1/-1`), which is exactly why it would have sat here until
    it did. It also built `f"{t:03d}-ccd.dat"` by hand with **no exclusion check** — the only reader
    in the app that could have opened one of the 26.

    ⛔ Do not reintroduce a fallback. If `loader` cannot be imported, the build MUST fail loudly.
    """
    from . import loader                                   # the ONE reader. No fallback. Ever.
    return loader.load_frames(Path(data_dir), list(trials))


def read_anchors(cache_dir, trials: list[int], cfg) -> dict:
    """The per-tile anchors t33 computed and cached -> {trial: {"anc": [x, y], "ncc": v}}.

    t33 persists them to `T33_anchors_<tag>_<hash>.npz` (t33.py:716/741) but does NOT put them in
    `info` — and they are the best per-tile confidence signal that exists (pass 2 only; 156/156
    reached NCC >= 0.30, median 0.815). So we read the file back.

    ⚠️ Uses `t33._tag` and `t33._cache_key`, which are PRIVATE. Flagged in the report. They are
    pure functions of the trial list and the config; if they are ever renamed this degrades to
    "no per-tile anchor data", never to wrong data (we return {} on any failure).
    ⚠️ Returns {} when the build ran with `cache=None` — there is no file to read.
    """
    if not cache_dir:
        return {}
    try:
        key, khash = t33._cache_key(cfg)
        p = Path(cache_dir) / f"T33_anchors_{t33._tag(list(trials))}_{khash}.npz"
        if not p.exists():
            return {}
        z = t33._load_checked(p, key)                       # REFUSES a mismatched config. Good.
        anc, ancv = z["anc"], z["ancv"]
        p2 = [t for t in trials if t > cfg.pass_split]
        if len(ancv) != len(p2):
            return {}
        out = {}
        for q, t in enumerate(p2):
            v = float(ancv[q])
            out[int(t)] = {"anc": [float(anc[q][0]), float(anc[q][1])],
                           "ncc": None if not np.isfinite(v) else v}
        return out
    except Exception:                                      # noqa: BLE001 - evidence, not a verdict
        return {}


def build_result(pos: dict, info: dict, trials: list[int], pass_split: int,
                 anchors: dict | None = None, dataset: str = "dataset",
                 build_id: str | None = None, created: str | None = None) -> dict:
    """t33's (pos, info) -> the `GET /api/build/result` body (API.md §10.2).

    `per_tile` is a **"go look here first" list, NOT a verdict.** What is honest and what is not:

      ✅ `anchor_ncc` — PASS 2 ONLY. The best signal there is (156/156 >= 0.30, median 0.815).
      ⚠️ `anchor_residual_px` = |(anc[q] + M1) - pos[t]| — probably THE number to sort a worklist
         on (it caught trial 311 at 2,706 px while its run agreed to 4.4 px), but it has fired
         exactly ONCE, its false-positive rate is unmeasured, and t33's own design treats a lone
         disagreeing anchor as an outlier TO DISCARD. Present as "go look", never as a verdict.
      ⚠️ `run_margin` — good, but the shipped build's min is 0.081 against a ~0.47 typical.
      🔴 **PASS-1 TILES HAVE NO PER-TILE CONFIDENCE AT ALL** (t27's info is aggregate-only) — and
         the WORST tile in the shipped 312/312 build (127, at 9.94 px) is a PASS-1 tile. The UI
         must say so: the absence of a warning here is NOT a clean bill of health.
      ⛔ NOT built on `quality.score_positions` (precision 0/11 on the ground-truth-PERFECT build).
      ⛔ `quality.score_build()` / `quality.leaderboard()` are DEAD (quality.py:84). Never called.
    """
    anchors = anchors or {}
    trials = [int(t) for t in trials]
    posn = {int(t): np.asarray(p, float).reshape(2) for t, p in pos.items()}
    p1 = [t for t in trials if t <= int(pass_split)]

    M1 = None
    if p1 and all(t in posn for t in p1):
        M1 = np.array([posn[t] for t in p1], float).min(0)   # recoverable from `pos` alone

    run_of, margin_of = {}, {}
    for r in (info.get("runs") or []):
        for t in (r.get("trials") or []):
            run_of[int(t)] = r.get("run")
            margin_of[int(t)] = float(r.get("margin")) if r.get("margin") is not None else None

    per_tile = {}
    for t in trials:
        a = anchors.get(t) or {}
        ncc = a.get("ncc")
        resid = None
        if ncc is not None and M1 is not None and t in posn and a.get("anc") is not None:
            w = np.asarray(a["anc"], float) + M1
            resid = float(np.hypot(*(w - posn[t])))
        per_tile[str(t)] = {
            "anchor_ncc": ncc,
            "anchor_residual_px": resid,
            "run": run_of.get(t),
            "run_margin": margin_of.get(t),
            "pass": 1 if t <= int(pass_split) else 2,
        }

    now = created or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return {
        "build_id": build_id or f"{dataset}__t33__{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}",
        "created": now,
        # ⭐ WHAT THE SOLVER WAS ACTUALLY GIVEN. Without these two the document can never know that
        # its build was solved on a DIFFERENT input than the one it now holds — and
        # `project.mark_stale_if_input_changed` degenerates into comparing the current trial list
        # with itself and never firing. Excluding a mid-run tile opens a gap where the serpentine
        # one-step prior does NOT hold; the positions either side of it were solved THROUGH it.
        "trials": [int(t) for t in trials],
        "gaps": [[int(a), int(b)] for a, b in gaps(trials)],
        "pass_split": int(pass_split),
        "positions": {str(int(t)): [float(p[0]), float(p[1])] for t, p in posn.items()},
        "n_placed": len(posn),
        "unplaced": [t for t in trials if t not in posn],
        "info": _config_effective(jsonable(info), info),     # <- info["config"] would CRASH json
        "seconds": float(info.get("seconds", 0.0)),
        "gpu": bool(info.get("gpu", False)),
        "per_tile": per_tile,
    }


def _config_effective(safe: dict, info: dict) -> dict:
    """Record the config t33 ACTUALLY RAN, not the sentinel it was handed.

    ⚠️ `t33.Config.t27` defaults to **`None`**, meaning "use `t27.Config(control=False)`" — it is
    resolved lazily inside `t33.place` via `cfg.t27_config()`. So a faithful `vars()` dump writes
    `"t27": null` into the build record, and from there into the PROJECT FILE's provenance and the
    QC report. That is a provenance hole: `null` does not tell a later reader which t27 knobs
    (`conf`, `run_conf`, ...) produced these positions, and those knobs are exactly what a
    reproduction attempt needs. Resolve the sentinel and store the effective sub-config.

    Purely additive: it reads `t33`/`t27`, mutates nothing inside them, and cannot affect
    `analysis/tests/test_mosaic_312.py`.
    """
    cfg = info.get("config")
    if cfg is None or not isinstance(safe.get("config"), dict):
        return safe
    if safe["config"].get("t27") is None:
        try:
            # ⚠️ A WARM CACHE HIT HANDS BACK A PLAIN DICT, NOT A t33.Config. `t33._load_checked`
            # rebuilds `info` from the cache file, so `cfg` is a dict and `cfg.t27_config()` does not
            # exist. Keying this fix on `hasattr(cfg, "t27_config")` therefore made it work ONLY on a
            # cold build and silently no-op on every cached one — which is the common case, and the
            # one whose provenance was landing in the project file with `"t27": null`. Resolve the
            # sentinel the same way t33 does, whichever shape the config arrives in.
            eff = cfg.t27_config() if hasattr(cfg, "t27_config") else t27.Config(control=False)
            if eff is not None:
                safe["config"]["t27"] = jsonable(eff)
                safe["config"]["t27_source"] = "t33 default (cfg.t27 was None -> t27.Config(control=False))"
        except Exception:                                    # never lose a build over provenance
            pass
    return safe


def build_worker(data_dir: str, trials: list[int], config: dict | None,
                 cache_dir: str | None, queue) -> None:
    """The build, in a SPAWNED CHILD PROCESS. `jobs.submit_process` targets this by dotted path
    (`app.backend.engine.build_worker`).

    WHY A CHILD PROCESS: **`t33.place` cannot be interrupted.** It runs 25 s - 10 min synchronously
    and has no callback and no flag to check. Cancel = `proc.terminate()`. There is no other way.

    THE QUEUE PROTOCOL (jobs.py drains it on a reader thread). Every message is a plain dict:
        {"type": "progress", "phase", "phase_index", "n_phases", "pct", "message", "eta_s"}
        {"type": "log",      "line": "<one raw t33 stdout line>"}     # keep the last 200
        {"type": "done",     "result": {...}}                         # == GET /api/build/result
        {"type": "error",    "error": {"code", "message", "traceback"}}
    Everything on it is JSON-safe already (`info` has been through `jsonable()`).

    Runtime: GPU cold ~180-200 s (the per-tile anchor loop is ~150 s of it); GPU warm ~25 s;
    CPU-only ~8-10 min. All three are shippable; the UI must say which one it is doing and why.
    """
    t0 = time.time()
    try:
        trials = [int(t) for t in trials]
        queue.put({"type": "progress", "phase": "pass1", "phase_index": 1, "n_phases": N_PHASES,
                   "pct": 0.0, "message": f"loading {len(trials)} frames", "eta_s": None})

        frames = _load_frames(Path(data_dir), trials)
        cfg = _make_config(config)
        cfg.verbose = True                                   # the ONLY progress signal there is

        # ⭐ WHICH CURVE IS THIS BUILD ON? The phase weighting is a completely different shape on the
        # CPU (pass 1 + backbone = 75 % of the build) than on the GPU (the anchor loop = 53 %), and
        # guessing wrong makes the ETA a lie by >2x for the whole first half. `gpu_info()` calls
        # `t27.xp()`, which EXECUTES A REAL OP — `import cupy` succeeds on a broken CUDA install, so
        # nothing less will do. It also warms the child's own CUDA context before the clock matters.
        on_gpu = bool(gpu_info()["available"])
        queue.put({"type": "log",
                   "line": f"[camea] build device: {'GPU (CuPy)' if on_gpu else 'CPU (numpy)'}"})

        enable_build_memo()                                  # bit-identical; see its docstring
        sink = _ProgressSink(queue, t0, len(trials),
                             weights=PHASE_WEIGHT_GPU if on_gpu else PHASE_WEIGHT_CPU)
        with contextlib.redirect_stdout(sink):
            pos, info = t33.place(trials, frames, cfg=cfg, cache=cache_dir)

        anchors = read_anchors(cache_dir, trials, cfg)
        result = build_result(pos, info, trials, cfg.pass_split, anchors=anchors,
                              dataset=Path(data_dir).name)
        queue.put({"type": "progress", "phase": "done", "phase_index": N_PHASES,
                   "n_phases": N_PHASES, "pct": 100.0,
                   "message": f"placed {result['n_placed']}/{len(trials)} tiles", "eta_s": 0.0})
        queue.put({"type": "done", "result": result})
    except Exception as e:                                   # noqa: BLE001
        queue.put({"type": "error", "error": {
            "code": "job_failed", "message": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc()}})
    finally:
        try:
            queue.close()
            queue.join_thread()
        except Exception:                                    # noqa: BLE001
            pass


# =============================================================================
# Rendering (used by export.py — it imports these, it does not re-derive them)
# =============================================================================
def render_mosaic(session, positions: dict, mode: str = "feather",
                  report=None, cancel=None, flat: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """-> (img, coverage). `coverage` = bool (True = real data).

    ⭐ **`flat` DECIDES WHAT THE PIXELS ARE, AND THE TWO ANSWERS ARE NOT INTERCHANGEABLE:**

      * `flat=True`  (**the DISPLAY path — the PNG**): `loader.flat_correct` = `frame / vignette`,
        **and then `x (level / median(frame))` — a PER-TILE GAIN.** That gain is what makes every
        tile agree in brightness, which is what makes the GLOBAL tone window (and therefore
        Difference mode) mean anything. Correct for a picture. **Wrong for a measurement.**
      * `flat=False` (**the TIFF — the deliverable**): the frames exactly as they came off the
        camera. RAW COUNTS.

    🔴 THE BUG THIS PARAMETER FIXES. The TIFF was rendered through `flat=True` while its own
    ImageDescription said `pixels=RAW CAMERA COUNTS`. Measured on a real export: trial 11's median
    went 2111 -> 3435 (x1.63), trial 16's 2702 -> 3528 (x1.31), trial 106's 3175 -> 3550 (x1.12) —
    every tile's exposure dragged onto the session `level`. So the file a biologist opens in Fiji was
    **exposure-normalised per tile**, with a header swearing it was not, and photometry off it was
    wrong. Exposure genuinely varies ~2.4x across this run: that is data, not an artefact, and the
    deliverable must not silently erase it.

    ⚠️ **THE COVERAGE MASK IS NOT OPTIONAL.** **13.1 % of the canvas is background encoded as
    exactly `0.0`**, indistinguishable from a legitimately black pixel, and **there is no alpha
    channel**. Export to a plain TIFF and the two merge forever. It is free — the union of the tile
    rectangles IS `wsum > 0` in the feather path (the feather is floored at 1e-3, never 0). We take
    it from `render._canvas` (render.py:81), which is pure geometry and touches no pixels.

    Modes (measured, CPU, 312 frames in RAM):
      * **feather — 1.11 s. The only interactive mode.** THE DEFAULT.
      * median — 41.7 s, ~800 MiB peak, plus a cosmetic `All-NaN slice` RuntimeWarning (suppressed).
      * alpha — 74.0 s, needs spectralign, and silently returns **float64 on a canvas 1 px LARGER
        in each dimension**. We pad the coverage mask to match rather than pretend they agree.
    """
    from . import loader                                   # the ONE flat-field. No fallback copy.

    pos = {}
    for t, xy in (positions or {}).items():
        t = int(t)
        if t in session.row_of and xy is not None and xy[0] is not None:
            pos[t] = np.asarray([float(xy[0]), float(xy[1])], float)
    if not pos:
        raise ValueError("nothing to render: no placed tiles")

    row_of, frames, flat_n = session.row_of, session.frames, session.flat_n
    level = float(session.tone.level)

    def frame_of(t):
        if cancel is not None and cancel.is_set():
            raise RuntimeError("cancelled")
        f = frames[row_of[int(t)]]
        if not flat:
            return np.asarray(f, np.float32)               # RAW CAMERA COUNTS. Untouched.
        return loader.flat_correct(f, flat_n, level)

    trials, P, H, W = mrender._canvas(pos, (TILE, TILE))     # geometry only; no pixels touched
    cov = np.zeros((H, W), bool)
    for (x, y) in P:
        cov[int(y):int(y) + TILE, int(x):int(x) + TILE] = True

    sink = _RenderSink(report, len(pos))
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="All-NaN slice encountered")
        with contextlib.redirect_stdout(sink):
            img = mrender.render(pos, frame_of, tilesize=(TILE, TILE), mode=mode)

    if img.shape != cov.shape:                               # mode="alpha": 1 px bigger each way
        c2 = np.zeros(img.shape, bool)
        c2[:cov.shape[0], :cov.shape[1]] = cov
        cov = c2
    return np.asarray(img), cov


class _RenderSink:
    """render.render prints `rendered k/N`; turn that into progress instead of noise."""

    def __init__(self, report, n):
        self.report, self.n, self.buf = report, max(n, 1), ""
        self.re = re.compile(r"rendered (\d+)/(\d+)")

    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            m = self.re.search(line)
            if m and self.report:
                self.report(100.0 * int(m.group(1)) / max(int(m.group(2)), 1), line.strip())
        return len(s)

    def flush(self):
        pass


# =============================================================================
# Scoring — DEV ONLY, and it comes with a warning
# =============================================================================
def score_against_gt(positions: dict, gt_path=None, rng: str = "merged", tol: float = 10.0) -> dict:
    """OPTIONAL, dev-only: score positions against `analysis/ground_truth/`. 260620d only.

    ⛔ **DO NOT REIMPLEMENT `score.robust_align`.** A reimplementation with a different tie-break
    scored the same positions **152/156** where the canonical one gives **155/156**. We IMPORT it.

    ⛔ **NEVER score a project file this app produced against the method that seeded it.** The
    result is 100 % BY CONSTRUCTION. This project has already destroyed one benchmark exactly that
    way (`analysis/archive/.../ground_truth/260620d.json` IS T27's own output). That is what the
    provenance stamp in API.md §11.4 exists for.
    """
    from analysis.benchmark import score as bscore          # it fixes its own sys.path

    build = {int(t): np.asarray([float(p[0]), float(p[1])], float)
             for t, p in positions.items() if p is not None and p[0] is not None}
    gt, _ = bscore.load_gt(gt_path, rng=rng)
    rep = bscore.score(build, gt, build_id="app:engine", tol=tol, rng=rng)
    return jsonable(rep)
