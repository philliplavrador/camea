"""The videomosaic MEA trace route's two resolutions, and the per-run envelope cache behind them.

⭐ **THE TRACE-VIEWER PORT (2026-08-15).** The Analyze MEA task got the whole-recording viewer
first (`test_mea_feature.py` § plan 004); this file proves the videomosaic side now carries the
same contract on `GET /api/videomosaic/{id}/mea/trace`:

* without `max_points` the OLD contract is untouched — raw samples, the 30 s window silently
  clamped, window-scoped health;
* with `max_points` the answer is a min/max envelope and the cap does not apply;
* a window too wide to read live is served from a per-run cache in the PROJECT STORE, and when
  that cache is missing the route refuses by name (409, `needs: envelope`) instead of blocking —
  `POST .../mea/envelopes` is the backfill that builds it.

🔴 **R44 IS LOAD-BEARING HERE AND IS ASSERTED.** The videomosaic attachment REFERENCES recordings
in place — `mea_dir` may point into the read-only data mirror — so the cache must land inside the
project folder and never beside the source `.h5`.

⛔ No dataset knowledge: the chip, the grid and every count come from the fixtures. The planted
4 × 12 grid mirrors `test_mea_orientation.py`'s (deliberately not the chip's own 13 × 5, and not
any real device).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from .conftest import err, run_job

pytest.importorskip("h5py")
pytest.importorskip("cv2")

#: The planted electrode grid — `test_mea_orientation.py`'s, for the same reasons.
GRID_COLS, GRID_ROWS = 4, 12

#: Under the default (no-flip) seating on the 13-wide fixture chip, grid "1-1" is chip electrode 0
#: = routed channel 0 (the busiest pad), and "2-1" is chip electrode 13 — an odd row, which the
#: fixture deliberately does not route. Both derived from fixture facts, not from the app.
ROUTED_ID = "1-1"
UNROUTED_ID = "2-1"


@pytest.fixture()
def slow_clock(measynth, monkeypatch):
    """The synthetic recorder at 1 kHz instead of 20 kHz, purely so a recording longer than the
    30 s cap — and one too long to read live — costs kilobytes. Same move as
    `test_mea_feature.py`; also a second guard that nothing quietly assumes MaxWell's rate."""
    monkeypatch.setattr(measynth, "FS_HZ", 1000.0)
    return measynth


def _project(client, tmp_path, videosynth, mod, *, seconds: float,
             name: str = "trace") -> tuple[str, Path, Path]:
    """A videomosaic project with the 4 × 12 grid planted and ONE recording of `seconds` attached.
    -> `(analysis_id, project_folder, mea_dir)`."""
    videosynth.write_survey_video(tmp_path / "survey.avi", rows=2)
    r = client.post("/api/videomosaic/projects",
                    json={"name": name, "video_path": str(tmp_path / "survey.avi")})
    assert r.status_code == 201, r.text
    a = r.json()
    aid = a["analysis_id"]

    mea_dir = tmp_path / "MEA"
    mod.write_recording(mea_dir / "P0000" / "Network" / "000010" / "data.raw.h5",
                        n_samples=int(round(seconds * mod.FS_HZ)))
    # ⭐ Attaching is a JOB since R48 (it opens every h5 it finds) — 202 + a poll.
    r = client.post("/api/videomosaic/mea/attach",
                    json={"analysis_id": aid, "mea_dir": str(mea_dir), "confirm": True})
    assert r.status_code == 202, r.text
    assert run_job(client, r.json()["job_id"])["result"]["kind"] == "mea_attach"

    # The grid, straight into the saved document — the disk is the interface these routes read
    # (the same staging move `test_mea_orientation.py` uses, for the same reason).
    folder = Path(a["folder"])
    doc = json.loads((folder / "document.camea.json").read_text("utf-8"))
    doc["electrodes"] = {"cols": GRID_COLS, "rows": GRID_ROWS}
    (folder / "document.camea.json").write_text(json.dumps(doc), encoding="utf-8")
    return aid, folder, mea_dir


def _trace(client, aid: str, **params) -> dict:
    r = client.get(f"/api/videomosaic/{aid}/mea/trace", params=params)
    assert r.status_code == 200, r.text
    return r.json()


