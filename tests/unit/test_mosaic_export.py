"""The mosaic exporter — `camea.legacy.mosaic.export`.

Every assertion here is one the project has already paid for. In order of what they cost:

  1. ⭐⭐ **TIFF AND PNG ARE TWO DIFFERENT RENDERS.** The TIFF is RAW CAMERA COUNTS; the PNG carries a
     per-tile gain. Both once came from the `flat=True` render while the TIFF's header said RAW —
     trial 11's median went 2111 -> 3435 (x1.63) and a biologist doing photometry in Fiji was reading
     exposure-normalised numbers out of a file that swore they were raw.
  2. ⚠️⚠️ **THE COVERAGE SIDECAR IS MANDATORY.** 13.1 % of the canvas is background encoded as
     exactly 0.0, a TIFF has no alpha channel, and without the mask "empty" and "black" merge forever.
  3. 🔴 **THE EXPORT DESCRIBES THE DOCUMENT AS EXPORTED, NOT AS POSTED.** A laundered document once
     produced a GT JSON saying "NOT AN INDEPENDENT GROUND TRUTH" beside a TIFF header saying
     "hand-placed from scratch". That is the mechanism that already destroyed one benchmark.
  4. ⛔ **THE GT IS SCOREABLE, OR IT DOES NOT LEAVE THE PROCESS.** `tiles[k].status == "anchor"` +
     `tolerance_px.region_default` are the only two lines `score.load_gt()` reads.
  5. ⛔ **EXPORTS NEVER LAND IN A DATASET.**
  6. positions.csv's header is EXACTLY `trial,x,y,state`.
  7. ⛔ **NO DATASET KNOWLEDGE.** No trial number is special; the denominator is the document's own
     excluded set and nothing else.

These run against the REAL `mosaic/document.py` and `mosaic/solve.py` — there is no stub. The tile
state machine, `normalise` and `MARGIN_THIN` all belong to those modules, and pinning the exporter
against a stand-in for them would pin nothing.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from camea.core import document as cdoc
from camea.core.frames import FrameStore, Tone
from camea.legacy.mosaic import export
from camea.legacy.mosaic.document import STATE_TO_STATUS

# ⭐ RETIRED, NOT REMOVED (2026-08-11). The snapshot mosaic builder moved to `camea.legacy.mosaic`
# and is no longer offered for new projects, so its suites are deselected from the fast run —
# `uv run pytest -q` skips this file, `uv run pytest -m legacy -q` still runs it, and it still
# passes. It is deselected because nobody is changing this feature, NOT because it is broken.
pytestmark = pytest.mark.legacy


# =================================================================================================
# Fixtures
# =================================================================================================
TILE = 64  # a small tile: these tests are about the FORMATS, not the compositor


@pytest.fixture
def frames() -> FrameStore:
    """Three 64x64 frames with wildly different exposures — which is the point: `flat_correct`'s
    per-tile gain drags them onto a common level, and that is exactly what the TIFF must NOT do.
    (Exposure genuinely varies ~2.4x across a real run.)"""
    rng = np.random.default_rng(11)
    stack = np.stack([
        rng.normal(1000, 40, (TILE, TILE)),
        rng.normal(3000, 40, (TILE, TILE)),
        rng.normal(2000, 40, (TILE, TILE)),
    ]).astype(np.float32)
    return FrameStore(
        trials=[11, 12, 13],
        frames=stack,
        flat_n=np.ones((TILE, TILE), np.float32),
        tone=Tone(lo=500.0, hi=3500.0, level=2000.0),
        metas={t: {"trial": t, "flip_x": True, "flip_y": True} for t in (11, 12, 13)},
    )


def _tile(state, x=None, y=None, **kw):
    d = {"state": state, "status": STATE_TO_STATUS[state], "x": x, "y": y}
    d.update(kw)
    return d


@pytest.fixture
def doc() -> dict:
    """A hand-placed document. Three tiles in a **staircase**, overlapping by half a tile — so the
    canvas has genuinely uncovered corners, which is the whole reason the coverage mask exists."""
    return {
        "schema_version": cdoc.SCHEMA_VERSION,
        "app": {"name": "Camea", "version": "0.2.0"},
        "id": "test-analysis",
        "feature": "mosaic",
        "dataset": "260620d",
        "experiment": "260620d",
        "data_dir": "",
        "dataset_key": "260620d-abc123",
        "created": "2026-07-14T00:00:00Z",
        "modified": "2026-07-14T00:00:00Z",
        "provenance": {"authored_by": "Camea", "app_version": "0.2.0",
                       "workflow": "hand placement from scratch", "seeded_from": None,
                       "independent_of_method": True},
        "tiles": {
            "11": _tile("anchored", 100.0, 100.0),
            "12": _tile("anchored", 132.0, 100.0),
            "13": _tile("unverified", 164.0, 132.0),
        },
        "trial_range": [11, 13],
        "pass_split": None,
        "origin_trial": 11,
        "tile_px": TILE,
        "coordinates": "RELATIVE. Tile TOP-LEFT in px from origin_trial at (0,0).",
        "tolerance_px": {"anchor": 96, "region_default": 256, "grading": 10},
        "gaps": [],
        "unusable_tiles": [],
    }


@pytest.fixture
def seeded_doc(doc) -> dict:
    """The same document, but every position started as t33's. **This is the hazardous one.**"""
    d = json.loads(json.dumps(doc))
    d["build"] = {"build_id": "b-9f2", "method": "t33", "n_placed": 3,
                  "positions": {"11": [100.0, 100.0], "12": [132.0, 100.0],
                                "13": [164.0, 100.0]},
                  "trials": [11, 12, 13], "gaps": []}
    for k, m in (("11", [100.0, 100.0]), ("12", [130.0, 100.0]), ("13", [164.0, 132.0])):
        d["tiles"][k]["machine"] = m          # 12 was moved 2 px by hand; 11 and 13 were not
    return d


