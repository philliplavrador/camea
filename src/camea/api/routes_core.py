"""routes_core.py — **everything a SECOND feature would reuse unchanged.**

    health · gpu · settings · fs · datasets · sessions · tiles · workspace · documents · jobs · dialogs

⛔ **THERE IS NO MOSAIC IN THIS FILE.** No tile, no anchor, no pass split, no exclusion, no trial
number is special. Grep it: the word `mosaic` appears only as a *string the user chose* (a feature
name arriving in a request body) and never as a branch. The day feature #2 lands, nothing here moves.

THE FOUR THINGS THIS FILE OWES THE REST OF THE APP
--------------------------------------------------
1. ⭐ **THE SESSION REGISTRY.** A session is ONE PER DATASET, shared by every open feature, and holds
   **no analysis state** (`core.frames.FrameStore` — pixels, the one global tone window, and nothing
   else). It lives here because *core owns sessions*; `camea.api.app` hands `SESSIONS.get` to each
   feature router at startup, so a feature never imports the API layer and the dependency arrow
   (`api -> features -> core -> engine`) stays intact.

2. 🔴 **THE FOLDER PICKER THAT WORKS WITHOUT A NATIVE WINDOW** — `GET /api/fs/list`. In `--browser`
   and `--headless` there is no pywebview, so `/api/dialog/*` **cannot** open a native dialog and
   honestly returns `501 no_window`. v1 stopped there, and the consequence was that the entire app
   was unreachable in the two modes a developer and a test actually run it in: you could not choose a
   dataset, so you could not do anything. **A 501 with no alternative is a dead app.** `fs/list` is
   the alternative: it lists a directory's subfolders and says which of them are datasets, so the UI
   browses the filesystem itself. It is served in **every** mode, native window or not.

3. **LONG OPERATIONS RETURN A JOB.** `open` is the only one core has. It never blocks.

4. **THE ERROR ENVELOPE.** `ApiError` -> `{"error": {"code", "message", "detail"}}`, rendered by the
   handler in `camea.api.app`. A 400 must never be able to become a 500 over a wiring detail.

⚠️ **IMPORTS ARE LAZY WHERE THEY ARE HEAVY.** Importing this module must not drag in cv2, cupy or
spectralign: `/openapi.json` has to be inspectable on a machine where the engine cannot even load
(that is how the TypeScript client is generated in CI). `camea.core.frames` (cv2) and
`camea.engine.t27` (cupy) are imported **inside** the handlers that need them.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response

import camea
from camea.api.schemas import (
    AnalysisListResponse,
    AnalysisSummary,
    RenameAnalysisRequest,
    AutosaveRequest,
    CreateAnalysisRequest,
    DatasetDetail,
    DatasetListResponse,
    DatasetScanRequest,
    DialogOpenDirectoryRequest,
    DialogOpenFileRequest,
    DialogPathResponse,
    DialogSaveFileRequest,
    DocumentResponse,
    ErrorCode,
    FsEntry,
    FsListResponse,
    GpuInfo,
    HealthResponse,
    Job,
    JobCancelResponse,
    JobListResponse,
    JobRef,
    LoadDocumentRequest,
    LoadDocumentResponse,
    LogResponse,
    OkResponse,
    OpenSessionRequest,
    SaveDocumentRequest,
    SaveResult,
    SessionListResponse,
    SessionResponse,
    Settings,
    SettingsUpdate,
    TextureResponse,
    ThumbsResponse,
    Tone,
    ToneUpdate,
    ValidateDocumentRequest,
    ValidationReport,
    WorkspaceInfo,
    WorkspaceSetRequest,
)
from camea.core import dataset as core_dataset
from camea.core import document as core_document
from camea.core import workspace as core_workspace
from camea.core.jobs import JOBS, OPEN_PHASES, NotCancellable, phase_reporter
from camea.settings import SETTINGS

router = APIRouter(tags=["core"])

_T0 = time.time()

#: How deep `GET /api/datasets` walks each remembered root. `POST /api/datasets/scan` takes its own.
DEFAULT_SCAN_DEPTH = 3

#: The browser card's thumbnail. A picture, not a measurement.
THUMBNAIL_PX = 256

#: Frames sampled to window a thumbnail. The tone is **global over the sample**, never per-frame —
#: a per-frame stretch would make the card lie about which datasets are dim.
THUMBNAIL_SAMPLE = 8


# =================================================================================================
# Errors
# =================================================================================================
class ApiError(HTTPException):
    """The `{"error": {"code", "message", "detail"}}` envelope, raised.

    ⚠️ It subclasses `HTTPException` on purpose. `camea.api.app` renders it as an `ErrorEnvelope`; if
    that handler ever went missing, the **status code still survives** and the body merely degrades to
    FastAPI's `{"detail": ...}`. A 400 must never be able to become a 500 over a wiring detail — that
    is the bug shape that turned v1's refused document into an opaque 500 on every 2-second autosave.

    `camea.features.mosaic.routes.ApiError` is the same class in shape and is handled by the same
    handler. Two definitions, one envelope; the handler keys on the `code` attribute, not the type.
    """

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
# ⭐ THE SESSION REGISTRY — core owns sessions; features borrow them
# =================================================================================================
class Session:
    """An OPEN dataset: its pixels, in RAM. **ONE per dataset, shared by every open feature.**

    ⛔ **IT HOLDS NO ANALYSIS STATE.** No tile states. No exclusions. No blank list. No run. No pass
    split. Those are a feature's and they live in its DOCUMENT.

    That is not tidiness — it is the match endpoints' correctness proof. v1's session carried `blank`,
    which `PUT /api/scan/blank` mutated and the matcher read, which made `POST /api/match/anchor`
    **not** a pure function of its request body (contrary to the comment at the top of its own
    server). The refusal set now travels in the request body. Nothing on this object may ever be
    written by an analysis route.
    """

    def __init__(self, dataset: Any, frames: Any, skipped: list[dict] | None = None) -> None:
        self.session_id: str = f"s_{uuid.uuid4().hex[:8]}"
        self.dataset = dataset
        self.frames = frames
        self.opened_at: str = core_document.iso_now()
        #: The frames that did NOT make it in, each with its reason. ⛔ Neither reason is a trial
        #: number: `not_snapshot` / `unreadable` / `off_shape` are facts about the file on disk.
        self.skipped: list[dict] = list(skipped or [])

    def to_json(self) -> dict:
        """`api.schemas.SessionResponse`."""
        store = self.frames
        return {
            "session_id": self.session_id,
            "dataset_key": self.dataset.key,
            "dataset": self.dataset.name,
            "experiment": self.dataset.experiment,
            "path": self.dataset.path.as_posix(),
            "opened_at": self.opened_at,
            # ⭐ A FRESH IDENTITY PER OPEN. Cache-bust every pixel URL with `?v={nonce}.{tone.version}`
            # — NOT the tone version alone, which is a dataclass default and resets to 1 on every open
            # while the pixels behind an `immutable, max-age=1y` URL change.
            "nonce": store.nonce,
            "w": store.shape[1],
            "h": store.shape[0],
            "trials": list(store.trials),
            "n": store.n,
            "skipped": list(self.skipped),
            "tone": store.tone.to_json(),
            # ⭐ WHAT THE READER ACTUALLY DID, off THIS acquisition's XML. Never asserted.
            "frame_note": store.frame_note,
            "gpu": gpu_info(),
            "n_log_entries": len(self.dataset.entries),
        }


class SessionRegistry:
    """Thread-safe. The API serves from a thread pool and a build's `open` runs on another."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_id: dict[str, Session] = {}

    def put(self, s: Session) -> Session:
        with self._lock:
            self._by_id[s.session_id] = s
        return s

    def get(self, session_id: str) -> Session | None:
        """⭐ **THIS IS WHAT `camea.api.app` INJECTS INTO EVERY FEATURE ROUTER.**"""
        with self._lock:
            return self._by_id.get(session_id)

    def by_dataset_key(self, key: str) -> Session | None:
        with self._lock:
            for s in reversed(list(self._by_id.values())):
                if s.dataset.key == key:
                    return s
        return None

    def list(self) -> list[Session]:
        with self._lock:
            return list(self._by_id.values())

    def close(self, session_id: str) -> bool:
        with self._lock:
            s = self._by_id.pop(session_id, None)
        if s is None:
            return False
        # The frame stack is ~340 MiB and the band stack is a second copy. Drop the references and
        # let the GC have them; the caches hang off the store, so there is nothing else to clear.
        s.frames = None  # type: ignore[assignment]
        return True

    def clear(self) -> None:
        with self._lock:
            self._by_id.clear()


