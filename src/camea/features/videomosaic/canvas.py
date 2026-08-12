"""Reading a built video mosaic back off disk, as pixels plus an honest coverage mask.

Two stages need this — the electrode map and locating a region recording — and they must
agree to the pixel, so there is ONE implementation. (This module docstring exists because the
repo has been bitten before by a second, subtly drifted copy of a rule: see
`core.workspace`'s note about the three write guards.)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


class MosaicMissing(FileNotFoundError):
    """No built mosaic to read, with the reason in one sentence (a 409 at the route)."""


def mosaic_path(doc: dict, out_dir: Path) -> Path:
    """Where the built mosaic PNG is, or `MosaicMissing`.

    ⚠️ `build.outputs.mosaic` is a FILENAME, never a path — a project moves (R44), so an
    absolute path recorded in a document would be a lie. `Path(...).name` re-asserts that even
    if an older document carries something longer.
    """
    build = doc.get("build") or {}
    name = (build.get("outputs") or {}).get("mosaic")
    if not build.get("built_at") or not isinstance(name, str) or not name:
        raise MosaicMissing("this project has no built mosaic yet — run the build first")
    p = Path(out_dir) / Path(name).name
    if not p.is_file():
        raise MosaicMissing(f"the built mosaic file is missing ({p.name}) — rebuild first")
    return p


def read_mosaic(doc: dict, out_dir: Path) -> tuple[np.ndarray, np.ndarray]:
    """`(image float32, valid bool)` — the toned composite and where it actually has data.

    🔴 **COVERAGE IS GEOMETRY, NOT `png > 0`.** The toned composite maps its darkest COVERED
    pixels to exactly 0 as well, and there is no alpha channel, so a `> 0` mask is riddled with
    speckle holes that any high-pass erosion then blows into dead zones — measured, that cost
    97 % of the pads on the synthetic survey. The document's placed keyframes ARE the coverage:
    the union of their rectangles, which is the same rule the snapshot exporter's mandatory
    mask follows. The pixel test survives only as the last resort for a document whose
    geometric facts are missing.
    """
    from PIL import Image

    path = mosaic_path(doc, out_dir)
    Image.MAX_IMAGE_PIXELS = None
    im = Image.open(path)
    # mode "P": the index plane IS the toned grey composite (the palette only tints it), so
    # reading indices directly beats a palette -> RGB -> grey round trip
    arr = np.asarray(im if im.mode == "P" else im.convert("L"), np.float32)
    return arr, coverage_mask(doc, arr.shape, arr)


def coverage_mask(doc: dict, shape: tuple[int, int],
                  arr: np.ndarray | None = None) -> np.ndarray:
    """The union of the placed keyframes' rectangles — pure geometry, no pixels consulted."""
    valid = np.zeros(shape, bool)
    src = doc.get("source") or {}
    fw, fh = int(src.get("width") or 0), int(src.get("height") or 0)
    if fw > 0 and fh > 0:
        for kf in (doc.get("keyframes") or {}).values():
            if not (isinstance(kf, dict) and kf.get("placed")
                    and kf.get("x") is not None and kf.get("y") is not None):
                continue
            x, y = int(round(float(kf["x"]))), int(round(float(kf["y"])))
            y0, y1 = max(0, y), min(shape[0], y + fh)
            x0, x1 = max(0, x), min(shape[1], x + fw)
            if y1 > y0 and x1 > x0:
                valid[y0:y1, x0:x1] = True
    if not valid.any() and arr is not None:
        valid = arr > 0                      # geometric facts missing: the pixel last resort
    return valid


__all__ = ["MosaicMissing", "coverage_mask", "mosaic_path", "read_mosaic"]
