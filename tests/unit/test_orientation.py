"""Scoring the four chip seatings.

⛔ Synthetic, non-MaxWell geometry throughout (stride 7, a 4x7 chip) — same rule as
test_mearecording.py. A test that hard-coded 220 would pass even if the code did too.

🔴 These tests check the ARITHMETIC, not that the answer means anything. The clock alignment it
rests on did not validate against the calcium video (issue 003); he asked for it built anyway. So
what is asserted here is that a planted correlation is found, that an untestable seating is reported
as untestable rather than as a bad score, and that nothing here confirms a seating on its own.
"""

from __future__ import annotations

import numpy as np
import pytest

from camea.features.videomosaic import orientation as ori

STRIDE = 7
COLS, ROWS = 4, 7          # a portrait grid of a landscape 7x4 chip


def test_population_rate_bins_spikes():
    r = ori.population_rate(np.array([0.05, 0.15, 0.16, 0.95]), 0.0, 1.0, bin_s=0.1)
    assert r.size == 10
    assert r[0] == 1 and r[1] == 2 and r[9] == 1


def test_population_rate_of_nothing_is_zeros_not_empty():
    assert ori.population_rate(np.zeros(0), 0.0, 1.0, bin_s=0.1).tolist() == [0.0] * 10


def test_pearson_is_none_on_a_flat_series():
    """⭐ Undefined, not zero. A flat series has no correlation to report, and calling it 0.0 would
    rank it against seatings that were genuinely tested."""
    assert ori.pearson(np.ones(10), np.arange(10.0)) is None
    assert ori.pearson(np.arange(10.0), np.arange(10.0)) == pytest.approx(1.0)


def test_align_offset_finds_a_planted_shift():
    a = ori.intervals_to_mask([(2.0, 3.0), (6.0, 7.0)], 10.0)
    b = ori.intervals_to_mask([(3.5, 4.5), (7.5, 8.5)], 10.0)   # same marks, 1.5 s later
    off, jac = ori.align_offset(a, b, max_shift_s=5.0)
    assert off == pytest.approx(-1.5, abs=0.11)
    assert jac > 0.9


def test_align_offset_reports_a_weak_score_when_there_is_no_alignment():
    rng = np.random.default_rng(0)
    a = rng.random(600) < 0.1
    b = rng.random(600) < 0.1
    _, jac = ori.align_offset(a, b, max_shift_s=10.0)
    assert jac < 0.5


# ── the seating scores ──────────────────────────────────────────────────────────────────────────


def _spiky(duration: float, bursts: list[float], per: int = 40) -> np.ndarray:
    rng = np.random.default_rng(1)
    out = []
    for b in bursts:
        out.append(b + rng.random(per) * 0.4)
    return np.sort(np.concatenate(out)) if out else np.zeros(0)


def test_the_seating_whose_electrodes_actually_fire_with_the_calcium_wins():
    """Plant the answer in one seating and check it is recovered."""
    duration = 20.0
    bursts = [2.0, 8.0, 14.0]
    calcium = ori.population_rate(_spiky(duration, bursts), 0.0, duration)

    # region covers one pad, col=1,row=1. Under no-flip that is chip (ex=0, ey=0) -> electrode 0.
    region = ["1-1"]
    truth_chip = 0
    channel_of = {truth_chip: 10}
    spikes_of = {10: _spiky(duration, bursts)}          # fires exactly with the calcium

    scores = ori.score_seatings(region, cols=COLS, rows=ROWS, stride=STRIDE,
                                channel_of=channel_of, spikes_of=spikes_of,
                                calcium=calcium, duration_s=duration)
    assert len(scores) == 4
    scorable = [s for s in scores if s.scorable]
    assert len(scorable) == 1                            # only one seating hits a recorded pad
    best = scorable[0]
    assert (best.flip_x, best.flip_y) == (False, False)
    assert best.correlation > 0.9


def test_a_seating_with_no_recorded_electrodes_is_untestable_not_badly_scored():
    """⭐ THE DISTINCTION THAT MATTERS. 'no electrode under this field' must not be reported as a
    correlation of zero — it would rank an untested seating alongside a tested-and-failed one."""
    duration = 10.0
    calcium = ori.population_rate(_spiky(duration, [1.0, 5.0]), 0.0, duration)
    scores = ori.score_seatings(["1-1"], cols=COLS, rows=ROWS, stride=STRIDE,
                                channel_of={}, spikes_of={},        # nothing was recorded
                                calcium=calcium, duration_s=duration)
    assert all(s.correlation is None for s in scores)
    assert all(not s.scorable for s in scores)
    assert all(s.n_recorded == 0 for s in scores)


def test_coverage_is_reported_against_the_region_size():
    duration = 5.0
    calcium = np.zeros(int(duration / ori.BIN_S))
    scores = ori.score_seatings(["1-1", "2-1", "3-1"], cols=COLS, rows=ROWS, stride=STRIDE,
                                channel_of={0: 1}, spikes_of={1: np.array([1.0])},
                                calcium=calcium, duration_s=duration)
    d = [s.as_dict() for s in scores]
    assert all(x["n_region"] == 3 for x in d)
    assert any(x["n_recorded"] == 1 and x["coverage"] == pytest.approx(1 / 3) for x in d)


def test_offset_shifts_the_mea_clock_onto_the_video():
    """The correlation must be recovered only once the planted offset is applied."""
    duration = 20.0
    bursts = [3.0, 9.0, 15.0]
    calcium = ori.population_rate(_spiky(duration, bursts), 0.0, duration)
    lag = 4.0
    spikes = _spiky(duration, bursts) + lag              # MEA clock runs 4 s ahead
    kw = dict(cols=COLS, rows=ROWS, stride=STRIDE, channel_of={0: 10},
              spikes_of={10: spikes}, calcium=calcium, duration_s=duration)

    wrong = [s for s in ori.score_seatings(["1-1"], offset_s=0.0, **kw) if s.scorable][0]
    right = [s for s in ori.score_seatings(["1-1"], offset_s=lag, **kw) if s.scorable][0]
    assert right.correlation > 0.9
    assert right.correlation > wrong.correlation


def test_malformed_electrode_ids_are_skipped_not_fatal():
    scores = ori.score_seatings(["1-1", "rubbish", "2"], cols=COLS, rows=ROWS, stride=STRIDE,
                                channel_of={}, spikes_of={}, calcium=np.zeros(10),
                                duration_s=1.0)
    assert all(s.n_region == 1 for s in scores)
