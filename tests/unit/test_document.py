"""The generic analysis document: the envelope, the provenance rule, and the round-trip.

⭐ **THE POINT OF THIS FILE.** `core.document` must not know what a tile is. So every test here drives
it through a *fake* feature — two of them: one mosaic-shaped, and one (`segmentation`) that has no
tiles at all and implements exactly one hook. If a change to core makes the second one impossible,
core has grown feature knowledge and the split has failed.

The tests that are not negotiable:
  * `test_a_document_cannot_launder_itself` — the one that guards the destroyed benchmark.
  * `test_provenance_warning_is_verbatim`   — the text is the artefact.
  * `test_unknown_keys_survive_a_round_trip` — a saved document is also somebody's ground truth.
  * `test_no_trial_number_is_special`       — the guard that once made his own session unsaveable.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from camea.core import document as D

# =================================================================================================
# Two fake features. Core must never be able to tell them apart.
# =================================================================================================


class FakeMosaic:
    """Mosaic-shaped: tiles, a build, a trial range. Implements every hook."""

    name = "fake_mosaic"

    # ---- the one hook that is not optional -------------------------------------------------------
    def machine_evidence(self, doc: dict) -> dict | None:
        build = doc.get("build")
        if isinstance(build, dict) and build:
            return {"method": build.get("method", "t33"), "build_id": build.get("build_id"),
                    "config": {}, "detected_from": "doc['build'] — the build block is still here"}
        machine = sorted(int(k) for k, v in (doc.get("tiles") or {}).items()
                         if isinstance(v, dict) and v.get("machine"))
        if machine:
            return {"method": "unknown (a machine build)", "build_id": None, "config": {},
                    "detected_from": f"{len(machine)} tile(s) still carry a `machine` position"}
        return None

    # ---- optional ---------------------------------------------------------------------------------
    def normalise(self, doc: dict) -> dict:
        tiles = doc.get("tiles") or {}
        doc["unusable_tiles"] = sorted(int(k) for k, v in tiles.items()
                                       if v.get("state") == "excluded")
        return doc

    def validate(self, doc: dict) -> list[tuple[str, str]]:
        tiles = doc.get("tiles")
        if not isinstance(tiles, dict):
            return [("hard", "tiles must be an object keyed by trial number")]
        want = sorted(int(k) for k, v in tiles.items() if v.get("state") == "excluded")
        if [int(t) for t in (doc.get("unusable_tiles") or [])] != want:
            return [("derived", f"unusable_tiles should be {want}")]
        return []

    def migrate(self, doc: dict) -> tuple[dict, list[str]]:
        doc.setdefault("unusable_tiles", [])
        return doc, []

    def human_edits(self, doc: dict) -> dict:
        tiles = doc.get("tiles") or {}
        return {"excluded": sum(1 for v in tiles.values() if v.get("state") == "excluded"),
                "anchored": sum(1 for v in tiles.values() if v.get("state") == "anchored")}

    def identity(self, doc: dict) -> str:
        lo, hi = doc.get("trial_range") or [0, 0]
        return f"{lo}-{hi}"

    def counts(self, doc: dict) -> dict:
        return {"n_tiles": len(doc.get("tiles") or {})}

    def new_payload(self, doc: dict, *, trials=(), **_kw) -> dict:
        trials = [int(t) for t in trials]
        doc["tiles"] = {str(t): {"state": "unplaced", "status": "unplaced", "x": None, "y": None}
                        for t in trials}
        doc["trial_range"] = [trials[0], trials[-1]] if trials else [0, 0]
        doc["tolerance_px"] = {"anchor": 96, "region_default": 256, "grading": 10}
        doc["unusable_tiles"] = []
        return doc


class FakeSegmentation:
    """⭐ A feature with **no tiles, no range, no geometry** — one hook and nothing else.

    It exists to prove core is feature-agnostic. Every optional hook it does *not* implement is a
    thing core must not require.
    """

    def machine_evidence(self, doc: dict) -> dict | None:
        if doc.get("masks_from_model"):
            return {"method": "segnet-v2", "detected_from": "doc['masks_from_model']"}
        return None


@pytest.fixture
def mosaic():
    """Register `fake_mosaic`, and put BOTH registries back afterwards."""
    yield from _registered("fake_mosaic", FakeMosaic())


@pytest.fixture
def seg():
    yield from _registered("fake_segmentation", FakeSegmentation())


def _registered(name: str, hooks):
    from camea.core import workspace as W

    before_d = dict(D._FEATURES)
    before_w = dict(W._FEATURES)
    D.register_feature(name, hooks)
    try:
        yield hooks
    finally:
        D._FEATURES.clear()
        D._FEATURES.update(before_d)
        W._FEATURES.clear()
        W._FEATURES.update(before_w)


def a_doc(hooks=None, **kw) -> dict:
    kw.setdefault("feature", "fake_mosaic")
    kw.setdefault("dataset", "260620d")
    kw.setdefault("dataset_key", "260620d-abc123")
    kw.setdefault("data_dir", "D:/data/260620d")
    kw.setdefault("trials", [11, 12, 13])
    return D.new_document(hooks=hooks, **kw)


# =================================================================================================
# ⭐ THE PROVENANCE RULE.  This is the file's reason to exist.
# =================================================================================================


def test_provenance_warning_is_verbatim():
    """The text IS the artefact. A paraphrase is a different claim, and a future reader of a stray
    JSON file has nothing but these words to go on."""
    assert D.PROVENANCE_WARNING == (
        "NOT AN INDEPENDENT GROUND TRUTH. Every position here started as a machine build's output "
        "and was confirmed or corrected by a human who could see it. It MUST NEVER be used to score "
        "that method or any method derived from it — the score would be 100 % by construction. This "
        "project has already destroyed one benchmark exactly this way.")


def test_a_hand_placed_document_is_independent_and_carries_no_warning(mosaic):
    doc = a_doc(mosaic)
    assert doc["provenance"]["independent_of_method"] is True
    assert doc["provenance"]["seeded_from"] is None
    assert "warning" not in doc["provenance"]           # a warning that cries wolf is never read
    assert doc["provenance"]["workflow"] == D.WORKFLOW_HAND
    assert D.validate(doc, mosaic) == []


def test_a_build_block_makes_the_document_non_independent(mosaic):
    doc = a_doc(mosaic)
    doc["build"] = {"build_id": "b1", "method": "t33"}

    out = D.stamp(doc, mosaic)
    assert out["provenance"]["independent_of_method"] is False
    assert out["provenance"]["warning"] == D.PROVENANCE_WARNING
    assert out["provenance"]["seeded_from"]["method"] == "t33"
    assert out["provenance"]["workflow"] == D.WORKFLOW_SEEDED


def test_a_single_machine_position_is_enough(mosaic):
    """One tile still carrying the solver's answer is machine evidence. There is no threshold."""
    doc = a_doc(mosaic)
    doc["tiles"]["12"]["machine"] = [10.0, 20.0]

    out = D.stamp(doc, mosaic)
    assert out["provenance"]["independent_of_method"] is False
    assert out["provenance"]["warning"] == D.PROVENANCE_WARNING
    assert "1 tile(s) still carry" in out["provenance"]["seeded_from"]["detected_from"]


