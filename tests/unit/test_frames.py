"""core/frames.py — the reader, the flat-field, the GLOBAL tone window, the display path.

Ported from `archive/app-v1/backend/loader.py :: _selftest` (260 lines of genuinely good
assertions, which lived in a `__main__` block and therefore never ran in CI). The ones that need
the 35 GB mirror live in `tests/slow/`; **these run on synthetic frames in a tmpdir and are fast**,
which means they run on every commit — which is the whole point.

⛔ Nothing in this file knows a trial number. Synthetic trials are 1, 2, 3.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from camea.core import frames as F

# =================================================================================================
# Synthetic frames — a fake acquisition, built by hand. No dataset, no `core.dataset`, no disk
# mirror. The `meta` dict is exactly what `core.dataset.read_trial_meta` produces.
# =================================================================================================
H = W = 64


def _meta(tmp: Path, trial: int, arr: np.ndarray, *, flip_x=True, flip_y=True) -> dict:
    dat = tmp / f"{trial:03d}-ccd.dat"
    dat.write_bytes(np.ascontiguousarray(arr.astype("<u2")).tobytes())
    h, w = arr.shape
    return {
        "trial": trial,
        "time": "2026-06-20T16:02:44Z",
        "w": w,
        "h": h,
        "bytes": 2,
        "dtype": "uint16",
        "flip_x": flip_x,
        "flip_y": flip_y,
        "dat": dat,
    }


def _rich(seed: int, h: int = H, w: int = W) -> np.ndarray:
    """A textured frame: real tissue detail on a ~2000-count pedestal."""
    r = np.random.default_rng(seed)
    return np.clip(r.normal(2000, 400, (h, w)), 0, 65535).astype(np.uint16)


def _flat(seed: int, h: int = H, w: int = W) -> np.ndarray:
    """A near-blank frame: the same pedestal, almost no structure. (Sensor noise only.)"""
    r = np.random.default_rng(seed)
    return np.clip(r.normal(2000, 6, (h, w)), 0, 65535).astype(np.uint16)


@pytest.fixture
def snaps(tmp_path: Path) -> dict[int, dict]:
    return {
        1: _meta(tmp_path, 1, _rich(1)),
        2: _meta(tmp_path, 2, _rich(2)),
        3: _meta(tmp_path, 3, _flat(3)),  # the near-blank one
    }


@pytest.fixture
def store(tmp_path: Path, snaps) -> F.FrameStore:
    return F.FrameStore.load(tmp_path, [1, 2, 3], snaps=snaps)


# =================================================================================================
# ⭐⭐ THE READER, AND THE FLIP
# =================================================================================================
def test_the_flip_is_a_true_180_rotation_not_a_transpose(tmp_path: Path):
    raw = _rich(9)
    m = _meta(tmp_path, 1, raw, flip_x=True, flip_y=True)
    out = F.load_frame(m)
    assert out[0, 0] == raw[-1, -1]  # 180, not a transpose
    assert np.array_equal(out, np.flip(np.flip(raw, 1), 0).astype(np.float32))


def test_the_flip_is_not_a_no_op(tmp_path: Path):
    """🔴 An unflipped read returns DIFFERENT pixels — and would have looked perfectly plausible.
    Every position, every SWIM dx/dy and all three ground truths live in the flipped frame."""
    raw = _rich(9)
    m = _meta(tmp_path, 1, raw, flip_x=True, flip_y=True)
    assert not np.array_equal(F.load_frame(m), raw.astype(np.float32))


def test_the_flip_is_CONDITIONAL_on_the_xml(tmp_path: Path):
    """⚠️ The reader honours the file. `ax=+1, ay=+1` (no `<transform>`) => NO flip. Nothing in the
    app may hard-code '180-degree-flipped' — see `frame_note`."""
    raw = _rich(9)
    m = _meta(tmp_path, 1, raw, flip_x=False, flip_y=False)
    assert np.array_equal(F.load_frame(m), raw.astype(np.float32))

    mx = _meta(tmp_path, 2, raw, flip_x=True, flip_y=False)
    assert np.array_equal(F.load_frame(mx), np.flip(raw, 1).astype(np.float32))


def test_reader_refuses_a_pixel_type_it_does_not_understand(tmp_path: Path):
    m = _meta(tmp_path, 1, _rich(1))
    m["dtype"] = "uint8"
    m["bytes"] = 1
    with pytest.raises(ValueError, match="unsupported pixel type"):
        F.load_frame(m)


def test_reader_refuses_a_dat_whose_size_disagrees_with_its_xml(tmp_path: Path):
    """⚠️ It never reshapes bytes into a lie. It says so and stops."""
    m = _meta(tmp_path, 1, _rich(1))
    m["h"] = H * 2  # the XML now claims twice the rows
    with pytest.raises(ValueError, match="px, XML says"):
        F.load_frame(m)


def test_load_frames_row_i_is_trials_i(tmp_path: Path, snaps):
    stack = F.load_frames(tmp_path, [3, 1], snaps=snaps)
    assert stack.shape == (2, H, W)
    assert stack.dtype == np.float32
    assert np.array_equal(stack[0], F.load_frame(snaps[3]))
    assert np.array_equal(stack[1], F.load_frame(snaps[1]))


# =================================================================================================
# ⚠️ SHAPE IS PER-TRIAL. Core refuses to guess which shape you meant.
# =================================================================================================
def test_a_mixed_shape_selection_is_REFUSED_not_reshaped(tmp_path: Path, snaps):
    """A genuine 1-frame snapshot at a different parpix is real data — it just cannot share a frame
    store. ⛔ Do NOT take the majority shape: which shape you meant is the caller's decision."""
    snaps[4] = _meta(tmp_path, 4, _rich(4, h=H // 2, w=W))
    with pytest.raises(F.MixedShapeError) as e:
        F.load_frames(tmp_path, [1, 2, 3, 4], snaps=snaps)
    groups = e.value.groups
    assert [(g["w"], g["h"], g["n"]) for g in groups] == [(W, H, 3), (W, H // 2, 1)]
    assert groups[1]["trials"] == [4]


def test_core_holds_no_512(store: F.FrameStore):
    """⛔ 512 is `t33.TILE` — the MOSAIC feature's gate. A store holds whatever the XML said."""
    assert store.shape == (H, W) == (64, 64)


def test_load_frames_names_the_trials_it_cannot_find(tmp_path: Path, snaps):
    with pytest.raises(ValueError, match=r"not snapshots.*\[99\]"):
        F.load_frames(tmp_path, [1, 99], snaps=snaps)


# =================================================================================================
# ⚠️⚠️ THE TONE WINDOW IS GLOBAL. Difference mode depends on it.
# =================================================================================================
def test_the_window_is_GLOBAL_so_a_near_blank_frame_STAYS_DIM(store: F.FrameStore):
    """🔴 **THE DISCRIMINATING TEST.** Under the global window the near-blank frame stays dim. A
    per-tile percentile stretch would over-brighten it to the *same contrast as a rich frame* —
    which makes overlapping tiles disagree in brightness and **destroys the Difference-mode check
    the entire verification loop depends on.** There is no per-tile path and there must never be
    one, not even for a thumbnail."""
    rich, empty = 1, 3
    g = {t: float(F.to_u8(store.frame(t), store.flat_n, store.tone).std()) for t in (rich, empty)}

    p = {}
    for t in (rich, empty):  # the FORBIDDEN per-tile way, computed only to show what it costs
        c = F.flat_correct(store.frame(t), store.flat_n, store.tone.level)
        plo, phi = np.percentile(c, [F.TONE_PCT_LO, F.TONE_PCT_HI])
        p[t] = float(np.clip((c - plo) * (255.0 / (phi - plo)), 0, 255).astype(np.uint8).std())

    assert g[rich] / g[empty] >= 3.0, "the global window must keep the near-blank frame dim"
    assert p[rich] / p[empty] < 1.5, "a per-tile stretch flattens them — which is why we do not"


def test_tone_samples_at_most_96_frames_evenly(tmp_path: Path):
    metas = {t: _meta(tmp_path, t, _rich(t)) for t in range(1, 8)}
    stack = F.load_frames(tmp_path, list(range(1, 8)), snaps=metas)
    tone, flat_n = F.compute_tone(stack)
    assert tone.n_sample == 7
    assert tone.hi > tone.lo
    assert tone.auto is True
    assert abs(float(flat_n.mean()) - 1.0) < 1e-4  # the vignette is normalised to mean 1


def test_compute_tone_refuses_a_degenerate_window(tmp_path: Path):
    """A constant frame has no window. Say so; do not divide by zero downstream."""
    m = {1: _meta(tmp_path, 1, np.full((H, W), 2000, np.uint16))}
    stack = F.load_frames(tmp_path, [1], snaps=m)
    with pytest.raises(ValueError, match="degenerate tone window"):
        F.compute_tone(stack)


def test_tone_lohi_reads_a_dataclass_or_a_dict(store: F.FrameStore):
    """A document's `tone` block is a plain dict; the session's is a `Tone`. One reader for both."""
    assert F.tone_lohi(store.tone) == (store.tone.lo, store.tone.hi)
    assert F.tone_lohi({"lo": 1.0, "hi": 2.0}) == (1.0, 2.0)
    assert F.tone_lohi(None) is None
    assert F.tone_lohi({"lo": 5.0, "hi": 5.0}) is None  # hi must exceed lo
    assert F.tone_lohi({"lo": 0.0, "hi": float("nan")}) is None


# =================================================================================================
# set_tone — the ONE mutation a FrameStore permits
# =================================================================================================
def test_set_tone_bumps_the_version_and_invalidates_every_display_cache(store: F.FrameStore):
    v0, png0, thumbs0 = store.tone.version, store.tile_png(1), store.thumbs()[0]

    store.set_tone(lo=1900.0, hi=2100.0)
    assert store.tone.version == v0 + 1
    assert store.tone.auto is False
    assert store.tile_png(1) != png0, "the tile cache did not invalidate — the pixels changed"
    assert store.thumbs()[0] != thumbs0, "the thumb cache did not invalidate"

    store.set_tone(auto=True)
    assert store.tone.auto is True
    assert store.tile_png(1) == png0, "auto must restore the MEASURED window, exactly"
    assert store.thumbs()[0] == thumbs0


def test_set_tone_refuses_hi_le_lo(store: F.FrameStore):
    """v1's tone route mutated the dataclass by hand and skipped this check entirely."""
    with pytest.raises(ValueError, match="hi must exceed lo"):
        store.set_tone(lo=9.0, hi=9.0)
    with pytest.raises(ValueError, match="hi must exceed lo"):
        store.set_tone(lo=100.0, hi=1.0)


def test_tone_NEVER_touches_the_matchers_input(store: F.FrameStore):
    """Tone is display-only. It never touches `band` (the matcher) or `frames` (the TIFF)."""
    band0 = store.band.copy()
    raw0 = store.frames.copy()
    store.set_tone(lo=1.0, hi=99.0)
    assert np.array_equal(store.band, band0)
    assert np.array_equal(store.frames, raw0)


def test_the_cache_buster_identifies_the_SESSION_not_just_the_tone(tmp_path: Path, snaps):
    """⭐ `?v={nonce}.{tone.version}`. `tone.version` is a dataclass default and **resets to 1 on
    every open**, while the pixels behind an `immutable, max-age=1yr` URL change. Two opens of the
    same directory must not produce the same `?v=`."""
    a = F.FrameStore.load(tmp_path, [1, 2, 3], snaps=snaps)
    b = F.FrameStore.load(tmp_path, [1, 2, 3], snaps=snaps)
    assert a.tone.version == b.tone.version == 1
    assert a.nonce != b.nonce
    assert a.version != b.version
    assert a.version == f"{a.nonce}.1"


# =================================================================================================
# The display path
# =================================================================================================
def test_tile_png_is_an_8_bit_png(store: F.FrameStore):
    png = store.tile_png(1)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    im = np.asarray(Image.open(BytesIO(png)))
    assert (im.shape, str(im.dtype)) == ((H, W), "uint8")


def test_tile_raw_round_trips_the_FLIPPED_frame_exactly(store: F.FrameStore):
    """RAW counts: no flat-field, no tone. Frames are float32 but hold integral counts, so the
    round-trip is exact."""
    b = store.tile_raw(1)
    assert len(b) == H * W * 2
    back = np.frombuffer(b, "<u2").reshape(H, W).astype(np.float32)
    assert np.array_equal(back, store.frame(1))


def test_thumbs_is_one_sprite_sheet_on_the_same_global_window(store: F.FrameStore):
    png, grid = store.thumbs(cell=16)
    assert grid == 2  # ceil(sqrt(3))
    sheet = np.asarray(Image.open(BytesIO(png)))
    assert sheet.shape == (2 * 16, 2 * 16)
    j = store.thumbs_json(cell=16)
    assert (j["grid"], j["cell"], j["n"], j["trials"]) == (2, 16, 3, [1, 2, 3])
    assert j["version"] == store.version


def test_a_frame_not_in_the_store_is_a_KeyError_not_a_wrong_frame(store: F.FrameStore):
    for call in (store.frame, store.banded, store.tile_png, store.tile_raw):
        with pytest.raises(KeyError):
            call(99)


# =================================================================================================
# The band stack + the texture measure
# =================================================================================================
def test_band_is_lazy_memoised_and_ONE_array_serves_both_consumers(store: F.FrameStore):
    """⭐ The matcher's DoG stack and the texture measure are the SAME array. Duplicate it and you
    pay +624 MiB; recompute it and you pay +3.0 s."""
    assert store._band is None
    b1 = store.band
    assert store.band is b1  # memoised: exactly one allocation
    assert np.array_equal(store.banded(2), F.band_pass_one(store.frame(2)))


def test_texture_is_the_band_stacks_per_frame_std(store: F.FrameStore):
    tex = store.texture()
    assert set(tex) == {1, 2, 3}
    for i, t in enumerate(store.trials):
        assert tex[t] == round(float(store.band[i].std()), 2)
    assert tex[3] < tex[1]  # the near-blank frame has less texture. That is all it says.


def test_texture_carries_NO_threshold_no_list_no_policy(store: F.FrameStore):
    """⛔ Core MEASURES. The mosaic feature PROPOSES. The human DECIDES. There is no
    `BLANK_THRESHOLD` in this module — 60.11 is one dataset's measured number and it is deleted."""
    assert not hasattr(F, "BLANK_THRESHOLD")
    assert not hasattr(F, "BLANK_PCT")
    assert not hasattr(F, "blank_scan")
    assert all(isinstance(v, float) for v in store.texture().values())


def test_texture_map_refuses_a_mismatched_trial_list(store: F.FrameStore):
    with pytest.raises(ValueError, match="trials but"):
        F.texture_map([1, 2], store.band)


# =================================================================================================
# ⭐ frame_note — DERIVED from this acquisition's XML, never asserted
# =================================================================================================
def test_frame_note_reports_what_the_reader_ACTUALLY_DID(tmp_path: Path):
    def note(**flips) -> str:
        metas = {t: _meta(tmp_path, t, _rich(t), **flips) for t in (1, 2)}
        return F.FrameStore.load(tmp_path, [1, 2], snaps=metas).frame_note

    assert "180deg-flipped" in note(flip_x=True, flip_y=True)
    assert "RAW sensor frame" in note(flip_x=False, flip_y=False)
    assert "horizontally-mirrored" in note(flip_x=True, flip_y=False)
    assert "vertically-mirrored" in note(flip_x=False, flip_y=True)


def test_frame_note_says_MIXED_rather_than_pick_one(tmp_path: Path):
    """A header that lies about its own coordinate frame is the one thing this project has been
    burned by. If the XMLs disagree, say so — do not average them."""
    metas = {
        1: _meta(tmp_path, 1, _rich(1), flip_x=True, flip_y=True),
        2: _meta(tmp_path, 2, _rich(2), flip_x=False, flip_y=False),
    }
    note = F.FrameStore.load(tmp_path, [1, 2], snaps=metas).frame_note
    assert "MIXED" in note


# =================================================================================================
# ⛔ THE STORE HOLDS NO ANALYSIS STATE
# =================================================================================================
def test_the_store_carries_no_analysis_state(store: F.FrameStore):
    """v1's `Session` carried `blank`, which a PUT route mutated and the matcher read — which made
    `POST /api/match/anchor` **not** a pure function of its request body. Do not give a future agent
    a place to put one."""
    for forbidden in ("blank", "excluded", "run", "pass_split", "gaps", "tiles", "cursor"):
        assert not hasattr(store, forbidden), f"FrameStore must not hold `{forbidden}`"