# =================================================================================================
# 1. ⭐⭐ TWO RENDERS. The TIFF is a MEASUREMENT; the PNG is a PICTURE.
# =================================================================================================
def test_raw_render_preserves_exposure_and_flat_render_normalises_it(frames, doc):
    """🔴 **THE BUG.** `flat=True` applies a PER-TILE GAIN (`level / median(frame)`). On a 3x exposure
    spread it drags every tile onto the session level. That is right for a picture and **wrong for a
    measurement** — and the TIFF's header says, in writing, that its counts are raw."""
    pos = export.render_positions(doc)
    raw, _ = export.render_mosaic(frames, pos, "feather", flat=False)
    lit, _ = export.render_mosaic(frames, pos, "feather", flat=True)

    # the RAW canvas keeps the ~1000 / ~3000 spread the camera actually saw
    assert raw.max() > 2800, raw.max()
    assert raw[raw > 0].min() < 1200, raw[raw > 0].min()

    # the FLAT canvas has had it normalised away — every tile is dragged onto the session `level`
    assert lit.max() < 2600, lit.max()                       # trial 12's 3000 counts are GONE
    assert abs(float(np.median(lit[lit > 0])) - frames.tone.level) < 250


def test_tiff_is_written_from_the_raw_render(tmp_path, frames, doc):
    """The pixels in the .tif must be the ones the camera produced, not the ones the picture wants."""
    tifffile = pytest.importorskip("tifffile")
    pos = export.render_positions(doc)
    raw, rcov = export.render_mosaic(frames, pos, "feather", flat=False)

    export.write_tiff(raw, rcov, tmp_path / "m.tif", description="raw")
    back = tifffile.imread(str(tmp_path / "m.tif"))
    assert back.dtype == np.uint16
    assert back.max() > 2800                       # trial 12's ~3000 counts survived
    np.testing.assert_array_equal(back[~rcov], 0)  # background is EXACTLY 0


# =================================================================================================
# 2. ⚠️⚠️ THE COVERAGE SIDECAR IS MANDATORY
# =================================================================================================
def test_tiff_always_emits_the_coverage_sidecar(tmp_path, frames, doc):
    """There is no flag that turns it off, and asking for `tiff` is what asks for it."""
    pytest.importorskip("tifffile")
    pos = export.render_positions(doc)
    raw, rcov = export.render_mosaic(frames, pos, "feather", flat=False)

    entries = export.write_tiff(raw, rcov, tmp_path / "m.tif")
    assert [e["kind"] for e in entries] == ["tiff", "coverage"]
    assert (tmp_path / "m_coverage.png").is_file()


