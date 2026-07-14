"""Canonical PLACEMENT-quality metric — the shared judge for every build.

Rendering can hide bad geometry, so we score the geometry directly against the PIXELS:
for every pair of tiles that overlap in the layout, crop the overlap region from each
band-passed (DoG) frame at the solved relative offset and take the zero-mean normalised
cross-correlation (NCC). High NCC = the tissue actually registers there; ~0 = the two
tiles are misplaced relative to each other. This does NOT trust SWIM snr or the solver.

Use `score_positions(...)` on any {trial:(x,y)} layout or positions.csv, or
`leaderboard()` to rank every build in output/mosaic/. All builds MUST be compared with
this one function so the numbers are commensurable.
"""
from pathlib import Path
import numpy as np


def band_pass(frames, lo=3, hi=30):
    import cv2
    return np.stack([cv2.GaussianBlur(f, (0, 0), lo) - cv2.GaussianBlur(f, (0, 0), hi)
                     for f in np.asarray(frames, np.float32)]).astype(np.float32)


def overlap_ncc(A, B, sx, sy, minov=3600, minside=40):
    """NCC of the overlap of band-passed tiles A,B when B sits at offset (sx,sy) from A
    (i.e. sx,sy = posB - posA). NaN if the overlap is too small to be meaningful."""
    sx, sy = int(round(sx)), int(round(sy))
    H, W = A.shape
    ax0, ax1 = max(0, sx), min(W, W + sx)
    ay0, ay1 = max(0, sy), min(H, H + sy)
    ow, oh = ax1 - ax0, ay1 - ay0
    if ow < minside or oh < minside or ow * oh < minov:
        return np.nan
    a = A[ay0:ay1, ax0:ax1].astype(np.float64)
    b = B[ay0 - sy:ay1 - sy, ax0 - sx:ax1 - sx].astype(np.float64)
    a -= a.mean(); b -= b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d > 0 else np.nan


def score_positions(pos, bp, trials, near=480):
    """`pos`: {trial:(x,y)}; `bp`: band-passed frames in `trials` order; `trials`: the
    trial id per bp row. Returns a dict of aggregate + per-tile placement scores.

    Headline numbers:
      med         median overlap-NCC over ALL overlapping pairs   (want high, ~0.6+)
      frac_good   fraction of overlapping pairs with NCC > 0.5     (want high)
      cons_med    median NCC over CONSECUTIVE pairs (the backbone) (A already ~0.70)
      n_bad_tiles tiles whose median link NCC < 0.3 (misplaced)    (want ~0)
    """
    TI = {int(t): i for i, t in enumerate(trials)}
    ts = [int(t) for t in sorted(pos) if int(t) in TI]
    P = np.array([pos[t] for t in ts]); idx = [TI[t] for t in ts]
    D = np.hypot(P[:, None, 0] - P[None, :, 0], P[:, None, 1] - P[None, :, 1])
    per = {t: [] for t in ts}
    allv, consv = [], []
    for a in range(len(ts)):
        for b in range(a + 1, len(ts)):
            if D[a, b] >= near:
                continue
            v = overlap_ncc(bp[idx[a]], bp[idx[b]], P[b, 0] - P[a, 0], P[b, 1] - P[a, 1])
            if np.isnan(v):
                continue
            allv.append(v); per[ts[a]].append(v); per[ts[b]].append(v)
            if abs(ts[a] - ts[b]) == 1:
                consv.append(v)
    allv = np.array(allv); consv = np.array(consv) if consv else np.array([np.nan])
    permed = {t: (float(np.median(v)) if v else np.nan) for t, v in per.items()}
    nbad = sum(1 for m in permed.values() if not np.isnan(m) and m < 0.3)
    return dict(n_pairs=int(len(allv)),
                med=float(np.median(allv)) if len(allv) else np.nan,
                mean=float(np.mean(allv)) if len(allv) else np.nan,
                frac_good=float((allv > 0.5).mean()) if len(allv) else np.nan,
                cons_med=float(np.nanmedian(consv)),
                n_bad_tiles=int(nbad), n_tiles=len(ts),
                per_tile=permed)


