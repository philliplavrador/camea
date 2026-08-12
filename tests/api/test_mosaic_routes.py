"""The MOSAIC routes, against the synthetic acquisition.

The interesting ones are the four that this project has already been burned by:

  * the run gate drops **only by shape**, and says so;
  * the blank scan **proposes** and never excludes;
  * a blank TARGET is refused while a blank ANCHOR is merely dropped (they are NOT symmetric);
  * `seed` keeps the human's work, and `discard-machine` is destructive or it is nothing.

⚠️ `build` is not run here — a real t33 solve needs the GPU and minutes. The finished-build register
is populated directly, which is what lets `seed` / `machine-evidence` / `discard` / `qc` / `export`
be tested honestly and in milliseconds. The build ROUTE itself (and its spawned child) is exercised
in `test_260620d.py`, under `-m slow`.
"""

from __future__ import annotations

from pathlib import Path

import math

import pytest

from .conftest import (
    OFF_SHAPE_TRIAL,
    RUN_HI,
    RUN_LO,
    STRAY_SNAPSHOTS,
    err,
    open_session,
    run_job,
)

# =================================================================================================
# Step 2 · Range
# =================================================================================================


def test_the_run_is_the_longest_snapshot_block_and_nothing_is_hard_coded(client, synth):
    sid = open_session(client, synth.path, synth.trials)["session_id"]
    run = client.post("/api/mosaic/run", json={"session_id": sid}).json()

    assert (run["lo"], run["hi"]) == (RUN_LO, RUN_HI)
    assert run["n"] == len(synth.trials)
    assert run["trials"] == synth.trials
    assert run["detected"] is True
    assert "longest run of Snapshot trials" in run["why"]
    assert run["dropped"] == []
    assert run["gaps"] == []


def test_the_pass_split_is_MEASURED_from_the_clock(client, synth):
    """⭐ **NEVER A HARD-CODED 166.** The split is the trial before the largest interior pause — the
    moment the stage drove back to the origin. Here it is planted in the synthetic log's timestamps
    and NOWHERE else, and the detector must find it.

    ⭐ `value` is the **LAST TRIAL OF PASS 1**, never the first of pass 2."""
    sid = open_session(client, synth.path, synth.trials)["session_id"]
    ps = client.post("/api/mosaic/run", json={"session_id": sid}).json()["pass_split"]

    assert ps["value"] == synth.pass_split
    assert ps["detected"] is True
    assert ps["gap_s"] == 40.0 and ps["median_gap_s"] == 2.0
    assert ps["n_pass1"] + ps["n_pass2"] == len(synth.trials)
    assert "NOT DECISIVE" not in ps["why"]


def test_the_pass_split_is_always_overridable(client, synth):
    sid = open_session(client, synth.path, synth.trials)["session_id"]
    run = client.post("/api/mosaic/run",
                      json={"session_id": sid, "pass_split": 15}).json()
    assert run["pass_split"]["value"] == 15
    assert run["pass_split"]["detected"] is False
    assert "by hand" in run["pass_split"]["why"]


def test_the_gate_drops_by_SHAPE_loudly_and_never_by_trial_number(client, synth):
    """⛔⛔ A frame leaves the run for exactly two reasons, and both are facts about the file on disk.
    ⚠️ The 512x128 frame is REAL DATA — it is simply not a 512x512 mosaic tile. It is dropped by
    shape, with its measured w/h, and never silently reshaped into a 512x512 lie."""
    sid = open_session(client, synth.path, synth.trials)["session_id"]
    run = client.post("/api/mosaic/run", json={"session_id": sid, "lo": 7, "hi": 9}).json()

    assert run["trials"] == [7, 8]
    dropped = {d["trial"]: d for d in run["dropped"]}
    assert dropped[OFF_SHAPE_TRIAL]["reason"] == "off_shape"
    assert (dropped[OFF_SHAPE_TRIAL]["w"], dropped[OFF_SHAPE_TRIAL]["h"]) == (512, 128)
    assert run["detected"] is False                          # chosen by hand


