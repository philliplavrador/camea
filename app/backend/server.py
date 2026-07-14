"""FastAPI server. Owns the SESSION; wires loader / engine / project / export together.

OWNER: agent 3 (with app/main.py). Nobody else edits this file.
CONTRACT: app/API.md — **every endpoint below is specified there, verbatim, request and response.**
Implement what API.md says, not what seems nicer. Six other agents are coding against it right now.

WHAT THE SERVER OWNS
--------------------
    the Session (data_dir, run, frames, band, tone, texture, blank scan) — expensive, so it lives here
    the job registry (jobs.JOBS)
    the match memo (engine's LRU)
    the build result

WHAT THE SERVER DOES **NOT** OWN
--------------------------------
    ⭐ THE DOCUMENT. Tile states, positions, exclusions and the cursor are owned by the FRONT END —
    it has the undo/redo stack — and are POSTED WHOLE when the backend needs them (save, autosave,
    export). This is deliberate: it makes `POST /api/match/anchor` a **pure function of its request
    body**, which is what makes the A-branch prefetch correct BY CONSTRUCTION rather than by
    discipline (API.md §7.4). Do not add server-side tile state. It would re-open the trap.

SECURITY
--------
Bind **127.0.0.1 ONLY**. Never `0.0.0.0`. No CORS policy (it is same-origin). The port is chosen
from the OS's free-port pool and handed to the window by `main.py`.

THREADING
---------
Every handler here is a plain `def` (not `async def`). Starlette therefore runs each one in its
worker **thread pool** — which is exactly what API.md §7.4 requires: "serve match requests from a
thread pool of >= 2 workers, so a prefetch in flight never blocks the foreground request the user is
waiting on". Do not turn these into `async def` without moving the work off the loop yourself.
"""
from __future__ import annotations

import json
import socket
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------------------------
# Import bootstrap. `app` is a namespace package under the repo root; `analysis` lives beside it.
# One constant for agent 8 to redirect under PyInstaller (sys._MEIPASS).
# ---------------------------------------------------------------------------------------------
REPO_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi import FastAPI, Request                      # noqa: E402
from fastapi.exceptions import RequestValidationError     # noqa: E402
from fastapi.responses import (                           # noqa: E402
    HTMLResponse,
    JSONResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles               # noqa: E402

from app.backend import __version__                       # noqa: E402
from app.backend import engine, export, jobs, loader, project  # noqa: E402

FRONTEND_DIR = REPO_ROOT / "app" / "frontend"

# =============================================================================
# Session state (module-level; there is exactly one open session)
# =============================================================================
SESSION = None          # loader.Session | None
WINDOW = None           # the pywebview Window, injected by main.py. None when headless.
BUILD = None            # engine.build_result()'s dict | None

BASE_URL: str = ""      # set by serve(); injected into index.html as window.CAMEA_API
PROJECT_PATH: str | None = None

#: set by `main.py --data-dir`; injected into index.html as `window.CAMEA_DATA_DIR` so the Load
#: field shows what the app was launched with. The SESSION itself is opened by a background job that
#: lands ~9 s later — the front end attaches to that job (sweep.js :: attachToPendingOpen).
LAUNCH_DATA_DIR: str | None = None

_STARTED = time.time()
_LOCK = threading.RLock()

#: the tone as it was auto-computed at open — so PUT /api/tone {"auto": true} can reset without
#: re-reading 96 frames.
_AUTO_TONE: tuple[float, float, float] | None = None

#: display caches, keyed on the tone version (the ONLY thing that changes a rendered pixel).
_PNG_CACHE: dict[tuple[int, int], bytes] = {}
_THUMB_CACHE: dict[int, tuple[bytes, int]] = {}
_GPU_INFO: dict | None = None

#: the job_id of the most recent build job whose result we have already hoisted into BUILD.
_BUILD_JOB_SEEN: str | None = None


APP = FastAPI(title="Camea Mosaic Builder", version=__version__, docs_url=None, redoc_url=None)


# =============================================================================
# Errors — API.md §1: non-2xx is {"error": {"code", "message", "detail"}}
# =============================================================================
class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, detail: dict | None = None):
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail or {}
        super().__init__(message)


def _err(status: int, code: str, message: str, detail: dict | None = None) -> JSONResponse:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if detail:
        body["error"]["detail"] = detail
    return JSONResponse(status_code=status, content=body)


@APP.exception_handler(ApiError)
def _on_api_error(request: Request, exc: ApiError):
    return _err(exc.status, exc.code, exc.message, exc.detail)


@APP.exception_handler(RequestValidationError)
def _on_validation_error(request: Request, exc: RequestValidationError):
    return _err(400, "bad_request", "malformed request body", {"errors": str(exc)})


@APP.exception_handler(Exception)
def _on_unhandled(request: Request, exc: Exception):
    return _err(500, "io_error", f"{type(exc).__name__}: {exc}",
                {"traceback": traceback.format_exc()[-4000:]})


def _need_session():
    if SESSION is None:
        raise ApiError(404, "no_session", "no acquisition directory is open")
    return SESSION


def _need_jobs():
    """`jobs.JOBS` is set at import time by jobs.py's implementation. If it is still None the app is
    half-built — say so plainly rather than throwing an AttributeError at the UI."""
    if jobs.JOBS is None:
        raise ApiError(500, "io_error",
                       "the job registry is not initialised (app/backend/jobs.py :: JOBS is None)")
    return jobs.JOBS


def _need_no_build():
    """API.md §7.6 — the build owns the GPU; the sweep is disabled while it runs."""
    if jobs.JOBS is not None and jobs.JOBS.running("build") is not None:
        raise ApiError(409, "busy", "a build is running; the sweep is disabled until it finishes")


def _iso(t: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t if t is not None else time.time()))


