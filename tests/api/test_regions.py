"""Region recordings, end to end (2026-08-11): *where on the mosaic was this field filmed?*

The whole pipeline in one fixture — build the mosaic, number the electrodes, then place a
fixed-field recording on it — because that is the order the app enforces and there is no
useful state in between. What makes this suite a test rather than a demonstration is that the
recording is **cut from the same synthetic world the survey swept**, at a rectangle this file
chose: `CROP`, magnified `MAG` times. So the answer is known before the job runs.

⭐ **THE ANSWER KEY IS IN CANVAS COORDINATES, AND IT HAS TO BE DERIVED.** The mosaic's canvas
is not the world: the solver puts the union of the placed keyframes' corner at (0, 0), so the
two frames differ by an offset nobody declares. `_world_to_canvas` reads that offset off the
built document — each placed keyframe's canvas x/y against the world x/y the fixture cut it
from — and the median of those differences is the transform. Judging a located rectangle
against `CROP` + that offset is judging it against where the pixels actually came from.

Two more truths are checked alongside the position, because a coordinate on its own can be
right by luck:

  * **the electrodes underneath** — a rectangle over an axis-aligned lattice must name a
    CONTIGUOUS block of columns and rows, and a complete one. Scattered or ragged ids mean the
    rectangle is not where it says it is, whatever its NCC.
  * **repeatability** — the same recording located twice gives the same answer to the pixel.

⛔ No dataset knowledge: the world, the lattice pitch, the magnification and the crop are all
this file's own inventions, declared at the top and never assumed by the app.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from .conftest import err, run_job

# =================================================================================================
# The synthetic experiment
# =================================================================================================

PITCH = 16.0
"""The planted electrode pitch, in world px. It is the RULER: the recording shows the same comb
at `PITCH * MAG`, and the ratio of the two is the zoom the app must measure rather than search."""

WORLD_HW = (900, 1200)
FRAME_HW = (240, 320)
SURVEY_ROWS = 3
"""The survey camera's frame and its sweep. Small on purpose — the fast suite must stay fast:
this world swept at this size builds a ~1184 x 505 mosaic in about a second, which still leaves
the matcher a search plane many times the size of the thing it is looking for."""

CFG = {"keyframe_spacing_frac": 0.42}
"""~134 px of travel between keyframes on a 320 px frame — 58 % sequential overlap, the same
overlap the other video fixtures use, expressed for this frame width."""

CROP = (380, 60, 300, 260)
"""⭐ **THE PLANTED ANSWER**: world (x, y, w, h) of the rectangle the fixed-field recording
filmed. Chosen to sit well inside what the serpentine actually covers, so the match is judged
on a real placement and not on a corner hanging off the coverage."""

MAG = 2.0
"""The recording's magnification over the survey. His words: the two *"pretty much always
differ"* — so a fixture where they agreed would test nothing.

⚠️ Crop × `MAG` is also what sets the FFT window the zoom is read in, and the lattice peak sits
`window / (PITCH * MAG)` bins from DC. Measured while writing this file: a 500 x 380 recording
puts that peak 6 bins out, inside the blob continuum, and the measurement comes back 17.9 px at
-25° — confidently wrong. At 600 x 520 the peak is 16 bins out and the answer is 32.000 px at
0.00°. The fixture is sized for the physics, not by taste.
"""


def _combed_world(videosynth, seed: int = 7) -> np.ndarray:
    """Multi-scale blobs (what registration locks onto) + a raised-cosine electrode comb.

    ⚠️ Raised to the 4th power, exactly as `test_electrodes.py` does and for the same measured
    reason: even powers of a plain cosine HALVE the period, and the lattice fitter dutifully
    reports pitch 8 on a "16 px" comb. Keep the two fixtures in step.
    """
    world = videosynth.survey_world(*WORLD_HW, seed=seed)
    h, w = world.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    comb = ((0.5 + 0.5 * np.cos(2 * np.pi * xx / PITCH)) *
            (0.5 + 0.5 * np.cos(2 * np.pi * yy / PITCH))) ** 4
    return np.clip(world + 30.0 * comb.astype(np.float32), 0, 255)


def _green(g: np.ndarray) -> np.ndarray:
    """One channel carrying the picture, the other two nearly dark — the single-channel source
    the pipeline's tint detection expects, same as every video fixture here."""
    import cv2

    u8 = np.clip(g, 0, 255).astype(np.uint8)
    return cv2.merge([(u8 * 0.06).astype(np.uint8), u8, (u8 * 0.03).astype(np.uint8)])


