"""solve.py — ⭐ **THE ENGINE ADAPTER.** The only module in the app that imports `t27` / `t33`.

Ported from `archive/app-v1/backend/engine.py` (1,660 lines, READ-ONLY reference). Everything that
was *mosaic* in that file is here; everything that was *core* went to `camea.core` and everything
that was *engine* went to `camea.engine`. See `docs/SPLIT.md` §1.6 for the line-by-line map.

⛔⛔ **THIS MODULE CALLS THE ENGINE. IT NEVER FORKS IT.**
Two copies of t33 is a silent regression. `tests/slow/test_solver_312.py` (~130 s cold, asserts
**312/312** against a hand-placed human ground truth) must still pass after anything that happens in
here. Nothing in this file edits t27/t33, shadows one of their names, or copies a number out of one.

**THE FOUR THINGS THIS MODULE ADDS, and why each is safe:**

 1. `_subpixel()` — a separable parabola on the exact-NCC 3x3. **ADDITIVE**: eight more
    `t33.exact_ncc` calls on the *outside*. Nothing inside t33 sees it.
 2. `_CompositeCache` — the INCREMENTAL anchor composite (268 ms -> 108 ms at 156 anchors). It keeps
    `t33.composite`'s running `acc`/`wsum` arrays instead of rebuilding them, and it is
    **bit-identical** — see the proof in the class docstring. It refuses its own fast path (and falls
    back to rebuilding from `t33.feather()` in the same order) the instant a precondition fails.
 3. The **build memo** — `camea.engine.adapters.build_memo()`, which memoises `t33._pool` by array
    IDENTITY on the reference side of the build's anchor loop. It caches the real function's own
    output object; it does not reimplement it.
 4. A **stdout scraper** for progress, because **t33 has no progress callback of any kind**.

⛔ **THE APP CARRIES NO DATASET KNOWLEDGE.** No trial number is special in this file. The refusal set
(`refuse=`) arrives **in the request**, from the document, where the human put it. There is no
`EXCLUDED`, no `BLANK_THRESHOLD`, no `usable_trials`. The one symbol the app takes from the exclusion
module is `gaps()`, and it takes it through `camea.core.dataset`.

---------------------------------------------------------------------------------------------------
WHAT ISN'T HERE, AND WHERE IT WENT
---------------------------------------------------------------------------------------------------
* `_predance_cuda_dlls` / `_predance_env_dlls`  -> `camea.engine.dll` (frozen-only; the conda half is
  **deleted** — under `uv` it was always a no-op, and the 312/312 guard runs t33 fully **cold**,
  which calls `np.linalg.solve` twice, so the BLAS delay-load is *proven* fine here).
* `_repo_root` / `REPO_ROOT` / the `sys.path` insert / `CAMEA_REPO_ROOT` -> **deleted**. `camea` is an
  installed package. A "point the app at another copy of the engine" knob is a loaded gun now that
  the engine is *in* the app.
* `gpu_info` / `warm_gpu`      -> the GPU layer (`camea.engine`). This module needs only `on_gpu()`,
                                 and there is **exactly one detector** — `t27.xp()`.
* `jsonable`                   -> `camea.core.document.jsonable`  (it was duplicated three times).
* `_load_frames`               -> `camea.core.frames.load_frames` — ⭐ **ONE READER.** v1's child
                                 carried an inline shim that flipped the frame **unconditionally**
                                 while the canonical reader flips **conditionally on the XML**. The
                                 child would have solved on 180-degree-rotated frames while the UI
                                 used un-rotated ones, and every tile would still have looked
                                 plausible. **No fallback. Ever.**
* `read_anchors` / the `t33._pool` patch / `render._canvas` / `t27._free`
                               -> `camea.engine.adapters` — the ONE module allowed to touch an
                                 underscore on t27/t33/render (`docs/ENGINE_MOVE.md` §4).
* `render_mosaic` / `_RenderSink` -> `legacy/mosaic/export.py`.
* `score_against_gt`           -> `tests/slow/`. It is dev-only, it is 260620d-only, and
                                 ⛔ **`score.robust_align` must never be reimplemented** (a rewrite
                                 with a different tie-break scored the same positions 152/156 where
                                 the canonical one gives 155/156).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import threading
import time
import traceback
from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from camea.core.dataset import gaps  # the ONE reach into the exclusion module: a pure function
from camea.core.document import jsonable  # t33's `info` holds a t27.Config; json.dumps CRASHES
from camea.core.frames import FrameStore, load_frames  # ⭐ THE reader. There is no other.

# ⛔⛔ THE ONLY MODULE IN THE APP PERMITTED THESE THREE LINES.
from camea.engine import t27, t33
from camea.engine.adapters import build_memo, free_gpu, read_anchors

__all__ = [
    # constants
    "TILE",
    "ANCHOR_KPK",
    "ANCHOR_MINFRAC",
    "ANCHOR_MINABS",
    "MATCH_CACHE_SIZE",
    "SNAP_RADIUS",
    "MAX_CANDIDATES",
    "MARGIN_THIN",
    "NMS_PX",
    "GPU_NOTE",
    "PHASES",
    "PHASE_WEIGHT_GPU",
    "PHASE_WEIGHT_CPU",
    "PHASE_INDEX",
    "N_PHASES",
    "BUILD_TARGET",
    # gpu
    "on_gpu",
    "release_gpu",
    # the anchor-composite primitive
    "Candidate",
    "MatchResult",
    "composite_of",
    "cache_key",
    "match_anchor",
    "score_at",
    "reset_caches",
    "cache_stats",
    # the build
    "make_config",
    "build_result",
    "build_worker",
    "read_anchors",
]


# =================================================================================================
# Constants that MUST NOT diverge (docs/BEHAVIOUR.md §7)
# =================================================================================================
#: `t33.TILE`. ⭐ **This 512 is the reason the 512x512 gate is MOSAIC's policy and not core's** — a
#: `FrameStore` holds frames of whatever shape the XML says; t33 does not.
TILE = 512

ANCHOR_KPK = 8  # ⚠️ exactly t33.place's per-tile anchor call (t33.py:732).
ANCHOR_MINFRAC = 0.0  # ⚠️ ditto. For ONE tile a *fractional* overlap rule would let a corner
ANCHOR_MINABS = 120000.0  #    match win, so the floor is ABSOLUTE. Do not "improve" these.

MATCH_CACHE_SIZE = 32  # LRU entries in the match memo
SNAP_RADIUS = 64  # ⚠️ NEVER let the UI exceed 128: the electrode grid repeats every 256 px
MAX_CANDIDATES = 9  # ⭐ 9, not 8 — or the key `9` can never fire
MARGIN_THIN = 0.10  # below this, the margin is the signature of a surviving grid alias
NMS_PX = 24.0  # t33.match's own peak separation

GPU_NOTE = (
    "GPU: a 312-tile build takes ~3 min. Without it, ~8-10 min - and the interactive sweep is "
    "only 1.46x slower (1,562 vs 1,068 ms per Space), because exact_ncc runs on the CPU either way."
)

#: The dotted path `core.jobs.submit_process` spawns. It must be importable in a FRESH interpreter.
BUILD_TARGET = "camea.legacy.mosaic.solve.build_worker"


# --- the phase weighting of a COLD build ---------------------------------------------------------
#
# 🔴 THERE ARE TWO OF THESE TABLES, AND THERE HAVE TO BE. MEASURED on one box, same build, same data,
# 312 tiles:
#
#            pass1   backbone   anchors   runs    total
#     GPU     17 s      22 s      59 s    12 s    112 s
#     CPU    218 s     220 s     129 s    20 s    588 s      <- the SHIPPED DEFAULT install
#
# The whole *shape* inverts: on the GPU the anchor loop dominates (53 %); on the CPU pass 1 +
# backbone are **75 % of the build**. A single GPU-calibrated table on a CPU machine is not an
# approximation, it is a different curve — it told a CPU user "~873 s left" when 368 s remained
# (+137 %). The child knows which device it is on before it starts, and it picks the right table.
#
# (This weighting is the *job's* knowledge, not the registry's — which is why `core.jobs.Progress`
# carries a bare `pct` and says nothing about phases. `docs/SPLIT.md` §1.4.)
PHASES = ("pass1", "backbone", "composite", "anchors", "recut", "runs")
PHASE_WEIGHT_GPU = {
    "pass1": 0.15, "backbone": 0.20, "composite": 0.02,
    "anchors": 0.52, "recut": 0.01, "runs": 0.10,
}
PHASE_WEIGHT_CPU = {
    "pass1": 0.37, "backbone": 0.37, "composite": 0.01,
    "anchors": 0.22, "recut": 0.01, "runs": 0.02,
}
PHASE_INDEX = {
    "pass1": 1, "backbone": 2, "composite": 3, "anchors": 4, "recut": 5, "runs": 5, "done": 6,
}
N_PHASES = 6


# =================================================================================================
# GPU — there is EXACTLY ONE DETECTOR, and it is `t27.xp()`
# =================================================================================================
def on_gpu() -> bool:
    """Is the engine actually on a GPU?

    🔴 **DETECTION MUST EXECUTE A REAL OP.** `import cupy` **succeeds** on a broken CUDA install (it
    emits only a UserWarning); it is `cupy.zeros(1) + 1` that raises. `t27.on_gpu()` calls `t27.xp()`,
    which does exactly that. **There is no second detector in this codebase and there must not be
    one.** (The human-readable `gpu_info` dict — `available` / `name` / `reason` / `note` — belongs to
    the GPU layer and the API, not to the mosaic feature. This module needs only the boolean.)
    """
    return bool(t27.on_gpu())


def release_gpu() -> None:
    """Drop CuPy's memory pool. Call this **before spawning a build child**, so the parent's device
    footprint does not collide with the child's: a 312-tile build peaks at ~2.0 GB and a 4 GB card is
    tight. A no-op on CPU; never raises."""
    free_gpu()


# =================================================================================================
# ⭐ THE INCREMENTAL ANCHOR COMPOSITE
# =================================================================================================
class _CompositeCache:
    """Keep `t33.composite`'s running `acc`/`wsum` arrays instead of rebuilding them every match.

    ⭐ **WHY THIS IS BIT-IDENTICAL, and not merely "close".** `t33.composite` accumulates

        for k, (x, y) in enumerate(P):
            acc[y:y+512, x:x+512] += B[rows[k]] * feather

    so every canvas pixel holds a float32 sum taken **in `k` order**. If we (a) add tiles in exactly
    that order and (b) only ever APPEND, then the partial sum after `m` tiles is bit-for-bit the
    prefix of the full sum — float addition is not associative, but it *is* deterministic, and we
    never reorder or re-associate anything. Growing the canvas is a pure integer paste of the old
    array into a bigger one, which changes no value at all.

    THE PRECONDITIONS. Each is CHECKED, and each falls back to a full rebuild — from `t33.feather()`,
    in the same order — when it fails:

      1. Same session (same band stack) — see `_token`.
      2. The new sorted anchor list has the OLD one as a PREFIX, and the old tiles' positions are
         unchanged. (A sweep anchors in ascending trial order, so this is the hot path. Re-dragging
         an anchor, or rescuing an out-of-order tile, correctly rebuilds.)
      3. ⚠️ **The integer layout of the old tiles must be a pure TRANSLATION of what it was.**
         `P = rint(local - m0)` and `m0 = local.min(0)` — so when a new tile extends the layout `m0`
         moves, and if it moves by a NON-INTEGER amount the rounding can change *per tile* (x=0.4
         with m0=0.0 rounds to 0; with m0=-0.3 it rounds to 1, while x=1.6 rounds to 2 in both).
         That is not a translation and the paste would be wrong. So we recompute `P` from scratch and
         verify that `P_new[:m] - P_old` is ONE constant vector. It usually is; when it is not, we
         rebuild. The check costs a few microseconds and it is the whole safety of the class.

    Verified against `t33.composite` on real data over a 156-step incremental sweep: `array_equal`
    on `img`, on `mask`, and an identical `m0`, at EVERY step.
    """

    def __init__(self) -> None:
        #: ⚠️ `score_at` runs **CONCURRENTLY** with `match_anchor`, on purpose — it used to wait out a
        #: whole match, so the live NCC under the user's cursor during a drag was up to a full match
        #: out of date (67 ms alone vs 439 ms behind a prefetch; on the CPU-only default a prefetch
        #: is 1,562 ms). This is the one piece of mutable state they share, so `get()` is atomic.
        #: Note the arrays it hands out are never mutated afterwards — every path allocates fresh
        #: `acc`/`wsum` — so a caller holding a previous result cannot have it changed underneath it.
        self._lock = threading.RLock()
        self._reset()
        self.hits = 0
        self.rebuilds = 0

    def _reset(self) -> None:
        self.token: str | None = None
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
        """-> `(img, mask, m0)`, exactly as `t33.composite(band, rows, local)` would return them."""
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
            shift = P[:m] - self.P                        # must be ONE constant integer vector
            if np.all(shift == shift[0]):
                sx, sy = int(shift[0][0]), int(shift[0][1])
                oh, ow = self.acc.shape
                Hc, Wc = int(P[:, 1].max()) + TILE, int(P[:, 0].max()) + TILE
                if sx >= 0 and sy >= 0 and sy + oh <= Hc and sx + ow <= Wc:
                    acc = np.zeros((Hc, Wc), np.float32)
                    wsum = np.zeros((Hc, Wc), np.float32)
                    acc[sy:sy + oh, sx:sx + ow] = self.acc     # a pure paste: no value changes
                    wsum[sy:sy + oh, sx:sx + ow] = self.wsum
                    fe = t33.feather()                         # t33's OWN feather. Not a copy.
                    for k in range(m, n):                      # append IN ORDER
                        x, y = int(P[k][0]), int(P[k][1])
                        acc[y:y + TILE, x:x + TILE] += band[rows[k]] * fe
                        wsum[y:y + TILE, x:x + TILE] += fe
                    self.hits += 1

        if acc is None:
            # Cold, or a precondition failed. Rebuild from t33's own primitives, in the same order,
            # so that the NEXT append is still bit-identical.
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

        # …and the tail of `t33.composite`, verbatim in effect: mean-subtract over the VALID MASK
        # only. An unmasked mean would be dragged by the zeros outside the hull and would bias every
        # NCC downstream by the *shape of the footprint*.
        msk = wsum > 0
        img = np.where(msk, acc / np.maximum(wsum, 1e-6), 0.0).astype(np.float32)
        img = np.where(msk, img - img[msk].mean(), 0.0).astype(np.float32)
        return img, msk, m0


_COMPOSITE = _CompositeCache()


def _require_tile_shape(store: FrameStore) -> None:
    """t33's composite, feather and FFT plans are **512x512, everywhere**. The 512x512 gate is
    mosaic's (`legacy/mosaic/run.py`), and this is that gate restated as a precondition: if an
    off-shape store ever reached the matcher, the feather would be pasted at the wrong stride and the
    answer would be **silently, plausibly wrong**. Fail loudly instead."""
    h, w = store.shape
    if (h, w) != (TILE, TILE):
        raise ValueError(
            f"the mosaic solver is {TILE}x{TILE}-only (that is t33.TILE), but this session holds "
            f"{w}x{h} frames. Select a {TILE}x{TILE} run before matching or building."
        )


def _token(store: FrameStore) -> str:
    """Identifies the loaded pixel stack, for the composite cache and the match memo.

    ⚠️ **IT USED TO BE `id(session.band)`, AND `id()` IS RECYCLED.** Measured: five sequential
    same-size allocations returned the SAME address four times. Two different sessions of the same
    dataset with the same tile count genuinely collided on that token, and the composite cache would
    then serve one session's answer to another. `FrameStore.nonce` is a uuid4 minted per open and
    cannot be recycled. (`reset_caches()` on every open is belt and braces on top of it.)
    """
    return f"{store.nonce}:{int(store.band.shape[0])}"


def _pos(positions: Mapping, t: int) -> tuple[float, float]:
    """Positions arrive from JSON with STRING keys (`"11"`) and from python with int keys."""
    v = positions.get(t, positions.get(str(t)))
    if v is None:
        raise KeyError(f"no position given for anchor {t}")
    return float(v[0]), float(v[1])


def composite_of(store: FrameStore, anchors: Sequence[int],
                 positions: Mapping) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """`(img, mask, m0)` for the anchor field.

    `anchors` need not be sorted — we sort. The contract says order is irrelevant, and the sort is
    what makes the incremental cache and the memo key agree on **one canonical order**.
    """
    _require_tile_shape(store)
    ts = sorted(int(t) for t in anchors)
    rows = [store.row_of[t] for t in ts]
    local = np.array([_pos(positions, t) for t in ts], float)
    return _COMPOSITE.get(store.band, _token(store), ts, rows, local)


def reset_caches() -> None:
    """Drop the composite cache and the match memo. **The API MUST call this whenever the session's
    pixels change** (a new open, a new run selection). v1 was carrying the previous session's arrays
    across an open."""
    _COMPOSITE.clear()
    with _MEMO_LOCK:
        _MEMO.clear()


def cache_stats() -> dict[str, int]:
    """Diagnostics only. Nothing branches on these."""
    with _MEMO_LOCK:
        n_memo = len(_MEMO)
    return {
        "composite_hits": _COMPOSITE.hits,
        "composite_rebuilds": _COMPOSITE.rebuilds,
        "memo_entries": n_memo,
    }


# =================================================================================================
# ⭐⭐ THE ANCHOR-COMPOSITE PRIMITIVE — one call, four features
# =================================================================================================
@dataclass
class Candidate:
    """One ranked candidate placement, in WORLD coordinates."""

    rank: int  # 0-indexed. **DISPLAYED as +1** — the key `1` is rank 0.
    x: float  # world TOP-LEFT. NOT a dx, NOT a centre. (Drawing a centre? add +TILE/2.)
    y: float
    ncc: float
    npix: int
    subpixel: bool  # True only for rank 0 (the alternatives stay on integers)

    def to_json(self) -> dict:
        return {"rank": int(self.rank), "x": float(self.x), "y": float(self.y),
                "ncc": float(self.ncc), "npix": int(self.npix), "subpixel": bool(self.subpixel)}


@dataclass
class MatchResult:
    """`POST /api/mosaic/match/anchor`'s body (`api.schemas.MatchResult`)."""

    target: int
    mode: str
    n_anchors: int
    composite: dict | None
    candidates: list[Candidate]
    best: Candidate | None
    margin: float | None
    margin_thin: bool
    refused: dict | None
    gpu: bool
    elapsed_ms: float
    cached: bool
    cache_key: str
    #: Anchors DROPPED from the composite because the human refused them (see `_refusal`). **Not an
    #: error** — but the UI must say so, because it silently changes the aperture the match had.
    dropped_anchors: list[int] = field(default_factory=list)

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