def test_rescope_makes_the_range_stick_and_keeps_the_work(client, synth):
    """⭐ `Apply` on the Range step. A project opens on every square snapshot the dataset holds —
    including the strays before the scan started (5, 7, 8 here; 1 and 5-7 on 260620d). They are not
    tiles of this mosaic, and until this route they were swept, solved and exported as if they were.

    🔴 And a re-scope must not wipe the sweep: every surviving tile keeps its position and its state.
    ⛔ A dropped trial is NOT an exclusion — `unusable_tiles` stays the human's own `E` presses."""
    everything = [*STRAY_SNAPSHOTS, *synth.trials]
    sid = open_session(client, synth.path, everything)["session_id"]
    aid = client.post("/api/projects",
                      json={"session_id": sid, "feature": "mosaic", "name": "s",
                            "trials": everything}).json()["analysis_id"]
    doc = client.get(f"/api/analyses/{aid}/document").json()["doc"]
    assert len(doc["tiles"]) == len(everything)              # the strays came in as tiles

    # some work on a tile that will SURVIVE, and one the user excluded by hand
    doc["tiles"][str(RUN_LO)].update({"state": "anchored", "status": "anchor", "human": True,
                                      "x": 0.0, "y": 0.0, "ncc": 0.91, "seq": 1})
    doc["tiles"][str(RUN_LO + 1)].update({"state": "excluded", "status": "excluded",
                                          "x": None, "y": None})

    r = client.post("/api/mosaic/document/rescope",
                    json={"session_id": sid, "doc": doc, "lo": RUN_LO, "hi": RUN_HI})
    assert r.status_code == 200, r.text
    out = r.json()

    assert out["removed"] == STRAY_SNAPSHOTS and out["n_placed_removed"] == 0
    assert out["added"] == []
    assert sorted(int(t) for t in out["doc"]["tiles"]) == synth.trials
    assert out["run"]["lo"] == RUN_LO and out["run"]["hi"] == RUN_HI
    assert out["doc"]["trial_range"] == [RUN_LO, RUN_HI]

    kept = out["doc"]["tiles"][str(RUN_LO)]
    assert kept["state"] == "anchored" and kept["ncc"] == 0.91  # the human's work survived
    assert out["doc"]["unusable_tiles"] == [RUN_LO + 1]         # ⛔ his `E`, and ONLY his `E`
    assert out["doc"]["pass_split"] == synth.pass_split         # re-detected for the new range


def test_rescope_refuses_a_range_with_no_snapshot_in_it(client, synth):
    sid = open_session(client, synth.path, synth.trials)["session_id"]
    aid = client.post("/api/projects",
                      json={"session_id": sid, "feature": "mosaic", "name": "s",
                            "trials": synth.trials}).json()["analysis_id"]
    doc = client.get(f"/api/analyses/{aid}/document").json()["doc"]

    r = client.post("/api/mosaic/document/rescope",
                    json={"session_id": sid, "doc": doc, "lo": 1, "hi": 2})  # E'phys trials only
    assert r.status_code == 400
    assert err(r)["code"] == "bad_request"


def test_gaps_is_a_pure_function_over_a_trial_list(client):
    """⭐ `gaps()` is the ONE symbol the app may import from the exclusion module — never `EXCLUDED`,
    never `usable_trials`. **This route is the single place the app touches it.** No session needed:
    it knows nothing about any dataset."""
    r = client.post("/api/mosaic/gaps", json={"trials": [11, 12, 13, 20, 21, 30]})
    assert r.status_code == 200
    assert [list(g) for g in r.json()["gaps"]] == [[13, 20], [21, 30]]
    assert client.post("/api/mosaic/gaps", json={"trials": []}).json()["gaps"] == []


def test_the_app_cannot_import_a_dataset_ruling(client):
    """⛔ **STRUCTURALLY ABSENT, NOT ABSENT BY CONVENTION.** `camea.engine.excluded` has `gaps()` and
    nothing else, so there is no `EXCLUDED` for a future agent to reach for."""
    from camea.engine import excluded

    for forbidden in ("EXCLUDED", "BLANK", "BLURRY", "usable_trials", "DATA_DIR", "PASS1"):
        assert not hasattr(excluded, forbidden), f"engine.excluded grew {forbidden}"


# =================================================================================================
# Step 3 · Screen — ⭐ IT RECOMMENDS. THE HUMAN TICKS.
# =================================================================================================