def _write_survey(path: Path, world: np.ndarray, videosynth) -> dict[int, tuple[float, float]]:
    """The survey sweep. -> `{frame_index: (world_x, world_y)}`, which is what makes the
    canvas-to-world transform derivable instead of guessed."""
    import cv2

    fh, fw = FRAME_HW
    pts = videosynth.serpentine_path(world.shape, FRAME_HW, rows=SURVEY_ROWS, step=16, dwell=10)
    vw = cv2.VideoWriter(path.as_posix(), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (fw, fh), True)
    assert vw.isOpened(), "no MJPG encoder — the video fixtures cannot be written"
    truth: dict[int, tuple[float, float]] = {}
    try:
        for i, (x, y) in enumerate(pts):
            vw.write(_green(world[y:y + fh, x:x + fw]))
            truth[i] = (float(x), float(y))
    finally:
        vw.release()
    return truth


def _write_recording(path: Path, world: np.ndarray, *, n_frames: int = 8, seed: int = 3) -> Path:
    """The fixed field: `CROP` blown up `MAG` times, held still, filmed for a few frames.

    ⭐ **Independent noise per frame, and nothing else moving.** That is what makes the three
    projections `core.locate` builds genuinely different pictures — median smooths the noise
    away, max keeps its brightest excursion, std is nothing BUT the noise — so "which still
    won" is a real choice the matcher makes rather than three copies of one image.
    """
    import cv2

    x0, y0, w, h = CROP
    crop = np.asarray(world[y0:y0 + h, x0:x0 + w], np.float32)
    big = cv2.resize(crop, (int(round(w * MAG)), int(round(h * MAG))),
                     interpolation=cv2.INTER_CUBIC)
    rng = np.random.default_rng(seed)
    vw = cv2.VideoWriter(path.as_posix(), cv2.VideoWriter_fourcc(*"MJPG"), 30.0,
                         (big.shape[1], big.shape[0]), True)
    assert vw.isOpened()
    try:
        for _ in range(n_frames):
            vw.write(_green(big + rng.normal(0.0, 4.0, big.shape).astype(np.float32)))
    finally:
        vw.release()
    return path


@pytest.fixture(scope="session")
def scene(tmp_path_factory, videosynth) -> dict:
    """One world, two videos cut from it: the survey that becomes the mosaic, and the
    fixed-field recording that must be found on it. Session-scoped — writing them is ~1 s and
    every test reads them read-only."""
    d = tmp_path_factory.mktemp("regionscene")
    world = _combed_world(videosynth)
    truth = _write_survey(d / "survey.avi", world, videosynth)
    _write_recording(d / "field one.avi", world)
    return {"survey": str(d / "survey.avi"), "recording": str(d / "field one.avi"),
            "truth": truth}


# =================================================================================================
# Driving the pipeline
# =================================================================================================


BASE = "regions"
"""The project's name, and therefore the stem of everything it writes into `outputs/` (R44):
a file he copies out to his desktop has to say which project it came from."""


def _create(client, scene, name: str = BASE) -> dict:
    r = client.post("/api/videomosaic/projects",
                    json={"name": name, "video_path": scene["survey"]})
    assert r.status_code == 201, r.text
    return r.json()


def _build(client, aid: str) -> dict:
    r = client.post("/api/videomosaic/build", json={"analysis_id": aid, "config": CFG})
    assert r.status_code == 202, r.text
    return run_job(client, r.json()["job_id"])["result"]


def _map_electrodes(client, aid: str) -> dict:
    """⭐ `partial` is the only honest declaration here (R45.8): a synthetic world with a comb
    planted on it is not a 220 x 120 MaxOne/MaxTwo, and `full` refuses anything that is not one
    rather than inventing the ~25,000 electrodes nobody imaged."""
    r = client.post("/api/videomosaic/electrodes/map",
                    json={"analysis_id": aid, "array_coverage": "partial"})
    assert r.status_code == 202, r.text
    return run_job(client, r.json()["job_id"])["result"]


def _locate(client, aid: str, path: str, name: str = "") -> dict:
    r = client.post("/api/videomosaic/regions/locate",
                    json={"analysis_id": aid, "path": path, "name": name})
    assert r.status_code == 202, r.text
    return run_job(client, r.json()["job_id"])["result"]


def _world_to_canvas(doc: dict, truth: dict[int, tuple[float, float]]) -> tuple[float, float]:
    """⭐ **THE TRANSFORM, READ OFF THE BUILD.** Every placed keyframe knows its canvas corner;
    the fixture knows the world corner it was cut from. The difference is the canvas origin, and
    the MEDIAN of those differences is it — a median rather than one keyframe's, because a single
    link's residual should not become the answer key."""
    dx, dy = [], []
    for idx, kf in (doc.get("keyframes") or {}).items():
        if not kf.get("placed") or int(idx) not in truth:
            continue
        wx, wy = truth[int(idx)]
        dx.append(float(kf["x"]) - wx)
        dy.append(float(kf["y"]) - wy)
    assert dx, "the build placed no keyframe this fixture knows the world position of"
    return float(np.median(dx)), float(np.median(dy))


