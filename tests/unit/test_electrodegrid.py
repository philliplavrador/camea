"""core.electrodegrid — the electrode-lattice fitter against synthetic grids with a
known answer key.

The generator plants pads at exactly known centres, so every assertion here is against
ground truth, not against the algorithm's own output. The nasty cases are the ones his
spec called out: rotation (the real grid sits at ~-2.2 deg), occluding cells (pads
hidden but still numbered), a 2 % pitch gradient (the measured focus drift that makes a
rigid global fit shear by whole cells), and a bright border ring that must never be
indexed as an extra electrode row.

The last section covers R45.8 — the device spec and the two coverage modes, and the STRICT
reading of "full" his 2026-08-11 ruling demands: *"if the user select full imaging then I
want the rules to be strictly enforced"*. It uses a DELIBERATELY TINY `DeviceSpec` (12 x 22)
so the enforcement logic is exercised in milliseconds; the real `MAXWELL` (220 x 120) is the
app's default and appears here only where its actual numbers are the point.

⭐ The adversarial theme of that section is A WRONG ID, not a crash: every test there tries to
sneak a shape or a numbering past the enforcement that LOOKS fine and is off by a constant.
"""

from __future__ import annotations

import csv
import json
import math

import numpy as np
import pytest

from camea.core.electrodegrid import (MAXWELL, DeviceSpec, GridMap, NoGridFound, fit_grid,
                                      write_map_files)


# =============================================================================
# Synthetic lattice with a known answer key
# =============================================================================
def lattice_image(cols=24, rows=16, pitch=14.0, angle_deg=0.0, *, pad_amp=60.0,
                  noise=2.0, gradient=0.0, n_occluders=0, missing=(), margin=48,
                  border_ring=False, seed=0, faint=(), faint_amp=0.22, shear_deg=0.0):
    """Render a synthetic electrode array; return (image, truth, meta).

    truth maps 1-based (col, row) -> exact pad centre (x, y). `gradient` stretches the
    column step linearly across the array (step_i = pitch * (1 + gradient * i/(cols-1))),
    mimicking the measured focus-driven pitch drift. `missing` pads are simply absent
    (dead electrode); occluders REPLACE the pads under a bright blob (a cell sitting on
    the array).

    `faint` pads are rendered at `faint_amp` of full brightness. ⭐ That is how a REAL line
    goes missing from a fit while staying plainly present in the pixels: the array mask is a
    Gabor ENERGY threshold, so a dim edge column falls out of it and is never indexed — while
    the matched filter is TM_CCOEFF_NORMED, a shape match independent of brightness, which
    still answers ~0.97 there. Exactly the split the evidence rule is built to read.

    ⚠️ **WHERE the dim cells sit decides the outcome, and both outcomes are ruled.** A dim
    PATCH is recovered (`_claim_dim_pads`, R45.9): it lies inside the fit's bounding box, so
    numbering it cannot move an array edge. A dim EDGE LINE is still dropped, and under "whole
    chip imaged" still refuses (R45.8): it lies OUTSIDE the box, so putting it back would be a
    claim about where the array starts — the repair rule that was twice caught shifting every
    id. Fixtures below rely on each half, so `faint` is not a single behaviour.

    `shear_deg` tilts the row axis off perpendicular (0 = square). `_lattice_vectors` accepts
    pairs up to ~12 deg off orthogonal, and on such a lattice projecting onto a1_hat is NOT
    the array frame — the dual basis is.
    """
    rng = np.random.default_rng(seed)

    # unrotated lattice coordinates (cumulative steps so a gradient stays a lattice)
    u = np.zeros(cols)
    for i in range(1, cols):
        u[i] = u[i - 1] + pitch * (1.0 + gradient * (i - 1) / max(1, cols - 1))
    v = np.arange(rows) * pitch

    sh = math.radians(shear_deg)
    e1 = np.array([1.0, 0.0])
    e2 = np.array([math.sin(sh), math.cos(sh)])          # perpendicular only at shear 0
    th = math.radians(angle_deg)
    R = np.array([[math.cos(th), -math.sin(th)], [math.sin(th), math.cos(th)]])
    pts = np.array([ui * e1 + vj * e2 for vj in v for ui in u])  # row-major
    pts = pts @ R.T
    off = margin - pts.min(0)
    pts += off

    W = int(math.ceil(pts[:, 0].max() + margin))
    H = int(math.ceil(pts[:, 1].max() + margin))
    img = np.full((H, W), 50.0, np.float32) + rng.normal(0, noise, (H, W)).astype(np.float32)

    truth = {}
    pads = np.zeros((H, W), np.float32)
    sig = 0.2 * pitch
    k = int(round(2.5 * sig)) * 2 + 1
    c = np.arange(k) - k // 2
    gx, gy = np.meshgrid(c, c)
    for n, (x, y) in enumerate(pts):
        col = n % cols + 1
        row = n // cols + 1
        truth[(col, row)] = (float(x), float(y))
        if (col, row) in missing:
            continue
        amp = pad_amp * faint_amp if (col, row) in faint else pad_amp
        ix, iy = int(round(x)), int(round(y))
        fx, fy = x - ix, y - iy
        blob = amp * np.exp(-((gx - fx) ** 2 + (gy - fy) ** 2) / (2 * sig ** 2))
        y0, y1 = iy - k // 2, iy + k // 2 + 1
        x0, x1 = ix - k // 2, ix + k // 2 + 1
        if 0 <= y0 and y1 <= H and 0 <= x0 and x1 <= W:
            pads[y0:y1, x0:x1] += blob

    occluded = np.zeros((H, W), np.float32)
    if n_occluders:
        yy, xx = np.mgrid[0:H, 0:W]
        lo = pts.min(0) + 4 * pitch
        hi = pts.max(0) - 4 * pitch
        for _ in range(n_occluders):
            ox = rng.uniform(lo[0], hi[0])
            oy = rng.uniform(lo[1], hi[1])
            r = rng.uniform(1.5, 2.5) * pitch
            d2 = (xx - ox) ** 2 + (yy - oy) ** 2
            soft = np.exp(-d2 / (2 * r ** 2)).astype(np.float32)
            pads *= 1.0 - np.clip(soft * 1.6, 0, 1)      # the cell hides the pads...
            occluded += 160.0 * soft                      # ...and glows on top

    img += pads + occluded

    if border_ring:
        x0, y0 = (pts.min(0) - 1.4 * pitch).astype(int)
        x1, y1 = (pts.max(0) + 1.4 * pitch).astype(int)
        for t in range(3):
            img[y0 + t, x0:x1] = 220.0
            img[y1 - t, x0:x1] = 220.0
            img[y0:y1, x0 + t] = 220.0
            img[y0:y1, x1 - t] = 220.0

    return img, truth, {"pitch": pitch, "angle": angle_deg}


