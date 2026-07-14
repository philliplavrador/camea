"""The mosaic document payload — the state machine, the derived fields, and the provenance.

Every test here is a statement that **can fail**, and most of them are a bug this project has already
paid for once:

  * the app auto-excluded 26 named trials of one acquisition, and answered on the user's behalf the
    exact question the app exists to help him answer (test_no_dataset_knowledge*);
  * a machine build was laundered into a "hand-placed ground truth" and **destroyed a benchmark**
    (test_provenance*, test_discard_machine*);
  * a re-solve **wiped** a 150-tile sweep with three hand corrections in it (test_seed*);
  * a stale build was exported as if nothing had changed, because the staleness check compared the
    trial list **with itself** (test_stale*);
  * `human_edits`' divert counters were dropped on every save (test_human_edits*).
"""
from __future__ import annotations

import json

import pytest

from camea.core import document as core
from camea.features.mosaic import document as M

# =================================================================================================
# fixtures
# =================================================================================================
RUN = list(range(11, 21))                     # a short contiguous run


def fresh(trials=RUN, **kw) -> dict:
    kw.setdefault("dataset", "260620d")
    kw.setdefault("dataset_key", "260620d-abc123")
    kw.setdefault("data_dir", "D:/data/260620d")
    return M.new_document(trials=list(trials), lo=trials[0], hi=trials[-1], **kw)


def place(doc: dict, trial: int, xy, state="unverified", **extra) -> dict:
    tile = doc["tiles"][str(trial)]
    tile["state"] = state
    tile["status"] = M.STATE_TO_STATUS[state]
    tile["x"], tile["y"] = float(xy[0]), float(xy[1])
    tile.update(extra)
    return doc


def exclude(doc: dict, trial: int) -> dict:
    tile = doc["tiles"][str(trial)]
    if tile.get("x") is not None:
        tile["last_xy"] = [tile["x"], tile["y"]]
    tile["state"] = "excluded"
    tile["status"] = "excluded"
    tile["x"] = tile["y"] = None
    return doc


def a_build(trials=RUN, dx=0.0, dy=0.0, **kw) -> dict:
    b = {"build_id": "b1", "method": "t33", "seconds": 25.0, "gpu": True,
         "positions": {t: [100.0 * i + dx, 7.0 * i + dy] for i, t in enumerate(trials)},
         "n_placed": len(trials), "info": {"config": {"pass_split": 166}}}
    b.update(kw)
    return b


# =================================================================================================
# ⛔ THE APP CARRIES NO DATASET KNOWLEDGE
# =================================================================================================
def test_no_dataset_knowledge_nothing_starts_excluded():
    """R2.1 — opening a dataset fresh excludes NOTHING, and 284 is an ordinary unplaced tile."""
    doc = fresh(range(11, 349))
    assert len(doc["tiles"]) == 338
    assert M.excluded_trials(doc) == []
    assert doc["unusable_tiles"] == []
    assert doc["tiles"]["284"]["state"] == "unplaced"
    assert doc["tiles"]["284"]["status"] == "unplaced"
    assert M.active_trials(doc) == list(range(11, 349))


def test_no_dataset_knowledge_gaps_are_none_on_a_fresh_open():
    """R2.3 — the Gaps field reads `none` until the USER excludes something."""
    assert fresh(range(11, 349))["gaps"] == []


def test_no_dataset_knowledge_the_module_imports_only_gaps():
    """R2.5 / rule 4 — `gaps()` is the ONE symbol the app may take from the exclusion module.

    A source-level guard, on IDENTIFIERS (an `ast` walk, not a substring scan — the prose in this
    file is *about* exclusions and must be allowed to say so).
    """
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path(M.__file__).read_text(encoding="utf-8"))
    forbidden = {"EXCLUDED", "BLANK", "BLURRY", "usable_trials", "BLANK_THRESHOLD",
                 "EXCLUDED_TRIALS", "DATA_DIR"}

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            imports.append(mod)
            assert "excluded" not in mod, (
                f"the mosaic document must not import from {mod!r} — it reaches `gaps()` through "
                "`camea.core.dataset`, the ONE place the app touches that module")
            for alias in node.names:
                assert alias.name not in forbidden, f"forbidden import: {alias.name}"
        if isinstance(node, ast.Name):
            assert node.id not in forbidden, f"forbidden identifier: {node.id}"
        if isinstance(node, ast.Attribute):
            assert node.attr not in forbidden, f"forbidden attribute: .{node.attr}"

    assert any(m == "camea.core.dataset" for m in imports)


