"""The MEA recording reader.

⛔ **THE FIXTURES HERE ARE DELIBERATELY NOT MAXWELL.** Same rule as
``web/src/features/electrodes/device.test.ts``: a test that asserted "stride is 220" would be
writing the device number down a second time, and would pass just as happily if the code had
hard-coded it. So the synthetic chip below is a 7-wide, 4-tall array on a 12.5 µm pitch. If
``derive_stride`` ever starts assuming a MaxOne, these go red.
"""

from __future__ import annotations

import numpy as np
import pytest

from camea.core import mearecording as mr

h5py = pytest.importorskip("h5py")

# The synthetic chip. Nothing here matches a real device, on purpose.
STRIDE = 7          # long axis
N_ROWS = 4          # short axis
PITCH = 12.5        # µm
FS = 1000.0         # Hz
LSB_V = 1e-6        # 1 µV per count
RAIL = 512


def _write(path, *, routed=((0, 3), (1, 9), (2, 16), (3, 22)), n_samples=4000,
           spikes=((100, 0, -25.0), (250, 1, -40.0), (900, 0, -31.0)),
           raw=None, with_run_id=True):
    """Build a minimal MaxLab-shaped file. ``routed`` is a list of (channel, electrode)."""
    routed = list(routed)
    n_ch = len(routed)
    with h5py.File(path, "w") as f:
        g = f.create_group("data_store/data0000")
        s = g.create_group("settings")
        s["sampling"] = np.array([FS])
        s["lsb"] = np.array([LSB_V])
        s["gain"] = np.array([512.0])
        s["hpf"] = np.array([300.0])
        m = np.empty(n_ch, dtype=[("channel", "<i4"), ("electrode", "<i4"),
                                  ("x", "<f8"), ("y", "<f8")])
        for i, (ch, el) in enumerate(routed):
            m[i] = (ch, el, (el % STRIDE) * PITCH, (el // STRIDE) * PITCH)
        s["mapping"] = m
        rg = g.create_group("groups/routed")
        rg["channels"] = np.array([c for c, _ in routed], dtype=np.uint16)
        rg["frame_nos"] = np.arange(1000, 1000 + n_samples, dtype=np.uint64)
        if raw is None:
            raw = np.full((n_ch, n_samples), RAIL, dtype=np.uint16)
        rg["raw"] = raw
        sp = np.empty(len(spikes), dtype=[("frameno", "<i8"), ("channel", "<i4"),
                                          ("amplitude", "<f4")])
        for i, (fr, ch, amp) in enumerate(spikes):
            sp[i] = (1000 + fr, ch, amp)
        g["spikes"] = sp
        if with_run_id:
            f["assay/run_id"] = np.array([b"000123"])
    return path


@pytest.fixture()
def rec(tmp_path):
    d = tmp_path / "Network" / "000123"
    d.mkdir(parents=True)
    return _write(d / mr.MEA_FILENAME)


# ── the layout is derived, never assumed ────────────────────────────────────────────────────────


def test_stride_is_derived_from_the_file_not_hard_coded(rec):
    with mr.MeaRecording(rec) as r:
        assert r.stride() == STRIDE


def test_stride_refuses_rather_than_guesses_when_the_numbering_is_inconsistent():
    el = np.array([0, 1, 2, 3])
    ex = np.array([0, 1, 2, 3])
    ey = np.array([0, 0, 1, 1])          # electrode 2 would need stride 0, electrode 3 stride -1
    with pytest.raises(mr.MeaError, match="refusing to guess"):
        mr.derive_stride(el, ex, ey)


def test_stride_refuses_when_everything_sits_on_one_row():
    with pytest.raises(mr.MeaError, match="one array row"):
        mr.derive_stride(np.array([0, 1, 2]), np.array([0, 1, 2]), np.array([0, 0, 0]))


def test_pitch_is_measured_from_the_mapping(rec):
    with mr.MeaRecording(rec) as r:
        assert r.pitch_um() == pytest.approx(PITCH)


def test_sparse_routing_does_not_fool_the_pitch(tmp_path):
    """⭐ REGRESSION, from real data (2026-08-13). One of this project's recordings routed only
    every OTHER pad, so the smallest gap between routed electrodes is twice the true pitch. Deriving
    the pitch from routed spacing gave 2x and then failed to explain the ids. The geometry must come
    from the numbering identity, which sparse routing cannot distort."""
    d = tmp_path / "Network" / "000123"
    d.mkdir(parents=True)
    # every other column, every other row -> routed gaps are 2*PITCH on both axes
    routed = [(i, ey * STRIDE + ex) for i, (ex, ey) in
              enumerate([(0, 0), (2, 0), (4, 0), (0, 2), (2, 2), (4, 2)])]
    p = _write(d / mr.MEA_FILENAME, routed=routed, spikes=())
    with mr.MeaRecording(p) as r:
        assert r.pitch_um() == pytest.approx(PITCH)
        assert r.stride() == STRIDE


def test_geometry_refuses_a_mapping_it_cannot_explain():
    """Two rows that imply different strides (10 vs 11) — no (pitch, stride) explains both, so the
    only correct answer is a refusal."""
    el = np.array([0, 1, 2, 10, 12])
    x = np.array([0.0, 12.5, 25.0, 0.0, 12.5])
    y = np.array([0.0, 0.0, 0.0, 12.5, 12.5])
    with pytest.raises(mr.MeaError, match="refusing to guess|whole multiples"):
        mr.derive_geometry(el, x, y)


def test_mapping_carries_derived_chip_indices(rec):
    with mr.MeaRecording(rec) as r:
        m = r.mapping()
        assert np.array_equal(m["ey"] * STRIDE + m["ex"], m["electrode"])


# ── the facts ───────────────────────────────────────────────────────────────────────────────────


def test_info_reads_header_without_touching_raw(rec):
    with mr.MeaRecording(rec) as r:
        i = r.info()
        assert (i.n_channels, i.n_samples) == (4, 4000)
        assert i.sampling_hz == FS
        assert i.lsb_uv == pytest.approx(1.0)
        assert i.duration_s == pytest.approx(4.0)
        assert i.run_id == "000123"
        assert i.assay == "Network"
        assert i.label == "Network/000123"
        assert i.n_spikes == 3


def test_run_id_falls_back_to_the_folder_when_the_file_is_silent(tmp_path):
    d = tmp_path / "ActivityScan" / "000777"
    d.mkdir(parents=True)
    p = _write(d / mr.MEA_FILENAME, with_run_id=False)
    with mr.MeaRecording(p) as r:
        assert r.info().run_id == "000777"
        assert r.info().assay == "ActivityScan"


def test_electrode_lookup_reports_unrecorded_electrodes_as_none(rec):
    with mr.MeaRecording(rec) as r:
        assert r.channel_of_electrode(9) == 1
        assert r.channel_of_electrode(11) is None      # never routed — a fact, not an error


def test_missing_file_is_refused(tmp_path):
    with pytest.raises(mr.NoRecordingsFound):
        mr.MeaRecording(tmp_path / "nope.h5")


# ── spikes: the half that needs no proprietary decoder ──────────────────────────────────────────


def test_spikes_are_seconds_from_the_first_stored_sample(rec):
    with mr.MeaRecording(rec) as r:
        sp = r.spikes()
        assert sp["t_s"].tolist() == pytest.approx([0.1, 0.25, 0.9])
        assert sp["amplitude_uv"].tolist() == pytest.approx([-25.0, -40.0, -31.0])


def test_spikes_of_channel_filters(rec):
    with mr.MeaRecording(rec) as r:
        assert r.spikes_of_channel(0)["t_s"].tolist() == pytest.approx([0.1, 0.9])


# ── the trace, and being honest about it ────────────────────────────────────────────────────────


def test_trace_converts_counts_to_microvolts(tmp_path):
    d = tmp_path / "Network" / "000123"
    d.mkdir(parents=True)
    raw = np.full((4, 4000), RAIL, dtype=np.uint16)
    raw[0, :10] = np.arange(10) + 100
    p = _write(d / mr.MEA_FILENAME, raw=raw)
    with mr.MeaRecording(p) as r:
        t = r.trace(0, 0.0, 0.01)
        assert t.tolist() == pytest.approx((np.arange(10) + 100).astype(float).tolist())


def test_trace_window_is_clipped_to_the_recording(rec):
    with mr.MeaRecording(rec) as r:
        assert r.trace(0, 3.9, 99.0).size == 100
        assert r.trace(0, 5.0, 6.0).size == 0


def test_trace_health_flags_a_railed_window(rec):
    """The whole point: a window that is one repeated value must be reported as unusable, so the UI
    can say so instead of drawing a convincing flat line."""
    with mr.MeaRecording(rec) as r:
        h = r.trace_health(0)
        assert h.fill_value == RAIL
        assert h.fill_fraction == 1.0
        assert h.flat is True


def test_trace_health_passes_a_real_looking_window(tmp_path):
    d = tmp_path / "Network" / "000123"
    d.mkdir(parents=True)
    rng = np.random.default_rng(0)
    raw = (RAIL + rng.integers(-20, 20, size=(4, 4000))).astype(np.uint16)
    p = _write(d / mr.MEA_FILENAME, raw=raw)
    with mr.MeaRecording(p) as r:
        h = r.trace_health(0)
        assert h.flat is False
        assert h.fill_fraction < 0.2


# ── the lamp episodes ───────────────────────────────────────────────────────────────────────────


def test_sync_episodes_finds_synchronous_excursions_only(tmp_path):
    """Neural activity is local; a lamp hits every channel at once. Only the second must be found."""
    d = tmp_path / "Network" / "000123"
    d.mkdir(parents=True)
    n_ch, n = 4, 4000
    raw = np.full((n_ch, n), RAIL, dtype=np.uint16)
    raw[0, 500:1500] = 5                       # one channel busy for 1 s -> NOT an episode
    raw[:, 2000:3000] = 5                      # all four together for 1 s -> an episode
    p = _write(d / mr.MEA_FILENAME, raw=raw)
    with mr.MeaRecording(p) as r:
        eps = r.sync_episodes(min_channels=3, min_duration_s=0.5)
    assert len(eps) == 1
    assert eps[0].start_s == pytest.approx(2.0, abs=0.01)
    assert eps[0].end_s == pytest.approx(3.0, abs=0.01)
    assert eps[0].peak_channels == 4


def test_sync_episodes_can_be_bounded_to_a_window_and_reports_absolute_times(tmp_path):
    """⭐ Scanning a whole recording is a full pass of the raw stream — far too slow for a request,
    so a chart asks only for the window it draws. The times must still be absolute: a lamp mark is
    a timestamp in the recording, not an offset into whatever window happened to reveal it."""
    d = tmp_path / "Network" / "000123"
    d.mkdir(parents=True)
    raw = np.full((4, 4000), RAIL, dtype=np.uint16)
    raw[:, 400:900] = 5      # 0.4-0.9 s
    raw[:, 2400:2900] = 5    # 2.4-2.9 s
    p = _write(d / mr.MEA_FILENAME, raw=raw)
    with mr.MeaRecording(p) as r:
        both = r.sync_episodes(min_channels=3, min_duration_s=0.4)
        assert [round(e.start_s, 2) for e in both] == [0.4, 2.4]
        # ask only for the second half — the first episode must not appear, the second keeps its
        # absolute time rather than being reported at 0.4 s into the window
        late = r.sync_episodes(2.0, 4.0, min_channels=3, min_duration_s=0.4)
        assert len(late) == 1
        assert late[0].start_s == pytest.approx(2.4, abs=0.02)
        assert late[0].end_s == pytest.approx(2.9, abs=0.02)


def test_sync_episodes_ignores_blips_below_the_duration_floor(tmp_path):
    d = tmp_path / "Network" / "000123"
    d.mkdir(parents=True)
    raw = np.full((4, 4000), RAIL, dtype=np.uint16)
    raw[:, 1000:1050] = 5                      # 50 ms — too short
    p = _write(d / mr.MEA_FILENAME, raw=raw)
    with mr.MeaRecording(p) as r:
        assert r.sync_episodes(min_channels=3, min_duration_s=0.5) == []


# ── discovery ───────────────────────────────────────────────────────────────────────────────────


def test_find_recordings_walks_a_tree_in_stable_order(tmp_path):
    for assay, run in (("Network", "000002"), ("Network", "000001"), ("ActivityScan", "000003")):
        d = tmp_path / "P1" / assay / run
        d.mkdir(parents=True)
        _write(d / mr.MEA_FILENAME)
    found = mr.find_recordings(tmp_path)
    assert [p.parent.name for p in found] == ["000003", "000001", "000002"]


def test_find_recordings_on_a_missing_folder_is_empty_not_an_error(tmp_path):
    assert mr.find_recordings(tmp_path / "gone") == []


def _session(tmp_path):
    """The real-world shape: optical and electrical halves as siblings under one session."""
    for plate, run in (("PLATE_A", "000001"), ("PLATE_B", "000002")):
        d = tmp_path / "MEA" / plate / "Network" / run
        d.mkdir(parents=True)
        _write(d / mr.MEA_FILENAME)
    img = tmp_path / "Imaging" / "PLATE_A" / "imaging"
    img.mkdir(parents=True)
    return img


def test_suggest_climbs_to_the_sibling_mea_folder(tmp_path):
    img = _session(tmp_path)
    hits = mr.suggest_recordings(img, "PLATE_A")
    assert [p.parent.name for p in hits] == ["000001"]


def test_suggest_prefers_the_named_plate_over_the_others(tmp_path):
    img = _session(tmp_path)
    assert all("PLATE_B" in str(p) for p in mr.suggest_recordings(img, "PLATE_B"))


def test_suggest_returns_everything_when_the_name_matches_nothing(tmp_path):
    """⛔ It must not return an empty list and let a caller think there is no data — it proposes
    what it found and the user decides."""
    img = _session(tmp_path)
    assert len(mr.suggest_recordings(img, "PLATE_ZZZ")) == 2


def test_suggest_on_a_missing_folder_is_empty(tmp_path):
    deep = tmp_path / "a" / "b" / "c" / "d" / "gone"
    assert mr.suggest_recordings(deep, "x") == []


def test_suggest_will_not_climb_out_of_its_budget(tmp_path):
    """⛔ A stale path must not let the search walk up to a drive root and propose an unrelated
    session's recordings — the confirm dialog looks identical either way."""
    _session(tmp_path)
    far = tmp_path / "a" / "b" / "c" / "d" / "e" / "f" / "gone"
    assert mr.suggest_recordings(far, "PLATE_A") == []


def test_suggest_survives_a_stale_data_dir(tmp_path):
    """⭐ REGRESSION, from real data (2026-08-13). Both of this project's saved documents point at a
    data_dir that no longer exists — the mirror gained a folder level after they were created. The
    search must climb to the nearest surviving ancestor instead of claiming there is no data."""
    _session(tmp_path)
    stale = tmp_path / "PLATE_A" / "imaging"          # never existed at this path
    assert not stale.exists()
    hits = mr.suggest_recordings(stale, "PLATE_A")
    assert [p.parent.name for p in hits] == ["000001"]


# ── orientation: explicit, never assumed ────────────────────────────────────────────────────────


def test_orientation_defaults_are_unconfirmed():
    o = mr.Orientation()
    assert o.confirmed is False
    assert (o.flip_x, o.flip_y) == (False, False)


def test_orientation_maps_chip_indices_into_grid_coordinates():
    """A portrait grid of a landscape chip: cols != stride, so the axes swap."""
    o = mr.Orientation()
    ex = np.array([0, 6])       # long axis
    ey = np.array([0, 3])       # short axis
    col, row = o.to_grid(ex, ey, cols=N_ROWS, rows=STRIDE, stride=STRIDE)
    assert col.tolist() == [1, 4]
    assert row.tolist() == [1, 7]


def test_orientation_flips_reverse_the_axes():
    ex = np.array([0])
    ey = np.array([0])
    col, row = mr.Orientation(flip_x=True, flip_y=True).to_grid(
        ex, ey, cols=N_ROWS, rows=STRIDE, stride=STRIDE)
    assert (col[0], row[0]) == (N_ROWS, STRIDE)


def test_orientation_without_transpose_when_shapes_already_agree():
    col, row = mr.Orientation().to_grid(
        np.array([2]), np.array([1]), cols=STRIDE, rows=N_ROWS, stride=STRIDE)
    assert (col[0], row[0]) == (3, 2)


@pytest.mark.parametrize("flip_x", [False, True])
@pytest.mark.parametrize("flip_y", [False, True])
@pytest.mark.parametrize("cols,rows", [(N_ROWS, STRIDE), (STRIDE, N_ROWS)])
def test_grid_round_trip_is_exact_in_every_seating(flip_x, flip_y, cols, rows):
    """⭐ The click direction must be the exact inverse of the render direction. An error here is
    invisible on screen and pairs the wrong neuron with the wrong voltage."""
    o = mr.Orientation(flip_x=flip_x, flip_y=flip_y)
    for ex in range(STRIDE):
        for ey in range(N_ROWS):
            col, row = o.to_grid(np.array([ex]), np.array([ey]),
                                 cols=cols, rows=rows, stride=STRIDE)
            back = o.from_grid(int(col[0]), int(row[0]), cols=cols, rows=rows, stride=STRIDE)
            assert back == (ex, ey)


def test_chip_electrode_recovers_the_maxwell_id():
    o = mr.Orientation()
    # electrode 15 on a stride-7 chip sits at ex=1, ey=2
    col, row = o.to_grid(np.array([1]), np.array([2]), cols=N_ROWS, rows=STRIDE, stride=STRIDE)
    assert o.chip_electrode(int(col[0]), int(row[0]),
                            cols=N_ROWS, rows=STRIDE, stride=STRIDE) == 15
