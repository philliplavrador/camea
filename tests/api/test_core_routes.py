"""The CORE routes, against a synthetic acquisition: settings, fs, datasets, sessions, tiles,
workspace, documents, jobs, dialogs.

⛔ **NOTHING IN THIS FILE IS ABOUT A MOSAIC.** Feature #2 reuses every route tested here, unchanged.
"""

from __future__ import annotations

import numpy as np
import pytest

from .conftest import OFF_SHAPE, OFF_SHAPE_TRIAL, RUN_HI, RUN_LO, TILE, err, open_session, run_job

# =================================================================================================
# settings — ⛔ two keys, and both of them are LISTS OF PATHS
# =================================================================================================


def test_settings_start_empty_and_round_trip(client, tmp_path):
    s = client.get("/api/settings").json()
    assert s == {"projects": [], "recent_datasets": []}

    s = client.put("/api/settings", json={"projects": [str(tmp_path)]}).json()
    assert s["projects"] == [str(tmp_path).replace("\\", "/")]
    assert client.get("/api/settings").json()["projects"] == s["projects"]


def test_settings_carry_no_dataset_knowledge(client, synth):
    """🔴 **THE STANDING RULING, ENFORCED WHERE IT WOULD BE MOST TEMPTING TO BREAK IT.** A settings
    file that remembered an exclusion would answer, on the user's behalf, the exact question the app
    exists to help him answer — the second time he opened the dataset. There is no toggle.

    ⚠️ Still true after the 2026-07-25 move to per-project folders: what is remembered is *where he
    saved* and *where he looked*, never anything about what is there."""
    client.post("/api/datasets/at", json={"path": str(synth.path.parent)})
    open_session(client, synth.path, synth.trials)

    s = client.get("/api/settings").json()
    assert set(s) == {"projects", "recent_datasets"}
    blob = str(s)
    for forbidden in ("excluded", "blank", "blurry", "trials", "threshold", "pass_split"):
        assert forbidden not in blob.lower(), f"settings leaked {forbidden!r}: {s}"
    # a remembered PATH is not knowledge about the data at that path
    assert any(synth.path.name in r for r in s["recent_datasets"])


def test_there_is_no_root_registry_to_scan(client, synth):
    """⛔ **`GET /api/datasets` and `POST /api/datasets/scan` ARE GONE** (his ruling, 2026-07-25).

    The app does not keep a list of folders to walk on every launch, and it does not go looking for
    the user's data. Looking at a folder tells him what is in *that* folder and remembers nothing.

    (Asserted against the CONTRACT, not a status code: the SPA catch-all serves index.html for any
    unmatched path, so a deleted route 200s with HTML rather than 404ing.)"""
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/datasets" not in paths
    assert "/api/datasets/scan" not in paths
    assert "/api/workspace" not in paths

    r = client.post("/api/datasets/at", json={"path": str(synth.path.parent)})
    assert r.status_code == 200, r.text
    assert synth.path.name in {d["name"] for d in r.json()["datasets"]}
    # ...and nothing was written down.
    assert client.get("/api/settings").json()["projects"] == []