def _report_adapter(report):
    """`loader` / `export` call `report(...)`; the registry wants a `jobs.Progress`.

    Tolerant on purpose — six agents wrote against one sentence of prose. Accepts a Progress, a
    kwargs bag, or (phase, pct, message) positionally, and never raises into the worker.
    """
    def r(*a, **kw):
        if report is None:
            return
        try:
            if a and isinstance(a[0], jobs.Progress):
                report(a[0])
                return
            if a and isinstance(a[0], dict):
                kw = {**a[0], **kw}
                a = ()
            if a:
                for key, val in zip(("phase", "pct", "message"), a):
                    kw.setdefault(key, val)
            p = jobs.Progress(
                phase=str(kw.get("phase", "")),
                phase_index=int(kw.get("phase_index", 0) or 0),
                n_phases=int(kw.get("n_phases", 1) or 1),
                pct=float(kw.get("pct", 0.0) or 0.0),
                message=str(kw.get("message", "") or ""),
                eta_s=kw.get("eta_s"),
            )
            report(p)
        except Exception:  # progress must never break a job
            pass
    return r


# =============================================================================
# App lifecycle
# =============================================================================
def create_app(repo_root: Path | None = None, window=None):
    """Build the FastAPI app. `window` is the pywebview Window (None when headless -> §13 returns
    501). Mounts `app/frontend/` at `/` as static files, and warms the GPU on a worker thread."""
    global WINDOW, FRONTEND_DIR, REPO_ROOT
    if repo_root is not None:
        REPO_ROOT = Path(repo_root)
        FRONTEND_DIR = REPO_ROOT / "app" / "frontend"
    WINDOW = window

    # -- GPU warm-up on a worker thread. Worth -497 ms off the first match, and it surfaces a
    #    broken CUDA install at LAUNCH instead of 40 minutes into a sweep. It must never be able
    #    to kill the window.
    def _warm():
        try:
            engine.warm_gpu()
        except Exception as e:  # noqa: BLE001
            print(f"[camea] GPU warm-up failed (the app still works on CPU): {e}", file=sys.stderr)
    threading.Thread(target=_warm, name="gpu-warm", daemon=True).start()

    # -- static files LAST: a mount at "/" would otherwise shadow every /api route.
    if FRONTEND_DIR.is_dir() and not any(getattr(r, "name", "") == "static" for r in APP.routes):
        APP.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="static")
    return APP


def serve(host: str = "127.0.0.1", port: int = 0) -> tuple[str, object]:
    """Start uvicorn on a daemon thread -> (base_url, server). `port=0` = pick a free one.

    We bind the socket OURSELVES and hand it to uvicorn, so the port is known before the server
    thread has even started — no polling, no race. **127.0.0.1 only. Never 0.0.0.0.**
    """
    global BASE_URL
    import uvicorn

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # 🔴 **NOT SO_REUSEADDR ON WINDOWS.** On Windows SO_REUSEADDR does not mean what it means on
    # POSIX: it lets a SECOND socket bind an address:port that a LIVE process is already listening
    # on, and the OS keeps routing to the old one. That trap has already been sprung here — a stale
    # server (PID 21988) was still holding 127.0.0.1:8791; a fresh `--port 8791` bound "successfully"
    # beside it and every request went to the STALE process, which was serving a different session's
    # pixels. SO_EXCLUSIVEADDRUSE is the Windows way to say what POSIX's SO_REUSEADDR says: the port
    # is mine, and a second bind FAILS LOUDLY (WinError 10048) instead of silently shadowing.
    if sys.platform == "win32":
        sock.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", ~socket.SO_REUSEADDR), 1)
    else:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(128)
    real_port = sock.getsockname()[1]

    BASE_URL = f"http://{host}:{real_port}"

    config = uvicorn.Config(APP, log_level="warning", access_log=False, lifespan="on")
    server = uvicorn.Server(config)
    server.config.load()

    t = threading.Thread(target=server.run, kwargs={"sockets": [sock]},
                         name="uvicorn", daemon=True)
    t.start()

    deadline = time.time() + 20.0
    while not getattr(server, "started", False) and time.time() < deadline:
        time.sleep(0.01)
    if not getattr(server, "started", False):
        raise RuntimeError("uvicorn did not start within 20 s")
    return BASE_URL, server


# =============================================================================
# The page itself — index.html with window.CAMEA_API injected BEFORE the scripts parse.
# (The front end also falls back to location.origin, which is the same thing; this just removes
# any doubt, and it is race-free in a way that a post-load evaluate_js is not.)
# =============================================================================
@APP.get("/", include_in_schema=False)
@APP.get("/index.html", include_in_schema=False)
def get_index():
    idx = FRONTEND_DIR / "index.html"
    if not idx.is_file():
        return HTMLResponse("<h1>Camea Mosaic Builder</h1><p>app/frontend/index.html is missing.</p>",
                            status_code=404)
    html = idx.read_text(encoding="utf-8")
    # ⭐ CAMEA_DATA_DIR: the directory `main.py --data-dir` was launched with. The front end reads it
    # into the Load field (`init()` has always had `if (window.CAMEA_DATA_DIR)`, but nothing ever set
    # it, so the field only ever showed a *placeholder* and the code was dead). The open itself is a
    # background job that finishes ~9 s AFTER this page loads — `sweep.js :: attachToPendingOpen()`
    # rides it. This is only the pre-filled path, so the user can see what he is looking at.
    inject = (f"<script>window.CAMEA_API = {json.dumps(BASE_URL or '')};"
              f"window.CAMEA_DATA_DIR = {json.dumps(LAUNCH_DATA_DIR or '')};</script>")
    low = html.lower()
    i = low.find("<head>")
    if i >= 0:
        html = html[: i + 6] + "\n" + inject + html[i + 6:]
    else:
        html = inject + html
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


# =============================================================================
# §14  Health / GPU
# =============================================================================
@APP.get("/api/health")
def get_health():
    """GET /api/health -> {"ok", "version", "python", "uptime_s"}"""
    return {
        "ok": True,
        "version": __version__,
        "python": ".".join(str(x) for x in sys.version_info[:3]),
        "uptime_s": round(time.time() - _STARTED, 1),
    }


