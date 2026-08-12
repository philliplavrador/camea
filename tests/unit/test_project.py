"""A project is ONE FOLDER, and Camea owns it — the store, the guards, the slot rule, and finding a
project again cold.

His ruling, 2026-08-10 (R44): *"camea saves project-specific files to its own repo automatically"*.
The user names where the data comes **from**; the app answers where the project goes. These tests
pin the parts that would quietly cost him work if they drifted — the store's shape, the refusals,
the slot guard, and the two very different things `delete` does inside the store and outside it.
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
    store_folders,
    store_root,
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


def test_the_app_state_dir_is_exempt_from_the_repo_rule_ONLY(tmp_path, monkeypatch):
    """⭐ **The STORE lives in `app_state_dir()` (R44)**, which a dev install may put beside the
    checkout (the e2e harness puts it at `web/.playwright-state`). The repo rule protects HIS work
    from a `git clean`; the state dir is the app's by construction, so it is exempt — and under R44
    that exemption is the normal path, not an edge case. ⛔ The evidence rule is NOT exempted.

    (`tmp_path` stands in for the checkout so this never writes into the real repo.)"""
    monkeypatch.setattr("camea.core.project.repo_root", lambda: tmp_path)
    monkeypatch.setenv("CAMEA_STATE_DIR", str(tmp_path / "web" / ".state"))

    # inside the "repo", and refused — the rule still bites everywhere else
    with pytest.raises(PathRefused):
        Project.open(tmp_path / "my-project", create=True)

    # inside the "repo" AND inside the state dir — allowed: this is where the store IS
    pr = Project.open(tmp_path / "web" / ".state" / "projects" / "vm-1", create=True)
    assert pr.path.is_dir()

    # …and a dataset inside the state dir is STILL read-only, exemption or no exemption
    ds = tmp_path / "web" / ".state" / "an-acquisition"
    ds.mkdir(parents=True, exist_ok=True)
    (ds / "log.txt").write_text("trial 011\n", encoding="utf-8")
    (ds / "011.xml").write_text("<vsdscope/>", encoding="utf-8")
    with pytest.raises(DatasetIsReadOnly):
        Project.open(ds / "mosaic", create=True)


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
# delete, OUTSIDE the store — ⚠️ the folder is HIS, and we are not greedy with it
# =================================================================================================


def test_delete_removes_OUR_files_and_leaves_HIS_alone(tmp_path):
    """🔴 The careful path, and it is not dead code under R44: `core.migrate` meets pre-R44 folders
    the user named, and a project whose migration failed is left in one. A stray PDF of his notes in
    that folder must survive his deleting the project. (In the store, `delete` takes the whole
    folder — see `test_deleting_a_project_IN_THE_STORE_takes_the_whole_folder`.)"""
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


# =================================================================================================
# THE STORE — ⭐ where every project lives (R44, 2026-08-10)
# =================================================================================================


def test_create_in_store_names_the_folder_after_the_id(tmp_path, monkeypatch):
    """⭐ Nobody reads this path, so it does not have to be legible — it has to be **collision-free
    and stable**. The id IS the folder name, so two projects called the same thing are two folders,
    and a rename never has to move anything."""
    monkeypatch.setenv("CAMEA_STATE_DIR", str(tmp_path / "state"))

    a = Project.create_in_store(feature="mosaic", name="pass 1", dataset_key="k1", dataset="d")
    b = Project.create_in_store(feature="mosaic", name="pass 1", dataset_key="k1", dataset="d")

    assert a.path.parent == store_root()
    assert a.path.name == a.analysis_id
    assert a.analysis_id != b.analysis_id and a.path != b.path
    assert sorted(store_folders()) == sorted([a.path.as_posix(), b.path.as_posix()])


def test_the_store_is_the_index_and_it_is_read_fresh(tmp_path, monkeypatch):
    """⭐ `ProjectSet.of_store()` is built per call, so a project made in another tab (or by a second
    Camea) shows up without a restart. There is no remembered list to fall out of sync with — which
    is the whole reason `settings.projects` could be deleted."""
    monkeypatch.setenv("CAMEA_STATE_DIR", str(tmp_path / "state"))
    assert ProjectSet.of_store().analyses() == []

    pr = Project.create_in_store(feature="mosaic", name="p", dataset_key="k1", dataset="d")
    pr.save_document({"id": pr.analysis_id, "dataset_key": "k1"})

    found = ProjectSet.of_store().analyses()
    assert [a.analysis_id for a in found] == [pr.analysis_id]


def test_deleting_a_project_IN_THE_STORE_takes_the_whole_folder(tmp_path, monkeypatch):
    """⭐ **R44 retires R42.8's Remove-vs-Delete.** The folder is Camea's, made by Camea; everything
    in it is the project, outputs included. A project the app stops listing is one nobody could ever
    reach again, so half-deleting it would only accumulate unreachable bytes on his C: drive."""
    monkeypatch.setenv("CAMEA_STATE_DIR", str(tmp_path / "state"))
    pr = Project.create_in_store(feature="mosaic", name="p", dataset_key="k1", dataset="d")
    pr.save_document({"id": pr.analysis_id, "dataset_key": "k1"})
    (pr.outputs_dir / "mosaic.png").write_bytes(b"PNG")

    pr.delete()

    assert not pr.path.exists()
    assert store_folders() == []


# =================================================================================================
# move_to — ⭐ how a pre-R44 project comes home to the store (`core.migrate`)
# =================================================================================================


def test_a_project_moves_whole_and_drops_the_legacy_draft_flag(tmp_path):
    """The migration's mechanics: the whole project — document, artifacts, manifest — arrives at the
    destination, and R43's `draft` flag is dropped on the way in, because in the store there is no
    such thing as a project without a home."""
    pr = make(tmp_path, folder="old")
    # A pre-R44 draft, as R43 left it on disk. `Project.create` cannot make one any more — the flag
    # only ever arrives from a manifest an older Camea wrote, which is exactly what this simulates.
    man = json.loads(pr.manifest_path.read_text("utf-8")) | {"draft": True}
    pr.manifest_path.write_text(json.dumps(man), encoding="utf-8")
    # ⚠️ The artifact is declared in `build.outputs`. That is what makes it OURS to move — see
    # `own_entries()`: the document is the authority on the build's files, never a glob.
    pr.save_document({"id": pr.analysis_id, "dataset_key": "k1", "hello": "world",
                      "build": {"outputs": {"mosaic": "night sky.png"}}})
    (pr.path / "night sky.png").write_bytes(b"PNG")
    aid, was = pr.analysis_id, pr.path

    moved = pr.move_to(tmp_path / "store" / aid)

    assert moved.path == (tmp_path / "store" / aid).resolve()
    assert moved.analysis_id == aid, "the id survives the move — it is the addressing token"
    assert (moved.path / "night sky.png").read_bytes() == b"PNG"
    assert (moved.path / "document.camea.json").is_file()
    assert not was.exists(), "the old folder is not left behind as a husk"
    assert json.loads((moved.path / MARKER).read_text("utf-8")).get("draft") is None


def test_move_to_refuses_a_folder_that_already_holds_a_project(tmp_path):
    """A migration must never merge two projects into one folder — it refuses, and reports."""
    make(tmp_path, folder="taken", label="his real work")
    pr = make(tmp_path, folder="old")

    with pytest.raises(PathRefused, match="already holds the project"):
        pr.move_to(tmp_path / "taken")
    assert pr.path.is_dir(), "a refused move leaves the project exactly where it was"


def test_move_to_refuses_to_write_over_HIS_files(tmp_path):
    """⭐ `open` adopts a non-empty folder on purpose — but adopting is not overwriting, and this
    checks before a single byte moves."""
    pr = make(tmp_path, folder="old")
    pr.save_document({"id": pr.analysis_id, "dataset_key": "k1"})
    dest = tmp_path / "not empty"
    dest.mkdir()
    (dest / "document.camea.json").write_text("his notes", encoding="utf-8")

    with pytest.raises(PathRefused, match="document.camea.json"):
        pr.move_to(dest)
    assert (dest / "document.camea.json").read_text("utf-8") == "his notes"
    assert pr.document_path.is_file(), "nothing moved"


def test_move_to_adopts_a_non_empty_folder_that_does_not_clash(tmp_path):
    pr = make(tmp_path, folder="old")
    dest = tmp_path / "his stuff"
    dest.mkdir()
    (dest / "notes.pdf").write_bytes(b"%PDF")

    moved = pr.move_to(dest)

    assert (moved.path / "notes.pdf").is_file(), "his own file is left alone"
    assert (moved.path / MARKER).is_file()


def test_move_to_refuses_a_destination_inside_a_dataset(tmp_path):
    """`refuse_write`, verbatim — the app does not write on the evidence, whenever it is asked."""
    ds = tmp_path / "260620d"
    ds.mkdir()
    (ds / "log.txt").write_text("trial 011\n", encoding="utf-8")
    (ds / "011.xml").write_text("<vsdscope/>", encoding="utf-8")
    pr = make(tmp_path, folder="old")

    with pytest.raises(DatasetIsReadOnly):
        pr.move_to(ds / "mosaic")
    assert pr.path.is_dir()
