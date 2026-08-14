"""The `mea` feature's API: create a project out of a name and nothing else, list it, open it.

⭐ **THE POINT OF THIS FILE IS THE ABSENCE OF A PATH.** Every other way to make a project in
Camea names something on disk — a dataset folder, a video file. This one names neither, and the
project still lands in the store with a document already written (R44). If a future change
reintroduces a path question here, these tests are what says so.

⛔ No dataset knowledge: nothing below asserts a channel count, a run id, an electrode or a
spike rate, because at this point in the feature's life the project holds no recording at all.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from .conftest import err, store_dir, store_entries


@pytest.fixture()
def survey_video(tmp_path_factory, videosynth) -> str:
    """A tiny synthetic survey video — the *other* task's input, borrowed for the one test that
    puts a project of each kind in the same store."""
    d = tmp_path_factory.mktemp("mea_videos")
    videosynth.write_survey_video(d / "survey.avi", rows=2)
    return str(d / "survey.avi")


def _create(client, name: str = "chip 3693") -> dict:
    r = client.post("/api/mea/projects", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


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
