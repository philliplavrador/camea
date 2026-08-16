"""export.py — ⭐ **THE DELIVERABLES.** The mosaic feature's file formats, and nothing else.

Ported from `archive/app-v1/backend/export.py` (724 lines) + `engine.render_mosaic`
(`archive/app-v1/backend/engine.py:1548`) + the three document serialisers (`project.to_gt:1143`,
`project.to_positions_csv:1157`, `project.qc_report:1176`).

    <basename>.tif             ⭐ THE REAL DELIVERABLE. 16-bit, RAW CAMERA COUNTS.
    <basename>_coverage.png    ⚠️⚠️ MANDATORY. Not an option. See `write_tiff`.
    <basename>.png             the display picture — flat-fielded, ONE global tone window.
    <basename>_positions.csv   header EXACTLY `trial,x,y,state`.
    <basename>_gt.json         the ground truth, stamped `independent_of_method: false`.
    <basename>_qc.json/.md     what the human did vs what the machine said.

Seven files. `ExportResult` says seven.

---------------------------------------------------------------------------------------------------
WHAT THIS MODULE OWNS, AND WHAT IT DELEGATES
---------------------------------------------------------------------------------------------------
It OWNS the **file formats**: the TIFF and its coverage sidecar, the display PNG, the CSV, the GT
JSON, the QC report, the physical-scale policy, and the two renders that feed the first two.

It DELEGATES everything else, because each of those things has exactly ONE implementation and this
file is not it:

    core.document       normalise -> stamp -> validate; `jsonable`; `PROVENANCE_WARNING`.
    core.workspace      WHERE it lands: the one write guard, the one atomic writer, `safe_basename`.
    core.frames         the pixels, the vignette, the ONE global tone window, `frame_note`.
    core.jobs           `Cancelled`, `Progress`, the cancel poll.
    mosaic.document     the tile state machine (`state_of`), `active_trials`, `is_build_stale`.
    engine.render       the compositor. Byte-identical to the one that produced 312/312.

⛔ **`score.robust_align` IS NOT REIMPLEMENTED ANYWHERE IN THIS FILE.** A reimplementation with a
different tie-break scored the same positions **152/156** where the canonical one gives **155/156**.
The exporter does not align and does not score: it writes the document, and the benchmark scorer
(`tests/guard/score.py`) imports its own `robust_align` when somebody scores it. ⛔ And **never** score a document this app
produced against the method that seeded it — that is 100 % by construction, and it is how this
project already destroyed one benchmark.

---------------------------------------------------------------------------------------------------
⛔ EXPORTS GO TO THE WORKSPACE. NEVER TO THE DATASET.
---------------------------------------------------------------------------------------------------
`workspace.refuse_write()` is the ONE guard (v1 had three — `project._refuse_data_dir`,
`server._refuse_data_dir` and this file's own `_guard_out_dir` — and they had already drifted; one
of them read a `DATA_DIR` constant out of the *exclusion* module, i.e. dataset knowledge sitting in
a path guard). It refuses `data/`, the open dataset's own directory, and **any** raw acquisition
folder on the way up, recognised by its shape rather than its name.

`export_to_analysis()` puts the files in `<workspace>/analyses/<id>/outputs/`, which is where an
analysis's outputs belong.

---------------------------------------------------------------------------------------------------
⛔ NO DATASET KNOWLEDGE
---------------------------------------------------------------------------------------------------
No trial number is special here. Every count in the QC report is over **the document's own excluded
set and nothing else** — the app has no list of its own. (⚠️ `qc.json`'s denominator key is
`not_excluded`, renamed from v1's `usable_trials`, which collided character-for-character with the
one symbol the standing ruling forbids the app to import.)
"""

from __future__ import annotations

import contextlib
import io
import re
import time
import warnings
from pathlib import Path
from typing import Any, Callable

import numpy as np

import camea
from camea.core import jobs, workspace
from camea.core.document import PROVENANCE_WARNING  # ⭐ re-exported. NEVER paraphrased.
from camea.core.document import iso_now, jsonable, machine_evidence, normalise, stamp, validate
from camea.core.frames import FrameStore, flat_correct, tone_lohi
from camea.core.jobs import Progress

# 🔴 v1 had TWO `_state_of`s (`project.py:186` and `export.py:133`) and **THEY DISAGREED**: export's
# returned `str(status)` for an unknown status, so a bench-written GT row with `status: "region"`
# became state `"region"` — in neither `{anchored, unverified}` — and the render then **silently
# dropped the tile**. project's maps the same row to `unverified`.
#
# ⇒ This module keeps **NO COPY of the state machine**, not even a "compatible" one: a compatible
# copy is exactly what the last one was. Importing `mosaic.document` is also what REGISTERS the
# feature's hooks with `core.document`, which is how `stamp()` derives the provenance verdict.
from camea.legacy.mosaic.document import (
    MOVED_EPS,
    PLACED_STATES,
    STATES,
    active_trials,
    is_build_stale,
    state_of,
    tiles_of,
)

__all__ = [
    "OUTPUT_KINDS",
    "DEFAULT_OUTPUTS",
    "RENDER_MODES",
    "PROVENANCE_WARNING",
    "ExportError",
    # the job
    "export_all",
    "export_to_analysis",
    # the document -> text serialisers
    "as_exported",
    "to_gt",
    "to_positions_csv",
    "qc_report",
    "render_positions",
    # the writers
    "write_tiff",
    "write_coverage",
    "write_png",
    "write_positions",
    "write_gt",
    "write_qc",
    # the pixels
    "render_mosaic",
    "coverage_mask",
    # policy
    "scale_metadata",
]


#: Every kind `POST /api/mosaic/export` accepts (`api.schemas.ExportKind`).
#: ⚠️ **`coverage` is NOT optional.** Asking for `tiff` writes it either way — it is listed here
#: only because a caller may legitimately want the mask *on its own* (it is pure geometry and costs
#: nothing: no pixel is read for it).
OUTPUT_KINDS: tuple[str, ...] = ("tiff", "coverage", "png", "positions", "gt", "qc")

#: `api.schemas.DEFAULT_OUTPUTS`. `coverage` is absent because `tiff` implies it.
DEFAULT_OUTPUTS: tuple[str, ...] = ("tiff", "png", "positions", "gt", "qc")

#: ⏱️ mode -> seconds per render (CPU, 312 frames in RAM). **feather is the default and the only
#: interactive one**, and the spread is the reason the export's bar has to be weighted at all: an
#: `alpha` render is **67x** a `feather` one, so `idx / n_phases` cannot describe both (R48.5).
#: The measurement is in `render_mosaic`'s docstring; these are the same three numbers, and they are
#: written down ONCE — `_export_steps` reads them, and `RENDER_MODES` is their keys.
_RENDER_COST: dict[str, float] = {"feather": 1.11, "median": 41.7, "alpha": 74.0}

RENDER_MODES: tuple[str, ...] = tuple(_RENDER_COST)


class ExportError(Exception):
    """Anything this module refuses to write. -> HTTP 400 `bad_request`."""


def _tiles(doc: dict) -> dict[int, dict]:
    """`tiles_of`, keyed by `int`. (JSON object keys are decimal strings; the trials are ints.)"""
    return {int(k): v for k, v in tiles_of(doc).items() if isinstance(v, dict)}


def _margin_thin() -> float:
    """The thin-margin threshold, from the ONE module that owns it.

    ⚠️ v1 had this number in **three** places (`__init__.THIN_MARGIN`, `engine.MARGIN_THIN`, and a
    bare literal `< 0.10` inside `project.qc_report`). A QC report that flags a different set of
    tiles from the one the matcher warned about is worse than no report. It is `solve.MARGIN_THIN`,
    and it is imported.

    A thin margin (best-minus-second NCC) is **the signature of a surviving grid alias** — the
    electrode grid repeats every 256 px. The shipped 312/312 build's worst run margin is 0.081
    against a ~0.47 typical.
    """
    from camea.legacy.mosaic.solve import MARGIN_THIN  # noqa: PLC0415 — see the docstring

    return float(MARGIN_THIN)