@pytest.fixture(scope="session")
def prebuilt(tmp_path_factory, scene) -> dict:
    """Sweep, build and number the electrodes ONCE, in a store of this fixture's own. -> the
    finished project FOLDER, for each test to take a copy of.

    ⭐ **Why a copy rather than a shared project.** Every test below needs those two steps done
    and then needs a project it is free to ruin — it deletes regions, renames them, rebuilds the
    mosaic under them. Running the pipeline once per test costs the fast suite ~12 s for a dozen
    byte-identical mosaics (measured: 35 s for this file, against 23 s this way); copying the
    finished project into each test's isolated store costs milliseconds and leaves every test
    exactly as independent as it was.

    ⚠️ **It is session-scoped so that its app is DEAD before any test's is alive.** pytest builds
    higher-scoped fixtures first, so this one's `TestClient` opens, works and closes before
    `client` is asked for — the two never share the process-level `JOBS`/`SETTINGS` singletons at
    the same moment, and `CAMEA_STATE_DIR` is handed back before `state_dir` sets it for the
    test. (`tests/api/conftest.py` documents what a leaked job costs; this is that warning obeyed
    rather than tested.)
    """
    from camea.api.app import create_app
    from fastapi.testclient import TestClient

    d = tmp_path_factory.mktemp("prebuilt")
    mp = pytest.MonkeyPatch()
    mp.setenv("CAMEA_STATE_DIR", str(d))
    try:
        with TestClient(create_app()) as c:
            a = _create(c, scene)
            _build(c, a["analysis_id"])
            _map_electrodes(c, a["analysis_id"])
    finally:
        mp.undo()
    return {"aid": a["analysis_id"], "folder": Path(a["folder"])}


@pytest.fixture()
def built(prebuilt, client, state_dir, scene) -> dict:
    """This test's own copy of that project, in this test's own store — plus the world→canvas
    transform and where `CROP` therefore ought to land on it."""
    import shutil

    folder = state_dir / "projects" / prebuilt["folder"].name
    shutil.copytree(prebuilt["folder"], folder)
    aid = prebuilt["aid"]
    doc = client.get(f"/api/analyses/{aid}/document").json()["doc"]
    assert doc["build"]["built_at"] and doc["electrodes"]["built_at"], \
        "the copied project must arrive built and mapped, or the copy is not a project"
    ox, oy = _world_to_canvas(doc, scene["truth"])
    return {"aid": aid, "folder": folder, "offset": (ox, oy),
            "expect": (CROP[0] + ox, CROP[1] + oy), "doc": doc}


def _contiguous(vals: list[int]) -> bool:
    return bool(vals) and vals == list(range(vals[0], vals[-1] + 1))


def _assert_solid_block(region: dict) -> tuple[list[int], list[int]]:
    """⭐ **THE SHAPE OF THE ANSWER IS ITSELF EVIDENCE.** A rectangle laid over a regular lattice
    covers a SOLID block of it: contiguous columns, contiguous rows, and no hole in the middle.
    Ids that skip about are what a rectangle in the wrong place looks like, whatever its NCC.

    ⚠️ The *border* is honestly ragged and must not be asserted away: the fitted lattice sits a
    hundredth of a degree off the canvas axes, so the outermost column and row cross the edge
    mid-way and lose a few cells. The interior is where completeness is a real claim.
    """
    e = region["electrodes"]
    pairs = list(zip(e["cols"], e["rows"]))
    assert len(pairs) == e["count"] == len(set(pairs)), "an electrode named twice is a bug"
    assert e["ids"] == [f"{c}-{r}" for c, r in pairs]
    assert e["detected"] + e["inferred"] == e["count"]

    cols, rows = sorted({c for c, _ in pairs}), sorted({r for _, r in pairs})
    assert _contiguous(cols) and _contiguous(rows), (cols, rows)
    inside = {(c, r) for c in cols[1:-1] for r in rows[1:-1]}
    assert inside <= set(pairs), sorted(inside - set(pairs))[:8]
    assert (len(cols) - 1) * (len(rows) - 1) <= e["count"] <= len(cols) * len(rows)
    return cols, rows


