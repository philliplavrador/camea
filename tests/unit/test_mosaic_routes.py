"""The mosaic router. **What these tests actually defend.**

Three of them are the point, and the rest are plumbing:

  * `test_nothing_is_dropped_by_trial_number` — the standing ruling, as a test. The gate may drop a
    frame for its SHAPE and for being absent from disk, and for nothing else, ever.
  * `test_the_scan_only_proposes` — the blank scan returns a *proposal* and no decision, and there is
    no threshold constant in the source to fall back on.
  * `test_match_is_a_pure_function_of_the_body` — the server holds no tile state, so the same body
    gives the same call and a different refusal set is a different call. This is the prefetch's
    correctness proof; if it fails, the sweep can be shown a match computed against the wrong field.

`solve` / `document` / `export` are other agents' files and may not exist yet, so every test that
needs one **injects a fake** through the router's own lazy accessors. Nothing here imports cv2's
friends, spectralign or a GPU.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from camea.core.dataset import Dataset, LogEntry
from camea.core.frames import Tone, FrameStore
from camea.core.jobs import JOBS
from camea.legacy.mosaic import routes

# ⭐ RETIRED, NOT REMOVED (2026-08-11). The snapshot mosaic builder moved to `camea.legacy.mosaic`
# and is no longer offered for new projects, so its suites are deselected from the fast run —
# `uv run pytest -q` skips this file, `uv run pytest -m legacy -q` still runs it, and it still
# passes. It is deselected because nobody is changing this feature, NOT because it is broken.
pytestmark = pytest.mark.legacy

TILE = routes.TILE


# =================================================================================================
# A session, built in memory. No disk, no pixels worth the name, no engine.
# =================================================================================================
def _entries(blocks: list[tuple[int, int]], step_s: float = 2.0,
             big_gap_after: int | None = None) -> tuple[LogEntry, ...]:
    """Snapshot trials in `blocks`, 2 s apart, with one 20 s pause after `big_gap_after`."""
    t0 = datetime(2026, 6, 20, 10, 0, 0, tzinfo=timezone.utc)
    out: list[LogEntry] = []
    clock = t0
    prev: datetime | None = None
    for lo, hi in blocks:
        for t in range(lo, hi + 1):
            gap = None if prev is None else round((clock - prev).total_seconds(), 1)
            out.append(LogEntry(trial=t, type="Snapshot",
                                time=clock.strftime("%Y-%m-%dT%H:%M:%SZ"), gap_s=gap, dt=clock))
            prev = clock
            clock += timedelta(seconds=(20.0 if t == big_gap_after else step_s))
    return tuple(out)


def _snaps(trials: list[int], off_shape: dict[int, tuple[int, int]] | None = None) -> dict[int, dict]:
    """The raw disk inventory. `off_shape` forces a (w, h) that is not TILExTILE."""
    off_shape = off_shape or {}
    out = {}
    for t in trials:
        w, h = off_shape.get(t, (TILE, TILE))
        out[t] = {"trial": t, "w": w, "h": h, "bytes": 2, "dtype": "uint16",
                  "flip_x": True, "flip_y": True, "dat": Path(f"{t:03d}-ccd.dat")}
    return out


def _frames(trials: list[int], rng: np.random.Generator, blank: list[int] = ()) -> FrameStore:
    """A tiny frame store. The mosaic router never reads a pixel except through `texture()`, so the
    frames need only be *frames* — a real 512x512 stack would make this suite take minutes."""
    n, side = len(trials), 32
    f = rng.normal(2000, 300, (n, side, side)).astype(np.float32)
    for t in blank:                       # a near-featureless frame -> a low DoG std
        f[trials.index(t)] = rng.normal(2000, 1.0, (side, side)).astype(np.float32)
    return FrameStore(
        trials=list(trials),
        frames=f,
        flat_n=np.ones((side, side), np.float32),
        tone=Tone(lo=0.0, hi=4095.0, level=2000.0),
        metas={t: {"flip_x": True, "flip_y": True} for t in trials},
    )


@pytest.fixture
def session(tmp_path):
    """Blocks (1,1), (5,7), (11,60) -> the run is 11-60. Trial 20 is 512x128 (off-shape) and trial
    25 has no frame on disk. The pass split is after 40 (a 20 s pause).

    ⚠️ Pass 1 must be big enough to support a 2nd percentile (`BLANK_MIN_REFERENCE`) or the blank
    scan honestly proposes **nothing** — which is a real behaviour, and it has its own test."""
    run = list(range(11, 61))
    blocks = [(1, 1), (5, 7), (11, 60)]
    all_snaps = [1, 5, 6, 7] + [t for t in run if t != 25]

    ds = Dataset(
        path=tmp_path / "260620d",
        name="260620d",
        experiment="260620d",
        entries=_entries(blocks, big_gap_after=40),
        snapshots=_snaps(all_snaps, off_shape={20: (TILE, 128)}),
    )
    loaded = [t for t in run if t not in (20, 25)]      # what the gate lets through
    rng = np.random.default_rng(7)
    return SimpleNamespace(
        session_id="sess_1",
        dataset=ds,
        frames=_frames(loaded, rng, blank=[13, 31]),
    )


@pytest.fixture
def client(session, tmp_path, monkeypatch):
    """The router, mounted, with `camea.api.app`'s exception handler stood in for."""
    monkeypatch.setattr(routes, "_SESSION_PROVIDER",
                        lambda sid: session if sid == session.session_id else None)

    # ⭐ **THE STORE SEAM (R44).** The export writes into the PROJECT's `outputs/`, so the router
    # resolves an `analysis_id` through this. A fake, because this file tests the ROUTER: the real
    # store is `core.project`'s and is tested in `tests/unit/test_project.py`.
    store = tmp_path / "store"

    def outputs_dir(analysis_id: str):
        d = store / analysis_id / "outputs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    monkeypatch.setattr(routes, "_PROJECTS_PROVIDER",
                        lambda: SimpleNamespace(outputs_dir=outputs_dir))

    app = FastAPI()

    @app.exception_handler(HTTPException)
    def _envelope(request, exc: HTTPException):
        d = exc.detail if isinstance(exc.detail, dict) else {"code": "bad_request",
                                                             "message": str(exc.detail)}
        return JSONResponse(status_code=exc.status_code, content={"error": d})

    app.include_router(routes.router)
    return TestClient(app, raise_server_exceptions=False)


