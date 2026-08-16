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

from .conftest import err, run_job, store_dir, store_entries

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


def test_the_summary_counts_the_shelf_so_the_home_card_can_say_it(client, session):
    """⭐ **ISSUE 011.** The home card said *"No recordings yet"* over a shelf of five, because
    `AnalysisSummary` carried no count an MEA project fills. The feature's `counts` hook now puts
    the shelf's length in `n_tiles` — the summary's per-feature count slot, the mosaic's own
    precedent — **derived from the document when the summary is built, never stored** (the issue
    file is explicit). An empty shelf stays 0, which is the card's honest "No recordings yet"."""
    a = _create(client, "counted", paths=session)
    aid = a["analysis_id"]
    assert a["n_tiles"] == len(session) == 2

    listed = next(x for x in client.get("/api/projects").json()["analyses"]
                  if x["analysis_id"] == aid)
    assert listed["n_tiles"] == 2
    # The sweep words stay unset: this feature anchors nothing and excludes nothing.
    assert listed["n_anchored"] is None and listed["n_excluded"] is None

    # Remove one -> the summary follows the document, because nothing was stored beside it.
    rid = _shelf(client, aid)[0]["id"]
    assert client.delete(f"/api/mea/{aid}/recordings/{rid}").status_code == 200
    assert client.get(f"/api/projects/{aid}").json()["n_tiles"] == 1

    # ...and the genuinely empty shelf reports 0 — the state "No recordings yet" was written for.
    empty = _create(client, "born empty")
    assert empty["n_tiles"] == 0


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


# ---- renaming one -------------------------------------------------------------------------------
def test_renaming_a_recording_changes_the_LABEL_and_touches_no_file(client, session):
    """⭐ A rename is a fact about the ROW, never about the bytes. His original stays byte-for-byte
    where it was, Camea's copy stays at its id-keyed path, and only the document's `label` moves."""
    a = _create(client, "rename", paths=[session[0]])
    aid = a["analysis_id"]
    row = _settled(client, aid)[0]
    folder = Path(a["folder"])
    original = Path(row["source_path"])
    before = original.read_bytes()

    r = client.patch(f"/api/mea/{aid}/recordings/{row['id']}", json={"label": "chip 3693 day 12"})
    assert r.status_code == 200, r.text
    renamed = r.json()["recordings"][0]
    assert renamed["label"] == "chip 3693 day 12"
    assert renamed["id"] == row["id"], "the id is forever — a rename does not re-mint it"
    assert renamed["stored_path"] == row["stored_path"], "the copy did not move"

    assert original.read_bytes() == before, "⛔ HIS FILE IS UNTOUCHED"
    assert (folder / row["stored_path"]).is_file(), "and the copy is where it was"

    doc = client.get(f"/api/analyses/{aid}/document").json()["doc"]
    assert doc["recordings"][0]["label"] == "chip 3693 day 12"


def test_the_new_name_survives_a_reload_and_reaches_the_open_screen(client, session):
    """The label the shelf shows is the document's, so the rename holds across a fresh read — and
    the layout route names the recording the same way, so the two screens cannot disagree."""
    aid, rid = _opened(client, session, "rename sticks")
    assert client.patch(f"/api/mea/{aid}/recordings/{rid}",
                        json={"label": "day 12"}).status_code == 200

    assert _shelf(client, aid)[0]["label"] == "day 12"
    assert _layout(client, aid, rid)["label"] == "day 12"


def test_a_blank_name_is_refused_and_whitespace_is_trimmed(client, session):
    """A nameless row is one he cannot pick out of a list — refused, not silently kept."""
    a = _create(client, "blank", paths=[session[0]])
    aid = a["analysis_id"]
    rid = _shelf(client, aid)[0]["id"]

    r = client.patch(f"/api/mea/{aid}/recordings/{rid}", json={"label": "   "})
    assert r.status_code == 400
    assert err(r)["code"] == "bad_request"
    assert _shelf(client, aid)[0]["label"] == "Network/000001", "nothing changed"

    r2 = client.patch(f"/api/mea/{aid}/recordings/{rid}", json={"label": "  day 12  "})
    assert r2.status_code == 200
    assert r2.json()["recordings"][0]["label"] == "day 12"


def test_renaming_something_that_is_not_there_is_a_404(client, session):
    a = _create(client, "404 rename", paths=[session[0]])
    r = client.patch(f"/api/mea/{a['analysis_id']}/recordings/rec_nope", json={"label": "x"})
    assert r.status_code == 404


def test_rename_refuses_a_project_of_another_task(client, survey_video):
    vm = client.post("/api/videomosaic/projects",
                     json={"name": "optical", "video_path": survey_video}).json()
    r = client.patch(f"/api/mea/{vm['analysis_id']}/recordings/rec_x", json={"label": "x"})
    assert r.status_code == 409
    assert "not an Analyze MEA project" in err(r)["message"]


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


# =================================================================================================
# Plan 003 — opening one recording: the chip, what happened on it, and one pad's trace
# =================================================================================================
#
# ⭐ **THE FIXTURE WAS BUILT FOR THIS** (`tests/fixtures/measynth.py`): 21 routed channels of a
# 13 x 5 chip, channel 0 the busiest, and **the last routed channel deliberately silent** — so the
# live end and the dead end of the colour scale are both real, and a broken ramp cannot pass.
#
# ⛔ **AND THE CHIP IS NOT A MAXWELL.** 13 x 5 on a 12.5 µm pitch is no device, so nothing that
# hard-coded 220 / 17.5 could pass these.


