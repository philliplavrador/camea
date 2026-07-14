"""Exports — 16-bit TIFF (+ coverage mask), display PNG, positions.csv, GT JSON, QC report.

OWNER: agent 6. Nobody else edits this file.
CONTRACT: app/API.md §12.

All five outputs, as separate files. `tifffile` is installed; do NOT pip install anything.
The export is a JOB (rendering is 1.1 s - 74 s depending on mode) — `jobs.JOBS.submit_thread`.

WHAT IS RENDERED: tiles whose state is `anchored`, plus `unverified` iff `include_unverified`.
`excluded` and `unplaced` are **never** rendered. (And the 26 thrown-out snapshots were never even
loaded — they are not in the session.)

────────────────────────────────────────────────────────────────────────────────────────────
WHAT THIS MODULE OWNS, AND WHAT IT DELEGATES
────────────────────────────────────────────────────────────────────────────────────────────
It OWNS the file formats: the 16-bit TIFF, its mandatory coverage sidecar, the display PNG, and
the physical-scale policy.

It DELEGATES the document, because `project.py` owns it and there must be exactly one
implementation of the state machine and of the provenance stamp:

    project.to_positions_csv(doc, include_unverified) -> the csv text
    project.to_gt(doc, app_version)                   -> the GT json (normalise -> stamp)
    project.qc_report(doc, app_version)               -> (json, markdown)
    project.validate(doc)                             -> problems (reported, never silently fixed)

and it delegates the pixels to `engine.py`, because that is the ONLY module allowed to touch
`analysis/mosaic/`:

    engine.render_mosaic(session, positions, mode, report, cancel) -> (img, coverage)

So there is exactly ONE implementation of the state machine, ONE of the provenance stamp, and ONE
of the renderer. `analysis/mosaic/` is never forked, and nothing here reimplements
`score.robust_align` (a reimplementation with a different tie-break scored the same positions
152/156 where the canonical one gives 155/156).
"""
from __future__ import annotations

import io
import json
import os
import time
import warnings
from pathlib import Path

import numpy as np

# ── siblings (relative when imported as app.backend.export; flat when run standalone) ─────
try:                                    # pragma: no cover - import plumbing
    from . import engine, project
    from .jobs import Cancelled, Progress
except ImportError:                     # pragma: no cover
    import engine, project              # type: ignore
    from jobs import Cancelled, Progress  # type: ignore


APP_VERSION = "1.0.0"
REPO_ROOT = Path(__file__).resolve().parents[2]      # the dir containing analysis/ and data/

#: the only kinds `POST /api/export` accepts. "tiff" ALWAYS also emits "coverage".
OUTPUT_KINDS = ("tiff", "png", "positions", "gt", "qc")

#: ONE source for the provenance warning — `project.py` owns it. Never paraphrase it.
PROVENANCE_WARNING = project.PROVENANCE_WARNING


# =============================================================================
# small helpers
# =============================================================================
def _is_cancelled(cancel) -> bool:
    """`cancel` is a threading.Event (jobs.submit_thread) — but tolerate a plain callable."""
    if cancel is None:
        return False
    if hasattr(cancel, "is_set"):
        return bool(cancel.is_set())
    if callable(cancel):
        return bool(cancel())
    return False


def _check(cancel) -> None:
    if _is_cancelled(cancel):
        raise Cancelled("export cancelled")


def _say(report, phase: str, idx: int, n: int, pct: float, message: str) -> None:
    if report is None:
        return
    report(Progress(phase=phase, phase_index=idx, n_phases=n,
                    pct=float(np.clip(pct, 0.0, 100.0)), message=message))


