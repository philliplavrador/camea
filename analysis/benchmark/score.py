"""Score a mosaic build against the hand-verified ground truth.

    python analysis/benchmark/score.py <positions.csv> [--range merged|pass1|pass2] [-v]
    python analysis/benchmark/score.py <positions.csv> --gt analysis/ground_truth/260620d_merged_11-348.json

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
26 snapshots (284-296, 299, 300-310, 348) are THROWN OUT. They are not data. In the ground
truth they carry `status: "excluded"` with x/y = null. This scorer counts ONLY
`status == "anchor"` tiles -- the denominators are 156 (pass 1) / 156 (pass 2) / 312 (merged),
never 182 or 338. And if a build emits a position for an excluded trial, that build LOADED a
frame it was forbidden to load: the scorer says so, loudly, and flags the report
`rule_break=True`. It is not silently dropped.

Headline: `pct_correct` -- % of ANCHOR tiles landing within 10 px of the human position.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                                   # analysis/
GT_DIR = ROOT / "ground_truth"

sys.path.insert(0, str(GT_DIR))
from excluded import EXCLUDED, usable_trials, gaps   # THE canonical trial list. Never hard-code one.

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
RANGES = {
    "pass1":  dict(lo=11,  hi=166, n=156, gt=GT_DIR / "260620d_pass1_11-166.json",
                   label="pass 1 (11-166)",
                   note="SOLVED by T27 (156/156). The CONTROL, not the target."),
    "pass2":  dict(lo=167, hi=348, n=156, gt=GT_DIR / "260620d_pass2_167-348.json",
                   label="pass 2 (167-348)",
                   note="156 usable tiles, NOT 182 -- 26 trials are excluded."),
    "merged": dict(lo=11,  hi=348, n=312, gt=GT_DIR / "260620d_merged_11-348.json",
                   label="merged (11-348)",
                   note="THE TARGET. 312 usable tiles, NOT 338."),
}
DEFAULT_RANGE = "merged"


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

    ⛔ ONLY `status == "anchor"` tiles are returned. `excluded` tiles (the 26 thrown-out
    snapshots; x/y are null) and any legacy `pending`/`region` rows carry no scorable position
    and are dropped here, so a denominator can never quietly become 182 or 338."""
    if path is None:
        path = RANGES[rng or DEFAULT_RANGE]["gt"]
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for k, v in doc["tiles"].items():
        if v.get("status") != "anchor" or v.get("x") is None or v.get("y") is None:
            continue
        out[int(k)] = dict(xy=np.array([float(v["x"]), float(v["y"])]),
                           r=float(v.get("r", doc["tolerance_px"]["region_default"])),
                           status="anchor")
    return out, doc


def load_positions(arg):
    """{trial: array([x,y])} from a positions.csv (columns: trial,x,y)."""
    p = Path(arg)
    if not p.exists():
        sys.exit(f"no such positions file: {arg}")
    out = {}
    with p.open(newline="") as fh:
        for row in csv.DictReader(fh):
            out[int(row["trial"])] = np.array([float(row["x"]), float(row["y"])])
    return out, p


def excluded_in(build) -> list[int]:
    """Trials in a build that should never have been loaded at all. Non-empty == RULE BREAK."""
    return sorted(t for t in build if t in EXCLUDED)


# --- the alignment --------------------------------------------------------------------
# ⚠️ VERBATIM from analysis/archive/challenge_2026-07/benchmark/score.py. PROVEN. Touch nothing.
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


def subscores(build, tol=DEFAULT_TOL):
    """For an 11-348 build: how it does on each pass, each aligned INDEPENDENTLY against that
    pass's own truth. (Aligned independently on purpose: it answers "did the method get pass 1's
    geometry right", separately from "did it tie the two passes together right".)"""
    out = {}
    for key in ("pass1", "pass2"):
        cfg = RANGES[key]
        sub = {t: p for t, p in build.items() if cfg["lo"] <= t <= cfg["hi"]}
        if len(sub) < 2:
            continue
        gt, _ = load_gt(cfg["gt"])
        out[key] = score(sub, gt, build_id=f"sub:{key}", tol=tol, rng=key)
    return out


