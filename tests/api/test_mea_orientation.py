"""The videomosaic MEA seating routes: the footprint GET, and the orientation test over regions.

⭐ **THE FIXTURE'S GEOMETRY IS THE ANSWER KEY.** `measynth` routes every OTHER column and row of a
13 x 5 chip, and the grid planted here is 4 x 12 — deliberately smaller than the chip and not equal
to it on either axis — so the four seatings put the recorded pads in four *disjoint* sets of grid
cells. Region A's electrode ids are exactly one seating's set; region B's single id belongs to the
diagonally opposite seating. Every coverage number below follows from that by geometry alone, with
no clock, no spikes and no video involved — which is precisely the property the coverage evidence
claims for itself.

🔴 The orientation result is UNVALIDATED and must say so (issue 003): these tests assert the shape
and the honesty rules — `confirmed` never true, `best` null when `decisive` is false, the caveat
present — never that the correlation means anything.

⛔ No dataset knowledge: chip, grid, regions and videos are all invented here or in the fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from .conftest import err, run_job

pytest.importorskip("h5py")
cv2 = pytest.importorskip("cv2")

#: The planted electrode grid. ⛔ Deliberately NOT the chip's own 13 x 5 (and not any device):
#: `cols != stride` exercises the transpose branch, and a grid smaller than the chip proves that a
#: routed pad without a place in this mosaic is honestly absent rather than wrapped back inside.
GRID_COLS, GRID_ROWS = 4, 12


def _grid_of(el: int, stride: int, flip_x: bool, flip_y: bool) -> tuple[int, int] | None:
    """THE ANSWER KEY: where a chip electrode should land in the planted grid — computed here from
    fixture facts, so the app's transform is being checked rather than echoed."""
    ex, ey = el % stride, el // stride
    col = (GRID_COLS - ey) if flip_y else (ey + 1)
    row = (GRID_ROWS - ex) if flip_x else (ex + 1)
    if not (1 <= col <= GRID_COLS and 1 <= row <= GRID_ROWS):
        return None
    return col, row


def _footprint(measynth, flip_x: bool, flip_y: bool) -> set[str]:
    """The 'col-row' ids the recorded pads should occupy under one seating."""
    out: set[str] = set()
    for _ch, el in measynth.routed():
        g = _grid_of(el, measynth.STRIDE, flip_x, flip_y)
        if g is not None:
            out.add(f"{g[0]}-{g[1]}")
    return out


SEATINGS = ((False, False), (True, False), (False, True), (True, True))


def _tiny_video(path: Path, n_frames: int = 24) -> str:
    """A few frames whose brightness cycles — enough for `video_activity` to have a non-flat
    series, and small enough that the job costs milliseconds."""
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (64, 48), True)
    assert vw.isOpened(), "no MJPG encoder — the video fixtures cannot be written"
    try:
        for i in range(n_frames):
            vw.write(np.full((48, 64, 3), 30 + 40 * (i % 4), np.uint8))
    finally:
        vw.release()
    return str(path)


def _create(client, tmp_path, videosynth, name: str = "seating") -> dict:
    videosynth.write_survey_video(tmp_path / "survey.avi", rows=2)
    r = client.post("/api/videomosaic/projects",
                    json={"name": name, "video_path": str(tmp_path / "survey.avi")})
    assert r.status_code == 201, r.text
    return r.json()


def _attach(client, tmp_path, measynth, aid: str) -> dict:
    """⭐ Attaching is a JOB since R48 (it opens every h5 it finds) — 202 + a poll, and the
    attachment that used to be the response body is now `result.attachment`."""
    measynth.write_session(tmp_path / "MEA")
    r = client.post("/api/videomosaic/mea/attach",
                    json={"analysis_id": aid, "mea_dir": str(tmp_path / "MEA"),
                          "confirm": True})
    assert r.status_code == 202, r.text
    res = run_job(client, r.json()["job_id"])["result"]
    assert res["kind"] == "mea_attach" and res["confirmed"] is True
    return res["attachment"]


def _plant(folder: Path, *, grid: bool = True, regions: list[dict] | None = None) -> None:
    """Write the electrode grid and the regions straight into the saved document — the same move
    `test_mea_feature.py` uses to stage a state, and legitimate for the same reason: these routes
    read the document from disk, so the disk is the interface."""
    doc = json.loads((folder / "document.camea.json").read_text("utf-8"))
    if grid:
        doc["electrodes"] = {"cols": GRID_COLS, "rows": GRID_ROWS}
    doc["regions"] = list(regions or [])
    (folder / "document.camea.json").write_text(json.dumps(doc), encoding="utf-8")


