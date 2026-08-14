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
    MeaChannelTrace,
    MeaChipActivity,
    MeaChipLayout,
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


# =================================================================================================
# Opening one recording — the chip, what happened on it, and one pad's trace
# =================================================================================================
#
# ⭐ **THIS IS THE WHOLE OF PLAN 003's BACKEND, AND IT IS SMALL ON PURPOSE.** `core/mearecording.py`
# already reads these files and `MeaRecording.activity()` already does the tally; these three routes
# resolve *which file* and hand back what it says.
#
# ⭐ **THE EXISTING `get_mea_trace` IN `features/videomosaic/routes.py` IS THE MODEL, NOT THE
# TARGET.** It answers the same question for a pad clicked in a *mosaic*, and two thirds of it is
# resolving a `col-row` id through the chip's seating to a channel. ⛔ **None of that belongs here:
# the click already knows its channel**, because the chip map was drawn from the file's own
# coordinates. What was reproduced deliberately is the half that is about being honest — the window
# clamping, `MAX_TRACE_SECONDS`, the spike window, `first_spike_s`, `trace_health` and the
# `RawUndecodable` arm. ⛔ And the two were NOT refactored to share: they answer different questions,
# and the thing they genuinely share (`core/mearecording.py`) is already shared.
#
# ⛔ **AND THERE IS NO SEATING WARNING HERE, EVER.** No `orientation` on any payload, no
# "provisional" anything. There is no microscope in this task; the file states its own `electrode`,
# `x_um` and `y_um`, so every id is exact. Importing that doubt would make the screen lie.

#: How much trace one request may return. A 300 s window at 20 kHz is 6M floats — far past what a
#: chart can draw and past what JSON should carry. The UI asks for the window it is drawing.
#: ⚠️ Same number and same reason as the videomosaic route's; deliberately not imported from it,
#: because a feature must not depend on another feature.
MAX_TRACE_SECONDS = 30.0


def _recording_path(analysis_id: str, recording_id: str) -> tuple[Path, dict]:
    """⭐ **THE ONE PLACE THESE THREE ROUTES DECIDE WHICH FILE TO OPEN.** -> `(path, entry)`.

    A `referenced` recording is read from `source_path`; a `stored` one from the project's own copy.
    ⚠️ That resolution is `recordings.open_path` and it is called here and nowhere else — three
    routes each deciding for themselves is exactly how one ends up on a stale copy while another is
    on the original, and the symptom would be two halves of this same screen disagreeing about the
    same recording (plan 002 § Decisions built it for this; plan 003 § Approach asks for it).

    ⛔ Refuses by name rather than 500ing when there is no file at either address — that is the
    *"this recording is no longer where you left it"* case, and it is a fact about his data.
    """
    from . import recordings as mrec

    doc, ws = _mea_project(analysis_id)
    recs = list(doc.get("recordings") or [])
    entry = next((r for r in recs if str(r.get("id")) == recording_id), None)
    if entry is None:
        raise ApiError(404, "not_found", f"no recording {recording_id!r} in this project")

    path = mrec.open_path(ws.folder_of(analysis_id), entry)
    if path is None:
        raise ApiError(
            409, "refused",
            f"{entry.get('label') or recording_id} is no longer where you left it "
            f"({entry.get('source_path') or 'no path recorded'}), and Camea has no copy of it.",
            {"recording_id": recording_id, "source_path": str(entry.get("source_path") or "")},
        )
    return path, entry


