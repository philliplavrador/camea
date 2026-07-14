"""The placement engine. **The science.**

`t27.py`, `t33.py`, `quality.py` and `render.py` are moved **BYTE-IDENTICALLY** from
`archive/analysis/mosaic/` and they are under the 312/312 regression guard
(`tests/slow/test_solver_312.py`), which rebuilds the whole 11-348 mosaic from the raw pixels and
fails unless every one of 312 tiles still lands within 10 px of a hand-placed human ground truth.

**Do not edit those four files.** Not to reformat, not to sort imports, not to "clean up" a dead
constant. 312/312 is a *fragile* kind of correct: the failure mode of tile placement is not drift
but a silent lock onto a wrong correlation peak, and a refactor that quietly changes a band-pass
sigma, an FFT padding, a mask rule or a cut threshold will not crash and will not look wrong — it
will move six tiles 256 px sideways and still render a mosaic that looks plausible at a glance.

Everything the app needs that is *not* public API on t27/t33/render lives in `adapters.py` — the one
module allowed to touch their privates. `score.py` is dev/benchmark-only and is deliberately NOT
imported here.

Importing this package costs **numpy and nothing else**. cv2 arrives at the first band-pass, cupy at
the first `t27.xp()`, spectralign at the first solve, matplotlib never unless you ask for a layout
PNG. Keep it that way.
"""
from . import dll                    # noqa: F401

# ⚠️ MODULE SCOPE, FIRST, ON PURPOSE. Before the first t27.xp() and before the first numpy.linalg
# call — and it must run in the SPAWNED BUILD CHILD too, which re-imports this module. A no-op
# under `uv run`; mandatory under PyInstaller. See dll.py for the two native crashes it prevents.
DLL_DIRS = dll.predance()

from . import excluded, quality, render, t27, t33          # noqa: E402
from .adapters import TILE, build_memo, canvas, free_gpu, gpu_info, read_anchors   # noqa: E402
from .excluded import gaps                                 # noqa: E402

__all__ = [
    "t27", "t33", "quality", "render", "excluded",
    "gaps",
    # ⭐ `gpu_info` is here so the API layer never has to import t27. There is exactly ONE detector
    # (`t27.xp()`, which executes a real op), and `solve.py` stays the only module outside this
    # package that may import t27/t33 — `tests/unit/test_mosaic_solve.py` asserts it.
    "TILE", "canvas", "free_gpu", "read_anchors", "build_memo", "gpu_info",
    "DLL_DIRS",
]
