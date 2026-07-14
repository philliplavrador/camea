"""frames.py — THE PIXELS: reading them, correcting them, windowing them, showing them.

Ported from `archive/app-v1/backend/loader.py` (READ-ONLY reference). This is **CORE**, so it is
**feature-agnostic**: nothing in this file knows what a *tile*, an *anchor*, a *pass split* or a
*mosaic* is.

⛔ **THERE IS NO 512 IN THIS FILE.** A `FrameStore` holds frames of whatever shape the XML says.
512 is `t33.TILE`, and the 512x512 gate is the MOSAIC feature's policy — `features/mosaic/run.py`.
Core reports the shape; it does not gate on one. (`docs/SPLIT.md` §1.1.)

⛔⛔ **THE APP CARRIES NO KNOWLEDGE OF ANY DATASET.** No trial number is special here. No exclusion
list, no `BLANK_THRESHOLD` fallback, no auto-reject. This module loads exactly what it is asked for.
The only things that may ever exclude a frame are (a) the human, in this session, and (b) a project
file he loaded — and neither of those lives here. (`docs/SPLIT.md` §0.1; CLAUDE.md.)

WHAT LIVES HERE
---------------
* the **reader** (`load_frame` / `load_frames`) — ⭐⭐ the conditional 180-degree flip,
* the **flat-field** (`compute_flat` / `flat_correct`),
* the **GLOBAL tone window** (`Tone` / `compute_tone` / `to_u8`) — ⚠️⚠️ never per-tile,
* the **display path** (`tile_png` / `tile_raw` / `thumb_sheet`),
* the **band-pass** — *imported*, never re-derived (see below),
* the **texture measure** (`texture_map`) — a per-frame number, therefore core,
* and `FrameStore`, which owns the pixels, the derived band stack and **the one display cache**.

WHAT DELIBERATELY DOES **NOT** LIVE HERE
---------------------------------------
`blank_scan` (the THRESHOLD and the PROPOSAL) is mosaic's: its threshold is defined in mosaic's own
terms — *the 2nd percentile of **pass-1** texture* — and `pass 1` only exists because `pass_split`
does. Core owns the MEASUREMENT (`texture_map`); the feature owns the POLICY; the human owns the
DECISION, and it lands in the document. (`docs/SPLIT.md` §5.)

🔴 THE ONE BAND-PASS
--------------------
`camea.engine.quality.band_pass` **IS** the band-pass, and there is no other. It is what
`t27.band_pass` delegates to, so it is under the **312/312 regression guard**: every number in this
project — every SWIM offset, every NCC, every texture value, all three ground truths — is measured
on *that* function's output.

v1 carried a **second** implementation (`loader.py:639`) whose own docstring claimed it was
"verified bit-identical" — a claim nothing in the repo tested. Two forks of the DoG that everything
is matched on, with nothing asserting they agree. So: this module **imports** the survivor. It does
not wrap it, re-derive it, or re-tune it, and `tests/unit/test_band_pass_is_singular.py` fails the
build if a second Gaussian DoG ever appears anywhere under `src/camea`.

⚠️ **KEEP OPENCV.** Swapping the DoG to `scipy.ndimage.gaussian_filter` shifts the blank metric by
**0.32 %** against a threshold whose nearest margin is **0.13 %** — it can flip a blank
classification. Saving installer megabytes is not worth a wrong answer. (`pyproject.toml`.)
"""

from __future__ import annotations

import math
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

# ⭐ THE band-pass. DoG(sigma=3, sigma=30), under the 312/312 guard via `t27.band_pass`.
# Imported, never re-derived. Never inline the two cv2 calls anywhere else — that is how the fork
# came back last time. Its sigmas are *its own defaults*; this module does not mirror them, because
# a mirrored constant is a constant that can drift.
from camea.engine.quality import band_pass

__all__ = [
    "FLAT_SIGMA",
    "TONE_PCT_LO",
    "TONE_PCT_HI",
    "TONE_N_SAMPLE",
    "TEXTURE_MEASURE",
    "MixedShapeError",
    "Tone",
    "band_pass",
    "band_pass_one",
    "load_frame",
    "load_frames",
    "compute_flat",
    "flat_correct",
    "compute_tone",
    "to_u8",
    "png_bytes",
    "tile_png",
    "tile_raw",
    "thumb_sheet",
    "tone_lohi",
    "texture_map",
    "shape_groups",
    "FrameStore",
]

