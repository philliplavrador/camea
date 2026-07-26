"""Score a mosaic build against the hand-verified ground truth. **DEV / BENCHMARK ONLY.**

⚠️ **THIS LIVES UNDER `tests/`, NOT INSIDE THE INSTALLABLE PACKAGE — ON PURPOSE.** It carries the
only dataset-shaped knowledge the scorer needs: `RANGES` (the 260620d denominators 156/156/312, the
trial ranges 11/166/167/348 and the `260620d_*.json` filenames) and `range_of()`'s 166/167 split.
The app carries no dataset knowledge — a hard rule with no toggle — and a pip-installable wheel must
not either, so this module is not shipped under `src/camea/`. It moved here from
`src/camea/engine/score.py` (`docs/ENGINE_MOVE.md` §3 argued for exactly this) and its only callers
are the regression guards under `tests/`. It **excludes nothing** and **decides nothing** (see
`set_excluded()` below): the exclusion ruling is always injected by the caller.

THE METRIC
----------
For every tile, how far is the build's placement from where the human put it?

A mosaic is only defined up to a GLOBAL SHIFT -- the whole assembled picture can sit
anywhere on the canvas and still be the same picture. So the shift is a nuisance
parameter, and before measuring anything we must slide the build's layout onto the
ground truth's. `robust_align` picks the shift that puts the MOST tiles inside their
tolerance. That is exactly the criterion the human audited by:

    "correct = tile sits in the right place relative to the biggest correct chain"

Crucially this cannot be gamed: the only freedom is one translation, so a build never
gains by placing a tile wrongly -- it can only gain by placing tiles where the human
placed them. A plain least-squares / MEAN fit WOULD be gameable in the other direction: a
build with many broken tiles gets its whole frame dragged by them, so its correct tiles are
scored as wrong. Hence the consensus fit.

⚠️ `robust_align` IS PROVEN CODE -- COPIED VERBATIM FROM THE ARCHIVED SCORER. DO NOT
REIMPLEMENT IT. A reimplementation with a different tie-break scored the SAME T27 positions
at 152/156 where this one gives 155/156. If you think you have a cleaner version, you have a
different scorer, and every number in RESULTS.md becomes incomparable.

⛔ THE EXCLUSION RULE
--------------------
Some snapshots are thrown out by the human. In a ground-truth doc they carry `status: "excluded"`
with x/y = null. This scorer counts ONLY `status == "anchor"` tiles -- so a denominator can never
quietly become 182 or 338. And if a build emits a position for a trial the human threw out, that
build LOADED a frame it was forbidden to load: the report is flagged `rule_break=True`, loudly. It
is not silently dropped.

⛔ **BUT THE LIST OF THROWN-OUT TRIALS IS NOT IN THIS FILE, AND MUST NEVER BE.** `EXCLUDED` starts
**empty** and is injected by the caller (`set_excluded()`), from the ruling that lives next to the
answer key it belongs to (`<CAMEA_GT_DIR>/excluded.py`). The app carries no dataset knowledge; that
is a hard rule with no toggle. A guard that wants a real `rule_break` check must inject the list and
assert that it did.

Headline: `pct_of_gt` -- % of ANCHOR tiles landing within 10 px of the human position.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np

# --- where the answer key lives -------------------------------------------------------
# ⛔ THE GROUND-TRUTH JSONs ARE NOT IN THE REPO AND MUST NEVER BE COMMITTED. They are the human's
# hand-authored answer key; committing them destroys the benchmark for everyone who clones. They
# live under archive/, which .gitignore excludes wholesale. Keep it that way.
#
# Resolved LAZILY, at call time, never at import: an import of this module must not depend on a
# research artefact being present on disk.
#
# ⚠️ parents[2], because this file is tests/guard/score.py: parents[0]=guard, parents[1]=tests,
# parents[2]=the repo root. (It was parents[3] under the old src/camea/engine/ home.)
_DEFAULT_GT_DIR = Path(__file__).resolve().parents[2] / "archive" / "analysis" / "ground_truth"

_NO_GT = """\
THE GROUND TRUTH IS NOT ON THIS MACHINE — nothing can be scored.

  looked in : {path}
  set it    : CAMEA_GT_DIR=<dir>     (PowerShell:  $env:CAMEA_GT_DIR = '<dir>')

That directory must hold the hand-authored answer key and the exclusion ruling it belongs to:
    260620d_pass1_11-166.json
    260620d_pass2_167-348.json
    260620d_merged_11-348.json
    excluded.py

