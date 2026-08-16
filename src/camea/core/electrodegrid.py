"""Electrode-grid mapping: find the MEA's electrode pads in a finished mosaic and give
every lattice position a stable ``column-row`` identity (top-left = 1-1, columns grow
rightward, rows grow downward — along the LATTICE axes, not the image axes).

WHAT THIS SOLVES
----------------
The electrodes are bright pads on a near-square lattice (measured on real data: ~13.8 px
pitch rotated ~-2.2 deg in snapshot mosaics; ~31 px in video mosaics — but nothing here
assumes either number: the app carries no dataset knowledge, so every parameter of the
lattice is measured from the image it is given). Two obvious designs fail on this data:

* A single rigid lattice fit (pitch+angle+phase, then ``index = round(inv(A) @ px)``)
  breaks because apparent pitch tracks FOCUS and drifts up to ~2 % across one mosaic
  (measured 14.02 -> 14.30 px within pass 1). Over ~230 columns that compounds to 4-5
  whole cells of silent indexing error.
* Pure per-dot detection with neighbour linking breaks because cells and neurites occlude
  whole patches of pads and stitch seams fragment the neighbour graph.

So we do what lattice-indexing in noisy micrographs classically does: a global FFT fit
*initialises* pitch and orientation, then indices spread outward from a high-confidence
seed by region growing, each step predicting the next centre from already-indexed
neighbours with *locally updated* lattice vectors (absorbing rotation, focus drift and
small stitch steps). Detected pads snap the lattice to the pixels; occluded positions are
carried as predictions and flagged ``inferred`` — every grid position inside the array
gets a centre and an ID (his ruling, 2026-08-11).

COORDINATES
-----------
``fit_grid`` works purely in the pixel space of the image it is given; callers translate
to their own world/canvas frames. ``lookup`` returns a hit only within
``hit_frac * pitch`` of a centre (his click rule: the pad plus a slim margin; gaps select
nothing — arrow keys in the UI recover from near-misses).

THE DEVICE, AND WHETHER IT IS ALL IN FRAME (R45.8, his ruling 2026-08-11)
------------------------------------------------------------------------
The lattice is still MEASURED — R45.1 is untouched, nothing here assumes a pitch or a
shape. What the *user* can tell us is which chip he imaged (*"the standard MaxOne/MaxTwo
sensor area is 26,400 electrodes = 220 x 120, with 17.5 um pitch"*) and whether the WHOLE
chip is in frame:

* ``device`` (a ``DeviceSpec``, normally ``MAXWELL``) supplies the physical pitch, and in
  the *partial* mode that is all it is used for: ``um_per_px = device.pitch_um / gm.pitch``
  is a MEASURED scale — a known physical length over the pixel length this image actually
  shows. It is a third, unrelated quantity to the provenance scale of R30; do not plumb it
  there.
* ``enforce_shape=True`` — set ONLY when he chose *"whole chip imaged"* — makes the device's
  array shape BINDING, and *"if the user select full imaging then I want the rules to be
  strictly enforced"* (his words, 2026-08-11). STRICT means the run ends in EXACTLY ONE of
  two states: a map that is exactly the device's shape with every one of its positions
  numbered, or a REFUSAL that says what it found. Never a third thing, and never ids that
  are quietly wrong. ⛔ **AND NO REPAIR PATH**: the shape either IS the device's or the job
  refuses, and the registration check then asks the pixels whether the array truly ends where
  the numbering says. Two repair rules were built before this and both were caught shifting
  every id by a constant while reporting the right shape (see ``_enforce_device_shape``) — a
  near miss is a refusal, and the user answers "part of the chip" or re-images. The spec
  CHECKS and COMPLETES a fit; it never replaces one, never edits one, and it binds only when
  he says the whole chip is in frame.

Every cell also carries ``x_um``/``y_um`` in the ARRAY's own frame: origin at the
least-squares lattice position of electrode 1-1, axes the mean lattice vectors normalised —
so the rotation is taken out and the numbers land near ``(col-1) * pitch_um`` while still
carrying the real, measured deviation. Pixels stay; um are alongside, never instead.

⛔ Every device number lives in ``DeviceSpec``/``MAXWELL`` and nowhere else — a pitch or a
count hard-coded anywhere else in app code is a violation of R45.8.

This module is feature-agnostic and pure: numpy at import, cv2/scipy inside functions
(route modules must keep ``/openapi.json`` importable), no camea imports.
"""

from __future__ import annotations

import dataclasses
import heapq
import math
from dataclasses import dataclass, field

import numpy as np

__all__ = ["FIT_SPAN", "FIT_STEPS", "MAXWELL", "DeviceSpec", "GridConfig", "GridMap",
           "NoGridFound", "fit_grid", "full_payload", "lattice_axes", "load_map_file",
           "measure_lattice", "write_map_files"]

#: The progress messages `fit_grid` emits, in order — callers map them to honest percentages.
#: 🔴 **ADD A STEP HERE AND YOU MUST ADD IT TO `FIT_SPAN` TOO.** A caller looks its weight up by
#: name, and a name that is not in the table falls back to 0 — which snaps the bar BACKWARDS to the
#: start of the fit mid-run, the one thing R48.5 exists to stop. The two are kept in step by
#: `tests/unit/test_electrodegrid.py`.
FIT_STEPS = ("high-pass", "lattice fit", "array mask", "pad detection", "indexing", "assembling")

#: step -> (start_fraction, end_fraction) of the whole fit. ⭐ **MEASURED, because the six are
#: nowhere near equal** and a caller dividing by six drew a bar that crawled through `indexing` and
#: then jumped a third of its length in one frame (BEHAVIOUR R48.5 — `pct` is overall).
#: Timed 2026-08-16 on the synthetic 220 x 120 lattice `tests/unit/test_electrodegrid.lattice_image`
#: builds (1879 x 3224 px, 2.02 s total): 6.2 / 16.7 / 17.8 / 12.1 / 38.6 / 8.6 %. A real survey
#: mosaic is bigger in pixels than in pads, which shifts weight towards the two pixel-bound steps —
#: so treat these as the shape of the cost, not as a promise about any one image.
#:
#: ⚠️ `indexing` (`_grow`) gets NO SUB-PROGRESS on purpose even though it is the biggest slice: it is
#: a heap-driven region grow with no upfront count — the frontier is discovered as it goes — so any
#: denominator would be invented. Its name is shown and its share of the bar is honest; per R48.9
#: that is what a step with no countable unit is allowed to do, and the whole fit is only ~6 s.
FIT_SPAN: dict[str, tuple[float, float]] = {
    "high-pass":     (0.00, 0.06),
    "lattice fit":   (0.06, 0.23),
    "array mask":    (0.23, 0.41),
    "pad detection": (0.41, 0.53),
    "indexing":      (0.53, 0.92),
    "assembling":    (0.92, 1.00),
}


def full_payload(gm: "GridMap", *, canvas_offset: tuple[float, float] = (0.0, 0.0),
                 **meta) -> dict:
    """`gm.payload()` shifted by `canvas_offset` (fit space -> the caller's coordinate
    space) with the offset recorded and any feature metadata folded in. Both features
    build their map file through this one function so the format cannot drift."""
    p = gm.payload()
    ox, oy = float(canvas_offset[0]), float(canvas_offset[1])
    if ox or oy:
        # ⚠️ PIXELS ONLY. `x_um`/`y_um` are in the ARRAY's own frame (origin electrode 1-1,
        # rotation taken out) — a canvas offset is a translation of the *image* frame and
        # has no meaning there. Shifting them would be silently wrong in the mosaic feature
        # alone (videomosaic's offset is (0,0), so the video tests would never catch it).
        p["cells"]["x"] = [round(x + ox, 2) for x in p["cells"]["x"]]
        p["cells"]["y"] = [round(y + oy, 2) for y in p["cells"]["y"]]
    p["canvas_offset"] = [round(ox, 4), round(oy, 4)]
    p.update(meta)
    return p


def summary_block(gm: "GridMap", *, built_at: str, outputs: dict[str, str],
                  source_stamp: str | None, coordinates: str | None,
                  array_coverage: str | None = None) -> dict:
    """The document's `electrodes` block — the SUMMARY both features store identically
    (the full table lives in the outputs/ file `outputs[\"map\"]` names).

    `array_coverage` defaults to what the fit was actually run under (`gm.array_coverage`),
    so the block cannot claim a coverage mode the map was not built with (R45.8)."""
    return {
        "built_at": built_at,
        "cols": gm.cols,
        "rows": gm.rows,
        "pitch_px": round(gm.pitch, 4),
        "angle_deg": round(gm.angle_deg, 4),
        "hit_radius_px": round(gm.hit_radius, 4),
        # what he declared, what it made the scale, and which chip said so — R45.8 wants
        # all three in the saved document, not just in the outputs/ file
        "array_coverage": array_coverage or gm.array_coverage,
        "um_per_px": round(gm.um_per_px, 6) if gm.um_per_px is not None else None,
        "device": gm.device.name if gm.device is not None else None,
        "stats": gm.stats,
        "outputs": dict(outputs),
        "source_stamp": source_stamp,
        "coordinates": coordinates,
    }