def _opened(client, session, name: str = "chip map") -> tuple[str, str]:
    """A project with one recording on it, settled. -> `(analysis_id, recording_id)`."""
    a = _create(client, name, paths=[session[0]])
    aid = a["analysis_id"]
    return aid, _settled(client, aid)[0]["id"]


def _layout(client, aid: str, rid: str) -> dict:
    r = client.get(f"/api/mea/{aid}/recordings/{rid}/layout")
    assert r.status_code == 200, r.text
    return r.json()


def _activity(client, aid: str, rid: str) -> dict:
    r = client.get(f"/api/mea/{aid}/recordings/{rid}/activity")
    assert r.status_code == 200, r.text
    return r.json()


# ---- the chip ------------------------------------------------------------------------------------
def test_layout_draws_one_pad_per_ROUTED_channel_at_the_files_own_coordinates(client, session,
                                                                             measynth):
    """⭐ **THE HEADLINE OF PLAN 003.** One dot per routed pad, positioned by the file's own µm
    coordinates — not by a grid Camea guessed, and not one dot per pad *on the chip*.

    ⛔ A pad that was never routed is **absent**, not zero: it is the absence of a measurement, and
    drawing it would invent data. The fixture routes 21 of its 65 pads, so this is a real test."""
    aid, rid = _opened(client, session)
    lay = _layout(client, aid, rid)

    routed = measynth.routed()
    assert len(lay["pads"]) == len(routed) == 21
    assert len(lay["pads"]) < measynth.STRIDE * measynth.N_ROWS, "⛔ only the ROUTED pads"
    assert [p["channel"] for p in lay["pads"]] == [c for c, _ in routed]
    assert [p["electrode"] for p in lay["pads"]] == [e for _, e in routed]

    # Positions are the file's own, and they satisfy the numbering the file states.
    for pad in lay["pads"]:
        ex = pad["electrode"] % lay["stride"]
        ey = pad["electrode"] // lay["stride"]
        assert pad["x_um"] == pytest.approx(ex * lay["pitch_um"])
        assert pad["y_um"] == pytest.approx(ey * lay["pitch_um"])


def test_layout_derives_the_chip_geometry_and_does_not_assume_a_maxwell(client, session, measynth):
    """⭐ `stride`/`pitch_um` come from the file's own numbering, verified against every routed pad.

    ⚠️ And **not** from the routed spacing: this fixture routes every OTHER column, so the smallest
    routed gap is 25 µm against a true pitch of 12.5. Anything that measured the gap reports double
    and this goes red — which is the bug real data caught once already."""
    aid, rid = _opened(client, session)
    lay = _layout(client, aid, rid)
    assert lay["stride"] == measynth.STRIDE == 13
    assert lay["pitch_um"] == pytest.approx(measynth.PITCH_UM) == pytest.approx(12.5)


def test_layout_carries_the_header_facts_and_needs_no_decoder(client, session, measynth):
    """The recording's own numbers, beside the chip. ⭐ The fixture's raw stream is declared and
    never written — exactly what the real files look like through the published decoder — so this
    passing proves the chip map does not touch it."""
    aid, rid = _opened(client, session)
    lay = _layout(client, aid, rid)
    assert lay["label"] == "Network/000001"
    assert lay["n_channels"] == 21
    assert lay["sampling_hz"] == pytest.approx(measynth.FS_HZ)
    assert lay["duration_s"] == pytest.approx(60_000 / measynth.FS_HZ)   # 3.0 s
    assert lay["n_spikes"] > 0


def test_layout_says_whether_the_decoder_is_on_this_machine(client, session):
    """⭐ The same fact the videomosaic attach reports (`decoder_present`), computed the same way
    (`mearecording.plugin_present()`) — served with the layout so the open screen can say the
    waveform situation ONCE, before anyone clicks a pad. ⚠️ Asserted against this machine's own
    truth, not a hard-coded False: a machine with MaxLab Live installed must pass too."""
    from camea.core import mearecording as mr

    aid, rid = _opened(client, session)
    lay = _layout(client, aid, rid)
    assert lay["decoder_present"] is mr.plugin_present()


# ---- what happened on it -------------------------------------------------------------------------
def test_activity_is_one_row_per_pad_in_LAYOUT_ORDER(client, session):
    """⭐ The two routes are joined by ORDER as well as by channel, so the UI never has to guess."""
    aid, rid = _opened(client, session)
    lay, act = _layout(client, aid, rid), _activity(client, aid, rid)
    assert [p["channel"] for p in act["pads"]] == [p["channel"] for p in lay["pads"]]
    assert act["n_pads"] == len(lay["pads"])


def test_activity_counts_add_up_to_the_recordings_own_total(client, session):
    aid, rid = _opened(client, session)
    act = _activity(client, aid, rid)
    assert sum(p["n_spikes"] for p in act["pads"]) == act["n_spikes"] > 0
    # Every spike in this fixture is on a routed channel, so nothing is unplaced — and the field
    # says so with a zero rather than being absent.
    assert act["n_spikes_unplaced"] == 0


def test_spikes_on_no_shown_pad_are_counted_and_the_total_is_untouched(client, tmp_path, measynth):
    """🔴 **MAXWELL §7.6 — the number that was being printed wrong.** A real file's total counts
    every spike the detector logged; the pads' tally omits every spike on a channel outside the
    routed mapping (measured 22,367 vs 15,688 on one of his). The route must serve the difference
    explicitly, derived — and ⛔ must NOT reconcile the header by shrinking the file total, which
    §7.6 forbids by name."""
    p = measynth.write_recording(tmp_path / "MEA" / "P0000" / "Network" / "000009" / "data.raw.h5",
                                 unplaced=7)
    a = _create(client, "unplaced", paths=[p.as_posix()])
    aid = a["analysis_id"]
    rid = _shelf(client, aid)[0]["id"]

    act = _activity(client, aid, rid)
    placed = sum(q["n_spikes"] for q in act["pads"])
    assert act["n_spikes_unplaced"] == 7
    assert act["n_spikes"] == placed + 7, "the file total stays the file's own"
    # The layout header states the same file total — the two surfaces must not disagree.
    lay = _layout(client, aid, rid)
    assert lay["n_spikes"] == act["n_spikes"]