@APP.get("/api/gpu")
def get_gpu():
    """GET /api/gpu -> engine.gpu_info()  (API.md §14)

    🔴 Detection MUST execute a real op — `import cupy` succeeds on a broken CUDA install. Reuse
    `t27.xp()`. Never write a second detector. (This handler does NOT contain a detector; it asks
    engine, which asks t27. That is the whole point.)
    """
    global _GPU_INFO
    if _GPU_INFO is None:
        _GPU_INFO = engine.gpu_info()
    return _GPU_INFO


# =============================================================================
# §4  Session
# =============================================================================
def _open_job(data_dir: Path, lo=None, hi=None, pass_split=None, project_path: str | None = None):
    """Submit the `open` job (2-6 s: frames + flat-field + tone + the 3.0 s texture scan)."""
    global BUILD, PROJECT_PATH

    def fn(report, cancel):
        global SESSION, BUILD, _AUTO_TONE, PROJECT_PATH
        sess = loader.open_session(
            data_dir, report=_report_adapter(report), cancel=cancel,
            lo=lo, hi=hi, pass_split=pass_split,
        )
        with _LOCK:
            SESSION = sess
            BUILD = None                     # a reload invalidates the build result (API.md §4.3)
            _AUTO_TONE = (sess.tone.lo, sess.tone.hi, sess.tone.level)
            _PNG_CACHE.clear()
            _THUMB_CACHE.clear()
            PROJECT_PATH = None
            # ⚠️ engine.py's own contract (engine.py:382): "server.py MUST call this whenever the
            # session's pixels change (a new open, or PATCH /api/session/run)". It was called in
            # exactly ONE place — the blank PUT — and never here. The composite cache and the match
            # memo were carrying the previous session's arrays across an open.
            engine.reset_caches()
        if project_path:
            doc, _warn = project.load(Path(project_path), session=sess)
            with _LOCK:
                PROJECT_PATH = str(project_path)
            # the document itself is the FRONT END's; it re-fetches it via /api/project/load.
        return get_session()

    return _need_jobs().submit_thread("open", fn)


@APP.post("/api/session/open", status_code=202)
def post_session_open(body: dict):
    """POST /api/session/open  {"data_dir", "project_path"?} -> 202 {"job_id", "kind": "open"}"""
    _need_no_build()
    data_dir = body.get("data_dir")
    if not data_dir:
        raise ApiError(400, "bad_request", "data_dir is required")
    p = Path(str(data_dir))
    if not p.is_dir():
        raise ApiError(400, "bad_request", f"not a directory: {p}")
    job = _open_job(p, project_path=body.get("project_path"))
    return {"job_id": job.job_id, "kind": "open"}


@APP.get("/api/session")
def get_session():
    """GET /api/session -> the full session object (API.md §4.2).
    404 {"error": {"code": "no_session"}} before a successful open.

    ⛔⛔ `run.trials` is EVERY genuine 512x512 snapshot on disk in range, and `excluded.trials` is
    **EMPTY**. The app carries no exclusion list and applies none (the user's ruling, 2026-07-14):
    the only things that may ever exclude a frame are the human, with `E`, and a project file he
    loaded — and both of those live in the FRONT END's document, not in this session.
    """
    s = _need_session()
    _hoist_build()
    body = s.to_json()
    # The four things the SERVER owns, not the loader.
    global _GPU_INFO
    if _GPU_INFO is None:
        try:
            _GPU_INFO = engine.gpu_info()
        except Exception:  # noqa: BLE001
            _GPU_INFO = {"available": False, "backend": "numpy", "name": None}
    body["gpu"] = _GPU_INFO
    body["build"] = None if BUILD is None else {
        k: BUILD.get(k) for k in ("build_id", "created", "n_placed", "unplaced", "seconds", "gpu")
    }
    body["project_path"] = PROJECT_PATH
    try:
        # ⚠️ `store_key`, not `dataset`: two directories both named `260620d` under different
        # parents would otherwise share one autosave file. See `loader.Session.store_key`.
        body["autosave_path"] = str(project.autosave_path(s.store_key))
    except Exception:  # noqa: BLE001
        body["autosave_path"] = None
    return body


@APP.patch("/api/session/run", status_code=202)
def patch_session_run(body: dict):
    """PATCH /api/session/run  {"lo"?, "hi"?, "pass_split"?} -> 202 {"job_id", "kind": "open"}

    A reload. Invalidates the build result, the tone window and the texture scan.
    ⚠️ Any change to the trial selection or the excluded set **MUST recompute `gaps`** before the
    next build. The serpentine one-step prior does not hold across an exclusion gap, and a build that
    assumes it away silently places the whole tail wrong. `loader.open_session` recomputes `gaps`
    from the new trial list — which is exactly why an override is a full RELOAD and not an in-place
    patch of `run`.
    """
    s = _need_session()
    _need_no_build()
    lo = body.get("lo", s.run["lo"])
    hi = body.get("hi", s.run["hi"])
    ps = body.get("pass_split", s.pass_split["value"])
    for name, v in (("lo", lo), ("hi", hi), ("pass_split", ps)):
        if v is not None and not isinstance(v, int):
            raise ApiError(400, "bad_request", f"{name} must be an integer")
    if lo is not None and hi is not None and lo > hi:
        raise ApiError(400, "bad_request", f"lo ({lo}) > hi ({hi})")
    job = _open_job(s.data_dir, lo=lo, hi=hi, pass_split=ps)
    return {"job_id": job.job_id, "kind": "open"}


@APP.get("/api/session/log")
def get_session_log():
    """GET /api/session/log -> the parsed log.txt table (API.md §4.4), for the "is this the right
    run?" panel. `gap_s` is measured between consecutive SNAPSHOT trials only."""
    s = _need_session()
    name, entries = loader.parse_log(Path(s.data_dir) / "log.txt")
    rows = [{"trial": e.trial, "type": e.type, "time": e.time, "gap_s": e.gap_s} for e in entries]
    return {
        "experiment": name,
        "entries": rows,
        "n_snapshot": sum(1 for e in entries if e.type == "Snapshot"),
        "n_other": sum(1 for e in entries if e.type != "Snapshot"),
    }


