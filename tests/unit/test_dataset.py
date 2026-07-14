"""core.dataset — the log grammar, the inventory, the timing split, and READ-ONLY.

Everything here runs on a **synthetic** dataset built in `tmp_path`: no data mirror, no pixels, no
GPU, milliseconds. The assertions that need the real 260620d numbers are in
`test_dataset_260620d.py` (marked `slow`, deselected by default).

The two tests that matter most are the ones that can only *fail*:

  * `test_the_settling_step_ties_the_true_break` — a naive argmax gets this **wrong**, and the
    wrong answer solves two scans against the wrong reference.
  * `test_opening_a_dataset_writes_nothing_into_it` + `test_no_write_verb_in_the_source` — a dataset
    is RAW. "We don't write to it" must be a thing that fails a build, not a thing we intend.
"""
from __future__ import annotations

import dataclasses
import io
import re
import tokenize
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from camea.core import dataset as ds

SRC = Path(ds.__file__)


def _code(path: Path) -> str:
    """The module's CODE, one logical line per line — **comments and string literals removed.**

    The source guards below scan for `open(` and for `EXCLUDED`, and `dataset.py`'s own docstrings
    say both words *in order to forbid them*. Scanning the raw text would trip over its own warning
    labels. So: tokenize, throw the prose away, and check what actually runs.
    """
    lines: dict[int, list[str]] = {}
    skip = {tokenize.COMMENT, tokenize.STRING, tokenize.NL, tokenize.NEWLINE,
            tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER}
    for tok in tokenize.generate_tokens(io.StringIO(path.read_text(encoding="utf-8")).readline):
        if tok.type not in skip:
            lines.setdefault(tok.start[0], []).append(tok.string)
    return "\n".join(" ".join(v) for _, v in sorted(lines.items()))

# =============================================================================
# a synthetic acquisition
# =============================================================================
_XML = """<?xml version="1.0"?>
<vsdscopeFile>
  <info type="{type}" trial="{trial:03d}" date="{date}" time="{time}"/>
  <ccd>
    <camera frames="{frames}" serpix="{w}" parpix="{h}" typebytes="2" type="uint16">
      <transform ax="{ax}" ay="{ay}"/>
    </camera>
  </ccd>
</vsdscopeFile>
"""

T0 = datetime(2026, 6, 20, 15, 47, 5)


def _trial_file(d: Path, trial: int, at: datetime, *, w=8, h=8, frames=1, ax=-1, ay=-1,
                dat_bytes: int | None = None, write_dat=True) -> None:
    (d / f"{trial:03d}.xml").write_text(
        _XML.format(type="snapshot", trial=trial, date=at.strftime("%y%m%d"),
                    time=at.strftime("%H%M%S"), frames=frames, w=w, h=h, ax=ax, ay=ay),
        encoding="utf-8")
    if write_dat:
        n = w * h * 2 if dat_bytes is None else dat_bytes
        (d / f"{trial:03d}-ccd.dat").write_bytes(b"\0" * n)