def _open(analysis_id: str, recording_id: str):
    """`_recording_path`, opened. Raises the refusal by name if the file stopped being readable.

    ⚠️ **IT TOUCHES THE MAPPING, NOT JUST THE HEADER, AND THAT IS THE POINT OF THE FUNCTION.**
    `info()` reads the header only; the chip's geometry is derived in `mapping()`, and
    `derive_geometry` **refuses by design** for real cases it cannot explain — every routed pad on
    one array row, a non-integer stride, positions that are not whole multiples of one pitch. Every
    route below then reaches for the mapping (directly, or through `stride()`/`activity()`), so
    unless it is touched *here* that refusal escapes as an unhandled error and the screen shows a
    **500** for a file Camea understands perfectly well and has a sentence about. Found in review;
    reproduced with a one-row mapping, which returned 500 from all three routes.
    """
    from camea.core import mearecording as mr  # noqa: PLC0415

    from . import recordings as mrec

    path, entry = _recording_path(analysis_id, recording_id)
    label = str(entry.get("label") or recording_id)
    rec = None
    try:
        rec = mr.MeaRecording(path)
        rec.info()                                           # the header…
        rec.mapping()                                        # …and the chip, so a bad file fails HERE
    except mr.MeaError as e:
        # ⛔ **NOT "this is not a MaxLab recording".** It got onto the shelf, so its header read
        # fine; what failed is deriving the chip's layout, and `derive_geometry` already says
        # exactly why ("the routed electrodes all sit on one array row", a non-integer stride…).
        # Calling a genuine MaxLab file "not a MaxLab recording" is a **lie about his data** — the
        # same mistake `utils/knowledge/mea-recordings.md` records against ActivityScan/000687 —
        # so the reader's own sentence is passed through whole.
        if rec is not None:
            rec.close()                                      # ⛔ never leak the handle on the way out
        raise ApiError(422, "refused",
                       f"Camea cannot work out the chip layout for {label}: {e}",
                       {"recording_id": recording_id, "reason": str(e)}) from e
    except Exception as e:                                   # noqa: BLE001
        # ⚠️ The file is at the address and no longer reads at all — it changed under him. Same
        # sentence the import would have given it, so he meets one refusal about this file, not two.
        # ⚠️ And the technical tail rides in `detail.reason`, never spliced into the sentence: that
        # separation is `NotARecording`'s whole design (plan 002).
        if rec is not None:
            rec.close()
        bad = mrec.NotARecording(path, f"{type(e).__name__}: {e}")
        raise ApiError(422, "refused", str(bad),
                       {"recording_id": recording_id, "reason": bad.reason}) from e
    return rec, entry


def _chip_rows(stride: int, mapping) -> tuple[int, str]:
    """How tall the whole chip is, and **how we know** -> `(rows, "device" | "recorded")`.

    ⭐ **HIS ANSWER, 2026-08-14: draw the WHOLE chip, with the recorded pads in their real place on
    it.** Which needs the chip's full size — and only half of that is in the file.

    * The **width** is `stride`, which the file's own numbering states and `derive_geometry`
      verifies against every routed pad. No question there.
    * The **height** is not in the file at all. A MaxOne routes ~1k channels of tens of thousands,
      so a recording that routed a corner block evidences *only that corner* — measured on this
      project's mirror, one recording routes 63x57 at the origin while another routes 216x111. Take
      the largest routed row and you would draw that first recording's chip less than half its true
      height, and the whole point of his answer (*"which part of the culture was recorded"*) is lost.

    So the one device fact Camea holds is **consulted**: `core.electrodegrid.MAXWELL` is R45.8's
    single place for a device number (*"the standard MaxOne/MaxTwo sensor area is 26,400 electrodes
    = 220 x 120, with 17.5 µm pitch"*), and its `axes` are deliberately **orientation-free**. So if
    the stride this file derived IS one of those axes, the chip's other axis is the other one.

    ⛔ **CONSULTED, NEVER ASSUMED — and that is the whole safety argument.** A file whose derived
    stride does not match the device is drawn as **what it actually shows**, and says so through
    `chip_extent`. Nothing is imposed on a file that did not ask for it, and no device number is
    written down here: it is read from the one place that holds it. ⛔ It is also not dataset
    knowledge (I1) — a device's physical shape is not a fact about anybody's culture, and the app
    still knows nothing about a plate, a run, or how active a chip should be.
    """
    from camea.core import electrodegrid as core_electrodegrid  # noqa: PLC0415

    for axis in core_electrodegrid.MAXWELL.axes:
        if int(axis) == int(stride):
            other = [a for a in core_electrodegrid.MAXWELL.axes if int(a) != int(stride)]
            return int(other[0] if other else axis), "device"
    # No device matches, so claim only what this file evidences — never more.
    return (int(mapping["ey"].max()) + 1 if mapping.size else 0), "recorded"