def test_coverage_distinguishes_background_from_black_tissue(tmp_path, frames, doc):
    """⚠️ Background is `0.0` and a black pixel is `0.0`. **The mask is the only thing that can tell
    them apart**, and a TIFF has no alpha channel."""
    from PIL import Image

    pos = export.render_positions(doc)
    _raw, rcov = export.render_mosaic(frames, pos, "feather", flat=False)
    export.write_coverage(rcov, tmp_path / "c.png")

    mask = np.asarray(Image.open(tmp_path / "c.png"))
    assert set(np.unique(mask)) <= {0, 255}
    assert 0 in np.unique(mask), "a 3-tile L-free strip should still have uncovered corners"
    np.testing.assert_array_equal(mask > 0, rcov)


def test_coverage_is_pure_geometry_and_reads_no_pixel(frames, doc):
    """It is FREE. Which is why there is no excuse for a TIFF that ships without one."""
    pos = export.render_positions(doc)
    geom = export.coverage_mask(frames, pos)
    _img, rendered = export.render_mosaic(frames, pos, "feather", flat=False)
    np.testing.assert_array_equal(geom, rendered)


# =================================================================================================
# 3. 🔴 THE DOCUMENT AS EXPORTED, NOT AS POSTED
# =================================================================================================
def test_a_laundered_document_gets_its_warning_put_back(seeded_doc):
    """🔴 **THE MECHANISM THAT ALREADY DESTROYED ONE BENCHMARK.** Null the build, null `seeded_from`,
    flip `independent_of_method` to true, delete the warning — **and move not one tile.** Every
    position is still t33's. Score t33 against that and it gets 100 % by construction."""
    laundered = json.loads(json.dumps(seeded_doc))
    laundered["build"] = None
    laundered["provenance"]["seeded_from"] = None
    laundered["provenance"]["independent_of_method"] = True
    laundered["provenance"].pop("warning", None)
    assert all(t.get("machine") for t in laundered["tiles"].values())  # the tiles never moved

    out, _problems = export.as_exported(laundered)

    assert out["provenance"]["independent_of_method"] is False
    assert out["provenance"]["warning"] == cdoc.PROVENANCE_WARNING  # verbatim
    # ⭐ And it says WHY, from the evidence — the tiles themselves. With the build block gone it
    # does not know *which* method placed them, and it says so rather than guessing one.
    seeded = out["provenance"]["seeded_from"]
    assert seeded and "machine" in seeded["method"]
    assert "`machine` position" in seeded["detected_from"]


def test_the_tiff_header_and_the_gt_tell_the_same_story(tmp_path, frames, seeded_doc):
    """A GT JSON saying "NOT AN INDEPENDENT GROUND TRUTH" beside a TIFF header saying "hand-placed
    from scratch" is precisely what shipped once. They are derived from the same stamped document."""
    tifffile = pytest.importorskip("tifffile")
    res = export.export_all(frames, None, seeded_doc, tmp_path, "m", outputs=["tiff", "gt"])

    with tifffile.TiffFile(str(tmp_path / "m.tif")) as tf:
        header = tf.pages[0].tags["ImageDescription"].value
    gt = json.loads((tmp_path / "m_gt.json").read_text(encoding="utf-8"))

    assert "NOT AN INDEPENDENT GROUND TRUTH" in header
    assert "hand-placed from scratch" not in header
    assert gt["provenance"]["independent_of_method"] is False
    assert gt["provenance"]["warning"] == cdoc.PROVENANCE_WARNING
    assert res["doc"]["provenance"]["independent_of_method"] is False


def test_a_genuinely_hand_placed_doc_carries_no_warning(tmp_path, frames, doc):
    """A warning that cries wolf is a warning nobody reads. **That document IS a truth.**"""
    pytest.importorskip("tifffile")
    export.export_all(frames, None, doc, tmp_path, "m", outputs=["tiff", "gt"])
    gt = json.loads((tmp_path / "m_gt.json").read_text(encoding="utf-8"))
    assert gt["provenance"]["independent_of_method"] is True
    assert "warning" not in gt["provenance"]


def test_the_tiff_header_never_hard_codes_a_flip(tmp_path, frames, doc):
    """⭐ It asks the FRAME STORE, which asked the XML. v1 asserted "180-degree-flipped"
    unconditionally while the reader flips CONDITIONALLY on `ax`/`ay`."""
    tifffile = pytest.importorskip("tifffile")
    frames.metas = {t: {"trial": t, "flip_x": False, "flip_y": False} for t in frames.trials}

    export.export_all(frames, None, doc, tmp_path, "m", outputs=["tiff"])
    with tifffile.TiffFile(str(tmp_path / "m.tif")) as tf:
        header = tf.pages[0].tags["ImageDescription"].value

    assert "RAW sensor frame" in header
    assert "180deg-flipped" not in header
    assert "top-left corners (NOT centres)" in header