@pytest.fixture()
def project(client, tmp_path, videosynth, measynth) -> dict:
    """A videomosaic project with an MEA attached, the 4 x 12 grid, and two located regions:
    A = exactly the no-flip seating's recorded cells (12 ids), B = one cell that only the
    double-flip seating covers."""
    a = _create(client, tmp_path, videosynth)
    aid = a["analysis_id"]
    _attach(client, tmp_path, measynth, aid)

    ids_a = sorted(_footprint(measynth, False, False))
    assert len(ids_a) == 12, "the fixture geometry moved — every count below is derived from it"
    # the fixture self-check: B's one id belongs to (True, True) and to no other seating
    assert [fl for fl in SEATINGS if "2-2" in _footprint(measynth, *fl)] == [(True, True)]

    _plant(Path(a["folder"]), regions=[
        {"id": "reg_a", "name": "field A", "electrodes": {"ids": ids_a},
         "source": {"path": _tiny_video(tmp_path / "field-a.avi")}},
        {"id": "reg_b", "name": "field B", "electrodes": {"ids": ["2-2"]},
         "source": {"path": _tiny_video(tmp_path / "field-b.avi")}},
    ])
    return {"aid": aid, "folder": Path(a["folder"]), "ids_a": ids_a}


# =================================================================================================
# The footprint — geometry only, cheap, four candidate seatings
# =================================================================================================
def test_footprint_names_each_seatings_recorded_cells(client, project, measynth):
    """⭐ THE HEADLINE: for each of the four seatings, exactly the grid cells the recorded pads
    would occupy — as the app's own "col-row" ids, matching the answer key computed from fixture
    facts. On this geometry the four sets are disjoint, so a transform error cannot hide."""
    r = client.get("/api/videomosaic/mea/footprint", params={"analysis_id": project["aid"]})
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["analysis_id"] == project["aid"]
    assert body["run_id"] == "000001"
    assert (body["cols"], body["rows"]) == (GRID_COLS, GRID_ROWS)
    assert body["stride"] == measynth.STRIDE
    assert body["n_routed"] == len(measynth.routed())
    assert body["orientation"]["confirmed"] is False

    assert [(s["flip_x"], s["flip_y"]) for s in body["seatings"]] == list(SEATINGS)
    seen: set[str] = set()
    for s in body["seatings"]:
        want = _footprint(measynth, s["flip_x"], s["flip_y"])
        assert set(s["electrodes"]) == want, (s["flip_x"], s["flip_y"])
        assert s["n_recorded"] == len(s["electrodes"]) == 12
        assert not (set(s["electrodes"]) & seen), "this geometry makes the four sets disjoint"
        seen |= set(s["electrodes"])


def test_footprint_counts_each_regions_covered_pads_per_seating(client, project):
    """The per-region counts are the orientation test's coverage evidence, without the job: A is
    fully under the no-flip seating and nothing else; B's one pad only under the double flip."""
    body = client.get("/api/videomosaic/mea/footprint",
                      params={"analysis_id": project["aid"]}).json()
    for s in body["seatings"]:
        by_id = {c["region_id"]: c for c in s["regions"]}
        assert set(by_id) == {"reg_a", "reg_b"}
        assert by_id["reg_a"]["n_region"] == 12 and by_id["reg_b"]["n_region"] == 1
        if (s["flip_x"], s["flip_y"]) == (False, False):
            assert by_id["reg_a"]["n_covered"] == 12
        else:
            assert by_id["reg_a"]["n_covered"] == 0
        assert by_id["reg_b"]["n_covered"] == (1 if (s["flip_x"], s["flip_y"]) == (True, True)
                                              else 0)
        assert by_id["reg_a"]["region_name"] == "field A"


def test_footprint_refuses_without_an_mea_and_without_a_map(client, tmp_path, videosynth,
                                                            measynth):
    """The same refusals as the orientation route, because they are the same missing facts."""
    a = _create(client, tmp_path, videosynth, name="bare")
    aid = a["analysis_id"]

    r = client.get("/api/videomosaic/mea/footprint", params={"analysis_id": aid})
    assert r.status_code == 409
    assert "no MEA recording" in err(r)["message"]

    _attach(client, tmp_path, measynth, aid)
    r = client.get("/api/videomosaic/mea/footprint", params={"analysis_id": aid})
    assert r.status_code == 409
    assert "map the electrodes" in err(r)["message"]