def load_map_file(out_dir, preferred_name: str | None) -> dict | None:
    """A map JSON back off disk: the recorded filename first, newest `*-electrodes.json`
    as fallback (the mosaic document is client-owned, so its block can lag the file)."""
    import json
    from pathlib import Path

    out_dir = Path(out_dir)
    p = out_dir / preferred_name if preferred_name else None
    if p is None or not p.is_file():
        found = sorted(out_dir.glob("*-electrodes.json"),
                       key=lambda q: q.stat().st_mtime, reverse=True)
        p = found[0] if found else None
    if p is None or not p.is_file():
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def write_map_files(payload: dict, json_path, csv_path) -> None:
    """Atomically write the full map as JSON plus a CSV twin
    (`electrode,col,row,x,y,x_um,y_um,kind,coverage`) that still says what it is after the
    user copies it out of the Outputs panel (R44). The um columns are blank when no device was
    given — there is then no measured scale, and a blank says that honestly (R45.8).

    🔴 `coverage` is a CONSTANT column, repeated on every row, and that repetition is the whole
    point. In `partial` mode `1-1` is the top-left of the IMAGED REGION, so `x_um`/`y_um` are
    anchored there and not on the chip's own corner; the app says so wherever it shows an id,
    but the CSV is the artifact that LEAVES the app (R44), and in a spreadsheet every caveat
    the UI carried is gone. A single header cell would not survive a sort, a filter, or a paste
    of one row into another sheet — so each row states the frame its um are in."""
    import csv
    import json
    import os

    jp, cp = str(json_path), str(csv_path)
    tmp = jp + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, separators=(",", ":"))
    os.replace(tmp, jp)

    cells = payload["cells"]
    n = len(cells["col"])
    xu = cells.get("x_um") or [""] * n
    yu = cells.get("y_um") or [""] * n
    # his declaration, echoed verbatim — never re-derived here, so the file cannot claim a
    # coverage the map was not built under
    coverage = str(payload.get("array_coverage") or "partial")
    tmp = cp + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["electrode", "col", "row", "x", "y", "x_um", "y_um", "kind", "coverage"])
        for col, row, x, y, x_um, y_um, kind in zip(cells["col"], cells["row"], cells["x"],
                                                    cells["y"], xu, yu, cells["kind"]):
            w.writerow([f"{col}-{row}", col, row, x, y, x_um, y_um,
                        "detected" if kind == 1 else "inferred", coverage])
    os.replace(tmp, cp)


# =============================================================================
# The device — the ONLY place a device number is allowed to live (R45.8)
# =============================================================================
@dataclass(frozen=True)
class DeviceSpec:
    """The chip the user says he imaged. Not a tunable and not a `GridConfig` field: a
    `GridConfig` is how hard we look, a `DeviceSpec` is a fact he asserts about the
    hardware. It only ever CHECKS and COMPLETES a measured fit (R45.1 stands)."""

    name: str = "MaxWell MaxOne/MaxTwo"

    axes: tuple[int, int] = (120, 220)
    """The two array axis lengths, ORIENTATION-FREE — the chip can sit portrait or
    landscape in the mosaic, so nothing may assume which of these is columns."""

    pitch_um: float = 17.5
    """Centre-to-centre electrode spacing in micrometres — the physical ruler that turns a
    measured pixel pitch into a scale."""

    @property
    def electrodes(self) -> int:
        """26,400 for MaxOne/MaxTwo — derived, never typed in twice."""
        return int(self.axes[0]) * int(self.axes[1])

    def as_dict(self) -> dict:
        """JSON-safe form for the payload/wire."""
        return {
            "name": self.name,
            "axes": [int(self.axes[0]), int(self.axes[1])],
            "pitch_um": float(self.pitch_um),
            "electrodes": self.electrodes,
        }


#: *"the standard MaxOne/MaxTwo sensor area is 26,400 electrodes = 220 x 120, with 17.5 um
#: pitch"* — his ruling, 2026-08-11. The app's one and only device fact.
MAXWELL = DeviceSpec()


# =============================================================================
# Configuration
# =============================================================================
@dataclass(frozen=True)
class GridConfig:
    """Tunables. Defaults are device-agnostic: the pitch is SEARCHED in
    [pitch_min, pitch_max], never assumed."""

    highpass_sigma: float = 7.0
    """Gaussian high-pass scale. ⚠️ Deliberately NOT the house DoG(3,30): that filter's
    negative lobe sits right on a ~14 px pitch and erases the grid (the documented trap —
    the matcher WANTS the grid gone; we want it back)."""

    pitch_min: float = 6.0
    pitch_max: float = 64.0
    """Plausible lattice period range in px. Wide on purpose — both known devices
    (~13.8 px snapshots, ~31 px video) sit comfortably inside."""

    peak_snr_min: float = 6.0
    """Refuse to see a lattice whose FFT fundamental is weaker than this over the local
    spectral background. The gridless synthetic fixture must refuse cleanly here."""

    corr_min: float = 0.15
    """Matched-filter floor for a pad detection."""

    snap_frac: float = 0.25
    """A predicted centre adopts a detection within snap_frac * pitch. Tight on purpose:
    a drifted prediction must NOT claim the wrong pad (off-by-one poison) — better to
    stay `inferred` and let growth re-approach from another side."""

    hit_frac: float = 0.30
    """lookup() selection radius as a fraction of pitch (his click rule: pad + slim
    margin; between-pad clicks miss)."""

    vec_beta: float = 0.25
    """How fast per-cell lattice vectors track the observed steps (exponential update).
    High enough to follow the ~2 % focus drift, low enough not to chase noise."""

    min_detected: int = 25
    """Refuse maps with fewer actually-detected pads than this — an indexing built
    almost entirely from inference is not a map, it is a guess."""


class NoGridFound(ValueError):
    """The image does not contain a usable electrode lattice (or too little of one)."""


# =============================================================================
# Result
# =============================================================================
@dataclass
class GridMap:
    """The finished mapping. ``centers[row-1, col-1]`` is the pad centre in the pixel
    space of the fitted image (NaN where the bounding box has no electrode, e.g. array
    corners clipped by the mosaic edge); ``kind`` is 0 absent / 1 detected / 2 inferred."""

    cols: int
    rows: int
    centers: np.ndarray            # float32 (rows, cols, 2) — x, y; NaN where absent
    kind: np.ndarray               # uint8   (rows, cols) — 0 absent / 1 detected / 2 inferred
    pitch: float                   # mean lattice step, px
    angle_deg: float               # rotation of the column axis vs image +x, degrees
    a1: tuple[float, float]        # mean column step vector (one cell to the right)
    a2: tuple[float, float]        # mean row step vector (one cell down)
    hit_radius: float              # px — lookup selection radius actually used
    stats: dict = field(default_factory=dict)

    conf: np.ndarray | None = None
    """float32 (rows, cols) — the matched-filter confidence of each DETECTED cell, NaN
    elsewhere. Kept per-cell (not just averaged) because a shape correction can DROP a line:
    `mean_confidence` then has to be re-averaged over the cells that actually survived, or the
    stats would describe a map nobody has (R45.8 strict)."""

    # --- the device half (R45.8); all None/"partial" when no device was supplied -------
    device: "DeviceSpec | None" = None
    um_per_px: float | None = None     # device.pitch_um / pitch — a MEASURED scale
    um: np.ndarray | None = None       # float32 (rows, cols, 2) — x_um, y_um; NaN absent
    array_coverage: str = "partial"
    """What the user declared: "full" (the whole chip is in frame — the device shape was
    enforced) or "partial" (numbering is relative to the IMAGED REGION, so 1-1 is the
    top-left of what was imaged, not of the chip). "partial" is the safe default: it
    assumes nothing."""

    # populated lazily by lookup()
    _tree: object = field(default=None, repr=False, compare=False)
    _flat: np.ndarray | None = field(default=None, repr=False, compare=False)

    KIND_ABSENT, KIND_DETECTED, KIND_INFERRED = 0, 1, 2

    def _index(self):
        """KD-tree over existing cells; centres absorb the measured drift, so nearest
        CENTRE (not nearest affine cell) is the correct query."""
        if self._tree is None:
            from scipy.spatial import cKDTree

            rr, cc = np.nonzero(self.kind)
            pts = self.centers[rr, cc]
            self._flat = np.column_stack([cc + 1, rr + 1]).astype(np.int32)
            self._tree = cKDTree(pts)
        return self._tree

    def lookup(self, x: float, y: float) -> dict | None:
        """Pixel -> electrode, or None outside the selection radius (his click rule)."""
        tree = self._index()
        d, i = tree.query([float(x), float(y)])
        if not math.isfinite(d) or d > self.hit_radius:
            return None
        col, row = (int(v) for v in self._flat[i])
        cx, cy = (float(v) for v in self.centers[row - 1, col - 1])
        hit = {
            "electrode": f"{col}-{row}",
            "col": col,
            "row": row,
            "center_x": cx,
            "center_y": cy,
            "distance": float(d),
            "kind": "detected" if self.kind[row - 1, col - 1] == self.KIND_DETECTED else "inferred",
        }
        if self.um is not None:
            # the readout shows the selection in um ALONGSIDE px (R45.8)
            hit["x_um"] = float(self.um[row - 1, col - 1, 0])
            hit["y_um"] = float(self.um[row - 1, col - 1, 1])
        return hit

    def payload(self) -> dict:
        """JSON-safe wire/outputs form: flat parallel arrays, absent cells omitted."""
        rr, cc = np.nonzero(self.kind)
        order = np.lexsort((cc, rr))
        rr, cc = rr[order], cc[order]
        pts = self.centers[rr, cc]
        cells = {
            "col": (cc + 1).tolist(),
            "row": (rr + 1).tolist(),
            "x": [round(float(v), 2) for v in pts[:, 0]],
            "y": [round(float(v), 2) for v in pts[:, 1]],
            # um ALONGSIDE px, never instead (R45.8). No device -> no measured scale -> the
            # lists are empty, which is how a reader tells "not known" from "0.0".
            "x_um": [],
            "y_um": [],
            "kind": self.kind[rr, cc].tolist(),
        }
        if self.um is not None:
            u = self.um[rr, cc]
            cells["x_um"] = [round(float(v), 2) for v in u[:, 0]]
            cells["y_um"] = [round(float(v), 2) for v in u[:, 1]]
        return {
            "cols": self.cols,
            "rows": self.rows,
            "pitch_px": round(self.pitch, 4),
            "angle_deg": round(self.angle_deg, 4),
            "hit_radius_px": round(self.hit_radius, 4),
            "a1": [round(v, 5) for v in self.a1],
            "a2": [round(v, 5) for v in self.a2],
            "um_per_px": round(self.um_per_px, 6) if self.um_per_px is not None else None,
            "device": self.device.as_dict() if self.device is not None else None,
            "array_coverage": self.array_coverage,
            "stats": self.stats,
            "cells": cells,
        }