def test_the_tiff_header_is_ascii_but_keeps_the_text(tmp_path, frames, seeded_doc):
    """TIFF's ImageDescription is an ASCII tag and `PROVENANCE_WARNING` has an em-dash.
    **Fold, do not drop** — the text is the entire point of putting it there."""
    tifffile = pytest.importorskip("tifffile")
    export.export_all(frames, None, seeded_doc, tmp_path, "m", outputs=["tiff"])
    with tifffile.TiffFile(str(tmp_path / "m.tif")) as tf:
        header = tf.pages[0].tags["ImageDescription"].value
    header.encode("ascii")  # raises if the fold leaked a byte
    assert "100 %" in header and "by construction" in header  # the sentence survived the fold


# =================================================================================================
# 4. ⛔ THE GT IS SCOREABLE, OR IT DOES NOT LEAVE THE PROCESS
# =================================================================================================
def test_gt_keeps_the_two_lines_score_load_gt_reads(tmp_path, doc):
    export.write_gt(doc, tmp_path / "gt.json")
    gt = json.loads((tmp_path / "gt.json").read_text(encoding="utf-8"))

    assert gt["tolerance_px"]["region_default"] == 256
    anchors = {k: v for k, v in gt["tiles"].items() if v["status"] == "anchor"}
    assert set(anchors) == {"11", "12"}                     # ⚠️ state `anchored` -> status `anchor`
    assert all(v["x"] is not None and v["y"] is not None for v in anchors.values())
    assert gt["tiles"]["13"]["status"] == "unverified"      # does NOT inflate the denominator


def test_a_gt_that_lost_region_default_is_repaired_on_the_way_out(tmp_path, doc):
    """`score.load_gt()` would KeyError on any tile with no explicit `r`. **A project the scorer
    cannot read is a project that cannot be checked** — so `document.normalise` puts the key back,
    and the exported GT is scoreable whatever the caller posted."""
    doc["tolerance_px"] = {"anchor": 96}
    export.write_gt(doc, tmp_path / "gt.json")
    gt = json.loads((tmp_path / "gt.json").read_text(encoding="utf-8"))
    assert gt["tolerance_px"]["region_default"] == 256


def test_an_unscoreable_gt_never_leaves_the_process(tmp_path):
    """The post-condition, checked on the *serialised* document — the belt to normalise's braces. If
    a future `normalise` ever stops repairing `tolerance_px`, this is what fails, loudly, instead of
    a GT file that KeyErrors inside somebody else's scorer a week later."""
    with pytest.raises(export.ExportError, match="region_default"):
        export._assert_scoreable({"tiles": {}, "tolerance_px": {"anchor": 96}})

    with pytest.raises(export.ExportError, match="null position"):
        export._assert_scoreable({
            "tolerance_px": {"region_default": 256},
            "tiles": {"11": {"status": "anchor", "x": None, "y": None}},
        })


def test_gt_with_no_anchors_warns_but_still_writes(tmp_path, doc):
    for t in doc["tiles"].values():
        t["state"], t["status"] = "unverified", "unverified"
    with pytest.warns(UserWarning, match="ZERO anchor tiles"):
        export.write_gt(doc, tmp_path / "gt.json")
    assert (tmp_path / "gt.json").is_file()


def test_the_origin_is_pinned_at_exactly_zero_zero(tmp_path, doc):
    """It matches `analysis/ground_truth/`, which has trial 11 at (0, 0). A layout is defined only up
    to a global translation, so this loses nothing."""
    gt = export.to_gt(doc)
    assert gt["origin_trial"] == 11
    assert (gt["tiles"]["11"]["x"], gt["tiles"]["11"]["y"]) == (0.0, 0.0)
    assert gt["tiles"]["12"]["x"] == 32.0


