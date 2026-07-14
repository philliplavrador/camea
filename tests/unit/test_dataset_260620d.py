"""core.dataset against the REAL acquisition. Ported from `archive/app-v1/backend/loader.py`'s
`_selftest` (:1146-1191), which is 260 lines of genuinely good assertions that lived in a
`__main__` block nobody ran.

⚠️ **`slow` — it needs the 35 GB read-only mirror** (`CAMEA_DATA_DIR`, see `tests/conftest.py`), so
it is deselected by default and never runs in CI. It needs no GPU and no pixels: it parses log.txt
and 342 XMLs, and takes about a second.

    uv run pytest tests/unit/test_dataset_260620d.py -q -m slow

⛔ Hard-coding 260620d's numbers **in a test** is right; hard-coding them in `src/` is the thing the
user had ripped out at real cost. This file is the answer key, not the app.
"""
from __future__ import annotations

import pytest

from camea.core import dataset as ds

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def data(dataset_dir):
    return ds.open_dataset(dataset_dir)


# =============================================================================
# 1. log.txt
# =============================================================================
def test_the_log(data):
    assert data.experiment == "260620d"
    assert data.name == "260620d"
    assert len(data.snapshot_trials) == 342
    assert sorted({e.type for e in data.entries}) == ["E'phys. + VSD", "Snapshot"]
    assert data.entry(11).time == "2026-06-20T16:02:44Z"
    assert data.blocks() == [(1, 1), (5, 7), (11, 348)]
    assert data.longest_block() == (11, 348)


# =============================================================================
# 2. the inventory — ⛔ EVERY snapshot on disk. Nothing is dropped by trial number.
# =============================================================================
def test_every_snapshot_in_the_run_is_present_and_nothing_is_excluded(data):
    """⛔ **338, not 312.** The 26 the research tree throws out are *data* to this app: the human
    excludes them in the Screen step and the sweep, or he does not. Core has no opinion and no list.
    """
    in_run = [t for t in data.readable_trials if 11 <= t <= 348]
    assert len(in_run) == 338
    assert 284 in in_run and 348 in in_run and 300 in in_run  # the ones v1 hid. They are frames.
    assert ds.gaps(in_run) == []  # contiguous: nothing has been excluded


def test_the_run_is_all_one_shape_and_the_flip_is_read_off_the_xml(data):
    groups = data.shape_groups()
    assert [(g["w"], g["h"], g["n"]) for g in groups] == [(512, 512, 342)]
    metas = [data.meta(t) for t in data.readable_trials]
    assert all(m["flip_x"] and m["flip_y"] for m in metas)  # ax=-1, ay=-1 on all 342
    assert all(m["dtype"] == "uint16" and m["bytes"] == 2 for m in metas)


def test_the_two_frame_snapshot_is_not_a_frame(data):
    """Trial 008 is a 2-frame "snapshot". `frames != 1` never reaches a reader."""
    assert 8 not in data.snapshots


# =============================================================================
# 3. ⭐ THE TIMING SPLIT — 166, measured. Never t33's literal 166.
# =============================================================================
def test_the_timing_split_is_166_and_the_naive_rule_would_say_11(data):
    trials = [t for t in data.readable_trials if 11 <= t <= 348]
    split = data.timing_split(11, 348, trials)

    assert split.value == 166  # ⭐ the LAST TRIAL OF PASS 1, not 167. Never pass 167 to t33.
    assert split.detected is True
    assert split.gap_s == 20.0
    assert split.median_gap_s == 2.0
    assert split.runner_up == (234, 8.0)  # not the 13.0 s at step #2 — the min-side guard ate it
    assert split.decisive is True  # 20.0 / 8.0 = 2.5x
    assert (split.n_before, split.n_after) == (156, 182)  # 338 = 156 + 182

    # THE TRAP, demonstrated rather than trusted: 11->12 is ALSO 20.0 s (settling right after
    # `Settings loaded`), it TIES the true boundary, and a naive argmax takes the first of a tie.
    snaps = sorted([e for e in data.entries if e.type == ds.SNAPSHOT and 11 <= e.trial <= 348],
                   key=lambda e: e.trial)
    steps = [(a.trial, round((b.dt - a.dt).total_seconds(), 1)) for a, b in zip(snaps, snaps[1:])]
    assert max(steps, key=lambda s: s[1])[0] == 11  # ⛔ the naive answer, and it is WRONG.

    # And dropping only the first step is not enough either: step #2 is 13.0 s, a 1.54x margin.
    assert sorted(steps[1:], key=lambda s: -s[1])[1][1] == 13.0


# =============================================================================
# 4. identity + read-only
# =============================================================================
def test_the_store_key_is_the_folder_not_the_name(data, dataset_dir):
    assert data.key == ds.store_key(dataset_dir)
    assert data.key.startswith("260620d-")


def test_the_mirror_is_read_only(data, dataset_dir):
    with pytest.raises(ds.DatasetIsReadOnly):
        data.refuse_write(dataset_dir / "mosaic.tif")
    with pytest.raises(ds.DatasetIsReadOnly):
        data.refuse_write(dataset_dir / "sub" / "260620d.camea.json")
