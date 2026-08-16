"""Region recordings: where on the mosaic a fixed-field calcium video was taken.

**The experiment this serves.** A culture sits on an MEA chip. While the chip records voltages,
a few REGIONS are also filmed with calcium imaging at high magnification, stage parked. At the
end one calcium video sweeps the whole chip and becomes the mosaic. Locating each fixed-region
recording on that mosaic, and naming the electrodes underneath it, is what pairs an MEA
channel's voltage trace with the calcium trace of the neuron sitting on top of it. That pairing
is the ground-truth dataset — the point of the whole app.

This module is the glue: decode -> measure the zoom -> match -> name the electrodes -> write.
The matching itself is `core.locate` (feature-agnostic); the lattice is `core.electrodegrid`.

⭐ **The human has the last word.** A located region lands `unconfirmed` with its evidence on
show (NCC, margin, which still won, and the alternatives). Drag it and snap it; press Confirm
and it becomes yours. Nothing here ever promotes itself — the same rule as I3 for anchors.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

PHASES = ("decode", "zoom", "match", "electrodes", "write")

DEFAULT_STILL_FRAMES = 24
"""How many frames are sampled to build the stills.

⭐ **Measured trade-off, not a guess.** The decode is a single forward pass whose cost is set by
the LAST index wanted, so sampling across the whole recording costs the same as sampling its
end — the frames in between are skipped with `grab()`, which does not pay for colour
conversion. So the only thing this number buys or costs is the median/max/std quality and the
peak memory (24 frames of 1080p as float32 is ~200 MB, and it is freed before the match's own
FFTs allocate). Below ~12 the median is visibly noisy; above ~32 nothing measurable improves.
"""

STATUS_UNCONFIRMED, STATUS_CONFIRMED = "unconfirmed", "confirmed"


# =================================================================================================
# Reading the recording
# =================================================================================================
def stills_from_video(path: str | Path, *, n_frames: int = DEFAULT_STILL_FRAMES,
                      report: Callable[..., None] | None = None,
                      cancel: Any = None) -> tuple[dict, Any]:
    """`({kind: still}, VideoInfo)` — one forward pass, three pictures.

    ⚠️ A fixed-field recording is not a survey and must not be treated as one: `pipeline.build`
    refuses a still video on purpose ("a mosaic needs a survey, not a still"). This is the other
    side of that guard — the case where the stage NOT moving is the whole point.
    """
    from camea.core import jobs as core_jobs
    from camea.core import locate

    from .video import probe, read_frames_at

    info = probe(path)
    want = locate.sample_indices(info.n_frames or 0, n_frames)
    if not want:
        # a container that will not admit its length: take the opening frames rather than fail
        want = list(range(n_frames))

    frames: list[np.ndarray] = []

    def consume(_idx: int, gray: np.ndarray) -> None:
        core_jobs.check_cancelled(cancel, "locate region")
        frames.append(np.asarray(gray, np.float32))

    def prog(done: int, total: int) -> None:
        core_jobs.say(report, "decode", 0, len(PHASES), 100.0 * done / max(1, total),
                      f"reading the recording ({done}/{total} frames)")

    read_frames_at(path, want, consume, progress=prog)
    if not frames:
        from .video import VideoError
        raise VideoError(f"{info.name} decoded no frames — the stream may be truncated")
    return locate.still_stack(frames), info


# =================================================================================================
# Locating one region
# =================================================================================================
def region_id(video_path: str | Path, existing: set[str] | None = None) -> str:
    """A stable short id from the video's resolved path, made unique against `existing`."""
    rp = Path(video_path).resolve().as_posix().lower()
    base = hashlib.sha1(rp.encode("utf-8")).hexdigest()[:10]
    used = existing or set()
    if base not in used:
        return base
    for k in range(2, 100):
        cand = f"{base}-{k}"
        if cand not in used:
            return cand
    raise ValueError("cannot allocate a region id")


