"""schemas.py — ⭐ **THE CONTRACT.** Every request and response body in the app is here.

**Why this file exists, and why nothing else may claim to be the contract.**
The v1 app's contract was `API.md` — 1,023 hand-written lines. It drifted from `server.py`
across three commits and ended up *actively wrong* in three places (it still described the
26 hard-coded exclusions, a fatal blank anchor, and a per-tile `force` flag). Prose cannot be
compiled and cannot be diffed against a running server. **So the contract is now code:**

    pydantic models here  ->  FastAPI's OpenAPI schema  ->  the generated TypeScript client

If a route is not in this file, the front end **cannot call it**. That is the point.
`docs/API.md` is an orientation essay. It may lag. **This file may not.**

---------------------------------------------------------------------------------------------
THE RULES THIS FILE IS BUILT ON  (docs/SPLIT.md §0; CLAUDE.md)
---------------------------------------------------------------------------------------------
1. ⛔ **THE APP CARRIES NO DATASET KNOWLEDGE.** There is no exclusion list in this file, no
   trial number is special, and no route auto-excludes anything. Exclusions are *user input*
   and they live in the DOCUMENT (`MosaicDocument.tiles[t].state == "excluded"`). The blank
   scan **proposes**; the human ticks. The one thing the app imports from the exclusion module
   is `gaps()` — a pure function over a trial list — and it is exposed at `POST /api/mosaic/gaps`.
2. **A DATASET IS READ-ONLY.** There is no route that writes into one. Analyses land in the
   WORKSPACE, which the user chooses.
3. **CORE IS FEATURE-AGNOSTIC.** `datasets` / `sessions` / `workspace` / `documents` / `jobs` /
   `tiles` know nothing about mosaics. Feature #2 reuses every one of them unchanged.
4. **LONG OPERATIONS RETURN A JOB.** open, build, export, re-check. They never block.
5. ⭐ **`POST /api/mosaic/match/*` IS A PURE FUNCTION OF ITS REQUEST BODY.** This is not a
   style preference — it is the prefetch's correctness proof (see `MatchAnchorRequest`).

Conventions
-----------
* **Positions are TOP-LEFT CORNERS, in world pixels, float.** Never centres. Anything drawing a
  centre adds +TILE/2. Off-by-256 is the classic bug in this project.
* **Trial ids** are ints in arrays. In JSON *object keys* they are decimal strings (`"11"`),
  because JSON has no integer keys. Never zero-pad. (`dict[int, ...]` below ⇒ string keys on
  the wire, ints in Python.)
* **Times** are ISO-8601 UTC strings ending in `Z` (plain `str`, not `datetime`: pydantic would
  serialise `+00:00` and every existing file on disk says `Z`).
* **Errors**: non-2xx returns `ErrorEnvelope`.
* **Orientation**: every pixel, position and dx/dy in this API lives in the frame the reader
  produced — which flips **conditionally**, on the trial XML's `ax`/`ay`. `SessionResponse.frame_note`
  says what was actually done. Nothing here asserts a flip.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

# =================================================================================================
# Base models
# =================================================================================================


class Req(BaseModel):
    """Base for request bodies. **`extra="forbid"`**: a typo'd field is a 422, not a silent
    default. The TS client is generated from these, so nothing legitimate ever sends extras."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Res(BaseModel):
    """Base for response bodies."""

    model_config = ConfigDict(populate_by_name=True)


class Open(BaseModel):
    """Base for the models that MUST round-trip keys they do not know about.

    ⚠️ **`extra="allow"` here is load-bearing, not laziness.** A saved document is also somebody's
    ground truth and may carry a hand-written note; `core.document.load` preserves unknown top-level
    and unknown per-tile keys **verbatim** (`archive/app-v1/backend/project.py:992-993`). A lossy
    round-trip destroys them. It is also how the mosaic payload rides FLAT beside the envelope
    (see `MosaicDocument`), and how a new `t33.Config` knob reaches the solver without a schema bump.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)


#: World top-left corner `(x, y)` in pixels. **NOT a centre.**
XY = tuple[float, float]

#: An inclusive trial-number gap `[a, b]`: acquisition jumped from a straight to b.
Gap = tuple[int, int]

#: A JSON scalar.
Scalar = float | int | bool | str | None

#: ⚠️ **A SOLVER CONFIG VALUE, AND IT IS NOT FLAT.** `t33.Config` **NESTS**: `config["t27"]` is a whole
#: `t27.Config` (`conf`, `run_conf`, `span`, `r0`, `gain`, `topn`, …), and `config["breaks"]` is a
#: list. `SeededFrom.config` and `BuildBlock.config` were both declared `dict[str, Scalar]`, which
#: **cannot represent the config the app actually ran** — measured against the live server, the very
#: first `POST /api/mosaic/seed` on a real t33 build died with four `ResponseValidationError`s
#: (`float_type` / `int_type` / `bool_type` / `string_type` on `doc.build.config.t27`). The config
#: that goes into the document is t33's own `info["config"]`, verbatim, and a schema that forbids it
#: is a schema that forbids recording what was run.
ConfigValue = Scalar | dict[str, Scalar] | list[Scalar]


# =================================================================================================
# Errors — the envelope every non-2xx uses
# =================================================================================================

ErrorCode = Literal[
    "bad_request",  # 400 — malformed / impossible request
    "not_found",  # 404
    "no_session",  # 404 — nothing is open
    "no_workspace",  # 409 — the user has not chosen a workspace yet
    "no_document",  # 404
    "busy",  # 409 — an exclusive-resource lease (e.g. the GPU) is held
    "refused",  # 409 — the server will not do this (see `message`); never a 500
    "range_mismatch",  # 409 — this document is for a different trial range / dataset
    "mixed_shape",  # 409 — the requested trials are not all the same frame shape
    "job_failed",  # 500
    "io_error",  # 500
    "no_window",  # 501 — headless: there is no native dialog
]


class ErrorBody(Res):
    code: ErrorCode
    message: str
    detail: dict[str, str] | None = Field(
        default=None, description="Machine-readable extras. Strings only — this is a display aid."
    )


class ErrorEnvelope(Res):
    """The body of every non-2xx response."""

    error: ErrorBody


class OkResponse(Res):
    ok: bool = True


# =================================================================================================
# Jobs — start / poll / cancel.  CORE. Feature-agnostic.
# =================================================================================================

JobState = Literal["queued", "running", "done", "failed", "cancelled"]

#: 🔶 `kind` is a free string, NOT a Literal. v1 hard-coded `Literal["open","build","export"]`
#: into the core registry; features register their own kinds now (`camea.core.jobs`).
JobKind = str


class JobRef(Res):
    """The 202 body of every long operation."""

    job_id: str
    kind: JobKind


class JobError(Res):
    code: str
    message: str
    traceback: str | None = None


class JobCancelResponse(Res):
    job_id: str
    state: JobState


class Job(Res):
    """Poll at 500 ms. There is no websocket — it is one client on localhost and a poll is 0.6 ms.

    ⚠️ **`eta_s` is only recomputed when the child prints a recognised line.** The front end must
    re-anchor its countdown **only when this raw number changes** (BEHAVIOUR R8.2) — re-anchoring on
    every 500 ms tick resets the clock and the countdown never moves. And there is deliberately **no
    server-side ETA heartbeat** (R8b): with a global-linear estimator, re-emitting during a silent
    phase makes the ETA count *up*.
    """

    job_id: str
    kind: JobKind
    state: JobState
    phase: str | None = None
    phase_index: int | None = None
    n_phases: int | None = None
    pct: float | None = Field(default=None, ge=0.0, le=100.0)
    message: str | None = None
    started_at: str | None = None
    elapsed_s: float | None = None
    eta_s: float | None = Field(
        default=None, description="Seconds remaining, or null when the phase is silent. May JUMP UP."
    )
    log_tail: list[str] = Field(
        default_factory=list, description="The last 200 lines the job narrated (the UI shows ~8)."
    )
    cancellable: bool = True
    exclusive: str | None = Field(
        default=None,
        description='The exclusive resource lease this job holds, e.g. "gpu". While one is held, '
        "another job wanting the same lease gets 409 busy.",
    )
    result: JobResult | None = Field(
        default=None, description="null until state == 'done'. Discriminated on `kind`."
    )
    error: JobError | None = Field(default=None, description="Set iff state == 'failed'.")


class JobListResponse(Res):
    jobs: list[Job] = Field(description="Newest first.")


# =================================================================================================
# Health / GPU / settings — CORE
# =================================================================================================


class HealthResponse(Res):
    ok: bool
    version: str
    python: str
    uptime_s: float


class GpuInfo(Res):
    """🔴 **DETECTION MUST EXECUTE A REAL OP.** `import cupy` *succeeds* on a broken CUDA install;
    it is `cupy.zeros(1) + 1` that raises. There is exactly **one** detector — `t27.xp()` — and
    there must never be a second. `reason` is a *string for the human*, never a verdict: "no GPU"
    because a CUDA DLL is off the search path is **fixable** and is not the same thing as "no card".
    """

    available: bool
    backend: Literal["cupy", "numpy"]
    name: str | None = None
    cupy: str | None = None
    cuda_runtime: int | None = None
    reason: str | None = Field(
        default=None, description="Why there is no GPU. Human-readable, and often actionable."
    )
    note: str | None = Field(default=None, description="What it costs the user, in real numbers.")


class Settings(Res):
    """Everything the app remembers between launches. ⛔ **No dataset knowledge lives here.**
    A remembered *path* is not knowledge about the data at that path.

    ⭐ **ONE KEY, since R44 (2026-08-10).** `projects` went with the folders it indexed: projects
    live in Camea's own store and the store IS the index. (`workspace` and `dataset_roots` went on
    2026-07-25.) What is left is the one thing the app cannot re-derive — where the user keeps his
    data, which is his to decide and nobody else's to remember."""

    recent_datasets: list[str] = Field(
        default_factory=list, description="Data folders recently opened. Offered back as completions."
    )


class SettingsUpdate(Req):
    recent_datasets: list[str] | None = None


# =================================================================================================
# 🔴 fs — THE FOLDER PICKER THAT DOES NOT NEED A NATIVE WINDOW.  CORE.
# =================================================================================================
#
# In `--browser` and `--headless` there is no pywebview, so `/api/dialog/*` cannot open a native
# dialog and honestly returns 501. `GET /api/fs/list` is the way out — served in EVERY mode. It is a
# directory LISTER, not a file server: it returns NAMES, never bytes.


class FsEntry(Res):
    """One row in the folder picker."""

    name: str
    path: str
    is_dataset: bool = Field(
        description="It has a `log.txt` and at least one `NNN.xml`. ⛔ Recognised by SHAPE, never by "
        "name — nothing in this app knows what a dataset is called."
    )
    n_children: int | None = Field(
        default=None, description="Sub-directories. null when the folder could not be read."
    )


class FsListResponse(Res):
    """`GET /api/fs/list` — the served folder picker. See the section note above."""

    path: str
    parent: str | None = Field(default=None, description="null at a filesystem root.")
    is_dataset: bool
    entries: list[FsEntry]
    roots: list[str] = Field(
        description="The drives / mount points, so the picker can start from nothing."
    )
    error: str | None = Field(
        default=None, description="Set when `path` itself could not be listed. Not an HTTP error — "
        "the picker must still render its roots and its parent."
    )


# =================================================================================================
# DATASETS — the browser. **The new home screen.**  CORE.
# =================================================================================================
#
# A DATASET is a folder of `.dat` frames + `log.txt`. It is RAW, and it is READ-ONLY: no route
# below writes to one, and `core.workspace` refuses any output path inside `data/` or inside an
# open dataset's own directory.
#
# These routes must be good enough to render the browser without opening anything: a thumbnail,
# a trial count, dates, and which analyses already exist for each dataset.


class ShapeGroup(Res):
    """Snapshot trials sharing one frame shape. ⛔ The browser reports shapes; it does not *gate*
    on one. The 512×512 gate is the mosaic feature's policy (512 is `t33.TILE`), not core's."""

    w: int
    h: int
    n: int
    trials: list[int]


class SnapshotBlock(Res):
    """A contiguous run of Snapshot trials in `log.txt`."""

    lo: int
    hi: int
    n: int


class AnalysisRef(Res):
    """A card on the dataset's tile in the browser: "you already have work here"."""

    analysis_id: str
    feature: str
    name: str
    modified: str
    n_anchored: int | None = None
    n_excluded: int | None = None


class DatasetSummary(Res):
    """One card in the browser."""

    key: str = Field(
        description="Stable id: basename + sha1 of the RESOLVED directory. ⭐ Two folders both "
        "named `260620d` under different parents must not share a cache file or an autosave slot."
    )
    name: str = Field(description="The folder's basename.")
    path: str
    experiment: str = Field(
        default="",
        description="The acquisition's own name (log.txt `New experiment:`), which may differ from "
        "the folder's. Recorded because a directory label can lie. Nothing branches on it.",
    )
    n_trials: int = Field(description="Every trial in log.txt, of any type.")
    n_snapshots: int
    first_at: str | None = None
    last_at: str | None = None
    shapes: list[ShapeGroup] = Field(default_factory=list)
    thumbnail_url: str | None = Field(
        default=None, description="GET /api/datasets/{key}/thumbnail.png — one frame, no session."
    )
    analyses: list[AnalysisRef] = Field(default_factory=list)
    last_opened: str | None = None
    warnings: list[str] = Field(default_factory=list)


