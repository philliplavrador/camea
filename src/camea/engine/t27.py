"""T27 — the placement method that solved the mosaic. Standalone, any trial range.

WHAT THIS IS
------------
`place(trials, frames)` takes a stack of 512x512 snapshots (in acquisition order) and
returns `{trial: (x, y)}` — where each snapshot belongs on the canvas. It is the exact
method shipped as the `260620d__T27_solve` build, lifted out of the challenge harness so
it runs on ANY set of snapshots instead of only the benchmark's trials 11-166.

The original lives in the archive (`analysis/archive/challenge_2026-07/`); this module is
the same algorithm with the harness dependencies (`challenge_lib`, the hard-coded trial
range, the %TEMP% caches) removed. Nothing about the maths changed.

HOW IT WORKS — four ideas, in order
-----------------------------------
1. MEASURE EVERY PAIR, NOT JUST THE NEIGHBOURS.  Older methods only compared snapshots
   that the *current layout* said were near each other — so a snapshot that had drifted to
   the wrong place was never compared against its true neighbours, and could never be
   rescued. Circular. Instead we SWIM all N*(N-1)/2 pairs up front, with no layout at all.
   On a GPU that is seconds.

2. THE SCAN IS A SERPENTINE, SO EVERY STEP IS AN AXIS MOVE.  The microscope walks down a
   column, turns, walks up the next. So one acquisition step is near-purely VERTICAL or
   near-purely HORIZONTAL — the true shift lies on one of two thin lines, not anywhere in
   the plane. We therefore search those two lines EXHAUSTIVELY at 1 px, computing the exact
   overlap-NCC at every candidate, and take the best. No SWIM peak list is consulted.
   The band is MEASURED from the confident steps (`precheck`), not assumed.
     - NEAR-ZERO VETO: shifts within R0 px of (0,0) are excluded. The periodic electrode
       grid self-correlates perfectly at zero shift, so an unconstrained search happily
       returns "these two tiles are in the same place" — which is never true of two
       consecutive acquisitions.
     - TRAP GUARD: a step keeps its incumbent SWIM shift unless the manifold search beats
       it by >= GAIN NCC. So a step whose true shift really is short keeps its correct
       incumbent instead of being dragged out past the veto radius.

3. THE COLUMN STRUCTURE IS TRUSTWORTHY; THE ROW STRUCTURE IS NOT.  After (2), every turn is
   pinned at high NCC and every in-column step has |dx| ~ 0 — so the chain's X coordinate
   (which column a tile is in) is far more reliable than its Y (which accumulates error).
   So we gate the all-to-all graph on X ONLY: admit a link iff its dx agrees with the
   chain's dx. dy is never constrained, so the graph stays free to repair vertical error.
   This is what kills the killer edge that broke earlier methods: two tiles 64 acquisition
   steps apart (several columns) cannot possibly be 8 px apart in x, however well the
   electrode grid happens to correlate.

4. ONCE THE LINKS ARE CLEAN, AVERAGE — DON'T THREAD.  The project's standing rule was
   "never average, thread through a spanning tree", because one bad link in a least-squares
   solve displaces a tile catastrophically. That rule was right for DIRTY links, where
   failure is binary (a tile is sub-pixel right or hundreds of px wrong). After (2) and (3)
   that regime is gone: every tile is within ~25 px and the whole residual is ACCUMULATED
   DRIFT. A tree cannot fix drift — it still threads each tile through one accumulating
   path. Averaging is the correct estimator FOR drift, and the redundant cross-column links
   tie the columns together directly instead of integrating the per-step bias. So:
   translation-only weighted least squares (spectralign `Placement.rigid`) with IRLS
   trimming as a guard.

WHAT IT ASSUMES (read before running it on a new range)
------------------------------------------------------
  * The snapshots are consecutive acquisitions of a SERPENTINE raster. `place()` warns if
    the trial numbers have gaps, because then a "consecutive" pair in the list is really a
    multi-step jump and idea (2) does not hold for it.
  * Tiles are 512x512 and steps are shorter than SPAN px.
  * The +/-256 alias is the electrode-grid period; the +/-512 alias is the FFT wraparound
    of a 512 px correlogram. Both are properties of the imaging, not of the trial range.

GPU: uses CuPy when it is importable, NumPy otherwise (same numbers, a lot slower). Both
accelerated paths are VALIDATED against the reference implementations at run time — see
`NccBank.validate` and `swim_all`. Never trust a fast path you have not checked.
"""
import glob
import os
import time
from collections import defaultdict

import numpy as np

# --- fixed by the imaging, not by the trial range -------------------------------------
H = W = 512
PAD = 1024                    # zero-pad -> LINEAR (not circular) cross-correlation
WHT = -0.65                   # spectralign's whitening exponent
EPS32 = np.float32(1e-30)     # GPUs flush denormals: 1e-40 -> 0 -> 0**neg -> inf -> NaN
MINOV, MINSIDE = 3600, 40     # quality.overlap_ncc's own validity rule
ALIAS = [-512, -256, 0, 256, 512]   # +/-512 = FFT wraparound; +/-256 = electrode grid