# --- constants. Each lives with the ONE module that owns it; nothing re-exports. ---------------
FLAT_SIGMA = 15.0  # the vignette's Gaussian sigma
TONE_PCT_LO, TONE_PCT_HI = 0.5, 99.6  # the global window's percentiles
TONE_N_SAMPLE = 96  # frames sampled, evenly, to estimate it

#: The wire name of the measure `texture_map` returns. It says "as read", not "of the flipped
#: frame", because the reader flips **conditionally** — see `FrameStore.frame_note`.
TEXTURE_MEASURE = "std of DoG(sigma=3, sigma=30) of the frame as read"

# ⛔ NOT HERE, AND NOT ANYWHERE:
#   TILE = 512            -> mosaic. Core holds frames of whatever shape the XML says.
#   DOG_LO, DOG_HI = 3,30 -> deleted. They are `quality.band_pass`'s own defaults.
#   BLANK_PCT = 2.0       -> mosaic (the threshold POLICY).
#   BLANK_THRESHOLD       -> DELETED. 60.11 is *one dataset's measured number*, and it sat in the
#                            app as a "fallback". That is dataset knowledge. The threshold is
#                            computed from the frames in front of it, every time, or not at all.


class MixedShapeError(ValueError):
    """The requested trials are not all one shape, and core **refuses to guess** which you meant.

    ⚠️ **SHAPE IS PER-TRIAL, NOT PER-DIRECTORY.** (Sibling directory `260620` has trial 021 as a
    genuine `type="snapshot" frames="1"` at parpix=128 — 512x128, 131,072 bytes. It is real data.)
    Inferring a shape from a file size, or reshaping 131,072 bytes into a 512x512 lie, is how a
    plausible-looking wrong answer gets made. Fail loudly instead; the caller picks a shape.

    `groups` is `[{"w", "h", "n", "trials"}, ...]` — the API turns it into a `409 mixed_shape`.
    """

    def __init__(self, groups: list[dict[str, Any]]) -> None:
        shown = ", ".join(f"{g['w']}x{g['h']} (n={g['n']})" for g in groups)
        super().__init__(f"the requested trials are not all one shape: {shown}")
        self.groups = groups


def band_pass_one(frame: np.ndarray) -> np.ndarray:
    """One 2-D frame -> its DoG.

    ⭐ Bit-identical to the stack path **by construction, not by assertion**: it *is* `band_pass`,
    on a 1-frame stack, so it runs exactly the same two `cv2.GaussianBlur` calls on exactly the
    same 2-D array. **Do not inline the two cv2 calls here.** (v1's second implementation existed
    only because `quality.band_pass`'s list-comp iterates the first axis, so a bare 2-D input would
    iterate *rows*. `frame[None]` costs nothing and removes the reason for a fork.)
    """
    f = np.asarray(frame, np.float32)
    if f.ndim != 2:
        raise ValueError(f"band_pass_one expects one 2-D frame, got shape {f.shape}")
    return band_pass(f[None])[0]


# =============================================================================
# The reader
# =============================================================================
def load_frame(meta: Mapping[str, Any]) -> np.ndarray:
    """One raw `.dat` -> float32 (h, w) in vscope's DISPLAY orientation. **THE reader.**

    ⭐⭐ **THE 180-DEGREE FLIP IS LOAD-BEARING, AND IT IS VERIFIED.** `np.flip(np.flip(raw, 1), 0)`
    is byte-identical both to `analysis/texture/make_texture.py` and to vscope itself
    (`vscope.load(xml).ccd["Cc"][0]`), on trials 11, 12, 166, 167, 347. It is a true 180 rotation
    (`out[0,0] == raw[-1,-1]`), not a transpose, and it is **not a no-op** — an unflipped read
    returns different pixels **and would have looked perfectly plausible**. Every existing position,
    every SWIM dx/dy and all three ground truths live in this frame. Do not "simplify" it.
    (`tests/slow/test_reader_matches_vscope.py` pins it against vscope.)

    ⚠️ It flips **CONDITIONALLY**, on the XML's `ax`/`ay`. It honours the file; it does not assert a
    flip. Nothing anywhere may hard-code "180-degree-flipped" — see `FrameStore.frame_note`, which
    is what the TIFF header and the document's `coordinates` note are built from.
    """
    if meta["dtype"] != "uint16" or meta["bytes"] != 2:
        raise ValueError(
            f"trial {meta['trial']}: unsupported pixel type "
            f"{meta['dtype']}/{meta['bytes']}B (only little-endian uint16 is read)"
        )
    raw = np.fromfile(meta["dat"], dtype="<u2")
    want = int(meta["h"]) * int(meta["w"])
    if raw.size != want:
        name = Path(meta["dat"]).name
        raise ValueError(
            f"trial {meta['trial']}: {name} has {raw.size} px, "
            f"XML says {meta['h']}x{meta['w']} = {want}"
        )
    raw = raw.reshape(int(meta["h"]), int(meta["w"]))
    if meta["flip_x"]:
        raw = np.flip(raw, 1)
    if meta["flip_y"]:
        raw = np.flip(raw, 0)
    return np.ascontiguousarray(raw, dtype=np.float32)


