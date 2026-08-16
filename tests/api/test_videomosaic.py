"""The videomosaic API, end to end against a synthetic survey video: probe → create project →
build (a real job, polled) → outputs. Same fixtures as the rest of the API suite — isolated state
dir, fresh app.

⭐ **NO FOLDER AT ALL (R44).** Create takes one path, the video; the project goes straight into
Camea's store and is listed from that moment; the build writes into its `outputs/`. There is no
save route and no export route to test — copying a chosen output out is core's
`POST /api/projects/{id}/outputs/copy` and is tested in `test_core_routes.py`.
"""

from __future__ import annotations

import json

from pathlib import Path

import pytest

from .conftest import err, run_job, store_dir, store_entries

CFG = {"keyframe_spacing_frac": 200.0 / 480.0}                        # 480-px-wide synthetic frames


@pytest.fixture()
def survey(tmp_path_factory, videosynth):
    d = tmp_path_factory.mktemp("videos")
    v = videosynth.write_survey_video(d / "survey.avi", rows=2)
    v["path"] = str(d / "survey.avi")
    return v


def _create(client, survey, name="vm") -> dict:
    r = client.post("/api/videomosaic/projects",
                    json={"name": name, "video_path": survey["path"]})
    assert r.status_code == 201, r.text
    return r.json()


# ---- probe --------------------------------------------------------------------------------------
def test_probe_returns_a_receipt(client, survey):
    r = client.post("/api/videomosaic/probe", json={"path": survey["path"]})
    assert r.status_code == 200, r.text
    j = r.json()
    assert (j["width"], j["height"]) == (480, 320)
    assert j["n_frames"] > 0 and j["size_bytes"] > 0
    assert j["name"] == "survey.avi"


def test_probe_refuses_garbage(client, tmp_path):
    p = tmp_path / "junk.mp4"
    p.write_bytes(b"not a movie" * 64)
    r = client.post("/api/videomosaic/probe", json={"path": str(p)})
    assert r.status_code == 400
    assert err(r)["code"] == "bad_request"
    r2 = client.post("/api/videomosaic/probe", json={"path": str(tmp_path / "nowhere.mp4")})
    assert r2.status_code == 400


# ---- project creation ----------------------------------------------------------------------------
def test_create_project_authors_a_document_in_the_store(client, survey, state_dir):
    """⭐ R44. No folder is asked for and none is a draft: the project is in Camea's store, with a
    document already on disk, from the moment Create returns."""
    a = _create(client, survey)
    assert a["feature"] == "videomosaic"
    assert Path(a["folder"]).parent == store_dir(state_dir)

    doc = client.get(f"/api/analyses/{a['analysis_id']}/document").json()["doc"]
    assert doc["feature"] == "videomosaic"
    assert doc["source"]["name"] == "survey.avi"
    assert doc["build"] is None and doc["keyframes"] == {}
    # provenance before any build: no machine evidence, honestly independent
    assert doc["provenance"]["independent_of_method"] is True


def test_a_new_video_project_is_listed_immediately(client, survey):
    """⭐ **R44 retires R43.3's reachable-but-not-listed.** There is no unsaved state to hide: the
    project is in the store, so it is on the home screen before the build has placed a frame. (R43
    hid it because its folder was one the user had not chosen yet — a lie about where his work was.
    Now the app chose, and can say so.)"""
    a = _create(client, survey)
    assert client.get(f"/api/analyses/{a['analysis_id']}/document").status_code == 200

    listed = client.get("/api/projects").json()["analyses"]
    assert any(x["analysis_id"] == a["analysis_id"] for x in listed)


def test_create_project_refuses_a_dead_video(client, tmp_path):
    r = client.post("/api/videomosaic/projects",
                    json={"name": "x", "video_path": str(tmp_path / "gone.mp4")})
    assert r.status_code == 400
    assert store_entries() == [], "a refused create must not leave a project behind"


def test_a_create_refusal_arrives_whole_not_letter_joined(client, survey, monkeypatch):
    """Issue 004 §1 — the route joined `e.args[0]`, which `ValidationError.__init__` had ALREADY
    joined into one string, so `"; ".join()` iterated its characters ("s; o; u; r; …"). The
    refusal must arrive as the sentence the error composed, verbatim — this repo's standing rule
    is that a refusal is shown whole."""
    from camea.core import document as core_document

    sentence = "source: a probed video receipt is required"

    def refuse(*_a, **_k):
        raise core_document.ValidationError([sentence])

    monkeypatch.setattr(core_document, "save_analysis", refuse)
    r = client.post("/api/videomosaic/projects",
                    json={"name": "x", "video_path": survey["path"]})
    assert r.status_code == 400
    msg = err(r)["message"]
    assert msg == sentence, f"garbled refusal: {msg!r}"
    assert "s; o; u" not in msg
    assert store_entries() == [], "a refused create must not leave a project behind"


