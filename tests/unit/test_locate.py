"""core.locate — placing a differently-magnified fixed-field recording on a mosaic.

Every assertion is against a planted answer key, never against the algorithm's own output.
The synthetic world is built once and then SAMPLED two different ways — a wide, ragged,
1:1 "mosaic" and a small, magnified, noisy "recording" cut from a known spot — so the test
reproduces the real asymmetry: the two pictures are of the same ground at different zooms,
taken with different noise, and nothing tells the matcher where to look.

The adversarial theme is A CONFIDENT WRONG PLACE, not a crash. The electrode lattice is a
periodic comb: it manufactures correlation peaks that score well and sit whole cells away
from the truth. So the tests check the *distance to the planted position*, and they check
that a recording of somewhere else does not get placed anyway.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from camea.core import locate
from camea.core.electrodegrid import NoGridFound, lattice_axes, measure_lattice

from test_electrodegrid import lattice_image  # noqa: E402 — sibling module, rootdir on sys.path


# =============================================================================
# A world, sampled two ways
# =============================================================================
def world_image(pitch=30.0, cols=80, rows=60, seed=3):
    """A chip: electrode lattice + bright cells sitting on it (the `n_occluders` blobs are
    exactly the right shape for neurons) + a border bar. ~2.5k x 1.9k px."""
    img, _truth, _meta = lattice_image(
        cols=cols, rows=rows, pitch=pitch, angle_deg=-2.2,
        n_occluders=40, border_ring=True, noise=2.0, seed=seed)
    return np.asarray(img, np.float32)


def ragged_mask(shape, seed=1):
    """A coverage mask with a bitten-out corner — a real survey does not cover a rectangle."""
    h, w = shape
    m = np.zeros((h, w), bool)
    m[:, :] = True
    m[: h // 5, : w // 6] = False                      # the corner the sweep missed
    return m


def recording_frames(world, x0, y0, cw, ch, zoom, n=6, noise=6.0, seed=11):
    """A stack of frames as the fixed-field camera would have seen it: the same ground at
    `zoom` times the mosaic's magnification, with independent noise per frame and a few
    cells firing in some frames and not others."""
    import cv2

    rng = np.random.default_rng(seed)
    crop = np.asarray(world[y0:y0 + ch, x0:x0 + cw], np.float32)
    big = cv2.resize(crop, (int(round(cw * zoom)), int(round(ch * zoom))),
                     interpolation=cv2.INTER_CUBIC)
    H, W = big.shape
    yy, xx = np.mgrid[0:H, 0:W]
    frames = []
    for i in range(n):
        f = big + rng.normal(0, noise, big.shape).astype(np.float32)
        # two cells that only light up in some frames — the temporal signal a max/std
        # projection is meant to recover and a single frame would miss
        if i % 2 == 0:
            for cx, cy in ((W * 0.3, H * 0.4), (W * 0.7, H * 0.6)):
                r = 0.05 * W
                f += 90.0 * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * r ** 2))
        frames.append(f.astype(np.float32))
    return frames


TRUTH_X, TRUTH_Y, CROP_W, CROP_H, ZOOM = 900, 700, 420, 320, 2.5


@pytest.fixture(scope="module")
def scene():
    w = world_image()
    frames = recording_frames(w, TRUTH_X, TRUTH_Y, CROP_W, CROP_H, ZOOM)
    return {"world": w, "mask": ragged_mask(w.shape), "frames": frames}


@pytest.fixture(scope="module")
def placed(scene):
    """The whole pipeline run once — several tests read different facts off the same answer,
    and it is the same run the app performs."""
    ref, rmask = locate.prepare_reference(scene["world"], scene["mask"])
    stills = locate.still_stack(scene["frames"])
    pm, am, _ = measure_lattice(scene["world"], scene["mask"])
    a1, a2, _ = lattice_axes(scene["world"], scene["mask"])
    zoom = locate.measure_zoom(stills["median"], pm, am)
    return {"ref": ref, "rmask": rmask, "stills": stills, "zoom": zoom, "lattice": (a1, a2),
            "loc": locate.locate(ref, rmask, stills, zoom, lattice=(a1, a2))}


# =============================================================================
# The ruler: the lattice measures the zoom
# =============================================================================
def test_the_lattice_measures_the_zoom_between_the_two_pictures(scene):
    """⭐ The load-bearing claim of the whole feature: the chip is a ruler, so the zoom is
    MEASURED and never searched."""
    pm, _am, _s = measure_lattice(scene["world"], scene["mask"])
    stills = locate.still_stack(scene["frames"])
    pr, _ar, _s2 = measure_lattice(stills["median"], pitch_min=6.0, pitch_max=200.0)

    assert pr == pytest.approx(30.0 * ZOOM, rel=0.06), f"recording pitch {pr}"
    assert pm == pytest.approx(30.0, rel=0.06), f"mosaic pitch {pm}"
    assert pm / pr == pytest.approx(1.0 / ZOOM, rel=0.06)


def test_measure_zoom_reports_a_measurement_not_a_guess(scene):
    stills = locate.still_stack(scene["frames"])
    pm, am, _ = measure_lattice(scene["world"], scene["mask"])
    z = locate.measure_zoom(stills["median"], pm, am)

    assert z.measured is True
    assert z.scale == pytest.approx(1.0 / ZOOM, rel=0.06)
    assert z.angle_delta is not None and abs(z.angle_delta) < 3.0, (
        "same rig, same orientation — the measured angles must agree")


def test_a_picture_with_no_lattice_says_so_instead_of_inventing_a_zoom():
    """A recording of bare tissue has no ruler in it. That is an answer, not a failure — and
    it must fall back to a search rather than report a made-up measurement."""
    rng = np.random.default_rng(0)
    blobs = rng.normal(0, 1, (400, 400)).astype(np.float32)
    with pytest.raises(NoGridFound):
        measure_lattice(blobs)

    z = locate.measure_zoom(blobs, 30.0, 0.0)
    assert z.measured is False
    assert z.scale == 1.0
    assert "no electrode lattice" in z.note
    assert len(locate.scale_ladder()) > 1


# =============================================================================
# The placement
# =============================================================================
def test_a_magnified_recording_lands_on_the_ground_it_was_cut_from(placed):
    """The whole feature, end to end, against the planted position."""
    loc = placed["loc"]

    assert loc.x == pytest.approx(TRUTH_X, abs=3.0), loc.to_json()
    assert loc.y == pytest.approx(TRUTH_Y, abs=3.0), loc.to_json()
    assert loc.w == pytest.approx(CROP_W, abs=3.0)
    assert loc.h == pytest.approx(CROP_H, abs=3.0)
    assert loc.outcome.confident, f"not confident: {loc.to_json()}"
    assert loc.still_kind in locate.STILL_KINDS


def test_the_refinement_beats_the_ffts_own_ruler(placed):
    """⭐ The FFT bin quantisation is worth a few percent of scale, which is several px of
    corner. The refined scale must be closer to the truth than the measured one was."""
    loc, z = placed["loc"], placed["zoom"]
    truth = 1.0 / ZOOM

    assert abs(loc.zoom.scale - truth) < abs(z.scale - truth), (
        f"refined {loc.zoom.scale} is no better than measured {z.scale} (truth {truth})")
    assert loc.zoom.scale == pytest.approx(truth, rel=0.01)


def test_every_still_kind_is_tried_and_the_winner_is_named(placed):
    """Which projection resembles the mosaic is a property of the preparation, so all of them
    are tried from ONE decode and the result says which won — never a silent choice."""
    loc = placed["loc"]
    assert set(placed["stills"]) == set(locate.STILL_KINDS)
    assert {r["still_kind"] for r in loc.tried} == set(locate.STILL_KINDS)
    assert loc.still_kind in {r["still_kind"] for r in loc.tried}


def test_the_runner_up_and_the_margin_come_back(placed):
    """`best - second` is the only evidence the aperture killed the aliases rather than
    outscoring them by a whisker. It must always be reported, and it must be measured on the
    surface the winner actually won on."""
    loc = placed["loc"]

    assert len(loc.outcome.candidates) >= 2
    assert loc.outcome.margin is not None
    assert loc.outcome.candidates[0].ncc >= loc.outcome.candidates[1].ncc
    assert loc.outcome.margin == pytest.approx(
        loc.outcome.candidates[0].ncc - loc.outcome.candidates[1].ncc, abs=1e-6)
    # and every alternative is a genuinely different place, not the same peak twice
    x0, y0 = loc.outcome.candidates[0].x, loc.outcome.candidates[0].y
    assert all(math.hypot(c.x - x0, c.y - y0) > locate.NMS_PX
               for c in loc.outcome.candidates[1:])


def test_positions_are_top_left_corners_not_centres(placed):
    """R19. Off-by-half-a-template is this project's classic bug."""
    loc = placed["loc"]
    # the centre would be a whole half-template away from the planted top-left
    assert abs(loc.x - TRUTH_X) < 0.25 * loc.w
    assert abs(loc.y - TRUTH_Y) < 0.25 * loc.h