class DatasetListResponse(Res):
    """What is at ONE folder the user just named. ⛔ Not a registry — nothing here was remembered
    or scanned on the app's initiative."""

    path: str = Field(description="The folder that was looked at, resolved.")
    is_dataset: bool = Field(
        default=False, description="True when that folder IS one acquisition (log.txt + NNN.xml)."
    )
    datasets: list[DatasetSummary]
    skipped: list[str] = Field(
        default_factory=list, description="Folders that looked like a dataset but could not be read."
    )


class DatasetAtRequest(Req):
    """`POST /api/datasets/at` — *"look at this folder."* (A POST, not a GET: Windows paths in query
    strings are an encoding trap.)

    ⛔ **Nothing is remembered and nothing is recommended.** The folder is either an acquisition, or
    it directly contains some — and that is as far as it looks. A deeper walk would be the app going
    looking for the user's data, which is exactly what was removed on 2026-07-25.
    """

    path: str
    depth: int = Field(
        default=2,
        ge=1,
        le=2,
        description="1 = this folder only. 2 (the default) = this folder, or the acquisitions "
        "DIRECTLY inside it — he may have typed the parent. Never deeper.",
    )


class TrialMeta(Res):
    """⚠️ **Shape is PER-TRIAL.** It is parsed from that trial's XML. It is never inferred from a
    file size, and a trial with `frames != 1` is rejected, not reshaped."""

    trial: int
    type: str = Field(description='The log.txt trial type, e.g. "Snapshot".')
    time: str | None = None
    gap_s: float | None = Field(
        default=None, description="Seconds since the previous SNAPSHOT. null for the first."
    )
    w: int | None = None
    h: int | None = None
    dtype: str | None = None
    bytes: int | None = None
    flip_x: bool | None = None
    flip_y: bool | None = None
    dat: str | None = None


class DatasetDetail(Res):
    """Everything the browser can say about a dataset **without loading a pixel**."""

    summary: DatasetSummary
    trials: list[TrialMeta]
    blocks: list[SnapshotBlock] = Field(
        description="Contiguous runs of Snapshot trials. A feature selects from these; core does "
        "not choose for it."
    )


# =================================================================================================
# SESSIONS — an OPEN dataset (its pixels, in RAM).  CORE.
# =================================================================================================
#
# ⭐ A session is ONE PER DATASET and is SHARED by every open feature. It is IMMUTABLE except for
# the display tone. It holds NO analysis state:
#
#     NO tile states.  NO exclusions.  NO blank list.  NO run.  NO pass_split.
#
# Those are the mosaic feature's, and they live in its DOCUMENT. (docs/SPLIT.md §2.4. The v1
# session carried `blank`, which `PUT /api/scan/blank` mutated and the matcher read — which made
# `POST /api/match/anchor` **not** a pure function of its body, contrary to the comment at the top
# of its own server. That endpoint is deleted; the refusal set now travels in the match body.)


class Tone(Res):
    """The display window. ⚠️⚠️ **GLOBAL, NEVER PER-TILE.** A per-tile percentile stretch
    over-brightens near-empty frames and makes overlapping tiles disagree in brightness — **which
    destroys the Difference-mode check the whole verification loop depends on.** There is no
    per-tile path and there must never be one. Tone is display-only: it never touches the matcher
    (which sees band-passed, mean-subtracted pixels) and never touches the exported TIFF."""

    lo: float
    hi: float
    level: float
    flat_sigma: float
    pct_lo: float
    pct_hi: float
    n_sample: int
    auto: bool
    version: int = Field(
        description="Bumped on every change. Half of the pixel cache-buster — see `Session.nonce`."
    )


class ToneUpdate(Req):
    lo: float | None = None
    hi: float | None = None
    auto: bool | None = Field(default=None, description="true = recompute and discard lo/hi.")


class SkippedFrame(Res):
    trial: int
    reason: Literal["off_shape", "unreadable", "not_snapshot"]
    w: int | None = None
    h: int | None = None
    message: str


class OpenSessionRequest(Req):
    """⚠️ `trials` is the caller's selection. A FrameStore holds one shape.

    * `trials: null` ⇒ every snapshot trial. If they are **not** all one shape the open fails with
      `409 mixed_shape`, listing the groups — core **refuses to guess** which shape you meant.
    * `trials: [...]` ⇒ exactly those. The mosaic feature passes its 512×512 selection here.

    ⛔ Nothing is ever dropped by TRIAL NUMBER. Only by shape, and only with a reason, reported in
    `SessionResponse.skipped`.
    """

    path: str | None = None
    dataset_key: str | None = None
    trials: list[int] | None = None


class SessionResponse(Res):
    session_id: str
    dataset_key: str
    dataset: str
    experiment: str
    path: str
    opened_at: str
    nonce: str = Field(
        description="⭐ A FRESH identity per open. Cache-bust every pixel URL with "
        "`?v={nonce}.{tone.version}`. **NOT the tone version alone** — that is a dataclass default "
        "and resets to 1 on every open, while the pixels behind an `immutable, max-age=1y` URL "
        "change. Open a second acquisition whose trial numbers overlap and the browser serves the "
        "FIRST dataset's pixels. (And `id()` is recycled — do not use it.)"
    )
    w: int
    h: int
    trials: list[int] = Field(description="What is actually loaded, in order.")
    n: int
    skipped: list[SkippedFrame] = Field(default_factory=list)
    tone: Tone
    frame_note: str = Field(
        description="⭐ What the reader ACTUALLY did to these pixels, derived from THIS "
        "acquisition's XML — never asserted. It goes into the TIFF header. Do not hard-code "
        '"180-degree-flipped" anywhere: the reader flips CONDITIONALLY on ax/ay, and a header that '
        "lies about its own coordinate frame is the one thing this project has been burned by."
    )
    gpu: GpuInfo
    n_log_entries: int


class SessionListResponse(Res):
    sessions: list[SessionResponse]


class LogEntry(Res):
    trial: int
    type: str
    time: str
    gap_s: float | None = None


class LogResponse(Res):
    """⚠️ `log.txt` prints the date **only** on `New experiment:` lines; every other line carries
    `HH:MM:SS` alone. The parser carries the date forward and handles midnight rollover."""

    experiment: str
    entries: list[LogEntry]
    n_snapshot: int
    n_other: int


class TextureResponse(Res):
    """⭐ **THE MEASUREMENT — and it is CORE, not mosaic.** `std(DoG(3,30))` answers "how much
    texture is in this image", which is a property of the FRAME. Every future feature asks it (a
    segmentation feature must not segment glare; the browser wants to say "these frames are empty").

    It is also **free** here and costs +3.0 s / +624 MiB anywhere else: the matcher's band-passed
    stack and this measure are **the same array**.

    ⛔ There is **no threshold here, no list, and no policy.** Turning a number into a *proposal*
    is the mosaic feature's job (`POST /api/mosaic/screen/propose`), and turning a proposal into a
    *decision* is the human's — it lands in the document. Never in the session.
    """

    measure: str = "std of DoG(sigma=3, sigma=30) of the frame as read"
    texture: dict[int, float]
    n: int


class ThumbsResponse(Res):
    """The contact sheet: ONE sprite sheet. Cell `i` holds `trials[i]` at
    `(x, y) = ((i % grid) * cell, (i // grid) * cell)`."""

    grid: int
    cell: int
    trials: list[int]
    n: int
    version: str = Field(description="`{nonce}.{tone.version}` — pass it as `?v=`.")


class OpenJobResult(Res):
    """`Job.result` when `kind == "open"`."""

    kind: Literal["open"] = "open"
    session: SessionResponse


# =================================================================================================
# PROJECTS — a project is ONE FOLDER, and CAMEA OWNS IT.  CORE.
# =================================================================================================
#
# ⭐ **R44 (2026-08-10).** Every project lives in the app's own store — `%LOCALAPPDATA%/Camea/
# projects/<analysis_id>/` — created automatically, never named by the user, and browsed only
# through the app (`GET /api/projects/{id}/outputs`). The user names exactly one path: where the
# DATA comes from. There is no save-folder question and therefore no save-folder schema.
#
# ⛔ The guards did not soften. `core.project` still refuses `data/`, the repo and any raw
# acquisition folder for every path it is handed — the store is exempt from the *repo* rule only,
# because it is the app's own state directory. The evidence rule has no exceptions.
#
# ⭐ `analysis_id` is still the addressing token: `core.document`, every feature and the whole front
# end name a project by its id, and none of them know where it is stored. See `core/project.py`.


class MigratedProject(Res):
    """One project that came home to the store."""

    name: str
    from_: str = Field(alias="from", description="The folder the user had saved it into.")
    to: str = Field(description="Where it is now, inside Camea's store.")


class FailedMigration(Res):
    """One project that did **not** move. ⭐ It is still exactly where it was."""

    path: str
    reason: str = Field(description="Said out loud, because the user's work is in that folder.")


class MigrationReport(Res):
    """`core.migrate`'s account of the one-time move into the store (R44).

    ⚠️ Reported, never silent. A project that moved without saying so would be indistinguishable
    from one that vanished, and these are folders the user chose and can still find in Explorer."""

    migrated: list[MigratedProject] = Field(default_factory=list)
    failed: list[FailedMigration] = Field(default_factory=list)


class AnalysisSummary(Res):
    """A project = a document + its outputs, in Camea's store.

    ⚠️ **`dataset`/`dataset_key`/`data_dir` may all be empty, and that is not an error.** They were
    mandatory while every task was a wrapper around something on disk; since `Analyze MEA`
    (2026-08-14) a task may have no input at creation at all — its project is a shelf, filled from
    inside. A client must render the blank as a state ("nothing added yet"), never as a missing
    value it should go and look for.
    """

    analysis_id: str
    feature: str = Field(description='"mosaic". Features register their own name.')
    name: str
    dataset_key: str
    dataset: str
    path: str
    folder: str = Field(
        default="",
        description="Where the project lives in Camea's store. ⚠️ Shown for support and diagnosis, "
        "not as somewhere to go: browsing a project means GET /api/projects/{id}/outputs.",
    )
    data_dir: str = Field(default="", description="Where this project's dataset lives.")
    created: str
    modified: str
    bytes: int
    n_tiles: int | None = None
    n_anchored: int | None = None
    n_excluded: int | None = None
    independent_of_method: bool | None = Field(
        default=None,
        description="⚠️ Derived from the document's HISTORY, never from what it claims about "
        "itself. Shown on the card so a seeded document can never be mistaken for a truth.",
    )


class AnalysisListResponse(Res):
    analyses: list[AnalysisSummary]
    unreadable: list[str] = Field(
        default_factory=list,
        description="Project folders in the store that could not be read (a corrupt manifest). "
        "Listed, never silently dropped — and never a failure of the whole home screen.",
    )
    migration: MigrationReport | None = Field(
        default=None,
        description="⭐ Set on the first launch after R44, when pre-R44 projects were brought into "
        "the store. The home screen states it once. null on every ordinary launch.",
    )


class CreateAnalysisRequest(Req):
    """⭐ **THE SERVER CREATES THE DOCUMENT**, via the feature's `new_document` hook.

    🔴 In v1 `project.new_doc()` and `project.seed_from_build()` were **dead code** — the front end
    reimplemented both in JS. That is how `human_edits`' divert counters were silently dropped on
    every save, and how "Skip — place by hand" could erase `seeded_from` while every tile still sat
    exactly where t33 put it. The document is authored on the server. It is not negotiable.
    """

    session_id: str
    feature: str
    name: str
    trials: list[int] | None = Field(
        default=None, description="The feature's selection. null = the session's whole trial list."
    )

    # ⭐ **NO `folder` (R44, 2026-08-10).** The app puts the project in its own store and tells the
    # user where it went. He named the data path; that was the only path question worth asking.


class RenameAnalysisRequest(Req):
    """Rename a project (`PATCH /api/projects/{id}`). Rewrites the manifest only — **the folder
    never moves; the id is forever.** This is what the project manager's rename does."""

    name: str


# =================================================================================================
# OUTPUTS — ⭐ THE ONLY DOOR TO A PROJECT'S FILES.  CORE.  (R44)
# =================================================================================================
#
# **His ruling, 2026-08-10:** *"if users want to browse their project data they have to do it
# through the app itself"* — and, asked how a mosaic then reaches a paper: *"click into a project and
# browse your outputs, select the one(s) you want and save it into somewhere."*
#
# So there are exactly three routes, and between them they are the whole story: **list** what a
# project built, **read** one of those files, and **copy** the chosen ones out to a folder the user
# names at that moment. ⛔ There is no route that opens Explorer, and none that hands out a path to
# paste into one.


class OutputEntry(Res):
    """One file in a project's `outputs/`."""

    name: str = Field(description="Its filename. ⛔ A name, never a path — there are no subfolders.")
    bytes: int
    modified: str
    media_type: str = Field(description="Guessed from the extension. What GET .../outputs/{name} serves.")
    previewable: bool = Field(
        default=False, description="True for images the browser can show inline."
    )


class OutputListResponse(Res):
    """`GET /api/projects/{id}/outputs` — everything this project has built, newest first."""

    outputs: list[OutputEntry] = Field(default_factory=list)


class CopyOutputsRequest(Req):
    """`POST /api/projects/{id}/outputs/copy` — **the one way work leaves Camea.**

    ⛔ The destination is refused (409) inside a dataset or inside `data/`, exactly as every other
    path the app writes to is. ⛔ A file already at the destination is **refused, never overwritten**
    — the user's folder is his, and this route is not allowed to be the reason something in it is
    gone."""

    names: list[str] = Field(description="Which outputs to copy. Names from the listing.")
    dest: str = Field(description="The folder to copy them into. Created if it does not exist.")


class CopyOutputsResponse(Res):
    copied: list[str] = Field(default_factory=list, description="The full paths written.")
    dest: str