# =================================================================================================
# The orientation test, across ALL scorable regions
# =================================================================================================
def test_orientation_scores_every_region_and_reports_the_breakdown(client, project):
    """⭐ Both regions take part; the top-level scores are their totals and `regions` carries each
    region's own four rows. The per-region recorded counts are pure geometry, so they are asserted
    exactly; the correlations are rng-fed and only their honesty rules are asserted."""
    r = client.post("/api/videomosaic/mea/orientation", json={"analysis_id": project["aid"]})
    assert r.status_code == 202, r.text
    res = run_job(client, r.json()["job_id"])["result"]

    assert res["kind"] == "mea_orientation"
    assert res["run_id"] == "000001"
    # several regions: the single-region fields are honestly blank, not one region masquerading
    assert (res["region_id"], res["region_name"]) == ("", "")

    assert [(s["flip_x"], s["flip_y"]) for s in res["scores"]] == list(SEATINGS)
    by_seat = {(s["flip_x"], s["flip_y"]): s for s in res["scores"]}
    # totals across the two regions: A puts 12 under no-flip, B puts 1 under double-flip
    assert by_seat[(False, False)]["n_recorded"] == 12
    assert by_seat[(True, False)]["n_recorded"] == 0
    assert by_seat[(False, True)]["n_recorded"] == 0
    assert by_seat[(True, True)]["n_recorded"] == 1
    assert all(s["n_region"] == 13 for s in res["scores"]), "the denominator is the total too"
    # untested is null, never zero — held across the aggregation
    for fl in ((True, False), (False, True)):
        assert by_seat[fl]["correlation"] is None and by_seat[fl]["scorable"] is False

    # the breakdown: one entry per region, each with its own alignment and its own four rows
    assert [b["region_id"] for b in res["regions"]] == ["reg_a", "reg_b"]
    a, b = res["regions"]
    assert a["region_name"] == "field A" and a["n_region"] == 12
    assert [(s["flip_x"], s["flip_y"]) for s in a["seatings"]] == list(SEATINGS)
    assert [s["n_recorded"] for s in a["seatings"]] == [12, 0, 0, 0]
    assert [s["n_recorded"] for s in b["seatings"]] == [0, 0, 0, 1]
    for block in (a, b):
        assert "offset_s" in block and "alignment_quality" in block

    # ⭐ the honesty rules, which no aggregation may relax: two seatings hold recorded pads here,
    # so coverage alone must NOT decide; and without `decisive` there is no `best` at all.
    assert res["decided_by"] != "coverage"
    if not res["decisive"]:
        assert res["best"] is None
    else:
        assert res["decided_by"] == "correlation" and res["best"]["confirmed"] is False
        assert res["beats_chance"] is True, "⛔ a correlation win must have cleared chance"
        assert res["margin"] is not None and res["margin"] >= 0.10
    assert res["caveat"], "the result must never arrive without its caveat"

    # the honesty meter rides on the result: a chance bar measured from the winner's own series
    assert "chance_level" in res and "beats_chance" in res
    if res["chance_level"] is not None:
        assert 0.0 <= res["chance_level"] <= 1.0
        assert isinstance(res["beats_chance"], bool)


def test_orientation_with_region_id_is_the_old_single_region_contract(client, project):
    """`region_id` narrows the test to one region — and with only region A in play, exactly one
    seating holds any recorded pad, which is the geometric case that IS decisive by coverage."""
    r = client.post("/api/videomosaic/mea/orientation",
                    json={"analysis_id": project["aid"], "region_id": "reg_a"})
    assert r.status_code == 202, r.text
    res = run_job(client, r.json()["job_id"])["result"]

    assert (res["region_id"], res["region_name"]) == ("reg_a", "field A")
    assert [b["region_id"] for b in res["regions"]] == ["reg_a"]
    assert all(s["n_region"] == 12 for s in res["scores"])

    assert res["decisive"] is True and res["decided_by"] == "coverage"
    assert (res["best"]["flip_x"], res["best"]["flip_y"]) == (False, False)
    assert res["best"]["confirmed"] is False, "🔴 only a human ever confirms a seating"
    assert "field A" in res["best"]["source"]


def test_orientation_skips_an_unscorable_region_but_refuses_when_named(client, project,
                                                                       tmp_path):
    """A region whose video went missing is skipped in an all-regions run (the others still
    count) — but asking for it BY ID is refused specifically, as it always was."""
    # break region B's video
    Path(tmp_path / "field-b.avi").unlink()

    r = client.post("/api/videomosaic/mea/orientation",
                    json={"analysis_id": project["aid"], "region_id": "reg_b"})
    assert r.status_code == 404
    assert "not where the project left it" in err(r)["message"]

    r = client.post("/api/videomosaic/mea/orientation", json={"analysis_id": project["aid"]})
    assert r.status_code == 202, r.text
    res = run_job(client, r.json()["job_id"])["result"]
    assert [b["region_id"] for b in res["regions"]] == ["reg_a"], "B skipped, A still scored"
    assert res["region_id"] == "reg_a", "one region survived, so the single-region fields hold it"