def make_dataset(root: Path, rows: list[tuple[int, str, datetime]], *, name="fake01", **kw) -> Path:
    """rows = [(trial, type, timestamp)]. Writes log.txt + one XML/.dat per Snapshot row."""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    lines = [f"{T0:%m/%d/%y} 15:46:58 New experiment: {name}",
             f"         {T0:%H:%M:%S} Settings loaded: 250712-mosaic"]
    for trial, ttype, at in rows:
        lines.append(f"         {at:%H:%M:%S} Trial {trial:03d}: {ttype}")
        if ttype == ds.SNAPSHOT:
            _trial_file(d, trial, at, **kw)
    (d / "log.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return d


def _serpentine(n=40, *, start=1, break_after=20) -> list[tuple[int, str, datetime]]:
    """Two scans of the same tissue, with 260620d's timing shape:

        step 0  (settling)      20 s   <- TIES the true break. A naive argmax takes THIS one.
        step 2  (still settling) 13 s
        the break               20 s
        one honest interior gap  8 s
        every other step         2 s
    """
    rows, t = [], T0
    for i in range(n):
        trial = start + i
        rows.append((trial, ds.SNAPSHOT, t))
        gap = 2
        if i == 0:
            gap = 20            # the settling tie
        elif i == 2:
            gap = 13            # still settling
        elif trial == break_after:
            gap = 20            # ⭐ the real break
        elif trial == break_after + 10:
            gap = 8             # the honest runner-up
        t = t + timedelta(seconds=gap)
    return rows


# =============================================================================
# log.txt
# =============================================================================
def test_parse_log_reads_the_experiment_the_types_and_the_times(tmp_path):
    d = make_dataset(tmp_path, [(1, ds.SNAPSHOT, T0),
                                (2, "E'phys. + VSD", T0 + timedelta(seconds=30)),
                                (3, ds.SNAPSHOT, T0 + timedelta(seconds=90))])
    experiment, entries = ds.parse_log(d / "log.txt")
    assert experiment == "fake01"
    assert [(e.trial, e.type) for e in entries] == [(1, "Snapshot"), (2, "E'phys. + VSD"),
                                                    (3, "Snapshot")]
    assert entries[0].time == "2026-06-20T15:47:05Z"       # ISO, UTC, `Z` — never `+00:00`


def test_gap_s_is_measured_between_SNAPSHOTS_only(tmp_path):
    """⚠️ A 2-minute E'phys trial in the middle is not a stage move. Letting it contribute a gap
    would hand the timing-split rule a spurious winner."""
    d = make_dataset(tmp_path, [(1, ds.SNAPSHOT, T0),
                                (2, "E'phys. + VSD", T0 + timedelta(seconds=30)),
                                (3, ds.SNAPSHOT, T0 + timedelta(seconds=90))])
    _, entries = ds.parse_log(d / "log.txt")
    assert [e.gap_s for e in entries] == [None, None, 90.0]   # 3 - 1 = 90 s, NOT 3 - 2 = 60 s


def test_the_date_carries_forward_and_rolls_over_at_midnight(tmp_path):
    """⚠️ The date appears ONLY on `New experiment:` lines. A missed rollover injects a -86,000 s
    gap, and the timing split is a *time-gap* rule."""
    d = tmp_path / "night"
    d.mkdir()
    (d / "log.txt").write_text(
        "06/20/26 23:59:00 New experiment: night\n"
        "         23:59:58 Trial 001: Snapshot\n"
        "         00:00:04 Trial 002: Snapshot\n", encoding="utf-8")
    _, entries = ds.parse_log(d / "log.txt")
    assert [e.time for e in entries] == ["2026-06-20T23:59:58Z", "2026-06-21T00:00:04Z"]
    assert entries[1].gap_s == 6.0                            # not -86,394


def test_snapshot_blocks_and_the_longest(tmp_path):
    rows = ([(1, ds.SNAPSHOT, T0)]
            + [(t, "E'phys. + VSD", T0) for t in (2, 3, 4)]
            + [(t, ds.SNAPSHOT, T0 + timedelta(seconds=t)) for t in (5, 6, 7)]
            + [(t, ds.SNAPSHOT, T0 + timedelta(seconds=t)) for t in range(11, 21)])
    d = make_dataset(tmp_path, rows)
    _, entries = ds.parse_log(d / "log.txt")
    assert ds.snapshot_blocks(entries) == [(1, 1), (5, 7), (11, 20)]
    assert ds.longest_block(ds.snapshot_blocks(entries)) == (11, 20)


# =============================================================================
# the trial XML — geometry, PER TRIAL
# =============================================================================
def test_read_trial_meta_parses_the_shape_and_the_CONDITIONAL_flip(tmp_path):
    d = tmp_path / "g"
    d.mkdir()
    _trial_file(d, 11, T0, w=512, h=512, ax=-1, ay=-1)
    _trial_file(d, 12, T0, w=512, h=512, ax=1, ay=1)
    a, b = ds.read_trial_meta(d / "011.xml"), ds.read_trial_meta(d / "012.xml")
    assert (a["w"], a["h"], a["dtype"], a["bytes"]) == (512, 512, "uint16", 2)
    assert (a["flip_x"], a["flip_y"]) == (True, True)
    assert (b["flip_x"], b["flip_y"]) == (False, False)       # ⭐ the flip is CONDITIONAL on ax/ay
    assert a["time"] == "2026-06-20T15:47:05Z"


def test_a_multi_frame_snapshot_is_rejected(tmp_path):
    """260620d's trial 008 is a 2-frame "snapshot". `frames != 1` is not a frame."""
    d = tmp_path / "g"
    d.mkdir()
    _trial_file(d, 8, T0, frames=2)
    assert ds.read_trial_meta(d / "008.xml") is None
    assert ds.list_snapshots(d) == {}


def test_shape_is_per_trial_and_an_off_shape_frame_is_NOT_dropped(tmp_path):
    """⛔ Core reports shapes. It does not gate on one — 512x512 is the MOSAIC feature's policy."""
    d = tmp_path / "g"
    d.mkdir()
    _trial_file(d, 20, T0, w=512, h=512)
    _trial_file(d, 21, T0, w=512, h=128)                      # the sibling dir's real 512x128 frame
    snaps = ds.list_snapshots(d)
    assert sorted(snaps) == [20, 21]                          # BOTH are in the inventory
    assert (snaps[21]["w"], snaps[21]["h"]) == (512, 128)


def test_a_frame_whose_dat_does_not_match_its_xml_is_not_an_inventory_entry(tmp_path):
    """A movie (375 frames in the .dat) fails the size check. So does a missing .dat."""
    d = tmp_path / "g"
    d.mkdir()
    _trial_file(d, 30, T0, w=8, h=8, dat_bytes=8 * 8 * 2 * 375)
    _trial_file(d, 31, T0, write_dat=False)
    _trial_file(d, 32, T0)
    assert sorted(ds.list_snapshots(d)) == [32]


# =============================================================================
# ⭐ THE TIMING SPLIT — measured, never 166
# =============================================================================
def test_the_settling_step_ties_the_true_break(tmp_path):
    """⭐⭐ THE TRAP. The block's FIRST step is also 20 s, and a naive argmax takes the first of a
    tie — returning the first trial of the run as "the split". Get this wrong and the two scans are
    solved against the wrong reference."""
    d = make_dataset(tmp_path, _serpentine(40, start=1, break_after=20))
    _, entries = ds.parse_log(d / "log.txt")

    # the trap is real: the naive rule picks step 0.
    snaps = [e for e in entries if e.type == ds.SNAPSHOT]
    steps = [(a.trial, (b.dt - a.dt).total_seconds()) for a, b in zip(snaps, snaps[1:])]
    assert max(steps, key=lambda s: s[1])[0] == 1             # ⛔ the naive answer. It is wrong.

    split = ds.detect_timing_split(entries, 1, 40, list(range(1, 41)))
    assert split.value == 20                                  # ⭐ the LAST TRIAL BEFORE THE BREAK
    assert split.detected is True
    assert split.gap_s == 20.0
    assert split.median_gap_s == 2.0
    assert split.runner_up == (30, 8.0)                       # the settling 13 s is excluded too
    assert split.decisive is True                             # 20 / 8 = 2.5x
    assert (split.n_before, split.n_after) == (20, 20)


def test_the_min_side_guard_excludes_the_whole_settling_prefix(tmp_path):
    """⚠️ Dropping only the FIRST step is not enough — step #2 (13 s) is still settling. The rule is
    physical: a real break splits the run into two substantial halves."""
    d = make_dataset(tmp_path, _serpentine(40))
    _, entries = ds.parse_log(d / "log.txt")
    split = ds.detect_timing_split(entries, 1, 40)
    assert split.value == 20
    assert split.runner_up is not None and split.runner_up[1] == 8.0   # not the 13 s at step #2


def test_a_run_too_short_to_split_says_so_and_does_not_guess(tmp_path):
    d = make_dataset(tmp_path, [(t, ds.SNAPSHOT, T0 + timedelta(seconds=2 * t)) for t in range(1, 4)])
    _, entries = ds.parse_log(d / "log.txt")
    split = ds.detect_timing_split(entries, 1, 3)
    assert split.value is None and split.detected is False
    assert "too few to split" in split.why


def test_a_weak_winner_is_reported_NOT_DECISIVE(tmp_path):
    d = make_dataset(tmp_path, _serpentine(40), name="weak")
    _, entries = ds.parse_log(d / "log.txt")
    # squeeze the winner down to 9 s against the 8 s runner-up by re-timing the break
    entries = [dataclasses.replace(e, dt=e.dt - timedelta(seconds=11)) if e.trial > 20 else e
               for e in entries]
    split = ds.detect_timing_split(entries, 1, 40)
    assert split.gap_s == 9.0 and split.decisive is False
    assert "NOT DECISIVE" in split.why


def test_the_split_counts_the_CALLERS_trial_list_not_everything_in_range(tmp_path):
    d = make_dataset(tmp_path, _serpentine(40))
    _, entries = ds.parse_log(d / "log.txt")
    split = ds.detect_timing_split(entries, 1, 40, trials=[5, 10, 25])
    assert (split.n_before, split.n_after) == (2, 1)


def test_a_gate_dropped_trial_still_counts_as_an_ACQUISITION_EVENT(tmp_path):
    """⚠️ The split is a rule about when the STAGE moved. A frame a feature's gate refuses was still
    a moment in time — leaving it out of the step list fabricates a pause that never happened."""
    d = make_dataset(tmp_path, _serpentine(40))
    _, entries = ds.parse_log(d / "log.txt")
    # trial 15 is "dropped" by the caller; the timestamps are untouched, so nothing moves.
    full = ds.detect_timing_split(entries, 1, 40)
    gated = ds.detect_timing_split(entries, 1, 40, trials=[t for t in range(1, 41) if t != 15])
    assert full.value == gated.value == 20
    assert full.gap_s == gated.gap_s == 20.0


# =============================================================================
# gaps — the ONE symbol from the exclusion module
# =============================================================================
def test_gaps_delegates_to_the_engine():
    from camea.engine import excluded
    assert ds.gaps([11, 12, 15, 16]) == list(excluded.gaps([11, 12, 15, 16])) == [(12, 15)]
    assert ds.gaps([11, 12, 13]) == []


def test_the_source_imports_gaps_AND_NOTHING_ELSE_from_the_exclusion_module():
    """⛔ THE APP CARRIES NO DATASET KNOWLEDGE. The source-level guard on the standing rule — the
    one that stops a well-meaning agent re-importing the 26-trial ruling "just for a default"."""
    code = _code(SRC)
    imports = re.findall(r"^from .*excluded import (.+)$", code, re.M)
    assert imports == ["gaps as _canonical_gaps"], imports
    for forbidden in ("EXCLUDED", "BLANK", "BLURRY", "usable_trials", "DATA_DIR"):
        assert not re.search(rf"\b{forbidden}\b", code), f"{forbidden} must never reach the app"


# =============================================================================
# identity
# =============================================================================
def test_store_key_separates_two_folders_with_the_same_name(tmp_path):
    """⚠️ Two directories both called `260620d` under different parents share the basename, the
    trial numbers and the config — so they collided on the identical t33 cache filename and the
    identical autosave slot, and `t33._load_checked` compares only the CONFIG."""
    a = tmp_path / "one" / "260620d"
    b = tmp_path / "two" / "260620d"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    assert ds.store_key(a) != ds.store_key(b)
    assert ds.store_key(a) == ds.store_key(a)                 # stable: the warm cache still works
    assert ds.store_key(a).startswith("260620d-")


# =============================================================================
# ⛔ READ-ONLY — enforced, not intended
# =============================================================================
def test_refuse_write_refuses_anything_inside_a_dataset(tmp_path):
    d = make_dataset(tmp_path, _serpentine(6))
    data = ds.open_dataset(d)
    for bad in (d, d / "out.tif", d / "sub" / "deep" / "x.json", d / ".." / d.name / "y"):
        with pytest.raises(ds.DatasetIsReadOnly):
            data.refuse_write(bad)
    data.refuse_write(tmp_path / "workspace" / "out.tif")      # outside: fine
    assert data.contains(d / "anything") is True
    assert data.contains(tmp_path / "elsewhere") is False


def test_opening_a_dataset_writes_nothing_into_it(tmp_path):
    """⭐ The strong form: open it, describe it, ask it everything — and the directory is
    byte-for-byte what it was, with no new file, no cache, no marker."""
    d = make_dataset(tmp_path, _serpentine(12))
    before = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in sorted(d.iterdir())}

    data = ds.open_dataset(d)
    data.detail()
    data.log_json()
    data.timing_split()
    data.gaps()
    data.shape_groups()

    after = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in sorted(d.iterdir())}
    assert after == before


