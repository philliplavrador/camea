"""routes.py — the mosaic feature's FastAPI router. **Everything under `/api/mosaic`.**

This is the mosaic's half of the old `app/backend/server.py`. The core half (health, gpu, datasets,
sessions, tiles, tone, workspace, documents, jobs, dialogs) is `camea/api/app.py` and is NOT here.

WHAT A ROUTE IN THIS FILE IS ALLOWED TO BE
------------------------------------------
A router, and nothing else. It **validates**, it **delegates**, it **shapes the reply**. The science
is in `solve.py`, the document rules are in `document.py`, the pixels that leave the process are in
`export.py`. If a handler here starts doing arithmetic on positions, it is in the wrong file.

THE FOUR RULES THIS FILE IS BUILT ON
-----------------------------------
1. ⛔ **NO DATASET KNOWLEDGE.** No trial number is special in this file. Nothing is auto-excluded —
   not by the blank scan (which *proposes*), not by the run gate (which drops **only** by frame
   shape, and says so). The one thing the app touches in the exclusion module is `gaps()`, and it
   reaches it through `camea.core.dataset.gaps`. `POST /api/mosaic/gaps` is that, exposed.

2. ⭐⭐ **`POST /api/mosaic/match/*` IS A PURE FUNCTION OF ITS REQUEST BODY.** This is not taste; it
   is the prefetch's correctness proof. The sweep fires tile N+1's match while tile N is still
   fading in, so the prefetch must **assume the user will press `A`** and include the tile under
   judgement in `anchors`. (Prefetching without it disagrees with the truth in 18 % of presses and
   is catastrophically wrong — up to 1,143 px — in 6 %.) The server memoises on a key that **IS**
   the anchor set, their positions **and the refusal set** — so pressing `E` changes the key, misses
   the memo, and forces an honest recompute. **The trap is structurally impossible to fall into as
   long as the server holds no tile state to be out of sync with.**

   ⇒ **This file holds no tile state.** Not a blank list, not an exclusion, not a cursor. The
   refusal set arrives in `MatchAnchorRequest.refuse` on every call, and it looks redundant, and it
   is not: v1 kept it on the session, `PUT /api/scan/blank` mutated it, and that single field is
   what made the match endpoints impure. **That endpoint does not exist here and must never come
   back.**

3. **LONG OPERATIONS RETURN A JOB.** `build` (a child process — `t33.place` has no cooperative
   cancel, so `terminate()` is the only cancel there is), `export` and `recheck`. They never block.

4. **THE 409.** Interactive match work is refused while a job holds the **`gpu` lease**. v1 asked
   `JOBS.running("build")` — a *feature's word* in a core check. We ask `JOBS.holder("gpu")`, which
   is the same protection stated as a resource fact, and which a future segmentation build gets for
   free.

WHAT THIS FILE OWES ANOTHER FILE
-------------------------------
`solve` / `document` / `export` are imported **lazily, inside the handlers** — on purpose. Importing
`camea.features.mosaic.routes` must not drag in cv2, cupy or spectralign (the package `__init__`
says so), and the API surface must be inspectable (`/openapi.json`) on a machine where the engine
cannot even load.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import numpy as np
from fastapi import APIRouter, HTTPException

from camea.api.schemas import (
    BlankProposal,
    BlankProposeRequest,
    BuildResult,
    BuildStartRequest,
    DiscardMachineRequest,
    DiscardMachineResponse,
    ElectrodeMapPayload,
    ElectrodeMapRequest,
    ErrorCode,
    ExportRequest,
    GapsRequest,
    GapsResponse,
    JobRef,
    MachineEvidenceRequest,
    MachineEvidenceResponse,
    MatchAnchorRequest,
    MatchResult,
    MatchScoreRequest,
    QcReport,
    QcRequest,
    RecheckRequest,
    RecomputeRequest,
    RescopeRequest,
    RescopeResponse,
    RunDetectRequest,
    RunDetection,
    ScoreResult,
    SeedRequest,
    SeedResponse,
)
from camea.core import dataset as core_dataset
from camea.core import document as core_document
from camea.core.frames import TEXTURE_MEASURE, FrameStore
from camea.core.jobs import JOBS, Busy, Progress, check_cancelled, report_adapter
from camea.core.workspace import DatasetIsReadOnly, app_state_dir, refuse_write, safe_basename

# =================================================================================================
# Constants — mosaic's, and only mosaic's
# =================================================================================================

#: ⭐ **512 IS `t33.TILE`**, which is precisely why the 512x512 gate is a *mosaic policy* and not a
#: core one: a `FrameStore` holds frames of whatever shape the XML says and does not care. Taken from
#: `camea.engine.TILE` (the public adapter constant) rather than copied, so there is one 512 in the
#: app and not a fourth.
from camea.engine import TILE  # noqa: E402  (kept beside the comment that explains it)

#: The blank proposal's percentile. A *policy*, applied to a *measurement* core owns.
#: ⛔ There is **no `BLANK_THRESHOLD` fallback constant.** v1 carried `60.11` — 260620d's own
#: measured number — in the source "as a fallback". That is dataset knowledge, and it is deleted,
#: not ported. The threshold is computed from the frames in front of it, every time.
BLANK_PCT = 2.0

#: A pass-1 reference set smaller than this cannot support a 2nd percentile. Nothing is proposed.
BLANK_MIN_REFERENCE = 20

#: t33 places pass 2 **against pass 1** and raises without a solvable reference pass. Refuse here,
#: where the message reaches the user, rather than failing the job 200 s in.
MIN_PASS1 = 4
MIN_PASS2 = 2

router = APIRouter(prefix="/api/mosaic", tags=["mosaic"])


# =================================================================================================
# Errors
# =================================================================================================
class ApiError(HTTPException):
    """The `{"error": {"code", "message", "detail"}}` envelope, raised.

    ⚠️ **It subclasses `HTTPException` deliberately.** `camea/api/app.py` owns the exception handler
    that renders `ErrorEnvelope`; this router is included into that app. If app.py registers a
    handler for *this* class (or hoists it to a shared `camea/api/errors.py` and imports it here —
    which is the better home), the envelope renders exactly. If it registers one only for
    `HTTPException`, the **status code still survives** and the body degrades to FastAPI's
    `{"detail": {...}}` rather than to an opaque 500. A 400 must never be able to become a 500 over
    a wiring detail — that is the bug shape that turned v1's refused document into an opaque 500 on
    every 2-second autosave.
    """

    def __init__(self, status: int, code: ErrorCode, message: str,
                 detail: dict[str, str] | None = None) -> None:
        self.code = code
        self.message = message
        self.info = dict(detail or {})
        super().__init__(
            status_code=status,
            detail={"code": code, "message": message, **({"detail": self.info} if self.info else {})},
        )


# =================================================================================================
# The session seam
# =================================================================================================
@runtime_checkable
class MosaicSession(Protocol):
    """What the mosaic needs from an open session. **Read-only, except that core may re-tone it.**

    ⛔ Note what is NOT here: no tile states, no exclusions, no blank list, no run, no pass split.
    Those are the *document's*, and the document is the client's to send. See rule 2 in the module
    docstring — the moment this object grows a mutable analysis field, the match endpoints stop
    being pure functions of their bodies and the prefetch's correctness argument collapses.
    """

    session_id: str
    dataset: core_dataset.Dataset
    frames: FrameStore


#: The registry lives in `camea/api/app.py` (core owns sessions; a session is shared by every open
#: feature). A feature must not import the api layer — so app.py **injects** the lookup here at
#: startup. One line, and it keeps the dependency arrow (`api -> features -> core`) intact.
_SESSION_PROVIDER: Any = None


def set_session_provider(fn: Any) -> None:
    """`fn(session_id: str) -> MosaicSession | None`. Called once, by `camea.api.app`."""
    global _SESSION_PROVIDER
    _SESSION_PROVIDER = fn


#: ⭐ **THE STORE (R44).** The export writes into the PROJECT's `outputs/`, so this router needs to
#: resolve an `analysis_id` the same way core does. Injected by `app.py`, for the same reason the
#: session provider is: a feature must not import the api layer.
_PROJECTS_PROVIDER: Any = None


def set_store(projects: Any) -> None:
    """`projects() -> ProjectSet`. Called once, by `camea.api.app`."""
    global _PROJECTS_PROVIDER
    _PROJECTS_PROVIDER = projects


def _outputs_dir(analysis_id: str):
    """⭐ Where an export lands (R44): `<store>/<analysis_id>/outputs/`.

    ⚠️ The id comes from the DOCUMENT being exported (`doc["id"]`), not from the wire — so an export
    can only ever write into the project whose document it is, which is the same rule
    `guard_slot` enforces on every save.
    """
    if _PROJECTS_PROVIDER is None:
        raise ApiError(500, "io_error",
                       "the mosaic router has no store provider — camea.api.app must call "
                       "camea.features.mosaic.routes.set_store() at startup")
    if not analysis_id:
        raise ApiError(400, "bad_request",
                       "this document carries no project id, so Camea does not know which "
                       "project's outputs to write into")
    try:
        return _PROJECTS_PROVIDER().outputs_dir(analysis_id)
    except Exception as e:                              # noqa: BLE001
        raise ApiError(404, "not_found", f"no project with id {analysis_id!r}: {e}") from e


def _session(session_id: str) -> MosaicSession:
    if _SESSION_PROVIDER is None:
        raise ApiError(500, "io_error",
                       "the mosaic router has no session provider — camea.api.app must call "
                       "camea.features.mosaic.routes.set_session_provider() at startup")
    s = _SESSION_PROVIDER(session_id)
    if s is None:
        raise ApiError(404, "no_session", f"no such session: {session_id}")
    return s


# =================================================================================================
# Lazy handles on the feature's other modules
# =================================================================================================
def _doc(model: Any) -> dict:
    """⭐⭐ **A `MosaicDocument` OFF THE WIRE -> THE DOCUMENT AS THE REST OF THIS PACKAGE DEFINES IT:
    a plain dict whose TILE KEYS ARE DECIMAL STRINGS.** Every route that takes a document uses this.
    Nothing may call `body.doc.model_dump()` directly.

    🔴 **THE SEAM BUG THIS CLOSES, AND IT WAS LIVE.** `schemas.MosaicDocument.tiles` is
    `dict[int, TileRecord]` — JSON has no integer keys, so pydantic parses `"11"` and hands back a
    dict keyed by the **int** `11`. But this feature's own contract is the opposite, and it says so:
    `document.tiles_of()` is documented `-> dict[str, dict]` ("Trial ids are decimal STRINGS in
    JSON"), and `document.normalise()` indexes `tiles[str(origin)]` — because that is what is **on
    disk**, and a document read back from a file has string keys.

    Most of `document.py` reads its tiles through `int(k)` comprehensions and so never noticed. Six
    lines do not (`normalise` 685/686/699/700, `seed_from_build` 469/470, `validate` 955), and those
    six are precisely the ones that set the ORIGIN TILE TO (0,0) and compute the SEED TRANSLATION.
    Measured against the live server: `POST /api/mosaic/seed` died with `KeyError: '11'` inside
    `normalise` — i.e. **the one route whose entire job is to not destroy the human's work, 500'd on
    every call**, and so did every other route that posts a document (`qc`, `recheck`, `export`,
    `discard-machine`).

    ⚠️ The save/load routes in `api/routes_core.py` never hit this, because `SaveDocumentRequest.doc`
    is the *base* `Document` — the mosaic payload rides through `extra="allow"` as an untouched dict,
    string keys intact. That is exactly why this was invisible until a `MosaicDocument`-typed route
    was actually driven. **Do not "fix" it by re-typing the schema**: the wire is JSON and the wire
    is right. Convert at the boundary, once, here.
    """
    doc = model.model_dump(by_alias=True)
    tiles = doc.get("tiles")
    if isinstance(tiles, dict):
        doc["tiles"] = {str(k): v for k, v in tiles.items()}
    build = doc.get("build")
    if isinstance(build, dict) and isinstance(build.get("positions"), dict):
        # `BuildBlock.positions` is `dict[int, XY]` and lands on disk as strings for the same reason.
        build["positions"] = {str(k): v for k, v in build["positions"].items()}
    return doc


def _solve():
    from camea.features.mosaic import solve
    return solve


def _document():
    from camea.features.mosaic import document
    return document


def _export():
    from camea.features.mosaic import export
    return export


# =================================================================================================
# Guards
# =================================================================================================
def _need_gpu_free() -> None:
    """409 `busy` while a job holds the **`gpu` lease**.

    🔴 The reason is two GPU contexts, not politeness: a spawned build's device peak is ~2.0 GB and
    the parent may already hold ~2 GB from interactive matching. On a 4 GB card that is the
    difference between a build and an OOM.

    ⚠️ **Ask about the LEASE, never about a KIND.** v1 asked `JOBS.running("build")` — the mosaic's
    word, hard-coded into the shared runner — and applied it to thread jobs too, which is why an
    `open` was refused outright while a build ran.
    """
    held = JOBS.holder("gpu")
    if held is not None:
        raise ApiError(409, "busy",
                       f"a {held.kind} job is running and holds the GPU; "
                       f"the sweep is disabled until it finishes",
                       {"job_id": held.job_id, "kind": held.kind})


def _cache_dir(s: MosaicSession) -> Path:
    """t33's on-disk solve cache, per dataset.

    ⚠️ **Keyed on `dataset.key` — basename + sha1 of the RESOLVED directory — never on the
    basename.** t33's cache filename carries a hash of the trial list and the config but **nothing
    that identifies the pixels**, so the directory was the only discriminator; two folders both
    called `260620d` under different parents collided on the identical filename, and
    `t33._load_checked` compares only the CONFIG and would hand back the wrong acquisition's layout
    as a warm hit.
    """
    d = app_state_dir() / "cache" / s.dataset.key
    d.mkdir(parents=True, exist_ok=True)
    return d


# =================================================================================================
# Step 2 · Range — the run and the pass split
# =================================================================================================
#
# 🔶 These are **mosaic's selection of the dataset**, not properties of it. Core serves the raw
# inventory (`snapshot_blocks`, the per-trial shape from the XML, `detect_timing_split`); the mosaic
# decides what to *do* with it. A future segmentation feature will want a different rule over the
# same frames, and it must not have to unpick this one.
#
# ⚠️ SPLIT §1.2 gives these a file of their own (`features/mosaic/run.py`), and they should be
# lifted into one. They are written here as **pure module-level functions over core's inventory** so
# that the lift is a cut-and-paste with no route change. See the report.


def _shape_gate(s: MosaicSession, lo: int, hi: int) -> tuple[list[int], list[dict]]:
    """⭐ **THE GATE, AND ITS ONLY TWO REASONS.**

    ⛔⛔ **NOTHING IS DROPPED BY TRIAL NUMBER.** A frame leaves this list for exactly two reasons,
    and both are facts about the file on disk:

        `off_shape`    — a genuine snapshot, but not TILExTILE (`t33.TILE`), read from its OWN XML
        `not_snapshot` — no .dat, a movie, a 2-frame "snapshot", unreadable XML

    ⚠️ **SHAPE IS PER-TRIAL, NOT PER-DIRECTORY.** The sibling acquisition `260620` has trial 021 as
    a genuine `type="snapshot" frames="1"` at 512x128 — 131,072 bytes. It is real data; it simply
    cannot be a 512x512 mosaic tile. It is dropped **here, loudly, by shape**, and never silently
    reshaped into a 512x512 lie.
    ⚠️ Dropping it opens an acquisition GAP (20 -> 22). `gaps()` recomputes, as it must.
    """
    snaps = s.dataset.snapshots          # the raw disk inventory. Filters nothing by trial number.
    trials: list[int] = []
    dropped: list[dict] = []
    for t in range(int(lo), int(hi) + 1):
        m = snaps.get(t)
        if m is None:
            dropped.append({"trial": t, "reason": "not_snapshot", "w": None, "h": None})
        elif (int(m["h"]), int(m["w"])) != (TILE, TILE):
            dropped.append({"trial": t, "reason": "off_shape", "w": int(m["w"]), "h": int(m["h"])})
        else:
            trials.append(t)
    return trials, dropped


def _detect_run(s: MosaicSession, lo: int | None, hi: int | None) -> dict:
    """The run = ⭐ **THE LONGEST CONTIGUOUS BLOCK OF `Snapshot` TRIALS**, gated to TILExTILE.

    Nothing is hard-coded. On 260620d there are 342 Snapshot trials in exactly three contiguous
    blocks — (1), (5-7), (11-348) — and this rule yields **11-348, all 338 of them**.

    ⚠️ Validated on **n = 1 dataset**. The UI must show what was detected and let the user override
    it — which is what `lo` / `hi` on the request are for. An override is *not* a session reload:
    the run does not live on the session any more.
    """
    blocks = s.dataset.blocks()
    if not blocks:
        raise ApiError(400, "bad_request", "this dataset's log.txt contains no Snapshot trials")

    detected = lo is None and hi is None
    if detected:
        b_lo, b_hi = s.dataset.longest_block()
    else:
        b_lo = int(lo) if lo is not None else int(blocks[0][0])
        b_hi = int(hi) if hi is not None else int(blocks[-1][1])
    if b_lo > b_hi:
        raise ApiError(400, "bad_request", f"lo ({b_lo}) > hi ({b_hi})")

    shown = ", ".join(f"{a}" if a == b else f"{a}-{b}" for a, b in blocks)
    plural = "s" if len(blocks) != 1 else ""
    why = (f"longest run of Snapshot trials ({len(blocks)} block{plural}: {shown})" if detected
           else f"{b_lo}-{b_hi}, chosen by hand (detected: {shown})")

    trials, dropped = _shape_gate(s, b_lo, b_hi)
    return {
        "lo": b_lo,
        "hi": b_hi,
        "trials": trials,
        "n": len(trials),
        "n_in_range": b_hi - b_lo + 1,
        "detected": detected,
        "why": why,
        "blocks": [{"lo": a, "hi": b, "n": b - a + 1} for a, b in blocks],
        "dropped": dropped,
    }


def _pass_split(s: MosaicSession, lo: int, hi: int, trials: list[int],
                override: int | None) -> dict:
    """⭐ `pass_split` — **the LAST TRIAL OF PASS 1** (166 on 260620d), never 167.

    ⛔ **This WRAPS `core.dataset.detect_timing_split`; it does not fork it.** The mechanism ("where
    did the stage drive all the way back to the origin") is core's, with all of its traps in one
    place. The *name* — and `t33.Config.pass_split`, the consumer — is the mosaic's.

    ⭐ **NEVER A HARD-CODED 166.** t33's literal default is *this dataset's* number.
    """
    if override is not None:
        n1 = sum(1 for t in trials if t <= int(override))
        n2 = len(trials) - n1
        return {"value": int(override), "detected": False,
                "why": f"set by hand to {int(override)} (the last trial of pass 1)",
                "gap_s": None, "median_gap_s": None, "runner_up": None,
                "n_pass1": n1, "n_pass2": n2}

    sp = s.dataset.timing_split(lo, hi, trials)
    j = sp.to_json()
    return {
        "value": j["value"],
        "detected": bool(j["detected"]),
        "why": j["why"],
        "gap_s": j["gap_s"],
        "median_gap_s": j["median_gap_s"],
        "runner_up": j["runner_up"],
        # core counts `n_before` / `n_after`; the mosaic calls the two halves passes.
        "n_pass1": int(j["n_before"]),
        "n_pass2": int(j["n_after"]),
    }


@router.post("/run", response_model=RunDetection)
def post_run(body: RunDetectRequest) -> dict:
    """`POST /api/mosaic/run` — detect the run and the pass split, **or override them.**

    ⭐ **NOT A SESSION RELOAD.** v1 made this a full re-open (5 s, and it invalidated the tone and
    the blank scan) because the run lived *on* the session. It does not any more: this is a pure
    function of the session's inventory, and it costs milliseconds.

    ⚠️ `gaps` is **derived** and is returned with the run, because the caller needs it the moment
    the trial list changes: a "consecutive" pair across a gap is a multi-step stage jump, and the
    serpentine one-axis step prior does **not** hold there. Miss this and the next solve is silently
    poisoned.
    """
    s = _session(body.session_id)
    run = _detect_run(s, body.lo, body.hi)
    run["pass_split"] = _pass_split(s, run["lo"], run["hi"], run["trials"], body.pass_split)
    run["gaps"] = core_dataset.gaps(run["trials"])
    return run


@router.post("/document/rescope", response_model=RescopeResponse)
def post_rescope(body: RescopeRequest) -> dict:
    """`POST /api/mosaic/document/rescope` — ⭐ **the Range step's `Apply`, made to STICK.**

    `POST /run` measures; this one writes. A project opens on every square snapshot the dataset holds,
    and on a real acquisition that includes the stray snapshots taken before the mosaic scan started
    (`1`, `5-7` on 260620d, ahead of the run at `11-348`). Until now `Apply` re-measured the run and
    left them in the document, so they were swept, solved and exported as tiles of a mosaic they were
    never part of. This re-authors the tile set to exactly the trials in range.

    ⛔ **NO DATASET KNOWLEDGE.** The trial list is `_detect_run` over `log.txt` + the per-trial XML
    shape, bounded by the range the USER typed. No number is named here, and nothing is defaulted for
    "his" dataset.
    ⛔ **A DROPPED TRIAL IS NOT AN EXCLUSION.** It does not land in `unusable_tiles` and it does not
    count as a human edit: it was never a tile of this mosaic. `E` remains the only thing that
    excludes.

    🔴 Every surviving tile keeps its position, state and provenance. The reply's `n_placed_removed`
    is the work that was thrown away — the caller confirms **before** calling (the Range step does).
    """
    s = _session(body.session_id)
    run = _detect_run(s, body.lo, body.hi)
    run["pass_split"] = _pass_split(s, run["lo"], run["hi"], run["trials"], body.pass_split)
    run["gaps"] = core_dataset.gaps(run["trials"])

    docmod = _document()
    try:
        doc, info = docmod.rescope(
            _doc(body.doc),
            run["trials"],
            lo=run["lo"],
            hi=run["hi"],
            pass_split=run["pass_split"]["value"],
            # ⭐ the measurement for any trial that has just JOINED the mosaic — the Screen step's
            # cards read it, and the session already holds it (no recompute).
            texture=s.frames.texture(),
            run={"detected": run["detected"], "why": run["why"],
                 "pass_split_detected": run["pass_split"]["detected"],
                 "pass_split_why": run["pass_split"]["why"]},
        )
    except core_document.DocumentError as e:
        raise ApiError(400, "bad_request", str(e)) from e

    # Stamp it, as `/seed` and `/discard-machine` do: the reply is a document the client can adopt
    # and autosave as-is, with its provenance recomputed against the tile set it actually carries.
    return {"doc": docmod.stamp(doc), "run": run, **info}


# =================================================================================================
# gaps — ⭐ THE ONE FUNCTION THE APP MAY IMPORT FROM THE EXCLUSION MODULE
# =================================================================================================
@router.post("/gaps", response_model=GapsResponse)
def post_gaps(body: GapsRequest) -> dict:
    """`POST /api/mosaic/gaps` — a **pure function over a trial list.**

    ⭐ `engine.excluded.gaps()` is the ONLY symbol the app may import from that module — never
    `EXCLUDED` / `BLANK` / `BLURRY` / `usable_trials`. There is no toggle. **This route is the single
    place the app touches it**, it reaches it through `camea.core.dataset.gaps`, and it is called on
    every change to the excluded set.
    """
    return {"gaps": core_dataset.gaps(body.trials)}


# =================================================================================================
# Step 3 · Screen — the blank PROPOSAL
# =================================================================================================
@router.post("/screen/propose", response_model=BlankProposal)
def post_screen_propose(body: BlankProposeRequest) -> dict:
    """`POST /api/mosaic/screen/propose` — ⭐ **IT RECOMMENDS. THE HUMAN TICKS. NOTHING IS
    AUTO-EXCLUDED.**

    The *measurement* is core's (`FrameStore.texture()` — `std(DoG(3,30))`, a property of the frame,
    and free because the matcher's band stack and this measure are the same array). The *policy* —
    "the 2nd percentile of PASS-1 texture" — is the mosaic's, because `pass 1` only exists because
    `pass_split` does. The *decision* is the human's and it lands in the **document**, not here.

    ⚠️⚠️ **ZERO MARGIN AT THE BOUNDARY, AND IT IS THE WHOLE REASON THIS MAY ONLY PROPOSE.**
    Genuinely-blank frames and perfectly good ones **interleave** below the threshold. Measured on
    260620d with the refusal lifted, the four trials the scan named landed **0.24 px**, **0.18 px**,
    **2.07 px** and **679 px** from the human truth. Three of four are ordinary tiles. One of four is
    real. A rule that cannot do better than that does not get to reject anything.

    ❌ **NO BLUR JUDGEMENT. EVER.** Across all 338 snapshots and 15 focus measures the best global
    blur threshold reaches **F1 = 0.37**, and variance-of-Laplacian — the textbook autofocus metric —
    scores **worse than chance**. No slider, no number, nowhere in the UI. Blur is his eye, in the
    sweep, with `E`.
    """
    s = _session(body.session_id)

    known = set(s.frames.trials)
    stray = [t for t in body.trials if t not in known]
    if stray:
        raise ApiError(400, "bad_request",
                       f"not loaded in this session: {stray[:12]}"
                       f"{' …' if len(stray) > 12 else ''}")

    all_texture = s.frames.texture()
    texture = {t: all_texture[t] for t in sorted(body.trials) if t in all_texture}

    ps = body.pass_split
    reference = [texture[t] for t in texture if ps is None or t <= int(ps)]

    if len(reference) >= BLANK_MIN_REFERENCE:
        thr = float(np.percentile(np.asarray(reference, dtype=float), BLANK_PCT))
        src = (f"{BLANK_PCT:g}nd percentile of pass-1 texture (n={len(reference)})" if ps is not None
               else f"{BLANK_PCT:g}nd percentile of the scanned texture (n={len(reference)}, "
                    f"no pass split)")
    else:
        thr = float("nan")
        src = (f"undetermined — only {len(reference)} reference trials "
               f"(need {BLANK_MIN_REFERENCE}). Nothing proposed.")

    finite = math.isfinite(thr)
    proposed = sorted(t for t, v in texture.items() if finite and v < thr)

    warn: str | None = None
    above = [v for v in texture.values() if finite and v >= thr]
    if finite and above and thr > 0:
        margin_pct = 100.0 * (min(above) - thr) / thr
        warn = (f"the nearest kept frame is only {margin_pct:.2f} % above the threshold — good "
                f"frames and blank ones interleave at the boundary. This measure is reliable for "
                f"BLANK and useless for BLUR. It proposes; you decide.")

    return {
        "threshold": round(thr, 2) if finite else None,
        "threshold_source": src,
        "measure": TEXTURE_MEASURE,      # core names the measure. The mosaic only sets the policy.
        "texture": texture,
        "proposed": proposed,
        "n_proposed": len(proposed),
        "n_scanned": len(texture),
        "margin_warning": warn,
    }


# =================================================================================================
# Step 4 · Place — the build
# =================================================================================================
def _validate_config(cfg: dict) -> dict:
    """An unknown knob is a **400**, not a job that fails 200 s in.

    ⭐ **VALIDATE BY CONSTRUCTING A REAL `t33.Config`.** Its `__init__` takes `**kw` and raises
    `TypeError: unknown T33 config knob: 'x'` itself. Do **not** introspect the signature — it is
    literally `(**kw)` — and do **not** hard-code the knob list here: t33 owns it, and a stale copy
    in a router would reject a knob t33 grew or accept one it dropped. (`BuildConfig` is
    `extra="allow"` for exactly this reason.)

    ⛔ `t33` is reached **through `solve`**, which is the only module in the app allowed to import
    it. This router never imports t33. (This is v1's mechanism, verbatim — it reached t33 through
    `engine` for the same reason.)
    """
    t33 = getattr(_solve(), "t33", None)
    Cfg = getattr(t33, "Config", None) if t33 is not None else None
    if Cfg is None:
        return cfg                      # engine not up: let the child raise, and the job fails loudly
    try:
        Cfg(**cfg)
    except TypeError as e:
        raise ApiError(400, "bad_request", str(e)) from e
    return cfg


def _build_trials(s: MosaicSession, want: list[int], pass_split: int) -> list[int]:
    """⭐ **`trials` IS THE DOCUMENT'S ACTIVE LIST, AND IT IS NOT COSMETIC.**

    v1 hard-wired this to the session's whole run, so a user who pressed `E` on a bad tile and then
    took the app's own advice to re-solve got **a re-solve on the identical input**: the excluded
    frame went straight back into the chain, still voting, still carrying its neighbours. The
    exclusion the app invited him to make never reached the solver. **This is the ONLY way a frame
    ever leaves a build.**

    t33 recomputes its own `breaks()` from whatever list it is handed, so passing the reduced list is
    all that is needed — the new gap is then *honoured* rather than assumed away.

    ⛔ The subset is the USER's. This function contributes no exclusions of its own and never will.
    """
    trials = sorted({int(t) for t in want})
    if not trials:
        raise ApiError(400, "bad_request", "trials is empty — there is nothing to solve")

    stray = [t for t in trials if t not in s.frames.row_of]
    if stray:
        raise ApiError(400, "bad_request",
                       f"trials not loaded in this session: {stray[:12]}"
                       f"{' …' if len(stray) > 12 else ''}")

    ps = int(pass_split)
    n1 = sum(1 for t in trials if t <= ps)
    n2 = len(trials) - n1
    if n1 < MIN_PASS1 or n2 < MIN_PASS2:
        raise ApiError(400, "bad_request",
                       f"only {n1} pass-1 and {n2} pass-2 tiles left "
                       f"(need {MIN_PASS1} and {MIN_PASS2}). Un-exclude some, or move the split.")
    return trials


@router.post("/build", response_model=JobRef, status_code=202)
def post_build(body: BuildStartRequest) -> dict:
    """`POST /api/mosaic/build` -> **202 `JobRef`**. Poll `GET /api/jobs/{id}`.

    It runs in a **CHILD PROCESS** and holds the **`gpu` lease** for its whole run. Both are
    forced, not chosen:

    * `t33.place` runs 25 s – 10 min **synchronously**, has **no progress callback of any kind**,
      and has **nothing inside it that checks a flag** — so there is no cooperative cancel to hook.
      `proc.terminate()` is the only cancel that can work. That is the whole reason for the process.
    * The parent may hold ~2 GB of device memory from interactive matching and the child needs ~2 GB
      more. On a 4 GB card the lease is the difference between a build and an OOM — so we also
      **release the parent's context before spawning**.

    `config: null` = t33's shipped **312/312 defaults**, and that is the one-button path.
    ⚠️ `pass_split` is the **DETECTED** value the caller sends, never t33's literal 166.
    """
    s = _session(body.session_id)

    cfg: dict[str, Any] = {}
    if body.config is not None:
        cfg = body.config.model_dump(exclude_none=True, by_alias=True)
    cfg["pass_split"] = int(body.pass_split)
    _validate_config(cfg)

    trials = _build_trials(s, body.trials, cfg["pass_split"])

    cache_dir = str(_cache_dir(s)) if body.use_cache else None

    # The parent's CuPy block pool. A no-op on CPU, and it never raises.
    try:
        from camea.engine import free_gpu
        free_gpu()
    except Exception:  # noqa: BLE001 — never let a housekeeping call refuse a build
        pass

    try:
        job = JOBS.submit_process(
            "build",
            "camea.features.mosaic.solve.build_worker",
            {
                "data_dir": str(s.dataset.path),
                "trials": trials,
                # ⚠️ `pass_split` IS A REQUIRED PARAMETER OF `build_worker`, and it is NOT read out of
                # `config`. Omitting it here raised `TypeError: build_worker() missing 1 required
                # positional argument` **inside the spawned child**, so every build failed ~1 s in
                # with a traceback nobody would have read as a wiring bug. It is passed BOTH ways on
                # purpose: `make_config(config, pass_split=...)` in the child takes this argument, and
                # `cfg["pass_split"]` is what `_validate_config` above already checked against a real
                # `t33.Config`.
                "pass_split": int(cfg["pass_split"]),
                "config": cfg,
                "cache_dir": cache_dir,
            },
            exclusive="gpu",
        )
    except Busy as e:
        raise ApiError(409, "busy", str(e) or "a job already holds the GPU") from e
    return {"job_id": job.job_id, "kind": "build"}


# --- the finished-build register -----------------------------------------------------------------
#
# `core.jobs` has no completion callback, so we lift a finished build's result out of the registry
# lazily, on every read. (SPLIT §1.5 suggests an `on_done` hook on the registry instead — that would
# be the better fix, and it is core's to make.)
#
# ⚠️ This is a **cache of a job result**, not tile state. It holds no positions the client is
# expected to trust and nothing the match endpoints read. See rule 2.
_BUILDS: dict[str, dict] = {}


def _hoist_builds() -> None:
    for j in JOBS.list():                       # newest first
        if j.kind != "build" or j.state != "done" or not j.result:
            continue
        bid = j.result.get("build_id") if isinstance(j.result, dict) else None
        if bid and bid not in _BUILDS:
            _BUILDS[str(bid)] = j.result


@router.get("/builds/{build_id}", response_model=BuildResult)
def get_build(build_id: str) -> dict:
    """`GET /api/mosaic/builds/{build_id}` — a finished build's full result.

    ⚠️ `per_tile` is a **"go look here first" list, not a verdict** — and 🔴 **pass-1 tiles have no
    per-tile confidence at all** (t27's info is aggregate-only), while the worst tile in the shipped
    312/312 build (trial 127, at 9.94 px) **is a pass-1 tile.** The absence of a warning is not a
    clean bill of health, and the UI must say so.
    """
    _hoist_builds()
    r = _BUILDS.get(build_id)
    if r is None:
        raise ApiError(404, "not_found", f"no completed build with id {build_id}")
    return r


@router.post("/seed", response_model=SeedResponse)
def post_seed(body: SeedRequest) -> dict:
    """`POST /api/mosaic/seed` — apply a build to a document. **The SERVER does this, not the JS.**

    🔴 **A RE-SOLVE MUST NOT DESTROY THE HUMAN'S WORK.** `document.seed_from_build` keeps every tile
    that is `anchored` **or** flagged `human` and seeds everything else *around* them, translating
    the build onto the human's field by the **MEDIAN** offset over the protected tiles — a median,
    not a mean, because a tile the human corrected *because the solver was wrong* is precisely an
    outlier, and one 2,969 px correction would drag a mean into nonsense. If none of the human's
    tiles are in the build the two frames cannot be tied together, and the server **refuses to
    seed** rather than guess.

    (v1 reimplemented all of this in `sweep.js` and called `setState` unconditionally on every
    non-excluded tile — so a 150-tile sweep with three catastrophic hand-corrections in it was wiped
    by taking the app's own advice to re-solve, and the autosave then wrote the wiped document over
    the crash-recovery file.)
    """
    _hoist_builds()
    build = _BUILDS.get(body.build_id)
    if build is None:
        raise ApiError(404, "not_found", f"no completed build with id {body.build_id}")

    docmod = _document()
    doc = _doc(body.doc)
    try:
        # ⚠️ `seed_from_build` returns **(doc, info)**, not a single dict. Returning the raw tuple
        # here made FastAPI try to validate a 2-tuple against `SeedResponse` — a 500 on the one route
        # whose whole job is to not destroy the human's work.
        doc, info = docmod.seed_from_build(doc, build)
    except (docmod.SeedRefused, ValueError) as e:  # no protected tile is in the build -> refuse
        raise ApiError(409, "refused", str(e)) from e
    # ⭐ STAMP THE RESPONSE. `seed_from_build` returns a NORMALISED but UNSTAMPED doc, so without this
    # the reply could carry a `build` block while `provenance.independent_of_method` is still true and
    # the warning is absent — the self-contradiction R28 exists to prevent. `stamp()` re-derives the
    # verdict from the document's HISTORY (the build block just added), forcing
    # `independent_of_method: false` + `PROVENANCE_WARNING`. It is the same `stamp()` the export path
    # runs (`features/mosaic/export.as_exported`), and it is idempotent — save/autosave/export re-stamp
    # anyway; this just makes the /seed RESPONSE already honest.
    return {"doc": docmod.stamp(doc), **info}


@router.post("/document/machine-evidence", response_model=MachineEvidenceResponse)
def post_machine_evidence(body: MachineEvidenceRequest) -> dict:
    """⚠️ **DERIVED FROM THE DOCUMENT'S HISTORY, NEVER FROM WHAT IT SAYS ABOUT ITSELF** — a `build`
    block, or a single tile still carrying a `machine` position. `seeded_from` is writable, and
    "Skip — place from scratch" once *erased it* while every tile kept t33's answer.

    🔴 **This project has already destroyed one benchmark exactly this way**
    (`analysis/archive/challenge_2026-07/benchmark/ground_truth/260620d.json` **is T27's own
    output**). Powers the provenance panel — which is a **live warning about current state**, and so
    it stays on the page rather than hiding behind a `?`.
    """
    # The router validates, delegates and shapes the reply — it does not derive provenance. The
    # verdict is a DOCUMENT RULE and lives in `document.machine_evidence_report` (which asks the
    # HISTORY, never `provenance.seeded_from`). (This route called a function of that name before one
    # existed, and 500'd on every load of the panel; the function is now real.)
    return _document().machine_evidence_report(_doc(body.doc))


@router.post("/document/discard-machine", response_model=DiscardMachineResponse)
def post_discard_machine(body: DiscardMachineRequest) -> dict:
    """*"Skip — place by hand"*. 🔴 **IT IS DESTRUCTIVE, OR IT IS NOTHING.**

    If anything in the document came from a machine it discards **every position and the build**.
    Otherwise it launders a machine build into an "independent ground truth": v1 nulled `build`,
    nulled `seeded_from`, set `independent_of_method: true`, deleted the warning — and **did not
    touch a single tile.** Every tile kept t33's position. Score t33 against that and it gets ~100 %
    **by construction.**

    `confirm` is `Literal[True]` in the schema: there is no path through this route by accident.
    """
    # ⚠️ `discard_machine` returns **(doc, info)**, not a single dict — the raw tuple could not
    # validate against `DiscardMachineResponse` and 500'd. Unpack it.
    docmod = _document()
    doc, info = docmod.discard_machine(_doc(body.doc))
    # ⭐ STAMP THE RESPONSE (as `/seed` does). The doc is normalised but unstamped; after a discard
    # there is no machine evidence left, so `stamp()` sets `independent_of_method: true` and drops the
    # warning — an honest, self-consistent reply rather than one carrying whatever the posted
    # provenance happened to claim. Same `stamp()` the export path runs; idempotent.
    return {"doc": docmod.stamp(doc), **info}


# =================================================================================================
# Step 5 · Sweep — ⭐⭐ THE ANCHOR-COMPOSITE PRIMITIVE
# =================================================================================================
def _check_match(s: MosaicSession, target: int, anchors: list[int],
                 positions: dict[int, tuple[float, float]]) -> list[int]:
    """The checks both match routes share. Returns the anchor list as a **sorted set**.

    ⭐ The memo key **IS the anchor set and their positions**, so the client's ORDER must not be able
    to change the answer, and a duplicated anchor must not be able to paste the same tile into the
    composite twice. Normalise here, once, for both routes.
    """
    if target not in s.frames.row_of:
        raise ApiError(400, "bad_request", f"target {target} is not loaded in this session")

    if not anchors:
        raise ApiError(400, "bad_request", "anchors must be a non-empty array of trial numbers")
    if target in anchors:
        raise ApiError(400, "bad_request", f"anchors must not contain the target ({target})")

    unknown = [a for a in anchors if a not in s.frames.row_of]
    if unknown:
        raise ApiError(400, "bad_request", f"anchors not loaded in this session: {unknown[:12]}")

    missing = [a for a in anchors if a not in positions]
    if missing:
        raise ApiError(400, "bad_request", f"positions missing for anchors: {missing[:12]}")

    return sorted(set(anchors))


@router.post("/match/anchor", response_model=MatchResult)
def post_match_anchor(body: MatchAnchorRequest) -> Any:
    """⭐⭐ **THE PRIMITIVE. ONE ENDPOINT, FOUR FEATURES**: place the next tile (`Space`), the ranked
    alternatives (`V`, `1`–`9`), rescue an unplaced tile, and snap a drag (`mode: "local"`).

    *Why a composite is the right primitive and not merely a convenient one:* of 719 genuinely
    overlapping tile PAIRS on this data the exact-NCC argmax is **> 20 px wrong for 38 of them (5 %),
    at scores up to 0.760** — one 0.760 winner is **757 px wrong** and the truth is the runner-up at
    0.677. The **same tile against a composite** scores 0.654 vs 0.416 next-best and lands **1.7 px**
    from the human. **Aperture is everything**, and the anchor field the user is building is a big,
    human-certified one.

    ⛔ **BLANK ⇒ REFUSED, NOT SCORED.** 200, with `candidates: []`, `best: null` and a populated
    `refused`. **There is no `force` flag and there will not be one.** Two blank frames 136 trials
    apart correlate **+0.43 at zero shift** (honest noise floor 0.115) because what they share is
    *fixed-pattern sensor structure*, which does not move with the stage — **they register
    confidently and wrongly.** A blank *anchor*, by contrast, is **dropped from the composite and is
    not fatal**: the rule that made it an error dead-ended the whole app, the moment the user
    anchored the first near-threshold trial the sweep refused **forever**, and it died one tile later.

    ⭐ **A plain `def`, not `async def`** — Starlette runs it in its thread pool, which is what stops
    an in-flight prefetch from blocking the foreground request the user is actually waiting on.
    """
    _need_gpu_free()
    s = _session(body.session_id)
    anchors = _check_match(s, body.target, body.anchors, body.positions)

    if body.mode == "local" and body.near is None:
        raise ApiError(400, "bad_request", "mode 'local' requires `near` — where you dropped the tile")

    # ⚠️ The radius is clamped in the schema (`le=256`), and the **UI must never exceed 128**: the
    # electrode grid repeats every 256 px, so a wide *local* search will confidently lock onto a grid
    # alias. To search wide, use `mode: "global"` — the FFT plus the margin is what survives them.
    res = _solve().match_anchor(
        s.frames,
        body.target,
        anchors,
        dict(body.positions),
        mode=body.mode,
        near=(tuple(body.near) if body.near is not None else None),
        radius=body.radius,
        max_candidates=body.max_candidates,
        refuse=list(body.refuse),
    )
    return res.to_json() if hasattr(res, "to_json") else res


@router.post("/match/score", response_model=ScoreResult)
def post_match_score(body: MatchScoreRequest) -> Any:
    """`POST /api/mosaic/match/score` — *"you dropped it here; what do the pixels say?"*

    One `exact_ncc`, no search (~31 ms). Used live during a drag (debounced), to label the
    alternatives, and to **re-measure a diverted tile's NCC where it actually sits** — because
    `TileRecord.ncc` is defined as the NCC **at the tile's final position**, on every path, and
    writing the rejected alias's score there would attribute it to the position that shipped.

    ⚠️ `ncc` is **`null`** below `exact_ncc`'s overlap floor. The honest answer is *"not
    measurable"* — **never `0.0`**.

    ⭐ Deliberately **NOT** serialised behind an in-flight `match/anchor`: it used to wait out a whole
    match, so the live NCC under the cursor was up to a full match out of date.
    """
    _need_gpu_free()
    s = _session(body.session_id)
    anchors = _check_match(s, body.target, body.anchors, body.positions)

    res = _solve().score_at(
        s.frames,
        body.target,
        anchors,
        dict(body.positions),
        tuple(body.at),
        refuse=list(body.refuse),
    )
    return res.to_json() if hasattr(res, "to_json") else res


# =================================================================================================
# The re-check
# =================================================================================================
def _anchor_field(doc: dict) -> dict[int, tuple[float, float]]:
    """`{trial: (x, y)}` for every **anchored** tile that actually carries a position.

    ⚠️ On disk an anchored tile's `status` is `"anchor"`, not `"anchored"` — and `score.load_gt()`
    keeps every tile whose **`status == "anchor"`**. Read `state` first (it wins if present) and
    fall back to the status spelling, or a document written by the bench is silently empty here.
    """
    out: dict[int, tuple[float, float]] = {}
    for k, t in (doc.get("tiles") or {}).items():
        state = t.get("state") or ("anchored" if t.get("status") == "anchor" else t.get("status"))
        if state != "anchored":
            continue
        x, y = t.get("x"), t.get("y")
        if x is None or y is None:
            continue
        out[int(k)] = (float(x), float(y))
    return out


@router.post("/recheck", response_model=JobRef, status_code=202)
def post_recheck(body: RecheckRequest) -> dict:
    """`POST /api/mosaic/recheck` -> **202 `JobRef`**. It is N x ~1 s, so it never blocks.

    🔴 **THE RE-CHECK IS GLOBAL, AND IT IS ALLOWED TO SAY NO.** It **never moves a tile** — it only
    measures it. Anything that disagrees with where the tile sits by more than `tolerance_px`
    **STAYS FLAGGED**, and the caller clears only the flags it is told it may clear.

    ⚠️ **IT MUST BE GLOBAL, AND THIS IS WHY.** v1 fired a *local* match (±64 px) and then cleared
    `stale` unconditionally. But a tile knocked off by a moved anchor is off by **hundreds** of px —
    failure on this data is **binary**, sub-pixel-right or wildly wrong — so a ±64 px window is
    *structurally blind to the one error the panel exists for*. Measured: a tile **380 px** from the
    truth re-checked locally to `ncc -0.0678`, was not moved, and had its flag **cleared** — the loud
    panel disappeared, the tile stayed 380 px wrong, and a negative NCC went into the document as its
    evidence.
    """
    _need_gpu_free()
    s = _session(body.session_id)
    doc = _doc(body.doc)

    field = _anchor_field(doc)
    if not field:
        raise ApiError(409, "refused",
                       "nothing is anchored — there is no reference field to re-check against")

    tiles = doc.get("tiles") or {}
    if body.trials is not None:
        targets = sorted({int(t) for t in body.trials})
    else:
        targets = sorted(int(k) for k, t in tiles.items() if t.get("stale"))

    # An anchor is the human's own certification. It is not re-judged by a machine.
    targets = [t for t in targets if t not in field and t in s.frames.row_of]

    refuse = list(((doc.get("blank_scan") or {}).get("blank")) or [])
    tol = float(body.tolerance_px)
    solve = _solve()

    def fn(report, cancel) -> dict:
        rows: list[dict] = []
        cleared: list[int] = []
        n = len(targets)
        for i, t in enumerate(targets):
            check_cancelled(cancel, "recheck")
            report(Progress(phase="recheck", phase_index=i + 1, n_phases=max(1, n),
                            pct=(100.0 * i / n if n else 100.0),
                            message=f"trial {t} ({i + 1}/{n})"))

            anchors = sorted(a for a in field if a != t)
            res = solve.match_anchor(s.frames, t, anchors, dict(field),
                                     mode="global", refuse=refuse)
            r = res.to_json() if hasattr(res, "to_json") else res

            tile = tiles.get(str(t)) or tiles.get(t) or {}
            at = (float(tile.get("x") or 0.0), float(tile.get("y") or 0.0))
            best = r.get("best")

            if best is None:
                # Refused (a blank target), or nothing correlated. **It stays flagged.** "I could not
                # measure it" is not "it is fine" — and the whole point of this panel is the tile
                # nobody looked at.
                rows.append({"trial": t, "at": at, "best": None, "disagree_px": None,
                             "ncc": None, "margin": r.get("margin"), "still_stale": True})
                continue

            bx, by = float(best["x"]), float(best["y"])
            d = math.hypot(bx - at[0], by - at[1])
            still = d > tol
            rows.append({"trial": t, "at": at, "best": (bx, by), "disagree_px": round(d, 2),
                         "ncc": best.get("ncc"), "margin": r.get("margin"), "still_stale": still})
            if not still:
                cleared.append(t)

        return {
            "kind": "recheck",
            "n_checked": len(targets),
            "cleared": cleared,
            "disagree": [r for r in rows if r["still_stale"]],
        }

    # ⭐ HOLDS THE `gpu` LEASE, exactly as `build` and `export` do. The recheck fires a GPU
    # `match_anchor` per target, so without the lease a build could start concurrently and defeat the
    # OOM protection the lease exists for (parent ~2 GB + a spawned build ~2 GB on a 4 GB card). The
    # interactive `_need_gpu_free()` above only refuses to START while a lease is held; the lease is
    # what stops the reverse race — a build starting mid-recheck.
    try:
        job = JOBS.submit_thread("recheck", fn, exclusive="gpu")
    except Busy as e:
        raise ApiError(409, "busy", str(e) or "a job already holds the GPU") from e
    return {"job_id": job.job_id, "kind": "recheck"}


@router.post("/recompute", response_model=JobRef, status_code=202)
def post_recompute(body: RecomputeRequest) -> dict:
    """`POST /api/mosaic/recompute` -> **202 `JobRef`**. ⭐ **THE TOOL THE USER REACHES FOR.**

    Freeze the tiles the human has anchored and re-place every other tile against their combined
    composite — then he anchors more and recomputes again. It is `recheck`'s per-target
    `match_anchor(global)` loop (same `gpu` lease, same progress/cancel, N × ~1 s so it never blocks),
    but it **writes** the answer instead of only measuring it.

    🔴 **It never moves an `anchored`, `human`, or `excluded` tile** — those are the frozen reference
    and the human's own work (the re-solve-wipes-the-sweep bug `seed_from_build` exists to prevent).
    Every placed tile lands `unverified` + `machine`; **nothing is auto-anchored** (I3), and the
    machine fingerprint keeps provenance honest. A target with no measurable overlap against the
    anchors is **left untouched** — its previous placement stands; anchor a neighbour and recompute.

    ⚡ The anchor set is FIXED across all targets, so `solve`'s incremental composite cache builds the
    reference composite **once** and reuses it for every match.
    """
    _need_gpu_free()
    s = _session(body.session_id)
    docmod = _document()
    doc = _doc(body.doc)

    field = _anchor_field(doc)
    if not field:
        raise ApiError(
            409, "refused",
            "nothing is anchored — there is no ground truth to place the rest against. Anchor a few "
            "tiles you trust, then recompute.")

    tiles = doc.get("tiles") or {}

    def _is_target(k: str | int, t: dict) -> bool:
        trial = int(k)
        if trial in field:                              # an anchor -> the frozen reference
            return False
        if t.get("human"):                              # a hand placement -> his own work
            return False
        state = t.get("state") or ("anchored" if t.get("status") == "anchor" else t.get("status"))
        if state == "excluded":                         # he ruled it out
            return False
        return trial in s.frames.row_of                 # loaded in this session

    if body.trials is not None:
        want = {int(t) for t in body.trials}
        targets = sorted(int(k) for k, t in tiles.items() if int(k) in want and _is_target(k, t))
    else:
        targets = sorted(int(k) for k, t in tiles.items() if _is_target(k, t))

    refuse = list(((doc.get("blank_scan") or {}).get("blank")) or [])
    anchors = sorted(field)
    solve = _solve()

    def fn(report, cancel) -> dict:
        placed: dict[int, tuple[float, float]] = {}
        n_unmeasurable = 0
        n = len(targets)
        for i, t in enumerate(targets):
            check_cancelled(cancel, "recompute")
            report(Progress(phase="recompute", phase_index=i + 1, n_phases=max(1, n),
                            pct=(100.0 * i / n if n else 100.0),
                            message=f"trial {t} ({i + 1}/{n})"))

            res = solve.match_anchor(s.frames, t, anchors, dict(field),
                                     mode="global", refuse=refuse)
            r = res.to_json() if hasattr(res, "to_json") else res
            best = r.get("best")
            if best is None:
                # Refused (a blank target), or nothing correlated against the anchors. Leave the tile
                # where it was — "I could not measure it" is not "move it to nowhere".
                n_unmeasurable += 1
                continue
            placed[t] = (float(best["x"]), float(best["y"]))

        new_doc, info = docmod.place_against_anchors(doc, placed)
        # ⭐ STAMP THE RESULT — like /seed. `place_against_anchors` returns a normalised but UNSTAMPED
        # doc; every re-placed tile now carries `machine`, so `stamp()` forces
        # `independent_of_method: false` + the warning. The reply is already honest.
        return {
            "kind": "recompute",
            "doc": docmod.stamp(new_doc),
            "n_placed": int(info["n_placed"]),
            "n_unmeasurable": int(n_unmeasurable),
            "n_reference": len(anchors),
        }

    # ⭐ HOLDS THE `gpu` LEASE, exactly as `build`, `export` and `recheck` do — it fires a GPU
    # `match_anchor` per target.
    try:
        job = JOBS.submit_thread("recompute", fn, exclusive="gpu")
    except Busy as e:
        raise ApiError(409, "busy", str(e) or "a job already holds the GPU") from e
    return {"job_id": job.job_id, "kind": "recompute"}


# =================================================================================================
# Step 6 · Mosaic — export + QC
# =================================================================================================
@router.post("/export", response_model=JobRef, status_code=202)
def post_export(body: ExportRequest) -> dict:
    """`POST /api/mosaic/export` -> **202 `JobRef`**. Holds the `gpu` lease.

    ⭐⭐ **TIFF AND PNG ARE TWO DIFFERENT RENDERS**, and `flat` decides what the pixels *are*:
    `flat=True` is a *picture* (per-tile gain); `flat=False` is **raw camera counts** = the TIFF. The
    TIFF was once rendered `flat=True` while its header said RAW — trial 11's median went 2111 ->
    3435 (x1.63).

    ⚠️⚠️ **THE COVERAGE MASK IS MANDATORY, NOT AN OPTION.** 13.1 % of the canvas is background
    encoded as exactly `0.0`, indistinguishable from a legitimately black pixel, and a TIFF has **no
    alpha channel**. Without the sidecar, "empty" and "black" merge forever. Asking for `tiff`
    implies `coverage`; the exporter writes it either way.

    🔴 The export describes the document **AS EXPORTED** (the *stamped* one), never as posted. A
    laundered doc once produced a GT JSON saying "NOT AN INDEPENDENT GROUND TRUTH" beside a TIFF
    header saying "hand-placed from scratch".
    """
    s = _session(body.session_id)
    doc = _doc(body.doc)

    # ⭐ **THE PROJECT'S OWN `outputs/` (R44)** — the user is not asked where this goes, and there is
    # no `dir` on the wire to ask with. He browses and copies out what he wants afterwards
    # (`GET /api/projects/{id}/outputs`), which is the only door to a project's files.
    #
    # ⛔ `refuse_write` still runs. The store cannot be inside a dataset, but this guard has exactly
    # one implementation and every write in the app goes through it; skipping it "because we know the
    # path is safe" is how v1 ended up with three copies that had drifted apart.
    out = _outputs_dir(str(doc.get("id") or ""))
    try:
        refuse_write(out, dataset_dir=s.dataset.path)
    except DatasetIsReadOnly as e:
        raise ApiError(409, "refused", str(e)) from e
    try:
        basename = safe_basename(body.basename or s.dataset.name)
    except ValueError as e:
        raise ApiError(400, "bad_request", str(e)) from e

    try:
        out.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise ApiError(500, "io_error", f"cannot create {out}: {e}") from e

    outputs = [str(o) for o in body.outputs]
    export = _export()

    def fn(report, cancel) -> dict:
        return export.export_all(
            s.frames,
            s.dataset,
            doc,
            out,
            basename,
            outputs,
            render_mode=body.render_mode,
            include_unverified=body.include_unverified,
            um_per_px=body.um_per_px,     # 📏 PIXELS ONLY unless the user typed a number in.
            report=report_adapter(report),
            cancel=cancel,
        )

    try:
        job = JOBS.submit_thread("export", fn, exclusive="gpu")
    except Busy as e:
        raise ApiError(409, "busy", str(e) or "a job already holds the GPU") from e
    return {"job_id": job.job_id, "kind": "export"}


@router.post("/qc", response_model=QcReport)
def post_qc(body: QcRequest) -> dict:
    """`POST /api/mosaic/qc` — what the human did vs what the machine said.

    ⭐ **EVERY NUMBER STATES ITS DENOMINATOR**, and the denominator is the document's own `excluded`
    set and nothing else — the app has no list of its own. (A percentage without one is how the
    182-vs-156 confusion started.)

    ⚠️ `diverted_to_solver` is counted **separately and named next to the number it contaminates**: a
    diverted tile *is* sitting exactly on the machine's position, so it lands inside
    `accepted_unchanged` and reads as agreement. It is not. The app never gave the matcher a vote
    there. In the defer flow this can be **302 of 311 tiles**.
    """
    # The router delegates. `document.qc_report` returns the JSON report (it is a thin delegation to
    # the exporter, which owns the computation so it exists in exactly one place — the router does not
    # know, and must not, that the numbers are assembled next to the pixels).
    return _document().qc_report(_doc(body.doc))


# =================================================================================================
# Step 7 · Electrodes — the grid identity of the BUILT mosaic (2026-08-11)
# =================================================================================================
@router.post("/electrodes/map", response_model=JobRef, status_code=202)
def post_electrodes_map(body: ElectrodeMapRequest) -> dict:
    """`POST /api/mosaic/electrodes/map` -> **202 `JobRef`**. Optional post-build stage: render
    the placed tiles (the export's own compositor) and fit the electrode lattice — pitch,
    rotation and phase MEASURED from this mosaic, never assumed (no dataset knowledge).

    ⭐ Files land in the project's `outputs/` (R44), `<name>-electrodes.json/.csv`; the job result
    carries the summary block for the CLIENT to merge into its document and save (this feature's
    document is client-owned, like export and unlike the videomosaic build).

    ⭐ `array_coverage` is HIS declaration (R45.8), made before the button is even enabled:
    `"full"` holds the fit to the MaxOne/MaxTwo's 220 × 120 (a near miss corrected and reported,
    a far miss refused by the fitter); `"partial"` enforces only the 17.5 µm scale and leaves
    `1-1` meaning the top-left of the IMAGED REGION. Defaulted `"partial"` here so an older
    client that does not send it cannot accidentally claim a whole chip.

    Holds the `gpu` lease: the render walks the same frame store the export does."""
    s = _session(body.session_id)
    doc = _doc(body.doc)

    if not _document().positions(doc, include_unverified=body.include_unverified):
        raise ApiError(409, "refused",
                       "nothing is placed yet — build the mosaic before mapping electrodes")

    out = _outputs_dir(str(doc.get("id") or ""))
    try:
        refuse_write(out, dataset_dir=s.dataset.path)
    except DatasetIsReadOnly as e:
        raise ApiError(409, "refused", str(e)) from e
    try:
        basename = safe_basename(str(doc.get("name") or "") or s.dataset.name)
    except ValueError:
        basename = safe_basename(str(doc.get("id") or "electrodes"))
    try:
        out.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise ApiError(500, "io_error", f"cannot create {out}: {e}") from e

    analysis_id = str(doc.get("id") or "")

    def fn(report, cancel) -> dict:
        from . import electrodes  # noqa: PLC0415
        result = electrodes.map_electrodes(
            s.frames, doc, out, basename,
            include_unverified=body.include_unverified,
            array_coverage=body.array_coverage,
            report=report, cancel=cancel)
        return {"kind": "electrode_map", "analysis_id": analysis_id, **result}

    try:
        job = JOBS.submit_thread("electrode_map", fn, exclusive="gpu")
    except Busy as e:
        raise ApiError(409, "busy", str(e) or "a job already holds the GPU") from e
    return {"job_id": job.job_id, "kind": "electrode_map"}


@router.get("/electrodes/{analysis_id}", response_model=ElectrodeMapPayload)
def get_electrodes(analysis_id: str) -> dict:
    """The full electrode map of a project, plus `stale` — computed against the SAVED document's
    current tile positions, so an edited/recomputed mosaic says "re-run" instead of silently
    highlighting drifted centres. (Unsaved client edits are the client's own staleness to track.)"""
    from camea.core import electrodegrid  # noqa: PLC0415
    from . import electrodes  # noqa: PLC0415

    out = _outputs_dir(analysis_id)
    doc: dict = {}
    try:
        loaded, _ = core_document.load_analysis(_PROJECTS_PROVIDER(), analysis_id)
        doc = loaded
    except Exception:  # noqa: BLE001 — no readable document: the file fallback still serves
        pass

    payload = electrodegrid.load_map_file(out, electrodes.recorded_map_name(doc))
    if payload is None:
        raise ApiError(404, "not_found",
                       "this project has no electrode map yet — run Map electrodes first")

    stale = False
    if doc.get("tiles"):
        now = electrodes.positions_stamp(
            doc, include_unverified=bool(payload.get("include_unverified", True)))
        stale = now != str(payload.get("source_stamp") or "")
    return {**payload, "stale": stale}


__all__ = ["router", "ApiError", "MosaicSession", "set_session_provider", "set_store",
           "TILE", "BLANK_PCT"]