# --- reporting ------------------------------------------------------------------------
def excl_banner(rep):
    if not rep.get("rule_break"):
        return []
    bad = rep["excluded_placed"]
    return ["",
            "  " + "!" * 72,
            f"  ⛔ RULE BREAK — this build places {len(bad)} EXCLUDED trial(s): "
            + " ".join(map(str, bad)),
            "     Those 26 snapshots are thrown out: they must never be loaded, never fed to a",
            "     method, never allowed to vote in a solve. A position for one of them means the",
            "     method read a frame it was forbidden to read. The build is DISQUALIFIED, not",
            "     quietly trimmed. Get the trial list from analysis/ground_truth/excluded.py.",
            "  " + "!" * 72]


def fmt(rep, verbose=False):
    L = []
    L.append(f"build            {rep['build_id']}")
    L.append(f"range            {RANGES[rep['range']]['label']}   "
             f"({RANGES[rep['range']]['note']})")
    L.append(f"tiles scored     {rep['n_tiles']} / {rep['n_gt']} ground-truth anchors"
             + (f"   ({rep['n_missing']} not placed by this build)" if rep["n_missing"] else ""))
    L += excl_banner(rep)
    L.append("")
    L.append(f"  CORRECT        {rep['n_correct']}/{rep['n_gt']}   "
             f"= {rep['pct_of_gt']:.1f}%      "
             f"(within {rep['tol']:.0f} px of the human position)")
    L.append(f"  median error   {rep['median_err']:8.1f} px")
    L.append(f"  mean / RMSE    {rep['mean_err']:8.1f} / {rep['rmse']:.1f} px")
    L.append(f"  90th pct / max {rep['p90_err']:8.1f} / {rep['max_err']:.1f} px")
    L.append("")
    lad = "  ".join(f"{t}px:{rep[f'pct_within_{t}']:.0f}%" for t in TOL_LADDER)
    L.append(f"  accuracy vs tolerance   {lad}")
    L.append(f"  alignment      shift ({rep['align_dx']:+.1f}, {rep['align_dy']:+.1f}) px on a "
             f"{rep['n_inliers']}-tile consensus; residual rotation {rep['rot_deg']:+.3f}deg")
    if rep["wrong"]:
        L.append("")
        L.append(f"  misplaced ({len(rep['wrong'])}): "
                 + " ".join(str(w) for w in rep["wrong"][:40])
                 + (" ..." if len(rep["wrong"]) > 40 else ""))
        if verbose:
            worst = sorted(rep["per_tile"].items(), key=lambda kv: -kv[1]["err"])[:12]
            L.append("  worst:  " + "  ".join(f"{t}:{v['err']:.0f}px" for t, v in worst))
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="score a build against the human ground truth")
    ap.add_argument("build", help="path to a positions.csv (columns trial,x,y)")
    ap.add_argument("--gt", type=Path, default=None,
                    help="ground-truth doc (default: chosen from --range / inferred)")
    ap.add_argument("--range", choices=sorted(RANGES), default=None,
                    help="pass1 | pass2 | merged (default: inferred from the trials placed)")
    ap.add_argument("--tol", type=float, default=DEFAULT_TOL,
                    help=f"correctness radius in px (default {DEFAULT_TOL:.0f}, the challenge)")
    ap.add_argument("--sub", action="store_true",
                    help="for an 11-348 build, also score each pass on its own truth")
    ap.add_argument("--json", action="store_true", help="emit the raw report as JSON")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 if the build places an excluded trial")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    build, path = load_positions(a.build)
    rng = a.range or range_of(build)
    gt, _doc = load_gt(a.gt or RANGES[rng]["gt"])
    rep = score(build, gt, build_id=path.stem if path.name != "positions.csv" else path.parent.name,
                tol=a.tol, rng=rng)

    if a.json:
        rep.pop("per_tile")
        if a.sub:
            rep["sub"] = {k: {kk: vv for kk, vv in v.items() if kk != "per_tile"}
                          for k, v in subscores(build, a.tol).items()}
        print(json.dumps(rep, indent=2))
    else:
        print(fmt(rep, a.verbose))
        if a.sub and rng == "merged":
            print("\n  sub-scores (each pass aligned independently on its own truth):")
            for k, r in subscores(build, a.tol).items():
                print(f"    {RANGES[k]['label']:<20s} {r['n_correct']}/{r['n_gt']} = "
                      f"{r['pct_of_gt']:.1f}%")
    return 1 if (a.strict and rep["rule_break"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
