"""Locate a small fixed-field picture inside a big finished mosaic.

**The question this answers.** A calcium recording of ONE region — the stage parked, seconds
to minutes of video — was taken somewhere on the chip. Later, a survey video swept the whole
chip and became a mosaic. *Where on that mosaic was the recording taken?* Answer that and the
electrode map (`core.electrodegrid`) names the electrodes underneath it, which is the whole
point: it pairs an MEA channel with the neuron whose calcium trace sits on top of it.

**Two unknowns, and only one of them is searched.**

* **Zoom.** The region recording is at a different magnification from the survey — his words,
  *"pretty much always differs"*. That would normally mean searching a ladder of scales, and
  every extra scale is another chance for a confident-but-wrong peak to win. It does not have
  to be searched: **the MEA lattice is in both pictures and it is a ruler.** Measure the pad
  pitch in each (`electrodegrid.measure_lattice`) and the ratio *is* the zoom, to whatever
  precision the FFT gives. A ladder is kept only as the fallback for a recording with no
  visible lattice.
* **Position.** Solved by masked normalised cross-correlation over the WHOLE plane
  (`engine.t33.match`), which is exactly the primitive that exists: small image inside big
  image, no prior, no search window, ragged reference footprint handled by the mask.

⛔ **Rotation is not solved.** Same rig, same camera orientation — his ruling. The lattice
angle IS measured on both sides and reported, so a reseated chip shows up as a number the
user can see rather than as a silently wrong placement.

⭐ **THE ARITHMETIC** (get it wrong and everything is a template-width out)::

    c = t33.match(REF, RMASK, tpl, TMASK)     # (dx, dy) == originB - originA
    #   A = the mosaic canvas, B = the resampled template, so:
    #                  ⭐  canvas_topleft = (dx, dy)  ⭐
    #   and the caller adds the canvas->world offset itself (0,0) for a video mosaic.

⚠️ **THE ALIAS RISK IS AT ITS MAXIMUM HERE.** `features/mosaic/solve.py` measured it on real
tile pairs: 5 % of genuinely-overlapping pairs put the exact-NCC argmax >20 px wrong at scores
up to 0.760, the worst case **757 px** wrong with the truth as the runner-up. One small field
against a whole mosaic is that problem with the largest possible search plane, and the MEA
lattice is a periodic comb that manufactures peaks. So this module never reports a winner
alone: it reports the **margin** (best - runner-up), which is the only evidence that the
aperture killed the aliases instead of merely outscoring them, and it reports the alternatives
so a human can take one. A thin margin is what a surviving alias looks like.

⭐ **What actually carries the signal.** The neurons. A fixed-region recording watched one
field for minutes, so every cell that fired at least once is recoverable from it; the mosaic
only glimpsed that ground for an instant as the stage swept past. The two pictures therefore
do NOT look alike in the same way, and which projection of the recording resembles the mosaic
best is not knowable in advance — so `still_stack` builds several (median / max / std) from
one decode and the caller matches each, keeping the best-scoring. When the MEA border is in
frame it is a gift: a straight, unique, non-periodic landmark, and the whole-plane NCC
exploits it for free with no special-casing.

⛔ No dataset knowledge lives here: no field size, no expected zoom, no per-recording case.
Everything is measured from the two pictures in front of it.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np

# =================================================================================================
# Constants
# =================================================================================================
LOCATE_STEPS = ("stills", "scale", "match", "verify")
"""Job phases, in order. `features/*/regions.py` reports progress against this tuple."""

STILL_KINDS = ("median", "max", "std")
"""The projections of a fixed-field recording that are tried, in order of preference on a tie.

`median` is the steady picture — cell bodies at rest, tissue, the grid, the border — and is
what a single mosaic keyframe most resembles. `max` is every neuron that fired at any point,
which is how a calcium field is normally turned into a cell map. `std` is the ACTIVE cells
only, with the static background removed. Which one wins is a property of the preparation
(are the cells bright at rest, or only when firing?), not something to decide in code.
"""

MARGIN_THIN = 0.10
"""Below this, `best - second` is the signature of a surviving alias rather than a win.
Same number and same reason as `features/mosaic/solve.py` — do not diverge them by taste."""

NCC_MIN = 0.12
"""A winner scoring below this is reported `confident=False` whatever its margin. Deliberately
low: this is not a quality bar, it is the floor under which "the best of a bad set" stops
meaning anything at all."""

NMS_PX = 24.0
"""Candidates closer together than this are the same peak (mirrors `solve.NMS_PX`)."""

SNAP_RADIUS = 96
"""Default half-width of the local re-search after a drag, in mosaic px. ⚠️ Wider than the
snapshot sweep's 64 because the user is dragging across a whole mosaic rather than nudging a
tile — but a LOCAL search is alias-bound by construction, so this is clamped (see `snap`)."""

SNAP_RADIUS_MAX = 768
"""⚠️ The hard ceiling on a local search. Past this, use a global match: local mode has no FFT
and no margin over the whole plane, so a wide local sweep is exactly how a grid alias wins.