# =================================================================================================
# The document, AS EXPORTED
# =================================================================================================
def as_exported(doc: dict, app_version: str | None = None) -> tuple[dict, list[str]]:
    """-> `(stamped_doc, problems)`. **Every writer below describes THIS document, not the posted one.**

    🔴 **THE BUG THIS EXISTS TO PREVENT.** `_tiff_description` used to read the RAW posted provenance
    block. A document that had been laundered — `build` nulled, `seeded_from` nulled,
    `independent_of_method` flipped to true, the warning deleted, **and not one tile moved** —
    therefore produced a GT JSON that correctly said *"NOT AN INDEPENDENT GROUND TRUTH"* beside a
    TIFF whose header cheerfully said *"hand-placed from scratch; no build seeded it"*. The header
    lied, on precisely the path that has already destroyed one benchmark in this project.

    `stamp()` re-derives the verdict from the document's **HISTORY** (`core.document.stamp` ->
    `machine_evidence` -> the feature's hook), so a hand-edited provenance block gets its
    `independent_of_method: false` and its `PROVENANCE_WARNING` put **back**.

    ⚠️ **The problems are REPORTED, never silently repaired and never fatal.** Refusing to write
    somebody's afternoon of work over a derived field would be worse than writing it with a warning.
    They land in the job result and in the QC report. (Validating the *posted* doc instead would
    report every field the export is about to fix — origin not yet at (0,0), gaps not yet recomputed
    — which is noise. What survives normalisation is a REAL problem.)

    ⛔ **IT IS UNCONDITIONAL, AND EVERY PUBLIC SERIALISER IN THIS FILE GOES THROUGH IT.** There is no
    "the caller already stamped it" fast path, and there must never be one: an `is it stamped?`
    heuristic is a hole shaped exactly like the laundering bug above. Stamping a stamped document is
    idempotent — it costs a deep copy and it makes an unstamped artefact **impossible to produce
    from this module**.
    """
    out = stamp(normalise(doc), app_version=app_version)
    return out, validate(out)


def to_gt(doc: dict, app_version: str | None = None) -> dict:
    """The document -> a ground-truth JSON that `tests/guard/score.py` scores **unchanged**.

    `score.load_gt()` keeps ONLY `status == "anchor"` rows with a non-null x/y (so `unverified` tiles
    correctly do not inflate the denominator) and falls back to `tolerance_px.region_default` for a
    missing per-tile `r`. Every app-only key is left in place — the scorer ignores them.
    """
    return as_exported(doc, app_version)[0]


def to_positions_csv(doc: dict, include_unverified: bool = True,
                     app_version: str | None = None) -> str:
    """The document -> `positions.csv`. Header **EXACTLY**::

        trial,x,y,state

    The first three names are what `score.load_positions` reads with a `csv.DictReader`. Do not
    rename them, do not reorder them, do not add a column before them.

    `excluded` and `unplaced` are omitted — they have no position, and that is the invariant the
    whole state machine rests on. `include_unverified` mirrors the render flag, so the csv describes
    what was actually exported.

    ⚠️ It runs `as_exported()` itself: `normalise()` is what pins `origin_trial` at exactly (0, 0),
    and that is what makes these numbers directly comparable with `analysis/ground_truth/`.
    """
    doc = to_gt(doc, app_version)
    rows = ["trial,x,y,state"]
    for t, tile in sorted(_tiles(doc).items()):
        st = state_of(tile)
        if st == "anchored" or (st == "unverified" and include_unverified):
            x, y = tile.get("x"), tile.get("y")
            if x is None or y is None:
                continue  # a placed state with no position: validate() reports it
            rows.append(f"{t},{float(x):.4f},{float(y):.4f},{st}")
    return "\n".join(rows) + "\n"


def render_positions(doc: dict, include_unverified: bool = True) -> dict[int, tuple[float, float]]:
    """`{trial: (x, y)}` for every tile that MAY be rendered. **World TOP-LEFT corners, not centres.**

    `anchored` **always**; `unverified` **iff** `include_unverified`. `excluded` and `unplaced` are
    **never** rendered — they have no position, and that is the invariant the whole state machine
    rests on.

    ⇒ It is `document.positions()`. There is no second one: *which tiles have a position* is the
    document's sentence, not the exporter's, and v1's second opinion on it silently dropped tiles.

    (R9b: deferring with `Space` keeps the solver's position and leaves the tile `unverified` — it is
    simply not drawn in the sweep. **Deferring must never destroy tissue**, and `include_unverified`
    is how those tiles still reach the final image.)
    """
    from camea.legacy.mosaic.document import positions  # noqa: PLC0415 — one implementation

    return positions(doc, include_unverified=include_unverified)


# =================================================================================================
# ⏱️ THE SPAN TABLE THE EXPORT'S BAR IS WEIGHTED BY (R48.5)
# =================================================================================================
#
# 🔴 **`pct` MUST BE OVERALL, ACROSS THE WHOLE EXPORT.** It was not: the render ran its own 0 -> 100
# and the first write then emitted `(idx - 0.5) / n_phases`, so on a TIFF + PNG export the bar filled
# twice, snapped backwards, and any ETA taken off it counted *up* through the render.
#
# The pieces of an export are nowhere near equal, which is why an unweighted `idx / n_phases` cannot
# describe them: an `alpha` render is 67x a `feather` one, while `positions.csv` is a few hundred
# bytes of text. So each step declares a cost, and the spans are the running sum normalised to 0-100
# — `features/videomosaic/pipeline._SPAN` written at run time rather than by hand, because an
# export's steps depend on what was asked for and on the render mode.
#
# Units are arbitrary but SHARED — only the ratios matter, so this needs to be right to about a
# factor of two, not to the millisecond.

#: Per WRITE. Sized off what each file actually *is* — a 78 MB uint16 TIFF (written, re-read and
#: atomically replaced) and its 39 Mpx PNG sidecar against a few KB of text — rather than off a
#: stopwatch, which is why they are round. Anything unlisted falls back to the cheapest.
_WRITE_COST = {"tiff": 4.0, "png": 2.0, "coverage": 1.0, "positions": 0.05, "gt": 0.05, "qc": 0.1}

#: The pure-geometry coverage path (`coverage_mask`) reads no pixel at all — it is the union of the
#: tile rectangles out of `render._canvas`. It still gets a step so the bar is not simply flat there.
_GEOMETRY_COST = 0.2


def _export_steps(kinds: list[str], render_mode: str, needs_pixels: bool) -> list[tuple[str, float]]:
    """The export's work, in the order it happens, as `[(step, cost), …]`.

    ⚠️ A render is paid **once per render, not once per export** — asking for both the TIFF and the
    PNG is two renders, because they are two different sets of pixels (`export_all`'s docstring says
    why, and it cost a x1.63 photometry bug to learn).
    """
    steps: list[tuple[str, float]] = []
    if needs_pixels:
        cost = _RENDER_COST.get(render_mode, min(_RENDER_COST.values()))
        steps += [(f"render:{k}", cost) for k in ("png", "tiff") if k in kinds]
    elif "coverage" in kinds:
        steps.append(("render:mask", _GEOMETRY_COST))
    return steps + [(k, _WRITE_COST.get(k, 0.05)) for k in kinds]


def _spans(steps: list[tuple[str, float]]) -> dict[str, tuple[float, float]]:
    """`[(step, cost), …]` in execution order -> `{step: (lo_pct, hi_pct)}`, the running sum
    normalised to 0-100."""
    total = sum(c for _, c in steps) or 1.0
    out: dict[str, tuple[float, float]] = {}
    acc = 0.0
    for key, cost in steps:
        lo = 100.0 * acc / total
        acc += cost
        out[key] = (lo, 100.0 * acc / total)
    return out