# =============================================================================
# Pipeline
# =============================================================================
def fit_grid(image: np.ndarray, valid: np.ndarray | None = None,
             cfg: GridConfig = GridConfig(), progress=None,
             device: DeviceSpec | None = None, enforce_shape: bool = False) -> GridMap:
    """Fit the electrode lattice of a finished mosaic.

    image    : 2-D grayscale, any dtype (raw counts or 8-bit render both work — the
               high-pass normalises scale away).
    valid    : optional bool mask of pixels that carry data (coverage); background
               outside it is ignored entirely.
    progress : optional callable(str) for job phase messages.
    device   : the chip the user says he imaged. Passed in BOTH coverage modes — it is
               what gives the um scale (`device.pitch_um / pitch`) and the per-cell
               `x_um`/`y_um`. Without it the map is pixels only.
    enforce_shape : make the device's array shape binding, STRICTLY (R45.8). ⚠️ True ONLY
               when the user chose "whole chip imaged" — a partial mosaic legitimately fits
               any shape, and enforcing there would refuse perfectly good maps. True returns
               the device's shape with every position numbered, or raises NoGridFound.
    """
    # ⛔ A programming error, not a user one: `enforce_shape` with no device would label the
    # map "full" while enforcing NOTHING — the one state his "strictly enforced" forbids most,
    # because the map then CLAIMS the whole chip without ever having been checked against it.
    if enforce_shape and device is None:
        raise ValueError(
            "enforce_shape=True needs a device: 'whole chip imaged' is a claim about a "
            "DeviceSpec, and there is nothing to enforce without one")

    say = progress or (lambda _msg: None)
    img = np.ascontiguousarray(image, dtype=np.float32)
    if img.ndim != 2:
        raise ValueError(f"expected a 2-D grayscale image, got shape {image.shape}")
    if valid is None:
        valid = np.ones(img.shape, bool)
    else:
        valid = np.asarray(valid, bool)
        if valid.shape != img.shape:
            raise ValueError("valid mask shape does not match the image")

    say("high-pass")
    hp, valid_core = _highpass(img, valid, cfg)

    say("lattice fit")
    a1, a2, snr = _lattice_vectors(hp, valid_core, cfg)

    say("array mask")
    mask = _array_mask(hp, valid_core, a1, a2)

    say("pad detection")
    # `corr` — the matched-filter surface — comes back out because the registration check below
    # asks the PIXELS whether the array really ends where the numbering says. It is already
    # computed here; recomputing it there would be a second, subtly different answer.
    xs, ys, conf, corr = _detect_pads(hp, mask, a1, a2, cfg)

    say("indexing")
    # A position may only claim a detection of honest strength: the matched filter's noise floor
    # on this small template reaches ~0.2-0.35, so an EMPTY position (dead or occluded pad) would
    # otherwise adopt a noise maximum and report 'detected'. Relative to the strong-pad
    # population so blur across a mosaic stays tolerated.
    # ⚠️ DERIVED ONCE, HERE, because `_assemble` recovers pads too (`_claim_dim_pads`) and a pad
    # it recovers has to clear the SAME bar growth held its own to — otherwise "detected" would
    # mean two different strengths of evidence in one map.
    conf_floor = 0.4 * float(np.percentile(conf, 90))
    cells = _grow(xs, ys, conf, a1, a2, mask, cfg, conf_floor)

    say("assembling")
    gm = _assemble(cells, a1, a2, snr, cfg, corr, conf_floor)

    # The device half runs on the finished, purely geometric assembly — `_assemble` stays a
    # function of the pixels alone, and everything the user ASSERTED is applied here.
    gm.array_coverage = "full" if enforce_shape else "partial"
    if device is not None:
        if enforce_shape:
            # ⛔ TWO CHECKS AND NO REPAIR. The shape is the device's or the job refuses; the
            # numbering is where the pixels put the array's edge or the job refuses. Nothing
            # here moves a line — see `_enforce_device_shape` for the two repair rules that
            # were built, tested, and caught shifting every id while reporting the right shape.
            _enforce_device_shape(gm, device)
            _assert_registered(gm, corr, valid_core, cfg)
            _fill_every_position(gm)     # full = the chip HAS an electrode everywhere
            _relax_grid_inferred(gm)     # the filled cells become their neighbours' consensus
            _refresh_stats(gm)           # the stats describe the map actually returned
            # ⚠️ the fill added cells; a KD-tree built before it would serve a grid that has
            # since gained positions
            gm._tree = None
            gm._flat = None
        _apply_um_frame(gm, device)             # both modes: 17.5 um is always the scale

    # ⭐ THE POSTCONDITION — *"if the user select full imaging then I want the rules to be
    # strictly enforced"*. ONE gate at the exit, not an invariant spread over the helpers, so
    # no path through this function can return a "full" map that is not the declared device.
    if enforce_shape:
        _assert_full_shape(gm, device)
    return gm


def measure_lattice(image: np.ndarray, valid: np.ndarray | None = None,
                    *, pitch_min: float = 6.0, pitch_max: float = 200.0,
                    cfg: GridConfig | None = None) -> tuple[float, float, float]:
    """`(pitch_px, angle_deg, snr)` — the lattice ALONE, without detecting or indexing pads.

    ⭐ **This is a ruler, and it is what makes a differently-magnified recording placeable.**
    The same electrode array appears in the mosaic and in a fixed-region calcium recording, so
    the ratio of the two measured pitches IS the magnification ratio between them
    (`core.locate.measure_zoom`). Measuring beats searching a ladder of zoom factors: one
    number instead of thirteen chances for a grid alias to win.

    It stops after `fit_grid`'s first two phases — high-pass, then the windowed-FFT
    fundamentals — so it costs a fraction of a full fit and needs no coverage geometry, no
    device, and no pad detection. Everything the full fit does after this point exists to
    NUMBER pads; none of it is needed to read a period.

    ⚠️ `pitch_max` defaults wider than `GridConfig`'s 64 px. That default bounds a *mosaic's*
    pitch; a region recording is by definition at higher magnification, and 17.5 um through
    40x optics lands well past 100 px. It is still bounded, because the FFT ring for a very
    long period sits within a few bins of DC where nothing can be told apart.

    Raises `NoGridFound` with a sentence when there is no lattice to read — which for a
    calcium recording of bare tissue is a legitimate answer, not a failure.
    """
    a1, a2, snr = lattice_axes(image, valid, pitch_min=pitch_min, pitch_max=pitch_max, cfg=cfg)
    # the same two derivations `_assemble` uses, so a measured pitch/angle is comparable with
    # a fitted map's `pitch_px` / `angle_deg` without anyone having to convert
    pitch = float((np.hypot(*a1) + np.hypot(*a2)) / 2)
    angle = float(math.degrees(math.atan2(a1[1], a1[0])))
    return pitch, angle, float(snr)


def lattice_axes(image: np.ndarray, valid: np.ndarray | None = None,
                 *, pitch_min: float = 6.0, pitch_max: float = 200.0,
                 cfg: GridConfig | None = None) -> tuple[np.ndarray, np.ndarray, float]:
    """`(a1, a2, snr)` — the two primitive lattice VECTORS, in px, as `_lattice_vectors` found
    them. `measure_lattice` is this reduced to a period and an angle.

    Wanted whole because a lattice's *direction* matters to anything that filters it out:
    `core.locate.notch_lattice` needs the reciprocal basis, and a pitch alone cannot give it.
    """
    base = cfg or GridConfig()
    c = dataclasses.replace(base, pitch_min=float(pitch_min), pitch_max=float(pitch_max))

    img = np.ascontiguousarray(image, dtype=np.float32)
    if img.ndim != 2:
        raise ValueError(f"expected a 2-D grayscale image, got shape {image.shape}")
    if valid is None:
        valid = np.ones(img.shape, bool)
    else:
        valid = np.asarray(valid, bool)
        if valid.shape != img.shape:
            raise ValueError("valid mask shape does not match the image")

    hp, core = _highpass(img, valid, c)
    a1, a2, snr = _lattice_vectors(hp, core, c)
    return np.asarray(a1, float), np.asarray(a2, float), float(snr)


# -----------------------------------------------------------------------------
def _highpass(img, valid, cfg):
    """img minus its Gaussian blur, MAD-normalised, zeroed off-mask. The mask is eroded
    by the filter scale so coverage edges (black -> bright ramps) cannot fake pads."""
    import cv2

    blur = cv2.GaussianBlur(img, (0, 0), cfg.highpass_sigma)
    hp = img - blur
    m = valid.astype(np.uint8)
    r = max(2, int(round(2 * cfg.highpass_sigma)))
    core = cv2.erode(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))).astype(bool)
    vals = hp[core]
    if vals.size < 1024:
        raise NoGridFound("almost no valid pixels to analyse")
    med = float(np.median(vals))
    mad = float(np.median(np.abs(vals - med))) * 1.4826
    if mad <= 0:
        raise NoGridFound("image is flat inside the valid mask")
    hp = (hp - med) / mad
    hp[~core] = 0.0
    return hp, core