# =============================================================================
# The alias killer
# =============================================================================
def test_notching_the_lattice_opens_the_margin_over_the_aliases(placed, scene):
    """⭐ THE LOAD-BEARING DEFENCE. The electrode comb manufactures peaks a whole number of
    cells away that score nearly as well as the truth — measured here, the runner-up sits ~10
    cells to the right. Removing the comb costs the answer nothing (a periodic pattern cannot
    say WHERE, only where-modulo-the-pitch) and roughly doubles the gap to those aliases.

    If this test ever goes red, the margins the user is shown have stopped meaning what the
    UI claims they mean — do not relax it, find out why."""
    a1, a2 = placed["lattice"]
    ref, rmask = placed["ref"], placed["rmask"]
    still = placed["stills"]["median"]
    scale = placed["loc"].zoom.scale

    tpl, tmsk = locate.prepare_template(still, scale)
    plain = locate.match(ref, rmask, tpl, tmsk)
    notched = locate.match(locate.notch_lattice(ref, a1, a2, valid=rmask), rmask,
                           locate.notch_lattice(tpl, a1, a2), tmsk)

    assert plain.margin is not None and notched.margin is not None
    assert notched.margin > 1.5 * plain.margin, (
        f"notched margin {notched.margin:.4f} vs plain {plain.margin:.4f}")
    # and it is still the RIGHT place — the notch must not buy confidence with correctness
    assert notched.best is not None
    assert math.hypot(notched.best.x - TRUTH_X, notched.best.y - TRUTH_Y) < 12.0