# =================================================================================================
# THE JOB
# =================================================================================================
def export_all(
    frames: FrameStore,
    dataset: Any,
    doc: dict,
    out_dir: str | Path,
    basename: str,
    outputs: list[str] | tuple[str, ...] | None = None,
    render_mode: str = "feather",
    include_unverified: bool = True,
    um_per_px: float | None = None,
    report: Callable[[Progress], None] | None = None,
    cancel: Any = None,
    app_version: str | None = None,
) -> dict:
    """The export job -> `api.schemas.ExportResult`.

    `jobs.JOBS.submit_thread(..., exclusive="gpu")`. It polls `cancel` between outputs and inside the
    render, so the user can stop a 74 s alpha render.

    `frames` is the open `core.frames.FrameStore` (the pixels, the ONE global tone window, and
    `frame_note` — what the reader ACTUALLY did to them). `dataset` is the `core.dataset.Dataset` it
    came from; it is named explicitly, and not dug out of `doc["data_dir"]`, because it is what the
    write guard refuses to write *into*. ⛔ **A DATASET IS RAW AND IS NEVER WRITTEN TO.** May be
    `None` only when there is no open dataset (a document-only export in a test).

    ⭐⭐ **TIFF AND PNG ARE TWO DIFFERENT RENDERS, AND CONFLATING THEM WAS A REAL BUG.**

      * the **PNG** -> `flat=True`: vignette-corrected **and per-tile exposure-normalised** onto the
        session `level`. That per-tile gain is what makes every tile agree in brightness, which is
        what makes the ONE global tone window (and Difference mode) mean anything. **It is a
        PICTURE.**
      * the **TIFF** -> `flat=False`: **RAW CAMERA COUNTS**, exactly as its own ImageDescription has
        always claimed. **It is a MEASUREMENT.**

    🔴 Before the fix, both came from the `flat=True` render while the TIFF's header said
    `pixels=RAW CAMERA COUNTS`. Measured: trial 11's median **2111 -> 3435 (x1.63)**, trial 16's
    2702 -> 3528 (x1.31). A biologist doing photometry in Fiji was reading exposure-normalised
    numbers out of a file that swore they were raw — and a per-tile gain is precisely the operation
    this project forbids everywhere else. Cost of doing it right: one extra render, only when both
    are asked for (feather +1.1 s).
    """
    t0 = time.time()

    kinds = list(dict.fromkeys(outputs if outputs is not None else DEFAULT_OUTPUTS))  # de-dup, order
    bad = [k for k in kinds if k not in OUTPUT_KINDS]
    if bad:
        raise ExportError(f"unknown output kind(s): {bad!r}; expected a subset of {OUTPUT_KINDS}")
    if not kinds:
        raise ExportError("nothing requested: `outputs` is empty")
    if render_mode not in RENDER_MODES:
        raise ExportError(f"unknown render_mode {render_mode!r} (expected {'|'.join(RENDER_MODES)})")

    # ⚠️⚠️ ONE coverage file, and asking for the TIFF is what asks for it. `write_tiff` ALWAYS emits
    # the sidecar — it is not optional and there is no flag that turns it off — so a caller who names
    # both gets one file, not two. (`coverage` on its own is still legal: it is pure geometry.)
    if "tiff" in kinds and "coverage" in kinds:
        kinds = [k for k in kinds if k != "coverage"]

    basename = workspace.safe_basename(basename)

    # ⛔ THE ONE WRITE GUARD. `data/`, the open dataset's directory, and any raw acquisition folder
    # on the way up — recognised by its SHAPE (log.txt + NNN.xml), never by its name. So an export
    # typed into an acquisition the app was never told about is refused too.
    ds_dir = getattr(dataset, "path", None) or (doc.get("data_dir") or None)
    out = workspace.refuse_write(Path(out_dir), dataset_dir=ds_dir)
    out.mkdir(parents=True, exist_ok=True)

    # 🔴 THE DOCUMENT AS EXPORTED. Not as posted. Every writer below is handed `stamped`.
    stamped, problems = as_exported(doc, app_version)

    positions = render_positions(stamped, include_unverified)
    needs_pixels = bool({"tiff", "png"} & set(kinds))
    if (needs_pixels or "coverage" in kinds) and not positions:
        raise ExportError(
            "nothing to render: no tile is `anchored`"
            + ("" if include_unverified else " (and `unverified` tiles were excluded)")
        )

    files: list[dict] = []
    n_phases = 1 + len(kinds)
    idx = 0

    # ⏱️ One span per step, so `pct` is overall across the whole export (R48.5).
    spans = _spans(_export_steps(kinds, render_mode, needs_pixels))

    def at(step: str, frac: float, phase: str, i: int, message: str) -> None:
        """Emit one `Progress` with `pct` mapped through `step`'s span, and the ETA derived from
        **that overall pct** — never from the step's own 0->1, which is what made the bar snap back.

        The countable unit under the renders is TILES (`_RenderSink` scrapes `rendered k/N` out of
        the compositor's stdout). A write has none — it is one blocking call — so it emits once, at
        its own `lo`, and the next step's `lo` (or the closing `done`) is what closes it out. There
        is no timer here and there must not be one: R48b — with `pct` pinned, re-emitting on a clock
        makes the ETA count up.
        """
        lo, hi = spans.get(step, (0.0, 100.0))
        pct = lo + (hi - lo) * min(1.0, max(0.0, frac))
        jobs.say(report, phase, i, n_phases, pct, message,
                 jobs.eta_from_fraction(time.time() - t0, pct / 100.0))

    # `render_mosaic(report=None)` skips the stdout scrape entirely — keep None meaning None, so a
    # reportless export (every unit test) does not pay for a regex per composited tile.
    at_or_none = at if report is not None else None

    img = cov = None  # the DISPLAY render (flat-fielded)  -> the PNG
    raw = rcov = None  # the RAW render (camera counts)     -> the TIFF
    shown = shown_cov = None  # whichever exists — the GEOMETRY is identical either way

    if needs_pixels:
        idx += 1
        jobs.check_cancelled(cancel, "export")
        if "png" in kinds:
            at("render:png", 0.0, "render", idx,
               f"rendering {len(positions)} tiles for the display PNG ({render_mode})")
            img, cov = render_mosaic(frames, positions, render_mode,
                                     report=_render_cb(at_or_none, "render:png", render_mode,
                                                       len(positions), idx),
                                     cancel=cancel, flat=True)
        if "tiff" in kinds:
            at("render:tiff", 0.0, "render", idx,
               f"rendering {len(positions)} tiles as RAW CAMERA COUNTS for the TIFF "
               f"({render_mode})")
            raw, rcov = render_mosaic(frames, positions, render_mode,
                                      report=_render_cb(at_or_none, "render:tiff", render_mode,
                                                        len(positions), idx),
                                      cancel=cancel, flat=False)
        jobs.check_cancelled(cancel, "export")
        shown = img if img is not None else raw
        shown_cov = cov if cov is not None else rcov
        at("render:tiff" if "tiff" in kinds else "render:png", 1.0, "render", idx,
           f"canvas {shown.shape[1]}x{shown.shape[0]} px, "
           f"{100.0 * float(shown_cov.mean()):.1f} % covered")
    elif "coverage" in kinds:
        # Pure geometry — no pixel is read. (`engine.adapters.canvas` -> `render._canvas`.)
        idx += 1
        at("render:mask", 0.0, "render", idx, f"masking {len(positions)} tiles")
        shown_cov = coverage_mask(frames, positions)
        at("render:mask", 1.0, "render", idx, f"masking {len(positions)} tiles")

    for kind in kinds:
        jobs.check_cancelled(cancel, "export")
        idx += 1
        at(kind, 0.0, kind, idx, f"writing {kind}")

        if kind == "tiff":
            files += write_tiff(  # -> [tiff, coverage]. The sidecar is not optional.
                raw, rcov, out / f"{basename}.tif",
                description=_tiff_description(stamped, frames, dataset, positions, render_mode,
                                              rcov, um_per_px),
                um_per_px=um_per_px,
            )
        elif kind == "coverage":
            files.append(write_coverage(shown_cov, out / f"{basename}_coverage.png"))
        elif kind == "png":
            files.append(write_png(img, cov, frames.tone, out / f"{basename}.png"))
        elif kind == "positions":
            files.append(write_positions(stamped, out / f"{basename}_positions.csv",
                                         include_unverified, app_version))
        elif kind == "gt":
            files.append(write_gt(stamped, out / f"{basename}_gt.json", app_version))
        elif kind == "qc":
            files += write_qc(
                stamped, out / f"{basename}_qc.json", out / f"{basename}_qc.md",
                render={
                    "mode": render_mode,
                    "n_rendered": len(positions),
                    "include_unverified": bool(include_unverified),
                    "coverage_pct": (round(100.0 * float(shown_cov.mean()), 2)
                                     if shown_cov is not None else None),
                    "canvas": ([int(shown.shape[1]), int(shown.shape[0])]
                               if shown is not None else None),
                    "tiff_pixels": "raw camera counts (no flat-field, no gain)",
                    "png_pixels": ("flat-fielded + per-tile gain to the session level, then ONE "
                                   "global tone window"),
                    "frame": frames.frame_note,
                },
                scale=scale_metadata(um_per_px),
                problems=problems,
                app_version=app_version,
            )

    jobs.say(report, "done", n_phases, n_phases, 100.0, f"wrote {len(files)} files", 0.0)
    return {
        "kind": "export",
        "files": files,
        "doc": stamped,  # ⭐ the document AS EXPORTED — stamped. Not as posted.
        "warnings": problems,
        "seconds": round(time.time() - t0, 2),
    }