# =============================================================================
# §5  Pixels   |   §6  Tone
# =============================================================================
def _frame_row(s, trial: int) -> int:
    row = s.row_of.get(trial)
    if row is None:
        raise ApiError(404, "not_found",
                       f"trial {trial} is not in the run ({s.run['lo']}-{s.run['hi']})")
    return row


@APP.get("/api/tile/{trial}.png")
def get_tile_png(trial: int, v: str | None = None):
    """GET /api/tile/{trial}.png?v={session_nonce}.{tone_version} -> 8-bit grayscale PNG, 512x512.
    Flat-fielded and mapped through the GLOBAL tone window. `Cache-Control: immutable`.

    ⚠️ `v` IS A STRING, AND IT MUST IDENTIFY THE SESSION, NOT JUST THE TONE. It used to be
    `?v={tone.version}` — and `tone.version` is a fresh-dataclass default, so it **resets to 1 on
    every open and every run change**, while the pixels behind the URL change (a different frame
    selection = a different tone window). Same URL, different bytes, served
    `max-age=31536000, immutable`: the browser would not revalidate for a YEAR. Open a second
    acquisition directory whose trial numbers overlap and the mosaic would render the FIRST
    dataset's pixels — and the whole verification loop is "the human looks at the pixels".
    The server still ignores the value; its only job is to be DIFFERENT when the bytes are.

    404 for any trial not in `run.trials`."""
    s = _need_session()
    row = _frame_row(s, trial)
    key = (trial, s.tone.version)
    png = _PNG_CACHE.get(key)
    if png is None:
        png = loader.tile_png(s.frames[row], s.flat_n, s.tone)
        if len(_PNG_CACHE) > 512:
            _PNG_CACHE.clear()
        _PNG_CACHE[key] = png
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})


@APP.get("/api/tile/{trial}.raw")
def get_tile_raw(trial: int):
    """GET /api/tile/{trial}.raw -> exactly 524,288 bytes, uint16 LE, 512x512, ALREADY FLIPPED,
    RAW camera counts. Headers: X-Camea-Shape: 512,512  |  X-Camea-Dtype: <u2"""
    s = _need_session()
    row = _frame_row(s, trial)
    raw = loader.tile_raw(s.frames[row])
    return Response(content=raw, media_type="application/octet-stream", headers={
        "X-Camea-Shape": "512,512",
        "X-Camea-Dtype": "<u2",
        "Cache-Control": "public, max-age=31536000, immutable",
    })


@APP.get("/api/thumbs.png")
def get_thumbs_png(v: str | None = None):
    """GET /api/thumbs.png?v={session_nonce}.{tone_version} -> the contact sheet (one sprite sheet,
    same GLOBAL window). `v` is a string and identifies the SESSION — see `get_tile_png`."""
    s = _need_session()
    hit = _THUMB_CACHE.get(s.tone.version)
    if hit is None:
        hit = loader.thumb_sheet(s.frames, s.flat_n, s.tone, cell=64)
        _THUMB_CACHE.clear()
        _THUMB_CACHE[s.tone.version] = hit
    return Response(content=hit[0], media_type="image/png",
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})


@APP.get("/api/thumbs.json")
def get_thumbs_json():
    """GET /api/thumbs.json -> {"grid", "cell", "trials", "n", "version"}"""
    s = _need_session()
    hit = _THUMB_CACHE.get(s.tone.version)
    if hit is None:
        hit = loader.thumb_sheet(s.frames, s.flat_n, s.tone, cell=64)
        _THUMB_CACHE.clear()
        _THUMB_CACHE[s.tone.version] = hit
    trials = list(s.run["trials"])
    return {"grid": int(hit[1]), "cell": 64, "trials": trials, "n": len(trials),
            "version": s.tone.version}


@APP.get("/api/tone")
def get_tone():
    """GET /api/tone -> the tone object (API.md §6.1)."""
    return _need_session().tone.to_json()


@APP.put("/api/tone")
def put_tone(body: dict):
    """PUT /api/tone {"lo"?, "hi"?, "auto"?} -> the tone object with `version` INCREMENTED.

    ⚠️ **TONE IS GLOBAL AND DISPLAY-ONLY.** It never touches the matcher (which works on the
    band-passed, mean-subtracted stack) and it never touches the exported TIFF. A **per-tile**
    stretch is forbidden: it makes overlapping tiles disagree in brightness and **destroys the
    Difference-mode check the whole verification loop depends on.**

    On a version change the front end MUST re-request every tile PNG with the new `?v=` and rebuild
    its baked background canvas.
    """
    s = _need_session()
    tone = s.tone
    with _LOCK:
        if body.get("auto"):
            if _AUTO_TONE is not None:
                tone.lo, tone.hi, tone.level = _AUTO_TONE
            tone.auto = True
        else:
            lo = body.get("lo", tone.lo)
            hi = body.get("hi", tone.hi)
            try:
                lo = float(lo)
                hi = float(hi)
            except (TypeError, ValueError):
                raise ApiError(400, "bad_request", "lo and hi must be numbers")
            if not (hi > lo):
                raise ApiError(400, "bad_request", f"hi ({hi}) must be greater than lo ({lo})")
            tone.lo, tone.hi = lo, hi
            tone.auto = False
        tone.version += 1
        _PNG_CACHE.clear()
        _THUMB_CACHE.clear()
    return tone.to_json()


# =============================================================================
# §9  The blank scan
# =============================================================================
@APP.get("/api/scan/blank")
def get_scan_blank():
    """GET /api/scan/blank -> loader.blank_scan()'s object. Computed during `session/open` (3.0 s).

    ❌ It RECOMMENDS. It never auto-rejects. **No slider, no blur judgement, and never a
    variance-of-Laplacian number in the UI** — across 15 focus measures the best global blur
    threshold reaches F1 = 0.37, and varlap scores *worse than chance*.
    """
    return _need_session().blank