# =================================================================================================
# DOCUMENTS — save / load / autosave.  CORE envelope; the FEATURE owns the payload.
# =================================================================================================
#
# 🔴 **THE PAYLOAD IS WRITTEN FLAT, AT THE TOP LEVEL.** The obvious envelope —
# `{..., "feature": "mosaic", "payload": {...}}` — is FORBIDDEN, because the benchmark scorer reads
#
#       doc["tiles"][k]["status"] == "anchor"   and   doc["tolerance_px"]["region_default"]
#
# at the TOP level, and a project the scorer cannot read is a project that cannot be checked.
# So `MosaicDocument` SUBCLASSES `Document` and adds its keys beside the envelope's. Route on
# `feature`; do not nest. (docs/SPLIT.md §4.2)


class AppStamp(Res):
    name: str
    version: str


class SeededFrom(Open):
    method: str
    build_id: str | None = None
    config: dict[str, ConfigValue] = Field(default_factory=dict)
    detected_from: str | None = Field(
        default=None, description="HOW the machine was detected. Evidence, not a self-declaration."
    )


class HumanEdits(Open):
    """The honest record of what the human actually did. Recomputed on every save. **Every number
    states its denominator.**

    ⚠️ `diverted_to_solver` is counted **separately and named next to the number it contaminates**:
    a diverted tile *is* sitting exactly on the machine's position, so it lands inside
    `accepted_unchanged` and reads as agreement. It is not. The app never gave the matcher a vote
    there. (In the defer flow this can be 302 of 311 tiles.)"""

    accepted_unchanged: int = 0
    moved: int = 0
    excluded: int = 0
    unverified: int = 0
    rescued: int = 0
    median_move_px: float = 0.0
    max_move_px: float = 0.0
    diverted_to_solver: int = 0
    diverted_trials: list[int] = Field(default_factory=list)
    diverted_note: str | None = None


class Scale(Res):
    """📏 **PIXELS ONLY.** `um_per_px` is `null` by default and the exporter writes no scale bar and
    no OME-TIFF `PhysicalSizeX/Y`. If the user types a number in, it is written **and stamped
    "user-supplied by hand, not measured"**. ❌ Never 1.237 µm/px — that came from a broken
    inference. (There is no magnification difference between the passes: cross-pass tissue scale is
    1.0000 ± 0.0002. The MEA grid pitch tracks *focus*, not magnification.)"""

    um_per_px: float | None = None
    source: Literal["unknown", "user-supplied by hand, not measured"] = "unknown"


class Provenance(Open):
    """⚠️ **NOT DECORATION.**

    `warning` is present **iff** `independent_of_method` is false, and it is the
    `PROVENANCE_WARNING` constant **verbatim, never paraphrased**. The verdict is derived from the
    document's **HISTORY** — a `build` block, or a single tile still carrying a `machine` position —
    and **never** from what the document says about itself, because `seeded_from` is writable and
    "Skip — place from scratch" once erased it while every tile kept t33's answer.

    🔴 **This project has already destroyed one benchmark exactly this way**
    (`analysis/archive/challenge_2026-07/benchmark/ground_truth/260620d.json` **is T27's own
    output**), and pass 1's ground truth got tiles 128/129/130/148 wrong for the same reason.
    """

    authored_by: str
    app_version: str
    workflow: str
    seeded_from: SeededFrom | None = None
    independent_of_method: bool
    warning: str | None = None
    human_edits: HumanEdits = Field(default_factory=HumanEdits)
    scale: Scale = Field(default_factory=Scale)


class Document(Open):
    """The generic envelope. **What every analysis has, whatever the feature is.**

    Unknown top-level keys — including a whole feature payload — are preserved **verbatim**.
    """

    schema_version: str
    app: AppStamp
    id: str
    feature: str
    dataset: str
    experiment: str = ""
    data_dir: str
    dataset_key: str
    created: str
    modified: str
    provenance: Provenance


class DocumentResponse(Res):
    doc: Document


class SaveDocumentRequest(Req):
    """`PUT /api/analyses/{analysis_id}/document` (into the workspace) or
    `POST /api/documents/save-as` (a file the user names — `Save…`, reachable from EVERY screen).

    ⚠️ **ORDER, on the server:** structural-validate → normalise → stamp → full-validate → write,
    **atomically** (temp + `os.replace`, under a lock, with fsync and a retry). Not
    `validate → normalise`: the derived fields are exactly the ones that drift when the user
    excludes a tile, and `normalise` is what repairs them. 🔴 On Windows two concurrent `os.replace`
    on one target give `WinError 5` and the loser's document was **silently lost**.
    """

    path: str | None = Field(
        default=None, description="save-as only. Refused inside `data/`, the repo, or the dataset."
    )
    doc: Document


class SaveResult(Res):
    path: str
    bytes: int
    saved_at: str
    warnings: list[str] = Field(default_factory=list)


class AutosaveRequest(Req):
    """`POST /api/analyses/{analysis_id}/autosave`. Debounced 2 s, **plus unconditionally on every
    `A` and `E`**. 🔴 **A FAILURE IS LOUD** — never swallowed. (`localStorage` failed *silently* in
    the sandbox and nearly cost a day's work. Autosave is a server file.)

    🔴 **THE RANGE GUARD RUNS HERE**, and in v1 it did not: `autosave()` carried it and nothing
    called `autosave()`. Pass 2's autosave once silently overwrote pass 1's ground-truth records,
    and the autosave slot keys on the DIRECTORY, not the trial range — so the collision is still
    open. A document whose range/dataset disagrees with the slot's is refused with
    `409 range_mismatch`. It is not merged, not renamed, not "repaired".
    """

    doc: Document


class LoadDocumentRequest(Req):
    """`POST /api/documents/load` — the Load screen's *"Load a project…"*, which must be reachable
    **cold** (no session). The server bootstraps a session from the file's own `data_dir`, then
    re-reads the file so the range guard actually runs against the session it belongs to."""

    path: str
    session_id: str | None = None


class LoadDocumentResponse(Res):
    doc: Document
    session: SessionResponse | None = Field(
        default=None, description="Set when the load had to open the dataset itself."
    )
    warnings: list[str] = Field(default_factory=list)
    migrated_from: str | None = Field(
        default=None, description="The old schema_version, if the file was migrated on the way in."
    )


class DocumentProblem(Res):
    kind: str
    message: str
    severity: Literal["error", "warning"] = "error"


class ValidateDocumentRequest(Req):
    doc: Document


class ValidationReport(Res):
    """⛔ **NO TRIAL NUMBER IS SPECIAL.** Nothing here may reject a document for WHICH trials it
    placed. The guard that used to live in v1 ("tile 284 is thrown out and carries a position")
    made the user's own session **unsaveable** the moment he anchored 284."""

    ok: bool
    problems: list[DocumentProblem] = Field(default_factory=list)


# =================================================================================================
# Native dialogs (pywebview).  CORE.
# =================================================================================================
#
# 🔴 Headless ⇒ **501 `no_window`**, and the front end falls back to `window.prompt()` — **which
# Playwright can answer.** That is the only reason the save → kill-server → cold-load → resume
# round-trip is drivable at all. Keep a headless-answerable path for both dialogs.


class DialogOpenDirectoryRequest(Req):
    title: str = "Choose a directory"
    start: str | None = None


class DialogOpenFileRequest(Req):
    title: str = "Open a file"
    filters: list[str] = Field(default_factory=list)


class DialogSaveFileRequest(Req):
    title: str = "Save"
    default_name: str | None = None
    filters: list[str] = Field(default_factory=list)


class DialogPathResponse(Res):
    path: str | None = Field(default=None, description="null = the user cancelled.")


# ⛔ **`RevealRequest` / `POST /api/fs/reveal` were DELETED on 2026-08-10 (R44).** Showing a project
# in Explorer was the last door out of the app to a project's files, and his ruling closed it: the
# app is how you browse your project data. What replaced it is `POST .../outputs/copy` — you take a
# copy of what you chose, to where you chose, deliberately.


# =================================================================================================
# =================================================================================================
#  MOSAIC — the feature.  Everything below this line is `features/mosaic/`.
# =================================================================================================
# =================================================================================================

# -------------------------------------------------------------------------------------------------
# The tile state machine — FOUR states. There are no others.
# -------------------------------------------------------------------------------------------------
#
# | state        | status (on disk) | position         | in the anchor field? | drawn | exported |
# |--------------|------------------|------------------|----------------------|-------|----------|
# | unplaced     | "unplaced"       | null             | no                   | no    | no       |
# | unverified   | "unverified"     | yes              | NO                   | NO ⭐ | iff asked|
# | anchored     | "anchor"    ⚠️   | yes              | YES                  | yes   | yes      |
# | excluded     | "excluded"       | null (→ last_xy) | no                   | no    | no       |
#
# ⚠️ **`state` and `status` DIFFER for anchored/"anchor"**, and `score.load_gt()` keeps every tile
# whose **`status == "anchor"`**. Get the mapping wrong and either nothing or everything lands in
# the exported ground truth. One writer for both fields; on load, `state` wins if present.

TileState = Literal["unplaced", "unverified", "anchored", "excluded"]
TileStatus = Literal["unplaced", "unverified", "anchor", "excluded"]
MatchMode = Literal["global", "local"]
RefusalReason = Literal["blank", "no_anchors"]
RenderMode = Literal["feather", "median", "alpha"]
ExportKind = Literal["tiff", "coverage", "png", "positions", "gt", "qc"]

#: The default export set. `coverage` is absent because it is NOT optional — asking for `tiff`
#: implies it, and the server writes it either way. See `ExportResult`.
DEFAULT_OUTPUTS: list[ExportKind] = ["tiff", "png", "positions", "gt", "qc"]


class RejectedMatch(Open):
    """What the matcher wanted, on a tile the app **diverted** to the solver's answer. It is the
    *evidence for* the divert and the QC report needs it in full."""

    x: float
    y: float
    ncc: float | None = None
    margin: float | None = None
    npix: int | None = None
    rank: int | None = None
    n_anchors: int | None = None


class TileRecord(Open):
    """One tile. `extra="allow"`: unknown per-tile keys round-trip verbatim (a hand-written note in
    somebody's ground truth must survive an app that has never heard of it).

    **Facts that are NOT states** (`blank` / `diverted` / `human` / `stale` / `machine` / `seq` /
    `alt_rank`): model them as fields, never as states, or the counters and the exports go wrong.

    ⚠️ **`ncc` is defined as THE NCC AT THE TILE'S FINAL POSITION**, on every path. On a divert the
    tile is *not* at the match's best position, so writing the rejected alias's score here would
    attribute it to the position that shipped. Re-measure with one `POST /api/mosaic/match/score`.

    ⚠️ A tile that leaves `excluded` must **stop claiming it was thrown out** — `excluded_reason` /
    `unusable_reason` die with the judgement, or a tile goes into the exported ground truth reading
    `status: "anchor", excluded: true`. **But `blank` is NOT cleared**: that is a *measurement*
    about the pixels, not a judgement.
    """

    status: TileStatus
    state: TileState
    x: float | None = None
    y: float | None = None
    r: float | None = Field(default=None, description="Draw radius/opacity hint. Display only.")
    pass_: int | None = Field(default=None, alias="pass")
    machine: XY | None = Field(
        default=None,
        description="What the solver said, translated into the document's frame. ⭐ Its mere "
        "presence makes the provenance non-independent — see `Provenance`.",
    )
    moved_px: float | None = Field(default=None, description="|position − machine|.")
    ncc: float | None = None
    margin: float | None = None
    npix: int | None = None
    n_anchors: int | None = None
    blank: bool = Field(
        default=False,
        description="MEASURED. The matcher refuses this tile. **It excludes nothing and it never "
        "will.** Never cleared — it is a fact about the pixels.",
    )
    texture: float | None = None
    judged_at: str | None = None
    seq: int | None = Field(default=None, description="Judgement order. The stale cascade is seq >.")
    human: bool = Field(
        default=False,
        description="A hand put this position here. ⚠️ `advance()` must NEVER re-match over it — "
        "when he drags a tile it is usually *because the matcher was wrong*.",
    )
    stale: bool = Field(
        default=False,
        description="Matched against an anchor field that has since changed. Cleared only by a "
        "GLOBAL re-check that agrees within 5 px — which is allowed to say NO.",
    )
    diverted: bool = Field(
        default=False,
        description="Sitting on the SOLVER's position because the match was not trustworthy. Dies "
        "the instant a hand rewrites the position. **Not** 'the human accepted the machine'.",
    )
    divert_reason: str | None = None
    rejected_match: RejectedMatch | None = None
    alt_rank: int | None = Field(
        default=None,
        description="Which peak the human chose. **0-indexed in storage; DISPLAYED as +1.** The "
        "number he reads and the number he presses must agree.",
    )
    last_xy: XY | None = Field(default=None, description="The position an `E` took away. For undo.")
    source: str | None = Field(default=None, description="Human-readable provenance of the position.")
    note: str | None = None
    excluded_reason: str | None = None
    unusable_reason: str | None = None


class TolerancePx(Open):
    """⛔ `region_default` is **REQUIRED** — `benchmark/score.py :: load_gt()` reads it, at the top
    level, and the exporter asserts it is there before the file leaves the process."""

    region_default: float