def shape_groups(snaps: Mapping[int, Mapping[str, Any]], trials: list[int]) -> list[dict[str, Any]]:
    """`trials` grouped by frame shape, biggest group first. The evidence in a `MixedShapeError`."""
    by: dict[tuple[int, int], list[int]] = {}
    for t in trials:
        m = snaps.get(t)
        if m is None:
            continue
        by.setdefault((int(m["w"]), int(m["h"])), []).append(t)
    groups = [{"w": w, "h": h, "n": len(ts), "trials": ts} for (w, h), ts in by.items()]
    groups.sort(key=lambda g: (-g["n"], g["w"], g["h"]))
    return groups


def load_frames(
    data_dir: Path | str | None,
    trials: list[int],
    snaps: Mapping[int, Mapping[str, Any]] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> np.ndarray:
    """The stack: float32 `(N, h, w)`, flipped per the XML, **raw camera counts**. Row `i` IS
    `trials[i]`.

    ⭐ **ONE READER.** v1's build child carried its own inline shim that flipped
    **unconditionally**, while this reader flips **conditionally on the XML** — so the solver would
    have run on 180-degree-rotated frames while the UI used un-rotated ones, and **every tile would
    still have looked plausible**. There is no fallback path and there must not be one.

    **338 frames in ~0.13 s** (0.37 ms/frame, warm OS cache). Loading is not the bottleneck.
    ⛔ **AND IT IS NOT CACHED TO DISK.** (Emphatically not `analysis/mosaic/io.load_frames`'s cache:
    that validates only `shape[0] == len(trials)`, so two *different* selections of the same size
    silently share an entry.)

    RAM: one 512x512 float32 frame = exactly 1.00 MiB, so 338 = **338 MiB**. Peak is 2-3x — the band
    stack is a full second copy. Budget ~1 GB host RAM.

    It loads exactly what it is asked for. There is no exclusion list here and nothing to refuse.
    Raises `MixedShapeError` if the selection spans more than one shape.
    """
    if snaps is None:
        if data_dir is None:
            raise ValueError("load_frames: give it either a data_dir or a snapshot inventory")
        snaps = _list_snapshots(Path(data_dir))

    missing = [t for t in trials if t not in snaps]
    if missing:
        where = f" in {data_dir}" if data_dir is not None else ""
        raise ValueError(f"not snapshots{where}: {missing[:10]}")

    if not trials:
        raise ValueError("load_frames: no trials")

    groups = shape_groups(snaps, trials)
    if len(groups) > 1:
        # ⚠️ Do NOT pick the majority shape. A frame store holds one shape; which one is the
        # caller's decision, and it is a decision core is not entitled to make for it.
        raise MixedShapeError(groups)

    w, h = int(groups[0]["w"]), int(groups[0]["h"])
    out = np.empty((len(trials), h, w), np.float32)
    for i, t in enumerate(trials):
        out[i] = load_frame(snaps[t])
        if progress and (i % 32 == 0):
            progress(i, len(trials))
    return out


def _list_snapshots(data_dir: Path) -> dict[int, dict[str, Any]]:
    """The disk inventory lives in `core.dataset` (it is log/XML grammar, not pixels). Imported
    lazily so this module has no import-time dependency on it."""
    from camea.core.dataset import list_snapshots

    return list_snapshots(data_dir)


# =============================================================================
# Flat-field + THE GLOBAL TONE WINDOW
# =============================================================================
@dataclass
class Tone:
    """The **GLOBAL** display window.

    ⚠️⚠️ **GLOBAL, NEVER PER-TILE.** A per-tile percentile stretch over-brightens near-empty frames
    and makes overlapping tiles disagree in brightness — **which destroys the Difference-mode check
    the entire verification loop depends on.** There is no per-tile path in this module and there
    must never be one, not even for a thumbnail.

    Tone is **display only**. It never touches the matcher (which sees band-passed, mean-subtracted
    pixels) and it never touches the exported TIFF.

    `version` bumps on every change. It is **half** of the front end's `?v=` cache-buster — the
    other half is `FrameStore.nonce`, because `version` is a dataclass default and resets to 1 on
    every open while the pixels behind an `immutable, max-age=1yr` URL change.
    """

    lo: float
    hi: float
    level: float
    flat_sigma: float = FLAT_SIGMA
    pct_lo: float = TONE_PCT_LO
    pct_hi: float = TONE_PCT_HI
    n_sample: int = TONE_N_SAMPLE
    auto: bool = True
    version: int = 1

    def to_json(self) -> dict[str, Any]:
        return {
            "lo": round(float(self.lo), 2),
            "hi": round(float(self.hi), 2),
            "level": round(float(self.level), 2),
            "flat_sigma": float(self.flat_sigma),
            "pct_lo": float(self.pct_lo),
            "pct_hi": float(self.pct_hi),
            "n_sample": int(self.n_sample),
            "auto": bool(self.auto),
            "version": int(self.version),
        }


def tone_lohi(tone: Tone | Mapping[str, Any] | None) -> tuple[float, float] | None:
    """`(lo, hi)` from a `Tone` **or** a plain dict (a document's `tone` block is a dict). `None` if
    there is no usable window. (`archive/app-v1/backend/export.py:107`.)"""
    if tone is None:
        return None
    if isinstance(tone, Mapping):
        lo, hi = tone.get("lo"), tone.get("hi")
    else:
        lo, hi = getattr(tone, "lo", None), getattr(tone, "hi", None)
    if lo is None or hi is None:
        return None
    lo, hi = float(lo), float(hi)
    if not math.isfinite(lo) or not math.isfinite(hi) or hi <= lo:
        return None
    return lo, hi


def compute_flat(frames: np.ndarray, sigma: float = FLAT_SIGMA) -> np.ndarray:
    """The vignette: normalised `Gaussian(sigma=15)` of the per-pixel median. Mean 1 by
    construction.

    (This `GaussianBlur` is a **vignette**, not a DoG. It is a single blur at sigma=15 and it is not
    subtracted from anything — see the band-pass note in the module docstring.)
    """
    flat = np.median(np.asarray(frames, np.float32), axis=0)
    flat = cv2.GaussianBlur(flat, (0, 0), float(sigma))
    return (flat / float(flat.mean())).astype(np.float32)


def flat_correct(frame: np.ndarray, flat_n: np.ndarray, level: float) -> np.ndarray:
    """`frame / flat_n`, renormalised to the common `level`.

    ⚠️ Note the **per-frame gain**, `level / median(frame)`. It is right for a *picture* and wrong
    for a *measurement*: it rescales each frame's counts. The TIFF export therefore has a `flat`
    flag, and `flat=False` (raw camera counts) is what its header promises. Rendering the TIFF with
    `flat=True` once took trial 11's median from 2111 to 3435 (x1.63) under a header saying RAW.
    """
    c = np.asarray(frame, np.float32) / np.maximum(flat_n, 1e-3)
    return c * (level / max(float(np.median(c)), 1e-3))


def compute_tone(frames: np.ndarray) -> tuple[Tone, np.ndarray]:
    """-> `(Tone, flat_n)`. Samples <= 96 frames **evenly** across the stack, estimates the vignette,
    and computes **ONE window for the whole dataset**::

        flat_n = normalise(GaussianBlur(median(sample, axis=0), sigma=15))   # mean 1
        level  = median of the per-frame medians      (exposure varies ~2.4x across a run)
        lo, hi = percentile(flat_corrected_sample, [0.5, 99.6])

    ⚠️⚠️ **GLOBALLY, NEVER PER-TILE.** See `Tone`.
    """
    n = len(frames)
    if n == 0:
        raise ValueError("compute_tone: no frames")
    step = max(1, n // TONE_N_SAMPLE)
    idx = list(range(0, n, step))[:TONE_N_SAMPLE]

    sample = np.asarray(frames, np.float32)[idx]
    flat_n = compute_flat(sample)
    level = float(np.median([np.median(f) for f in sample]))
    corrected = np.stack([flat_correct(f, flat_n, level) for f in sample])
    lo, hi = (float(v) for v in np.percentile(corrected, [TONE_PCT_LO, TONE_PCT_HI]))
    del corrected
    if not math.isfinite(lo) or not math.isfinite(hi) or hi <= lo:
        raise ValueError(f"degenerate tone window [{lo}, {hi}]")
    return Tone(lo=lo, hi=hi, level=level, n_sample=len(idx)), flat_n


# =============================================================================
# The display path
# =============================================================================
def to_u8(frame: np.ndarray, flat_n: np.ndarray, tone: Tone) -> np.ndarray:
    """Flat-field + the GLOBAL window -> uint8 (h, w).

    **Every displayed pixel goes through this** — the tile PNGs, the thumbnails and the exported
    display PNG. ONE window for all of them.
    """
    c = flat_correct(frame, flat_n, tone.level)
    return np.clip((c - tone.lo) * (255.0 / (tone.hi - tone.lo)), 0, 255).astype(np.uint8)


def png_bytes(u8: np.ndarray) -> bytes:
    buf = BytesIO()
    Image.fromarray(np.ascontiguousarray(u8), "L").save(
        buf, "PNG", optimize=False, compress_level=1
    )
    return buf.getvalue()


def tile_png(frame: np.ndarray, flat_n: np.ndarray, tone: Tone) -> bytes:
    """-> 8-bit grayscale PNG bytes."""
    return png_bytes(to_u8(frame, flat_n, tone))


def tile_raw(frame: np.ndarray) -> bytes:
    """-> uint16 **little-endian**, row-major, **ALREADY FLIPPED**, **RAW camera counts** (no
    flat-field, no tone). This is the 16-bit pixel data, not a picture.

    Frames are stored float32 but hold integral counts, so the round-trip is exact. Only ~1/20 of
    the uint16 range is used (global max across all 338 snapshots of 260620d = 18,022 / 65,535) and
    the saturated fraction is exactly 0.0 in every frame — the clip here can never bite.
    """
    return np.ascontiguousarray(np.clip(frame, 0, 65535).astype("<u2")).tobytes()


def _sheet(u8_stack: np.ndarray, cell: int) -> tuple[bytes, int]:
    n = len(u8_stack)
    grid = int(math.ceil(math.sqrt(n))) if n else 1
    rows = int(math.ceil(n / grid)) if n else 1
    sheet = np.zeros((rows * cell, grid * cell), np.uint8)
    for i in range(n):
        r, c = divmod(i, grid)
        sheet[r * cell : (r + 1) * cell, c * cell : (c + 1) * cell] = cv2.resize(
            u8_stack[i], (cell, cell), interpolation=cv2.INTER_AREA
        )
    return png_bytes(sheet), grid


def thumb_sheet(
    frames: np.ndarray, flat_n: np.ndarray, tone: Tone, cell: int = 64
) -> tuple[bytes, int]:
    """The contact sheet -> `(png_bytes, grid)`. `grid = ceil(sqrt(n))`, row-major in trial order.

    Same **GLOBAL** window: a per-tile stretch here would make the contact sheet lie about which
    frames are dim — which is the one thing the Screen step exists to show him.
    """
    if not len(frames):
        return _sheet(np.zeros((0, cell, cell), np.uint8), cell)
    return _sheet(np.stack([to_u8(f, flat_n, tone) for f in frames]), cell)


# =============================================================================
# The texture measure — ⭐ CORE, not mosaic
# =============================================================================
def texture_map(trials: list[int], band: np.ndarray) -> dict[int, float]:
    """`{trial: std(DoG(3, 30)(frame))}`, to 2 dp. Row `i` of `band` is `trials[i]`.

    ⭐ **THE MEASURE IS A PROPERTY OF THE FRAME, NOT OF THE MOSAIC.** "How much texture is in this
    image" is a question every future feature asks: a segmentation feature must not segment glare; a
    dataset browser wants to say "these 11 frames are empty". So it is core.

    ⭐ And it is **free** here and costs +3.0 s / +624 MiB anywhere else: the matcher's band-passed
    stack and this measure are **the same array**. It is bit-identical either way — the texture
    measure *is* `band_pass(frame).std()` — which is the whole reason `open` is ~5 s and not ~8 s.
    (Verified equal to the precomputed `analysis/texture/260620d_texture.json` on every trial, to
    the stored 2 dp; `tests/slow/` pins it.)

    ⛔ **No threshold, no list, no policy.** Turning a number into a *proposal* is the mosaic
    feature's job (`features/mosaic/blank.py`); turning a proposal into a *decision* is the human's,
    and it lands in the document. ❌ And there is **no blur judgement, ever**: across 338 snapshots
    and 15 focus measures the best global blur threshold reaches F1 = 0.37, and
    variance-of-Laplacian scores **worse than chance**.
    """
    if len(band) != len(trials):
        raise ValueError(f"texture_map: {len(trials)} trials but {len(band)} band rows")
    return {t: round(float(band[i].std()), 2) for i, t in enumerate(trials)}


# =============================================================================
# The frame store — the pixels of ONE open dataset
# =============================================================================
@dataclass
class FrameStore:
    """The pixels of an open dataset, plus everything derived from them.

    ⭐ **IMMUTABLE EXCEPT FOR THE DISPLAY TONE.** It holds **no analysis state**:

        NO tile states.  NO exclusions.  NO blank list.  NO run.  NO pass_split.

    Those are a *feature's*, and they live in its DOCUMENT. (v1's `Session` carried `blank`, which
    `PUT /api/scan/blank` mutated and the matcher read — which made `POST /api/match/anchor` **not**
    a pure function of its request body, contrary to the comment at the top of its own server, and
    is why the server had to reset the match memo on every scan edit. The refusal set now travels in
    the match request body. `docs/SPLIT.md` §2.4.)

    ⚠️ ONE SHAPE. A store holds frames of exactly one `(h, w)` — whatever the XML said. It does not
    know or care whether that is 512.
    """

    trials: list[int]
    frames: np.ndarray  # (N, h, w) float32, flipped per the XML, RAW counts
    flat_n: np.ndarray
    tone: Tone
    #: per-trial XML metadata (`core.dataset.read_trial_meta`). Read for `frame_note` only —
    #: `FrameStore` holds pixels, not inventory.
    metas: dict[int, dict[str, Any]] = field(default_factory=dict)

    #: the lo/hi that `set_tone(auto=True)` restores. (v1 had this twice: on the session AND on the
    #: server, as `_AUTO_TONE`.)
    auto_lohi: tuple[float, float] = (0.0, 0.0)

    #: ⭐ **A FRESH IDENTITY FOR EVERY OPEN.** Two things needed one and were faking it with `id()`:
    #:   * the composite cache and the match memo keyed on `id(band)` — and CPython **recycles**
    #:     `id()` (measured: 4 of 5 same-size allocations reused an address), so two sessions of the
    #:     same dataset with the same frame count **collided**;
    #:   * the front end's `?v={tone.version}` cache-buster resets to 1 on every open while the
    #:     pixels behind that URL change — and the URL is served `immutable, max-age=1yr`. Open a
    #:     second acquisition whose trial numbers overlap and the canvas shows the FIRST one's
    #:     pixels, for a year.
    #: It is not a secret and it is deliberately not stable across restarts.
    nonce: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    # --- caches. THE ONLY ONES. (v1 had two of each: `Session._u8`/`_thumbs` AND
    # `server._PNG_CACHE`/`_THUMB_CACHE`, two caches for the same pixels.) All are keyed on
    # `tone.version` — the same number the front end uses as its cache-buster, so they cannot drift.
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)
    _band: np.ndarray | None = field(default=None, repr=False, compare=False)
    _texture: dict[int, float] | None = field(default=None, repr=False, compare=False)
    _u8: np.ndarray | None = field(default=None, repr=False, compare=False)
    _u8_version: int = field(default=-1, repr=False, compare=False)
    _png: dict[int, bytes] = field(default_factory=dict, repr=False, compare=False)
    _png_version: int = field(default=-1, repr=False, compare=False)
    _thumbs: tuple[bytes, int] | None = field(default=None, repr=False, compare=False)
    _thumbs_version: int = field(default=-1, repr=False, compare=False)
    _thumbs_cell: int = field(default=-1, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.row_of: dict[int, int] = {t: i for i, t in enumerate(self.trials)}

    # --- identity ---------------------------------------------------------------------------
    @property
    def n(self) -> int:
        return len(self.trials)

    @property
    def shape(self) -> tuple[int, int]:
        """`(h, w)` of every frame in this store."""
        return (int(self.frames.shape[1]), int(self.frames.shape[2]))

    @property
    def version(self) -> str:
        """⭐ The pixel cache-buster: `{nonce}.{tone.version}`. **NOT the tone version alone.**"""
        return f"{self.nonce}.{self.tone.version}"

    # --- pixel accessors: the ONLY way anything else gets at a frame -------------------------
    def frame(self, trial: int) -> np.ndarray:
        if trial not in self.row_of:
            raise KeyError(trial)  # -> 404: not in this store
        return self.frames[self.row_of[trial]]

    def banded(self, trial: int) -> np.ndarray:
        if trial not in self.row_of:
            raise KeyError(trial)
        return self.band[self.row_of[trial]]

    @property
    def band(self) -> np.ndarray:
        """The DoG(3,30) stack — **the matcher's input, and the texture measure's**.

        ⭐ **ONE ARRAY SERVES BOTH.** That is the entire reason it lives in core and not in a
        feature: push it into one and you either duplicate the array (+624 MiB) or duplicate the
        compute (+3.0 s).

        Lazy and memoised: it is a **full second copy of the stack** (624 MiB at n=312), so it is
        allocated once, on first use, and never per match. `open` warms it deliberately.
        """
        with self._lock:
            if self._band is None:
                self._band = band_pass(self.frames)
            return self._band

    def texture(self) -> dict[int, float]:
        """`{trial: round(std(band[i]), 2)}`. Memoised; free once `band` exists."""
        with self._lock:
            if self._texture is None:
                self._texture = texture_map(self.trials, self.band)
            return dict(self._texture)

    # --- the display path. Callers use THESE, not the free functions. ------------------------
    def _u8_stack(self) -> np.ndarray:
        """Every display frame, uint8 (~85 MiB at n=338). Rebuilt **only** when `tone.version`
        changes (0.9 s). This is what makes a tone change safe: there is exactly one cache, and it
        is keyed on the same number the front end sends as `?v=`, so the two cannot drift apart."""
        with self._lock:
            if self._u8 is None or self._u8_version != self.tone.version:
                self._u8 = np.stack([to_u8(f, self.flat_n, self.tone) for f in self.frames])
                self._u8_version = self.tone.version
                self._thumbs = None
                self._png.clear()
            return self._u8

    def tile_png(self, trial: int) -> bytes:
        """8-bit grayscale PNG of one frame, flat-fielded and mapped through the GLOBAL window.
        `KeyError` (-> 404) for anything not in this store."""
        if trial not in self.row_of:
            raise KeyError(trial)
        with self._lock:
            if self._png_version != self.tone.version:
                self._png.clear()
                self._png_version = self.tone.version
            png = self._png.get(trial)
            if png is None:
                png = png_bytes(self._u8_stack()[self.row_of[trial]])
                if len(self._png) > 512:
                    self._png.clear()
                self._png[trial] = png
            return png

    def tile_raw(self, trial: int) -> bytes:
        """uint16 LE, ALREADY FLIPPED, RAW counts. No flat-field, no tone."""
        return tile_raw(self.frame(trial))

    def thumbs(self, cell: int = 64) -> tuple[bytes, int]:
        """The contact sheet -> `(png, grid)`. Cached on `tone.version`."""
        with self._lock:
            if (
                self._thumbs is None
                or self._thumbs_version != self.tone.version
                or self._thumbs_cell != cell
            ):
                self._thumbs = _sheet(self._u8_stack(), cell)
                self._thumbs_version = self.tone.version
                self._thumbs_cell = cell
            return self._thumbs

    def thumbs_json(self, cell: int = 64) -> dict[str, Any]:
        _, grid = self.thumbs(cell)
        return {
            "grid": grid,
            "cell": cell,
            "trials": list(self.trials),
            "n": self.n,
            "version": self.version,
        }

    def set_tone(
        self, lo: float | None = None, hi: float | None = None, auto: bool = False
    ) -> Tone:
        """Bumps `version`, which invalidates every display cache above. **The only mutation a
        FrameStore permits.**

        ⚠️ GLOBAL ONLY. There is no per-tile path and there must never be one. Tone never touches
        `band` (the matcher) or `frames` (the exported TIFF).

        (v1's tone route mutated `tone.lo`/`.hi`/`.version` **by hand**, skipping this method's
        `hi > lo` validation and its cache invalidation, and re-implementing both — badly.)
        """
        with self._lock:
            if auto:
                new_lo, new_hi = self.auto_lohi
                is_auto = True
            else:
                new_lo = float(self.tone.lo if lo is None else lo)
                new_hi = float(self.tone.hi if hi is None else hi)
                is_auto = False
            if not (math.isfinite(new_lo) and math.isfinite(new_hi)) or new_hi <= new_lo:
                raise ValueError(f"bad tone window [{new_lo}, {new_hi}]: hi must exceed lo")
            self.tone = Tone(
                lo=new_lo,
                hi=new_hi,
                level=self.tone.level,
                flat_sigma=self.tone.flat_sigma,
                pct_lo=self.tone.pct_lo,
                pct_hi=self.tone.pct_hi,
                n_sample=self.tone.n_sample,
                auto=is_auto,
                version=self.tone.version + 1,
            )
            return self.tone

    # --- what the reader ACTUALLY did ---------------------------------------------------------
    @property
    def frame_note(self) -> str:
        """⭐ **WHICH PIXEL FRAME THESE POSITIONS ARE IN — read off THIS acquisition's XML, never
        asserted.** It goes into the TIFF header and the document's `coordinates` note.

        ⚠️ `load_frame` flips **CONDITIONALLY** (`ax=-1` -> flip x, `ay=-1` -> flip y): it honours
        the file. But v1's `project.COORDINATES` and the exported TIFF's `ImageDescription` both
        stated "180-degree-flipped display frame" **UNCONDITIONALLY**. On 260620d all 342 XMLs are
        `ax=-1, ay=-1`, so the two agree and nothing can go wrong *today*. On an acquisition whose
        `<transform>` is absent or says `ax=+1`, the reader returns an **unflipped** frame — the
        mosaic would still be self-consistently correct (matcher, canvas and export all agree) — but
        every exported artefact would carry a **false claim about its own coordinate frame**, on the
        one axis this project has been burned by, in the file most likely to be handed to someone
        else. **Do not hard-code "180-degree-flipped" anywhere. Build the string from here.**
        """
        fx = [bool(m["flip_x"]) for m in self.metas.values()]
        fy = [bool(m["flip_y"]) for m in self.metas.values()]
        if not fx:
            return "unknown pixel frame (no frame metadata)"
        if all(fx) and all(fy):
            return "the vscope-displayed (180deg-flipped: XML ax=-1, ay=-1) frame"
        if not any(fx) and not any(fy):
            return "the RAW sensor frame (this acquisition's XML declares NO flip: ax=+1, ay=+1)"
        if all(fx) and not any(fy):
            return "the horizontally-mirrored frame (XML ax=-1, ay=+1)"
        if all(fy) and not any(fx):
            return "the vertically-mirrored frame (XML ax=+1, ay=-1)"
        return (
            "a MIXED frame - the trials in this run do not agree on their XML <transform>. "
            "That is not something this app can express in one coordinate note; check the XMLs"
        )

    # --- construction ---------------------------------------------------------------------------
    @classmethod
    def load(
        cls,
        data_dir: Path | str | None,
        trials: list[int],
        snaps: Mapping[int, Mapping[str, Any]] | None = None,
        progress: Callable[[int, int], None] | None = None,
    ) -> FrameStore:
        """Read the pixels, estimate the vignette, compute the ONE global window. ~1-2 s.

        The band stack and the texture map are **not** computed here — they are lazy on the store.
        The `open` job warms them (that is its `texture` phase) so the first match does not pay for
        them; a dataset-browser thumbnail never touches them at all.
        """
        if snaps is None:
            if data_dir is None:
                raise ValueError("FrameStore.load: give it either a data_dir or an inventory")
            snaps = _list_snapshots(Path(data_dir))
        frames = load_frames(data_dir, trials, snaps=snaps, progress=progress)
        tone, flat_n = compute_tone(frames)
        return cls(
            trials=list(trials),
            frames=frames,
            flat_n=flat_n,
            tone=tone,
            metas={t: dict(snaps[t]) for t in trials},
            auto_lohi=(tone.lo, tone.hi),
        )