#: THE registry. `camea.api.app` hands `SESSIONS.get` to each feature router at startup.
SESSIONS = SessionRegistry()


def _session(session_id: str) -> Session:
    s = SESSIONS.get(session_id)
    if s is None:
        raise ApiError(404, "no_session", f"no such session: {session_id}")
    return s


# =================================================================================================
# GPU — 🔴 there is EXACTLY ONE DETECTOR, and the API layer does not own it
# =================================================================================================
#
# ⛔ **THE API MAY NOT IMPORT t27.** `features/mosaic/solve.py` is the ONLY module outside `engine/`
# that may import t27/t33 (`docs/SPLIT.md` §0.5, asserted by
# `tests/unit/test_mosaic_solve.py::test_solve_is_the_ONLY_module_under_src_that_imports_t27_or_t33`
# — which caught this the moment it was written the other way). Two entry points into the engine is
# how two copies of it get made.
#
# So the detector lives in `camea.engine.adapters.gpu_info()`, beside the other six private reaches,
# and we call it through the package. It memoises, and its first call **executes a real CUDA op** —
# `import cupy` succeeds on a broken install; only `cupy.zeros(1) + 1` raises.


def gpu_info() -> dict:
    """`api.schemas.GpuInfo` — from `camea.engine`, which owns the one detector.

    Lazy (`camea.engine` pulls in numpy + the DLL dance) and never fatal: on a machine where the
    engine cannot even load, the app must still serve `/openapi.json` and its own dataset browser.
    """
    try:
        from camea.engine import gpu_info as detect

        return detect()
    except Exception as e:  # noqa: BLE001 — no engine is a fact to report, not a 500 to raise
        return {
            "available": False, "backend": "numpy", "name": "CPU (numpy)", "cupy": None,
            "cuda_runtime": None,
            "reason": f"the engine could not be loaded ({type(e).__name__}: {e})",
            "note": "Placement is unavailable until the engine imports. The browser still works.",
        }


# =================================================================================================
# health / gpu
# =================================================================================================
@router.get("/api/health", response_model=HealthResponse)
def get_health() -> dict:
    """Is the server up? **Cheap, and it touches nothing** — no engine, no GPU, no disk. It is what a
    test harness and the launcher poll while the window is still painting."""
    return {
        "ok": True,
        "version": camea.__version__,
        "python": sys.version.split()[0],
        "uptime_s": round(time.time() - _T0, 1),
    }


@router.get("/api/gpu", response_model=GpuInfo)
def get_gpu() -> dict:
    """See `gpu_info()`. The first call costs ~200 ms and is memoised for the life of the process."""
    return gpu_info()


# =================================================================================================
# settings
# =================================================================================================
@router.get("/api/settings", response_model=Settings)
def get_settings() -> dict:
    return SETTINGS.ensure_loaded().to_json()


@router.put("/api/settings", response_model=Settings)
def put_settings(body: SettingsUpdate) -> dict:
    """⛔ Three keys, all of them paths. See `camea.settings` — a settings file that remembered an
    exclusion would be answering, on the user's behalf, the question the app exists to help him
    answer."""
    SETTINGS.ensure_loaded()
    fields = body.model_dump(exclude_unset=True)
    SETTINGS.update(
        workspace=fields.get("workspace", None) if "workspace" in fields else None,
        dataset_roots=fields.get("dataset_roots") if "dataset_roots" in fields else None,
    )
    # `workspace: null` in the body means FORGET IT — and `update()` cannot tell that from "absent".
    if "workspace" in fields and fields["workspace"] is None:
        SETTINGS.set_workspace(None)
    return SETTINGS.to_json()


# =================================================================================================
# 🔴 fs — THE FOLDER PICKER THAT DOES NOT NEED A NATIVE WINDOW
# =================================================================================================
#
# In `--browser` and `--headless` there is no pywebview, so `/api/dialog/*` cannot open a native
# dialog and honestly returns 501. **v1 stopped there, and that made the app unusable in the two
# modes a developer and a test actually run it in**: with no way to name a folder, there was nothing
# you could do. This is the way out, and it is served in EVERY mode.
#
# ⛔ It is a *directory lister*, not a file server: it returns NAMES, never bytes. It cannot read a
# file, and there is nothing to write with.
#
# ⚠️ `FsEntry` / `FsListResponse` are wire models and so live in `camea.api.schemas` with every other
# request/response model (the single-source-of-contract invariant), and are imported at the top of
# this file. They are NOT redefined here.


def _fs_roots() -> list[str]:
    """The drives (Windows) or `/` (POSIX), plus `~`. Cheap and never raises."""
    out: list[str] = []
    if os.name == "nt":
        for letter in "CDEFGHIJKLMNOPQRSTUVWXYZAB":
            d = f"{letter}:/"
            if Path(d).is_dir():
                out.append(d)
    else:
        out.append("/")
    home = str(Path.home()).replace("\\", "/")
    if home not in out:
        out.append(home)
    return out


