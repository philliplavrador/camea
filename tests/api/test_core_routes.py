"""The CORE routes, against a synthetic acquisition: settings, fs, datasets, sessions, tiles,
workspace, documents, jobs, dialogs.

⛔ **NOTHING IN THIS FILE IS ABOUT A MOSAIC.** Feature #2 reuses every route tested here, unchanged.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from .conftest import (
    OFF_SHAPE,
    OFF_SHAPE_TRIAL,
    RUN_HI,
    RUN_LO,
    TILE,
    err,
    new_project,
    open_session,
    run_job,
    store_dir,
    store_entries,
)


# =================================================================================================
# Local helpers — the three routes R48 promoted to jobs (2026-08-16)
# =================================================================================================
#
# ⭐ `POST /api/datasets/at`, `POST .../outputs/copy` and `POST /api/documents/load` answer **202
# `JobRef`** now, so every one of them is submit-then-poll. These are two-liners over `run_job` (the
# suite's one polling loop) so no test below grows a wait of its own — and so that the **202** and
# the **submit-time refusals** are asserted in exactly one place each.


def scan_at(client, path, *, depth: int | None = None) -> dict:
    """*"Look at THIS folder."* -> the `DatasetScanResult`."""
    body = {"path": str(path)}
    if depth is not None:
        body["depth"] = depth
    r = client.post("/api/datasets/at", json=body)
    assert r.status_code == 202, r.text
    return run_job(client, r.json()["job_id"])["result"]


def copy_outputs(client, analysis_id: str, names: list[str], dest) -> dict:
    """Take a copy out of a project (R44) -> the `CopyOutputsResult`.

    ⚠️ Asserts the **202** only. The three refusals are still synchronous and are asserted as
    4xx-on-submit by the tests that own them — this helper must never be used to check one.
    """
    r = client.post(f"/api/projects/{analysis_id}/outputs/copy",
                    json={"names": names, "dest": str(dest)})
    assert r.status_code == 202, r.text
    return run_job(client, r.json()["job_id"])["result"]


def load_document(client, path, session_id: str | None = None) -> dict:
    """*"Load a project…"* -> the `LoadDocumentResult`. Refusals (missing file, no `data_dir`, the
    range guard) are still 4xx on the submit and are asserted by their own tests."""
    r = client.post("/api/documents/load",
                    json={"path": str(path), "session_id": session_id})
    assert r.status_code == 202, r.text
    return run_job(client, r.json()["job_id"])["result"]


# =================================================================================================
# settings — ⛔ two keys, and both of them are LISTS OF PATHS
# =================================================================================================


def test_settings_start_empty_and_round_trip(client, tmp_path):
    """⭐ **ONE KEY, since R44.** `projects` went with the folders it indexed — the store is the
    index now, so there is nothing for settings to keep in sync with it."""
    s = client.get("/api/settings").json()
    assert s == {"recent_datasets": []}

    s = client.put("/api/settings", json={"recent_datasets": [str(tmp_path)]}).json()
    assert s["recent_datasets"] == [str(tmp_path).replace("\\", "/")]
    assert client.get("/api/settings").json()["recent_datasets"] == s["recent_datasets"]


def test_settings_carry_no_dataset_knowledge(client, synth):
    """🔴 **THE STANDING RULING, ENFORCED WHERE IT WOULD BE MOST TEMPTING TO BREAK IT.** A settings
    file that remembered an exclusion would answer, on the user's behalf, the exact question the app
    exists to help him answer — the second time he opened the dataset. There is no toggle.

    ⚠️ Still true after R44 moved projects into the app's own store: the only thing remembered is
    *where he looked for data*, never anything about what is there."""
    client.post("/api/datasets/at", json={"path": str(synth.path.parent)})
    open_session(client, synth.path, synth.trials)

    s = client.get("/api/settings").json()
    assert set(s) == {"recent_datasets"}
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

    body = scan_at(client, synth.path.parent)
    assert synth.path.name in {d["name"] for d in body["datasets"]}
    # ...and no project folder was written down: there is no such index any more (R44).
    assert set(client.get("/api/settings").json()) == {"recent_datasets"}


def test_a_mistyped_folder_is_refused_ON_THE_REQUEST(client, tmp_path):
    """⭐ **R48 promoted the scan to a job; it did NOT push the refusal into it.** *"No such
    directory"* is still a **400 on the request that asked**, so a typo lands beside the box he typed
    it in — not as a job that fails a moment later with nobody waiting on it."""
    r = client.post("/api/datasets/at", json={"path": str(tmp_path / "nope")})
    assert r.status_code == 400
    assert err(r)["code"] == "bad_request"


def test_pointing_AT_a_dataset_says_so(client, synth):
    """He types the acquisition folder itself — the common case. One entry, `is_dataset` true, so
    the UI can take it without making him choose from a list of one."""
    body = scan_at(client, synth.path)
    assert body["is_dataset"] is True
    assert len(body["datasets"]) == 1
    assert body["datasets"][0]["name"] == synth.path.name


# =================================================================================================
# electrodes — ⭐ THE DEVICE SPEC IS SERVED, so the UI never has to retype it (R45.8)
# =================================================================================================


def test_the_device_spec_is_served_and_it_IS_MAXWELL(client):
    """🔴 **THE NUMBERS ON THE WIRE ARE `MAXWELL`'S — asserted against the dataclass, never against
    literals.** R45.8 makes 220 x 120 at 17.5 µm *binding* when the user declares "whole chip
    imaged", and the UI has to state that bargain before he can press Map. It was stating it from a
    hard-coded copy in TypeScript, so changing `DeviceSpec` would have left the panel promising one
    array while the fitter enforced another — a lie the type system cannot catch and the user
    cannot see.

    ⚠️ A literal in this test would rebuild exactly that second copy, one layer down. It compares
    the response with the spec object, so the day the device changes this test changes with it — and
    a route that answered from its own constants goes red."""
    from camea.core.electrodegrid import MAXWELL

    r = client.get("/api/electrodes/device")
    assert r.status_code == 200, r.text
    d = r.json()

    assert d["name"] == MAXWELL.name
    assert d["axes"] == [int(MAXWELL.axes[0]), int(MAXWELL.axes[1])]
    assert d["pitch_um"] == MAXWELL.pitch_um
    assert d["electrodes"] == MAXWELL.electrodes
    # the count is DERIVED, so the wire can never carry a shape and a total that disagree
    assert d["electrodes"] == d["axes"][0] * d["axes"][1]


def test_the_device_route_is_CORE_and_knows_nothing_about_a_feature(client):
    """⛔ Both features map electrodes off the same `core.electrodegrid`, and the coverage control is
    mounted by both — so the spec hangs off `/api/electrodes/…`, not under `/api/mosaic/…`. It also
    costs nothing: no session, no project, no pixels, on a completely cold app."""
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/electrodes/device" in paths
    assert "/api/mosaic/electrodes/device" not in paths

    assert client.get("/api/electrodes/device").status_code == 200
    assert client.get("/api/sessions").json()["sessions"] == []   # nothing was opened to answer it


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


def test_there_is_no_route_that_opens_a_project_in_explorer(client):
    """⛔ **R44: the app is the only door to project data.** `POST /api/fs/reveal` opened a project
    folder in Explorer and is DELETED — asserted against the contract, because the SPA catch-all
    serves index.html for an unmatched path and a deleted route would otherwise 200 with HTML."""
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/fs/reveal" not in paths


# =================================================================================================
# datasets — the browser
# =================================================================================================


def test_looking_at_a_folder_reports_what_is_in_it(client, synth):
    body = scan_at(client, synth.path.parent)
    ds = next(d for d in body["datasets"] if d["name"] == synth.path.name)

    assert ds["n_snapshots"] == len(synth.trials) + 4        # 3 strays + 1 off-shape
    assert ds["experiment"] == "synth"
    shapes = {(s["w"], s["h"]): s["n"] for s in ds["shapes"]}
    assert shapes[(TILE, TILE)] == len(synth.trials) + 3
    assert shapes[OFF_SHAPE] == 1                            # ⛔ REPORTED. Core does not gate on it.

    # ⛔ and NOTHING was remembered — there is no root registry any more.
    assert set(client.get("/api/settings").json()) == {"recent_datasets"}


def test_dataset_detail_and_thumbnail_cost_no_session(client, synth):
    key = scan_at(client, synth.path.parent)["datasets"][0]["key"]

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
# projects — ⭐ CAMEA'S OWN STORE (R44). The user names the DATA path and nothing else.
# =================================================================================================


def test_the_home_screen_starts_empty_and_that_is_not_an_error(client):
    """⭐ There is no store to choose first — the app owns it (R44) — so there is no `no_workspace`
    409 to hit. No projects yet is a 200 and an empty list, the honest first-run state."""
    r = client.get("/api/projects")
    assert r.status_code == 200
    assert r.json()["analyses"] == []


def test_the_app_names_the_project_folder_and_the_user_is_never_asked(client, synth, state_dir):
    """⭐ **R44, THE WHOLE RULING IN ONE TEST.** *"camea saves project-specific files to its own repo
    automatically."* Create carries **no** folder, and the project lands in the store under an id."""
    s = open_session(client, synth.path, synth.trials)
    r = new_project(client, s["session_id"], name="pass 1", trials=synth.trials)
    assert r.status_code == 201, r.text
    a = r.json()

    folder = Path(a["folder"])
    assert folder.parent == store_dir(state_dir), f"{folder} is not in Camea's store"
    assert folder.name == a["analysis_id"], "the id IS the folder name"
    assert (folder / "camea-project.json").is_file()
    assert (folder / "document.camea.json").is_file()


