"""The whole video→mosaic pipeline, orchestrated: probe → track → keyframes → register →
solve → render → save. This is the module the build job runs; everything in it is cancellable
and reports progress in the shapes `core.jobs` expects.

Design that earns a sentence here:
- TWO decode passes, never the whole video in RAM: pass 1 streams every frame at track scale;
  pass 2 is one forward `grab()` sweep that decodes only the chosen keyframes, cached
  flattened at float16 (a ~4 MB/frame budget with a loud guard, not an OOM).
- A validated link is never re-measured. Refine rounds exist to give *rejected and missing*
  candidates a better prior (after a global solve, every keyframe — whatever tracking segment
  it was born in — sits in one gauge, so cross-segment overlaps become measurable).
- The document/UI get a SUMMARY; the full per-link forensic record goes to `build.json`
  beside the mosaic, for developers.
"""

from __future__ import annotations

import csv
import json
import os
import time
from pathlib import Path
from typing import Callable

import numpy as np

from ...core.jobs import Progress, check_cancelled
from .colour import ColourStats, palette_rgb, tint_of
from .config import VideoConfig
from .register import Link, candidate_links, measure_link
from .render import (RenderError, background_full, exposure_gains, preview_of, render,
                     subtract_background)
from .solvelinks import solve_links
from .track import track
from .video import VideoError, probe, read_frames_at

#: phase -> (start_pct, end_pct). Weights measured on the real thing: tracking IS the build.
_SPAN = {"probe": (0, 2), "track": (2, 48), "keyframes": (48, 62), "register": (62, 84),
         "solve": (84, 86), "render": (86, 96), "save": (96, 100)}
PHASES = list(_SPAN)


class PipelineError(Exception):
    """The build cannot continue, with the reason in one sentence (becomes the job error)."""


#: logical artifact -> filename suffix. ⭐ **The artifacts are named after the PROJECT and written
#: into the project folder itself** — no `outputs/` for this feature (R43). The folder the user
#: names at the end is both the project and the export, so what he sees when he opens it is
#: `<his project>.png`, not a subfolder holding a file called `mosaic.png`.
ARTIFACTS = {"mosaic": ".png", "preview": "-preview.png",
             "positions": "-positions.csv", "build": "-build.json"}


def artifact_names(basename: str) -> dict[str, str]:
    """`{"mosaic": "survey-01.png", …}` — the one place the naming lives. The API's outputs route
    resolves a logical name through the document's recorded paths and falls back to this."""
    return {k: f"{basename}{suffix}" for k, suffix in ARTIFACTS.items()}


def _emitter(report: Callable[[Progress], None] | None):
    t0 = time.monotonic()

    def emit(phase: str, frac: float, message: str = "", eta_s: float | None = None) -> None:
        if report is None:
            return
        lo, hi = _SPAN[phase]
        report(Progress(phase=phase, phase_index=PHASES.index(phase), n_phases=len(PHASES),
                        pct=lo + (hi - lo) * min(1.0, max(0.0, frac)),
                        message=message, eta_s=eta_s))

    emit.t0 = t0  # type: ignore[attr-defined]
    return emit