def test_the_blank_scan_proposes_and_excludes_NOTHING(client, synth):
    sid = open_session(client, synth.path, synth.trials)["session_id"]
    r = client.post("/api/mosaic/screen/propose",
                    json={"session_id": sid, "trials": synth.trials,
                          "pass_split": synth.pass_split})
    assert r.status_code == 200
    p = r.json()
    assert p["n_scanned"] == len(synth.trials)
    assert p["threshold_source"]                             # ⛔ computed, never a carried constant
    assert isinstance(p["proposed"], list)

    # ⭐ THE POINT: a proposal changes NO document. Nothing is auto-excluded, here or anywhere.
    aid = client.post("/api/projects",
                      json={"session_id": sid, "feature": "mosaic", "name": "s",
                            "trials": synth.trials}).json()["analysis_id"]
    doc = client.get(f"/api/analyses/{aid}/document").json()["doc"]
    assert [t for t, v in doc["tiles"].items() if v["state"] == "excluded"] == []


def test_there_is_no_blank_threshold_constant_in_the_source(client):
    """⛔ v1 carried `60.11` — 260620d's own measured number — in the source "as a fallback". That is
    dataset knowledge. It is deleted, not ported: the threshold is computed from the frames in front
    of it, every time."""
    from camea.features.mosaic import routes

    assert not hasattr(routes, "BLANK_THRESHOLD")
    assert routes.BLANK_PCT == 2.0                           # a POLICY (a percentile), not a value


# =================================================================================================
# Step 5 · Sweep — ⭐⭐ the anchor-composite primitive
# =================================================================================================


def test_match_anchor_finds_the_truth_we_planted(client, synth):
    """⭐ The synthetic tiles were cut from one source image at KNOWN offsets. The matcher has never
    been told them. It must find them — and `world_topleft = m0 + (dx, dy)`, which is the arithmetic
    that is ~512 px wrong if you get it backwards."""
    sid = open_session(client, synth.path, synth.trials)["session_id"]
    a, t = synth.trials[0], synth.trials[1]

    r = client.post("/api/mosaic/match/anchor",
                    json={"session_id": sid, "target": t, "anchors": [a],
                          "positions": {str(a): [0.0, 0.0]}, "mode": "global"})
    assert r.status_code == 200, r.text
    m = r.json()

    truth = synth.truth(t, a)
    best = m["best"]
    assert best is not None
    assert abs(best["x"] - truth[0]) < 2.0, f"x: {best['x']} vs {truth[0]}"
    assert abs(best["y"] - truth[1]) < 2.0, f"y: {best['y']} vs {truth[1]}"
    assert best["ncc"] > 0.5
    assert m["n_anchors"] == 1
    assert m["composite"]["m0"] == [0.0, 0.0]
    assert m["cache_key"]


def test_match_is_a_pure_function_of_its_body_and_memoises_on_it(client, synth):
    """⭐⭐ The prefetch's correctness proof. The memo key **IS** the anchor set, their positions and
    the refusal set — so pressing `E` instead of `A` changes the key, misses the memo, and forces an
    honest recompute. **The trap is structurally impossible to fall into.**"""
    sid = open_session(client, synth.path, synth.trials)["session_id"]
    a, b, t = synth.trials[0], synth.trials[1], synth.trials[2]
    body = {"session_id": sid, "target": t, "anchors": [a, b],
            "positions": {str(a): list(synth.truth(a, a)), str(b): list(synth.truth(b, a))},
            "mode": "global"}

    first = client.post("/api/mosaic/match/anchor", json=body).json()
    again = client.post("/api/mosaic/match/anchor", json=body).json()
    assert again["cached"] is True
    assert again["cache_key"] == first["cache_key"]
    assert again["best"] == first["best"]

    # the ORDER of the anchors must not be able to change the answer (the server sorts)
    shuffled = {**body, "anchors": [b, a]}
    assert client.post("/api/mosaic/match/anchor", json=shuffled).json()["cache_key"] == \
        first["cache_key"]

    # a DIFFERENT refusal set is a different question ⇒ a different key ⇒ an honest recompute
    refused = {**body, "refuse": [b]}
    assert client.post("/api/mosaic/match/anchor", json=refused).json()["cache_key"] != \
        first["cache_key"]