class Config:
    """T27's knobs. The defaults are the ones that produced the shipped build."""

    def __init__(self, **kw):
        self.conf = 0.62        # "confident" consecutive step (pre-check + column structure)
        self.run_conf = 0.55    # below this a step BREAKS the chain into runs; tiles either
                                # side get no column label and are exempt from the gate
        self.span = 340         # exhaustive search half-range, px (real max step was 273.6)
        self.band_pad = 4       # manifold band = (measured max cross-component) + this
        self.r0 = 40.0          # near-zero veto radius, consecutive steps only
        self.gain = 0.05        # trap guard: manifold must beat the incumbent by this
        self.gate_tol = 60.0    # column gate: |dx_link - dx_chain| tolerance, px
        self.topn = 6           # keep a link only if it is a top-6 link of one of its ends
        self.null_q = 99.5      # permutation-null percentile -> the NCC floor
        self.null_n = 3000      # permutation-null sample size
        self.r_drop = 25.0      # IRLS: drop a link whose residual exceeds this
        self.irls_iters = 6
        self.control = True     # run the stride-2 full-plane control (honesty check)
        self.seed = 11
        for k, v in kw.items():
            if not hasattr(self, k):
                raise TypeError(f"unknown T27 config knob: {k!r}")
            setattr(self, k, v)

    def __repr__(self):
        return "Config(" + ", ".join(f"{k}={v}" for k, v in vars(self).items()) + ")"


# =============================================================================
# Array backend: CuPy if we can get it, NumPy if we cannot. Same numbers either way.
# =============================================================================
_XP = None
_GPU = False


def _cuda_dll_dance():
    """The pip nvidia-*-cu12 wheels hide their DLLs in site-packages/nvidia/*/bin, which
    CuPy does not auto-discover on Windows. add_dll_directory (for the .pyd's dependent
    DLLs, which ignore PATH on py3.8+) AND PATH (NVRTC loads nvrtc-builtins at runtime via
    a plain LoadLibrary, which does use PATH). See utils/knowledge/gpu-acceleration.md."""
    import sysconfig
    sp = sysconfig.get_paths()["purelib"]
    dirs = [d for d in sorted(glob.glob(os.path.join(sp, "nvidia", "*", "bin")))
            if os.path.isdir(d)]
    for d in dirs:
        os.add_dll_directory(d)
    if dirs:
        os.environ["PATH"] = os.pathsep.join(dirs) + os.pathsep + os.environ.get("PATH", "")


def xp():
    """The array module in use. Import CuPy lazily so NumPy-only machines still work."""
    global _XP, _GPU
    if _XP is None:
        try:
            _cuda_dll_dance()
            import cupy
            cupy.zeros(1) + 1                    # force context creation -> fail loudly here
            _XP, _GPU = cupy, True
            print(f"[gpu] CuPy {cupy.__version__}, CUDA runtime "
                  f"{cupy.cuda.runtime.runtimeGetVersion()} — using the GPU")
        except Exception as e:                   # noqa: BLE001 - any failure -> CPU is fine
            _XP, _GPU = np, False
            print(f"[gpu] CuPy unavailable ({type(e).__name__}: {e})\n"
                  f"[gpu] falling back to NumPy — identical results, but MUCH slower.")
    return _XP


def on_gpu():
    xp()
    return _GPU


def _np(a):
    """Device array -> host array."""
    return _XP.asnumpy(a) if _GPU else np.asarray(a)


def _free():
    if _GPU:
        _XP.get_default_memory_pool().free_all_blocks()


def _batches(gpu_b, cpu_b):
    return gpu_b if on_gpu() else cpu_b


# =============================================================================
# Frames
# =============================================================================
def band_pass(frames, lo=3, hi=30):
    """DoG g(3)-g(30) — the representation everything in this project matches on. It
    suppresses the periodic electrode grid and the slow illumination vignette, leaving
    tissue texture. Identical to mosaic.quality.band_pass."""
    from . import quality
    return quality.band_pass(frames, lo, hi)


def apo_window(n=512):
    """spectralign funcs.apodize's window: cosine fadeout over the outer 1/4."""
    xx = np.linspace(-1, 1, n)
    vv = np.ones((n,), np.float32)
    idx = np.abs(xx) > .5
    vv[idx] = .5 - .5 * np.cos(2 * np.pi * xx[idx])
    return (vv.reshape(n, 1) * vv.reshape(1, n)).astype(np.float32)