class FakeSolve:
    """Records every call. `t33.Config` raises on an unknown knob, exactly as the real one does."""

    class t33:
        class Config:
            def __init__(self, **kw):
                known = {"pass_split", "anchor_ncc", "split_px", "look", "min_side", "t27"}
                bad = set(kw) - known
                if bad:
                    raise TypeError(f"unknown T33 config knob: {sorted(bad)[0]!r}")
                self.__dict__.update(kw)

    def __init__(self):
        self.calls: list[dict] = []

    def match_anchor(self, frames, target, anchors, positions, *, mode="global", near=None,
                     radius=64, max_candidates=9, refuse=()):
        self.calls.append({"kind": "anchor", "target": target, "anchors": list(anchors),
                           "positions": dict(positions), "mode": mode, "near": near,
                           "radius": radius, "max_candidates": max_candidates,
                           "refuse": list(refuse)})
        best = {"rank": 0, "x": 10.0, "y": 20.0, "ncc": 0.71, "npix": 4096, "subpixel": True}
        return {"target": target, "mode": mode, "n_anchors": len(anchors),
                "composite": {"w": 1, "h": 1, "valid_px": 1, "m0": (0.0, 0.0)},
                "candidates": [best], "best": best, "margin": 0.42, "margin_thin": False,
                "refused": None, "dropped_anchors": [], "gpu": False, "elapsed_ms": 1.0,
                "cached": False, "cache_key": "k"}

    def score_at(self, frames, target, anchors, positions, at, *, refuse=()):
        self.calls.append({"kind": "score", "target": target, "anchors": list(anchors),
                           "at": tuple(at), "refuse": list(refuse)})
        return {"target": target, "at": tuple(at), "ncc": 0.66, "npix": 4096,
                "refused": None, "dropped_anchors": [], "elapsed_ms": 1.0}


@pytest.fixture
def solve(monkeypatch):
    fake = FakeSolve()
    monkeypatch.setattr(routes, "_solve", lambda: fake)
    return fake