def test_a_blank_ANCHOR_is_dropped_and_is_NOT_fatal(client, synth):
    """🔴 **THE RULE THAT DEAD-ENDED THE WHOLE APP.** Making a blank anchor an error meant that the
    moment the user anchored the first near-threshold frame, every subsequent `Space` refused
    **forever** — and the sweep died one tile later. A blank anchor is dropped from the composite. A
    blank TARGET is refused. **They are not symmetric and must not be made so.**"""
    sid = open_session(client, synth.path, synth.trials)["session_id"]
    a, b, t = synth.trials[0], synth.trials[1], synth.trials[2]

    r = client.post("/api/mosaic/match/anchor",
                    json={"session_id": sid, "target": t, "anchors": [a, b],
                          "positions": {str(a): list(synth.truth(a, a)),
                                        str(b): list(synth.truth(b, a))},
                          "refuse": [b]})                    # b is "blank" -> dropped, not fatal
    assert r.status_code == 200
    m = r.json()
    assert m["dropped_anchors"] == [b]
    assert m["refused"] is None
    assert m["best"] is not None                             # the sweep CARRIES ON


def test_a_blank_TARGET_is_refused_and_there_is_no_force_flag(client, synth):
    """⛔ Two blank frames correlate **+0.43 at zero shift** because what they share is fixed-pattern
    sensor structure, which does not move with the stage. **They register confidently and wrongly.**"""
    sid = open_session(client, synth.path, synth.trials)["session_id"]
    a, t = synth.trials[0], synth.trials[2]

    m = client.post("/api/mosaic/match/anchor",
                    json={"session_id": sid, "target": t, "anchors": [a],
                          "positions": {str(a): [0.0, 0.0]}, "refuse": [t]}).json()
    assert m["refused"]["reason"] == "blank"
    assert m["candidates"] == [] and m["best"] is None

    # there is no force flag, and adding one is a 422
    r = client.post("/api/mosaic/match/anchor",
                    json={"session_id": sid, "target": t, "anchors": [a],
                          "positions": {str(a): [0.0, 0.0]}, "refuse": [t], "force": True})
    assert r.status_code == 422


def test_every_anchor_blank_is_no_anchors(client, synth):
    sid = open_session(client, synth.path, synth.trials)["session_id"]
    a, t = synth.trials[0], synth.trials[1]
    m = client.post("/api/mosaic/match/anchor",
                    json={"session_id": sid, "target": t, "anchors": [a],
                          "positions": {str(a): [0.0, 0.0]}, "refuse": [a]}).json()
    assert m["refused"]["reason"] == "no_anchors"


def test_match_score_says_NOT_MEASURABLE_rather_than_zero(client, synth):
    """⚠️ `ncc` is **null** below `exact_ncc`'s overlap floor. The honest answer is "not measurable" —
    **never `0.0`**, which reads as "measured, and bad"."""
    sid = open_session(client, synth.path, synth.trials)["session_id"]
    a, t = synth.trials[0], synth.trials[1]
    truth = synth.truth(t, a)

    good = client.post("/api/mosaic/match/score",
                       json={"session_id": sid, "target": t, "anchors": [a],
                             "positions": {str(a): [0.0, 0.0]}, "at": list(truth)}).json()
    assert good["ncc"] > 0.5 and good["npix"] > 3000

    far = client.post("/api/mosaic/match/score",
                      json={"session_id": sid, "target": t, "anchors": [a],
                            "positions": {str(a): [0.0, 0.0]}, "at": [9e4, 9e4]}).json()
    assert far["ncc"] is None                                # not 0.0
    assert far["npix"] == 0


def test_local_mode_needs_a_drop_point(client, synth):
    sid = open_session(client, synth.path, synth.trials)["session_id"]
    a, t = synth.trials[0], synth.trials[1]
    r = client.post("/api/mosaic/match/anchor",
                    json={"session_id": sid, "target": t, "anchors": [a],
                          "positions": {str(a): [0.0, 0.0]}, "mode": "local"})
    assert r.status_code == 400
    assert "near" in err(r)["message"]


def test_a_local_snap_pulls_a_dropped_tile_onto_the_truth(client, synth):
    sid = open_session(client, synth.path, synth.trials)["session_id"]
    a, t = synth.trials[0], synth.trials[1]
    tx, ty = synth.truth(t, a)
    m = client.post("/api/mosaic/match/anchor",
                    json={"session_id": sid, "target": t, "anchors": [a],
                          "positions": {str(a): [0.0, 0.0]}, "mode": "local",
                          "near": [tx + 23, ty - 17], "radius": 64}).json()
    assert abs(m["best"]["x"] - tx) < 2.0 and abs(m["best"]["y"] - ty) < 2.0


