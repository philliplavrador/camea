"""The ONE module in the repo allowed to touch a `_private` on t27 / t33 / render.

`t27.py`, `t33.py`, `quality.py` and `render.py` are **byte-identical** copies of
`archive/analysis/mosaic/` and they are under the 312/312 regression guard
(`tests/slow/test_solver_312.py`). We do **not** rename their internals to make them public: every
rename is a byte-change to guarded code in exchange for a leading underscore. `_tag` -> `tag` is
three edits in t33; `_pool` -> `pool` is a `def` plus two call sites inside `match()`; `_canvas` ->
`canvas` is a `def` plus two call sites in render.py. None of that buys anything.

So every private reach lives **here**, behind a public name, and there are exactly **six** of them
(ported from the old `app/backend/engine.py`, which had exactly the same six):

    1. t33._pool         -> build_memo()      the pass-1 composite memo (engine.py:1076-1122)
    2. t33._tag          \\
    3. t33._cache_key     >-> read_anchors()  the per-tile anchors t33 caches but never returns
    4. t33._load_checked /                    (engine.py:1344-1374)
    5. t27._free         -> free_gpu()        (engine.py:361, 372, 1001)
    6. render._canvas    -> canvas()          (engine.py:1602)

This file is NOT under the guard, so it may be edited freely. And if some future agent ever *does*
rename something inside t33, exactly one file breaks — loudly, at import — instead of four.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from . import render, t27, t33

TILE = 512

__all__ = ["TILE", "canvas", "free_gpu", "read_anchors", "build_memo", "gpu_info"]


# --- 0. t27.xp() -> the ONE GPU detector -----------------------------------------------------
#
# ⭐ **THE DETECTOR LIVES HERE BECAUSE THE API LAYER IS NOT ALLOWED TO IMPORT t27.** `solve.py` is
# the only module outside `engine/` that may (`docs/SPLIT.md` §0.5, and
# `tests/unit/test_mosaic_solve.py` asserts it) — and the API needs `GpuInfo` for every
# `SessionResponse`. So the human-readable dict is assembled here, in the adapter layer, exactly as
# v1 did it (`archive/app-v1/backend/engine.py:287`). `camea.api.routes_core` calls
# `camea.engine.gpu_info()` and never sees t27.

_GPU_INFO: dict | None = None
_GPU_LOCK = threading.Lock()

GPU_NOTE = (
    "A 312-tile build takes ~3 min cold and ~25 s warm on the GPU. The interactive sweep is "
    "~1,068 ms per Space."
)
CPU_NOTE = (
    "No usable CUDA GPU. A 312-tile build takes ~8-10 min on the CPU instead of ~3 min. The "
    "interactive sweep is only 1.46x slower (1,562 vs 1,068 ms per Space), because exact_ncc runs "
    "on the CPU either way — the part you spend an hour in is barely affected."
)


def gpu_info() -> dict:
    """`api.schemas.GpuInfo`. Memoised: the first call **executes a real CUDA op** (~200 ms).

    🔴 **DETECTION MUST EXECUTE A REAL OP.** `import cupy` **SUCCEEDS** on a broken CUDA install — it
    emits only a `UserWarning`; it is **`cupy.zeros(1) + 1`** that raises. A `try: import cupy /
    except ImportError` guard **DOES NOT WORK.**

    ⇒ We call **`t27.xp()`** and nothing else. It does the DLL dance, imports CuPy, forces a context
    with a real op, and falls back to numpy on ANY exception. **There is no second detector in this
    codebase and there must not be one.**

    `reason` is a **string for the human, never a verdict**: "no GPU" because a CUDA DLL is off the
    search path is *fixable*, and it is not the same thing as "no card". Being honest about the bill
    (`note`) and silent about the bug (`reason`) is how a fixable DLL-path problem becomes a
    permanent 8-minute build.
    """
    global _GPU_INFO
    with _GPU_LOCK:
        if _GPU_INFO is not None:
            return dict(_GPU_INFO)

        xp = t27.xp()                       # <- the real op happens in HERE, not out here
        available = bool(t27.on_gpu())
        info: dict = {
            "available": available,
            "backend": "cupy" if available else "numpy",
            "name": None,
            "cupy": None,
            "cuda_runtime": None,
            "reason": None,
            "note": GPU_NOTE if available else CPU_NOTE,
        }
        if available:
            try:
                info["cupy"] = str(xp.__version__)
                info["cuda_runtime"] = int(xp.cuda.runtime.runtimeGetVersion())
                name = xp.cuda.runtime.getDeviceProperties(0)["name"]
                info["name"] = name.decode() if isinstance(name, bytes) else str(name)
            except Exception as e:          # noqa: BLE001 — details are a nicety; the verdict is not
                info["name"] = f"(CUDA device, details unavailable: {type(e).__name__})"
        else:
            info["name"] = "CPU (numpy)"
            info["reason"] = (
                "CuPy is not installed, or CUDA could not be initialised — t27.xp() fell back to "
                "NumPy, and the line it printed to the console says which. If this machine has a "
                "card, it is usually fixable: install the `gpu` extra (`uv sync --extra gpu`), which "
                "pulls the nvidia-* CUDA runtime wheels the DLL dance looks for."
            )

        _GPU_INFO = info
        return dict(info)


# --- 6. render._canvas ---------------------------------------------------------------------
def canvas(pos: dict, tilesize: tuple[int, int] = (TILE, TILE)):
    """`(trials, P, H, W)` — the integer tile top-lefts and the size of the union canvas.

    Pure geometry; no pixels are touched. This is what a coverage mask is built from, and the mask
    is **not optional**: ~13 % of the canvas is background, encoded as exactly 0.0, and there is no
    alpha channel to tell it apart from a genuinely black pixel.
    """
    return render._canvas(pos, tilesize)


# --- 5. t27._free --------------------------------------------------------------------------
def free_gpu() -> None:
    """Release CuPy's block pool. A no-op on CPU, and never raises."""
    try:
        t27._free()
    except Exception:  # noqa: BLE001
        pass


