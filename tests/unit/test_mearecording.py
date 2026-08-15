"""The MEA recording reader.

⛔ **THE FIXTURES HERE ARE DELIBERATELY NOT MAXWELL.** Same rule as
``web/src/features/electrodes/device.test.ts``: a test that asserted "stride is 220" would be
writing the device number down a second time, and would pass just as happily if the code had
hard-coded it. So the synthetic chip below is a 7-wide, 4-tall array on a 12.5 µm pitch. If
``derive_stride`` ever starts assuming a MaxOne, these go red.
"""

from __future__ import annotations

import dataclasses

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


# ── the per-pad tally the chip map is coloured by ───────────────────────────────────────────────


def test_activity_counts_every_routed_pad_in_mapping_order(rec):
    with mr.MeaRecording(rec) as r:
        act = r.activity()
        # One row per routed pad, aligned with `mapping()` so the two zip without a join.
        assert act["channel"].tolist() == r.mapping()["channel"].tolist()
        # channel 0 fired twice, channel 1 once, and the rest of the routed set heard nothing.
        assert act["n_spikes"].tolist() == [2, 1, 0, 0]


def test_activity_rate_is_per_second_of_the_recording(rec):
    with mr.MeaRecording(rec) as r:
        # 4000 samples at 1 kHz = 4 s, so two spikes is 0.5/s.
        assert r.info().duration_s == pytest.approx(4.0)
        assert r.activity()["rate_hz"].tolist() == pytest.approx([0.5, 0.25, 0.0, 0.0])


def test_a_routed_pad_that_heard_nothing_is_zero_not_absent(rec):
    """⛔ Silence is a MEASUREMENT — the amplifier was on that pad for the whole recording and
    detected nothing. A pad that was never routed is simply not in the mapping. The chip map has to
    draw the first and cannot draw the second, so they must never collapse into one another."""
    with mr.MeaRecording(rec) as r:
        act = r.activity()
        assert act.size == r.mapping().size == 4
        silent = act[act["n_spikes"] == 0]
        assert silent["channel"].tolist() == [2, 3]
        assert silent["rate_hz"].tolist() == [0.0, 0.0]


def test_activity_does_not_credit_a_spike_on_an_unrouted_channel(tmp_path):
    """⚠️ The regression this method's `searchsorted` guard exists for. Without confirming the hit,
    a spike on a channel absent from the mapping lands on whichever pad sits at the insertion
    point — i.e. it is silently added to an innocent electrode's count, which would light up a pad
    on the chip map that recorded nothing."""
    d = tmp_path / "Network" / "000123"
    d.mkdir(parents=True)
    p = _write(d / mr.MEA_FILENAME,
               routed=((0, 3), (2, 16)),
               spikes=((100, 0, -25.0), (250, 1, -40.0), (300, 9, -12.0)))
    with mr.MeaRecording(p) as r:
        act = r.activity()
        # Channels 1 and 9 are not routed here, so their spikes belong to nobody.
        assert act["channel"].tolist() == [0, 2]
        assert act["n_spikes"].tolist() == [1, 0]
        assert int(act["n_spikes"].sum()) == 1


def test_activity_is_all_zeros_when_nothing_was_detected(tmp_path):
    d = tmp_path / "Network" / "000123"
    d.mkdir(parents=True)
    p = _write(d / mr.MEA_FILENAME, spikes=())
    with mr.MeaRecording(p) as r:
        act = r.activity()
        assert act.size == 4
        assert act["n_spikes"].tolist() == [0, 0, 0, 0]
        assert act["rate_hz"].tolist() == [0.0, 0.0, 0.0, 0.0]


def test_activity_needs_no_decoder(rec):
    """⭐ The whole reason the chip map is worth drawing before the MaxWell decoder is found: the
    spike table is uncompressed, so this is exactly right on a machine where `trace()` is a rail."""
    with mr.MeaRecording(rec) as r:
        assert r.trace_health(0).flat is True          # the fixture's raw stream IS a rail
        assert int(r.activity()["n_spikes"].sum()) == 3


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


# ── one read instead of two: `trace_window` ─────────────────────────────────────────────────────
#
# ⭐ Plan 004's free fix. Every caller that presents a trace honestly needs the waveform AND its
# health, and `trace()` + `trace_health()` each decompress the window independently. `trace_window`
# pays once — so the ONE thing these tests have to hold it to is that it did not change the answer.