@APP.put("/api/scan/blank")
def put_scan_blank(body: dict):
    """PUT /api/scan/blank {"blank": [289, 304]} -> the updated scan object.

    ⭐ THE TICK HAS TO MEAN SOMETHING. The scan RECOMMENDS and the user TICKS (API.md §9) — but
    `engine.match_anchor` REFUSES whatever is in this list, so until the tick reached the server the
    recommendation was, in effect, an auto-reject: the matcher refused every trial the measure named
    and the user could not overrule it.

    ⚠️ MEASURED ON 260620d — why this endpoint is not cosmetic. The threshold is the 2nd percentile
    of pass-1 texture, so ~2 % of pass 1 falls below it BY CONSTRUCTION. It names 34, 55, 56 and 127.
    Matched against a 16-anchor field with the refusal lifted:

        trial  34 ->   0.24 px from the human truth  (ncc 0.699, margin 0.460)   NOT BLANK
        trial  55 ->   0.18 px                       (ncc 0.696, margin 0.251)   NOT BLANK
        trial  56 ->   2.07 px                       (ncc 0.653, margin 0.162)   NOT BLANK
        trial 127 -> 679.33 px WRONG                 (ncc 0.656, margin 0.129)   genuinely misleads

    Three of the four are ordinary tiles that pass 1 places correctly, and refusing them cost the user
    three hand-drags for nothing. The fourth is real. The measure is a CONTINUUM on this data (good
    and blank textures interleave below the threshold) — which is exactly why the human decides and
    the code does not.

    Refusing is not excluding: a trial listed here stays in the document and can still be hand-placed.
    """
    s = _need_session()
    if "blank" not in body:
        raise ApiError(400, "bad_request", "needs a `blank` list of trial numbers")
    try:
        want = {int(t) for t in (body["blank"] or [])}
    except (TypeError, ValueError):
        raise ApiError(400, "bad_request", "`blank` must be a list of integers")

    unknown = sorted(want - set(s.run["trials"]))
    if unknown:
        raise ApiError(400, "bad_request", f"not in the run: {unknown}")

    with _LOCK:
        s.blank["blank"] = sorted(want)
        s.blank["n_blank"] = len(want)
        s.blank["accepted"] = True
        # The memo key is the ANCHOR SET, not the refusal set — a stale entry could hand back a score
        # for a tile that is now refused (or withhold one that is not). Drop it.
        engine.reset_caches()
    return s.blank


# =============================================================================
# §7  ⭐⭐ THE ANCHOR-COMPOSITE PRIMITIVE
# =============================================================================
def _parse_positions(raw: Any) -> dict[int, tuple[float, float]]:
    if not isinstance(raw, dict):
        raise ApiError(400, "bad_request", "positions must be an object of {trial: [x, y]}")
    out: dict[int, tuple[float, float]] = {}
    for k, v in raw.items():
        try:
            t = int(k)
            x, y = float(v[0]), float(v[1])
        except Exception:
            raise ApiError(400, "bad_request", f"positions[{k!r}] must be [x, y] numbers")
        out[t] = (x, y)
    return out


def _validate_match(body: dict, need_mode: bool):
    s = _need_session()
    _need_no_build()

    target = body.get("target")
    if not isinstance(target, int):
        raise ApiError(400, "bad_request", "target must be an integer trial number")
    if target not in s.row_of:
        raise ApiError(400, "bad_request", f"target {target} is not in run.trials")

    anchors = body.get("anchors")
    if not isinstance(anchors, list) or not anchors:
        raise ApiError(400, "bad_request", "anchors must be a non-empty array of trial numbers")
    anchors = [int(a) for a in anchors]
    if target in anchors:
        raise ApiError(400, "bad_request", f"anchors must not contain the target ({target})")
    unknown = [a for a in anchors if a not in s.row_of]
    if unknown:
        raise ApiError(400, "bad_request", f"anchors not in run.trials: {unknown}")

    positions = _parse_positions(body.get("positions"))
    missing = [a for a in anchors if a not in positions]
    if missing:
        raise ApiError(400, "bad_request", f"positions missing for anchors: {missing}")

    mode = body.get("mode", "global")
    near = body.get("near")
    if need_mode:
        if mode not in ("global", "local"):
            raise ApiError(400, "bad_request", "mode must be 'global' or 'local'")
        if mode == "local":
            if near is None:
                raise ApiError(400, "bad_request", "mode 'local' requires `near` (the drop point)")
            try:
                near = (float(near[0]), float(near[1]))
            except Exception:
                raise ApiError(400, "bad_request", "near must be [x, y]")
        else:
            near = None

    # ⚠️ radius NEVER exceeds 256 (and the UI must not exceed 128): the electrode grid repeats
    # every 256 px and a wide LOCAL search locks confidently onto a grid alias. Search wide with
    # mode="global" — the FFT plus the margin is what survives the aliases.
    radius = int(body.get("radius") or 64)
    radius = max(8, min(256, radius))
    max_candidates = int(body.get("max_candidates") or 8)
    max_candidates = max(1, min(16, max_candidates))
    return s, target, sorted(anchors), positions, mode, near, radius, max_candidates


@APP.post("/api/match/anchor")
def post_match_anchor(body: dict):
    """POST /api/match/anchor -> engine.match_anchor(...).to_json()   (API.md §7.1)

    ONE ENDPOINT, FOUR FEATURES: place-next (Space) · ranked alternatives · rescue an unplaced tile ·
    snap a drag (mode="local").

    ⛔ **BLANK => REFUSED, NOT SCORED** (§7.3): 200 with candidates=[], best=null, and a populated
    `refused`. There is no `force` flag. (The refusal is engine's — the server does not second-guess
    it and does not offer an override.)

    ⭐ **MEMOISED** (§7.4). The key IS the anchor set, which is what makes the front end's A-branch
    prefetch correct by construction. This handler is a plain `def`, so Starlette runs it in its
    thread pool: a prefetch in flight never blocks the foreground request the user is waiting on.

    🔴 **409 busy while a `build` job is running** — the build owns the GPU.
    """
    s, target, anchors, positions, mode, near, radius, maxc = _validate_match(body, need_mode=True)
    res = engine.match_anchor(s, target, anchors, positions,
                              mode=mode, near=near, radius=radius, max_candidates=maxc)
    return res.to_json() if hasattr(res, "to_json") else res


