"""A project is ONE FOLDER — the guards, the slot rule, and finding it again cold.

His ruling, 2026-07-25: a project names *where its data comes from* and *where it is saved*, and the
folder he names IS the project. These tests pin the parts that would quietly cost him work if they
drifted — the refusals, the slot guard, and the fact that `delete` is not greedy with a folder he
owns.
"""

from __future__ import annotations

import json

import pytest

from camea.core.dataset import DatasetIsReadOnly
from camea.core.project import (
    MARKER,
    NoSuchProject,
    Project,
    ProjectError,
    ProjectSet,
)
from camea.core.workspace import PathRefused, SlotMismatch, repo_root


def make(tmp_path, folder="p", label="a project", **kw):
    """One project in `tmp_path/<folder>`, called `label`. (The two are deliberately separate: the
    folder is what HE named on disk, the label is what the card shows — a rename changes only one.)
    """
    return Project.create(
        tmp_path / folder,
        feature=kw.pop("feature", "mosaic"),
        name=label,
        dataset_key=kw.pop("dataset_key", "k1"),
        dataset=kw.pop("dataset", "260620d"),
        data_dir=kw.pop("data_dir", "D:/data/260620d"),
        **kw,
    )


# =================================================================================================
# the layout
# =================================================================================================


def test_the_folder_he_named_IS_the_project(tmp_path):
    """⛔ No `analyses/<uuid>/` wrapper. He opens the folder in Explorer and sees his work."""
    pr = make(tmp_path)
    assert pr.path == (tmp_path / "p").resolve()
    assert (pr.path / MARKER).is_file()
    assert pr.document_path == pr.path / "document.camea.json"
    assert pr.autosave_path == pr.path / "autosave.camea.json"
    assert pr.autosave_path != pr.document_path  # the crash net is never the document


def test_the_manifest_carries_paths_and_labels_and_NO_dataset_knowledge(tmp_path):
    """⛔ HARD RULE 3. A dataset's path, name and key are a place and a label. A trial number, an
    exclusion or a threshold in here would be the app answering, on his behalf, the question it
    exists to help him answer."""
    pr = make(tmp_path)
    man = json.loads((pr.path / MARKER).read_text(encoding="utf-8"))
    assert man["dataset_key"] == "k1"
    assert man["data_dir"] == "D:/data/260620d"
    blob = str(man).lower()
    for forbidden in ("excluded", "blank", "blurry", "threshold", "pass_split", "trials"):
        assert forbidden not in blob, f"the manifest leaked {forbidden!r}: {man}"


# =================================================================================================
# ⛔ the refusals — at the one moment he names the place
# =================================================================================================


def test_a_project_inside_a_dataset_is_refused(tmp_path):
    """⛔ **THE APP DOES NOT WRITE ON THE EVIDENCE.** Recognised by SHAPE, never by name — so a
    folder the app was never told about is refused too."""
    ds = tmp_path / "some_acquisition"
    ds.mkdir()
    (ds / "log.txt").write_text("New experiment: x\n", encoding="utf-8")
    (ds / "001.xml").write_text("<x/>", encoding="utf-8")

    with pytest.raises(DatasetIsReadOnly):
        Project.open(ds / "work", create=True)
    with pytest.raises(DatasetIsReadOnly):
        Project.open(ds, create=True)


def test_a_project_inside_the_repo_is_refused():
    """It would be committed, `.gitignore`d, or blown away by a clean. His work is not our source."""
    root = repo_root()
    assert root is not None, "these tests run from the checkout"
    with pytest.raises(PathRefused):
        Project.open(root / "my-project", create=True)


def test_a_file_is_not_a_folder(tmp_path):
    f = tmp_path / "notes.txt"
    f.write_text("hi", encoding="utf-8")
    with pytest.raises(PathRefused):
        Project.open(f, create=True)


def test_creating_over_an_existing_project_is_REFUSED_not_silent(tmp_path):
    """🔴 Silently overwriting is how a day of sweeping disappears. The existing project is NAMED in
    the error, so he knows what he nearly lost."""
    make(tmp_path, folder="p", label="the first one")
    with pytest.raises(ProjectError, match="the first one"):
        make(tmp_path, folder="p", label="the second one")


def test_a_non_empty_folder_with_no_marker_is_ADOPTED_not_rejected(tmp_path):
    """He pointed at it deliberately. Refusing would only make him make another one beside it."""
    d = tmp_path / "mine"
    d.mkdir()
    (d / "notes.txt").write_text("my notes", encoding="utf-8")
    pr = make(tmp_path, folder="mine")
    assert pr.is_project()
    assert (d / "notes.txt").is_file()  # untouched


# =================================================================================================
# 🔴 the slot guard — the same rule as the workspace's, from the same implementation
# =================================================================================================