def test_the_scan_proposes_it_never_excludes():
    """The blank scan RECOMMENDS. The tile is still ordinary `unplaced` data."""
    doc = fresh(blank={"threshold": 60.11, "proposed": [12, 15]},
                texture={11: 90.0, 12: 55.0, 15: 58.0})
    assert doc["tiles"]["12"]["blank"] is True
    assert doc["tiles"]["12"]["state"] == "unplaced"     # NOT excluded. Never excluded.
    assert M.excluded_trials(doc) == []
    assert doc["blank_scan"]["blank"] == [12, 15]        # the DECISION starts as `Hand place`
    assert doc["blank_scan"]["scanned"] == [12, 15]      # the MEASUREMENT, and it never moves
    assert doc["blank_scan"]["accepted"] is False
    assert M.refusal_set(doc) == [12, 15]
    assert doc["tiles"]["12"]["texture"] == 55.0


def test_a_kept_frame_leaves_the_refusal_set_but_stays_measured_blank():
    """`Keep` lifts the refusal (a decision). `blank` is a measurement and is never cleared."""
    doc = fresh(blank={"proposed": [12, 15]})
    doc["blank_scan"]["blank"] = [15]                    # he pressed Keep on 12
    doc["blank_scan"]["overruled_by_user"] = [12]
    doc = M.normalise(doc)
    assert M.refusal_set(doc) == [15]
    assert doc["tiles"]["12"]["blank"] is True           # still a fact about the pixels


# =================================================================================================
# the four-state machine
# =================================================================================================
def test_both_spellings_are_written_and_anchored_is_status_anchor():
    doc = M.normalise(place(fresh(), 11, (0, 0), state="anchored"))
    assert doc["tiles"]["11"]["state"] == "anchored"
    assert doc["tiles"]["11"]["status"] == "anchor"      # ⚠️ what score.load_gt() keys on


def test_state_of_maps_a_legacy_bench_row_by_its_position():
    assert M.state_of({"status": "region", "x": 1.0, "y": 2.0}) == "unverified"
    assert M.state_of({"status": "pending", "x": None, "y": None}) == "unplaced"
    assert M.state_of({"status": "anchor", "x": 0, "y": 0}) == "anchored"
    assert M.state_of({"state": "excluded", "status": "excluded"}) == "excluded"


def test_a_tile_that_leaves_excluded_stops_claiming_it_was_thrown_out():
    doc = fresh()
    doc["tiles"]["12"].update({"state": "excluded", "status": "excluded",
                               "excluded_reason": "blurry", "unusable_reason": "blurry"})
    doc = M.normalise(doc)
    assert doc["tiles"]["12"]["excluded"] is True

    place(doc, 12, (10, 10), state="anchored")
    doc = M.normalise(doc)
    tile = doc["tiles"]["12"]
    assert tile["status"] == "anchor"
    assert tile["excluded"] is False
    assert "excluded_reason" not in tile and "unusable_reason" not in tile


def test_excluding_keeps_the_position_in_last_xy_and_nulls_x_y():
    doc = M.normalise(exclude(place(fresh(), 12, (33.0, 44.0)), 12))
    tile = doc["tiles"]["12"]
    assert tile["x"] is None and tile["y"] is None
    assert tile["last_xy"] == [33.0, 44.0]


# =================================================================================================
# ⚠️ gaps — DERIVED, and recomputed on every change to the excluded set
# =================================================================================================
def test_excluding_a_tile_opens_a_gap():
    doc = M.normalise(exclude(fresh(), 15))
    assert M.active_trials(doc) == [11, 12, 13, 14, 16, 17, 18, 19, 20]
    assert doc["gaps"] == [[14, 16]]
    assert doc["unusable_tiles"] == [15]


