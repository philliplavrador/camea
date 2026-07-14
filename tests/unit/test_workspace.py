"""The workspace: where analyses live, and the three things it exists to prevent.

Every test here is one of the failures in `core/workspace.py`'s docstring, made executable:

  1. writing on the raw evidence   -> `test_refuse_*`
  2. two writers destroying each other -> `test_atomic_*`, `test_concurrent_writers_*`
  3. one document overwriting another  -> `test_slot_guard_*`

plus the question the whole module exists to answer: *"which analyses exist for dataset X, and
when were they last touched?"*
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from camea.core import workspace as ws
from camea.core.workspace import DatasetIsReadOnly, PathRefused, SlotMismatch, Workspace


@pytest.fixture
def wsp(tmp_path: Path) -> Workspace:
    return Workspace.open(tmp_path / "camea-work")


def _doc(analysis_id: str, dataset_key: str = "260620d-abc123", **extra) -> dict:
    d = {
        "schema_version": "camea-document-1.0",
        "app": {"name": "Camea", "version": "0.2.0"},
        "id": analysis_id,
        "feature": "mosaic",
        "dataset": "260620d",
        "data_dir": "D:/data/260620d",
        "dataset_key": dataset_key,
        "created": "2026-07-14T10:00:00Z",
        "modified": "2026-07-14T10:00:00Z",
        "provenance": {"authored_by": "human", "independent_of_method": True},
    }
    d.update(extra)
    return d


def _fake_dataset(root: Path) -> Path:
    """A directory with a raw acquisition's SHAPE. It is not named 260620d and it does not have to
    be — the guard reads the shape, never the name."""
    d = root / "some-acquisition"
    d.mkdir(parents=True)
    (d / "log.txt").write_text("28/06/20 10:00:00 New experiment: whatever\n")
    (d / "011.xml").write_text("<vsdscopeSettings/>")
    (d / "011-ccd.dat").write_bytes(b"\0\0")
    return d


# =================================================================================================
# 1. ⛔ THE APP DOES NOT WRITE ON THE EVIDENCE
# =================================================================================================


def test_refuse_write_inside_the_repo_data_mirror():
    """`data/` is a 35 GB read-only rclone mirror. Nothing this app does ever lands in it."""
    root = ws.repo_root()
    assert root is not None, "the tests run from the checkout; repo_root() must find it"
    with pytest.raises(DatasetIsReadOnly):
        ws.refuse_write(root / "data" / "drive" / "260620" / "out.camea.json")


def test_refuse_write_inside_the_open_dataset(tmp_path: Path):
    ds = _fake_dataset(tmp_path)
    with pytest.raises(DatasetIsReadOnly):
        ws.refuse_write(ds / "mosaic.camea.json", dataset_dir=ds)


def test_refuse_write_inside_ANY_acquisition_folder_even_unnamed(tmp_path: Path):
    """⭐ The guard does not need to be TOLD which dataset is open. A `Save…` typed into any folder
    that holds a `log.txt` + `NNN.xml` is refused — including a nested subfolder of one."""
    ds = _fake_dataset(tmp_path)
    (ds / "results").mkdir()
    with pytest.raises(DatasetIsReadOnly):
        ws.refuse_write(ds / "results" / "mine.camea.json")  # no dataset_dir= passed


def test_refuse_write_allows_an_ordinary_folder(tmp_path: Path):
    assert ws.refuse_write(tmp_path / "out" / "x.json") == (tmp_path / "out" / "x.json").resolve()


def test_workspace_may_not_live_inside_the_repo():
    """The user's work is not the app's source tree. A workspace under the checkout gets committed,
    gitignored, or blown away by a clean."""
    root = ws.repo_root()
    with pytest.raises(PathRefused):
        Workspace.open(root / "my-analyses")


def test_workspace_may_not_live_inside_a_dataset(tmp_path: Path):
    ds = _fake_dataset(tmp_path)
    with pytest.raises(DatasetIsReadOnly):
        Workspace.open(ds / "analyses")


def test_safe_basename_refuses_traversal():
    assert ws.safe_basename(" 260620d_mosaic ") == "260620d_mosaic"
    for bad in ("", "..", "a/b", "a\\b", "C:x", "a?b", "  . "):
        with pytest.raises(ValueError):
            ws.safe_basename(bad)


# =================================================================================================
# create / open
# =================================================================================================


def test_open_creates_the_marker_and_the_analyses_dir(tmp_path: Path):
    w = Workspace.open(tmp_path / "work")
    assert (w.path / ws.MARKER).is_file()
    assert (w.path / ws.ANALYSES_DIR).is_dir()
    assert w.info() == {
        "path": ws._fwd(w.path),
        "exists": True,
        "writable": True,
        "n_analyses": 0,
    }


def test_open_adopts_an_existing_folder(tmp_path: Path):
    d = tmp_path / "existing"
    d.mkdir()
    (d / "notes.txt").write_text("mine")
    w = Workspace.open(d)
    assert (d / "notes.txt").read_text() == "mine"  # nothing is destroyed
    assert (w.path / ws.MARKER).is_file()


def test_open_no_create_refuses_a_missing_folder(tmp_path: Path):
    with pytest.raises(ws.WorkspaceError):
        Workspace.open(tmp_path / "nope", create=False)


def test_open_refuses_a_file(tmp_path: Path):
    f = tmp_path / "a-file"
    f.write_text("")
    with pytest.raises(PathRefused):
        Workspace.open(f)


def test_create_analysis_lays_out_the_folder(wsp: Workspace):
    a = wsp.create_analysis(
        feature="mosaic", name="Pass 1 (11-166)", dataset_key="k1", dataset="260620d"
    )
    assert a.analysis_id.startswith("pass-1-11-166-")
    assert a.dir.is_dir()
    assert (a.dir / ws.MANIFEST).is_file()
    assert a.path == a.dir / ws.DOCUMENT
    assert not a.path.exists()  # ⭐ no document until core.document authors one
    assert a.bytes == 0
    assert a.n_anchored is None  # honest: there is nothing to count yet


def test_create_analysis_twice_is_refused(wsp: Workspace):
    a = wsp.create_analysis(feature="mosaic", name="x", dataset_key="k", dataset="d")
    with pytest.raises(ws.WorkspaceError):
        wsp.create_analysis(
            feature="mosaic", name="x", dataset_key="k", dataset="d", analysis_id=a.analysis_id
        )


@pytest.mark.parametrize("bad", ["..", "../../Windows", "a/b", ".", "", "a\\b"])
def test_an_analysis_id_is_never_trusted(wsp: Workspace, bad: str):
    """`analysis_id` is a directory name and it arrives over HTTP."""
    with pytest.raises(ws.WorkspaceError):
        wsp.dir_of(bad)


def test_rename_does_not_move_the_directory(wsp: Workspace):
    a = wsp.create_analysis(feature="mosaic", name="first", dataset_key="k", dataset="d")
    b = wsp.rename(a.analysis_id, "second")
    assert b.name == "second"
    assert b.analysis_id == a.analysis_id  # ⭐ an id is forever: a bookmarked path keeps working
    assert b.dir == a.dir


# =================================================================================================
# 3. 🔴 ONE DOCUMENT MUST NEVER OVERWRITE ANOTHER
# =================================================================================================


def test_save_and_load_round_trip(wsp: Workspace):
    a = wsp.create_analysis(feature="mosaic", name="p1", dataset_key="k", dataset="260620d")
    doc = _doc(a.analysis_id, "k", tiles={"11": {"status": "anchor", "x": 0, "y": 0}})
    res = wsp.save_document(a.analysis_id, doc)

    assert Path(res["path"]) == a.path
    assert res["bytes"] == a.path.stat().st_size
    on_disk = json.loads(a.path.read_text(encoding="utf-8"))
    assert on_disk == doc  # ⚠️ the workspace writes what it is given. It does not "fix" a document.


def test_slot_guard_refuses_another_analysis_document(wsp: Workspace):
    """🔴 THE GUARD THAT WAS NEVER WIRED UP IN v1. Pass 2's autosave silently overwrote pass 1's
    ground-truth records. A document may only be written into the analysis it belongs to."""
    a = wsp.create_analysis(feature="mosaic", name="pass 1", dataset_key="k", dataset="d")
    b = wsp.create_analysis(feature="mosaic", name="pass 2", dataset_key="k", dataset="d")

    wsp.save_document(a.analysis_id, _doc(a.analysis_id, "k"))
    with pytest.raises(SlotMismatch):
        wsp.save_document(b.analysis_id, _doc(a.analysis_id, "k"))  # pass 1's doc into pass 2's slot
    with pytest.raises(SlotMismatch):
        wsp.autosave(b.analysis_id, _doc(a.analysis_id, "k"))

    assert not b.path.exists()  # refused means REFUSED — not merged, not renamed, not "repaired"


def test_slot_guard_refuses_a_document_from_another_dataset(wsp: Workspace):
    a = wsp.create_analysis(feature="mosaic", name="x", dataset_key="dataset-A", dataset="A")
    with pytest.raises(SlotMismatch):
        wsp.save_document(a.analysis_id, _doc(a.analysis_id, dataset_key="dataset-B"))


def test_two_ranges_of_one_dataset_cannot_collide(wsp: Workspace):
    """⭐ THE ROOT FIX. In v1 the autosave slot was keyed on the DATASET DIRECTORY, so two trial
    ranges of one dataset shared a filename — and pass 2 ate pass 1. Here they are two analyses,
    with two directories, and the collision is structurally impossible."""
    p1 = wsp.create_analysis(feature="mosaic", name="pass 1", dataset_key="k", dataset="260620d")
    p2 = wsp.create_analysis(feature="mosaic", name="pass 2", dataset_key="k", dataset="260620d")

    wsp.autosave(p1.analysis_id, _doc(p1.analysis_id, "k", trial_range=[11, 166]))
    wsp.autosave(p2.analysis_id, _doc(p2.analysis_id, "k", trial_range=[167, 348]))

    assert wsp.autosave_path(p1.analysis_id) != wsp.autosave_path(p2.analysis_id)
    a1 = json.loads(wsp.autosave_path(p1.analysis_id).read_text())
    assert a1["trial_range"] == [11, 166]  # still pass 1's. Untouched.


def test_autosave_never_writes_over_the_document(wsp: Workspace):
    a = wsp.create_analysis(feature="mosaic", name="x", dataset_key="k", dataset="d")
    wsp.save_document(a.analysis_id, _doc(a.analysis_id, "k", cursor=11))
    wsp.autosave(a.analysis_id, _doc(a.analysis_id, "k", cursor=99))

    assert json.loads(a.path.read_text())["cursor"] == 11  # the saved file is the user's
    assert json.loads(wsp.autosave_path(a.analysis_id).read_text())["cursor"] == 99


def test_recovery_reports_a_newer_autosave(wsp: Workspace):
    a = wsp.create_analysis(feature="mosaic", name="x", dataset_key="k", dataset="d")
    assert wsp.recovery(a.analysis_id) is None

    wsp.save_document(a.analysis_id, _doc(a.analysis_id, "k"))
    wsp.autosave(a.analysis_id, _doc(a.analysis_id, "k"))
    os.utime(wsp.autosave_path(a.analysis_id), (2e9, 2e9))  # an hour of sweeping, never saved

    r = wsp.recovery(a.analysis_id)
    assert r is not None and r["newer"] is True


def test_autosave_failure_is_loud(wsp: Workspace):
    """🔴 NEVER SWALLOWED. `localStorage` failed *silently* and nearly cost a day's work; that is
    why autosave is a server file at all."""
    a = wsp.create_analysis(feature="mosaic", name="x", dataset_key="k", dataset="d")
    with pytest.raises(ws.WorkspaceError):
        wsp.autosave(a.analysis_id, {"id": a.analysis_id, "bad": {1, 2}})  # a set is not JSON


# =================================================================================================
# 2. 🔴 ATOMIC WRITES
# =================================================================================================


def test_atomic_write_leaves_no_temp_files(tmp_path: Path):
    p = tmp_path / "d" / "x.json"
    ws.atomic_write_text(p, "hello\n")
    assert p.read_text() == "hello\n"
    assert [f.name for f in p.parent.iterdir()] == ["x.json"]  # the .camea-*.tmp is gone


def test_atomic_write_is_utf8_lf(tmp_path: Path):
    p = tmp_path / "x.json"
    ws.atomic_write_text(p, 'a\n"—"\n')
    assert p.read_bytes() == 'a\n"—"\n'.encode()  # LF, not CRLF, even on Windows


def test_concurrent_writers_do_not_destroy_each_other(tmp_path: Path):
    """🔴 On Windows two concurrent `os.replace` on one target give `WinError 5` and the loser's
    document was SILENTLY LOST (reproduced in v1: 4 concurrent autosaves -> 1 failed)."""
    p = tmp_path / "doc.json"
    errors: list[BaseException] = []

    def write(i: int) -> None:
        try:
            ws.atomic_write_text(p, json.dumps({"writer": i}) + "\n")
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=write, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    assert 0 <= json.loads(p.read_text())["writer"] < 8  # one whole winner; never a torn file


def test_dumps_refuses_a_non_serialisable_document_loudly():
    """⚠️ It does not stringify. t33's `info["config"]` holds a nested `t27.Config` and `json.dumps`
    crashes on it — the caller must run it through core's `jsonable()`, not have it papered over."""
    with pytest.raises(ws.WorkspaceError, match="jsonable"):
        ws.dumps({"config": object()})