def export_to_analysis(
    frames: FrameStore,
    dataset: Any,
    doc: dict,
    ws: Any,
    analysis_id: str,
    basename: str,
    **kw: Any,
) -> dict:
    """`export_all` into `<workspace>/analyses/<analysis_id>/outputs/`.

    ⭐ **THIS IS WHERE AN ANALYSIS'S OUTPUTS BELONG.** A DATASET is raw and is never written to; an
    ANALYSIS is what you did to it, and it lives in the workspace the user chose. `export_all` still
    takes a bare directory, because *"export to a folder I name"* is a real thing the user does — and
    `workspace.refuse_write` guards both paths identically.
    """
    return export_all(frames, dataset, doc, ws.outputs_dir(analysis_id), basename, **kw)


# =================================================================================================
# RENDER — `engine.render`, the compositor that produced the 312/312 mosaic
# =================================================================================================
def render_mosaic(
    frames: FrameStore,
    positions: dict[int, tuple[float, float]],
    mode: str = "feather",
    report: Callable[..., None] | None = None,
    cancel: Any = None,
    flat: bool = True,
) -> tuple[np.ndarray, np.ndarray]:
    """-> `(img, coverage)`. `coverage` is bool: **True = real data.**

    ⭐ **`flat` DECIDES WHAT THE PIXELS ARE, AND THE TWO ANSWERS ARE NOT INTERCHANGEABLE.**

      * `flat=True`  — `core.frames.flat_correct` = `frame / vignette`, **then x (level /
        median(frame))**, a **PER-TILE GAIN**. Right for a picture; **wrong for a measurement.**
      * `flat=False` — the frames exactly as they came off the camera. **RAW COUNTS.** The TIFF.

    ⚠️⚠️ **THE COVERAGE MASK IS NOT OPTIONAL, AND IT IS NOT A NICETY.** `engine.render` writes
    background as exactly `0.0` and there is **no alpha channel**, so *"no data"* and *"black tissue"*
    are the SAME NUMBER. On the shipped 312-tile build that is **13.1 % of the canvas**. The mask is
    FREE — the union of the tile rectangles, straight out of `render._canvas`, which is pure geometry
    and touches no pixels — and without it the two merge **forever**.

    ⚠️ The tile size is the **frame store's own shape**, not a hard-coded 512. The mosaic's 512x512
    gate has already run upstream (512 is `t33.TILE`); rendering does not need to assume it again.

    Modes (measured, CPU, 312 frames in RAM):
      * **feather — 1.11 s. The only interactive mode. THE DEFAULT.**
      * median — 41.7 s, ~800 MiB peak (its cosmetic `All-NaN slice` warning is suppressed).
      * alpha  — 74.0 s, needs spectralign, and silently returns a canvas **1 px LARGER in each
        dimension**. We pad the mask to match rather than pretend they agree.
    """
    # ⚠️ LAZY, and it buys something specific: `spectralign` (which `mode="alpha"` needs) and
    # `tifffile` must not load for a `positions`-only or `gt`-only export, which touches no pixel.
    # (numpy, cv2 and `camea.engine` arrive anyway, via `core.frames` -> `engine.quality.band_pass`.)
    from camea.engine import render as erender  # noqa: PLC0415

    pos = _valid_positions(frames, positions)
    h, w = frames.shape
    level = float(frames.tone.level)

    def frame_of(t: int) -> np.ndarray:
        jobs.check_cancelled(cancel, "export")
        f = frames.frame(int(t))
        if not flat:
            return np.asarray(f, np.float32)  # RAW CAMERA COUNTS. Untouched.
        return flat_correct(f, frames.flat_n, level)

    cov = _mask(pos, (h, w))

    sink = _RenderSink(report, len(pos))
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="All-NaN slice encountered")
        with contextlib.redirect_stdout(sink):
            img = erender.render(pos, frame_of, tilesize=(h, w), mode=mode)

    img = np.asarray(img)
    if img.shape != cov.shape:  # mode="alpha": 1 px bigger each way
        padded = np.zeros(img.shape, bool)
        padded[: cov.shape[0], : cov.shape[1]] = cov
        cov = padded
    return img, cov


def coverage_mask(
    frames: FrameStore, positions: dict[int, tuple[float, float]]
) -> np.ndarray:
    """The coverage mask **without reading a single pixel** — it is pure geometry.

    Which is why there is no excuse for a TIFF that ships without one.
    """
    return _mask(_valid_positions(frames, positions), frames.shape)


def _valid_positions(
    frames: FrameStore, positions: dict[int, tuple[float, float]]
) -> dict[int, np.ndarray]:
    pos: dict[int, np.ndarray] = {}
    for t, xy in (positions or {}).items():
        t = int(t)
        if t in frames.row_of and xy is not None and xy[0] is not None and xy[1] is not None:
            pos[t] = np.asarray([float(xy[0]), float(xy[1])], float)
    if not pos:
        raise ExportError("nothing to render: no placed tile is in this frame store")
    return pos


def _mask(pos: dict[int, np.ndarray], tilesize: tuple[int, int]) -> np.ndarray:
    from camea.engine.adapters import canvas  # noqa: PLC0415 — lazy; see `render_mosaic`

    h, w = tilesize
    _trials, P, H, W = canvas(pos, (h, w))  # geometry only; no pixels touched
    cov = np.zeros((H, W), bool)
    for x, y in P:
        cov[int(y): int(y) + h, int(x): int(x) + w] = True
    return cov


class _RenderSink:
    """`engine.render.render` **prints** `rendered k/N` — it has no progress callback. Scrape stdout
    and turn the noise into progress. (Same trick, same reason, as the build's `_ProgressSink`.)"""

    _RE = re.compile(r"rendered (\d+)/(\d+)")

    #: ⏱️ Seconds between progress emits. A `feather` render composites ~280 tiles a second, and one
    #: `Progress` per tile is 280 lock-takes and 280 log lines a second for a bar nobody can read
    #: that fast. 10 Hz is well past what the eye resolves and the end of the render is emitted by
    #: `export_all` regardless, so the last tile is never the one that gets dropped.
    _MIN_INTERVAL_S = 0.1

    def __init__(self, report: Callable[..., None] | None, n: int) -> None:
        self.report, self.n, self.buf = report, max(n, 1), ""
        self._last = 0.0

    def write(self, s: str) -> int:
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            m = self._RE.search(line)
            if m and self.report:
                now = time.monotonic()
                if now - self._last < self._MIN_INTERVAL_S:
                    continue
                self._last = now
                self.report(100.0 * int(m.group(1)) / max(int(m.group(2)), 1), line.strip())
        return len(s)

    def flush(self) -> None:
        pass


