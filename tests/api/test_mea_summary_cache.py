"""`GET /api/videomosaic/{id}/mea` answers from the summary cache (2026-08-16).

The route used to run `_summarise` — an h5 header open per recording, through HDF5's global lock —
on the request thread, on **every** visit to the feature screen, for headers that never change on a
read-only mirror. Now the summary is remembered against a fingerprint of the files themselves
(path, size, mtime), the attach job primes it, and the headers are re-opened only when a file
actually changed.

⛔ No dataset knowledge: the chip and every count come from the `measynth` fixture.
"""

from __future__ import annotations

import os

import pytest

from .conftest import run_job

pytest.importorskip("h5py")
pytest.importorskip("cv2")


def _attached_project(client, tmp_path, videosynth, measynth) -> tuple[str, list]:
    videosynth.write_survey_video(tmp_path / "survey.avi", rows=2)
    r = client.post("/api/videomosaic/projects",
                    json={"name": "cache", "video_path": str(tmp_path / "survey.avi")})
    assert r.status_code == 201, r.text
    aid = r.json()["analysis_id"]
    measynth.write_session(tmp_path / "MEA")
    r = client.post("/api/videomosaic/mea/attach",
                    json={"analysis_id": aid, "mea_dir": str(tmp_path / "MEA"),
                          "confirm": True})
    assert r.status_code == 202, r.text
    res = run_job(client, r.json()["job_id"])["result"]
    assert res["kind"] == "mea_attach"
    paths = sorted((tmp_path / "MEA").rglob("data.raw.h5"))
    assert paths, "the fixture wrote no recordings — every assertion below would be vacuous"
    return aid, paths


def test_the_attach_job_primes_the_cache_and_a_change_invalidates_it(
        client, tmp_path, videosynth, measynth, monkeypatch):
    from camea.features.videomosaic import routes

    aid, paths = _attached_project(client, tmp_path, videosynth, measynth)

    # Count the h5-opening walk from here on. ⚠️ Patched AFTER the attach: the job legitimately
    # pays for one walk — the point is that the request path then never pays for it again.
    calls: list[int] = []
    real = routes._summarise

    def counting(paths_, **kw):
        calls.append(1)
        return real(paths_, **kw)

    monkeypatch.setattr(routes, "_summarise", counting)

    # ⭐ Primed by the job: two visits to the screen, zero header walks.
    for _ in range(2):
        r = client.get(f"/api/videomosaic/{aid}/mea")
        assert r.status_code == 200, r.text
        assert r.json()["attached"] is True
        assert len(r.json()["recordings"]) == len(paths)
    assert calls == [], "the request path re-opened h5 headers the attach job had just read"

    # ⭐ The cache is honest, not a snapshot: touch one recording and the next visit re-reads.
    st = paths[0].stat()
    os.utime(paths[0], ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    assert client.get(f"/api/videomosaic/{aid}/mea").status_code == 200
    assert len(calls) == 1, "a changed file must invalidate the remembered summary"

    # …and the re-read is itself remembered.
    assert client.get(f"/api/videomosaic/{aid}/mea").status_code == 200
    assert len(calls) == 1