def test_the_radius_is_clamped_because_the_grid_repeats_every_256_px(client, synth):
    sid = open_session(client, synth.path, synth.trials)["session_id"]
    a, t = synth.trials[0], synth.trials[1]
    r = client.post("/api/mosaic/match/anchor",
                    json={"session_id": sid, "target": t, "anchors": [a],
                          "positions": {str(a): [0.0, 0.0]}, "mode": "local",
                          "near": [0, 0], "radius": 999})
    assert r.status_code == 422


@pytest.mark.parametrize("body,why", [
    ({"anchors": [], "positions": {}}, "non-empty"),
    ({"anchors": [12], "positions": {"12": [0, 0]}}, "must not contain the target"),
    ({"anchors": [11], "positions": {}}, "positions missing"),
])
def test_the_match_preconditions_are_400s_not_500s(client, synth, body, why):
    sid = open_session(client, synth.path, synth.trials)["session_id"]
    r = client.post("/api/mosaic/match/anchor",
                    json={"session_id": sid, "target": 12, **body})
    assert r.status_code == 400
    assert why in err(r)["message"]


# =================================================================================================
# Step 4/6 · seed, provenance, qc, export  (against a fabricated build — see the module docstring)
# =================================================================================================


@pytest.fixture()
def seeded(client, synth):
    """A session, a document, and a finished build in the register. -> `(sid, aid, doc, build_id)`."""
    from camea.features.mosaic import routes as mosaic_routes

    sid = open_session(client, synth.path, synth.trials)["session_id"]
    aid = client.post("/api/projects",
                      json={"session_id": sid, "feature": "mosaic", "name": "seeded",
                            "trials": synth.trials}).json()["analysis_id"]
    doc = client.get(f"/api/analyses/{aid}/document").json()["doc"]

    a0 = synth.trials[0]
    build = {
        "kind": "build",                                     # ⭐ the discriminator tag
        "build_id": "bld_test",
        "created": "2026-07-14T00:00:00Z",
        "method": "t33",
        "trials": list(synth.trials),
        "gaps": [],
        "pass_split": synth.pass_split,
        # the machine's answer, in ITS OWN frame — deliberately offset from the human's
        "positions": {str(t): [synth.truth(t, a0)[0] + 1000.0, synth.truth(t, a0)[1] + 1000.0]
                      for t in synth.trials},
        "n_placed": len(synth.trials),
        "unplaced": [],
        "seconds": 1.0,
        "gpu": False,
        "info": {"seconds": 1.0, "gpu": False, "config": {"pass_split": synth.pass_split,
                                                          "t27": {"conf": 0.62, "span": 340}}},
        "per_tile": {str(t): {"anchor_ncc": None, "anchor_residual_px": None, "run": None,
                              "run_margin": None, "pass": 1 if t <= synth.pass_split else 2}
                     for t in synth.trials},
    }
    mosaic_routes._BUILDS["bld_test"] = build
    return sid, aid, doc, "bld_test"


def test_a_build_result_carries_its_config_even_though_it_NESTS(client, seeded):
    """⚠️ `t33.Config` **nests** — `config["t27"]` is a whole `t27.Config`. `BuildBlock.config` was
    declared `dict[str, scalar]`, which cannot represent it, and the first real seed died with four
    `ResponseValidationError`s. The schema must be able to record what was actually run."""
    _sid, _aid, _doc, bid = seeded
    r = client.get(f"/api/mosaic/builds/{bid}")
    assert r.status_code == 200
    assert r.json()["info"]["config"]["t27"]["conf"] == 0.62