# -----------------------------------------------------------------------------
def _lattice_vectors(hp, valid, cfg):
    """Initial primitive lattice vectors from the averaged windowed power spectrum.

    Windows are placed where coverage is best; Hann windowing kills the frame's own
    edges. The two fundamentals must be near-orthogonal with similar radii (a square-ish
    lattice) — that pairing requirement is what rejects 1-D structures (the array's
    border bar) and broadband texture. ⚠️ The peaks give period and DIRECTION; for a
    near-orthogonal lattice the primitive vector along peak f is f * N/|f|² to excellent
    approximation, and region growing refines the rest."""
    H, W = hp.shape
    N = 1 << int(math.log2(max(64, min(1024, min(H, W)))))
    if N > min(H, W):
        N = 1 << int(math.log2(min(H, W)))
    if N < 64 or N < 4 * cfg.pitch_min:
        raise NoGridFound("image too small for a lattice fit")

    # best-covered windows on a coarse grid, greedily kept apart
    step = max(1, N // 2)
    cand = []
    for oy in range(0, H - N + 1, step):
        for ox in range(0, W - N + 1, step):
            frac = valid[oy:oy + N, ox:ox + N].mean()
            if frac > 0.35:
                cand.append((frac, oy, ox))
    if not cand:
        raise NoGridFound("no window with enough coverage")
    cand.sort(reverse=True)
    wins, taken = [], []
    for frac, oy, ox in cand:
        if all(abs(oy - ty) >= N // 2 or abs(ox - tx) >= N // 2 for ty, tx in taken):
            wins.append((oy, ox))
            taken.append((oy, ox))
            if len(wins) == 5:
                break

    hann = np.hanning(N).astype(np.float32)
    win2d = hann[:, None] * hann[None, :]
    P = np.zeros((N, N), np.float32)
    for oy, ox in wins:
        P += np.abs(np.fft.fftshift(np.fft.fft2(hp[oy:oy + N, ox:ox + N] * win2d))) ** 2

    ctr = N // 2
    yy, xx = np.mgrid[0:N, 0:N]
    r = np.hypot(yy - ctr, xx - ctr)
    band = (r >= N / cfg.pitch_max) & (r <= N / cfg.pitch_min)

    # Robust spectral background per radius ring. ⚠️ A plain ring-median is POISONED on
    # the rings that carry the lattice peaks themselves (tangential mainlobe leakage
    # lifts the whole ring ~20x, measured) — ranking by P/median then prefers bins one
    # ring INWARD of every true peak. So: take the min of the ring-medians over a small
    # radial neighbourhood (the leakage is radially local), gate on that, and rank
    # candidate PAIRS by raw power, where fundamentals genuinely dominate.
    rbin = r.astype(np.int32)
    lo_r, hi_r = int(N / cfg.pitch_max) - 3, int(N / cfg.pitch_min) + 4
    med = {}
    for rad in range(max(1, lo_r), hi_r + 1):
        sel = rbin == rad
        if sel.any():
            med[rad] = float(np.median(P[sel]))
    bg = np.full(N, np.inf, np.float32)
    for rad in med:
        near = [med.get(rad + d) for d in (-3, -2, -1, 0, 1, 2, 3)]
        bg[rad] = max(1e-12, min(v for v in near if v is not None))

    import cv2
    dil = cv2.dilate(P, np.ones((5, 5), np.uint8))
    py_, px_ = np.nonzero((P >= dil) & band)
    fs = []
    for py, px in zip(py_, px_):
        fy, fx = int(py - ctr), int(px - ctr)
        if fy < 0 or (fy == 0 and fx <= 0):
            continue
        rad = int(round(math.hypot(fx, fy)))
        snr_here = float(P[py, px] / bg[min(rad, N - 1)])
        if snr_here < cfg.peak_snr_min:
            continue
        # 2-D isolation: a true lattice fundamental is a point in the spectrum. The
        # border ring's straight lines make RIDGES (1-D combs) whose maxima stay high
        # along the ridge, and out-of-focus blobs make smooth slopes whose "maxima"
        # stay high in every direction — both must never be paired into a lattice.
        peak = float(P[py, px])
        ring_max = 0.0
        for t in range(8):
            a = t * math.pi / 4
            sy = py + int(round(3.2 * math.sin(a)))
            sx = px + int(round(3.2 * math.cos(a)))
            if 0 <= sy < N and 0 <= sx < N:
                ring_max = max(ring_max, float(P[sy, sx]))
        if ring_max > 0.35 * peak:
            continue
        fs.append((peak, snr_here, float(fx), float(fy)))
    fs.sort(reverse=True)
    fs = fs[:24]
    if len(fs) < 2:
        raise NoGridFound("no periodic lattice in the spectrum")

    def power_at(fx, fy):
        iy, ix = int(round(fy)) + ctr, int(round(fx)) + ctr
        if 0 <= iy < N and 0 <= ix < N:
            return float(P[iy, ix])
        return 0.0

    best = None
    for i in range(len(fs)):
        p1, s1, x1, y1 = fs[i]
        r1 = math.hypot(x1, y1)
        for j in range(i + 1, len(fs)):
            p2, s2, x2, y2 = fs[j]
            r2 = math.hypot(x2, y2)
            if not (0.8 <= r1 / r2 <= 1.25):
                continue
            cosang = abs(x1 * x2 + y1 * y2) / (r1 * r2)
            if cosang > 0.20:  # within ~12 deg of orthogonal
                continue
            # half-sum test: if (f1+f2)/2 is itself a strong peak, (f1, f2) are the
            # DIAGONALS of a denser reciprocal lattice, not its fundamentals
            half = max(power_at((x1 + x2) / 2, (y1 + y2) / 2),
                       power_at((x1 - x2) / 2, (y1 - y2) / 2))
            if half > 0.25 * min(p1, p2):
                continue
            score = p1 + p2
            if best is None or score > best[0]:
                best = (score, (x1, y1), (x2, y2), min(s1, s2))
    if best is None:
        raise NoGridFound("no orthogonal peak pair — not a 2-D lattice")

    _, f1, f2, snr = best
    vecs = []
    for fx, fy in (f1, f2):
        rr = fx * fx + fy * fy
        vecs.append((fx * N / rr, fy * N / rr))
    # a1 = the more horizontal axis pointing right; a2 = the other pointing down
    vecs.sort(key=lambda v: abs(v[1]) / (abs(v[0]) + 1e-12))
    a1, a2 = vecs
    if a1[0] < 0:
        a1 = (-a1[0], -a1[1])
    if a2[1] < 0:
        a2 = (-a2[0], -a2[1])
    return np.array(a1, np.float64), np.array(a2, np.float64), float(snr)


# -----------------------------------------------------------------------------
def _array_mask(hp, valid, a1, a2):
    """Where the ARRAY is: quadrature (Gabor) energy at BOTH lattice frequencies —
    the border ring and plain tissue have at most one. Interior holes (pads hidden
    under cells) are filled: occlusion must not stop indexing, his every-position
    ruling depends on it."""
    import cv2

    pitch = (np.hypot(*a1) + np.hypot(*a2)) / 2
    E = None
    for v in (a1, a2):
        per = float(np.hypot(*v))
        d = (v[0] / per, v[1] / per)
        k = int(round(2.2 * pitch)) | 1
        c = np.arange(k) - k // 2
        gx, gy = np.meshgrid(c, c)
        proj = gx * d[0] + gy * d[1]
        env = np.exp(-(gx ** 2 + gy ** 2) / (2 * (0.8 * per) ** 2)).astype(np.float32)
        kc = (env * np.cos(2 * np.pi * proj / per)).astype(np.float32)
        ks = (env * np.sin(2 * np.pi * proj / per)).astype(np.float32)
        kc -= kc.mean()
        ks -= ks.mean()
        rc = cv2.filter2D(hp, cv2.CV_32F, kc)
        rs = cv2.filter2D(hp, cv2.CV_32F, ks)
        # ⚠️ smoothing sigma is deliberately TIGHT (0.6 pitch): with sigma = pitch the
        # pads' energy spills ~1.5 pitches past the array edge, the close() below then
        # bridges the gap to the border ring, and the ring's line detections mint
        # phantom edge columns that shift EVERY id by one or two (observed).
        e = cv2.GaussianBlur(rc * rc + rs * rs, (0, 0), 0.6 * pitch)
        E = e if E is None else np.sqrt(E * e)

    E[~valid] = 0.0
    pos = E[E > 0]
    if pos.size == 0:
        raise NoGridFound("no lattice energy anywhere")
    hi = float(np.percentile(pos, 90))
    if hi <= 0:
        raise NoGridFound("no lattice energy anywhere")
    m = (E > 0.15 * hi).astype(np.uint8)

    r = max(3, int(round(0.75 * pitch)))
    se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, se)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, se)

    # keep components of meaningful size (>= ~5x5 cells)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    keep = np.zeros_like(m)
    min_area = (5 * pitch) ** 2
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] >= min_area:
            keep[lab == i] = 1
    if not keep.any():
        raise NoGridFound("lattice energy exists but never forms an array-sized region")

    # fill interior holes (occluders): anything not reachable from the border is array
    ff = keep.copy()
    ffm = np.zeros((ff.shape[0] + 2, ff.shape[1] + 2), np.uint8)
    cv2.floodFill(ff, ffm, (0, 0), 1)
    holes = (ff == 0)
    keep[holes] = 1

    # pull the outer boundary back toward the outermost pads: the energy blur + close
    # smear the mask ~1-2 pitches past the array, and growth would happily index noise
    # there as a phantom edge row/column
    r2 = max(1, int(round(0.6 * pitch)))
    se2 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r2 + 1, 2 * r2 + 1))
    shrunk = cv2.erode(keep, se2)
    if shrunk.any():
        keep = shrunk
    return keep.astype(bool)


# -----------------------------------------------------------------------------
def _detect_pads(hp, mask, a1, a2, cfg):
    """Matched-filter pad candidates with sub-pixel centres, plus the SURFACE they came from.

    The template is a small bright blob at the lattice scale; TM_CCOEFF_NORMED makes the
    confidence comparable across bright and dim regions. `corr` is returned as well because it
    is the only honest evidence about a line the fit did NOT index: a candidate edge line has
    no detections by definition, so counting them says nothing — reading `corr` where its pads
    would be says everything (R45.8 strict)."""
    import cv2

    pitch = (np.hypot(*a1) + np.hypot(*a2)) / 2
    sig = max(1.0, 0.18 * pitch)
    k = int(round(pitch)) | 1
    c = np.arange(k) - k // 2
    gx, gy = np.meshgrid(c, c)
    tmpl = np.exp(-(gx ** 2 + gy ** 2) / (2 * sig ** 2)).astype(np.float32)

    corr_small = cv2.matchTemplate(hp, tmpl, cv2.TM_CCOEFF_NORMED)
    corr = np.full(hp.shape, -1.0, np.float32)
    o = k // 2
    corr[o:o + corr_small.shape[0], o:o + corr_small.shape[1]] = corr_small

    r = max(2, int(round(0.30 * pitch)))
    se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    dil = cv2.dilate(corr, se)
    py, px = np.nonzero((corr >= dil) & (corr >= cfg.corr_min) & mask)
    if py.size == 0:
        raise NoGridFound("no pad-like detections inside the array")

    xs = np.empty(py.size, np.float32)
    ys = np.empty(py.size, np.float32)
    cf = corr[py, px].astype(np.float32)
    for i in range(py.size):
        xs[i], ys[i] = _subpixel(corr, int(px[i]), int(py[i]))
    return xs, ys, cf, corr