def test_trace_window_is_exactly_trace_and_trace_health_from_a_single_read(tmp_path):
    """🔴 **THE WHOLE POINT OF IT, AND THE ONLY WAY IT CAN GO WRONG.** It is an optimisation, so a
    drift between it and the pair it replaces would be invisible on screen and wrong in the data."""
    d = tmp_path / "Network" / "000123"
    d.mkdir(parents=True)
    rng = np.random.default_rng(3)
    raw = (RAIL + rng.integers(-40, 40, size=(4, 4000))).astype(np.uint16)
    raw[1, 1500:1508] = 3          # a spike, so the extremes are not all noise
    p = _write(d / mr.MEA_FILENAME, raw=raw)

    with mr.MeaRecording(p) as r:
        for ch in (0, 1, 2, 3):
            for t0, t1 in ((0.0, 1.0), (0.5, 2.25), (3.9, 99.0), (0.0, None)):
                uv, health = r.trace_window(ch, t0, t1)
                assert uv.tolist() == r.trace(ch, t0, t1).tolist(), (ch, t0, t1)
                assert health == r.trace_health(ch, t0, t1), (ch, t0, t1)


def test_trace_window_on_an_empty_or_inverted_window_is_empty_and_zeroed(rec):
    """⚠️ Not an error — an empty window is what a caller gets for asking past the end, and the
    route turns it into a refusal itself. The health must be zeroed rather than invented."""
    with mr.MeaRecording(rec) as r:
        for t0, t1 in ((2.0, 1.0), (5.0, 6.0), (1.0, 1.0)):
            uv, health = r.trace_window(0, t0, t1)
            assert uv.size == 0, (t0, t1)
            assert health == mr.TraceHealth(0, 0, 0.0, 0), (t0, t1)
            assert health == r.trace_health(0, t0, t1), (t0, t1)


def test_health_of_needs_no_file_and_agrees_with_the_reader(rec):
    """`health_of` is the same arithmetic with the counts already in hand — that is what lets the
    envelope builder measure a whole recording without a second pass."""
    counts = np.array([7, 7, 7, 9], dtype=np.uint16)
    h = mr.health_of(counts)
    assert (h.n_samples, h.fill_value, h.distinct_values) == (4, 7, 2)
    assert h.fill_fraction == pytest.approx(0.75)
    assert mr.health_of(np.empty(0, dtype=np.uint16)) == mr.TraceHealth(0, 0, 0.0, 0)
    with mr.MeaRecording(rec) as r:
        assert mr.health_of(np.full(4000, RAIL, dtype=np.uint16)) == r.trace_health(0)


# ── the honest thinning: `minmax_columns` ───────────────────────────────────────────────────────


def test_minmax_columns_leaves_a_window_narrower_than_the_canvas_untouched():
    """Fewer values than columns means there is nothing to reduce — and reducing anyway would put
    a fabricated shape on screen where the real samples fit."""
    v = np.arange(5, dtype=np.float64)
    for n in (5, 6, 500):
        lo, hi = mr.minmax_columns(v, n)
        assert lo.tolist() == v.tolist()
        assert hi.tolist() == v.tolist()
    lo, hi = mr.minmax_columns(np.empty(0, dtype=np.float64), 8)
    assert lo.size == hi.size == 0


def test_minmax_columns_is_amplitude_conservative():
    """🔴 **A SPIKE MAY NEVER BE THINNED AWAY.** Sub-sampling a 20 kHz stream lands on a 5-16 sample
    spike roughly never and draws a calm line over a burst. Each column keeps the true extent of its
    own slice, so the tallest thing in the window is still the tallest thing on screen."""
    rng = np.random.default_rng(17)
    v = rng.standard_normal(1000)
    v[437] = 50.0                      # one sample, far above everything
    v[811] = -50.0

    lo, hi = mr.minmax_columns(v, 16)
    assert lo.size == hi.size == 16
    cut = np.linspace(0, v.size, 17, dtype=np.int64)
    for j in range(16):
        seg = v[cut[j]:cut[j + 1]]
        assert lo[j] == seg.min()
        assert hi[j] == seg.max()
    assert hi.max() == 50.0 and lo.min() == -50.0
    assert np.all(lo <= hi)


# ── the whole recording at a glance: the min/max envelope ───────────────────────────────────────
#
# ⭐ Plan 004. The `Analyze MEA` panel draws the WHOLE recording, and MaxWell chunks the raw stream
# across every channel at once — so one channel's full length costs almost what all of them cost.
# The answer is a single pass, cached. These hold it to the two promises that make such a cache
# honest: it **brackets** every real sample (nothing can hide between the columns), and it carries
# its **own** whole-recording health rather than borrowing whatever window happened to be open.