# =================================================================================================
# ⛔ THE STANDING RULING — the app carries no dataset knowledge
# =================================================================================================
def test_nothing_is_dropped_by_trial_number(client):
    """⛔ **THE RULING, AS A TEST.** The gate drops a frame for its SHAPE (`off_shape`) or because it
    is not on disk (`not_snapshot`), and for **nothing else, ever**. No trial number is special.

    v1 hard-coded 26 excluded trial numbers for the user's own dataset and auto-applied them — it
    answered, on his behalf, the exact question the app exists to help him answer.
    """
    r = client.post("/api/mosaic/run", json={"session_id": "sess_1"})
    assert r.status_code == 200, r.text
    body = r.json()

    assert (body["lo"], body["hi"]) == (11, 60)          # the longest contiguous Snapshot block
    assert body["detected"] is True
    assert body["n_in_range"] == 50

    reasons = {d["reason"] for d in body["dropped"]}
    assert reasons <= {"off_shape", "not_snapshot"}, "a THIRD reason to drop a frame appeared"

    dropped = {d["trial"]: d["reason"] for d in body["dropped"]}
    assert dropped == {20: "off_shape", 25: "not_snapshot"}
    assert [d for d in body["dropped"] if d["reason"] == "off_shape"][0]["h"] == 128

    # Every other trial in range survives. Nothing was quietly removed.
    assert body["trials"] == [t for t in range(11, 61) if t not in (20, 25)]
    assert body["n"] == 48


def test_the_gate_opens_gaps_and_they_are_recomputed(client):
    """⚠️ Dropping 20 and 25 opens acquisition GAPS. A "consecutive" pair across one is a multi-step
    stage jump and the serpentine one-axis step prior does **not** hold there. `gaps` is DERIVED and
    is returned with the run — miss it and the next solve is silently poisoned."""
    body = client.post("/api/mosaic/run", json={"session_id": "sess_1"}).json()
    assert [tuple(g) for g in body["gaps"]] == [(19, 21), (24, 26)]


def test_gaps_route_is_a_pure_function_of_its_list(client):
    """⭐ `gaps()` is the ONE symbol the app may import from the exclusion module — never `EXCLUDED`,
    `BLANK`, `BLURRY` or `usable_trials`. This route is the single place the app touches it."""
    r = client.post("/api/mosaic/gaps", json={"trials": [11, 12, 13, 40, 41]})
    assert r.status_code == 200
    assert [tuple(g) for g in r.json()["gaps"]] == [(13, 40)]

    assert client.post("/api/mosaic/gaps", json={"trials": []}).json()["gaps"] == []


def test_the_source_carries_no_dataset_knowledge():
    """⛔ **A SOURCE-LEVEL GUARD**, because this is the rule the project has paid for twice.

    ⚠️ It checks the **CODE**, not the prose. The docstrings in this feature *quote* the measured
    evidence (`60.11`, trial `127`, "never `EXCLUDED`") and they must go on quoting it — an argument
    the reader cannot check is an argument the next agent will overrule. What may not exist is a
    trial number or a measured threshold that the app can **act on**: a name it binds, a number it
    compares against, a list it iterates.
    """
    import ast

    tree = ast.parse(Path(routes.__file__).read_text(encoding="utf-8"))

    # --- 1. IDENTIFIERS. Every name the code binds, reads, imports or calls.
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.alias):
            names.add(node.name.rpartition(".")[2])
            if node.asname:
                names.add(node.asname)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)

    # ⭐ `gaps` is the ONE symbol the app may reach in the exclusion module. These are the others.
    for forbidden in ("EXCLUDED", "BLANK", "BLURRY", "usable_trials", "BLANK_THRESHOLD", "DATA_DIR"):
        assert forbidden not in names, \
            f"{forbidden!r} is dataset knowledge and the code must not be able to reach it"

    # --- 2. LITERALS. No measured constant and no trial number the code could act on.
    #        (512 is `t33.TILE` and is *imported*, never written. 2.0, 9, 64, 4, 2 are policy.)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
                and not isinstance(node.value, bool):
            assert node.value not in (60.11, 60.1, 166, 284, 348, 338, 312, 127), \
                f"{node.value!r} is this dataset's own number, sitting in the app's source"


# =================================================================================================
# Step 2 · Range
# =================================================================================================
def test_the_run_is_overridable_and_an_override_is_not_a_reload(client):
    """⚠️ Both rules are MEASURED and validated on **n = 1 dataset**. They are always overridable —
    and an override is a pure recompute, not the 5 s session re-open v1 did (which also threw away
    the tone and the blank scan)."""
    body = client.post("/api/mosaic/run",
                       json={"session_id": "sess_1", "lo": 11, "hi": 24}).json()
    assert (body["lo"], body["hi"]) == (11, 24)
    assert body["detected"] is False
    assert body["trials"] == [t for t in range(11, 25) if t != 20]


