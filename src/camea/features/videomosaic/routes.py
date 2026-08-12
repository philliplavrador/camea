"""The videomosaic API — probe a video, create a project from it, build (a job), fetch outputs.

Same contracts as everywhere else in Camea:
- long work is a 202 `JobRef` + `GET /api/jobs/{id}` polling (the build is a cancellable
  thread job; there is no GPU in this pipeline, but two builds share one lease so they queue
  instead of thrashing the CPU);
- ⭐ THE SERVER CREATES THE DOCUMENT (`POST /api/videomosaic/projects` mirrors
  `POST /api/projects`, minus the dataset session a video does not have);
- errors are the `ErrorEnvelope`, raised through this router's own `ApiError` (the
  `HTTPException` subclass pattern — see `features/mosaic/routes.py`);
- every write path goes through `core.workspace.refuse_write`.

⭐ **NO FOLDER AT ALL (his ruling, 2026-08-10 — BEHAVIOUR R44).** Create takes one path, the video;
the project is made in Camea's own store and the build writes its artifacts into that project's
`outputs/`. There is no save route and no export route — getting a copy out is core's
`POST /api/projects/{id}/outputs/copy`, which every feature shares.

⚠️ **This retires R43's draft dance** (create a draft → build → `POST /api/videomosaic/save` moves it
into the folder he names). R43 was already deleting a redundant second directory question; R44
deletes the first one too. What survives from it: the build still starts on Create, and the
artifacts are still named after the **project** rather than after their kind, so a file copied out
of Camea says what it is on the user's desktop.

Import discipline: this module imports **no cv2** — `/openapi.json` must import clean; the
pipeline is imported inside handlers/jobs only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from fastapi import APIRouter
from fastapi.exceptions import HTTPException
from fastapi.responses import FileResponse, Response

from camea.api.schemas import (  # schemas is deliberately importable by features
    AnalysisSummary,
    CreateVideoProjectRequest,
    ElectrodeMapPayload,
    ErrorCode,
    JobRef,
    VideoBuildRequest,
    VideoElectrodeMapRequest,
    VideoProbeRequest,
    VideoSource,
)
from camea.core import document as core_document
from camea.core import project as core_project
from camea.core import workspace as core_workspace
from camea.core.jobs import JOBS, Busy
from camea.core.workspace import safe_basename

from .config import VideoConfig
from .document import FEATURE, apply_build

router = APIRouter()

JOB_KIND = "videomosaic_build"
#: One lease for all video builds: purely so two 5-minute CPU builds queue, not interleave.
LEASE = "videomosaic"

#: What `GET .../outputs/{name}` will serve — a whitelist of LOGICAL names, not a directory
#: listing. The real filenames follow the project's name; the handler resolves them through the
#: document's `build.outputs`, so the URL the front end builds never has to change.
#:
#: ⚠️ This is the FEATURE's route, and it exists for the one thing core's generic outputs routes
#: cannot do: render `mosaic.png` and `preview.png` on the feature's own screen without first
#: listing the directory to learn what the project happens to be called. Core's
#: `GET /api/projects/{id}/outputs` is the browser (R44); this is the feature's `<img src>`.
OUTPUT_FILES = {
    "mosaic.png": ("mosaic", "image/png"),
    "preview.png": ("preview", "image/png"),
    "positions.csv": ("positions", "text/csv"),
    "build.json": ("build", "application/json"),
}


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
# The store seam — a feature never imports the api layer; app.py injects these at startup.
# =================================================================================================
_PROJECTS_PROVIDER: Callable[[], core_project.ProjectSet] | None = None


def set_store(projects: Callable[[], core_project.ProjectSet]) -> None:
    global _PROJECTS_PROVIDER
    _PROJECTS_PROVIDER = projects


def _projects() -> core_project.ProjectSet:
    """The store (R44), fresh per call — the same one `routes_core` serves from."""
    if _PROJECTS_PROVIDER is None:
        raise RuntimeError("videomosaic routes not wired: call "
                           "camea.features.videomosaic.routes.set_store() at startup")
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


def _probe(path: str):
    """Probe, with `VideoError` mapped to the envelope. cv2 loads here, not at import."""
    from .video import VideoError, probe
    try:
        return probe(path)
    except VideoError as e:
        raise ApiError(400, "bad_request", str(e)) from e


def _video_key(path: Path) -> str:
    """A stable dataset-key analogue for a video file: name + hash of its resolved path —
    the same shape `Dataset.key` has, so project cards and filters just work."""
    import hashlib
    rp = path.resolve().as_posix().lower()
    return f"{path.stem}-{hashlib.sha1(rp.encode('utf-8')).hexdigest()[:12]}"


# =================================================================================================
# Routes
# =================================================================================================
@router.post("/api/videomosaic/probe", response_model=VideoSource)
def post_probe(body: VideoProbeRequest) -> dict:
    """The receipt: does this path decode as video, and what does it claim to contain?
    Proves a frame actually decodes — 'probed OK' can be trusted by Create."""
    if not body.path.strip():
        raise ApiError(400, "bad_request", "give the path of a video file")
    return _probe(body.path.strip()).to_json()


@router.post("/api/videomosaic/projects", status_code=201, response_model=AnalysisSummary)
def post_video_project(body: CreateVideoProjectRequest) -> dict:
    """⭐ THE SERVER CREATES THE DOCUMENT — `POST /api/projects` for a video source.

    No session: the video is probed here (a real decode, not a header parse) and its receipt
    becomes the document's `source`.

    ⭐ **AND NO FOLDER (R44).** The project is made in Camea's store, listed on the home screen from
    this moment, and its build writes into its own `outputs/`. There is nothing left to ask."""
    name = body.name.strip()
    video_path = body.video_path.strip()
    if not video_path:
        raise ApiError(400, "bad_request", "`video_path` is required")
    info = _probe(video_path)
    vp = Path(info.path)

    try:
        pr = core_project.Project.create_in_store(
            feature=FEATURE,
            name=name or vp.stem,
            dataset_key=_video_key(vp),
            dataset=info.name,
            data_dir=vp.parent.as_posix(),
        )
    except Exception as e:                                   # noqa: BLE001
        raise _project_error(e) from e

    ws = core_project.ProjectSet([pr.path.as_posix()])
    try:
        doc = core_document.new_document(
            feature=FEATURE,
            id=pr.analysis_id,
            dataset=info.name,
            dataset_key=_video_key(vp),
            data_dir=vp.parent.as_posix(),
            experiment="",
            name=name or vp.stem,
            source=info.to_json(),
        )
        core_document.save_analysis(ws, pr.analysis_id, doc)
    except core_document.ValidationError as e:
        _abandon(pr)
        raise ApiError(400, "bad_request",
                       "; ".join(e.args[0]) if e.args else str(e)) from e
    except core_document.DocumentError as e:
        _abandon(pr)
        raise ApiError(400, "bad_request", str(e)) from e

    # Nothing to remember: the project is in the store, and the store is the index (R44).
    core_document.DOCUMENTS.put(doc, pr.document_path)
    return pr.summary().to_json()


def _abandon(pr: core_project.Project) -> None:
    """Tear a half-made project back down, so a failed create leaves nothing on the home screen.
    It is in the store, so `delete()` takes the whole folder — there is nothing of the user's in
    it to spare, and there never was: he has not seen it yet."""
    try:
        pr.delete()
    except Exception:                                        # noqa: BLE001
        pass


@router.post("/api/videomosaic/build", status_code=202, response_model=JobRef)
def post_build(body: VideoBuildRequest) -> dict:
    """The whole pipeline as one cancellable job: track → keyframes → register → solve →
    render → save.

    ⭐ The artifacts land in the project's **`outputs/`, named after the project** (R44) — the one
    place the outputs browser reads for every feature, and names that still say what they are when
    the user copies one out to his desktop. The document is updated and saved by the JOB
    (server-side), so the result the UI polls out is already durable."""
    analysis_id = body.analysis_id
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
                       "not a video mosaic")

    try:
        cfg = VideoConfig.from_overrides(body.config or None)
    except ValueError as e:
        raise ApiError(400, "bad_request", str(e)) from e

    src = (doc.get("source") or {}).get("path") or ""
    if not Path(src).is_file():
        raise ApiError(409, "refused",
                       f"the source video is not there any more: {src}. Reconnect the drive "
                       "or recreate the project against the file's new home.")
    doc_path = ws.document_path(analysis_id)
    out_dir = ws.outputs_dir(analysis_id)                    # ⭐ <project>/outputs/ (R44)
    try:
        base = safe_basename(str(doc.get("name") or "") or analysis_id)
    except ValueError:
        base = safe_basename(analysis_id)                    # a name of pure punctuation

    box: dict = {}                                           # filled right after submit

    def log_line(line: str) -> None:
        # read the box lazily per line — the worker thread can outrun `box["job"] = job`
        j = box.get("job")
        if j is not None:
            j._log(line)

    def fn(report, cancel):
        from . import pipeline
        result = pipeline.build(src, out_dir, cfg, basename=base, report=report, cancel=cancel,
                                log=log_line)
        fresh, _ = core_document.load_analysis(ws, analysis_id)
        updated = apply_build(fresh, result)
        saved = core_document.save_analysis(ws, analysis_id, updated)
        core_document.DOCUMENTS.put(saved["doc"], doc_path)
        return {
            "kind": JOB_KIND,
            "doc": core_document.jsonable(saved["doc"]),
            "canvas": result["canvas"],
            "stats": result["stats"],
            "outputs": result["outputs"],
        }

    try:
        job = JOBS.submit_thread(JOB_KIND, fn, exclusive=LEASE)
    except Busy as e:
        raise ApiError(409, "busy", str(e)) from e
    box["job"] = job
    return {"job_id": job.job_id, "kind": job.kind}


@router.get("/api/videomosaic/{analysis_id}/outputs/{name}", response_class=Response,
            include_in_schema=True)
def get_output(analysis_id: str, name: str, v: str | None = None) -> Response:
    """One built artifact, addressed by its LOGICAL name (`mosaic.png` / `preview.png` /
    `positions.csv` / `build.json`) and resolved to the real file through the document's
    `build.outputs` — on disk it lives in `outputs/`, named after the project (R44).

    `v` is the cache-buster the UI appends (the build's `built_at`); the response itself says
    no-store because a rebuild overwrites in place."""
    entry = OUTPUT_FILES.get(name)
    if entry is None:
        raise ApiError(404, "not_found", f"no such output {name!r}; "
                       f"outputs are {sorted(OUTPUT_FILES)}")
    logical, media = entry
    ws = _projects()
    try:
        folder = ws.outputs_dir(analysis_id)
    except Exception as e:                                   # noqa: BLE001
        raise _project_error(e) from e

    filename = name                                          # pre-R43 projects used it literally
    try:
        doc, _ = core_document.load_analysis(ws, analysis_id)
        recorded = ((doc.get("build") or {}).get("outputs") or {}).get(logical)
        if isinstance(recorded, str) and recorded:
            filename = Path(recorded).name                   # a name, never a path off the folder
    except Exception:                                        # noqa: BLE001
        pass                                                 # no document is a 404 below, not a 500

    p = folder / filename
    if not p.is_file():
        raise ApiError(404, "not_found",
                       "this project has no built mosaic yet — run the build first")
    return FileResponse(p, media_type=media, headers={"Cache-Control": "no-store"})


# ⛔ **`POST /api/videomosaic/save` was DELETED on 2026-08-10 (R44).** It moved a draft into the
# folder the user named while looking at the finished mosaic. There is no draft and no folder to
# name: the project has been in the store since Create. Taking a copy of the mosaic somewhere is
# `POST /api/projects/{id}/outputs/copy` — core's, shared, and available to every feature.


# =================================================================================================
# Electrodes — the grid identity of the SAVED video mosaic (2026-08-11)
# =================================================================================================

ELECTRODE_JOB_KIND = "electrode_map"


@router.post("/api/videomosaic/electrodes/map", response_model=JobRef, status_code=202)
def post_electrodes_map(body: VideoElectrodeMapRequest) -> dict:
    """`POST /api/videomosaic/electrodes/map` -> **202 `JobRef`**. Fit the electrode lattice of
    the built `mosaic.png` — its canvas is 1:1 with video pixels, so the map needs no offset.

    ⭐ Same artifacts and block as the mosaic feature (`<name>-electrodes.json/.csv` in
    `outputs/`, R44), but here the DOCUMENT IS SERVER-OWNED: the job saves `electrodes` into it
    and returns the saved doc, exactly like the build job. `source_stamp` is the build's
    `built_at` — a rebuild makes the map stale, and the GET below says so.

    ⭐ `array_coverage` is HIS declaration (R45.8), same contract as the snapshot route:
    `"full"` holds the fit to the MaxOne/MaxTwo's 220 × 120 (near miss corrected and reported,
    far miss refused); `"partial"` enforces only the 17.5 µm scale and leaves `1-1` meaning the
    top-left of the IMAGED REGION. Defaulted `"partial"` — the mode that assumes nothing."""
    analysis_id = body.analysis_id
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
                       "not a video mosaic")
    build = doc.get("build") or {}
    mosaic_name = (build.get("outputs") or {}).get("mosaic")
    if not build.get("built_at") or not isinstance(mosaic_name, str) or not mosaic_name:
        raise ApiError(409, "refused",
                       "this project has no built mosaic yet — run the build first")
    out_dir = ws.outputs_dir(analysis_id)
    doc_path = ws.document_path(analysis_id)
    mosaic_path = out_dir / Path(mosaic_name).name           # a name, never a path
    if not mosaic_path.is_file():
        raise ApiError(409, "refused",
                       f"the built mosaic file is missing ({mosaic_path.name}) — rebuild first")
    try:
        base = safe_basename(str(doc.get("name") or "") or analysis_id)
    except ValueError:
        base = safe_basename(analysis_id)
    built_stamp = str(build.get("built_at") or "")
    coverage = body.array_coverage

    def fn(report, cancel):
        import time

        import numpy as np
        from PIL import Image

        from camea.core import electrodegrid
        from camea.core import jobs as core_jobs

        core_jobs.say(report, "read", 0, 3, 0.0, "reading the mosaic")
        Image.MAX_IMAGE_PIXELS = None
        im = Image.open(mosaic_path)
        # mode "P": the index plane IS the toned grey composite (the palette only tints it),
        # so reading indices directly beats a palette->RGB->grey round trip
        arr = np.asarray(im if im.mode == "P" else im.convert("L"), np.float32)

        # ⭐ Coverage is GEOMETRY, not pixels: the toned composite maps its darkest covered
        # pixels to exactly 0 too, and treating those as "no data" riddles the mask with
        # speckle holes that the high-pass erosion then blows up into dead zones (measured:
        # it cost 97 % of the pads on the synthetic survey). The document's placed keyframes
        # ARE the coverage — same rule as the snapshot exporter's mandatory mask.
        valid = np.zeros(arr.shape, bool)
        src_info = doc.get("source") or {}
        fw, fh = int(src_info.get("width") or 0), int(src_info.get("height") or 0)
        if fw > 0 and fh > 0:
            for kf in (doc.get("keyframes") or {}).values():
                if not (isinstance(kf, dict) and kf.get("placed")
                        and kf.get("x") is not None and kf.get("y") is not None):
                    continue
                x, y = int(round(float(kf["x"]))), int(round(float(kf["y"])))
                y0, y1 = max(0, y), min(arr.shape[0], y + fh)
                x0, x1 = max(0, x), min(arr.shape[1], x + fw)
                if y1 > y0 and x1 > x0:
                    valid[y0:y1, x0:x1] = True
        if not valid.any():
            valid = arr > 0                      # geometric facts missing: pixel fallback

        def prog(msg: str) -> None:
            core_jobs.check_cancelled(cancel, "electrode map")
            steps = electrodegrid.FIT_STEPS
            idx = steps.index(msg) if msg in steps else 0
            # ⚠️ `Progress.pct` is 0-100, not 0-1
            core_jobs.say(report, "fit", 1, 3, 100.0 * idx / len(steps), msg)

        # ⭐ R45.8. The device goes in for BOTH modes — it is what buys the µm scale (17.5 µm
        # over the pitch this mosaic measures). Only the 220 × 120 shape rule is conditional,
        # and only on what HE declared; a far-off fit under `full` raises and the job fails.
        gm = electrodegrid.fit_grid(arr, valid=valid, progress=prog,
                                    device=electrodegrid.MAXWELL,
                                    enforce_shape=(coverage == "full"))

        core_jobs.say(report, "write", 2, 3, 0.0, "writing the electrode table")
        built_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        payload = electrodegrid.full_payload(
            gm,
            canvas_offset=(0.0, 0.0),
            coordinates=None,
            built_at=built_at,
            source_stamp=built_stamp,
            array_coverage=coverage,
            feature="videomosaic",
            space="canvas px (1:1 with mosaic.png)",
        )
        names = {"map": f"{base}-electrodes.json", "csv": f"{base}-electrodes.csv"}
        electrodegrid.write_map_files(payload, out_dir / names["map"], out_dir / names["csv"])
        # the block records the coverage he declared, the µm scale it bought and the device
        # name — the same three R45.8 keys the snapshot feature saves, from the same helper,
        # so the SERVER-owned document and the CLIENT-owned one cannot disagree
        block = electrodegrid.summary_block(
            gm, built_at=built_at, outputs=names, source_stamp=built_stamp, coordinates=None,
            array_coverage=coverage)

        fresh, _ = core_document.load_analysis(ws, analysis_id)
        fresh["electrodes"] = block
        saved = core_document.save_analysis(ws, analysis_id, fresh)
        core_document.DOCUMENTS.put(saved["doc"], doc_path)
        return {"kind": ELECTRODE_JOB_KIND, "analysis_id": analysis_id,
                "electrodes": block, "doc": core_document.jsonable(saved["doc"])}

    try:
        job = JOBS.submit_thread(ELECTRODE_JOB_KIND, fn, exclusive=LEASE)
    except Busy as e:
        raise ApiError(409, "busy", str(e)) from e
    return {"job_id": job.job_id, "kind": ELECTRODE_JOB_KIND}


@router.get("/api/videomosaic/{analysis_id}/electrodes", response_model=ElectrodeMapPayload)
def get_electrode_map(analysis_id: str) -> dict:
    """The full electrode map + `stale` (the map's `source_stamp` vs the current build's
    `built_at` — a rebuilt mosaic invalidates the map and the UI says so)."""
    from camea.core import electrodegrid  # noqa: PLC0415

    ws = _projects()
    try:
        folder = ws.outputs_dir(analysis_id)
    except Exception as e:                                   # noqa: BLE001
        raise _project_error(e) from e
    doc: dict = {}
    try:
        doc, _ = core_document.load_analysis(ws, analysis_id)
    except Exception:                                        # noqa: BLE001
        pass                                                 # the file fallback still serves

    name = (((doc.get("electrodes") or {}).get("outputs")) or {}).get("map")
    payload = electrodegrid.load_map_file(folder, name if isinstance(name, str) else None)
    if payload is None:
        raise ApiError(404, "not_found",
                       "this project has no electrode map yet — run Map electrodes first")
    built = str(((doc.get("build") or {}).get("built_at")) or "")
    stale = str(payload.get("source_stamp") or "") != built
    return {**payload, "stale": stale}


__all__ = ["router", "ApiError", "set_store", "JOB_KIND", "FEATURE"]
