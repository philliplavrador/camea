"""camea.features.mosaic — stitch a serpentine scan of overlapping snapshots into one mosaic.

The first feature. It owns its own selection of the dataset (the run, the 512x512 gate, the pass
split), its own document payload, its own solver adapter and its own exports.

⛔ **THE APP CARRIES NO DATASET KNOWLEDGE, AND THAT INCLUDES THIS PACKAGE.** No trial number is
special anywhere under here. There is no exclusion list, no blank threshold constant, no "known bad"
frames. The blank scan *proposes*; the human ticks; the decision lives in the document. The only
symbol importable from the exclusion module is `gaps()`, and the app reaches it through
`camea.core.dataset.gaps`.

⭐ `solve.py` is the **only** module in the app allowed to import `t27` / `t33`. The 512 in this
feature is `t33.TILE`, which is why the 512x512 gate is a *mosaic policy* and not a core one — core
holds frames of whatever shape the XML says.

⚠️ This `__init__` deliberately imports nothing: importing `camea.features.mosaic` must not drag in
cv2, cupy or spectralign. Import the module you want (`from camea.features.mosaic import solve`).
"""