def test_create_refuses_a_folder_it_was_never_offered(client, synth):
    """⛔ **THE CONTRACT HAS NO `folder` (R44).** Not "ignored" — absent. A build that still sent one
    would be a front end that still believes it chooses where the user's work lives."""
    props = client.get("/openapi.json").json()["components"]["schemas"]["CreateAnalysisRequest"]
    assert "folder" not in props["properties"]
    assert "/api/projects/folder" not in client.get("/openapi.json").json()["paths"]


def test_two_projects_of_the_same_name_are_two_folders(client, synth):
    """🔴 Under R42 a second project in the same folder was **refused**, because overwriting one is
    how a day of sweeping disappears. In the store there is nothing to overwrite: the id is the
    folder name, so the same name twice is simply two projects."""
    s = open_session(client, synth.path, synth.trials)
    first = new_project(client, s["session_id"], name="same")
    second = new_project(client, s["session_id"], name="same")
    assert first.status_code == 201 and second.status_code == 201

    a, b = first.json(), second.json()
    assert a["analysis_id"] != b["analysis_id"]
    assert a["folder"] != b["folder"]
    assert len(client.get("/api/projects").json()["analyses"]) == 2


# =================================================================================================
# documents — the server authors them
# =================================================================================================


def test_the_SERVER_creates_the_document(client, synth):
    """🔴 In v1 `new_doc()` was dead code and the front end built the document in JavaScript — which
    is how the divert counters were dropped on every save. **The document is authored on the
    server.**"""
    s = open_session(client, synth.path, synth.trials)
    r = client.post("/api/projects",
                    json={"session_id": s["session_id"], "feature": "mosaic", "name": "pass 1",
                          "trials": synth.trials})
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


