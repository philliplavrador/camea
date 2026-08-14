"""The `mea` feature's API: create a project with its recordings on it, and manage that shelf.

⭐ **PLAN 001 SHIPPED THE PROJECT; PLAN 002 PUT SOMETHING ON IT.** The half of this file above the
`the shelf` banner is 001's and is still true — a project can be made from a name alone, and the
empty shelf is an ordinary state, because it is what he is left with once he removes the last
recording. Below the banner is 002: the wizard's Files step, the import, the background copy and
the two refusals that have to be *said* rather than swallowed.

⭐ **THE THREE THINGS BELOW THAT ARE WORTH THE MOST:**
- a bad path means **no project is created**, and the refusal names the file;
- removing a recording deletes **Camea's copy** and leaves his original exactly where it was;
- a recording whose original has moved says so, and does not come back as a row of zeros.

⛔ **No dataset knowledge.** Nothing here asserts a plate, a run, an expected spike rate or a
channel count as an app default. The numbers that do appear come from `tests/fixtures/measynth.py`,
whose chip is deliberately not a MaxWell — HARD RULE 3 permits fixture numbers inside `tests/` and
forbids them in the app.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from .conftest import err, store_dir, store_entries

pytest.importorskip("h5py")


@pytest.fixture()
def survey_video(tmp_path_factory, videosynth) -> str:
    """A tiny synthetic survey video — the *other* task's input, borrowed for the one test that
    puts a project of each kind in the same store."""
    d = tmp_path_factory.mktemp("mea_videos")
    videosynth.write_survey_video(d / "survey.avi", rows=2)
    return str(d / "survey.avi")


@pytest.fixture()
def session(tmp_path, measynth) -> list[str]:
    """A two-recording MaxLab session on disk, in a folder this test owns.

    ⚠️ Written per test rather than shared, because half of these tests **move or delete the
    original** to check what the shelf says about it. A session-scoped fixture would let one test's
    vandalism decide another's result."""
    return [p.as_posix() for p in measynth.write_session(tmp_path / "MEA")]