def _mixed(n_ch: int = 4, n: int = 4000, seed: int = 5) -> np.ndarray:
    """A raw block with a different character on every channel, so no one shape can stand in for
    another: a dead rail, real noise with two spikes, a mostly-railed channel, and a square wave."""
    rng = np.random.default_rng(seed)
    raw = np.full((n_ch, n), RAIL, dtype=np.uint16)
    raw[1] = (RAIL + rng.integers(-60, 60, size=n)).astype(np.uint16)
    raw[1, 1234] = 3                                   # one sample, right at the bottom
    raw[1, 2500:2506] = 1200                           # a short burst, right at the top
    raw[2, : n // 4] = (RAIL + rng.integers(-60, 60, size=n // 4)).astype(np.uint16)
    raw[3, ::2] = RAIL + 7                             # two values only
    return raw


def _mixed_recording(tmp_path, **kw):
    d = tmp_path / "Network" / "000123"
    d.mkdir(parents=True, exist_ok=True)
    return _write(d / mr.MEA_FILENAME, raw=_mixed(**kw))


def test_the_envelope_brackets_every_real_sample(tmp_path):
    """🔴 **THE HONESTY GUARANTEE.** A spike must never be able to fall outside the extent that gets
    drawn. Each column's `lo`/`hi` is the true min and max of the samples under it, so every sample
    of the recording lies inside the picture — whatever the eye can resolve at that width.

    ⚠️ The bucket edges are recomputed here from `n_samples` and `n_buckets` alone. That is not a
    copy of the implementation: an even split is the only one consistent with the linear time axis
    the payload promises (`t = bucket / n_buckets * duration_s`)."""
    raw = _mixed()
    p = _mixed_recording(tmp_path)
    n_buckets = 37                                     # deliberately not a divisor of 4000

    with mr.MeaRecording(p) as r:
        env = r.build_envelope(n_buckets)
        n = r.info().n_samples

    assert env.n_buckets == n_buckets
    edges = np.linspace(0, n, n_buckets + 1, dtype=np.int64)
    for ch in (0, 1, 2, 3):
        row = env.row_of(ch)
        assert row is not None
        for j in range(n_buckets):
            seg = raw[row, edges[j]:edges[j + 1]]
            assert seg.size
            assert env.lo[row, j] <= seg.min(), (ch, j)
            assert env.hi[row, j] >= seg.max(), (ch, j)
            assert np.all((seg >= env.lo[row, j]) & (seg <= env.hi[row, j])), (ch, j)

    # ⭐ And stated once more without any edges at all: the extremes of the whole recording survive.
    for ch in (0, 1, 2, 3):
        row = env.row_of(ch)
        assert env.lo[row].min() == raw[row].min()
        assert env.hi[row].max() == raw[row].max()
    assert env.lo[env.row_of(1)].min() == 3, "the one-sample trough is still drawn"
    assert env.hi[env.row_of(1)].max() == 1200, "and so is the burst"


def test_the_envelopes_health_is_a_full_reads_health_channel_for_channel(tmp_path):
    """🔴 **IT MAY NOT BORROW A WINDOW'S NUMBER.** A railed stretch is indistinguishable from a
    genuinely quiet electrode, and the rail fraction *changes with window length* — so the cache
    measures the whole recording itself, and must get exactly what a full read would have got.

    ⚠️ `fill_fraction` is stored as float32 to halve the cache, so it is compared at that precision
    and no coarser. `flat` — the verdict the screen actually shows — must be identical."""
    p = _mixed_recording(tmp_path)
    with mr.MeaRecording(p) as r:
        env = r.build_envelope(37)
        for ch in (0, 1, 2, 3):
            cached, full = env.health_of(ch), r.trace_health(ch)
            assert cached is not None
            assert cached.n_samples == full.n_samples == r.info().n_samples
            assert cached.fill_value == full.fill_value, ch
            assert cached.distinct_values == full.distinct_values, ch
            assert np.float32(cached.fill_fraction) == np.float32(full.fill_fraction), ch
            assert cached.flat == full.flat, ch

    # The fixture is worth something only if the four channels disagree about all this.
    assert env.health_of(0).flat is True and env.health_of(1).flat is False
    assert env.health_of(0).fill_fraction == 1.0
    assert env.health_of(3).distinct_values == 2
    assert env.health_of(9999) is None, "a channel that was never routed has no health"


def test_the_envelope_round_trips_through_disk(tmp_path):
    """Everything the panel draws from has to survive the save — the columns, the channel ids, and
    the three numbers that turn stored counts back into microvolts and seconds."""
    p = _mixed_recording(tmp_path)
    with mr.MeaRecording(p) as r:
        env = r.build_envelope(64)

    dest = tmp_path / "cache" / mr.ENVELOPE_FILENAME
    mr.save_envelope(dest, env)
    assert dest.is_file()
    back = mr.load_envelope(dest)

    assert back is not None
    assert back.version == env.version == mr.ENVELOPE_VERSION
    assert np.array_equal(back.lo, env.lo)
    assert np.array_equal(back.hi, env.hi)
    assert back.lo.dtype == env.lo.dtype, "stored unscaled, in the file's own dtype"
    assert np.array_equal(back.channels, env.channels)
    assert back.n_samples == env.n_samples == 4000
    assert back.sampling_hz == env.sampling_hz == FS
    assert back.lsb_uv == env.lsb_uv
    assert back.n_buckets == env.n_buckets == 64
    assert back.duration_s == pytest.approx(4.0)
    assert np.array_equal(back.fill_value, env.fill_value)
    assert np.array_equal(back.fill_fraction, env.fill_fraction)
    assert np.array_equal(back.distinct_values, env.distinct_values)
    for ch in (0, 1, 2, 3):
        assert back.health_of(ch) == env.health_of(ch)


def test_a_missing_or_foreign_or_stale_cache_is_a_MISS_not_an_ERROR(tmp_path):
    """⛔ **A CACHE MISS IS NEVER SOMETHING HE HAS TO READ ABOUT.** The answer is a rebuild, so
    every unusable file has to come back as `None` — including one written by an older Camea, which
    must be rebuilt rather than reinterpreted."""
    p = _mixed_recording(tmp_path)
    with mr.MeaRecording(p) as r:
        env = r.build_envelope(16)

    assert mr.load_envelope(tmp_path / "never-written.npz") is None

    foreign = tmp_path / "foreign.npz"
    foreign.write_bytes(b"this is not an npz at all, just some bytes")
    assert mr.load_envelope(foreign) is None

    stale = tmp_path / "stale.npz"
    mr.save_envelope(stale, dataclasses.replace(env, version=mr.ENVELOPE_VERSION + 1))
    assert mr.load_envelope(stale) is None, "a bumped version REBUILDS; it is never reinterpreted"

    fresh = tmp_path / "fresh.npz"
    mr.save_envelope(fresh, env)
    assert mr.load_envelope(fresh) is not None, "...and a current one still loads"


def test_a_TRUNCATED_cache_is_a_MISS_not_an_ERROR(tmp_path):
    """⭐ **REGRESSION, 2026-08-15.** A half-written `.npz` does not raise anything in
    `(OSError, KeyError, ValueError)`: numpy hands the file to `zipfile`, which raises
    `zipfile.BadZipFile` — a plain `Exception`. Caught narrowly, that escaped as a **500** from
    `GET /recordings/envelopes` and from the trace route, on a screen whose whole design is to say
    *"not read yet"* honestly instead.

    ⚠️ `save_envelope` writes `.part` and renames, so Camea itself will not leave one of these —
    but a full disk, a killed process or a half-copied project folder will. ⛔ Do not narrow the
    `except` again; this is the test that says so."""
    p = _mixed_recording(tmp_path)
    with mr.MeaRecording(p) as r:
        env = r.build_envelope(16)
    good = tmp_path / "good.npz"
    mr.save_envelope(good, env)
    whole = good.read_bytes()

    for cut in (4, 22, len(whole) // 4, len(whole) // 2, len(whole) - 1):
        half = tmp_path / f"half{cut}.npz"
        half.write_bytes(whole[:cut])
        assert mr.load_envelope(half) is None, cut

    # ...and one that merely *looks* like a zip, which is the other way numpy reaches `zipfile`.
    looks_like = tmp_path / "looks-like.npz"
    looks_like.write_bytes(b"PK\x03\x04" + b"nothing else about this is a zip file")
    assert mr.load_envelope(looks_like) is None


def test_the_envelope_window_clamps_to_its_own_buckets_and_honours_max_points(tmp_path):
    """⚠️ **THE RETURNED TIMES ARE THE BUCKETS ACTUALLY COVERED, NOT WHAT WAS ASKED FOR.** The
    cache cannot honestly report a finer edge than a bucket, so a caller labels its axis from these
    — which is only safe if they are always inside the recording."""
    p = _mixed_recording(tmp_path)
    with mr.MeaRecording(p) as r:
        env = r.build_envelope(64)
    dur = env.duration_s

    for t0, t1, cap in ((-500.0, 9999.0, 20), (0.0, dur, 7), (1.0, 1.5, 4), (99.0, 199.0, 20)):
        got = env.window(0, t0, t1, cap)
        assert got is not None, (t0, t1)
        lo, hi, w0, w1 = got
        assert lo.size == hi.size, (t0, t1)
        assert lo.size <= cap, (t0, t1)
        assert lo.size >= 1, (t0, t1)
        assert np.all(lo <= hi), (t0, t1)
        assert 0.0 <= w0 < w1 <= dur, (t0, t1, w0, w1)

    # A cap wider than the cache is not padded — it returns what it has.
    lo, hi, w0, w1 = env.window(0, 0.0, dur, 10_000)
    assert lo.size == hi.size == env.n_buckets == 64
    assert (w0, w1) == (0.0, pytest.approx(dur))

    # ⛔ And a channel that was never routed is `None`, not an empty picture of nothing.
    assert env.window(9999, 0.0, dur, 20) is None


def test_the_envelope_window_comes_back_in_microvolts(tmp_path):
    """Stored as raw counts and scaled on the way out — so the cache is half the size and exactly
    reversible. `lsb_uv` is 1.0 on this fixture, so a scale that was dropped would still show; the
    check that catches it is against the real samples."""
    raw = _mixed()
    p = _mixed_recording(tmp_path)
    with mr.MeaRecording(p) as r:
        env = r.build_envelope(64)
        lsb = r.info().lsb_uv

    lo, hi, _w0, _w1 = env.window(1, 0.0, env.duration_s, 10_000)
    row = env.row_of(1)
    assert lo.min() == pytest.approx(raw[row].min() * lsb)
    assert hi.max() == pytest.approx(raw[row].max() * lsb)


def test_a_recording_with_no_continuous_trace_is_refused_by_name(tmp_path):
    """⛔ **A FACT ABOUT THE ASSAY, NOT A FAILURE.** An ActivityScan writes no continuous stream at
    all, so there is nothing to reduce — and the refusal has to say that rather than read as a
    broken file. (`start_envelope` turns it into "nothing to do", which is why the words matter.)"""
    d = tmp_path / "ActivityScan" / "000687"
    d.mkdir(parents=True)
    p = _write(d / mr.MEA_FILENAME, n_samples=0, spikes=())
    with mr.MeaRecording(p) as r:
        assert r.info().n_samples == 0
        with pytest.raises(mr.MeaError, match="no continuous trace"):
            r.build_envelope(64)


def test_an_envelope_of_no_buckets_is_refused(rec):
    with mr.MeaRecording(rec) as r:
        with pytest.raises(ValueError, match="at least 1"):
            r.build_envelope(0)


def test_the_envelope_never_claims_more_buckets_than_the_recording_has_samples(tmp_path):
    """⚠️ Asking for more columns than there are samples would leave empty ones, and an empty
    column has no honest min or max. The count is capped at what the file can fill."""
    d = tmp_path / "Network" / "000123"
    d.mkdir(parents=True)
    p = _write(d / mr.MEA_FILENAME, n_samples=50, spikes=())
    with mr.MeaRecording(p) as r:
        env = r.build_envelope(8192)
    assert env.n_buckets == 50
    assert env.lo.shape == env.hi.shape == (4, 50)


def test_the_builder_reports_progress_and_the_same_answer_whatever_the_block_size(tmp_path):
    """⚠️ It reads in blocks so a 6-billion-sample file does not have to fit in memory, and the
    block size is a memory budget — it must not be able to change the picture."""
    p = _mixed_recording(tmp_path)
    seen: list[float] = []
    with mr.MeaRecording(p) as r:
        one = r.build_envelope(37, progress=seen.append)
        many = r.build_envelope(37, max_block_values=500)

    assert np.array_equal(one.lo, many.lo)
    assert np.array_equal(one.hi, many.hi)
    assert np.array_equal(one.fill_value, many.fill_value)
    assert np.array_equal(one.distinct_values, many.distinct_values)
    assert seen and seen == sorted(seen)
    assert seen[-1] == pytest.approx(1.0), "it finishes at 100 %, so a progress bar can land"


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