# --- convenience over the output/mosaic tree ------------------------------------------
import os as _os
# Builds are only commensurable WITHIN a trial range, so output/mosaic/ is split into
# trials_<lo>-<hi>_n<count>/ subfolders. MROOT selects the ACTIVE range; override with the
# CAMEA_MOSAIC_ROOT env var to score/rank a different range. (Metric math is unchanged.)
_MBASE = Path("D:/Projects/Camea/analysis/output/mosaic")
MROOT = Path(_os.environ.get("CAMEA_MOSAIC_ROOT", str(_MBASE / "trials_015-166_n152")))
# Each range folder owns its stack + trial list: _frames/{frames.npy, trials.json}.
# Row i of frames.npy IS trials[i]. Everything resolves from MROOT alone.
_FRAMES = MROOT / "_frames" / "frames.npy"
_TRIALS_JSON = MROOT / "_frames" / "trials.json"
_BP = None


def _bp_and_trials():
    """Band-passed A-frame stack + the trial ids in that stack's order, cached in-process.

    frames.npy is written by io.load_frames over io.list_trials(trial_min, trial_max), so the
    trial ids are derived from A's build.json (the range that produced the cache) using the
    same "xml exists on disk" rule -- this stays correct for ANY trial window, not just 11-347.
    """
    global _BP
    if _BP is None:
        fr = np.load(_FRAMES)
        _BP = band_pass(fr)
    import json
    if _TRIALS_JSON.exists():                           # per-range sidecar: row i == trials[i]
        trials = json.loads(_TRIALS_JSON.read_text())
    else:                                               # legacy: derive from A's build.json
        bj = json.loads((MROOT / "260620d__A_fullframe" / "build.json").read_text())
        root = Path(bj["data_root"]) / bj["date_dir"]
        trials = [t for t in range(int(bj["trial_min"]), int(bj["trial_max"]) + 1)
                  if (root / f"{t:03d}.xml").exists()]
        if len(trials) != _BP.shape[0]:                 # cache/range mismatch -> A's placed order
            import pandas as pd
            trials = sorted(int(t) for t in
                            pd.read_csv(MROOT / "260620d__A_fullframe" / "positions.csv").trial)
    if len(trials) != _BP.shape[0]:
        raise RuntimeError(f"trial list ({len(trials)}) != frame rows ({_BP.shape[0]}) in {MROOT}")
    return _BP, trials


def score_build(build_id, near=480):
    import pandas as pd
    bp, trials = _bp_and_trials()
    df = pd.read_csv(MROOT / build_id / "positions.csv")
    pos = {int(t): (float(x), float(y)) for t, x, y in df[["trial", "x", "y"]].itertuples(index=False)}
    s = score_positions(pos, bp, trials, near)
    s.pop("per_tile", None)
    s["build_id"] = build_id
    return s


def leaderboard(near=480):
    import pandas as pd
    rows = [score_build(p.name, near) for p in sorted(MROOT.glob("260620d__*"))
            if (p / "positions.csv").exists()]
    lb = pd.DataFrame(rows).sort_values("med", ascending=False)
    return lb[["build_id", "med", "frac_good", "cons_med", "n_bad_tiles", "n_tiles", "n_pairs"]]


def quality_plot(pos, bp, trials, path, title="", near=480):
    """Scatter of tiles coloured by per-tile median overlap NCC (red=misplaced,
    green=good), with the worst tile ids labelled. Saves to `path`."""
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    s = score_positions(pos, bp, trials, near)
    ts = sorted(pos); P = np.array([pos[t] for t in ts]) + 256
    mv = np.array([s["per_tile"].get(int(t), np.nan) for t in ts])
    span = P.max(0) - P.min(0)
    fig, ax = plt.subplots(figsize=(8, float(np.clip(8 * span[1] / max(span[0], 1) / 3, 6, 40))))
    sc = ax.scatter(P[:, 0], P[:, 1], c=mv, cmap="RdYlGn", vmin=0, vmax=0.7, s=55)
    for (x, y), t, m in zip(P, ts, mv):
        if not np.isnan(m) and m < 0.3:
            ax.annotate(str(int(t)), (x, y), fontsize=6, ha="center", va="center")
    ax.set_aspect("equal"); ax.invert_yaxis()
    plt.colorbar(sc, label="median overlap NCC")
    ax.set_title(f"{title}\nmed {s['med']:.3f}  good {s['frac_good']:.2f}  "
                 f"cons {s['cons_med']:.3f}  bad-tiles {s['n_bad_tiles']}/{s['n_tiles']}")
    fig.savefig(path, dpi=110, bbox_inches="tight"); plt.close(fig)
    return s