def assert_every_truth_resolves(gm, truth, *, center_tol_frac=0.35):
    """Every planted position must look up to its own (col, row) — the whole feature."""
    bad = []
    for (col, row), (x, y) in truth.items():
        hit = gm.lookup(x, y)
        if hit is None or hit["col"] != col or hit["row"] != row:
            bad.append(((col, row), hit and (hit["col"], hit["row"])))
        elif hit["distance"] > center_tol_frac * gm.pitch:
            bad.append(((col, row), f"centre off by {hit['distance']:.2f}px"))
    assert not bad, f"{len(bad)}/{len(truth)} positions mis-resolved; first: {bad[:5]}"


# =============================================================================
# The core promises
# =============================================================================
def test_clean_grid_indexes_every_pad_exactly():
    img, truth, _ = lattice_image(cols=24, rows=16, pitch=14.0)
    gm = fit_grid(img)
    assert (gm.cols, gm.rows) == (24, 16)
    assert_every_truth_resolves(gm, truth, center_tol_frac=0.2)
    assert gm.stats["n_detected"] >= 0.95 * len(truth)


@pytest.mark.parametrize("angle", [3.0, -3.0, -2.2])
def test_rotated_grid_numbers_along_the_lattice_not_the_image(angle):
    img, truth, _ = lattice_image(cols=24, rows=16, pitch=14.0, angle_deg=angle)
    gm = fit_grid(img)
    assert (gm.cols, gm.rows) == (24, 16)
    assert abs(gm.angle_deg - angle) < 0.6
    assert_every_truth_resolves(gm, truth, center_tol_frac=0.25)


def test_top_left_is_1_1_and_axes_point_right_and_down():
    img, truth, _ = lattice_image(cols=10, rows=8, pitch=14.0, angle_deg=-2.0)
    gm = fit_grid(img)
    hit = gm.lookup(*truth[(1, 1)])
    assert (hit["col"], hit["row"]) == (1, 1)
    hit = gm.lookup(*truth[(2, 1)])
    assert (hit["col"], hit["row"]) == (2, 1)
    hit = gm.lookup(*truth[(1, 2)])
    assert (hit["col"], hit["row"]) == (1, 2)
    hit = gm.lookup(*truth[(10, 8)])
    assert (hit["col"], hit["row"]) == (10, 8)
    assert gm.a1[0] > 0 and gm.a2[1] > 0


def test_occluded_pads_are_inferred_but_correctly_numbered():
    img, truth, _ = lattice_image(cols=26, rows=18, pitch=14.0, angle_deg=-2.2,
                                  n_occluders=5, seed=3)
    gm = fit_grid(img)
    assert (gm.cols, gm.rows) == (26, 18)
    assert_every_truth_resolves(gm, truth)
    assert gm.stats["n_inferred"] > 0, "occluders should force some inferred cells"


def test_two_percent_pitch_gradient_does_not_shear_the_numbering():
    """The rigid-fit killer: 200 columns with the measured ~2 % focus drift accumulate
    ~2 whole pitches of phase error — region growing must stay exact anyway."""
    img, truth, _ = lattice_image(cols=200, rows=10, pitch=13.8, gradient=0.02,
                                  angle_deg=-1.0, seed=1)
    gm = fit_grid(img)
    assert (gm.cols, gm.rows) == (200, 10)
    assert_every_truth_resolves(gm, truth)


def test_dead_electrodes_keep_their_number():
    missing = {(5, 5), (13, 2), (13, 3), (20, 11), (7, 9)}
    img, truth, _ = lattice_image(cols=24, rows=12, pitch=14.0, missing=missing, seed=2)
    gm = fit_grid(img)
    assert_every_truth_resolves(gm, truth)
    for col, row in missing:
        hit = gm.lookup(*truth[(col, row)])
        assert hit["kind"] == "inferred", f"{col}-{row} should be inferred"


def test_border_ring_is_never_an_extra_electrode_row():
    img, truth, _ = lattice_image(cols=20, rows=14, pitch=14.0, angle_deg=-2.0,
                                  border_ring=True)
    gm = fit_grid(img)
    assert (gm.cols, gm.rows) == (20, 14)
    assert_every_truth_resolves(gm, truth, center_tol_frac=0.25)