# ---- the old contract, unmoved ------------------------------------------------------------------
def test_the_trace_route_without_max_points_is_exactly_what_it_always_was(
        client, tmp_path, videosynth, slow_clock):
    """🔴 **THE HALF THAT MAY NOT MOVE.** Raw samples, `resolution: "samples"`, the window wider
    than the cap silently clamped rather than refused, window-scoped health, and the lamp marks
    for the window. Every caller written before today relies on this."""
    from camea.features.videomosaic.routes import MAX_TRACE_SECONDS

    aid, _folder, _mea = _project(client, tmp_path, videosynth, slow_clock, seconds=45.0)
    body = _trace(client, aid, electrode=ROUTED_ID, t0=0.0, t1=9999.0)

    assert body["resolution"] == "samples"
    assert body["min_uv"] == [] and body["max_uv"] == []
    assert body["recorded"] is True and body["channel"] == 0
    assert body["duration_s"] == pytest.approx(45.0)
    assert body["t0_s"] == 0.0
    assert body["t1_s"] == pytest.approx(MAX_TRACE_SECONDS), "⛔ silently clamped, not refused"
    assert body["t1_s"] < body["duration_s"], "the fixture must outlast the cap or this proves nothing"
    assert len(body["trace_uv"]) == int(round(MAX_TRACE_SECONDS * body["sampling_hz"]))
    assert body["health"] is not None and body["health_scope"] == "window"
    assert body["sync_episodes"] == [], "the unallocated raw stream is all rail — no lamp marks"
    assert body["orientation"]["confirmed"] is False, "the seating doubt still rides on the payload"
    assert body["max_window_s"] == pytest.approx(MAX_TRACE_SECONDS), \
        "⛔ I1 in miniature — the client reads the cap, never writes 30 down"


# ---- the new contract: a reduced picture, at any width -------------------------------------------
def test_max_points_returns_an_envelope_and_the_30_s_ceiling_stops_applying(
        client, tmp_path, videosynth, slow_clock):
    """⭐ **THE HEADLINE, PORTED.** A 45 s window comes back whole — as `min_uv`/`max_uv` columns —
    and `t1_s` is the end of the recording, not `t0 + 30`. Narrow enough here to read live, so the
    health is the window's own."""
    from camea.features.videomosaic.routes import MAX_TRACE_SECONDS

    aid, _folder, _mea = _project(client, tmp_path, videosynth, slow_clock, seconds=45.0)
    body = _trace(client, aid, electrode=ROUTED_ID, t0=0.0, t1=9999.0, max_points=600)

    assert body["resolution"] == "envelope"
    assert body["trace_uv"] == [], "⛔ never both — `resolution` says which arrived"
    assert body["min_uv"] and body["max_uv"]
    assert len(body["min_uv"]) == len(body["max_uv"]) <= 600
    assert all(lo <= hi for lo, hi in zip(body["min_uv"], body["max_uv"], strict=True))
    assert body["t0_s"] == 0.0
    assert body["t1_s"] == pytest.approx(45.0)
    assert body["t1_s"] > MAX_TRACE_SECONDS, "⭐ the cap did NOT apply"
    assert body["health"] is not None and body["health_scope"] == "window"
    assert body["chip_electrode"] == 0, "the videomosaic identity facts survive the new contract"


def test_an_unrouted_electrode_is_a_fact_at_either_resolution(client, tmp_path, videosynth,
                                                              measynth):
    """⭐ *"Never recorded"* is the ordinary answer on a MaxWell and stays a 200 with
    `recorded: false` at both resolutions — never a 404, never an empty envelope drawn as a flat
    line at zero."""
    aid, _folder, _mea = _project(client, tmp_path, videosynth, measynth, seconds=3.0)
    for params in ({}, {"max_points": 500}):
        body = _trace(client, aid, electrode=UNROUTED_ID, **params)
        assert body["recorded"] is False, params
        assert body["trace_uv"] == [] and body["min_uv"] == [] and body["max_uv"] == [], params