def test_a_document_cannot_launder_itself(mosaic):
    """🔴 **THE REGRESSION TEST FOR THE DESTROYED BENCHMARK.**

    v1's *"Skip — place from scratch"* nulled the build, nulled `seeded_from`, set
    `independent_of_method: true` and deleted the warning — **without touching a single tile.** Every
    tile kept the solver's position. Score the solver against that and it gets ~100 % by construction.

    The verdict is derived from the HISTORY. A document that lies about itself is corrected, and it is
    also *reported* — a laundered file that merely gets fixed on the way out would still have been
    handed to a scorer on the way in.
    """
    laundered = a_doc(mosaic)
    laundered["tiles"]["11"]["machine"] = [0.0, 0.0]     # the fingerprint the button did not erase
    laundered["provenance"]["seeded_from"] = None        # ... while the block claims innocence
    laundered["provenance"]["independent_of_method"] = True
    laundered["provenance"].pop("warning", None)

    problems = D.validate(laundered, mosaic)
    assert any("machine-seeded" in p for p in problems)
    assert any("BY CONSTRUCTION" in p for p in problems)

    out = D.stamp(laundered, mosaic)
    assert out["provenance"]["independent_of_method"] is False
    assert out["provenance"]["warning"] == D.PROVENANCE_WARNING