# =================================================================================================
# ⭐ THE BROWSER'S QUESTION: which analyses exist for dataset X, and when were they last touched?
# =================================================================================================


def test_analyses_are_listed_by_dataset_newest_touch_first(wsp: Workspace):
    a = wsp.create_analysis(feature="mosaic", name="A", dataset_key="ds-1", dataset="one")
    b = wsp.create_analysis(feature="mosaic", name="B", dataset_key="ds-1", dataset="one")
    c = wsp.create_analysis(feature="mosaic", name="C", dataset_key="ds-2", dataset="two")

    for x in (a, b, c):
        wsp.save_document(x.analysis_id, _doc(x.analysis_id, x.dataset_key))
    os.utime(b.path, (2e9, 2e9))  # B was touched most recently

    assert [x.analysis_id for x in wsp.analyses("ds-1")] == [b.analysis_id, a.analysis_id]
    assert [x.analysis_id for x in wsp.analyses("ds-2")] == [c.analysis_id]

    idx = wsp.by_dataset()
    assert set(idx) == {"ds-1", "ds-2"}
    assert [x.name for x in idx["ds-1"]] == ["B", "A"]


def test_modified_tracks_the_AUTOSAVE_too(wsp: Workspace):
    """An hour of sweeping that was only ever autosaved is still an hour of work. A card that reads
    '3 days ago' because only the explicit save counted would be a lie about whether it is safe."""
    a = wsp.create_analysis(feature="mosaic", name="x", dataset_key="k", dataset="d")
    wsp.save_document(a.analysis_id, _doc(a.analysis_id, "k"))
    before = wsp.get(a.analysis_id).modified

    wsp.autosave(a.analysis_id, _doc(a.analysis_id, "k"))
    os.utime(wsp.autosave_path(a.analysis_id), (2e9, 2e9))
    assert wsp.get(a.analysis_id).modified > before