def test_excluding_the_first_trial_opens_no_gap_but_changes_the_input():
    doc = M.normalise(exclude(fresh(), 11))
    assert doc["gaps"] == []
    assert 11 not in M.active_trials(doc)


def test_un_excluding_closes_the_gap_again():
    doc = M.normalise(exclude(fresh(), 15))
    doc["tiles"]["15"].update({"state": "unplaced", "status": "unplaced"})
    doc = M.normalise(doc)
    assert doc["gaps"] == []


# =================================================================================================
# normalise — the origin, and the SAME translation on machine / last_xy
# =================================================================================================
def test_normalise_pins_the_origin_and_shifts_machine_and_last_xy_together():
    doc = fresh()
    place(doc, 11, (100.0, 50.0), state="anchored", machine=[90.0, 50.0])
    place(doc, 12, (612.0, 50.0), machine=[610.0, 55.0])
    doc["tiles"]["13"]["last_xy"] = [100.0, 150.0]
    doc = M.normalise(doc)

    assert doc["origin_trial"] == 11
    assert (doc["tiles"]["11"]["x"], doc["tiles"]["11"]["y"]) == (0.0, 0.0)
    assert (doc["tiles"]["12"]["x"], doc["tiles"]["12"]["y"]) == (512.0, 0.0)
    # ⚠️ the same translation, or moved_px stops meaning anything
    assert doc["tiles"]["11"]["machine"] == [-10.0, 0.0]
    assert doc["tiles"]["12"]["machine"] == [510.0, 5.0]
    assert doc["tiles"]["13"]["last_xy"] == [0.0, 100.0]
    assert doc["tiles"]["11"]["moved_px"] == 10.0
    assert doc["tiles"]["12"]["moved_px"] == round((2.0 ** 2 + 5.0 ** 2) ** 0.5, 4)


def test_the_origin_is_the_first_anchor_not_the_first_placed_tile():
    doc = fresh()
    place(doc, 11, (5.0, 5.0))                            # unverified
    place(doc, 13, (1000.0, 0.0), state="anchored")
    doc = M.normalise(doc)
    assert doc["origin_trial"] == 13
    assert (doc["tiles"]["13"]["x"], doc["tiles"]["13"]["y"]) == (0.0, 0.0)
    assert doc["tiles"]["11"]["x"] == -995.0


def test_normalise_does_not_touch_the_envelope():
    doc = fresh()
    before = json.dumps(doc["provenance"], sort_keys=True)
    out = M.normalise(place(doc, 11, (1.0, 1.0), state="anchored"))
    assert json.dumps(out["provenance"], sort_keys=True) == before


# =================================================================================================
# ⭐ the provenance — derived from the HISTORY, never from the self-declaration
# =================================================================================================
def test_machine_evidence_finds_the_build_block():
    doc, _ = M.seed_from_build(fresh(), a_build())
    ev = M.machine_evidence(doc)
    assert ev is not None and ev["method"] == "t33" and ev["build_id"] == "b1"
    assert "doc['build']" in ev["detected_from"]


def test_machine_evidence_finds_a_lone_machine_position_with_no_build_block():
    """🔴 The laundering path: null the build, keep every tile exactly where the solver put it."""
    doc, _ = M.seed_from_build(fresh(), a_build())
    doc["build"] = None                                   # "Skip — place from scratch"
    doc["provenance"]["seeded_from"] = None
    ev = M.machine_evidence(doc)
    assert ev is not None
    assert "still carry a `machine` position" in ev["detected_from"]


def test_a_hand_placed_document_is_independent_and_carries_no_warning():
    doc = M.stamp(M.normalise(place(fresh(), 11, (0.0, 0.0), state="anchored")))
    assert M.machine_evidence(doc) is None
    assert doc["provenance"]["independent_of_method"] is True
    assert doc["provenance"]["seeded_from"] is None
    assert "warning" not in doc["provenance"]             # a warning that cries wolf is not read