⭐ **Why it is this big** — found by driving the real app. A mosaic 5319 x 7356 draws ~0.079
CSS px per mosaic px at fit zoom, so a 40 px nudge of the mouse is a **506 px** move on the
mosaic. A radius that sounds generous in mosaic pixels is nothing at all in hand movements,
and the first ceiling (512) could not reach back from an ordinary drag: the snap landed 450 px
from the truth at NCC 0.51. This is R45.7 again in a different costume — a distance that is
sane in mosaic px is meaningless on screen — and the answer is the same: let the interaction's
own scale set the number (`snap_radius_for`), and put the ceiling where a search is still
affordable rather than where it merely sounded safe."""


def snap_radius_for(moved_px: float) -> int:
    """The local-search half-width that can actually reach back from a drag of `moved_px`.

    The user drags to say *"it belongs over there"*; if the search cannot cover the distance he
    moved it, the snap answers a question he did not ask. So the window is the drag plus a
    margin — never smaller than the default, never past the ceiling.
    """
    want = 1.25 * abs(float(moved_px)) + 64.0
    return int(max(SNAP_RADIUS, min(SNAP_RADIUS_MAX, round(want))))

MAX_CANDIDATES = 9

_SCALE_LADDER_LO, _SCALE_LADDER_HI, _SCALE_LADDER_N = 0.25, 4.0, 13
"""The fallback when no lattice can be measured in the recording — a geometric ladder, log-even
between the bounds. ⚠️ Only ever used when the measurement REFUSED; a measured scale is one
number and thirteen chances for an alias are not the same thing as one."""


# =================================================================================================
# Results
# =================================================================================================
@dataclass(frozen=True)
class Candidate:
    """One place the template could sit. `x`/`y` are the **top-left corner** of the template in
    the reference's own pixel space — never a centre (R19), never a delta."""

    rank: int
    x: float
    y: float
    ncc: float
    npix: int
    subpixel: bool = False

    def to_json(self) -> dict:
        return {"rank": self.rank, "x": round(self.x, 2), "y": round(self.y, 2),
                "ncc": round(self.ncc, 4), "npix": int(self.npix),
                "subpixel": bool(self.subpixel)}


@dataclass
class MatchOutcome:
    """What the pixels said. `refused` carries a sentence when nothing could be measured."""

    candidates: list[Candidate] = field(default_factory=list)
    margin: float | None = None
    margin_thin: bool = False
    elapsed_ms: float = 0.0
    refused: str | None = None

    @property
    def best(self) -> Candidate | None:
        return self.candidates[0] if self.candidates else None

    @property
    def confident(self) -> bool:
        """⭐ Two conditions, and the margin is the load-bearing one. A confident-looking NCC
        with no gap to the runner-up is the exact signature of the 757 px failure."""
        b = self.best
        if b is None:
            return False
        if b.ncc < NCC_MIN:
            return False
        return self.margin is not None and self.margin >= MARGIN_THIN


# =================================================================================================
# Stills — one decode, several pictures
# =================================================================================================
def still_stack(frames: Sequence[np.ndarray], kinds: Sequence[str] = STILL_KINDS) -> dict:
    """`{kind: float32 (h, w)}` from a stack of decoded grey frames.

    Takes the frames it is given rather than reading the video itself: decoding is the
    feature's business (`core` may not import `features`), and the same stack is wanted for
    every projection — decoding three times to build three pictures would be silly.
    """
    if not len(frames):
        raise ValueError("no frames to build a still from")
    stack = np.asarray(frames, np.float32)
    if stack.ndim != 3:
        raise ValueError(f"expected a stack of 2-D frames, got shape {stack.shape}")
    out: dict[str, np.ndarray] = {}
    for kind in kinds:
        if kind == "median":
            out[kind] = np.median(stack, axis=0).astype(np.float32)
        elif kind == "max":
            out[kind] = stack.max(axis=0).astype(np.float32)
        elif kind == "std":
            # ⚠️ ddof=0 on purpose: with a handful of frames the unbiased correction is a
            # constant gain, and NCC is invariant to gain — it would buy nothing and could
            # divide by zero at n=1.
            out[kind] = stack.std(axis=0).astype(np.float32)
        else:
            raise ValueError(f"unknown still kind {kind!r}")
    return out


def sample_indices(n_frames: int, want: int) -> list[int]:
    """Up to `want` frame indices spread evenly over the whole recording.

    ⭐ Spread, not the first N. A fixed-field recording's information is *temporal* — which
    cells lit up, and when — so the first second of it is one sample of the activity, not a
    summary of it. `video.read_frames_at` is a single forward pass whose cost is set by the
    HIGHEST index, so spreading costs the decode of the whole file either way; the frames in
    between are skipped with `grab()`, which does not pay for colour conversion.
    """
    n = int(n_frames)
    k = max(1, int(want))
    if n <= 0:
        return []
    if n <= k:
        return list(range(n))
    # endpoints included; a recording's first and last frames are as much data as its middle
    return sorted({int(round(i * (n - 1) / (k - 1))) for i in range(k)})


# =================================================================================================
# Preparing the two sides
# =================================================================================================
def prepare_reference(image: np.ndarray, valid: np.ndarray | None = None
                      ) -> tuple[np.ndarray, np.ndarray]:
    """The mosaic canvas, in the exact representation `t33.match` expects.

    Band-passed, then **mean-subtracted over the valid mask only** and zeroed outside it —
    `t33.composite`'s own convention, and it is not cosmetic: an unmasked mean is dragged by
    the background zeros, and every NCC downstream would be biased by the shape of the hull.

    🔴 `valid` is COVERAGE and it is not optional. A toned composite maps its darkest covered
    pixels to exactly 0.0 and there is no alpha channel, so `image > 0` conflates "no data"
    with "black tissue" — the mistake that cost 97 % of the pads in the electrode work. Pass
    the geometric union of the placed frames' rectangles.
    """
    from .frames import band_pass_one

    img = np.ascontiguousarray(image, np.float32)
    if img.ndim != 2:
        raise ValueError(f"expected a 2-D reference image, got shape {image.shape}")
    if valid is None:
        mask = np.ones(img.shape, bool)
    else:
        mask = np.ascontiguousarray(valid, bool)
        if mask.shape != img.shape:
            raise ValueError("the coverage mask does not match the reference image")
    if not mask.any():
        raise ValueError("the coverage mask is empty — nothing to match against")

    ref = band_pass_one(img)
    ref[~mask] = 0.0
    ref -= float(ref[mask].mean())
    ref[~mask] = 0.0
    return np.ascontiguousarray(ref, np.float32), mask


