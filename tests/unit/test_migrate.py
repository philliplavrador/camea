"""The one-time launch migration into the store (R44, `core.migrate`).

🔴 **THIS IS THE MOST DANGEROUS CODE IN THE APP AFTER `Project.delete`.** It moves the user's real
work, unattended, before he has clicked anything, on the first launch after the change. Every test
here is about a way it could take or lose something it was not asked to.

His instruction was *"migrate it all if possible"* — so the happy path moves everything, and every
unhappy path leaves the project **exactly where it was** and says so.
"""

from __future__ import annotations

import json

import pytest

from camea.core.migrate import migrate_to_store
from camea.core.project import MARKER, Project, ProjectSet, store_folders, store_root


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    """Every test gets its own store. ⚠️ Set before anything asks for `app_state_dir()`."""
    monkeypatch.setenv("CAMEA_STATE_DIR", str(tmp_path / "state"))


def old_project(path, *, name="his work", feature="mosaic", aid=None, draft=False):
    """A project as R42/R43 left it: in a folder the USER named, outside the store."""
    pr = Project.create(path, feature=feature, name=name, dataset_key="k1", dataset="260620d",
                        data_dir="D:/data/260620d", analysis_id=aid)
    pr.save_document({"id": pr.analysis_id, "dataset_key": "k1", "tiles": {}})
    if draft:
        man = json.loads(pr.manifest_path.read_text("utf-8")) | {"draft": True}
        pr.manifest_path.write_text(json.dumps(man), encoding="utf-8")
    return pr


# =================================================================================================
# the happy path — ⭐ "migrate it all if possible"
# =================================================================================================


def test_it_moves_a_saved_project_into_the_store(tmp_path):
    pr = old_project(tmp_path / "my mosaics" / "pass 1", name="pass 1")
    aid, was = pr.analysis_id, pr.path

    report = migrate_to_store([was.as_posix()])

    assert [m["name"] for m in report.migrated] == ["pass 1"]
    assert report.failed == []
    assert not was.exists(), "the folder he named held only ours, so it goes"

    now = store_root() / aid
    assert now.is_dir() and (now / "document.camea.json").is_file()
    assert [a.analysis_id for a in ProjectSet.of_store().analyses()] == [aid]


def test_it_reports_where_each_project_came_from_and_went(tmp_path):
    """⚠️ Reported, never silent. A project that moved without saying so would be indistinguishable
    from one that vanished — and these are folders the user chose and can still open in Explorer."""
    pr = old_project(tmp_path / "old place", name="named")
    aid = pr.analysis_id                                # ⚠️ read BEFORE the manifest moves
    report = migrate_to_store([pr.path.as_posix()])

    entry = report.migrated[0]
    assert entry["from"] == (tmp_path / "old place").as_posix()
    assert entry["to"] == (store_root() / aid).as_posix()
    assert report.to_json()["migrated"] == report.migrated


def test_it_collects_a_leftover_R43_draft_too(tmp_path):
    """⭐ *"migrate it all"*. An R43 draft was an unsaved video build in `app_state_dir()/drafts/`,
    swept after 24 h. Under R44 it is simply a project, so it is **kept** — and the `draft` flag is
    dropped on the way in, because there is no such thing as a project without a home now."""
    d = store_root().parent / "drafts" / "vm-1"
    old_project(d, name="night sky", feature="videomosaic", aid="vm-1", draft=True)

    report = migrate_to_store([])                       # ⭐ found by the migrator, not passed in

    assert [m["name"] for m in report.migrated] == ["night sky"]
    man = json.loads((store_root() / "vm-1" / MARKER).read_text("utf-8"))
    assert "draft" not in man
    assert not d.exists()


def test_it_is_idempotent_and_a_second_launch_does_nothing(tmp_path):
    pr = old_project(tmp_path / "old", name="once")
    first = migrate_to_store([pr.path.as_posix()])
    assert len(first.migrated) == 1

    again = migrate_to_store([pr.path.as_posix()])
    assert again.migrated == [] and again.failed == []
    assert again.ran is False
    assert len(store_folders()) == 1


def test_a_project_already_in_the_store_is_skipped_not_moved_onto_itself(tmp_path):
    pr = Project.create_in_store(feature="mosaic", name="native", dataset_key="k1", dataset="d")
    report = migrate_to_store([pr.path.as_posix()])
    assert not report.ran
    assert pr.path.is_dir()


# =================================================================================================
# ⛔ what it must never take
# =================================================================================================


def test_it_leaves_the_users_own_files_where_they_are(tmp_path):
    """⛔ **NOTHING OF HIS IS TAKEN.** Only Camea's files move; his folder survives with his files
    in it. A thesis PDF he kept beside his mosaic is not the app's to relocate."""
    pr = old_project(tmp_path / "shared folder")
    (pr.path / "thesis.pdf").write_bytes(b"%PDF")
    (pr.path / "notes.txt").write_text("mine", encoding="utf-8")

    report = migrate_to_store([pr.path.as_posix()])

    assert len(report.migrated) == 1
    assert (tmp_path / "shared folder").is_dir(), "his folder stays — it is not empty"
    assert (tmp_path / "shared folder" / "thesis.pdf").is_file()
    assert (tmp_path / "shared folder" / "notes.txt").read_text("utf-8") == "mine"
    assert not (tmp_path / "shared folder" / MARKER).exists(), "…but ours left"


def test_a_folder_that_is_not_a_project_is_not_our_business(tmp_path):
    d = tmp_path / "just a folder"
    d.mkdir()
    (d / "photo.png").write_bytes(b"PNG")

    report = migrate_to_store([d.as_posix()])

    assert not report.ran
    assert (d / "photo.png").is_file()