def test_a_document_cannot_cry_wolf_either(mosaic):
    """The mirror image: a warning on a document with nothing machine-made in it is *also* wrong.
    A warning nobody can act on is a warning everybody learns to ignore."""
    doc = a_doc(mosaic)
    doc["provenance"]["warning"] = D.PROVENANCE_WARNING
    doc["provenance"]["independent_of_method"] = False

    assert any("must be OMITTED" in p for p in D.validate(doc, mosaic))
    out = D.stamp(doc, mosaic)
    assert out["provenance"]["independent_of_method"] is True
    assert "warning" not in out["provenance"]


def test_a_feature_without_machine_evidence_cannot_register():
    """Fail closed. A missing hook would imply "independent", which is the single most expensive wrong
    answer in this project's history."""
    class NoHook:
        pass

    with pytest.raises(D.DocumentError, match="machine_evidence"):
        D.register_feature("broken", NoHook())


def test_an_unregistered_feature_fails_closed():
    doc = {"feature": "nobody_registered_this", "dataset": "x", "tiles": {}}
    with pytest.raises(D.UnknownFeature):
        D.stamp(doc)


# =================================================================================================
# ⭐ CORE IS FEATURE-AGNOSTIC
# =================================================================================================


def test_a_feature_with_no_tiles_at_all_works(seg):
    """`FakeSegmentation` implements ONE hook and has no tiles, no range and no geometry. If this
    ever needs more, core has grown feature knowledge."""
    doc = D.new_envelope(feature="fake_segmentation", dataset="260620d")
    doc["masks"] = {"11": "blob"}                        # its payload. Core has never heard of it.

    out = D.stamp(D.normalise(doc, seg), seg)
    assert D.validate(out, seg) == []
    assert out["provenance"]["independent_of_method"] is True
    assert out["masks"] == {"11": "blob"}

    out["masks_from_model"] = True                       # ... now a machine touched it
    out = D.stamp(out, seg)
    assert out["provenance"]["independent_of_method"] is False
    assert out["provenance"]["warning"] == D.PROVENANCE_WARNING


def test_core_holds_no_dataset_knowledge():
    """⛔ **THE APP CARRIES NO DATASET KNOWLEDGE.**

    Checked against the **executable code**, with the comments and docstrings stripped: the prose is
    allowed — required, even — to cite the history that justifies these rules (the benchmark this
    project destroyed is named in `machine_evidence`, and that citation is the evidence for the single
    most important rule in the file). What may not exist is a *line that runs* and knows a dataset.

    The four symbols are forbidden outright, in prose too: they are the exclusion module's, `gaps()`
    is the only thing the app may ever import from it, and there is no toggle.
    """
    import ast

    src = Path(D.__file__).read_text(encoding="utf-8")
    for forbidden in ("EXCLUDED", "BLURRY", "usable_trials"):
        assert forbidden not in src, f"core/document.py names {forbidden!r} — it must not"

    tree = ast.parse(src)
    for node in ast.walk(tree):                          # drop every docstring, keep every statement
        body = getattr(node, "body", None)
        if (isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str)):
            body.pop(0)
    code = ast.unparse(tree)                             # ast.unparse drops comments outright

    for forbidden in ("260620", "excluded", "blank", "blurry", "trial"):
        assert forbidden not in code.lower(), (
            f"core/document.py has {forbidden!r} in code it RUNS. Core knows nothing about a dataset, "
            f"a trial number, or an exclusion — those are the mosaic feature's, and they live in the "
            f"document the user loaded.")


def test_no_trial_number_is_special(mosaic, tmp_path):
    """⛔ The guard that used to live in v1's validator ("tile 284 is THROWN OUT and carries a
    position") made the user's own session **unsaveable** the moment he anchored 284."""
    doc = a_doc(mosaic, trials=[283, 284, 285])
    doc["tiles"]["284"].update(state="anchored", status="anchor", x=0.0, y=0.0)

    assert D.validate(doc, mosaic) == []
    res = D.save(tmp_path / "p.camea.json", doc, mosaic)
    assert res["bytes"] > 0