def _atomic_bytes(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _atomic_text(path: Path, text: str) -> None:
    _atomic_bytes(path, text.encode("utf-8"))


def _entry(kind: str, path: Path) -> dict:
    return {"kind": kind, "path": str(path).replace("\\", "/"), "bytes": path.stat().st_size}


def _tone_lohi(tone) -> tuple[float, float] | None:
    """(lo, hi) from a loader.Tone dataclass OR a plain dict. None if there is no tone window."""
    if tone is None:
        return None
    lo = getattr(tone, "lo", None) if not isinstance(tone, dict) else tone.get("lo")
    hi = getattr(tone, "hi", None) if not isinstance(tone, dict) else tone.get("hi")
    if lo is None or hi is None or not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return None
    return float(lo), float(hi)


_ASCII_FOLD = str.maketrans({"—": "--", "–": "-", "’": "'", "‘": "'", "“": '"', "”": '"',
                             "µ": "u", "°": " deg", "≥": ">=", "≤": "<=", "×": "x",
                             "⚠": "!", "⭐": "*", "⛔": "!!", "→": "->", "…": "..."})


def _ascii(s: str) -> str:
    """TIFF's ImageDescription is an **ASCII** tag — `tifffile` raises on a non-ASCII byte, and the
    provenance warning contains an em-dash. Fold, do not drop: the text is the point."""
    return s.translate(_ASCII_FOLD).encode("ascii", "ignore").decode("ascii")


def _tiles(doc: dict) -> dict[int, dict]:
    return {int(k): v for k, v in (doc.get("tiles") or {}).items()}


def _state_of(tile: dict) -> str:
    """`state` wins if present, else derive it from the GT `status` (the bench never wrote one)."""
    st = tile.get("state")
    if st:
        return str(st)
    status = tile.get("status")
    return "anchored" if status == "anchor" else (str(status) if status else "unplaced")


# =============================================================================
# what gets rendered
# =============================================================================
def render_positions(doc: dict, include_unverified: bool = True) -> dict[int, tuple[float, float]]:
    """{trial: (x, y)} for every tile that MAY be rendered.

    `anchored` always; `unverified` only if `include_unverified`. `excluded` and `unplaced` are
    never rendered — they have no position (x = y = null) and that is the invariant the whole
    state machine rests on.
    """
    want = {"anchored"} | ({"unverified"} if include_unverified else set())
    out: dict[int, tuple[float, float]] = {}
    for t, tile in _tiles(doc).items():
        if _state_of(tile) not in want:
            continue
        x, y = tile.get("x"), tile.get("y")
        if x is None or y is None:
            continue                    # a placed state with no position: project.validate errors
        out[t] = (float(x), float(y))
    return out


# =============================================================================
# THE JOB
# =============================================================================
def export_all(session, doc: dict, out_dir: Path, basename: str,
               outputs: list[str], render_mode: str = "feather",
               include_unverified: bool = True, um_per_px: float | None = None,
               report=None, cancel=None) -> dict:
    """The export job. -> {"files": [{"kind", "path", "bytes"}, ...]}  (API.md §12.1)

    `outputs` ⊆ {"tiff", "png", "positions", "gt", "qc"}. "tiff" ALWAYS also writes "coverage".
    Polls `cancel` between outputs and around the render, so the user can stop a 74 s alpha render.
    """
    t0 = time.time()
    outputs = list(dict.fromkeys(outputs or []))            # de-dup, keep order
    bad = [o for o in outputs if o not in OUTPUT_KINDS]
    if bad:
        raise ValueError(f"unknown output kind(s): {bad!r}; expected a subset of {list(OUTPUT_KINDS)}")
    if not outputs:
        raise ValueError("nothing requested: `outputs` is empty")
    if render_mode not in ("feather", "median", "alpha"):
        raise ValueError(f"unknown render_mode {render_mode!r} (expected feather|median|alpha)")

    basename = _safe_basename(basename)
    out_dir = _guard_out_dir(Path(out_dir), session)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Validate the document **as it will be exported** — i.e. after project.normalise + stamp, which
    # is exactly what `to_gt` / `to_positions_csv` / `qc_report` each do. Validating the raw posted
    # doc instead would report every derived field the export is about to fix (origin not yet at
    # [0,0], gaps not yet recomputed), which is noise. What survives normalisation is a REAL problem.
    # The export still writes — refusing to write somebody's afternoon of work over a derived field
    # would be worse — but every problem lands in the QC report and in the job result.
    #
    # 🔴 AND KEEP THE STAMPED DOC. Every writer below must describe the document AS EXPORTED, not as
    # posted. `project.to_gt` -> `stamp()` re-derives the provenance verdict from the tiles' own
    # history (`project.machine_evidence`), so a doc whose provenance block has been hand-edited to
    # claim independence gets its `independent_of_method: false` and its warning put BACK.
    # `_tiff_description` used to read the RAW posted provenance instead — so a laundered doc
    # produced a GT JSON that correctly said "NOT AN INDEPENDENT GROUND TRUTH" beside a TIFF whose
    # header cheerfully said "hand-placed from scratch; no build seeded it". The header lied, on
    # precisely the path that has already destroyed one benchmark in this project.
    stamped = project.to_gt(doc, APP_VERSION)
    problems = project.validate(stamped)

    files: list[dict] = []
    n_phases = 1 + len(outputs)
    idx = 0

    positions = render_positions(doc, include_unverified)
    needs_pixels = bool({"tiff", "png"} & set(outputs))
    if needs_pixels and not positions:
        raise ValueError("nothing to render: no tile is `anchored`"
                         + ("" if include_unverified else " (and `unverified` tiles were excluded)"))

    # ⭐⭐ TWO RENDERS, BECAUSE THEY ARE TWO DIFFERENT THINGS — and conflating them was a real bug.
    #
    #   * the PNG  -> `flat=True`:  vignette-corrected AND per-tile exposure-normalised onto the
    #     session `level`. That per-tile gain is what makes every tile agree in brightness, which is
    #     what makes the ONE global tone window (and Difference mode) mean anything. It is a PICTURE.
    #   * the TIFF -> `flat=False`: **raw camera counts**, exactly as API.md §12 specifies and as the
    #     file's own ImageDescription has always claimed. It is a MEASUREMENT.
    #
    # 🔴 Before this, BOTH came from the `flat=True` render, and the TIFF's header said
    # `pixels=RAW CAMERA COUNTS`. Measured: trial 11's median 2111 -> 3435 (x1.63), trial 16's
    # 2702 -> 3528 (x1.31). A biologist doing photometry in Fiji was reading exposure-normalised
    # numbers out of a file that swore they were raw — and a per-tile gain is precisely the operation
    # this project forbids everywhere else.
    #
    # Cost: one extra render only when BOTH are asked for (feather: +1.1 s; alpha: +74 s — and alpha
    # is already a 74 s opt-in with a cancel button).
    img = cov = None            # the DISPLAY render (flat-fielded) -> the PNG
    raw = rcov = None           # the RAW render (camera counts)    -> the TIFF
    shown = shown_cov = None    # whichever exists — the geometry is identical either way
    if needs_pixels:
        idx += 1
        _check(cancel)
        if "png" in outputs:
            _say(report, "render", idx, n_phases, 0.0,
                 f"rendering {len(positions)} tiles for the display PNG ({render_mode})")
            img, cov = _render(session, positions, render_mode, report, cancel, flat=True)
        if "tiff" in outputs:
            _say(report, "render", idx, n_phases, 0.0,
                 f"rendering {len(positions)} tiles as RAW CAMERA COUNTS for the TIFF ({render_mode})")
            raw, rcov = _render(session, positions, render_mode, report, cancel, flat=False)
        _check(cancel)
        shown = img if img is not None else raw
        shown_cov = cov if cov is not None else rcov
        _say(report, "render", idx, n_phases, 100.0 * idx / n_phases,
             f"canvas {shown.shape[1]}x{shown.shape[0]} px, "
             f"{100.0 * float(shown_cov.mean()):.1f} % covered")

    for kind in outputs:
        _check(cancel)
        idx += 1
        _say(report, kind, idx, n_phases, 100.0 * (idx - 0.5) / n_phases, f"writing {kind}")

        if kind == "tiff":
            files += write_tiff(raw, rcov, out_dir / f"{basename}.tif",
                                description=_tiff_description(stamped, session, positions,
                                                              render_mode, rcov, um_per_px),
                                um_per_px=um_per_px)
        elif kind == "png":
            files.append(write_png(img, cov, getattr(session, "tone", None),
                                   out_dir / f"{basename}.png"))
        elif kind == "positions":
            files.append(write_positions(doc, out_dir / f"{basename}_positions.csv",
                                         include_unverified))
        elif kind == "gt":
            files.append(write_gt(doc, out_dir / f"{basename}_gt.json", APP_VERSION))
        elif kind == "qc":
            files += write_qc(doc, out_dir / f"{basename}_qc.json", out_dir / f"{basename}_qc.md",
                              render=dict(mode=render_mode, n_rendered=len(positions),
                                          include_unverified=bool(include_unverified),
                                          coverage_pct=(round(100.0 * float(shown_cov.mean()), 2)
                                                        if shown_cov is not None else None),
                                          canvas=([int(shown.shape[1]), int(shown.shape[0])]
                                                  if shown is not None else None),
                                          tiff_pixels="raw camera counts (no flat-field, no gain)",
                                          png_pixels="flat-fielded + per-tile gain to the session "
                                                     "level, then ONE global tone window"),
                              scale=scale_metadata(um_per_px),
                              problems=problems)

    _say(report, "done", n_phases, n_phases, 100.0, f"wrote {len(files)} files")
    return {"files": files, "seconds": round(time.time() - t0, 2), "warnings": problems}


def _safe_basename(basename: str) -> str:
    b = (basename or "").strip().strip(". ")
    if not b or any(c in b for c in '\\/:*?"<>|'):
        raise ValueError(f"bad basename: {basename!r}")
    return b


def _guard_out_dir(out_dir: Path, session) -> Path:
    """⛔ `data/` IS NEVER WRITTEN TO. Refuse an export directory inside the acquisition mirror."""
    out = Path(out_dir).expanduser().resolve()
    forbidden = [REPO_ROOT / "data"]
    dd = getattr(session, "data_dir", None)
    if dd:
        forbidden.append(Path(dd).resolve())
    for f in forbidden:
        try:
            f = f.resolve()
        except OSError:
            continue
        if out == f or f in out.parents:
            raise ValueError(f"refusing to export into the read-only data mirror: {out}")
    return out


# =============================================================================
# RENDER — delegated to engine.py, the ONLY module allowed to touch analysis/mosaic/
# =============================================================================
def _render(session, positions, mode, report, cancel, flat: bool = True
            ) -> tuple[np.ndarray, np.ndarray]:
    """`engine.render_mosaic` -> (img, coverage = bool).

    ⭐ `flat=False` -> **RAW CAMERA COUNTS** (the TIFF). `flat=True` -> flat-fielded and per-tile
    exposure-normalised onto the session level (the display PNG, whose global tone window lives in
    exactly that space). They are different pixels and they are not interchangeable — see
    `engine.render_mosaic`.

    ⚠️ THE COVERAGE MASK IS NOT OPTIONAL, AND IT IS NOT A NICETY. `mosaic.render.render` writes
    background as exactly `0.0` and there is no alpha channel, so "no data" and "black tissue" are
    the SAME NUMBER. On the shipped 312-tile build that is **13.1 % of the canvas**. The mask is
    free (the union of the tile rectangles == `wsum > 0` in the feather path) and without it the
    two merge forever.

    ⚠️ `engine.render_mosaic`'s progress callback is `report(pct, message)` — NOT the
    `report(Progress)` that `jobs.submit_thread` hands us. API.md does not pin engine's internal
    callback shape, so we adapt rather than assume; `_render_cb` accepts either.
    """
    try:
        img, cov = engine.render_mosaic(session, positions, mode=mode,
                                        report=_render_cb(report, mode, len(positions)),
                                        cancel=cancel, flat=flat)
    except RuntimeError as e:                   # engine raises RuntimeError("cancelled") on the flag
        if _is_cancelled(cancel):
            raise Cancelled("export cancelled during the render") from e
        raise
    img = np.asarray(img)
    cov = np.asarray(cov, bool)
    if cov.shape != img.shape:                  # mode="alpha" is 1 px larger in each dimension
        raise ValueError(f"engine returned a {cov.shape} mask for a {img.shape} mosaic")
    return img, cov


def _render_cb(report, mode: str, n: int):
    """Adapt engine's `report(pct, message)` to the job registry's `report(Progress)`."""
    if report is None:
        return None

    def cb(*args):
        if len(args) == 1 and hasattr(args[0], "phase"):        # already a Progress
            report(args[0])
            return
        pct = float(args[0]) if args else 0.0
        msg = str(args[1]) if len(args) > 1 else f"rendering {n} tiles"
        report(Progress(phase="render", phase_index=1, n_phases=2, pct=pct,
                        message=f"{msg} ({mode})"))
    return cb


# =============================================================================
# 1. THE 16-BIT TIFF  (+ its mandatory coverage sidecar)
# =============================================================================
def write_tiff(img: np.ndarray, coverage: np.ndarray, path: Path,
               description: str | None = None, um_per_px: float | None = None) -> list[dict]:
    """**THE REAL DELIVERABLE** — a 16-bit TIFF that opens in Fiji/ImageJ at full depth.
    **Nothing in the repo writes one today.**

    `img` MUST be the **`flat=False`** render — RAW CAMERA COUNTS, no flat-field, no per-tile gain,
    no tone map. (uint16, but only ~1/20 of the range is used: the global max across all 338
    snapshots is 18,022 / 65,535, and the saturated fraction is exactly 0.0 in every frame. We do not
    rescale; Fiji has a window/level.)

    ⛔ **DO NOT PASS THE DISPLAY RENDER IN HERE.** It carries a **per-tile gain** (`level /
    median(frame)`) that drags every tile's exposure onto a common level — measured x1.63 on trial
    11, x1.31 on trial 16. That is the right thing for a picture and the wrong thing for a
    measurement, and this file's ImageDescription says, in writing, that the counts are raw. Two
    renders is cheap; a header that lies is not.

    ⚠️⚠️ **THE COVERAGE MASK IS MANDATORY, NOT A NICETY.**
    **13.1 % of the canvas is background encoded as exactly `0.0`** — indistinguishable from a
    legitimately black pixel — and **there is no alpha channel.** Written to a plain TIFF, "no data"
    and "black tissue" merge **forever**. The mask is FREE (`wsum > 0` in the feather path). It is
    written as a **sidecar 8-bit PNG** (`<basename>_coverage.png`, 0 = no data, 255 = covered) — a
    sidecar, not a second TIFF page, because a two-page TIFF confuses Fiji users and this must be
    unambiguous.

    -> [tiff entry, coverage entry]
    """
    import tifffile

    path = Path(path)
    img = np.asarray(img)
    coverage = np.asarray(coverage, bool)
    if coverage.shape != img.shape:
        raise ValueError(f"coverage {coverage.shape} does not match the mosaic {img.shape}")

    lost = int(np.count_nonzero(~np.isfinite(img)))
    u16 = np.clip(np.nan_to_num(img, nan=0.0, posinf=65535.0, neginf=0.0),
                  0, 65535).astype(np.uint16)
    u16[~coverage] = 0                        # background is EXACTLY 0 — and the mask says so
    if lost:
        warnings.warn(f"{lost} non-finite pixel(s) in the mosaic were written as 0")

    kw: dict = {}
    if description:
        kw["description"] = _ascii(description)   # TIFF ImageDescription is an ASCII tag
    if um_per_px:                              # user-supplied only — see scale_metadata()
        px_per_cm = 1e4 / float(um_per_px)
        kw["resolution"] = (px_per_cm, px_per_cm)
        kw["resolutionunit"] = "CENTIMETER"

    tmp = path.with_suffix(path.suffix + ".tmp")
    tifffile.imwrite(str(tmp), u16, photometric="minisblack", **kw)
    os.replace(tmp, path)

    cov_path = path.with_name(path.stem + "_coverage.png")
    _write_png_u8(np.where(coverage, 255, 0).astype(np.uint8), cov_path)
    return [_entry("tiff", path), _entry("coverage", cov_path)]


def _tiff_description(doc, session, positions, mode, coverage, um_per_px) -> str:
    n_anch = sum(1 for t in _tiles(doc).values() if _state_of(t) == "anchored")
    n_unv = sum(1 for t in _tiles(doc).values() if _state_of(t) == "unverified")
    prov = (doc.get("provenance") or {})
    lines = [
        f"Camea Mosaic Builder {APP_VERSION}",
        f"dataset={doc.get('dataset') or getattr(session, 'dataset', '?')}",
        f"tiles rendered={len(positions)} (anchored={n_anch}, unverified={n_unv} in the document)",
        f"render_mode={mode}",
        "pixels=RAW CAMERA COUNTS, uint16. NO flat-field, NO per-tile gain, NOT tone-mapped "
        "(Fiji has a window/level). Exposure genuinely varies ~2.4x across this run and that "
        "variation is PRESERVED here: it is data, not an artefact. The display PNG beside this "
        "file is the flat-fielded, exposure-normalised picture - use that one for figures, and "
        "this one for measurements.",
        # ⚠️ ASK THE SESSION, WHICH ASKED THE XML. This line used to assert "180-degree-flipped"
        # unconditionally while `loader.load_frame` flips CONDITIONALLY on `ax`/`ay` — a header that
        # could lie about its own coordinate frame, on the one axis this project has been burned by.
        "coordinates=top-left corners (NOT centres), in "
        + str(getattr(session, "frame_note", "the vscope-displayed (180deg-flipped) frame")),
        f"coverage={100.0 * float(np.asarray(coverage).mean()):.1f} % of this canvas is real data; "
        "the rest is background encoded as EXACTLY 0 and is INDISTINGUISHABLE from black tissue. "
        "Use the sidecar *_coverage.png (0 = no data, 255 = covered).",
    ]
    if um_per_px:
        lines.append(f"um_per_px={um_per_px} (USER-SUPPLIED BY HAND, not measured by this app)")
    else:
        lines.append("scale=PIXELS ONLY. This app does not measure um/px, so none is written. "
                     "(There is NO magnification difference between the passes: cross-pass tissue "
                     "scale = 1.0000 +/- 0.0002. The old '2.5 %' figure came from the electrode-grid "
                     "pitch, which tracks FOCUS, not magnification - see app/SCALE.md. One scale bar "
                     "spanning both passes is safe.)")
    # ⚠️ ASK THE TILES, NOT THE PROVENANCE BLOCK. `export_all` hands us the STAMPED doc, so
    # `prov` is already authoritative — but we re-derive from `project.machine_evidence` anyway,
    # because the provenance block is exactly the field a "place from scratch" button can erase
    # while every tile still sits where t33 put it. A header that lies about provenance is worse
    # than no header: it is a certificate of independence for a machine's own output.
    seeded = (bool(prov.get("seeded_from"))
              or prov.get("independent_of_method") is False
              or bool(doc.get("build"))
              or bool(project.machine_evidence(doc)))
    if seeded:
        lines.append("PROVENANCE: " + PROVENANCE_WARNING)
    else:
        lines.append("PROVENANCE: hand-placed from scratch; no build seeded it "
                     "(independent_of_method: true).")
    return "\n".join(lines)


# =============================================================================
# 2. THE DISPLAY PNG
# =============================================================================
def write_png(img: np.ndarray, coverage: np.ndarray, tone, path: Path) -> dict:
    """The display PNG, 8-bit, full resolution. For figures and slides.

    ⚠️⚠️ **TONE-MAP GLOBALLY.** One 0.5 / 99.6-percentile window across all frames after
    flat-fielding — `session.tone`, the same window every tile in the UI went through. A **per-tile**
    stretch over-brightens near-empty frames and makes overlapping tiles disagree in tone, **which
    destroys the Difference-mode check the whole verification loop depends on.** There is no
    per-tile path in this app.

    ⚠️ The shipped `mosaic.png` in the repo is NOT the mosaic — it is a matplotlib figure
    (1416x2426, 0.629x linear, 8-bit RGBA, a 1-99 stretch baked in, and a **title drawn on**). We do
    not imitate it: these are the actual pixels, at the actual size, with no decoration.
    """
    path = Path(path)
    img = np.asarray(img, np.float32)
    coverage = np.asarray(coverage, bool)
    if coverage.shape != img.shape:
        raise ValueError(f"coverage {coverage.shape} does not match the mosaic {img.shape}")

    win = _tone_lohi(tone)
    if win is None:
        # The session always carries a tone window; this is only reached if it does not. Still
        # ONE window for the WHOLE mosaic — never per tile.
        sample = img[coverage]
        if sample.size == 0:
            raise ValueError("nothing covered: cannot window an empty mosaic")
        lo, hi = (float(v) for v in np.percentile(sample, [0.5, 99.6]))
        if hi <= lo:
            hi = lo + 1.0
    else:
        lo, hi = win

    u8 = np.clip((img - lo) * (255.0 / (hi - lo)), 0, 255).astype(np.uint8)
    u8[~coverage] = 0                       # background: black, and the coverage PNG says which
    _write_png_u8(u8, path)
    return _entry("png", path)


def _write_png_u8(u8: np.ndarray, path: Path) -> None:
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(np.ascontiguousarray(u8, np.uint8), mode="L").save(buf, format="PNG")
    _atomic_bytes(Path(path), buf.getvalue())


# =============================================================================
# 3a. positions.csv
# =============================================================================
def write_positions(doc: dict, path: Path, include_unverified: bool = True) -> dict:
    """`positions.csv` — **`project.to_positions_csv(doc)`**, which normalises `origin_trial` to
    (0, 0) and writes the header **exactly** `trial,x,y,state`. The first three names are what
    `benchmark/score.py :: load_positions` reads with a `csv.DictReader`. Do not rename them.

    `include_unverified` mirrors the render flag, so the csv describes what was actually exported.
    `excluded` and `unplaced` tiles are omitted — they have no position.
    """
    text = project.to_positions_csv(doc, include_unverified)
    head = text.splitlines()[0] if text else ""
    if head != "trial,x,y,state":                       # score.load_positions reads these names
        raise ValueError(f"positions.csv header must be exactly 'trial,x,y,state', got {head!r}")
    _atomic_text(Path(path), text)
    return _entry("positions", Path(path))


# =============================================================================
# 3b. the ground-truth JSON
# =============================================================================
def write_gt(doc: dict, path: Path, app_version: str = APP_VERSION) -> dict:
    """The ground-truth JSON — `project.to_gt(doc)`. Scoreable by `analysis/benchmark/score.py`
    unchanged (it keeps only `status == "anchor"` tiles, so `unverified` ones correctly do not
    inflate the denominator).

    ⚠️ **THE PROVENANCE STAMP IS MANDATORY** (API.md §11.4, project_schema.json). It says out loud,
    in the file, that this is **"a build a human signed off on", NOT an independent ground truth**,
    and that it **must never be used to score the solver that produced it**. Pass 1's truth got four
    tiles wrong exactly this way, and this project has already destroyed one benchmark by
    overwriting it with an algorithm's output.

    ⛔ **`score.robust_align` IS NOT REIMPLEMENTED ANYWHERE IN THIS FILE.** (A reimplementation with
    a different tie-break scored the same positions 152/156 where the canonical one gives 155/156.)
    The exporter does not align or score anything: it writes the document, and `benchmark/score.py`
    imports its own `robust_align` when somebody scores it.
    """
    gt = _assert_scoreable(project.to_gt(doc, app_version))
    _atomic_text(Path(path), json.dumps(gt, indent=1, ensure_ascii=False, default=_jsonable))
    return _entry("gt", Path(path))


def _jsonable(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, Path):
        return str(o).replace("\\", "/")
    return vars(o)          # t33's info nests a t27.Config: json.dumps CRASHES without this


def _assert_scoreable(gt: dict) -> dict:
    """The two lines `score.load_gt()` actually reads, checked before the file leaves the process.

        doc["tiles"][k]["status"] == "anchor"  ->  x / y
        doc["tolerance_px"]["region_default"]  ->  the fallback per-tile r

    A project the scorer cannot read is a project that cannot be checked. Keep it that way.
    """
    tol = gt.get("tolerance_px") or {}
    if "region_default" not in tol:
        raise ValueError("GT export is missing tolerance_px.region_default — score.load_gt() would "
                         "KeyError on any tile without an explicit `r`")
    n_anchor = 0
    for k, v in (gt.get("tiles") or {}).items():
        if not str(k).isdigit():
            raise ValueError(f"tile key {k!r} is not a decimal trial number")
        if v.get("status") == "anchor":
            if v.get("x") is None or v.get("y") is None:
                raise ValueError(f"tile {k} is status=anchor with a null position")
            n_anchor += 1
    if n_anchor == 0:
        warnings.warn("the exported GT has ZERO anchor tiles — score.py would find nothing to score")
    return gt


# =============================================================================
# 4. THE QC REPORT — what the human did vs what the machine said
# =============================================================================
def write_qc(doc: dict, path_json: Path, path_md: Path,
             render: dict | None = None, scale: dict | None = None,
             problems: list[str] | None = None) -> list[dict]:
    """The QC report — **`project.qc_report(doc)`** — as both `.json` and a human-readable `.md`.

    What the human did vs what the machine said: accepted unchanged, moved (and by how far, per
    tile, sorted worst first), excluded, still unverified, rescued. **This is also the honest
    provenance record**, and it is what makes the mosaic safe to hand to somebody else. Every
    number states its denominator (156 / 156 / 312 on this data).

    `project.qc_report` owns the *document* half of the report. This function adds the two things
    only the exporter knows — **what was actually rendered** (mode, tile count, and the coverage
    fraction that the TIFF cannot express on its own) and **the scale policy** — and appends them
    to both files.
    """
    qc, md = project.qc_report(doc, APP_VERSION)
    qc = dict(qc)
    if render:
        qc["render"] = render
    if scale:
        qc["scale"] = scale
    if problems:
        qc["document_problems"] = problems
    md = md.rstrip("\n") + "\n" + _qc_export_markdown(render, scale, problems)
    _atomic_text(Path(path_json), json.dumps(qc, indent=1, ensure_ascii=False, default=_jsonable))
    _atomic_text(Path(path_md), md)
    return [_entry("qc", Path(path_json)), _entry("qc", Path(path_md))]


def _qc_export_markdown(render: dict | None, scale: dict | None, problems: list[str] | None) -> str:
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
        if render.get("coverage_pct") is not None:
            A(f"- **{render['coverage_pct']} % of the canvas is real data.** The remaining "
              f"{round(100.0 - render['coverage_pct'], 2)} % is background encoded as **exactly 0**, "
              "which is indistinguishable from a legitimately black pixel — the 16-bit TIFF has no "
              "alpha channel. That is what the sidecar `*_coverage.png` is for (**0 = no data, "
              "255 = covered**). Without it, *empty* and *black* merge forever.")
        A("")
    A("## Scale")
    A("")
    if scale and scale.get("um_per_px"):
        A(f"**{scale['um_per_px']} µm/px — {scale.get('source')}.** This number was typed in by the "
          "user; **this app did not measure it.** One value is the right shape: there is **no "
          "magnification difference between the passes** (cross-pass tissue scale **1.0000 ± "
          "0.0002**, `app/SCALE.md`), so a single scale bar spanning both passes is safe. ⚠️ Do not "
          "use **1.237 µm/px** — it came from an inference that has been proven wrong.")
    else:
        A("**Pixels only.** No scale bar, no OME-TIFF `PhysicalSizeX/Y` — this app does not measure "
          "µm/px. ⚠️ The old warning about *'a 2.5 % magnification difference between the passes'* "
          "was **WRONG and is now settled** (`app/SCALE.md`): the MEA grid pitch tracks **focus**, "
          "not magnification — it swings 3.5 % across five frames taken on a *stationary* stage, "
          "while the fitted tissue scale stays flat. Cross-pass scale is **1.0000 ± 0.0002**. "
          "Calibrate from the **stage**, not the grid.")
    A("")
    if problems:
        A("## ⚠️ Document problems (`project.validate`)")
        A("")
        A("The export was written anyway — these are reported, not silently repaired:")
        A("")
        for p in problems:
            A(f"- {p}")
        A("")
    A("## Caveats that apply to every number above")
    A("")
    A("- **Pass-1 tiles have no per-tile confidence at all.** t27's `info` is aggregate-only, and "
      "the worst tile in the shipped 312/312 build (**127, at 9.94 px**) is a *pass-1* tile. The "
      "absence of a warning on a pass-1 tile is **not** a clean bill of health.")
    A("- **A thin margin (< 0.10) is the signature of a surviving alias.** The shipped build's "
      "worst run margin is 0.081 against a ~0.47 typical.")
    A("- **Blur is not measured here, and must not be.** Across 15 focus measures the best global "
      "blur threshold reaches F1 = 0.37, and variance-of-Laplacian scores *worse than chance*. "
      "Every blur call in this document is a human's. `blank`, by contrast, *is* measured.")
    A("")
    return "\n".join(L)


# =============================================================================
# 📏 Physical scale
# =============================================================================
def scale_metadata(um_per_px: float | None) -> dict:
    """⛔ **THE EXPORTER WRITES PIXELS ONLY. `um_per_px` DEFAULTS TO None AND STAYS None.**

    No scale bar. No OME-TIFF `PhysicalSizeX/Y` — **this app does not measure µm/px.**

    ⚠️ **THE OLD WARNING HERE WAS WRONG, AND SAYING IT IN AN EXPORTED FILE WAS WORSE.** It asserted
    "a 2.5 % magnification difference between the passes, not yet resolved". It IS resolved
    (`app/SCALE.md`): the MEA grid pitch tracks **FOCUS**, not stage magnification — across the five
    frames of the pass-boundary dwell (a *stationary* stage, tissue NCC ~1.000) the pitch swings
    14.22 -> 13.84 while the fitted tissue scale stays flat at 1.0010 ± 0.0001. Cross-pass tissue
    scale is **1.0000 ± 0.0002**, > 80 sigma from 1.025. **There is no magnification difference, and
    ONE scale bar spanning both passes is safe.**

    If — and only if — the user fills the optional µm/px field in by hand, we write physical units
    AND record `"source": "user-supplied"`, so nobody later mistakes a typed-in number for a
    measured one. ❌ 1.237 µm/px (pass 1) came from the broken inference — never use it.
    """
    NOTE = ("This app does NOT measure um/px. There is no magnification difference between the "
            "passes (cross-pass tissue scale 1.0000 +/- 0.0002, app/SCALE.md), so ONE scale is the "
            "right shape and a single scale bar spanning both passes is safe. The MEA grid pitch is "
            "NOT a valid calibration - it tracks focus. Calibrate from the stage.")
    if um_per_px is None:
        return {"um_per_px": None, "source": "unknown",
                "note": "PIXELS ONLY. No physical scale is written and no scale bar is drawn. " + NOTE}
    v = float(um_per_px)
    if not np.isfinite(v) or v <= 0:
        raise ValueError(f"um_per_px must be a positive number, got {um_per_px!r}")
    return {"um_per_px": v, "source": "user-supplied",
            "note": "SUPPLIED BY HAND by the user - NOT measured by this app. " + NOTE}