def test_an_unknown_feature_is_a_400_not_a_guess(client, synth):
    s = open_session(client, synth.path, synth.trials)
    r = client.post("/api/projects",
                    json={"session_id": s["session_id"], "feature": "segmentation", "name": "x"})
    assert r.status_code == 400


def test_save_load_autosave_and_the_derived_gaps(client, synth):
    """⚠️ `gaps` is DERIVED and is recomputed on every save. Trial numbers are acquisition ORDER but
    stop being CONTIGUOUS the moment the human excludes one — and across a gap the serpentine
    one-axis step prior does NOT hold."""
    s = open_session(client, synth.path, synth.trials)
    aid = client.post("/api/projects",
                      json={"session_id": s["session_id"], "feature": "mosaic", "name": "sweep",
                            "trials": synth.trials}).json()["analysis_id"]
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


def test_the_slot_guard_refuses_someone_elses_document(client, synth):
    """🔴 Pass 2's autosave once silently overwrote pass 1's ground-truth records. A document may only
    be written into the analysis whose `id` it carries. **Not merged, not renamed, not "repaired".**"""
    s = open_session(client, synth.path, synth.trials)
    mk = lambda name: client.post(  # noqa: E731
        "/api/projects",
        json={"session_id": s["session_id"], "feature": "mosaic", "name": name,
              "trials": synth.trials}).json()["analysis_id"]
    a1, a2 = mk("one"), mk("two")

    doc1 = client.get(f"/api/analyses/{a1}/document").json()["doc"]
    r = client.put(f"/api/analyses/{a2}/document", json={"doc": doc1})
    assert r.status_code == 409
    assert err(r)["code"] == "range_mismatch"