def test_activity_rate_is_spikes_per_second_of_this_recording(client, session):
    aid, rid = _opened(client, session)
    act = _activity(client, aid, rid)
    assert act["duration_s"] == pytest.approx(3.0)
    for pad in act["pads"]:
        assert pad["rate_hz"] == pytest.approx(pad["n_spikes"] / act["duration_s"])
    assert act["max_rate_hz"] == pytest.approx(max(p["rate_hz"] for p in act["pads"]))


def test_a_pad_that_heard_NOTHING_is_reported_as_zero_not_dropped(client, session):
    """🔴 **THE ONE THE CHIP MAP'S COLOURS DEPEND ON.** The fixture's last routed channel is
    deliberately silent. It must arrive as a pad with **0 spikes**, not be missing from the list —
    a dead pad is a measurement (the amplifier was there and heard nothing), and the screen has to
    be able to draw it unmistakably. If it were dropped it would look like a pad that was never
    routed, which is a different fact entirely."""
    aid, rid = _opened(client, session)
    lay, act = _layout(client, aid, rid), _activity(client, aid, rid)

    silent = [p for p in act["pads"] if p["n_spikes"] == 0]
    assert silent, "the fixture guarantees at least one"
    assert act["n_silent"] == len(silent)
    # It is on the chip too — it has a position, so the map can draw it.
    for pad in silent:
        assert any(q["channel"] == pad["channel"] for q in lay["pads"])
    assert all(p["rate_hz"] == 0.0 for p in silent)


def test_activity_with_a_window_counts_only_that_stretch_and_says_so(client, session):
    """⭐ **"Colours follow the view" (2026-08-16).** With `t0`/`t1` the same tally covers only
    `[t0, t1)`: the reply names the served window, `duration_s` becomes what the rates were
    divided by (MAXWELL §7.3 — the UI must put THAT length beside a windowed silent count), and
    the two halves of a recording sum, pad for pad, to the whole of it. The file's own total is
    untouched by the window."""
    aid, rid = _opened(client, session)
    whole = _activity(client, aid, rid)

    r = client.get(f"/api/mea/{aid}/recordings/{rid}/activity", params={"t0": 0.0, "t1": 1.5})
    assert r.status_code == 200, r.text
    first = r.json()
    assert (first["t0_s"], first["t1_s"]) == (0.0, 1.5)
    assert first["duration_s"] == pytest.approx(1.5)
    for pad in first["pads"]:
        assert pad["rate_hz"] == pytest.approx(pad["n_spikes"] / 1.5)
    assert first["n_silent"] == sum(1 for p in first["pads"] if p["n_spikes"] == 0)
    assert first["max_rate_hz"] == pytest.approx(max(p["rate_hz"] for p in first["pads"]))

    # `t0` alone is a window too — the end clamps to the recording, and says so.
    r = client.get(f"/api/mea/{aid}/recordings/{rid}/activity", params={"t0": 1.5})
    assert r.status_code == 200, r.text
    second = r.json()
    assert second["t0_s"] == 1.5
    assert second["t1_s"] == pytest.approx(whole["duration_s"])

    for a, b, w in zip(first["pads"], second["pads"], whole["pads"], strict=True):
        assert a["channel"] == b["channel"] == w["channel"]
        assert a["n_spikes"] + b["n_spikes"] == w["n_spikes"]
    assert first["n_spikes"] == second["n_spikes"] == whole["n_spikes"]


def test_activity_without_a_window_is_exactly_what_it_always_was(client, session):
    """⛔ The whole-recording tally is the contract every existing caller relies on: no window
    fields set, `duration_s` the recording's own, counts identical to before the params existed."""
    aid, rid = _opened(client, session)
    act = _activity(client, aid, rid)
    assert act["t0_s"] is None and act["t1_s"] is None
    assert act["duration_s"] == pytest.approx(3.0)


def test_an_empty_activity_window_is_refused_not_zeroed(client, session):
    """An empty window answered with zeros would render a uniformly quiet chip — the exact
    laundering MAXWELL exists to prevent. Refused by name, the trace route's own rule."""
    aid, rid = _opened(client, session)
    r = client.get(f"/api/mea/{aid}/recordings/{rid}/activity", params={"t0": 2.0, "t1": 1.0})
    assert r.status_code == 422
    assert err(r)["code"] == "refused"
    # A window entirely past the end of the recording is empty too, not invented.
    r = client.get(f"/api/mea/{aid}/recordings/{rid}/activity", params={"t0": 99.0})
    assert r.status_code == 422


def test_the_scale_is_the_recordings_own_and_nothing_declares_a_maximum(client, session):
    """⛔ **I1.** `max_rate_hz` is the busiest pad in THIS file — the two fixture recordings have
    different spike tables (different seeds), so if anything had baked a scale in, these two would
    agree and they must not."""
    a = _create(client, "two", paths=session)
    aid = a["analysis_id"]
    rows = _settled(client, aid)
    one = _activity(client, aid, rows[0]["id"])
    two = _activity(client, aid, rows[1]["id"])
    assert one["max_rate_hz"] > 0 and two["max_rate_hz"] > 0
    assert (one["n_spikes"], one["max_rate_hz"]) != (two["n_spikes"], two["max_rate_hz"])