def test_seed_translates_onto_the_HUMANS_frame_and_keeps_his_work(client, synth, seeded):
    """🔴 **A RE-SOLVE MUST NOT DESTROY THE HUMAN'S WORK.** v1 called `setState` unconditionally on
    every non-excluded tile, so a 150-tile sweep with three catastrophic hand corrections in it was
    **wiped** by taking the app's own advice to re-solve — and the autosave then wrote the wiped
    document over the crash-recovery file.

    ⭐ And the translation is a **MEDIAN, not a mean**: a tile the human corrected *because the solver
    was wrong* is precisely an outlier, and one 2,969 px correction would drag a mean into nonsense.
    """
    sid, aid, doc, bid = seeded
    a0 = synth.trials[0]

    # the human has already certified two tiles, in HIS frame, and moved one of them a long way
    keep, moved = synth.trials[0], synth.trials[1]
    doc["tiles"][str(keep)].update({"state": "anchored", "status": "anchor", "x": 0.0, "y": 0.0,
                                    "human": True})
    doc["tiles"][str(moved)].update({"state": "anchored", "status": "anchor",
                                     "x": synth.truth(moved, a0)[0],
                                     "y": synth.truth(moved, a0)[1], "human": True})

    r = client.post("/api/mosaic/seed", json={"doc": doc, "build_id": bid})
    assert r.status_code == 200, r.text
    out = r.json()

    assert out["n_protected"] == 2
    assert out["seed_translation"] == [-1000.0, -1000.0]     # the build slid onto the human's frame

    tiles = out["doc"]["tiles"]
    assert tiles[str(keep)]["x"] == 0.0                      # ⭐ THE HUMAN'S TILE DID NOT MOVE
    assert tiles[str(keep)]["state"] == "anchored"

    other = synth.trials[4]
    assert tiles[str(other)]["state"] == "unverified"        # ⭐ NOT anchored. He has not looked yet.
    assert tiles[str(other)]["x"] == pytest.approx(synth.truth(other, a0)[0], abs=0.01)
    assert tiles[str(other)]["machine"] is not None


def test_seed_REFUSES_rather_than_guess_a_translation(client, seeded):
    """If none of the human's tiles are in the build, the two frames cannot be tied together. The
    server refuses. **Guessing would slide his whole field.**"""
    sid, aid, doc, bid = seeded
    from camea.features.mosaic import routes as mosaic_routes

    mosaic_routes._BUILDS[bid]["positions"] = {}             # a build that placed nothing he holds
    doc["tiles"]["11"].update({"state": "anchored", "status": "anchor", "x": 5.0, "y": 5.0,
                               "human": True})
    r = client.post("/api/mosaic/seed", json={"doc": doc, "build_id": bid})
    assert r.status_code == 409
    assert err(r)["code"] == "refused"


def test_machine_evidence_is_derived_from_HISTORY_not_self_declaration(client, seeded):
    """🔴 **This project has already destroyed one benchmark exactly this way.** `seeded_from` is
    writable, and "Skip — place from scratch" once *erased it* while every tile kept t33's answer."""
    sid, aid, doc, bid = seeded
    seeded_doc = client.post("/api/mosaic/seed",
                             json={"doc": {**doc, "tiles": _anchor_one(doc)}, "build_id": bid}
                             ).json()["doc"]

    # the document LIES about itself
    seeded_doc["provenance"]["seeded_from"] = None
    seeded_doc["provenance"]["independent_of_method"] = True
    seeded_doc["provenance"].pop("warning", None)

    ev = client.post("/api/mosaic/document/machine-evidence", json={"doc": seeded_doc}).json()
    assert ev["independent_of_method"] is False              # ⭐ the HISTORY wins
    assert ev["has_build"] is True
    assert ev["n_machine_tiles"] > 0
    assert ev["warning"].startswith("NOT AN INDEPENDENT GROUND TRUTH")


def test_discard_machine_is_DESTRUCTIVE_or_it_is_nothing(client, seeded):
    """🔴 v1 nulled `build`, nulled `seeded_from`, set `independent_of_method: true`, deleted the
    warning — and **did not touch a single tile.** Every tile kept t33's position. Score t33 against
    that and it gets ~100 % **by construction.**"""
    sid, aid, doc, bid = seeded
    seeded_doc = client.post("/api/mosaic/seed",
                             json={"doc": {**doc, "tiles": _anchor_one(doc)}, "build_id": bid}
                             ).json()["doc"]

    r = client.post("/api/mosaic/document/discard-machine",
                    json={"doc": seeded_doc, "confirm": True})
    assert r.status_code == 200
    out = r.json()
    assert out["had_build"] is True and out["n_positions_discarded"] > 0

    # EVERY position is gone, and so is the build.
    for t in out["doc"]["tiles"].values():
        assert t["x"] is None and t["y"] is None
        assert t["state"] == "unplaced"
        assert t.get("machine") is None
    assert out["doc"]["build"] is None

    ev = client.post("/api/mosaic/document/machine-evidence", json={"doc": out["doc"]}).json()
    assert ev["independent_of_method"] is True and ev["warning"] is None


def test_discard_machine_cannot_be_reached_by_accident(client, seeded):
    sid, aid, doc, bid = seeded
    assert client.post("/api/mosaic/document/discard-machine",
                       json={"doc": doc, "confirm": False}).status_code == 422