def _render_cb(
    at: Callable[..., None] | None, step: str, mode: str, n: int, idx: int
) -> Callable[..., None] | None:
    """Adapt `_RenderSink`'s `report(pct, message)` to `export_all`'s span-weighted emitter.

    ⚠️ The sink's `pct` is the render's OWN 0->100 — tiles composited out of `n`. It is handed on as
    a fraction and `at` maps it into this render's slice of the whole export, because a render that
    paints the bar 0 -> 100 by itself is exactly the R48.5 violation: on a TIFF + PNG export it did
    that twice and then jumped backwards to the first write.

    (`core.jobs.report_adapter` maps positionals as `(phase, pct, message)`, which is the wrong
    shape for this one. The renderer's callback shape is not part of any contract, so we adapt
    rather than assume.)
    """
    if at is None:
        return None

    def cb(*args: Any) -> None:
        # `_RenderSink` is the only caller, and it always passes `(pct, line)`.
        pct = float(args[0]) if args else 0.0
        msg = str(args[1]) if len(args) > 1 else f"rendering {n} tiles"
        at(step, pct / 100.0, "render", idx, f"{msg} ({mode})")

    return cb


# =================================================================================================
# 1. THE 16-BIT TIFF  (+ its MANDATORY coverage sidecar)
# =================================================================================================
def write_tiff(
    img: np.ndarray,
    coverage: np.ndarray,
    path: str | Path,
    description: str | None = None,
    um_per_px: float | None = None,
) -> list[dict]:
    """**THE REAL DELIVERABLE** — a 16-bit TIFF that opens in Fiji/ImageJ at full depth.
    -> `[tiff entry, coverage entry]`.

    ⛔ **DO NOT PASS THE DISPLAY RENDER IN HERE.** `img` MUST be the **`flat=False`** render — RAW
    CAMERA COUNTS, no flat-field, no per-tile gain, no tone map. The display render carries a
    per-tile gain (`level / median(frame)`) that drags every tile's exposure onto a common level
    (measured x1.63 on trial 11, x1.31 on trial 16). That is right for a picture and wrong for a
    measurement — and this file's ImageDescription says, **in writing**, that the counts are raw.
    Two renders is cheap; a header that lies is not.

    (uint16, but only ~1/20 of the range is used: the global max across all 338 snapshots is
    18,022 / 65,535 and the saturated fraction is exactly 0.0 in every frame. **We do not rescale** —
    Fiji has a window/level, and rescaling would be one more silent transform of a measurement.)

    ⚠️⚠️ **THE COVERAGE MASK IS MANDATORY, NOT A NICETY.** **13.1 % of the canvas is background
    encoded as exactly `0.0`** — indistinguishable from a legitimately black pixel — and **a TIFF has
    no alpha channel.** Written to a plain TIFF, *"no data"* and *"black tissue"* merge **forever**.
    It goes out as a **sidecar 8-bit PNG** (`<basename>_coverage.png`; 0 = no data, 255 = covered) —
    a sidecar and not a second TIFF page, because a two-page TIFF confuses Fiji users and this must
    be unambiguous.
    """
    import tifffile  # noqa: PLC0415 — a heavy import for one of six outputs

    path = Path(path)
    img = np.asarray(img)
    coverage = np.asarray(coverage, bool)
    if coverage.shape != img.shape:
        raise ExportError(f"coverage {coverage.shape} does not match the mosaic {img.shape}")

    lost = int(np.count_nonzero(~np.isfinite(img)))
    u16 = np.clip(
        np.nan_to_num(img, nan=0.0, posinf=65535.0, neginf=0.0), 0, 65535
    ).astype(np.uint16)
    u16[~coverage] = 0  # background is EXACTLY 0 — and the sidecar is what says so
    if lost:
        warnings.warn(f"{lost} non-finite pixel(s) in the mosaic were written as 0", stacklevel=2)

    kw: dict[str, Any] = {}
    if description:
        kw["description"] = _ascii(description)  # TIFF's ImageDescription is an ASCII tag
    if um_per_px:  # 📏 user-supplied only — see `scale_metadata`
        px_per_cm = 1e4 / float(um_per_px)
        kw["resolution"] = (px_per_cm, px_per_cm)
        kw["resolutionunit"] = "CENTIMETER"

    # `tifffile` writes through a file handle, so it cannot go through `workspace.atomic_write_bytes`
    # directly — but the temp-then-replace shape is kept, so a crash never leaves a half-written TIFF
    # where a whole one used to be.
    tmp = path.with_suffix(path.suffix + ".tmp")
    tifffile.imwrite(str(tmp), u16, photometric="minisblack", **kw)
    try:
        workspace.atomic_write_bytes(path, tmp.read_bytes())
    finally:
        tmp.unlink(missing_ok=True)

    cov_entry = write_coverage(coverage, path.with_name(path.stem + "_coverage.png"))
    return [workspace.file_entry("tiff", path), cov_entry]


def write_coverage(coverage: np.ndarray, path: str | Path) -> dict:
    """The sidecar: 8-bit, **0 = no data, 255 = covered**. The only thing that can tell background
    from black tissue once the TIFF is on somebody else's disk."""
    cov = np.asarray(coverage, bool)
    _write_png_u8(np.where(cov, 255, 0).astype(np.uint8), Path(path))
    return workspace.file_entry("coverage", Path(path))


def _tiff_description(
    doc: dict,
    frames: FrameStore,
    dataset: Any,
    positions: dict,
    mode: str,
    coverage: np.ndarray | None,
    um_per_px: float | None,
) -> str:
    tiles = _tiles(doc)
    n_anch = sum(1 for t in tiles.values() if state_of(t) == "anchored")
    n_unv = sum(1 for t in tiles.values() if state_of(t) == "unverified")
    prov = doc.get("provenance") or {}
    cov_pct = 100.0 * float(np.asarray(coverage).mean()) if coverage is not None else float("nan")

    lines = [
        f"Camea {camea.__version__} - mosaic",
        f"dataset={doc.get('dataset') or getattr(dataset, 'name', None) or '?'}",
        f"tiles rendered={len(positions)} (anchored={n_anch}, unverified={n_unv} in the document)",
        f"render_mode={mode}",
        "pixels=RAW CAMERA COUNTS, uint16. NO flat-field, NO per-tile gain, NOT tone-mapped "
        "(Fiji has a window/level). Exposure genuinely varies ~2.4x across this run and that "
        "variation is PRESERVED here: it is data, not an artefact. The display PNG beside this "
        "file is the flat-fielded, exposure-normalised picture - use that one for figures, and "
        "this one for measurements.",
        # ⭐ ASK THE FRAME STORE, WHICH ASKED THE XML. This line used to assert "180-degree-flipped"
        # UNCONDITIONALLY while the reader flips CONDITIONALLY on `ax`/`ay` — a header that could lie
        # about its own coordinate frame, on the one axis this project has been burned by, in the
        # file most likely to be handed to somebody else.
        f"coordinates=top-left corners (NOT centres), in {frames.frame_note}",
        f"coverage={cov_pct:.1f} % of this canvas is real data; the rest is background encoded as "
        "EXACTLY 0 and is INDISTINGUISHABLE from black tissue. Use the sidecar *_coverage.png "
        "(0 = no data, 255 = covered).",
    ]
    if um_per_px:
        lines.append(f"um_per_px={um_per_px} (USER-SUPPLIED BY HAND, not measured by this app)")
    else:
        lines.append(
            "scale=PIXELS ONLY. This app does not measure um/px, so none is written. (There is NO "
            "magnification difference between the passes: cross-pass tissue scale = 1.0000 "
            "+/- 0.0002. The old '2.5 %' figure came from the electrode-grid pitch, which tracks "
            "FOCUS, not magnification. One scale bar spanning both passes is safe.)"
        )

    # ⭐ ASK THE TILES, NOT THE PROVENANCE BLOCK. `export_all` hands us the STAMPED doc, so `prov` is
    # already authoritative — and we re-derive from the history ANYWAY, because the provenance block
    # is exactly the field a "place from scratch" button can erase while every tile still sits where
    # t33 put it. A header that lies about provenance is worse than no header: it is a certificate of
    # independence for a machine's own output.
    seeded = (
        bool(prov.get("seeded_from"))
        or prov.get("independent_of_method") is False
        or bool(doc.get("build"))
        or machine_evidence(doc) is not None
    )
    lines.append(
        "PROVENANCE: " + PROVENANCE_WARNING if seeded else
        "PROVENANCE: hand-placed from scratch; no build seeded it (independent_of_method: true)."
    )
    return "\n".join(lines)