⛔ Those files are NOT in the repo and MUST NEVER BE COMMITTED.
"""


def gt_dir() -> Path:
    """The ground-truth directory: `$CAMEA_GT_DIR`, else the archived research tree. LOUD if absent."""
    p = Path(os.environ.get("CAMEA_GT_DIR") or _DEFAULT_GT_DIR)
    if not p.is_dir():
        raise RuntimeError(_NO_GT.format(path=p))
    return p


# THE CHALLENGE CRITERION: a tile is correct if it lands within this many px of the human
# position. 10 px is a strict, near-exact test -- and it costs nothing, because placement
# failure here is BINARY: a tile is either sub-pixel right or hundreds of px wrong. Measured:
# the top builds score identically at 10 px and at 256 px. SWIM either locks the correct
# correlation peak or a wrong peak / grid alias; it does not drift.
DEFAULT_TOL = 10.0

# reported alongside the headline, so the binary-failure claim stays visible (and so a build
# that IS merely drifting would show up as a rising curve instead of a flat line)
TOL_LADDER = (5, 10, 25, 50, 96, 256)

# --- the three ranges, each with its own human ground truth and its own denominator --------
# ⚠️ 260620d. `gt` is a FILENAME, resolved against gt_dir() at call time — never an absolute path
# baked in at import.
RANGES = {
    "pass1":  dict(lo=11,  hi=166, n=156, gt="260620d_pass1_11-166.json",
                   label="pass 1 (11-166)",
                   note="SOLVED by T27 (156/156). The CONTROL, not the target."),
    "pass2":  dict(lo=167, hi=348, n=156, gt="260620d_pass2_167-348.json",
                   label="pass 2 (167-348)",
                   note="156 usable tiles, NOT 182 -- 26 trials are excluded."),
    "merged": dict(lo=11,  hi=348, n=312, gt="260620d_merged_11-348.json",
                   label="merged (11-348)",
                   note="THE TARGET. 312 usable tiles, NOT 338."),
}
DEFAULT_RANGE = "merged"


# --- the exclusion ruling: INJECTED, never stored ------------------------------------------
EXCLUDED: frozenset[int] = frozenset()   # ⛔ EMPTY. The app knows no trial numbers. See the docstring.


def set_excluded(trials) -> frozenset[int]:
    """Hand this scorer the human's thrown-out trials, for the `rule_break` check.

    ⛔ The caller owns this list. It comes from the human or from the ruling that ships beside the
    answer key (`<CAMEA_GT_DIR>/excluded.py`), and it is never hard-coded here. Until it is set,
    `rule_break` is vacuously False — so a guard that relies on it MUST call this and MUST assert
    that what it injected is non-empty.
    """
    global EXCLUDED
    EXCLUDED = frozenset(int(t) for t in trials)
    return EXCLUDED


def range_of(trials) -> str:
    """Which range a build belongs to, from the trials it actually placed."""
    ts = [t for t in trials]
    if not ts:
        return DEFAULT_RANGE
    if max(ts) <= 166:
        return "pass1"
    if min(ts) >= 167:
        return "pass2"
    return "merged"


# --- loading --------------------------------------------------------------------------
def load_gt(path=None, rng=None):
    """{trial: {'xy': array([x,y]), 'r': float, 'status': 'anchor'}} for every ANCHOR tile.

    ⛔ ONLY `status == "anchor"` tiles are returned. `excluded` tiles (the thrown-out snapshots; x/y
    are null) and any legacy `pending`/`region` rows carry no scorable position and are dropped here,
    so a denominator can never quietly become 182 or 338."""
    if path is None:
        path = gt_dir() / RANGES[rng or DEFAULT_RANGE]["gt"]     # resolved HERE, not at import
    path = Path(path)
    if not path.exists():
        raise RuntimeError(_NO_GT.format(path=path.parent) + f"\n  missing: {path.name}")
    doc = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for k, v in doc["tiles"].items():
        if v.get("status") != "anchor" or v.get("x") is None or v.get("y") is None:
            continue
        out[int(k)] = dict(xy=np.array([float(v["x"]), float(v["y"])]),
                           r=float(v.get("r", doc["tolerance_px"]["region_default"])),
                           status="anchor")
    return out, doc


def excluded_in(build) -> list[int]:
    """Trials in a build that should never have been loaded at all. Non-empty == RULE BREAK."""
    return sorted(t for t in build if t in EXCLUDED)


# --- the alignment --------------------------------------------------------------------
# ⚠️ VERBATIM from analysis/benchmark/score.py, which took it VERBATIM from the archived scorer.
# PROVEN. Touch nothing.
def robust_align(build, gt, max_iter=20):
    """Translation `t` (build + t -> gt frame) maximising the number of tiles that land
    within their own tolerance. Returns (t, inlier_trials, n_candidates_tied).

    Exhaustive 1-point consensus: every shared tile proposes the shift that would make
    IT exact; score each proposal by how many other tiles it also brings inside tolerance;
    keep the best, then re-fit on its inliers (mean) and re-collect until stable. n is
    small (~312) so the O(n^2) sweep is free and there is no random seed / RANSAC luck.
    """
    shared = sorted(set(build) & set(gt))
    if len(shared) < 2:
        raise SystemExit(f"only {len(shared)} tiles shared with the ground truth")
    B = np.array([build[t] for t in shared])          # build positions
    G = np.array([gt[t]["xy"] for t in shared])       # truth positions
    R = np.array([gt[t]["r"] for t in shared])        # per-tile tolerance
    O = G - B                                         # per-tile implied shift

    def inliers_of(t):
        return np.hypot(*(O - t).T) <= R

    # 1-point consensus sweep: each tile's own implied shift is a candidate
    best_t, best_mask, best_key = None, None, (-1, np.inf)
    n_tied = 0
    for c in O:
        m = inliers_of(c)
        n = int(m.sum())
        # tie-break on tightness: median residual among the inliers
        med = float(np.median(np.hypot(*(O[m] - c).T))) if n else np.inf
        key = (-n, med)
        if key < best_key:
            best_t, best_mask, best_key, n_tied = c.copy(), m, key, 1
        elif key == best_key:
            n_tied += 1

    # re-fit on the consensus set and re-collect, until the inlier set stops changing
    t = best_t
    mask = best_mask
    for _ in range(max_iter):
        if not mask.any():
            break
        t_new = O[mask].mean(0)
        m_new = inliers_of(t_new)
        if m_new.sum() < mask.sum():        # never let a refit shrink the consensus
            break
        t, changed = t_new, not np.array_equal(m_new, mask)
        mask = m_new
        if not changed:
            break

    return t, [shared[i] for i in np.where(mask)[0]], n_tied


def residual_rotation_deg(build, gt, inliers):
    """Rotation implied by the inlier set (sanity check -- builds share one orientation,
    so this must be ~0). Closed-form 2D fit; np.linalg.svd can abort this env's LAPACK."""
    if len(inliers) < 3:
        return 0.0
    B = np.array([build[t] for t in inliers], float)
    G = np.array([gt[t]["xy"] for t in inliers], float)
    b, g = B - B.mean(0), G - G.mean(0)
    a = float((b[:, 0] * g[:, 0] + b[:, 1] * g[:, 1]).sum())
    c = float((b[:, 0] * g[:, 1] - b[:, 1] * g[:, 0]).sum())
    return float(np.degrees(np.arctan2(c, a)))


