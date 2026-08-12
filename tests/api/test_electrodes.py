"""The electrode-mapping API, end to end (2026-08-11).

Snapshot side: a synthetic acquisition whose tiles carry a PLANTED electrode lattice with a
known answer key (the unit suite's own generator — same truth discipline as every fixture
here: cut from one source, judged against where things actually are). The document is
hand-anchored at the truth offsets, saved through the real PUT (validate → normalise →
stamp), mapped, and the resulting grid ids are checked RELATIVELY against planted pads —
`col`/`row` deltas between two known pads must equal the planted deltas exactly.

Video side: a survey video of a world that carries the same planted lattice, built by the
real pipeline, then mapped off the saved mosaic.png.

⭐ The committed gridless fixtures stay byte-identical — and double as the negative test:
mapping them must REFUSE (a clean job failure naming the lattice), never hallucinate a grid.

R45.8 — the device and what he declared about it. Both fixtures are small planted fields, so
they exercise `array_coverage="partial"` positively (the 17.5 µm scale, and nothing else
assumed) and `array_coverage="full"` negatively: a 34 × 46 field is NOT a 220 × 120
MaxOne/MaxTwo, and claiming the whole chip must refuse rather than invent 25,000 electrodes.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

from unit.test_electrodegrid import lattice_image

from .conftest import _XML, TILE, err, new_project, open_session, run_job

# =================================================================================================
# The grid acquisition — two 512x512 snapshot tiles cut from one lattice world
# =================================================================================================

GRID_PITCH = 14.0
GRID_ANGLE = -2.0
STEP_Y = 128          # trial 12 sits one stage step below trial 11: 75 % overlap, like the suite's


def _write_grid_dataset(root: Path):
    """Two snapshot trials cut from one planted-lattice world at known offsets.
    -> (root, truth) where truth maps (col, row) -> WORLD px (trial 11's top-left = world 0,0)."""
    root.mkdir(parents=True, exist_ok=True)
    img, truth, _ = lattice_image(cols=34, rows=46, pitch=GRID_PITCH, angle_deg=GRID_ANGLE,
                                  margin=36, seed=5)
    src = np.clip(img * 18.0, 0, 65535).astype(np.uint16)
    assert src.shape[0] >= TILE + STEP_Y + 4 and src.shape[1] >= TILE + 4

    lines = ["06/20/26 15:46:58 New experiment: grid", "         15:47:05 Settings loaded: grid"]
    for i, trial in enumerate((11, 12)):
        x, y = 4, 4 + i * STEP_Y
        tile = src[y:y + TILE, x:x + TILE]
        raw = np.flip(np.flip(tile, 0), 1)                   # the reader flips it BACK (ax=-1)
        np.ascontiguousarray(raw, dtype="<u2").tofile(root / f"{trial:03d}-ccd.dat")
        (root / f"{trial:03d}.xml").write_text(
            _XML.format(typ="snapshot", trial=trial, frames=1, w=TILE, h=TILE, ax=-1, ay=-1,
                        time="154700"),
            encoding="utf-8")
        lines.append(f"         15:48:{2 * i:02d} Trial {trial:03d}: Snapshot")
    (root / "log.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    world_truth = {cr: (sx - 4.0, sy - 4.0) for cr, (sx, sy) in truth.items()}
    return root, world_truth


@pytest.fixture(scope="session")
def grid_data(tmp_path_factory):
    return _write_grid_dataset(tmp_path_factory.mktemp("griddata") / "gridd")


def _anchored_doc(client, session_id: str, analysis_id: str) -> dict:
    """The project's own document with trials 11/12 anchored at the truth offsets."""
    doc = client.get(f"/api/analyses/{analysis_id}/document").json()["doc"]
    for trial, (x, y) in ((11, (0.0, 0.0)), (12, (0.0, float(STEP_Y)))):
        t = dict(doc["tiles"][str(trial)])
        t.update(state="anchored", status="anchor", x=x, y=y, human=True)
        doc["tiles"][str(trial)] = t
    return doc


def _run_to_failure(client, job_id: str, timeout: float = 120.0) -> str:
    """Poll a job that is EXPECTED to fail and return its message. (`run_job` asserts success —
    a refusal is the result here, so it needs its own loop.)"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["state"] in ("done", "failed", "cancelled"):
            break
        time.sleep(0.05)
    assert j["state"] == "failed", j
    return (j.get("error") or {}).get("message", "")


def _nearest_cell(payload: dict, x: float, y: float):
    """Test-side lookup: nearest existing cell, or None outside the hit radius —
    re-implemented here so the server's own lookup is judged, not trusted."""
    c = payload["cells"]
    xs = np.asarray(c["x"], float)
    ys = np.asarray(c["y"], float)
    d = np.hypot(xs - x, ys - y)
    i = int(np.argmin(d))
    if d[i] > payload["hit_radius_px"]:
        return None
    return c["col"][i], c["row"][i], float(d[i])


# =================================================================================================
# Snapshot mosaic
# =================================================================================================
def test_map_then_lookup_matches_the_planted_lattice(client, grid_data):
    root, truth = grid_data
    session = open_session(client, root)
    sid = session["session_id"]
    a = new_project(client, sid, name="gridp", trials=[11, 12]).json()
    aid = a["analysis_id"]
    doc = _anchored_doc(client, sid, aid)

    put = client.put(f"/api/analyses/{aid}/document", json={"doc": doc})
    assert put.status_code == 200, put.text

    r = client.post("/api/mosaic/electrodes/map", json={"session_id": sid, "doc": doc})
    assert r.status_code == 202, r.text
    job = run_job(client, r.json()["job_id"])
    res = job["result"]
    assert res["kind"] == "electrode_map" and res["analysis_id"] == aid
    block = res["electrodes"]
    assert block["cols"] > 20 and block["rows"] > 30
    assert abs(block["pitch_px"] - GRID_PITCH) < 0.5
    assert abs(block["angle_deg"] - GRID_ANGLE) < 0.6

    g = client.get(f"/api/mosaic/electrodes/{aid}")
    assert g.status_code == 200, g.text
    payload = g.json()
    assert payload["canvas_offset"] == [0.0, 0.0]            # trial 11 anchors world (0,0)

    # ⭐ relative correctness against the PLANTED truth: two pads a known (5, 3) apart
    # must come back exactly (5, 3) apart, wherever 1-1 landed on the visible field
    a_cr, b_cr = (10, 10), (15, 13)
    hit_a = _nearest_cell(payload, *truth[a_cr])
    hit_b = _nearest_cell(payload, *truth[b_cr])
    assert hit_a and hit_b, "planted pads must resolve"
    assert hit_b[0] - hit_a[0] == b_cr[0] - a_cr[0]
    assert hit_b[1] - hit_a[1] == b_cr[1] - a_cr[1]
    assert hit_a[2] < 0.25 * payload["pitch_px"]

    # a click halfway between two pads selects nothing (his rule)
    ax, ay = truth[a_cr]
    nx, ny = truth[(11, 10)]
    assert _nearest_cell(payload, (ax + nx) / 2, (ay + ny) / 2) is None

    # the numbering is 1-based from the top-left of what is visible
    assert min(payload["cells"]["col"]) == 1 and min(payload["cells"]["row"]) == 1


def test_map_files_land_in_outputs_and_the_panel_lists_them(client, grid_data):
    root, _ = grid_data
    session = open_session(client, root)
    sid = session["session_id"]
    a = new_project(client, sid, name="gridq", trials=[11, 12]).json()
    aid = a["analysis_id"]
    doc = _anchored_doc(client, sid, aid)
    client.put(f"/api/analyses/{aid}/document", json={"doc": doc})

    r = client.post("/api/mosaic/electrodes/map", json={"session_id": sid, "doc": doc})
    run_job(client, r.json()["job_id"])

    names = [o["name"] for o in client.get(f"/api/projects/{aid}/outputs").json()["outputs"]]
    assert any(n.endswith("-electrodes.json") for n in names), names
    assert any(n.endswith("-electrodes.csv") for n in names), names

    csv_name = next(n for n in names if n.endswith("-electrodes.csv"))
    body = client.get(f"/api/projects/{aid}/outputs/{csv_name}").content.decode()
    # ⭐ R45.8: µm rides ALONGSIDE pixels — the copied-out CSV carries both, never one instead
    # of the other. (This header is the thing a user opens in Excel; it is part of the contract.)
    # 🔴 And the trailing `coverage` column: see the test below for WHY it cannot be optional.
    assert body.splitlines()[0] == "electrode,col,row,x,y,x_um,y_um,kind,coverage"
    assert ",detected," in body
    row = body.splitlines()[1].split(",")
    assert len(row) == 9, row
    float(row[5]), float(row[6])                             # x_um / y_um are real numbers
    assert row[7] in ("detected", "inferred")
    assert row[8] in ("full", "partial")


def test_the_csv_says_WHOSE_coordinates_it_carries_on_every_row(client, grid_data):
    """🔴 **THE COLUMN THAT STOPS A PARTIAL MAP READING AS A CHIP MAP.**

    In `partial` mode `1-1` is the top-left of the **IMAGED REGION**, so `x_um`/`y_um` are anchored
    there — not on the chip's own corner. The app says so everywhere it shows ids; the CSV did not,
    and the CSV is the artifact that LEAVES the app (R44: the user ticks it in the Outputs panel,
    copies it out and opens it in Excel, where every caveat the UI carried is gone). Two files, one
    of each mode, were then indistinguishable — same header, same-looking numbers, coordinates in
    two different frames.

    So every row states its frame. A constant column is the point: a spreadsheet gets sorted,
    filtered and pasted into another sheet a row at a time, and a single header cell would not
    survive any of that.
    """
    root, _ = grid_data
    session = open_session(client, root)
    sid = session["session_id"]
    aid = new_project(client, sid, name="gridcsv", trials=[11, 12]).json()["analysis_id"]
    doc = _anchored_doc(client, sid, aid)
    client.put(f"/api/analyses/{aid}/document", json={"doc": doc})

    r = client.post("/api/mosaic/electrodes/map",
                    json={"session_id": sid, "doc": doc, "array_coverage": "partial"})
    assert r.status_code == 202, r.text
    block = run_job(client, r.json()["job_id"])["result"]["electrodes"]

    csv_name = block["outputs"]["csv"]
    lines = client.get(f"/api/projects/{aid}/outputs/{csv_name}").content.decode().splitlines()
    assert lines[0].split(",")[-1] == "coverage"

    # ⭐ it is HIS declaration, echoed — the same string the document's block records, on every
    # single row, so no row of this file can be read out of its frame
    said = {ln.split(",")[-1] for ln in lines[1:] if ln}
    assert said == {block["array_coverage"]} == {"partial"}, sorted(said)[:4]


def test_partial_coverage_measures_the_micrometre_scale(client, grid_data):
    """⭐ R45.8, `partial`: no shape rule at all, but the 17.5 µm pitch still buys a MEASURED
    scale — µm/px is the device pitch over the pitch THIS mosaic shows, and every electrode
    carries its position in the array's own frame alongside its pixels."""
    root, _ = grid_data
    session = open_session(client, root)
    sid = session["session_id"]
    a = new_project(client, sid, name="gridum", trials=[11, 12]).json()
    aid = a["analysis_id"]
    doc = _anchored_doc(client, sid, aid)
    client.put(f"/api/analyses/{aid}/document", json={"doc": doc})

    r = client.post("/api/mosaic/electrodes/map",
                    json={"session_id": sid, "doc": doc, "array_coverage": "partial"})
    assert r.status_code == 202, r.text
    block = run_job(client, r.json()["job_id"])["result"]["electrodes"]

    # what the DOCUMENT remembers: the declaration, the scale, the device that supplied it
    assert block["array_coverage"] == "partial"
    assert block["device"] and "Max" in block["device"]
    assert abs(block["um_per_px"] - 17.5 / block["pitch_px"]) < 1e-3

    payload = client.get(f"/api/mosaic/electrodes/{aid}").json()
    assert payload["array_coverage"] == "partial"
    dev = payload["device"]
    assert dev["pitch_um"] == 17.5 and dev["electrodes"] == 26400
    assert sorted(dev["axes"]) == [120, 220]
    # a 14 px pitch under a 17.5 µm device: ~1.25 µm/px, and NOT the identity
    assert abs(payload["um_per_px"] - 17.5 / payload["pitch_px"]) < 1e-3

    c = payload["cells"]
    assert len(c["x_um"]) == len(c["col"]) and len(c["y_um"]) == len(c["col"])

    # ⭐ the frame is the ARRAY's own: one column right = +17.5 µm, one row down = +17.5 µm,
    # rotation taken out (the planted lattice sits -2 deg off the image axes, so a µm frame
    # that merely rescaled pixels would fail this)
    at = {(c["col"][i], c["row"][i]): i for i in range(len(c["col"]))}
    mid_c, mid_r = payload["cols"] // 2, payload["rows"] // 2
    i0, i1, i2 = at[(mid_c, mid_r)], at[(mid_c + 1, mid_r)], at[(mid_c, mid_r + 1)]
    assert abs((c["x_um"][i1] - c["x_um"][i0]) - 17.5) < 1.5
    assert abs((c["y_um"][i1] - c["y_um"][i0])) < 1.5
    assert abs((c["y_um"][i2] - c["y_um"][i0]) - 17.5) < 1.5

    # origin: electrode 1-1's lattice position, so column 1 sits near 0 µm — a fraction of a
    # pitch, not a whole one (it is the least-squares origin, not cell 1-1's own noisy centre)
    first = min(i for i in range(len(c["col"])) if c["col"][i] == 1)
    assert abs(c["x_um"][first]) < 0.5 * 17.5


def test_declaring_the_whole_chip_refuses_a_field_that_is_not_one(client, grid_data):
    """⭐ R45.8, `full`: this fixture plants a 34 × 46 field — nothing like a 220 × 120
    MaxOne/MaxTwo. Claiming the whole chip must REFUSE, naming both shapes and pointing at
    the mode that fits, never quietly manufacture ~25,000 electrodes that were never imaged."""
    root, _ = grid_data
    session = open_session(client, root)
    sid = session["session_id"]
    a = new_project(client, sid, name="gridfull", trials=[11, 12]).json()
    aid = a["analysis_id"]
    doc = _anchored_doc(client, sid, aid)
    client.put(f"/api/analyses/{aid}/document", json={"doc": doc})

    r = client.post("/api/mosaic/electrodes/map",
                    json={"session_id": sid, "doc": doc, "array_coverage": "full"})
    assert r.status_code == 202, r.text
    msg = _run_to_failure(client, r.json()["job_id"])
    assert "220" in msg and "120" in msg, msg                # the device shape, named
    assert "partially imaged" in msg, msg                    # and the way out, named

    # a refusal writes nothing: the project has no half-built map to mistake for a real one
    assert client.get(f"/api/mosaic/electrodes/{aid}").status_code == 404


def test_editing_the_mosaic_makes_the_map_stale(client, grid_data):
    root, _ = grid_data
    session = open_session(client, root)
    sid = session["session_id"]
    a = new_project(client, sid, name="gridr", trials=[11, 12]).json()
    aid = a["analysis_id"]
    doc = _anchored_doc(client, sid, aid)
    client.put(f"/api/analyses/{aid}/document", json={"doc": doc})

    r = client.post("/api/mosaic/electrodes/map", json={"session_id": sid, "doc": doc})
    result = run_job(client, r.json()["job_id"])["result"]

    # the client merges the block and saves — the app's own flow
    doc["electrodes"] = result["electrodes"]
    client.put(f"/api/analyses/{aid}/document", json={"doc": doc})
    assert client.get(f"/api/mosaic/electrodes/{aid}").json()["stale"] is False

    doc["tiles"]["12"] = {**doc["tiles"]["12"], "y": float(doc["tiles"]["12"]["y"]) + 6.0}
    client.put(f"/api/analyses/{aid}/document", json={"doc": doc})
    assert client.get(f"/api/mosaic/electrodes/{aid}").json()["stale"] is True


def test_an_unbuilt_project_is_refused(client, grid_data):
    root, _ = grid_data
    session = open_session(client, root)
    sid = session["session_id"]
    a = new_project(client, sid, name="grids", trials=[11, 12]).json()
    doc = client.get(f"/api/analyses/{a['analysis_id']}/document").json()["doc"]

    r = client.post("/api/mosaic/electrodes/map", json={"session_id": sid, "doc": doc})
    assert r.status_code == 409
    assert err(r)["code"] == "refused"


def test_no_map_yet_is_a_404(client, grid_data):
    root, _ = grid_data
    session = open_session(client, root)
    a = new_project(client, session["session_id"], name="gridt", trials=[11, 12]).json()
    g = client.get(f"/api/mosaic/electrodes/{a['analysis_id']}")
    assert g.status_code == 404
    assert err(g)["code"] == "not_found"


def test_a_gridless_mosaic_refuses_instead_of_hallucinating(client, synth):
    """⭐ The committed fixture has NO electrode lattice — the map job must fail cleanly and
    say why, never mint an indexing out of texture."""
    session = open_session(client, synth.path, trials=synth.trials)
    sid = session["session_id"]
    a = new_project(client, sid, name="nogrid", trials=synth.trials).json()
    doc = client.get(f"/api/analyses/{a['analysis_id']}/document").json()["doc"]
    for i, trial in enumerate(synth.trials[:3]):
        t = dict(doc["tiles"][str(trial)])
        t.update(state="anchored", status="anchor", x=0.0, y=float(i * 128), human=True)
        doc["tiles"][str(trial)] = t

    r = client.post("/api/mosaic/electrodes/map", json={"session_id": sid, "doc": doc})
    assert r.status_code == 202, r.text
    msg = _run_to_failure(client, r.json()["job_id"])
    assert "lattice" in msg or "grid" in msg or "periodic" in msg, msg


# =================================================================================================
# Videomosaic
# =================================================================================================
@pytest.fixture()
def grid_survey(tmp_path_factory, videosynth):
    """A survey video whose world carries a planted lattice (pitch 16, faint enough that the
    tracker's blobs still dominate registration — the grid is exactly the comb-false-peak
    adversary the pipeline guards against, which makes this fixture double coverage)."""
    import cv2

    d = tmp_path_factory.mktemp("gridvideo")
    p = d / "gridsurvey.avi"
    world = videosynth.survey_world(seed=7)
    h, w = world.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    pitch = 16.0
    # raised-cosine pads (even powers of a plain cosine HALVE the period — measured the
    # hard way: the fitter dutifully reported pitch 8 on a "16 px" comb)
    comb = ((0.5 + 0.5 * np.cos(2 * np.pi * xx / pitch)) *
            (0.5 + 0.5 * np.cos(2 * np.pi * yy / pitch))) ** 4
    world = np.clip(world + 30.0 * comb.astype(np.float32), 0, 255)

    pts = videosynth.serpentine_path(world.shape, (320, 480), rows=2, step=16, dwell=12)
    vw = cv2.VideoWriter(p.as_posix(), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (480, 320), True)
    assert vw.isOpened()
    try:
        for x, y in pts:
            g = np.clip(world[y:y + 320, x:x + 480], 0, 255).astype(np.uint8)
            vw.write(cv2.merge([(g * 0.06).astype(np.uint8), g, (g * 0.03).astype(np.uint8)]))
    finally:
        vw.release()
    return {"path": str(p), "pitch": pitch}


CFG = {"keyframe_spacing_frac": 200.0 / 480.0}


def test_video_map_fits_the_planted_lattice_and_a_rebuild_stales_it(client, grid_survey):
    a = client.post("/api/videomosaic/projects",
                    json={"name": "vmgrid", "video_path": grid_survey["path"]}).json()
    aid = a["analysis_id"]
    build = client.post("/api/videomosaic/build", json={"analysis_id": aid, "config": CFG})
    assert build.status_code == 202, build.text
    run_job(client, build.json()["job_id"])

    r = client.post("/api/videomosaic/electrodes/map",
                    json={"analysis_id": aid, "array_coverage": "partial"})
    assert r.status_code == 202, r.text
    res = run_job(client, r.json()["job_id"])["result"]
    assert res["kind"] == "electrode_map"
    assert abs(res["electrodes"]["pitch_px"] - grid_survey["pitch"]) < 1.0
    # the job saved the document server-side, like the build does
    doc = client.get(f"/api/analyses/{aid}/document").json()["doc"]
    assert doc["electrodes"]["cols"] > 10 and doc["electrodes"]["rows"] > 10
    # ⭐ R45.8: the SERVER-owned document records what he declared and the scale it bought,
    # in exactly the same three keys the client-owned snapshot document carries
    assert doc["electrodes"]["array_coverage"] == "partial"
    assert doc["electrodes"]["device"] and "Max" in doc["electrodes"]["device"]
    assert abs(doc["electrodes"]["um_per_px"] - 17.5 / doc["electrodes"]["pitch_px"]) < 1e-3

    g = client.get(f"/api/videomosaic/{aid}/electrodes")
    assert g.status_code == 200, g.text
    payload = g.json()
    assert payload["stale"] is False
    assert payload["canvas_offset"] == [0.0, 0.0]
    assert payload["array_coverage"] == "partial"
    assert payload["device"]["electrodes"] == 26400
    assert len(payload["cells"]["x_um"]) == len(payload["cells"]["col"])
    # internal coherence: one cell to the right = one pitch to the right — judged on an
    # INTERIOR detected pair (corner cells at the coverage edge wear real local squeeze)
    c = payload["cells"]
    at = {(c["col"][i], c["row"][i]): i for i in range(len(c["col"]))}
    mid_c, mid_r = payload["cols"] // 2, payload["rows"] // 2
    i0, i1 = at[(mid_c, mid_r)], at[(mid_c + 1, mid_r)]
    assert abs((c["x"][i1] - c["x"][i0]) - payload["pitch_px"]) < 2.0

    rebuild = client.post("/api/videomosaic/build", json={"analysis_id": aid, "config": CFG})
    run_job(client, rebuild.json()["job_id"])
    assert client.get(f"/api/videomosaic/{aid}/electrodes").json()["stale"] is True


def test_video_map_refuses_without_a_build(client, grid_survey):
    a = client.post("/api/videomosaic/projects",
                    json={"name": "vmearly", "video_path": grid_survey["path"]}).json()
    r = client.post("/api/videomosaic/electrodes/map", json={"analysis_id": a["analysis_id"]})
    assert r.status_code == 409
    assert err(r)["code"] == "refused"
