"""The `mea` API — create a project with its recordings on it, and manage that shelf.

Same contracts as everywhere else in Camea:
- ⭐ THE SERVER CREATES THE DOCUMENT (`POST /api/mea/projects` mirrors
  `POST /api/videomosaic/projects`, minus the probe a task with no input file cannot do);
- errors are the `ErrorEnvelope`, raised through this router's own `ApiError` (the
  `HTTPException` subclass pattern — see `features/videomosaic/routes.py`);
- the store arrives through the `set_store` seam, because a feature never imports `camea.api`.

⭐ **CREATE-WITH-RECORDINGS IS ONE CALL** (his instruction, 2026-08-14, plan 002). *"You create the
project then you select what you want to do in this project ... then after that it asks you to
upload the files you need for that task."* So the wizard's Files step hands its chosen paths to
this one route, and there is **no moment where a project exists with nothing on it because a second
call failed** — a stranded project he can see on the home screen and cannot use is a mess he would
have to clear up by hand before he could try again.

⚠️ **AND `paths` IS OPTIONAL, BECAUSE THE EMPTY SHELF IS STILL A REAL STATE.** A project whose
recordings he has since removed is empty and must keep working; `POST` with no `paths` is exactly
what plan 001 shipped.

⛔ **NOTHING IS WRITTEN OUTSIDE THE PROJECT.** Everything this module puts on disk goes into
`%LOCALAPPDATA%/Camea/projects/<analysis_id>/` — the manifest, the document, and (plan 002) the
project's own copies of the recordings under `recordings/`. ⛔ **The user's `.h5` files are opened
read-only and are never modified or moved**, which matters more here than anywhere else in Camea:
this is the first thing in the app that reads from his 35 GB mirror in order to copy out of it.

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

⚠️ **Plan 002 did not change this.** Its recordings are entries in the DOCUMENT, each with its
own `source_path`; they are not a dataset and they must not become one. ⛔ In particular
`source_path` did **not** become the project's `data_dir`: a recording is a file the shelf holds,
and there may be several, from anywhere.

Import discipline: no h5py, no numpy work, nothing heavy at MODULE scope — `/openapi.json` must
import clean. `features/mea/recordings.py` is imported lazily inside the handlers that read a file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from fastapi import APIRouter, Query
from fastapi.exceptions import HTTPException

from camea.api.schemas import (  # schemas is deliberately importable by features
    AddMeaRecordingsRequest,
    AnalysisSummary,
    CreateMeaProjectRequest,
    ErrorCode,
    MeaBrowseResult,
    MeaShelf,
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
# The shelf's plumbing
# =================================================================================================


def _mea_project(analysis_id: str) -> tuple[dict, core_project.ProjectSet]:
    """The project's document, or the right refusal. Shared by every shelf route.

    ⛔ Refuses a project of another task by name (409), the way `_video_project` does. The feature
    string on the manifest is the gate, and it is the only thing that decides which screens and
    which routes a project answers to."""
    ws = _projects()
    try:
        doc, _ = core_document.load_analysis(ws, analysis_id)
    except FileNotFoundError as e:
        raise ApiError(404, "no_document", f"analysis {analysis_id} has no document") from e
    except Exception as e:                                   # noqa: BLE001
        raise _project_error(e) from e
    if doc.get("feature") != FEATURE:
        raise ApiError(409, "refused",
                       f"analysis {analysis_id} is a {doc.get('feature')!r} project, "
                       "not an Analyze MEA project")
    return doc, ws


def _read_paths(paths: list[str]) -> list[dict]:
    """Every path -> a document entry, or the refusal that names the first bad one.

    ⭐ **ALL OR NOTHING.** One unreadable file and none of them are added. The alternative — take
    the good ones and report the rest — has nowhere to live at *creation* (the response there is
    the project itself), and one rule he can state to himself beats two that differ by which door
    he came through. ⛔ And the refusal NAMES the file: a path silently dropped from an import is
    the exact failure plan 002 calls out.
    """
    from . import recordings as mrec

    out: list[dict] = []
    for p in paths:
        raw = (p or "").strip()
        if not raw:
            continue
        try:
            out.append(mrec.record_for(raw))
        except mrec.NotARecording as e:
            raise ApiError(400, "bad_request", str(e),
                           {"path": e.path, "reason": e.reason}) from e
    return out


def _save_recordings(ws: core_project.ProjectSet, analysis_id: str,
                     recs: list[dict]) -> dict:
    """Write `recordings` into the SAVED document. -> the saved doc.

    ⭐ Always re-loads fresh under the lock, never writes back a document captured earlier: several
    copy jobs are flipping their own entries to `stored` at the same time, and a stale write would
    silently drop one of those flips. See `recordings.py`'s module docstring.
    """
    from . import recordings as mrec

    with mrec._DOC_LOCK:
        fresh, _ = core_document.load_analysis(ws, analysis_id)
        fresh["recordings"] = recs
        saved = core_document.save_analysis(ws, analysis_id, fresh)
        core_document.DOCUMENTS.put(saved["doc"], ws.document_path(analysis_id))
        return saved["doc"]


def _patch_recording(analysis_id: str, recording_id: str, changes: dict) -> None:
    """Apply `changes` to ONE recording in the saved document. The copy job's way home.

    ⚠️ Runs on a worker thread, minutes after the request that started it returned — so it resolves
    the store afresh and swallows a project that has been deleted meanwhile. A copy that lands after
    its project is gone is not an error; it is a race the user won.
    """
    from . import recordings as mrec

    try:
        ws = _projects()
        with mrec._DOC_LOCK:
            fresh, _ = core_document.load_analysis(ws, analysis_id)
            recs = list(fresh.get("recordings") or [])
            hit = next((r for r in recs if str(r.get("id")) == recording_id), None)
            if hit is None:
                return                                       # removed while its copy was running
            recs = [({**r, **changes} if r is hit else r) for r in recs]
            fresh["recordings"] = recs
            saved = core_document.save_analysis(ws, analysis_id, fresh)
            core_document.DOCUMENTS.put(saved["doc"], ws.document_path(analysis_id))
    except Exception:                                        # noqa: BLE001
        pass                                                 # never take a job down over bookkeeping


def _start_copies(ws: core_project.ProjectSet, analysis_id: str, recs: list[dict]) -> None:
    """Kick off one copy job per new recording — see `recordings.py` for why per recording."""
    from . import recordings as mrec

    folder = ws.folder_of(analysis_id)
    for rec in recs:
        def save(rid: str, changes: dict) -> None:
            _patch_recording(analysis_id, rid, changes)
        try:
            mrec.start_copy(folder, analysis_id, rec, save)
        except Exception:                                    # noqa: BLE001
            # ⛔ A copy that will not start must never fail the import. The recording is on the
            # shelf and readable from the original, which is the whole point of "reference it until
            # the copy is finished".
            _patch_recording(analysis_id, str(rec.get("id") or ""),
                             {"copy_state": "failed",
                              "copy_error": "the copy could not be started"})


def _shelf(ws: core_project.ProjectSet, analysis_id: str, doc: dict) -> dict:
    from . import recordings as mrec

    return {"analysis_id": analysis_id,
            "recordings": mrec.shelf(ws.folder_of(analysis_id), doc)}


# =================================================================================================
# Routes
# =================================================================================================
@router.post("/api/mea/projects", status_code=201, response_model=AnalysisSummary)
def post_mea_project(body: CreateMeaProjectRequest) -> dict:
    """⭐ **THE SERVER CREATES THE DOCUMENT** — `POST /api/projects` for the standalone MEA task.
    A name and the recordings the wizard picked go in; a project with those already on its shelf
    comes out. No session, no probe, no folder.

    ⭐ **EVERY PATH IS READ BEFORE THE PROJECT EXISTS.** That ordering is the whole reason this is
    one call: if one of them is not a MaxLab recording, the refusal names it and **no project is
    created**, so there is nothing for him to clean up before trying again.

    The project carries `dataset_key=""` / `dataset=""` / `data_dir=""` — see the module
    docstring for why an empty key beats a minted one, and what was read to decide it. ⛔ A
    recording's `source_path` does **not** become `data_dir`: the shelf may hold several, from
    anywhere, and none of them is "the project's dataset".
    """
    name = body.name.strip() or DEFAULT_NAME
    records = _read_paths(list(body.paths))                  # ⭐ refuses BEFORE anything is made

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
        # ⭐ The recordings go on the shelf in the SAME save the document is first written by. The
        # payload is authored empty (`document.new_payload` refuses to be seeded) and filled here,
        # so there is exactly one shape of `recordings` entry in the app and it is minted in one
        # place — `recordings.record_for`.
        doc["recordings"] = records
        core_document.save_analysis(ws, pr.analysis_id, doc)
    except core_document.ValidationError as e:
        _abandon(pr)
        # ⚠️ `str(e)`, NOT `"; ".join(e.args[0])`. `ValidationError.__init__` has already joined
        # `.problems` into one string, so `args[0]` is that string — and joining a string iterates
        # its CHARACTERS ("bad thing" -> "b; a; d; ..."). The sibling video route still carries the
        # copy this was taken from; it is filed, not silently fixed here.
        raise ApiError(400, "bad_request", str(e)) from e
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
    # ⚠️ **After the document is safely on disk, and never before.** The copy jobs write back into
    # that document; starting one against a document that does not exist yet is a race with a
    # guaranteed loser. A copy that fails to start does not fail the create — the recording is
    # readable from the original either way.
    if records:
        _start_copies(_projects(), pr.analysis_id, records)
    return pr.summary().to_json()


# =================================================================================================
# The shelf
# =================================================================================================


@router.get("/api/mea/browse", response_model=MeaBrowseResult)
def get_mea_browse(path: str = Query(..., description="The folder to look under.")) -> dict:
    """⭐ **THE ONE ROUTE WITH NO PROJECT.** Every `data.raw.h5` under `path`, with enough of each
    file's own facts that he can tell which ones he means before he ticks them.

    ⚠️ **It has no `analysis_id`, and must never be given one "for consistency"** — the wizard calls
    it *before a project exists*. That is precisely what makes one import component mountable in two
    places: it browses, it lists, it hands back the paths he ticked, and it creates nothing.

    ⛔ It reads and never writes. ⭐ And it is the picker he will actually use: the native
    multi-select dialog only exists with `--window`, and he drives Camea over VSCode remote where
    that route is a 501.
    """
    from . import recordings as mrec

    root = Path((path or "").strip()).expanduser()
    if not root.is_dir():
        raise ApiError(400, "bad_request", f"there is no folder at {root.as_posix()}")
    try:
        rows, truncated = mrec.candidates(root)
    except OSError as e:
        raise ApiError(500, "io_error", f"could not read {root.as_posix()}: {e}") from e
    return {"path": root.as_posix(), "recordings": rows, "truncated": truncated}


@router.get("/api/mea/{analysis_id}/recordings", response_model=MeaShelf)
def get_mea_recordings(analysis_id: str) -> dict:
    """Everything on this project's shelf, with **live** copy state.

    Every number is read off the file on the way past — see `recordings.shelf_entry`. That is what
    makes a recording whose original has moved say so, instead of showing a row of zeros.
    """
    doc, ws = _mea_project(analysis_id)
    return _shelf(ws, analysis_id, doc)


@router.post("/api/mea/{analysis_id}/recordings", status_code=201, response_model=MeaShelf)
def post_mea_recordings(analysis_id: str, body: AddMeaRecordingsRequest) -> dict:
    """Add several recordings at once — *"opens file explorer, can import multiple at a time"*.

    Each one is read to confirm it is a MaxLab recording (⛔ refused **by name** if it is not, and
    then none of them are added), recorded as `referenced`, and given a copy job. He can open any of
    them the moment this returns; the copies land behind him.

    ⭐ This is the same work `POST /api/mea/projects` does with its `paths`, through the same three
    functions — so the wizard's Files step and the in-project button cannot drift apart.
    """
    doc, ws = _mea_project(analysis_id)
    records = _read_paths(list(body.paths))
    if not records:
        raise ApiError(400, "bad_request", "no recordings were given to add")

    recs = [*(doc.get("recordings") or []), *records]
    saved = _save_recordings(ws, analysis_id, recs)
    _start_copies(ws, analysis_id, records)
    return _shelf(ws, analysis_id, saved)


@router.delete("/api/mea/{analysis_id}/recordings/{recording_id}", response_model=MeaShelf)
def delete_mea_recording(analysis_id: str, recording_id: str) -> dict:
    """Forget a recording, and delete **Camea's copy** of it.

    ⛔ **THE USER'S ORIGINAL IS NEVER TOUCHED**, and there is no confirm box, because there is
    nothing of his to lose: the only bytes removed are a copy Camea made itself, inside the project
    folder (his ruling, 2026-08-14). A copy still in flight is cancelled first.
    """
    doc, ws = _mea_project(analysis_id)
    from . import recordings as mrec

    recs = list(doc.get("recordings") or [])
    gone = next((r for r in recs if str(r.get("id")) == recording_id), None)
    if gone is None:
        raise ApiError(404, "not_found", f"no recording {recording_id!r} in this project")

    mrec.forget(ws.folder_of(analysis_id), gone)
    saved = _save_recordings(ws, analysis_id, [r for r in recs if r is not gone])
    return _shelf(ws, analysis_id, saved)


__all__ = ["router", "ApiError", "set_store", "FEATURE", "DEFAULT_NAME"]
