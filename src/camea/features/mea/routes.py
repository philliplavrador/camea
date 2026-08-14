"""The `mea` API — create a project, and (for now) nothing else.

Same contracts as everywhere else in Camea:
- ⭐ THE SERVER CREATES THE DOCUMENT (`POST /api/mea/projects` mirrors
  `POST /api/videomosaic/projects`, minus the probe a task with no input file cannot do);
- errors are the `ErrorEnvelope`, raised through this router's own `ApiError` (the
  `HTTPException` subclass pattern — see `features/videomosaic/routes.py`);
- the store arrives through the `set_store` seam, because a feature never imports `camea.api`.

⭐ **THIS TASK ASKS ZERO PATH QUESTIONS** — one fewer than any other feature in the app. R44
already said the user never names where a project *goes*; here he does not name where the data
comes *from* either, because at creation there is no data. He types a name, picks the task, and
he is in the project. Recordings are added from inside it (plan 002).

⛔ **AND IT WRITES NOTHING OUTSIDE THE PROJECT.** The whole of this module's disk contact is
`Project.create_in_store` + `save_analysis`, both of which land inside
`%LOCALAPPDATA%/Camea/projects/<analysis_id>/` and both of which go through
`core.workspace.refuse_write`.

---------------------------------------------------------------------------------------------
⭐ **THE `dataset_key` DECISION, RECORDED — plan 001 § Open left this one to the build.**
---------------------------------------------------------------------------------------------
A new `mea` project is created with **`dataset_key=""`, `dataset=""`, `data_dir=""`**, not with
a key minted from the analysis id. The choice was made by reading what the empty string actually
does in the four places that touch it, not by taste:

* `ProjectSet.analyses()` filters on `dataset_key` **only when a caller passes one**
  (`if dataset_key is not None`), so an empty key is never filtered off the home screen.
* `by_dataset()` groups on it, so every `mea` project lands in one `""` bucket. Its single
  consumer is `routes_core._analyses_index()`, whose result is looked up **by a real dataset's
  key** to decorate a browser card with "you already have work here". Nobody ever asks for the
  `""` bucket, so it costs nothing and misleads nobody.
* `workspace.guard_slot` and `document.Scope.agrees_with` **both abstain on a blank**
  (`if dkey and man.get("dataset_key") and ...`). A blank key is therefore permissive — which is
  what a project whose contents arrive later needs — where a minted one would be a hard identity
  asserted about data that does not exist yet.
* `read_analysis` copies it straight onto `AnalysisSummary`; the home-screen card renders
  `dataset` (blank ⇒ the card says so in words) and `data_dir` (blank ⇒ the line is absent).
  Nothing breaks and nothing shows a placeholder.

A minted key would have bought exactly one thing — a private bucket in an index nobody reads —
at the price of the app claiming there is a dataset at an address that resolves to nothing.
⛔ *A key is an address, not a fact about the data at it*, and here there is no address. So:
empty, and honestly empty.

⚠️ **Plan 002 does not change this.** Its recordings are entries in the DOCUMENT, each with its
own `source_path`; they are not a dataset and they must not become one.

Import discipline: no h5py, no numpy work, nothing heavy — `/openapi.json` must import clean.
"""

from __future__ import annotations

from typing import Callable

from fastapi import APIRouter
from fastapi.exceptions import HTTPException

from camea.api.schemas import (  # schemas is deliberately importable by features
    AnalysisSummary,
    CreateMeaProjectRequest,
    ErrorCode,
)
from camea.core import document as core_document
from camea.core import project as core_project
from camea.core import workspace as core_workspace

from .document import FEATURE

router = APIRouter()

#: What an unnamed project is called. The name box is optional and a project with no name at
#: all is unfindable on the home screen; every other feature falls back to something about its
#: input (the video's stem), and this one has no input to fall back to.
DEFAULT_NAME = "Untitled MEA project"