def test_pass_split_is_the_last_trial_of_pass_1(client):
    """⭐ `value` is the **LAST TRIAL OF PASS 1**, never the first of pass 2. t33 hard-partitions on
    `t <= cfg.pass_split`; hand it the wrong side and the two scans are solved against the wrong
    reference."""
    ps = client.post("/api/mosaic/run", json={"session_id": "sess_1"}).json()["pass_split"]
    assert ps["value"] == 40            # the 20 s pause is 40 -> 41; the value is 40, never 41
    assert ps["detected"] is True
    assert ps["gap_s"] == 20.0
    assert ps["n_pass1"] + ps["n_pass2"] == 48


def test_pass_split_override_is_honoured_and_says_so(client):
    ps = client.post("/api/mosaic/run",
                     json={"session_id": "sess_1", "pass_split": 30}).json()["pass_split"]
    assert ps["value"] == 30
    assert ps["detected"] is False
    assert "hand" in ps["why"]


def test_run_on_an_unknown_session_is_404(client):
    r = client.post("/api/mosaic/run", json={"session_id": "nope"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "no_session"


# =================================================================================================
# Step 3 · Screen — the blank proposal
# =================================================================================================
def test_the_scan_only_proposes(client, session):
    """⭐⭐ **IT RECOMMENDS. THE HUMAN TICKS. NOTHING IS AUTO-EXCLUDED.**

    The response carries a *proposal* and a *measurement*. It carries no decision, it excludes
    nothing, and there is nothing in it the caller can mistake for a verdict.

    ⚠️ ZERO MARGIN AT THE BOUNDARY: on the real data, three of the four trials this measure named
    land 0.24 / 0.18 / 2.07 px from the human truth — they are **ordinary tiles** — while the fourth
    lands **679 px wrong**. One of four. That is exactly why it may only ever propose.
    """
    trials = list(session.frames.trials)
    r = client.post("/api/mosaic/screen/propose",
                    json={"session_id": "sess_1", "trials": trials, "pass_split": 40})
    assert r.status_code == 200, r.text
    body = r.json()

    assert set(body) == {"threshold", "threshold_source", "measure", "texture",
                         "proposed", "n_proposed", "n_scanned", "margin_warning"}
    assert "excluded" not in body and "accepted" not in body and "blank" not in body

    assert body["n_scanned"] == len(trials)
    assert body["threshold"] is not None
    assert "percentile" in body["threshold_source"]
    assert body["measure"] == "std of DoG(sigma=3, sigma=30) of the frame as read"

    # The two flat frames are the least textured, so the measure sees them.
    tex = {int(k): v for k, v in body["texture"].items()}
    assert tex[13] < tex[11] and tex[31] < tex[11]
    assert set(body["proposed"]) <= set(trials)
    assert body["n_proposed"] == len(body["proposed"])


def test_no_blur_number_anywhere(client, session):
    """❌ **NO BLUR JUDGEMENT. EVER.** Across 338 snapshots and 15 focus measures the best global blur
    threshold reaches F1 = 0.37; variance-of-Laplacian — the textbook autofocus metric — scores
    **worse than chance**. Catching all 15 of his blurry frames also rejects 62 good ones, best case.

    So the response may carry **no blur FIELD and no blur NUMBER**. (It may, and does, carry a
    *sentence* saying the measure is useless for blur — telling the user what a number does not mean
    is the opposite of scoring him on it.) Blur is his eye, in the sweep, with `E`.
    """
    body = client.post("/api/mosaic/screen/propose",
                       json={"session_id": "sess_1", "trials": list(session.frames.trials)}).json()

    for key in body:
        for word in ("blur", "laplacian", "focus", "sharp", "quality", "score"):
            assert word not in key.lower(), f"the scan is offering a {word} field: {key!r}"

    # The measure it DOES report is texture, and it says so in full.
    assert body["measure"] == "std of DoG(sigma=3, sigma=30) of the frame as read"


def test_the_threshold_is_computed_not_remembered(client, session):
    """⛔ There is **no `BLANK_THRESHOLD` fallback**. With too small a reference set the honest answer
    is *nothing proposed* — not 260620d's measured 60.11, which v1 carried in the source."""
    body = client.post("/api/mosaic/screen/propose",
                       json={"session_id": "sess_1", "trials": [11, 12, 13],
                             "pass_split": 25}).json()
    assert body["threshold"] is None
    assert body["proposed"] == []
    assert "undetermined" in body["threshold_source"]


def test_propose_refuses_a_trial_that_is_not_loaded(client):
    r = client.post("/api/mosaic/screen/propose",
                    json={"session_id": "sess_1", "trials": [11, 999]})
    assert r.status_code == 400
    assert "999" in r.json()["error"]["message"]


# =================================================================================================
# Step 4 · Place — the build
# =================================================================================================
def test_the_build_solves_the_document_s_list_not_the_run(client, session, solve, monkeypatch):
    """⭐ **`trials` IS THE DOCUMENT'S ACTIVE LIST.** v1 hard-wired the session's whole run here, so a
    user who pressed `E` and then re-solved got a re-solve on the **identical input** — the excluded
    frame went straight back into the chain. This is the ONLY way a frame ever leaves a build."""
    spawned: dict = {}

    def fake_submit(kind, target, kwargs, exclusive=None):
        spawned.update(kind=kind, target=target, kwargs=kwargs, exclusive=exclusive)
        return SimpleNamespace(job_id="job_abc")

    monkeypatch.setattr(JOBS, "submit_process", fake_submit)

    active = [t for t in session.frames.trials if t not in (13, 31)]   # he pressed E on two
    r = client.post("/api/mosaic/build", json={"session_id": "sess_1", "trials": active,
                                               "pass_split": 40})
    assert r.status_code == 202, r.text
    assert r.json() == {"job_id": "job_abc", "kind": "build"}

    assert spawned["kwargs"]["trials"] == active
    assert 13 not in spawned["kwargs"]["trials"] and 31 not in spawned["kwargs"]["trials"]
    assert spawned["kwargs"]["config"]["pass_split"] == 40
    assert spawned["target"] == "camea.legacy.mosaic.solve.build_worker"
    # 🔴 It holds the GPU lease, and it runs in a CHILD PROCESS — `t33.place` has no cooperative
    # cancel, so `terminate()` is the only cancel there is.
    assert spawned["exclusive"] == "gpu"


def test_an_unknown_config_knob_is_a_400_not_a_failed_job(client, solve):
    """⚠️ Validated by **constructing a real `t33.Config`** — it raises `TypeError` on an unknown knob
    itself. The router never hard-codes the knob list (a stale copy would reject a knob t33 grew), and
    it never imports t33: it reaches it through `solve`, the one module allowed to."""
    r = client.post("/api/mosaic/build",
                    json={"session_id": "sess_1", "trials": list(range(11, 40)),
                          "pass_split": 25, "config": {"nonsense": 3}})
    assert r.status_code == 400
    assert "nonsense" in r.json()["error"]["message"]


def test_a_build_with_no_solvable_reference_pass_is_refused_up_front(client, solve):
    """t33 places pass 2 **against pass 1** and raises without a reference pass. Say so here, where
    the message reaches the user, rather than failing the job 200 s in."""
    r = client.post("/api/mosaic/build",
                    json={"session_id": "sess_1", "trials": [11, 12, 30, 31, 32],
                          "pass_split": 25})
    assert r.status_code == 400
    msg = r.json()["error"]["message"]
    assert "pass-1" in msg and "Un-exclude" in msg


def test_a_build_trial_that_is_not_loaded_is_a_400(client, solve):
    r = client.post("/api/mosaic/build",
                    json={"session_id": "sess_1", "trials": [11, 12, 13, 14, 30, 31, 999],
                          "pass_split": 25})
    assert r.status_code == 400
    assert "999" in r.json()["error"]["message"]


# =================================================================================================
# Step 5 · Sweep — ⭐⭐ the primitive, and the 409
# =================================================================================================
def _match_body(**kw):
    body = {"session_id": "sess_1", "target": 12,
            "anchors": [14, 11], "positions": {"11": [0, 0], "14": [512, 0]}}
    body.update(kw)
    return body


def test_match_is_a_pure_function_of_the_body(client, solve):
    """⭐⭐ **THE PREFETCH'S CORRECTNESS PROOF.**

    The server holds no tile state, so the answer is a function of the body alone. Two things follow,
    and both are tested here:

      1. the anchor ORDER cannot change the call (the server sorts — the memo key is the *set*);
      2. the REFUSAL SET travels in the body and reaches the solver, so pressing `E` genuinely
         changes the key, misses the memo, and forces an honest recompute.

    In v1 the refusal set lived on the session and `PUT /api/scan/blank` mutated it — which made this
    endpoint impure, contrary to the comment at the top of its own server.
    """
    r = client.post("/api/mosaic/match/anchor", json=_match_body(refuse=[31, 13]))
    assert r.status_code == 200, r.text
    assert r.json()["best"]["ncc"] == 0.71

    call = solve.calls[-1]
    assert call["anchors"] == [11, 14]              # SORTED — the client sent [14, 11]
    assert sorted(call["refuse"]) == [13, 31]       # the refusal set reached the solver
    assert call["mode"] == "global"
    assert call["max_candidates"] == 9              # ⭐ 9, or key `9` can never fire

    # A different refusal set is a DIFFERENT call. It is not folded away.
    client.post("/api/mosaic/match/anchor", json=_match_body(refuse=[]))
    assert solve.calls[-1]["refuse"] == []

    # A duplicated anchor must not paste the same tile into the composite twice.
    client.post("/api/mosaic/match/anchor", json=_match_body(anchors=[14, 11, 14]))
    assert solve.calls[-1]["anchors"] == [11, 14]


def test_the_target_may_not_be_its_own_anchor(client, solve):
    r = client.post("/api/mosaic/match/anchor", json=_match_body(target=11))
    assert r.status_code == 400
    assert "must not contain the target" in r.json()["error"]["message"]


def test_an_anchor_with_no_position_is_a_400(client, solve):
    r = client.post("/api/mosaic/match/anchor",
                    json=_match_body(anchors=[11, 14, 15], positions={"11": [0, 0], "14": [1, 1]}))
    assert r.status_code == 400
    assert "15" in r.json()["error"]["message"]


def test_an_empty_anchor_field_is_a_400(client, solve):
    r = client.post("/api/mosaic/match/anchor", json=_match_body(anchors=[], positions={}))
    assert r.status_code == 400


def test_local_mode_needs_a_drop_point(client, solve):
    r = client.post("/api/mosaic/match/anchor", json=_match_body(mode="local"))
    assert r.status_code == 400
    assert "near" in r.json()["error"]["message"]

    ok = client.post("/api/mosaic/match/anchor",
                     json=_match_body(mode="local", near=[100, 200], radius=64))
    assert ok.status_code == 200
    assert solve.calls[-1]["near"] == (100.0, 200.0)


def test_the_local_radius_can_never_reach_a_grid_alias(client, solve):
    """⚠️ The electrode grid repeats every **256 px**, so a wide *local* search locks confidently onto
    a grid alias. The schema clamps at 256 (and the UI must never exceed 128). To search wide, use
    `mode: "global"` — the FFT plus the margin is what survives the aliases."""
    r = client.post("/api/mosaic/match/anchor",
                    json=_match_body(mode="local", near=[0, 0], radius=512))
    assert r.status_code == 422                      # the contract refuses it; it is not clamped away


def test_score_re_measures_where_the_tile_actually_sits(client, solve):
    """⚠️ `TileRecord.ncc` is defined as the NCC **at the tile's final position**, on every path. On a
    divert the tile is not at the match's best position, so the app throws that number away and
    re-measures here — writing the rejected alias's score onto the tile would attribute it to the
    position that shipped."""
    r = client.post("/api/mosaic/match/score", json=_match_body(at=[300.5, 12.0]))
    assert r.status_code == 200, r.text
    assert r.json()["ncc"] == 0.66
    call = solve.calls[-1]
    assert call["kind"] == "score" and call["at"] == (300.5, 12.0)
    assert call["anchors"] == [11, 14]


def test_the_sweep_is_409_while_a_job_holds_the_gpu(client, solve):
    """🔴 The build owns the card. ⚠️ And the guard asks about the **LEASE**, never about a *kind*:
    v1 asked `JOBS.running("build")` — the mosaic's word, hard-coded into the runner every feature
    shares — and applied it to thread jobs too, which is why an `open` was refused while a build ran.
    """
    release = threading.Event()
    job = JOBS.submit_thread("build", lambda report, cancel: release.wait(5), exclusive="gpu")
    try:
        for path, body in (("/api/mosaic/match/anchor", _match_body()),
                           ("/api/mosaic/match/score", _match_body(at=[0, 0]))):
            r = client.post(path, json=body)
            assert r.status_code == 409, path
            assert r.json()["error"]["code"] == "busy"
            assert job.job_id in r.json()["error"]["detail"]["job_id"]
    finally:
        release.set()

    # ...and the moment the lease is dropped the sweep is live again.
    for _ in range(200):
        if JOBS.holder("gpu") is None:
            break
        threading.Event().wait(0.01)
    assert client.post("/api/mosaic/match/anchor", json=_match_body()).status_code == 200


# =================================================================================================
# The re-check
# =================================================================================================
def _doc(tiles: dict[int, dict]) -> dict:
    return {
        "schema_version": "camea-document-1.0",
        "app": {"name": "Camea", "version": "0.2.0"},
        "id": "d1", "feature": "mosaic", "dataset": "260620d", "experiment": "260620d",
        "data_dir": "/x", "dataset_key": "k", "created": "2026-07-14T00:00:00Z",
        "modified": "2026-07-14T00:00:00Z",
        "provenance": {"authored_by": "human", "app_version": "0.2.0",
                       "workflow": "hand placement from scratch", "independent_of_method": True},
        "tiles": {str(k): v for k, v in tiles.items()},
        "trial_range": [11, 40], "origin_trial": 11, "coordinates": "test",
        "tolerance_px": {"region_default": 10.0},
    }


def test_the_anchor_field_reads_status_anchor(client):
    """⚠️ In memory a tile is `anchored`; on disk its `status` is `"anchor"` — and `score.load_gt()`
    keeps every tile whose **`status == "anchor"`**. Get the mapping wrong and either nothing or
    everything lands in the exported ground truth."""
    field = routes._anchor_field(_doc({
        11: {"status": "anchor", "state": "anchored", "x": 0.0, "y": 0.0},
        12: {"status": "anchor", "x": 5.0, "y": 5.0},          # a bench-written row: no `state`
        13: {"status": "unverified", "state": "unverified", "x": 9.0, "y": 9.0},
        14: {"status": "anchor", "state": "anchored", "x": None, "y": None},   # certified, no position
    }))
    assert field == {11: (0.0, 0.0), 12: (5.0, 5.0)}


def test_the_recheck_is_global_and_is_allowed_to_say_no(client, solve, session):
    """🔴 **IT NEVER MOVES A TILE — IT ONLY MEASURES ONE**, and anything that disagrees by more than
    `tolerance_px` **STAYS FLAGGED**.

    ⚠️ And it must be GLOBAL. v1 fired a *local* match (±64 px) and then cleared `stale`
    unconditionally — but a tile knocked off by a moved anchor is off by **hundreds** of px, so a
    ±64 px window is structurally blind to the one error the panel exists for. Measured: a tile 380 px
    from the truth re-checked locally to ncc −0.0678, was not moved, and had its flag **cleared**.
    """
    doc = _doc({
        11: {"status": "anchor", "state": "anchored", "x": 0.0, "y": 0.0},
        12: {"status": "anchor", "state": "anchored", "x": 512.0, "y": 0.0},
        # FakeSolve always answers (10, 20). This one sits there: it agrees.
        15: {"status": "unverified", "state": "unverified", "x": 10.0, "y": 20.0, "stale": True},
        # ...and this one is 380 px away. It must STAY FLAGGED.
        16: {"status": "unverified", "state": "unverified", "x": 390.0, "y": 20.0, "stale": True},
    })
    r = client.post("/api/mosaic/recheck",
                    json={"session_id": "sess_1", "doc": doc, "tolerance_px": 5.0})
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]

    for _ in range(500):
        job = JOBS.get(job_id)
        if job.state in ("done", "failed", "cancelled"):
            break
        threading.Event().wait(0.01)
    assert job.state == "done", job.error
    res = job.result

    assert res["n_checked"] == 2
    assert res["cleared"] == [15]
    assert [d["trial"] for d in res["disagree"]] == [16]
    assert res["disagree"][0]["disagree_px"] == 380.0
    assert res["disagree"][0]["still_stale"] is True

    # ⭐ EVERY re-check was GLOBAL. Not one ±64 px local search.
    checks = [c for c in solve.calls if c["kind"] == "anchor"]
    assert checks and all(c["mode"] == "global" for c in checks)
    # An anchor is the human's own certification. A machine does not re-judge it.
    assert {c["target"] for c in checks} == {15, 16}


def test_a_recheck_with_no_anchors_is_refused(client, solve):
    r = client.post("/api/mosaic/recheck", json={
        "session_id": "sess_1",
        "doc": _doc({11: {"status": "unverified", "state": "unverified", "x": 1.0, "y": 1.0}}),
    })
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "refused"


# =================================================================================================
# Step 6 · Mosaic — export
# =================================================================================================
def test_an_export_CANNOT_NAME_A_FOLDER_AT_ALL(client, session, monkeypatch):
    """⛔ **A DATASET IS THE MICROSCOPE'S EVIDENCE. THE APP DOES NOT WRITE ON THE EVIDENCE** — and
    since R44 it cannot even be asked to: `dir` is gone from the contract, the export goes into the
    project's own `outputs/`, and `Req` is `extra="forbid"`, so a client still sending a folder gets
    a 422 rather than a quiet write somewhere nobody expects."""
    monkeypatch.setattr(routes, "_export", lambda: SimpleNamespace(export_all=lambda *a, **k: {}))
    session.dataset.path.mkdir(parents=True, exist_ok=True)
    (session.dataset.path / "log.txt").write_text("x", encoding="utf-8")
    (session.dataset.path / "011.xml").write_text("<x/>", encoding="utf-8")

    r = client.post("/api/mosaic/export", json={
        "session_id": "sess_1",
        "dir": str(session.dataset.path / "out"),
        "basename": "m",
        "doc": _doc({}),
    })
    assert r.status_code == 422


def test_an_export_of_a_document_with_no_project_is_refused_not_guessed(client, monkeypatch):
    """⚠️ The destination is derived from the DOCUMENT's `id`, never from the wire — so a document
    that carries no project id has nowhere to go, and Camea says so instead of inventing a folder."""
    monkeypatch.setattr(routes, "_export", lambda: SimpleNamespace(export_all=lambda *a, **k: {}))
    doc = _doc({}) | {"id": ""}

    r = client.post("/api/mosaic/export",
                    json={"session_id": "sess_1", "basename": "m", "doc": doc})
    assert r.status_code == 400
    assert "project" in r.json()["error"]["message"]


def test_export_starts_a_job_that_holds_the_gpu(client, session, tmp_path, monkeypatch):
    seen: dict = {}

    def export_all(frames, dataset, doc, out, basename, outputs, **kw):
        seen.update(out=out, basename=basename, outputs=list(outputs), **kw)
        return {"kind": "export", "files": [], "doc": doc, "warnings": []}

    monkeypatch.setattr(routes, "_export", lambda: SimpleNamespace(export_all=export_all))

    r = client.post("/api/mosaic/export", json={
        "session_id": "sess_1", "basename": "260620d", "doc": _doc({}),
    })
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    for _ in range(500):
        job = JOBS.get(job_id)
        if job.state in ("done", "failed", "cancelled"):
            break
        threading.Event().wait(0.01)
    assert job.state == "done", job.error

    assert job.exclusive == "gpu"
    # ⭐ R44: it wrote into the PROJECT's outputs/, addressed by the document's own id.
    assert seen["out"].name == "outputs" and seen["out"].parent.name == "d1"
    assert seen["basename"] == "260620d"
    # The default set. `coverage` is absent because it is NOT optional — the exporter writes it
    # either way, and without it "empty" and "black" merge forever in a TIFF with no alpha channel.
    assert seen["outputs"] == ["tiff", "png", "positions", "gt", "qc"]
    assert seen["render_mode"] == "feather"
    assert seen["include_unverified"] is True
    assert seen["um_per_px"] is None        # 📏 PIXELS ONLY unless the user typed a number in.


def test_qc_and_the_document_routes_delegate(client, monkeypatch):
    """The router validates and delegates. It does not compute a document rule of its own."""
    calls: list[str] = []

    fake = SimpleNamespace(
        qc_report=lambda doc: (calls.append("qc"), {
            "dataset": "260620d", "trial_range": [11, 40], "pass_split": 25,
            "generated": "2026-07-14T00:00:00Z", "app": {"name": "Camea", "version": "0.2.0"},
            "denominator": {"trials_in_document": 1, "not_excluded": 1, "excluded": 0},
            "by_state": {"anchored": [11]}, "moved": [], "thin_margin": [], "rescued": [],
            "build_stale": False, "provenance": _doc({})["provenance"],
        })[1],
        machine_evidence_report=lambda doc: (calls.append("evidence"), {
            "seeded_from": None, "has_build": False, "n_machine_tiles": 0,
            "independent_of_method": True, "warning": None,
        })[1],
    )
    monkeypatch.setattr(routes, "_document", lambda: fake)

    doc = _doc({11: {"status": "anchor", "state": "anchored", "x": 0.0, "y": 0.0}})
    assert client.post("/api/mosaic/qc", json={"doc": doc}).status_code == 200
    assert client.post("/api/mosaic/document/machine-evidence",
                       json={"doc": doc}).status_code == 200
    assert calls == ["qc", "evidence"]


def test_there_is_no_put_scan_blank(client):
    """⛔ **THE ENDPOINT THAT MADE THE MATCHER IMPURE IS GONE, AND IT MUST NOT COME BACK.** The
    refusal set is the *document's*, and it travels in `MatchAnchorRequest.refuse`."""
    paths = {r.path for r in routes.router.routes}
    assert not any("scan" in p and "blank" in p for p in paths)
    assert client.put("/api/mosaic/scan/blank", json={"blank": [13]}).status_code in (404, 405)
