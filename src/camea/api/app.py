"""app.py — the FastAPI application. **The wiring, and nothing else.**

    create_app()  ->  core router  +  every feature router  +  the error envelope  +  CORS

WHAT THIS FILE IS
-----------------
Three jobs, and it must not grow a fourth:

1. **Mount the routers.** `api/routes_core.py` (health, gpu, settings, fs, datasets, sessions, tiles,
   workspace, documents, jobs, dialogs) and each feature's own — `features/mosaic/routes.py` today.
   A feature registers its document hooks by being imported; it is imported here and nowhere else.

2. ⭐ **INJECT THE SESSION LOOKUP INTO EACH FEATURE.** Core owns sessions (one per dataset, shared by
   every open feature). A feature must not import the API layer — the arrow is one-way,
   `api -> features -> core -> engine` — so app.py *hands* it `SESSIONS.get`. One line per feature,
   and it is what keeps the arrow intact.

3. **Render the error envelope.** Every non-2xx is `{"error": {"code", "message", "detail"}}`
   (`schemas.ErrorEnvelope`). 🔴 **A 400 MUST NEVER BE ABLE TO BECOME A 500 OVER A WIRING DETAIL** —
   in v1 a refused document did exactly that, on every 2-second autosave, and the user saw an opaque
   500 where he was owed a reason.

⭐ **THE OPENAPI SCHEMA IS THE CONTRACT** (`schemas.py` -> `/openapi.json` -> the TypeScript client).
So `/openapi.json` **must be inspectable on a machine where the engine cannot even load** — that is
how the client is generated in CI, on a box with no CUDA and no data. Importing this module therefore
imports **no cv2, no cupy, no spectralign**: every heavy import in the routers is inside a handler.
`camea.api.app` -> `import fastapi, camea.core.*` and stops. Keep it that way; it is one `uv run
python -c "import camea.api.app"` away from being checked.

⚠️ **CORS is for the VITE DEV SERVER, and for nothing else.** In `--window` and `--browser` the page
is served from this same origin and no CORS header is ever consulted. `localhost:5173` is where `npm
run dev` lives. We do **not** open this up: the server binds 127.0.0.1 (never 0.0.0.0), and it holds
a filesystem browser and a document writer.
"""

from __future__ import annotations

import time
import traceback
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import camea
from camea.api import routes_core
from camea.api.schemas import ErrorCode

__all__ = ["create_app", "APP", "CORS_ORIGINS"]

#: The Vite dev server. ⛔ Not a wildcard, and never `0.0.0.0`.
CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",     # `vite preview`
    "http://127.0.0.1:4173",
]

#: HTTP status -> the `ErrorCode` we use when an exception did not carry one of its own.
_STATUS_CODE: dict[int, ErrorCode] = {
    400: "bad_request",
    404: "not_found",
    409: "refused",
    500: "io_error",
    501: "no_window",
}


def _envelope(status: int, code: str, message: str,
              detail: dict[str, str] | None = None) -> JSONResponse:
    """`schemas.ErrorEnvelope`. **The body of every non-2xx response in the app.**"""
    body: dict[str, Any] = {"code": code, "message": message}
    if detail:
        body["detail"] = {str(k): str(v) for k, v in detail.items()}
    return JSONResponse({"error": body}, status_code=status)


def create_app(*, cors: bool = True) -> FastAPI:
    """The app. Import-safe: it touches no disk, opens no dataset and does not look for a GPU."""
    app = FastAPI(
        title="Camea",
        version=camea.__version__,
        description=(
            "A microscopy analysis desktop app. A DATASET is raw and read-only; an ANALYSIS is what "
            "you did to it, and it lives in the WORKSPACE you chose. This schema is THE CONTRACT: "
            "the TypeScript client is generated from it. See src/camea/api/schemas.py."
        ),
    )

    if cors:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=CORS_ORIGINS,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # ---------------------------------------------------------------------------------------------
    # The error envelope. ONE shape, whatever raised.
    # ---------------------------------------------------------------------------------------------
    @app.exception_handler(HTTPException)
    def _on_http_error(request: Request, exc: HTTPException) -> JSONResponse:
        """⭐ **ONE HANDLER FOR BOTH `ApiError`s.** `routes_core.ApiError` and
        `features.mosaic.routes.ApiError` are two classes with the same shape, and a feature must not
        have to import the API layer to raise one. So this handler keys on the **`code` attribute**,
        not on the type — a new feature's `ApiError` is handled for free, and a plain
        `HTTPException(404)` still renders a proper envelope instead of FastAPI's `{"detail": ...}`.
        """
        code = getattr(exc, "code", None) or _STATUS_CODE.get(exc.status_code, "bad_request")
        message = getattr(exc, "message", None)
        detail = getattr(exc, "info", None)
        if message is None:
            d = exc.detail
            message = d.get("message", str(d)) if isinstance(d, dict) else str(d)
        return _envelope(exc.status_code, str(code), str(message), detail)

    @app.exception_handler(RequestValidationError)
    def _on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        """A 422 from pydantic. `Req` is `extra="forbid"`, so a typo'd field lands here — which is the
        point: a silent default is how a client and a server drift apart."""
        errs = exc.errors()
        first = errs[0] if errs else {}
        loc = ".".join(str(p) for p in (first.get("loc") or [])[1:]) or "body"
        return _envelope(
            422, "bad_request",
            f"{loc}: {first.get('msg', 'invalid request body')}",
            {"n_errors": str(len(errs)),
             "fields": ", ".join(".".join(str(p) for p in (e.get("loc") or [])[1:]) for e in errs[:8])},
        )

    @app.exception_handler(Exception)
    def _on_unhandled(request: Request, exc: Exception) -> JSONResponse:
        """The last resort. It **prints the traceback to the server console** — a 500 the user cannot
        act on is at least a 500 the developer can."""
        traceback.print_exc()
        return _envelope(500, "io_error", f"{type(exc).__name__}: {exc}",
                         {"route": request.url.path})

    # ---------------------------------------------------------------------------------------------
    # The routers
    # ---------------------------------------------------------------------------------------------
    app.include_router(routes_core.router)

    # ⭐ THE FEATURES. Importing one registers its document hooks with core
    # (`core.document.register_feature`), which is what lets `core.document.load()` open its
    # documents and what puts its counts on a browser card. Import it here and nowhere else.
    from camea.features.mosaic import document as mosaic_document  # noqa: F401 — registers the hooks
    from camea.features.mosaic import routes as mosaic_routes

    # ⭐ The injection (see the module docstring, point 2). A feature never imports `camea.api`.
    mosaic_routes.set_session_provider(routes_core.SESSIONS.get)
    app.include_router(mosaic_routes.router)

    @app.get("/", include_in_schema=False)
    def _root() -> dict:
        """No front end is bundled yet. Point a human at the docs rather than at a 404."""
        return {
            "app": "Camea",
            "version": camea.__version__,
            "docs": "/docs",
            "openapi": "/openapi.json",
            "health": "/api/health",
            "note": "The UI is served by the Vite dev server in --browser; see `camea --help`.",
        }

    app.state.started_at = time.time()
    return app


#: The module-level app, for `uvicorn camea.api.app:APP`. `create_app()` is what the launcher and the
#: tests call — a fresh app per test process, with no shared FastAPI state.
APP = create_app()