def test_an_id_collision_is_REFUSED_and_the_original_is_left_alone(tmp_path):
    """⛔ **IT NEVER DESTROYS TO MAKE ROOM.** Two projects claiming one id is exactly the case where
    a silent overwrite would cost him a week of sweeping."""
    Project.create(store_root() / "twin", feature="mosaic", name="the one in the store",
                   dataset_key="k1", dataset="d", analysis_id="twin")
    pr = old_project(tmp_path / "outside", name="the one outside", aid="twin")
    (pr.path / "night sky.png").write_bytes(b"PNG")

    report = migrate_to_store([pr.path.as_posix()])

    assert report.migrated == []
    assert len(report.failed) == 1
    assert "twin" in report.failed[0]["reason"]
    assert pr.document_path.is_file(), "the project is still where it was, whole"
    assert (pr.path / "night sky.png").is_file()
    assert json.loads((store_root() / "twin" / MARKER).read_text("utf-8"))["name"] \
        == "the one in the store"


def test_an_unreachable_folder_is_reported_and_never_fails_the_launch(tmp_path):
    """⛔ **IT NEVER FAILS A LAUNCH.** An unplugged drive costs the user that project this time, and
    the migration will try again next launch."""
    good = old_project(tmp_path / "here", name="here")

    report = migrate_to_store(["Z:/unplugged/project", good.path.as_posix()])

    assert [m["name"] for m in report.migrated] == ["here"]
    assert report.failed == [], "a folder that is not a project at all is simply not our business"


def test_a_manifest_with_no_id_is_refused_rather_than_guessed(tmp_path):
    pr = old_project(tmp_path / "broken")
    man = json.loads(pr.manifest_path.read_text("utf-8"))
    del man["analysis_id"]
    pr.manifest_path.write_text(json.dumps(man), encoding="utf-8")

    report = migrate_to_store([pr.path.as_posix()])

    assert report.migrated == []
    assert "analysis_id" in report.failed[0]["reason"]
    assert pr.document_path.is_file()


def test_an_unreadable_manifest_is_reported_not_raised(tmp_path):
    pr = old_project(tmp_path / "corrupt")
    pr.manifest_path.write_text("{ this is not json", encoding="utf-8")

    report = migrate_to_store([pr.path.as_posix()])

    assert report.migrated == []
    assert len(report.failed) == 1
    assert pr.path.is_dir()


# =================================================================================================
# ⭐ the video feature's flat artifacts -> outputs/
# =================================================================================================


def _video_project(path, name="night sky"):
    """An R43 video project: artifacts FLAT in the folder, named after the project."""
    pr = Project.create(path, feature="videomosaic", name=name, dataset_key="v1",
                        dataset="survey.avi", data_dir="D:/videos")
    for suffix in (".png", "-preview.png", "-positions.csv", "-build.json"):
        (pr.path / f"{name}{suffix}").write_bytes(b"data")
    pr.save_document({
        "id": pr.analysis_id, "dataset_key": "v1",
        "build": {"outputs": {"mosaic": f"{name}.png", "preview": f"{name}-preview.png",
                              "positions": f"{name}-positions.csv", "build": f"{name}-build.json"}},
    })
    return pr


def test_flat_video_artifacts_are_collected_into_outputs(tmp_path):
    """⭐ R43.5 wrote them flat because that folder WAS the export. Under R44 nobody opens it, so
    every feature's built files belong in the one place the outputs browser reads."""
    pr = _video_project(tmp_path / "old video")
    aid = pr.analysis_id

    report = migrate_to_store([pr.path.as_posix()])
    assert len(report.migrated) == 1 and report.failed == []

    now = store_root() / aid
    assert sorted(p.name for p in (now / "outputs").iterdir()) == [
        "night sky-build.json", "night sky-positions.csv", "night sky-preview.png", "night sky.png",
    ]
    assert sorted(p.name for p in now.iterdir()) == [
        "camea-project.json", "document.camea.json", "outputs",
    ]
    # ⭐ `build.outputs` still holds bare FILENAMES — the values never needed to change, which is
    # why R43.7 (a recorded path would be a lie the moment the project moved) still holds.
    doc = json.loads((now / "document.camea.json").read_text("utf-8"))
    assert doc["build"]["outputs"]["mosaic"] == "night sky.png"


def test_only_files_THE_DOCUMENT_NAMES_are_swept_into_outputs(tmp_path):
    """⚠️ The document is the authority on which files are the build's, not a glob. A file of the
    user's that happens to sit beside them is not swept up."""
    pr = _video_project(tmp_path / "old video")
    aid = pr.analysis_id
    (pr.path / "my own screenshot.png").write_bytes(b"PNG")

    migrate_to_store([pr.path.as_posix()])

    assert (tmp_path / "old video" / "my own screenshot.png").is_file(), (
        "⛔ his file is not the app's to relocate — it stays in the folder he named")
    now = store_root() / aid
    assert not (now / "my own screenshot.png").exists()
    assert not (now / "outputs" / "my own screenshot.png").exists()


def test_a_mosaic_project_with_an_outputs_dir_is_left_as_it_is(tmp_path):
    """The dataset feature always wrote to `outputs/`. Migration must not disturb it."""
    pr = old_project(tmp_path / "old mosaic")
    aid = pr.analysis_id
    (pr.outputs_dir / "mosaic.tiff").write_bytes(b"II*\x00")

    migrate_to_store([pr.path.as_posix()])

    now = store_root() / aid
    assert (now / "outputs" / "mosaic.tiff").read_bytes() == b"II*\x00"