def test_a_corrupt_document_does_not_blank_the_browser(wsp: Workspace):
    good = wsp.create_analysis(feature="mosaic", name="good", dataset_key="k", dataset="d")
    bad = wsp.create_analysis(feature="mosaic", name="bad", dataset_key="k", dataset="d")
    wsp.save_document(good.analysis_id, _doc(good.analysis_id, "k"))
    bad.path.write_text("{ this is not json")

    listed = {x.analysis_id: x for x in wsp.analyses()}
    assert set(listed) == {good.analysis_id, bad.analysis_id}  # both still LIST
    assert listed[bad.analysis_id].warnings  # and the broken one says so
    assert listed[bad.analysis_id].n_anchored is None


def test_delete_removes_the_analysis_and_its_outputs(wsp: Workspace):
    a = wsp.create_analysis(feature="mosaic", name="x", dataset_key="k", dataset="d")
    wsp.save_document(a.analysis_id, _doc(a.analysis_id, "k"))
    (wsp.outputs_dir(a.analysis_id) / "mosaic.tiff").write_bytes(b"II*\0")

    wsp.delete(a.analysis_id)
    assert not a.dir.exists()
    assert wsp.analyses() == []
    with pytest.raises(ws.NoSuchAnalysis):
        wsp.delete(a.analysis_id)