def test_save_as_and_a_COLD_load(client, synth, tmp_path):
    """⭐ *"Load a project…"* must work **cold**, with no session. The app remembers nothing between
    launches, so this file is its only memory: save -> quit -> load restores the session whole."""
    s = open_session(client, synth.path, synth.trials)
    aid = client.post("/api/projects",
                      json={"session_id": s["session_id"], "feature": "mosaic", "name": "cold",
                            "trials": synth.trials}).json()["analysis_id"]
    doc = client.get(f"/api/analyses/{aid}/document").json()["doc"]

    out = tmp_path / "handed-out.camea.json"
    r = client.post("/api/documents/save-as", json={"path": str(out), "doc": doc})
    assert r.status_code == 200 and out.is_file()

    client.delete(f"/api/sessions/{s['session_id']}")        # <- the app now knows NOTHING
    assert client.get("/api/sessions").json()["sessions"] == []

    body = load_document(client, out)
    assert body["session"] is not None                       # bootstrapped from the doc's data_dir
    assert body["session"]["n"] == len(synth.trials)
    assert body["doc"]["id"] == aid


def test_a_COLD_load_still_REFUSES_on_the_request(client, synth, tmp_path):
    """🔴 **R48 made the load a job; the guards did NOT move into it.** They need the dataset's
    identity and not one pixel, so every one of them is still 4xx on the request that asked —
    a refusal that arrived as a failed job five seconds later would be a regression.

    ⭐ The load-bearing one is the **range guard**: a document for a different acquisition is
    `409 range_mismatch`, and that is what stops pass 2's file quietly overwriting pass 1's."""
    # a file that is not there
    r = client.post("/api/documents/load", json={"path": str(tmp_path / "ghost.camea.json")})
    assert r.status_code == 404 and err(r)["code"] == "not_found"

    s = open_session(client, synth.path, synth.trials)
    aid = client.post("/api/projects",
                      json={"session_id": s["session_id"], "feature": "mosaic", "name": "guard",
                            "trials": synth.trials}).json()["analysis_id"]
    doc = client.get(f"/api/analyses/{aid}/document").json()["doc"]

    # ⛔ a document that says nothing about where its data came from, loaded cold
    orphan = dict(doc, data_dir="")
    p = tmp_path / "orphan.camea.json"
    assert client.post("/api/documents/save-as",
                       json={"path": str(p), "doc": orphan}).status_code == 200
    client.delete(f"/api/sessions/{s['session_id']}")
    r = client.post("/api/documents/load", json={"path": str(p)})
    assert r.status_code == 400 and err(r)["code"] == "bad_request"


def test_save_as_INTO_the_dataset_is_refused(client, synth):
    s = open_session(client, synth.path, synth.trials)
    aid = client.post("/api/projects",
                      json={"session_id": s["session_id"], "feature": "mosaic", "name": "x",
                            "trials": synth.trials}).json()["analysis_id"]
    doc = client.get(f"/api/analyses/{aid}/document").json()["doc"]
    r = client.post("/api/documents/save-as",
                    json={"path": str(synth.path / "sneaky.camea.json"), "doc": doc})
    assert r.status_code == 409
    assert err(r)["code"] == "refused"


def test_validate_never_rejects_a_document_for_WHICH_trials_it_placed(client, synth):
    """⛔ **NO TRIAL NUMBER IS SPECIAL.** v1's guard ("tile 284 is thrown out and carries a position")
    made the user's own session unsaveable the moment he anchored 284."""
    s = open_session(client, synth.path, synth.trials)
    aid = client.post("/api/projects",
                      json={"session_id": s["session_id"], "feature": "mosaic", "name": "v",
                            "trials": synth.trials}).json()["analysis_id"]
    doc = client.get(f"/api/analyses/{aid}/document").json()["doc"]

    for t in synth.trials:                                   # anchor EVERY tile, by hand
        doc["tiles"][str(t)].update({"state": "anchored", "status": "anchor",
                                     "x": 0.0, "y": 0.0, "human": True})
    r = client.post("/api/documents/validate", json={"doc": doc})
    assert r.status_code == 200
    assert r.json()["ok"] is True, r.json()["problems"]
    assert client.put(f"/api/analyses/{aid}/document", json={"doc": doc}).status_code == 200


