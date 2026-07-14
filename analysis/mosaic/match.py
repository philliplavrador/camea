"""Stage (3): the SWAPPABLE shift source -- how a pairwise snapshot displacement
`X_j - X_i` is measured. This is the ONLY stage that differs between builds; the
backbone/refine/render stages (solve.py, render.py) are identical regardless.

Every matcher exposes the same small interface, used by solve.py + render.py:
  .trials, .TI              trial ids (acquisition order) and id -> index map
  .backbone_step(i)         shift trials[i] -> trials[i+1] for the initial chain, or None
  .backbone_link(i, P)      always-kept consecutive link (a, b, shift, weight) for refine
  .loop_link(i, j, P, tol)  candidate non-consecutive link (a, b, shift, weight), or None
  .frame(t)                 raw float frame for trial t (for the render stage)

Note: solve.py walks consecutive positions i -> i+1. This assumes `trials` is
contiguous (no holes), which holds for 260620d (trials 11..347, all present).
"""
from pathlib import Path
import numpy as np


class FullframeMatcher:
    """Full-frame SWIM (Signal Whitening Image Matching) on whole 512x512 frames.
    Unambiguous to +/-256 px; ~400 px of shared tissue lets the true correlation peak
    beat the periodic electrode grid, so it is grid-robust out of the box (reads no
    run_swim results). Matches on the band-passed frames, renders the raw frames."""

    def __init__(self, trials, frames, match_imgs, snr_min):
        from spectralign.image import Image
        self.trials = list(trials)
        self.TI = {t: i for i, t in enumerate(self.trials)}
        self.frames = frames
        self.snr_min = snr_min
        self._imgs = [Image(np.asarray(m, float)) for m in match_imgs]
        self._cache = {}

    def match(self, i, j):
        """Full-frame SWIM between trials[i] and trials[j]; returns (shift X_j-X_i, snr),
        cached so each frame pair is aligned at most once."""
        from spectralign.swim import Swim
        if (i, j) not in self._cache:
            sw = Swim().align(self._imgs[i], self._imgs[j])
            dx, dy = sw.shift
            self._cache[(i, j)] = (np.array([-dx, -dy]), float(sw.snr))  # X_j - X_i = (-dx, -dy)
        return self._cache[(i, j)]

    def backbone_step(self, i):
        sh, _ = self.match(i, i + 1)
        return sh

    def backbone_link(self, i, P):
        a, b = self.trials[i], self.trials[i + 1]
        sh, snr = self.match(i, i + 1)
        return (a, b, sh, max(snr, 1.0))

    def loop_link(self, i, j, P, tol):
        sh, snr = self.match(i, j)
        if snr >= self.snr_min and np.hypot(*(sh - (P[j] - P[i]))) < tol:
            return (self.trials[i], self.trials[j], sh, snr)
        return None

    def frame(self, t):
        return self.frames[self.TI[t]].astype(float)

    def stats(self):
        return f"SWIM cache {len(self._cache)}"