@APP.post("/api/match/score")
def post_match_score(body: dict):
    """POST /api/match/score -> engine.score_at(...)   (API.md §7.2)
    "You dropped it here; here's what the pixels say." One exact_ncc, no search.
    `ncc` is **null** below exact_ncc's overlap floor — the honest answer is "not measurable",
    never 0.0. Blank tiles are refused here too."""
    s, target, anchors, positions, _m, _n, _r, _c = _validate_match(body, need_mode=False)
    at = body.get("at")
    try:
        at = (float(at[0]), float(at[1]))
    except Exception:
        raise ApiError(400, "bad_request", "`at` must be [x, y] — the world top-left you dropped it at")
    return engine.score_at(s, target, anchors, positions, at)


# =============================================================================
# §8  Jobs
# =============================================================================
def _hoist_build():
    """Lift a finished build job's result into BUILD. The registry has no completion callback, so
    we do it lazily — on every job poll, session read and build-result read."""
    global BUILD, _BUILD_JOB_SEEN
    if jobs.JOBS is None:
        return
    for j in jobs.JOBS.list():                     # newest first
        if j.kind != "build":
            continue
        if j.state == "done" and j.result and j.job_id != _BUILD_JOB_SEEN:
            with _LOCK:
                BUILD = j.result
                _BUILD_JOB_SEEN = j.job_id
        break


@APP.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    """GET /api/jobs/{job_id} -> the Job object (API.md §8.1). Poll every 500 ms."""
    _hoist_build()
    j = _need_jobs().get(job_id)
    if j is None:
        raise ApiError(404, "not_found", f"no such job: {job_id}")
    return j.to_json()


@APP.get("/api/jobs")
def get_jobs():
    """GET /api/jobs -> {"jobs": [...]}, newest first."""
    _hoist_build()
    return {"jobs": [j.to_json() for j in _need_jobs().list()]}


@APP.post("/api/jobs/{job_id}/cancel", status_code=202)
def post_job_cancel(job_id: str):
    """POST /api/jobs/{job_id}/cancel -> 202 {"job_id", "state": "cancelling"}. Idempotent.
    A `done` job -> 409.

    ⚠️ `t33.place` has no cooperative cancel — the build runs in a CHILD PROCESS and cancel is
    `terminate()`. That is the whole reason for the process.
    """
    reg = _need_jobs()
    j = reg.get(job_id)
    if j is None:
        raise ApiError(404, "not_found", f"no such job: {job_id}")
    try:
        j = reg.cancel(job_id)
    except jobs.NotCancellable as e:
        raise ApiError(409, "bad_request", str(e) or f"job {job_id} has already finished")
    state = j.state if j.state in ("cancelled", "failed") else "cancelling"
    return {"job_id": job_id, "state": state}


# =============================================================================
# §10  Build
# =============================================================================
def _validate_config(cfg: dict) -> None:
    """An unknown knob is a `TypeError` in `t33.Config` -> 400 (API.md §10.1).

    `t33.Config.__init__` takes `**kw` and raises `TypeError: unknown T33 config knob: 'x'` itself
    (t33.py:136), so we validate by CONSTRUCTING one. Do not introspect the signature — it is
    literally `(**kw)` — and do not hard-code the knob list here: t33 owns it, and a stale copy in
    the server would reject a knob t33 grew, or accept one it dropped.

    `t33` is reached through `engine`, which is the only module allowed to import it.
    """
    t33 = getattr(engine, "t33", None)
    Cfg = getattr(t33, "Config", None) if t33 is not None else None
    if Cfg is None:
        return                              # engine not up yet: let the child raise, job -> failed
    try:
        Cfg(**cfg)
    except TypeError as e:
        raise ApiError(400, "bad_request", str(e))


@APP.post("/api/build/start", status_code=202)
def post_build_start(body: dict):
    """POST /api/build/start  {"config"?, "use_cache", "trials"?} -> 202 {"job_id", "kind": "build"}
    409 if a build is already running.

    `config: null` = **t33's shipped 312/312 defaults** — that is the one-button path and it stays
    the default. An unknown knob raises TypeError in t33.Config -> 400.
    ⚠️ `pass_split` defaults to the session's **DETECTED** value, not to t33's literal 166.

    ⭐ **`trials` IS THE DOCUMENT'S ACTIVE TRIAL LIST, AND IT IS NOT COSMETIC.** It used to be
    hard-wired to `s.run["trials"]` — the session's whole run — so a user who pressed `E` on a bad
    tile and then re-solved got **a re-solve on the identical input**: the excluded frame went
    straight back into the chain, still voting, still carrying its neighbours. The exclusion the app
    invited him to make never reached the solver. `t33` recomputes its own `breaks()` from whatever
    list it is given, so passing the reduced list is all that is needed — the new gap is then
    honoured rather than assumed away. **This is now the ONLY way a frame ever leaves a build.**

    Before spawning: `engine.release_gpu()` — the parent may hold ~2 GB of device memory from
    interactive matching and the child needs ~2 GB more. On a 4 GB card that is the difference
    between a build and an OOM.
    """
    s = _need_session()
    cfg = body.get("config") or {}
    if not isinstance(cfg, dict):
        raise ApiError(400, "bad_request", "config must be an object or null")
    cfg = dict(cfg)

    # ⚠️ the session's DETECTED split, not t33's literal 166.
    cfg.setdefault("pass_split", s.pass_split["value"])
    _validate_config(cfg)

    trials = _build_trials(s, body.get("trials"), cfg["pass_split"])

    cache_dir = None
    if body.get("use_cache", True):
        # ⚠️ NOT `s.dataset`. The t33 cache filename carries the trial hash and the config hash but
        # NOTHING that identifies the pixels — the directory was the only discriminator, and it was
        # the folder's BASENAME. Two `260620d` folders under different parents collided on the
        # identical filename and `_load_checked` (config-only) would accept the wrong layout as warm.
        cache_dir = str(_appdata() / "cache" / s.store_key)
        Path(cache_dir).mkdir(parents=True, exist_ok=True)

    try:
        engine.release_gpu()
    except Exception as e:  # noqa: BLE001
        print(f"[camea] release_gpu failed (continuing): {e}", file=sys.stderr)

    try:
        job = _need_jobs().submit_process("build", "app.backend.engine.build_worker", {
            "data_dir": str(s.data_dir),
            "trials": trials,
            "config": cfg,
            "cache_dir": cache_dir,
        })
    except jobs.Busy:
        raise ApiError(409, "busy", "a build is already running")
    return {"job_id": job.job_id, "kind": "build", "n_trials": len(trials)}


