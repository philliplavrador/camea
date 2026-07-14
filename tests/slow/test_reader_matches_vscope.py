"""THE NUMPY .dat READER **IS** vscope. Proven on all 312 guard frames, not on 5.

    uv run pytest tests/slow/test_reader_matches_vscope.py -q -m slow -s

WHY THIS TEST EXISTS
--------------------
`vscope` **cannot be pip-installed** — it declares `Requires-Dist: cairo`, and there is no package
named `cairo` on PyPI. So it is not in the uv env and it never will be. The old guard read its frames
through `mosaic.io.load_frames`, i.e. through vscope, and would die at import here.

The new reader is numpy: `np.fromfile("<u2")` -> reshape -> **flip per the XML's `ax`/`ay`**. That
last step is the whole risk. vscope returns the *DISPLAY* frame; 260620d's XML says `ax=-1, ay=-1`,
so the display frame is the raw array **rotated 180 degrees**. Every SWIM dx/dy and all three ground
truths live in that flipped frame. A naive `np.fromfile().reshape(512,512)` gives a mosaic 180
degrees out from every prior result — **and it will look perfectly plausible.**

`archive/analysis/output/tests/frames_011-348_n312.npy` (327 MB) was written by `mosaic.io.
load_frames`, i.e. **BY VSCOPE**, over exactly the 312 trials the guard uses. So a decisive,
zero-vscope certification is available for free: if our reader reproduces it **bit-for-bit**, the
vscope question is closed permanently and that cache can be deleted.

If this FAILS: **STOP THE MIGRATION.** You have found a real orientation or dtype bug and every
number downstream of it is wrong.

(This is a one-shot certification against an artefact that is not in the repo and is not required.
It SKIPS when the cache is absent — unlike the 312/312 guard, which FAILS. The guard's own assertion
is an independent second proof anyway: t33 on differently-decoded pixels would not land 312 tiles
inside 10 px of a hand-placed truth. It just tells you *that* something broke, not *what*.)
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

DEFAULT_CACHE = (Path(__file__).resolve().parents[2]
                 / "archive" / "analysis" / "output" / "tests" / "frames_011-348_n312.npy")


@pytest.fixture(scope="session")
def vscope_cache() -> Path:
    p = Path(os.environ.get("CAMEA_VSCOPE_CACHE") or DEFAULT_CACHE)
    if not p.exists():
        pytest.skip(f"vscope's frame cache is not on this machine ({p}). It is a 327 MB research "
                    f"artefact, not a repo file. Set CAMEA_VSCOPE_CACHE to point at it.")
    return p


@pytest.mark.slow
def test_reader_is_vscope(dataset_dir, gt_excluded, load_frames, vscope_cache):
    gt_excluded.DATA_DIR = dataset_dir
    trials = gt_excluded.usable_trials(*gt_excluded.MERGED)
    assert len(trials) == 312

    ours = load_frames(dataset_dir, trials)          # numpy: fromfile + reshape + the 180° flip
    theirs = np.load(vscope_cache)                   # vscope: 312 x 512 x 512 float32

    assert ours.shape == theirs.shape == (312, 512, 512)
    assert ours.dtype == theirs.dtype == np.float32
    if not np.array_equal(ours, theirs):
        bad = [int(trials[i]) for i in range(len(trials))
               if not np.array_equal(ours[i], theirs[i])][:10]
        flipped = np.array_equal(ours[0], np.flip(np.flip(theirs[0], 0), 1))
        pytest.fail(
            f"THE NUMPY READER IS NOT VSCOPE. STOP.\n"
            f"  {len(bad)}+ frames differ, first: {bad}\n"
            f"  frame 0 matches vscope's 180-degree ROTATION: {flipped}"
            f"{'  <-- the flip is inverted. See loader.py:459.' if flipped else ''}",
            pytrace=False)