class BlankScanBlock(Open):
    """⭐ **THE SCAN RECOMMENDS. THE USER TICKS. NOTHING IS AUTO-EXCLUDED.**

    `blank` is the DECISION — the list the human left standing, which the matcher will refuse. It
    lives **here, in the document**, and it travels to the matcher **in the request body**
    (`MatchAnchorRequest.refuse`). It is *not* server state. (In v1 it was, and that single field
    is what made the match endpoints impure.)"""

    threshold: float | None = None
    measure: str = "std of DoG(sigma=3, sigma=30) of the frame as read"
    blank: list[int] = Field(default_factory=list)
    scanned: list[int] = Field(default_factory=list)
    accepted: bool = False
    overruled_by_user: list[int] = Field(
        default_factory=list, description="Frames the scan proposed and the human pressed Keep on."
    )


class RunBlock(Open):
    """What the run detection said, recorded so the document can explain itself later."""

    detected: bool = True
    why: str = ""
    pass_split_detected: bool = True
    pass_split_why: str = ""
    n_trials: int = 0


class BuildInfo(Open):
    """t33's own `info` dict, made JSON-safe. ⚠️ `info["config"]` holds a nested `t27.Config` and
    `json.dumps(info)` **crashes** without a coercer. And a **warm cache hit hands back a plain
    dict**, not a `t33.Config` — do not key the coercion on `hasattr(cfg, "t27_config")`, or it is a
    no-op on every cached build, which is the common case."""

    seconds: float | None = None
    gpu: bool | None = None


class BuildBlock(Open):
    """The build, as recorded in the document.

    ⭐ `trials` + `gaps` are **what the solver was actually given**. Without them the document can
    never know its build was solved on a *different* input, and the staleness check degenerates into
    comparing the current trial list with itself. **A build with no recorded `trials` is treated as
    STALE** — the backend refuses to guess."""

    build_id: str | None = None
    method: str = "t33"
    created: str | None = None
    seconds: float | None = None
    gpu: bool | None = None
    n_placed: int = 0
    config: dict[str, ConfigValue] = Field(default_factory=dict)
    info: BuildInfo | None = None
    positions: dict[int, XY] = Field(default_factory=dict)
    trials: list[int] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    stale: bool = False
    stale_reason: str | None = None


class ToneSnapshot(Open):
    """A *display* snapshot, so a reload resumes where he left off. Core owns the tone; the document
    only records it. (⛔ The opacity slider is **not** here: `.camea.json` records the mosaic, not
    the operator's viewing preferences.)"""

    lo: float | None = None
    hi: float | None = None
    level: float | None = None
    flat_sigma: float | None = None
    pct_lo: float | None = None
    pct_hi: float | None = None
    auto: bool | None = None


class MosaicDocument(Document):
    """⭐ **THE MOSAIC PAYLOAD, FLAT, BESIDE THE ENVELOPE.** (See the `Document` note: nesting it
    under `payload` would make it unreadable to the scorer, and a project the scorer cannot read is
    a project that cannot be checked.)

    ⛔ **NOTHING STARTS `excluded`.** Every trial in the run starts `unplaced`. A frame becomes
    `excluded` only when the human presses `E`, or when a project file he loaded says so.
    """

    tiles: dict[int, TileRecord]
    trial_range: tuple[int, int]
    pass_split: int | None = None
    origin_trial: int
    tile_px: int = 512
    coordinates: str = Field(
        description="⚠️ Built from `SessionResponse.frame_note` — i.e. from THIS acquisition's XML. "
        'Never the unconditional literal "180deg-flipped" the v1 constant carried.'
    )
    tolerance_px: TolerancePx
    gaps: list[Gap] = Field(
        default_factory=list,
        description="⚠️ **DERIVED. Recomputed on EVERY change to the excluded set.** Trial numbers "
        "are acquisition ORDER but are NOT contiguous once anything is excluded, and a "
        "'consecutive' pair across a gap is a multi-step jump where the serpentine one-axis step "
        "prior does NOT hold. Miss this and the next solve is silently poisoned.",
    )
    unusable_tiles: list[int] = Field(default_factory=list)
    cursor: int | None = Field(
        default=None,
        description="The sweep position, saved so a load resumes there. 🔴 An **integer**, never "
        "null-on-Escape: `Esc` deselects, it does not abandon the tile you are judging.",
    )
    blank_scan: BlankScanBlock = Field(default_factory=BlankScanBlock)
    run: RunBlock = Field(default_factory=RunBlock)
    build: BuildBlock | None = None
    tone: ToneSnapshot = Field(default_factory=ToneSnapshot)
    electrodes: "ElectrodeMapBlock | None" = Field(
        default=None, description="The fitted electrode-grid summary (2026-08-11); the full "
        "per-electrode table is an outputs/ file it names. None until Map electrodes runs.")


# -------------------------------------------------------------------------------------------------
# Step 2 · Range — the run and the pass split.  MOSAIC's selection of the dataset.
# -------------------------------------------------------------------------------------------------
#
# 🔶 These are **mosaic's**, not core's: `detect_run` applies the 512×512 gate (512 is `t33.TILE`)
# and `pass_split` is `t33.Config.pass_split`. A future segmentation feature will want a different
# selection rule over the same dataset. Core serves `blocks` + `TrialMeta.gap_s`; mosaic decides.
#
# ⚠️ Both rules are MEASURED, are validated on **n = 1 dataset**, and are always overridable. Show
# the number; put the reasoning behind a `?`.


class RunnerUpSplit(Res):
    after_trial: int
    gap_s: float


class PassSplit(Res):
    """⭐ `value` is the **LAST TRIAL OF PASS 1** (166 on 260620d), never 167.

    ⚠️ Keep the `MIN_SIDE_FRAC = 0.20` guard: without it a naive argmax returns **11**, because
    11→12 is *also* 20.0 s (settling right after `Settings loaded`) and ties the true boundary."""

    value: int | None
    detected: bool
    why: str
    gap_s: float | None = None
    median_gap_s: float | None = None
    runner_up: RunnerUpSplit | None = None
    n_pass1: int = 0
    n_pass2: int = 0


class DroppedTrial(Res):
    trial: int
    reason: Literal["off_shape", "not_snapshot"]
    w: int | None = None
    h: int | None = None


class RunDetectRequest(Req):
    """`POST /api/mosaic/run` — detect, or override. **A pure function of the session's inventory.**

    ⭐ It is NOT a session reload. v1 made `PATCH /api/session/run` a full re-open (5 s, and it
    invalidated the tone and the scan) because the run lived *on* the session. It does not any more.
    """

    session_id: str
    lo: int | None = None
    hi: int | None = None
    pass_split: int | None = None


class RunDetection(Res):
    lo: int
    hi: int
    trials: list[int] = Field(
        description="⛔ The run, gated **by shape only**. Nothing is dropped by trial number, ever. "
        "Every snapshot on disk in range is here."
    )
    n: int
    n_in_range: int
    detected: bool
    why: str = Field(description="MEASURED. Goes behind the `?`, verbatim.")
    blocks: list[SnapshotBlock] = Field(default_factory=list)
    dropped: list[DroppedTrial] = Field(default_factory=list)
    pass_split: PassSplit
    gaps: list[Gap] = Field(default_factory=list)


class RescopeRequest(Req):
    """`POST /api/mosaic/document/rescope` — the Range step's `Apply`, applied to the DOCUMENT.

    ⭐ **THE SERVER RE-AUTHORS THE TILE SET.** `POST /api/mosaic/run` only *measures* the run; it
    leaves the document alone, so a project opened on every square snapshot in the dataset kept the
    stray pre-scan snapshots (`1`, `5-7` on 260620d) as tiles of the mosaic. This is the route that
    makes the answer stick — and it is a route, not four edits in the browser, because a changed
    trial list changes the **gaps** and makes the build **stale**.

    🔴 It keeps every surviving tile's work byte-for-byte; only trials that leave the range are
    dropped. `n_placed_removed` in the reply is what the caller should have confirmed first."""

    session_id: str
    doc: MosaicDocument
    lo: int | None = None
    hi: int | None = None
    pass_split: int | None = Field(
        default=None, description="Override. Omit and the split is re-detected for the new range."
    )


class RescopeResponse(Res):
    doc: MosaicDocument
    run: RunDetection = Field(description="The re-detection the new tile set was authored from.")
    n_trials: int
    added: list[int]
    removed: list[int] = Field(
        description="Trials that left the mosaic. ⛔ NOT 'excluded' — they were never tiles of it, "
        "and they do not appear in `unusable_tiles` or in the human-edit counters."
    )
    n_added: int
    n_removed: int
    n_placed_removed: int = Field(
        description="How many of `removed` carried a position. The work that was thrown away."
    )


# -------------------------------------------------------------------------------------------------
# gaps — ⭐ THE ONE FUNCTION THE APP MAY IMPORT FROM THE EXCLUSION MODULE
# -------------------------------------------------------------------------------------------------


class GapsRequest(Req):
    """`POST /api/mosaic/gaps` — a **pure function over a trial list**.

    ⭐ `engine.excluded.gaps()` is the ONLY symbol the app may import from that module. Never
    `EXCLUDED` / `BLANK` / `BLURRY` / `usable_trials`. There is no toggle. This route is the single
    place the app touches it, and it is called on every change to the excluded set."""

    trials: list[int]


class GapsResponse(Res):
    gaps: list[Gap]


# -------------------------------------------------------------------------------------------------
# Step 3 · Screen — the blank PROPOSAL.  (The measurement is core; the decision is the document's.)
# -------------------------------------------------------------------------------------------------


class BlankProposeRequest(Req):
    """`POST /api/mosaic/screen/propose`. Needs `pass_split` because the threshold is defined in
    mosaic's terms: *the 2.0th percentile of PASS-1 texture*."""

    session_id: str
    trials: list[int]
    pass_split: int | None = None


class BlankProposal(Res):
    """⭐ **IT RECOMMENDS. IT NEVER REJECTS.**

    ⚠️ **ZERO MARGIN AT THE BOUNDARY.** Genuinely-blank frames and perfectly good ones *interleave*
    below the threshold. Measured with the refusal lifted, three of the four near-threshold trials
    land 0.24 / 0.18 / 2.07 px from the human truth — they are **ordinary tiles** — while the fourth
    lands **679 px wrong**. One of four. That is exactly why the measure may only ever propose.

    ❌ **NO BLUR JUDGEMENT. EVER.** Across 15 focus measures the best global blur threshold reaches
    F1 = 0.37, and variance-of-Laplacian scores **worse than chance**. No slider, no number, nowhere
    in the UI. Blur is his eye, in the sweep, with `E`.

    ⛔ There is no `BLANK_THRESHOLD` fallback constant. The threshold is **computed from the frames
    in front of it, every time.** A measured number carried in the source would be dataset knowledge.
    """

    threshold: float | None
    threshold_source: str
    measure: str
    texture: dict[int, float]
    proposed: list[int]
    n_proposed: int
    n_scanned: int
    margin_warning: str | None = None


# -------------------------------------------------------------------------------------------------
# Step 4 · Place — the build.
# -------------------------------------------------------------------------------------------------


class T27Config(Open):
    conf: float | None = None
    run_conf: float | None = None
    span: int | None = None
    control: bool | None = None


class BuildConfig(Open):
    """The Advanced drawer. ⚠️ The drawer must say: *"Off the validated path. The shipped 312/312
    build used the defaults."*

    ⚠️ **`pass_split` defaults to the session's DETECTED value, not to t33's literal 166.**
    Validation is done by **constructing** a real `t33.Config` — it raises `TypeError` on an unknown
    knob itself. ⛔ Do not hard-code the knob list here; `extra="allow"` is what lets a new t33 knob
    through without a schema change."""

    pass_split: int | None = None
    anchor_ncc: float | None = None
    split_px: float | None = None
    look: int | None = None
    min_side: int | None = None
    t27: T27Config | None = None


class BuildStartRequest(Req):
    """`POST /api/mosaic/build` → 202 `JobRef`. Holds the **`gpu` exclusive lease** for its whole
    run; another job that wants it gets `409 busy`.

    ⭐ **`trials` IS THE DOCUMENT'S ACTIVE LIST** — everything the user has *not* excluded. This is
    the ONLY way a frame ever leaves a build. Hard-wiring the session's run list here meant pressing
    `E` and then "re-solve" re-solved the **identical problem** and put the excluded frame straight
    back into the chain.

    `config: null` = t33's shipped 312/312 defaults, and that is the one-button path.

    `use_cache` is a **speed** switch, not a correctness one (warm ≈ 25 s vs cold ≈ 3 min). t33's
    cache filename carries a hash of the trial list + config and a mismatch is **refused, not
    repaired** — it cannot serve a stale answer for a different input.
    """

    session_id: str
    trials: list[int]
    pass_split: int
    config: BuildConfig | None = None
    use_cache: bool = True
    analysis_id: str | None = None


class PerTileEvidence(Res):
    """**A "go look here first" list, NOT a verdict.**

    🔴 **PASS-1 TILES HAVE NO PER-TILE CONFIDENCE AT ALL** — t27's info is aggregate-only, and the
    worst tile in the shipped 312/312 build (trial 127, at 9.94 px) **is a pass-1 tile**. Say so,
    loudly, on the screen: **the absence of a warning is not a clean bill of health.**

    ⛔ Do **not** rebuild this on `quality.score_positions`: on the ground-truth-perfect 312/312
    build it flags 11 tiles and **all 11 are false positives (precision 0/11)**. And
    `quality.score_build()` / `quality.leaderboard()` are **dead** — they raise."""

    anchor_ncc: float | None = Field(default=None, description="PASS 2 ONLY. The best signal there is.")
    anchor_residual_px: float | None = Field(
        default=None,
        description="Probably THE number to sort a worklist on (it caught a tile at 2,706 px) — but "
        "it has fired exactly once and its false-positive rate is unmeasured. 'Go look', never a "
        "verdict.",
    )
    run: str | None = None
    run_margin: float | None = None
    pass_: int = Field(alias="pass")