def notch_lattice(img: np.ndarray, a1: Sequence[float], a2: Sequence[float],
                  *, valid: np.ndarray | None = None, orders: int = 3,
                  rad_frac: float = 0.30) -> np.ndarray:
    """Remove the electrode lattice from a band-passed picture. **This is the alias killer.**

    ⭐ **Why it is sound, not merely helpful.** A perfectly periodic pattern carries no absolute
    position information — only phase modulo the pitch. Every place the comb can sit on itself
    correlates almost equally well, which is precisely how a match lands whole cells away with a
    confident score. Deleting the comb therefore costs the answer *nothing it could have used*
    and takes away the alias generator. Everything aperiodic survives untouched: the tissue, the
    neurons, and the array's border — which is the one landmark that is unique on the whole chip.

    ⭐ **Measured on the synthetic scene** (a deliberately grid-dominated world), `best - second`
    across three scale errors, without -> with:

        scale error 0 %:   0.064 -> 0.134
        scale error 3 %:   0.068 -> 0.135
        scale error 5 %:   0.046 -> 0.087

    It roughly DOUBLES the margin at every scale error, which is the difference between the
    global search picking the right peak and picking a neighbour.

    ⚠️ Used for the GLOBAL search only. The refinement and the drag-snap run on the un-notched
    picture: inside a bounded window there is no alias to kill, and the grid is sharp, high-
    contrast detail that helps settle the last fraction of a pixel.

    `a1`/`a2` are the real-space primitive vectors in px (`electrodegrid.lattice_axes`). Their
    reciprocal basis is `inv([a1 a2])^T`; a disc of `rad_frac` of the reciprocal spacing is
    zeroed at every harmonic `k*b1 + l*b2` up to `orders`, excluding DC.
    """
    f = np.ascontiguousarray(img, np.float32)
    A = np.array([[float(a1[0]), float(a2[0])], [float(a1[1]), float(a2[1])]], float)
    if abs(float(np.linalg.det(A))) < 1e-9:
        return f                                  # degenerate axes: nothing safe to remove
    B = np.linalg.inv(A).T                        # columns b1, b2, in cycles/px

    H, W = f.shape
    F = np.fft.rfft2(f)
    fy = np.fft.fftfreq(H)[:, None] * H
    fx = np.fft.rfftfreq(W)[None, :] * W
    step = min(math.hypot(B[0, 0] * W, B[1, 0] * H), math.hypot(B[0, 1] * W, B[1, 1] * H))
    r = max(2.0, float(rad_frac) * step)
    for k in range(-orders, orders + 1):
        for lo in range(-orders, orders + 1):
            if k == 0 and lo == 0:
                continue
            gx = (k * B[0, 0] + lo * B[0, 1]) * W
            gy = (k * B[1, 0] + lo * B[1, 1]) * H
            if gx < 0:                            # rfft2 keeps fx >= 0; fold the conjugate half
                gx, gy = -gx, -gy
            # fy is periodic in H, so wrap the difference before measuring the distance
            d2 = (fx - gx) ** 2 + (((fy - gy + H / 2.0) % H) - H / 2.0) ** 2
            F[d2 < r * r] = 0.0
    out = np.fft.irfft2(F, s=(H, W)).astype(np.float32)

    if valid is not None:
        m = np.asarray(valid, bool)
        out[~m] = 0.0
        out -= float(out[m].mean())
        out[~m] = 0.0
    else:
        out -= float(out.mean())
    return np.ascontiguousarray(out, np.float32)


