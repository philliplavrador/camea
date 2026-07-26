"""🔴 THE REGRESSION GUARD. Run it after touching ANYTHING under `src/camea/engine/`.

    uv run pytest tests/slow/test_solver_312.py -q -m slow -s          (~130 s, needs the GPU)

Rebuilds the whole 11-348 mosaic **from the raw pixels** with `camea.engine.t33.place()` and fails
loudly unless it still scores **312/312** against the hand-placed human ground truth.

WHY THIS EXISTS
---------------
312/312 is the whole result of this project, and it is a *fragile* kind of correct: the failure mode
of tile placement is not drift but a silent lock onto a wrong correlation peak. A refactor that
quietly changes a band-pass sigma, an FFT padding, a mask rule or a cut threshold will not crash and
will not look wrong — it will just move six tiles 256 px sideways and still render a mosaic that
looks plausible at a glance. Nothing else in this repo would catch that. This does.

WHAT IT ACTUALLY CHECKS (all six must hold)
  1. the trial list is the canonical one   -> 312 usable snapshots, no thrown-out frame loaded,
                                              and the SAME tiles the answer key describes
  2. t33 places every one of them          -> 312 positions out
  3. THE PASS-1 CONTROL is intact          -> pass-1 tiles are byte-identical to t27's own layout
                                              (`info["pass1_max_dev"] == 0`, EXACTLY). If this
                                              drifts, a global solve has crept back in and pass 2's
                                              links are voting on pass-1 tiles — the mistake t33's
                                              design forbids.
  4. the score is 312/312 within 10 px     -> against the human ground truth, via the canonical
                                              scorer (`tests/guard/score.py`, whose `robust_align` is
                                              proven code — a reimplementation with a different
                                              tie-break scored the SAME positions 152/156 where this
                                              one gives 155/156)
  5. no thrown-out frame was PLACED        -> `rule_break` is False, against a REAL exclusion list
                                              injected from the ruling beside the answer key
  6. the engine under test is UNPATCHED    -> `t33._pool` is t33's own (the app's build memo is a
                                              context manager precisely so it cannot leak into here)

THE PLACEMENT IS ALWAYS COLD. `t33.place(..., cache=None)`: no cached SWIM bank, no cached backbone,
no cached anchors. **A guard that reads back its own previous answer is not a guard.** And the frames
are cold too — the old guard cached the *decode* to a 327 MB .npy; that cache is gone. Reading 312
frames costs ~0.13 s.

⭐ IT ALSO PROVES SOMETHING FOR FREE. `t27.solve_rigid` -> `spectralign.placement.rigid` ->
`np.linalg.solve` is on the COLD path and only the cold path. Under conda-without-activation that
delay-load fast-failed the process with 0xC0000409 (no Python exception, nothing to catch) and
silently killed every first build. This guard being green under `uv run` is the proof that the uv
env's BLAS is fine — and that the old conda DLL pre-dance is genuinely dead. (The FROZEN half is not
proven by anything yet. See `camea/engine/dll.py`.)
"""
from __future__ import annotations

import time

import numpy as np
import pytest

from camea.engine import t27, t33
from guard import score as bscore     # tests/guard/score.py — the scorer, NOT shipped in the wheel

EXPECT_TILES = 312          # 11-348, with the 26 thrown-out frames removed. NOT 338.
TOL_PX = 10.0               # the challenge criterion
RANGE = "merged"            # 11-348


def _trials(dataset_dir, gt_excluded) -> list[int]:
    """THE trial list, from the ruling that lives beside the answer key — never hard-coded here.

    ⛔ This list is the ANALYSIS tree's business, not the app's. `camea.engine.excluded` has `gaps()`
    and nothing else, on purpose. The guard is allowed to know it because the guard is scoring one
    specific acquisition against one specific human's answer key.
    """
    gt_excluded.DATA_DIR = dataset_dir       # is_snapshot() checks the disk; point it at OUR mirror
    lo, hi = gt_excluded.MERGED
    trials = gt_excluded.usable_trials(lo, hi)
    assert len(trials) == EXPECT_TILES, (
        f"usable_trials({lo}, {hi}) gave {len(trials)} trials, expected {EXPECT_TILES}. "
        f"The exclusion ruling or the data mirror has changed.")
    assert not (set(trials) & set(gt_excluded.EXCLUDED)), "a thrown-out trial reached the guard's input"
    return trials