@router.get("/api/mea/{analysis_id}/recordings/{recording_id}/layout",
            response_model=MeaChipLayout)
def get_mea_layout(analysis_id: str, recording_id: str) -> dict:
    """The chip as this recording describes it — every routed pad, at its own µm position.

    ⭐ **ONLY THE ROUTED PADS.** A MaxOne routes ~1k channels out of tens of thousands of pads, so
    most of the chip carries no data at all — and a pad that was never routed is not a measurement
    of silence, it is the *absence* of a measurement. Drawing them would invent data.

    ⭐ `stride` and `pitch_um` are **derived from the file's own numbering and verified against every
    routed pad**, never taken from a datasheet. ⚠️ And never measured from the routed spacing: one of
    this project's recordings routed every other pad, so the smallest routed gap is twice the truth.

    ⛔ Needs no proprietary decoder — the mapping table is plain HDF5.
    """
    rec, entry = _open(analysis_id, recording_id)
    try:
        info = rec.info()
        m = rec.mapping()
        stride = rec.stride()
        rows, extent = _chip_rows(stride, m)
        return {
            "analysis_id": analysis_id,
            "recording_id": recording_id,
            "label": str(entry.get("label") or info.label),
            "run_id": str(entry.get("run_id") or info.run_id),
            "assay": str(entry.get("assay") or info.assay),
            "pads": [{"channel": int(p["channel"]), "electrode": int(p["electrode"]),
                      "x_um": float(p["x_um"]), "y_um": float(p["y_um"])} for p in m],
            "stride": stride,
            "pitch_um": rec.pitch_um(),
            "chip_cols": stride,
            "chip_rows": rows,
            "chip_extent": extent,
            "n_channels": info.n_channels,
            "n_samples": info.n_samples,
            "duration_s": info.duration_s,
            "sampling_hz": info.sampling_hz,
            "n_spikes": info.n_spikes,
        }
    finally:
        rec.close()


@router.get("/api/mea/{analysis_id}/recordings/{recording_id}/activity",
            response_model=MeaChipActivity)
def get_mea_activity(analysis_id: str, recording_id: str) -> dict:
    """The per-pad tally the chip map is coloured by — one row per routed pad, in `layout` order.

    ⭐ **A GET, NOT A JOB, AND THAT WAS MEASURED** (plan 003 § Open asked). One pass over the spike
    table of a real 300 s recording: **2.3–21 ms** end to end including the layout, over all five
    readable recordings in the mirror (the worst is 982 channels × 244,925 spikes at 21 ms). Nothing
    here is slow enough to need a spinner, let alone a job — so it is a plain GET and the screen
    draws on the first paint.

    ⭐ **AND IT NEEDS NO PROPRIETARY DECODER**, because the spike table is written uncompressed by
    the on-chip detector. This is the reason the chip map is worth building before the decoder
    problem is solved: it is exactly right on a machine where the waveform is a rail.

    ⛔ A count. Not a rate per neuron, not a burst, not a verdict on whether the culture is healthy
    (I1) — and `max_rate_hz` is the busiest pad *in this recording*, so the UI can scale its colours
    to the file in front of it. There is no number in Camea for how active a chip should be.
    """
    rec, _entry = _open(analysis_id, recording_id)
    try:
        info = rec.info()
        act = rec.activity()
        return {
            "analysis_id": analysis_id,
            "recording_id": recording_id,
            "pads": [{"channel": int(a["channel"]), "n_spikes": int(a["n_spikes"]),
                      "rate_hz": float(a["rate_hz"])} for a in act],
            "duration_s": info.duration_s,
            "n_spikes": info.n_spikes,
            "n_pads": int(act.size),
            "n_silent": int((act["n_spikes"] == 0).sum()),
            "max_rate_hz": float(act["rate_hz"].max()) if act.size else 0.0,
        }
    finally:
        rec.close()