def _create(client, name: str = "chip 3693", paths: list[str] | None = None) -> dict:
    body: dict = {"name": name}
    if paths is not None:
        body["paths"] = paths
    r = client.post("/api/mea/projects", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _shelf(client, aid: str) -> list[dict]:
    r = client.get(f"/api/mea/{aid}/recordings")
    assert r.status_code == 200, r.text
    return r.json()["recordings"]


def _settled(client, aid: str, tries: int = 200) -> list[dict]:
    """The shelf once every copy has stopped moving. ⚠️ Polls rather than sleeps: the copy is a
    thread job and a fixed sleep is the flake this suite would get away with for a week."""
    import time

    for _ in range(tries):
        rows = _shelf(client, aid)
        if all(r["copy_state"] in ("stored", "failed") for r in rows):
            return rows
        time.sleep(0.02)
    raise AssertionError(f"copies never settled: {[r['copy_state'] for r in rows]}")


# ---- creation -----------------------------------------------------------------------------------
def test_create_takes_a_name_and_nothing_else(client, state_dir):
    """⭐ Name in, project out. It lands in Camea's store with a document on disk, and the only
    thing the caller had to know was what to call it."""
    a = _create(client)
    assert a["feature"] == "mea"
    assert a["name"] == "chip 3693"
    assert Path(a["folder"]).parent == store_dir(state_dir)

    folder = Path(a["folder"])
    assert sorted(p.name for p in folder.iterdir()) == [
        "camea-project.json", "document.camea.json",
    ], "a fresh mea project is a manifest and a document — nothing has been built yet"

    man = json.loads((folder / "camea-project.json").read_text("utf-8"))
    assert man["feature"] == "mea"


def test_the_document_is_an_empty_shelf(client):
    """The payload plan 002 grows into: `recordings: []`. ⭐ And **no `source`** — this project
    is not a wrapper around one file, so there is no single thing for it to point at."""
    a = _create(client)
    doc = client.get(f"/api/analyses/{a['analysis_id']}/document").json()["doc"]
    assert doc["feature"] == "mea"
    assert doc["recordings"] == []
    assert "source" not in doc


def test_nothing_here_came_from_a_machine(client):
    """⭐ This feature places nothing and proposes nothing, so its document is honestly
    independent and carries **no** provenance warning. A warning that cries wolf is one nobody
    reads (`core.document.stamp`). See `features/mea/document.py` for the full argument — and for
    when this answer must change."""
    a = _create(client)
    doc = client.get(f"/api/analyses/{a['analysis_id']}/document").json()["doc"]
    prov = doc["provenance"]
    assert prov["independent_of_method"] is True
    assert prov["seeded_from"] is None
    # ⚠️ On the wire `warning` is always a key (`schemas.Provenance` declares it), so `null` is the
    # assertion here. ON DISK it is genuinely absent, and that is the one `stamp()` guarantees.
    assert prov["warning"] is None
    on_disk = json.loads((Path(a["folder"]) / "document.camea.json").read_text("utf-8"))
    assert "warning" not in on_disk["provenance"]


def test_the_dataset_fields_are_empty_and_that_is_deliberate(client):
    """⭐ Plan 001 § Open, decided in the build: an `mea` project carries **`dataset_key=""`**.

    There is no dataset, so there is no address to mint a key for — and a blank key is what the
    slot guard and the scope guard both treat as "no opinion", which is what a project whose
    contents arrive later needs. See `features/mea/routes.py :: post_mea_project` for the whole
    reasoning, including what was read to reach it.
    """
    a = _create(client)
    assert a["dataset_key"] == ""
    assert a["dataset"] == ""
    assert a["data_dir"] == ""

    # ⭐ ...and the empty key does not poison anything that groups on it.
    listed = client.get("/api/projects").json()["analyses"]
    assert [x["analysis_id"] for x in listed if x["analysis_id"] == a["analysis_id"]]
    # a filter for a REAL dataset must not sweep this project up
    assert client.get("/api/projects?dataset_key=whatever").json()["analyses"] == []


def test_an_unnamed_project_still_has_a_name(client):
    """There is no filename to fall back to, so the fallback is a placeholder — never blank,
    because a blank card on the home screen is a project he cannot pick out."""
    r = client.post("/api/mea/projects", json={"name": "   "})
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "Untitled MEA project"

    # the field is optional altogether
    r2 = client.post("/api/mea/projects", json={})
    assert r2.status_code == 201, r2.text
    assert r2.json()["name"] == "Untitled MEA project"


def test_a_typo_is_a_422_not_a_silent_default(client):
    """`Req` is `extra="forbid"` — the whole contract rests on a client and a server that cannot
    drift apart quietly."""
    r = client.post("/api/mea/projects", json={"name": "x", "video_path": "/tmp/x.avi"})
    assert r.status_code == 422
    assert err(r)["code"] == "bad_request"


# ---- it is an ORDINARY project ------------------------------------------------------------------
def test_it_lists_renames_reopens_and_deletes_like_any_other_project(client):
    """⭐ The whole promise of the feature gate: a new task is a new `feature` string, and every
    core route the home screen drives already works on it."""
    a = _create(client, "before")
    aid = a["analysis_id"]

    listed = client.get("/api/projects").json()["analyses"]
    assert any(x["analysis_id"] == aid and x["feature"] == "mea" for x in listed)

    # opened by id — what the FeatureGate does on /project/:id
    got = client.get(f"/api/projects/{aid}").json()
    assert got["feature"] == "mea" and got["name"] == "before"

    r = client.patch(f"/api/projects/{aid}", json={"name": "after"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "after"
    assert client.get(f"/api/projects/{aid}").json()["name"] == "after"

    assert client.delete(f"/api/projects/{aid}").status_code == 200
    assert not any(x["analysis_id"] == aid
                   for x in client.get("/api/projects").json()["analyses"])
    assert store_entries() == []


def test_two_projects_of_two_tasks_live_side_by_side(client, survey_video):
    """A `mea` project and a `videomosaic` project in one store, each opening as itself. This is
    the thing plan 001 exists to make true, and the only test that checks both at once."""
    mea = _create(client, "electrical")
    r = client.post("/api/videomosaic/projects",
                    json={"name": "optical", "video_path": survey_video})
    assert r.status_code == 201, r.text
    vm = r.json()

    listed = {x["analysis_id"]: x["feature"] for x in
              client.get("/api/projects").json()["analyses"]}
    assert listed[mea["analysis_id"]] == "mea"
    assert listed[vm["analysis_id"]] == "videomosaic"

    # ⛔ and the video feature refuses to act on the mea one — the gate is the feature string
    b = client.post("/api/videomosaic/build", json={"analysis_id": mea["analysis_id"]})
    assert b.status_code == 409
    assert "not a video mosaic" in err(b)["message"]


# =================================================================================================
# THE SHELF — plan 002. Picking recordings at creation, the copy behind them, and the refusals.
# =================================================================================================


# ---- browse: the one route with no project ------------------------------------------------------
def test_browse_lists_every_recording_under_a_folder(client, session):
    """⭐ The route the WIZARD calls, before any project exists. It walks a folder and reports what
    is under it, with enough of each file's own facts to tell them apart."""
    root = Path(session[0]).parents[3]
    r = client.get("/api/mea/browse", params={"path": str(root)})
    assert r.status_code == 200, r.text
    body = r.json()

    labels = [x["label"] for x in body["recordings"]]
    assert labels == ["Network/000001", "Network/000002"]
    assert body["truncated"] is False
    for x in body["recordings"]:
        assert x["readable"] is True
        assert x["duration_s"] and x["n_channels"] and x["bytes"]


def test_browse_takes_no_project_id_and_writes_nothing(client, session):
    """⛔ **It must not be given a project "for consistency"** — the wizard has none yet, and a
    picker that mutates anything cannot be mounted there at all. Proved by the store staying empty
    across a browse, and by the browsed folder being byte-for-byte what it was."""
    root = Path(session[0]).parents[3]
    before = sorted((p.name, p.stat().st_size if p.is_file() else -1) for p in root.rglob("*"))
    assert client.get("/api/mea/browse", params={"path": str(root)}).status_code == 200
    assert store_entries() == [], "browsing created no project"
    after = sorted((p.name, p.stat().st_size if p.is_file() else -1) for p in root.rglob("*"))
    assert after == before, "browsing wrote nothing"


def test_browse_lists_an_unreadable_file_rather_than_dropping_it(client, tmp_path):
    """⭐ A `data.raw.h5` that does not open is **greyed, not gone**. Dropping it would make the
    folder look emptier than it is, and the one thing worse than a refusal is one he never saw."""
    d = tmp_path / "MEA" / "Network" / "000009"
    d.mkdir(parents=True)
    (d / "data.raw.h5").write_bytes(b"not an hdf5 file at all")

    body = client.get("/api/mea/browse", params={"path": str(tmp_path)}).json()
    assert len(body["recordings"]) == 1
    row = body["recordings"][0]
    assert row["readable"] is False
    assert row["problem"], "a refused row must say why"
    assert row["label"] == "000009", "it still names itself — not a bare path in a list of names"


def test_browse_on_a_folder_with_no_recordings_is_an_empty_list_not_an_error(client, tmp_path):
    """He pointed at the wrong folder. That is a fact about the folder, not a failure — the screen
    says there is nothing here and he browses on."""
    (tmp_path / "empty").mkdir()
    r = client.get("/api/mea/browse", params={"path": str(tmp_path / "empty")})
    assert r.status_code == 200
    assert r.json()["recordings"] == []


def test_browse_refuses_a_folder_that_is_not_there(client, tmp_path):
    r = client.get("/api/mea/browse", params={"path": str(tmp_path / "nowhere")})
    assert r.status_code == 400
    assert "no folder" in err(r)["message"]


# ---- create WITH recordings ---------------------------------------------------------------------
def test_create_with_paths_lands_the_recordings_on_the_shelf_in_one_call(client, session):
    """⭐ **THE HEADLINE OF PLAN 002.** *"You create the project then you select what you want to do
    ... then after that it asks you to upload the files you need for that task."* One call — there
    is never a moment where a project exists with nothing on it because a second call failed."""
    a = _create(client, "electrical", paths=session)
    rows = _shelf(client, a["analysis_id"])

    assert [r["label"] for r in rows] == ["Network/000001", "Network/000002"]
    assert [r["source_path"] for r in rows] == session
    for r in rows:
        assert r["id"] and r["id"] != r["source_path"], "the id is minted, never the path"
        assert r["missing"] is False
        assert r["n_spikes"] is not None


def test_a_path_that_is_not_a_recording_means_NO_PROJECT_and_names_the_file(client, session,
                                                                           tmp_path):
    """🔴 The refusal that has to be *said*. And the ordering that makes it cheap: every path is
    read **before** the project is created, so a bad one leaves nothing on the home screen for him
    to delete before he can try again."""
    bad = tmp_path / "MEA" / "Network" / "000009"
    bad.mkdir(parents=True)
    (bad / "data.raw.h5").write_bytes(b"nope")

    r = client.post("/api/mea/projects",
                    json={"name": "doomed", "paths": [session[0], str(bad / "data.raw.h5")]})
    assert r.status_code == 400
    assert "000009/data.raw.h5" in err(r)["message"], "the refusal NAMES the file"
    assert "not a MaxLab recording" in err(r)["message"]
    assert store_entries() == [], "⭐ no project was created, so there is nothing to clean up"


def test_create_with_no_paths_is_still_exactly_the_empty_shelf(client):
    """⚠️ The empty-shelf path is not a leftover — it is the project whose recordings he has all
    removed, and it is a `Done when` box of its own."""
    a = _create(client, "empty")
    assert _shelf(client, a["analysis_id"]) == []
    doc = client.get(f"/api/analyses/{a['analysis_id']}/document").json()["doc"]
    assert doc["recordings"] == []


# ---- the copy -----------------------------------------------------------------------------------
def test_the_copy_lands_inside_the_project_and_nowhere_else(client, session, state_dir):
    """⭐ *"Reference it until the copy is finished."* The recording is readable the instant it is
    added; a job pulls the bytes in behind it. ⛔ R44: the copy goes in `<project>/recordings/` and
    nothing is written anywhere else — asserted by listing the project folder EXACTLY."""
    a = _create(client, "copying", paths=session)
    folder = Path(a["folder"])
    rows = _settled(client, a["analysis_id"])

    assert [r["copy_state"] for r in rows] == ["stored", "stored"]
    for r in rows:
        assert r["stored_path"].startswith("recordings/")
        assert (folder / r["stored_path"]).is_file()
        assert (folder / r["stored_path"]).read_bytes() == Path(r["source_path"]).read_bytes()

    assert sorted(p.name for p in folder.iterdir()) == [
        "camea-project.json", "document.camea.json", "recordings",
    ]
    assert Path(a["folder"]).parent == store_dir(state_dir)


def test_a_recording_is_usable_before_its_copy_finishes(client, session):
    """⭐ The whole point of the answer he gave: the shelf reports the file's real numbers straight
    away, whether the copy has landed or not. The copy state changes; the recording does not."""
    a = _create(client, "immediate", paths=session)
    early = _shelf(client, a["analysis_id"])
    assert all(r["n_spikes"] is not None and r["missing"] is False for r in early)

    late = _settled(client, a["analysis_id"])
    assert [r["n_spikes"] for r in late] == [r["n_spikes"] for r in early]


def test_the_document_records_where_it_came_from_and_nothing_about_what_is_in_it(client, session):
    """⛔ I1, at the one place this feature could break it. A path is a path; a channel count is
    knowledge about the data, and it is read off the file every time instead of being written down.
    """
    a = _create(client, "i1", paths=session)
    _settled(client, a["analysis_id"])
    doc = client.get(f"/api/analyses/{a['analysis_id']}/document").json()["doc"]

    rec = doc["recordings"][0]
    assert set(rec) == {"id", "label", "run_id", "assay", "source_path", "stored_path",
                        "copy_state", "copy_error", "bytes", "added"}
    for banned in ("n_channels", "n_spikes", "n_samples", "duration_s", "channels", "stride",
                   "pitch_um", "electrodes"):
        assert banned not in rec, f"{banned} is a fact about the DATA and must not be stored"


# ---- adding from inside the project -------------------------------------------------------------
def test_add_recordings_from_inside_the_project(client, session):
    """The second door. Same work, same three functions — so the wizard and the button cannot
    drift apart."""
    a = _create(client, "grow")
    aid = a["analysis_id"]

    r = client.post(f"/api/mea/{aid}/recordings", json={"paths": [session[0]]})
    assert r.status_code == 201, r.text
    assert [x["label"] for x in r.json()["recordings"]] == ["Network/000001"]

    r2 = client.post(f"/api/mea/{aid}/recordings", json={"paths": [session[1]]})
    assert [x["label"] for x in r2.json()["recordings"]] == ["Network/000001", "Network/000002"]
    assert len({x["id"] for x in r2.json()["recordings"]}) == 2


def test_the_same_file_twice_is_two_rows_with_two_ids(client, session):
    """⚠️ `id` is minted, not derived from the path — so adding the same file again is a second row
    with its own copy, not a silent no-op. (A path is not an identity; it is where something was.)
    """
    a = _create(client, "twice", paths=[session[0], session[0]])
    rows = _settled(client, a["analysis_id"])
    assert len(rows) == 2
    assert rows[0]["id"] != rows[1]["id"]
    assert rows[0]["stored_path"] != rows[1]["stored_path"]


def test_adding_a_bad_path_adds_none_of_them_and_names_it(client, session, tmp_path):
    """All or nothing, the same rule as at creation — one rule he can state to himself beats two
    that differ by which door he came through."""
    a = _create(client, "strict", paths=[session[0]])
    aid = a["analysis_id"]
    (tmp_path / "notes.jpg").write_bytes(b"JPEG")

    r = client.post(f"/api/mea/{aid}/recordings",
                    json={"paths": [session[1], str(tmp_path / "notes.jpg")]})
    assert r.status_code == 400
    assert "notes.jpg is not a MaxLab recording" in err(r)["message"]
    assert len(_shelf(client, aid)) == 1, "the good one was not added either"


def test_the_shelf_refuses_a_project_of_another_task(client, survey_video):
    """The gate is the feature string, both ways round — 001 asserted the video route refusing an
    `mea` project; this is the mirror."""
    vm = client.post("/api/videomosaic/projects",
                     json={"name": "optical", "video_path": survey_video}).json()
    r = client.get(f"/api/mea/{vm['analysis_id']}/recordings")
    assert r.status_code == 409
    assert "not an Analyze MEA project" in err(r)["message"]


# ---- removing one -------------------------------------------------------------------------------
def test_removing_a_recording_deletes_OUR_copy_and_leaves_HIS_original(client, session):
    """🔴 **THE ONE THAT MUST NEVER REGRESS.** *"Forgets it and deletes Camea's copy. The user's
    original file is never touched."* No confirm box, because there is nothing of his to lose."""
    a = _create(client, "remove", paths=session)
    aid = a["analysis_id"]
    folder = Path(a["folder"])
    rows = _settled(client, aid)
    gone, kept = rows[0], rows[1]
    copy_was = folder / gone["stored_path"]
    assert copy_was.is_file()

    r = client.delete(f"/api/mea/{aid}/recordings/{gone['id']}")
    assert r.status_code == 200, r.text
    assert [x["id"] for x in r.json()["recordings"]] == [kept["id"]]

    assert not copy_was.exists(), "Camea's copy went"
    assert not copy_was.parent.exists(), "and so did its folder"
    assert Path(gone["source_path"]).is_file(), "⛔ HIS FILE IS STILL THERE"
    assert (folder / kept["stored_path"]).is_file(), "the other recording is untouched"


def test_removing_the_last_recording_leaves_a_working_empty_project(client, session):
    """The empty shelf he can get back to. It is the same screen 001 shipped, and its Add button
    still works."""
    a = _create(client, "back to empty", paths=[session[0]])
    aid = a["analysis_id"]
    rid = _shelf(client, aid)[0]["id"]

    assert client.delete(f"/api/mea/{aid}/recordings/{rid}").json()["recordings"] == []
    assert client.post(f"/api/mea/{aid}/recordings",
                       json={"paths": [session[1]]}).status_code == 201
    assert len(_shelf(client, aid)) == 1


def test_removing_something_that_is_not_there_is_a_404(client, session):
    a = _create(client, "404", paths=[session[0]])
    r = client.delete(f"/api/mea/{a['analysis_id']}/recordings/rec_nope")
    assert r.status_code == 404


def test_deleting_the_project_takes_the_recordings_with_it(client, session):
    """R44: in the store, delete means delete — the whole folder, copies included."""
    a = _create(client, "whole", paths=session)
    _settled(client, a["analysis_id"])
    folder = Path(a["folder"])

    assert client.delete(f"/api/projects/{a['analysis_id']}").status_code == 200
    assert not folder.exists()
    assert store_entries() == []
    assert all(Path(p).is_file() for p in session), "⛔ and his originals are still his"


# ---- the original moved -------------------------------------------------------------------------
def test_a_referenced_recording_whose_original_moved_says_so(client, session):
    """🔴 The second refusal that has to be *said*, not swallowed. A recording read from the
    original, with the original gone, is `missing` and carries **no numbers** — a row of zeros
    reads as a silent chip, which is a lie about his data."""
    a = _create(client, "moved", paths=[session[0]])
    aid = a["analysis_id"]
    _settled(client, aid)

    # The pre-copy state, staged: he moved the folder before the copy had landed.
    folder = Path(a["folder"])
    doc = json.loads((folder / "document.camea.json").read_text("utf-8"))
    doc["recordings"][0]["stored_path"] = ""
    doc["recordings"][0]["copy_state"] = "referenced"
    doc["recordings"][0]["source_path"] = "D:/somewhere/he/moved/it/data.raw.h5"
    (folder / "document.camea.json").write_text(json.dumps(doc), encoding="utf-8")

    row = _shelf(client, aid)[0]
    assert row["missing"] is True
    assert row["copy_state"] == "referenced"
    assert (row["n_spikes"], row["n_channels"], row["duration_s"]) == (None, None, None)
    assert row["label"] == "Network/000001", "it still knows what it was"


def test_a_stored_recording_survives_the_original_being_deleted(client, session):
    """⭐ Which is the whole reason the copy exists. Once it has landed, the project stops caring
    where the file came from."""
    a = _create(client, "self contained", paths=[session[0]])
    aid = a["analysis_id"]
    _settled(client, aid)

    Path(session[0]).unlink()

    row = _shelf(client, aid)[0]
    assert row["missing"] is False
    assert row["copy_state"] == "stored"
    assert row["n_spikes"] is not None