def test_a_seeded_document_carries_the_warning_verbatim():
    doc, _ = M.seed_from_build(fresh(), a_build())
    doc = M.stamp(doc)
    prov = doc["provenance"]
    assert prov["independent_of_method"] is False
    assert prov["warning"] == core.PROVENANCE_WARNING     # VERBATIM. Never paraphrased.
    assert prov["workflow"] == core.WORKFLOW_SEEDED


def test_the_laundered_document_is_still_stamped_not_independent():
    """The whole point: a document cannot lie its way out of the warning."""
    doc, _ = M.seed_from_build(fresh(), a_build())
    doc["build"] = None
    doc["provenance"].update({"seeded_from": None, "independent_of_method": True})
    doc["provenance"].pop("warning", None)

    out = M.stamp(doc)                                    # the stamp re-derives from the HISTORY
    assert out["provenance"]["independent_of_method"] is False
    assert out["provenance"]["warning"] == core.PROVENANCE_WARNING


# =================================================================================================
# discard_machine — 🔴 destructive, or nothing
# =================================================================================================
def test_discard_machine_destroys_every_position_and_the_build():
    doc, _ = M.seed_from_build(fresh(), a_build())
    doc["tiles"]["11"].update({"state": "anchored", "status": "anchor", "human": True,
                               "ncc": 0.9, "seq": 1, "source": "t33"})
    doc = M.normalise(doc)

    out, info = M.discard_machine(doc)
    assert info["had_build"] is True
    assert info["n_positions_discarded"] == len(RUN)
    assert out["build"] is None
    for tile in out["tiles"].values():
        assert tile["state"] == "unplaced" and tile["status"] == "unplaced"
        assert tile["x"] is None and tile["y"] is None and tile["machine"] is None
        for key in ("ncc", "margin", "seq", "human", "source", "diverted"):
            assert key not in tile
    out = M.stamp(out)
    assert M.machine_evidence(out) is None                # and NOW it is honestly independent
    assert out["provenance"]["independent_of_method"] is True


def test_discard_machine_keeps_the_humans_exclusions_and_the_measurements():
    doc = fresh(blank={"proposed": [12]})
    doc, _ = M.seed_from_build(doc, a_build())
    exclude(doc, 14)
    doc = M.normalise(doc)

    out, _ = M.discard_machine(doc)
    assert out["tiles"]["14"]["state"] == "excluded"      # HIS decision. Not the machine's.
    assert out["unusable_tiles"] == [14]
    assert out["tiles"]["12"]["blank"] is True            # a measurement, not an opinion


# =================================================================================================
# seed_from_build — 🔴 a re-solve must not destroy the human's work
# =================================================================================================
def test_seed_places_every_unruled_tile_unverified_and_nothing_is_auto_anchored():
    doc, info = M.seed_from_build(fresh(), a_build())
    assert info["n_seeded"] == len(RUN)
    assert info["n_protected"] == 0
    assert M.anchored_trials(doc) == []                   # I3: NOTHING is ever auto-anchored
    assert len(M.placed_trials(doc)) == len(RUN)
    assert doc["tiles"]["12"]["state"] == "unverified"
    assert doc["tiles"]["12"]["machine"] is not None
    assert doc["build"]["trials"] == M.active_trials(doc)
    assert doc["build"]["gaps"] == doc["gaps"]


def test_a_re_solve_keeps_anchored_and_human_tiles_and_slides_the_build_onto_them():
    doc, _ = M.seed_from_build(fresh(), a_build())
    # the human anchors 11 where he says it goes, and drags 12 by hand
    place(doc, 11, (0.0, 0.0), state="anchored")
    place(doc, 12, (105.0, 8.0), human=True)
    doc = M.normalise(doc)
    human_12 = (doc["tiles"]["12"]["x"], doc["tiles"]["12"]["y"])

    # the same solver, re-run, landing 1000 px away in its own frame
    out, info = M.seed_from_build(doc, a_build(dx=1000.0, dy=-500.0))
    assert info["n_protected"] == 2
    assert out["tiles"]["11"]["state"] == "anchored"
    assert (out["tiles"]["12"]["x"], out["tiles"]["12"]["y"]) == human_12   # NOT overwritten
    # and the rest is seeded IN HIS FRAME, not 1000 px away
    assert abs(out["tiles"]["13"]["x"] - 200.0) < 6.0