# =================================================================================================
# The happy path
# =================================================================================================
def test_a_planted_field_is_found_where_it_was_planted(client, scene, built):
    """⭐ **THE WHOLE FEATURE, AGAINST AN ANSWER KEY.** `CROP` of the world, magnified `MAG`
    times and filmed, must come back at `CROP` in the mosaic's own coordinates — and must name a
    solid rectangle of electrodes, because that pairing (MEA channel ↔ calcium trace) is the only
    reason anyone wanted the coordinate.

    Three independent statements, and it takes all three to believe the answer: the corner is
    where the pixels came from; the ids underneath are a complete contiguous block rather than a
    scatter; and locating the same recording again returns the identical number, so the match is
    a measurement and not a coin toss.
    """
    aid = built["aid"]
    res = _locate(client, aid, scene["recording"], name="field one")
    assert res["kind"] == "locate_region" and res["analysis_id"] == aid
    region = res["region"]

    ex, ey = built["expect"]
    assert abs(region["x"] - ex) < 6.0, (region["x"], ex)
    assert abs(region["y"] - ey) < 6.0, (region["y"], ey)
    canvas = built["doc"]["build"]["canvas"]
    assert 0 <= region["x"] and region["x"] + region["w"] <= canvas["w"]
    assert 0 <= region["y"] and region["y"] + region["h"] <= canvas["h"]
    # the rectangle is the crop at the mosaic's scale — the zoom taken back out
    assert abs(region["w"] - CROP[2]) < 8.0 and abs(region["h"] - CROP[3]) < 8.0

    cols, rows = _assert_solid_block(region)
    # ~300 x 260 canvas px over a ~16 px pitch: a real block, not two pads and a rounding error
    assert len(cols) >= 14 and len(rows) >= 12, (len(cols), len(rows))
    assert region["electrodes"]["map"] == f"{BASE}-electrodes.json"
    assert region["electrodes"]["array_coverage"] == "partial"

    # it is unconfirmed and it says so — nothing here promotes itself (I3, applied to a rectangle)
    assert region["status"] == "unconfirmed" and region["placed_by"] == "machine"
    assert region["confident"] is True and region["ncc"] > 0.3

    # 🔴 THE DOCUMENT IS SERVER-OWNED: the job saved it, so a plain refetch already has the region
    doc = client.get(f"/api/analyses/{aid}/document").json()["doc"]
    assert [r["id"] for r in doc["regions"]] == [region["id"]]
    assert doc["regions"][0]["x"] == region["x"]

    # ⭐ **AND IT IS A MEASUREMENT, NOT A DRAW.** The same recording against the same mosaic
    # comes back at the same corner, the same size, over the same electrodes — to the pixel.
    again = _locate(client, aid, scene["recording"])["region"]
    assert (again["x"], again["y"], again["w"], again["h"]) == \
        (region["x"], region["y"], region["w"], region["h"])
    assert again["electrodes"]["ids"] == region["electrodes"]["ids"]


def test_the_zoom_is_measured_from_the_lattice_and_not_searched(client, scene, built):
    """⭐ **THE CHIP IS THE RULER.** The same electrode comb is in both pictures, so the ratio of
    the two pitches IS the magnification — one number, measured, rather than a ladder of thirteen
    scales each of which is another chance for a confident-but-wrong peak.

    `measured=False` would mean the lattice could not be read and a search happened instead. That
    is a different kind of answer and the record has to say which one it is.
    """
    region = _locate(client, built["aid"], scene["recording"])["region"]
    zoom = region["zoom"]
    assert zoom["measured"] is True, zoom["note"]
    assert abs(zoom["scale"] - 1.0 / MAG) < 0.02, zoom
    assert abs(zoom["pitch_mosaic_px"] - PITCH) < 1.0
    assert abs(zoom["pitch_recording_px"] - PITCH * MAG) < 2.5
    # same rig, same orientation: the angle is not solved, but it IS reported, so a reseated
    # chip shows up as a number rather than as a silently wrong placement
    assert abs(zoom["angle_delta_deg"]) < 5.0
    assert "measured" in zoom["note"]


def test_the_record_says_which_still_won_and_what_else_was_tried(client, scene, built):
    """Whether the cells are bright at rest or only when firing is a property of the
    preparation, so three projections are built from one decode and each is matched. The winner
    is named, and every loser is on the record with its score — a poor result has to be
    diagnosable, not merely disbelievable."""
    region = _locate(client, built["aid"], scene["recording"])["region"]
    assert region["still_kind"] in ("median", "max", "std")
    tried = region["tried"]
    assert {row["still_kind"] for row in tried} == {"median", "max", "std"}
    # the zoom was measured, so each kind was tried once and at one scale — not thirteen
    assert len(tried) == 3
    assert all(abs(row["scale"] - region["zoom"]["scale"]) < 0.15 for row in tried), tried
    assert any(row["still_kind"] == region["still_kind"] for row in tried)
    assert all(row["ncc"] is not None and row["refused"] is None for row in tried), tried


def test_the_margin_and_the_alternatives_come_back_with_the_answer(client, scene, built):
    """🔴 **THE MARGIN IS THE EVIDENCE, NOT THE NCC.** A periodic comb over a whole mosaic
    manufactures confident-looking peaks (measured elsewhere at up to 0.760 and 757 px wrong), so
    a winner alone says nothing. What says something is how far it stands above its own
    runner-up — and the runners-up ride along so a human can take one instead."""
    region = _locate(client, built["aid"], scene["recording"])["region"]
    cands = region["candidates"]
    assert len(cands) >= 2, cands
    assert [c["rank"] for c in cands] == list(range(len(cands)))
    assert cands[0]["ncc"] >= cands[1]["ncc"]
    assert region["ncc"] == cands[0]["ncc"]
    # the reported margin is exactly best - runner-up (both rounded to 4 dp on the wire)
    assert abs(region["margin"] - (cands[0]["ncc"] - cands[1]["ncc"])) < 2e-4
    # and the two flags are that margin against `locate.MARGIN_THIN` / `locate.NCC_MIN`,
    # spelled out here so a quietly re-tuned constant shows up as a red test
    assert region["margin_thin"] is (region["margin"] < 0.10)
    assert region["confident"] is (region["ncc"] >= 0.12 and not region["margin_thin"])
    # rank 0 is where the region sits; it was settled sub-pixel, not left on the integer grid
    assert (cands[0]["x"], cands[0]["y"]) == (region["x"], region["y"])
    assert cands[0]["subpixel"] is True