def test_a_dataset_description_cannot_be_edited(tmp_path):
    data = ds.open_dataset(make_dataset(tmp_path, _serpentine(6)))
    with pytest.raises(dataclasses.FrozenInstanceError):
        data.experiment = "something else"                     # type: ignore[misc]


#: Every way this module could touch the disk in anger. `\bopen\s*\(` catches the builtin — and not
#: `open_dataset(`, which is a word-boundary miss. Whitespace-tolerant because `_code` re-joins the
#: token stream. ⚠️ If you need a new verb here, you are about to write into a dataset. Don't.
_WRITE_VERBS = [
    r"\bopen\s*\(",
    r"\.\s*write(_text|_bytes)?\s*\(",
    r"\bshutil\b",
    r"\bos\s*\.\s*(remove|unlink|rename|replace|makedirs|mkdir|rmdir|chmod|utime)\b",
    r"\.\s*(mkdir|touch|unlink|rmdir|rename|replace|chmod|tofile)\s*\(",
    r"\bnp\s*\.\s*(save|savez|savetxt)\b",
    r"\btempfile\b",
]


def test_no_write_verb_in_the_source():
    """⭐ THE GUARD THAT OUTLIVES US. A dataset is raw. If a future agent adds a write path to this
    module — a thumbnail cache, a `.camea` marker, a "small" index — this fails."""
    code = _code(SRC)
    for verb in _WRITE_VERBS:
        hits = [ln for ln in code.splitlines() if re.search(verb, ln)]
        assert hits == [], f"{verb}: core.dataset must never write. A DATASET IS RAW.\n{hits}"