# ---- one pad's trace -----------------------------------------------------------------------------
def test_trace_is_asked_for_BY_CHANNEL_and_names_its_electrode(client, session):
    """⭐ By channel, because the click already knows its channel — the chip map was drawn from the
    file's own coordinates, so there is nothing to resolve. ⛔ And no `orientation` anywhere on the
    payload: there is no microscope in this task and no seating to be provisional about."""
    aid, rid = _opened(client, session)
    lay = _layout(client, aid, rid)
    pad = lay["pads"][0]

    r = client.get(f"/api/mea/{aid}/recordings/{rid}/trace",
                   params={"channel": pad["channel"], "t0": 0.0, "t1": 1.0})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["recorded"] is True
    assert body["channel"] == pad["channel"]
    assert body["electrode"] == pad["electrode"]
    assert (body["x_um"], body["y_um"]) == (pad["x_um"], pad["y_um"])
    assert "orientation" not in body and "chip_electrode" not in body


def test_trace_returns_the_spikes_even_though_the_waveform_did_not_decode(client, session):
    """🔴 **THE POINT OF THE WHOLE SCREEN.** The fixture's raw stream is declared and never written,
    which is exactly what the real recordings look like through the published MaxWell decoder. The
    waveform must come back flagged `flat` — and the spike ticks must come back **correct anyway**,
    because the on-chip detector wrote them uncompressed."""
    aid, rid = _opened(client, session)
    lay = _layout(client, aid, rid)
    busiest = lay["pads"][0]["channel"]                      # the fixture makes channel 0 busiest

    r = client.get(f"/api/mea/{aid}/recordings/{rid}/trace",
                   params={"channel": busiest, "t0": 0.0, "t1": 3.0})
    body = r.json()
    assert body["health"] is not None
    assert body["health"]["flat"] is True, "⛔ it must SAY the waveform is not usable"
    assert body["n_spikes_total"] > 0, "⭐ and the spikes are right regardless"
    assert len(body["spikes"]) > 0
    assert all(0.0 <= s["t_s"] < 3.0 for s in body["spikes"])


def test_trace_window_is_clamped_and_first_spike_points_somewhere_worth_looking(client, session):
    aid, rid = _opened(client, session)
    lay = _layout(client, aid, rid)
    ch = lay["pads"][0]["channel"]

    # t1 past the end of the recording is clipped to the recording, never invented.
    r = client.get(f"/api/mea/{aid}/recordings/{rid}/trace", params={"channel": ch, "t1": 9999})
    body = r.json()
    assert body["t1_s"] == pytest.approx(body["duration_s"]) == pytest.approx(3.0)
    assert body["first_spike_s"] is not None
    assert 0.0 <= body["first_spike_s"] <= body["duration_s"]

    # An empty window is refused rather than answered with an empty chart.
    r = client.get(f"/api/mea/{aid}/recordings/{rid}/trace",
                   params={"channel": ch, "t0": 2.0, "t1": 1.0})
    assert r.status_code == 422
    assert err(r)["code"] == "refused"


def test_trace_of_a_channel_that_was_never_routed_is_a_FACT_not_an_error(client, session):
    """⭐ *"never recorded"* is the ordinary answer on a MaxWell — ~1k pads of tens of thousands are
    routed. The chip map only draws routed pads so a click cannot normally land here, but a stale
    URL can, and it must read as a fact about the experiment rather than a 404."""
    aid, rid = _opened(client, session)
    r = client.get(f"/api/mea/{aid}/recordings/{rid}/trace", params={"channel": 9999})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["recorded"] is False
    assert body["trace_uv"] == [] and body["spikes"] == []
    assert body["electrode"] is None


# ---- which file gets read, and what happens when there is none -----------------------------------
def test_all_three_routes_read_the_PROJECTS_OWN_COPY_once_it_has_landed(client, session):
    """⭐ **`recordings.open_path` IS THE ONE PLACE THAT DECIDES**, and all three of these call it.
    Once the copy has landed, deleting his original changes nothing at all — which is exactly what
    would break if a route had decided for itself and gone on reading `source_path`."""
    aid, rid = _opened(client, session)
    before = (_layout(client, aid, rid), _activity(client, aid, rid))

    Path(session[0]).unlink()                                # his original goes; the copy remains

    assert _layout(client, aid, rid) == before[0]
    assert _activity(client, aid, rid) == before[1]
    r = client.get(f"/api/mea/{aid}/recordings/{rid}/trace", params={"channel": 0})
    assert r.status_code == 200, r.text


def test_a_recording_with_no_file_at_either_address_is_refused_BY_NAME(client, session):
    """🔴 Never an empty chip map. A recording read from the original, with the original gone, has
    nothing to draw — and the refusal has to say *which* recording and *where* it looked."""
    a = _create(client, "moved", paths=[session[0]])
    aid = a["analysis_id"]
    _settled(client, aid)

    folder = Path(a["folder"])
    doc = json.loads((folder / "document.camea.json").read_text("utf-8"))
    rid = doc["recordings"][0]["id"]
    doc["recordings"][0]["stored_path"] = ""
    doc["recordings"][0]["copy_state"] = "referenced"
    doc["recordings"][0]["source_path"] = "D:/somewhere/he/moved/it/data.raw.h5"
    (folder / "document.camea.json").write_text(json.dumps(doc), encoding="utf-8")

    for route in ("layout", "activity"):
        r = client.get(f"/api/mea/{aid}/recordings/{rid}/{route}")
        assert r.status_code == 409, (route, r.text)
        assert err(r)["code"] == "refused"
        assert "Network/000001" in err(r)["message"]
        assert "somewhere/he/moved/it" in err(r)["message"]


