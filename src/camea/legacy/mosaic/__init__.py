"""camea.legacy.mosaic — stitch a serpentine scan of overlapping snapshots into one mosaic.

The first feature. It owns its own selection of the dataset (the run, the 512x512 gate, the pass
split), its own document payload, its own solver adapter and its own exports.

⭐ **RETIRED 2026-08-11 — MOVED HERE FROM `camea.features.mosaic`, NOT REMOVED.** The New-project
screen no longer offers the snapshot task (the user's work is video-based), but this router is
still mounted by `api/app.py` and every snapshot project already on disk still opens, saves and
exports. It was retired because the product moved on, *not* because it is broken: the 312/312
solver guard behind it is green. See `camea/legacy/__init__.py`.

⛔ **THE APP CARRIES NO DATASET KNOWLEDGE, AND THAT INCLUDES THIS PACKAGE.** No trial number is
special anywhere under here. There is no exclusion list, no blank threshold constant, no "known bad"
frames. The blank scan *proposes*; the human ticks; the decision lives in the document. The only
symbol importable from the exclusion module is `gaps()`, and the app reaches it through
`camea.core.dataset.gaps`.

⭐ `solve.py` is the **only** module in the app allowed to import `t27` / `t33`. The 512 in this
feature is `t33.TILE`, which is why the 512x512 gate is a *mosaic policy* and not a core one — core
holds frames of whatever shape the XML says.

⚠️ This `__init__` deliberately imports nothing: importing `camea.legacy.mosaic` must not drag in
cv2, cupy or spectralign. Import the module you want (`from camea.legacy.mosaic import solve`).
"""