def _build(dataset_dir, trials, load_frames):
    """Run the method from the pixels. -> (pos, info, seconds)."""
    frames = load_frames(dataset_dir, trials)
    assert frames.shape == (EXPECT_TILES, 512, 512), f"bad frame stack {frames.shape}"

    cfg = t33.Config(pass_split=166, t27=t27.Config(control=False))   # 166 = last trial of pass 1
    t0 = time.time()
    pos, info = t33.place(trials, frames, cfg, cache=None)            # cache=None -> FULLY COLD
    return pos, info, time.time() - t0


def _check(pos, info, gt):
    """-> (ok, report, lines). Every assertion the guard makes, as data."""
    L: list[str] = []
    ok = True

    n = len(pos)
    L.append(f"  tiles placed        {n} / {EXPECT_TILES}")
    ok &= n == EXPECT_TILES

    dev = info["pass1_max_dev"]
    L.append(f"  PASS-1 CONTROL      max deviation {dev:.6f} px  (must be exactly 0)")
    ok &= dev == 0.0

    posf = {int(t): np.asarray(p, float) for t, p in pos.items()}
    rep = bscore.score(posf, gt, build_id="guard:t33", tol=TOL_PX, rng=RANGE)

    L.append(f"  scored              {rep['n_correct']} / {rep['n_gt']} within {TOL_PX:.0f} px "
             f"= {rep['pct_of_gt']:.1f}%")
    L.append(f"  error               median {rep['median_err']:.1f}  p90 {rep['p90_err']:.1f}  "
             f"max {rep['max_err']:.1f} px")
    L.append(f"  thrown-out frames   "
             f"{'NONE (clean)' if not rep['rule_break'] else rep['excluded_placed']}")
    ok &= rep["n_gt"] == EXPECT_TILES
    ok &= rep["n_correct"] == EXPECT_TILES
    ok &= not rep["rule_break"]

    if rep["wrong"]:
        L.append("")
        L.append(f"  REGRESSED TILES ({len(rep['wrong'])}): " + " ".join(map(str, rep["wrong"])))
        worst = sorted(rep["per_tile"].items(), key=lambda kv: -kv[1]["err"])[:10]
        L.append("  worst:  " + "  ".join(f"{t}:{v['err']:.0f}px" for t, v in worst))
    return ok, rep, L


@pytest.mark.slow
def test_merged_312(dataset_dir, gt_dir, gt_excluded, load_frames):
    """t33 must still place all 312 tiles of 11-348 within 10 px of the human ground truth."""
    # 6. the engine under test must be the engine we ship, unpatched.
    assert t33._pool.__module__ == t33.__name__, \
        "t33._pool is monkey-patched (adapters.build_memo leaked?). The guard measures the ENGINE."

    # the exclusion ruling: INJECTED, so `rule_break` is a real check and not vacuously true.
    excl = bscore.set_excluded(gt_excluded.EXCLUDED)
    assert len(excl) == 26, f"the ruling injected {len(excl)} thrown-out trials, expected 26"

    trials = _trials(dataset_dir, gt_excluded)
    gt, _doc = bscore.load_gt(gt_dir / bscore.RANGES[RANGE]["gt"])
    assert set(trials) == set(gt), (
        "the trial list and the answer key do not describe the same tiles: "
        f"{sorted(set(trials) - set(gt))[:8]} placed-but-not-in-GT, "
        f"{sorted(set(gt) - set(trials))[:8]} in-GT-but-not-placed")

    pos, info, secs = _build(dataset_dir, trials, load_frames)
    print("\n" + "=" * 78)
    print("REGRESSION GUARD — camea.engine.t33.place() must still be 312/312 on trials 11-348")
    print("=" * 78)
    print(f"\nplaced {len(pos)} snapshots in {secs:.0f}s "
          f"({'GPU' if info['gpu'] else 'CPU'}), fully cold\n")

    ok, _rep, lines = _check(pos, info, gt)
    print("\n".join(lines))
    print()
    print("  ==> PASS. 312/312. The result is intact." if ok else
          "  ==> FAIL. The 100% is BROKEN. Do not ship this.")
    assert ok, "t33 no longer scores 312/312 on 11-348:\n" + "\n".join(lines)