class BuildResult(Res):
    """`Job.result` when `kind == "build"`. Also `GET /api/mosaic/builds/{build_id}`."""

    kind: Literal["build"] = "build"
    build_id: str
    created: str
    trials: list[int] = Field(description="⭐ WHAT THE SOLVER WAS ACTUALLY GIVEN.")
    gaps: list[Gap] = Field(description="⭐ ditto — see `BuildBlock`.")
    pass_split: int
    positions: dict[int, XY]
    n_placed: int
    unplaced: list[int]
    seconds: float
    gpu: bool
    info: BuildInfo
    per_tile: dict[int, PerTileEvidence]


class SeedRequest(Req):
    """`POST /api/mosaic/seed` — apply a build to a document. **The SERVER does this**, not the
    front end (see `CreateAnalysisRequest`).

    🔴 **A RE-SOLVE MUST NOT DESTROY THE HUMAN'S WORK.** It **keeps** every tile that is `anchored`
    **or** flagged `human`, and seeds everything else *around* them — translating the build onto the
    human's field by the **MEDIAN** offset over the protected tiles (a median, not a mean: a tile the
    human corrected *because t33 was wrong* is precisely an outlier, and one 2,969 px correction
    would drag a mean into nonsense). If **none** of the human's tiles are in the build, the two
    frames cannot be tied together and the server **refuses to seed** (`409 refused`) rather than
    guess.

    (v1 called `setState` unconditionally on every non-excluded tile, so a 150-tile sweep with three
    catastrophic hand-corrections in it was wiped by taking the app's own advice to re-solve — and
    the autosave then wrote the wiped document over the crash-recovery file.)"""

    doc: MosaicDocument
    build_id: str


class SeedResponse(Res):
    doc: MosaicDocument
    n_seeded: int
    n_protected: int = Field(description="anchored + human tiles the build was NOT allowed to touch.")
    seed_translation: XY


class MachineEvidenceRequest(Req):
    doc: MosaicDocument


class MachineEvidenceResponse(Res):
    """Powers the provenance panel (a **live warning**, and it stays on the page) and the confirm
    text of "Skip — place by hand". Derived from HISTORY, never from what the document claims."""

    seeded_from: SeededFrom | None
    has_build: bool
    n_machine_tiles: int
    independent_of_method: bool
    warning: str | None = Field(default=None, description="`PROVENANCE_WARNING`, verbatim, or null.")


class DiscardMachineRequest(Req):
    """`POST /api/mosaic/document/discard-machine` — *"Skip — place by hand"*.

    🔴 **IT IS DESTRUCTIVE, OR IT IS NOTHING.** If anything in the document came from a machine it
    discards **every position and the build** (and `machine`, `ncc`, `margin`, `seq`, `human`,
    `source`). Otherwise it launders a machine build into an "independent ground truth": v1 nulled
    `build`, nulled `seeded_from`, set `independent_of_method: true`, deleted the warning — and
    **did not touch a single tile.** Every tile kept t33's position. **Score t33 against that and it
    gets ~100 % by construction. That is the exact mechanism that already destroyed one benchmark in
    this project.**

    Call `machine-evidence` first to name the count in the confirm."""

    doc: MosaicDocument
    confirm: Literal[True] = Field(
        description="Must be literally `true`. There is no path through this route by accident."
    )


class DiscardMachineResponse(Res):
    doc: MosaicDocument
    n_positions_discarded: int
    had_build: bool


# -------------------------------------------------------------------------------------------------
# Step 5 · Sweep — ⭐⭐ THE ANCHOR-COMPOSITE PRIMITIVE. The heart of the app.
# -------------------------------------------------------------------------------------------------
#
# **One endpoint powers four features**: place the next tile (`Space`), the ranked alternatives
# (`V`, `1`–`9`), rescue an unplaced tile, and snap a drag (`mode: "local"`).
#
# *Why a composite is the right primitive, not merely a convenient one:* of 719 genuinely-overlapping
# tile PAIRS on this data, the exact-NCC argmax is **>20 px wrong for 38 of them (5 %), at scores up
# to 0.760** — one 0.760 winner is **757 px wrong** and the truth is the runner-up at 0.677. The
# **same tile against a composite** scores 0.654 vs 0.416 next-best and lands **1.7 px** from the
# human. **Aperture is everything**, and the anchor field the user is building is a big, human-
# certified one.


class Candidate(Res):
    """A peak. `x`/`y` are **world top-left positions** — the server has already done the
    `m0 + (dx, dy)` conversion; the front end never sees a composite coordinate.

    ⚠️ `npix = 0` from a tier-A candidate means **"not measured"**, not "no overlap". Pass it
    through untouched."""

    rank: int = Field(description="0-indexed. **DISPLAYED as +1** — key `1` is rank 0.")
    x: float
    y: float
    ncc: float | None
    npix: int
    subpixel: bool


class CompositeInfo(Res):
    w: int
    h: int
    valid_px: int
    m0: XY


class Refusal(Res):
    """⛔ **BLANK FRAMES ARE REFUSED, NOT SCORED. There is no `force` flag and there will not be
    one.** Two blank frames 136 trials apart correlate **+0.43 at zero shift** (honest noise floor
    0.115) because what they share is *fixed-pattern sensor structure*, which does not move with the
    stage. **They register confidently and wrongly.**

    * **`target` is blank** → REFUSE. `candidates: []`, `best: null`. This is the real hazard.
    * **an `anchor` is blank** → **DROPPED from the composite** (`MatchResult.dropped_anchors`).
      **Not fatal.** 🔴 The rule that made a blank anchor an error dead-ended the app: the moment the
      user anchored the first near-threshold trial, every subsequent `Space` and snap refused
      **forever** and the sweep died at the next tile.
    * **every anchor is blank** → `reason: "no_anchors"`.

    **A human may still place a blank tile by hand** — a human eye is allowed to do what the
    correlator must not. It gets **no NCC**, because there is no honest one."""

    reason: RefusalReason
    trials: list[int]
    texture: float | None = None
    threshold: float | None = None
    message: str


class MatchAnchorRequest(Req):
    """⭐⭐ **A PURE FUNCTION OF THIS BODY.** The server holds no tile state to be out of sync with.

    🔴 **THE PREFETCH, AND THE CORRECTNESS TRAP IN IT.** Every `Space` costs ~1 s, so the front end
    fires the *next* tile's match the instant the current one is **displayed** — and that prefetch
    **MUST INCLUDE THE TILE CURRENTLY UNDER JUDGEMENT IN `anchors`**, i.e. it must assume the user
    will press `A`. Prefetching from a composite **without** it **disagrees with the truth in 18 % of
    presses and is catastrophically wrong (up to 1,143 px) in 6 %**.

    The server memoises on

        cache_key = sha1({session nonce, target, [(t, x, y) for t in sorted(anchors)],
                          mode, near, radius, max_candidates, sorted(refuse)})

    — i.e. **the key IS the anchor set and their positions.** Press `E` instead of `A` and the set
    genuinely differs ⇒ the key differs ⇒ the memo misses ⇒ the server recomputes honestly. **The
    trap is structurally impossible to fall into, as long as the server holds no tile state.**

    ⇒ ⛔ **NEVER add a client-side prefetch cache keyed on the trial number.** The prefetch is
    literally the same POST, fired early, and its answer is thrown away.
    ⇒ ⛔ **Never invent a second server cache keyed on the trial number.**
    """

    session_id: str
    target: int
    anchors: list[int] = Field(
        description="The reference field. Order is irrelevant (the server sorts). Must be non-empty "
        "and must not contain `target`."
    )
    positions: dict[int, XY] = Field(
        description="World top-left of **every** trial in `anchors`. Extras ignored; a missing "
        "anchor is a 400."
    )
    mode: MatchMode = "global"
    near: XY | None = Field(
        default=None, description="REQUIRED when mode == 'local': where the user dropped the tile."
    )
    radius: int = Field(
        default=64,
        ge=8,
        le=256,
        description="local only. ⚠️ **Never widen past 128 in the UI**: the electrode grid repeats "
        "every **256 px** and a wide *local* search will confidently lock onto a grid alias. To "
        "search wide, use `mode: 'global'` — the FFT + margin is what survives the aliases.",
    )
    max_candidates: int = Field(default=9, ge=1, le=16, description="⭐ 9, or key `9` can never fire.")
    refuse: list[int] = Field(
        default_factory=list,
        description="🔴 **THE REFUSAL SET, IN THE BODY** — the blank list the human left standing "
        "(`MosaicDocument.blank_scan.blank`). It is part of `cache_key`. In v1 this was hidden "
        "server state that `PUT /api/scan/blank` mutated, which is precisely what made this "
        "endpoint impure. **That endpoint no longer exists.**",
    )


class MatchResult(Res):
    """`candidates` is sorted by `ncc` descending, peaks ≥ 24 px apart (t33's NMS). It may be empty.

    ⚠️ **The aperture is small at the start.** With one anchor down this call *is* a tile-pair — the
    weak case above. It works anyway because consecutive snapshots overlap ~78 %. **But surface the
    evidence** (`n_anchors`, `composite.valid_px`, `ncc`, `margin`) on every placement, so the user
    watches the evidence strengthen instead of taking it on faith."""

    target: int
    mode: MatchMode
    n_anchors: int
    composite: CompositeInfo | None = None
    candidates: list[Candidate] = Field(default_factory=list)
    best: Candidate | None = None
    margin: float | None = Field(
        default=None, description="candidates[0].ncc − candidates[1].ncc. null if there is only one."
    )
    margin_thin: bool = Field(
        default=False,
        description="margin < 0.10. ⚠️ **THE UI MUST FLAG IT LOUDLY** — this is what a surviving "
        "grid alias looks like. The shipped build's worst run margin is 0.081 vs a ~0.47 typical.",
    )
    refused: Refusal | None = None
    dropped_anchors: list[int] = Field(
        default_factory=list, description="Blank anchors dropped from the composite. Not an error."
    )
    gpu: bool
    elapsed_ms: float
    cached: bool
    cache_key: str


class MatchScoreRequest(Req):
    """`POST /api/mosaic/match/score` — *"you dropped it here; what do the pixels say?"* One
    `exact_ncc`, no search (~31 ms). Used live during a drag (debounced 150 ms), to label the
    alternatives, and to **re-measure a diverted tile's NCC where it actually sits**.

    ⭐ Deliberately **NOT** serialised behind an in-flight `match/anchor`: it used to wait out a
    whole match, so the live NCC under the cursor was up to a full match out of date."""

    session_id: str
    target: int
    anchors: list[int]
    positions: dict[int, XY]
    at: XY
    refuse: list[int] = Field(default_factory=list)


class ScoreResult(Res):
    """⚠️ `ncc` is **`null`** when the overlap is below `exact_ncc`'s floor (< 3000 valid px, or
    < 64 px on a side). The honest answer is *"not measurable"* — **never `0.0`**."""

    target: int
    at: XY
    ncc: float | None
    npix: int
    refused: Refusal | None = None
    dropped_anchors: list[int] = Field(default_factory=list)
    elapsed_ms: float


class RecheckRequest(Req):
    """`POST /api/mosaic/recheck` → 202 `JobRef` (it is N × ~1 s — it never blocks).

    🔴 **THE RE-CHECK IS GLOBAL, AND IT IS ALLOWED TO SAY NO.** It **never moves a tile** — it only
    measures it. Anything that disagrees with where the tile sits by more than `tolerance_px`
    **STAYS FLAGGED**.

    v1 fired a *local* match (±64 px) and then cleared `stale` unconditionally. But a tile knocked
    off by a moved anchor is off by **hundreds** of px — failure on this data is **binary**,
    sub-pixel-right or wildly wrong — so a ±64 px window is *structurally blind* to the one error the
    panel exists for. Measured: a tile **380 px** from the truth re-checked locally to `ncc −0.0678`,
    was not moved, and had its flag **cleared** — the loud panel disappeared and the tile stayed 380
    px wrong, with a negative NCC recorded in the document as its evidence."""

    session_id: str
    doc: MosaicDocument
    trials: list[int] | None = Field(default=None, description="null = every tile flagged stale.")
    tolerance_px: float = 5.0


class RecheckRow(Res):
    trial: int
    at: XY
    best: XY | None
    disagree_px: float | None
    ncc: float | None
    margin: float | None
    still_stale: bool


class RecheckResult(Res):
    """`Job.result` when `kind == "recheck"`. ⚠️ It returns **rows, not a document** — the re-check
    does not move anything; the front end clears the flags it is told it may clear."""

    kind: Literal["recheck"] = "recheck"
    n_checked: int
    cleared: list[int]
    disagree: list[RecheckRow] = Field(description="**Go and look.** These are still wrong.")


class RecomputeRequest(Req):
    """`POST /api/mosaic/recompute` → 202 `JobRef`. ⭐ **The tool the user reaches for.** Freeze the
    tiles he has anchored and re-place every other tile against their combined composite — then he
    anchors more and recomputes again.

    It is `recheck`'s per-target `match_anchor(global)` loop, but it **writes** the answer instead of
    only measuring it: every placed tile lands `unverified` + `machine` (never `anchored` — I3), and
    an `anchored`, `human`, or `excluded` tile is never touched (the frozen reference / his own work).
    A target with no measurable overlap against the anchors is **left untouched** — anchor a neighbour
    and recompute again."""

    session_id: str
    doc: MosaicDocument
    trials: list[int] | None = Field(
        default=None,
        description="null = every non-anchored, non-human, non-excluded, loaded tile.")