# --- 2/3/4. t33._tag + _cache_key + _load_checked -------------------------------------------
def read_anchors(cache_dir, trials: list[int], cfg) -> dict:
    """The per-tile anchors t33 computed and cached -> `{trial: {"anc": [x, y], "ncc": v}}`.

    t33 persists them to `T33_anchors_<tag>_<hash>.npz` (t33.py:716/741) but does **not** put them
    in `info` — and they are the best per-tile confidence signal that exists (pass 2 only; on
    260620d, 156/156 reached NCC >= 0.30, median 0.815). So we read the file back.

    `_tag` / `_cache_key` / `_load_checked` are pure functions of the trial list and the config. If
    they are ever renamed, this degrades to **"no per-tile anchor data"** — never to wrong data:
    every failure path returns `{}`. `_load_checked` also *refuses* an npz whose config hash differs,
    which is the whole reason we go through it rather than `np.load`.

    ⚠️ Returns `{}` when the build ran with `cache=None` — there is no file to read.
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
    except Exception:                                      # noqa: BLE001 — evidence, not a verdict
        return {}


# --- 1. t33._pool ---------------------------------------------------------------------------
_POOL_MEMO: list = []


@contextmanager
def build_memo(max_entries: int = 2):
    """Memoise `t33._pool` on the REFERENCE side of the build's per-tile anchor loop.

    The loop (t33.py:729-739) calls `match(IMG1, MSK1, tile, TMSK)` once per pass-2 tile — 156 times
    with the SAME 7 Mpx pass-1 composite — and `t33.match` re-pools that composite every single time.
    This hands back the identical arrays the real `_pool` returned the first time.

    ⭐ **BIT-IDENTICAL BY CONSTRUCTION.** It caches the real function's own OUTPUT OBJECT, keyed by
    array IDENTITY (`is`), holding strong references so an `id()` cannot be recycled underneath it.
    It does not reimplement `_pool`, does not touch `_smooth()`, and does not change any FFT size
    (the grid stays exactly 2160x1350 as shipped). `t33.match` never mutates what `_pool` gives it —
    it reads `.shape` / `.sum()` and feeds them to `_surfaces`, which copies into new arrays.

    ⚠️ **A CONTEXT MANAGER, not the old `enable_build_memo()` / `disable_build_memo()` pair.** Those
    were a global, permanent monkey-patch on a module the guard also imports, and nothing enforced
    that it was ever turned off. This cannot leak: `finally:` puts the real `_pool` back. The guard
    asserts it is unpatched anyway (`t33._pool.__module__ == t33.__name__`).

    HONEST SCOPE: the 25 s figure in the old SPEED notes is for memoising the pooled reference **and
    its three FFTs**. The FFTs live INSIDE `t33._surfaces`; caching them means editing t33, under the
    guard. This is the pooling half only.
    """
    orig = t33._pool

    def _pool_memo(img, msk, ds):
        for (ci, cm, cds, out) in _POOL_MEMO:
            if ci is img and cm is msk and cds == ds:      # identity, not equality. Exact.
                return out
        out = orig(img, msk, ds)
        _POOL_MEMO.append((img, msk, ds, out))             # strong refs: id() cannot be recycled
        while len(_POOL_MEMO) > max_entries:
            _POOL_MEMO.pop(0)
        return out

    t33._pool = _pool_memo
    try:
        yield
    finally:
        t33._pool = orig
        _POOL_MEMO.clear()