#: TIFF's `ImageDescription` is an **ASCII** tag — `tifffile` raises on a non-ASCII byte, and
#: `PROVENANCE_WARNING` contains an em-dash and a `%` sign in prose. **Fold, do not drop:** the text
#: is the entire point of putting it there.
_ASCII_FOLD = str.maketrans({
    "—": "--", "–": "-", "’": "'", "‘": "'", "“": '"', "”": '"',
    "µ": "u", "°": " deg", "≥": ">=", "≤": "<=", "×": "x",
    "⚠": "!", "⭐": "*", "⛔": "!!", "→": "->", "…": "...",
})


def _ascii(s: str) -> str:
    return s.translate(_ASCII_FOLD).encode("ascii", "ignore").decode("ascii")


# =================================================================================================
# 2. THE DISPLAY PNG
# =================================================================================================
def write_png(
    img: np.ndarray, coverage: np.ndarray, tone: Any, path: str | Path
) -> dict:
    """The display PNG: 8-bit, full resolution, no decoration. For figures and slides.

    ⚠️⚠️ **TONE-MAP GLOBALLY. ONE WINDOW FOR THE WHOLE MOSAIC.** It is `frames.tone` — the *same*
    0.5/99.6-percentile window every tile in the UI went through. A **per-tile** stretch
    over-brightens near-empty frames and makes overlapping tiles disagree in tone, **which destroys
    the Difference-mode check the whole verification loop depends on.** There is no per-tile path in
    this app and there must never be one.

    ⚠️ The `mosaic.png` shipped in the old repo is NOT the mosaic — it is a matplotlib figure
    (1416x2426, 0.629x linear, 8-bit RGBA, a 1-99 stretch baked in, and a **title drawn on**). We do
    not imitate it. These are the actual pixels, at the actual size.
    """
    path = Path(path)
    img = np.asarray(img, np.float32)
    coverage = np.asarray(coverage, bool)
    if coverage.shape != img.shape:
        raise ExportError(f"coverage {coverage.shape} does not match the mosaic {img.shape}")

    win = tone_lohi(tone)
    if win is None:
        # The store always carries a tone window; this is only reached if it somehow does not. Still
        # ONE window for the WHOLE mosaic — never per tile.
        sample = img[coverage]
        if sample.size == 0:
            raise ExportError("nothing covered: cannot window an empty mosaic")
        lo, hi = (float(v) for v in np.percentile(sample, [0.5, 99.6]))
        if hi <= lo:
            hi = lo + 1.0
    else:
        lo, hi = win

    u8 = np.clip((img - lo) * (255.0 / (hi - lo)), 0, 255).astype(np.uint8)
    u8[~coverage] = 0  # background: black — and the coverage PNG is what says which
    _write_png_u8(u8, path)
    return workspace.file_entry("png", path)


def _write_png_u8(u8: np.ndarray, path: Path) -> None:
    from PIL import Image  # noqa: PLC0415

    buf = io.BytesIO()
    Image.fromarray(np.ascontiguousarray(u8, np.uint8), mode="L").save(buf, format="PNG")
    workspace.atomic_write_bytes(path, buf.getvalue())


# =================================================================================================
# 3a. positions.csv
# =================================================================================================
def write_positions(doc: dict, path: str | Path, include_unverified: bool = True,
                    app_version: str | None = None) -> dict:
    """`positions.csv`. The header is **asserted** before the file leaves the process."""
    text = to_positions_csv(doc, include_unverified, app_version)
    head = text.splitlines()[0] if text else ""
    if head != "trial,x,y,state":  # `score.load_positions` DictReads the first three names
        raise ExportError(f"positions.csv header must be exactly 'trial,x,y,state', got {head!r}")
    workspace.atomic_write_text(Path(path), text)
    return workspace.file_entry("positions", Path(path))


# =================================================================================================
# 3b. the ground-truth JSON
# =================================================================================================
def write_gt(doc: dict, path: str | Path, app_version: str | None = None) -> dict:
    """The ground-truth JSON. Scoreable by `tests/guard/score.py` unchanged.

    ⚠️ **THE PROVENANCE STAMP IS MANDATORY, AND IT IS NOT DECORATION.** It says out loud, **in the
    file**, that this is *a build a human signed off on* and **NOT an independent ground truth**, and
    that it **must never be used to score the solver that produced it**. Pass 1's own truth got tiles
    128/129/130/148 wrong exactly this way, and this project has already destroyed one benchmark by
    overwriting it with an algorithm's output.

    ⭐ It is checked **scoreable** before it leaves the process — see `_assert_scoreable`.
    """
    gt = _assert_scoreable(to_gt(doc, app_version))  # ⛔ unconditional. See `as_exported`.
    workspace.atomic_write_text(Path(path), workspace.dumps(jsonable(gt)))
    return workspace.file_entry("gt", Path(path))


def _assert_scoreable(gt: dict) -> dict:
    """⭐ **THE TWO LINES `score.load_gt()` ACTUALLY READS**, checked before the file leaves the
    process::

        doc["tiles"][k]["status"] == "anchor"   ->   x / y
        doc["tolerance_px"]["region_default"]   ->   the fallback per-tile r

    **A project the scorer cannot read is a project that cannot be checked.** Keep it that way.
    """
    tol = gt.get("tolerance_px") or {}
    if "region_default" not in tol:
        raise ExportError(
            "the GT export is missing `tolerance_px.region_default` — `score.load_gt()` would "
            "KeyError on any tile without an explicit `r`, and a project the scorer cannot read is "
            "a project that cannot be checked."
        )
    n_anchor = 0
    for k, v in (gt.get("tiles") or {}).items():
        if not str(k).isdigit():
            raise ExportError(f"tile key {k!r} is not a decimal trial number")
        if v.get("status") == "anchor":
            if v.get("x") is None or v.get("y") is None:
                raise ExportError(f"tile {k} is status=anchor with a null position")
            n_anchor += 1
    if n_anchor == 0:
        warnings.warn(
            "the exported GT has ZERO anchor tiles — `score.py` would find nothing to score "
            "(it keeps only `status == \"anchor\"` rows)",
            stacklevel=2,
        )
    return gt