def test_seed_refuses_when_it_cannot_tie_the_two_frames_together():
    doc = M.normalise(place(fresh(), 11, (0.0, 0.0), state="anchored"))
    with pytest.raises(M.SeedRefused):
        M.seed_from_build(doc, a_build(trials=[17, 18, 19, 20]))   # 11 is not in the build


def test_seed_records_the_machine_answer_on_a_tile_it_may_not_move():
    doc = M.normalise(place(fresh(), 11, (0.0, 0.0), state="anchored"))
    out, _ = M.seed_from_build(doc, a_build())
    assert out["tiles"]["11"]["state"] == "anchored"
    assert out["tiles"]["11"]["machine"] is not None      # the evidence survives
    assert out["tiles"]["11"]["moved_px"] is not None


def test_the_build_keeps_the_machines_untouched_answer():
    doc, _ = M.seed_from_build(fresh(), a_build(dx=1000.0))
    assert doc["build"]["positions"]["11"] == [1000.0, 0.0]     # the build's own frame
    assert doc["tiles"]["11"]["x"] == 0.0                       # the document's frame


# =================================================================================================
# staleness — ⚠️ excluding a tile changes the input to the solver
# =================================================================================================
def test_excluding_a_tile_makes_the_build_stale():
    doc, _ = M.seed_from_build(fresh(), a_build())
    assert M.is_build_stale(doc) == (False, None)

    doc = M.normalise(exclude(doc, 15))
    stale, why = M.is_build_stale(doc)
    assert stale is True
    assert "15" in why and "Re-solve" in why


def test_a_build_that_does_not_record_its_input_is_stale():
    """🔴 UNKNOWN IS NOT THE SAME AS UNCHANGED. v1 compared the trial list with itself."""
    doc = fresh()
    doc["build"] = {"build_id": "old", "method": "t33", "positions": {}}   # no `trials`
    doc = M.normalise(doc)
    stale, why = M.is_build_stale(doc)
    assert stale is True
    assert "does not record which trials" in why


# =================================================================================================
# human_edits — the honest record
# =================================================================================================
def test_human_edits_counts_and_names_the_diverted_tiles():
    doc, _ = M.seed_from_build(fresh(), a_build())
    doc["tiles"]["13"]["diverted"] = True                 # sitting exactly on the solver's answer
    doc["tiles"]["14"]["diverted"] = True
    place(doc, 12, (300.0, 300.0))                        # a real hand move
    doc = M.stamp(M.normalise(doc))

    he = doc["provenance"]["human_edits"]
    assert he["diverted_to_solver"] == 2
    assert he["diverted_trials"] == [13, 14]
    assert "do not read that number as human agreement" in he["diverted_note"]
    # ⚠️ and they ARE inside accepted_unchanged — which is exactly why the note exists
    assert he["accepted_unchanged"] >= 2
    assert he["moved"] == 1
    assert he["max_move_px"] > 0.0


def test_human_edits_counts_every_exclusion_as_a_human_edit():
    doc = M.stamp(M.normalise(exclude(exclude(fresh(), 12), 15)))
    assert doc["provenance"]["human_edits"]["excluded"] == 2


def test_human_edits_rescued_is_a_tile_the_solver_could_not_place():
    doc, _ = M.seed_from_build(fresh(), a_build(trials=RUN[:-1]))   # 20 is unplaced by the solver
    place(doc, 20, (900.0, 63.0), human=True)                       # the human rescues it
    doc = M.stamp(M.normalise(doc))
    assert doc["provenance"]["human_edits"]["rescued"] == 1