# =============================================================================
# the Dataset object and the wire contract
# =============================================================================
def test_open_dataset_needs_a_log_and_a_frame(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError):
        ds.open_dataset(empty)                                 # no log.txt
    with pytest.raises(FileNotFoundError):
        ds.open_dataset(tmp_path / "nope")                     # no directory
    d = tmp_path / "logonly"
    d.mkdir()
    (d / "log.txt").write_text("06/20/26 15:46:58 New experiment: logonly\n", encoding="utf-8")
    (d / "001.xml").write_text("<not-xml", encoding="utf-8")
    with pytest.raises(ValueError):
        ds.open_dataset(d)                                     # log, but no readable snapshot


def test_a_snapshot_in_the_log_with_no_frame_on_disk_is_a_WARNING_not_an_exclusion(tmp_path):
    rows = _serpentine(8)
    d = make_dataset(tmp_path, rows)
    (d / "005.xml").unlink()
    (d / "005-ccd.dat").unlink()
    data = ds.open_dataset(d)
    assert any("no readable frame on disk" in w for w in data.warnings)
    assert 5 in data.snapshot_trials                           # ⛔ still a trial. Nothing acts on it.
    assert 5 not in data.readable_trials


def test_the_summary_and_detail_satisfy_the_api_contract(tmp_path):
    from camea.api import schemas

    d = make_dataset(tmp_path, _serpentine(24))
    data = ds.open_dataset(d)

    summary = schemas.DatasetSummary.model_validate(data.summary())
    assert summary.key == data.key and summary.name == "fake01"
    assert summary.experiment == "fake01"
    assert summary.n_trials == 24 and summary.n_snapshots == 24
    assert [(g.w, g.h, g.n) for g in summary.shapes] == [(8, 8, 24)]

    detail = schemas.DatasetDetail.model_validate(data.detail())
    assert [b.model_dump() for b in detail.blocks] == [{"lo": 1, "hi": 24, "n": 24}]
    assert len(detail.trials) == 24
    assert detail.trials[0].dat == "001-ccd.dat"
    assert detail.trials[0].flip_x is True

    log = schemas.LogResponse.model_validate(data.log_json())
    assert (log.n_snapshot, log.n_other) == (24, 0)


