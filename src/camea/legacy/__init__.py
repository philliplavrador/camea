"""camea.legacy — retired features. **Kept working, not kept current.**

WHAT "LEGACY" MEANS HERE
-----------------------
A package under `camea.legacy` is a feature that Camea **no longer offers on the New-project
screen** but **still opens**. It is not dead code, not a stub, and not a candidate for deletion:
every project a user has already built with it must keep opening, exporting and saving exactly as
it did. Its router is still mounted by `api/app.py`; its document hooks are still registered.

WHAT IS IN HERE, AND WHY
------------------------
`legacy.mosaic` — the **snapshot** mosaic builder: stitch a serpentine scan of overlapping
snapshots into one mosaic, machine-placed then *human-verified* (place → sweep to
confirm/correct/exclude → Recompute against the anchors → export). It was the app's first feature
and the reason the engine exists.

⭐ **IT WAS RETIRED ON 2026-08-11 BECAUSE THE USER'S WORK IS VIDEO-BASED — NOT BECAUSE IT IS
BROKEN.** It works. Behind it sits the sacred 312/312 solver guard
(`tests/slow/test_solver_312.py`): the placement engine, run cold, puts all 312 usable tiles of
260620d within 10 px of hand-authored ground truth, pass-1 deviation exactly 0. That guard still
runs, and it still governs `src/camea/engine/**`, which is **not** legacy and has **not** moved.

RULES FOR THIS PACKAGE
----------------------
* ⛔ **Do not delete it.** Existing snapshot projects must still open.
* Its tests still exist and still pass; they are simply deselected from the fast run
  (`pytestmark = pytest.mark.legacy`; `uv run pytest -m legacy` runs them). See `pyproject.toml`.
* The dependency arrow is unchanged and still one-way: `api -> legacy/features -> core -> engine`.
  A legacy feature may use `camea.core`; it may not import `camea.api`, and no live feature should
  grow an import of `camea.legacy`.
* If the snapshot workflow ever comes back, it moves back to `camea.features` — that is the whole
  point of keeping it importable and green.
"""
