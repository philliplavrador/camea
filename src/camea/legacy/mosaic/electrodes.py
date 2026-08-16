"""Map the electrode grid of the BUILT snapshot mosaic (2026-08-11).

An optional post-build stage: render the placed tiles into the same composite the export
draws (feather, flat=True — a picture is the right substrate for a matched filter), hand
it to `core.electrodegrid`, and store every electrode's `column-row` identity.

COORDINATES — the one subtlety worth reading twice. `engine.render` puts canvas (0,0) at
the top-left-most RENDERED tile: `canvas = rint(world - min(world))`. The map therefore
comes back in canvas px and is SHIFTED INTO DOCUMENT WORLD COORDS before it is written,
with `canvas_offset` (= that min) recorded so the rendered PNG/TIFF space stays reachable.
The viewer works in world coords, so its clicks need no translation at all.

STALENESS. The map describes the tile positions it was computed from — `positions_stamp`
checksums them (2 dp, the export's own precision) into `electrodes.source_stamp`. Any
sweep edit or recompute changes the stamp and the UI shows "stale — re-run" instead of
silently highlighting drifted centres. (`normalise()` may also translate every tile when
the origin re-pins; the stamp catches that identically.)

The document is CLIENT-owned in this feature (like export, unlike the videomosaic build):
the job returns the `electrodes` block and the UI merges + saves.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

from camea.core import jobs

PHASES = ("render", "fit", "write")

#: phase -> (start_pct, end_pct). 🔴 **`pct` IS OVERALL, ACROSS THE WHOLE JOB (R48.5)** — and this
#: stage is the ruling's own example of getting it wrong. Every phase used to report its own scale:
#: render emitted `0.0`, fit crawled 0 -> 83, and then write emitted `0.0` again, so the last thing
#: the user saw before the map appeared was the bar snapping back to empty.
#:
#: The weights are what this stage has been measured at, not guesses about it: `fit_grid` takes
#: **~6 s** on the real 5319 x 7356 mosaic (`utils/knowledge/electrodes.md` — 6.1 s on the video
#: mosaic, 5.9 s on P003693), a `feather` `render_mosaic` **~1.1 s**, and writing the JSON + CSV of
#: 26,400 cells is well under a second. ⛔ These are the algorithm's proportions, not any dataset's:
#: the fit dominates because it FFTs and matched-filters a 39 Mpx canvas, whatever produced it.
_SPAN = {"render": (0.0, 15.0), "fit": (15.0, 97.0), "write": (97.0, 100.0)}


def _emitter(report: Callable | None, t0: float) -> Callable[[str, float, str], None]:
    """`emit(phase, frac, message)` — maps a phase-local 0..1 into that phase's slice of the whole
    job and derives the ETA from **the overall pct** (R48.3/R48.5).

    ⚠️ `frac` is 0..1 and `Progress.pct` is 0-100. That conversion lives HERE and nowhere else — a
    fraction handed straight to `Progress.pct` freezes the UI bar at its floor, which this stage has
    already done once.

    ⛔ Nothing here runs on a timer. With `pct` pinned, a clock-driven re-emit makes the ETA count
    *up* — that is R8b, and R48b did not lift it. Call this only where the counter moved.
    """
    def emit(phase: str, frac: float, message: str) -> None:
        lo, hi = _SPAN[phase]
        pct = lo + (hi - lo) * min(1.0, max(0.0, float(frac)))
        # ⚠️ `phase_index` stays 0-based here: the UI renders `phaseIndex + 1`.
        jobs.say(report, phase, PHASES.index(phase), len(PHASES), pct, message,
                 jobs.eta_from_fraction(time.monotonic() - t0, pct / 100.0))

    return emit


def positions_stamp(doc: dict, *, include_unverified: bool = True) -> str:
    """Checksum of the placed positions a map is computed FROM. 2 dp — the precision the
    export itself writes — so float jitter below what anyone can see never fakes an edit."""
    from . import document as mdoc  # noqa: PLC0415

    pos = mdoc.positions(doc, include_unverified=include_unverified)
    blob = json.dumps(
        [[int(t), round(float(x), 2), round(float(y), 2)]
         for t, (x, y) in sorted(pos.items())],
        separators=(",", ":"),
    )
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def map_electrodes(
    frames: Any,
    doc: dict,
    out_dir: str | Path,
    basename: str,
    *,
    include_unverified: bool = True,
    array_coverage: str = "partial",
    report: Callable | None = None,
    cancel: Any = None,
) -> dict:
    """Render → fit → write. Returns `{"electrodes": <block>}` for the job result; the
    files land in `out_dir` (= `<project>/outputs/`, R44) named `<basename>-electrodes.*`.

    `array_coverage` is the user's own declaration (R45.8), never inferred: `"full"` means he
    says the whole MaxOne/MaxTwo chip is in frame, so the fit is held to 220 × 120 and a near
    miss is corrected; `"partial"` enforces nothing but the 17.5 µm scale. Default `"partial"`
    — the assumption-free mode — because a silent map must never claim the whole chip."""
    from camea.core import electrodegrid  # noqa: PLC0415 — cv2/scipy stay out of import time
    from . import document as mdoc  # noqa: PLC0415
    from . import export as mexport  # noqa: PLC0415

    out_dir = Path(out_dir)
    positions = mdoc.positions(doc, include_unverified=include_unverified)
    emit = _emitter(report, time.monotonic())

    emit("render", 0.0, "rendering the mosaic")
    # ⏱️ The countable unit of the render is TILES — `render_mosaic`'s sink already scrapes
    # `rendered k/N` out of the compositor's stdout, and passing nothing here threw it away.
    img, cov = mexport.render_mosaic(
        frames, positions, mode="feather", flat=True, cancel=cancel,
        report=(lambda pct, *_: emit("render", float(pct) / 100.0, "rendering the mosaic"))
        if report is not None else None)

    # the canvas↔world tie: engine.render subtracts the elementwise min over the tiles it
    # actually drew — recompute it over the SAME filtered position set the render used
    valid = mexport._valid_positions(frames, positions)
    import numpy as np  # noqa: PLC0415

    arr = np.array([p for p in valid.values()], float)
    offset = (float(arr[:, 0].min()), float(arr[:, 1].min()))

    def fit_progress(msg: str) -> None:
        jobs.check_cancelled(cancel, "electrode map")
        # ⏱️ The six fit steps are NOT equal cost — `electrodegrid.FIT_SPAN` is the measured shape,
        # and dividing by six is what made this bar crawl through `indexing` and then leap (R48.5).
        # ⛔ ONE copy of that measurement, and it is the engine's: the videomosaic electrode map
        # reads the same table. `fit_grid` announces a step BEFORE running it, so the step's own `lo`
        # is how far the fit has actually got.
        lo, _hi = electrodegrid.FIT_SPAN.get(msg, (0.0, 0.0))
        emit("fit", lo, msg)

    # ⭐ R45.8. The device spec goes in for BOTH coverage modes — it is what buys the µm scale
    # (17.5 µm over the pitch this image measures). Only `enforce_shape` is conditional: the
    # 220 × 120 rule binds when, and only when, HE said the whole chip is in frame. A far-off
    # fit under `full` raises NoGridFound and the job fails saying so — never a quiet fudge.
    gm = electrodegrid.fit_grid(np.asarray(img, np.float32), valid=cov,
                                progress=fit_progress,
                                device=electrodegrid.MAXWELL,
                                enforce_shape=(array_coverage == "full"))

    # the last boundary a stop can be taken at: everything after this writes files (R48.7)
    jobs.check_cancelled(cancel, "electrode map")
    emit("write", 0.0, "writing the electrode table")
    built_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    # canvas px -> document world px (the viewer's own space)
    payload = electrodegrid.full_payload(
        gm,
        canvas_offset=offset,
        coordinates=str(doc.get("coordinates") or "") or None,
        built_at=built_at,
        source_stamp=positions_stamp(doc, include_unverified=include_unverified),
        include_unverified=include_unverified,
        array_coverage=array_coverage,
        feature="mosaic",
        space="document world px (rendered-canvas px + canvas_offset)",
    )

    names = {"map": f"{basename}-electrodes.json", "csv": f"{basename}-electrodes.csv"}
    electrodegrid.write_map_files(payload, out_dir / names["map"], out_dir / names["csv"])
    emit("write", 1.0, f"wrote {names['map']} and {names['csv']}")

    # R45.8: the DOCUMENT keeps the block, so a reopened project still knows whether `1-1` is the
    # chip's corner or only the imaged region's, and the panel can say "whole chip · +1 col
    # corrected · 1.25 µm/px" without re-reading the table. `summary_block` carries the coverage,
    # the scale and the device name; both features record them identically, from the same place.
    block = electrodegrid.summary_block(
        gm, built_at=built_at, outputs=names,
        source_stamp=payload["source_stamp"], coordinates=payload["coordinates"],
        array_coverage=array_coverage)
    return {"electrodes": block}


def recorded_map_name(doc: dict) -> str | None:
    """The map filename `doc[\"electrodes\"]` names, if the block has been saved yet."""
    name = (((doc.get("electrodes") or {}).get("outputs")) or {}).get("map")
    return name if isinstance(name, str) and name else None