def test_pointing_AT_a_dataset_says_so(client, synth):
    """He types the acquisition folder itself — the common case. One entry, `is_dataset` true, so
    the UI can take it without making him choose from a list of one."""
    r = client.post("/api/datasets/at", json={"path": str(synth.path)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_dataset"] is True
    assert len(body["datasets"]) == 1
    assert body["datasets"][0]["name"] == synth.path.name


# =================================================================================================
# 🔴 fs — THE SERVED FOLDER PICKER. The reason --browser and --headless are usable at all.
# =================================================================================================


def test_the_folder_picker_lists_directories_and_marks_datasets(client, synth):
    r = client.get("/api/fs/list", params={"path": str(synth.path.parent)})
    assert r.status_code == 200
    body = r.json()
    entries = {e["name"]: e for e in body["entries"]}
    assert synth.path.name in entries
    assert entries[synth.path.name]["is_dataset"] is True
    assert body["parent"] is not None
    assert body["roots"], "the picker must be able to start from nothing"


def test_the_folder_picker_recognises_a_dataset_by_SHAPE_not_by_name(client, tmp_path):
    """⛔ A folder is a dataset iff it has a `log.txt` and at least one `NNN.xml`. That is the whole
    rule. Nothing in this app knows what a dataset is called."""
    d = tmp_path / "definitely_not_called_a_dataset"
    d.mkdir()
    r = client.get("/api/fs/list", params={"path": str(tmp_path)})
    assert {e["name"]: e["is_dataset"] for e in r.json()["entries"]}[d.name] is False


def test_the_folder_picker_survives_a_bad_path(client):
    """It must still render its roots and its parent — a picker that 500s on a typo is a picker the
    user cannot back out of."""
    r = client.get("/api/fs/list", params={"path": "Z:/no/such/place"})
    assert r.status_code == 200
    assert r.json()["error"]
    assert r.json()["roots"]


def test_no_window_means_501_AND_A_WAY_OUT(client):
    """🔴 In `--browser` and `--headless` there is no pywebview, so a native dialog cannot exist. v1
    returned a bare 501 and **left the user with no way to choose a folder at all** — which made the
    app unusable in the two modes a developer and a test actually run it in. The 501 must NAME the
    served picker, and the served picker must work."""
    for route in ("open-directory", "open-file", "save-file"):
        r = client.post(f"/api/dialog/{route}", json={"title": "x"})
        assert r.status_code == 501
        e = err(r)
        assert e["code"] == "no_window"
        assert "/api/fs/list" in e["message"]
    assert client.get("/api/fs/list").status_code == 200


# =================================================================================================
# datasets — the browser
# =================================================================================================


def test_looking_at_a_folder_reports_what_is_in_it(client, synth):
    r = client.post("/api/datasets/at", json={"path": str(synth.path.parent)})
    assert r.status_code == 200
    body = r.json()
    ds = next(d for d in body["datasets"] if d["name"] == synth.path.name)

    assert ds["n_snapshots"] == len(synth.trials) + 4        # 3 strays + 1 off-shape
    assert ds["experiment"] == "synth"
    shapes = {(s["w"], s["h"]): s["n"] for s in ds["shapes"]}
    assert shapes[(TILE, TILE)] == len(synth.trials) + 3
    assert shapes[OFF_SHAPE] == 1                            # ⛔ REPORTED. Core does not gate on it.

    # ⛔ and NOTHING was remembered — there is no root registry any more.
    assert client.get("/api/settings").json()["projects"] == []


def test_dataset_detail_and_thumbnail_cost_no_session(client, synth):
    key = client.post("/api/datasets/at",
                      json={"path": str(synth.path.parent)}).json()["datasets"][0]["key"]

    d = client.get(f"/api/datasets/{key}").json()
    blocks = [(b["lo"], b["hi"]) for b in d["blocks"]]
    assert blocks == [(5, 5), (7, 9), (RUN_LO, RUN_HI)]      # core REPORTS blocks; it picks none
    assert len(d["trials"]) == len(synth.trials) + 6         # every trial in log.txt, of any type

    png = client.get(f"/api/datasets/{key}/thumbnail.png")
    assert png.status_code == 200
    assert png.content[:4] == b"\x89PNG"                     # a card, with no 340 MiB session


def test_an_unknown_dataset_key_is_a_404(client):
    assert client.get("/api/datasets/nope-deadbeef").status_code == 404


# =================================================================================================
# sessions
# =================================================================================================


def test_open_reports_what_it_actually_read(client, synth):
    s = open_session(client, synth.path, synth.trials)
    assert s["n"] == len(synth.trials)
    assert (s["w"], s["h"]) == (TILE, TILE)
    assert s["trials"] == synth.trials
    assert s["skipped"] == []
    assert s["nonce"] and len(s["nonce"]) >= 8
    assert s["gpu"]["backend"] in ("cupy", "numpy")


def test_frame_note_is_READ_OFF_THE_XML_never_asserted(client, synth, synth_noflip):
    """⭐ v1's exported TIFF header said "180-degree-flipped display frame" **UNCONDITIONALLY**, while
    the reader flips **CONDITIONALLY** on `ax`/`ay`. On an acquisition that does not flip, that header
    is a false claim about its own coordinate frame — in the file most likely to be handed to somebody
    else, on the one axis this project has been burned by."""
    flipped = open_session(client, synth.path, synth.trials)["frame_note"]
    plain = open_session(client, synth_noflip.path, synth_noflip.trials)["frame_note"]
    assert "180deg-flipped" in flipped and "ax=-1" in flipped
    assert "NO flip" in plain and "ax=+1" in plain
    assert flipped != plain


def test_a_mixed_shape_open_is_refused_and_says_why(client, synth):
    """⛔ A FrameStore holds ONE shape. **Which one you meant is a decision core is not entitled to
    make for you** — so it refuses, and lists the groups. It does not pick the majority."""
    r = client.post("/api/sessions", json={"path": str(synth.path), "trials": None})
    assert r.status_code == 409
    e = err(r)
    assert e["code"] == "mixed_shape"
    assert "512x128" in e["detail"]["groups"]


def test_nothing_is_ever_dropped_by_trial_number(client, synth):
    """⛔ A frame leaves the selection for exactly two reasons, and both are facts about the file on
    disk. **This route is where an exclusion list would have gone, and there is not one.**"""
    s = open_session(client, synth.path, [*synth.trials, 999])
    assert s["n"] == len(synth.trials)
    assert [k["trial"] for k in s["skipped"]] == [999]
    assert s["skipped"][0]["reason"] == "not_snapshot"       # not "excluded". There is no such thing.


def test_the_off_shape_trial_is_real_data_and_core_still_loads_it(client, synth):
    """Core holds frames of whatever shape the XML says. "512x512 only" is the MOSAIC's policy, not
    core's — and a future feature may happily take this frame."""
    s = open_session(client, synth.path, [OFF_SHAPE_TRIAL])
    assert (s["w"], s["h"]) == OFF_SHAPE
    assert s["n"] == 1


def test_session_log_texture_and_tone(client, synth):
    s = open_session(client, synth.path, synth.trials)
    sid = s["session_id"]

    log = client.get(f"/api/sessions/{sid}/log").json()
    assert log["n_snapshot"] == len(synth.trials) + 4 and log["n_other"] == 2

    tex = client.get(f"/api/sessions/{sid}/texture").json()
    assert tex["n"] == len(synth.trials)
    assert tex["measure"].startswith("std of DoG")
    assert all(v > 0 for v in tex["texture"].values())
    # ⛔ a MEASUREMENT. No threshold, no list, no policy anywhere in the body.
    assert set(tex) == {"measure", "texture", "n"}

    tone = client.get(f"/api/sessions/{sid}/tone").json()
    assert tone["hi"] > tone["lo"] and tone["auto"] is True

    bumped = client.put(f"/api/sessions/{sid}/tone", json={"lo": 1.0, "hi": 2.0}).json()
    assert (bumped["lo"], bumped["hi"]) == (1.0, 2.0)
    assert bumped["version"] > tone["version"]              # the pixel caches key on this
    back = client.put(f"/api/sessions/{sid}/tone", json={"auto": True}).json()
    assert (back["lo"], back["hi"]) == (tone["lo"], tone["hi"])

    bad = client.put(f"/api/sessions/{sid}/tone", json={"lo": 9.0, "hi": 1.0})
    assert bad.status_code == 400                           # hi must exceed lo


def test_tiles_and_thumbs(client, synth):
    s = open_session(client, synth.path, synth.trials)
    sid, t = s["session_id"], synth.trials[0]

    png = client.get(f"/api/sessions/{sid}/tiles/{t}.png", params={"v": s["nonce"]})
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"
    assert "immutable" in png.headers["cache-control"]

    raw = client.get(f"/api/sessions/{sid}/tiles/{t}.raw")
    assert raw.status_code == 200
    assert len(raw.content) == TILE * TILE * 2              # uint16 LE, raw counts, already flipped
    px = np.frombuffer(raw.content, "<u2")
    assert px.max() > 0 and px.max() < 65535

    assert client.get(f"/api/sessions/{sid}/tiles/9999.png").status_code == 404

    sheet = client.get(f"/api/sessions/{sid}/thumbs.png", params={"v": s["nonce"]})
    assert sheet.status_code == 200 and sheet.content[:4] == b"\x89PNG"
    tj = client.get(f"/api/sessions/{sid}/thumbs.json").json()
    assert tj["n"] == len(synth.trials)
    assert tj["grid"] == int(np.ceil(np.sqrt(len(synth.trials))))
    assert tj["version"].startswith(s["nonce"])            # ⭐ nonce.toneversion, not toneversion


def test_delete_a_session(client, synth):
    sid = open_session(client, synth.path, synth.trials)["session_id"]
    assert client.delete(f"/api/sessions/{sid}").json() == {"ok": True}
    assert client.get(f"/api/sessions/{sid}").status_code == 404
    assert client.delete(f"/api/sessions/{sid}").status_code == 404


# =================================================================================================
# project folders — ⛔ NEVER inside a dataset, NEVER inside the repo
# =================================================================================================


def test_the_home_screen_starts_empty_and_that_is_not_an_error(client):
    """⭐ There is no store to choose first (his ruling, 2026-07-25), so there is no `no_workspace`
    409 to hit. No projects yet is a 200 and an empty list — the honest first-run state."""
    r = client.get("/api/projects")
    assert r.status_code == 200
    assert r.json()["analyses"] == []


def test_a_project_folder_inside_the_dataset_is_refused(client, synth):
    """⛔ **THE APP DOES NOT WRITE ON THE EVIDENCE.** Refused at the one moment he names the place."""
    s = open_session(client, synth.path, synth.trials)
    r = client.post("/api/projects",
                    json={"session_id": s["session_id"], "feature": "mosaic", "name": "x",
                          "folder": str(synth.path / "work")})
    assert r.status_code == 409
    assert err(r)["code"] == "refused"


def test_a_project_folder_inside_the_repo_is_refused(client, synth):
    """A project under the checkout would be committed, `.gitignore`d, or blown away by a clean.
    The user's work does not live in the app's source tree."""
    from camea.core.workspace import repo_root

    root = repo_root()
    assert root is not None, "these tests run from the checkout"
    s = open_session(client, synth.path, synth.trials)
    r = client.post("/api/projects",
                    json={"session_id": s["session_id"], "feature": "mosaic", "name": "x",
                          "folder": str(root / "my-project")})
    assert r.status_code == 409
    assert err(r)["code"] == "refused"


def test_folder_writability_is_proved_not_assumed(client, workspace):
    info = client.get("/api/projects/folder", params={"path": str(workspace)}).json()
    assert info["exists"] is True and info["writable"] is True
    assert info["is_project"] is False


def test_a_folder_that_already_holds_a_project_is_refused_not_overwritten(client, synth, workspace):
    """🔴 Silently overwriting a project folder is how a day of sweeping disappears. He is told to
    pick another folder, and the existing project is named so he knows what he nearly lost."""
    s = open_session(client, synth.path, synth.trials)
    body = {"session_id": s["session_id"], "feature": "mosaic", "name": "first",
            "folder": str(workspace / "p")}
    assert client.post("/api/projects", json=body).status_code == 201

    again = client.post("/api/projects", json={**body, "name": "second"})
    assert again.status_code == 400
    assert "first" in err(again)["message"]


# =================================================================================================
# documents — the server authors them
# =================================================================================================


def test_the_SERVER_creates_the_document(client, synth, workspace):
    """🔴 In v1 `new_doc()` was dead code and the front end built the document in JavaScript — which
    is how the divert counters were dropped on every save. **The document is authored on the
    server.**"""
    s = open_session(client, synth.path, synth.trials)
    r = client.post("/api/projects",
                    json={"session_id": s["session_id"], "feature": "mosaic", "name": "pass 1",
                          "trials": synth.trials, "folder": str(workspace / "pass-1")})
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["n_tiles"] == len(synth.trials)
    assert a["n_anchored"] == 0
    assert a["independent_of_method"] is True

    # ⛔⛔ NOTHING STARTS EXCLUDED.
    assert a["n_excluded"] == 0

    doc = client.get(f"/api/analyses/{a['analysis_id']}/document").json()["doc"]
    assert doc["id"] == a["analysis_id"]        # ⭐ the slot guard depends on this
    assert doc["feature"] == "mosaic"
    assert {t["state"] for t in doc["tiles"].values()} == {"unplaced"}
    assert doc["coordinates"].endswith("translation before measuring.") or "TOP-LEFT" in doc["coordinates"]


def test_an_unknown_feature_is_a_400_not_a_guess(client, synth, workspace):
    s = open_session(client, synth.path, synth.trials)
    r = client.post("/api/projects",
                    json={"session_id": s["session_id"], "feature": "segmentation", "name": "x",
                          "folder": str(workspace / "x")})
    assert r.status_code == 400


def test_save_load_autosave_and_the_derived_gaps(client, synth, workspace):
    """⚠️ `gaps` is DERIVED and is recomputed on every save. Trial numbers are acquisition ORDER but
    stop being CONTIGUOUS the moment the human excludes one — and across a gap the serpentine
    one-axis step prior does NOT hold."""
    s = open_session(client, synth.path, synth.trials)
    aid = client.post("/api/projects",
                      json={"session_id": s["session_id"], "feature": "mosaic", "name": "sweep",
                            "trials": synth.trials, "folder": str(workspace / "sweep")}).json()["analysis_id"]
    doc = client.get(f"/api/analyses/{aid}/document").json()["doc"]
    assert doc["gaps"] == []

    victim = str(synth.trials[5])
    doc["tiles"][victim]["state"] = "excluded"
    doc["tiles"][victim]["status"] = "excluded"

    saved = client.put(f"/api/analyses/{aid}/document", json={"doc": doc})
    assert saved.status_code == 200, saved.text
    assert saved.json()["bytes"] > 0

    back = client.get(f"/api/analyses/{aid}/document").json()["doc"]
    a, b = synth.trials[4], synth.trials[6]
    assert [a, b] in [list(g) for g in back["gaps"]], back["gaps"]

    r = client.post(f"/api/analyses/{aid}/autosave", json={"doc": back})
    assert r.status_code == 200
    assert r.json()["path"].endswith("autosave.camea.json")   # BESIDE the document, never over it


def test_the_slot_guard_refuses_someone_elses_document(client, synth, workspace):
    """🔴 Pass 2's autosave once silently overwrote pass 1's ground-truth records. A document may only
    be written into the analysis whose `id` it carries. **Not merged, not renamed, not "repaired".**"""
    s = open_session(client, synth.path, synth.trials)
    mk = lambda name: client.post(  # noqa: E731
        "/api/projects",
        json={"session_id": s["session_id"], "feature": "mosaic", "name": name,
              "trials": synth.trials, "folder": str(workspace / name)}).json()["analysis_id"]
    a1, a2 = mk("one"), mk("two")

    doc1 = client.get(f"/api/analyses/{a1}/document").json()["doc"]
    r = client.put(f"/api/analyses/{a2}/document", json={"doc": doc1})
    assert r.status_code == 409
    assert err(r)["code"] == "range_mismatch"


def test_save_as_and_a_COLD_load(client, synth, workspace, tmp_path):
    """⭐ *"Load a project…"* must work **cold**, with no session. The app remembers nothing between
    launches, so this file is its only memory: save -> quit -> load restores the session whole."""
    s = open_session(client, synth.path, synth.trials)
    aid = client.post("/api/projects",
                      json={"session_id": s["session_id"], "feature": "mosaic", "name": "cold",
                            "trials": synth.trials, "folder": str(workspace / "cold")}).json()["analysis_id"]
    doc = client.get(f"/api/analyses/{aid}/document").json()["doc"]

    out = tmp_path / "handed-out.camea.json"
    r = client.post("/api/documents/save-as", json={"path": str(out), "doc": doc})
    assert r.status_code == 200 and out.is_file()

    client.delete(f"/api/sessions/{s['session_id']}")        # <- the app now knows NOTHING
    assert client.get("/api/sessions").json()["sessions"] == []

    r = client.post("/api/documents/load", json={"path": str(out)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session"] is not None                       # bootstrapped from the doc's data_dir
    assert body["session"]["n"] == len(synth.trials)
    assert body["doc"]["id"] == aid


def test_save_as_INTO_the_dataset_is_refused(client, synth, workspace):
    s = open_session(client, synth.path, synth.trials)
    aid = client.post("/api/projects",
                      json={"session_id": s["session_id"], "feature": "mosaic", "name": "x",
                            "trials": synth.trials, "folder": str(workspace / "x")}).json()["analysis_id"]
    doc = client.get(f"/api/analyses/{aid}/document").json()["doc"]
    r = client.post("/api/documents/save-as",
                    json={"path": str(synth.path / "sneaky.camea.json"), "doc": doc})
    assert r.status_code == 409
    assert err(r)["code"] == "refused"


def test_validate_never_rejects_a_document_for_WHICH_trials_it_placed(client, synth, workspace):
    """⛔ **NO TRIAL NUMBER IS SPECIAL.** v1's guard ("tile 284 is thrown out and carries a position")
    made the user's own session unsaveable the moment he anchored 284."""
    s = open_session(client, synth.path, synth.trials)
    aid = client.post("/api/projects",
                      json={"session_id": s["session_id"], "feature": "mosaic", "name": "v",
                            "trials": synth.trials, "folder": str(workspace / "v")}).json()["analysis_id"]
    doc = client.get(f"/api/analyses/{aid}/document").json()["doc"]

    for t in synth.trials:                                   # anchor EVERY tile, by hand
        doc["tiles"][str(t)].update({"state": "anchored", "status": "anchor",
                                     "x": 0.0, "y": 0.0, "human": True})
    r = client.post("/api/documents/validate", json={"doc": doc})
    assert r.status_code == 200
    assert r.json()["ok"] is True, r.json()["problems"]
    assert client.put(f"/api/analyses/{aid}/document", json={"doc": doc}).status_code == 200


def test_delete_an_analysis(client, synth, workspace):
    s = open_session(client, synth.path, synth.trials)
    aid = client.post("/api/projects",
                      json={"session_id": s["session_id"], "feature": "mosaic", "name": "d",
                            "trials": synth.trials, "folder": str(workspace / "d")}).json()["analysis_id"]
    assert client.delete(f"/api/projects/{aid}").json() == {"ok": True}
    assert client.get("/api/projects").json()["analyses"] == []
    assert client.delete(f"/api/projects/{aid}").status_code == 404


def test_rename_a_project_rewrites_the_manifest_and_keeps_the_id(client, synth, workspace):
    """The project manager's rename: `PATCH /api/projects/{id}`. It rewrites the manifest
    name; the id (the directory) is forever, so the slot guard and every stored path keep working."""
    s = open_session(client, synth.path, synth.trials)
    aid = client.post("/api/projects",
                      json={"session_id": s["session_id"], "feature": "mosaic", "name": "before",
                            "trials": synth.trials, "folder": str(workspace / "before")}).json()["analysis_id"]
    r = client.patch(f"/api/projects/{aid}", json={"name": "after"})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "after"
    assert body["analysis_id"] == aid                        # ⭐ the id never moves
    # it persists — the list reflects the new name.
    listed = client.get("/api/projects").json()["analyses"]
    assert [a["name"] for a in listed if a["analysis_id"] == aid] == ["after"]
    # an empty name is refused; a missing analysis is a 404.
    assert client.patch(f"/api/projects/{aid}", json={"name": "  "}).status_code == 400
    assert client.patch("/api/projects/nope", json={"name": "x"}).status_code == 404


# =================================================================================================
# jobs
# =================================================================================================


def test_jobs_list_get_and_cancel(client, synth):
    r = client.post("/api/sessions", json={"path": str(synth.path), "trials": synth.trials})
    job_id = r.json()["job_id"]
    done = run_job(client, job_id)
    assert done["kind"] == "open"
    assert done["result"]["kind"] == "open"                  # ⭐ the discriminator tag
    assert done["pct"] == 100.0

    jobs = client.get("/api/jobs").json()["jobs"]
    assert jobs[0]["job_id"] == job_id                       # newest first

    c = client.post(f"/api/jobs/{job_id}/cancel")            # already finished
    assert c.status_code == 409
    assert client.get("/api/jobs/nope").status_code == 404


@pytest.mark.parametrize("path", ["/api/sessions/x/log", "/api/sessions/x/texture",
                                  "/api/sessions/x/tone", "/api/sessions/x/thumbs.json"])
def test_every_session_route_404s_on_an_unknown_session(client, path):
    assert client.get(path).status_code == 404