# =================================================================================================
# The pipeline is step by step
# =================================================================================================
def test_an_unbuilt_project_is_refused(client, scene):
    """There is nothing to locate against until the survey has become a mosaic. A refusal, in a
    sentence that says what to do — never a job that fails five seconds later."""
    a = _create(client, scene, name="nobuild")
    r = client.post("/api/videomosaic/regions/locate",
                    json={"analysis_id": a["analysis_id"], "path": scene["recording"]})
    assert r.status_code == 409
    body = err(r)
    assert body["code"] == "refused"
    assert "build" in body["message"].lower(), body["message"]


def test_a_project_with_no_electrode_map_is_refused(client, scene):
    """⭐ **HIS RULING: THE PIPELINE IS STEP BY STEP.** A located rectangle whose electrodes
    cannot be named is half an answer — it is a coordinate nobody can pair a voltage trace with —
    so the map comes first and the refusal says so."""
    a = _create(client, scene, name="nomap")
    aid = a["analysis_id"]
    _build(client, aid)

    r = client.post("/api/videomosaic/regions/locate",
                    json={"analysis_id": aid, "path": scene["recording"]})
    assert r.status_code == 409
    body = err(r)
    assert body["code"] == "refused"
    assert "electrode" in body["message"].lower(), body["message"]
    # a refusal writes nothing: no half-region, and no video dragged into the project either
    assert client.get(f"/api/videomosaic/{aid}/regions").json()["regions"] == []


# =================================================================================================
# What the project keeps
# =================================================================================================
def test_the_recording_is_copied_into_the_project_and_never_twice(client, scene, built):
    """⭐ **THE PROJECT HOLDS ITS FILES** (his ruling, 2026-08-11). A located region must stay
    locatable after the original recording is moved, renamed or deleted, so the video is copied
    into `<project>/videos/` and everything downstream reads it from there.

    And re-locating must ADOPT that copy rather than make a second one: same name, same size, so
    a user who presses Locate twice does not pay for the recording twice on disk.
    """
    aid, folder = built["aid"], built["folder"]
    _locate(client, aid, scene["recording"])

    videos = sorted(p.name for p in (folder / "videos").iterdir())
    assert videos == ["field one.avi"], videos
    assert (folder / "videos" / "field one.avi").stat().st_size == \
        Path(scene["recording"]).stat().st_size

    _locate(client, aid, scene["recording"])
    assert sorted(p.name for p in (folder / "videos").iterdir()) == videos, \
        "locating the same recording again must not multiply it on disk"


def test_the_region_files_land_in_outputs_and_the_panel_lists_them(client, scene, built):
    """⭐ **R44.** Everything a feature builds lands in `<project>/outputs/`, and the Outputs
    panel is the only way to browse it. One JSON and one CSV for ALL the regions, rewritten
    whole: the list is the answer, it is always current, and two recordings can never collide
    over a filename."""
    aid, folder = built["aid"], built["folder"]
    region = _locate(client, aid, scene["recording"], name="field one")["region"]

    payload = client.get(f"/api/videomosaic/{aid}/regions").json()
    names = payload["outputs"]
    assert names == {"regions": f"{BASE}-regions.json", "csv": f"{BASE}-regions.csv"}
    out = folder / "outputs"
    assert (out / names["regions"]).is_file() and (out / names["csv"]).is_file()
    assert (out / str(region["still"])).is_file(), "the still the UI fades into the rectangle"

    listed = {o["name"] for o in client.get(f"/api/projects/{aid}/outputs").json()["outputs"]}
    assert names["regions"] in listed and names["csv"] in listed
    assert str(region["still"]) in listed

    body = client.get(f"/api/projects/{aid}/outputs/{names['csv']}").content.decode()
    lines = body.splitlines()
    assert lines[0] == ("region_id,name,video,status,placed_by,x,y,w,h,scale,still_kind,ncc,"
                        "margin,confident,n_electrodes,electrode_ids")
    assert len(lines) == 2, lines
    row = lines[1].split(",")
    assert len(row) == 16, row
    assert row[0] == region["id"] and row[1] == "field one"
    assert row[2] == "field one.avi"
    assert row[3] == "unconfirmed" and row[4] == "machine"
    assert (float(row[5]), float(row[6])) == (region["x"], region["y"])
    # ⭐ the pairing itself rides out in the last two columns. This CSV is the artifact that
    # LEAVES the app (R44) — a coordinate without the electrode ids beside it is not the answer.
    assert row[14] == str(region["electrodes"]["count"])
    assert row[15] == " ".join(region["electrodes"]["ids"])

    # the JSON is the same list with its frame stated — a coordinate whose space is not written
    # down beside it is a number waiting to be misread once the file is off this machine
    saved = json.loads((out / names["regions"]).read_text(encoding="utf-8"))
    assert "mosaic canvas px" in saved["space"] and "TOP-LEFT" in saved["space"]
    assert saved["electrode_map"] == f"{BASE}-electrodes.json"
    assert saved["built_from"] == region["source_stamp"]
    assert [r["id"] for r in saved["regions"]] == [region["id"]]


