"""🔴 THERE IS EXACTLY ONE BAND-PASS, AND THIS FILE IS WHY IT STAYS THAT WAY.

`camea.engine.quality.band_pass` is a DoG(sigma=3, sigma=30). `t27.band_pass` **delegates** to it,
so it sits under the **312/312 regression guard**: every SWIM offset, every NCC, every texture
value and all three ground truths in this project are measured on that one function's output.

v1 carried a **second** implementation (`archive/app-v1/backend/loader.py:639`) whose own docstring
claimed it was *"Verified bit-identical"* to the first — a claim **nothing in the repo tested**. Two
forks of the DoG that everything is matched on, with nothing asserting they agree. They *did* agree,
by luck and by care; the next edit to either would have been silent.

So: `core.frames` **imports** the survivor, and these four tests stop the fork coming back.
(docs/SPLIT.md §3.)
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest

from camea.core import frames
from camea.engine import quality

SRC = Path(__file__).resolve().parents[2] / "src"

#: The DoG's signature in source: two Gaussian blurs, subtracted. Matches
#: `cv2.GaussianBlur(f, (0,0), lo) - cv2.GaussianBlur(f, (0,0), hi)` however it is spelled.
#: ⚠️ Deliberately NOT a bare search for "GaussianBlur": `core.frames.compute_flat` legitimately
#: uses one — as a **vignette** (a single blur at sigma=15, subtracted from nothing). It is the
#: *subtracted pair* that is the DoG, and the DoG is what may exist only once.
#: (`.{0,120}?` rather than `[^)]*` because the argument list itself contains `)` — the ksize is
#: `(0, 0)`. `test_the_regex_finds_the_real_dog` pins the regex itself against the real source, so
#: this guard cannot pass by failing to match anything.)
_DOG = re.compile(r"GaussianBlur\(.{0,120}?\)\s*-\s*(?:\w+\.)?GaussianBlur\(", re.S)


def _rand(shape=(512, 512), seed: int = 7) -> np.ndarray:
    """A fixed, seeded frame with the counts of a real one (median ~2000, 16-bit-ish)."""
    return np.random.default_rng(seed).normal(2000, 300, shape).astype(np.float32)


# =================================================================================================
# 1. IDENTITY, not equality. `core.frames` re-exports the engine's function OBJECT.
# =================================================================================================
def test_frames_reexports_the_engine_band_pass():
    assert frames.band_pass is quality.band_pass


# =================================================================================================
# 2. ⭐ THE SOURCE-LEVEL GUARD. Exactly ONE file under src/camea may contain a Gaussian DoG.
#    This is the one that actually stops a well-meaning agent "inlining a two-liner" again.
# =================================================================================================
def test_only_quality_py_contains_a_gaussian_dog():
    hits = sorted(
        p.relative_to(SRC).as_posix()
        for p in (SRC / "camea").rglob("*.py")
        if _DOG.search(p.read_text(encoding="utf-8"))
    )
    assert hits == ["camea/engine/quality.py"], (
        f"a second Gaussian DoG appeared in {hits}. There is exactly ONE band-pass in this "
        f"project and it is camea.engine.quality.band_pass — IMPORT it, do not re-derive it."
    )


def test_the_regex_finds_the_real_dog():
    """🔴 A guard that matches NOTHING passes for free. Pin the regex against the real thing — both
    spellings the project has actually used. (It first shipped as `[^)]*`, which cannot cross the
    `(0, 0)` ksize and matched neither.)"""
    import inspect

    assert _DOG.search(inspect.getsource(quality.band_pass))
    assert _DOG.search(inspect.getsource(_loader_band_pass))
    assert _DOG.search("a = GaussianBlur(f,(0,0),3)-GaussianBlur(f,(0,0),30)")  # no spaces, no cv2.


def test_the_vignette_is_not_mistaken_for_a_dog():
    """A sanity check on the guard above: `compute_flat`'s single blur must NOT match `_DOG`, or
    test #2 is passing for the wrong reason and would not catch a real fork."""
    src = (SRC / "camea" / "core" / "frames.py").read_text(encoding="utf-8")
    assert "GaussianBlur" in src  # the vignette is there...
    assert not _DOG.search(src)  # ...and it is not a DoG.


# =================================================================================================
# 3. 🔴 THE SURVIVOR IS BIT-IDENTICAL TO THE ONE THAT WAS DELETED.
#
#    `_loader_band_pass` below is `archive/app-v1/backend/loader.py:639`, verbatim. It is the
#    implementation this port removed. Reproducing it HERE — in a test, where a mirror is legal —
#    is what turns v1's *comment* ("Verified bit-identical to both") into an assertion that runs.
#    If anyone ever edits `quality.band_pass`, this fails.
# =================================================================================================
def _loader_band_pass(frames_in: np.ndarray) -> np.ndarray:
    """The DELETED implementation. Do not use it anywhere but here."""
    import cv2

    DOG_LO, DOG_HI = 3, 30
    f = np.asarray(frames_in, np.float32)
    if f.ndim == 2:
        return cv2.GaussianBlur(f, (0, 0), DOG_LO) - cv2.GaussianBlur(f, (0, 0), DOG_HI)
    return np.stack(
        [cv2.GaussianBlur(x, (0, 0), DOG_LO) - cv2.GaussianBlur(x, (0, 0), DOG_HI) for x in f]
    ).astype(np.float32)


def test_survivor_is_bit_identical_to_the_deleted_loader_band_pass_3d():
    stack = np.stack([_rand(seed=s) for s in (1, 2, 3)])
    got = frames.band_pass(stack)
    want = _loader_band_pass(stack)
    assert got.dtype == want.dtype == np.float32
    assert np.array_equal(got, want), "the ONE band-pass has drifted from the one it replaced"


def test_survivor_is_bit_identical_to_the_deleted_loader_band_pass_2d():
    """The 2-D branch was the *only* real difference between the two implementations, and it is the
    one `texture_map` used. `band_pass_one` replaces it by construction, not by assertion."""
    f = _rand(seed=11)
    assert np.array_equal(frames.band_pass_one(f), _loader_band_pass(f))


def test_the_sigmas_are_still_3_and_30():
    """⛔ `quality.band_pass`'s DEFAULTS are the sigmas. v1 mirrored them into two more modules as
    `DOG_LO`/`DOG_HI`; those mirrors are deleted, so nothing can drift from them — but the defaults
    themselves are still load-bearing, and `core.frames` calls the function with no sigmas at all."""
    import inspect

    sig = inspect.signature(quality.band_pass)
    assert (sig.parameters["lo"].default, sig.parameters["hi"].default) == (3, 30)


# =================================================================================================
# 4. The 2-D convenience path IS the 3-D path. Bit-for-bit, on random data.
# =================================================================================================
def test_band_pass_one_is_the_stack_path():
    f = _rand(seed=7)
    assert np.array_equal(frames.band_pass_one(f), frames.band_pass(f[None])[0])


def test_band_pass_one_refuses_a_stack():
    with pytest.raises(ValueError, match="2-D"):
        frames.band_pass_one(np.zeros((2, 64, 64), np.float32))