def _build_trials(s, want, pass_split) -> list[int]:
    """The trial list the solver is actually given. Defaults to the whole run; a subset (the
    document's non-excluded tiles) is honoured, and anything else is a 400.

    ⭐ The subset is the USER's — the app contributes no exclusions of its own.
    """
    run = list(s.run["trials"])
    if want is None:
        return run
    if not isinstance(want, list):
        raise ApiError(400, "bad_request", "trials must be an array of trial numbers, or null")
    try:
        trials = sorted({int(t) for t in want})
    except (TypeError, ValueError):
        raise ApiError(400, "bad_request", "trials must be integers")
    stray = [t for t in trials if t not in s.row_of]
    if stray:
        raise ApiError(400, "bad_request", f"trials not in this run: {stray[:12]}")
    # t33 places pass 2 AGAINST pass 1 and needs a solvable reference pass; it raises otherwise.
    # Say so here, where the message can reach the user, rather than failing the job 200 s in.
    ps = int(pass_split)
    n1 = sum(1 for t in trials if t <= ps)
    n2 = sum(1 for t in trials if t > ps)
    if n1 < 4 or n2 < 2:
        raise ApiError(400, "bad_request",
                       f"only {n1} pass-1 and {n2} pass-2 tiles left (need 4 and 2). "
                       f"Un-exclude some, or move the split.")
    return trials


@APP.get("/api/build/result")
def get_build_result():
    """GET /api/build/result -> API.md §10.2. 404 before a build has completed.

    ⚠️ t33's `info` is NOT JSON-serializable (a nested t27.Config) — `engine.jsonable()` it.
    ⚠️ `per_tile` is a "go look here first" list, **not a verdict** — and **pass-1 tiles have no
    per-tile confidence at all**, while the worst tile in the shipped build (127, 9.94 px) is a
    pass-1 tile.
    """
    _hoist_build()
    if BUILD is None:
        raise ApiError(404, "not_found", "no build has completed in this session")
    return BUILD


# =============================================================================
# §11  Project   |   §12  Exports
# =============================================================================
def _appdata() -> Path:
    import os
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.local/share")
    return Path(base) / "Camea"


@APP.post("/api/project/save")
def post_project_save(body: dict):
    """POST /api/project/save {"path", "doc"} -> {"path", "bytes", "saved_at"}.
    Validates, fills derived fields, **stamps the provenance** (§11.4), writes atomically."""
    global PROJECT_PATH
    path = body.get("path")
    doc = body.get("doc")
    if not path or not isinstance(doc, dict):
        raise ApiError(400, "bad_request", "path and doc are required")
    p = Path(str(path))
    _refuse_data_dir(p)
    try:
        # ⭐ THE PROJECT FILE IS THE ONLY MEMORY. Exclusions live in the document the front end posts
        # here — not in the app, and not in this session. `session` is passed for the run range and
        # the acquisition's name, nothing more.
        res = project.save(p, doc, session=SESSION, app_version=__version__)
    except project.RangeMismatch as e:
        # ⚠️ NOT a ValueError — project.ProjectError derives from Exception. Catching only
        # ValueError here let this escape as a 500 and the front end could not tell "you opened
        # the wrong project" from "the server broke". 409, per API.md §11.
        raise ApiError(409, "range_mismatch", str(e))
    except project.ValidationError as e:
        raise ApiError(400, "invalid_document", str(e),
                       detail={"problems": list(getattr(e, "problems", []) or [])})
    except project.ProjectError as e:
        raise ApiError(400, "bad_request", str(e))
    except ValueError as e:
        raise ApiError(400, "bad_request", str(e))
    except OSError as e:
        raise ApiError(500, "io_error", str(e))
    with _LOCK:
        PROJECT_PATH = str(p)
    return res


@APP.post("/api/project/load")
def post_project_load(body: dict):
    """POST /api/project/load {"path"} -> {"doc", "warnings"}

    ⚠️ **GUARD THE RANGE**, as the bench does (template.html:2012): if the document's
    `dataset`/`trial_range` differ from the open session's, **REFUSE** with 409. Pass 2's autosave
    once silently overwrote pass 1's ground-truth records. Do not re-open that hole.
    """
    global PROJECT_PATH
    path = body.get("path")
    if not path:
        raise ApiError(400, "bad_request", "path is required")
    p = Path(str(path))
    if not p.is_file():
        raise ApiError(404, "not_found", f"no such file: {p}")
    try:
        doc, warnings = project.load(p, session=SESSION)
    except project.RangeMismatch as e:
        # ⭐ THE RANGE GUARD. 409, exactly as API.md §11.2 specifies.
        # ⚠️ project.RangeMismatch is a ProjectError, which derives from Exception — NOT from
        # ValueError. The old `except ValueError` never fired, so a wrong-range project came back
        # as a 500. It still refused the load (good) but the front end saw an opaque server error.
        # Pass 2's autosave once silently overwrote pass 1's ground-truth records; this is the
        # guard that keeps that hole shut, and it has to be legible.
        raise ApiError(409, "range_mismatch", str(e))
    except project.ValidationError as e:
        raise ApiError(400, "invalid_document", str(e),
                       detail={"problems": list(getattr(e, "problems", []) or [])})
    except project.ProjectError as e:
        raise ApiError(400, "bad_request", str(e))
    except json.JSONDecodeError as e:
        raise ApiError(400, "invalid_document", f"not valid JSON: {e}")
    except ValueError as e:
        raise ApiError(400, "bad_request", str(e))
    except OSError as e:
        raise ApiError(500, "io_error", str(e))
    with _LOCK:
        PROJECT_PATH = str(p)
    return {"doc": doc, "warnings": list(warnings or [])}