def test_trial_rows_report_every_trial_of_every_type(tmp_path):
    rows = [(1, ds.SNAPSHOT, T0), (2, "E'phys. + VSD", T0 + timedelta(seconds=10)),
            (3, ds.SNAPSHOT, T0 + timedelta(seconds=20))]
    data = ds.open_dataset(make_dataset(tmp_path, rows))
    got = {r["trial"]: r for r in data.trial_rows()}
    assert sorted(got) == [1, 2, 3]
    assert got[2]["type"] == "E'phys. + VSD" and got[2]["w"] is None    # no frame; still a trial
    assert got[3]["w"] == 8


# =============================================================================
# discovery
# =============================================================================
def test_scan_finds_the_datasets_under_a_folder_the_user_pointed_at(tmp_path):
    root = tmp_path / "drive"
    make_dataset(root / "260620" / "imaging", _serpentine(6), name="260620d")
    make_dataset(root / "260620" / "imaging", _serpentine(6), name="260620e")
    (root / "notes").mkdir(parents=True)
    (root / "notes" / "readme.txt").write_text("hi", encoding="utf-8")

    res = ds.scan(root, depth=4)
    assert [x.name for x in res.datasets] == ["260620d", "260620e"]
    assert res.skipped == []


def test_scan_does_not_descend_into_a_dataset(tmp_path):
    d = make_dataset(tmp_path, _serpentine(6))
    (d / "nested").mkdir()
    make_dataset(d / "nested", _serpentine(6), name="inner")
    res = ds.scan(tmp_path, depth=5)
    assert [x.name for x in res.datasets] == ["fake01"]


def test_scan_reports_what_it_could_not_read_instead_of_hiding_it(tmp_path):
    d = tmp_path / "broken"
    d.mkdir()
    (d / "log.txt").write_text("06/20/26 15:46:58 New experiment: broken\n", encoding="utf-8")
    (d / "001.xml").write_text("<not-xml", encoding="utf-8")
    res = ds.scan(tmp_path, depth=2)
    assert res.datasets == []
    assert len(res.skipped) == 1 and res.skipped[0]["path"].endswith("broken")