# =================================================================================================
# validate — ⛔ no trial number is special
# =================================================================================================
def test_anchoring_284_is_valid_and_saveable():
    """🔴 The guard that used to live here made the user's own session UNSAVEABLE the moment he
    anchored 284."""
    doc = M.normalise(place(fresh(range(11, 349)), 284, (0.0, 0.0), state="anchored"))
    assert core.structural_problems(doc, M.HOOKS) == []
    out = M.prepare(doc)                                  # would raise ValidationError
    assert out["tiles"]["284"]["status"] == "anchor"


def test_a_state_status_disagreement_is_hard_and_is_never_guessed_at():
    doc = fresh()
    doc["tiles"]["11"].update({"state": "unverified", "status": "anchor", "x": 0.0, "y": 0.0})
    kinds = dict((msg, kind) for kind, msg in M.validate(doc))
    assert any(k == "hard" and "disagrees" in m for m, k in kinds.items())
    with pytest.raises(core.ValidationError):
        M.prepare(doc)


def test_a_placed_tile_with_no_position_is_hard():
    doc = fresh()
    doc["tiles"]["11"].update({"state": "anchored", "status": "anchor"})   # no x/y
    assert any(k == "hard" for k, _ in M.validate(doc))


def test_a_tile_outside_the_trial_range_is_hard():
    doc = fresh()
    doc["tiles"]["999"] = dict(doc["tiles"]["11"])
    assert any(k == "hard" and "999" in m for k, m in M.validate(doc))


def test_the_gap_invariant_is_an_error_not_a_note():
    doc = M.normalise(exclude(fresh(), 15))
    doc["gaps"] = []                                      # a lie
    kinds = [k for k, m in M.validate(doc) if "gaps" in m]
    assert kinds == ["derived"]                           # repaired by normalise, never ignored
    assert M.prepare(doc)["gaps"] == [[14, 16]]


def test_tolerance_px_region_default_is_required_by_the_scorer():
    doc = fresh()
    doc["tolerance_px"] = {}
    assert any("region_default" in m for _k, m in M.validate(doc))
    assert M.prepare(doc)["tolerance_px"]["region_default"] == 256


# =================================================================================================
# ⭐ the document IS a ground-truth document — the scorer reads it unchanged
# =================================================================================================
def test_the_scorer_reads_a_saved_document_unchanged(tmp_path):
    from camea.engine import score

    doc = fresh()
    place(doc, 11, (0.0, 0.0), state="anchored")
    place(doc, 12, (512.0, 3.0), state="anchored")
    place(doc, 13, (1024.0, 6.0))                         # unverified — NOT an anchor
    exclude(doc, 14)

    path = tmp_path / "gt.camea.json"
    core.save(path, doc, M.HOOKS)

    gt, raw = score.load_gt(path)
    assert sorted(gt) == [11, 12]                         # only status == "anchor"
    assert gt[11]["r"] == 96.0                            # the tile's own `r`
    assert raw["tolerance_px"]["region_default"] == 256


def test_unknown_keys_round_trip_verbatim(tmp_path):
    doc = fresh()
    doc["a_hand_written_note"] = "this is somebody's ground truth"
    doc["tiles"]["11"]["reviewed_by"] = "PL"
    place(doc, 11, (0.0, 0.0), state="anchored")

    path = tmp_path / "p.camea.json"
    core.save(path, doc, M.HOOKS)
    out, _warn = core.load(path, M.HOOKS)
    assert out["a_hand_written_note"] == "this is somebody's ground truth"
    assert out["tiles"]["11"]["reviewed_by"] == "PL"


def test_the_cursor_survives_a_round_trip_as_an_integer(tmp_path):
    doc = M.normalise(place(fresh(), 11, (0.0, 0.0), state="anchored"))
    doc["cursor"] = 14
    path = tmp_path / "p.camea.json"
    core.save(path, doc, M.HOOKS)
    out, _ = core.load(path, M.HOOKS)
    assert out["cursor"] == 14 and isinstance(out["cursor"], int)


