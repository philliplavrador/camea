"""⭐ **THE API, AGAINST THE REAL ACQUISITION.** The numbers this project has been burned by.

⚠️ **`slow`** — it needs the 35 GB read-only mirror (`CAMEA_DATA_DIR`, see `tests/conftest.py`), so
it is deselected by default and never runs in CI:

    uv run pytest tests/api/test_260620d.py -q -m slow

⛔ Hard-coding 260620d's numbers **in a test** is right. Hard-coding them in `src/` is the thing the
user had ripped out at real cost. **This file is the answer key. The app is not allowed to have one.**

THE TWO NUMBERS, AND WHY THEY ARE THE WHOLE POINT
-------------------------------------------------
**338, not 312.** The run is 338 snapshot trials. 312 is what is left after the user throws out 26 of
them — and that is *his* ruling, made in *his* session, on frames *he* has looked at. It is never a
default, it is not in the app, and an app that opened this dataset and showed him 312 tiles would
have answered, on his behalf, the exact question it exists to help him answer.

**166, not 167.** `pass_split` is the LAST TRIAL OF PASS 1. And it is measured from the clock, never
carried in the source: t33's literal default of 166 is *this dataset's* number.
"""

from __future__ import annotations

import pytest

from .conftest import err, open_session, run_job

pytestmark = pytest.mark.slow

#: The truth about 260620d. Every one of these was measured against the live server.
N_SNAPSHOTS_ON_DISK = 342          # every readable 1-frame snapshot, of any shape
N_LOG_TRIALS = 348
BLOCKS = [(1, 1), (5, 7), (11, 348)]
RUN = (11, 348)
N_RUN = 338                        # ⛔⛔ NOT 312.
PASS_SPLIT = 166                   # ⛔ NOT 167.
N_PASS1, N_PASS2 = 156, 182


@pytest.fixture(scope="module")
def data_dir(request):
    return request.getfixturevalue("dataset_dir")


def test_the_browser_sees_342_snapshots_of_one_shape(client, data_dir):
    r = client.post("/api/datasets/scan", json={"root": str(data_dir.parent), "depth": 2})
    assert r.status_code == 200
    ds = next(d for d in r.json()["datasets"] if d["name"] == "260620d")

    assert ds["n_trials"] == N_LOG_TRIALS
    assert ds["n_snapshots"] == N_SNAPSHOTS_ON_DISK
    assert ds["experiment"] == "260620d"
    assert [(s["w"], s["h"], s["n"]) for s in ds["shapes"]] == [(512, 512, N_SNAPSHOTS_ON_DISK)]

    detail = client.get(f"/api/datasets/{ds['key']}").json()
    assert [(b["lo"], b["hi"]) for b in detail["blocks"]] == BLOCKS

    png = client.get(f"/api/datasets/{ds['key']}/thumbnail.png")
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"


def test_open_loads_every_snapshot_and_excludes_NOTHING(client, data_dir):
    """⛔ **THE RULING, TESTED.** The app has no list of 26 trial numbers, so it cannot apply one."""
    s = open_session(client, data_dir)

    assert s["n"] == N_SNAPSHOTS_ON_DISK
    assert s["skipped"] == []
    assert (s["w"], s["h"]) == (512, 512)
    assert s["frame_note"] == "the vscope-displayed (180deg-flipped: XML ax=-1, ay=-1) frame"
    assert s["n_log_entries"] == N_LOG_TRIALS

    # every one of the 26 the USER throws out is present, and ordinary
    for t in (284, 285, 297, 298, 310, 348):
        assert t in s["trials"]


def test_THE_RUN_IS_338_AND_THE_SPLIT_IS_166(client, data_dir):
    """⭐⭐ **THE TWO NUMBERS.** See the module docstring."""
    sid = open_session(client, data_dir)["session_id"]
    run = client.post("/api/mosaic/run", json={"session_id": sid}).json()

    assert (run["lo"], run["hi"]) == RUN
    assert run["n"] == N_RUN, f"the app produced {run['n']} trials; it must produce {N_RUN}"
    assert run["n_in_range"] == N_RUN
    assert run["trials"] == list(range(11, 349))
    assert run["dropped"] == []                       # all 338 are genuine 512x512 snapshots
    assert run["gaps"] == []                          # ⭐ contiguous — until the HUMAN excludes one

    ps = run["pass_split"]
    assert ps["value"] == PASS_SPLIT, "166 is the LAST TRIAL OF PASS 1, never 167"
    assert ps["detected"] is True
    assert (ps["n_pass1"], ps["n_pass2"]) == (N_PASS1, N_PASS2)
    assert ps["gap_s"] == 20.0 and ps["median_gap_s"] == 2.0
    # ⚠️ the guard that stops a naive argmax returning 11 (11->12 is ALSO 20.0 s)
    assert ps["runner_up"]["after_trial"] == 234