def test_a_dim_corner_is_still_the_array():
    """⭐ **A DIM PATCH OF THE ARRAY IS STILL THE ARRAY** (his report, 2026-08-11: *"electrodes
    are missing for this mosaic in the bottom left corner"*).

    A survey mosaic is not evenly lit — illumination drifts across a 4-minute sweep, and the
    corner reached last can come out several times dimmer than the middle while showing exactly
    the same pads. The array mask is a Gabor ENERGY threshold set from a percentile of the WHOLE
    image, and energy goes as amplitude SQUARED: on his real 5319x7356 video mosaic the
    bottom-left corner ran 3.9x down in high-pass amplitude, so ~8x down in energy, and fell
    under a bar the bright majority had set. 120 positions went unnumbered — while the matched
    filter, which is normalised and therefore blind to brightness, read **0.64** there, *higher*
    than at the indexed cells around it. The pads were never in doubt; only the mask was.

    ⛔ The mask is NOT what was changed, and `_claim_dim_pads` explains at length why: every
    brightness-invariant statistic that recovers this corner also drags the mask's outer boundary
    a lattice step outward, onto the pads' own filter bleed, which is a phantom edge line and a
    shift of every id. The boundary stays put and the INTERIOR is revisited instead.

    This plants the failure: a corner block at 22 % amplitude — the ratio measured on his mosaic
    — surrounded by array on two sides. Those pads are visible to any brightness-invariant test,
    so they must be numbered, and numbered as DETECTED: they were measured, not guessed. An
    `inferred` centre here would mean the fitter fell back on arithmetic where it had pixels to
    read. (Headroom, measured: full recovery holds down to 0.10 amplitude; past that it degrades
    to fewer detections and never to a wrong id.)
    """
    dim = {(c, r) for c in range(1, 9) for r in range(16, 21)}
    img, truth, _ = lattice_image(cols=24, rows=20, pitch=14.0, angle_deg=-2.0,
                                  faint=dim, seed=5)
    gm = fit_grid(img)

    assert (gm.cols, gm.rows) == (24, 20), "the dim corner must not shrink the array"
    assert_every_truth_resolves(gm, truth)

    got = [(c, r) for c, r in dim if gm.kind[r - 1, c - 1] == GridMap.KIND_DETECTED]
    assert len(got) >= 0.9 * len(dim), (
        f"only {len(got)}/{len(dim)} dim corner pads were DETECTED — the rest were inferred or "
        f"absent, i.e. the mask still reads brightness where it means to read lattice content")


# =============================================================================
# The click rule
# =============================================================================
def test_clicks_between_pads_select_nothing():
    img, truth, _ = lattice_image(cols=16, rows=12, pitch=14.0)
    gm = fit_grid(img)
    (x, y) = truth[(6, 6)]
    a1 = np.array(gm.a1)
    near = np.array([x, y]) + 0.2 * a1
    assert gm.lookup(*near)["electrode"] == "6-6", "a near-miss inside the pad margin selects"
    mid = np.array([x, y]) + 0.5 * a1
    assert gm.lookup(*mid) is None, "the midpoint between two pads selects nothing"
    diag = np.array([x, y]) + 0.5 * a1 + 0.5 * np.array(gm.a2)
    assert gm.lookup(*diag) is None, "the four-corner point selects nothing"


def test_clicks_outside_the_array_select_nothing():
    img, truth, _ = lattice_image(cols=16, rows=12, pitch=14.0, margin=60)
    gm = fit_grid(img)
    assert gm.lookup(3.0, 3.0) is None
    assert gm.lookup(img.shape[1] - 3.0, img.shape[0] - 3.0) is None


def test_arrow_step_neighbours_are_one_lattice_vector_apart():
    """The UI's arrow keys move col/row +-1; those cells must sit one lattice step away."""
    img, truth, _ = lattice_image(cols=16, rows=12, pitch=14.0, angle_deg=-2.2)
    gm = fit_grid(img)
    c66 = gm.centers[5, 5]
    c76 = gm.centers[5, 6]
    c67 = gm.centers[6, 5]
    assert np.hypot(*(c76 - c66 - np.array(gm.a1))) < 0.2 * gm.pitch
    assert np.hypot(*(c67 - c66 - np.array(gm.a2))) < 0.2 * gm.pitch


# =============================================================================
# Refusals and plumbing
# =============================================================================
def test_a_gridless_image_refuses_cleanly():
    rng = np.random.default_rng(0)
    img = np.full((512, 512), 50.0, np.float32) + rng.normal(0, 3, (512, 512)).astype(np.float32)
    yy, xx = np.mgrid[0:512, 0:512]
    for _ in range(30):
        ox, oy, r = rng.uniform(40, 472), rng.uniform(40, 472), rng.uniform(8, 40)
        img += 120.0 * np.exp(-((xx - ox) ** 2 + (yy - oy) ** 2) / (2 * r ** 2)).astype(np.float32)
    with pytest.raises(NoGridFound):
        fit_grid(img)