class SubregionMatcher:
    """Subregion overlap-pairing consensus, from a run_swim `comparisons/results.csv`.
    Each subregion-pair SWIM shift is converted to a whole-snapshot shift
    `X_b - X_a = (o_x_a - o_x_b - dx, o_y_a - o_y_b - dy)`; a per-pair consensus anchors
    on the highest-SNR (overlap) pairing and rejects the +/-grid-period alias pairings.
    Renders raw frames loaded on demand via vscope."""

    def __init__(self, run_dir, data_root, date_dir, snr_min, clus_tol, prior_tol,
                 min_sup, ccd_key="Cc", frame_idx=0, trial_min=None, trial_max=None):
        import pandas as pd
        run_dir = Path(run_dir)
        self.data_root = Path(data_root)
        self.date_dir = date_dir
        self.ccd_key = ccd_key
        self.frame_idx = frame_idx
        self.clus_tol = clus_tol
        self.prior_tol = prior_tol
        self.min_sup = min_sup

        meta = pd.read_csv(run_dir / "subregions" / "metadata.csv")
        off_x = dict(zip(meta.stack_index, meta.crop_x_start))
        off_y = dict(zip(meta.stack_index, meta.crop_y_start))

        df = pd.read_csv(run_dir / "comparisons" / "results.csv",
                         usecols=["trial_a", "subregion_a_index", "trial_b",
                                  "subregion_b_index", "dx", "dy", "snr", "status"])
        self.n_all = len(df)
        # Restrict to a trial window (both trials in range). The run_swim results.csv is
        # all-to-all, so any sub-range's pairwise comparisons are already present here --
        # no need to re-run the pipeline; just keep the rows whose BOTH trials are in range.
        if trial_min is not None:
            df = df[(df.trial_a >= trial_min) & (df.trial_b >= trial_min)]
        if trial_max is not None:
            df = df[(df.trial_a <= trial_max) & (df.trial_b <= trial_max)]
        df = df[(df.status == "ok") & (df.snr >= snr_min)].copy()
        # convert each subregion PAIRING to a whole-snapshot shift X_b - X_a
        df["ix"] = df.subregion_a_index.map(off_x) - df.subregion_b_index.map(off_x) - df.dx
        df["iy"] = df.subregion_a_index.map(off_y) - df.subregion_b_index.map(off_y) - df.dy

        self.GRP = {}
        for key, g in df.groupby(["trial_a", "trial_b"]):
            self.GRP[key] = (g.ix.to_numpy(), g.iy.to_numpy(), g.snr.to_numpy())
        self.trials = sorted(pd.unique(pd.concat([df.trial_a, df.trial_b])).tolist())
        self.TI = {t: i for i, t in enumerate(self.trials)}
        self.n_ok = len(df)

    def consensus(self, a, b, pred=None):
        """One robust snapshot shift X_b - X_a for pair (a,b) from its subregion pairings.
        Anchors on the highest-confidence (overlap) pairing and takes the SNR-weighted
        mean of the tightest cluster, rejecting grid-alias pairings. With a prior
        prediction, only the cluster near it is considered."""
        if (a, b) not in self.GRP:
            return None
        ix, iy, snr = self.GRP[(a, b)]
        sel = np.ones(len(ix), bool)
        if pred is not None:
            sel = np.hypot(ix - pred[0], iy - pred[1]) < self.prior_tol
            if not sel.any():
                return None
        idx = np.where(sel)[0]
        anchor = idx[np.argmax(snr[idx])]                                # highest-confidence pairing
        clus = idx[np.hypot(ix[idx] - ix[anchor], iy[idx] - iy[anchor]) < self.clus_tol]
        if len(clus) < self.min_sup:
            return None
        w = snr[clus]
        return np.array([np.sum(ix[clus] * w) / w.sum(),
                         np.sum(iy[clus] * w) / w.sum()]), float(w.sum())

    def backbone_step(self, i):
        c = self.consensus(self.trials[i], self.trials[i + 1])
        return c[0] if c else None

    def backbone_link(self, i, P):
        a, b = self.trials[i], self.trials[i + 1]
        c = self.consensus(a, b)
        if c:
            return (a, b, c[0], max(c[1], 1.0))
        return (a, b, P[self.TI[b]] - P[self.TI[a]], 0.5)   # weak fallback keeps graph connected

    def loop_link(self, i, j, P, tol):
        a, b = self.trials[i], self.trials[j]
        c = self.consensus(a, b, pred=P[j] - P[i])          # pairing agreeing with current layout
        if c and np.hypot(*(c[0] - (P[j] - P[i]))) < tol:
            return (a, b, c[0], c[1])
        return None

    def frame(self, t):
        import vscope
        vs = vscope.load(str(self.data_root / self.date_dir / f"{int(t):03d}.xml"))
        return np.asarray(vs.ccd[self.ccd_key][self.frame_idx], float)

    def stats(self):
        return f"{len(self.GRP)} compared pairs"


class FusedMatcher:
    """Combine the two independent shift sources: full-frame SWIM AND subregion consensus.
    Placement follows the grid-robust full-frame SWIM, but every link is CORROBORATED with
    the subregion overlap-pairing consensus for that pair:
      - backbone link: full-frame shift, with its weight boosted when the subregion
        consensus (searched near the full-frame answer) agrees within `fuse_tol`;
      - loop link: accepted ONLY when the full-frame SWIM agrees with the current layout
        AND the subregion consensus corroborates it within `fuse_tol` -> two agreeing
        methods must independently vote for a non-consecutive link before it is trusted,
        which is far stricter than either alone (kills the residual grid aliases).
    Renders whatever frame `ff` holds (raw; run.py flat-fields for the render stage)."""

    def __init__(self, ff: "FullframeMatcher", sub: "SubregionMatcher", fuse_tol, snr_min):
        self.ff = ff
        self.sub = sub
        self.fuse_tol = fuse_tol
        self.snr_min = snr_min
        self.trials = ff.trials
        self.TI = ff.TI
        self.frames = ff.frames
        self._corr = 0            # count of corroborated links (diagnostic)

    def _sub(self, a, b, pred):
        """Subregion consensus for (a,b) searched near the full-frame prediction `pred`,
        or None if that pair was not compared / has no agreeing cluster."""
        if (a, b) not in self.sub.GRP:
            return None
        return self.sub.consensus(a, b, pred=pred)

    def backbone_step(self, i):
        return self.ff.backbone_step(i)

    def backbone_link(self, i, P):
        a, b, sh, w = self.ff.backbone_link(i, P)
        c = self._sub(a, b, sh)
        if c is not None and np.hypot(*(c[0] - sh)) < self.fuse_tol:
            w = w + c[1]                                  # both methods agree -> trust more
            self._corr += 1
        return (a, b, sh, w)

    def loop_link(self, i, j, P, tol):
        sh, snr = self.ff.match(i, j)
        if snr < self.snr_min or np.hypot(*(sh - (P[j] - P[i]))) >= tol:
            return None
        c = self._sub(self.trials[i], self.trials[j], sh)
        if c is None or np.hypot(*(c[0] - sh)) >= self.fuse_tol:
            return None                                   # require subregion corroboration
        self._corr += 1
        return (self.trials[i], self.trials[j], sh, snr + c[1])

    def frame(self, t):
        return self.ff.frame(t)

    def stats(self):
        return f"fused: {self._corr} corroborated, ff cache {len(self.ff._cache)}"
