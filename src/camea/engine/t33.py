"""T33 — the placement method that solved BOTH passes. Standalone, any two-pass range.

WHAT THIS IS
------------
`place(trials, frames)` takes a stack of 512x512 snapshots spanning TWO serpentine scans of
the same tissue (in acquisition order) and returns `{trial: (x, y)}`. It is the exact method
shipped as the `260620d__T33_composite_aperture_v3` build — the first to place all 312 usable
snapshots of 11-348 within 10 px of the human ground truth — lifted out of the challenge
harness (`analysis/builds/challenge/challenge_lib.py`) so that it runs on any set of
snapshots instead of only the benchmark's trials. Nothing about the maths changed.

`t27.place` solves ONE serpentine scan (pass 1: 156/156). Run it on the merged 11-348 range
and it gets 39.7 %. T33 is the answer to *why*, and it is one idea.

⭐ THE IDEA: AN APERTURE, NOT A PAIR
------------------------------------
Registering two 512x512 tiles is registering a ~77 kpx overlap. At that aperture the data
cannot tell the truth from its aliases:
  * the electrode grid is periodic at 256 px, so a shift of (dx, dy) and a shift of
    (dx +/- 256, dy +/- 256) look almost equally good;
  * a 512 px correlogram wraps around, manufacturing a +/-512 rival;
  * and tissue is self-similar, so somewhere else on the sample there is a patch that
    genuinely does look like this one.
Pass 1 survives that because its serpentine prior (t27, idea 2) collapses the search to two
thin lines. Pass 2 must be tied to pass 1 across a jump the prior says nothing about, so it
has no such crutch — and pairwise SWIM confidently returns the wrong peak. Every method that
tried to bridge the two passes tile-by-tile lost to that alias, at high NCC, without
complaint. Confidence is not the problem. The APERTURE is.

So: don't ask a tile. Ask the whole picture.

  1. Pass 1 is already solved, so FREEZE it: render its 156 tiles into ONE rigid ~7 Mpx
     composite image with a validity mask. That composite is now an ABSOLUTE reference field
     — a coordinate system, not a tile.
  2. Cut pass 2 into RIGID RUNS (stretches whose internal geometry is trustworthy), render
     each run to its OWN composite, and match run-vs-pass-1 by masked NCC over the WHOLE
     plane.

A 0.26-2.4 Mpx aperture against a 7 Mpx field is a different measurement from a 77 kpx one.
The alias lattice is still there, but a +/-256 px displacement now has to explain *millions*
of pixels of tissue instead of tens of thousands — and it cannot. The rivals collapse; the
margin between the best peak and the second is large and honest. The cross-pass tie is then
whatever those matches say: DERIVED from the pixels, never typed in.

THE SECOND IDEA: THE RUN STRUCTURE IS MEASURED, NOT THRESHOLDED
---------------------------------------------------------------
v1 of this method cut pass 2 into runs wherever a consecutive step's NCC fell below a
data-derived floor, and scored 306/312. Its 6 survivors were all at the TAIL of a run: the
run OFFSETS were all right, and the damage was a bad step INSIDE a run that passed the NCC
gate anyway (notably 204->205, a freak (323.6, -228.8) step at high confidence) and that the
chain then integrated straight through. A threshold cannot catch a confident lie.

The aperture can, one level down. Once pass 1 is frozen, EVERY pass-2 tile can be matched
against it individually — a 262 kpx aperture, still far too big for a +/-256 alias to
survive — giving that tile an ABSOLUTE position (its "anchor"). For a run that really is
rigid, the implied run origin

        o_t  =  anchor_t  -  (local_t - m0)

is the SAME for every tile in the run. Where o_t JUMPS, the chain is broken. That is a
MEASUREMENT, not a threshold. Split the run there, re-render, re-match.

THE TRAP IN THAT FIX (and it cost a tile)
-----------------------------------------
One anchor can be wrong. If a lone bad anchor is allowed to cut a chain, the method invents a
run boundary and breaks a tile that was fine (v2 split 311->312 off the strength of a single
bad anchor at the head of a run — its only miss). So a CUT needs a quorum: >= MIN_SIDE
agreeing anchors on BOTH sides. A single disagreeing anchor is an OUTLIER TO DISCARD, not a
cut.

⚠ AND THE QUORUM MUST BE CAPPED BY THE WITNESSES THAT EXIST. Uncapped, the rule can demand
more corroborating anchors than a side physically has — the tail after the 190->191 split is
EXACTLY 2 tiles, so a quorum of 3 is unsatisfiable there and the cut gets refused for want of
witnesses that cannot exist. That made MIN_SIDE=2 look like a magic number tuned to the
answer (1 -> 311/312, 3 -> 310/312). It is not: cap the demand at the available population and
MIN_SIDE = 2, 3, 4, 5, 8 ALL give 312/312. The rule does not rest on a lucky integer.

WHAT IT ASSUMES (read before running it on a new range)
------------------------------------------------------
  * `trials` spans TWO passes over the SAME tissue, in acquisition order, split at
    `cfg.pass_split` (the last trial of pass 1). Pass 1 must be solvable by t27 alone — it is
    the frozen reference, and if it is wrong, everything hangs off a wrong field.
  * The two passes OVERLAP substantially. The whole method is "find pass 2's runs inside pass
    1's picture"; if the scans cover different tissue there is nothing to find.
  * Trial numbers are acquisition order but NOT necessarily contiguous — on 260620d, 26
    snapshots are thrown out, opening gaps at 283->297 and 298->311. A "consecutive" pair
    across a gap is a multi-step jump, so it is NEVER a serpentine step and is always a run
    boundary. `place()` detects this from the trial numbers; do not assume it away.
  * Pass 1's tiles are NEVER MOVED. They come out exactly as t27 placed them. That is the
    control: if a merged build's pass-1 subset degrades, the merge broke something.

GPU: uses CuPy through `t27.xp()` when it is importable, NumPy otherwise (same numbers, a lot
slower). Quiet by default; `Config(verbose=True)` reproduces the challenge build's full log.
"""
import hashlib
import json
import os
import time
from contextlib import contextmanager, redirect_stdout
from io import StringIO
from pathlib import Path