def test_delete_an_analysis(client, synth, state_dir):
    """⭐ **DELETE MEANS DELETE (R44).** R42.8's Remove-vs-Delete is retired: the folder is Camea's,
    so a project the app stops listing is one nobody could ever reach again. `delete_files` is gone
    and the whole folder goes."""
    s = open_session(client, synth.path, synth.trials)
    a = new_project(client, s["session_id"], name="d", trials=synth.trials).json()
    aid, folder = a["analysis_id"], Path(a["folder"])
    assert folder.is_dir()

    assert client.delete(f"/api/projects/{aid}").json() == {"ok": True}
    assert client.get("/api/projects").json()["analyses"] == []
    assert not folder.exists(), "the store folder is Camea's; delete takes all of it"
    assert store_entries() == [], "and leaves nothing behind in the store"
    assert client.delete(f"/api/projects/{aid}").status_code == 404


# =================================================================================================
# OUTPUTS — ⭐ THE ONLY DOOR TO A PROJECT'S FILES (R44)
# =================================================================================================


def _built(client, synth, name: str = "p", files: dict[str, bytes] | None = None):
    """A project with some files in its `outputs/`. -> `(analysis_id, outputs_dir)`.

    ⚠️ Written straight to disk rather than by running a build: these tests are about the *browser*,
    and a real mosaic build here would test the mosaic feature instead.
    """
    s = open_session(client, synth.path, synth.trials)
    a = new_project(client, s["session_id"], name=name, trials=synth.trials).json()
    out = Path(a["folder"]) / "outputs"
    out.mkdir(parents=True, exist_ok=True)
    for fn, data in (files or {"mosaic.png": b"\x89PNG\r\n\x1a\n fake", "qc.md": b"# qc"}).items():
        (out / fn).write_bytes(data)
    return a["analysis_id"], out


def test_outputs_are_listed_off_the_directory_not_the_document(client, synth):
    """⭐ The browser's whole source. It answers *what is there*, not what the last build recorded —
    a file written by an older Camea, or deleted underneath us, has to show up as it actually is."""
    aid, out = _built(client, synth)
    r = client.get(f"/api/projects/{aid}/outputs")
    assert r.status_code == 200, r.text
    by_name = {o["name"]: o for o in r.json()["outputs"]}

    assert set(by_name) == {"mosaic.png", "qc.md"}
    assert by_name["mosaic.png"]["previewable"] is True
    assert by_name["mosaic.png"]["media_type"] == "image/png"
    assert by_name["qc.md"]["previewable"] is False          # offered as a copy, never rendered
    assert by_name["qc.md"]["bytes"] == 4

    (out / "qc.md").unlink()                                 # gone from disk -> gone from the list
    assert {o["name"] for o in client.get(f"/api/projects/{aid}/outputs").json()["outputs"]} \
        == {"mosaic.png"}


def test_a_project_with_nothing_built_lists_empty_and_that_is_not_a_404(client, synth):
    s = open_session(client, synth.path, synth.trials)
    aid = new_project(client, s["session_id"], trials=synth.trials).json()["analysis_id"]
    r = client.get(f"/api/projects/{aid}/outputs")
    assert r.status_code == 200
    assert r.json()["outputs"] == []