# =================================================================================================
# 5. ⛔ EXPORTS GO TO THE WORKSPACE. NEVER TO A DATASET.
# =================================================================================================
def test_refuses_to_export_into_a_raw_acquisition(tmp_path, frames, doc):
    """⛔ **A DATASET IS THE MICROSCOPE'S EVIDENCE. THE APP DOES NOT WRITE ON THE EVIDENCE.** It is
    recognised by its SHAPE (`log.txt` + `NNN.xml`), never by its name — so a folder the app was
    never told about is refused too."""
    from camea.core.dataset import DatasetIsReadOnly

    fake = tmp_path / "260620d"
    fake.mkdir()
    (fake / "log.txt").write_text("New experiment: x\n", encoding="utf-8")
    (fake / "011.xml").write_text("<vsdscopeSettings/>", encoding="utf-8")

    with pytest.raises(DatasetIsReadOnly):
        export.export_all(frames, None, doc, fake / "out", "m", outputs=["positions"])


def test_a_bad_basename_is_refused(tmp_path, frames, doc):
    with pytest.raises(ValueError):
        export.export_all(frames, None, doc, tmp_path, "../evil", outputs=["positions"])


def test_export_to_analysis_lands_in_the_workspace(tmp_path, frames, doc):
    from camea.core.workspace import Workspace

    ws = Workspace.open(tmp_path / "ws")
    a = ws.create_analysis(feature="mosaic", name="pass 1", dataset_key="k", dataset="260620d")
    doc["id"] = a.analysis_id

    res = export.export_to_analysis(frames, None, doc, ws, a.analysis_id, "m", outputs=["positions"])
    assert (ws.outputs_dir(a.analysis_id) / "m_positions.csv").is_file()
    assert res["files"][0]["path"].endswith("/outputs/m_positions.csv")


# =================================================================================================
# 6. positions.csv — the header is a CONTRACT
# =================================================================================================
def test_positions_csv_header_is_exactly_what_the_scorer_dictreads(tmp_path, doc):
    export.write_positions(doc, tmp_path / "p.csv")
    lines = (tmp_path / "p.csv").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "trial,x,y,state"
    assert lines[1].startswith("11,0.0000,0.0000,anchored")
    assert len(lines) == 4  # header + 11 + 12 + 13


def test_positions_csv_omits_unverified_when_asked(tmp_path, doc):
    export.write_positions(doc, tmp_path / "p.csv", include_unverified=False)
    body = (tmp_path / "p.csv").read_text(encoding="utf-8").splitlines()[1:]
    assert [r.split(",")[0] for r in body] == ["11", "12"]


def test_excluded_and_unplaced_are_never_rendered_and_never_written(tmp_path, doc):
    doc["tiles"]["13"] = _tile("excluded", last_xy=[164.0, 100.0])
    doc["tiles"]["14"] = _tile("unplaced")

    assert set(export.render_positions(doc)) == {11, 12}
    export.write_positions(doc, tmp_path / "p.csv")
    body = (tmp_path / "p.csv").read_text(encoding="utf-8").splitlines()[1:]
    assert [r.split(",")[0] for r in body] == ["11", "12"]


def test_a_bench_written_row_with_an_unknown_status_still_renders(doc):
    """🔴 v1 had TWO `_state_of`s and they DISAGREED. export's returned `str(status)`, so a GT row
    with `status: "region"` became state `"region"` — in neither {anchored, unverified} — and was
    **silently not rendered**. There is one now, and it lives in `mosaic/document.py`."""
    doc["tiles"]["13"] = {"status": "region", "x": 164.0, "y": 100.0}
    assert 13 in export.render_positions(doc)


# =================================================================================================
# 7. THE QC REPORT — every number states its denominator
# =================================================================================================
def test_qc_denominator_is_the_documents_own_excluded_set(seeded_doc):
    """⛔ **NO DATASET KNOWLEDGE.** The app has no exclusion list of its own, so the denominator is
    a pure function of THIS document: un-exclude the tile and the denominator moves."""
    seeded_doc["tiles"]["14"] = _tile("excluded")
    qc, md = export.qc_report(seeded_doc)

    assert qc["denominator"] == {
        "trials_in_document": 4, "not_excluded": 3, "excluded": 1, "excluded_trials": [14],
        "note": qc["denominator"]["note"],
    }
    assert "usable_trials" not in qc["denominator"]  # ⚠️ RENAMED: it collided with the forbidden one
    assert "**3** trials the human did not exclude" in md

    seeded_doc["tiles"]["14"] = _tile("unplaced")   # he changed his mind. The report follows him.
    qc2, _ = export.qc_report(seeded_doc)
    assert qc2["denominator"]["not_excluded"] == 4
    assert qc2["denominator"]["excluded_trials"] == []