import numpy as np

from . import t27

# --- fixed by the imaging, not by the trial range -------------------------------------
TILE = 512
EPS32 = np.float32(1e-30)     # GPUs flush denormals: 1e-40 -> 0 -> 0**neg -> inf -> NaN


class Config:
    """T33's knobs. The defaults are the ones that produced the shipped build.

    (The challenge script spelled these ANCHOR_NCC / SPLIT_PX / LOOK / MIN_SIDE. Same values,
    house naming.)
    """

    def __init__(self, **kw):
        self.pass_split = 166   # LAST TRIAL OF PASS 1. Everything <= this is the frozen
                                # reference pass; everything above it is placed against it.
                                # This is the one number the method cannot measure for itself
                                # — it is a fact about the acquisition, so the CALLER supplies
                                # it. Do not bury it in the body.
        self.anchor_ncc = 0.30  # a per-tile composite anchor must reach this masked NCC to vote
        self.split_px = 12.0    # a jump in the implied run origin bigger than this = broken chain
        self.look = 3           # how far ahead we look for anchors corroborating a candidate cut
        self.min_side = 2       # a CUT needs >= this many agreeing anchors on BOTH sides, capped
                                # by the witnesses that physically exist. See the module docstring.
        self.t27 = None         # the t27.Config for the two sub-solves. None -> Config(control=False):
                                # the stride-2 full-plane control is an honesty check on t27's
                                # serpentine prior, and it is expensive; T33 runs t27 twice.
        self.verbose = False    # True reproduces the challenge build's log, line for line
        for k, v in kw.items():
            if not hasattr(self, k):
                raise TypeError(f"unknown T33 config knob: {k!r}")
            setattr(self, k, v)

    def t27_config(self):
        return self.t27 if self.t27 is not None else t27.Config(control=False)

    def __repr__(self):
        return "Config(" + ", ".join(f"{k}={v}" for k, v in vars(self).items()) + ")"


# =============================================================================
# Plumbing: logging, hushing t27, cache paths
# =============================================================================
def _logger(verbose, t0):
    if not verbose:
        return lambda *a: None

    def log(*a):
        print(f"[{time.time() - t0:7.1f}s]", *a, flush=True)
    return log


@contextmanager
def _hush(verbose):
    """t27 narrates every step to stdout. That is right for `t27.place`, but T33 calls it
    twice as a subroutine, so by default we swallow it and let `cfg.verbose` decide."""
    if verbose:
        yield
    else:
        with redirect_stdout(StringIO()):
            yield


def _tag(trials):
    """The trial-set part of a cache name: (first, last, n, **hash of the membership**).

    ⚠ (first, last, n) IS NOT A KEY — it names a RANGE, and what the cache is a function of is a
    SET. Exclude trial 100 from 11-348 and exclude trial 150 instead, and both give
    `trials_011-347_n311`: two different tile sets, one filename, and `_load_checked` only refuses a
    mismatched CONFIG — never a mismatched membership. The raw SWIM bank, the pass-1 layout, the
    pass-2 backbone and the per-tile anchors would all be silently reused across two different
    problems, and `engine.read_anchors` maps anchors back to trials by INDEX ORDER behind nothing
    but a length check, so the anchor NCCs would attach to the WRONG TILES.

    It was unreachable only while the app's build ignored the user's exclusions. It is reachable now
    that it does not, and this is the same bug class `_cache_key` (below) already shipped once — "the
    lie with a plausible mtime". The hash costs nothing; a stale hit costs the result.

    (Changing the name orphans any cache file written before this fix. That is harmless — they are
    recomputed — and it is far cheaper than reading one of them back.)
    """
    ts = [int(t) for t in trials]
    h = hashlib.sha1(",".join(str(t) for t in ts).encode("utf-8")).hexdigest()[:8]
    return f"trials_{ts[0]:03d}-{ts[-1]:03d}_n{len(ts)}_{h}"


def _cache_key(cfg):
    """The CONFIG the cached T33 arrays are a function of -> (json text, short hash).

    ⚠ THE TRIAL RANGE IS NOT A SUFFICIENT CACHE KEY, and believing it was is a bug this module
    shipped with. `T33_backbone_*.npz` holds L1 (t27's pass-1 layout), the pass-2 backbone
    (fsx/fsy/fncc/step2) and cut_thr; `T33_anchors_*.npz` holds anchors matched against the
    composite built FROM L1. Every one of those numbers depends on `cfg.t27` (conf, run_conf,
    span, gain, gate_tol, r_drop, null_q, null_n, seed, ...) and on `cfg.pass_split` (which
    decides who is even IN each pass). Keyed by the range alone, a warm cache would skip the
    recompute entirely and hand back the OLD answer while `info["config"]` — and the notebook's
    results.json — reported the NEW knobs. Silently. That is the lie with a plausible mtime.

    So the key is (pass_split, the whole t27 sub-config). It is deliberately the WHOLE t27
    config rather than the subset provably read: `control` is print-only today, and a key that
    depends on which knobs happen to be inert is a key that rots. A needless recompute costs
    minutes; a stale one costs the result.

    T33's OWN knobs (anchor_ncc, split_px, look, min_side) are NOT in the key, because they are
    applied to the anchors AFTER they are loaded — nothing cached is a function of them. If you
    ever make one of them feed the backbone or the anchors, put it in here.
    """
    payload = json.dumps(
        {"pass_split": int(cfg.pass_split),
         "t27": {k: (v if isinstance(v, (bool, int, float, str)) or v is None else repr(v))
                 for k, v in sorted(vars(cfg.t27_config()).items())}},
        sort_keys=True)
    return payload, hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]


def _cache_path(cache, name):
    if cache is None:
        return None
    d = Path(cache)
    d.mkdir(parents=True, exist_ok=True)
    return d / name