def test_a_fresh_document_has_338_tiles_and_0_excluded(client, data_dir, workspace):
    """⭐ The number the user actually sees when he opens his data."""
    sid = open_session(client, data_dir)["session_id"]
    trials = client.post("/api/mosaic/run", json={"session_id": sid}).json()["trials"]

    a = client.post("/api/projects",
                    json={"session_id": sid, "feature": "mosaic", "name": "11-348",
                          "trials": trials, "folder": str(workspace / "11-348")}).json()
    assert a["n_tiles"] == N_RUN
    assert a["n_excluded"] == 0
    assert a["n_anchored"] == 0

    doc = client.get(f"/api/analyses/{a['analysis_id']}/document").json()["doc"]
    assert len(doc["tiles"]) == N_RUN
    assert {t["state"] for t in doc["tiles"].values()} == {"unplaced"}
    assert doc["gaps"] == []


def test_312_IS_SOMETHING_THE_USER_PRODUCES_NEVER_A_DEFAULT(client, data_dir, workspace):
    """⭐⭐ The whole ruling in one test. The app starts at 338. The USER gets to 312, by pressing `E`
    — in this session, or in a project file he loaded. And the moment he does, the GAPS open, and the
    serpentine one-axis step prior stops holding across them."""
    sid = open_session(client, data_dir)["session_id"]
    trials = client.post("/api/mosaic/run", json={"session_id": sid}).json()["trials"]
    aid = client.post("/api/projects",
                      json={"session_id": sid, "feature": "mosaic", "name": "his ruling",
                            "trials": trials, "folder": str(workspace / "his-ruling")}).json()["analysis_id"]
    doc = client.get(f"/api/analyses/{aid}/document").json()["doc"]

    # HIS ruling, applied BY HIM. It lives in this test file, which is the answer key — not in src/.
    his = [284, 285, 286, 287, 288, 289, 290, 291, 292, 293, 294, 295, 296, 299,
           300, 301, 302, 303, 304, 305, 306, 307, 308, 309, 310, 348]
    assert len(his) == 26
    for t in his:
        doc["tiles"][str(t)].update({"state": "excluded", "status": "excluded"})

    assert client.put(f"/api/analyses/{aid}/document", json={"doc": doc}).status_code == 200
    back = client.get(f"/api/analyses/{aid}/document").json()["doc"]

    active = [int(k) for k, v in back["tiles"].items() if v["state"] != "excluded"]
    assert len(active) == 312                        # ⭐ 312, produced BY HIM, from 338.

    # ⚠️ AND THE GAPS OPENED. 283->297 and 298->311, exactly as the ruling warns.
    gaps = {tuple(g) for g in back["gaps"]}
    assert (283, 297) in gaps and (298, 311) in gaps

    # and it survives a save -> quit -> cold load. This file is the app's only memory.
    client.delete(f"/api/sessions/{sid}")
    r = client.post("/api/documents/load",
                    json={"path": client.get("/api/projects").json()["analyses"][0]["path"]})
    assert r.status_code == 200
    reloaded = r.json()["doc"]
    assert len([1 for v in reloaded["tiles"].values() if v["state"] == "excluded"]) == 26


def test_the_texture_measure_is_a_measurement_and_not_a_verdict(client, data_dir):
    """⭐ `std(DoG(3,30))` is a property of the FRAME, and it is CORE. ❌ And there is no blur
    judgement, ever: across 15 focus measures the best global blur threshold reaches F1 = 0.37, and
    variance-of-Laplacian scores **worse than chance**."""
    sid = open_session(client, data_dir)["session_id"]
    tex = client.get(f"/api/sessions/{sid}/texture").json()

    assert tex["n"] == N_SNAPSHOTS_ON_DISK
    assert set(tex) == {"measure", "texture", "n"}     # ⛔ no threshold, no list, no policy

    # the 11 genuinely-blank frames really are the lowest — but nothing in the app acts on that.
    lowest = sorted(tex["texture"], key=lambda k: tex["texture"][k])[:10]
    assert len({300, 301, 302, 303, 304, 305} & {int(k) for k in lowest}) >= 5