# =================================================================================================
# The human has the last word
# =================================================================================================
def test_snapping_moves_it_back_and_renames_the_electrodes_underneath(client, scene, built):
    """*"I dragged it here — now snap it."* A bounded local re-search at the SETTLED scale,
    seeded where the user dropped the rectangle.

    ⭐ The proof is that a deliberate nudge is undone: dropped 24 px away, the snap has to walk
    it back to where the global match had it, re-name the electrodes from the new corner, and
    stamp the placement as the human's (`hand+snap`) — because from now on it is his, not the
    machine's.
    """
    aid = built["aid"]
    region = _locate(client, aid, scene["recording"])["region"]
    x0, y0 = region["x"], region["y"]

    r = client.post("/api/videomosaic/regions/snap",
                    json={"analysis_id": aid, "region_id": region["id"],
                          "x": x0 + 24.0, "y": y0 - 18.0})
    assert r.status_code == 202, r.text
    snapped = run_job(client, r.json()["job_id"])["result"]["region"]

    assert snapped["id"] == region["id"]
    assert abs(snapped["x"] - x0) < 4.0 and abs(snapped["y"] - y0) < 4.0, (snapped, x0, y0)
    assert snapped["placed_by"] == "hand+snap"
    assert snapped["status"] == "unconfirmed", "a snap is a correction, not a signature"
    assert snapped["moved_px"] > 10.0, "it says how far it walked from where he dropped it"
    assert (snapped["w"], snapped["h"]) == (region["w"], region["h"]), \
        "a snap corrects WHERE the field is, never how big it is"
    # ⚠️ the GLOBAL margin is not restated by a local search — a neighbouring shoulder inside the
    # window is not a rival place on the mosaic
    assert snapped["snap_margin"] is not None

    assert snapped["electrodes"]["ids"] == region["electrodes"]["ids"], \
        "back at the same corner, the same electrodes are underneath"
    saved = client.get(f"/api/analyses/{aid}/document").json()["doc"]["regions"][0]
    assert saved["placed_by"] == "hand+snap" and saved["x"] == snapped["x"]


def test_the_snap_search_width_is_recorded_and_clamped(client, scene, built):
    """The UI may ask for a wider local search (`SnapRegionRequest.radius`); the record answers
    with `snap_radius_px` — what was ACTUALLY searched, i.e. the ask through the same clamp
    `locate.snap` applies — so a banner can quote it honestly. And with no ask, the recorded
    number is the drag-derived default, to the pixel."""
    import math

    from camea.core import locate as core_locate

    aid = built["aid"]
    region = _locate(client, aid, scene["recording"])["region"]

    def _snap(**extra) -> dict:
        cur = client.get(f"/api/videomosaic/{aid}/regions").json()["regions"][0]
        r = client.post("/api/videomosaic/regions/snap",
                        json={"analysis_id": aid, "region_id": region["id"],
                              "x": cur["x"] + 24.0, "y": cur["y"] - 18.0, **extra})
        assert r.status_code == 202, r.text
        return run_job(client, r.json()["job_id"])["result"]["region"]

    # an explicit ask is used as given (inside the clamp) and recorded
    assert _snap(radius=120)["snap_radius_px"] == 120
    # a tiny ask is floored exactly as `locate.snap` floors it — the record never understates
    assert _snap(radius=4)["snap_radius_px"] == 8
    # no ask: the window is derived from the drag (24, -18 → 30 px), and the record says so
    expected = core_locate.snap_radius_for(math.hypot(24.0, 18.0))
    assert _snap()["snap_radius_px"] == expected