# =============================================================================
# SWIM — an exact, batched re-implementation of spectralign Swim().align
# =============================================================================
class Swim:
    """Batched phase-correlation with partial spectral whitening.

    Asymmetric on purpose, exactly as spectralign is: the STATIONARY tile is apodized
    before its FFT, the MOVING tile is not. Returns shift == pos_j - pos_i.
    """

    def __init__(self, B):
        x = xp()
        Bf = np.asarray(B, np.float32)
        apo = apo_window(Bf.shape[-1])
        gray = Bf.mean(axis=(1, 2), keepdims=True)
        A = apo[None] * Bf + (1.0 - apo)[None] * gray     # apodize the STATIONARY tile
        A = A - A.mean(axis=(1, 2), keepdims=True)
        M = Bf - Bf.mean(axis=(1, 2), keepdims=True)      # MOVING tile is NOT apodized
        self.FA = x.fft.rfft2(x.asarray(A)).astype("complex64")
        self.FM = x.fft.rfft2(x.asarray(M)).astype("complex64")
        self.xg = x.arange(11) - 5
        _free()

    def run(self, ii, jj, batch=None):
        x = xp()
        batch = batch or _batches(256, 32)
        out = np.zeros((len(ii), 3), np.float64)
        for s in range(0, len(ii), batch):
            e = min(s + batch, len(ii))
            a = x.asarray(ii[s:e])
            b = x.asarray(jj[s:e])
            prd = self.FA[a] * x.conj(self.FM[b])
            pw = (prd.real ** 2 + prd.imag ** 2) + EPS32
            prd = prd * (pw ** (WHT / 2)).astype("float32")
            shf = x.fft.irfft2(prd, s=(H, W))
            n = e - s
            flat = shf.reshape(n, -1)
            idx = x.argmax(flat, axis=1)
            xm = (idx % W).astype("int64")
            ym = (idx // W).astype("int64")
            pk = flat[x.arange(n), idx]
            snr = (pk - flat.mean(axis=1)) / (flat.std(axis=1) + 1e-40)
            xf = x.where(xm >= W // 2, xm - W, xm)
            yf = x.where(ym >= H // 2, ym - H, ym)
            xx_ = (xf[:, None] + self.xg[None, :]) % W     # 11x11 centre-of-mass -> sub-pixel
            yy_ = (yf[:, None] + self.xg[None, :]) % H
            win = shf[x.arange(n)[:, None, None], yy_[:, :, None], xx_[:, None, :]]
            win = win - win.mean(axis=(1, 2), keepdims=True)
            win = x.maximum(win, 0)
            sw = win.sum(axis=(1, 2))
            cx = (win * self.xg[None, None, :]).sum(axis=(1, 2)) / (sw + 1e-40)
            cy = (win * self.xg[None, :, None]).sum(axis=(1, 2)) / (sw + 1e-40)
            out[s:e, 0] = _np(xf + cx)
            out[s:e, 1] = _np(yf + cy)
            out[s:e, 2] = _np(snr)
            _free()
        return out


def _swim_reference(B, i, j):
    """spectralign's own Swim, one pair — the thing the batched path must agree with."""
    from spectralign.image import Image
    from spectralign.swim import Swim as SpSwim
    sw = SpSwim().align(Image(B[i].astype(float)), Image(B[j].astype(float)))
    dx, dy = sw.shift
    return np.array([-dx, -dy])


def swim_all(B, cache=None, validate=True, rng_seed=7):
    """Every pair's SWIM shift, with NO layout involved. -> (ii, jj, shift[P,2])

    This is idea (1): the candidate set must not be chosen by the error it is meant to fix.
    """
    n = len(B)
    ii, jj = (a.astype(np.int64) for a in np.triu_indices(n, k=1))

    if cache is not None and os.path.exists(cache):
        z = np.load(cache)
        if int(z["n"]) == n and len(z["ii"]) == len(ii):
            print(f"[swim] loaded {len(ii):,} cached all-to-all shifts from {os.path.basename(cache)}")
            return z["ii"], z["jj"], z["sh"][:, :2]

    t = time.time()
    sh = Swim(B).run(ii, jj)
    print(f"[swim] {len(ii):,} pairs in {time.time() - t:.1f}s "
          f"({'GPU' if on_gpu() else 'CPU'})")

    if validate:
        r = np.random.default_rng(rng_seed)
        k = r.choice(len(ii), min(30, len(ii)), replace=False)
        ref = np.array([_swim_reference(B, int(ii[q]), int(jj[q])) for q in k])
        err = np.abs(sh[k, :2] - ref).max()
        print(f"[validate] batched SWIM vs spectralign Swim on {len(k)} pairs: "
              f"max |d| = {err:.2e} px")
        if err > 0.01:
            raise RuntimeError(f"batched SWIM disagrees with spectralign by {err:.3f} px")

    if cache is not None:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        np.savez_compressed(cache, ii=ii, jj=jj, sh=sh, n=n)
    return ii, jj, sh[:, :2]


# =============================================================================
# Exact overlap-NCC at ARBITRARY integer shifts, batched.
#   NCC(s) = (C_ab(s) - Sa.Sb/n) / sqrt((Sa2 - Sa^2/n)(Sb2 - Sb^2/n))
# C_ab from a zero-padded FFT correlation; the local sums from integral images (Lewis).
# Reproduces quality.overlap_ncc to <1e-5 — asserted at run time in validate().
# =============================================================================
class NccBank:
    def __init__(self, B):
        x = xp()
        self.B = np.asarray(B, np.float32)
        self.n = len(self.B)
        self.F = x.fft.rfft2(x.asarray(self.B), s=(PAD, PAD)).astype("complex64")
        d = self.B.astype(np.float64)                 # float64: the integral-image
        h, w = self.B.shape[1:]                       # differences cancel catastrophically
        self.S1 = np.zeros((self.n, h + 1, w + 1), np.float64)
        self.S2 = np.zeros((self.n, h + 1, w + 1), np.float64)
        self.S1[:, 1:, 1:] = d.cumsum(1).cumsum(2)
        self.S2[:, 1:, 1:] = (d * d).cumsum(1).cumsum(2)
        _free()

    @staticmethod
    def _rect(S, k, y0, y1, x0, x1):
        return S[k, y1, x1] - S[k, y0, x1] - S[k, y1, x0] + S[k, y0, x0]

    def _norm(self, aa, bb, sx, sy, Cab):
        ax0 = np.maximum(0, sx); ax1 = np.minimum(W, W + sx)
        ay0 = np.maximum(0, sy); ay1 = np.minimum(H, H + sy)
        nn = (ax1 - ax0) * (ay1 - ay0)
        Sa = self._rect(self.S1, aa, ay0, ay1, ax0, ax1)
        Sa2 = self._rect(self.S2, aa, ay0, ay1, ax0, ax1)
        Sb = self._rect(self.S1, bb, ay0 - sy, ay1 - sy, ax0 - sx, ax1 - sx)
        Sb2 = self._rect(self.S2, bb, ay0 - sy, ay1 - sy, ax0 - sx, ax1 - sx)
        va = Sa2 - Sa * Sa / nn
        vb = Sb2 - Sb * Sb / nn
        d = np.sqrt(np.maximum(va, 0) * np.maximum(vb, 0))
        return np.where(d > 0, (Cab - Sa * Sb / nn) / np.where(d > 0, d, 1.0), np.nan)

    @staticmethod
    def _valid(sx, sy):
        ow = np.minimum(W, W + sx) - np.maximum(0, sx)
        oh = np.minimum(H, H + sy) - np.maximum(0, sy)
        return (ow >= MINSIDE) & (oh >= MINSIDE) & (ow * oh >= MINOV)

    def at(self, ii, jj, SX, SY, batch=None):
        """PER-PAIR candidate shifts. SX,SY: (P,K) -> (P,K) NCC; NaN where overlap too small."""
        x = xp()
        batch = batch or _batches(48, 6)
        P, K = SX.shape
        sx = np.rint(SX).astype(np.int64)
        sy = np.rint(SY).astype(np.int64)
        ok = self._valid(sx, sy)
        out = np.full((P, K), np.nan)
        ii = np.asarray(ii); jj = np.asarray(jj)
        for s in range(0, P, batch):
            e = min(s + batch, P)
            a = x.asarray(ii[s:e]); b = x.asarray(jj[s:e])
            C = x.fft.irfft2(self.F[a] * x.conj(self.F[b]), s=(PAD, PAD)).reshape(e - s, -1)
            m = ok[s:e]
            r, c = np.where(m)
            if len(r):
                lx = sx[s:e][m] % PAD
                ly = sy[s:e][m] % PAD
                gidx = x.asarray(r * (PAD * PAD) + ly * PAD + lx)
                Cab = _np(C.ravel()[gidx]).astype(np.float64)
                v = self._norm(ii[s:e][r], jj[s:e][r], sx[s:e][m], sy[s:e][m], Cab)
                blk = out[s:e]; blk[r, c] = v; out[s:e] = blk
                del gidx, Cab
            del C
            _free()
        return out

    def scan(self, ii, jj, SH, batch=None, kblock=40000):
        """EXHAUSTIVE argmax over a SHARED integer shift grid SH (K,2).

        The correlation surface C is computed ONCE per pair-batch, so every extra candidate
        shift is just an index into it: 64,000 candidates cost barely more than 25. That is
        the whole reason the axis-manifold search is affordable. -> (best_ncc, sx, sy)
        """
        x = xp()
        batch = batch or _batches(16, 2)
        P = len(ii)
        ii = np.asarray(ii); jj = np.asarray(jj)
        sx, sy = SH[:, 0].astype(np.int64), SH[:, 1].astype(np.int64)
        keep = self._valid(sx, sy)
        sx, sy = sx[keep], sy[keep]
        K = len(sx)
        if K == 0:
            raise ValueError("every candidate shift was rejected for insufficient overlap")
        bestv = np.full(P, -np.inf)
        bestk = np.zeros(P, np.int64)
        for s in range(0, P, batch):
            e = min(s + batch, P)
            n = e - s
            a = x.asarray(ii[s:e]); b = x.asarray(jj[s:e])
            C = x.fft.irfft2(self.F[a] * x.conj(self.F[b]), s=(PAD, PAD)).reshape(n, -1)
            for k0 in range(0, K, kblock):
                k1 = min(k0 + kblock, K)
                Kb = k1 - k0
                lin = x.asarray((sy[k0:k1] % PAD) * PAD + (sx[k0:k1] % PAD))
                Cab = _np(C[:, lin]).astype(np.float64)                  # (n, Kb)
                v = self._norm(np.repeat(ii[s:e], Kb), np.repeat(jj[s:e], Kb),
                               np.tile(sx[k0:k1], n), np.tile(sy[k0:k1], n),
                               Cab.ravel()).reshape(n, Kb)
                v = np.where(np.isnan(v), -np.inf, v)
                kk = np.argmax(v, axis=1)
                vv = v[np.arange(n), kk]
                up = vv > bestv[s:e]
                bl = bestv[s:e].copy(); bl[up] = vv[up]; bestv[s:e] = bl
                bk = bestk[s:e].copy(); bk[up] = (k0 + kk)[up]; bestk[s:e] = bk
                del lin, Cab
            del C
            _free()
        return bestv, sx[bestk].astype(float), sy[bestk].astype(float)

    def validate(self, ii, jj, n=200, seed=3):
        """NEVER trust an accelerated path unvalidated. Two checks:
        (a) the batched NCC vs the judge's own quality.overlap_ncc;
        (b) the exhaustive scan() vs the per-pair at() path."""
        from . import quality
        r = np.random.default_rng(seed)
        k = r.choice(len(ii), min(n, len(ii)), replace=False)
        SX = r.integers(-460, 461, (len(k), 1)).astype(float)
        SY = r.integers(-460, 461, (len(k), 1)).astype(float)
        mine = self.at(np.asarray(ii)[k], np.asarray(jj)[k], SX, SY)[:, 0]
        errs = []
        for q, p in enumerate(k):
            ref = quality.overlap_ncc(self.B[ii[p]], self.B[jj[p]], SX[q, 0], SY[q, 0])
            if np.isnan(ref) and np.isnan(mine[q]):
                continue
            errs.append(abs(ref - mine[q]))
        e = float(np.nanmax(errs)) if errs else 0.0
        print(f"[validate] batched NCC vs quality.overlap_ncc on {len(errs)} (pair,shift): "
              f"max err {e:.2e}")
        if e > 1e-4:
            raise RuntimeError(f"batched NCC disagrees with the judge by {e:.2e}")

        SH = np.stack(np.meshgrid(np.arange(-90, 91, 30), np.arange(-90, 91, 30),
                                  indexing="ij"), -1).reshape(-1, 2)
        m = min(20, len(k))
        kk = k[:m]
        bv, _, _ = self.scan(np.asarray(ii)[kk], np.asarray(jj)[kk], SH)
        ref = self.at(np.asarray(ii)[kk], np.asarray(jj)[kk],
                      np.tile(SH[:, 0], (m, 1)).astype(float),
                      np.tile(SH[:, 1], (m, 1)).astype(float))
        ref = np.nanmax(np.where(np.isnan(ref), -np.inf, ref), axis=1)
        d = float(np.max(np.abs(bv - ref)))
        print(f"[validate] exhaustive scan() vs at() argmax on {m} pairs: max err {d:.2e}")
        if d > 1e-9:
            raise RuntimeError("scan() and at() disagree")


# =============================================================================
# De-alias: the 5x5 +/-256 / +/-512 lattice, arbitrated by the PIXELS
# =============================================================================
def dealias(bank, ii, jj, sh):
    """SWIM reports a shift modulo two ambiguities: the 512 px FFT wraparound and the
    256 px electrode-grid period. Try all 25 combinations and let the exact overlap-NCC
    (the judge's own measure) decide which one is real."""
    ax = np.array([[a, b] for a in ALIAS for b in ALIAS], float)
    SX = sh[:, 0][:, None] + ax[None, :, 0]
    SY = sh[:, 1][:, None] + ax[None, :, 1]
    V = bank.at(ii, jj, SX, SY)
    good = ~np.all(np.isnan(V), axis=1)
    Vf = np.where(np.isnan(V), -np.inf, V)
    k = np.argmax(Vf, axis=1)
    r = np.arange(len(ii))
    n_moved = int(np.sum(good & (k != 12)))            # 12 == the (0,0) alias
    return SX[r, k], SY[r, k], np.where(good, Vf[r, k], np.nan), good, n_moved


# =============================================================================
# STEP 1 — the falsifiable pre-check (run FIRST, reported whatever it says)
# =============================================================================
def precheck(cfg, trials, ci, cj, dsx, dsy, dncc):
    """Does the true consecutive shift really lie on an axis? MEASURE it, do not assume it.

    Returns the band (px) to search either side of each axis — derived from the data.
    """
    conf = dncc >= cfg.conf
    if conf.sum() == 0:
        raise RuntimeError(
            f"no consecutive step reached NCC {cfg.conf} — the axis band cannot be measured. "
            f"Best step was {np.nanmax(dncc):.3f}. Are these snapshots really a serpentine "
            f"raster in acquisition order?")
    cross = np.minimum(np.abs(dsx), np.abs(dsy))
    cc = cross[conf]
    viol = np.where(conf & (cross > 4.0))[0]

    print("\n" + "=" * 78)
    print("STEP 1 — PRE-CHECK: does a consecutive step really lie on an AXIS?")
    print("=" * 78)
    print(f"  confident steps (overlap_ncc >= {cfg.conf}): {int(conf.sum())} of {len(ci)}")
    print(f"  cross-axis component min(|dx|,|dy|):  median {np.median(cc):.2f}  "
          f"p90 {np.percentile(cc, 90):.2f}  p99 {np.percentile(cc, 99):.2f}  MAX {cc.max():.2f}")
    print(f"  steps violating a <= 4 px band: {len(viol)}")
    for v in viol:
        print(f"      {trials[ci[v]]:3d}->{trials[cj[v]]:3d}  ({dsx[v]:7.1f},{dsy[v]:7.1f})  "
              f"ncc {dncc[v]:.3f}   cross {cross[v]:.1f} px")
    band = int(np.ceil(cc.max())) + cfg.band_pad
    if len(viol):
        print(f"  VERDICT: the literal '<= 4 px' form of the claim is FALSE "
              f"({len(viol)} confident violators).")
        print(f"           The premise SURVIVES in its DIRECTIONAL form — every confident step "
              f"is still\n           overwhelmingly one-axis (median cross {np.median(cc):.2f} px "
              f"against a step of ~150 px) —\n           but the band is MEASURED, not assumed: "
              f"band = {band} px.")
    else:
        print(f"  VERDICT: premise HOLDS at <= 4 px. band = {band} px.")
    return band, conf


# =============================================================================
# STEP 2 — the exhaustive axis-manifold backbone
# =============================================================================
def _manifold_grid(cfg, band):
    a = np.arange(-cfg.span, cfg.span + 1)
    c = np.arange(-band, band + 1)
    V = np.stack(np.meshgrid(c, a, indexing="ij"), -1).reshape(-1, 2)    # near-vertical
    Hz = np.stack(np.meshgrid(a, c, indexing="ij"), -1).reshape(-1, 2)   # near-horizontal
    S = np.unique(np.vstack([V, Hz]), axis=0).astype(np.int64)
    keep = np.hypot(S[:, 0], S[:, 1]) >= cfg.r0                          # NEAR-ZERO VETO
    return S[keep], int((~keep).sum())


def _full_plane_grid(cfg, stride):
    a = np.arange(-cfg.span, cfg.span + 1, stride)
    S = np.stack(np.meshgrid(a, a, indexing="ij"), -1).reshape(-1, 2).astype(np.int64)
    return S[np.hypot(S[:, 0], S[:, 1]) >= cfg.r0]


def subpixel(bank, ci, cj, sx, sy):
    """3x3 parabola on the exact-NCC surface. Integer shifts would inject up to +/-0.5 px
    of rounding into every path through the graph, so a corrected step must keep sub-pixel
    accuracy."""
    off = np.array([-1, 0, 1])
    SX = sx[:, None] + np.tile(off, 3)[None, :]
    SY = sy[:, None] + np.repeat(off, 3)[None, :]
    V = bank.at(ci, cj, SX, SY).reshape(len(ci), 3, 3)          # [dy, dx]
    V = np.where(np.isnan(V), -np.inf, V)
    out = np.stack([sx, sy], 1).astype(float)
    for q in range(len(ci)):
        f = V[q]
        if not np.isfinite(f).all():
            continue
        for ax_, cur in ((1, 0), (0, 1)):                       # 1 -> dx (cols), 0 -> dy (rows)
            g = f[1, :] if ax_ == 1 else f[:, 1]
            den = g[0] - 2 * g[1] + g[2]
            if den < -1e-12:                                    # a real maximum
                d = 0.5 * (g[0] - g[2]) / den
                if abs(d) <= 0.5:
                    out[q, cur] += d
    return out[:, 0], out[:, 1]


def fix_backbone(cfg, bank, trials, ci, cj, dsx, dsy, dncc, band):
    print("\n" + "=" * 78)
    print(f"STEP 2 — EXHAUSTIVE AXIS-MANIFOLD SEARCH over the {len(ci)} consecutive steps")
    print("=" * 78)
    SH, nveto = _manifold_grid(cfg, band)
    print(f"  manifold: |cross| <= {band}, |along| <= {cfg.span}  ->  {len(SH):,} integer "
          f"shifts/pair ({nveto} removed by the near-zero veto r < {cfg.r0:.0f} px)")
    t = time.time()
    mv, msx, msy = bank.scan(ci, cj, SH)
    print(f"  {len(ci)} pairs x {len(SH):,} shifts = {len(ci) * len(SH):,} exact NCC "
          f"evaluations in {time.time() - t:.1f}s")

    if cfg.control:
        # Is the manifold prior doing statistical work, or merely saving compute? Say so.
        SP = _full_plane_grid(cfg, 2)
        t = time.time()
        pv, psx, psy = bank.scan(ci, cj, SP)
        agree = np.hypot(msx - psx, msy - psy) <= 4
        print(f"  CONTROL — stride-2 FULL PLANE ({len(SP):,} shifts, {time.time() - t:.1f}s): "
              f"the unconstrained\n           argmax agrees with the manifold argmax on "
              f"{int(agree.sum())}/{len(ci)} steps, and beats it by\n           >0.02 NCC on "
              f"{int((pv - mv > 0.02).sum())}. (Agreement everywhere => the prior saves "
              f"compute, it is not\n           doing statistical work — which is the honest "
              f"thing to be able to say.)")

    # TRAP GUARD: keep the incumbent unless clearly beaten.
    move = (mv - dncc) >= cfg.gain
    fsx, fsy, fncc = dsx.copy(), dsy.copy(), dncc.copy()
    if move.any():
        rsx, rsy = subpixel(bank, ci[move], cj[move], msx[move], msy[move])
        fsx[move] = rsx; fsy[move] = rsy; fncc[move] = mv[move]
    print(f"\n  TRAP GUARD: a step moves only if the manifold beats its incumbent by "
          f">= {cfg.gain} NCC.\n  -> {int(move.sum())} of {len(ci)} steps moved:")
    for q in np.where(move)[0]:
        d = np.hypot(fsx[q] - dsx[q], fsy[q] - dsy[q])
        print(f"      {trials[ci[q]]:3d}->{trials[cj[q]]:3d}  ({dsx[q]:7.1f},{dsy[q]:7.1f}) "
              f"ncc {dncc[q]:.3f}   ->   ({fsx[q]:7.1f},{fsy[q]:7.1f}) ncc {fncc[q]:.3f}   "
              f"(+{fncc[q] - dncc[q]:.3f}, moved {d:.0f} px)")
    lo = np.where(fncc < cfg.run_conf)[0]
    print(f"  backbone after correction: min ncc {np.nanmin(fncc):.3f}, "
          f"{len(lo)} steps still below {cfg.run_conf}"
          + ("" if not len(lo) else ": " + ", ".join(
              f"{trials[ci[q]]}->{trials[cj[q]]}({fncc[q]:.2f})" for q in lo)))
    return fsx, fsy, fncc, move


# =============================================================================
# STEP 3 — column identity as an eligibility gate on the all-to-all graph
# =============================================================================
def column_gate(cfg, trials, ii, jj, sx, sy, ci, cj, fsx, fsy, fncc):
    """Gate the graph on X ONLY. dy is never constrained, so the graph stays free to repair
    the vertical errors — which is where every remaining failure lives."""
    n = len(trials)
    print("\n" + "=" * 78)
    print(f"STEP 3 — COLUMN-IDENTITY GATE on the {len(ii):,}-pair all-to-all graph")
    print("=" * 78)
    conf = fncc >= cfg.conf
    turn = conf & (np.abs(fsx) > np.abs(fsy))
    print(f"  confident steps {int(conf.sum())}/{len(ci)};  TURN steps (|dx|>|dy|): "
          f"{int(turn.sum())}")
    for q in np.where(turn)[0]:
        print(f"      turn {trials[ci[q]]:3d}->{trials[cj[q]]:3d}  "
              f"({fsx[q]:7.1f},{fsy[q]:6.1f})  ncc {fncc[q]:.3f}")
    inc = conf & ~turn
    if inc.any():
        print(f"  in-column steps: |dx| median {np.median(np.abs(fsx[inc])):.2f} "
              f"max {np.abs(fsx[inc]).max():.2f}  <- a column is a near-perfect vertical line")
    if turn.sum():
        print(f"  column pitch (median |dx| over turns) = {np.median(np.abs(fsx[turn])):.1f} px")

    # x_chain: accumulate dx along the corrected backbone. An UNCONFIDENT step breaks the
    # chain into RUNS — we never gate on a column label we are not sure of.
    solid = fncc >= cfg.run_conf
    run = np.zeros(n, np.int64)
    xch = np.zeros(n)
    r = 0
    for k in range(len(ci)):
        if not solid[k]:
            r += 1
            xch[k + 1] = 0.0
        else:
            xch[k + 1] = xch[k] + fsx[k]
        run[k + 1] = r
    sizes = np.bincount(run)
    print(f"  chain broken by {int((~solid).sum())} step(s) below {cfg.run_conf} into "
          f"{r + 1} run(s) (largest {sizes.max()} tiles).\n  Pairs whose two tiles are in "
          f"DIFFERENT runs are EXEMPT from the gate — their column offset is\n  genuinely "
          f"unknown, and we never gate on a label we are not sure of.")

    same = run[ii] == run[jj]
    pred = xch[jj] - xch[ii]
    dev = np.abs(sx - pred)
    gateable = same & (jj - ii >= 2)                  # never gate a consecutive link
    kill = gateable & (dev > cfg.gate_tol)
    print(f"  gate: |dx_link - dx_chain| <= {cfg.gate_tol:.0f} px, applied to the "
          f"{int(gateable.sum()):,} non-consecutive\n  pairs inside a run -> KILLED "
          f"{int(kill.sum()):,} links "
          f"({100 * kill.sum() / max(1, gateable.sum()):.1f}% of gateable)")
    return ~kill, kill, run, xch


# =============================================================================
# The estimator: matched null -> top-N trust -> weighted least squares (IRLS)
# =============================================================================
def permutation_floor(cfg, bank, ii, jj, sx, sy):
    """A null for a max-over-25-aliases statistic must ITSELF be a max-over-25-aliases
    statistic, or it calibrates a number we never compute. (Taking the max over 25 aliases
    inflates the null by ~0.20 NCC — 0.265 -> 0.466. Getting this wrong lets pure noise
    links past the floor.)"""
    r = np.random.default_rng(cfg.seed)
    P = len(ii)
    a = r.integers(0, P, cfg.null_n)
    b = r.integers(0, P, cfg.null_n)
    b = np.where(b == a, (b + 1) % P, b)
    ax = np.array([[p, q] for p in ALIAS for q in ALIAS], float)
    SX = sx[b][:, None] + ax[None, :, 0]
    SY = sy[b][:, None] + ax[None, :, 1]
    V = bank.at(ii[a], jj[a], SX, SY)
    best = np.where(np.isnan(V), -np.inf, V).max(axis=1)
    best = best[np.isfinite(best)]
    floor = float(np.percentile(best, cfg.null_q))
    print(f"\n[null] matched permutation null, n={len(best)}: median {np.median(best):.3f}  "
          f"p{cfg.null_q} = FLOOR {floor:.3f}")
    return floor


def top_n_gate(ii, jj, ncc, keep, topn):
    """Keep a link only if it is among the topn best links of at least one of its ends."""
    per = defaultdict(list)
    for e in np.where(keep)[0]:
        per[int(ii[e])].append((ncc[e], e))
        per[int(jj[e])].append((ncc[e], e))
    ok = np.zeros(len(ii), bool)
    for lst in per.values():
        lst.sort(key=lambda z: -z[0])
        for _, e in lst[:topn]:
            ok[e] = True
    return ok


def solve_rigid(links, ctr=256):
    """Translation-only global least squares over links (a, b, shift, w), where a,b are
    TRIAL ids and shift == pos_b - pos_a. spectralign Placement.rigid (its `fix=` is buggy
    in 0.4.2, so we mean-centre ourselves instead)."""
    from spectralign import Placement
    plc = Placement()
    for a, b, sh, w in links:
        plc.addmatch(a, b, (ctr, ctr), (ctr - sh[0], ctr - sh[1]), weight=float(w))
    return {t: np.array(xy) for t, xy in plc.rigid().items()}


def solve_irls(links, r_drop, iters=6, ctr=256, protect=()):
    """`Placement.rigid` has no outlier rejection, so iteratively drop links whose residual
    exceeds `r_drop` and re-solve. Links in `protect` (the consecutive backbone) are never
    dropped — they are what keeps the graph connected."""
    prot = {frozenset(p) for p in protect}
    keep = list(links)
    pos = solve_rigid(keep, ctr)
    for _ in range(iters):
        nk = [(a, b, sh, w) for a, b, sh, w in keep
              if frozenset((a, b)) in prot
              or np.hypot(*(sh - (pos[b] - pos[a]))) < r_drop]
        if len(nk) == len(keep):
            break
        keep = nk
        pos = solve_rigid(keep, ctr)
    return pos, keep


def solve_positions(cfg, trials, ii, jj, sx, sy, ncc, eligible, floor, cons):
    """ONCE THE BACKBONE IS RIGHT, THE FAILURE MODE CHANGES — AND SO MUST THE ESTIMATOR.

    See idea (4) in the module docstring. Weighted least squares over the corrected
    backbone + the trusted gated cross-links.
    """
    print("\n" + "=" * 78)
    print("STEP 4 — WEIGHTED LEAST SQUARES over the corrected backbone + gated cross-links")
    print("=" * 78)
    v = eligible & np.isfinite(ncc)
    keep = v & (ncc >= floor)
    trusted = np.zeros(len(ii), bool)
    idx = np.where(keep)[0]
    if len(idx):
        tg = top_n_gate(ii[idx], jj[idx], ncc[idx], np.ones(len(idx), bool), cfg.topn)
        trusted[idx[tg]] = True
    trusted[cons] = True                      # the corrected consecutive steps always ride
    e = np.where(trusted)[0]

    bad_w = int(np.sum(~np.isfinite(ncc[e])))
    if bad_w:
        print(f"[solve] {bad_w} trusted link(s) have no measurable NCC (too little overlap); "
              f"giving them the minimum weight rather than a NaN one")
    links = []
    for k in e:
        w = ncc[k] if np.isfinite(ncc[k]) else 0.0
        links.append((trials[int(ii[k])], trials[int(jj[k])],
                      np.array([sx[k], sy[k]]), float(max(w, 1e-3))))
    n_cons = int(np.isin(e, cons).sum())
    print(f"[solve] {len(links):,} links ({n_cons} consecutive, {len(links) - n_cons} cross)")

    protect = [(trials[int(ii[k])], trials[int(jj[k])]) for k in cons]
    pos, kept = solve_irls(links, r_drop=cfg.r_drop, iters=cfg.irls_iters, protect=protect)
    print(f"[solve] IRLS kept {len(kept):,}/{len(links):,} links "
          f"(dropped {len(links) - len(kept)} with residual > {cfg.r_drop:.0f} px)")

    missing = [t for t in trials if t not in pos]
    if missing:
        raise RuntimeError(
            f"{len(missing)} snapshot(s) were never placed — the link graph is disconnected: "
            f"{missing[:12]}{'...' if len(missing) > 12 else ''}")
    return pos


# =============================================================================
# The whole method, end to end
# =============================================================================
def place(trials, frames, cfg=None, swim_cache=None):
    """Place `frames` (N,512,512 raw, acquisition order) -> {trial: (x, y)}.

    Returns (pos, info). `info` carries the diagnostics the steps printed, so the notebook
    can show them without re-deriving anything.
    """
    cfg = cfg or Config()
    trials = [int(t) for t in trials]
    n = len(trials)
    if n != len(frames):
        raise ValueError(f"{n} trials but {len(frames)} frames")
    if n < 4:
        raise ValueError(f"need at least 4 snapshots to place a mosaic, got {n}")

    gaps = [(trials[i], trials[i + 1]) for i in range(n - 1) if trials[i + 1] != trials[i] + 1]
    if gaps:
        print(f"\n  !! WARNING: the trial numbers are not contiguous — {len(gaps)} gap(s), "
              f"e.g. {gaps[:5]}.\n     T27 assumes consecutive snapshots are ONE acquisition "
              f"step apart (the serpentine\n     axis rule, idea 2). Across a gap that is "
              f"false, and the step may also exceed\n     span={cfg.span} px. The solve will "
              f"still run, but treat those steps with suspicion.\n")

    t0 = time.time()
    print(f"[data] {n} snapshots, trials {trials[0]}..{trials[-1]}")
    B = band_pass(frames)
    print(f"[data] band-passed (DoG 3-30) -> {B.shape}")

    # (1) every pair, no layout
    ii, jj, sh = swim_all(B, cache=swim_cache)
    bank = NccBank(B)
    bank.validate(ii, jj)

    sx, sy, ncc, good, n_moved = dealias(bank, ii, jj, sh)
    print(f"[dealias] {int(good.sum()):,}/{len(ii):,} pairs have a usable overlap; "
          f"{n_moved:,} moved off the rank-1 SWIM peak onto a +/-256 / +/-512 alias")

    cons = np.where(jj == ii + 1)[0]                  # the consecutive acquisition steps
    ci, cj = ii[cons], jj[cons]
    dsx, dsy, dncc = sx[cons].copy(), sy[cons].copy(), ncc[cons].copy()

    band, _ = precheck(cfg, trials, ci, cj, dsx, dsy, dncc)                      # STEP 1
    fsx, fsy, fncc, moved = fix_backbone(cfg, bank, trials, ci, cj,
                                         dsx, dsy, dncc, band)                   # STEP 2

    sxF, syF, nccF = sx.copy(), sy.copy(), ncc.copy()   # corrected backbone -> the graph
    sxF[cons], syF[cons], nccF[cons] = fsx, fsy, fncc

    elig, killed, run, xch = column_gate(cfg, trials, ii, jj, sxF, syF,
                                         ci, cj, fsx, fsy, fncc)                 # STEP 3

    floor = permutation_floor(cfg, bank, ii, jj, sx, sy)
    pos = solve_positions(cfg, trials, ii, jj, sxF, syF, nccF,
                          elig, floor, cons)                                     # STEP 4

    del bank
    _free()
    dt = time.time() - t0
    print(f"\n[done] placed {len(pos)} snapshots in {dt:.0f}s "
          f"({'GPU' if on_gpu() else 'CPU'})")

    info = dict(n_tiles=n, n_pairs=int(len(ii)), band=int(band),
                n_steps_moved=int(moved.sum()), n_links_killed=int(killed.sum()),
                n_alias_moved=int(n_moved), floor=float(floor),
                backbone_min_ncc=float(np.nanmin(fncc)),
                backbone_med_ncc=float(np.nanmedian(fncc)),
                n_runs=int(run.max() + 1), seconds=float(dt), gpu=bool(on_gpu()),
                gaps=gaps, config=vars(cfg).copy())
    return {t: np.asarray(p, float) for t, p in pos.items()}, info