def _load_checked(path, key):
    """Load a T33 cache file, but REFUSE it unless it was written by this exact config.

    The hash is already in the filename, so a mismatch here should be unreachable — which is
    precisely why it is worth asserting. It turns a hash collision, a hand-edited file or a
    half-migrated cache dir into a loud refusal instead of a wrong mosaic. Belt to the
    filename's braces; the failure this guards against is silent by nature.
    """
    z = np.load(path)
    got = str(z["key"]) if "key" in z.files else None
    if got != key:
        raise RuntimeError(
            f"{path.name} was written by a DIFFERENT config than the one you just asked for, so "
            f"reusing it would answer a question you did not ask.\n"
            f"  cached:    {got}\n"
            f"  requested: {key}\n"
            f"Delete that file (or point `cache=` at a fresh directory) and re-run.")
    return z


def breaks(trials, pass_split):
    """Every place the acquisition chain is NOT one serpentine step: [(row, ta, tb, why)].

    Three kinds, and they are the #1 silent build-killer: the PASS BOUNDARY (the stage went
    back to the start and re-scanned — not a serpentine step at all), and each EXCLUSION GAP
    (a thrown-out snapshot means the two survivors either side of it are several acquisition
    steps apart). The one-axis step prior does not hold across any of them, so every one of
    them is an unconditional run boundary.
    """
    out = []
    for i in range(len(trials) - 1):
        a, b = int(trials[i]), int(trials[i + 1])
        pa = 1 if a <= pass_split else 2
        pb = 1 if b <= pass_split else 2
        if pa != pb:
            out.append((i, a, b, "pass boundary — the scan restarted; not a serpentine step"))
        elif b != a + 1:
            out.append((i, a, b, f"exclusion gap — {b - a} acquisition steps, not 1"))
    return out


# =============================================================================
# THE COMPOSITE — a set of placed tiles rendered into ONE image + its validity mask
# =============================================================================
_FEATHER = {}


def feather(h=TILE, w=TILE):
    """A bilinear tent, floored away from zero. Tiles overlap; a hard-edged paste leaves a
    seam at every join, and a seam is a strong edge that the correlator will happily lock
    onto. Weighting each tile by its distance from its own centre puts the joins where the
    data is weakest and makes the composite read as one continuous field."""
    if (h, w) not in _FEATHER:
        yy, xx = np.mgrid[0:h, 0:w]
        f = (1 - np.abs(xx - (w - 1) / 2) / ((w - 1) / 2)) * \
            (1 - np.abs(yy - (h - 1) / 2) / ((h - 1) / 2))
        _FEATHER[(h, w)] = np.clip(f, 1e-3, None).astype(np.float32)
    return _FEATHER[(h, w)]


def composite(B, rows, local):
    """Render band-passed tiles `B[rows]` at positions `local` -> (img, mask, m0).

    `m0` is the corner the layout was shifted by, so a tile's position inside the composite is
    `local - m0` and its position in the composite's parent frame is recoverable. The image is
    mean-subtracted OVER THE VALID MASK ONLY (an unmasked mean would be dragged by the zeros
    outside the footprint, and every NCC downstream would be biased by the shape of the hull).
    """
    fe = feather()
    m0 = local.min(0)
    P = np.rint(local - m0).astype(int)
    Wc, Hc = int(P[:, 0].max()) + TILE, int(P[:, 1].max()) + TILE
    acc = np.zeros((Hc, Wc), np.float32)
    wsum = np.zeros((Hc, Wc), np.float32)
    for k, (x, y) in enumerate(P):
        acc[y:y + TILE, x:x + TILE] += B[rows[k]] * fe
        wsum[y:y + TILE, x:x + TILE] += fe
    msk = wsum > 0
    img = np.where(msk, acc / np.maximum(wsum, 1e-6), 0.0).astype(np.float32)
    img = np.where(msk, img - img[msk].mean(), 0.0).astype(np.float32)
    return img, msk, m0


# =============================================================================
# THE MATCHER — masked NCC over the whole plane, between two arbitrary-sized images
# =============================================================================
def _smooth(n):
    """The next 2-3-5-smooth integer >= n. FFTs of an awkward size are orders of magnitude
    slower; the composites are megapixels, so this is not a micro-optimisation."""
    while True:
        m = n
        for p in (2, 3, 5):
            while m % p == 0:
                m //= p
        if m == 1:
            return n
        n += 1


def _pool(img, msk, ds):
    """Box-downsample an image AND its mask by `ds`. The coarse pass only has to get us
    within +/- ds px; the exact-NCC refinement below does the rest. A pooled pixel is valid
    only if at least half its sources were — otherwise the ragged boundary of the footprint
    leaks zeros into the correlation."""
    if ds == 1:
        return img.astype(np.float32), msk.astype(np.float32)
    h, w = img.shape
    H2, W2 = h // ds, w // ds
    a = (img * msk)[:H2 * ds, :W2 * ds].reshape(H2, ds, W2, ds).sum((1, 3))
    m = msk.astype(np.float32)[:H2 * ds, :W2 * ds].reshape(H2, ds, W2, ds).sum((1, 3))
    mm = (m >= (ds * ds) * 0.5).astype(np.float32)
    return (np.where(m > 0, a / np.maximum(m, 1e-6), 0.0) * mm).astype(np.float32), mm