def test_an_output_is_served_and_can_be_asked_for_as_a_download(client, synth):
    aid, _ = _built(client, synth)
    r = client.get(f"/api/projects/{aid}/outputs/mosaic.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert "attachment" not in r.headers.get("content-disposition", "")

    d = client.get(f"/api/projects/{aid}/outputs/mosaic.png", params={"download": True})
    assert 'attachment; filename="mosaic.png"' in d.headers["content-disposition"]


@pytest.mark.parametrize("name", ["...", "..\\secret", "mosaic.png:stream", "*.png", " "])
def test_an_output_name_cannot_escape_the_outputs_folder(client, synth, name):
    """🔴 `name` arrives over HTTP and is never used to build a path blind. `outputs/` is flat by
    construction, so a name that needs a separator is a name that is trying something."""
    aid, _ = _built(client, synth)
    r = client.get(f"/api/projects/{aid}/outputs/{name}")
    assert r.status_code in (400, 404), r.text


@pytest.mark.parametrize("name", ["..", "../../camea-project.json", "../../../settings.json",
                                  "sub/mosaic.png"])
def test_a_traversing_output_name_never_reaches_the_handler_at_all(client, synth, name):
    """⚠️ `".."` is here rather than above because httpx **normalises it out of the URL** before the
    request is sent, so it never tests the server at all from that side.

    A name containing a **separator** does not match this route — the SPA catch-all answers it
    with `index.html`, so the status is a 200 and means nothing. What matters is what it is NOT: the
    file it was reaching for. Asserted on the bytes, because a status code would pass either way."""
    aid, _ = _built(client, synth)
    r = client.get(f"/api/projects/{aid}/outputs/{name}")
    assert b"camea_project" not in r.content
    assert b"recent_datasets" not in r.content
    assert not r.headers["content-type"].startswith("image/")


def test_copying_outputs_out_is_a_COPY_and_the_project_keeps_them(client, synth, outbox):
    """⭐ *"click into a project and browse your outputs, select the one(s) you want and save it into
    somewhere."* The store stays the home; what leaves is a copy he asked for."""
    aid, out = _built(client, synth)
    dest = outbox / "for-the-paper"

    res = copy_outputs(client, aid, ["mosaic.png", "qc.md"], dest)
    assert sorted(Path(p).name for p in res["copied"]) == ["mosaic.png", "qc.md"]
    assert (dest / "mosaic.png").read_bytes() == (out / "mosaic.png").read_bytes()
    assert (out / "mosaic.png").is_file(), "a copy is not a move"
    # ⏱️ R48 — the bar was counting BYTES, and the result says how many it counted.
    assert res["bytes"] == sum((out / n).stat().st_size for n in ("mosaic.png", "qc.md"))


def test_copying_out_refuses_to_write_over_HIS_files(client, synth, outbox):
    """⛔ The destination is the user's folder. A clash refuses the WHOLE request and names the
    files — never half a copy with one of his overwritten."""
    aid, _ = _built(client, synth)
    (outbox / "mosaic.png").write_bytes(b"something of his")

    r = client.post(f"/api/projects/{aid}/outputs/copy",
                    json={"names": ["mosaic.png", "qc.md"], "dest": str(outbox)})
    assert r.status_code == 409
    assert err(r)["code"] == "refused"
    assert "mosaic.png" in err(r)["message"]
    assert (outbox / "mosaic.png").read_bytes() == b"something of his"
    assert not (outbox / "qc.md").exists(), "refused means nothing was written, not some of it"


def test_copying_out_INTO_the_dataset_is_refused(client, synth):
    """⛔ **THE APP DOES NOT WRITE ON THE EVIDENCE** — and an export is still a write."""
    aid, _ = _built(client, synth)
    r = client.post(f"/api/projects/{aid}/outputs/copy",
                    json={"names": ["mosaic.png"], "dest": str(synth.path / "exports")})
    assert r.status_code == 409
    assert err(r)["code"] == "refused"


def test_copying_an_output_that_is_not_this_projects_is_refused(client, synth):
    aid, _ = _built(client, synth, name="mine")
    other, _ = _built(client, synth, name="theirs", files={"secret.csv": b"x"})

    r = client.post(f"/api/projects/{aid}/outputs/copy",
                    json={"names": ["secret.csv"], "dest": str(synth.path.parent / "nope")})
    assert r.status_code == 404
    assert other != aid


def test_rename_a_project_rewrites_the_manifest_and_keeps_the_id(client, synth):
    """The project manager's rename: `PATCH /api/projects/{id}`. It rewrites the manifest
    name; the id (the directory) is forever, so the slot guard and every stored path keep working."""
    s = open_session(client, synth.path, synth.trials)
    aid = client.post("/api/projects",
                      json={"session_id": s["session_id"], "feature": "mosaic", "name": "before",
                            "trials": synth.trials}).json()["analysis_id"]
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