def test_qc_names_the_diverts_next_to_the_number_they_contaminate(seeded_doc):
    """⭐ A diverted tile sits **at the machine's position**, so it lands inside `accepted_unchanged`
    and reads as human agreement it never gave."""
    seeded_doc["tiles"]["13"]["diverted"] = True
    qc, md = export.qc_report(seeded_doc)

    assert qc["human_edits"]["diverted_to_solver"] == 1
    assert qc["human_edits"]["diverted_trials"] == [13]
    assert "DIVERTED to the solver" in md
    assert "accepted" in md.split("DIVERTED to the solver")[1][:400]


def test_qc_moved_rows_are_worst_first_and_carry_the_evidence(seeded_doc):
    seeded_doc["tiles"]["12"]["ncc"] = 0.91
    seeded_doc["tiles"]["12"]["margin"] = 0.42
    qc, _md = export.qc_report(seeded_doc)

    assert [r["trial"] for r in qc["moved"]] == [12]   # 11 and 13 sit exactly on the machine
    assert qc["moved"][0]["moved_px"] == pytest.approx(2.0)
    assert qc["moved"][0]["from"] == [30.0, 0.0] and qc["moved"][0]["to"] == [32.0, 0.0]
    assert qc["moved"][0]["ncc"] == 0.91


def test_qc_thin_margin_threshold_comes_from_the_matcher(seeded_doc):
    """⚠️ v1 had this number in THREE places. A QC report that flags a different set of tiles from
    the one the matcher warned about is worse than no report."""
    from camea.legacy.mosaic.solve import MARGIN_THIN

    seeded_doc["tiles"]["12"]["margin"] = 0.081   # the shipped build's worst run margin
    seeded_doc["tiles"]["13"]["margin"] = 0.47    # typical
    qc, _md = export.qc_report(seeded_doc)

    assert qc["thin_margin"] == [12]
    assert qc["thin_margin_threshold"] == MARGIN_THIN


def test_qc_report_carries_the_provenance_warning_verbatim(seeded_doc):
    qc, md = export.qc_report(seeded_doc)
    assert qc["provenance"]["warning"] == cdoc.PROVENANCE_WARNING
    assert cdoc.PROVENANCE_WARNING in md
    assert "THIS IS NOT AN INDEPENDENT GROUND TRUTH" in md


def test_qc_says_pass1_tiles_have_no_confidence(tmp_path, doc):
    """🔴 **THE ABSENCE OF A WARNING IS NOT A CLEAN BILL OF HEALTH.** The worst tile in the shipped
    312/312 build (127, at 9.94 px) is a pass-1 tile, and t27's info is aggregate-only."""
    export.write_qc(doc, tmp_path / "qc.json", tmp_path / "qc.md")
    md = (tmp_path / "qc.md").read_text(encoding="utf-8")
    assert "no per-tile confidence at all" in md
    assert "not** a clean bill of health" in md


def test_qc_refuses_to_judge_blur(tmp_path, doc):
    """❌ **NO BLUR SCORE. ANYWHERE. EVER.** Variance-of-Laplacian scores worse than chance."""
    export.write_qc(doc, tmp_path / "qc.json", tmp_path / "qc.md")
    md = (tmp_path / "qc.md").read_text(encoding="utf-8")
    assert "Blur is not measured here" in md
    qc = json.loads((tmp_path / "qc.json").read_text(encoding="utf-8"))
    assert not any("blur" in k.lower() for k in qc)


# =================================================================================================
# 8. 📏 SCALE — pixels only
# =================================================================================================
def test_scale_is_pixels_only_by_default():
    s = export.scale_metadata(None)
    assert s["um_per_px"] is None and s["source"] == "unknown"
    assert "1.237" not in json.dumps(s)          # ❌ it came from a broken inference


def test_a_typed_in_scale_is_stamped_as_typed_in():
    s = export.scale_metadata(1.5)
    assert s["um_per_px"] == 1.5
    assert s["source"] == "user-supplied by hand, not measured"   # api.schemas.Scale.source
    assert "NOT measured by this app" in s["note"]


def test_a_nonsense_scale_is_refused():
    with pytest.raises(export.ExportError):
        export.scale_metadata(0.0)
    with pytest.raises(export.ExportError):
        export.scale_metadata(-3.0)