def test_an_unknown_recording_id_is_a_404_on_every_route(client, session):
    aid, _rid = _opened(client, session)
    for route in ("layout", "activity", "trace?channel=0"):
        r = client.get(f"/api/mea/{aid}/recordings/rec_nope/{route}")
        assert r.status_code == 404, (route, r.text)


def test_these_routes_refuse_a_project_of_another_task(client, survey_video):
    """The feature string on the manifest is the gate, the same way every other shelf route is."""
    r = client.post("/api/videomosaic/projects",
                    json={"name": "video", "video_path": survey_video})
    assert r.status_code == 201, r.text
    aid = r.json()["analysis_id"]
    r = client.get(f"/api/mea/{aid}/recordings/rec_x/layout")
    assert r.status_code == 409
    assert err(r)["code"] == "refused"


def test_layout_reports_the_WHOLE_chip_so_the_map_can_place_the_recorded_block(client, session,
                                                                              measynth):
    """⭐ **HIS ANSWER, 2026-08-14: draw the whole chip, recorded pads in their real place on it.**

    The width is `stride`, which the file states and `derive_geometry` verifies. The height is not
    in the file, so it is either the one device Camea knows (when the derived stride matches one of
    its orientation-free axes) or, failing that, only what this recording evidences — and
    `chip_extent` says which. ⛔ This fixture's chip is 13 x 5, which is no device, so it must take
    the honest fallback rather than being told it is a MaxWell."""
    aid, rid = _opened(client, session)
    lay = _layout(client, aid, rid)

    assert lay["chip_cols"] == lay["stride"] == measynth.STRIDE == 13
    assert lay["chip_extent"] == "recorded", "⛔ 13 is not a MaxWell axis — claim only what is shown"
    assert lay["chip_rows"] == measynth.N_ROWS == 5

    # ⭐ And the outline actually CONTAINS the pads — a box the dots fall outside of is worse than
    # no box at all.
    for pad in lay["pads"]:
        assert 0 <= pad["x_um"] <= (lay["chip_cols"] - 1) * lay["pitch_um"]
        assert 0 <= pad["y_um"] <= (lay["chip_rows"] - 1) * lay["pitch_um"]


def test_the_chip_height_is_taken_from_the_device_only_when_the_file_agrees():
    """⛔ **THE DEVICE IS CONSULTED, NEVER ASSUMED**, and this is the unit that pins it.

    `core.electrodegrid.MAXWELL` is R45.8's single place for a device number and its axes are
    orientation-free, so a file whose own derived stride IS one of them tells us the other one. A
    file whose stride is anything else is drawn as what it shows — nothing is imposed on it."""
    import numpy as np

    from camea.core import electrodegrid as eg
    from camea.features.mea import routes as mea_routes

    long_axis, short_axis = max(eg.MAXWELL.axes), min(eg.MAXWELL.axes)
    mapping = np.array([(0, 0)], dtype=[("ey", "<i8"), ("x", "<i8")])

    # The file says it is that device, so the other axis is known.
    assert mea_routes._chip_rows(long_axis, mapping) == (short_axis, "device")
    assert mea_routes._chip_rows(short_axis, mapping) == (long_axis, "device")

    # It says it is something else, so we claim only the rows it evidences.
    mapping = np.array([(0, 0), (6, 0)], dtype=[("ey", "<i8"), ("x", "<i8")])
    assert mea_routes._chip_rows(13, mapping) == (7, "recorded")


def test_a_file_whose_CHIP_LAYOUT_cannot_be_derived_is_refused_not_a_500(client, session,
                                                                        tmp_path):
    """⚠️ **FOUND IN REVIEW.** `info()` reads the header; the chip's geometry is derived in
    `mapping()`, and `derive_geometry` refuses **by design** for cases it cannot explain — every
    routed pad on one array row, a non-integer stride. All three routes reach for the mapping, so
    unless `_open` touches it that refusal escapes as an unhandled error and the user gets a **500**
    for a file Camea understands perfectly well and has a sentence about.

    ⛔ A 500 is *"Camea broke"*. This is *"this file does not describe a chip I can lay out"*, which
    is a fact about his data and must be said as one."""
    import h5py
    import numpy as np

    # A MaxLab-shaped file whose routed pads all sit on ONE array row, so the stride is
    # unconstrained and `derive_geometry` refuses rather than guessing a transposed chip.
    d = tmp_path / "P9999" / "Network" / "000009"
    d.mkdir(parents=True)
    p = d / "data.raw.h5"
    n = 4
    with h5py.File(p, "w") as f:
        g = f.create_group("data_store/data0000")
        s = g.create_group("settings")
        for k, v in (("sampling", 20000.0), ("lsb", 6.294e-6), ("gain", 512.0), ("hpf", 300.0)):
            s[k] = np.array([v])
        m = np.empty(n, dtype=[("channel", "<i4"), ("electrode", "<i4"),
                               ("x", "<f8"), ("y", "<f8")])
        for i in range(n):
            m[i] = (i, i, i * 10.0, 0.0)                     # every pad on row 0
        s["mapping"] = m
        rg = g.create_group("groups/routed")
        rg["channels"] = np.arange(n, dtype=np.uint16)
        rg["frame_nos"] = np.arange(1000, 1000 + 100, dtype=np.uint64)
        rg.create_dataset("raw", shape=(n, 100), dtype="<u2", chunks=(n, 100))
        g["spikes"] = np.empty(0, dtype=[("frameno", "<i8"), ("channel", "<i4"),
                                         ("amplitude", "<f4")])
        f["assay/run_id"] = np.array([b"000009"])

    # ⚠️ It gets onto the shelf, because `facts_of` reads the header only — see issue 008.
    a = _create(client, "bad layout", paths=[p.as_posix()])
    aid = a["analysis_id"]
    rid = _shelf(client, aid)[0]["id"]

    for route in ("layout", "activity", "trace?channel=0"):
        r = client.get(f"/api/mea/{aid}/recordings/{rid}/{route}")
        assert r.status_code == 422, (route, r.status_code, r.text)
        assert err(r)["code"] == "refused", route
        # ⛔ And it does NOT say "this is not a MaxLab recording" — it IS one, its header read
        # fine, and only the layout could not be derived. Calling a genuine MaxLab file "not a
        # recording" is the lie `utils/knowledge/mea-recordings.md` records against
        # ActivityScan/000687. It says what actually failed, in the reader's own words.
        assert "one array row" in err(r)["message"], route
        assert "not a MaxLab recording" not in err(r)["message"], route
        assert "chip layout" in err(r)["message"], route