class RecomputeResult(Res):
    """`Job.result` when `kind == "recompute"`. ⚠️ Unlike `recheck`, it **returns the DOCUMENT** — the
    front end adopts it exactly as it adopts a `/seed` result (and re-hydrates the sweep)."""

    kind: Literal["recompute"] = "recompute"
    doc: MosaicDocument
    n_placed: int = Field(description="tiles re-placed against the anchor composite.")
    n_unmeasurable: int = Field(
        description="targets with no measurable overlap with the anchors — left untouched.")
    n_reference: int = Field(description="anchored tiles used as the frozen ground truth.")


# -------------------------------------------------------------------------------------------------
# Step 6 · Mosaic — export + QC.
# -------------------------------------------------------------------------------------------------


class ExportRequest(Req):
    """`POST /api/mosaic/export` → 202 `JobRef`. Holds the `gpu` lease.

    **What is rendered:** `anchored`, plus `unverified` **iff `include_unverified`**. `excluded` and
    `unplaced` are **never** rendered. Positions are normalised so `origin_trial` sits at exactly
    `(0, 0)`, matching `analysis/ground_truth/`.

    `render_mode` default **feather** — the only interactive one (feather 1.11 s; median 41.7 s;
    alpha 74 s).

    ⭐⭐ **TIFF AND PNG ARE TWO DIFFERENT RENDERS.** The `flat` flag decides what the pixels *are*:
    `flat=True` is a *picture* (per-tile gain); `flat=False` is **raw camera counts** = the TIFF.
    The TIFF was once rendered `flat=True` while its header said RAW — trial 11's median went
    2111 → 3435 (×1.63).

    🔴 The export must describe the document **AS EXPORTED** (the *stamped* one), not as posted. A
    laundered doc once produced a GT JSON saying "NOT AN INDEPENDENT GROUND TRUTH" beside a TIFF
    header saying "hand-placed from scratch"."""

    session_id: str
    basename: str = Field(
        description="What the exported files are CALLED. ⭐ Not where they go — since R44 they go "
        "into this project's outputs/, and the user is never asked for a folder."
    )
    doc: MosaicDocument
    outputs: list[ExportKind] = Field(default_factory=lambda: list(DEFAULT_OUTPUTS))
    render_mode: RenderMode = "feather"
    include_unverified: bool = True
    um_per_px: float | None = Field(default=None, description="📏 See `Scale`. Pixels only by default.")


class ExportedFile(Res):
    kind: ExportKind
    path: str
    bytes: int


class ExportResult(Res):
    """`Job.result` when `kind == "export"`. **7 files.**

    ⚠️⚠️ **THE COVERAGE MASK IS MANDATORY**, not an option: **13.1 % of the canvas is background
    encoded as exactly `0.0`**, indistinguishable from a legitimately black pixel, and a TIFF has
    **no alpha channel**. Without the sidecar, "empty" and "black" merge forever. It is free
    (`wsum > 0` in the feather path). Asking for `tiff` implies `coverage`.

    `positions.csv`'s header is **exactly** `trial,x,y,state` — `score.load_positions` DictReads the
    first three. The GT JSON is asserted **scoreable** (`tiles[k].status`, `tolerance_px.region_default`)
    before it leaves the process."""

    kind: Literal["export"] = "export"
    files: list[ExportedFile]
    doc: MosaicDocument = Field(description="The document **as exported** — stamped. Not as posted.")
    warnings: list[str] = Field(default_factory=list)


class QcRequest(Req):
    doc: MosaicDocument


class QcDenominator(Open):
    """⭐ **EVERY NUMBER STATES ITS DENOMINATOR.** A percentage without one is how the 182-vs-156
    confusion started. The denominator is the document's own `excluded` set, and nothing else — the
    app has no list of its own.

    ⚠️ **`not_excluded` was called `usable_trials` in v1's `qc.json`, and it is RENAMED here on
    purpose.** The name collided, character for character, with `excluded.usable_trials()` — the one
    symbol the standing ruling forbids the app to import. A key in a report is not a function, but
    the whole point of that ruling is that nobody should ever have to make that distinction. The
    number is unchanged: **every tile the human did not exclude.** (Nothing machine-readable depends
    on the old name: `score.py` reads `gt.json` and `positions.csv`, never `qc.json`.)"""

    trials_in_document: int
    not_excluded: int
    excluded: int


class QcMovedRow(Open):
    trial: int
    moved_px: float
    from_: XY = Field(alias="from")
    to: XY
    state: TileState
    ncc: float | None = None
    margin: float | None = None
    n_anchors: int | None = None
    note: str | None = None


class QcReport(Open):
    """What the human did vs what the machine said. This report **is** the honest record of the
    anchoring hazard, and it is what makes the output safe to hand to somebody else."""

    dataset: str
    trial_range: tuple[int, int]
    pass_split: int | None
    generated: str
    app: AppStamp
    denominator: QcDenominator
    by_state: dict[TileState, list[int]]
    moved: list[QcMovedRow]
    thin_margin: list[int]
    rescued: list[int]
    build_stale: bool
    build_stale_reason: str | None = None
    provenance: Provenance


# =================================================================================================
# Video mosaic (`features/videomosaic`) — a mosaic built AUTOMATICALLY from a survey video.
# =================================================================================================
class VideoSource(Res):
    """The probe receipt. `fps`/`n_frames` are what the container CLAIMS (phone video is often
    VFR) — good for a receipt, never for arithmetic. Probing decodes a real frame, so a receipt
    means 'this will decode', not 'a header parsed'."""

    path: str
    name: str
    width: int
    height: int
    fps: float
    n_frames: int
    duration_s: float
    size_bytes: int


class VideoProbeRequest(Req):
    path: str = Field(description="Path of a video file (mp4/avi/…) — anything cv2 decodes.")


class CreateVideoProjectRequest(Req):
    """⭐ THE SERVER CREATES THE DOCUMENT — `POST /api/videomosaic/projects`. The video-source
    sibling of `CreateAnalysisRequest`: no session, the probed receipt becomes `doc.source`.

    ⭐ **NO `folder` — and neither has the dataset task since R44 (2026-08-10).** Both create their
    project in Camea's store. R43 got here first for this feature, by deferring the folder question
    until the mosaic existed; R44 removed the question instead."""

    name: str
    video_path: str


class VideoBuildRequest(Req):
    analysis_id: str
    config: dict[str, ConfigValue] | None = Field(
        default=None,
        description="VideoConfig overrides, for development and tests. The UI sends null: a "
        "normal user never tunes computer-vision parameters to get a mosaic.")


class VideoKeyframeRecord(Open):
    """One automatically selected video frame. `x`/`y` are canvas top-left corners (R19),
    null when the frame could not be tied to the mosaic (`placed: false`)."""

    x: float | None = None
    y: float | None = None
    segment: int | None = None
    reason: str | None = None
    placed: bool = False


class VideoMosaicDocument(Document):
    """A videomosaic document: envelope + `source`/`config`/`build`/`keyframes`, flat."""

    source: VideoSource | None = None
    config: dict[str, ConfigValue] | None = None
    build: dict | None = Field(
        default=None, description="{built_at, canvas, outputs, stats} — the last build's "
        "summary; the full forensics live in outputs/build.json.")
    keyframes: dict[str, VideoKeyframeRecord] = Field(default_factory=dict)
    electrodes: "ElectrodeMapBlock | None" = Field(
        default=None, description="The fitted electrode-grid summary (2026-08-11); stale when "
        "its source_stamp no longer equals build.built_at. None until Map electrodes runs.")
    regions: list["RegionRecord"] = Field(
        default_factory=list, description="Fixed-field calcium recordings located on this "
        "mosaic (2026-08-11), newest last. Empty until Locate regions runs.")


class VideoCanvasSize(Res):
    w: int
    h: int


class VideoMosaicBuildResult(Res):
    """`job.result` of a `videomosaic_build` job. The document is already SAVED server-side
    when this appears — the UI refetches or takes `doc` as-is; it never authors."""

    kind: Literal["videomosaic_build"] = "videomosaic_build"
    doc: VideoMosaicDocument
    canvas: VideoCanvasSize
    stats: dict
    outputs: dict[str, str] = Field(
        description="logical name -> FILENAME of each artifact (mosaic, preview, positions, "
        "build). They sit in the project folder itself, named after the project. Filenames, not "
        "paths: a saved project moves (R43), and a recorded absolute path would go stale.")


# ⛔ **`VideoSaveRequest` / `POST /api/videomosaic/save` were DELETED on 2026-08-10 (R44).** There is
# nothing to save into: the project was in Camea's store from the moment it was created, and the
# mosaic is in its `outputs/`. Getting a copy out is `POST /api/projects/{id}/outputs/copy`, which
# every feature shares.


# =================================================================================================
# Electrodes — the grid mapping BOTH features share (2026-08-11)
# =================================================================================================
#
# ⭐ The MEA's electrode pads form a near-square lattice; `core.electrodegrid` measures it from the
# FINISHED mosaic (pitch, rotation, phase — never assumed: the app carries no dataset knowledge) and
# gives every position a `column-row` id, `1-1` top-left, columns rightward, rows downward ALONG THE
# LATTICE (the real grid sits ~2 deg off the image axes). Occluded positions carry interpolated
# centres flagged `inferred` — every position is numbered (his ruling, 2026-08-11).
#
# 🔶 Coordinates: the MOSAIC feature stores centres in DOCUMENT WORLD px (the viewer's space), with
# `canvas_offset` recording `world - rendered_canvas`; the VIDEOMOSAIC stores canvas px (its canvas
# IS the mosaic.png). `coordinates` carries the session's frame note, same as the document.
#
# ⭐ **THE DEVICE IS KNOWN, AND HE SAYS WHETHER IT IS ALL IN FRAME (R45.8, 2026-08-11).** The chip is
# a MaxWell MaxOne/MaxTwo: 220 × 120 = 26,400 electrodes at 17.5 µm pitch. That spec lives in exactly
# one place (`core.electrodegrid.DeviceSpec` / `MAXWELL`) and it **checks and completes** a measured
# fit — it never replaces one, so R45.1 stands: the lattice is still measured off the pixels. It
# binds only as far as the user lets it, and he says so BEFORE mapping via `array_coverage`:
#   * `"full"`  — the whole chip is in frame: the fit must come out 220 × 120 (either orientation);
#                 a near miss is corrected (edge lines added as `inferred` / a phantom line dropped)
#                 and the correction is reported in `stats.shape_corrected`, never silent; a fit far
#                 off REFUSES, naming both shapes.
#   * `"partial"` — only part of the chip is imaged: no shape rule at all, and `1-1` is the top-left
#                 of the IMAGED REGION, not of the chip.
# Both modes get the 17.5 µm scale: `um_per_px = 17.5 / measured pitch_px`, and every electrode
# carries `x_um`/`y_um` in the array's own frame **alongside** its pixels.
# ⚠️ This `um_per_px` is NOT the export/provenance `Scale.um_per_px` (R30: pixels only, a hand-typed
# magnification is a lie). It is a MEASURED quantity — a known device pitch over the pitch this image
# actually shows — and it stays on the electrode surfaces. Do not plumb it into `Scale`.
# ⛔ The server defaults `array_coverage` to `"partial"`, the mode that assumes nothing; the UI
# refuses to map at all until he has picked one (no default may map silently).
# ⭐ And the spec is **SERVED**, not retyped: `GET /api/electrodes/device` (core — both features map
# the same chip) hands the UI `MAXWELL` itself, so the sentence the user agrees to before mapping
# quotes the numbers that will actually be enforced. See `ElectrodeDevice`.


ARRAY_COVERAGE_DESC = (
    "Did the user say the WHOLE chip is in frame? 'full' enforces the device shape "
    "(220 x 120 = 26,400 electrodes, either orientation) and corrects a near miss; 'partial' "
    "enforces nothing but the 17.5 um scale, and 1-1 is the top-left of the imaged region. "
    "R45.8 — he picks before mapping; the server default is the assumption-free one.")


class ElectrodeDevice(Res):
    """`GET /api/electrodes/device` — ⭐ **THE CHIP, ON THE WIRE, so nothing has to retype it.**

    🔴 R45.8 put every device number in exactly one place (`core.electrodegrid.DeviceSpec` /
    `MAXWELL`) — and then the coverage question the UI asks *before* mapping wrote them out a second
    time as button prose ("220 × 120", "26,400", "17.5 µm"), in TypeScript, where nothing keeps them
    honest. Change `DeviceSpec.axes` and the panel goes on promising the old array while the fitter
    enforces the new one: **the UI describing a rule it is not the one enforcing.** This model is the
    fix — the spec is served, typed, and the UI reads it instead of repeating it.

    ⛔ **No field here has a default.** A default would be a second copy of the device fact, which is
    the very duplication this endpoint exists to close. The values are `MAXWELL`'s, whatever they are.
    """

    name: str = Field(description='Whose numbers these are, e.g. "MaxWell MaxOne/MaxTwo".')
    axes: tuple[int, int] = Field(
        description="The two array axis lengths, **ORIENTATION-FREE** — the chip can sit portrait or "
        "landscape in a mosaic, so neither the fitter nor the UI may assume which one is columns.")
    pitch_um: float = Field(
        description="Centre-to-centre electrode spacing, µm. The physical ruler that turns the "
        "MEASURED pixel pitch into a scale (`um_per_px = pitch_um / pitch_px`) — in BOTH coverage "
        "modes. It is never used to assume a pitch: R45.1 stands, the lattice is measured.")
    electrodes: int = Field(
        description="axes[0] * axes[1]. Derived by the spec, never typed in twice — and the number a "
        "'whole chip imaged' map must contain, exactly.")