def test_qc_states_its_denominator(client, synth, seeded):
    """⭐ **EVERY NUMBER STATES ITS DENOMINATOR** — and the denominator is the document's own excluded
    set, and nothing else. The app has no list of its own. (A percentage without one is how the
    182-vs-156 confusion started.)"""
    sid, aid, doc, bid = seeded
    doc["tiles"][str(synth.trials[3])].update({"state": "excluded", "status": "excluded"})

    r = client.post("/api/mosaic/qc", json={"doc": doc})
    assert r.status_code == 200
    qc = r.json()
    d = qc["denominator"]
    assert d["trials_in_document"] == len(synth.trials)
    assert d["excluded"] == 1
    assert d["not_excluded"] == len(synth.trials) - 1
    assert "usable_trials" not in str(qc)                    # ⛔ renamed on purpose. See the schema.


def test_export_writes_the_seven_files_and_the_coverage_mask_is_MANDATORY(client, synth, seeded):
    """⚠️⚠️ 13.1 % of the canvas is background encoded as exactly `0.0`, indistinguishable from a
    legitimately black pixel — and a TIFF has **no alpha channel**. Without the sidecar, "empty" and
    "black" merge forever. **Asking for `tiff` implies `coverage`.**

    ⭐ **AND IT LANDS IN THE PROJECT'S `outputs/` (R44)** — there is no `dir` on the wire, because
    the user is not asked where an export goes. He browses and copies out what he wants afterwards.
    """
    sid, aid, doc, bid = seeded
    a0 = synth.trials[0]
    for t in synth.trials[:6]:
        doc["tiles"][str(t)].update({"state": "anchored", "status": "anchor",
                                     "x": synth.truth(t, a0)[0], "y": synth.truth(t, a0)[1],
                                     "human": True})

    r = client.post("/api/mosaic/export",
                    json={"session_id": sid, "basename": "m", "doc": doc,
                          "outputs": ["tiff", "png", "positions", "gt", "qc"],
                          "render_mode": "feather"})
    assert r.status_code == 202, r.text
    job = run_job(client, r.json()["job_id"])
    assert job["result"]["kind"] == "export"

    kinds = {f["kind"] for f in job["result"]["files"]}
    assert "coverage" in kinds, "the coverage mask is not optional"
    assert {"tiff", "png", "positions", "gt", "qc"} <= kinds
    assert all(f["bytes"] > 0 for f in job["result"]["files"])

    out = Path(client.get(f"/api/projects/{aid}").json()["folder"]) / "outputs"
    csv = (out / "m_positions.csv").read_text().splitlines()
    assert csv[0] == "trial,x,y,state"                       # score.load_positions DictReads these

    # ⭐ …and the outputs browser lists exactly what the job says it wrote (R44). This is the whole
    # promise of the panel: what is on the card is what is on disk.
    listed = {o["name"] for o in client.get(f"/api/projects/{aid}/outputs").json()["outputs"]}
    assert listed == {Path(f["path"]).name for f in job["result"]["files"]}


def test_an_export_CANNOT_NAME_A_FOLDER_AT_ALL(client, synth, seeded):
    """⛔ **R44 removed `dir` from the contract**, so the old "export into the dataset" refusal has
    nothing left to refuse: there is no way to ask for it. `Req` is `extra="forbid"`, so a client
    that still sends one is a 422 rather than a silent write somewhere nobody expects."""
    sid, aid, doc, bid = seeded
    props = client.get("/openapi.json").json()["components"]["schemas"]["ExportRequest"]
    assert "dir" not in props["properties"]

    r = client.post("/api/mosaic/export",
                    json={"session_id": sid, "dir": str(synth.path / "out"), "basename": "m",
                          "doc": doc})
    assert r.status_code == 422