# =================================================================================================
# 9. The job as a whole
# =================================================================================================
def test_export_all_writes_seven_files(tmp_path, frames, doc):
    """`ExportResult` says seven: tiff, coverage, png, positions, gt, qc.json, qc.md."""
    pytest.importorskip("tifffile")
    res = export.export_all(frames, None, doc, tmp_path, "mosaic")

    assert [e["kind"] for e in res["files"]] == [
        "tiff", "coverage", "png", "positions", "gt", "qc", "qc"]
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "mosaic.png", "mosaic.tif", "mosaic_coverage.png", "mosaic_gt.json",
        "mosaic_positions.csv", "mosaic_qc.json", "mosaic_qc.md",
    ]
    assert all(e["bytes"] > 0 for e in res["files"])


def test_asking_for_tiff_and_coverage_writes_one_coverage_file(tmp_path, frames, doc):
    pytest.importorskip("tifffile")
    res = export.export_all(frames, None, doc, tmp_path, "m", outputs=["tiff", "coverage"])
    assert [e["kind"] for e in res["files"]] == ["tiff", "coverage"]
    assert len(list(tmp_path.glob("*_coverage.png"))) == 1


def test_coverage_alone_needs_no_pixels(tmp_path, frames, doc, monkeypatch):
    """It is geometry. A caller who wants only the mask must not pay for a render."""
    def _boom(*a, **kw):
        raise AssertionError("render_mosaic was called for a coverage-only export")

    monkeypatch.setattr(export, "render_mosaic", _boom)
    res = export.export_all(frames, None, doc, tmp_path, "m", outputs=["coverage"])
    assert [e["kind"] for e in res["files"]] == ["coverage"]


def test_a_cancelled_export_raises_the_one_cancelled(tmp_path, frames, doc):
    """⛔ There is exactly ONE `Cancelled`, and it is `core.jobs`'. v1 had two, so a cancelled job was
    marked **failed, with a traceback**, instead of cancelled."""
    import threading

    from camea.core.jobs import Cancelled

    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        export.export_all(frames, None, doc, tmp_path, "m", outputs=["tiff"], cancel=cancel)


def test_an_empty_render_is_refused_not_written(tmp_path, frames, doc):
    for t in doc["tiles"].values():
        t["state"], t["status"] = "unplaced", "unplaced"
    with pytest.raises(export.ExportError, match="nothing to render"):
        export.export_all(frames, None, doc, tmp_path, "m", outputs=["png"])


def test_unknown_kinds_and_modes_are_refused(tmp_path, frames, doc):
    with pytest.raises(export.ExportError, match="unknown output kind"):
        export.export_all(frames, None, doc, tmp_path, "m", outputs=["jpeg"])
    with pytest.raises(export.ExportError, match="unknown render_mode"):
        export.export_all(frames, None, doc, tmp_path, "m", outputs=["png"], render_mode="bicubic")


def test_progress_is_reported_and_ends_at_100(tmp_path, frames, doc):
    seen: list = []
    export.export_all(frames, None, doc, tmp_path, "m", outputs=["png", "positions"],
                      report=seen.append)
    assert seen and seen[-1].pct == 100.0
    assert {p.phase for p in seen} >= {"render", "png", "positions", "done"}


def test_the_png_is_one_global_window(tmp_path, frames, doc):
    """⚠️⚠️ **GLOBAL, NEVER PER-TILE.** A per-tile stretch makes overlapping tiles disagree in
    brightness, which destroys the Difference-mode check the verification loop depends on."""
    from PIL import Image

    pos = export.render_positions(doc)
    img, cov = export.render_mosaic(frames, pos, "feather", flat=True)
    export.write_png(img, cov, frames.tone, tmp_path / "m.png")

    u8 = np.asarray(Image.open(tmp_path / "m.png"))
    lo, hi = frames.tone.lo, frames.tone.hi
    expect = np.clip((img - lo) * (255.0 / (hi - lo)), 0, 255).astype(np.uint8)
    expect[~cov] = 0
    np.testing.assert_array_equal(u8, expect)


def test_the_result_doc_is_the_stamped_one(tmp_path, frames, seeded_doc):
    """`ExportResult.doc` — *"the document as exported. Not as posted."*"""
    res = export.export_all(frames, None, seeded_doc, tmp_path, "m", outputs=["gt"])
    on_disk = json.loads((tmp_path / "m_gt.json").read_text(encoding="utf-8"))
    assert res["doc"]["provenance"]["warning"] == on_disk["provenance"]["warning"]
    assert res["doc"]["tiles"]["11"]["x"] == on_disk["tiles"]["11"]["x"] == 0.0