class ElectrodeMapRequest(Req):
    """`POST /api/mosaic/electrodes/map` — fit the electrode grid of the built mosaic."""

    session_id: str
    doc: "MosaicDocument"
    include_unverified: bool = Field(
        default=True, description="Render (and therefore map) the same tile set the export "
        "defaults to: anchored plus unverified. False = certified field only.")
    array_coverage: Literal["full", "partial"] = Field(
        default="partial", description=ARRAY_COVERAGE_DESC)


class VideoElectrodeMapRequest(Req):
    """`POST /api/videomosaic/electrodes/map` — fit the grid of the saved video mosaic."""

    analysis_id: str
    array_coverage: Literal["full", "partial"] = Field(
        default="partial", description=ARRAY_COVERAGE_DESC)


class ElectrodeMapBlock(Open):
    """`doc[\"electrodes\"]` — the SUMMARY of a fitted grid (the full per-electrode table lives in
    `outputs/<name>-electrodes.json`, listed here by filename). `source_stamp` identifies the tile
    positions / build the map was computed from; when it no longer matches, the map is STALE and
    the UI says so instead of silently highlighting drifted centres."""

    built_at: str | None = None
    cols: int = 0
    rows: int = 0
    pitch_px: float = 0.0
    angle_deg: float = 0.0
    hit_radius_px: float = 0.0
    stats: dict = Field(
        default_factory=dict, description="the fit's own numbers, plus `um_per_px` and — when the "
        "whole chip was declared imaged and the fit was a near miss — `shape_corrected` "
        "({'cols': +1, 'rows': -1}), which the panel MUST show: a corrected shape is never silent.")
    outputs: dict[str, str] = Field(
        default_factory=dict, description="logical name ('map', 'csv') -> FILENAME in outputs/.")
    source_stamp: str | None = None
    coordinates: str | None = None
    array_coverage: str = Field(
        default="partial", description="what the user declared before mapping: 'full' or 'partial'. "
        "Recorded so a reopened project still knows whether 1-1 is the chip's corner or only the "
        "imaged region's (R45.8). Old blocks predate the field and read as 'partial'.")
    um_per_px: float | None = Field(
        default=None, description="device pitch / measured pitch_px. None when no device applied.")
    device: str | None = Field(
        default=None, description="the device NAME the spec came from ('MaxWell MaxOne/MaxTwo'). "
        "The full spec (axes, pitch, electrode count) rides on the payload, not on this summary.")


class ElectrodeCells(Res):
    """Flat parallel arrays, one entry per EXISTING grid position (absent corners omitted).
    `kind`: 1 = detected on the pixels, 2 = inferred from the lattice (occluded/dead pad).

    `x`/`y` are pixels in the feature's own space; `x_um`/`y_um` are the SAME positions in the
    ARRAY's frame — origin at electrode 1-1's lattice position, rotation taken out, so x grows
    along columns and y along rows. They land near `(col-1) * 17.5` / `(row-1) * 17.5` but carry
    the real measured deviation. Both are served: µm is added ALONGSIDE pixels, never instead."""

    col: list[int]
    row: list[int]
    x: list[float]
    y: list[float]
    kind: list[int]
    x_um: list[float] = Field(
        default_factory=list, description="µm along the column axis. Empty on maps written before "
        "R45.8 (and whenever no device spec applied) — never assume it is populated.")
    y_um: list[float] = Field(default_factory=list, description="µm along the row axis.")


class ElectrodeMapPayload(Res):
    """The full electrode map, served typed so the client never re-derives geometry. A pixel
    resolves to electrode `col-row` only within `hit_radius_px` of that centre (his click rule:
    the pad plus a slim margin; the gaps select nothing — arrow keys step to neighbours)."""

    cols: int
    rows: int
    pitch_px: float
    angle_deg: float
    hit_radius_px: float
    a1: tuple[float, float] = Field(description="mean column step vector (one cell rightward), px")
    a2: tuple[float, float] = Field(description="mean row step vector (one cell downward), px")
    canvas_offset: tuple[float, float] = Field(
        description="world = rendered-canvas px + this offset. (0,0) for the videomosaic.")
    coordinates: str | None = None
    built_at: str | None = None
    stale: bool = Field(description="True when the mosaic changed after this map was built "
                        "(tile positions edited / rebuilt) — re-run the mapping.")
    stats: dict = Field(default_factory=dict)
    um_per_px: float | None = Field(
        default=None, description="MEASURED scale: the device's known pitch (17.5 µm) over the "
        "pitch this image actually shows. None when the map was written without a device spec. "
        "⚠️ Not the provenance `Scale.um_per_px` (R30) — that one stays absent.")
    device: dict | None = Field(
        default=None, description="the spec that supplied the µm scale: "
        "{name, axes, pitch_um, electrodes}. None on maps written before R45.8.")
    array_coverage: str = Field(
        default="partial", description="'full' = the user declared the whole chip imaged, so the "
        "shape was checked against the device (and any near miss corrected — see "
        "`stats.shape_corrected`). 'partial' = only part of the chip: **1-1 is the top-left of the "
        "IMAGED REGION, not of the chip**, and the UI must say so.")
    cells: ElectrodeCells


class ElectrodeMapResult(Res):
    """`job.result` of an `electrode_map` job (either feature). The videomosaic job saves its
    document server-side and returns it; the mosaic feature's document is CLIENT-owned, so the UI
    merges `electrodes` into its doc and saves — same split as build vs export."""

    kind: Literal["electrode_map"] = "electrode_map"
    analysis_id: str
    electrodes: ElectrodeMapBlock
    doc: Document | None = None


# =================================================================================================
# THE ELECTRICAL HALF — what an electrode actually measured *(2026-08-13)*
# =================================================================================================
#
# The mosaic names electrodes; a MaxWell recording says what they recorded. Clicking a pad and
# seeing its trace is the first place the two halves of the ground-truth pairing meet in the UI.
#
# ⭐ THREE THINGS THIS CONTRACT REFUSES TO HIDE, because each one silently corrupts the pairing:
#   1. **Most electrodes were never recorded.** ~1k of 26.4k are routed at acquisition, so
#      `recorded: false` is the common answer and must render as a fact, not an empty chart.
#   2. **The raw stream may not decode.** MaxWell compresses it with a proprietary filter whose
#      decoder ships with MaxLab Live; the published one does not reconstruct this project's files
#      (98% of samples come back as one fill value). `health` carries that measurement so the UI
#      can say so — see `core/mearecording.py` for the evidence.
#   3. **The chip's seating in the mosaic is not knowable from any file.** `orientation.confirmed`
#      is false until something establishes it, and while it is false an electrode's identity is
#      provisional. Never present an unconfirmed pairing as settled.

class MeaRecordingSummary(Res):
    """One `data.raw.h5` found for a project. Header facts only — no raw decode needed."""

    run_id: str = Field(description='The acquisition run, e.g. "000690".')
    assay: str = Field(description='The assay folder that holds it, e.g. "Network".')
    label: str = Field(description='What a human calls it: "Network/000690".')
    path: str
    n_channels: int = Field(description="Electrodes actually routed and recorded — NOT the chip's "
                            "electrode count. The rest of the array has no trace at all.")
    n_samples: int
    sampling_hz: float
    duration_s: float
    lsb_uv: float = Field(description="Microvolts per stored count.")
    gain: float
    hpf_hz: float
    n_spikes: int = Field(description="Spikes MaxWell's on-chip detector wrote into the file. "
                          "Needs no proprietary decoder, so this number is always trustworthy.")


class MeaOrientation(Res):
    """How the chip's own axes sit in the mosaic — the half no file records (see header)."""

    flip_x: bool = False
    flip_y: bool = False
    confirmed: bool = Field(default=False, description="False until something ESTABLISHED this "
                            "seating. While false the UI must mark electrode identity provisional.")
    source: str = Field(default="", description="How it was established, for provenance.")


class MeaAttachment(Res):
    """What electrical data a project has, and whether its trace can be believed."""

    attached: bool
    mea_dir: str | None = Field(default=None, description="The folder the recordings were found "
                                "in. ⛔ Read-only, outside the project, never written to.")
    recordings: list[MeaRecordingSummary] = Field(default_factory=list)
    stride: int | None = Field(default=None, description="The array's long-axis length, DERIVED "
                               "from the recording's own numbering and verified against every "
                               "routed electrode — never a datasheet number.")
    pitch_um: float | None = Field(default=None, description="Also derived from the numbering, "
                                   "not from the routed spacing (sparse routing would double it).")
    orientation: MeaOrientation = Field(default_factory=MeaOrientation)
    decoder_present: bool = Field(default=False, description="A MaxWell decode plug-in is on this "
                                  "machine. Says NOTHING about whether it decodes correctly — only "
                                  "a trace's `health` can say that.")


class SeatingScorePayload(Res):
    """One candidate seating and how well it explains the data."""

    flip_x: bool
    flip_y: bool
    n_recorded: int = Field(description="Of the region's pads, how many this seating maps onto "
                            "electrodes that were actually recorded.")
    n_region: int = Field(description="How many pads the region covers — the denominator.")
    coverage: float
    n_spikes: int
    correlation: float | None = Field(
        default=None, description="Spike rate vs calcium activity. ⭐ **null means UNTESTABLE** — "
        "this seating puts no recorded electrode under the field — which is a different answer "
        "from a low correlation and must never be rendered as one.")
    scorable: bool


class OrientationTestResult(Res):
    """`job.result` of an `mea_orientation` job — the four seatings, ranked.

    🔴 **UNVALIDATED, AND THE UI MUST SAY SO** (issue 003). The clock alignment rests on the 2P-lamp
    marks, and those did not survive checking against the calcium video: 70 MEA episodes against 5
    video dark stretches, no consistent offset, and a confound where the "episodes" may be where the
    broken decoder emitted anything rather than where the lamp fired. He asked for it built anyway
    (2026-08-13). It ranks; it never confirms. `Orientation.confirmed` is set by a human only.
    """

    kind: Literal["mea_orientation"] = "mea_orientation"
    analysis_id: str
    run_id: str
    region_id: str
    region_name: str = ""
    scores: list[SeatingScorePayload] = Field(default_factory=list)
    best: MeaOrientation | None = Field(
        default=None, description="The top-ranked seating — a PROPOSAL, and only when `decisive`. "
        "Never applied by the job, and null when the seatings could not be told apart.")
    decisive: bool = Field(
        default=False, description="⭐ Whether the data actually separated the seatings. False "
        "means the UI must say **cannot tell** and offer no winner — crowning the top of four "
        "near-identical numbers would manufacture an answer out of noise.")
    decided_by: str = Field(
        default="", description="What separated them: 'coverage' (only one seating puts any "
        "recorded electrode under the field — a geometric fact, independent of the decoder and the "
        "clock, so the strongest evidence available here), 'correlation', or '' when nothing did.")
    margin: float | None = Field(
        default=None, description="Top correlation minus runner-up, among testable seatings. "
        "Null when fewer than two were testable.")
    offset_s: float = Field(default=0.0, description="Clock shift applied, MEA onto video.")
    alignment_quality: float = Field(
        default=0.0, description="Jaccard overlap of the two lamp-mark trains at that offset. "
        "⚠️ Read it sceptically: two mostly-on signals overlap substantially at ANY shift. On this "
        "project's data the best was 0.65 between signals of 60% and 80% duty — i.e. chance.")
    caveat: str = Field(default="", description="Why this result cannot be taken at face value. "
                        "The UI shows it verbatim, never behind a `?`.")


class MeaOrientationRequest(Req):
    analysis_id: str
    region_id: str | None = Field(default=None, description="Which located region to test against. "
                                  "Defaults to the first one the project has.")
    run_id: str | None = None


class MeaAttachRequest(Req):
    analysis_id: str
    mea_dir: str | None = Field(default=None, description="Where to look. When omitted the server "
                                "searches beside the project's dataset folder and reports what it "
                                "found — the user still confirms before it is saved.")
    confirm: bool = Field(default=False, description="False = discover and report only. True = "
                          "save this attachment onto the project.")
    orientation: MeaOrientation | None = None


class TraceHealthPayload(Res):
    """How much of a returned window is one repeated value — the honesty check on a waveform."""

    n_samples: int
    fill_value: int
    fill_fraction: float = Field(description="Share of samples equal to the commonest value. A "
                                 "live electrode carries thermal noise, so a healthy window sits "
                                 "low; near 1.0 means the decoder did not reconstruct the stream.")
    distinct_values: int
    flat: bool = Field(description="⛔ True = NOT a usable waveform. The UI must say so rather "
                       "than draw a convincing flat line.")


class MeaSpike(Res):
    t_s: float
    amplitude_uv: float


class MeaSyncEpisode(Res):
    """A stretch where hundreds of channels left the rail together — a 2P lamp artefact.

    ⭐ Deliberate, not noise: the experimenters switched the lamp to stamp the MEA record with
    events also visible optically, so the two clocks can be aligned. Render them, never remove them.
    """

    start_s: float
    end_s: float
    duration_s: float
    peak_channels: int