def test_the_notch_leaves_the_aperiodic_picture_alone(placed):
    """The tissue, the neurons and the array's BORDER are what actually say where you are.
    Only the comb may be deleted."""
    a1, a2 = placed["lattice"]
    rng = np.random.default_rng(7)
    blobs = np.zeros((512, 512), np.float32)
    yy, xx = np.mgrid[0:512, 0:512]
    for _ in range(12):
        cx, cy = rng.uniform(60, 450, 2)
        blobs += 100.0 * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * 14.0 ** 2))
    blobs -= blobs.mean()

    out = locate.notch_lattice(blobs, a1, a2)
    keep = float((out * blobs).sum() / (blobs * blobs).sum())
    assert keep > 0.9, f"the notch ate {100 * (1 - keep):.0f}% of an aperiodic picture"


def test_a_degenerate_lattice_is_a_no_op_not_a_crash(placed):
    """Parallel 'axes' have no reciprocal basis. Refusing to filter is the right answer."""
    a = np.zeros((64, 64), np.float32)
    a[16:32, 16:32] = 5.0
    same = locate.notch_lattice(a, (10.0, 0.0), (20.0, 0.0))
    assert np.allclose(same, a)


# =============================================================================
# Drag, then snap
# =============================================================================
def test_a_dragged_rectangle_snaps_back_to_the_truth(placed):
    """The correction primitive: dropped ~60 px off, a bounded local re-search recovers it.

    It uses the recording's SETTLED scale — the one the document stores after locating — which
    is the only scale the app ever snaps at."""
    loc = placed["loc"]
    tpl, tmsk = locate.prepare_template(placed["stills"][loc.still_kind], loc.zoom.scale)

    out = locate.snap(placed["ref"], placed["rmask"], tpl, tmsk,
                      (TRUTH_X + 47, TRUTH_Y - 39), radius=96)

    assert out.best is not None, out.refused
    assert out.best.x == pytest.approx(TRUTH_X, abs=3.0)
    assert out.best.y == pytest.approx(TRUTH_Y, abs=3.0)