@APP.post("/api/project/autosave")
def post_project_autosave(body: dict):
    """POST /api/project/autosave {"doc"} -> {"path", "saved_at"}. Debounced at 2 s by the front
    end, plus unconditionally on every A / E.

    ⛔ `data/` is NEVER written to. This is genuine crash recovery on disk — NOT localStorage,
    which in the artifact sandbox failed SILENTLY and nearly cost a day's work.
    """
    s = _need_session()
    doc = body.get("doc")
    if not isinstance(doc, dict):
        raise ApiError(400, "bad_request", "doc is required")
    p = project.autosave_path(s.store_key)   # keyed on the DIRECTORY, not its basename
    _refuse_data_dir(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        res = project.save(p, doc, session=s, app_version=__version__)
    # ⚠️ project.ValidationError is a ProjectError, NOT a ValueError — it used to sail past the
    # `except ValueError` below and come back as an opaque **HTTP 500** on every 2-second autosave.
    # Same bug shape as the RangeMismatch-as-500 on /api/project/load. A refused document is a 400
    # and it must say WHICH tile.
    except project.ValidationError as e:
        raise ApiError(400, "invalid_document", str(e),
                       detail={"problems": list(getattr(e, "problems", []) or [])})
    except project.ProjectError as e:
        raise ApiError(400, "bad_request", str(e))
    except ValueError as e:
        raise ApiError(400, "bad_request", str(e))
    except OSError as e:
        raise ApiError(500, "io_error", str(e))
    return {"path": str(p), "saved_at": res.get("saved_at", _iso())}


def _refuse_data_dir(p: Path):
    """⛔ `data/` is the read-only raw mirror. Nothing this app does ever writes into it."""
    try:
        rp = p.resolve()
    except OSError:
        rp = p
    data = (REPO_ROOT / "data").resolve()
    if str(rp).lower().startswith(str(data).lower()):
        raise ApiError(400, "bad_request", "refusing to write inside data/ — it is the read-only raw mirror")


@APP.post("/api/export", status_code=202)
def post_export(body: dict):
    """POST /api/export -> 202 {"job_id", "kind": "export"}   (API.md §12)"""
    s = _need_session()
    out_dir = body.get("dir")
    basename = body.get("basename") or s.dataset
    doc = body.get("doc")
    if not out_dir or not isinstance(doc, dict):
        raise ApiError(400, "bad_request", "dir and doc are required")
    outputs = body.get("outputs") or ["tiff", "png", "positions", "gt", "qc"]
    known = {"tiff", "png", "positions", "gt", "qc"}
    bad = [o for o in outputs if o not in known]
    if bad:
        raise ApiError(400, "bad_request", f"unknown output(s): {bad}. Known: {sorted(known)}")
    render_mode = body.get("render_mode") or "feather"
    if render_mode not in ("feather", "median", "alpha"):
        raise ApiError(400, "bad_request", "render_mode must be feather | median | alpha")
    include_unverified = bool(body.get("include_unverified", True))
    um_per_px = body.get("um_per_px")          # ⛔ PIXELS ONLY unless the user typed a number in.

    out = Path(str(out_dir))
    _refuse_data_dir(out)
    out.mkdir(parents=True, exist_ok=True)

    def fn(report, cancel):
        return export.export_all(
            s, doc, out, str(basename), list(outputs),
            render_mode=render_mode, include_unverified=include_unverified,
            um_per_px=um_per_px, report=_report_adapter(report), cancel=cancel,
        )

    job = _need_jobs().submit_thread("export", fn)
    return {"job_id": job.job_id, "kind": "export"}


# =============================================================================
# §13  Native dialogs (proxied to pywebview — the WebView cannot open one itself)
# =============================================================================
def _need_window():
    if WINDOW is None:
        raise ApiError(501, "bad_request", "no window (headless) — pass the path directly")
    return WINDOW


def _file_types(filters) -> tuple:
    """pywebview wants ("Camea project (*.camea.json)",) — i.e. exactly what the API already sends."""
    if not filters:
        return ()
    return tuple(str(f) for f in filters)


def _first(paths):
    if not paths:
        return None
    if isinstance(paths, (list, tuple)):
        return str(paths[0]) if paths else None
    return str(paths)


@APP.post("/api/dialog/open-directory")
def post_dialog_open_directory(body: dict):
    """POST /api/dialog/open-directory -> {"path"} | {"path": null}.
    501 when WINDOW is None (headless / pytest — the tests pass paths directly)."""
    w = _need_window()
    import webview
    r = w.create_file_dialog(webview.FOLDER_DIALOG)
    return {"path": _first(r)}


@APP.post("/api/dialog/open-file")
def post_dialog_open_file(body: dict):
    """POST /api/dialog/open-file -> {"path"} | {"path": null}"""
    w = _need_window()
    import webview
    r = w.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False,
                             file_types=_file_types(body.get("filters")))
    return {"path": _first(r)}


@APP.post("/api/dialog/save-file")
def post_dialog_save_file(body: dict):
    """POST /api/dialog/save-file -> {"path"} | {"path": null}"""
    w = _need_window()
    import webview
    r = w.create_file_dialog(webview.SAVE_DIALOG,
                             save_filename=str(body.get("default_name") or ""),
                             file_types=_file_types(body.get("filters")))
    return {"path": _first(r)}