def build(video_path: str | Path, out_dir: str | Path, cfg: VideoConfig | None = None, *,
          basename: str = "mosaic", diagnostics: bool = False,
          report: Callable[[Progress], None] | None = None, cancel=None,
          log: Callable[[str], None] | None = None) -> dict:
    """Build the mosaic. Returns the JSON-safe result the job/result/document all share.

    `out_dir` is the **project folder** and `basename` the project's name (already through
    `safe_basename`): the artifacts land directly in it as `<basename>.png` and friends — see
    `ARTIFACTS`.

    ⭐ `diagnostics` writes the developer's extra files (the estimated background). **Off by
    default, and the app never turns it on**: since R43 the output folder is one the *user* named
    and opens in Explorer, so anything in it that is not his mosaic is clutter he did not ask for.
    `cli.py` — the dev harness — passes True.

    Raises `PipelineError` / `VideoError` / `RenderError` with a user-readable sentence;
    everything deeper is a bug and may propagate as itself.
    """
    cfg = cfg or VideoConfig()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    names = artifact_names(basename)
    emit = _emitter(report)
    say = log or (lambda s: None)
    t_start = time.monotonic()

    # ---- probe ---------------------------------------------------------------------------
    emit("probe", 0.0, "opening video")
    info = probe(video_path)
    say(f"video: {info.name} {info.width}x{info.height} ~{info.n_frames} frames "
        f"@ {info.fps:.1f} fps")
    emit("probe", 1.0, f"{info.width}×{info.height}, ~{info.n_frames} frames")

    # ---- pass 1: track -------------------------------------------------------------------
    t0 = time.monotonic()

    def track_progress(i: int, n: int) -> None:
        rate = i / max(1e-6, time.monotonic() - t0)
        eta = (n - i) / rate if rate > 0 and i > 50 else None
        emit("track", i / max(1, n), f"analyzing motion: frame {i} / {n}", eta)

    tr = track(str(video_path), info, cfg, progress=track_progress, cancel=cancel)
    say(f"tracked {tr.stats['frames_tracked']}/{tr.n_read} frames, "
        f"{tr.stats['segments']} segment(s), {tr.stats['frames_black']} black, "
        f"path {tr.stats['total_path_px']:.0f} px, {len(tr.keyframes)} keyframes")
    if tr.n_read == 0:
        raise PipelineError("the video decoded no frames at all")
    if len(tr.keyframes) < cfg.min_keyframes:
        if tr.stats["frames_black"] >= tr.n_read - 1:
            raise PipelineError("every frame of this video is black — nothing to build from")
        if tr.stats["total_path_px"] < cfg.keyframe_spacing_frac * info.width:
            raise PipelineError(
                "the camera barely moves in this video (total travel "
                f"{tr.stats['total_path_px']:.0f} px) — a mosaic needs a survey, not a still")
        raise PipelineError(
            f"only {len(tr.keyframes)} usable keyframe(s) were found — too few to mosaic")

    # ---- pass 2: decode + flatten the keyframes -------------------------------------------
    frame_mb = info.width * info.height * 2 / 1e6            # float16
    need_mb = frame_mb * len(tr.keyframes)
    if need_mb > cfg.max_keyframe_cache_mb:
        raise PipelineError(
            f"{len(tr.keyframes)} keyframes would need {need_mb:.0f} MB of working memory "
            f"(cap {cfg.max_keyframe_cache_mb:.0f} MB). This video's motion path is unusually "
            "long; raise `keyframe_spacing_frac` or split the video.")

    bg = background_full(tr.bg_small, (info.width, info.height), cfg)
    say(f"background model: {'yes' if bg is not None else 'no (too few moving frames)'}")
    cache: dict[int, np.ndarray] = {}                        # keyframe LIST index -> float16
    levels: dict[int, float] = {}
    by_frame = {k.index: i for i, k in enumerate(tr.keyframes)}

    def consume(frame_idx: int, gray: np.ndarray) -> None:
        check_cancelled(cancel, "keyframe decode")
        i = by_frame[frame_idx]
        f = subtract_background(gray, bg)
        cache[i] = f.astype(np.float16)
        on = f[f > 5.0]
        levels[i] = float(np.percentile(on, 60)) if on.size > f.size * 0.01 else 0.0

    # The source's colour, measured on the very frames that become the mosaic's pixels — evenly
    # spread, and free, because this decode pass is happening anyway. It informs the PALETTE only;
    # `to_gray` has already reduced what registration and rendering see.
    tint_stats = ColourStats()
    tint_every = max(1, len(by_frame) // max(1, cfg.tint_samples))

    def sample_colour(frame_idx: int, frame_bgr: np.ndarray) -> None:
        if by_frame[frame_idx] % tint_every == 0:
            tint_stats.offer(frame_bgr, cfg)

    got = read_frames_at(str(video_path), list(by_frame),
                         consume,
                         progress=lambda i, n: emit("keyframes", i / n,
                                                    f"decoding keyframes: {i} / {n}"),
                         colour=sample_colour)
    tint = tint_of(tint_stats, cfg)
    tint_text = "grey (not single-channel)" if tint is None else \
        "BGR " + " ".join(f"{v:.3f}" for v in tint)
    say(f"source colour: {tint_text} — {tint_stats.n_frames} frame(s) sampled, "
        f"hue concentration {tint_stats.hue_concentration():.4f}")
    if len(got) < len(by_frame):
        say(f"⚠ {len(by_frame) - len(got)} keyframe(s) could not be re-decoded — the stream "
            "ends earlier than the container claimed")
    keyframes = [tr.keyframes[by_frame[f]] for f in got]
    if len(keyframes) < cfg.min_keyframes:
        raise PipelineError("the keyframes chosen in pass 1 could not be re-decoded — "
                            "the stream may be truncated")
    # re-index everything to the frames we actually hold
    keep = sorted(by_frame[f] for f in got)
    remap = {old: new for new, old in enumerate(keep)}
    cache = {remap[i]: v for i, v in cache.items() if i in remap}
    levels = {remap[i]: v for i, v in levels.items() if i in remap}
    keyframes = [tr.keyframes[i] for i in keep]

    kf_pos = np.array([[k.x, k.y] for k in keyframes])
    kf_seg = np.array([k.segment for k in keyframes], np.int32)

    def fetch(i: int) -> np.ndarray:
        return cache[i].astype(np.float32)

    # ---- register + solve (round 0, then refine rounds) -----------------------------------
    all_links: dict[tuple[int, int], Link] = {}

    def measure_round(cands: list[Link], round_no: int, pos_of: Callable[[int], np.ndarray],
                      frac0: float, frac1: float) -> int:
        fresh = 0
        todo = [l for l in cands if (l.a, l.b) not in all_links
                or not all_links[(l.a, l.b)].ok]
        t_reg = time.monotonic()
        for n_done, l in enumerate(todo):
            check_cancelled(cancel, "registration")
            prior = tuple(pos_of(l.b) - pos_of(l.a)) if l.kind != "bridge" else (0.0, 0.0)
            measured = measure_link(fetch(l.a), fetch(l.b), prior, l, cfg)
            key = (l.a, l.b)
            if key not in all_links or (measured.ok and not all_links[key].ok):
                all_links[key] = measured
                fresh += int(measured.ok)
            if not measured.ok:
                say(f"  round {round_no}: link kf{l.a}->kf{l.b} ({l.kind}) rejected: "
                    f"{measured.reject_reason} (resp {measured.response:.2f}, "
                    f"ncc {measured.ncc:.2f})")
            rate = (n_done + 1) / max(1e-6, time.monotonic() - t_reg)
            emit("register", frac0 + (frac1 - frac0) * (n_done + 1) / max(1, len(todo)),
                 f"registering frames: {n_done + 1} / {len(todo)}",
                 (len(todo) - n_done - 1) / rate if rate > 0 else None)
        return fresh

    cands = candidate_links(kf_pos, kf_seg, (info.width, info.height), cfg,
                            trust_all_priors=False)
    measure_round(cands, 0, lambda i: kf_pos[i], 0.0,
                  0.6 if cfg.refine_rounds else 1.0)
    sol = solve_links(len(keyframes), list(all_links.values()), cfg)
    say(f"solve round 0: {sol.stats}")

    for r in range(cfg.refine_rounds):
        cands = candidate_links(sol.pos, sol.component, (info.width, info.height), cfg,
                                trust_all_priors=False, bridge_to_first=True)
        fresh = measure_round(cands, r + 1, lambda i: sol.pos[i],
                              0.6 + 0.4 * r / cfg.refine_rounds,
                              0.6 + 0.4 * (r + 1) / cfg.refine_rounds)
        if fresh == 0:
            break
        sol = solve_links(len(keyframes), list(all_links.values()), cfg)
        say(f"solve round {r + 1}: {sol.stats}")

    emit("solve", 1.0, "alignment solved")
    links = list(all_links.values())
    n_ok = sum(1 for l in links if l.ok)
    if int(sol.placed.sum()) < cfg.min_keyframes:
        raise PipelineError(
            f"registration failed: of {len(links)} candidate pairs only {n_ok} could be "
            "verified, which does not connect the video into one mosaic. The footage may "
            "lack texture or overlap.")

    placed_idx = [i for i in range(len(keyframes)) if sol.placed[i]]
    dropped_idx = [i for i in range(len(keyframes)) if not sol.placed[i]]
    if dropped_idx:
        say(f"⚠ {len(dropped_idx)} keyframe(s) could not be tied to the main mosaic and are "
            f"left out: video frames {[keyframes[i].index for i in dropped_idx]}")

    # ---- render ----------------------------------------------------------------------------
    gains = exposure_gains({i: levels.get(i, 0.0) for i in placed_idx}, cfg)
    try:
        rr = render({i: (float(sol.pos[i, 0]), float(sol.pos[i, 1])) for i in placed_idx},
                    fetch, (info.width, info.height), gains, cfg,
                    progress=lambda i, n: emit("render", i / n, f"rendering mosaic: {i} / {n}"),
                    cancel=cancel)
    except RenderError as e:
        raise PipelineError(str(e)) from e

    # ---- save ------------------------------------------------------------------------------
    emit("save", 0.2, "writing outputs")
    from PIL import Image                                    # lazy: keep import time lean

    def commit(name: str, write) -> None:
        """Write to a temp sibling, fsync-free, then os.replace — each artifact lands whole or
        not at all; a crash mid-save leaves the previous build's file, never half of both."""
        tmp = out / f".tmp-{name}"
        write(tmp)
        os.replace(tmp, out / name)

    if diagnostics and tr.bg_small is not None:              # dev only — see `diagnostics` above
        b = tr.bg_small
        b8 = np.clip((b - b.min()) / max(1e-6, float(b.max() - b.min())) * 255, 0, 255)
        commit(f"{basename}-background.png",
               lambda t: Image.fromarray(b8.astype(np.uint8), mode="L").save(t, format="PNG"))

    # ⭐ The mosaic goes out PALETTISED, not RGB. The index plane is byte-identical to the grey
    # composite — the numbers a scientist measures are untouched — while the file opens in the
    # source's own colour in any viewer, which is exactly what a Fiji LUT is for. It costs ~18 %
    # more bytes than grey and is slightly FASTER to write; true RGB would have cost 47 % and three
    # accumulators to store two channels of codec ringing. `palette_rgb(None)` is the identity ramp,
    # so a video that fails the single-channel test comes out as plain grey.
    pal = palette_rgb(tint)

    def png(u8: np.ndarray, path, level: int) -> None:
        im = Image.fromarray(u8, mode="P")
        im.putpalette(pal)
        im.save(path, format="PNG", compress_level=level)

    commit(names["mosaic"], lambda t: png(rr.mosaic_u8, t, cfg.png_compress_level))
    commit(names["preview"], lambda t: png(preview_of(rr.mosaic_u8, cfg), t, 6))
    with (out / ".tmp-positions.csv").open("w", newline="", encoding="utf-8") as fh:
        cw = csv.writer(fh)
        cw.writerow(["keyframe", "video_frame", "x_px", "y_px", "segment", "reason",
                     "gain", "placed"])
        for i, k in enumerate(keyframes):
            x = sol.pos[i, 0] - rr.origin_x if sol.placed[i] else ""
            y = sol.pos[i, 1] - rr.origin_y if sol.placed[i] else ""
            cw.writerow([i, k.index, x and round(float(x), 2), y and round(float(y), 2),
                         k.segment, k.reason, rr.gains.get(i, ""), bool(sol.placed[i])])
    os.replace(out / ".tmp-positions.csv", out / names["positions"])

    ok_links = [l for l in links if l.ok]
    reject_hist: dict[str, int] = {}
    for l in links:
        if not l.ok:
            reject_hist[l.reject_reason or "?"] = reject_hist.get(l.reject_reason or "?", 0) + 1
    stats = {
        "video": info.to_json(),
        "track": tr.stats,
        "registration": {
            "links_measured": len(links),
            "links_ok": n_ok,
            "links_rejected": len(links) - n_ok,
            "reject_reasons": reject_hist,
            "median_response": round(float(np.median([l.response for l in ok_links])), 4)
            if ok_links else 0.0,
            "median_ncc": round(float(np.median([l.ncc for l in ok_links])), 4)
            if ok_links else 0.0,
            "by_kind": {kind: sum(1 for l in ok_links if l.kind == kind)
                        for kind in ("seq", "cross", "bridge")},
        },
        "solve": sol.stats,
        "render": rr.stats,
        "colour": tint_stats.to_json(cfg),
        "keyframes_placed": len(placed_idx),
        "keyframes_dropped": len(dropped_idx),
        "dropped_video_frames": [keyframes[i].index for i in dropped_idx],
        "elapsed_s": round(time.monotonic() - t_start, 1),
    }
    commit(names["build"], lambda t: t.write_text(json.dumps({
        "stats": stats,
        "config": cfg.to_json(),
        "keyframes": [k.to_json() for k in keyframes],
        "links": [l.to_json() for l in links],
    }, indent=2), encoding="utf-8"))

    emit("save", 1.0, "done")
    say(f"mosaic {rr.canvas_w}×{rr.canvas_h}, coverage {rr.coverage_frac:.0%}, "
        f"{len(placed_idx)}/{len(keyframes)} keyframes, {stats['elapsed_s']} s")
    return {
        "stats": stats,
        "config": cfg.to_json(),
        "canvas": {"w": rr.canvas_w, "h": rr.canvas_h},
        # ⭐ FILENAMES, not absolute paths — and this is what the outputs route resolves through.
        # 🔴 A saved project MOVES (`Project.move_to`, R43), so an absolute path recorded here would
        # be a lie the moment the user names his folder; the filenames stay true wherever it lands.
        "outputs": dict(names),
        "keyframes": {str(keyframes[i].index): {
            "x": round(float(sol.pos[i, 0] - rr.origin_x), 2),
            "y": round(float(sol.pos[i, 1] - rr.origin_y), 2),
            "segment": int(keyframes[i].segment),
            "reason": keyframes[i].reason,
            "placed": True,
        } for i in placed_idx} | {str(keyframes[i].index): {
            "x": None, "y": None,
            "segment": int(keyframes[i].segment),
            "reason": keyframes[i].reason,
            "placed": False,
        } for i in dropped_idx},
    }


__all__ = ["build", "PipelineError", "VideoError", "PHASES"]