def test_confirm_is_the_humans_signature_and_a_name_cannot_be_blank(client, scene, built):
    """⭐ Nothing here ever promotes itself. A located region is `unconfirmed` until he says
    otherwise, and when he does it sticks — through the saved document and back out of a GET.
    The name is his too, which is exactly why an empty one is refused rather than accepted and
    quietly replaced with something the app made up."""
    aid = built["aid"]
    region = _locate(client, aid, scene["recording"])["region"]
    assert region["name"] == "field one", "the file's own name is the default label"

    r = client.patch("/api/videomosaic/regions",
                     json={"analysis_id": aid, "region_id": region["id"], "status": "confirmed"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "confirmed"

    r2 = client.patch("/api/videomosaic/regions",
                      json={"analysis_id": aid, "region_id": region["id"], "name": "  CA1 west "})
    assert r2.status_code == 200, r2.text
    assert r2.json()["name"] == "CA1 west"
    assert r2.json()["status"] == "confirmed", "renaming does not un-sign it"

    got = client.get(f"/api/videomosaic/{aid}/regions").json()["regions"][0]
    assert (got["status"], got["name"]) == ("confirmed", "CA1 west")
    saved = client.get(f"/api/analyses/{aid}/document").json()["doc"]["regions"][0]
    assert (saved["status"], saved["name"]) == ("confirmed", "CA1 west")

    blank = client.patch("/api/videomosaic/regions",
                         json={"analysis_id": aid, "region_id": region["id"], "name": "   "})
    assert blank.status_code == 400
    assert err(blank)["code"] == "bad_request"
    assert client.get(f"/api/videomosaic/{aid}/regions").json()["regions"][0]["name"] == "CA1 west"


def test_deleting_a_region_forgets_it_and_takes_its_still_with_it(client, scene, built):
    """Forget means forget: gone from the document, gone from the rewritten outputs files, and
    its picture gone off the disk. A still left behind is clutter in the Outputs panel that names
    a region nobody can see."""
    aid, folder = built["aid"], built["folder"]
    region = _locate(client, aid, scene["recording"])["region"]
    still = folder / "outputs" / str(region["still"])
    assert still.is_file()

    d = client.delete(f"/api/videomosaic/{aid}/regions/{region['id']}")
    assert d.status_code == 200, d.text
    assert d.json()["regions"] == []
    assert not still.exists(), "the still went with it"

    assert client.get(f"/api/videomosaic/{aid}/regions").json()["regions"] == []
    assert client.get(f"/api/analyses/{aid}/document").json()["doc"]["regions"] == []
    csv_name = d.json()["outputs"]["csv"]
    body = client.get(f"/api/projects/{aid}/outputs/{csv_name}").content.decode()
    assert len(body.splitlines()) == 1, "the CSV is rewritten whole, so it forgets too"


def test_locate_again_answers_from_the_projects_own_copy(client, scene, built, tmp_path):
    """⭐ **"Locate again" resolves the video INSIDE the project** (R46.9). The original file the
    user once named can be long gone — the project adopted the recording, so re-locating reads
    `<project>/videos/<name>` and never the absolute path the document happens to remember.

    ⭐ R46.6: the re-located region is machine-proposed again — `unconfirmed`, `machine`, fresh
    evidence — even though he had confirmed the old placement. Confirm is the one confirm step.
    """
    import shutil

    aid = built["aid"]
    # Locate from a throwaway copy, then DELETE it: only the project's own copy remains.
    gone = tmp_path / "field one.avi"
    shutil.copy2(scene["recording"], gone)
    region = _locate(client, aid, str(gone), name="field one")["region"]
    gone.unlink()

    ok = client.patch("/api/videomosaic/regions",
                      json={"analysis_id": aid, "region_id": region["id"],
                            "status": "confirmed"})
    assert ok.status_code == 200

    r = client.post("/api/videomosaic/regions/relocate",
                    json={"analysis_id": aid, "region_id": region["id"]})
    assert r.status_code == 202, r.text
    again = run_job(client, r.json()["job_id"])["result"]["region"]

    assert again["id"] == region["id"]
    assert again["status"] == "unconfirmed" and again["placed_by"] == "machine"
    assert again["name"] == "field one", "the label is his and survives the re-run"
    assert (again["x"], again["y"], again["w"], again["h"]) == \
        (region["x"], region["y"], region["w"], region["h"]), \
        "same mosaic, same recording — the measurement repeats"
    # replaced IN PLACE: one region, one row, and the saved document agrees
    listed = client.get(f"/api/videomosaic/{aid}/regions").json()["regions"]
    assert [g["id"] for g in listed] == [region["id"]]
    assert listed[0]["status"] == "unconfirmed"


def test_locate_again_refuses_what_it_cannot_do(client, scene, built):
    """A region id the project never had is a 404; a project whose own copy of the recording is
    gone gets a sentence that says what to do, never a job that fails later."""
    aid, folder = built["aid"], built["folder"]
    r = client.post("/api/videomosaic/regions/relocate",
                    json={"analysis_id": aid, "region_id": "ghost"})
    assert r.status_code == 404 and err(r)["code"] == "not_found"

    region = _locate(client, aid, scene["recording"])["region"]
    (folder / "videos" / "field one.avi").unlink()
    r2 = client.post("/api/videomosaic/regions/relocate",
                     json={"analysis_id": aid, "region_id": region["id"]})
    assert r2.status_code == 409 and err(r2)["code"] == "refused"
    assert "copy" in err(r2)["message"], err(r2)["message"]


def test_a_rebuild_makes_every_location_stale(client, scene, built):
    """⭐ A location is a statement about a particular mosaic. Rebuild it and the canvas may be a
    different size, in a different place, from different keyframes — so every rectangle placed on
    the old one is STALE and the UI says so. It never silently drifts.

    ⭐ And stale is answered PER ROW (2026-08-16): the payload flag says whether any row is, each
    region's own `stale` says which — derived on serve, never stored in the document. Locating a
    stale region again refreshes its stamp, so the flag clears for that row honestly.
    """
    aid = built["aid"]
    region = _locate(client, aid, scene["recording"])["region"]
    payload = client.get(f"/api/videomosaic/{aid}/regions").json()
    assert payload["stale"] is False
    assert payload["regions"][0]["stale"] is False
    assert payload["built_from"] == region["source_stamp"]

    _build(client, aid)
    after = client.get(f"/api/videomosaic/{aid}/regions").json()
    assert after["stale"] is True
    assert after["regions"], "stale is a warning, not a deletion — his placement is still his"
    assert all(r["stale"] is True for r in after["regions"])
    assert after["built_from"] != region["source_stamp"]

    # a synchronous PATCH answers with the same derived truth…
    p = client.patch("/api/videomosaic/regions",
                     json={"analysis_id": aid, "region_id": region["id"], "name": "still mine"})
    assert p.status_code == 200 and p.json()["stale"] is True
    # …but the DOCUMENT never stores it — stale is an answer, not a fact
    saved = client.get(f"/api/analyses/{aid}/document").json()["doc"]["regions"][0]
    assert "stale" not in saved

    # locate it again against the REBUILT mosaic: the stamp refreshes and the row's flag clears
    rr = client.post("/api/videomosaic/regions/relocate",
                     json={"analysis_id": aid, "region_id": region["id"]})
    assert rr.status_code == 202, rr.text
    run_job(client, rr.json()["job_id"])
    final = client.get(f"/api/videomosaic/{aid}/regions").json()
    assert final["stale"] is False
    assert final["regions"][0]["stale"] is False
    assert final["regions"][0]["status"] == "unconfirmed"
    assert final["regions"][0]["name"] == "still mine"


def test_a_region_id_this_project_never_had_is_a_404(client, scene):
    """Every route that names a region agrees about a name it does not know. Cheap to get wrong
    one route at a time, which is why all three are asserted together."""
    aid = _create(client, scene, name="strangers")["analysis_id"]

    d = client.delete(f"/api/videomosaic/{aid}/regions/ghost")
    assert d.status_code == 404 and err(d)["code"] == "not_found"

    p = client.patch("/api/videomosaic/regions",
                     json={"analysis_id": aid, "region_id": "ghost", "status": "confirmed"})
    assert p.status_code == 404 and err(p)["code"] == "not_found"

    s = client.post("/api/videomosaic/regions/snap",
                    json={"analysis_id": aid, "region_id": "ghost", "x": 10.0, "y": 10.0})
    assert s.status_code == 404 and err(s)["code"] == "not_found"


# =================================================================================================
# The served picker (2026-08-16) — `GET /api/videomosaic/browse-videos`
# =================================================================================================


def test_browse_videos_lists_probes_and_refuses_without_dropping(client, tmp_path, videosynth):
    """⭐ The Regions step's folder door — the one that works over VSCode remote, where the native
    multi-select dialog is a 501 (R38). Every video under the folder comes back probed; a file
    that is named like a video but does not decode is LISTED with its refusal, never dropped."""
    d = tmp_path / "acq"
    (d / "sub").mkdir(parents=True)
    videosynth.write_survey_video(d / "region_a.avi", rows=2)
    (d / "sub" / "not_really.mp4").write_bytes(b"this is not a video")
    (d / "notes.txt").write_text("not listed - not a video extension", encoding="utf-8")

    r = client.get("/api/videomosaic/browse-videos", params={"path": str(d)})
    assert r.status_code == 200, r.text
    body = r.json()
    rows = {v["label"]: v for v in body["videos"]}
    assert set(rows) == {"region_a.avi", "not_really.mp4"}

    good = rows["region_a.avi"]
    assert good["readable"] is True
    assert good["n_frames"] > 0 and good["width"] > 0 and good["height"] > 0
    assert good["bytes"] > 0

    junk = rows["not_really.mp4"]
    assert junk["readable"] is False
    assert junk["problem"], "a refusal must say why"
    assert body["truncated"] is False


def test_browse_videos_refuses_a_missing_folder_by_name(client, tmp_path):
    r = client.get("/api/videomosaic/browse-videos", params={"path": str(tmp_path / "nope")})
    assert r.status_code == 400 and err(r)["code"] == "bad_request"