# =================================================================================================
# THE ENVELOPE, THE PAYLOAD, AND THE ROUND-TRIP
# =================================================================================================


def test_the_payload_is_flat_and_the_scorer_can_read_it(mosaic, tmp_path):
    """⛔ `{..., "payload": {...}}` is FORBIDDEN. `benchmark/score.py :: load_gt()` reads
    `doc["tiles"][k]["status"]` and `doc["tolerance_px"]["region_default"]` at the TOP level, and a
    project the scorer cannot read is a project that cannot be checked."""
    doc = a_doc(mosaic)
    doc["tiles"]["11"].update(state="anchored", status="anchor", x=0.0, y=0.0)

    path = tmp_path / "p.camea.json"
    D.save(path, doc, mosaic)
    raw = json.loads(path.read_text(encoding="utf-8"))

    assert "payload" not in raw
    assert raw["tiles"]["11"]["status"] == "anchor"      # exactly what load_gt() reads
    assert raw["tolerance_px"]["region_default"] == 256
    assert raw["feature"] == "fake_mosaic"               # routing lives in a key, not in a nesting


def test_unknown_keys_survive_a_round_trip(mosaic, tmp_path):
    """⚠️ A saved document is also somebody's ground truth and may carry a hand-written note. A lossy
    round-trip destroys it — and core has never heard of most of what is in the file."""
    doc = a_doc(mosaic)
    doc["a_hand_written_note"] = "trial 12 is out of focus but usable — PL, 2026-07-14"
    doc["tiles"]["12"]["some_future_key"] = {"deep": [1, 2, {"deeper": True}]}

    path = tmp_path / "p.camea.json"
    D.save(path, doc, mosaic)
    back, _ = D.load(path, mosaic)

    assert back["a_hand_written_note"] == doc["a_hand_written_note"]
    assert back["tiles"]["12"]["some_future_key"] == {"deep": [1, 2, {"deeper": True}]}


def test_save_then_load_restores_the_session(mosaic, tmp_path):
    """R2.6 — save, kill the app, load: exclusions, placements and the cursor all come back. Since the
    app carries no dataset knowledge, this file is its ONLY memory."""
    doc = a_doc(mosaic)
    doc["tiles"]["11"].update(state="anchored", status="anchor", x=0.0, y=0.0)
    doc["tiles"]["13"].update(state="excluded", status="excluded")
    doc["cursor"] = 12

    path = tmp_path / "p.camea.json"
    D.save(path, doc, mosaic)
    back, warnings = D.load(path, mosaic)

    assert back["tiles"]["11"]["status"] == "anchor"
    assert back["tiles"]["13"]["state"] == "excluded"
    assert back["cursor"] == 12
    assert back["unusable_tiles"] == [13]                # derived, and repaired by normalise
    assert back["id"] == doc["id"]                       # the id is stable across a round-trip
    assert warnings == []


def test_the_id_and_created_are_stable_across_saves(mosaic, tmp_path):
    doc = a_doc(mosaic)
    first = D.save(tmp_path / "p.camea.json", doc, mosaic)["doc"]
    second = D.save(tmp_path / "p.camea.json", first, mosaic)["doc"]

    assert second["id"] == first["id"] == doc["id"]
    assert second["created"] == first["created"]


# =================================================================================================
# THE SAVE ORDER
# =================================================================================================


def test_save_normalises_before_it_validates(mosaic, tmp_path):
    """⚠️ **THE ORDER IS THE POINT.** The derived fields are *exactly* the ones that drift the moment
    the user excludes a record — and `normalise()` is what repairs them. `validate -> normalise` would
    reject a perfectly good document for drift the very next line of code fixes."""
    doc = a_doc(mosaic)
    doc["tiles"]["13"].update(state="excluded", status="excluded")
    assert doc["unusable_tiles"] == []                   # drifted: `13` is excluded and not listed
    assert D.validate(doc, mosaic)                       # ... and validate says so

    res = D.save(tmp_path / "p.camea.json", doc, mosaic)  # ... and the save succeeds anyway
    assert res["doc"]["unusable_tiles"] == [13]