def _surfaces(A, MA, Bi, MB, N0, N1):
    """The three whole-plane surfaces, in one pass of FFTs: masked NCC, the overlap count
    n(s), and a phase-correlation surface.

    MASKED NCC IS THE POINT. Two composites are ragged, partially-overlapping footprints, so
    an ordinary NCC would divide by statistics gathered over pixels that do not exist. Every
    sum here is therefore taken through the mask (Sa, Sa2, Sb, Sb2, n all vary with the shift
    s, and are themselves correlations), which is what makes a shift comparable to a shift
    that overlaps a different amount of the plane.

    The phase-correlation surface rides along because it is nearly free and it peaks
    differently: NCC likes broad agreement, PC likes sharp structure. Feeding both peak lists
    into the refinement means a candidate that either one finds gets a fair hearing.
    """
    x = t27.xp()
    s = (N0, N1)
    FA = x.fft.rfft2(x.asarray(A * MA), s=s).astype("complex64")
    FA2 = x.fft.rfft2(x.asarray(A * A * MA), s=s).astype("complex64")
    FMA = x.fft.rfft2(x.asarray(MA), s=s).astype("complex64")
    FB = x.fft.rfft2(x.asarray(Bi * MB), s=s).astype("complex64")
    FB2 = x.fft.rfft2(x.asarray(Bi * Bi * MB), s=s).astype("complex64")
    FMB = x.fft.rfft2(x.asarray(MB), s=s).astype("complex64")
    t27._free()

    def C(P, Q):
        return x.fft.irfft2(P * x.conj(Q), s=s)

    n = x.maximum(C(FMA, FMB), 0)
    nz = x.maximum(n, 1.0)
    Sa = C(FA, FMB)
    Sa2 = C(FA2, FMB)
    del FA2
    Sb = C(FMA, FB)
    Sb2 = C(FMA, FB2)
    del FB2
    Cab = C(FA, FB)
    va = x.maximum(Sa2 - Sa * Sa / nz, 0)
    del Sa2
    vb = x.maximum(Sb2 - Sb * Sb / nz, 0)
    del Sb2
    den = x.sqrt(va * vb)
    del va, vb
    ncc = x.where(den > 1e-3, (Cab - Sa * Sb / nz) / x.maximum(den, 1e-3), -1.0)
    del Sa, Sb, Cab, den, nz
    prd = FA * x.conj(FB)
    pw = (prd.real ** 2 + prd.imag ** 2) + EPS32
    prd = prd * (pw ** (t27.WHT / 2)).astype("float32")
    PC = x.fft.irfft2(prd, s=s)
    del prd, pw, FA, FB, FMA, FMB
    out = (t27._np(ncc), t27._np(n), t27._np(PC))
    del ncc, n, PC
    t27._free()
    return out


def _peaks(S, valid, k, nms):
    """The k best DISTINCT peaks of a surface (greedy argmax + non-maximum suppression). A
    correlation peak is several px wide, so without NMS 'the top 10 peaks' would be ten
    pixels of the same peak and we would never see the runner-up we need for a margin."""
    flat = np.where(valid, S, -np.inf).astype(np.float32)
    H, W = S.shape
    out = []
    for _ in range(k):
        i = int(np.argmax(flat))
        if not np.isfinite(float(flat.ravel()[i])):
            break
        y, x = divmod(i, W)
        out.append((y, x))
        flat[max(0, y - nms):y + nms + 1, max(0, x - nms):x + nms + 1] = -np.inf
    return out


def exact_ncc(A, MA, Bi, MB, dx, dy, stride=1):
    """The exact masked NCC of two images at ONE integer offset (dx, dy) = originB - originA.

    This is the arbiter. The FFT surfaces above are how we find candidates; this is how we
    RANK them, because it is computed in the spatial domain with no wraparound, no
    downsampling and no smoothing. `stride` subsamples for speed during the coarse tiers —
    the winner is always re-scored at stride 1.
    """
    HA, WA = A.shape
    HB, WB = Bi.shape
    ax0, ax1 = max(0, dx), min(WA, WB + dx)
    ay0, ay1 = max(0, dy), min(HA, HB + dy)
    if ax1 - ax0 < 64 or ay1 - ay0 < 64:
        return np.nan, 0
    a = A[ay0:ay1:stride, ax0:ax1:stride]
    b = Bi[ay0 - dy:ay1 - dy:stride, ax0 - dx:ax1 - dx:stride]
    m = MA[ay0:ay1:stride, ax0:ax1:stride] & MB[ay0 - dy:ay1 - dy:stride, ax0 - dx:ax1 - dx:stride]
    nn = int(m.sum())
    if nn < 3000:
        return np.nan, nn
    am, bm = a * m, b * m
    sa = float(am.sum(dtype=np.float64))
    sb = float(bm.sum(dtype=np.float64))
    va = float((am * am).sum(dtype=np.float64)) - sa * sa / nn
    vb = float((bm * bm).sum(dtype=np.float64)) - sb * sb / nn
    if va <= 0 or vb <= 0:
        return np.nan, nn
    sab = float((am * bm).sum(dtype=np.float64))
    return float((sab - sa * sb / nn) / np.sqrt(va * vb)), nn * stride * stride


def _sig(idx, N, ext):
    """An FFT correlation index is unsigned and wraps; turn it back into a signed shift."""
    return idx if idx < ext else idx - N