def locate_region(doc: dict, out_dir: Path, basename: str, video_path: str | Path, *,
                  name: str | None = None, rid: str | None = None,
                  report: Callable[..., None] | None = None, cancel: Any = None) -> dict:
    """Place one fixed-field recording on this project's built mosaic. -> the region record."""
    from camea.core import electrodegrid
    from camea.core import jobs as core_jobs
    from camea.core import locate

    from . import canvas as vcanvas

    out_dir = Path(out_dir)
    stills, info = stills_from_video(video_path, report=report, cancel=cancel)

    core_jobs.say(report, "zoom", 1, len(PHASES), 0.0, "reading the mosaic")
    arr, valid = vcanvas.read_mosaic(doc, out_dir)
    core_jobs.check_cancelled(cancel, "locate region")

    # ⭐ The mosaic's own lattice: its PITCH is the ruler that gives the zoom, and its AXES are
    # what `notch_lattice` needs to delete the comb. Prefer the numbers the electrode map
    # already measured — the pipeline maps electrodes before this step, and re-measuring would
    # be a second answer to a question already answered — but measure if it is absent.
    # ⚠️ a1/a2 live in the map FILE, not in the document's summary block, which carries only
    # the pitch and the angle. The file is read once here and reused for the electrode names.
    emap = load_map(doc, out_dir) or {}
    pitch_mosaic = float(emap.get("pitch_px") or 0.0)
    angle_mosaic = emap.get("angle_deg")
    a1 = emap.get("a1")
    a2 = emap.get("a2")
    if not (pitch_mosaic > 0 and isinstance(a1, (list, tuple)) and isinstance(a2, (list, tuple))):
        core_jobs.say(report, "zoom", 1, len(PHASES), 30.0, "measuring the mosaic's lattice")
        try:
            v1, v2, _snr = electrodegrid.lattice_axes(arr, valid)
            a1, a2 = list(v1), list(v2)
            pitch_mosaic = float((np.hypot(*v1) + np.hypot(*v2)) / 2)
            angle_mosaic = float(np.degrees(np.arctan2(v1[1], v1[0])))
        except Exception:                                          # noqa: BLE001
            a1 = a2 = None

    core_jobs.say(report, "zoom", 1, len(PHASES), 70.0, "measuring the recording's lattice")
    # ⭐ ALL the stills go in, not just the median: `measure_zoom` requires two independent
    # projections to agree on the pitch before it will call the zoom MEASURED.
    zoom = locate.measure_zoom(stills, pitch_mosaic,
                               float(angle_mosaic) if angle_mosaic is not None else None)

    ref, refmask = locate.prepare_reference(arr, valid)

    def prog(msg: str) -> None:
        core_jobs.check_cancelled(cancel, "locate region")
        core_jobs.say(report, "match", 2, len(PHASES), 0.0, msg)

    lattice = (a1, a2) if (a1 is not None and a2 is not None) else None
    loc = locate.locate(ref, refmask, stills, zoom, lattice=lattice, progress=prog)

    core_jobs.say(report, "electrodes", 3, len(PHASES), 0.0, "naming the electrodes")
    cells = electrodes_under(doc, out_dir, loc.x, loc.y, loc.w, loc.h, payload=emap or None)

    core_jobs.say(report, "write", 4, len(PHASES), 0.0, "writing the region")
    # 🔴 NOT uniquified against the existing regions. The id is a hash of the video's path in
    # the project, and `_adopt_video` deliberately does not copy the same file twice — so
    # re-locating a recording must REPLACE its region, not add a second one pointing at the same
    # file. Uniquifying here made the route's replace-by-id filter dead code and produced exactly
    # that duplicate. (Found by the API tests, 2026-08-11.)
    rid = rid or region_id(video_path)
    still_name = f"{basename}-region-{rid}-still.png"
    write_still(stills[loc.still_kind], loc.zoom.scale, out_dir / still_name)

    src = info.to_json()
    return {
        "id": rid,
        "name": (name or "").strip() or Path(str(src.get("name") or video_path)).stem,
        "source": src,
        "still": still_name,
        "status": STATUS_UNCONFIRMED,
        "placed_by": "machine",
        "located_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_stamp": str((doc.get("build") or {}).get("built_at") or ""),
        "electrodes": cells,
        **loc.to_json(),
    }