def test_the_snap_radius_is_clamped(placed):
    """⚠️ A local search has no whole-plane view, so it cannot tell a peak from one of twenty
    identical ones. Widened without bound it is an alias generator."""
    loc = placed["loc"]
    tpl, tmsk = locate.prepare_template(placed["stills"][loc.still_kind], loc.zoom.scale)

    # a hilarious radius must not be honoured; it must simply be clamped and still answer
    out = locate.snap(placed["ref"], placed["rmask"], tpl, tmsk, (TRUTH_X, TRUTH_Y),
                      radius=10_000)
    assert out.best is not None
    assert locate.SNAP_RADIUS_MAX < 10_000


# =============================================================================
# Refusing is a correct outcome
# =============================================================================
def test_a_template_bigger_than_the_mosaic_is_refused_with_a_sentence(scene):
    ref, rmask = locate.prepare_reference(scene["world"], scene["mask"])
    huge = np.zeros((ref.shape[0] + 64, ref.shape[1] + 64), np.float32)
    out = locate.match(ref, rmask, huge, np.ones(huge.shape, bool))

    assert out.best is None
    assert out.refused and "bigger than the mosaic" in out.refused


def test_a_recording_of_nowhere_is_not_reported_as_confident(scene):
    """Pure noise correlates with nothing. It must come back not-confident — a rectangle the
    user is told not to trust, never a confident claim about which electrodes were recorded."""
    ref, rmask = locate.prepare_reference(scene["world"], scene["mask"])
    rng = np.random.default_rng(5)
    junk = rng.normal(0, 20, (320, 420)).astype(np.float32)
    tpl, tmsk = locate.prepare_template(junk, 1.0)

    out = locate.match(ref, rmask, tpl, tmsk)
    assert not out.confident, f"noise was called confident: ncc={out.best and out.best.ncc}"


def test_locate_refuses_out_loud_when_nothing_can_be_placed(scene):
    ref, rmask = locate.prepare_reference(scene["world"], scene["mask"])
    too_big = np.zeros((ref.shape[0] + 8, ref.shape[1] + 8), np.float32)
    with pytest.raises(locate.NoLocation):
        locate.locate(ref, rmask, {"median": too_big},
                      locate.Zoom(scale=1.0, measured=True))


# =============================================================================
# The small print
# =============================================================================
def test_the_reference_is_mean_subtracted_over_the_mask_only(scene):
    """An unmasked mean is dragged by the background zeros and biases every NCC by the shape
    of the hull — `t33.composite`'s rule, restated here because this canvas is not its."""
    ref, mask = locate.prepare_reference(scene["world"], scene["mask"])
    assert float(ref[mask].mean()) == pytest.approx(0.0, abs=1e-3)
    assert not ref[~mask].any(), "outside the coverage must be exactly zero"


def test_sample_indices_spread_over_the_whole_recording():
    idx = locate.sample_indices(1000, 25)
    assert len(idx) == 25
    assert idx[0] == 0 and idx[-1] == 999
    assert idx == sorted(idx)
    # a short recording gives back what it has, without duplicates
    assert locate.sample_indices(4, 25) == [0, 1, 2, 3]
    assert locate.sample_indices(0, 25) == []


def test_a_still_stack_is_built_from_one_decode():
    frames = [np.full((6, 6), float(i), np.float32) for i in range(5)]
    s = locate.still_stack(frames)
    assert s["median"][0, 0] == pytest.approx(2.0)
    assert s["max"][0, 0] == pytest.approx(4.0)
    assert s["std"][0, 0] == pytest.approx(math.sqrt(2.0))


def test_the_scale_ladder_is_log_even_and_brackets_one():
    lad = locate.scale_ladder()
    assert lad[0] < 1.0 < lad[-1]
    ratios = [lad[i + 1] / lad[i] for i in range(len(lad) - 1)]
    assert max(ratios) - min(ratios) < 1e-3, "the ladder must be geometric, not arithmetic"