def test_a_structurally_broken_document_is_refused(mosaic, tmp_path):
    """`normalise()` cannot invent a `tiles` object. A hard problem refuses the write."""
    doc = a_doc(mosaic)
    doc["tiles"] = "not an object"

    with pytest.raises(D.ValidationError) as e:
        D.save(tmp_path / "p.camea.json", doc, mosaic)
    assert "tiles" in str(e.value)
    assert not (tmp_path / "p.camea.json").exists()      # never write a broken file


def test_an_unknown_problem_kind_from_a_feature_is_a_bug(mosaic):
    class Sloppy(FakeMosaic):
        def validate(self, doc):
            return [("catastrophic", "oh no")]

    with pytest.raises(D.DocumentError, match="unknown problem kind"):
        D.validate(a_doc(mosaic), Sloppy())


# =================================================================================================
# THE SCOPE GUARD — "pass 2's autosave silently overwrote pass 1's ground-truth records"
# =================================================================================================


def test_loading_a_document_for_another_range_is_refused(mosaic, tmp_path):
    doc = a_doc(mosaic, trials=[11, 12, 13])
    path = tmp_path / "p.camea.json"
    D.save(path, doc, mosaic)

    pass2 = D.Scope(dataset="260620d", dataset_key="260620d-abc123", identity="167-348")
    with pytest.raises(D.RangeMismatch, match="11-13"):
        D.load(path, mosaic, expect=pass2)

    same = D.Scope(dataset="260620d", dataset_key="260620d-abc123", identity="11-13")
    back, _ = D.load(path, mosaic, expect=same)          # the right scope opens fine
    assert back["trial_range"] == [11, 13]


def test_loading_a_document_for_another_dataset_is_refused(mosaic, tmp_path):
    path = tmp_path / "p.camea.json"
    D.save(path, a_doc(mosaic), mosaic)

    other = D.Scope(dataset="260621a", dataset_key="260621a-zzz999")
    with pytest.raises(D.RangeMismatch):
        D.load(path, mosaic, expect=other)


def test_a_blank_scope_field_abstains():
    """A document that predates a field must still open. A guard that fires on a missing field is a
    guard the user learns to route around."""
    old = D.Scope(dataset="260620d")                     # no key, no identity
    now = D.Scope(dataset="260620d", dataset_key="260620d-abc123", identity="11-348")
    assert old.agrees_with(now) and now.agrees_with(old)

    assert not D.Scope(dataset_key="a").agrees_with(D.Scope(dataset_key="b"))
    assert not D.Scope(identity="11-166").agrees_with(D.Scope(identity="167-348"))


# =================================================================================================
# MIGRATION — a v1 project file, and a ground truth that predates the app
# =================================================================================================


def test_a_v1_project_file_opens(mosaic, tmp_path):
    """v1 wrote `camea-project-1.0` and had no `feature` key — there was only one feature. It must
    open, and it must not lose a key on the way."""
    v1 = {
        "schema_version": "camea-project-1.0",
        "dataset": "260620d",
        "trial_range": [11, 13],
        "tolerance_px": {"anchor": 96, "region_default": 256, "grading": 10},
        "tiles": {"11": {"state": "anchored", "status": "anchor", "x": 0.0, "y": 0.0},
                  "12": {"state": "unplaced", "status": "unplaced"}},
        "unusable_tiles": [],
        "a_key_core_has_never_heard_of": 42,
    }
    path = tmp_path / "old.camea.json"
    path.write_text(json.dumps(v1), encoding="utf-8")

    doc, warnings = D.load(path, mosaic)
    assert doc["feature"] == D.LEGACY_FEATURE
    assert doc["schema_version"] == D.SCHEMA_VERSION
    assert doc["id"]                                     # minted, and stable from now on
    assert doc["a_key_core_has_never_heard_of"] == 42
    assert any("camea-project-1.0" in w for w in warnings)
    assert any("predates the split" in w for w in warnings)