# =================================================================================================
# 4. THE QC REPORT — what the human did vs what the machine said
# =================================================================================================
def qc_report(doc: dict, app_version: str | None = None) -> tuple[dict, str]:
    """-> `(json, markdown)`. **This report IS the honest record of the anchoring hazard**, and it is
    what makes the mosaic safe to hand to somebody else.

    ⭐ **EVERY NUMBER STATES ITS DENOMINATOR.** A percentage without one is how the 182-vs-156
    confusion started. The denominator is **the document's own `excluded` set and nothing else** —
    the app has no list of its own.

    ⚠️ `denominator.not_excluded` was called `usable_trials` in v1's `qc.json` and is **renamed on
    purpose**: the old name collided, character for character, with `excluded.usable_trials()` — the
    one symbol the standing ruling forbids the app to import. The number is unchanged (every tile the
    human did not exclude), and nothing machine-readable depended on the old name (`score.py` reads
    `gt.json` and `positions.csv`, never `qc.json`).
    """
    doc = to_gt(doc, app_version)  # ⛔ unconditional. See `as_exported`.

    states = tuple(STATES)
    placed = set(PLACED_STATES)
    moved_eps = float(MOVED_EPS)
    thin_thr = _margin_thin()

    tiles = _tiles(doc)
    prov = doc.get("provenance") or {}
    he = prov.get("human_edits") or {}

    n_total = len(tiles)
    n_run = len(active_trials(doc))  # ⛔ everything the human did NOT exclude. Nothing else.
    by = {s: sorted(t for t, v in tiles.items() if state_of(v) == s) for s in states}
    n_excl = len(by.get("excluded", []))

    moved_rows = sorted(
        (
            {
                "trial": t,
                "moved_px": float(v["moved_px"]),
                "from": [float(v["machine"][0]), float(v["machine"][1])],
                "to": [float(v["x"]), float(v["y"])],
                "state": state_of(v),
                "ncc": v.get("ncc"),
                "margin": v.get("margin"),
                "n_anchors": v.get("n_anchors"),
                "note": v.get("note"),
            }
            for t, v in tiles.items()
            if state_of(v) in placed
            and v.get("moved_px") is not None
            and v.get("machine")
            and float(v["moved_px"]) >= moved_eps
        ),
        key=lambda r: -r["moved_px"],
    )
    thin = sorted(
        t for t, v in tiles.items()
        if v.get("margin") is not None
        and float(v["margin"]) < thin_thr
        and state_of(v) in placed
    )
    # "the solver could not place it; the human did" — only meaningful in a seeded document.
    rescued = sorted(
        t for t, v in tiles.items()
        if state_of(v) in placed and v.get("machine") is None and prov.get("seeded_from")
    )
    stale, stale_why = is_build_stale(doc)

    rep: dict[str, Any] = {
        "dataset": doc.get("dataset"),
        "trial_range": doc.get("trial_range"),
        "pass_split": doc.get("pass_split"),
        "generated": iso_now(),
        "app": {"name": "Camea", "version": app_version or camea.__version__},
        "denominator": {
            "trials_in_document": n_total,
            "not_excluded": n_run,
            "excluded": n_excl,
            "excluded_trials": by.get("excluded", []),
            "note": "Every percentage in this report is over the trials the human did NOT exclude, "
                    "never over the document's row count. The app has no exclusion list of its own: "
                    "this denominator comes from this document and nowhere else.",
        },
        "by_state": {s: by.get(s, []) for s in states},
        "human_edits": he,
        "moved": moved_rows,
        "rescued": rescued,
        "thin_margin": thin,
        "thin_margin_threshold": thin_thr,
        "thin_margin_note": f"A thin margin (< {thin_thr:.2f} best-minus-second NCC) is the "
                            "signature of a surviving grid alias — the electrode grid repeats every "
                            "256 px. Look at these first.",
        "gaps": doc.get("gaps"),
        "gaps_note": "Trial numbers are acquisition ORDER but are not contiguous once anything is "
                     "excluded. The serpentine one-axis step prior does NOT hold across these, and "
                     "a build that assumes them away places the whole tail wrong.",
        "build": ({k: v for k, v in (doc.get("build") or {}).items() if k != "positions"}
                  if doc.get("build") else None),
        "build_stale": bool(stale),
        "build_stale_reason": stale_why,
        "provenance": prov,
    }
    return rep, _qc_markdown(rep, doc, moved_eps)


def _qc_markdown(rep: dict, doc: dict, moved_eps: float) -> str:
    prov = rep["provenance"]
    he = rep["human_edits"]
    by = rep["by_state"]
    n_run = rep["denominator"]["not_excluded"]
    n_total = rep["denominator"]["trials_in_document"]
    n_excl = rep["denominator"]["excluded"]
    rng = doc.get("trial_range") or ["?", "?"]

    def pct(n: int) -> str:
        return f"{100.0 * n / n_run:.1f} %" if n_run else "—"

    def n_of(state: str) -> int:
        return len(by.get(state, []))

    L: list[str] = [
        f"# QC report — {rep['dataset']}  (trials {rng[0]}–{rng[1]})",
        "",
        f"Generated {rep['generated']} by {rep['app']['name']} {rep['app']['version']}.",
        "",
    ]

    if not prov.get("independent_of_method"):
        seeded = prov.get("seeded_from") or {}
        L += [
            "> ## ⚠️ THIS IS NOT AN INDEPENDENT GROUND TRUTH",
            ">",
            "> " + PROVENANCE_WARNING,
            ">",
            f"> Seeded from **{seeded.get('method')}**, build `{seeded.get('build_id')}`."
            + (f" (Detected from: {seeded['detected_from']}.)" if seeded.get("detected_from") else ""),
            "",
        ]
    else:
        L += [
            "> **Hand placement from scratch.** No build seeded this document, so it *is* an "
            "independent truth and it may be used to score a method.",
            "",
        ]

    if rep["build_stale"]:
        L += ["> ## ⚠️ THE BATCH BUILD IS STALE", ">", "> " + str(rep["build_stale_reason"]), ""]

    L += [
        "## The denominator",
        "",
        f"- **{n_run}** trials the human did not exclude. Every percentage below is over those "
        f"{n_run}.",
        f"- {n_total} tile rows in the document; **{n_excl}** excluded.",
        "- ⛔ The app has no exclusion list of its own. Every exclusion here is the human's — pressed "
        "in the sweep, or loaded from a project file he saved.",
        "",
        "## What the human did",
        "",
        "| | tiles | of the run |",
        "|---|---:|---:|",
        f"| **anchored** (`A` — certified) | {n_of('anchored')} | {pct(n_of('anchored'))} |",
        f"| **unverified** (`Space`, no decision) | {n_of('unverified')} | {pct(n_of('unverified'))} |",
        f"| **unplaced** (never placed) | {n_of('unplaced')} | {pct(n_of('unplaced'))} |",
        f"| **excluded** (`E`) | {n_excl} | — |",
        "",
        "## Human vs machine",
        "",
    ]

    if doc.get("build"):
        L += [
            f"- **accepted unchanged** (moved < {moved_eps} px): "
            f"**{he.get('accepted_unchanged', 0)}**",
            f"- **moved by hand**: **{he.get('moved', 0)}**  "
            f"(median {float(he.get('median_move_px') or 0.0):.2f} px, max "
            f"{float(he.get('max_move_px') or 0.0):.2f} px — over the moved tiles only)",
            f"- **rescued** (the solver could not place it; the human did): "
            f"**{he.get('rescued', 0)}**",
            f"- **still unverified**: **{he.get('unverified', 0)}**",
            "",
        ]
        # ⭐ AND THE DIVERTS. The app placed these at the SOLVER's position because the
        # anchor-composite match was not trustworthy there. They ARE at the machine's position, so
        # they land inside `accepted unchanged` above — and without this block that number reads as
        # human agreement it never got. **Say it next to the number it contaminates.** (In the defer
        # flow this can be 302 of 311 tiles.)
        if he.get("diverted_to_solver"):
            L += [
                f"### ⚠️ {he['diverted_to_solver']} tiles were DIVERTED to the solver",
                "",
                "**They sit at the machine's position, so they are counted inside *accepted "
                "unchanged* above. The app never gave the matcher a vote on them.**",
                "",
                "- " + " ".join(str(t) for t in (he.get("diverted_trials") or [])),
            ]
            if he.get("diverted_note"):
                L.append("- " + str(he["diverted_note"]))
            L.append("")
        if rep["moved"]:
            L += [
                "### Tiles the human moved (worst first)",
                "",
                "| trial | moved (px) | machine | human | NCC | margin | anchors |",
                "|---:|---:|---|---|---:|---:|---:|",
            ]
            for r in rep["moved"]:
                f_ = f"({r['from'][0]:.1f}, {r['from'][1]:.1f})"
                t_ = f"({r['to'][0]:.1f}, {r['to'][1]:.1f})"
                ncc = "—" if r["ncc"] is None else f"{float(r['ncc']):.3f}"
                mg = "—" if r["margin"] is None else f"{float(r['margin']):.3f}"
                na = "—" if r["n_anchors"] is None else str(r["n_anchors"])
                L.append(
                    f"| {r['trial']} | {r['moved_px']:.2f} | {f_} | {t_} | {ncc} | {mg} | {na} |"
                )
            L.append("")
    else:
        L += ["- No build seeded this document — every position is the human's.", ""]

    if rep["thin_margin"]:
        L += [
            f"### ⚠️ Thin margins (< {rep['thin_margin_threshold']:.2f}) — the signature of a "
            "surviving alias",
            "",
            "- " + " ".join(str(t) for t in rep["thin_margin"]),
            "",
        ]
    if by.get("unplaced"):
        L += ["### Still unplaced", "", "- " + " ".join(str(t) for t in by["unplaced"]), ""]

    L += [
        "## Acquisition gaps",
        "",
        ("- " + "  ".join(f"{a}→{b}" for a, b in (rep["gaps"] or []))) if rep["gaps"] else "- none",
        "- " + rep["gaps_note"],
        "",
    ]
    return "\n".join(L)