def prepare_template(image: np.ndarray, scale: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """The recording's still, resampled to the mosaic's scale and band-passed.

    ⭐ **Resample FIRST, band-pass SECOND.** The band-pass is defined in pixels, so filtering
    before the resample would hand the two sides different spatial frequency windows and the
    NCC would be comparing differently-blurred pictures. After the resample both sides see the
    same filter at the same scale — which is also what makes the electrode comb attenuate
    identically on both sides instead of beating against itself.
    """
    import cv2

    from .frames import band_pass_one

    img = np.ascontiguousarray(image, np.float32)
    if img.ndim != 2:
        raise ValueError(f"expected a 2-D template image, got shape {image.shape}")
    s = float(scale)
    if not (math.isfinite(s) and s > 0):
        raise ValueError(f"scale must be a positive number, got {scale!r}")

    if abs(s - 1.0) > 1e-6:
        h, w = img.shape
        nh, nw = max(8, int(round(h * s))), max(8, int(round(w * s)))
        # INTER_AREA is the correct shrink (it averages, so it does not alias the electrode
        # comb into a lower frequency); INTER_CUBIC is the correct enlarge.
        interp = cv2.INTER_AREA if s < 1.0 else cv2.INTER_CUBIC
        img = cv2.resize(img, (nw, nh), interpolation=interp)

    tpl = band_pass_one(np.ascontiguousarray(img, np.float32))
    tpl = tpl - float(tpl.mean())
    return np.ascontiguousarray(tpl, np.float32), np.ones(tpl.shape, bool)


# =================================================================================================
# The match
# =================================================================================================
def match(ref: np.ndarray, refmask: np.ndarray, tpl: np.ndarray, tplmask: np.ndarray,
          *, max_candidates: int = MAX_CANDIDATES, kpk: int = 8) -> MatchOutcome:
    """Whole-plane masked NCC of `tpl` against `ref`. Best first, distinct peaks only.

    ⚠️ `minfrac=0.0` and an ABSOLUTE overlap floor of half the template's area. A *fractional*
    floor is a fraction of the smaller footprint, i.e. of the template — which lets a sliver of
    a corner hanging off the canvas edge win. `t33.place` reaches the same conclusion for the
    same reason ("For ONE tile a fractional overlap rule would let a corner match win").
    """
    from ..engine import t33

    t0 = time.perf_counter()
    if tpl.shape[0] > ref.shape[0] or tpl.shape[1] > ref.shape[1]:
        return MatchOutcome(refused=(
            f"the recording covers {tpl.shape[1]} x {tpl.shape[0]} px at the mosaic's scale, "
            f"which is bigger than the mosaic itself ({ref.shape[1]} x {ref.shape[0]}) — "
            "check the zoom: this recording looks lower-magnification than the survey"),
            elapsed_ms=(time.perf_counter() - t0) * 1e3)

    minabs = 0.5 * float(tpl.shape[0] * tpl.shape[1])
    raw = t33.match(ref, refmask, tpl, tplmask, kpk=kpk, minfrac=0.0, minabs=minabs)
    if not raw:
        return MatchOutcome(refused=(
            "no position on the mosaic overlaps this recording enough to score — the field "
            "may sit outside what the survey covered"),
            elapsed_ms=(time.perf_counter() - t0) * 1e3)

    # ⚠️ `t33.match` appends its leftover coarse candidates WITHOUT re-sorting, and gives them
    # npix=0 meaning "not measured". Sort here so `margin` is honestly best-minus-runner-up.
    order = sorted(raw, key=lambda z: -float(z[0]))
    margin = (float(order[0][0]) - float(order[1][0])) if len(order) > 1 else None

    cands: list[Candidate] = []
    for i, (ncc, dx, dy, npix) in enumerate(order[:max_candidates]):
        x, y, sub = float(dx), float(dy), False
        if i == 0:
            fx, fy = subpixel(ref, refmask, tpl, tplmask, int(dx), int(dy))
            x, y, sub = fx, fy, (fx, fy) != (float(dx), float(dy))
        cands.append(Candidate(rank=i, x=x, y=y, ncc=float(ncc), npix=int(npix), subpixel=sub))

    return MatchOutcome(
        candidates=cands, margin=margin,
        margin_thin=(margin is not None and margin < MARGIN_THIN),
        elapsed_ms=(time.perf_counter() - t0) * 1e3)


def snap(ref: np.ndarray, refmask: np.ndarray, tpl: np.ndarray, tplmask: np.ndarray,
         near: Sequence[float], radius: int = SNAP_RADIUS,
         *, max_candidates: int = MAX_CANDIDATES,
         lattice: tuple[Sequence[float], Sequence[float]] | None = None) -> MatchOutcome:
    """*"I dropped it here — now snap it."* Exhaustive exact-NCC around `near`, no FFT.

    `near` is the top-left the user dragged the rectangle to, in the reference's pixel space.

    ⚠️ **The radius is clamped.** A local search has no FFT surface and therefore no view of
    the whole plane, so it cannot see that the peak it found is one of twenty identical ones.
    Inside a bounded window that is fine — the user has just told it where to look. Widened
    without bound it becomes a confident alias generator, which is why the ceiling exists and
    why the honest way to search wide is a global `match`.
    """
    from ..engine import t33

    t0 = time.perf_counter()
    r = int(max(8, min(int(radius), SNAP_RADIUS_MAX)))
    cx, cy = int(round(float(near[0]))), int(round(float(near[1])))

    # ⚠️ The coarse grid is O(r²) evaluations, so a wide window has to step wider or a drag from
    # fit zoom would cost tens of seconds. Rank 0 is polished by ±`step` afterwards, so nothing
    # is lost: the coarse pass only has to land within one step of the peak.
    step = 4 if r <= 160 else 8

    # 🔴 A WIDE LOCAL SEARCH IS ALIAS-PRONE — measured: over a ±440 px window on a grid-dominated
    # scene it picked the cell one row DOWN (29.2 px on a 30.1 px pitch) at a comfortable 0.87.
    # Narrow windows are safe because they cannot reach a neighbouring cell at all; wide ones can,
    # and then the comb decides. So the same split as the global search applies at this scale
    # too: FIND THE CELL on the notched picture, where the comb cannot vote, and SETTLE THE PIXEL
    # on the plain one, where the grid is the sharpest detail there is.
    wide = lattice is not None and r > 160
    cref, ctpl = ref, tpl
    if wide:
        cref = notch_lattice(ref, lattice[0], lattice[1], valid=refmask)
        ctpl = notch_lattice(tpl, lattice[0], lattice[1])

    coarse: list[tuple[float, int, int, int]] = []
    for dy in range(cy - r, cy + r + 1, step):
        for dx in range(cx - r, cx + r + 1, step):
            ncc, npix = t33.exact_ncc(cref, refmask, ctpl, tplmask, dx, dy, stride=4)
            if math.isfinite(ncc):
                coarse.append((float(ncc), dx, dy, int(npix)))
    if not coarse:
        return MatchOutcome(refused=(
            "nothing measurable within the snap radius — the rectangle may be off the "
            "mosaic's covered area"), elapsed_ms=(time.perf_counter() - t0) * 1e3)

    coarse.sort(key=lambda z: -z[0])
    kept: list[tuple[float, int, int, int]] = []
    for c in coarse:
        if all(math.hypot(c[1] - k[1], c[2] - k[2]) > NMS_PX for k in kept):
            kept.append(c)
            if len(kept) >= max_candidates:
                break

    out: list[tuple[float, int, int, int]] = []
    for i, (_ncc, dx, dy, _n) in enumerate(kept):
        if i == 0:
            # the polish is ALWAYS on the plain picture — see the note above
            best = (-2.0, dx, dy, 0)
            for yy in range(dy - step, dy + step + 1):
                for xx in range(dx - step, dx + step + 1):
                    v, n = t33.exact_ncc(ref, refmask, tpl, tplmask, xx, yy)
                    if math.isfinite(v) and v > best[0]:
                        best = (float(v), xx, yy, int(n))
            out.append(best)
        else:
            v, n = t33.exact_ncc(ref, refmask, tpl, tplmask, dx, dy)
            if math.isfinite(v):
                out.append((float(v), dx, dy, int(n)))
    if not out:
        return MatchOutcome(refused="nothing measurable within the snap radius",
                            elapsed_ms=(time.perf_counter() - t0) * 1e3)
    out.sort(key=lambda z: -z[0])

    margin = (out[0][0] - out[1][0]) if len(out) > 1 else None
    cands: list[Candidate] = []
    for i, (ncc, dx, dy, npix) in enumerate(out):
        x, y, sub = float(dx), float(dy), False
        if i == 0:
            fx, fy = subpixel(ref, refmask, tpl, tplmask, int(dx), int(dy))
            x, y, sub = fx, fy, (fx, fy) != (float(dx), float(dy))
        cands.append(Candidate(rank=i, x=x, y=y, ncc=float(ncc), npix=int(npix), subpixel=sub))

    return MatchOutcome(
        candidates=cands, margin=margin,
        margin_thin=(margin is not None and margin < MARGIN_THIN),
        elapsed_ms=(time.perf_counter() - t0) * 1e3)


def subpixel(ref: np.ndarray, refmask: np.ndarray, tpl: np.ndarray, tplmask: np.ndarray,
             dx: int, dy: int) -> tuple[float, float]:
    """Separable parabolic fit on the exact-NCC 3x3 around an integer winner.

    Purely additive — eight extra `exact_ncc` calls. Each offset is clipped to +-0.5 px and
    forced to zero where the three-point curvature is not a peak: *do not interpolate a
    shoulder*. (Lifted from `features/mosaic/solve._subpixel`, which is about to become
    legacy; the behaviour is deliberately identical.)
    """
    from ..engine import t33

    g = np.full((3, 3), np.nan, float)
    for j, yy in enumerate((dy - 1, dy, dy + 1)):
        for i, xx in enumerate((dx - 1, dx, dx + 1)):
            v, _n = t33.exact_ncc(ref, refmask, tpl, tplmask, xx, yy)
            g[j, i] = v
    if not np.isfinite(g).all():
        return float(dx), float(dy)

    def peak(a: float, b: float, c: float) -> float:
        denom = a - 2.0 * b + c
        if denom >= 0:                      # not a peak — a shoulder or a plateau
            return 0.0
        return float(np.clip(0.5 * (a - c) / denom, -0.5, 0.5))

    return dx + peak(g[1, 0], g[1, 1], g[1, 2]), dy + peak(g[0, 1], g[1, 1], g[2, 1])


# =================================================================================================
# Zoom
# =================================================================================================
@dataclass(frozen=True)
class Zoom:
    """How much the recording must be shrunk/grown to sit on the mosaic, and where it came from.

    `scale` multiplies recording px to give mosaic px. `measured` is False when the lattice
    could not be read and a ladder was used instead — the difference matters, and the UI says
    which happened rather than presenting a guess as a measurement.
    """

    scale: float
    measured: bool
    pitch_recording: float | None = None
    pitch_mosaic: float | None = None
    angle_recording: float | None = None
    angle_mosaic: float | None = None
    note: str = ""

    @property
    def angle_delta(self) -> float | None:
        """Degrees the recording's lattice is turned relative to the mosaic's, folded into
        (-45, 45] because a square lattice is its own answer every 90 degrees."""
        if self.angle_recording is None or self.angle_mosaic is None:
            return None
        d = (float(self.angle_recording) - float(self.angle_mosaic) + 45.0) % 90.0 - 45.0
        return float(d)

    def to_json(self) -> dict:
        return {"scale": round(float(self.scale), 6), "measured": bool(self.measured),
                "pitch_recording_px": (round(self.pitch_recording, 4)
                                       if self.pitch_recording is not None else None),
                "pitch_mosaic_px": (round(self.pitch_mosaic, 4)
                                    if self.pitch_mosaic is not None else None),
                "angle_recording_deg": (round(self.angle_recording, 4)
                                        if self.angle_recording is not None else None),
                "angle_mosaic_deg": (round(self.angle_mosaic, 4)
                                     if self.angle_mosaic is not None else None),
                "angle_delta_deg": (round(self.angle_delta, 4)
                                    if self.angle_delta is not None else None),
                "note": self.note}


def scale_ladder(lo: float = _SCALE_LADDER_LO, hi: float = _SCALE_LADDER_HI,
                 n: int = _SCALE_LADDER_N) -> list[float]:
    """Log-even scale factors, the fallback when no lattice can be measured."""
    return [float(round(math.exp(v), 4))
            for v in np.linspace(math.log(lo), math.log(hi), int(n))]


LATTICE_SNR_MIN = 12.0
"""Below this the FFT fundamental is not distinct enough to call a MEASUREMENT.

⚠️ `GridConfig.peak_snr_min` (6.0) is the floor for *refusing to see a lattice at all*, and it is
not the same question. A recording can clear it and still hand back a confidently wrong period —
observed: a 500 x 380 frame of a 40 px comb (whose fundamental sits ~6 FFT bins from DC, inside
the blob continuum) reported `pitch 17.88, angle -24.78` with every appearance of success, which
drove a scale that was half right and a placement **475 px** out. The `measured` flag exists to
tell a measurement from a guess; without a floor of its own it cannot."""

AGREE_FRAC = 0.05
"""Two independent projections of the same recording must agree on the pitch to within this."""


def measure_zoom(still: np.ndarray | dict, pitch_mosaic: float,
                 angle_mosaic: float | None = None,
                 *, pitch_min: float = 6.0, pitch_max: float = 200.0) -> Zoom:
    """Read the recording's lattice and turn it into a scale. Never raises.

    ⭐ **The ruler is the chip.** Both pictures show the same electrode array, so
    `pitch_mosaic / pitch_recording` is the magnification ratio directly — no search, no user
    input, and the same lattice machinery the electrode map already trusts.

    ⚠️ `pitch_max` is wider than `GridConfig`'s default 64 px. That default bounds a MOSAIC's
    pitch; a region recording is by definition at higher magnification and 40x optics put the
    17.5 um pitch well past 100 px. Too wide is not free either — the FFT ring for a very
    large period sits within a few bins of DC — hence a bound rather than none.
    """
    from . import electrodegrid

    pm = float(pitch_mosaic)
    if not (math.isfinite(pm) and pm > 0):
        return Zoom(scale=1.0, measured=False,
                    note="the mosaic's own lattice pitch is unknown, so there is nothing to "
                         "compare the recording against")
    # ⭐ TWO INDEPENDENT WITNESSES. When several projections of the recording are available they
    # are all read, and they must AGREE. They share no noise and very little structure — a median
    # is the steady picture, a max is every cell that ever fired — so a period both of them find
    # is in the tissue, while a spurious peak in one is very unlikely to be echoed by the other.
    # This is the cheapest honest check available, and it costs one extra FFT.
    stills = ({k: v for k, v in still.items() if isinstance(v, np.ndarray)}
              if isinstance(still, dict) else {"still": still})
    if not stills:
        return Zoom(scale=1.0, measured=False, pitch_mosaic=pm, angle_mosaic=angle_mosaic,
                    note="there is no picture of the recording to measure")

    reads: dict[str, tuple[float, float, float]] = {}
    last_err = ""
    for kind, img in stills.items():
        try:
            reads[kind] = electrodegrid.measure_lattice(
                img, pitch_min=pitch_min, pitch_max=pitch_max)
        except Exception as e:                                      # noqa: BLE001
            last_err = str(e)
    if not reads:
        return Zoom(scale=1.0, measured=False, pitch_mosaic=pm, angle_mosaic=angle_mosaic,
                    note=f"no electrode lattice could be measured in the recording ({last_err}) "
                         "— falling back to a search over zoom factors")

    strong = {k: v for k, v in reads.items() if v[2] >= LATTICE_SNR_MIN}
    if not strong:
        best = max(reads.values(), key=lambda v: v[2])
        return Zoom(scale=1.0, measured=False, pitch_mosaic=pm, angle_mosaic=angle_mosaic,
                    note=f"the recording's lattice is too faint to measure (strongest peak "
                         f"{best[2]:.1f}, needs {LATTICE_SNR_MIN:.0f}) — falling back to a "
                         "search over zoom factors")

    # ⭐ CONSENSUS, NOT STRENGTH. The winner is the pitch the most pictures agree on, and SNR only
    # breaks a tie. ⚠️ Both simpler rules were tried and are wrong on real video:
    #   * "take the strongest" — measured, a std-dev picture of a compressed recording reported
    #     **8.0 px** for a true 32 px comb (a harmonic) with the HIGHEST peak of the three, and
    #     would have set the zoom four times too small.
    #   * "require unanimity" — that same odd read would veto a median and a max agreeing
    #     exactly, throwing away an honest measurement in favour of a search.
    # Counting agreement is what survives both: a harmonic is one voice, the truth is two.
    def votes(p: float) -> int:
        return sum(1 for v in strong.values() if abs(v[0] - p) <= AGREE_FRAC * p)

    kind = max(strong, key=lambda k: (votes(strong[k][0]), strong[k][2]))
    pr, ar, snr = strong[kind]
    if len(strong) > 1 and votes(pr) < 2:
        return Zoom(scale=1.0, measured=False, pitch_mosaic=pm, angle_mosaic=angle_mosaic,
                    note="the recording's pictures disagree about the electrode pitch ("
                         + ", ".join(f"{k} {v[0]:.1f}px" for k, v in strong.items())
                         + ") — falling back to a search over zoom factors")
    return Zoom(scale=pm / pr, measured=True, pitch_recording=pr, pitch_mosaic=pm,
                angle_recording=ar, angle_mosaic=angle_mosaic,
                note=f"measured on the {kind}: {pr:.3f} px pitch in the recording (peak "
                     f"{snr:.0f}x background) against {pm:.3f} px in the mosaic")


# =================================================================================================
# The whole answer
# =================================================================================================
def refine_scale(ref: np.ndarray, refmask: np.ndarray, still: np.ndarray,
                 scale: float, at: Sequence[float], size: Sequence[float],
                 *, span: float = 0.08, steps: int = 9, radius: int = 32
                 ) -> tuple[float, MatchOutcome, tuple[int, int]]:
    """Tune the zoom against the PIXELS, around an already-found position.

    ⭐ **Why this exists, measured.** The FFT that reads the lattice pitch is quantised in
    bins, and for a magnified recording the fundamental sits only ~7 bins from DC — so the
    measured zoom is good to a few percent, not to a fraction of one. Three percent of a
    420 px field is ~13 px of width, which lands the top-left corner ~7 px off even when the
    match itself is perfect. (Exactly that was observed on the synthetic scene: a correct
    placement reported 432 x 329 for a planted 420 x 320.) The FFT is a good ruler and a poor
    micrometer, so it supplies the starting point and the pixels finish the job.

    ⭐ **The rectangle is re-centred, not re-cornered.** Changing the scale changes the
    template's SIZE; if the top-left were held fixed the picture would slide by half the size
    change and the local search would have to chase it. Holding the centre keeps every trial
    over the same ground, so the only thing being compared is sharpness of agreement.

    Scored on plain NCC — legitimate here and nowhere else, because every trial is the same
    still on the same reference at nearly the same size, so the surfaces are comparable.
    """
    lo, hi = math.log(1.0 - float(span)), math.log(1.0 + float(span))
    factors = [math.exp(v) for v in np.linspace(lo, hi, int(steps))]
    cx = float(at[0]) + float(size[0]) / 2.0
    cy = float(at[1]) + float(size[1]) / 2.0

    best: tuple[float, MatchOutcome, tuple[int, int]] | None = None
    for f in factors:
        s = float(scale) * f
        tpl, tmsk = prepare_template(still, s)
        h, w = tpl.shape
        near = (cx - w / 2.0, cy - h / 2.0)
        out = snap(ref, refmask, tpl, tmsk, near, radius=radius)
        if out.best is None:
            continue
        if best is None or out.best.ncc > best[1].best.ncc:      # type: ignore[union-attr]
            best = (s, out, (h, w))
    if best is None:
        return float(scale), MatchOutcome(refused="the refinement found nothing measurable"), (
            0, 0)
    return best


@dataclass
class Located:
    """Where the recording sits, plus every number that says how much to believe it."""

    x: float
    y: float
    w: float
    h: float
    still_kind: str
    zoom: Zoom
    outcome: MatchOutcome
    tried: list[dict] = field(default_factory=list)

    def to_json(self) -> dict:
        b = self.outcome.best
        return {
            "x": round(self.x, 2), "y": round(self.y, 2),
            "w": round(self.w, 2), "h": round(self.h, 2),
            "still_kind": self.still_kind,
            "zoom": self.zoom.to_json(),
            "ncc": round(b.ncc, 4) if b else None,
            "margin": round(self.outcome.margin, 4) if self.outcome.margin is not None else None,
            "margin_thin": bool(self.outcome.margin_thin),
            "confident": bool(self.outcome.confident),
            "candidates": [c.to_json() for c in self.outcome.candidates],
            "elapsed_ms": round(self.outcome.elapsed_ms, 1),
            "tried": self.tried,
        }


def locate(ref: np.ndarray, refmask: np.ndarray, stills: dict, zoom: Zoom,
           *, lattice: tuple[Sequence[float], Sequence[float]] | None = None,
           progress: Callable[[str], None] | None = None,
           max_candidates: int = MAX_CANDIDATES) -> Located:
    """Try each still (and each scale, if the zoom had to fall back) and keep the best.

    ⭐ **"Best" is scored on the margin, not the NCC.** Two projections of the same recording
    produce NCCs that are not comparable — a std-dev picture has different statistics from a
    median one — but the margin is a *within-surface* quantity: how far the winner stands
    above its own runner-up on its own correlation surface. That is comparable, and it is the
    quantity that actually predicts whether the answer is right.
    """
    say = progress or (lambda _m: None)
    scales = [zoom.scale] if zoom.measured else scale_ladder()
    kinds = [k for k in STILL_KINDS if k in stills] or list(stills)
    if not kinds:
        raise ValueError("no stills to match with")

    # ⭐ Both sides lose the electrode comb before any whole-plane search. See `notch_lattice`:
    # a periodic pattern cannot say WHERE, only where-modulo-the-pitch, so deleting it costs
    # nothing and roughly doubles the margin over the aliases it was manufacturing.
    def notched(a: np.ndarray, mask: np.ndarray | None) -> np.ndarray:
        if lattice is None:
            return a
        return notch_lattice(a, lattice[0], lattice[1], valid=mask)

    ref_g = notched(ref, refmask)

    best: Located | None = None
    tried: list[dict] = []
    total = len(kinds) * len(scales)
    done = 0
    for s in scales:
        for kind in kinds:
            done += 1
            say(f"matching {kind}"
                + ("" if zoom.measured else f" at {s:.2f}x")
                + f" ({done}/{total})")
            tpl, tmsk = prepare_template(stills[kind], s)
            tpl = notched(tpl, None)
            out = match(ref_g, refmask, tpl, tmsk, max_candidates=max_candidates)
            row = {"still_kind": kind, "scale": round(float(s), 4),
                   "ncc": round(out.best.ncc, 4) if out.best else None,
                   "margin": round(out.margin, 4) if out.margin is not None else None,
                   "refused": out.refused}
            tried.append(row)
            if out.best is None:
                continue
            here = Located(x=out.best.x, y=out.best.y,
                           w=float(tpl.shape[1]), h=float(tpl.shape[0]),
                           still_kind=kind,
                           zoom=(zoom if zoom.measured
                                 else Zoom(scale=float(s), measured=False,
                                           pitch_mosaic=zoom.pitch_mosaic,
                                           angle_mosaic=zoom.angle_mosaic, note=zoom.note)),
                           outcome=out)
            if best is None or _rank(here) > _rank(best):
                best = here

    if best is None:
        raise NoLocation(
            "none of the pictures built from this recording could be placed on the mosaic — "
            "the field may sit outside the surveyed area, or the recording may be too "
            "different from the survey to match")
    best.tried = tried

    # ⭐ The FFT gave a ruler; the pixels give the micrometer. Two narrowing rounds — the
    # first catches the few-percent bin error, the second settles it — each re-snapping the
    # position at the new size so scale and place converge together rather than fighting.
    # Measured on the synthetic scene: 0.4116 -> 0.4013 (truth 0.4000), NCC 0.814 -> 0.918,
    # and the corner from ~7 px out to sub-pixel.
    # ⚠️ The refinement runs on the UN-notched pictures. Inside a bounded window there is no
    # alias left to kill, and the grid is the sharpest, highest-contrast detail in the frame —
    # exactly what settles the last fraction of a pixel. Notching there would throw away the
    # signal that makes the answer precise, having already served its purpose upstream.
    say("verifying the scale")
    still = stills[best.still_kind]
    scale = best.zoom.scale
    at, size = (best.x, best.y), (best.w, best.h)
    for span, steps, radius in ((0.10, 11, 40), (0.02, 9, 12)):
        s2, out2, hw = refine_scale(ref, refmask, still, scale, at, size,
                                    span=span, steps=steps, radius=radius)
        if out2.best is None:
            break
        scale, at, size = s2, (out2.best.x, out2.best.y), (float(hw[1]), float(hw[0]))
    spent = best.outcome.elapsed_ms

    # 🔴 THE MARGIN MUST BE MEASURED ON THE SURFACE THE WINNER WON ON. The first pass scored
    # every candidate at the FFT's few-percent-wrong scale, where the true place is blurred and
    # the aliases are not — so its `best - second` understates the gap and would flag a
    # perfectly good placement as thin (0.064 vs 0.16 measured on the synthetic scene). A
    # re-scored runner-up is not a cosmetic improvement, it is the difference between reporting
    # "confident" and reporting "check this", which is the one number the user acts on.
    say("re-scoring the alternatives")
    tpl, tmsk = prepare_template(still, scale)
    final = match(ref_g, refmask, notched(tpl, None), tmsk, max_candidates=max_candidates)
    if final.best is None:
        # the refinement moved off a measurable spot: keep the first pass rather than nothing
        return best

    # Settle the corner on the un-notched picture, seeded at the answer the notched search
    # committed to. A tight radius: this is the last fraction of a pixel, not a search.
    settled = snap(ref, refmask, tpl, tmsk, (final.best.x, final.best.y), radius=12)
    fx, fy = ((settled.best.x, settled.best.y) if settled.best is not None
              else (final.best.x, final.best.y))
    cands = [Candidate(rank=0, x=fx, y=fy, ncc=final.best.ncc, npix=final.best.npix,
                       subpixel=True)] + list(final.candidates[1:])
    return Located(x=fx, y=fy,
                   w=float(tpl.shape[1]), h=float(tpl.shape[0]),
                   still_kind=best.still_kind,
                   zoom=Zoom(scale=scale, measured=best.zoom.measured,
                             pitch_recording=best.zoom.pitch_recording,
                             pitch_mosaic=best.zoom.pitch_mosaic,
                             angle_recording=best.zoom.angle_recording,
                             angle_mosaic=best.zoom.angle_mosaic,
                             note=best.zoom.note),
                   outcome=MatchOutcome(
                       candidates=cands, margin=final.margin,
                       margin_thin=final.margin_thin,
                       elapsed_ms=spent + final.elapsed_ms + settled.elapsed_ms),
                   tried=tried)


def _rank(loc: Located) -> tuple:
    """Sort key: margin first (see `locate`), NCC only to break a tie."""
    m = loc.outcome.margin if loc.outcome.margin is not None else -1.0
    n = loc.outcome.best.ncc if loc.outcome.best else -1.0
    return (round(float(m), 4), float(n))


class NoLocation(ValueError):
    """The recording could not be placed, with the reason in one sentence (it surfaces as the
    job's error message). ⭐ Refusing is a correct outcome — a hallucinated location that names
    the wrong electrodes is far more expensive than a sentence saying it could not tell."""


__all__ = [
    "Candidate", "LOCATE_STEPS", "Located", "MARGIN_THIN", "MAX_CANDIDATES", "MatchOutcome",
    "NCC_MIN", "NoLocation", "SNAP_RADIUS", "SNAP_RADIUS_MAX", "STILL_KINDS", "Zoom",
    "locate", "match", "measure_zoom", "prepare_reference", "prepare_template",
    "sample_indices", "scale_ladder", "snap", "still_stack", "subpixel",
]