def resnap_region(doc: dict, out_dir: Path, region: dict, at: tuple[float, float], *,
                  radius: int | None = None, report: Callable[..., None] | None = None,
                  cancel: Any = None) -> dict:
    """*"I dragged it here — now snap it."* A bounded local re-search at the region's SETTLED
    scale, seeded where the user dropped it.

    ⭐ The rectangle keeps the size the locating run measured. The user is correcting WHERE the
    field is, not how big it is, and re-deriving the zoom from a hand position would let one
    correction quietly undo the other.
    """
    from camea.core import jobs as core_jobs
    from camea.core import locate

    from . import canvas as vcanvas

    out_dir = Path(out_dir)
    still_path = out_dir / str(region.get("still") or "")
    core_jobs.say(report, "decode", 0, 2, 0.0, "reading the recording's picture")
    still = read_still(still_path)

    core_jobs.say(report, "match", 1, 2, 0.0, "matching where you dropped it")
    arr, valid = vcanvas.read_mosaic(doc, out_dir)
    ref, refmask = locate.prepare_reference(arr, valid)
    core_jobs.check_cancelled(cancel, "snap region")

    # the still on disk is ALREADY at mosaic scale (see `write_still`), so it goes in at 1.0
    tpl, tmsk = locate.prepare_template(still, 1.0)
    # ⭐ THE SEARCH MUST COVER THE DRAG. How far he moved it is the only honest scale for the
    # window: at fit zoom on a 5319 x 7356 mosaic a 40 px nudge of the mouse is 506 mosaic px,
    # so a fixed radius that reads as generous cannot reach back from an ordinary gesture.
    # (Measured before the fix: a 506 px drag snapped 450 px from the truth at NCC 0.51.)
    was = (float(region.get("x") or 0.0), float(region.get("y") or 0.0))
    moved = float(np.hypot(float(at[0]) - was[0], float(at[1]) - was[1]))
    emap = load_map(doc, out_dir) or {}
    a1, a2 = emap.get("a1"), emap.get("a2")
    lattice = ((a1, a2) if isinstance(a1, (list, tuple)) and isinstance(a2, (list, tuple))
               else None)
    # ⭐ The half-width ACTUALLY searched: the caller's ask (or the drag-derived default) through
    # the same clamp `locate.snap` applies — recorded on the region so a result can quote what
    # was looked at, never what was asked for.
    r_used = int(max(8, min(int(radius or locate.snap_radius_for(moved)),
                            locate.SNAP_RADIUS_MAX)))
    out = locate.snap(ref, refmask, tpl, tmsk, at, radius=r_used, lattice=lattice)
    if out.best is None:
        raise locate.NoLocation(out.refused or "nothing measurable where you dropped it")

    moved = float(np.hypot(out.best.x - float(at[0]), out.best.y - float(at[1])))
    updated = dict(region)
    updated.update({
        "x": round(out.best.x, 2), "y": round(out.best.y, 2),
        "w": float(tpl.shape[1]), "h": float(tpl.shape[0]),
        "ncc": round(out.best.ncc, 4),
        # ⚠️ The GLOBAL margin is not re-stated here and must not be: a local search's runner-up
        # is a neighbouring shoulder inside the window, not a rival place on the mosaic, so
        # quoting it as "the margin" would be a reassuring number about nothing.
        "snap_margin": round(out.margin, 4) if out.margin is not None else None,
        "snap_radius_px": r_used,
        "moved_px": round(moved, 2),
        "placed_by": "hand+snap",
        "status": STATUS_UNCONFIRMED,
        "located_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    updated["electrodes"] = electrodes_under(
        doc, out_dir, out.best.x, out.best.y, float(tpl.shape[1]), float(tpl.shape[0]),
        payload=emap or None)
    return updated


# =================================================================================================
# The electrodes underneath
# =================================================================================================
def load_map(doc: dict, out_dir: Path) -> dict | None:
    """The full electrode-map payload this project's document names, or None."""
    from camea.core import electrodegrid

    name = ((doc.get("electrodes") or {}).get("outputs") or {}).get("map")
    return electrodegrid.load_map_file(Path(out_dir), name if isinstance(name, str) else None)


def electrodes_under(doc: dict, out_dir: Path, x: float, y: float, w: float, h: float,
                     *, payload: dict | None = None) -> dict | None:
    """Which mapped electrodes fall inside the rectangle. `None` when nothing is mapped yet.

    ⭐ **This is the answer the whole feature exists to produce.** A located rectangle is only
    interesting because it names the MEA channels whose voltages can now be paired with the
    calcium traces recorded over them.

    A centre inside the rectangle counts. Not "wholly inside", because an electrode is a point
    in this map (its centre is what the lattice fit measured), and not "within a margin",
    because that would invent a tolerance nobody asked for.
    """
    from camea.core import electrodegrid

    payload = payload or load_map(doc, out_dir)
    if not payload:
        return None
    name = ((doc.get("electrodes") or {}).get("outputs") or {}).get("map")
    cells = payload.get("cells") or {}
    xs, ys = cells.get("x") or [], cells.get("y") or []
    cols, rows = cells.get("col") or [], cells.get("row") or []
    kinds = cells.get("kind") or []
    if not xs:
        return None

    ax, ay = np.asarray(xs, float), np.asarray(ys, float)
    inside = (ax >= x) & (ax < x + w) & (ay >= y) & (ay < y + h)
    idx = np.nonzero(inside)[0]
    ids = [f"{int(cols[i])}-{int(rows[i])}" for i in idx]
    n_detected = sum(1 for i in idx
                     if i < len(kinds) and int(kinds[i]) == electrodegrid.GridMap.KIND_DETECTED)
    return {
        "count": int(idx.size),
        "detected": int(n_detected),
        "inferred": int(idx.size) - int(n_detected),
        "ids": ids,
        "cols": [int(cols[i]) for i in idx],
        "rows": [int(rows[i]) for i in idx],
        "map": name,
        "array_coverage": (doc.get("electrodes") or {}).get("array_coverage"),
        "um_per_px": (doc.get("electrodes") or {}).get("um_per_px"),
    }


# =================================================================================================
# Artifacts
# =================================================================================================
def write_still(still: np.ndarray, scale: float, path: Path) -> None:
    """The winning still, resampled to MOSAIC SCALE and toned, as a PNG.

    ⭐ Stored at mosaic scale on purpose: it is what the UI fades into the rectangle to let the
    user judge the match by eye, and it is what a re-snap matches with — so the one file serves
    both, and neither has to re-derive the zoom.
    """
    import cv2
    from PIL import Image

    img = np.asarray(still, np.float32)
    s = float(scale)
    if abs(s - 1.0) > 1e-6:
        h, w = img.shape
        img = cv2.resize(img, (max(4, int(round(w * s))), max(4, int(round(h * s)))),
                         interpolation=cv2.INTER_AREA if s < 1.0 else cv2.INTER_CUBIC)
    lo, hi = (float(v) for v in np.percentile(img, (0.5, 99.6)))
    if hi <= lo:
        lo, hi = float(img.min()), float(img.max() or 1.0)
    u8 = np.clip((img - lo) / max(1e-6, hi - lo), 0, 1)
    Image.fromarray((u8 * 255).astype(np.uint8), mode="L").save(path)


def read_still(path: Path) -> np.ndarray:
    from PIL import Image

    if not Path(path).is_file():
        raise FileNotFoundError(
            f"the recording's picture is missing ({Path(path).name}) — locate it again")
    Image.MAX_IMAGE_PIXELS = None
    return np.asarray(Image.open(path).convert("L"), np.float32)


def write_region_files(doc: dict, out_dir: Path, basename: str) -> dict[str, str]:
    """`<basename>-regions.json` + `.csv` — every located region, rewritten whole each time.

    One file for all of them rather than one per region: the list is the answer, it is always
    current, and two recordings can never collide over a filename.
    """
    out_dir = Path(out_dir)
    names = {"regions": f"{basename}-regions.json", "csv": f"{basename}-regions.csv"}
    regions = list(doc.get("regions") or [])

    payload = {
        "space": "mosaic canvas px (1:1 with the built mosaic.png); x/y are TOP-LEFT corners",
        "built_from": (doc.get("build") or {}).get("built_at"),
        "electrode_map": ((doc.get("electrodes") or {}).get("outputs") or {}).get("map"),
        "regions": regions,
    }
    _atomic_write(out_dir / names["regions"],
                  json.dumps(payload, indent=1).encode("utf-8"))

    head = ("region_id,name,video,status,placed_by,x,y,w,h,scale,still_kind,ncc,margin,"
            "confident,n_electrodes,electrode_ids\n")
    rows = [head]
    for r in regions:
        ids = " ".join((r.get("electrodes") or {}).get("ids") or [])
        rows.append(",".join([
            str(r.get("id", "")), _csv(r.get("name")), _csv((r.get("source") or {}).get("name")),
            str(r.get("status", "")), str(r.get("placed_by", "")),
            f"{float(r.get('x', 0)):.2f}", f"{float(r.get('y', 0)):.2f}",
            f"{float(r.get('w', 0)):.2f}", f"{float(r.get('h', 0)):.2f}",
            f"{float((r.get('zoom') or {}).get('scale') or 0):.6f}",
            str(r.get("still_kind", "")),
            "" if r.get("ncc") is None else f"{float(r['ncc']):.4f}",
            "" if r.get("margin") is None else f"{float(r['margin']):.4f}",
            "true" if r.get("confident") else "false",
            str((r.get("electrodes") or {}).get("count", "")),
            _csv(ids),
        ]) + "\n")
    _atomic_write(out_dir / names["csv"], "".join(rows).encode("utf-8"))
    return names


def _csv(v: Any) -> str:
    s = "" if v is None else str(v)
    return f'"{s.replace(chr(34), chr(34) * 2)}"' if any(c in s for c in ',"\n') else s


def _atomic_write(path: Path, data: bytes) -> None:
    """Temp + replace. A failed rewrite must never leave a file that lies about the regions."""
    import os

    tmp = Path(path).with_suffix(Path(path).suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


__all__ = ["DEFAULT_STILL_FRAMES", "PHASES", "STATUS_CONFIRMED", "STATUS_UNCONFIRMED",
           "electrodes_under", "load_map", "locate_region", "read_still", "region_id",
           "resnap_region", "stills_from_video", "write_region_files", "write_still"]