def _subpixel(corr, x: int, y: int) -> tuple[float, float]:
    """A correlation maximum refined to sub-pixel by a 1-D parabola per axis.

    ⚠️ ONE COPY, TWO CALLERS (`_detect_pads` and `_claim_dim_pads`). A pad growth found and a
    pad recovered later must land on the same sub-pixel convention or the two populations would
    sit a fraction of a pixel apart on the same lattice, and `_step_residuals` — the gate that
    decides whether an image has a lattice at all — would read that split as incoherence."""
    def parab(cm, cc, cp):
        den = cm + cp - 2 * cc
        if den >= -1e-9:
            return 0.0
        return float(np.clip(0.5 * (cm - cp) / den, -0.5, 0.5))

    H, W = corr.shape
    dx = parab(corr[y, x - 1], corr[y, x], corr[y, x + 1]) if 0 < x < W - 1 else 0.0
    dy = parab(corr[y - 1, x], corr[y, x], corr[y + 1, x]) if 0 < y < H - 1 else 0.0
    return x + dx, y + dy


# -----------------------------------------------------------------------------
class _Buckets:
    """Pitch-sized spatial hash over detections — O(1) 'nearest unclaimed within r'."""

    def __init__(self, xs, ys, cell):
        self.xs, self.ys, self.cell = xs, ys, float(cell)
        self.claimed = np.zeros(xs.size, bool)
        self.map: dict[tuple[int, int], list[int]] = {}
        for i in range(xs.size):
            self.map.setdefault((int(xs[i] // cell), int(ys[i] // cell)), []).append(i)

    def nearest_free(self, x, y, r, conf=None, min_conf=-1.0):
        bx, by = int(x // self.cell), int(y // self.cell)
        best, bd = -1, r * r
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for i in self.map.get((bx + dx, by + dy), ()):
                    if self.claimed[i] or (conf is not None and conf[i] < min_conf):
                        continue
                    d = (self.xs[i] - x) ** 2 + (self.ys[i] - y) ** 2
                    if d <= bd:
                        best, bd = i, d
        return best


def _grow(xs, ys, conf, a1, a2, mask, cfg, conf_floor):
    """Confidence-ordered region growing. Each assigned cell carries its own local
    lattice vectors, exponentially updated from the steps actually observed — this is
    what absorbs the focus-driven pitch drift a rigid model cannot. Predictions average
    over ALL already-indexed neighbours; a tight snap radius keeps a drifted prediction
    from claiming the wrong pad (stay inferred, approach again from another side)."""
    pitch = (np.hypot(*a1) + np.hypot(*a2)) / 2
    r_snap = cfg.snap_frac * pitch
    H, W = mask.shape
    bk = _Buckets(xs, ys, max(4.0, pitch))

    order = np.argsort(conf)[::-1]
    seed = -1
    for i in order[:400]:
        x, y = float(xs[i]), float(ys[i])
        hits = 0
        for u, v in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            p = (x + u * a1[0] + v * a2[0], y + u * a1[1] + v * a2[1])
            j = bk.nearest_free(p[0], p[1], r_snap)
            if j >= 0 and j != i:
                hits += 1
        if hits >= 5:
            seed = int(i)
            break
    if seed < 0:
        raise NoGridFound("no coherent seed — detections do not sit on one lattice")

    # cell record: [x, y, prio, kind, v1x, v1y, v2x, v2y]
    cells: dict[tuple[int, int], list[float]] = {}
    K_DET, K_INF = 1, 2

    def assign(ij, x, y, prio, kind, v1, v2):
        cells[ij] = [x, y, prio, kind, v1[0], v1[1], v2[0], v2[1]]
        i, j = ij
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if (i + di, j + dj) not in cells:
                heapq.heappush(frontier, (-prio, next(seq), i + di, j + dj))

    frontier: list = []
    from itertools import count
    seq = count()
    bk.claimed[seed] = True
    assign((0, 0), float(xs[seed]), float(ys[seed]), 1.0, K_DET,
           (float(a1[0]), float(a1[1])), (float(a2[0]), float(a2[1])))

    p_lo, p_hi = 0.85 * pitch, 1.15 * pitch
    while frontier:
        _, _, i, j = heapq.heappop(frontier)
        if (i, j) in cells:
            continue
        preds, v1s, v2s, prios = [], [], [], []
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nb = cells.get((i + di, j + dj))
            if nb is None:
                continue
            nx, ny, nprio, _, v1x, v1y, v2x, v2y = nb
            preds.append((nx - di * v1x - dj * v2x, ny - di * v1y - dj * v2y))
            v1s.append((v1x, v1y))
            v2s.append((v2x, v2y))
            prios.append(nprio)
        if not preds:
            continue
        px = float(np.mean([p[0] for p in preds]))
        py = float(np.mean([p[1] for p in preds]))
        iy, ix = int(round(py)), int(round(px))
        if not (0 <= ix < W and 0 <= iy < H) or not mask[iy, ix]:
            continue
        v1 = np.mean(v1s, axis=0)
        v2 = np.mean(v2s, axis=0)

        d = bk.nearest_free(px, py, r_snap, conf, conf_floor)
        if d >= 0:
            bk.claimed[d] = True
            dx, dy = float(xs[d]), float(ys[d])
            # observed steps refine the local vectors (clamped so noise can't run away)
            for di, dj in ((1, 0), (-1, 0)):
                nb = cells.get((i + di, j + dj))
                if nb is not None:
                    obs = np.array([(dx - nb[0]) / -di, (dy - nb[1]) / -di])
                    if p_lo <= np.hypot(*obs) <= p_hi:
                        v1 = v1 + cfg.vec_beta * (obs - v1)
            for di, dj in ((0, 1), (0, -1)):
                nb = cells.get((i + di, j + dj))
                if nb is not None:
                    obs = np.array([(dx - nb[0]) / -dj, (dy - nb[1]) / -dj])
                    if p_lo <= np.hypot(*obs) <= p_hi:
                        v2 = v2 + cfg.vec_beta * (obs - v2)
            assign((i, j), dx, dy, float(conf[d]), K_DET,
                   (float(v1[0]), float(v1[1])), (float(v2[0]), float(v2[1])))
        else:
            # occluded/undetectable: carry the prediction, decayed priority so growth
            # prefers flowing through real detections and closes holes from all sides
            prio = 0.85 * float(np.mean(prios))
            if prio > 1e-4:
                assign((i, j), px, py, prio, K_INF,
                       (float(v1[0]), float(v1[1])), (float(v2[0]), float(v2[1])))

    # Inferred centres from single-pass growth carry chain drift (they were predicted
    # from whichever neighbours happened to be assigned first). Relax them to the
    # consensus of ALL their neighbours — detected cells stay pinned — then give each a
    # second chance to land on a real, unclaimed detection, and relax once more.
    _relax_inferred(cells, K_INF)
    for (i, j), rec in cells.items():
        if rec[3] == K_INF:
            d = bk.nearest_free(rec[0], rec[1], r_snap, conf, conf_floor)
            if d >= 0:
                bk.claimed[d] = True
                rec[0], rec[1], rec[3] = float(xs[d]), float(ys[d]), K_DET
    _relax_inferred(cells, K_INF)
    return cells


def _relax_inferred(cells, K_INF, iters=12):
    """Jacobi-relax inferred centres onto the lattice their neighbours agree on. Each
    neighbour votes with its OWN local vectors, so the relaxation follows the measured
    drift instead of a rigid model; diagonal votes serve cells with no axis neighbour."""
    axis = ((1, 0), (-1, 0), (0, 1), (0, -1))
    diag = ((1, 1), (1, -1), (-1, 1), (-1, -1))
    inferred = [ij for ij, rec in cells.items() if rec[3] == K_INF]
    for _ in range(iters):
        moved = 0.0
        new = {}
        for (i, j) in inferred:
            preds, v1s, v2s = [], [], []
            for di, dj in axis + diag:
                nb = cells.get((i + di, j + dj))
                if nb is None:
                    continue
                nx, ny, _, _, v1x, v1y, v2x, v2y = nb
                preds.append((nx - di * v1x - dj * v2x, ny - di * v1y - dj * v2y))
                v1s.append((v1x, v1y))
                v2s.append((v2x, v2y))
            if preds:
                new[(i, j)] = (float(np.mean([p[0] for p in preds])),
                               float(np.mean([p[1] for p in preds])),
                               [float(v) for v in np.mean(v1s, axis=0)],
                               [float(v) for v in np.mean(v2s, axis=0)])
        for (i, j), (x, y, v1, v2) in new.items():
            rec = cells[(i, j)]
            moved = max(moved, abs(rec[0] - x) + abs(rec[1] - y))
            rec[0], rec[1] = x, y
            rec[4], rec[5], rec[6], rec[7] = v1[0], v1[1], v2[0], v2[1]
        if moved < 0.05:
            break


# -----------------------------------------------------------------------------
def _claim_dim_pads(centers, kind, conf, a1m, a2m, corr, conf_floor, cfg) -> int:
    """Recover pads the array mask was too dim to admit — INSIDE the fit's own bounding box, on
    the matched filter's word, one ring at a time. Returns how many were claimed.

    ⭐ **WHY THIS EXISTS** (his report, 2026-08-11: *"electrodes are missing for this mosaic in
    the bottom left corner"*). `_array_mask` thresholds Gabor ENERGY, which goes as amplitude
    SQUARED, against a percentile of the WHOLE image — so it measures BRIGHTNESS where it means
    to measure lattice content. A survey mosaic is not evenly lit: on his real 5319x7356 video
    mosaic the corner swept last ran 3.9x down in high-pass amplitude — 8x down in energy — and
    fell under a bar the bright middle had set. 120 positions went unnumbered, while the matched
    filter read **0.64** there, *higher* than at the indexed cells around them. The pads were
    never in doubt. Only the mask was.

    ⛔ **AND WHY THE MASK IS NOT WHAT CHANGED.** Every brightness-invariant statistic that
    recovers the corner also drags the mask's outer boundary a full lattice step outward
    (measured on this mosaic: a locally-referenced energy and a normalised coherence both reach
    +1.00 steps where the shipped mask reaches +0.50). One step out is where the PADS' OWN filter
    support bleeds to — it is literally made of pads, so no intensity statistic evaluated there
    can tell it from a pad. That step is a phantom edge line, and a phantom edge line shifts
    EVERY id by one. Nothing downstream would catch it: a phantom line here carries ~191
    claimable cells against `_assemble`'s trim threshold of 44, and `_assert_registered` is blind
    to a phantom that is already INSIDE the numbering. In partial mode nothing else looks at all.

    So the boundary stays exactly where the conservative mask put it, and only the INTERIOR is
    revisited. A position already inside the fit's bounding box has indexed array on both sides
    of it along at least one axis, by construction — admitting it cannot move an edge. That
    geometric bound is what makes this safe without a threshold to tune, and it is why the rule
    is written as "fill the box", not "loosen the mask".

    ⚠️ **IT ADDS ONLY MEASURED PADS, NEVER GUESSES.** A position whose pixels show nothing is
    left exactly as it was, for the notch fill and (in full mode) `_fill_every_position` to
    reason about — so a corner the COVERAGE never saw stays absent, which is what "partial"
    means. And the claim must clear `conf_floor`, the same bar growth held its own detections to,
    so a recovered pad is evidence of the same strength and not a weaker class wearing the same
    label.

    ⚠️ It cannot steal a neighbour's ground: the search radius is `snap_frac * pitch` — growth's
    own snap radius — so two adjacent positions' windows stay half a pitch apart at closest.
    """
    rows, cols = kind.shape
    pitch = (np.hypot(*a1m) + np.hypot(*a2m)) / 2
    r_snap = cfg.snap_frac * pitch
    # every assigned neighbour votes, each stepping to this cell with the vector that separates
    # them; the diagonals are in because a cell first reached at a box corner can have no axis
    # neighbour yet
    nbrs = ((0, -1, a1m), (0, 1, -a1m), (-1, 0, a2m), (1, 0, -a2m),
            (-1, -1, a1m + a2m), (-1, 1, -a1m + a2m),
            (1, -1, a1m - a2m), (1, 1, -a1m - a2m))
    claimed = 0
    for _ in range(rows + cols + 2):       # each pass reaches one ring further into the hole
        got = 0
        for r, c in np.argwhere(kind == GridMap.KIND_ABSENT):
            r, c = int(r), int(c)
            preds = [centers[r + dr, c + dc] + v for dr, dc, v in nbrs
                     if 0 <= r + dr < rows and 0 <= c + dc < cols and kind[r + dr, c + dc]]
            # two independent votes minimum: one neighbour's own drift would otherwise place
            # the window, and a window in the wrong place finds either nothing or the wrong pad
            if len(preds) < 2:
                continue
            px, py = (float(v) for v in np.mean(preds, axis=0))
            hit = _peak_near(corr, px, py, r_snap, conf_floor)
            if hit is None:
                continue
            centers[r, c] = (hit[0], hit[1])
            kind[r, c] = GridMap.KIND_DETECTED
            conf[r, c] = hit[2]
            got += 1
        claimed += got
        if not got:
            break
    return claimed


def _peak_near(corr, x: float, y: float, radius: float,
               floor: float) -> tuple[float, float, float] | None:
    """`(x, y, confidence)` of the matched filter's best pad within `radius` of (x, y), sub-pixel
    — or None if the strongest thing there is not pad-like enough to claim.

    Reads the correlation surface DIRECTLY rather than the detection list, because the detections
    were only ever collected inside the array mask: at a position the mask excluded there is no
    candidate to find, which is precisely the situation this recovers from."""
    H, W = corr.shape
    r = max(1, int(round(radius)))
    ix, iy = int(round(x)), int(round(y))
    x0, x1 = max(1, ix - r), min(W - 1, ix + r + 1)
    y0, y1 = max(1, iy - r), min(H - 1, iy + r + 1)
    if x1 <= x0 or y1 <= y0:
        return None
    win = corr[y0:y1, x0:x1]
    wy, wx = np.unravel_index(int(np.argmax(win)), win.shape)
    px, py = x0 + int(wx), y0 + int(wy)
    best = float(corr[py, px])
    if best < floor:
        return None
    # the window is a square but the snap radius is a DISC, the same shape growth snapped with
    if (px - x) ** 2 + (py - y) ** 2 > radius ** 2:
        return None
    sx, sy = _subpixel(corr, px, py)
    return sx, sy, best


def _assemble(cells, a1, a2, snr, cfg, corr=None, conf_floor=-1.0):
    """Integer indices -> 1-based grid with 1-1 at top-left. Edge rows/columns with zero
    detected pads are trimmed: an inferred-only fringe (mask slop) must never shift the
    numbering of everything else by one."""
    K_DET = 1
    idx = np.array(list(cells.keys()), np.int64)
    kinds = np.array([cells[tuple(k)][3] for k in idx], np.uint8)

    i_lo, i_hi = int(idx[:, 0].min()), int(idx[:, 0].max())
    j_lo, j_hi = int(idx[:, 1].min()), int(idx[:, 1].max())

    # robust edge trim: a REAL edge row/column carries a meaningful share of detected
    # pads; a phantom one (mask slop + a couple of noise hits that survived the snap)
    # carries almost none. One phantom edge row would shift EVERY id by one.
    det = idx[kinds == K_DET]
    col_counts = {i: int((det[:, 0] == i).sum()) for i in range(i_lo, i_hi + 1)}
    row_counts = {j: int((det[:, 1] == j).sum()) for j in range(j_lo, j_hi + 1)}
    t_col = max(2, int(math.ceil(0.2 * max(col_counts.values(), default=0))))
    t_row = max(2, int(math.ceil(0.2 * max(row_counts.values(), default=0))))
    while i_lo <= i_hi and col_counts[i_lo] < t_col:
        i_lo += 1
    while i_hi >= i_lo and col_counts[i_hi] < t_col:
        i_hi -= 1
    while j_lo <= j_hi and row_counts[j_lo] < t_row:
        j_lo += 1
    while j_hi >= j_lo and row_counts[j_hi] < t_row:
        j_hi -= 1
    if i_hi < i_lo or j_hi < j_lo:
        raise NoGridFound("nothing detected after trimming")

    cols = i_hi - i_lo + 1
    rows = j_hi - j_lo + 1
    centers = np.full((rows, cols, 2), np.nan, np.float32)
    kind = np.zeros((rows, cols), np.uint8)
    # per-cell confidence, kept as a PLANE: a later shape correction may drop a line, and
    # `mean_confidence` then has to be re-averaged over the survivors (R45.8 strict)
    conf = np.full((rows, cols), np.nan, np.float32)
    v1s, v2s, confs = [], [], []
    n_det = n_inf = 0
    for (i, j), rec in cells.items():
        if not (i_lo <= i <= i_hi and j_lo <= j <= j_hi):
            continue
        r, c = j - j_lo, i - i_lo
        centers[r, c] = (rec[0], rec[1])
        kind[r, c] = rec[3]
        if rec[3] == K_DET:
            n_det += 1
            conf[r, c] = rec[2]
            confs.append(rec[2])
            v1s.append((rec[4], rec[5]))
            v2s.append((rec[6], rec[7]))
        else:
            n_inf += 1

    if n_det < cfg.min_detected:
        raise NoGridFound(f"only {n_det} pads detected — not enough to trust an indexing")

    a1m = np.mean(v1s, axis=0)
    a2m = np.mean(v2s, axis=0)
    pitch = float((np.hypot(*a1m) + np.hypot(*a2m)) / 2)

    # ⭐ Pads the mask was too DIM to admit, recovered on the matched filter's word before
    # anything interpolates over them — a position with a pad in the pixels must come out
    # `detected` with a measured centre, not `inferred` from arithmetic (his bottom-left corner,
    # 2026-08-11). Runs BEFORE the notch fill so a recovered pad anchors the next ring instead of
    # being pre-empted by a guess.
    n_claimed = 0
    if corr is not None:
        n_claimed = _claim_dim_pads(centers, kind, conf, a1m, a2m, corr, conf_floor, cfg)

    # Fill one-cell notches the tight array mask clipped at the boundary: an absent
    # cell with >= 2 assigned axis neighbours is inside the array by construction and
    # gets an interpolated (inferred) centre — every position numbered, his ruling.
    for _ in range(2):
        filled = 0
        for rr in range(rows):
            for cc_ in range(cols):
                if kind[rr, cc_] != 0:
                    continue
                preds = []
                if cc_ > 0 and kind[rr, cc_ - 1]:
                    preds.append(centers[rr, cc_ - 1] + a1m)
                if cc_ < cols - 1 and kind[rr, cc_ + 1]:
                    preds.append(centers[rr, cc_ + 1] - a1m)
                if rr > 0 and kind[rr - 1, cc_]:
                    preds.append(centers[rr - 1, cc_] + a2m)
                if rr < rows - 1 and kind[rr + 1, cc_]:
                    preds.append(centers[rr + 1, cc_] - a2m)
                if len(preds) >= 2:
                    centers[rr, cc_] = np.mean(preds, axis=0)
                    kind[rr, cc_] = 2
                    n_inf += 1
                    filled += 1
        if not filled:
            break

    res = _step_residuals(centers, kind, a1m, a2m)

    # Lattice coherence: real pads sit on the lattice to a small fraction of the pitch;
    # a "grid" assembled from noise maxima scatters uniformly inside the snap radius.
    # This is the final line of defence for images that have no electrode array at all.
    med_res = float(np.median(res))
    if med_res > 0.12 * pitch:
        raise NoGridFound(
            f"detections do not cohere into a lattice (median step residual "
            f"{med_res:.2f}px on a {pitch:.1f}px pitch)")

    # ⚠️ Counted off the FINAL planes, not off the running totals: `_claim_dim_pads` turns absent
    # cells into detected ones after the loop above filled `n_det`/`n_inf` in, and stats that
    # describe the map before that describe a map nobody has (the same rule `_refresh_stats`
    # follows for the shape corrections).
    n_det = int((kind == K_DET).sum())
    n_inf = int((kind == 2).sum())
    confs = conf[kind == K_DET]
    confs = confs[np.isfinite(confs)]

    stats = {
        "n_detected": int(n_det),
        "n_inferred": int(n_inf),
        "detected_frac": round(n_det / max(1, n_det + n_inf), 4),
        "fft_snr": round(float(snr), 2),
        "mean_confidence": round(float(np.mean(confs)), 4) if confs.size else 0.0,
        # how many of those detections the array mask had missed for being dim. Reported because
        # it is the first number worth reading if the recovery pass ever misbehaves: on an evenly
        # lit image it is 0, and a large value says the mask and the pixels disagreed a lot.
        "n_recovered": int(n_claimed),
        "step_residual_median_px": round(float(np.median(res)), 3),
        "step_residual_p95_px": round(float(np.percentile(res, 95)), 3),
    }
    return GridMap(
        cols=cols, rows=rows, centers=centers, kind=kind,
        pitch=pitch,
        angle_deg=float(math.degrees(math.atan2(a1m[1], a1m[0]))),
        a1=(float(a1m[0]), float(a1m[1])),
        a2=(float(a2m[0]), float(a2m[1])),
        hit_radius=float(cfg.hit_frac * pitch),
        stats=stats,
        conf=conf,
    )


def _step_residuals(centers, kind, a1m, a2m) -> np.ndarray:
    """|observed step - mean lattice vector| over every detected-to-detected neighbour pair —
    the QC number that would expose a systematic (off-by-one-ish) shear.

    Shared with the post-correction stats so both are computed the same way: after a line is
    added or dropped the numbers have to be re-derived from the FINAL grid, and re-deriving
    them with a second, slightly different formula is how two "residuals" come to disagree."""
    K_DET = GridMap.KIND_DETECTED
    rows, cols = kind.shape
    res = []
    for r in range(rows):
        for c in range(cols - 1):
            if kind[r, c] == K_DET and kind[r, c + 1] == K_DET:
                res.append(float(np.hypot(*(centers[r, c + 1] - centers[r, c] - a1m))))
    for r in range(rows - 1):
        for c in range(cols):
            if kind[r, c] == K_DET and kind[r + 1, c] == K_DET:
                res.append(float(np.hypot(*(centers[r + 1, c] - centers[r, c] - a2m))))
    return np.array(res) if res else np.array([0.0])


# =============================================================================
# The device half — shape enforcement and the um frame (R45.8)
# =============================================================================
# `axis` below is the axis of `centers`/`kind` a LINE runs across: 1 = a column (stepped by
# a1), 0 = a row (stepped by a2). `kind.shape[axis]` is therefore the number of such lines.
_AXIS_LINE = {1: "column", 0: "row"}      # the same axis, named as a user reads a refusal

#: A predicted centre is good to about a pixel — the lattice vectors are MEANS over an array
#: whose pitch drifts ~2 % with focus — so the evidence sampler takes the best `corr` in a 3x3
#: window. Wider would start harvesting noise maxima and lend a phantom line a score it has
#: not earned; narrower would punish a real line for a half-pixel of extrapolation.
_EV_RAD = 1

#: How much like electrodes the strip just OUTSIDE the array may look before the numbering is
#: not to be trusted, as a fraction of the outermost line inside it.
#:
#: ⚠️ MEASURED, and the margin is genuinely narrow — do not "tidy" this number:
#:   0.15  synthetic background beyond a clean planted array   (must pass)
#:   0.63  worst of the four edges on his REAL 120 x 220 video mosaic, whose fit is known
#:         correct — the chip's own border structure sits right outside the pads and scores  (must pass)
#:   0.79  a genuinely SHIFTED map: a real but dim electrode line sitting outside the
#:         numbering, which is the whole failure this check exists to catch        (must refuse)
#: 0.70 is the only value between the last two. Raising it lets a shifted map through; lowering
#: it refuses his real mosaic, which is the geometry "whole chip imaged" actually means.
_BORDER_FRAC = 0.70


def _fmt_score(v: float) -> str:
    """A score in a refusal message. NaN is not a small number, it is NO EVIDENCE (the
    candidate line falls outside the image or outside the coverage), and the message has to
    say that rather than print a misleading `nan`."""
    return f"{v:.2f}" if math.isfinite(v) else "none"


def _corr_median(corr: np.ndarray, valid: np.ndarray, pts: np.ndarray) -> float:
    """Median matched-filter response at the places a line's pads WOULD be.

    This is the ONLY honest evidence about a line the fit did not index: such a line has no
    detections BY DEFINITION, so counting detections says nothing about whether it exists —
    reading `corr` where its pads would be says everything. `corr` is TM_CCOEFF_NORMED, so it
    is a shape match independent of brightness: a real but DIM edge column (too faint for the
    array mask, which is an energy threshold) still answers loudly here.

    Centres outside the image or outside the coverage mask are not counted; fewer than three
    countable centres returns NaN, and NaN means "no evidence", which every gate below treats
    as a failure. A line nobody can see is never added and never dropped — it is refused."""
    H, W = corr.shape
    vals = []
    for x, y in pts:
        if not (math.isfinite(float(x)) and math.isfinite(float(y))):
            continue
        ix, iy = int(round(float(x))), int(round(float(y)))
        if not (_EV_RAD <= ix < W - _EV_RAD and _EV_RAD <= iy < H - _EV_RAD):
            continue
        if not valid[iy, ix]:
            continue
        vals.append(float(corr[iy - _EV_RAD:iy + _EV_RAD + 1,
                               ix - _EV_RAD:ix + _EV_RAD + 1].max()))
    if len(vals) < 3:
        return float("nan")
    return float(np.median(vals))


def _edge_line_points(gm: GridMap, axis: int, low: bool) -> tuple[np.ndarray, np.ndarray]:
    """(centres of the outermost EXISTING line at this end, predicted centres one step beyond).

    The prediction steps off the ADJACENT existing line with the mean lattice vector, cell by
    cell — never off a distant anchor. The first array is the reference the second is judged
    against: same surface, same sampler, same cells' worth of it, so the comparison measures
    the pixels and not the sampling."""
    step = np.asarray(gm.a1 if axis == 1 else gm.a2, np.float64)
    C = np.moveaxis(gm.centers, axis, 0).astype(np.float64)   # (nlines, ncross, 2)
    K = np.moveaxis(gm.kind, axis, 0)                          # (nlines, ncross)
    line = 0 if low else K.shape[0] - 1
    here = C[line][K[line] != GridMap.KIND_ABSENT]
    beyond = here + (-step if low else step)
    return here, beyond


def _shape_refusal(gm: GridMap, want_cols: int, want_rows: int, because: str = "") -> str:
    """The one refusal wording. It names WHAT WAS FOUND, WHAT WAS DECLARED, and the way out that
    is honest — his own: say only part of the chip is in frame."""
    return (f"the whole array was declared imaged, but the fit found {gm.cols} x {gm.rows}, "
            f"not {want_cols} x {want_rows}{because} — if this mosaic shows only part of the "
            f"chip, choose 'partially imaged'")


def _enforce_device_shape(gm: GridMap, device: DeviceSpec) -> None:
    """He said the WHOLE chip is in frame, so the fit must BE the device's shape — *"if the user
    select full imaging then I want the rules to be strictly enforced"* (2026-08-11).

    Exact (in either orientation — the chip can sit portrait or landscape) -> accepted.
    Anything else -> refused, naming both shapes.

    ⛔ **THERE IS NO REPAIR PATH, AND THAT IS THE FEATURE.** Two were built and both were caught
    shifting every id by a constant while reporting the right shape. The first chose which edge
    to add or drop by counting detected pads; but `_assemble`'s edge trim can drop a weak line at
    BOTH ends, and the count rule then put them both back on ONE side — 264/264 ids wrong. The
    second asked the PIXELS which end was missing, answered correctly, and was still wrong,
    because nothing re-examined the lines the fit had already accepted. Every repair is a guess
    about registration dressed as arithmetic about cardinality, and a guess that goes the wrong
    way renumbers the whole array silently. Refusing costs the user one click (say "part of the
    chip", or re-image); a shifted map costs him every conclusion he draws from it."""
    A, B = sorted((int(gm.cols), int(gm.rows)))
    a, b = sorted(int(v) for v in device.axes)
    want_cols, want_rows = (a, b) if gm.cols <= gm.rows else (b, a)
    if (A, B) != (a, b):
        raise NoGridFound(_shape_refusal(gm, want_cols, want_rows))


def _assert_registered(gm: GridMap, corr: np.ndarray, valid: np.ndarray, cfg: GridConfig) -> None:
    """The right 26,400 positions — not 26,400 positions one line to the left.

    ⭐ **CARDINALITY IS NOT REGISTRATION.** Counting lines cannot tell those apart, and the case
    that exploits it is real: one true edge column too DIM for the array mask (an energy
    threshold) is missed, while the chip's bright border bar one step past the OTHER edge is
    indexed as a column. The two errors cancel, the shape check sees an exact 220 x 120, and
    every id is off by one. So the exit also asks the pixels a question a shifted map cannot
    answer: **is the array's edge where the numbering says it is?**

    For each of the four ends: sample the matched filter where the NEXT line's pads would be. It
    must not look like electrodes compared with the outermost line inside the array. NaN outside
    (off the image, or off the coverage — a mosaic cut flush at the chip) is not evidence of
    anything and passes: this check refuses a map that has array beyond its own border, never one
    that simply ends where the picture does.

    It can only REFUSE. It never moves a line, never renumbers, never repairs — the one thing
    every previous attempt at strictness got wrong."""
    for axis in (1, 0):
        for low in (True, False):
            inside, outside = _edge_line_points(gm, axis, low)
            s_in = _corr_median(corr, valid, inside)
            s_out = _corr_median(corr, valid, outside)
            if not (math.isfinite(s_in) and math.isfinite(s_out)):
                continue                      # nothing to see beyond the picture: not a failure
            if s_out >= _BORDER_FRAC * s_in and s_out >= cfg.corr_min:
                end = "before" if low else "after"
                raise NoGridFound(
                    f"'whole chip imaged' was declared and the fit is the right shape "
                    f"({gm.cols} x {gm.rows}), but the pixels {end} the array's edge still look "
                    f"like electrodes ({_fmt_score(s_out)} against {_fmt_score(s_in)} on "
                    f"{_AXIS_LINE[axis]} {'1' if low else str(gm.cols if axis == 1 else gm.rows)}) "
                    f"— the numbering may be shifted by a {_AXIS_LINE[axis]}, so it is refused "
                    f"rather than returned. If this mosaic shows only part of the chip, choose "
                    f"'partially imaged'")


def _fill_every_position(gm: GridMap) -> None:
    """FULL mode only: number every position the chip HAS.

    He declared the whole chip in frame, and the chip carries an electrode at EVERY one of its
    positions — so a "full" map that quietly omits the corners the mosaic clipped is a map of
    something else. Absent cells take an interpolated centre flagged INFERRED, growing outward
    from assigned neighbours a ring at a time (Jacobi: a whole pass reads the previous pass, so
    the result does not depend on iteration order). `_relax_grid_inferred` then settles them.

    ⚠️ PARTIAL mode never runs this: there, "we did not see it and the device shape does not
    apply" is the honest answer, and absent stays absent."""
    a1 = np.asarray(gm.a1, np.float64)
    a2 = np.asarray(gm.a2, np.float64)
    rows, cols = gm.kind.shape
    C = gm.centers.astype(np.float64)
    K = gm.kind
    # every assigned neighbour votes, each stepping to this cell with the vector that separates
    # them. The four diagonals are in because a corner the mosaic clipped can have no axis
    # neighbour at all on the pass that first reaches it.
    nbrs = ((0, -1, a1), (0, 1, -a1), (-1, 0, a2), (1, 0, -a2),
            (-1, -1, a1 + a2), (-1, 1, -a1 + a2), (1, -1, a1 - a2), (1, 1, -a1 - a2))
    for _ in range(rows + cols + 2):          # each pass grows the filled region by one ring
        absent = np.argwhere(K == GridMap.KIND_ABSENT)
        if absent.size == 0:
            break
        new = {}
        for r, c in absent:
            preds = [C[r + dr, c + dc] + v for dr, dc, v in nbrs
                     if 0 <= r + dr < rows and 0 <= c + dc < cols and K[r + dr, c + dc]]
            if preds:
                new[(int(r), int(c))] = np.mean(preds, axis=0)
        if not new:
            break
        for (r, c), p in new.items():
            C[r, c] = p
            K[r, c] = GridMap.KIND_INFERRED
    gm.centers = C.astype(np.float32)
    if (K == GridMap.KIND_ABSENT).any():
        # only reachable if the grid has no assigned cell at all, which `_assemble`'s
        # `min_detected` already refuses — but "full" must never return a hole
        raise NoGridFound("the whole array was declared imaged, but positions remain that no "
                          "neighbour can place — if this mosaic shows only part of the chip, "
                          "choose 'partially imaged'")


def _relax_grid_inferred(gm: GridMap) -> None:
    """Re-run the growth-time Jacobi relaxation over the FINISHED grid.

    `_fill_every_position` interpolates outward ring by ring, so the cells it adds hold
    placeholder centres that lean on whichever neighbours the ring reached first — not a
    consensus. This is the SAME relaxation `_grow` uses (deliberately the same function, so the
    two cannot drift apart): detected cells stay pinned, every inferred centre becomes the
    average of what all eight of its neighbours predict for it."""
    rows, cols = gm.kind.shape
    a1, a2 = gm.a1, gm.a2
    # `_relax_inferred` speaks the growth record: [x, y, prio, kind, v1x, v1y, v2x, v2y] keyed
    # (column index, row index). Per-cell lattice vectors were averaged away by `_assemble`, so
    # every cell votes with the mean pair — which is what the finished map is expressed in.
    cells: dict[tuple[int, int], list[float]] = {}
    for r in range(rows):
        for c in range(cols):
            k = int(gm.kind[r, c])
            if k:
                x, y = gm.centers[r, c]
                cells[(c, r)] = [float(x), float(y), 0.0, k,
                                 a1[0], a1[1], a2[0], a2[1]]
    _relax_inferred(cells, GridMap.KIND_INFERRED)
    for (c, r), rec in cells.items():
        gm.centers[r, c] = (rec[0], rec[1])


def _refresh_stats(gm: GridMap) -> None:
    """Re-derive every count and residual from the FINAL grid.

    A correction adds, drops and re-numbers cells; stats carried over from before it describe a
    map nobody has. `mean_confidence` is re-averaged from the per-cell `conf` plane (which the
    line edits carry in lockstep) rather than from the pre-correction mean, and the residuals go
    back through `_step_residuals` — the same function `_assemble` used, so the two numbers are
    the same measurement of two different grids and not two measurements."""
    K = gm.kind
    n_det = int((K == GridMap.KIND_DETECTED).sum())
    n_inf = int((K == GridMap.KIND_INFERRED).sum())
    gm.stats["n_detected"] = n_det
    gm.stats["n_inferred"] = n_inf
    gm.stats["detected_frac"] = round(n_det / max(1, n_det + n_inf), 4)
    if gm.conf is not None:
        c = gm.conf[K == GridMap.KIND_DETECTED]
        c = c[np.isfinite(c)]
        gm.stats["mean_confidence"] = round(float(np.mean(c)), 4) if c.size else 0.0
    res = _step_residuals(gm.centers, K, np.asarray(gm.a1, np.float64),
                          np.asarray(gm.a2, np.float64))
    gm.stats["step_residual_median_px"] = round(float(np.median(res)), 3)
    gm.stats["step_residual_p95_px"] = round(float(np.percentile(res, 95)), 3)


def _assert_full_shape(gm: GridMap, device: DeviceSpec) -> None:
    """⭐ THE POSTCONDITION. *"if the user select full imaging then I want the rules to be
    strictly enforced"* — so "full" ends in EXACTLY ONE of two states: the declared device's
    shape with every one of its positions numbered, or a refusal that says what it found.

    ONE gate, at the exit of `fit_grid`, and deliberately not an invariant spread across the
    helpers: a helper each of whose steps is locally right can still compose into a wrong map,
    and only a check on the thing actually being RETURNED can rule that out. It is a
    belt-and-braces assertion by design — if it ever fires, a path above it is wrong, and
    refusing is the only answer that cannot hand back ids that are quietly off."""
    want = tuple(sorted(int(v) for v in device.axes))
    got = tuple(sorted((int(gm.cols), int(gm.rows))))
    n = int((gm.kind != GridMap.KIND_ABSENT).sum())
    if got == want and n == device.electrodes and gm.kind.shape == (gm.rows, gm.cols):
        return
    # named in the orientation the fit came out in, the same convention the enforcement uses,
    # so he is not left comparing "12 x 22" against "22 x 12" and wondering which is which
    wc, wr = want if gm.cols <= gm.rows else (want[1], want[0])
    raise NoGridFound(
        f"'whole chip imaged' was declared, but the finished map is {gm.cols} x {gm.rows} with "
        f"{n} numbered electrodes, not {wc} x {wr} with {device.electrodes} — refusing rather "
        f"than returning ids that may be wrong; if this mosaic shows only part of the chip, "
        f"choose 'partially imaged'")


def _apply_um_frame(gm: GridMap, device: DeviceSpec) -> None:
    """The 17.5 um rule — the half that applies in BOTH coverage modes.

    `um_per_px` is MEASURED: a known physical pitch over the pixel pitch this image actually
    shows. Per-cell coordinates are expressed in the ARRAY's own frame — origin at the
    LEAST-SQUARES lattice position of electrode 1-1 (not cell 1-1's own centre, which may be
    absent, inferred, or carrying local drift), axes THE LATTICE'S OWN — so rotation is taken
    out and x_um grows along columns, y_um along rows. The numbers land near
    (col-1)*pitch_um / (row-1)*pitch_um but carry the real deviation: they are the measured
    positions converted, not the ideal lattice redrawn.

    ⚠️ THE DUAL BASIS, NOT A PROJECTION. It is tempting to write x_um = (d . a1_hat) * um_per_px
    — and that is exact only when a1 is perpendicular to a2. `_lattice_vectors` accepts pairs up
    to ~12 deg off orthogonal (real lattices are not perfectly square, and neither is the FFT's
    read of them), and at row 220 a 12 deg shear misplaces x_um by ~770 um — 44 whole electrodes
    — while every number still looks plausible. So solve [a1 a2] @ (u, v) = d for the LATTICE
    coordinates and scale those: exact for any basis, and identical to the projection on a
    square one."""
    gm.device = device
    gm.um_per_px = float(device.pitch_um) / float(gm.pitch)

    a1 = np.asarray(gm.a1, np.float64)
    a2 = np.asarray(gm.a2, np.float64)
    det = float(a1[0] * a2[1] - a1[1] * a2[0])
    if abs(det) < 1e-9:
        raise NoGridFound("the two lattice vectors are parallel — no array frame exists")
    # inverse of [a1 a2] (columns), i.e. pixels -> lattice coordinates
    inv = np.array([[a2[1], -a2[0]], [-a1[1], a1[0]]], np.float64) / det

    rows, cols = gm.kind.shape
    cc, rr = np.meshgrid(np.arange(cols, dtype=np.float64),
                         np.arange(rows, dtype=np.float64))
    ctr = gm.centers.astype(np.float64)

    # with the lattice vectors fixed, the LS origin is just the mean of every existing cell
    # stepped back to (1, 1)
    have = gm.kind != GridMap.KIND_ABSENT
    back = ctr - cc[..., None] * a1 - rr[..., None] * a2
    origin = back[have].mean(axis=0)

    d = ctr - origin                       # NaN at absent cells, and NaN it stays
    uv = d @ inv.T                         # (u, v): how many lattice steps out from 1-1
    gm.um = (uv * float(device.pitch_um)).astype(np.float32)
    gm.stats["um_per_px"] = round(gm.um_per_px, 6)