@router.get("/api/mea/{analysis_id}/recordings/{recording_id}/trace",
            response_model=MeaChannelTrace)
def get_mea_channel_trace(analysis_id: str, recording_id: str,
                          channel: int = Query(..., description="The routed channel that was "
                                                                "clicked on the chip map."),
                          t0: float = 0.0, t1: float | None = None) -> dict:
    """One pad's stored waveform and its spikes, for the window `[t0, t1)`.

    ⭐ **BY CHANNEL, BECAUSE THE CLICK ALREADY KNOWS ITS CHANNEL.** The chip map was drawn from
    `layout`, so the dot he clicked carries its own channel — there is nothing to resolve and no
    seating to guess. ⛔ That is the whole difference from the videomosaic trace route, and it is why
    the two are separate rather than shared.

    ⚠️ **`health` IS NOT DECORATION.** The published MaxWell decoder does not reconstruct this
    project's files, and a railed window drawn without that caveat looks exactly like a genuinely
    silent electrode. ⭐ The spikes are unaffected — the on-chip detector wrote them uncompressed —
    so they are returned and drawn even when the waveform is refused.
    """
    from camea.core import mearecording as mr  # noqa: PLC0415

    rec, _entry = _open(analysis_id, recording_id)
    try:
        info = rec.info()
        m = rec.mapping()
        base = {"analysis_id": analysis_id, "recording_id": recording_id, "channel": int(channel),
                "duration_s": info.duration_s, "sampling_hz": info.sampling_hz}

        hit = m[m["channel"] == int(channel)]
        if hit.size == 0:
            # ⭐ The ordinary answer, and a FACT rather than a failure: this pad was never routed.
            # The chip map only draws routed pads, so a click cannot normally land here — but a
            # stale URL or a recording swapped under him can, and it must not read as an error.
            return {**base, "recorded": False, "t0_s": 0.0, "t1_s": 0.0}

        end = info.duration_s if t1 is None else float(t1)
        start = max(0.0, float(t0))
        end = min(end, start + MAX_TRACE_SECONDS, info.duration_s)
        if end <= start:
            raise ApiError(422, "refused", "the requested window is empty")

        spikes = rec.spikes_of_channel(channel)
        # Where the activity starts, so the caller can open ITS window somewhere worth looking
        # rather than at t=0. ⚠️ Clamped at 0: a few spikes are logged during the pre-roll, i.e.
        # before the first stored sample, and a negative window start is not a real window.
        first = float(max(0.0, spikes["t_s"].min())) if spikes.size else None
        window = spikes[(spikes["t_s"] >= start) & (spikes["t_s"] < end)]
        out: dict = {
            **base,
            "recorded": True,
            "electrode": int(hit["electrode"][0]),
            "x_um": float(hit["x_um"][0]),
            "y_um": float(hit["y_um"][0]),
            "t0_s": start,
            "t1_s": end,
            "n_spikes_total": int(spikes.size),
            "first_spike_s": first,
            "spikes": [{"t_s": float(s["t_s"]), "amplitude_uv": float(s["amplitude_uv"])}
                       for s in window],
        }
        try:
            out["trace_uv"] = [float(v) for v in rec.trace(channel, start, end)]
            out["health"] = rec.trace_health(channel, start, end).as_dict()
        except mr.RawUndecodable as e:
            # ⭐ The spikes above are still exactly right — return them, and say the waveform is
            # unavailable rather than drawing a flat line that looks like a silent electrode.
            out["trace_uv"] = []
            out["health"] = None
            out["decode_error"] = str(e)
        return out
    finally:
        rec.close()


__all__ = ["router", "ApiError", "set_store", "FEATURE", "DEFAULT_NAME", "MAX_TRACE_SECONDS"]