# =================================================================================================
# migrate
# =================================================================================================
def test_migrate_drops_the_excluded_trials_block_and_never_resurrects_it(tmp_path):
    """R2.4 — loading an old file that carries a hard-coded exclusion list and re-saving it DELETES
    it. A block of dataset knowledge is not a hand-written note."""
    old = {
        "schema_version": "camea-project-1.0",
        "dataset": "260620d", "data_dir": "D:/data/260620d",
        "EXCLUDED_TRIALS": {"trials": [284, 285], "why": "the user's ruling"},
        "trial_range": [11, 20], "tolerance_px": dict(M.TOLERANCE_PX),
        "tiles": {str(t): {"status": "unplaced", "x": None, "y": None} for t in RUN},
    }
    path = tmp_path / "old.camea.json"
    path.write_text(json.dumps(old), encoding="utf-8")

    doc, warnings = core.load(path, M.HOOKS)
    assert "EXCLUDED_TRIALS" not in doc
    assert any("EXCLUDED_TRIALS" in w for w in warnings)
    assert M.excluded_trials(doc) == []                   # and it did NOT exclude 284/285

    core.save(path, doc, M.HOOKS)
    assert "EXCLUDED_TRIALS" not in json.loads(path.read_text(encoding="utf-8"))


def test_a_hand_authored_ground_truth_opens_unchanged(tmp_path):
    """It predates the app: no schema_version, no `feature`, no `state`, no `trial_range`."""
    gt = {
        "tolerance_px": {"region_default": 256},
        "tiles": {"11": {"status": "anchor", "x": 0.0, "y": 0.0, "r": 96},
                  "12": {"status": "anchor", "x": 512.0, "y": 1.0},
                  "13": {"status": "region", "x": 900.0, "y": 2.0},
                  "14": {"status": "excluded", "x": None, "y": None}},
    }
    path = tmp_path / "260620d.json"
    path.write_text(json.dumps(gt), encoding="utf-8")

    doc, _warn = core.load(path, M.HOOKS)
    assert doc["feature"] == "mosaic"                     # the legacy default, on FORMAT grounds
    assert doc["trial_range"] == [11, 14]                 # derived from the tiles it carries
    assert doc["tiles"]["11"]["state"] == "anchored"
    assert doc["tiles"]["13"]["state"] == "unverified"    # a legacy row, mapped by its POSITION
    assert doc["tiles"]["13"]["legacy_status"] == "region"
    assert doc["tiles"]["14"]["state"] == "excluded"
    assert doc["unusable_tiles"] == [14]
    # ⭐ and it is an honest truth: nothing in it came from a machine
    assert doc["provenance"]["independent_of_method"] is True


# =================================================================================================
# the hooks
# =================================================================================================
def test_the_feature_registers_itself_on_import():
    assert core.hooks_for("mosaic") is M.HOOKS
    assert "mosaic" in core.registered_features()


def test_identity_is_the_trial_range_and_guards_the_slot(tmp_path):
    """🔴 Pass 2's autosave once silently overwrote pass 1's ground-truth records. The slot keyed on
    the DIRECTORY; two ranges of one dataset collided. `identity` is what closes it."""
    doc = fresh(range(167, 349))
    assert M.identity(doc) == "167-348"
    assert core.scope_of(doc, M.HOOKS).identity == "167-348"

    path = tmp_path / "pass2.camea.json"
    core.save(path, doc, M.HOOKS)
    pass1 = core.Scope(dataset="260620d", dataset_key="260620d-abc123", identity="11-166")
    with pytest.raises(core.RangeMismatch):
        core.load(path, M.HOOKS, expect=pass1)


def test_counts_are_what_the_browser_card_shows():
    doc = M.normalise(exclude(place(fresh(), 11, (0, 0), state="anchored"), 15))
    assert M.counts(doc) == {"n_tiles": 10, "n_anchored": 1, "n_excluded": 1}


def test_coordinates_is_built_from_the_frame_note_never_asserted():
    note = "the RAW sensor frame (this acquisition's XML declares NO flip: ax=+1, ay=+1)"
    doc = fresh(frame_note=note)
    assert note in doc["coordinates"]
    assert "180deg-flipped" not in doc["coordinates"]
    assert "origin_trial" in doc["coordinates"] and "TOP-LEFT" in doc["coordinates"]