def test_orientation_footprint_and_job_agree_on_coverage(client, project):
    """🔴 THE CROSS-CHECK: the footprint's per-region `n_covered` and the job's per-region
    `n_recorded` are the same geometric fact through two code paths (`to_grid` vs
    `chip_electrode`). If they ever disagree, one of the two transforms is wrong — silently."""
    foot = client.get("/api/videomosaic/mea/footprint",
                      params={"analysis_id": project["aid"]}).json()
    r = client.post("/api/videomosaic/mea/orientation", json={"analysis_id": project["aid"]})
    res = run_job(client, r.json()["job_id"])["result"]

    job_cover = {(b["region_id"], s["flip_x"], s["flip_y"]): s["n_recorded"]
                 for b in res["regions"] for s in b["seatings"]}
    foot_cover = {(c["region_id"], s["flip_x"], s["flip_y"]): c["n_covered"]
                  for s in foot["seatings"] for c in s["regions"]}
    assert job_cover == foot_cover


# =================================================================================================
# How the clocks were aligned — and the caveat that must match it
# =================================================================================================
def test_orientation_says_when_the_clocks_were_never_aligned(client, project):
    """measynth writes no `bits`, and its 21 channels can never clear the 50-channel episode bar —
    so this run has NO clock alignment, and the result must say exactly that: the unaligned
    wording, not the lamp wording written for a different kind of run."""
    from camea.features.videomosaic.routes import ORIENTATION_CAVEAT_UNALIGNED

    r = client.post("/api/videomosaic/mea/orientation", json={"analysis_id": project["aid"]})
    res = run_job(client, r.json()["job_id"])["result"]
    assert res["alignment_source"] == "none"
    assert res["caveat"] == ORIENTATION_CAVEAT_UNALIGNED


def test_orientation_prefers_the_rigs_own_time_stamp(client, project, tmp_path):
    """⭐ When the recording carries a digital time-stamp (`bits`), the MEA-side marks come from
    it INSTEAD of the distrusted lamp episodes — and the caveat changes with the grounds: the
    timing doubt is gone, the pulse-to-brightness pairing doubt is not."""
    import h5py
    from camea.features.videomosaic.routes import ORIENTATION_CAVEAT_TTL

    rec = tmp_path / "MEA" / "P0000" / "Network" / "000001" / "data.raw.h5"
    with h5py.File(rec, "a") as f:
        first = int(f["data_store/data0000/groups/routed/frame_nos"][0])
        fs = float(f["data_store/data0000/settings/sampling"][0])
        pulse = np.array([(first + int(0.5 * fs), 6), (first + int(0.6 * fs), 0)],
                         dtype=[("frameno", "<u8"), ("bits", "<u2")])
        f.create_group("bits")["0000"] = pulse

    r = client.post("/api/videomosaic/mea/orientation", json={"analysis_id": project["aid"]})
    res = run_job(client, r.json()["job_id"])["result"]

    assert res["alignment_source"] == "ttl"
    assert res["caveat"] == ORIENTATION_CAVEAT_TTL
    # the honesty rules do not loosen because the grounds improved
    if not res["decisive"]:
        assert res["best"] is None
    elif res["best"] is not None:
        assert res["best"]["confirmed"] is False


def test_the_caveat_names_what_each_alignment_rested_on():
    """🔴 One wording per grounds, all three refusing to confirm — the result must never look
    more settled than it is, whichever clock it stood on."""
    from camea.features.videomosaic import routes as vroutes

    assert vroutes.orientation_caveat("ttl") == vroutes.ORIENTATION_CAVEAT_TTL
    assert vroutes.orientation_caveat("lamp") == vroutes.ORIENTATION_CAVEAT
    assert vroutes.orientation_caveat("none") == vroutes.ORIENTATION_CAVEAT_UNALIGNED
    for wording in (vroutes.ORIENTATION_CAVEAT_TTL, vroutes.ORIENTATION_CAVEAT,
                    vroutes.ORIENTATION_CAVEAT_UNALIGNED):
        assert "NOT confirmation" in wording
    # the TTL wording carries the one doubt that survives the better clock
    assert "pairing" in vroutes.ORIENTATION_CAVEAT_TTL
    # the unaligned wording says the correlations mean nothing
    assert "not aligned" in vroutes.ORIENTATION_CAVEAT_UNALIGNED


def test_orientation_refuses_when_no_region_is_scorable(client, tmp_path, videosynth, measynth):
    """Regions exist but none can be scored (no electrodes named) — a refusal that says what a
    region needs, never an empty result."""
    a = _create(client, tmp_path, videosynth, name="unscorable")
    aid = a["analysis_id"]
    _attach(client, tmp_path, measynth, aid)
    _plant(Path(a["folder"]), regions=[
        {"id": "reg_x", "name": "bare", "electrodes": {"ids": []},
         "source": {"path": str(tmp_path / "nowhere.avi")}},
    ])
    r = client.post("/api/videomosaic/mea/orientation", json={"analysis_id": aid})
    assert r.status_code == 409
    assert "none of the located regions" in err(r)["message"]
