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

import os
from pathlib import Path
from typing import Callable

import numpy as np

from fastapi import APIRouter
from fastapi.exceptions import HTTPException
from fastapi.responses import FileResponse, Response

from camea.api.schemas import (  # schemas is deliberately importable by features
    AnalysisSummary,
    CreateVideoProjectRequest,
    ElectrodeMapPayload,
    ElectrodeTracePayload,
    ErrorCode,
    JobRef,
    LocateRegionRequest,
    MeaAttachment,
    MeaAttachRequest,
    MeaOrientationRequest,
    RegionRecord,
    RegionsPayload,
    RegionUpdateRequest,
    SnapRegionRequest,
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

from . import canvas as vcanvas
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
    out_dir = ws.outputs_dir(analysis_id)
    doc_path = ws.document_path(analysis_id)
    try:
        vcanvas.mosaic_path(doc, out_dir)        # the two refusals, stated in ONE place
    except vcanvas.MosaicMissing as e:
        raise ApiError(409, "refused", str(e)) from e
    try:
        base = safe_basename(str(doc.get("name") or "") or analysis_id)
    except ValueError:
        base = safe_basename(analysis_id)
    built_stamp = str(build.get("built_at") or "")
    coverage = body.array_coverage

    def fn(report, cancel):
        import time

        from camea.core import electrodegrid
        from camea.core import jobs as core_jobs

        from . import canvas as vcanvas

        core_jobs.say(report, "read", 0, 3, 0.0, "reading the mosaic")
        # ⭐ ONE read-back, shared with the region-locating stage — see `canvas.read_mosaic`
        # for why coverage is geometry and never `png > 0`.
        arr, valid = vcanvas.read_mosaic(doc, out_dir)

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


# =================================================================================================
# REGION RECORDINGS — where a fixed-field calcium video sits on this mosaic *(2026-08-11)*
# =================================================================================================
#
# The last step of the pipeline: build the mosaic, number the electrodes, then place each
# fixed-field recording on it so the electrodes it covers can be named. The document is
# SERVER-owned here, exactly like the build and the electrode map — every job below re-loads the
# document fresh, mutates one key, saves, and returns the saved doc for the UI to adopt.

REGION_JOB_KIND = "locate_region"


def _video_project(analysis_id: str) -> tuple[dict, core_project.ProjectSet]:
    """The project's document, or the right refusal. Shared by every region route."""
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
    return doc, ws


def _region_basename(doc: dict, analysis_id: str) -> str:
    try:
        return safe_basename(str(doc.get("name") or "") or analysis_id)
    except ValueError:
        return safe_basename(analysis_id)


def _save_regions(ws, analysis_id: str, regions: list[dict]) -> dict:
    """Write `regions` into the SAVED document and rewrite the outputs files. -> the saved doc.

    ⭐ Always re-load fresh. The document captured when a job was submitted is minutes old by
    the time the job lands, and a build or an electrode map may have written it meanwhile.
    """
    from . import regions as vregions

    fresh, _ = core_document.load_analysis(ws, analysis_id)
    fresh["regions"] = regions
    out_dir = ws.outputs_dir(analysis_id)
    vregions.write_region_files(fresh, out_dir, _region_basename(fresh, analysis_id))
    saved = core_document.save_analysis(ws, analysis_id, fresh)
    core_document.DOCUMENTS.put(saved["doc"], ws.document_path(analysis_id))
    return saved["doc"]


def _adopt_video(ws, analysis_id: str, path: str) -> Path:
    """Copy a recording into the project and hand back its new home.

    ⭐ **The project HOLDS its files** (his ruling, 2026-08-11: *"the project is what holds the
    project files"*). A located region must stay locatable after the original video is moved,
    renamed or deleted, so the video is copied into `<project>/videos/` and everything downstream
    reads it from there. `Project.own_entries` includes that folder, so a project that moves
    takes its recordings with it.

    A file already in the project with the same name and size is adopted rather than re-copied —
    re-locating a recording must not multiply it on disk.
    """
    import shutil

    src = Path(path).expanduser()
    if not src.is_file():
        raise ApiError(400, "bad_request", f"no video file at {src.as_posix()}")
    try:
        dest_dir = ws.videos_dir(analysis_id)
    except Exception as e:                                   # noqa: BLE001
        raise _project_error(e) from e
    if src.resolve().parent == Path(dest_dir).resolve():
        return src                                           # already ours
    try:
        dest = Path(dest_dir) / safe_basename(src.name)
    except ValueError:
        dest = Path(dest_dir) / f"recording{src.suffix}"
    if dest.exists() and dest.stat().st_size == src.stat().st_size:
        return dest
    stem, suffix = dest.stem, dest.suffix
    k = 2
    while dest.exists():
        dest = Path(dest_dir) / f"{stem}-{k}{suffix}"
        k += 1
    try:
        shutil.copy2(src, dest)
    except OSError as e:
        raise ApiError(500, "io_error", f"could not copy {src.name} into the project: {e}") from e
    return dest


@router.post("/api/videomosaic/regions/locate", status_code=202, response_model=JobRef)
def post_locate_region(body: LocateRegionRequest) -> dict:
    """`POST /api/videomosaic/regions/locate` -> **202 `JobRef`**. Add a fixed-field recording
    and find where on the built mosaic it was taken.

    ⭐ The zoom is MEASURED, not searched: the electrode lattice appears in both pictures and the
    ratio of the two pitches is the magnification ratio. Several stills (median / max / std) are
    built from one decode and each is matched, because whether the neurons are bright at rest or
    only when firing is a property of the preparation.

    ⚠️ Refuses without a built mosaic, and without an electrode map — the pipeline is step by
    step (his ruling), and a location whose electrodes cannot be named is half an answer.
    """
    analysis_id = body.analysis_id
    doc, ws = _video_project(analysis_id)
    out_dir = ws.outputs_dir(analysis_id)
    try:
        vcanvas.mosaic_path(doc, out_dir)
    except vcanvas.MosaicMissing as e:
        raise ApiError(409, "refused", str(e)) from e
    if not (doc.get("electrodes") or {}).get("built_at"):
        raise ApiError(409, "refused",
                       "map the electrodes first — locating a recording is only useful once "
                       "the electrodes under it can be named")
    if not body.path.strip():
        raise ApiError(400, "bad_request", "give the path of a recording to locate")

    video = _adopt_video(ws, analysis_id, body.path.strip())
    base = _region_basename(doc, analysis_id)
    label = body.name

    def fn(report, cancel):
        from . import regions as vregions

        fresh, _ = core_document.load_analysis(ws, analysis_id)
        region = vregions.locate_region(fresh, out_dir, base, video, name=label,
                                        report=report, cancel=cancel)
        kept = [r for r in (fresh.get("regions") or [])
                if str(r.get("id")) != str(region["id"])]
        saved = _save_regions(ws, analysis_id, [*kept, region])
        return {"kind": REGION_JOB_KIND, "analysis_id": analysis_id, "region": region,
                "doc": core_document.jsonable(saved)}

    try:
        job = JOBS.submit_thread(REGION_JOB_KIND, fn, exclusive=LEASE)
    except Busy as e:
        raise ApiError(409, "busy", str(e)) from e
    return {"job_id": job.job_id, "kind": REGION_JOB_KIND}


@router.post("/api/videomosaic/regions/snap", status_code=202, response_model=JobRef)
def post_snap_region(body: SnapRegionRequest) -> dict:
    """`POST /api/videomosaic/regions/snap` -> **202 `JobRef`**. *"I dragged it here, now snap
    it"* — a bounded local re-search seeded where the user dropped the rectangle.

    ⭐ Correct beats fast (R23): the committed number is the server's masked NCC on the real
    pixels, not a browser-side guess. About a second, and his ruling accepts that.
    """
    analysis_id = body.analysis_id
    doc, ws = _video_project(analysis_id)
    out_dir = ws.outputs_dir(analysis_id)
    regions = list(doc.get("regions") or [])
    target = next((r for r in regions if str(r.get("id")) == body.region_id), None)
    if target is None:
        raise ApiError(404, "not_found", f"no region {body.region_id!r} in this project")
    at = (float(body.x), float(body.y))
    radius = body.radius

    def fn(report, cancel):
        from camea.core import locate as core_locate

        from . import regions as vregions

        fresh, _ = core_document.load_analysis(ws, analysis_id)
        rs = list(fresh.get("regions") or [])
        cur = next((r for r in rs if str(r.get("id")) == body.region_id), target)
        try:
            updated = vregions.resnap_region(fresh, out_dir, cur, at, radius=radius,
                                             report=report, cancel=cancel)
        except core_locate.NoLocation as e:
            raise RuntimeError(str(e)) from e
        rs = [updated if str(r.get("id")) == body.region_id else r for r in rs]
        saved = _save_regions(ws, analysis_id, rs)
        return {"kind": REGION_JOB_KIND, "analysis_id": analysis_id, "region": updated,
                "doc": core_document.jsonable(saved)}

    try:
        job = JOBS.submit_thread(REGION_JOB_KIND, fn, exclusive=LEASE)
    except Busy as e:
        raise ApiError(409, "busy", str(e)) from e
    return {"job_id": job.job_id, "kind": REGION_JOB_KIND}


@router.patch("/api/videomosaic/regions", response_model=RegionRecord)
def patch_region(body: RegionUpdateRequest) -> dict:
    """Rename a region, or confirm it. Both are the user's word, so both are synchronous.

    ⭐ **Confirm is the human's signature.** A located region is `unconfirmed` until he says
    otherwise; nothing here ever promotes itself, which is I3 (nothing is auto-anchored) applied
    to a rectangle instead of a tile.
    """
    doc, ws = _video_project(body.analysis_id)
    regions = list(doc.get("regions") or [])
    idx = next((i for i, r in enumerate(regions)
                if str(r.get("id")) == body.region_id), None)
    if idx is None:
        raise ApiError(404, "not_found", f"no region {body.region_id!r} in this project")

    updated = dict(regions[idx])
    if body.name is not None:
        label = body.name.strip()
        if not label:
            raise ApiError(400, "bad_request", "a region needs a name")
        updated["name"] = label
    if body.status is not None:
        updated["status"] = body.status
    regions[idx] = updated
    _save_regions(ws, body.analysis_id, regions)
    return updated


@router.delete("/api/videomosaic/{analysis_id}/regions/{region_id}",
               response_model=RegionsPayload)
def delete_region(analysis_id: str, region_id: str) -> dict:
    """Forget a located region. Its still goes with it, and so does the project's copy of the
    recording — unless another region is still using that same file. The project holds the files,
    so removing the region removes what it brought in; but it must not remove what something else
    still needs."""
    doc, ws = _video_project(analysis_id)
    regions = list(doc.get("regions") or [])
    gone = next((r for r in regions if str(r.get("id")) == region_id), None)
    if gone is None:
        raise ApiError(404, "not_found", f"no region {region_id!r} in this project")

    out_dir = ws.outputs_dir(analysis_id)
    still = gone.get("still")
    if isinstance(still, str) and still:
        try:
            (out_dir / Path(still).name).unlink(missing_ok=True)
        except OSError:
            pass                                  # a locked still is not a failed delete

    keep = [r for r in regions if r is not gone]
    video = str(((gone.get("source") or {}).get("path")) or "")
    if video:
        others = {str(((r.get("source") or {}).get("path")) or "") for r in keep}
        vp = Path(video)
        try:
            inside = vp.parent.resolve() == Path(ws.videos_dir(analysis_id)).resolve()
        except Exception:                         # noqa: BLE001
            inside = False
        # ⛔ Only ever OUR copy, and only when nothing else points at it. The original the user
        # chose is his and is never touched (R44's write guard in spirit).
        if inside and video not in others:
            try:
                vp.unlink(missing_ok=True)
            except OSError:
                pass
    saved = _save_regions(ws, analysis_id, keep)
    return _regions_payload(analysis_id, saved, ws)


@router.get("/api/videomosaic/{analysis_id}/regions", response_model=RegionsPayload)
def get_regions(analysis_id: str) -> dict:
    """Every located region + `stale` (rebuild the mosaic and every location is stale)."""
    doc, ws = _video_project(analysis_id)
    return _regions_payload(analysis_id, doc, ws)


def _regions_payload(analysis_id: str, doc: dict, ws) -> dict:
    built = str((doc.get("build") or {}).get("built_at") or "")
    regions = list(doc.get("regions") or [])
    stale = any(str(r.get("source_stamp") or "") != built for r in regions)
    base = _region_basename(doc, analysis_id)
    return {"analysis_id": analysis_id, "regions": regions, "built_from": built or None,
            "stale": stale,
            "outputs": {"regions": f"{base}-regions.json", "csv": f"{base}-regions.csv"}}


# =================================================================================================
# THE ELECTRICAL HALF — attaching a MaxWell recording, and reading one electrode's trace
# =================================================================================================
#
# ⭐ The optical half of this feature says WHERE each electrode is; these routes say WHAT it
# recorded. Clicking a pad and seeing its trace is where the ground-truth pairing first becomes
# visible (see `utils/knowledge/mea-calcium-goal.md`).
#
# ⛔ **NOTHING HERE WRITES OUTSIDE THE PROJECT** (R44). The recordings are read in place from the
# read-only mirror; the project stores only the *path* to them plus the seating the user confirmed.
# ⛔ **AND NOTHING HERE DECIDES A PAIRING.** Attachment is proposed and confirmed; the chip's
# seating stays `confirmed: false` until something establishes it. An unconfirmed pairing is
# reported as provisional, never as an answer.

#: How much trace one request may return. A 300 s window at 20 kHz is 6M floats — far past what a
#: chart can draw and past what JSON should carry. The UI asks for the window it is showing.
MAX_TRACE_SECONDS = 30.0


def _mea_block(doc: dict) -> dict:
    return dict(doc.get("mea") or {})


def _orientation_of(block: dict):
    from camea.core import mearecording  # noqa: PLC0415

    o = dict(block.get("orientation") or {})
    return mearecording.Orientation(
        flip_x=bool(o.get("flip_x", False)),
        flip_y=bool(o.get("flip_y", False)),
        confirmed=bool(o.get("confirmed", False)),
        source=str(o.get("source") or ""),
    )


def _summarise(paths: list[Path]) -> tuple[list[dict], int | None, float | None]:
    """Header facts for each recording + the chip layout they agree on.

    The layout is DERIVED per file and must agree across them; a disagreement means the folder
    holds recordings from different devices, which we refuse rather than average.
    """
    from camea.core import mearecording  # noqa: PLC0415

    out: list[dict] = []
    stride: int | None = None
    pitch: float | None = None
    for p in paths:
        try:
            with mearecording.MeaRecording(p) as r:
                out.append(r.info().as_dict())
                s, q = r.stride(), r.pitch_um()
        except mearecording.MeaError:
            continue
        if stride is None:
            stride, pitch = s, q
        elif s != stride:
            raise ApiError(409, "refused",
                           "these recordings describe different chip layouts "
                           f"(stride {stride} vs {s}) — they cannot belong to one project")
    return out, stride, pitch


@router.get("/api/videomosaic/{analysis_id}/mea", response_model=MeaAttachment)
def get_mea(analysis_id: str) -> dict:
    """What electrical data this project has. Empty-but-fine when nothing is attached yet."""
    from camea.core import mearecording  # noqa: PLC0415

    doc, _ = _video_project(analysis_id)
    block = _mea_block(doc)
    present = mearecording.plugin_present()
    if not block.get("mea_dir"):
        return {"attached": False, "recordings": [], "decoder_present": present,
                "orientation": _orientation_of(block).as_dict()}
    paths = mearecording.find_recordings(block["mea_dir"])
    recs, stride, pitch = _summarise(paths)
    return {"attached": bool(recs), "mea_dir": block["mea_dir"], "recordings": recs,
            "stride": stride, "pitch_um": pitch, "decoder_present": present,
            "orientation": _orientation_of(block).as_dict()}


@router.post("/api/videomosaic/mea/attach", response_model=MeaAttachment)
def post_mea_attach(body: MeaAttachRequest) -> dict:
    """Find the recordings that belong to a project — and, on `confirm`, remember them.

    ⭐ Two-step ON PURPOSE. Without `confirm` this only *reports* what it found, so the user sees
    the actual paths before anything is written. Attaching the wrong plate would pair one culture's
    voltages with another culture's neurons — silently, and in a dataset meant to be ground truth.
    """
    from camea.core import mearecording  # noqa: PLC0415

    doc, ws = _video_project(body.analysis_id)
    if body.mea_dir:
        root = Path(body.mea_dir)
        if not root.is_dir():
            raise ApiError(404, "not_found", f"no folder at {body.mea_dir}")
        paths = mearecording.find_recordings(root)
        if not paths:
            raise ApiError(404, "not_found",
                           f"no {mearecording.MEA_FILENAME} anywhere under {body.mea_dir}")
    else:
        data_dir = str(doc.get("data_dir") or "")
        if not data_dir:
            raise ApiError(409, "refused",
                           "this project does not record where its data came from, so there is "
                           "nowhere to look — name the recording folder instead")
        paths = mearecording.suggest_recordings(data_dir, str(doc.get("name") or ""))
        if not paths:
            raise ApiError(404, "not_found",
                           "no MaxWell recordings found near this project's data folder")
        root = Path(os.path.commonpath([str(p.parent) for p in paths]))
        # With a single recording the common path IS its run folder, which would freeze the
        # attachment to that one run — a later run in the same assay would never be found. Step
        # out to the folder that HOLDS runs so the attachment stays true as the session grows.
        if (root / mearecording.MEA_FILENAME).is_file():
            root = root.parent

    recs, stride, pitch = _summarise(paths)
    if not recs:
        raise ApiError(422, "refused",
                       "found recording files but none could be read as a MaxLab recording")
    orientation = (mearecording.Orientation(**body.orientation.model_dump())
                   if body.orientation else _orientation_of(_mea_block(doc)))
    payload = {"attached": True, "mea_dir": str(root).replace("\\", "/"), "recordings": recs,
               "stride": stride, "pitch_um": pitch,
               "decoder_present": mearecording.plugin_present(),
               "orientation": orientation.as_dict()}
    if body.confirm:
        fresh, _ = core_document.load_analysis(ws, body.analysis_id)
        fresh["mea"] = {"mea_dir": payload["mea_dir"], "orientation": orientation.as_dict(),
                        "stride": stride, "pitch_um": pitch}
        saved = core_document.save_analysis(ws, body.analysis_id, fresh)
        core_document.DOCUMENTS.put(saved["doc"], ws.document_path(body.analysis_id))
    return payload


@router.get("/api/videomosaic/{analysis_id}/mea/trace", response_model=ElectrodeTracePayload)
def get_mea_trace(analysis_id: str, electrode: str, run_id: str | None = None,
                  t0: float = 0.0, t1: float | None = None) -> dict:
    """One electrode's stored trace and its spikes, for the window `[t0, t1)`.

    `electrode` is the Camea grid id the user clicked (`"col-row"`). Resolving it to a MaxWell
    channel needs the chip's seating, which is why `orientation` rides on the response: while it is
    unconfirmed the caller must present the identity as provisional.

    ⚠️ `health` is not decoration. The published MaxWell decoder does not reconstruct this
    project's files, and a railed window drawn without that caveat looks exactly like a real
    silent electrode. See `core/mearecording.py`.
    """
    from camea.core import mearecording  # noqa: PLC0415

    doc, ws = _video_project(analysis_id)
    block = _mea_block(doc)
    if not block.get("mea_dir"):
        raise ApiError(409, "refused", "no MEA recording is attached to this project")

    grid = dict(doc.get("electrodes") or {})
    cols, rows = int(grid.get("cols") or 0), int(grid.get("rows") or 0)
    if not (cols and rows):
        raise ApiError(409, "refused",
                       "this project has no electrode map yet — map the electrodes first")
    try:
        col, row = (int(v) for v in electrode.split("-", 1))
    except ValueError as e:
        raise ApiError(422, "refused",
                       f"{electrode!r} is not a 'col-row' electrode id") from e
    if not (1 <= col <= cols and 1 <= row <= rows):
        raise ApiError(404, "not_found",
                       f"electrode {electrode} is outside this {cols}x{rows} map")

    paths = mearecording.find_recordings(block["mea_dir"])
    if run_id:
        paths = [p for p in paths if p.parent.name == run_id]
    if not paths:
        raise ApiError(404, "not_found", "that recording is no longer where the project left it")

    orientation = _orientation_of(block)
    with mearecording.MeaRecording(paths[0]) as r:
        info = r.info()
        stride = r.stride()
        chip = orientation.chip_electrode(col, row, cols=cols, rows=rows, stride=stride)
        channel = r.channel_of_electrode(chip)
        base = {"electrode": electrode, "run_id": info.run_id, "chip_electrode": chip,
                "orientation": orientation.as_dict(), "sampling_hz": info.sampling_hz}
        if channel is None:
            # The ordinary case: this pad was never routed. A fact, not a failure.
            return {**base, "recorded": False, "t0_s": 0.0, "t1_s": 0.0}

        end = info.duration_s if t1 is None else float(t1)
        start = max(0.0, float(t0))
        end = min(end, start + MAX_TRACE_SECONDS, info.duration_s)
        if end <= start:
            raise ApiError(422, "refused", "the requested window is empty")

        spikes = r.spikes_of_channel(channel)
        # Where the activity starts, so the caller can open ITS window somewhere worth looking
        # rather than at t=0. Clamped at 0: a few spikes are logged during the pre-roll, i.e.
        # before the first stored sample, and a negative window start is not a real window.
        first = float(max(0.0, spikes["t_s"].min())) if spikes.size else None
        window = spikes[(spikes["t_s"] >= start) & (spikes["t_s"] < end)]
        out = {**base, "recorded": True, "channel": channel, "t0_s": start, "t1_s": end,
               "n_spikes_total": int(spikes.size), "first_spike_s": first,
               "duration_s": info.duration_s,
               "spikes": [{"t_s": float(s["t_s"]), "amplitude_uv": float(s["amplitude_uv"])}
                          for s in window]}
        try:
            out["trace_uv"] = [float(v) for v in r.trace(channel, start, end)]
            out["health"] = r.trace_health(channel, start, end).as_dict()
            # ⭐ The 2P lamp marks, for THIS window only. Bounded deliberately: over the whole
            # recording this is a full pass of the raw stream (~16 s) and has no business inside a
            # request. A shorter floor than the default too — a mark clipped by the window edge
            # would vanish entirely at 0.5 s, and the point of drawing them is that they are there.
            out["sync_episodes"] = [
                e.as_dict() for e in r.sync_episodes(start, end, min_duration_s=0.02)
            ]
        except mearecording.RawUndecodable as e:
            # The spikes above are still good — return them and say the waveform is unavailable.
            out["trace_uv"] = []
            out["health"] = None
            out["decode_error"] = str(e)
        return out


ORIENTATION_JOB_KIND = "mea_orientation"

#: How far the best correlation must beat the runner-up before the test claims it separated them.
#: Measured on this project's data, the four seatings of P003693 land within 0.04 of each other
#: (-0.137 to -0.175) — noise. Same instinct as the mosaic's `margin_thin`: a win by nothing is not
#: a win, and it must be reported as "cannot tell" rather than as the top of a list.
MIN_CORRELATION_MARGIN = 0.10

#: 🔴 Shown verbatim wherever the result is. Not behind a `?` — the whole point is that a reader
#: who glances at the winning seating still learns it is not evidence (issue 003).
ORIENTATION_CAVEAT = (
    "This ranking is NOT confirmation. It aligns the two clocks using the 2P lamp marks, and those "
    "marks did not survive checking against the calcium video — 70 electrical episodes against 5 "
    "dark stretches in the video, with no time-shift lining them up. The episodes may also be an "
    "artefact of the raw stream failing to decode rather than the lamp firing. Treat the winner as "
    "a suggestion to check, not an answer, and re-run this once the MaxLab decoder is in place."
)


@router.post("/api/videomosaic/mea/orientation", status_code=202, response_model=JobRef)
def post_mea_orientation(body: MeaOrientationRequest) -> dict:
    """Score the four chip seatings against a located region (202 + `JobRef`).

    A job because it reads every frame of the region recording and makes a full pass over the MEA
    spike table — minutes, not milliseconds.

    ⭐ **IT PROPOSES; IT NEVER APPLIES.** The winning seating comes back in the result and a human
    confirms it through `POST /mea/attach`. That is his rule for the whole app and it matters most
    here: a wrong seating pairs every neuron with the wrong electrode, and would do so invisibly.
    """
    from camea.core import mearecording  # noqa: PLC0415

    from . import orientation as vorient  # noqa: PLC0415

    analysis_id = body.analysis_id
    doc, ws = _video_project(analysis_id)
    block = _mea_block(doc)
    if not block.get("mea_dir"):
        raise ApiError(409, "refused", "no MEA recording is attached to this project")

    grid = dict(doc.get("electrodes") or {})
    cols, rows = int(grid.get("cols") or 0), int(grid.get("rows") or 0)
    if not (cols and rows):
        raise ApiError(409, "refused", "map the electrodes before testing the orientation")

    regions = list(doc.get("regions") or [])
    if body.region_id:
        regions = [r for r in regions if str(r.get("id")) == body.region_id]
    if not regions:
        raise ApiError(409, "refused",
                       "this test needs a located region recording — the electrodes under a field "
                       "are what its spikes are compared against. Locate one first.")
    region = regions[0]
    ids = list((region.get("electrodes") or {}).get("ids") or [])
    if not ids:
        raise ApiError(409, "refused",
                       "that region has no electrodes named under it, so there is nothing to score")
    video = str((region.get("source") or {}).get("path") or "")
    if not video or not Path(video).is_file():
        raise ApiError(404, "not_found",
                       "the region's own recording is not where the project left it")

    paths = mearecording.find_recordings(block["mea_dir"])
    if body.run_id:
        paths = [p for p in paths if p.parent.name == body.run_id]
    if not paths:
        raise ApiError(404, "not_found", "no MEA recording to test against")
    rec_path = paths[0]

    def fn(report, cancel):
        from camea.core import jobs as core_jobs  # noqa: PLC0415

        core_jobs.say(report, "video", 1, 3, 0.0, "reading the region recording")
        calcium, _fps = vorient.video_activity(video)
        core_jobs.check_cancelled(cancel, "orientation test")
        duration = calcium.size * vorient.BIN_S

        core_jobs.say(report, "mea", 2, 3, 0.0, "reading the electrical recording")
        with mearecording.MeaRecording(rec_path) as r:
            info = r.info()
            stride = r.stride()
            m = r.mapping()
            channel_of = {int(e): int(c) for e, c in zip(m["electrode"], m["channel"])}
            sp = r.spikes()
            spikes_of: dict[int, np.ndarray] = {}
            for ch in np.unique(sp["channel"]):
                spikes_of[int(ch)] = sp["t_s"][sp["channel"] == ch]
            # The lamp marks on each side, and the shift that best lines them up.
            try:
                eps = r.sync_episodes()
                mea_mask = vorient.intervals_to_mask(
                    [(e.start_s, e.end_s) for e in eps], info.duration_s)
            except mearecording.RawUndecodable:
                mea_mask = np.zeros(0, dtype=bool)
        core_jobs.check_cancelled(cancel, "orientation test")

        core_jobs.say(report, "score", 3, 3, 0.0, "scoring the four seatings")
        lo, hi = float(calcium.min()), float(calcium.max())
        dark = calcium < (lo + 0.5 * (hi - lo)) if hi > lo else np.zeros(calcium.size, dtype=bool)
        offset, quality = vorient.align_offset(mea_mask, dark) if mea_mask.size else (0.0, 0.0)

        scores = vorient.score_seatings(
            ids, cols=cols, rows=rows, stride=stride, channel_of=channel_of,
            spikes_of=spikes_of, calcium=calcium, duration_s=duration, offset_s=offset)

        # Rank only what is scorable. A seating with no recorded electrode under the field is not a
        # loser — it is untested, and sorting it against tested ones would be a lie about the data.
        ranked = sorted((s for s in scores if s.scorable),
                        key=lambda s: (s.correlation or -1.0), reverse=True)

        # ⭐ WHAT ACTUALLY SEPARATED THEM — and whether anything did.
        #
        # Coverage first, and it is the strongest evidence this test can produce: if only ONE
        # seating puts any recorded electrode under the field, that is pure geometry. It does not
        # depend on the clock alignment, and it does not depend on the raw stream decoding — the
        # two things issue 003 says cannot be trusted here. (Measured on P003658: one seating puts
        # 210 pads under the region, the other three put none.)
        #
        # Otherwise fall back to correlation, but only if the top actually beats the runner-up. Four
        # near-identical numbers separated by 0.004 are noise, and crowning one would manufacture the
        # answer this whole feature exists to avoid.
        best = ranked[0] if ranked else None
        margin = (float(ranked[0].correlation - ranked[1].correlation)  # type: ignore[operator]
                  if len(ranked) >= 2 else None)
        if len(ranked) == 1:
            decisive, decided_by = True, "coverage"
        elif margin is not None and margin >= MIN_CORRELATION_MARGIN:
            decisive, decided_by = True, "correlation"
        else:
            decisive, decided_by = False, ""
        return {
            "kind": ORIENTATION_JOB_KIND,
            "analysis_id": analysis_id,
            "run_id": rec_path.parent.name,
            "region_id": str(region.get("id") or ""),
            "region_name": str(region.get("name") or ""),
            "scores": [s.as_dict() for s in scores],
            # ⛔ No winner at all when nothing separated them. A `best` the UI could apply would be
            # read as an answer however it was captioned.
            "best": ({"flip_x": best.flip_x, "flip_y": best.flip_y, "confirmed": False,
                      "source": f"orientation test vs region {region.get('name') or ''}".strip()}
                     if (best and decisive) else None),
            "decisive": decisive,
            "decided_by": decided_by,
            "margin": margin,
            "offset_s": float(offset),
            "alignment_quality": float(quality),
            "caveat": ORIENTATION_CAVEAT,
        }

    try:
        job = JOBS.submit_thread(ORIENTATION_JOB_KIND, fn, exclusive=LEASE)
    except Busy as e:
        raise ApiError(409, "busy", str(e)) from e
    return {"job_id": job.job_id, "kind": ORIENTATION_JOB_KIND}


__all__ = ["router", "ApiError", "set_store", "JOB_KIND", "REGION_JOB_KIND",
           "ORIENTATION_JOB_KIND", "FEATURE"]