class ApiError(HTTPException):
    """The `{"error": {"code", "message", "detail"}}` envelope, raised. Subclasses
    `HTTPException` so a wiring miss degrades the body, never the status (the mosaic
    router's reasoning, verbatim)."""

    def __init__(self, status: int, code: ErrorCode, message: str,
                 detail: dict[str, str] | None = None) -> None:
        self.code = code
        self.message = message
        self.info = dict(detail or {})
        super().__init__(
            status_code=status,
            detail={"code": code, "message": message,
                    **({"detail": self.info} if self.info else {})},
        )


# =================================================================================================
# The store seam — a feature never imports the api layer; app.py injects this at startup.
# =================================================================================================
_PROJECTS_PROVIDER: Callable[[], core_project.ProjectSet] | None = None


def set_store(projects: Callable[[], core_project.ProjectSet]) -> None:
    global _PROJECTS_PROVIDER
    _PROJECTS_PROVIDER = projects


def _projects() -> core_project.ProjectSet:
    """The store (R44), fresh per call — the same one `routes_core` serves from."""
    if _PROJECTS_PROVIDER is None:
        raise RuntimeError("mea routes not wired: call "
                           "camea.features.mea.routes.set_store() at startup")
    return _PROJECTS_PROVIDER()


def _project_error(e: Exception) -> ApiError:
    """The same mapping `routes_core` uses — a refused place is 409, never a 400/500."""
    if isinstance(e, core_workspace.DatasetIsReadOnly):
        return ApiError(409, "refused", str(e))
    if isinstance(e, core_project.PathRefused):
        return ApiError(409, "refused", str(e))
    if isinstance(e, core_project.NoSuchProject):
        return ApiError(404, "not_found", str(e))
    if isinstance(e, core_workspace.WorkspaceError):
        return ApiError(400, "bad_request", str(e))
    if isinstance(e, OSError):
        return ApiError(500, "io_error", str(e))
    return ApiError(400, "bad_request", str(e))


def _abandon(pr: core_project.Project) -> None:
    """Tear a half-made project back down, so a failed create leaves nothing on the home screen.
    It is in the store, so `delete()` takes the whole folder — there is nothing of the user's in
    it to spare, and there never was: he has not seen it yet."""
    try:
        pr.delete()
    except Exception:                                        # noqa: BLE001
        pass


# =================================================================================================
# Routes
# =================================================================================================
@router.post("/api/mea/projects", status_code=201, response_model=AnalysisSummary)
def post_mea_project(body: CreateMeaProjectRequest) -> dict:
    """⭐ **THE SERVER CREATES THE DOCUMENT** — `POST /api/projects` for a project that starts
    empty. A name in, a project out, and there is nothing else to ask: no session, no probe, no
    folder. The document is an empty shelf (`features/mea/document.py`).

    The project carries `dataset_key=""` / `dataset=""` / `data_dir=""` — see the module
    docstring for why an empty key beats a minted one, and what was read to decide it.
    """
    name = body.name.strip() or DEFAULT_NAME

    try:
        pr = core_project.Project.create_in_store(
            feature=FEATURE,
            name=name,
            dataset_key="",
            dataset="",
            data_dir="",
        )
    except Exception as e:                                   # noqa: BLE001
        raise _project_error(e) from e

    ws = core_project.ProjectSet([pr.path.as_posix()])
    try:
        doc = core_document.new_document(
            feature=FEATURE,
            id=pr.analysis_id,
            dataset="",
            dataset_key="",
            data_dir="",
            experiment="",
            name=name,
        )
        core_document.save_analysis(ws, pr.analysis_id, doc)
    except core_document.ValidationError as e:
        _abandon(pr)
        raise ApiError(400, "bad_request",
                       "; ".join(e.args[0]) if e.args else str(e)) from e
    except core_document.DocumentError as e:
        _abandon(pr)
        raise ApiError(400, "bad_request", str(e)) from e
    except Exception as e:                                   # noqa: BLE001
        # ⚠️ Anything at all — an unwritable store, a full disk. A half-made project must not
        # reach the home screen, whatever the reason it failed to finish.
        _abandon(pr)
        raise _project_error(e) from e

    # Nothing to remember: the project is in the store, and the store is the index (R44).
    core_document.DOCUMENTS.put(doc, pr.document_path)
    return pr.summary().to_json()


__all__ = ["router", "ApiError", "set_store", "FEATURE", "DEFAULT_NAME"]
