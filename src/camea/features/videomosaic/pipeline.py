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

from ...core.jobs import Progress, check_cancelled, eta_from_fraction
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


#: ⏱️ How far into the WHOLE build before we will name a time. `core.jobs.ETA_MIN_FRACTION` is 2 %,
#: which here is exactly where `probe` ends — and probe is a file open plus one decoded frame, near
#: constant, while everything after it scales with the length of the video. Extrapolating an
#: eight-minute build from it announces "10 s left" at the top of the run. 5 % puts the first
#: estimate a little way into `track`, where the number is measured throughput.
_ETA_MIN_OVERALL = 0.05

#: ⏱️ Floor on how often a phase may speak. A `Progress` is not free — the registry appends every
#: message to the job's log tail — and registration measures a link in ~0.1 s, so a per-iteration
#: emit would push ten messages a second at a bar that redraws once. A phase's first and last word
#: are never dropped, so no transition is swallowed and every span lands on its own end.
_MIN_EMIT_S = 0.25


def _emitter(report: Callable[[Progress], None] | None):
    """`emit(phase, frac, message)` — maps a phase-local 0..1 into that phase's slice of `_SPAN`,
    and derives the ETA **here, once, from the resulting OVERALL fraction** (R48.5).

    ⭐ The estimate is computed in exactly one place on purpose. Every phase used to be free to work
    one out for itself and only `track` ever did, so on his 16,098-frame video the time remaining
    appeared for 46 % of the build and vanished for the other 54 % — which reads as a hang, not as
    honesty. Deriving it from the weighted overall pct also kills the whole family of bugs where a
    phase hands `eta_from_fraction` its own 0→1: the number then counts *up* inside every phase and
    restarts at every boundary. Registration is the worst case — each refine round builds a fresh
    `todo` list, so a per-round estimate would jump backwards in the middle of one phase.
    """
    t0 = time.monotonic()
    st = {"t": t0 - _MIN_EMIT_S - 1.0, "phase": ""}

    def emit(phase: str, frac: float, message: str = "") -> None:
        if report is None:
            return
        now = time.monotonic()
        f = min(1.0, max(0.0, float(frac)))
        if f < 1.0 and phase == st["phase"] and now - st["t"] < _MIN_EMIT_S:
            return
        st["t"], st["phase"] = now, phase
        lo, hi = _SPAN[phase]
        pct = lo + (hi - lo) * f
        report(Progress(phase=phase, phase_index=PHASES.index(phase), n_phases=len(PHASES),
                        pct=pct, message=message,
                        # ⛔ NOT `f` — that is phase-local. `pct` is the whole job and `t0` is the
                        # whole job's clock, so this pair is the only one that answers "how much
                        # longer until the mosaic exists" (R48.5).
                        eta_s=eta_from_fraction(now - t0, pct / 100.0, _ETA_MIN_OVERALL)))

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
    def track_progress(i: int, n: int) -> None:
        # `n` comes from CAP_PROP_FRAME_COUNT and it lies in BOTH directions (video.py's header
        # note); `track` raises it as the stream approaches the claim. The 99 % ceiling is the
        # other half of that: on a container whose count happens to be exact the phase would
        # otherwise report itself finished while frames are still arriving. Only the final
        # `progress(n_read, n_read)`, fired after the decode loop ends, closes this span.
        #
        # ⛔ R48.10 — a denominator that MOVED must not be printed as though the container had said
        # it. Once `track` has revised the claim, the count is ours and the sentence says `~`; the
        # closing tick (`i >= n`) is the one exact number here and prints bare.
        done = i >= n
        total = f"{n}" if done or n == info.n_frames else f"~{n}"
        frac = i / max(1, n)
        emit("track", frac if done else min(0.99, frac),
             f"analyzing motion: frame {i} / {total}")

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

    n_decoded = 0

    def consume(frame_idx: int, gray: np.ndarray) -> None:
        nonlocal n_decoded
        check_cancelled(cancel, "keyframe decode")
        n_decoded += 1
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

    def kf_scanned(pos: int, span: int) -> None:
        # ⏱️ The bar is driven by FRAMES WALKED PAST, not by keyframes produced. This is one forward
        # `grab()` pass, so the cost is the walking — while keyframes are spaced by TRAVEL, so a
        # dwell is a long stretch of the video that yields none and a bar counting keyframes freezes
        # exactly where the decoder is busiest. The sentence still counts keyframes, because that is
        # what he asked for.
        emit("keyframes", pos / max(1, span), f"decoding keyframes: {n_decoded} / {len(by_frame)}")

    got = read_frames_at(str(video_path), list(by_frame),
                         consume,
                         scanned=kf_scanned,
                         colour=sample_colour, cancel=cancel)
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
        todo = [lk for lk in cands if (lk.a, lk.b) not in all_links
                or not all_links[(lk.a, lk.b)].ok]
        # ⚠️ Every refine round starts a FRESH `todo`, so the counter genuinely does restart —
        # "3 / 18" straight after "340 / 340" reads as a jump backwards unless the sentence says
        # which round it belongs to. The BAR does not move back (`frac0`/`frac1` give each round its
        # own slice of the register span) and neither does the ETA (it comes from the overall pct,
        # not from this loop's rate — which is what would have restarted with `todo`).
        what = "registering frames" if round_no == 0 else \
            f"re-checking alignment, round {round_no}"
        for n_done, lk in enumerate(todo):
            check_cancelled(cancel, "registration")
            prior = tuple(pos_of(lk.b) - pos_of(lk.a)) if lk.kind != "bridge" else (0.0, 0.0)
            measured = measure_link(fetch(lk.a), fetch(lk.b), prior, lk, cfg)
            key = (lk.a, lk.b)
            if key not in all_links or (measured.ok and not all_links[key].ok):
                all_links[key] = measured
                fresh += int(measured.ok)
            if not measured.ok:
                say(f"  round {round_no}: link kf{lk.a}->kf{lk.b} ({lk.kind}) rejected: "
                    f"{measured.reject_reason} (resp {measured.response:.2f}, "
                    f"ncc {measured.ncc:.2f})")
            emit("register", frac0 + (frac1 - frac0) * (n_done + 1) / max(1, len(todo)),
                 f"{what}: {n_done + 1} / {len(todo)}")
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

    # 🔴 Close the register span on its own end (R48.5). Nothing inside the loop above guarantees
    # it: a refine round whose `todo` comes out empty emits not once, and round 0's terminal tick
    # sits at frac 0.6, which the cadence guard is free to drop. Measured on tests/fixtures/
    # survey.avi, registration reached **62.1 of its 62→84 span** and the bar then jumped 22 points
    # to `solve`. This is real advancement, not a heartbeat — registration is finished here.
    emit("register", 1.0, f"{sum(1 for lk in all_links.values() if lk.ok)} of "
                          f"{len(all_links)} frame pairs registered")
    emit("solve", 1.0, "alignment solved")
    links = list(all_links.values())
    n_ok = sum(1 for lk in links if lk.ok)
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
    # The last place a Stop can be honoured cheaply. Past here the artifacts start landing, and a
    # half-written set of outputs is worse than a build that finishes and is thrown away — so the
    # writes below deliberately have no cancel checks between them.
    check_cancelled(cancel, "saving the outputs")
    from PIL import Image                                    # lazy: keep import time lean

    def commit(name: str, write) -> None:
        """Write to a temp sibling, fsync-free, then os.replace — each artifact lands whole or
        not at all; a crash mid-save leaves the previous build's file, never half of both."""
        tmp = out / f".tmp-{name}"
        write(tmp)
        os.replace(tmp, out / name)

    n_save = len(ARTIFACTS) + int(bool(diagnostics and tr.bg_small is not None))
    n_written = 0

    def writing(what: str) -> None:
        """Tick the save phase, announced BEFORE each write with the fraction ALREADY on disk — so
        the sentence names what he is waiting on and the bar never claims work it has not done.

        ⏱️ One tick per named artifact is as fine-grained as this phase honestly goes: PIL exposes
        no callback inside `Image.save`, so a 400 Mpx PNG encode is a single atom however it is
        counted. It still beats what stood here — one "writing outputs" pinned at 96 % until the
        whole job said `done`, which on a large canvas is the longest silent stretch of the build.
        """
        nonlocal n_written
        emit("save", n_written / n_save, f"writing {what}")
        n_written += 1

    if diagnostics and tr.bg_small is not None:              # dev only — see `diagnostics` above
        writing("the background model")
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

    writing("the mosaic image")
    commit(names["mosaic"], lambda t: png(rr.mosaic_u8, t, cfg.png_compress_level))
    writing("the preview")
    commit(names["preview"], lambda t: png(preview_of(rr.mosaic_u8, cfg), t, 6))
    writing("the positions table")
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

    ok_links = [lk for lk in links if lk.ok]
    reject_hist: dict[str, int] = {}
    for lk in links:
        if not lk.ok:
            reject_hist[lk.reject_reason or "?"] = reject_hist.get(lk.reject_reason or "?", 0) + 1
    stats = {
        "video": info.to_json(),
        "track": tr.stats,
        "registration": {
            "links_measured": len(links),
            "links_ok": n_ok,
            "links_rejected": len(links) - n_ok,
            "reject_reasons": reject_hist,
            "median_response": round(float(np.median([lk.response for lk in ok_links])), 4)
            if ok_links else 0.0,
            "median_ncc": round(float(np.median([lk.ncc for lk in ok_links])), 4)
            if ok_links else 0.0,
            "by_kind": {kind: sum(1 for lk in ok_links if lk.kind == kind)
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
    writing("the build record")
    commit(names["build"], lambda t: t.write_text(json.dumps({
        "stats": stats,
        "config": cfg.to_json(),
        "keyframes": [k.to_json() for k in keyframes],
        "links": [lk.to_json() for lk in links],
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