# =================================================================================================
# Plan 004 — the WHOLE recording in one picture: `max_points`, and the cache behind it
# =================================================================================================
#
# ⭐ **HIS RULING, 2026-08-15: *"make it so it can go beyond the 30 sec limit"*, and the answer is a
# SMALLER payload, not a bigger one.** `MAX_TRACE_SECONDS` stays at 30 and keeps governing
# raw-sample requests; a caller that says how many columns it can draw gets a min/max envelope
# instead, at any width. So there are now two contracts on one route, and the first of them must not
# have moved: every existing test above calls it without `max_points` and is untouched, on purpose.
#
# ⛔ **AND NOTHING HERE WRITES 30 DOWN ON THE CLIENT'S BEHALF.** `max_window_s` is on the payload;
# these tests read the constant off the route rather than repeating the number (I1 in miniature).


def _trace(client, aid: str, rid: str, **params) -> dict:
    r = client.get(f"/api/mea/{aid}/recordings/{rid}/trace", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _envelope_rows(client, aid: str) -> list[dict]:
    r = client.get(f"/api/mea/{aid}/recordings/envelopes")
    assert r.status_code == 200, r.text
    return r.json()["recordings"]


def _envelopes_settled(client, aid: str, tries: int = 500) -> list[dict]:
    """The envelope list once no build is running. ⚠️ Polls rather than sleeps, same reason as
    `_settled` — and it is needed at all because **import starts one build per recording**, so a
    test that wants to observe the un-built state has to wait for those to stop first."""
    import time

    rows: list[dict] = []
    for _ in range(tries):
        rows = _envelope_rows(client, aid)
        if not any(x["job_id"] for x in rows):
            return rows
        time.sleep(0.02)
    raise AssertionError(f"envelope builds never settled: {[x['job_id'] for x in rows]}")


def _drop_envelopes(folder: Path) -> int:
    """Delete every cached envelope in a project. -> how many went.

    ⭐ **SAFE, AND THAT IS THE POINT OF THE FORMAT.** It is a cache, not data: nothing he authored
    is in it and the only cost of losing one is a rebuild. It is also the only way a test can see
    the `ready: false` state at all, because the import already built them."""
    from camea.core.mearecording import ENVELOPE_FILENAME

    gone = list(Path(folder).rglob(ENVELOPE_FILENAME))
    for p in gone:
        p.unlink()
    return len(gone)


@pytest.fixture()
def slow_clock(measynth, monkeypatch):
    """The synthetic recorder, clocked at 1 kHz instead of 20 kHz. -> the module.

    ⚠️ Purely so a recording **longer than `MAX_TRACE_SECONDS`** costs kilobytes: proving the 30 s
    clamp needs a recording longer than 30 s, and 30 s at 20 kHz is 600k JSON numbers in one
    response. ⛔ It is also a second guard on I1 — nothing may quietly assume MaxWell's rate."""
    monkeypatch.setattr(measynth, "FS_HZ", 1000.0)
    return measynth


def _long_recording(client, mod, tmp_path, *, seconds: float, name: str) -> tuple[str, str, Path]:
    """A project holding one recording `seconds` long. -> `(analysis_id, recording_id, folder)`."""
    p = mod.write_recording(tmp_path / name / "Network" / "000010" / "data.raw.h5",
                            n_samples=int(round(seconds * mod.FS_HZ)))
    a = _create(client, name, paths=[p.as_posix()])
    aid = a["analysis_id"]
    return aid, _settled(client, aid)[0]["id"], Path(a["folder"])


# ---- the old contract, unmoved ------------------------------------------------------------------
def test_the_trace_route_without_max_points_is_exactly_what_it_always_was(client, slow_clock,
                                                                         tmp_path):
    """🔴 **THE HALF THAT MAY NOT MOVE.** Raw samples, `resolution: "samples"`, and a window wider
    than the cap **silently clamped** rather than refused — the videomosaic sibling still does the
    same thing and every caller written before today relies on it.

    ⚠️ The clamp is silent by design, which is exactly why the client must label its axis from the
    returned `t0_s`/`t1_s` and never from what it asked for. This asserts the returned pair."""
    from camea.features.mea.routes import MAX_TRACE_SECONDS

    aid, rid, _folder = _long_recording(client, slow_clock, tmp_path,
                                        seconds=45.0, name="unclamped")
    body = _trace(client, aid, rid, channel=0, t0=0.0, t1=9999.0)

    assert body["resolution"] == "samples"
    assert body["min_uv"] == [] and body["max_uv"] == []
    assert body["duration_s"] == pytest.approx(45.0)
    assert body["t0_s"] == 0.0
    assert body["t1_s"] == pytest.approx(MAX_TRACE_SECONDS), "⛔ silently clamped, not refused"
    assert body["t1_s"] < body["duration_s"], "the fixture must outlast the cap or this proves nothing"
    assert len(body["trace_uv"]) == int(round(MAX_TRACE_SECONDS * body["sampling_hz"]))
    assert body["health"] is not None


def test_max_window_s_is_on_the_payload_so_the_client_never_writes_30_down(client, session):
    """⛔ **I1 IN MINIATURE.** A transport limit of this build, not a fact about anyone's recording —
    and a number the frontend must read rather than repeat. It is on the payload at both
    resolutions, and on the "never recorded" answer too, because the client reads it once."""
    from camea.features.mea.routes import MAX_TRACE_SECONDS

    aid, rid = _opened(client, session)
    for params in ({"channel": 0}, {"channel": 0, "max_points": 200}, {"channel": 9999}):
        body = _trace(client, aid, rid, **params)
        assert body["max_window_s"] == pytest.approx(MAX_TRACE_SECONDS), params


# ---- the new contract: a reduced picture, at any width -------------------------------------------
def test_max_points_returns_an_envelope_and_the_30_s_ceiling_stops_applying(client, slow_clock,
                                                                           tmp_path):
    """⭐ **THE HEADLINE.** *"make it so it can go beyond the 30 sec limit."* A 45 s window comes
    back whole — as `min_uv`/`max_uv` columns rather than 45,000 samples — and `t1_s` is the end of
    the recording, not `t0 + 30`."""
    from camea.features.mea.routes import MAX_TRACE_SECONDS

    aid, rid, _folder = _long_recording(client, slow_clock, tmp_path, seconds=45.0, name="whole")
    body = _trace(client, aid, rid, channel=0, t0=0.0, t1=9999.0, max_points=600)

    assert body["resolution"] == "envelope"
    assert body["trace_uv"] == [], "⛔ never both — `resolution` says which arrived"
    assert body["min_uv"] and body["max_uv"]
    assert len(body["min_uv"]) == len(body["max_uv"]) <= 600
    assert all(lo <= hi for lo, hi in zip(body["min_uv"], body["max_uv"], strict=True))
    assert body["t0_s"] == 0.0
    assert body["t1_s"] == pytest.approx(45.0)
    assert body["t1_s"] > MAX_TRACE_SECONDS, "⭐ the cap did NOT apply"
    assert body["health"] is not None, "R3.8 — the warning survives every zoom level"
    assert body["spikes"] is not None


def test_a_narrow_window_with_max_points_still_says_envelope(client, session):
    """⚠️ `resolution` is what the caller asked for, not what the server happened to read. A window
    short enough to read live is still reduced and still labelled `envelope`, so a chart never has
    to guess which pair of arrays to draw from."""
    aid, rid = _opened(client, session)
    body = _trace(client, aid, rid, channel=0, t0=0.0, t1=0.05, max_points=4096)
    assert body["resolution"] == "envelope"
    assert body["trace_uv"] == []
    assert len(body["min_uv"]) == len(body["max_uv"])
    assert body["min_uv"], "a real window returns real columns"


def test_max_points_must_be_positive(client, session):
    """⛔ Zero columns is not a picture. Refused by the route's own declaration (`gt=0`), so it
    never reaches the reducer as a division by nothing."""
    aid, rid = _opened(client, session)
    for bad in (0, -1, -600):
        r = client.get(f"/api/mea/{aid}/recordings/{rid}/trace",
                       params={"channel": 0, "max_points": bad})
        assert r.status_code == 422, (bad, r.text)
        assert err(r)["code"] == "bad_request", bad


def test_an_unrouted_channel_is_a_FACT_at_either_resolution(client, session):
    """⭐ The plan 003 answer, held at the new resolution too: *"never recorded"* is the ordinary
    answer on a MaxWell and must stay a 200 with `recorded: false` — ⛔ never a 404, and never an
    empty envelope that would draw as a flat line at zero."""
    aid, rid = _opened(client, session)
    for params in ({}, {"max_points": 500}):
        r = client.get(f"/api/mea/{aid}/recordings/{rid}/trace",
                       params={"channel": 9999, **params})
        assert r.status_code == 200, (params, r.text)
        body = r.json()
        assert body["recorded"] is False, params
        assert body["electrode"] is None, params
        assert body["trace_uv"] == [] and body["min_uv"] == [] and body["max_uv"] == [], params
        assert body["spikes"] == [], params


# ---- the cache: what makes a whole 300 s recording affordable ------------------------------------
def test_a_window_too_wide_to_read_live_comes_from_the_cache(client, slow_clock, tmp_path):
    """⭐ **WHY THE PRECOMPUTE EXISTS AT ALL.** MaxWell chunks the raw stream across every channel,
    so reading one channel end to end costs 12-23 s on his files — not something a click can pay
    for. Past `LIVE_READ_MAX_SAMPLES` the answer comes from the cached envelope instead.

    ⚠️ And when there is no cache the route **says so by name** rather than blocking for half a
    minute: a 409 that names what it needs, so the screen can offer to build it."""
    from camea.features.mea.routes import LIVE_READ_MAX_SAMPLES

    # ⛔ Derived from the route's own budget, never written down: long enough that the whole
    # recording cannot be read live, and not one sample longer.
    seconds = (LIVE_READ_MAX_SAMPLES * 1.25) / slow_clock.FS_HZ
    aid, rid, folder = _long_recording(client, slow_clock, tmp_path, seconds=seconds, name="wide")
    _envelopes_settled(client, aid)
    assert _drop_envelopes(folder) == 1

    r = client.get(f"/api/mea/{aid}/recordings/{rid}/trace",
                   params={"channel": 0, "t0": 0.0, "t1": 9999.0, "max_points": 500})
    assert r.status_code == 409, r.text
    assert err(r)["code"] == "refused"
    assert err(r)["detail"]["needs"] == "envelope", "it names WHAT is missing, not just that it is"

    # ⭐ Build it — and the same request now answers, from the cache, in one small response.
    started = client.post(f"/api/mea/{aid}/recordings/envelopes").json()["started"]
    assert len(started) == 1
    run_job(client, started[0])

    body = _trace(client, aid, rid, channel=0, t0=0.0, t1=9999.0, max_points=500)
    assert body["resolution"] == "envelope"
    assert body["trace_uv"] == []
    assert 0 < len(body["min_uv"]) == len(body["max_uv"]) <= 500
    assert all(lo <= hi for lo, hi in zip(body["min_uv"], body["max_uv"], strict=True))
    # ⚠️ The buckets actually covered — the client labels its axis from THESE, because a cache
    # cannot honestly report a finer edge than one of its own columns.
    assert body["t0_s"] >= 0.0
    assert body["t1_s"] == pytest.approx(body["duration_s"], abs=body["duration_s"] / 100)
    assert body["health"] is not None, "🔴 R3.8 — the 'did not decode' warning survives out here too"

    # ⚠️ And it is the cache's OWN whole-recording health, so it does not move with the window.
    narrow = _trace(client, aid, rid, channel=0, t0=0.0, t1=1.0, max_points=500)
    assert narrow["resolution"] == "envelope"
    assert narrow["health"]["n_samples"] < body["health"]["n_samples"]


# ---- the shelf of envelopes, and the backfill he asked for by name -------------------------------
def test_the_envelope_list_is_one_row_per_recording_and_says_which_are_ready(client, session):
    """⭐ **AND A NEWLY IMPORTED RECORDING ALREADY HAS ONE** — his answer on when the one-off read
    should run was *"when you import"*, so by the time he reaches the screen every pad is instant.

    ⚠️ `ready: false` is an ORDINARY state and never means a recording is broken — it means only
    the narrow windows the app can read live are available, which is still a working trace panel.
    The only way to observe it after an import is to take the cache away, which is safe."""
    a = _create(client, "envelopes", paths=session)
    aid = a["analysis_id"]
    _settled(client, aid)
    rows = _envelopes_settled(client, aid)
    shelf = _shelf(client, aid)

    assert [x["recording_id"] for x in rows] == [s["id"] for s in shelf]
    assert [x["label"] for x in rows] == [s["label"] for s in shelf] == ["Network/000001",
                                                                        "Network/000002"]
    assert all(x["ready"] for x in rows), "⭐ built at import — nothing to wait for on the screen"

    assert _drop_envelopes(Path(a["folder"])) == len(rows)
    after = _envelope_rows(client, aid)
    assert [x["recording_id"] for x in after] == [s["id"] for s in shelf]
    assert [x["ready"] for x in after] == [False, False]
    assert all(x["job_id"] == "" and x["pct"] == 0.0 for x in after), "nothing is running"


def test_the_backfill_starts_a_job_per_unbuilt_recording_and_nothing_when_they_are_all_built(
        client, session):
    """⭐ **HE ASKED FOR THIS BY NAME**: *"go ahead and run the loader on the MEAs I have already
    imported."* A project that predates the feature catches up from here — as background jobs with
    progress, never a blocking request — and calling it twice costs nothing."""
    a = _create(client, "backfill", paths=session)
    aid = a["analysis_id"]
    _settled(client, aid)
    _envelopes_settled(client, aid)
    assert _drop_envelopes(Path(a["folder"])) == 2

    r = client.post(f"/api/mea/{aid}/recordings/envelopes")
    assert r.status_code == 200, r.text
    started = r.json()["started"]
    assert len(started) == 2
    for jid in started:
        res = run_job(client, jid)["result"]
        assert res["kind"] == "mea_envelope"
        assert res["built"] is True
        assert res["n_buckets"] > 0
        assert res["analysis_id"] == aid

    assert all(x["ready"] for x in _envelope_rows(client, aid))

    again = client.post(f"/api/mea/{aid}/recordings/envelopes")
    assert again.status_code == 200, again.text
    assert again.json()["started"] == [], "⭐ everything is built, so it starts nothing"
    assert all(x["ready"] for x in again.json()["recordings"])


def test_the_envelope_routes_refuse_a_project_of_another_task(client, survey_video):
    """The feature string is the gate here too — ⛔ including on the POST, which starts work."""
    vm = client.post("/api/videomosaic/projects",
                     json={"name": "optical", "video_path": survey_video}).json()
    aid = vm["analysis_id"]
    for call in (client.get, client.post):
        r = call(f"/api/mea/{aid}/recordings/envelopes")
        assert r.status_code == 409, r.text
        assert "not an Analyze MEA project" in err(r)["message"]


def test_the_envelope_list_of_an_empty_project_is_an_empty_list(client):
    """The empty shelf, one screen further on. Nothing to read, nothing to build, no error."""
    a = _create(client, "nothing yet")
    r = client.get(f"/api/mea/{a['analysis_id']}/recordings/envelopes")
    assert r.status_code == 200, r.text
    assert r.json()["recordings"] == []
    assert client.post(f"/api/mea/{a['analysis_id']}/recordings/envelopes"
                       ).json()["started"] == []