@router.get("/api/fs/list", response_model=FsListResponse)
def get_fs_list(
    path: str | None = Query(default=None, description="Absolute directory. Omit to get the roots."),
) -> dict:
    """List a directory's **sub-directories** — the served folder picker.

    ⭐ **This is the route that keeps `--browser` and `--headless` usable.** The native dialogs need a
    pywebview window; this needs nothing. It is how the UI lets the user choose a dataset folder, a
    workspace folder or an export folder when there is no native dialog to open — and it is what
    makes the whole app drivable by Playwright.

    ⛔ **Directories only. It never returns a file's contents, and there is no write path here.**
    """
    roots = _fs_roots()
    if not path:
        return {"path": "", "parent": None, "is_dataset": False, "entries":
                [{"name": r, "path": r, "is_dataset": False, "n_children": None} for r in roots],
                "roots": roots, "error": None}

    p = Path(path).expanduser()
    try:
        p = p.resolve()
    except OSError:
        p = p.absolute()

    fwd = p.as_posix()
    parent = p.parent.as_posix() if p.parent != p else None
    is_ds = core_dataset._looks_like_a_dataset(p) if p.is_dir() else False

    if not p.is_dir():
        return {"path": fwd, "parent": parent, "is_dataset": False, "entries": [],
                "roots": roots, "error": f"not a directory: {fwd}"}

    entries: list[dict] = []
    try:
        children = sorted((c for c in p.iterdir() if c.is_dir()), key=lambda c: c.name.lower())
    except OSError as e:
        return {"path": fwd, "parent": parent, "is_dataset": is_ds, "entries": [],
                "roots": roots, "error": str(e)}

    for c in children:
        if c.name.startswith((".", "$")):
            continue
        try:
            n = sum(1 for _ in c.iterdir() if _.is_dir())
        except OSError:
            n = None
        entries.append({
            "name": c.name,
            "path": c.as_posix(),
            "is_dataset": core_dataset._looks_like_a_dataset(c),
            "n_children": n,
        })
    return {"path": fwd, "parent": parent, "is_dataset": is_ds, "entries": entries,
            "roots": roots, "error": None}


# =================================================================================================
# datasets — the browser. THE NEW HOME SCREEN.
# =================================================================================================
#
# ⛔ A DATASET IS READ-ONLY. Nothing below writes to one, and `core.workspace.refuse_write` refuses
# any output path inside `data/` or inside an acquisition folder — recognised by its SHAPE, never by
# its name.

#: `{key: resolved path}` for every dataset we have seen this run. It is a *lookup*, not knowledge:
#: `GET /api/datasets/{key}` has to find the folder again, and a key is a hash, not a path.
_DATASET_PATHS: dict[str, str] = {}
_DATASET_LOCK = threading.RLock()


def _remember(ds: Any) -> Any:
    with _DATASET_LOCK:
        _DATASET_PATHS[ds.key] = ds.path.as_posix()
    return ds


def _dataset_for_key(key: str) -> Any:
    """Re-open the dataset a key names. Re-scans the remembered roots once if we have not seen it."""
    with _DATASET_LOCK:
        p = _DATASET_PATHS.get(key)
    if p is None:
        _scan_roots()                                   # a cold start: nothing has been listed yet
        with _DATASET_LOCK:
            p = _DATASET_PATHS.get(key)
    if p is None:
        raise ApiError(404, "not_found", f"no dataset with key {key!r} under the remembered roots. "
                                         f"Point the app at its folder (POST /api/datasets/scan).")
    try:
        return _remember(core_dataset.open_dataset(p))
    except (OSError, ValueError) as e:
        raise ApiError(404, "not_found", f"{p}: {e}") from e


def _workspace_or_none() -> core_workspace.Workspace | None:
    """The chosen workspace, if there is one and it is still there. **Never raises**: the dataset
    browser must render on a machine where the workspace drive is unplugged."""
    path = SETTINGS.ensure_loaded().workspace
    if not path:
        return None
    try:
        return core_workspace.Workspace.open(path, create=False)
    except Exception:                                   # noqa: BLE001
        return None


def _analyses_index() -> dict[str, list[dict]]:
    """`{dataset_key: [AnalysisRef, ...]}` — the "you already have work here" card. `{}` with no
    workspace, and `{}` if it cannot be read. It is a decoration on a browser card; it does not get
    to fail the browser."""
    ws = _workspace_or_none()
    if ws is None:
        return {}
    try:
        return {k: [a.to_ref() for a in v] for k, v in ws.by_dataset().items()}
    except Exception:                                   # noqa: BLE001
        return {}


def _scan_roots(depth: int = DEFAULT_SCAN_DEPTH) -> tuple[list[Any], list[dict], list[str]]:
    """Every dataset under every remembered root. -> `(datasets, skipped, roots)`."""
    roots = list(SETTINGS.ensure_loaded().dataset_roots)
    found: list[Any] = []
    skipped: list[dict] = []
    seen: set[str] = set()
    for r in roots:
        try:
            res = core_dataset.scan(r, depth=depth)
        except (OSError, ValueError) as e:
            skipped.append({"path": r, "reason": str(e)})
            continue
        skipped += list(res.skipped)
        for ds in res.datasets:
            if ds.key in seen:
                continue                                # two roots that overlap must not double-list
            seen.add(ds.key)
            found.append(_remember(ds))
    found.sort(key=lambda d: d.name)
    return found, skipped, roots


def _dataset_list_body(datasets: list[Any], skipped: list[dict], roots: list[str]) -> dict:
    idx = _analyses_index()
    recents = {p.lower() for p in SETTINGS.recent_datasets}
    return {
        "roots": roots,
        "datasets": [
            ds.summary(
                thumbnail_url=f"/api/datasets/{ds.key}/thumbnail.png",
                analyses=idx.get(ds.key, []),
                last_opened=(ds.path.as_posix() if ds.path.as_posix().lower() in recents else None),
            )
            for ds in datasets
        ],
        "skipped": [s.get("path", "") if isinstance(s, dict) else str(s) for s in skipped],
    }


@router.get("/api/datasets", response_model=DatasetListResponse)
def get_datasets() -> dict:
    """**The home screen.** Every dataset under the folders the user has pointed at, with no pixel
    loaded (~0.2 s each). An empty `roots` is the honest first-run state — the UI shows the folder
    picker (`GET /api/fs/list`) rather than pretending to know where his data is."""
    datasets, skipped, roots = _scan_roots()
    return _dataset_list_body(datasets, skipped, roots)