class ElectrodeTracePayload(Res):
    """Everything the panel needs for one clicked electrode."""

    electrode: str = Field(description='The Camea grid id that was clicked, e.g. "42-117".')
    recorded: bool = Field(description="False when this pad was never routed — the ordinary case. "
                           "Render as a fact; there is no trace to draw.")
    run_id: str | None = None
    channel: int | None = Field(default=None, description="The MaxWell channel carrying it.")
    chip_electrode: int | None = Field(default=None, description="MaxWell's own electrode id.")
    t0_s: float = 0.0
    t1_s: float = 0.0
    sampling_hz: float = 0.0
    trace_uv: list[float] = Field(default_factory=list, description="The stored waveform in µV. "
                                  "⚠️ Judge it with `health` before believing it.")
    health: TraceHealthPayload | None = None
    spikes: list[MeaSpike] = Field(default_factory=list, description="Detected spikes inside the "
                                   "window. Trustworthy independently of the trace.")
    n_spikes_total: int = Field(default=0, description="Across the whole recording, not the window.")
    first_spike_s: float | None = Field(
        default=None, description="When this electrode first fired. ⭐ The UI opens its window HERE "
        "rather than at t=0: a 300 s recording stepped one second at a time would take 200 clicks "
        "to reach the activity, and a dead opening window makes a working electrode look broken.")
    duration_s: float = Field(default=0.0, description="The whole recording, so the UI can scrub.")
    sync_episodes: list[MeaSyncEpisode] = Field(default_factory=list)
    orientation: MeaOrientation = Field(default_factory=MeaOrientation)


# =================================================================================================
# REGION RECORDINGS — where a fixed-field calcium video sits on the mosaic *(2026-08-11)*
# =================================================================================================
#
# The experiment: a culture on an MEA chip is filmed region by region with calcium imaging while
# the chip records voltages, and finally swept whole to build the mosaic. Locating a fixed-region
# recording on that mosaic — and naming the electrodes under it — is what pairs an MEA channel
# with the neuron whose calcium trace sits on top of it.
#
# ⭐ Every number a user needs to judge a placement rides on the record: which still won, the
# measured zoom and whether it WAS measured, the NCC, the margin over the runner-up, and the
# alternatives. A placement is `unconfirmed` until he says otherwise.

class RegionZoom(Res):
    """How much the recording was shrunk/grown to sit on the mosaic, and where that came from."""

    scale: float = Field(description="Multiply recording px by this to get mosaic px.")
    measured: bool = Field(
        description="True when the ratio was MEASURED from the electrode lattice in both "
        "pictures. False means no lattice could be read and a ladder of zoom factors was "
        "searched instead — a guess the UI must not present as a measurement.")
    pitch_recording_px: float | None = None
    pitch_mosaic_px: float | None = None
    angle_recording_deg: float | None = None
    angle_mosaic_deg: float | None = None
    angle_delta_deg: float | None = Field(
        default=None, description="Degrees the recording's lattice is turned relative to the "
        "mosaic's, folded into (-45, 45]. Rotation is NOT solved (same rig, same orientation) "
        "— this is reported so a reseated chip is visible instead of silently mis-placed.")
    note: str = ""


class RegionCandidate(Res):
    """One place the recording could sit. `x`/`y` are TOP-LEFT corners (R19), never centres."""

    rank: int
    x: float
    y: float
    ncc: float
    npix: int
    subpixel: bool = False


class RegionElectrodes(Res):
    """The electrodes whose centres fall inside the rectangle — the point of the whole feature."""

    count: int
    detected: int
    inferred: int
    ids: list[str] = Field(description="`col-row`, the electrode map's own ids.")
    cols: list[int] = Field(default_factory=list)
    rows: list[int] = Field(default_factory=list)
    map: str | None = Field(default=None, description="The map FILENAME these ids came from.")
    array_coverage: str | None = None
    um_per_px: float | None = None


class RegionRecord(Open):
    """`doc[\"regions\"][i]` — one located recording, with its evidence."""

    id: str
    name: str = Field(description="Editable label; defaults to the video's file name.")
    source: VideoSource | None = None
    still: str | None = Field(
        default=None, description="FILENAME in outputs/ of the winning still, already resampled "
        "to MOSAIC SCALE — the picture the UI fades into the rectangle, and the template a "
        "re-snap matches with. One file, both jobs.")
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0
    still_kind: str = Field(
        default="", description="Which projection of the recording won: median / max / std.")
    zoom: RegionZoom | None = None
    ncc: float | None = None
    margin: float | None = Field(
        default=None, description="best - runner-up on the GLOBAL surface. The only evidence "
        "that the aperture killed the electrode-comb aliases rather than outscoring them.")
    margin_thin: bool = False
    confident: bool = False
    candidates: list[RegionCandidate] = Field(default_factory=list)
    tried: list[dict] = Field(
        default_factory=list, description="Every still x scale that was attempted, with its "
        "score — so a poor result can be diagnosed instead of merely disbelieved.")
    electrodes: RegionElectrodes | None = None
    status: Literal["unconfirmed", "confirmed"] = "unconfirmed"
    placed_by: str = Field(default="machine", description="machine | hand | hand+snap")
    located_at: str | None = None
    source_stamp: str | None = Field(
        default=None, description="The build's `built_at` this was placed against. Rebuild the "
        "mosaic and the location is STALE — it never silently drifts.")
    moved_px: float | None = None
    snap_margin: float | None = None
    elapsed_ms: float | None = None


class LocateRegionRequest(Req):
    """`POST /api/videomosaic/regions/locate` — add a recording and place it."""

    analysis_id: str
    path: str = Field(description="The video file to add. ⭐ The ONE path question allowed "
                      "inside a project (R44): where the recording came from. It is COPIED into "
                      "the project, which then owns it.")
    name: str = Field(default="", description="Optional label; defaults to the file's name.")


class SnapRegionRequest(Req):
    """`POST /api/videomosaic/regions/snap` — *"I dragged it here, now snap it."*"""

    analysis_id: str
    region_id: str
    x: float = Field(description="Where the user dropped the rectangle's TOP-LEFT, mosaic px.")
    y: float
    radius: int | None = Field(
        default=None, description="Local search half-width in mosaic px. Clamped server-side: a "
        "local search has no whole-plane view, so a wide one is an alias generator.")


class RegionUpdateRequest(Req):
    """`PATCH /api/videomosaic/regions` — rename, or confirm. Both are the user's word."""

    analysis_id: str
    region_id: str
    name: str | None = None
    status: Literal["unconfirmed", "confirmed"] | None = None


class RegionsPayload(Res):
    """`GET /api/videomosaic/{id}/regions`."""

    analysis_id: str
    regions: list[RegionRecord] = Field(default_factory=list)
    built_from: str | None = None
    stale: bool = Field(
        default=False, description="True when the mosaic was rebuilt after these were placed.")
    outputs: dict[str, str] = Field(default_factory=dict)


class LocateRegionResult(Res):
    """`job.result` of a `locate_region` job. The videomosaic document is SERVER-owned, so it is
    already saved when this appears — the UI adopts `doc` or refetches; it never authors."""

    kind: Literal["locate_region"] = "locate_region"
    analysis_id: str
    region: RegionRecord
    doc: Document | None = None


# =================================================================================================
# Analyze MEA (`features/mea`) — a MaxWell recording on its own, with no calcium in sight.
# =================================================================================================
#
# ⚠️ **Not to be confused with the `Mea*` models above.** Those belong to `videomosaic`: they attach
# an electrical recording to an *optical* project and carry the chip-seating question that comes
# with a microscope. This task has no microscope, so it has none of that — and it must not grow it
# "for consistency" (his interview, 2026-08-14).


class CreateMeaProjectRequest(Req):
    """⭐ THE SERVER CREATES THE DOCUMENT — `POST /api/mea/projects` -> 201 `AnalysisSummary`.

    ⭐ **A NAME, AND NOTHING ELSE.** The sibling requests each carry the one input their task is
    a wrapper around — `CreateAnalysisRequest` a session, `CreateVideoProjectRequest` a video
    path. This one carries none, because the project *is the shelf*: he names it, and puts
    recordings on it from inside. Asking for the first `.h5` here was considered and rejected.

    ⭐ **And no `folder`, like every create since R44** — the project is made in Camea's own
    store. Between that and having no input file, this route asks **zero path questions**, which
    is one fewer than any other way to make a project.
    """

    name: str = Field(
        default="",
        description="What he wants to call it. Blank is allowed and becomes a placeholder — "
        "there is no filename to fall back to.",
    )


# =================================================================================================
# The job-result union — declared last, because it names every feature's result.
# =================================================================================================
#
# 🔶 `core.jobs` itself knows nothing about these; `kind` is a free string there and features
# register their own. This union lives in the API layer (which is allowed to know every feature) so
# that the generated TypeScript client gets a real discriminated union on `Job.result.kind` instead
# of an `any`. **A new feature adds a member here, and nowhere else.**

JobResult = Annotated[
    Union[OpenJobResult, BuildResult, ExportResult, RecheckResult, RecomputeResult,
          VideoMosaicBuildResult, ElectrodeMapResult, LocateRegionResult,
          OrientationTestResult],
    Field(discriminator="kind"),
]

Job.model_rebuild()
MosaicDocument.model_rebuild()
VideoMosaicDocument.model_rebuild()


__all__ = [
    # base / common
    "Req",
    "Res",
    "Open",
    "XY",
    "Gap",
    "Scalar",
    "ConfigValue",
    # errors
    "ErrorCode",
    "ErrorBody",
    "ErrorEnvelope",
    "OkResponse",
    # jobs
    "JobState",
    "JobKind",
    "JobRef",
    "JobError",
    "JobCancelResponse",
    "Job",
    "JobListResponse",
    "JobResult",
    # videomosaic
    "VideoSource",
    "VideoProbeRequest",
    "CreateVideoProjectRequest",
    "VideoBuildRequest",
    "VideoKeyframeRecord",
    "VideoMosaicDocument",
    "VideoCanvasSize",
    "VideoMosaicBuildResult",
    # region recordings (videomosaic)
    "LocateRegionRequest",
    "LocateRegionResult",
    "RegionCandidate",
    "RegionElectrodes",
    "RegionRecord",
    "RegionUpdateRequest",
    "RegionZoom",
    "RegionsPayload",
    "SnapRegionRequest",
    # electrodes (both features)
    "ElectrodeDevice",
    "ElectrodeMapRequest",
    "VideoElectrodeMapRequest",
    "ElectrodeMapBlock",
    "ElectrodeCells",
    "ElectrodeMapPayload",
    "ElectrodeMapResult",
    "ElectrodeTracePayload",
    "MeaAttachRequest",
    "MeaAttachment",
    "MeaOrientationRequest",
    "OrientationTestResult",
    "SeatingScorePayload",
    "MeaOrientation",
    "MeaRecordingSummary",
    "MeaSpike",
    "MeaSyncEpisode",
    "TraceHealthPayload",
    # Analyze MEA (its own feature — see the section note; not the videomosaic `Mea*` models)
    "CreateMeaProjectRequest",
    # health / gpu / settings
    "HealthResponse",
    "GpuInfo",
    "Settings",
    "SettingsUpdate",
    # datasets
    "ShapeGroup",
    "SnapshotBlock",
    "AnalysisRef",
    "DatasetSummary",
    "DatasetListResponse",
    "DatasetAtRequest",
    "TrialMeta",
    "DatasetDetail",
    # sessions
    "Tone",
    "ToneUpdate",
    "SkippedFrame",
    "OpenSessionRequest",
    "SessionResponse",
    "SessionListResponse",
    "LogEntry",
    "LogResponse",
    "TextureResponse",
    "ThumbsResponse",
    "OpenJobResult",
    # projects — one project is ONE FOLDER, named by the user (R42)
    "AnalysisSummary",
    "RenameAnalysisRequest",
    "AnalysisListResponse",
    "MigratedProject",
    "FailedMigration",
    "MigrationReport",
    "OutputEntry",
    "OutputListResponse",
    "CopyOutputsRequest",
    "CopyOutputsResponse",
    "CreateAnalysisRequest",
    # documents
    "AppStamp",
    "SeededFrom",
    "HumanEdits",
    "Scale",
    "Provenance",
    "Document",
    "DocumentResponse",
    "SaveDocumentRequest",
    "SaveResult",
    "AutosaveRequest",
    "LoadDocumentRequest",
    "LoadDocumentResponse",
    "DocumentProblem",
    "ValidateDocumentRequest",
    "ValidationReport",
    # dialogs
    "DialogOpenDirectoryRequest",
    "DialogOpenFileRequest",
    "DialogSaveFileRequest",
    "DialogPathResponse",
    # mosaic — document
    "TileState",
    "TileStatus",
    "RejectedMatch",
    "TileRecord",
    "TolerancePx",
    "BlankScanBlock",
    "RunBlock",
    "BuildInfo",
    "BuildBlock",
    "ToneSnapshot",
    "MosaicDocument",
    # mosaic — run / gaps / screen
    "RunnerUpSplit",
    "PassSplit",
    "DroppedTrial",
    "RunDetectRequest",
    "RunDetection",
    "RescopeRequest",
    "RescopeResponse",
    "GapsRequest",
    "GapsResponse",
    "BlankProposeRequest",
    "BlankProposal",
    # mosaic — build
    "T27Config",
    "BuildConfig",
    "BuildStartRequest",
    "PerTileEvidence",
    "BuildResult",
    "SeedRequest",
    "SeedResponse",
    "MachineEvidenceRequest",
    "MachineEvidenceResponse",
    "DiscardMachineRequest",
    "DiscardMachineResponse",
    # mosaic — sweep
    "MatchMode",
    "RefusalReason",
    "Candidate",
    "CompositeInfo",
    "Refusal",
    "MatchAnchorRequest",
    "MatchResult",
    "MatchScoreRequest",
    "ScoreResult",
    "RecheckRequest",
    "RecheckRow",
    "RecheckResult",
    "RecomputeRequest",
    "RecomputeResult",
    # mosaic — export / qc
    "RenderMode",
    "ExportKind",
    "DEFAULT_OUTPUTS",
    "ExportRequest",
    "ExportedFile",
    "ExportResult",
    "QcRequest",
    "QcDenominator",
    "QcMovedRow",
    "QcReport",
]