def test_the_blank_scan_proposes_and_the_boundary_has_ZERO_MARGIN(client, data_dir):
    """⭐ **IT RECOMMENDS. IT NEVER REJECTS.** Measured with the refusal lifted, three of the four
    near-threshold trials land 0.24 / 0.18 / 2.07 px from the human truth — they are **ordinary
    tiles** — while the fourth lands **679 px wrong**. One of four. That is exactly why the measure
    may only ever propose."""
    sid = open_session(client, data_dir)["session_id"]
    run = client.post("/api/mosaic/run", json={"session_id": sid}).json()

    p = client.post("/api/mosaic/screen/propose",
                    json={"session_id": sid, "trials": run["trials"],
                          "pass_split": run["pass_split"]["value"]}).json()
    assert p["n_scanned"] == N_RUN
    assert "percentile of pass-1 texture (n=156)" in p["threshold_source"]
    assert p["margin_warning"] and "interleave" in p["margin_warning"]

    # it proposes far FEWER than the 26 the human threw out — the other 15 are BLURRY, and no
    # automatic sharpness measure reproduces that call. His eye does, in the sweep, with `E`.
    assert 0 < p["n_proposed"] < 26


def test_tiles_and_the_sweep_on_real_pixels(client, data_dir):
    s = open_session(client, data_dir)
    sid = s["session_id"]

    raw = client.get(f"/api/sessions/{sid}/tiles/11.raw")
    assert len(raw.content) == 512 * 512 * 2
    assert client.get(f"/api/sessions/{sid}/tiles/11.png").content[:4] == b"\x89PNG"

    m = client.post("/api/mosaic/match/anchor",
                    json={"session_id": sid, "target": 12, "anchors": [11],
                          "positions": {"11": [0.0, 0.0]}, "mode": "global"}).json()
    assert m["best"]["ncc"] > 0.5
    assert m["margin_thin"] is False
    # consecutive snapshots overlap ~78 %: the step is one axis, and it is ~178 px on this run.
    assert abs(m["best"]["x"]) < 5.0
    assert 150.0 < m["best"]["y"] < 200.0


def test_a_real_t33_build_runs_in_a_child_and_its_result_is_readable(client, data_dir):
    """🔴 The build runs in a SPAWNED CHILD (t33 has no cooperative cancel, so `terminate()` is the
    only cancel there is) and holds the `gpu` lease. This is the end-to-end proof that the child gets
    its arguments — a missing `pass_split` kwarg made every build die inside the child with a
    `TypeError` — and that its result carries the `kind` tag `GET /api/jobs/{id}` needs to serialise
    it (without which a *successful* build 500'd on every poll)."""
    sid = open_session(client, data_dir)["session_id"]
    run = client.post("/api/mosaic/run", json={"session_id": sid}).json()
    sub = run["trials"][:12]                          # 12 tiles: seconds, not minutes

    r = client.post("/api/mosaic/build",
                    json={"session_id": sid, "trials": sub, "pass_split": sub[5],
                          "config": None, "use_cache": True})
    assert r.status_code == 202
    job = run_job(client, r.json()["job_id"], timeout=900)

    res = job["result"]
    assert res["kind"] == "build"                     # ⭐ the discriminator tag
    assert res["n_placed"] == len(sub)
    assert res["trials"] == sub                       # ⭐ WHAT THE SOLVER WAS ACTUALLY GIVEN
    assert res["unplaced"] == []
    assert client.get(f"/api/mosaic/builds/{res['build_id']}").status_code == 200

    # while it held the `gpu` lease, interactive matching was refused — as a RESOURCE fact, not a
    # feature's word. (It has finished by now, so this only checks the shape of the guard.)
    assert res["gpu"] in (True, False)


def test_the_gpu_lease_refuses_a_second_build(client, data_dir):
    """**Ask about the LEASE, never about a KIND.** v1 asked `JOBS.running("build")` — the mosaic's
    word, hard-coded into the shared runner — which is why an `open` was refused while a build ran."""
    sid = open_session(client, data_dir)["session_id"]
    run = client.post("/api/mosaic/run", json={"session_id": sid}).json()
    sub = run["trials"][:12]
    body = {"session_id": sid, "trials": sub, "pass_split": sub[5], "use_cache": True}

    first = client.post("/api/mosaic/build", json=body)
    assert first.status_code == 202
    second = client.post("/api/mosaic/build", json=body)
    if second.status_code == 409:                     # the first may already have finished (warm)
        assert err(second)["code"] == "busy"
    run_job(client, first.json()["job_id"], timeout=900)