@router.post("/api/datasets/scan", response_model=DatasetListResponse)
def post_datasets_scan(body: DatasetScanRequest) -> dict:
    """*"Point me at a folder."* A POST, not a GET: a Windows path in a query string is an encoding
    trap, and scanning also updates `settings.dataset_roots`.

    ⛔ Nothing here recognises a dataset by name. A folder is a dataset iff it has a `log.txt` and at
    least one `NNN.xml`. That is the whole rule.
    """
    try:
        res = core_dataset.scan(body.root, depth=body.depth)
    except (OSError, ValueError) as e:
        raise ApiError(400, "bad_request", str(e)) from e

    if body.remember:
        SETTINGS.ensure_loaded().add_root(res.root)

    for ds in res.datasets:
        _remember(ds)
    return _dataset_list_body(list(res.datasets), list(res.skipped),
                             list(SETTINGS.ensure_loaded().dataset_roots))


@router.get("/api/datasets/{key}", response_model=DatasetDetail)
def get_dataset(key: str) -> dict:
    """Everything sayable about a dataset **without loading a pixel**: every trial (of any type), its
    timestamp, its per-trial shape from its own XML, and the contiguous Snapshot blocks.

    ⛔ **Core reports the blocks; it does not choose one.** "The run is the longest block, restricted
    to 512x512" is the *mosaic feature's* selection rule, and the next feature will want a different
    one over the same frames.
    """
    ds = _dataset_for_key(key)
    return ds.detail(thumbnail_url=f"/api/datasets/{ds.key}/thumbnail.png",
                     analyses=_analyses_index().get(ds.key, []))


_THUMB_CACHE: dict[str, bytes] = {}


@router.get("/api/datasets/{key}/thumbnail.png", response_class=Response,
            responses={200: {"content": {"image/png": {}}}})