# =================================================================================================
# THE FEATURE HOOKS — core counts tiles without knowing what a tile is
# =================================================================================================


def test_core_reports_no_counts_for_an_unregistered_feature(wsp: Workspace, monkeypatch):
    """⛔ Core must never grow an `if feature == "mosaic"`. With no hook registered it reports
    `None` — which is honest — and it never guesses."""
    monkeypatch.setattr(ws, "_FEATURES", {})
    a = wsp.create_analysis(feature="segmentation", name="x", dataset_key="k", dataset="d")
    wsp.save_document(a.analysis_id, _doc(a.analysis_id, "k", tiles={"11": {"status": "anchor"}}))
    got = wsp.get(a.analysis_id)
    assert (got.n_tiles, got.n_anchored, got.n_excluded) == (None, None, None)


def test_a_registered_feature_fills_the_card(wsp: Workspace, monkeypatch):
    monkeypatch.setattr(ws, "_FEATURES", {})
    ws.register_feature(
        "mosaic",
        counts=lambda d: {
            "n_tiles": len(d.get("tiles", {})),
            "n_anchored": sum(1 for t in d["tiles"].values() if t.get("status") == "anchor"),
            "n_excluded": sum(1 for t in d["tiles"].values() if t.get("status") == "excluded"),
        },
    )
    a = wsp.create_analysis(feature="mosaic", name="x", dataset_key="k", dataset="d")
    wsp.save_document(
        a.analysis_id,
        _doc(
            a.analysis_id,
            "k",
            tiles={
                "11": {"status": "anchor"},
                "12": {"status": "excluded"},
                "13": {"status": "unplaced"},
            },
        ),
    )
    got = wsp.get(a.analysis_id)
    assert (got.n_tiles, got.n_anchored, got.n_excluded) == (3, 1, 1)
    assert got.to_ref()["n_anchored"] == 1