# ---- the cache: 409 by name, the backfill builds it, and R44 on where it lands -------------------
def test_a_window_too_wide_to_read_live_needs_the_envelope_and_the_backfill_builds_it(
        client, tmp_path, videosynth, slow_clock):
    """⭐ **THE WHOLE CONTRACT IN ONE WALK.** Wide window with no cache -> 409 that names what is
    missing; the status route says `ready: false`; the backfill starts one job per run; once it
    lands the same request answers from the cache with whole-recording health.

    🔴 And R44 is asserted on the way: the cache is INSIDE the project folder, and nothing —
    nothing at all — was written beside the source recording."""
    from camea.features.videomosaic.routes import LIVE_READ_MAX_SAMPLES

    # Derived from the route's own budget, never written down: too long to read live, barely.
    seconds = (LIVE_READ_MAX_SAMPLES * 1.25) / slow_clock.FS_HZ
    aid, folder, mea_dir = _project(client, tmp_path, videosynth, slow_clock, seconds=seconds)
    before = sorted(p.as_posix() for p in mea_dir.rglob("*"))

    r = client.get(f"/api/videomosaic/{aid}/mea/trace",
                   params={"electrode": ROUTED_ID, "t0": 0.0, "t1": 9999.0, "max_points": 500})
    assert r.status_code == 409, r.text
    assert err(r)["code"] == "refused"
    assert err(r)["detail"]["needs"] == "envelope", "it names WHAT is missing, not just that it is"

    rows = client.get(f"/api/videomosaic/{aid}/mea/envelopes").json()["recordings"]
    assert [x["run_id"] for x in rows] == ["000010"]
    assert rows[0]["label"] == "Network/000010"
    assert rows[0]["ready"] is False and rows[0]["job_id"] == ""

    started = client.post(f"/api/videomosaic/{aid}/mea/envelopes").json()["started"]
    assert len(started) == 1
    res = run_job(client, started[0])["result"]
    assert res["kind"] == "mea_envelope" and res["built"] is True and res["n_buckets"] > 0

    assert all(x["ready"] for x in
               client.get(f"/api/videomosaic/{aid}/mea/envelopes").json()["recordings"])
    again = client.post(f"/api/videomosaic/{aid}/mea/envelopes").json()
    assert again["started"] == [], "⭐ everything is built, so calling it twice costs nothing"

    body = _trace(client, aid, electrode=ROUTED_ID, t0=0.0, t1=9999.0, max_points=500)
    assert body["resolution"] == "envelope"
    assert 0 < len(body["min_uv"]) == len(body["max_uv"]) <= 500
    assert body["t1_s"] == pytest.approx(body["duration_s"], abs=body["duration_s"] / 100)
    assert body["health"] is not None, "🔴 R3.8 — the 'did not decode' warning survives out here"
    assert body["health_scope"] == "recording", "the cache's own whole-recording figure, said so"
    assert body["sync_episodes"] == [], "served from the sidecar the job wrote — rail, so none"

    # 🔴 R44, both halves: inside the project store …
    inside = list(folder.rglob("envelope.npz"))
    assert len(inside) == 1 and "recordings" in inside[0].parts
    assert (inside[0].parent / "sync.json").is_file(), "the lamp-mark sidecar landed beside it"
    # … and NOT ONE new byte beside his recording.
    assert sorted(p.as_posix() for p in mea_dir.rglob("*")) == before


def test_the_envelope_routes_refuse_where_the_other_mea_routes_do(client, tmp_path, videosynth,
                                                                  measynth):
    """The same two gates every route on this attachment has: no attachment is a 409 that says so,
    and a project of another task is refused by its feature string — ⛔ including on the POST,
    which starts work."""
    videosynth.write_survey_video(tmp_path / "survey.avi", rows=2)
    a = client.post("/api/videomosaic/projects",
                    json={"name": "bare", "video_path": str(tmp_path / "survey.avi")}).json()
    for call in (client.get, client.post):
        r = call(f"/api/videomosaic/{a['analysis_id']}/mea/envelopes")
        assert r.status_code == 409, r.text
        assert "no MEA recording is attached" in err(r)["message"]

    p = measynth.write_recording(tmp_path / "MEA2" / "P0000" / "Network" / "000001" /
                                 "data.raw.h5")
    m = client.post("/api/mea/projects", json={"name": "shelf", "paths": [p.as_posix()]}).json()
    for call in (client.get, client.post):
        r = call(f"/api/videomosaic/{m['analysis_id']}/mea/envelopes")
        assert r.status_code == 409, r.text
        assert "not a video mosaic" in err(r)["message"]