def match(A, MA, Bi, MB, kpk=10, minfrac=0.10, minabs=40000.0):
    """Register image B against image A over the WHOLE PLANE. -> [(ncc, dx, dy, npix)], best
    first, distinct peaks only. `(dx, dy) == originB - originA`.

    THIS FUNCTION IS THE APERTURE. There is no search window and no prior: B is slid over
    every relative position of A that shares enough pixels to be measurable, and the masked
    NCC decides. That is affordable only because it is an FFT, and it is *trustworthy* only
    because the images are big — a 512x512 tile matched this way would come back with a
    confident +/-256 alias, which is exactly the failure this whole module exists to escape.

    Three tiers, each narrower and more exact than the last:
      A. coarse (downsampled by 2 or 4) FFT surfaces -> candidate peaks, re-scored by
         `exact_ncc` at stride 4 over the +/-ds neighbourhood the pooling could have hidden;
      B. the best 4 survivors, exhaustively searched at +/-ds and stride 2;
      C. the winner polished at +/-3 px, stride 1 — the number we report.

    `minfrac`/`minabs` set how much overlap a shift must have before it may win at all. A
    shift with a sliver of overlap can score a beautiful NCC on 40 pixels of noise; this is
    the guard against it. (Anchoring a single TILE uses minfrac=0, minabs=120000: a tile is
    small enough that a fractional rule would let a corner match win, so the floor is
    absolute — roughly half a tile of real overlap.)

    Returning the runner-up matters as much as the winner: `best - second` is the MARGIN, and
    it is the only evidence we have that the aperture actually killed the aliases rather than
    merely outscoring them by a whisker.
    """
    ds = 2 if max(A.shape + Bi.shape) <= 4200 else 4
    Ad, MAd = _pool(A, MA, ds)
    Bd, MBd = _pool(Bi, MB, ds)
    ha, wa = Ad.shape
    hb, wb = Bd.shape
    N0, N1 = _smooth(ha + hb), _smooth(wa + wb)
    ncc, n, PC = _surfaces(Ad, MAd, Bd, MBd, N0, N1)
    nmin = max(minfrac * min(MAd.sum(), MBd.sum()), minabs / (ds * ds))
    valid = n >= nmin
    if not valid.any():
        return []
    pk = _peaks(ncc, valid, kpk, max(8, 96 // ds)) + _peaks(PC, valid, 5, max(8, 96 // ds))
    del ncc, n, PC

    tierA = []
    for (yi, xi) in pk:
        cy, cx = _sig(yi, N0, ha) * ds, _sig(xi, N1, wa) * ds
        bv, bxy = -2.0, (cx, cy)
        for ey in (-ds, 0, ds):
            for ex in (-ds, 0, ds):
                v, _ = exact_ncc(A, MA, Bi, MB, cx + ex, cy + ey, stride=4)
                if np.isfinite(v) and v > bv:
                    bv, bxy = v, (cx + ex, cy + ey)
        if bv > -2:
            tierA.append((bv, bxy[0], bxy[1]))
    if not tierA:
        return []
    tierA.sort(key=lambda z: -z[0])

    tierB = []
    for (_, cx, cy) in tierA[:4]:
        best = (-2.0, cx, cy, 0)
        for ey in range(-ds, ds + 1):
            for ex in range(-ds, ds + 1):
                v, nn = exact_ncc(A, MA, Bi, MB, cx + ex, cy + ey, stride=2)
                if np.isfinite(v) and v > best[0]:
                    best = (v, cx + ex, cy + ey, nn)
        if best[0] > -2:
            tierB.append(best)
    if not tierB:
        return []
    tierB.sort(key=lambda z: -z[0])

    def polish(cx, cy):
        best = (-2.0, cx, cy, 0)
        for ey in range(-3, 4):
            for ex in range(-3, 4):
                v, nn = exact_ncc(A, MA, Bi, MB, cx + ex, cy + ey, stride=1)
                if np.isfinite(v) and v > best[0]:
                    best = (v, cx + ex, cy + ey, nn)
        return best

    win = polish(tierB[0][1], tierB[0][2])
    out = [win]
    for s in tierB[1:]:
        if np.hypot(s[1] - win[1], s[2] - win[2]) > 24:
            out.append(polish(s[1], s[2]))
    for s in tierA:
        if all(np.hypot(s[1] - o[1], s[2] - o[2]) > 24 for o in out):
            out.append((s[0], s[1], s[2], 0))
    return out


# =============================================================================
# STEP 2 — the pass-2 backbone and its FIRST cut (t27's machinery, pass 2 alone)
# =============================================================================
def pass2_backbone(cfg, B2, p2_trials, swim_cache=None):
    """The N-1 consecutive shifts of pass 2, corrected by t27's exhaustive axis-manifold
    search -> (fsx, fsy, fncc, step, cut_thr).

    This is `t27.place`'s STEP 1 + STEP 2, on pass 2 alone, and NOT its solve: we want pass
    2's chain, not pass 2's global layout (a global least-squares over pass 2 alone is exactly
    what scores 37 %). `step[k]` is False where the trial numbers are not contiguous — the
    exclusion gaps. Those steps are never given to `precheck`/`fix_backbone`, because they are
    not serpentine steps and the one-axis prior would be measuring a jump.

    `cut_thr` is DERIVED, not chosen: the higher of t27's run-confidence floor and the
    permutation null (what a random pair of these tiles scores when it is definitely wrong).
    """
    c27 = cfg.t27_config()
    ii2, jj2, sh2 = t27.swim_all(B2, cache=swim_cache)
    bank2 = t27.NccBank(B2)
    bank2.validate(ii2, jj2)
    sx2, sy2, ncc2, good2, _ = t27.dealias(bank2, ii2, jj2, sh2)

    cons2 = np.where(jj2 == ii2 + 1)[0]
    ci2, cj2 = ii2[cons2], jj2[cons2]
    step = np.array([(p2_trials[k + 1] == p2_trials[k] + 1)
                     for k in range(len(p2_trials) - 1)], bool)
    g = np.where(step)[0]

    dsx, dsy, dncc = sx2[cons2].copy(), sy2[cons2].copy(), ncc2[cons2].copy()
    band, _ = t27.precheck(c27, p2_trials, ci2[g], cj2[g], dsx[g], dsy[g], dncc[g])
    a_, b_, c_, _ = t27.fix_backbone(c27, bank2, p2_trials, ci2[g], cj2[g],
                                     dsx[g], dsy[g], dncc[g], band)
    fsx, fsy, fncc = dsx.copy(), dsy.copy(), dncc.copy()
    fsx[g], fsy[g], fncc[g] = a_, b_, c_

    floor2 = t27.permutation_floor(c27, bank2, ii2, jj2, sx2, sy2)
    cut_thr = max(floor2, c27.run_conf)
    del bank2
    t27._free()
    return fsx, fsy, fncc, step, float(cut_thr)


def make_runs(brk, n):
    """Split 0..n-1 into maximal runs, cutting wherever `brk[k]` marks the step k -> k+1 as
    broken. A RUN is a stretch of pass 2 whose internal geometry we are prepared to treat as
    rigid — it is what gets rendered to a composite and placed as one object."""
    out, cur = [], [0]
    for k in range(n - 1):
        if brk[k]:
            out.append(cur)
            cur = []
        cur.append(k + 1)
    out.append(cur)
    return out


def chain(runs, fsx, fsy, n):
    """Accumulate each run's steps from its own first tile -> (n,2) LOCAL positions. Every run
    starts at (0,0) in its own frame; the runs are tied to each other only by pass 1, later."""
    loc = np.zeros((n, 2))
    for r in runs:
        c = np.zeros(2)
        loc[r[0]] = c
        for q in range(len(r) - 1):
            c = c + np.array([fsx[r[q]], fsy[r[q]]])
            loc[r[q + 1]] = c
    return loc


# =============================================================================
# THE METHOD, end to end
# =============================================================================
def place(trials, frames, cfg=None, cache=None):
    """Place `frames` (N,512,512 raw, acquisition order, TWO passes) -> (pos, info).

    `trials` — the usable trial ids in ACQUISITION ORDER (get them from
        `analysis/ground_truth/excluded.py :: usable_trials`; never hard-code a range).
        Row i of `frames` IS trial `trials[i]`.
    `cfg`   — a `t33.Config`. `cfg.pass_split` (default 166) is the last trial of pass 1.
    `cache` — a DIRECTORY. Cold (None or empty) it computes everything from the pixels; warm
        it reuses the two all-pairs SWIM banks, the pass-1 layout + pass-2 backbone, and the
        per-tile anchors. Every cache file carries the trial range AND a hash of the config it
        was computed under in its NAME (and the config itself inside it — a mismatched load is
        refused, not repaired). CHANGE A KNOB AND YOU GET A RECOMPUTE, not last run's answer
        wearing this run's config. See `_cache_key`.

    Returns `pos` = {trial: array([x, y])} and an `info` dict: the runs and where each landed,
    the cuts (which came from the NCC floor, which from the aperture), the anchor statistics,
    the margin table, the derived cross-pass tie, and the pass-1 control deviation.

    ⚠ THE PASS-1 CONTROL. Pass-1 tiles come out EXACTLY as `t27.place` put them — the merge
    cannot move them, by construction, and `info["pass1_max_dev"]` proves it (0.000000 px). If
    you ever see that number drift, a "global solve over everything" has crept back in, and it
    is letting pass 2's links vote on pass-1 tiles. That is the mistake this design forbids.
    """
    cfg = cfg or Config()
    trials = [int(t) for t in trials]
    frames = np.asarray(frames)
    n = len(trials)
    if n != len(frames):
        raise ValueError(f"{n} trials but {len(frames)} frames")
    if list(trials) != sorted(set(trials)):
        raise ValueError("trials must be unique and in ascending acquisition order")

    p1t = [t for t in trials if t <= cfg.pass_split]
    p2t = [t for t in trials if t > cfg.pass_split]
    if len(p1t) < 4 or len(p2t) < 2:
        raise ValueError(
            f"pass_split={cfg.pass_split} gives {len(p1t)} pass-1 and {len(p2t)} pass-2 "
            f"snapshots. T33 places pass 2 AGAINST pass 1; it needs a solvable reference pass "
            f"and something to place on it. For a single scan, use t27.place.")

    t0 = time.time()
    log = _logger(cfg.verbose, t0)
    ti = {t: i for i, t in enumerate(trials)}
    r1 = np.array([ti[t] for t in p1t])
    r2 = np.array([ti[t] for t in p2t])
    tag = _tag(trials)
    key, khash = _cache_key(cfg)      # the CONFIG the cached arrays depend on. See _cache_key.

    log(f"{n} tiles; pass 1 = {len(p1t)}, pass 2 = {len(p2t)}")
    for row, a, b, why in breaks(trials, cfg.pass_split):
        log(f"   BREAK row {row}: {a} -> {b}   ({why})")

    with _hush(cfg.verbose):
        B = t27.band_pass(frames)                   # DoG 3-30: the representation we match on

    # -------------------------------------------------------------------------------------
    # 1 + 2. PASS 1 frozen; PASS 2 backbone -> the FIRST cut (t27's NCC threshold). Cached.
    # -------------------------------------------------------------------------------------
    bcache = _cache_path(cache, f"T33_backbone_{tag}_{khash}.npz")
    if bcache is not None and bcache.exists():
        z = _load_checked(bcache, key)
        L1, fsx, fsy, fncc = z["L1"], z["fsx"], z["fsy"], z["fncc"]
        step2 = z["step2"].astype(bool)
        cut_thr = float(z["cut_thr"])
        if L1.shape[0] != len(p1t) or len(fsx) != max(len(p2t) - 1, 0):
            raise RuntimeError(
                f"{bcache.name} holds a {L1.shape[0]}-tile pass 1 and a {len(fsx)}-step pass-2 "
                f"backbone, but this call wants {len(p1t)} and {len(p2t) - 1}. The cache does not "
                f"describe this problem — delete it and re-run.")
        log(f"loaded the cached pass-1 layout + pass-2 backbone from {bcache.name}")
    else:
        log("=" * 90)
        log("STEP 1 — PASS 1 solved ALONE by t27 (frozen; nothing can move a pass-1 tile)")
        log("=" * 90)
        p1c = _cache_path(cache, f"swim_all_{_tag(p1t)}.npz")
        with _hush(cfg.verbose):
            P1, _ = t27.place(p1t, frames[r1], cfg=cfg.t27_config(),
                              swim_cache=None if p1c is None else str(p1c))
        L1 = np.array([P1[t] for t in p1t], float)
        t27._free()

        log("=" * 90)
        log("STEP 2 — PASS 2 backbone (t27 machinery, pass 2 alone)")
        log("=" * 90)
        p2c = _cache_path(cache, f"swim_all_{_tag(p2t)}.npz")
        with _hush(cfg.verbose):
            fsx, fsy, fncc, step2, cut_thr = pass2_backbone(
                cfg, B[r2], p2t, swim_cache=None if p2c is None else str(p2c))
        if bcache is not None:
            np.savez_compressed(bcache, L1=L1, fsx=fsx, fsy=fsy, fncc=fncc,
                                step2=step2, cut_thr=cut_thr, key=np.array(key))
            log(f"cached the pass-1 layout + pass-2 backbone -> {bcache.name}")

    log(f"run-cut threshold (data-derived) = {cut_thr:.3f}")
    brk0 = (~step2) | (fncc < cut_thr)
    cuts_ncc = []
    for k in np.where(brk0)[0]:
        why = "EXCLUSION GAP" if not step2[k] else f"ncc {fncc[k]:.3f} < {cut_thr:.3f}"
        cuts_ncc.append((int(p2t[k]), int(p2t[k + 1]), why))
        log(f"    cut {p2t[k]:3d} -> {p2t[k + 1]:3d}   {why}")

    runs = make_runs(brk0, len(p2t))
    loc2 = chain(runs, fsx, fsy, len(p2t))
    log(f"pass 2 -> {len(runs)} runs (the NCC-threshold cut), sizes {[len(r) for r in runs]}")

    # -------------------------------------------------------------------------------------
    # 3. THE FROZEN PASS-1 COMPOSITE — the absolute reference field
    # -------------------------------------------------------------------------------------
    IMG1, MSK1, M1 = composite(B, r1, L1)
    log(f"pass-1 composite {IMG1.shape[1]} x {IMG1.shape[0]} px, "
        f"valid {int(MSK1.sum()):,} px")

    # -------------------------------------------------------------------------------------
    # 4. PER-TILE ANCHORS — every pass-2 tile matched against the frozen pass-1 composite
    # -------------------------------------------------------------------------------------
    log("=" * 90)
    log("STEP 3 — PER-TILE ANCHORS: each pass-2 tile matched against the frozen pass-1 composite")
    log("=" * 90)
    TMSK = np.ones((TILE, TILE), bool)
    acache = _cache_path(cache, f"T33_anchors_{tag}_{khash}.npz")
    t_anchor = time.time()
    if acache is not None and acache.exists():
        z = _load_checked(acache, key)
        anc, ancv = z["anc"], z["ancv"]
        if len(ancv) != len(p2t):
            raise RuntimeError(
                f"{acache.name} holds {len(ancv)} anchors but pass 2 has {len(p2t)} tiles. The "
                f"cache does not describe this problem — delete it and re-run.")
        log(f"loaded the cached per-tile anchors from {acache.name}")
    else:
        anc = np.full((len(p2t), 2), np.nan)
        ancv = np.full(len(p2t), np.nan)
        for q in range(len(p2t)):
            tile = B[r2[q]].astype(np.float32)
            tile = tile - tile.mean()
            c = match(IMG1, MSK1, tile, TMSK, kpk=8, minfrac=0.0, minabs=120000.0)
            if c:
                v, dx, dy, _ = c[0]
                anc[q] = (dx, dy)
                ancv[q] = v
            if q % 30 == 0:
                log(f"    anchored {q}/{len(p2t)} tiles ({time.time() - t_anchor:.0f}s)")
            t27._free()
        if acache is not None:
            np.savez_compressed(acache, anc=anc, ancv=ancv, key=np.array(key))
    ok = np.isfinite(ancv) & (ancv >= cfg.anchor_ncc)
    log(f"per-tile anchors: {int(ok.sum())}/{len(p2t)} reached NCC >= {cfg.anchor_ncc} "
        f"(median NCC {np.nanmedian(ancv):.3f}) in {time.time() - t_anchor:.0f}s")

    # -------------------------------------------------------------------------------------
    # 5. RE-CUT THE RUNS FROM THE ANCHORS — the run structure is MEASURED, not thresholded
    # -------------------------------------------------------------------------------------
    log("=" * 90)
    log("STEP 4 — RE-CUT: where the implied run origin JUMPS, the chain is broken")
    log("=" * 90)
    brk = brk0.copy()
    nsplit = 0
    ndrop = 0
    cuts_aperture = []
    for r in runs:
        m0 = loc2[np.array(r)].min(0)
        conf = [q for q in r if ok[q]]                   # tiles of this run with a usable anchor
        O = {q: anc[q] - (loc2[q] - m0) for q in conf}   # the implied RUN ORIGIN each one votes for
        grp = []                                         # the current agreeing group
        i = 0
        while i < len(conf):
            q = conf[i]
            if not grp:
                grp = [q]
                i += 1
                continue
            med = np.median(np.array([O[g] for g in grp]), axis=0)
            d = float(np.hypot(*(O[q] - med)))
            if d <= cfg.split_px:
                grp.append(q)
                i += 1
                continue
            # A DISAGREEMENT. Is it a broken chain, or just one bad anchor?
            tail = conf[i:i + cfg.look]                  # the witnesses that ACTUALLY exist ahead
            nnew = sum(1 for p in tail if np.hypot(*(O[p] - O[q])) <= cfg.split_px)
            # Never demand more corroboration than a side can physically supply — a 2-tile tail
            # can never muster 3 witnesses, and refusing the cut for that reason is an artefact
            # of the formula, not evidence. Floor of 2: one anchor is never a corroboration.
            need = max(2, min(cfg.min_side, len(grp), len(tail)))
            k = q - 1                                    # the step (q-1) -> q
            if len(grp) >= need and nnew >= need and 0 <= k < len(brk) and not brk[k]:
                brk[k] = True
                nsplit += 1
                cuts_aperture.append((int(p2t[k]), int(p2t[q]), float(d), int(nnew),
                                      float(fncc[k])))
                log(f"    SPLIT {p2t[k]:3d} -> {p2t[q]:3d}: the implied run origin jumps "
                    f"{d:7.0f} px, corroborated by {nnew} anchors either side  (that step's "
                    f"backbone ncc was {fncc[k]:.3f} — it PASSED the NCC gate and is still wrong)")
                grp = [q]
            elif len(grp) < need:
                # the group so far rests on a SINGLE anchor — that is not enough to cut a chain
                # on. Discard it as an outlier and restart. (This is what broke tile 311 in v2.)
                ndrop += len(grp)
                log(f"    OUTLIER ANCHOR at trial {p2t[grp[0]]:3d} (only {len(grp)} anchor "
                    f"before the {d:.0f} px disagreement at {p2t[q]}) — DISCARDED, no cut. "
                    f"The chain stands.")
                grp = [q]
            else:
                ndrop += 1                               # a lone bad anchor inside a solid group
                log(f"    outlier anchor at trial {p2t[q]:3d} ({d:.0f} px off its run, "
                    f"{nnew} corroborators) — ignored, no cut")
            i += 1
    log(f"{nsplit} extra cut(s) found by the aperture that the NCC threshold missed; "
        f"{ndrop} anchor(s) discarded as outliers")

    runs = make_runs(brk, len(p2t))
    loc2 = chain(runs, fsx, fsy, len(p2t))
    log(f"pass 2 -> {len(runs)} runs, sizes {[len(r) for r in runs]}")

    # -------------------------------------------------------------------------------------
    # 6. MATCH EVERY RUN AGAINST PASS 1 (an anchor STAR: run-to-run links add nothing —
    #    every run already has the whole of pass 1 to talk to, and a run-run link would only
    #    let one run's error propagate into another's)
    # -------------------------------------------------------------------------------------
    log("=" * 90)
    log("STEP 5 — COMPOSITE-TO-COMPOSITE: every run matched against the frozen pass-1 composite")
    log("=" * 90)
    log(f"{'run':>5s} {'tiles':>5s} {'best':>7s} {'2nd':>7s} {'MARGIN':>7s} {'dx':>7s} "
        f"{'dy':>7s} {'ov_kpx':>8s}")

    pos = {}
    for q, t in enumerate(p1t):
        pos[int(t)] = L1[q]                          # PASS 1: FROZEN. Untouched. The control.

    margins = []
    run_info = []
    origins = {}
    for k, r in enumerate(runs):
        rr = np.array(r)
        rows, loc = r2[rr], loc2[rr]
        img, msk, m0 = composite(B, rows, loc)
        c = match(img, msk, IMG1, MSK1)              # A = the run, B = pass 1
        if not c:
            raise RuntimeError(f"run R{k} ({len(r)} tiles) got no composite candidate at all")
        v, dx, dy, nn = c[0]
        second = c[1][0] if len(c) > 1 else np.nan
        margins.append((f"R{k}", len(r), float(v), float(second), float(v - second)))
        log(f"{'R' + str(k):>5s} {len(r):5d} {v:7.3f} {second:7.3f} {v - second:7.3f} "
            f"{dx:7d} {dy:7d} {nn / 1000:8.0f}")
        # (dx,dy) = origin_pass1 - origin_run  =>  origin_run (in pass-1 composite coords) = -(dx,dy)
        O = -np.array([float(dx), float(dy)]) + M1   # + M1: back into pass-1's own local frame
        origins[f"R{k}"] = [float(O[0]), float(O[1])]
        run_info.append(dict(run=f"R{k}", n=len(r), trials=[int(p2t[q]) for q in r],
                             ncc=float(v), second=float(second), margin=float(v - second),
                             dx=int(dx), dy=int(dy), overlap_px=int(nn),
                             origin=[float(O[0]), float(O[1])]))
        for j, row in enumerate(rows):
            pos[int(trials[row])] = O + (loc[j] - m0)
        t27._free()

    if len(pos) != n:
        raise RuntimeError(f"placed {len(pos)} snapshots, expected {n}")

    d1 = np.array([pos[t] for t in p1t]) - L1
    pass1_dev = float(np.abs(d1).max())
    log(f"PASS-1 CONTROL: pass-1 tiles are EXACTLY the frozen t27 pass-1 layout — max "
        f"deviation {pass1_dev:.6f} px (they were never touched)")

    log("=" * 90)
    log("MARGIN TABLE — every run's offset against the frozen pass-1 composite")
    for nm, nt, v, s2, mg in margins:
        log(f"  {nm:>5s} {nt:3d} tiles   best {v:.3f}   2nd {s2:.3f}   MARGIN {mg:.3f}")

    # The CROSS-PASS TIE, derived from the pixels: `origins` is where each rigid pass-2 run
    # landed in pass 1's frame. There is no single number that the method needs — that is the
    # point of the run decomposition — so the tie is reported run by run, and the largest run
    # (the one with the biggest aperture, hence the most trustworthy offset) is called out.
    biggest = max(run_info, key=lambda d: d["n"])
    dt = time.time() - t0
    log(f"[done] placed {len(pos)} snapshots in {dt:.0f}s "
        f"({'GPU' if t27.on_gpu() else 'CPU'})")

    info = dict(
        n_tiles=n, n_pass1=len(p1t), n_pass2=len(p2t),
        pass_split=int(cfg.pass_split),
        breaks=[(int(a), int(b), why) for _, a, b, why in breaks(trials, cfg.pass_split)],
        cut_thr=float(cut_thr),
        cuts_ncc=cuts_ncc,                       # the FIRST cut: gaps + steps below the floor
        cuts_aperture=cuts_aperture,             # the SECOND cut: where the run origin jumped
        n_extra_cuts=int(nsplit),
        n_anchors_dropped=int(ndrop),
        anchors_ok=int(ok.sum()),
        anchor_med_ncc=float(np.nanmedian(ancv)),
        n_runs=len(runs),
        runs=run_info,
        margins=[[nm, nt, v, s2, mg] for nm, nt, v, s2, mg in margins],
        min_margin=float(min(m[4] for m in margins)),
        run_origins=origins,                     # <- THE MEASURED CROSS-PASS TIE, run by run
        cross_pass_tie=biggest["origin"],        #    (the largest run's, as a single number)
        cross_pass_tie_run=biggest["run"],
        pass1_max_dev=pass1_dev,                 # the control: must be 0.0
        pass1_composite_px=[int(IMG1.shape[1]), int(IMG1.shape[0])],
        seconds=float(dt), gpu=bool(t27.on_gpu()),
        config=vars(cfg).copy())
    return {t: np.asarray(p, float) for t, p in pos.items()}, info