def test_an_unexpected_midsave_failure_leaves_no_project_behind(client, survey, monkeypatch):
    """Issue 004 §2 — an `OSError` in `save_analysis` (unwritable store, full disk) used to escape
    AFTER the manifest was written: a project the user never finished creating appeared on his
    home screen with no document in it. The catch-all now abandons it, like the mea route."""
    from camea.core import document as core_document

    def full_disk(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(core_document, "save_analysis", full_disk)
    r = client.post("/api/videomosaic/projects",
                    json={"name": "x", "video_path": survey["path"]})
    assert r.status_code == 500
    assert err(r)["code"] == "io_error"
    assert store_entries() == [], "a failed create must not leave a project behind"
    listed = client.get("/api/projects").json()["analyses"]
    assert listed == [], "and nothing broken reaches the home screen"


# ---- build → browse → copy out ---------------------------------------------------------------
def test_build_end_to_end_and_the_outputs_are_browsable(client, survey, outbox, state_dir):
    """⭐ **THE WHOLE R44 FLOW: no directory question at all until he wants a copy.**"""
    a = _create(client, survey, name="night sky")
    aid = a["analysis_id"]
    folder = Path(a["folder"])

    r = client.post("/api/videomosaic/build", json={"analysis_id": aid, "config": CFG})
    assert r.status_code == 202, r.text
    job = run_job(client, r.json()["job_id"])
    res = job["result"]
    assert res["kind"] == "videomosaic_build"
    assert res["canvas"]["w"] > 1000 and res["canvas"]["h"] > 300
    assert res["stats"]["solve"]["components"] == 1
    assert res["stats"]["keyframes_dropped"] == 0
    # ⭐ still named after the PROJECT, not after "mosaic" — verbatim, spaces and all. The reason
    # changed with R44 (he no longer opens the folder) but the value did not: a file he copies out
    # of Camea has to say what it is once it is sitting on his desktop.
    assert res["outputs"]["mosaic"] == "night sky.png"
    assert res["outputs"]["positions"] == "night sky-positions.csv"

    # the job SAVED the document server-side — the wire copy and the disk copy agree
    doc = client.get(f"/api/analyses/{aid}/document").json()["doc"]
    assert doc["build"] is not None and doc["keyframes"]
    assert any(v["placed"] for v in doc["keyframes"].values())
    assert doc["provenance"]["independent_of_method"] is False, (
        "a built video mosaic is machine output and must say so")

    # ⭐ THE ARTIFACTS ARE IN `outputs/` (R44) — one layout for every feature, so one browser.
    out = folder / "outputs"
    assert sorted(p.name for p in out.iterdir()) == [
        "night sky-build.json",
        "night sky-positions.csv",
        "night sky-preview.png",
        "night sky.png",
    ], "and NOTHING else: a developer's diagnostic image is clutter he never asked for"
    assert sorted(p.name for p in folder.iterdir()) == [
        "camea-project.json", "document.camea.json", "outputs",
    ]
    on_disk = json.loads((folder / "document.camea.json").read_text("utf-8"))
    assert on_disk["build"]["canvas"] == res["canvas"]

    # the FEATURE's route still serves them by LOGICAL name (its own <img src>)
    for name in ("mosaic.png", "preview.png", "positions.csv", "build.json"):
        g = client.get(f"/api/videomosaic/{aid}/outputs/{name}")
        assert g.status_code == 200, name
        assert g.headers["cache-control"] == "no-store"
    assert client.get(f"/api/videomosaic/{aid}/outputs/document.camea.json").status_code == 404

    # ⭐ ...and CORE's browser lists the same four by their real names, for him to choose from
    listed = client.get(f"/api/projects/{aid}/outputs").json()["outputs"]
    assert {o["name"] for o in listed} == {p.name for p in out.iterdir()}
    assert next(o for o in listed if o["name"] == "night sky.png")["previewable"] is True

    # ⭐ and THIS is how the mosaic reaches a paper: pick one, name a folder, take a copy.
    r = client.post(f"/api/projects/{aid}/outputs/copy",
                    json={"names": ["night sky.png"], "dest": str(outbox)})
    assert r.status_code == 200, r.text
    assert (outbox / "night sky.png").is_file()
    assert (out / "night sky.png").is_file(), "a copy — the project keeps its mosaic"


def test_there_is_no_save_route_any_more(client):
    """⛔ **R44 deleted `POST /api/videomosaic/save`.** There is nothing to save into: the project
    has been in the store since Create."""
    assert "/api/videomosaic/save" not in client.get("/openapi.json").json()["paths"]


def test_build_refuses_bad_config_and_missing_video(client, survey):
    a = _create(client, survey)
    r = client.post("/api/videomosaic/build",
                    json={"analysis_id": a["analysis_id"],
                          "config": {"keyframe_spacing": 1}})
    assert r.status_code == 400
    assert "unknown VideoConfig keys" in err(r)["message"]

    r2 = client.post("/api/videomosaic/build", json={"analysis_id": "no-such-analysis"})
    assert r2.status_code == 404


def test_outputs_before_build_404(client, survey):
    a = _create(client, survey)
    g = client.get(f"/api/videomosaic/{a['analysis_id']}/outputs/mosaic.png")
    assert g.status_code == 404