def test_the_slot_guard_refuses_someone_elses_document(tmp_path):
    """🔴 Pass 2's autosave once silently overwrote pass 1's ground-truth records. Not merged, not
    renamed, not "repaired" — refused."""
    pr = make(tmp_path)
    aid = pr.analysis_id

    pr.save_document({"id": aid, "dataset_key": "k1", "tiles": {}})  # its own: fine

    with pytest.raises(SlotMismatch):
        pr.save_document({"id": "somebody-else", "dataset_key": "k1"})
    with pytest.raises(SlotMismatch):
        pr.autosave({"id": aid, "dataset_key": "a-different-dataset"})


def test_the_autosave_lands_BESIDE_the_document_never_over_it(tmp_path):
    """Recovery must be able to show him both and let him choose."""
    pr = make(tmp_path)
    aid = pr.analysis_id
    pr.save_document({"id": aid, "dataset_key": "k1", "n": 1})
    pr.autosave({"id": aid, "dataset_key": "k1", "n": 2})

    assert json.loads(pr.document_path.read_text(encoding="utf-8"))["n"] == 1
    assert json.loads(pr.autosave_path.read_text(encoding="utf-8"))["n"] == 2
    rec = pr.recovery()
    assert rec is not None and rec["newer"] is True


# =================================================================================================
# delete — ⚠️ the folder is HIS, and we are not greedy with it
# =================================================================================================


def test_delete_removes_OUR_files_and_leaves_HIS_alone(tmp_path):
    """🔴 Under the old layout this was an `rmtree` of a uuid dir Camea made. The folder is now one
    HE named and may hold things we did not put there. A stray PDF of his notes must survive."""
    pr = make(tmp_path)
    pr.save_document({"id": pr.analysis_id, "dataset_key": "k1"})
    (pr.outputs_dir / "mosaic.tiff").write_bytes(b"II*\x00")
    stray = pr.path / "his-notes.pdf"
    stray.write_bytes(b"%PDF-1.4")

    pr.delete()

    assert not pr.document_path.exists()
    assert not (pr.path / "outputs").exists()
    assert not pr.manifest_path.exists()
    assert stray.is_file(), "deleting a project must not take his own files with it"
    assert pr.path.is_dir(), "...nor the folder they are in"


def test_delete_removes_the_folder_when_HE_left_nothing_in_it(tmp_path):
    pr = make(tmp_path)
    pr.save_document({"id": pr.analysis_id, "dataset_key": "k1"})
    pr.delete()
    assert not pr.path.exists()


# =================================================================================================
# the registry — finding a project again with no root scan to fall back on
# =================================================================================================


def test_the_set_finds_a_project_by_id_across_folders(tmp_path):
    a = make(tmp_path, folder="a", label="A", dataset_key="k1")
    b = make(tmp_path, folder="b", label="B", dataset_key="k2")
    ps = ProjectSet([a.path.as_posix(), b.path.as_posix()])

    assert ps.get(a.analysis_id).name == "A"
    assert ps.folder_of(b.analysis_id) == b.path
    assert {x.name for x in ps.analyses()} == {"A", "B"}
    assert set(ps.by_dataset()) == {"k1", "k2"}


def test_an_unknown_id_is_NoSuchProject_not_a_crash(tmp_path):
    ps = ProjectSet([make(tmp_path).path.as_posix()])
    with pytest.raises(NoSuchProject):
        ps.get("nobody")


def test_a_vanished_folder_is_SKIPPED_not_a_failure_of_the_listing(tmp_path):
    """One unplugged drive must cost him that project's card, never his home screen."""
    a = make(tmp_path, folder="a", label="A")
    ps = ProjectSet([a.path.as_posix(), (tmp_path / "gone").as_posix(),
                     "Z:/definitely/not/here"])
    assert [x.name for x in ps.analyses()] == ["A"]


def test_data_dirs_is_how_a_dataset_is_found_again_COLD(tmp_path):
    """⭐ There is no root registry to re-scan any more. A project records where its data was, so
    opening last week's project still works — without the app remembering anything ABOUT the data."""
    a = make(tmp_path, folder="a", data_dir="D:/data/260620d")
    b = make(tmp_path, folder="b", data_dir="D:/data/260621a")
    ps = ProjectSet([a.path.as_posix(), b.path.as_posix()])
    assert set(ps.data_dirs()) == {"D:/data/260620d", "D:/data/260621a"}


def test_rename_rewrites_the_manifest_and_the_folder_does_NOT_move(tmp_path):
    """⭐ An id is forever. A rename that moved the folder would break the slot guard, every path the
    document carries, and any Explorer window he has open on it."""
    pr = make(tmp_path, label="before")
    aid, where = pr.analysis_id, pr.path

    after = pr.rename("after")

    assert after.name == "after"
    assert after.analysis_id == aid
    assert pr.path == where and where.is_dir()