def test_recheck_is_GLOBAL_and_is_allowed_to_say_no(client, synth, seeded):
    """🔴 It **never moves a tile** — it only measures it. v1 fired a *local* match (±64 px) and then
    cleared `stale` unconditionally — but a tile knocked off by a moved anchor is off by **hundreds**
    of px, so a ±64 px window is structurally blind to the one error the panel exists for."""
    sid, aid, doc, bid = seeded
    a0 = synth.trials[0]
    for t in synth.trials[:4]:                               # a certified anchor field
        doc["tiles"][str(t)].update({"state": "anchored", "status": "anchor",
                                     "x": synth.truth(t, a0)[0], "y": synth.truth(t, a0)[1],
                                     "human": True})
    victim = synth.trials[5]                                 # unverified, and 400 px WRONG
    doc["tiles"][str(victim)].update({"state": "unverified", "status": "unverified",
                                      "x": synth.truth(victim, a0)[0] + 400.0,
                                      "y": synth.truth(victim, a0)[1] + 400.0, "stale": True})

    r = client.post("/api/mosaic/recheck",
                    json={"session_id": sid, "doc": doc, "trials": [victim], "tolerance_px": 5.0})
    assert r.status_code == 202
    res = run_job(client, r.json()["job_id"])["result"]
    assert res["kind"] == "recheck"
    assert res["n_checked"] == 1
    assert res["cleared"] == []                              # ⭐ IT SAID NO.
    row = res["disagree"][0]
    assert row["trial"] == victim
    assert row["still_stale"] is True
    assert row["disagree_px"] > 100                          # a LOCAL window would never have seen it


def test_recheck_with_nothing_anchored_is_refused(client, seeded):
    sid, aid, doc, bid = seeded
    r = client.post("/api/mosaic/recheck", json={"session_id": sid, "doc": doc})
    assert r.status_code == 409
    assert err(r)["code"] == "refused"


def test_recompute_re_places_a_tile_against_the_frozen_anchor_field(client, synth, seeded):
    """⭐ RECOMPUTE = recheck's per-target `match_anchor` loop, but it WRITES: it re-places every
    non-anchored tile against the frozen anchor composite (`unverified` + `machine`), and NEVER touches
    an `anchored`/`human` tile. A machine placed it, so the reply is stamped non-independent."""
    sid, aid, doc, bid = seeded
    a0 = synth.trials[0]
    anchors = list(synth.trials[:4])                        # a certified anchor field, at the truth
    for t in anchors:
        doc["tiles"][str(t)].update({"state": "anchored", "status": "anchor",
                                     "x": synth.truth(t, a0)[0], "y": synth.truth(t, a0)[1],
                                     "human": True})
    victim = synth.trials[5]                                 # unverified, planted 400 px WRONG
    doc["tiles"][str(victim)].update({"state": "unverified", "status": "unverified",
                                      "x": synth.truth(victim, a0)[0] + 400.0,
                                      "y": synth.truth(victim, a0)[1] + 400.0})
    anchor_xy = (doc["tiles"][str(anchors[0])]["x"], doc["tiles"][str(anchors[0])]["y"])

    r = client.post("/api/mosaic/recompute",
                    json={"session_id": sid, "doc": doc, "trials": [victim]})
    assert r.status_code == 202
    res = run_job(client, r.json()["job_id"])["result"]
    assert res["kind"] == "recompute"
    assert res["n_reference"] == len(anchors)
    assert res["n_placed"] == 1
    new = res["doc"]

    # the anchored tile is the FROZEN reference — untouched, still anchored, same position.
    a = new["tiles"][str(anchors[0])]
    assert a["state"] == "anchored"
    assert (a["x"], a["y"]) == anchor_xy

    # the victim was re-placed against the anchors: unverified, carrying `machine`, back near the truth.
    v = new["tiles"][str(victim)]
    assert v["state"] == "unverified"
    assert v.get("machine") is not None
    err_px = math.hypot(v["x"] - synth.truth(victim, a0)[0], v["y"] - synth.truth(victim, a0)[1])
    assert err_px < 10.0                                     # a 400 px error, snapped back onto the truth

    # a machine touched it -> the response is stamped, and can never claim to be an independent truth.
    assert new["provenance"]["independent_of_method"] is False


def test_recompute_with_nothing_anchored_is_refused(client, seeded):
    """Nothing anchored ⇒ there is no ground truth to place the rest against. Refused, not guessed."""
    sid, aid, doc, bid = seeded
    r = client.post("/api/mosaic/recompute", json={"session_id": sid, "doc": doc})
    assert r.status_code == 409
    assert err(r)["code"] == "refused"


def _anchor_one(doc: dict) -> dict:
    """Give the human one certified tile, so `seed` has something to tie the frames together with."""
    tiles = {k: dict(v) for k, v in doc["tiles"].items()}
    first = sorted(tiles, key=int)[0]
    tiles[first].update({"state": "anchored", "status": "anchor", "x": 0.0, "y": 0.0, "human": True})
    return tiles