def test_the_valid_mask_confines_the_fit():
    img, truth, _ = lattice_image(cols=20, rows=14, pitch=14.0)
    valid = np.zeros(img.shape, bool)
    valid[:, : img.shape[1] // 2] = True     # right half "uncovered"
    gm = fit_grid(img, valid=valid)
    assert gm.cols < 20, "cells in the masked-out half must not be indexed as detected"
    for (col, row), (x, y) in truth.items():
        if x < img.shape[1] // 2 - 2 * 14.0 and col <= gm.cols and row <= gm.rows:
            hit = gm.lookup(x, y)
            assert hit is not None and (hit["col"], hit["row"]) == (col, row)


def test_payload_is_flat_json_safe_and_1_based():
    img, _, _ = lattice_image(cols=12, rows=9, pitch=14.0)
    p = fit_grid(img).payload()
    n = len(p["cells"]["col"])
    assert n == len(p["cells"]["row"]) == len(p["cells"]["x"]) == len(p["cells"]["kind"])
    assert min(p["cells"]["col"]) == 1 and min(p["cells"]["row"]) == 1
    assert max(p["cells"]["col"]) == p["cols"] and max(p["cells"]["row"]) == p["rows"]
    assert set(p["cells"]["kind"]) <= {1, 2}
    json.dumps(p)


# =============================================================================
# The device, and whether it is all in frame (R45.8)
# =============================================================================
#: A tiny stand-in for the real chip. ⚠️ Every enforcement case below has to run the whole
#: fitter, so a 220 x 120 fixture would cost minutes; the LOGIC is shape-agnostic, and the
#: real numbers are guarded separately against MAXWELL.
TEST_DEVICE = DeviceSpec(name="test device", axes=(12, 22), pitch_um=17.5)


def faint_col(col, rows=22):
    """A whole column, dim. ⭐ `faint` keeps the pads in the PIXELS while dropping them out of
    the energy-thresholded array mask — a real edge line the fit never indexes, which is the
    only honest fixture for "put the missing line back".

    ⚠️ A WHOLE line, and at an EDGE, on purpose. R45.9's recovery pass deliberately cannot reach
    it: the line falls outside the fit's bounding box, which is exactly what keeps that pass from
    being able to move an array edge. Dim a *patch* instead and it is recovered — see
    `test_a_dim_corner_is_still_the_array`. Shorten these fixtures to a partial line and they
    stop testing R45.8's refusal, because the fit would then find the column."""
    return {(col, r) for r in range(1, rows + 1)}


def faint_row(row, cols=12):
    return {(c, row) for c in range(1, cols + 1)}


def assert_is_the_whole_device(gm, device=TEST_DEVICE):
    """⭐ THE POSTCONDITION, asserted from the outside on every full-coverage result.

    *"if the user select full imaging then I want the rules to be strictly enforced"* — so a
    returned map is the declared device's shape with EVERY one of its positions numbered.
    There is no third state; the only other outcome allowed anywhere below is NoGridFound."""
    assert sorted((gm.cols, gm.rows)) == sorted(device.axes), (gm.cols, gm.rows)
    assert gm.kind.shape == (gm.rows, gm.cols)
    assert int((gm.kind != GridMap.KIND_ABSENT).sum()) == device.electrodes
    assert not np.isnan(gm.centers).any(), "a numbered position with no centre is not numbered"
    assert gm.array_coverage == "full"
    assert gm.stats["n_detected"] + gm.stats["n_inferred"] == device.electrodes


def test_the_device_spec_is_the_only_place_the_device_numbers_live():
    """*"the standard MaxOne/MaxTwo sensor area is 26,400 electrodes = 220 x 120, with
    17.5 um pitch"* — orientation-free, and the count is DERIVED so the two halves of his
    sentence can never drift apart."""
    assert sorted(MAXWELL.axes) == [120, 220]
    assert MAXWELL.pitch_um == 17.5
    assert MAXWELL.electrodes == 26_400
    assert MAXWELL.as_dict() == {"name": MAXWELL.name, "axes": [120, 220],
                                 "pitch_um": 17.5, "electrodes": 26_400}
    assert DeviceSpec(axes=(4, 5)).electrodes == 20


def test_enforcing_a_shape_with_no_device_is_a_programming_error():
    """⛔ Not a refusal — a ValueError. "Whole chip imaged" is a claim ABOUT a DeviceSpec;
    without one the map would be labelled "full" while nothing whatsoever was enforced, which
    is the one state his "strictly enforced" forbids most: it CLAIMS the chip and was never
    checked against it. A caller that reaches here has a bug, and dressing that bug up as a
    friendly refusal ships it to him."""
    img, _, _ = lattice_image(cols=12, rows=22, pitch=14.0)
    with pytest.raises(ValueError) as excinfo:
        fit_grid(img, device=None, enforce_shape=True)
    assert not isinstance(excinfo.value, NoGridFound), "a bug, not a thing the user did"
    assert "device" in str(excinfo.value)


# -----------------------------------------------------------------------------
# STRICT full coverage: the exact shape, every position, or a refusal
# -----------------------------------------------------------------------------
def test_full_coverage_leaves_an_exact_device_shape_untouched():
    img, truth, _ = lattice_image(cols=12, rows=22, pitch=14.0, angle_deg=-2.0, seed=7)
    gm = fit_grid(img, device=TEST_DEVICE, enforce_shape=True)
    assert (gm.cols, gm.rows) == (12, 22)
    assert "shape_corrected" not in gm.stats, "a fit that already matches is not 'corrected'"
    assert gm.payload()["array_coverage"] == "full"
    assert_is_the_whole_device(gm)
    assert_every_truth_resolves(gm, truth, center_tol_frac=0.25)


@pytest.mark.parametrize("name,kw", [
    ("occluders", dict(n_occluders=4, seed=3)),
    ("dead lines", dict(missing={(6, r) for r in range(1, 23)}
                                | {(c, 11) for c in range(1, 13)}, seed=2)),
    ("rotation", dict(angle_deg=-3.0, seed=4)),
    ("pitch gradient", dict(gradient=0.02, angle_deg=-1.0, seed=1)),
    ("all at once", dict(n_occluders=3, angle_deg=-2.2, gradient=0.02,
                         missing={(4, r) for r in range(1, 23)}, seed=11)),
])
def test_full_coverage_always_exits_as_the_whole_device(name, kw):
    """⭐ EVERY position numbered, whatever the image does to the pads. The chip HAS an
    electrode at all of its positions, so a "full" map that quietly omits the corner a mosaic
    clipped, or the column a cell sat on, is a map of something else. Occluders, a dead row AND
    a dead column, rotation and the measured 2 % focus drift all come out the same shape."""
    img, truth, _ = lattice_image(cols=12, rows=22, pitch=14.0, **kw)
    gm = fit_grid(img, device=TEST_DEVICE, enforce_shape=True)
    assert_is_the_whole_device(gm)
    assert_every_truth_resolves(gm, truth)


@pytest.mark.parametrize("name,kw,raw", [
    ("a dim LOW edge column",  dict(faint=faint_col(1)),   "11 x 22"),
    ("a dim HIGH edge column", dict(faint=faint_col(12)),  "11 x 22"),
    ("a dim edge ROW",         dict(faint=faint_row(1)),   "12 x 21"),
])
def test_a_missing_edge_line_refuses_rather_than_repairing(name, kw, raw):
    """⛔ **NO REPAIR PATH — A NEAR MISS IS A REFUSAL** (his "strictly enforced", 2026-08-11).

    A real edge line too dim for the array mask leaves the fit one line short. Two rules for
    putting it back were built and BOTH were caught renumbering the whole array while reporting
    the right shape: the first chose the side by counting detected pads (which says nothing
    about a line that was never indexed), the second asked the pixels and still lost, because
    nothing re-examined the lines already accepted. Adding a line is a claim about WHERE the
    array starts, and getting that wrong shifts every id by a constant — silently, under a map
    that looks perfect. So the fit is the device's shape or the job refuses."""
    img, _, _ = lattice_image(cols=12, rows=22, pitch=14.0, angle_deg=-2.0, seed=7, **kw)
    assert f"{fit_grid(img).cols} x {fit_grid(img).rows}" == raw, "fixture guard"

    with pytest.raises(NoGridFound) as excinfo:
        fit_grid(img, device=TEST_DEVICE, enforce_shape=True)
    msg = str(excinfo.value)
    assert raw in msg, "the refusal names what was found"
    assert "12 x 22" in msg, "...and what was declared"
    assert "partially imaged" in msg, "...and what he can do about it"


def test_a_line_trimmed_at_BOTH_ends_refuses_instead_of_renumbering():
    """🔴 **THE DEFECT THE REPAIR RULES DIED FOR** (adversarial review, finding #2).

    `_assemble`'s edge trim can drop a weak line at BOTH ends. The count rule then put both
    replacements on ONE side: right shape, "2 columns added" dutifully reported, and every id
    off by a constant. Reproduced on this exact fixture."""
    img, _, _ = lattice_image(cols=12, rows=22, pitch=14.0, angle_deg=-2.0, seed=7,
                              faint=faint_col(1) | faint_col(12))
    assert fit_grid(img).cols == 10, "fixture guard: the raw fit must lose BOTH edge columns"

    with pytest.raises(NoGridFound) as excinfo:
        fit_grid(img, device=TEST_DEVICE, enforce_shape=True)
    msg = str(excinfo.value)
    assert "10 x 22" in msg and "12 x 22" in msg
    assert "partially imaged" in msg


@pytest.mark.parametrize("name,missing", [
    # a 13th column with pads at only 6 of its 22 positions — enough detections to survive the
    # edge trim. The old rule deleted it and returned a confident 12 x 22.
    ("a sparse phantom column", {(13, r) for r in range(7, 23)}),
    # …and the dangerous twin: a GENUINE 13-column array declared as a 12-column chip.
    ("a real 13th column", {(13, r) for r in (3, 8, 14, 19)}),
])
def test_an_extra_edge_column_refuses_rather_than_trimming(name, missing):
    """The mirror image, and the more dangerous half. Trimming asks the same unanswerable
    question as extending — WHICH end is wrong — and deleting the wrong one throws away a
    column of real, imaged electrodes and renumbers the rest. 13 is not 12; refuse."""
    img, _, _ = lattice_image(cols=13, rows=22, pitch=14.0, angle_deg=-2.0,
                              missing=missing, seed=7)
    assert fit_grid(img).cols == 13, "fixture guard: the raw fit must have one column too many"

    with pytest.raises(NoGridFound) as excinfo:
        fit_grid(img, device=TEST_DEVICE, enforce_shape=True)
    msg = str(excinfo.value)
    assert "13 x 22" in msg and "12 x 22" in msg
    assert "partially imaged" in msg


def test_a_map_of_the_right_SIZE_but_the_wrong_PLACE_is_refused():
    """🔴 **CARDINALITY IS NOT REGISTRATION** (adversarial review, round two, finding #1).

    The one case a count can never catch: the array here is 13 columns wide and column 1 is too
    dim to index, so the fit comes back with columns 2..13 — exactly 12 x 22, exactly 264
    positions, an exact match for the declared chip. Every shape assertion passes. Every id is
    one column out.

    `_assert_registered` is what stands between that map and the user: the pixels one step
    beyond the numbering's low edge still look like electrodes, so the array does not end where
    the map says it does, and the job refuses instead of returning ids that are quietly wrong."""
    img, _, _ = lattice_image(cols=13, rows=22, pitch=14.0, angle_deg=-2.0, seed=7,
                              faint=faint_col(1))
    raw = fit_grid(img)
    assert (raw.cols, raw.rows) == (12, 22), (
        "fixture guard: the raw fit must be the RIGHT SHAPE in the WRONG PLACE")

    with pytest.raises(NoGridFound) as excinfo:
        fit_grid(img, device=TEST_DEVICE, enforce_shape=True)
    msg = str(excinfo.value)
    assert "shifted" in msg, "the refusal says what it suspects"
    assert "column" in msg, "...on which axis"
    assert "partially imaged" in msg


def test_a_fit_far_from_the_device_shape_refuses_and_names_both_shapes():
    img, _, _ = lattice_image(cols=24, rows=16, pitch=14.0)
    with pytest.raises(NoGridFound) as excinfo:
        fit_grid(img, device=MAXWELL, enforce_shape=True)
    msg = str(excinfo.value)
    assert "24 x 16" in msg, "the refusal names what was found"
    assert "220 x 120" in msg, "...and what was expected"
    assert "partially imaged" in msg, "...and what he should do about it"

    # the very same image maps fine once he says only part of the chip is in frame
    gm = fit_grid(img, device=MAXWELL, enforce_shape=False)
    assert (gm.cols, gm.rows) == (24, 16)
    assert gm.array_coverage == "partial"


def test_the_postcondition_cannot_be_dodged(monkeypatch):
    """⭐ THE GUARANTEE BEHIND THE WORD "STRICTLY": one gate at the EXIT of `fit_grid`, not an
    invariant spread over the helpers.

    Here the shape check itself is sabotaged into a no-op — the shape of every bug that could
    ever live in it. A map one column short of the declared chip still must not reach the
    caller, because a returned map is a map he will trust. The gate that stops it has to be
    downstream of everything, on the object actually being returned."""
    import camea.core.electrodegrid as eg

    monkeypatch.setattr(eg, "_enforce_device_shape", lambda *a, **kw: None)
    monkeypatch.setattr(eg, "_assert_registered", lambda *a, **kw: None)
    img, _, _ = lattice_image(cols=12, rows=22, pitch=14.0, angle_deg=-2.0, seed=7,
                              faint=faint_col(1))
    with pytest.raises(NoGridFound) as excinfo:
        fit_grid(img, device=TEST_DEVICE, enforce_shape=True)
    msg = str(excinfo.value)
    assert "11 x 22" in msg, "the refusal names the shape that actually came out"
    assert str(TEST_DEVICE.electrodes) in msg, "...and how many electrodes were declared"
    assert "partially imaged" in msg


def test_stats_describe_the_map_actually_returned():
    """Review finding #10. Full mode numbers every position the chip has, so the counts and
    residuals a fit ends with are not the ones the user is shown — they must be re-derived from
    the finished grid, or the panel reports a map nobody has."""
    img, _, _ = lattice_image(cols=12, rows=22, pitch=14.0, angle_deg=-2.0, seed=7,
                              n_occluders=3, missing={(4, r) for r in range(1, 23)})
    gm = fit_grid(img, device=TEST_DEVICE, enforce_shape=True)

    assert gm.stats["n_detected"] == int((gm.kind == GridMap.KIND_DETECTED).sum())
    assert gm.stats["n_inferred"] == int((gm.kind == GridMap.KIND_INFERRED).sum())
    assert gm.stats["n_detected"] + gm.stats["n_inferred"] == TEST_DEVICE.electrodes
    assert gm.stats["detected_frac"] == round(
        gm.stats["n_detected"] / TEST_DEVICE.electrodes, 4)

    # mean_confidence is averaged over the cells that are actually detected, from the per-cell
    # plane — not over a set that the fill has since changed
    surv = gm.conf[gm.kind == GridMap.KIND_DETECTED]
    assert gm.stats["mean_confidence"] == round(float(np.mean(surv[np.isfinite(surv)])), 4)
    assert gm.stats["step_residual_p95_px"] >= gm.stats["step_residual_median_px"] >= 0.0


# -----------------------------------------------------------------------------
# Partial coverage: only the 17.5 um rule
# -----------------------------------------------------------------------------
def test_partial_coverage_leaves_an_odd_shape_alone():
    """*"If they pick partial only enforce the 17.5 um rule."*"""
    missing = {(13, r) for r in (3, 8, 14, 19)}
    img, truth, _ = lattice_image(cols=13, rows=22, pitch=14.0, angle_deg=-2.0,
                                  missing=missing, seed=7)
    gm = fit_grid(img, device=TEST_DEVICE, enforce_shape=False)
    assert (gm.cols, gm.rows) == (13, 22), "partial mode must not touch the shape"
    assert "shape_corrected" not in gm.stats
    assert gm.array_coverage == "partial"
    assert gm.um_per_px is not None, "17.5 um is the scale in BOTH modes"
    assert gm.lookup(*truth[(1, 1)])["electrode"] == "1-1"


def test_partial_coverage_leaves_absent_cells_absent():
    """The honest answer in partial mode is a HOLE: "we did not see it, and the device shape
    does not apply here". Only "whole chip imaged" licenses numbering a position nobody
    imaged, because only then does the chip itself vouch that one is there."""
    img, _, _ = lattice_image(cols=24, rows=16, pitch=14.0, angle_deg=-2.0, n_occluders=3,
                              seed=13)
    valid = np.ones(img.shape, bool)
    valid[: img.shape[0] // 3, : img.shape[1] // 3] = False      # a corner never imaged
    gm = fit_grid(img, valid=valid, device=MAXWELL, enforce_shape=False)

    absent = int((gm.kind == GridMap.KIND_ABSENT).sum())
    assert absent > 0, "fixture guard: the clipped corner must leave real holes"
    assert gm.um is not None and np.isnan(gm.um[gm.kind == GridMap.KIND_ABSENT]).all()
    p = gm.payload()
    assert len(p["cells"]["col"]) == gm.cols * gm.rows - absent, "holes are omitted, not zeroed"


# -----------------------------------------------------------------------------
# The um frame
# -----------------------------------------------------------------------------
def test_um_per_px_is_the_device_pitch_over_the_measured_pitch():
    img, _, _ = lattice_image(cols=16, rows=12, pitch=14.0)
    gm = fit_grid(img, device=MAXWELL)
    assert gm.um_per_px == pytest.approx(MAXWELL.pitch_um / gm.pitch)
    assert gm.um_per_px == pytest.approx(17.5 / 14.0, abs=0.02), "measured, never assumed"

    p = gm.payload()
    assert p["um_per_px"] == round(gm.um_per_px, 6)
    assert p["device"] == MAXWELL.as_dict()
    assert p["array_coverage"] == "partial"
    assert gm.stats["um_per_px"] == round(gm.um_per_px, 6), "the stats reach the document"


def test_um_coordinates_are_the_array_frame_with_the_rotation_taken_out():
    img, truth, _ = lattice_image(cols=16, rows=12, pitch=14.0, angle_deg=-2.2)
    gm = fit_grid(img, device=DeviceSpec(name="t", axes=(16, 12)))
    p = gm.payload()
    n = len(p["cells"]["col"])
    assert len(p["cells"]["x_um"]) == len(p["cells"]["y_um"]) == n

    worst = 0.0
    for col, row, x_um, y_um in zip(p["cells"]["col"], p["cells"]["row"],
                                    p["cells"]["x_um"], p["cells"]["y_um"]):
        worst = max(worst, abs(x_um - (col - 1) * 17.5), abs(y_um - (row - 1) * 17.5))
    assert worst < 2.5, f"um coordinates drift {worst:.2f} um from the ideal lattice"

    # the rotation really is out: column 1 wanders several PIXELS down the image, but its
    # x_um is flat — that is what "the array's own frame" buys. (The residual ~1 um is the
    # error in the MEASURED a2, the axis column 1 runs along: the dual basis reads x in
    # LATTICE coordinates, so column 1's flatness now reports a2's accuracy, not a1's.)
    px = [x for x, c in zip(p["cells"]["x"], p["cells"]["col"]) if c == 1]
    um = [x for x, c in zip(p["cells"]["x_um"], p["cells"]["col"]) if c == 1]
    assert max(px) - min(px) > 4.0
    assert max(um) - min(um) < 1.5

    # and the click readout carries um alongside px
    hit = gm.lookup(*truth[(4, 3)])
    assert hit["electrode"] == "4-3"
    assert hit["x_um"] == pytest.approx(3 * 17.5, abs=2.5)
    assert hit["y_um"] == pytest.approx(2 * 17.5, abs=2.5)


def test_um_on_a_sheared_lattice_uses_the_dual_basis_not_a_projection():
    """🔴 Review finding #6. `x_um = (d . a1_hat) * um_per_px` is exact ONLY when a1 is
    perpendicular to a2 — and `_lattice_vectors` accepts pairs up to ~12 deg off orthogonal.
    This lattice is planted 8 deg off; the projection misplaces electrodes by more than a whole
    pitch while every number still looks plausible, and at row 220 of a real MaxOne that error
    is ~770 um, or 44 electrodes. Solving [a1 a2] @ (u, v) = d for the lattice coordinates is
    exact for any basis, and identical to the projection on a square one."""
    img, truth, _ = lattice_image(cols=20, rows=14, pitch=14.0, angle_deg=-2.0,
                                  shear_deg=8.0, seed=5)
    gm = fit_grid(img, device=DeviceSpec(name="t", axes=(20, 14)))
    a1, a2 = np.asarray(gm.a1), np.asarray(gm.a2)
    off = math.degrees(math.asin(abs(float(a1 @ a2)) / (np.hypot(*a1) * np.hypot(*a2))))
    assert off > 3.0, f"fixture guard: the fitted basis is only {off:.2f} deg off orthogonal"

    p = gm.payload()
    worst = 0.0
    for col, row, x_um, y_um in zip(p["cells"]["col"], p["cells"]["row"],
                                    p["cells"]["x_um"], p["cells"]["y_um"]):
        worst = max(worst, abs(x_um - (col - 1) * 17.5), abs(y_um - (row - 1) * 17.5))
    assert worst < 4.0, f"um coordinates drift {worst:.2f} um on a sheared lattice"

    # ...and the projection this replaced, recomputed here so the failure it used to hide is
    # visible: on the very same fit it puts electrodes more than a whole pitch out of place.
    e1 = a1 / np.hypot(*a1)
    rows, cols = gm.kind.shape
    cc, rr = np.meshgrid(np.arange(cols, dtype=float), np.arange(rows, dtype=float))
    ctr = gm.centers.astype(float)
    have = gm.kind != GridMap.KIND_ABSENT
    origin = (ctr - cc[..., None] * a1 - rr[..., None] * a2)[have].mean(axis=0)
    d = ctr - origin
    old_x = (d[..., 0] * e1[0] + d[..., 1] * e1[1]) * gm.um_per_px
    old_worst = max(abs(old_x[r, c] - c * 17.5)
                    for r in range(rows) for c in range(cols) if have[r, c])
    assert old_worst > 17.5, ("the old projection would have been within one pitch here — "
                              "this fixture no longer demonstrates the defect")


def test_no_device_means_no_um_at_all(tmp_path):
    """No device, no measured scale — and the map says "not known" rather than inventing
    a zero."""
    img, _, _ = lattice_image(cols=12, rows=9, pitch=14.0)
    gm = fit_grid(img)
    assert gm.device is None and gm.um_per_px is None and gm.um is None
    assert gm.array_coverage == "partial"

    p = gm.payload()
    assert p["um_per_px"] is None and p["device"] is None
    assert p["cells"]["x_um"] == [] and p["cells"]["y_um"] == []
    assert "um_per_px" not in p["stats"]
    json.dumps(p)

    write_map_files(p, tmp_path / "m.json", tmp_path / "m.csv")
    rows = list(csv.reader((tmp_path / "m.csv").read_text(encoding="utf-8").splitlines()))
    assert rows[0] == ["electrode", "col", "row", "x", "y", "x_um", "y_um", "kind", "coverage"]
    assert rows[1][5] == "" and rows[1][6] == "", "blank, not a made-up 0.0"


def test_the_payload_and_the_csv_carry_the_um_columns(tmp_path):
    img, _, _ = lattice_image(cols=14, rows=10, pitch=14.0, angle_deg=-2.0)
    gm = fit_grid(img, device=DeviceSpec(name="t", axes=(14, 10)))
    p = gm.payload()
    n = len(p["cells"]["col"])

    write_map_files(p, tmp_path / "m.json", tmp_path / "m.csv")
    rows = list(csv.reader((tmp_path / "m.csv").read_text(encoding="utf-8").splitlines()))
    assert rows[0] == ["electrode", "col", "row", "x", "y", "x_um", "y_um", "kind", "coverage"]
    assert len(rows) == n + 1
    first = rows[1]
    assert first[0] == f"{p['cells']['col'][0]}-{p['cells']['row'][0]}"
    assert float(first[3]) == p["cells"]["x"][0]        # pixels stay ...
    assert float(first[5]) == p["cells"]["x_um"][0]     # ... um are alongside
    assert float(first[6]) == p["cells"]["y_um"][0]

    saved = json.loads((tmp_path / "m.json").read_text(encoding="utf-8"))
    assert saved["um_per_px"] == p["um_per_px"]
    assert saved["device"]["pitch_um"] == 17.5
    assert saved["array_coverage"] == "partial"


def test_the_csv_states_its_coordinate_frame_on_every_row(tmp_path):
    """🔴 In `partial` mode `1-1` is the top-left of the IMAGED REGION, so x_um/y_um are
    anchored there and not on the chip's corner. The CSV is the artifact that LEAVES the app
    (R44) into a spreadsheet, where every caveat the UI carried is gone — and a header cell
    does not survive a sort, a filter, or a paste of one row into another sheet. So the frame
    rides on EVERY row."""
    img, _, _ = lattice_image(cols=12, rows=9, pitch=14.0)
    p = fit_grid(img, device=MAXWELL).payload()
    write_map_files(p, tmp_path / "m.json", tmp_path / "m.csv")
    lines = (tmp_path / "m.csv").read_text(encoding="utf-8").splitlines()
    assert lines[0].split(",")[-1] == "coverage"
    assert {ln.split(",")[-1] for ln in lines[1:] if ln} == {"partial"}

    img, _, _ = lattice_image(cols=12, rows=22, pitch=14.0, angle_deg=-2.0, seed=7)
    p = fit_grid(img, device=TEST_DEVICE, enforce_shape=True).payload()
    write_map_files(p, tmp_path / "f.json", tmp_path / "f.csv")
    lines = (tmp_path / "f.csv").read_text(encoding="utf-8").splitlines()
    assert {ln.split(",")[-1] for ln in lines[1:] if ln} == {"full"}
    assert len(lines) == TEST_DEVICE.electrodes + 1, "full = a row per electrode on the chip"


def test_every_fit_step_has_a_measured_weight_and_the_weights_tile_the_bar():
    """🔴 BEHAVIOUR R48.5 — `pct` is OVERALL. The electrode-map job looks each step's share of the
    bar up in `FIT_SPAN` **by the name `fit_grid` emits**, so a step added to `FIT_STEPS` without a
    weight would fall back to 0 and snap the bar backwards to the start of the fit mid-run. It also
    checks the weights are contiguous and cover 0..1 — a gap is a bar that jumps, an overlap is a
    bar that goes back."""
    from camea.core.electrodegrid import FIT_SPAN, FIT_STEPS

    assert tuple(FIT_SPAN) == FIT_STEPS, "same steps, same order"
    spans = list(FIT_SPAN.values())
    assert spans[0][0] == 0.0 and spans[-1][1] == 1.0
    for (_a, b), (c, d) in zip(spans, spans[1:]):
        assert b == c, "the weights must tile the bar with no gap and no overlap"
        assert c < d, "a step with no width cannot be seen"