# --- the score ------------------------------------------------------------------------
def with_tol(gt, tol):
    """The same ground truth with every tolerance forced to `tol` px (None = keep each
    tile's own `r`). The challenge scores at tol=10."""
    if tol is None:
        return gt
    return {t: dict(v, r=float(tol)) for t, v in gt.items()}


def score(build, gt, build_id=None, tol=DEFAULT_TOL, rng=None):
    """Full report dict for one build. `build`/`gt` as returned by the loaders above.

    `tol` overrides every tile's own `r` (default: the 10 px challenge criterion). Pass
    tol=None to score against the per-tile `r` recorded in the ground-truth file.

    The denominator is `n_gt` -- the ANCHOR tiles of this range (156/156/312). A build that
    places fewer is not let off: `n_missing` says how many it never placed, and `pct_correct`
    is over the tiles it shares with the truth, so `pct_of_gt` is also reported (correct /
    all anchors), which is the honest headline for a partial build."""
    gt = with_tol(gt, tol)
    t, inliers, n_tied = robust_align(build, gt)
    shared = sorted(set(build) & set(gt))

    per = {}
    for tr in shared:
        d = float(np.hypot(*(build[tr] + t - gt[tr]["xy"])))
        per[tr] = dict(err=d, r=gt[tr]["r"], ok=bool(d <= gt[tr]["r"]))

    err = np.array([per[tr]["err"] for tr in shared])
    ok = np.array([per[tr]["ok"] for tr in shared])
    n = len(shared)
    bad_trials = excluded_in(build)          # ⛔ frames that should never have been loaded

    rep = dict(
        build_id=build_id,
        range=rng or range_of(build),
        tol=float(gt[shared[0]]["r"]),                 # the criterion this run was scored at
        n_tiles=n,                                     # tiles shared with the truth
        n_gt=len(gt),                                  # THE DENOMINATOR: 156 / 156 / 312 anchors
        n_missing=len(set(gt) - set(build)),           # GT tiles the build never placed
        n_correct=int(ok.sum()),
        pct_correct=100.0 * float(ok.mean()),          # <-- THE HEADLINE
        pct_of_gt=100.0 * int(ok.sum()) / len(gt),     # correct / ALL anchors (== headline if complete)
        median_err=float(np.median(err)),
        mean_err=float(err.mean()),
        rmse=float(np.sqrt((err ** 2).mean())),
        p90_err=float(np.percentile(err, 90)),
        max_err=float(err.max()),
        n_inliers=len(inliers),                        # size of the consensus used to align
        align_dx=float(t[0]), align_dy=float(t[1]),
        rot_deg=residual_rotation_deg(build, gt, inliers),
        n_tied=n_tied,
        wrong=[int(tr) for tr in shared if not per[tr]["ok"]],
        # ⛔ THE EXCLUSION RULE. Never silent.
        rule_break=bool(bad_trials),
        excluded_placed=bad_trials,
        per_tile={int(k): v for k, v in per.items()},
    )
    for tol_ in TOL_LADDER:
        rep[f"pct_within_{tol_}"] = 100.0 * float((err <= tol_).mean())
    return rep