def test_a_ground_truth_with_no_schema_version_opens(mosaic, tmp_path):
    """The hand-authored ground truths predate the app entirely: no `schema_version`, no `feature`,
    no `provenance`. Refusing to open one would make the answer key unreadable to the app that is
    scored against it."""
    gt = {"dataset": "260620d",
          "tiles": {"11": {"status": "anchor", "x": 0.0, "y": 0.0, "state": "anchored"}},
          "tolerance_px": {"region_default": 256}}
    path = tmp_path / "gt.json"
    path.write_text(json.dumps(gt), encoding="utf-8")

    doc, warnings = D.load(path, mosaic)
    assert doc["feature"] == D.LEGACY_FEATURE
    assert doc["provenance"]["independent_of_method"] is True   # nothing machine-made in it
    assert any("no provenance block" in w for w in warnings)


def test_a_seeded_v1_file_is_still_seeded_after_migration(mosaic, tmp_path):
    """⭐ Migration must not launder. A v1 file whose tiles carry the solver's answer comes out the
    other side still saying so."""
    v1 = {"schema_version": "camea-project-1.0", "dataset": "260620d",
          "tiles": {"11": {"state": "anchored", "status": "anchor", "x": 0.0, "y": 0.0,
                           "machine": [0.0, 0.0]}},
          "unusable_tiles": []}
    path = tmp_path / "old.camea.json"
    path.write_text(json.dumps(v1), encoding="utf-8")

    doc, _ = D.load(path, mosaic)
    out = D.stamp(doc, mosaic)
    assert out["provenance"]["independent_of_method"] is False
    assert out["provenance"]["warning"] == D.PROVENANCE_WARNING


def test_a_random_json_object_is_not_a_camea_document(mosaic, tmp_path):
    """Refusing to guess: a payload routed to the wrong feature's hooks is worse than a 400."""
    path = tmp_path / "shopping.json"
    path.write_text(json.dumps({"milk": 2, "eggs": 6}), encoding="utf-8")

    with pytest.raises(D.DocumentError, match="Refusing to guess"):
        D.load(path, mosaic)


# =================================================================================================
# THE WORKSPACE — save / autosave into an analysis
# =================================================================================================


@pytest.fixture
def ws(tmp_path, monkeypatch):
    from camea.core.workspace import Workspace

    monkeypatch.setenv("CAMEA_STATE_DIR", str(tmp_path / "state"))
    return Workspace.open(tmp_path / "workspace")


def test_a_document_is_saved_into_its_analysis(mosaic, ws):
    a = ws.create_analysis(feature="fake_mosaic", name="pass 1",
                           dataset_key="260620d-abc123", dataset="260620d")
    doc = a_doc(mosaic, id=a.analysis_id)                # ⭐ the id IS the analysis id

    res = D.save_analysis(ws, a.analysis_id, doc, mosaic)
    assert json.loads(ws.document_path(a.analysis_id).read_text(encoding="utf-8"))["id"] == \
        a.analysis_id
    assert res["doc"]["id"] == a.analysis_id

    back, _ = D.load_analysis(ws, a.analysis_id, mosaic)
    assert back["tiles"].keys() == {"11", "12", "13"}


def test_a_document_cannot_be_written_into_another_analysis(mosaic, ws):
    """🔴 The slot guard (`workspace._guard_slot`). Pass 2's autosave once silently overwrote pass 1's
    ground-truth records. It is not merged, not renamed, not "repaired" — it is refused.

    Two ranges of one dataset are two analyses, so the v1 collision cannot even arise; this is the
    belt to that braces."""
    from camea.core.workspace import SlotMismatch

    one = ws.create_analysis(feature="fake_mosaic", name="pass 1",
                             dataset_key="260620d-abc123", dataset="260620d")
    two = ws.create_analysis(feature="fake_mosaic", name="pass 2",
                             dataset_key="260620d-abc123", dataset="260620d")
    doc = a_doc(mosaic, id=one.analysis_id)

    with pytest.raises(SlotMismatch, match=one.analysis_id):
        D.save_analysis(ws, two.analysis_id, doc, mosaic)


def test_a_document_for_another_dataset_cannot_enter_this_analysis(mosaic, ws):
    """The other half of the slot guard: the right id, the wrong dataset."""
    from camea.core.workspace import SlotMismatch

    a = ws.create_analysis(feature="fake_mosaic", name="pass 1",
                           dataset_key="260621a-zzz", dataset="260621a")
    doc = a_doc(mosaic, id=a.analysis_id)                # carries dataset_key 260620d-abc123

    with pytest.raises(SlotMismatch):
        D.save_analysis(ws, a.analysis_id, doc, mosaic)