def get_dataset_thumbnail(key: str) -> Response:
    """One frame, **with no session**: the browser card must not cost 5 s and 340 MiB.

    The window is computed **globally over a small sample** of this dataset's own frames, never
    per-frame: a per-frame stretch would over-brighten a near-empty acquisition and make the card lie
    about which datasets are dim. (~10 ms, then cached.)
    """
    from camea.core import frames as core_frames  # cv2. Lazy: /openapi.json must not need it.

    ds = _dataset_for_key(key)
    cached = _THUMB_CACHE.get(ds.key)
    if cached is not None:
        return Response(cached, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=300"})

    trials = ds.readable_trials
    if not trials:
        raise ApiError(404, "not_found", f"{ds.name} has no readable snapshot to make a thumbnail of")

    # An even sample — and all of ONE shape, because a FrameStore holds one shape and `compute_tone`
    # stacks them. Take the biggest shape group; the card is a picture, not a measurement.
    groups = ds.shape_groups()
    pool = groups[0]["trials"] if groups else trials
    step = max(1, len(pool) // THUMBNAIL_SAMPLE)
    sample = pool[::step][:THUMBNAIL_SAMPLE] or pool[:1]

    try:
        import cv2
        import numpy as np

        stack = core_frames.load_frames(ds.path, list(sample), snaps=ds.snapshots)
        tone, flat_n = core_frames.compute_tone(stack)
        u8 = core_frames.to_u8(stack[len(stack) // 2], flat_n, tone)
        h, w = u8.shape
        scale = THUMBNAIL_PX / float(max(h, w))
        small = cv2.resize(u8, (max(1, int(w * scale)), max(1, int(h * scale))),
                           interpolation=cv2.INTER_AREA)
        png = core_frames.png_bytes(np.ascontiguousarray(small))
    except Exception as e:                              # noqa: BLE001
        raise ApiError(500, "io_error", f"could not render a thumbnail for {ds.name}: {e}") from e

    _THUMB_CACHE[ds.key] = png
    return Response(png, media_type="image/png", headers={"Cache-Control": "public, max-age=300"})


# =================================================================================================
# sessions — an OPEN dataset (its pixels, in RAM)
# =================================================================================================
def _resolve_open_target(body: OpenSessionRequest) -> Any:
    if not body.path and not body.dataset_key:
        raise ApiError(400, "bad_request", "give me either a `path` or a `dataset_key`")
    if body.dataset_key:
        return _dataset_for_key(body.dataset_key)
    try:
        return _remember(core_dataset.open_dataset(body.path))   # type: ignore[arg-type]
    except FileNotFoundError as e:
        raise ApiError(404, "not_found", str(e)) from e
    except ValueError as e:
        raise ApiError(400, "bad_request", str(e)) from e


@router.post("/api/sessions", response_model=JobRef, status_code=202)
def post_sessions(body: OpenSessionRequest) -> dict:
    """Open a dataset -> **202 `JobRef`**. Poll `GET /api/jobs/{id}`; `result` is an `OpenJobResult`.

    ⛔ **NOTHING IS EVER DROPPED BY TRIAL NUMBER.** A frame leaves the selection for exactly two
    reasons, both facts about the file on disk — it is `not_snapshot` (no readable 1-frame .dat/.xml
    pair) or it is `off_shape` — and every one of them is reported in `SessionResponse.skipped` with
    its reason. **The app has no exclusion list, and this route is where one would have gone.**

    `trials: null` ⇒ every snapshot trial. If they are not all one shape the open is refused with
    **409 `mixed_shape`**, listing the groups: a FrameStore holds ONE shape, and *which one you meant*
    is a decision core is not entitled to make for you.

    ⚠️ The shape check runs **before** the job is submitted (`open_dataset` is ~0.2 s and touches no
    pixels), so `mixed_shape` is a real 409 the client can act on, and not a job that fails 5 s later.
    """
    from camea.core import frames as core_frames   # cv2 — lazy.

    ds = _resolve_open_target(body)

    want = sorted({int(t) for t in body.trials}) if body.trials is not None else ds.snapshot_trials
    if not want:
        raise ApiError(400, "bad_request", f"{ds.name} has no snapshot trials to open")

    # --- the two honest reasons a frame is dropped, and NEITHER of them is its trial number -------
    skipped: list[dict] = []
    have: list[int] = []
    for t in want:
        m = ds.snapshots.get(t)
        if m is None:
            entry = ds.entry(t)
            reason = "not_snapshot" if (entry is None or entry.type != core_dataset.SNAPSHOT) \
                else "unreadable"
            skipped.append({"trial": t, "reason": reason, "w": None, "h": None,
                            "message": (f"trial {t} has no readable 1-frame snapshot on disk "
                                        f"(no .dat/.xml pair, a movie, or a 2-frame 'snapshot')")})
        else:
            have.append(t)

    if not have:
        raise ApiError(400, "bad_request",
                       f"none of the {len(want)} requested trials has a readable frame on disk")

    groups = core_frames.shape_groups(ds.snapshots, have)
    if len(groups) > 1:
        raise ApiError(
            409, "mixed_shape",
            "these trials are not all the same frame shape, and a session holds exactly one. "
            "Choose the shape you meant and pass those trials explicitly.",
            {"groups": "; ".join(f"{g['w']}x{g['h']}: {g['n']} trials" for g in groups)},
        )

    def fn(report, cancel) -> dict:
        emit = phase_reporter(report, OPEN_PHASES)
        emit("scan_dir", 2.0, f"{ds.name}: {len(have)} snapshot trials")
        emit("parse_log", 5.0, f"{len(ds.entries)} log entries")

        def on_frame(i: int, n: int) -> None:
            emit("load_frames", 5.0 + 55.0 * i / max(1, n), f"reading frame {i}/{n}")

        store = core_frames.FrameStore.load(ds.path, have, snaps=ds.snapshots, progress=on_frame)
        emit("flat_field", 65.0, "estimating the vignette")
        emit("tone", 72.0, "one global window for the whole dataset")
        # ⭐ Warm the band stack HERE, in the job, where the user is watching a progress bar — not on
        # the first `Space`, where he is waiting on a match. It is also the texture map: the matcher's
        # band-passed stack and `std(DoG(3,30))` are THE SAME ARRAY (+0 s, +0 MiB).
        emit("texture", 80.0, "band-passing (the matcher's input, and the texture measure)")
        store.texture()
        emit("done", 100.0, f"{store.n} frames, {store.shape[1]}x{store.shape[0]}")

        s = SESSIONS.put(Session(ds, store, skipped))
        SETTINGS.ensure_loaded().touch_dataset(ds.path)
        return {"kind": "open", "session": s.to_json()}

    job = JOBS.submit_thread("open", fn)
    return {"job_id": job.job_id, "kind": "open"}


@router.get("/api/sessions", response_model=SessionListResponse)
def get_sessions() -> dict:
    return {"sessions": [s.to_json() for s in SESSIONS.list()]}


@router.get("/api/sessions/{session_id}", response_model=SessionResponse)
def get_session(session_id: str) -> dict:
    return _session(session_id).to_json()


@router.delete("/api/sessions/{session_id}", response_model=OkResponse)
def delete_session(session_id: str) -> dict:
    """Frees the stack (~340 MiB, plus the band stack's second copy)."""
    if not SESSIONS.close(session_id):
        raise ApiError(404, "no_session", f"no such session: {session_id}")
    return {"ok": True}


@router.get("/api/sessions/{session_id}/log", response_model=LogResponse)
def get_session_log(session_id: str) -> dict:
    """⚠️ `log.txt` prints the date **only** on `New experiment:` lines; every other line carries
    `HH:MM:SS` alone. The parser carries the date forward and rolls it over at midnight — get that
    wrong and you inject a -86,000 s gap into the timing-split rule."""
    return _session(session_id).dataset.log_json()


@router.get("/api/sessions/{session_id}/texture", response_model=TextureResponse)
def get_session_texture(session_id: str) -> dict:
    """⭐ **THE MEASUREMENT, AND IT IS CORE.** `std(DoG(3,30))` answers *"how much texture is in this
    image"*, which is a property of the FRAME — every future feature asks it.

    ⛔ **There is no threshold here, no list, and no policy.** Turning a number into a *proposal* is a
    feature's job (`POST /api/mosaic/screen/propose`); turning a proposal into a *decision* is the
    human's, and it lands in his document. Never in the session.
    """
    from camea.core.frames import TEXTURE_MEASURE

    s = _session(session_id)
    tex = s.frames.texture()
    return {"measure": TEXTURE_MEASURE, "texture": tex, "n": len(tex)}


@router.get("/api/sessions/{session_id}/tone", response_model=Tone)
def get_tone(session_id: str) -> dict:
    return _session(session_id).frames.tone.to_json()


@router.put("/api/sessions/{session_id}/tone", response_model=Tone)
def put_tone(session_id: str, body: ToneUpdate) -> dict:
    """⚠️⚠️ **GLOBAL, NEVER PER-TILE.** A per-tile percentile stretch over-brightens near-empty frames
    and makes overlapping tiles disagree in brightness — **which destroys the Difference-mode check
    the whole verification loop depends on.** There is no per-tile path and there must never be one.

    Tone is display-only: it never touches the matcher (which sees band-passed, mean-subtracted
    pixels) and it never touches the exported TIFF.
    """
    s = _session(session_id)
    try:
        tone = s.frames.set_tone(lo=body.lo, hi=body.hi, auto=bool(body.auto))
    except ValueError as e:
        raise ApiError(400, "bad_request", str(e)) from e
    return tone.to_json()


# =================================================================================================
# tiles — the pixels
# =================================================================================================
#: ⭐ The `?v={nonce}.{tone.version}` cache-buster is what makes this safe. **NOT the tone version
#: alone** — that is a dataclass default and resets to 1 on every open, while the pixels behind the
#: URL change. Open a second acquisition whose trial numbers overlap and the browser would serve the
#: FIRST dataset's pixels, for a year.
_IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}


@router.get("/api/sessions/{session_id}/tiles/{trial}.png", response_class=Response,
            responses={200: {"content": {"image/png": {}}}})
def get_tile_png(session_id: str, trial: int, v: str | None = None) -> Response:
    """8-bit grayscale PNG: flat-fielded, through the **one global** tone window."""
    s = _session(session_id)
    try:
        png = s.frames.tile_png(trial)
    except KeyError:
        raise ApiError(404, "not_found",
                       f"trial {trial} is not loaded in session {session_id}") from None
    return Response(png, media_type="image/png", headers=dict(_IMMUTABLE))


@router.get("/api/sessions/{session_id}/tiles/{trial}.raw", response_class=Response,
            responses={200: {"content": {"application/octet-stream": {}}}})
def get_tile_raw(session_id: str, trial: int, v: str | None = None) -> Response:
    """uint16 **little-endian**, row-major, **ALREADY FLIPPED** per this acquisition's XML, and
    **RAW CAMERA COUNTS** — no flat-field, no tone. This is pixel data, not a picture."""
    s = _session(session_id)
    try:
        raw = s.frames.tile_raw(trial)
    except KeyError:
        raise ApiError(404, "not_found",
                       f"trial {trial} is not loaded in session {session_id}") from None
    return Response(raw, media_type="application/octet-stream", headers=dict(_IMMUTABLE))


@router.get("/api/sessions/{session_id}/thumbs.png", response_class=Response,
            responses={200: {"content": {"image/png": {}}}})
def get_thumbs_png(session_id: str, v: str | None = None, cell: int = 64) -> Response:
    """The contact sheet: ONE sprite sheet, `grid = ceil(sqrt(n))`, row-major in trial order.
    Same **global** window — a per-tile stretch here would make the sheet lie about which frames are
    dim, which is the one thing the Screen step exists to show him."""
    s = _session(session_id)
    png, _ = s.frames.thumbs(cell)
    return Response(png, media_type="image/png", headers=dict(_IMMUTABLE))


@router.get("/api/sessions/{session_id}/thumbs.json", response_model=ThumbsResponse)
def get_thumbs_json(session_id: str, cell: int = 64) -> dict:
    """Cell `i` holds `trials[i]` at `(x, y) = ((i % grid) * cell, (i // grid) * cell)`."""
    return _session(session_id).frames.thumbs_json(cell)


# =================================================================================================
# workspace — where the analyses live
# =================================================================================================
def _workspace() -> core_workspace.Workspace:
    path = SETTINGS.ensure_loaded().workspace
    if not path:
        raise ApiError(409, "no_workspace",
                       "no workspace has been chosen. Pick a folder for your analyses "
                       "(PUT /api/workspace) — it may not be inside a dataset or inside the repo.")
    try:
        return core_workspace.Workspace.open(path, create=True)
    except core_workspace.DatasetIsReadOnly as e:
        raise ApiError(409, "refused", str(e)) from e
    except core_workspace.PathRefused as e:
        raise ApiError(409, "refused", str(e)) from e
    except core_workspace.WorkspaceError as e:
        raise ApiError(400, "bad_request", str(e)) from e


@router.get("/api/workspace", response_model=WorkspaceInfo)
def get_workspace() -> dict:
    """`writable` is **proved, not assumed** (it writes and deletes a probe file): a workspace on a
    drive that has been unplugged must show up on the Load screen as `writable: false`, not as a 500
    an hour into a sweep."""
    path = SETTINGS.ensure_loaded().workspace
    if not path:
        return {"path": None, "exists": False, "writable": False, "n_analyses": 0}
    try:
        return core_workspace.Workspace.open(path, create=False).info()
    except Exception:                                   # noqa: BLE001 — a vanished drive is not a 500
        return {"path": path, "exists": False, "writable": False, "n_analyses": 0}


@router.put("/api/workspace", response_model=WorkspaceInfo)
def put_workspace(body: WorkspaceSetRequest) -> dict:
    """⛔ **NEVER inside a dataset. NEVER inside the repo.** Both are refused here, at the one moment
    the user names the place — a workspace under the checkout would be committed, `.gitignore`d, or
    blown away by a clean. His work does not live in the app's source tree."""
    try:
        ws = core_workspace.Workspace.open(body.path, create=body.create)
    except core_workspace.DatasetIsReadOnly as e:
        raise ApiError(409, "refused", str(e)) from e
    except core_workspace.PathRefused as e:
        raise ApiError(409, "refused", str(e)) from e
    except core_workspace.WorkspaceError as e:
        raise ApiError(400, "bad_request", str(e)) from e
    except OSError as e:
        raise ApiError(500, "io_error", f"cannot create {body.path}: {e}") from e

    SETTINGS.ensure_loaded().set_workspace(ws.path)
    return ws.info()


@router.get("/api/workspace/analyses", response_model=AnalysisListResponse)
def get_analyses(dataset_key: str | None = None, feature: str | None = None) -> dict:
    ws = _workspace()
    return {"workspace": ws.path.as_posix(),
            "analyses": [a.to_json() for a in ws.analyses(dataset_key=dataset_key, feature=feature)]}


@router.post("/api/workspace/analyses", response_model=AnalysisSummary, status_code=201)
def post_analyses(body: CreateAnalysisRequest) -> dict:
    """⭐ **THE SERVER CREATES THE DOCUMENT**, via the feature's `new_payload` hook.

    🔴 In v1 `new_doc()` and `seed_from_build()` were **dead code** — the front end reimplemented both
    in JavaScript. That is how `human_edits`' divert counters were silently dropped on every save, and
    how *"Skip — place by hand"* could erase `seeded_from` while every tile still sat exactly where
    t33 put it. **The document is authored on the server. It is not negotiable.**

    ⭐ The document's `id` **is** the `analysis_id` — `workspace._guard_slot` refuses any document
    whose `id` is not the analysis it is being written into, and that is what makes v1's autosave slot
    collision (pass 2 silently overwriting pass 1's ground-truth records) impossible rather than
    merely unlikely.
    """
    s = _session(body.session_id)
    ws = _workspace()

    if body.feature not in core_document.registered_features():
        raise ApiError(400, "bad_request",
                       f"no feature is registered under {body.feature!r} "
                       f"(registered: {core_document.registered_features()})")

    trials = sorted({int(t) for t in body.trials}) if body.trials is not None \
        else list(s.frames.trials)
    stray = [t for t in trials if t not in s.frames.row_of]
    if stray:
        raise ApiError(400, "bad_request", f"trials not loaded in this session: {stray[:12]}")

    try:
        analysis = ws.create_analysis(feature=body.feature, name=body.name,
                                      dataset_key=s.dataset.key, dataset=s.dataset.name,
                                      data_dir=s.dataset.path.as_posix())
    except core_workspace.WorkspaceError as e:
        raise ApiError(400, "bad_request", str(e)) from e

    # ⛔ Core passes the feature a bag of FACTS ABOUT THE SESSION and nothing else. It does not know
    # what the feature will do with them (mosaic's `new_payload` takes `**_ignored`), and it holds no
    # opinion about which trials are special — because it has none. **NOTHING STARTS EXCLUDED.**
    try:
        doc = core_document.new_document(
            feature=body.feature,
            id=analysis.analysis_id,
            dataset=s.dataset.name,
            dataset_key=s.dataset.key,
            data_dir=s.dataset.path.as_posix(),
            experiment=s.dataset.experiment,
            name=body.name,
            trials=trials,
            frame_note=s.frames.frame_note,
            tone=s.frames.tone.to_json(),
            texture=s.frames.texture(),
        )
        core_document.save_analysis(ws, analysis.analysis_id, doc)
    except core_document.ValidationError as e:
        ws.delete(analysis.analysis_id)                 # do not leave a half-made analysis behind
        raise ApiError(400, "bad_request", "; ".join(e.args[0]) if e.args else str(e)) from e
    except core_document.DocumentError as e:
        ws.delete(analysis.analysis_id)
        raise ApiError(400, "bad_request", str(e)) from e

    core_document.DOCUMENTS.put(doc, ws.document_path(analysis.analysis_id))
    return ws.get(analysis.analysis_id).to_json()


@router.patch("/api/workspace/analyses/{analysis_id}", response_model=AnalysisSummary)
def rename_analysis(analysis_id: str, body: RenameAnalysisRequest) -> dict:
    """Rename an analysis — the project manager's rename. ⭐ Rewrites the manifest ONLY; the directory
    never moves and the `analysis_id` is forever (a rename that moved the dir would break the slot guard
    and every path the document carries)."""
    ws = _workspace()
    name = body.name.strip()
    if not name:
        raise ApiError(400, "bad_request", "a project name cannot be empty")
    try:
        return ws.rename(analysis_id, name).to_json()
    except core_workspace.NoSuchAnalysis as e:
        raise ApiError(404, "not_found", str(e)) from e
    except core_workspace.WorkspaceError as e:
        raise ApiError(400, "bad_request", str(e)) from e


@router.delete("/api/workspace/analyses/{analysis_id}", response_model=OkResponse)
def delete_analysis(analysis_id: str) -> dict:
    ws = _workspace()
    try:
        ws.delete(analysis_id)
    except core_workspace.NoSuchAnalysis as e:
        raise ApiError(404, "not_found", str(e)) from e
    except core_workspace.WorkspaceError as e:
        raise ApiError(400, "bad_request", str(e)) from e
    core_document.DOCUMENTS.close(analysis_id)
    return {"ok": True}


# =================================================================================================
# documents — save / load / autosave.  CORE envelope; the FEATURE owns the payload.
# =================================================================================================
def _doc_of(body: Any) -> dict:
    """The posted document, as a plain dict with its unknown keys intact.

    ⚠️ `by_alias=True` matters: `TileRecord.pass_` is `alias="pass"` and `QcMovedRow.from_` is
    `alias="from"`. Dump under the *wire* names, or the feature's own code cannot find them.
    """
    return body.doc.model_dump(by_alias=True)


def _document_error(e: Exception) -> ApiError:
    if isinstance(e, core_document.RangeMismatch):
        return ApiError(409, "range_mismatch", str(e))
    if isinstance(e, core_workspace.SlotMismatch):
        return ApiError(409, "range_mismatch", str(e))
    if isinstance(e, core_document.ValidationError):
        msgs = e.args[0] if e.args and isinstance(e.args[0], list) else [str(e)]
        return ApiError(400, "bad_request", "; ".join(str(m) for m in msgs))
    if isinstance(e, core_workspace.NoSuchAnalysis):
        return ApiError(404, "not_found", str(e))
    if isinstance(e, core_workspace.DatasetIsReadOnly | core_workspace.PathRefused):
        return ApiError(409, "refused", str(e))
    if isinstance(e, core_document.DocumentError | core_workspace.WorkspaceError):
        return ApiError(400, "bad_request", str(e))
    if isinstance(e, OSError):
        return ApiError(500, "io_error", str(e))
    return ApiError(500, "io_error", f"{type(e).__name__}: {e}")


@router.get("/api/analyses/{analysis_id}/document", response_model=DocumentResponse)
def get_document(analysis_id: str, recovered: bool = False) -> dict:
    """`recovered=true` reads the **autosave** instead — ask `Workspace.recovery()` first: an autosave
    NEWER than the document is a recovery prompt, an older one is noise."""
    ws = _workspace()
    try:
        doc, _ = core_document.load_analysis(ws, analysis_id, recovered=recovered)
    except FileNotFoundError as e:
        raise ApiError(404, "no_document", f"analysis {analysis_id} has no saved document") from e
    except Exception as e:                              # noqa: BLE001
        raise _document_error(e) from e
    core_document.DOCUMENTS.put(doc, ws.document_path(analysis_id))
    return {"doc": doc}


@router.put("/api/analyses/{analysis_id}/document", response_model=SaveResult)
def put_document(analysis_id: str, body: SaveDocumentRequest) -> dict:
    """⚠️ **THE ORDER, ON THE SERVER: structural-validate -> normalise -> stamp -> full-validate ->
    write, atomically.** Not `validate -> normalise`: the derived fields are exactly the ones that
    drift the moment the user excludes a tile, and `normalise` is what repairs them — validating them
    first rejects a perfectly good document for drift the very next line of code fixes.
    (`core.document.prepare` owns that order; this route only picks the destination.)"""
    ws = _workspace()
    try:
        res = core_document.save_analysis(ws, analysis_id, _doc_of(body))
    except Exception as e:                              # noqa: BLE001
        raise _document_error(e) from e
    core_document.DOCUMENTS.put(res["doc"], res["path"])
    return {k: res[k] for k in ("path", "bytes", "saved_at", "warnings")}


@router.post("/api/analyses/{analysis_id}/autosave", response_model=SaveResult)
def post_autosave(analysis_id: str, body: AutosaveRequest) -> dict:
    """The crash net. Debounced 2 s, **plus unconditionally on every `A` and `E`**.

    🔴 **A FAILURE IS LOUD** — it is never swallowed. (`localStorage` failed *silently* in the sandbox
    and nearly cost a day's work; that is why the crash net is a server file at all.)

    🔴 **THE SLOT GUARD RUNS HERE, AND IN v1 IT DID NOT** — `project.autosave()` carried it and nothing
    ever called it. Pass 2's autosave once silently overwrote pass 1's ground-truth records. A
    document whose `id`/`dataset_key` disagrees with the slot's is refused with `409 range_mismatch`.
    It is not merged, not renamed, not "repaired".
    """
    ws = _workspace()
    try:
        res = core_document.autosave(ws, analysis_id, _doc_of(body))
    except Exception as e:                              # noqa: BLE001
        raise _document_error(e) from e
    return {k: res[k] for k in ("path", "bytes", "saved_at", "warnings")}


@router.post("/api/documents/load", response_model=LoadDocumentResponse)
def post_document_load(body: LoadDocumentRequest) -> dict:
    """*"Load a project…"* — and it **must work COLD**, with no session open. That is the whole point:
    the app remembers nothing between launches, so this file is its only memory. Save -> quit ->
    load restores the session whole, and nothing else does.

    The server bootstraps a session from the file's own `data_dir` when one is not given, then
    re-reads the file **against that session's scope**, so the range guard actually runs against the
    session the document belongs to.
    """
    from camea.core import frames as core_frames

    p = Path(body.path).expanduser()
    if not p.is_file():
        raise ApiError(404, "not_found", f"no such file: {p}")

    warnings: list[str] = []
    try:
        doc, w = core_document.load(p)                  # unguarded first read: we need its data_dir
        warnings += list(w)
    except Exception as e:                              # noqa: BLE001
        raise _document_error(e) from e

    session_json: dict | None = None
    s = SESSIONS.get(body.session_id) if body.session_id else None

    if s is None:
        data_dir = str(doc.get("data_dir") or "")
        if not data_dir:
            raise ApiError(400, "bad_request",
                           "this document does not say which dataset it belongs to (`data_dir` is "
                           "empty) and no session was given. Open the dataset first.")
        if not Path(data_dir).is_dir():
            raise ApiError(404, "not_found",
                           f"the dataset this document was made from is not on this machine: "
                           f"{data_dir}")
        try:
            ds = _remember(core_dataset.open_dataset(data_dir))
            trials = [int(k) for k in (doc.get("tiles") or {})] or ds.snapshot_trials
            trials = sorted({t for t in trials if t in ds.snapshots})
            store = core_frames.FrameStore.load(ds.path, trials, snaps=ds.snapshots)
        except (OSError, ValueError) as e:
            raise ApiError(500, "io_error", f"could not open {data_dir}: {e}") from e
        s = SESSIONS.put(Session(ds, store))
        SETTINGS.ensure_loaded().touch_dataset(ds.path)
        session_json = s.to_json()
        warnings.append(f"opened {ds.name} from the document's own data_dir ({len(trials)} frames)")

    # ⭐ NOW re-read it against the session's scope — this is where the range guard actually fires.
    expect = core_document.Scope(dataset=s.dataset.name, dataset_key=s.dataset.key)
    try:
        doc, w2 = core_document.load(p, expect=expect)
        warnings += [x for x in w2 if x not in warnings]
    except Exception as e:                              # noqa: BLE001
        raise _document_error(e) from e

    core_document.DOCUMENTS.put(doc, p)
    return {"doc": doc, "session": session_json, "warnings": warnings, "migrated_from": None}


@router.post("/api/documents/save-as", response_model=SaveResult)
def post_document_save_as(body: SaveDocumentRequest) -> dict:
    """**`Save…`** — a file the user names, reachable from EVERY screen (not buried behind the last
    step: since the app carries no dataset knowledge, this file is its only memory, and the one
    artefact that makes a session resumable must not be the one thing he cannot reach mid-sweep).

    ⛔ Refused inside `data/`, inside the repo's dataset mirror, or inside the dataset itself.
    """
    if not body.path:
        raise ApiError(400, "bad_request", "save-as needs a `path`")
    try:
        res = core_document.save(body.path, _doc_of(body))
    except Exception as e:                              # noqa: BLE001
        raise _document_error(e) from e
    core_document.DOCUMENTS.put(res["doc"], res["path"])
    return {k: res[k] for k in ("path", "bytes", "saved_at", "warnings")}


@router.post("/api/documents/validate", response_model=ValidationReport)
def post_document_validate(body: ValidateDocumentRequest) -> dict:
    """⛔ **NO TRIAL NUMBER IS SPECIAL.** Nothing here may reject a document for WHICH trials it
    placed. The guard that used to live in v1 ("tile 284 is thrown out and carries a position") made
    the user's own session **unsaveable** the moment he anchored 284."""
    doc = _doc_of(body)
    try:
        problems = core_document.report(doc)
    except core_document.UnknownFeature as e:
        return {"ok": False, "problems": [{"kind": "feature", "message": str(e),
                                           "severity": "error"}]}
    return {"ok": not any(p["severity"] == "error" for p in problems), "problems": problems}


# =================================================================================================
# jobs
# =================================================================================================
@router.get("/api/jobs", response_model=JobListResponse)
def get_jobs() -> dict:
    return {"jobs": [j.to_json() for j in JOBS.list()]}


@router.get("/api/jobs/{job_id}", response_model=Job)
def get_job(job_id: str) -> dict:
    """Poll at 500 ms. There is no websocket — it is one client on localhost and a poll is 0.6 ms.

    ⚠️ **`eta_s` is only recomputed when the child prints a recognised line.** Re-anchor the UI's
    countdown **only when this raw number changes**; re-anchoring on every tick resets the clock and
    the countdown never moves. And it may **jump UP** — an honest revision beats a smooth lie.
    """
    j = JOBS.get(job_id)
    if j is None:
        raise ApiError(404, "not_found", f"no such job: {job_id}")
    return j.to_json()


@router.post("/api/jobs/{job_id}/cancel", response_model=JobCancelResponse, status_code=202)
def post_job_cancel(job_id: str) -> dict:
    """Idempotent. A finished job is a **409**, not a lie.

    A process job's cancel is `terminate()` — that is not a shortcut, it is the only cancel there is:
    `t33.place` runs 25 s – 10 min synchronously with no callback and nothing inside it that checks a
    flag.
    """
    try:
        j = JOBS.cancel(job_id)
    except NotCancellable as e:
        code: ErrorCode = "not_found" if "no such job" in str(e) else "refused"
        raise ApiError(404 if code == "not_found" else 409, code, str(e)) from e
    return {"job_id": j.job_id, "state": j.state}


# =================================================================================================
# dialogs — the native pickers.  🔴 501 WHEN THERE IS NO WINDOW, AND THERE IS A WAY OUT.
# =================================================================================================
#
# `camea.api.app` sets `WINDOW` when the app runs with a pywebview shell (`camea --window`). In
# `--browser` and `--headless` there is none, and these routes say so — honestly, with `no_window`.
#
# ⭐ **AND THAT IS NOT A DEAD END.** `GET /api/fs/list` is the served folder picker and it works in
# EVERY mode. The 501 body names it. v1 returned a bare 501 and left the user (and Playwright) with
# no way to choose a folder at all.

WINDOW: Any = None


def set_window(window: Any) -> None:
    """Called once, by `camea.shell`, with the pywebview `Window`. Nothing else may set this."""
    global WINDOW
    WINDOW = window


_NO_WINDOW = (
    "there is no native window in this mode (--browser / --headless), so there is no native file "
    "dialog. Use GET /api/fs/list — the served folder picker. It works in every mode."
)


def _no_window() -> ApiError:
    return ApiError(501, "no_window", _NO_WINDOW, {"use": "GET /api/fs/list"})


@router.post("/api/dialog/open-directory", response_model=DialogPathResponse)
def post_dialog_open_directory(body: DialogOpenDirectoryRequest) -> dict:
    if WINDOW is None:
        raise _no_window()
    import webview  # noqa: PLC0415

    got = WINDOW.create_file_dialog(webview.FOLDER_DIALOG,
                                    directory=str(body.start or ""), allow_multiple=False)
    return {"path": (str(got[0]).replace("\\", "/") if got else None)}


@router.post("/api/dialog/open-file", response_model=DialogPathResponse)
def post_dialog_open_file(body: DialogOpenFileRequest) -> dict:
    if WINDOW is None:
        raise _no_window()
    import webview  # noqa: PLC0415

    got = WINDOW.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False,
                                    file_types=tuple(body.filters) or ())
    return {"path": (str(got[0]).replace("\\", "/") if got else None)}


@router.post("/api/dialog/save-file", response_model=DialogPathResponse)
def post_dialog_save_file(body: DialogSaveFileRequest) -> dict:
    if WINDOW is None:
        raise _no_window()
    import webview  # noqa: PLC0415

    got = WINDOW.create_file_dialog(webview.SAVE_DIALOG,
                                    save_filename=str(body.default_name or ""),
                                    file_types=tuple(body.filters) or ())
    if not got:
        return {"path": None}
    path = got[0] if isinstance(got, (list, tuple)) else got
    return {"path": str(path).replace("\\", "/")}


__all__ = ["router", "ApiError", "Session", "SESSIONS", "SessionRegistry", "gpu_info", "set_window",
           "FsEntry", "FsListResponse"]