def write_qc(
    doc: dict,
    path_json: str | Path,
    path_md: str | Path,
    render: dict | None = None,
    scale: dict | None = None,
    problems: list[str] | None = None,
    app_version: str | None = None,
) -> list[dict]:
    """The QC report, as both `.json` and a human-readable `.md`. -> `[json entry, md entry]`.

    `qc_report()` owns the *document* half. This adds the two things only the exporter knows — **what
    was actually rendered** (mode, tile count, and the coverage fraction the TIFF cannot express on
    its own) and **the scale policy** — plus any document problems, and appends them to both files.
    """
    qc, md = qc_report(doc, app_version)
    qc = dict(qc)
    if render:
        qc["render"] = render
    if scale:
        qc["scale"] = scale
    if problems:
        qc["document_problems"] = list(problems)
    md = md.rstrip("\n") + "\n" + _qc_export_markdown(render, scale, problems)

    workspace.atomic_write_text(Path(path_json), workspace.dumps(jsonable(qc)))
    workspace.atomic_write_text(Path(path_md), md)
    return [workspace.file_entry("qc", Path(path_json)), workspace.file_entry("qc", Path(path_md))]


def _qc_export_markdown(
    render: dict | None, scale: dict | None, problems: list[str] | None
) -> str:
    L: list[str] = [""]
    A = L.append
    if render:
        A("## The exported mosaic")
        A("")
        A(f"- mode **{render['mode']}**, **{render['n_rendered']}** tiles rendered "
          f"({'anchored + unverified' if render.get('include_unverified') else 'anchored only'}). "
          "`excluded` and `unplaced` are never rendered.")
        if render.get("canvas"):
            A(f"- canvas **{render['canvas'][0]} × {render['canvas'][1]} px**")
        if render.get("frame"):
            A(f"- coordinates: tile **top-left corners** (not centres), in {render['frame']} — read "
              "off this acquisition's own XML, never asserted.")
        if render.get("coverage_pct") is not None:
            A(f"- **{render['coverage_pct']} % of the canvas is real data.** The remaining "
              f"{round(100.0 - render['coverage_pct'], 2)} % is background encoded as **exactly 0**, "
              "which is indistinguishable from a legitimately black pixel — the 16-bit TIFF has no "
              "alpha channel. That is what the sidecar `*_coverage.png` is for (**0 = no data, "
              "255 = covered**). Without it, *empty* and *black* merge forever.")
        A("- The **TIFF** is raw camera counts (a measurement). The **PNG** is flat-fielded and "
          "exposure-normalised (a picture). They are two different renders and they are not "
          "interchangeable.")
        A("")
    A("## Scale")
    A("")
    if scale and scale.get("um_per_px"):
        A(f"**{scale['um_per_px']} µm/px — {scale.get('source')}.** This number was typed in by the "
          "user; **this app did not measure it.** One value is the right shape: there is **no "
          "magnification difference between the passes** (cross-pass tissue scale **1.0000 ± "
          "0.0002**), so a single scale bar spanning both passes is safe. ⚠️ Do not use "
          "**1.237 µm/px** — it came from an inference that has been proven wrong.")
    else:
        A("**Pixels only.** No scale bar, no OME-TIFF `PhysicalSizeX/Y` — this app does not measure "
          "µm/px. ⚠️ The old warning about *'a 2.5 % magnification difference between the passes'* "
          "was **WRONG and is now settled**: the MEA grid pitch tracks **focus**, not magnification "
          "— it swings 3.5 % across five frames taken on a *stationary* stage, while the fitted "
          "tissue scale stays flat. Cross-pass scale is **1.0000 ± 0.0002**. Calibrate from the "
          "**stage**, not the grid.")
    A("")
    if problems:
        A("## ⚠️ Document problems")
        A("")
        A("The export was written anyway — these are **reported, not silently repaired**:")
        A("")
        for p in problems:
            A(f"- {p}")
        A("")
    A("## Caveats that apply to every number above")
    A("")
    A("- **Pass-1 tiles have no per-tile confidence at all.** t27's `info` is aggregate-only, and "
      "the worst tile in the shipped 312/312 build (**trial 127, at 9.94 px**) is a *pass-1* tile. "
      "The absence of a warning on a pass-1 tile is **not** a clean bill of health.")
    A("- **A thin margin is the signature of a surviving alias.** The shipped build's worst run "
      "margin is 0.081 against a ~0.47 typical.")
    A("- **Blur is not measured here, and it must not be.** Across 15 focus measures the best global "
      "blur threshold reaches F1 = 0.37, and variance-of-Laplacian scores *worse than chance*. Every "
      "blur call in this document is a human's. `blank`, by contrast, **is** measured.")
    A("- **The live sweep is a faithful guide to GEOMETRY, not to PHOTOMETRY.** Judge alignment "
      "there; judge tone here.")
    A("")
    return "\n".join(L)


# =================================================================================================
# 📏 PHYSICAL SCALE
# =================================================================================================
def scale_metadata(um_per_px: float | None) -> dict:
    """⛔ **THE EXPORTER WRITES PIXELS ONLY. `um_per_px` DEFAULTS TO `None` AND STAYS `None`.**

    No scale bar. No OME-TIFF `PhysicalSizeX/Y`. **This app does not measure µm/px.**

    ⚠️ **THE OLD WARNING HERE WAS WRONG, AND SAYING IT IN AN EXPORTED FILE WAS WORSE.** It asserted
    *"a 2.5 % magnification difference between the passes, not yet resolved"*. It **is** resolved:
    the MEA grid pitch tracks **FOCUS**, not stage magnification — across the five frames of the
    pass-boundary dwell (a *stationary* stage, tissue NCC ~1.000) the pitch swings 14.22 -> 13.84
    while the fitted tissue scale stays flat at 1.0010 ± 0.0001. Cross-pass tissue scale is
    **1.0000 ± 0.0002**, > 80 sigma from 1.025. **There is no magnification difference, and ONE scale
    bar spanning both passes is safe.**

    If — and only if — the user types a µm/px in by hand, we write physical units **and stamp the
    source**, so nobody later mistakes a typed-in number for a measured one.
    ❌ **Never 1.237 µm/px.** It came from the broken inference.
    """
    NOTE = (
        "This app does NOT measure um/px. There is no magnification difference between the passes "
        "(cross-pass tissue scale 1.0000 +/- 0.0002), so ONE scale is the right shape and a single "
        "scale bar spanning both passes is safe. The MEA grid pitch is NOT a valid calibration - it "
        "tracks focus. Calibrate from the stage."
    )
    if um_per_px is None:
        return {
            "um_per_px": None,
            "source": "unknown",
            "note": "PIXELS ONLY. No physical scale is written and no scale bar is drawn. " + NOTE,
        }
    v = float(um_per_px)
    if not np.isfinite(v) or v <= 0:
        raise ExportError(f"um_per_px must be a positive number, got {um_per_px!r}")
    return {
        "um_per_px": v,
        "source": "user-supplied by hand, not measured",  # `api.schemas.Scale.source`, verbatim
        "note": "SUPPLIED BY HAND by the user - NOT measured by this app. " + NOTE,
    }