def test_the_autosave_lands_beside_the_document_and_is_stamped(mosaic, ws):
    """⚠️ The crash net is not the document, and it is never written over it — recovery must be able
    to show the user both. And it is STAMPED: an unstamped autosave is an unmarked machine-seeded
    document sitting on disk."""
    a = ws.create_analysis(feature="fake_mosaic", name="pass 1",
                           dataset_key="260620d-abc123", dataset="260620d")
    doc = a_doc(mosaic, id=a.analysis_id)
    doc["build"] = {"build_id": "b1", "method": "t33"}   # a machine touched it

    D.autosave(ws, a.analysis_id, doc, mosaic)

    assert not ws.document_path(a.analysis_id).exists()  # the crash net is not the save
    saved = json.loads(ws.autosave_path(a.analysis_id).read_text(encoding="utf-8"))
    assert saved["provenance"]["independent_of_method"] is False
    assert saved["provenance"]["warning"] == D.PROVENANCE_WARNING

    rec = ws.recovery(a.analysis_id)
    assert rec and rec["newer"] is True


def test_saving_into_the_dataset_is_refused(mosaic, tmp_path):
    """⛔ A DATASET IS RAW AND IS NEVER WRITTEN TO."""
    from camea.core.dataset import DatasetIsReadOnly

    ds = tmp_path / "260620d"
    ds.mkdir()
    (ds / "log.txt").write_text("New experiment: 260620d\n", encoding="utf-8")
    (ds / "011.xml").write_text("<x/>", encoding="utf-8")

    with pytest.raises(DatasetIsReadOnly):
        D.save(ds / "sneaky.camea.json", a_doc(mosaic), mosaic)


# =================================================================================================
# jsonable — the coercer.  ⚠️ `json.dumps(info)` CRASHES without it.
# =================================================================================================


def test_jsonable_coerces_a_config_object():
    """t33's `info["config"]` holds a nested `t27.Config` and `json.dumps` crashes on it."""
    class Config:
        def __init__(self):
            self.pass_split = 166
            self.t27 = Inner()

    class Inner:
        def __init__(self):
            self.conf = 0.5

    out = D.jsonable({"config": Config()})
    assert out == {"config": {"pass_split": 166, "t27": {"conf": 0.5}}}
    json.dumps(out)                                      # the whole point


def test_jsonable_coerces_numpy_and_drops_nan():
    np = pytest.importorskip("numpy")
    out = D.jsonable({"a": np.float32(1.5), "b": np.array([1, 2]), "c": float("nan"),
                      "d": float("inf")})
    assert out == {"a": 1.5, "b": [1, 2], "c": None, "d": None}
    json.dumps(out)


def test_jsonable_survives_a_warm_cache_hit(mosaic):
    """⚠️ A warm cache hit hands back a **plain dict**, not a `t33.Config`. Keying the coercion on the
    type made it a no-op on every cached build — which is the common case."""
    assert D.jsonable({"config": {"pass_split": 166}}) == {"config": {"pass_split": 166}}


# =================================================================================================
# DocumentStore
# =================================================================================================


def test_the_store_holds_more_than_one_open_document(mosaic):
    """v1 kept "which file is open" in a single module-level `PROJECT_PATH` on the server. Two
    features on one dataset — or two mosaics on one dataset, which is legal — need two."""
    D.DOCUMENTS.clear()
    one = D.DOCUMENTS.put(a_doc(mosaic), path="C:/tmp/one.camea.json")
    two = D.DOCUMENTS.put(a_doc(mosaic))

    assert {d.id for d in D.DOCUMENTS.list()} == {one.id, two.id}
    assert D.DOCUMENTS.get(one.id).path == "C:/tmp/one.camea.json"
    assert D.DOCUMENTS.get(two.id).path is None

    D.DOCUMENTS.close(one.id)
    assert [d.id for d in D.DOCUMENTS.list()] == [two.id]
    D.DOCUMENTS.clear()