def test_provenance_on_the_card_comes_from_HISTORY_not_self_declaration(wsp: Workspace, monkeypatch):
    """🔴 `independent_of_method` is WRITABLE, and "Skip — place from scratch" once erased
    `seeded_from` while every tile kept the solver's answer. **This project has already destroyed one
    benchmark exactly that way.** If the feature can see a machine in the document's history, its
    answer WINS over what the document claims about itself."""
    monkeypatch.setattr(ws, "_FEATURES", {})
    ws.register_feature(
        "mosaic",
        machine_evidence=lambda d: (
            {"method": "t33"} if any(t.get("machine") for t in d.get("tiles", {}).values()) else None
        ),
    )
    a = wsp.create_analysis(feature="mosaic", name="laundered", dataset_key="k", dataset="d")
    doc = _doc(a.analysis_id, "k", tiles={"11": {"status": "anchor", "machine": [0.0, 0.0]}})
    doc["provenance"]["independent_of_method"] = True  # ← the document's own claim. A lie.
    wsp.save_document(a.analysis_id, doc)

    assert wsp.get(a.analysis_id).independent_of_method is False


def test_a_broken_feature_hook_does_not_break_the_listing(wsp: Workspace, monkeypatch):
    monkeypatch.setattr(ws, "_FEATURES", {})

    def boom(_doc):
        raise RuntimeError("the mosaic feature is having a day")

    ws.register_feature("mosaic", counts=boom, machine_evidence=boom)
    a = wsp.create_analysis(feature="mosaic", name="x", dataset_key="k", dataset="d")
    wsp.save_document(a.analysis_id, _doc(a.analysis_id, "k"))

    got = wsp.get(a.analysis_id)
    assert got.n_anchored is None
    assert len(got.warnings) == 2
    assert got.independent_of_method is True  # fell back to the envelope's stamped verdict


# =================================================================================================
# app state — NOT the workspace
# =================================================================================================


def test_app_state_dir_is_not_the_workspace(tmp_path: Path, monkeypatch):
    """⭐ Settings live in %LOCALAPPDATA%. The user's WORK does not: in v1 the autosave went here,
    keyed on the dataset, and two trial ranges collided in it."""
    monkeypatch.setenv("CAMEA_STATE_DIR", str(tmp_path / "state"))
    d = ws.app_state_dir()
    assert d.is_dir() and d == tmp_path / "state"