# --- the memo ------------------------------------------------------------------------------------
_MEMO: OrderedDict[str, MatchResult] = OrderedDict()
_MEMO_LOCK = threading.Lock()
_INFLIGHT: dict[str, threading.Event] = {}
#: Serialises the actual compute. The GPU has one memory pool and the composite cache has one set of
#: running arrays; two matches at once would fight over both. A **duplicate** request (the A-branch
#: prefetch the user then confirms) does not wait on this lock at all — it waits on the in-flight
#: event and takes the memo hit. ⚠️ `score_at` is **deliberately not** under it: see `_CompositeCache`.
_COMPUTE_LOCK = threading.Lock()


def cache_key(nonce: str, target: int, anchors: Sequence[int], positions: Mapping, mode: str,
              near: Sequence[float] | None, radius: int, max_candidates: int,
              refuse: Iterable[int] = ()) -> str:
    """The memo key. ⭐⭐ **THIS FUNCTION IS THE PREFETCH'S CORRECTNESS GUARANTEE.**

    🔴 **THE TRAP IT DEFUSES.** The front end prefetches tile N+1's match the instant tile N is
    *displayed*. That prefetch **MUST use the composite INCLUDING the tile currently under
    judgement** — i.e. it must assume the user will press `A`. Prefetching from a composite
    **without** it disagrees with the truth in **18 % of presses and is catastrophically wrong (up to
    1,143 px) in 6 %**.

    Because **the key IS the anchor set and their positions**, a user who presses `E` instead
    produces a genuinely different key, the memo MISSES, and the server recomputes honestly. The trap
    is *structurally impossible* to fall into — **as long as nobody invents a second cache keyed on
    the trial number.** Do not. Not on the server, and not in the browser.

    ⚠️ **`refuse` IS PART OF THE KEY.** In v1 the refusal set was hidden state on the session that
    `PUT /api/scan/blank` mutated — which is exactly what made this endpoint *not* a pure function of
    its request body, contrary to the comment at the top of its own server, and is why the server had
    to blow the caches away on every scan edit. It now travels in the body, so it must be in the key.
    """
    payload = json.dumps({
        "nonce": str(nonce),
        "target": int(target),
        "anchors": [[int(t), round(_pos(positions, t)[0], 3), round(_pos(positions, t)[1], 3)]
                    for t in sorted(int(a) for a in anchors)],
        "mode": mode,
        "near": [round(float(near[0]), 3), round(float(near[1]), 3)]
                if (mode == "local" and near is not None) else None,
        "radius": int(radius) if mode == "local" else None,
        "max_candidates": int(max_candidates),
        "refuse": sorted({int(t) for t in refuse}),
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _refuse_set(refuse: Iterable[int] | None) -> set[int]:
    """⛔ **THE REFUSAL SET IS AN ARGUMENT, NOT STATE.** It is the blank list the human left standing
    (`MosaicDocument.blank_scan.blank`), and it arrives in the request body. There is no module-level
    list here, no threshold constant, and nothing that could ever refuse a frame the user did not."""
    return {int(t) for t in (refuse or ())}


def _texture_of(store: FrameStore, t: int) -> float | None:
    """The MEASURE (`std(DoG(3,30))`) for one trial. It is core's — a property of the frame — and it
    is memoised on the store; the `open` job warms it. Read for the refusal *message* only: nothing
    in this module ever turns a texture number into a decision."""
    try:
        return store.texture().get(int(t))
    except Exception:  # noqa: BLE001 — evidence for a message must never fail a match
        return None


def _refusal(store: FrameStore, target: int, refuse: set[int],
             threshold: float | None = None) -> dict | None:
    """⛔ **BLANK TILES ARE REFUSED, NOT SCORED — and it is the TARGET that is fatal.**

    Two blank frames **136 trials apart** correlate **+0.43 at zero shift** (honest noise floor
    0.115), because what they share is *fixed-pattern sensor structure*, which does not move with the
    stage. **They register confidently and wrongly.** There is no `force` flag and there will not be
    one: a human may still DRAG a blank tile into place — a human eye is allowed to do what the
    correlator must not — but Space, Snap and Score all refuse.

    ⚠️ **THE TARGET, NOT THE ANCHORS.** The old API said "…or if any tile in `anchors` is", and that
    clause **dead-ends the app**. It was written assuming the refusal list could only ever hold
    frames that were never anchorable. It cannot: the human ticks the list, in trial order, and the
    moment he keeps trial 34 refused and then anchors it, every subsequent Space and Snap would
    refuse **forever** and the sweep would die at tile 35.

    So a refused **ANCHOR** is **dropped from the composite** (`_blank_anchors`) and reported, never
    fatal. That is strictly *safer* on the axis the trap actually cares about — a blank frame's
    fixed-pattern structure now contributes **no pixels at all** to any correlation — and it keeps the
    sweep alive. If the target's only overlap was with a dropped anchor, `npix` falls under
    `exact_ncc`'s floor and the honest answer is `ncc: null`, "not measurable".
    """
    who = int(target)
    if who not in refuse:
        return None
    return {
        "reason": "blank",
        "trials": [who],
        "texture": _texture_of(store, who),
        "threshold": None if threshold is None else float(threshold),
        "message": (
            f"Trial {who} is near-featureless glare. Any match it scores is fixed-pattern sensor "
            f"structure, not the scene - it would register confidently and wrongly. Place it by "
            f"hand, or exclude it."),
    }


def _blank_anchors(anchors: Sequence[int], refuse: set[int]) -> list[int]:
    """The anchors we must DROP from the composite (see `_refusal`). Never fatal."""
    return sorted({int(a) for a in anchors if int(a) in refuse})


def _no_anchors(dropped: Sequence[int], what: str) -> dict:
    return {
        "reason": "no_anchors",
        "trials": [int(t) for t in dropped],
        "texture": None,
        "threshold": None,
        "message": (f"Every anchor offered is a blank frame, so there is no scene texture to "
                    f"{what} against. Anchor a tile with real structure first."),
    }


def _tile_for_match(store: FrameStore, target: int) -> tuple[np.ndarray, np.ndarray]:
    """The matcher's tile: **BAND-PASSED and MEAN-SUBTRACTED**, exactly as `t33.place` prepares it
    (t33.py:730-731). The composite is built from the SAME band-passed stack.

    ⚠️ **Tone mapping is for the DISPLAY only and must never touch this path.**
    """
    tile = store.band[store.row_of[int(target)]].astype(np.float32)
    tile = tile - tile.mean()
    return tile, np.ones((TILE, TILE), bool)


def _subpixel(IMG, MSK, tile, TMSK, dx: int, dy: int) -> tuple[float, float]:
    """Integer winner -> sub-pixel. A separable parabolic peak fit on the exact-NCC 3x3.

    8 extra `t33.exact_ncc` calls, ~30 ms. Applied to `candidates[0]` **only**. **ADDITIVE** — it
    does not touch t33 and it cannot affect the 312/312 guard.

    ⚠️ Do NOT replace this with a browser-side JS NCC: that search is alias-safe only within ~±48 px
    (the electrode grid repeats every **256 px**) and past that it locks onto a confident, WRONG grid
    alias. *Correct beats fast* — his explicit ruling on the snap.
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
    """`mode="local"` — **THE SNAP.** An exhaustive `exact_ncc` inside `radius` of the drop point.

    A **coarse grid at step 4** (`exact_ncc(..., stride=4)`, as t33's own tier A does), then NMS,
    then ±4 at pixel stride 1 around the winner, then the sub-pixel parabola. -> the same
    `[(ncc, dx, dy, npix)]` shape `t33.match` returns, best first, peaks >= `NMS_PX` apart.

    ⚠️ **Never widen `radius` past 128 in the UI.** The electrode grid repeats every **256 px** and a
    wide LOCAL search will confidently lock onto a grid alias. To search wide, use `mode="global"`:
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
    store: FrameStore,
    target: int,
    anchors: Sequence[int],
    positions: Mapping,
    mode: str = "global",
    near: Sequence[float] | None = None,
    radius: int = SNAP_RADIUS,
    max_candidates: int = MAX_CANDIDATES,
    refuse: Iterable[int] | None = None,
    threshold: float | None = None,
) -> MatchResult:
    """⭐⭐ **THE HEART OF THE APP.** Match `target` against the composite of the ANCHORED tiles.

    ⭐ **A PURE FUNCTION OF ITS ARGUMENTS.** There is no tile state on the server to be out of sync
    with — that is not a stylistic preference, it is `cache_key`'s correctness argument. `refuse`
    arrives from the document, in the request body.

    **ONE CALL, FOUR FEATURES:**
      * **place the next tile** on `Space`   -> `mode="global"`, take `candidates[0]`
      * **show ranked alternatives** (`V`, `1`-`9`) -> the SAME response, `candidates[1..]`
      * **rescue a tile the solver missed** -> the SAME call, on an unplaced tile
      * **snap a human's drag** (`S`)        -> `mode="local"`, `near` = the drop point

    **WHY A COMPOSITE IS THE RIGHT PRIMITIVE AND NOT MERELY A CONVENIENT ONE — APERTURE IS
    EVERYTHING.** Of 719 genuinely-overlapping tile PAIRS on this data, the exact-NCC argmax is >20 px
    wrong for 38 (5 %), at scores up to 0.760 — the canonical case (222 vs 250) has the 0.760 winner
    **757 px wrong** and the *truth* as the runner-up at 0.677. The same tile matched against the
    pass-1 COMPOSITE scores 0.654 vs 0.416 next-best and lands **1.7 px** from the human.

    **THE ARITHMETIC** (get it wrong and everything is ~512 px out)::

        IMG, MSK, m0 = t33.composite(band, rows, local)      # m0 = local.min(0)
        c = t33.match(IMG, MSK, tile, TMSK)                  # (dx, dy) == originB - originA
        #   A = the composite, B = the tile, so:
        #                    ⭐  world_topleft = m0 + (dx, dy)  ⭐

    ⚠️ **THE APERTURE IS SMALL AT THE START.** With ONE anchor down this call *is* a tile-pair — the
    weak case above. What saves the opening is that consecutive snapshots overlap ~78 % and
    consecutive whole-frame matches are the alias-robust ones. So **SURFACE THE EVIDENCE**:
    `n_anchors`, `composite.valid_px`, `ncc` and `margin` are in the response precisely so the user
    can watch the evidence strengthen instead of taking it on faith. **`margin_thin` (< 0.10) must be
    flagged loudly** — the shipped build's worst run margin is 0.081 against a ~0.47 typical, and a
    thin margin is exactly what a surviving alias looks like.

    Cost: ~1,068 ms GPU / 1,562 ms CPU (global); ~200-500 ms (local). MEMOISED — a repeat call with
    the same body returns in ~1 ms with `cached: true`, which is what makes the prefetch free.
    """
    t_start = time.time()
    target = int(target)
    anchors = sorted({int(a) for a in anchors})
    mode = str(mode or "global")
    refused_set = _refuse_set(refuse)

    if mode not in ("global", "local"):
        raise ValueError(f"mode must be 'global' or 'local', not {mode!r}")
    if not anchors:
        raise ValueError("match_anchor needs at least one anchor")
    if target in anchors:
        raise ValueError(f"target {target} is also listed as an anchor")
    if target not in store.row_of:
        raise KeyError(f"trial {target} is not in this session")
    for a in anchors:
        if a not in store.row_of:
            raise KeyError(f"anchor trial {a} is not in this session")
        _pos(positions, a)                                  # raises KeyError -> 400
    if mode == "local" and near is None:
        raise ValueError("mode='local' requires `near` (the world top-left you dropped it at)")
    radius = int(np.clip(int(radius), 8, 256))
    max_candidates = int(np.clip(int(max_candidates), 1, 16))

    # ⛔ Refusal is decided BEFORE any pixels are matched, and it is never cached (it is free).
    #    A refused TARGET is fatal. A refused ANCHOR is dropped, not fatal — see `_refusal`.
    refused = _refusal(store, target, refused_set, threshold)
    dropped = _blank_anchors(anchors, refused_set)
    if refused is None and dropped and not [a for a in anchors if a not in dropped]:
        refused = _no_anchors(dropped, "match")
    if refused is not None:
        return MatchResult(
            target=target, mode=mode, n_anchors=len(anchors),
            composite=None, candidates=[], best=None, margin=None, margin_thin=False,
            refused=refused, dropped_anchors=list(dropped), gpu=on_gpu(),
            elapsed_ms=(time.time() - t_start) * 1e3, cached=False,
            cache_key=cache_key(store.nonce, target, anchors, positions, mode, near, radius,
                                max_candidates, refused_set))

    # The EFFECTIVE anchor field: a refused frame contributes no pixels to any correlation. The memo
    # is keyed on THIS, not on what was asked for — two requests that reduce to the same composite
    # genuinely share an answer, and the A-branch prefetch stays correct by construction.
    anchors = [a for a in anchors if a not in dropped]
    positions = {k: v for k, v in positions.items() if int(k) not in dropped}

    key = cache_key(store.nonce, target, anchors, positions, mode, near, radius, max_candidates,
                    refused_set)

    # --- the memo + single-flight ---------------------------------------------------------------
    # A prefetch already in flight for THIS key is not recomputed by the foreground request that
    # follows it: the second caller waits on the event and takes the hit. A prefetch for a DIFFERENT
    # key (the user pressed `E`, not `A`) simply misses — which is the whole point.
    while True:
        with _MEMO_LOCK:
            if key in _MEMO:
                _MEMO.move_to_end(key)
                hit = _MEMO[key]
                return MatchResult(**{**vars(hit), "cached": True,
                                      "elapsed_ms": (time.time() - t_start) * 1e3})
            ev = _INFLIGHT.get(key)
            if ev is None:
                ev = threading.Event()
                _INFLIGHT[key] = ev
                break
        ev.wait(timeout=600)     # someone else is computing this exact request; loop back and read
        # their answer out of the memo.

    try:
        with _COMPUTE_LOCK:
            res = _match_compute(store, target, anchors, positions, mode, near,
                                 radius, max_candidates, key, t_start)
        res.dropped_anchors = list(dropped)
        with _MEMO_LOCK:
            _MEMO[key] = res
            _MEMO.move_to_end(key)
            while len(_MEMO) > MATCH_CACHE_SIZE:
                _MEMO.popitem(last=False)
        return res
    finally:
        with _MEMO_LOCK:
            _INFLIGHT.pop(key, None)
        ev.set()


def _match_compute(store, target, anchors, positions, mode, near, radius,
                   max_candidates, key, t_start) -> MatchResult:
    IMG, MSK, m0 = composite_of(store, anchors, positions)
    tile, TMSK = _tile_for_match(store, target)

    if mode == "global":
        cands = t33.match(IMG, MSK, tile, TMSK,
                          kpk=ANCHOR_KPK, minfrac=ANCHOR_MINFRAC, minabs=ANCHOR_MINABS)
    else:
        nx, ny = float(near[0]), float(near[1])
        cx = int(round(nx - float(m0[0])))
        cy = int(round(ny - float(m0[1])))
        cands = _local_search(IMG, MSK, tile, TMSK, cx, cy, radius, max_candidates)

    # `margin` is taken from the FULL ranked list, before truncation: best - second. (Identical to
    # candidates[0]-candidates[1] at the default `max_candidates`; strictly more honest if a caller
    # asks for only one.)
    margin = None
    if len(cands) >= 2:
        margin = float(cands[0][0]) - float(cands[1][0])

    # ⚠️ NOTE FOR THE UI, and do not "fix" it here. The tail of `t33.match`'s ranked list is its
    # tier-A candidates, which it appends WITHOUT re-scoring (t33.py:521) — they carry **npix = 0**,
    # which means **"not measured"**, NOT "no overlap". Only rank 0 (and the tier-B survivors) have a
    # real npix. We pass t33's numbers through UNTOUCHED: rescoring them would cost ~240 ms per Space
    # press and would shift `margin` away from t33's own definition of it. So: **do not render a
    # candidate's `npix == 0` as evidence of nothing.** Rank 0's npix is real; use that, plus
    # `composite.valid_px` and the margin.
    out: list[Candidate] = []
    for i, (ncc, dx, dy, npix) in enumerate(cands[:max_candidates]):
        x = float(m0[0]) + float(dx)                        # ⭐ world = m0 + (dx, dy)
        y = float(m0[1]) + float(dy)
        sub = False
        if i == 0:
            fx, fy = _subpixel(IMG, MSK, tile, TMSK, int(dx), int(dy))
            x = float(m0[0]) + fx
            y = float(m0[1]) + fy
            sub = True
        out.append(Candidate(rank=i, x=x, y=y, ncc=float(ncc), npix=int(npix), subpixel=sub))

    free_gpu()
    return MatchResult(
        target=target, mode=mode, n_anchors=len(anchors),
        composite={"w": int(IMG.shape[1]), "h": int(IMG.shape[0]),
                   "valid_px": int(MSK.sum()), "m0": [float(m0[0]), float(m0[1])]},
        candidates=out, best=out[0] if out else None,
        margin=margin,
        margin_thin=bool(margin is not None and margin < MARGIN_THIN),
        refused=None, gpu=on_gpu(),
        elapsed_ms=(time.time() - t_start) * 1e3, cached=False, cache_key=key)


def score_at(
    store: FrameStore,
    target: int,
    anchors: Sequence[int],
    positions: Mapping,
    at: Sequence[float],
    refuse: Iterable[int] | None = None,
    threshold: float | None = None,
) -> dict:
    """*"You dropped it HERE; here is what the pixels say."* One `t33.exact_ncc`, no search (~31 ms).

    -> `{"target", "at", "ncc", "npix", "refused", "dropped_anchors", "elapsed_ms"}`

    ⚠️ **`ncc` is `None` when the overlap is under `exact_ncc`'s floor** (< 3,000 valid px, or < 64 px
    on a side). The honest answer there is *"not measurable"* — **never `0.0`**. A blank target is
    refused here too; same rule, no exceptions.

    ⭐ **DELIBERATELY NOT UNDER `_COMPUTE_LOCK`.** It used to be, and that made the live-during-a-drag
    NCC readout wait out an entire `match_anchor`: measured **67 ms alone vs 439 ms** while a prefetch
    was in flight — and on the CPU-only default a prefetch is 1,562 ms, so the number under the user's
    cursor could be a **full match out of date while he is steering by it**. Nothing here contends with
    the matcher: `t33.composite` and `t33.exact_ncc` are pure host numpy (no CuPy pool, no GPU), and
    the ONE piece of shared mutable state — the incremental composite cache — is atomic in itself and
    never mutates an array it has already handed out.
    """
    t0 = time.time()
    target = int(target)
    anchors = sorted({int(a) for a in anchors})
    ax, ay = float(at[0]), float(at[1])
    refused_set = _refuse_set(refuse)

    if target not in store.row_of:
        raise KeyError(f"trial {target} is not in this session")

    refused = _refusal(store, target, refused_set, threshold)   # the TARGET only — see `_refusal`
    dropped = _blank_anchors(anchors, refused_set)
    anchors = [a for a in anchors if a not in dropped]          # blanks contribute no pixels, ever
    positions = {k: v for k, v in positions.items() if int(k) not in dropped}
    if refused is None and dropped and not anchors:
        refused = _no_anchors(dropped, "score")
    if refused is not None:
        return {"target": target, "at": [ax, ay], "ncc": None, "npix": 0,
                "refused": refused, "dropped_anchors": list(dropped),
                "elapsed_ms": round((time.time() - t0) * 1e3, 1)}
    if not anchors:
        raise ValueError("score_at needs at least one anchor")
    for a in anchors:
        if a not in store.row_of:
            raise KeyError(f"anchor trial {a} is not in this session")

    IMG, MSK, m0 = composite_of(store, anchors, positions)
    tile, TMSK = _tile_for_match(store, target)
    dx = int(round(ax - float(m0[0])))                          # exact_ncc takes INTEGER offsets
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


# =================================================================================================
# THE BUILD — a long-running job, in a CHILD PROCESS
# =================================================================================================
class _ProgressSink:
    """🔴 **THE STDOUT SCRAPER.** `t33` has **no progress callback of any kind** — its only signal is
    `print` behind `cfg.verbose`. So we run it under `redirect_stdout` and scrape its narration.

    Do **not** invent your own line rules, and do **not** "smooth" the warm-cache case where the job
    legitimately jumps straight to `runs`.
    """

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

    # 🔴 INTRA-PHASE PROGRESS FOR `pass1` AND `backbone` — **75 % of a CPU build**, and it used to show
    # the user EXACTLY TWO STATIC NUMBERS. Neither phase emitted a `frac`, so `pct` was pinned and
    # `eta_s` was `None` (an ETA needs pct > 2). Measured on the CPU-only path — the SHIPPED DEFAULT
    # install — the bar sat at **0.0 %, with no ETA, for 3 min 40 s**, under the constant message
    # "pass 1 (t27, frozen reference)", with a Cancel button helpfully to hand. Then it jumped to
    # 20.0 % and sat there for **another 3 min 40 s**. A lab-mate who cancels that has cancelled a
    # build that would have produced 312/312.
    #
    # t33 runs t27 inside itself and its `_hush` lets t27's own narration through at verbose=True, so
    # there IS a signal — it was simply never scraped. These are t27's markers, in the order it emits
    # them, mapped to a fraction of the enclosing phase. The fractions are **ordinal, not linear in
    # time** (the true split is unmeasured and differs GPU vs CPU) — but a bar that MOVES and a message
    # that CHANGES is the difference between "it is working" and "it has hung", and that is the failure
    # being fixed. `_enter`'s never-go-backwards guard still protects the phase itself.
    #
    # ⚠️ t27's own "STEP 1/2/3/4" headers say PRE-CHECK / EXHAUSTIVE / COLUMN-IDENTITY / WEIGHTED —
    # they cannot collide with t33's "STEP 1 — PASS 1" / "STEP 2 — PASS 2 backbone" above, which is why
    # these regexes are anchored on the WORDS, not the numbers.
    SUBSTEPS = (
        (re.compile(r"\[data\] .* snapshots, trials"),          0.02, "loading the band-passed stack"),
        (re.compile(r"\[data\] band-passed"),                   0.05, "band-passed (DoG 3-30)"),
        (re.compile(r"\[swim\] .*pairs in |\[swim\] loaded"),   0.55, "all-to-all SWIM shifts done"),
        (re.compile(r"\[validate\] batched NCC"),               0.60, "NCC bank validated"),
        (re.compile(r"\[dealias\]"),                            0.65, "de-aliased the pair shifts"),
        (re.compile(r"STEP 1\s*[—\-]\s*PRE-CHECK"),             0.68, "pre-check: is a step an axis move?"),
        (re.compile(r"STEP 2\s*[—\-]\s*EXHAUSTIVE"),            0.72, "exhaustive axis-manifold search"),
        (re.compile(r"backbone after correction"),              0.84, "backbone corrected"),
        (re.compile(r"\[null\] matched permutation null"),      0.88, "permutation null measured"),
        (re.compile(r"STEP 3\s*[—\-]\s*COLUMN-IDENTITY"),       0.90, "column-identity gate"),
        (re.compile(r"STEP 4\s*[—\-]\s*WEIGHTED"),              0.93, "weighted least-squares solve"),
        (re.compile(r"\[solve\] IRLS kept"),                    0.97, "IRLS converged"),
    )

    def __init__(self, queue, t0: float, n_total: int, weights: dict | None = None):
        self.q = queue
        self.t0 = t0
        self.n_total = int(n_total)
        self.buf = ""
        self.phase = "pass1"
        self.frac = 0.0
        self.n_runs = 0
        self.runs_seen: set[int] = set()
        self.w = dict(weights or PHASE_WEIGHT_GPU)

    # --- the file protocol ----------------------------------------------------------------------
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
        """**A phase may never go BACKWARDS.**

        🔴 WHY THIS GUARD EXISTS, and it is not paranoia: **t33 runs t27 INSIDE itself**, and with
        `verbose=True` t33's `_hush` lets t27's own narration through to the same stdout. t27 prints
        its OWN `[done] placed 156 snapshots` when it finishes pass 1 — **a third of the way into the
        build**. Scraped naively, that line sends the progress bar to **100 %** and then back to 20 %.
        (Measured: it did exactly that on the first cold run.) `[done]` is therefore gated on the tile
        count matching the WHOLE build (see `RE_DONE` below), and this guard is the backstop for any
        other line the inner t27 may ever emit that looks like an outer phase.
        """
        try:
            if PHASES.index(phase) < PHASES.index(self.phase):
                return False
        except ValueError:
            pass                                    # "done" is not in PHASES; it always wins
        self.phase, self.frac = phase, frac
        return True

    # --- the scraper ----------------------------------------------------------------------------
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
            # ⚠️ ONLY the outer t33 `[done]` — t27's inner one (pass 1 alone) reports a SMALLER count,
            # and mistaking it for the end is the bug this whole guard exists for.
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
            # ⭐ t27's own narration, inside t33's pass-1 / backbone phases. Monotone WITHIN the phase
            #   — a later t27 line can never pull the bar back (`backbone` re-runs the same markers,
            #   but `_enter` has already moved the phase on, and `frac` is reset to 0 there).
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
                # ⚠️ t33 prints its MARGIN TABLE after the run loop, and those rows look exactly like
                # run rows. A SET (not a counter) is what keeps that from double-counting, and
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
        """-> `(frac, note)` for a t27 narration line inside pass1/backbone, else `None`."""
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
        # ⏱️ A global linear extrapolation. It MAY JUMP UP, and that is an honest revision — the front
        # end anchors a 1 Hz local countdown on it and re-anchors only when this raw number CHANGES.
        # ⛔ There is deliberately no server-side ETA heartbeat: `pct` is pinned during a silent phase,
        # so re-emitting with a growing `elapsed` would make the ETA count *up*. (`core.jobs`.)
        eta = (el * (100.0 - pct) / pct) if pct > 2.0 and pct < 100.0 else None
        return {"type": "progress", "phase": self.phase,
                "phase_index": PHASE_INDEX.get(self.phase, 0), "n_phases": N_PHASES,
                "pct": round(pct, 1), "message": message,
                "eta_s": None if eta is None else round(eta, 0)}


def make_config(config: Mapping | None, pass_split: int | None = None):
    """`dict` -> `t33.Config`. **An unknown knob raises `TypeError`** (t33 does it itself, in its own
    `__init__`) -> the API turns that into a 400. ⛔ Do not hard-code the knob list anywhere.

    ⚠️⚠️ **`cfg.pass_split` MUST BE THE DETECTED SPLIT.** `t33.Config`'s default is **166**, which is
    *260620d's* number — it is exactly the dataset knowledge the app is forbidden to carry. So the
    caller supplies it, always, and this refuses to build a config without one. (An explicit
    `config["pass_split"]` from the Advanced drawer wins: the detection is a *default*, and it is
    always overridable.)
    """
    cfg_d = dict(config or {})
    if pass_split is not None:
        cfg_d.setdefault("pass_split", int(pass_split))
    if cfg_d.get("pass_split") is None:
        raise ValueError(
            "the pass split must be supplied by the caller: t33.Config's default of 166 is one "
            "acquisition's measured number, and the app carries no dataset knowledge. Pass the "
            "session's DETECTED split (legacy/mosaic/run.py)."
        )
    t27_d = cfg_d.pop("t27", None)
    if t27_d is None:
        cfg = t33.Config(**cfg_d)                    # t33's default: t27.Config(control=False)
    else:
        cfg = t33.Config(t27=t27.Config(**dict(t27_d)), **cfg_d)
    return cfg


def build_result(pos: Mapping, info: Mapping, trials: Sequence[int], pass_split: int,
                 anchors: Mapping | None = None, dataset: str = "dataset",
                 build_id: str | None = None, created: str | None = None) -> dict:
    """t33's `(pos, info)` -> the `BuildResult` body (`api.schemas.BuildResult`).

    `per_tile` is a **"go look here first" list, NOT a verdict.** What is honest and what is not:

      ✅ `anchor_ncc` — **PASS 2 ONLY.** The best signal there is (156/156 >= 0.30, median 0.815).
      ⚠️ `anchor_residual_px` = `|(anc[q] + M1) - pos[t]|` — probably THE number to sort a worklist on
         (it caught trial 311 at **2,706 px** while its run agreed to 4.4 px) — but it has fired
         exactly ONCE, its false-positive rate is unmeasured, and t33's own design treats a lone
         disagreeing anchor as an outlier TO DISCARD. Present as "go look", never as a verdict.
      ⚠️ `run_margin` — good, but the shipped build's minimum is 0.081 against a ~0.47 typical.
      🔴 **PASS-1 TILES HAVE NO PER-TILE CONFIDENCE AT ALL** (t27's `info` is aggregate-only) — and the
         **worst tile in the shipped 312/312 build (trial 127, at 9.94 px) is a PASS-1 tile.** The UI
         must say so, loudly: **the absence of a warning here is NOT a clean bill of health.**
      ⛔ NOT built on `quality.score_positions`: on the ground-truth-PERFECT 312/312 build it flags 11
         tiles and **all 11 are false positives (precision 0/11)**.
      ⛔ `quality.score_build()` / `quality.leaderboard()` are **DEAD**. They raise. Never call them.
    """
    anchors = dict(anchors or {})
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
        # ⭐ **THE DISCRIMINATOR TAG, AND IT IS NOT DECORATION.** `api.schemas.JobResult` is a
        # `Field(discriminator="kind")` union over `OpenJobResult | BuildResult | ExportResult |
        # RecheckResult`, so `GET /api/jobs/{id}` cannot serialise a `Job.result` that does not carry
        # one: pydantic raises `union_tag_not_found` and the poll 500s. Measured: the build itself
        # succeeded (12/12 tiles, 8.0 s, GPU) and then **every single poll of it returned a 500** — a
        # green build the client could never read. The other three producers already emit it
        # (`export_all` -> "export", `routes.post_recheck` -> "recheck", the core open job ->
        # "open"); this one did not. A new job kind must add it here, and to the union.
        "kind": "build",
        "build_id": build_id or f"{dataset}__t33__{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}",
        "created": now,
        # ⭐ **WHAT THE SOLVER WAS ACTUALLY GIVEN.** Without these two the document can never know its
        # build was solved on a DIFFERENT input than the one it now holds, and the staleness check
        # degenerates into comparing the current trial list with itself and never firing. Excluding a
        # mid-run tile opens a GAP, and across a gap the serpentine one-axis step prior does NOT
        # hold — the positions either side of it were solved *through* it.
        "trials": [int(t) for t in trials],
        "gaps": [[int(a), int(b)] for a, b in gaps(trials)],
        "pass_split": int(pass_split),
        "positions": {str(int(t)): [float(p[0]), float(p[1])] for t, p in posn.items()},
        "n_placed": len(posn),
        "unplaced": [t for t in trials if t not in posn],
        "info": _config_effective(jsonable(info), info),   # <- info["config"] would CRASH json.dumps
        "seconds": float(info.get("seconds", 0.0)),
        "gpu": bool(info.get("gpu", False)),
        "per_tile": per_tile,
    }


def _config_effective(safe: dict, info: Mapping) -> dict:
    """Record the config t33 **actually ran**, not the sentinel it was handed.

    ⚠️ `t33.Config.t27` defaults to **`None`**, meaning "use `t27.Config(control=False)`" — it is
    resolved lazily inside `t33.place` via `cfg.t27_config()`. So a faithful `vars()` dump writes
    `"t27": null` into the build record, and from there into the DOCUMENT's provenance and the QC
    report. That is a provenance hole: `null` does not tell a later reader which t27 knobs (`conf`,
    `run_conf`, …) produced these positions, and those knobs are exactly what a reproduction attempt
    needs.

    ⚠️ **A WARM CACHE HIT HANDS BACK A PLAIN DICT, NOT A `t33.Config`** — `t33._load_checked` rebuilds
    `info` from the cache file. Keying this fix on `hasattr(cfg, "t27_config")` therefore made it work
    ONLY on a cold build and silently no-op on every cached one, **which is the common case**, and the
    one whose provenance was landing in the project file with `"t27": null`.

    Purely additive: it reads t33/t27, mutates nothing inside them, and cannot affect the guard.
    """
    cfg = info.get("config")
    if cfg is None or not isinstance(safe.get("config"), dict):
        return safe
    if safe["config"].get("t27") is None:
        try:
            eff = cfg.t27_config() if hasattr(cfg, "t27_config") else t27.Config(control=False)
            if eff is not None:
                safe["config"]["t27"] = jsonable(eff)
                safe["config"]["t27_source"] = (
                    "t33 default (cfg.t27 was None -> t27.Config(control=False))")
        except Exception:  # noqa: BLE001 — never lose a build over provenance
            pass
    return safe


def build_worker(data_dir: str, trials: Sequence[int], pass_split: int,
                 config: Mapping | None = None, cache_dir: str | None = None,
                 queue=None, memo: bool = True) -> None:
    """⭐ **THE BUILD, IN A SPAWNED CHILD PROCESS.** `core.jobs.submit_process` targets this by dotted
    path — `BUILD_TARGET` — and calls it with `queue=<mp.Queue>` plus these kwargs.

    **WHY A CHILD PROCESS:** `t33.place` **cannot be interrupted.** It runs 25 s – 10 min
    synchronously, has no callback and no flag to check. **Cancel is `proc.terminate()`. There is no
    other way.** (`core.jobs`.)

    THE QUEUE PROTOCOL (`core.jobs.JobRegistry._apply` drains it on a reader thread). Every message is
    a plain dict, and everything on it is **already JSON-safe** (`info` has been through `jsonable`)::

        {"type": "progress", "phase", "phase_index", "n_phases", "pct", "message", "eta_s"}
        {"type": "log",      "line": "<one raw t33 stdout line>"}      # the last 200 are kept
        {"type": "done",     "result": {...}}                          # == api.schemas.BuildResult
        {"type": "error",    "error": {"code", "message", "traceback"}}

    `trials` is **the DOCUMENT's active list** — everything the human has not excluded. That is the
    only way a frame ever leaves a build. (Hard-wiring the session's run list here meant pressing `E`
    and then "re-solve" re-solved the *identical* problem and put the excluded frame straight back
    into the chain.)

    `memo=False` is the **A/B escape hatch** for verifying that the `t33._pool` memo really is
    bit-identical. It is not a UI switch.

    Runtime: GPU cold ~180-200 s (the per-tile anchor loop is ~150 s of it); GPU warm ~25 s; CPU-only
    ~8-10 min. All three ship; the UI must say which one it is doing, and why.
    """
    t0 = time.time()
    try:
        trials = [int(t) for t in trials]
        queue.put({"type": "progress", "phase": "pass1", "phase_index": 1, "n_phases": N_PHASES,
                   "pct": 0.0, "message": f"loading {len(trials)} frames", "eta_s": None})

        # ⭐ THE ONE READER. It flips CONDITIONALLY, on this acquisition's XML. There is no fallback
        # and there must not be one: a child that solved on 180-degree-rotated frames while the UI
        # used un-rotated ones would put every tile 180 degrees out — and every tile would still have
        # looked plausible. (0.12 s for 312 frames. Do NOT build a shared-memory apparatus for that.)
        frames = load_frames(Path(data_dir), trials)

        cfg = make_config(config, pass_split=pass_split)
        cfg.verbose = True                                   # the ONLY progress signal there is

        # ⭐ WHICH CURVE IS THIS BUILD ON? The phase weighting is a completely different *shape* on the
        # CPU (pass 1 + backbone = 75 % of the build) than on the GPU (the anchor loop = 53 %), and
        # guessing wrong makes the ETA a lie by >2x for the whole first half. `on_gpu()` goes through
        # `t27.xp()`, which EXECUTES A REAL OP — `import cupy` succeeds on a broken CUDA install, so
        # nothing less will do. It also warms the child's own CUDA context before the clock matters.
        gpu = on_gpu()
        queue.put({"type": "log",
                   "line": f"[camea] build device: {'GPU (CuPy)' if gpu else 'CPU (numpy)'}"})

        sink = _ProgressSink(queue, t0, len(trials),
                             weights=PHASE_WEIGHT_GPU if gpu else PHASE_WEIGHT_CPU)

        # `build_memo` is a CONTEXT MANAGER, not v1's enable/disable pair: it restores the real
        # `t33._pool` in a `finally:`, so the patch cannot leak out of this child and be live when the
        # 312/312 guard runs. (The guard asserts `t33._pool.__module__ == t33.__name__` anyway.)
        with contextlib.ExitStack() as stack:
            if memo:
                stack.enter_context(build_memo())
            stack.enter_context(contextlib.redirect_stdout(sink))
            pos, info = t33.place(trials, frames, cfg=cfg, cache=cache_dir)

        anchors = read_anchors(cache_dir, trials, cfg)       # `{}` when cache_dir is None. Never wrong.
        result = build_result(pos, info, trials, cfg.pass_split, anchors=anchors,
                              dataset=Path(data_dir).name)
        queue.put({"type": "progress", "phase": "done", "phase_index": N_PHASES,
                   "n_phases": N_PHASES, "pct": 100.0,
                   "message": f"placed {result['n_placed']}/{len(trials)} tiles", "eta_s": 0.0})
        queue.put({"type": "done", "result": result})
    except Exception as e:  # noqa: BLE001 — a crash in the child must still reach the user
        queue.put({"type": "error", "error": {
            "code": "job_failed", "message": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc()}})
    finally:
        try:
            queue.close()
            queue.join_thread()
        except Exception:  # noqa: BLE001
            pass
