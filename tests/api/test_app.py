"""The app itself: the schema, the error envelope, CORS, and the one import rule that matters.

⭐ **THE OPENAPI SCHEMA IS THE CONTRACT** — the TypeScript client is generated from it. So the tests
that matter most here are the ones that say *"this schema can be generated on a machine with no
GPU, no CUDA and no data"*, and *"every non-2xx has the same body"*.
"""

from __future__ import annotations

import subprocess
import sys

from camea.api.app import _DIST

from .conftest import err


def test_health_touches_nothing(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["python"].startswith("3.")
    assert body["uptime_s"] >= 0.0


def test_the_openapi_schema_is_servable(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    s = r.json()
    # Every route the front end may call. If a route is not here, the client cannot call it — and
    # that is the point of the contract living in `schemas.py`.
    for path in ("/api/health", "/api/gpu", "/api/settings", "/api/fs/list", "/api/datasets/at",
                 "/api/sessions", "/api/projects",
                 "/api/projects/{analysis_id}",
                 "/api/projects/{analysis_id}/outputs",
                 "/api/projects/{analysis_id}/outputs/copy",
                 "/api/jobs", "/api/documents/load",
                 "/api/mosaic/run", "/api/mosaic/gaps", "/api/mosaic/match/anchor",
                 "/api/mosaic/build", "/api/mosaic/export", "/api/mosaic/recompute", "/api/mosaic/qc"):
        assert path in s["paths"], f"{path} is missing from the OpenAPI schema"
    assert "MosaicDocument" in s["components"]["schemas"]


def test_job_result_is_a_discriminated_union_on_kind(client):
    """🔴 `Job.result` is `Field(discriminator="kind")`. **Every job's result MUST carry its tag** or
    `GET /api/jobs/{id}` cannot serialise it and the poll 500s — which is exactly what happened to a
    perfectly good build (12/12 tiles, 8.0 s) until `solve.build_result()` learned to emit
    `"kind": "build"`. If a new job kind is added, this test is where it is caught."""
    s = client.get("/openapi.json").json()
    job = s["components"]["schemas"]["Job"]
    result = job["properties"]["result"]
    # pydantic renders the union under anyOf/oneOf, and the tag is `kind`.
    blob = str(result)
    assert "kind" in blob or "discriminator" in blob
    for member in ("OpenJobResult", "BuildResult", "ExportResult", "RecheckResult"):
        assert member in s["components"]["schemas"], f"{member} is not in the schema"
        props = s["components"]["schemas"][member]["properties"]
        assert "kind" in props, f"{member} has no `kind` discriminator"


def test_every_non_2xx_is_an_error_envelope(client):
    """⛔ ONE error shape, whatever raised. A 400 must never be able to become a 500 over a wiring
    detail — that is the bug shape that turned v1's refused document into an opaque 500 on every
    2-second autosave."""
    for r in (client.get("/api/jobs/nope"),                  # routes_core.ApiError -> 404
              client.get("/api/sessions/nope"),              # -> 404 no_session
              client.post("/api/mosaic/gaps", json={"trials": "not a list"})):   # -> 422 pydantic
        e = err(r)
        assert set(e) <= {"code", "message", "detail"}
        assert isinstance(e["code"], str) and isinstance(e["message"], str)

    assert err(client.get("/api/jobs/nope"))["code"] == "not_found"
    assert err(client.get("/api/sessions/nope"))["code"] == "no_session"


def test_the_mosaic_routers_error_class_renders_the_same_envelope(client, synth):
    """`features.mosaic.routes.ApiError` is a DIFFERENT class from `routes_core.ApiError`. The
    handler in `api/app.py` keys on the `code` attribute, not the type — so a feature never has to
    import the API layer to raise a proper error."""
    r = client.post("/api/mosaic/run", json={"session_id": "nope"})
    assert r.status_code == 404
    assert err(r)["code"] == "no_session"


def test_extra_fields_are_a_422_not_a_silent_default(client):
    """`Req` is `extra="forbid"`. A typo'd field is a 422 — a silent default is how a client and a
    server drift apart."""
    r = client.post("/api/mosaic/gaps", json={"trials": [1, 2], "trialz": [3]})
    assert r.status_code == 422
    assert err(r)["code"] == "bad_request"


def test_cors_is_the_vite_dev_server_and_not_a_wildcard(client):
    from camea.api.app import CORS_ORIGINS

    assert "http://localhost:5173" in CORS_ORIGINS
    assert "*" not in CORS_ORIGINS
    r = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_importing_the_app_does_not_import_cupy_or_spectralign():
    """⭐ `/openapi.json` must be inspectable on a machine where the ENGINE CANNOT EVEN LOAD — that is
    how the TypeScript client is generated in CI, on a box with no CUDA and no data. Importing the
    app must therefore not pull in cupy or spectralign. (cv2 and numpy do come in, through
    `core.frames`; they are pure-CPU wheels and are not the hazard.)"""
    code = (
        "import sys; import camea.api.app as a; a.create_app();"
        "bad=[m for m in ('cupy','spectralign') if m in sys.modules];"
        "print('BAD' if bad else 'OK', bad)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.startswith("OK"), out.stdout


def test_the_root_page_points_a_human_somewhere_useful(client):
    """Two contracts, picked at import time by whether `web/dist/` exists (CI's backend job never
    builds it; a dev box that has run `npm run build` has it). Either way `/` must resolve to
    something a human can act on — the built UI, or a pointer to how to get one."""
    r = client.get("/")
    assert r.status_code == 200
    if _DIST.is_dir():
        assert r.headers["content-type"].startswith("text/html")
        assert '<div id="root">' in r.text
    else:
        assert r.json()["openapi"] == "/openapi.json"


def test_unmatched_routes_fall_back_to_the_spa_when_built(client):
    """`createBrowserRouter` means a path like `/project/<id>` has no server-side route of its own —
    only the SPA's client-side router resolves it, so a hard refresh there must not 404."""
    r = client.get("/project/some-id")
    if _DIST.is_dir():
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
    else:
        assert r.status_code == 404
