"""Glue: run all six stages from a BuildConfig and write self-describing outputs
(positions.csv, build.json manifest, layout_scatter.png, mosaic.npy/png).

A build notebook is just: define a BuildConfig, call `build(cfg)`.
"""
import json
import numpy as np
import pandas as pd

from . import io, solve, render
from .match import FullframeMatcher, SubregionMatcher, FusedMatcher


def _fullframe(cfg):
    trials = io.list_trials(cfg.data_root, cfg.date_dir, cfg.trial_min, cfg.trial_max)
    print(f"{len(trials)} snapshot trials: {trials[0]}..{trials[-1]}")
    frames = io.load_frames(cfg.data_root, cfg.date_dir, trials,
                            cfg.ccd_key, cfg.frame_idx, cache=cfg.out_dir() / "frames.npy")
    sigmas = cfg.dog if cfg.use_bandpass else None
    match_imgs = io.bandpass(frames, sigmas)
    print("matching on", "band-passed" if cfg.use_bandpass else "raw", "frames")
    return FullframeMatcher(trials, frames, match_imgs, cfg.snr_min)


def _subregion(cfg):
    m = SubregionMatcher(cfg.run_dir, cfg.data_root, cfg.date_dir, cfg.snr_min,
                         cfg.clus_tol, cfg.prior_tol, cfg.min_sup,
                         cfg.ccd_key, cfg.frame_idx,
                         trial_min=cfg.trial_min, trial_max=cfg.trial_max)
    print(f"{m.n_all:,} comparisons -> {m.n_ok:,} ok; "
          f"{len(m.trials)} trials, {len(m.GRP):,} compared pairs")
    return m


def make_matcher(cfg):
    """Build stage (3), the swappable shift source, from the config."""
    if cfg.match == "fullframe":
        return _fullframe(cfg)
    if cfg.match == "subregion":
        return _subregion(cfg)
    if cfg.match == "fused":
        ff = _fullframe(cfg)
        sub = _subregion(cfg)
        print(f"fused: corroborating full-frame SWIM with subregion consensus (fuse_tol={cfg.fuse_tol}px)")
        return FusedMatcher(ff, sub, cfg.fuse_tol, cfg.snr_min)

    raise ValueError(f"unknown match source: {cfg.match!r} (expected 'fullframe' | 'subregion' | 'fused')")


def _frame_provider(cfg, matcher):
    """The frames handed to the render stage. Raw by default; flat-fielded (vignette
    divided out, optional per-frame level match) when cfg.flatfield is set."""
    base = matcher.frame
    if not cfg.flatfield:
        return base
    frames = getattr(matcher, "frames", None)
    if frames is None:                                     # subregion matcher holds no stack
        trials = io.list_trials(cfg.data_root, cfg.date_dir, cfg.trial_min, cfg.trial_max)
        frames = io.load_frames(cfg.data_root, cfg.date_dir, trials, cfg.ccd_key,
                                cfg.frame_idx, cache=cfg.out_dir() / "frames.npy")
    flat_n = io.compute_flat(frames, cfg.flat_sigma)
    level = io.flat_level(frames) if cfg.level_norm else None
    print(f"flat-field: {cfg.flatfield} sigma={cfg.flat_sigma}, level-norm {'on' if level else 'off'}")
    return lambda t: io.flat_correct(base(t), flat_n, level)


def build(cfg, show=True, matcher=None):
    """Run the full pipeline, write outputs, return {pos, posdf, mosaic, out_dir, matcher}.

    Pass `matcher=` a custom stage-③ matcher (implementing the match.py interface) to use
    it WITHOUT editing run.make_matcher / match.py -- so independent teams can run fully in
    parallel without touching shared files. Equivalently, a team can compute its own
    positions with any algorithm, save them, and use `cfg.positions_from=<its csv>` with
    `match="fullframe"` (frames come from the shared cache) -- also zero shared-file edits.
    """
    out = cfg.out_dir()
    out.mkdir(parents=True, exist_ok=True)
    print("out:", out)

    matcher = matcher if matcher is not None else make_matcher(cfg)
    if cfg.positions_from:                                 # render-only: reuse a solved layout
        src = pd.read_csv(cfg.positions_from)
        pos = {int(t): np.array([float(x), float(y)]) for t, x, y in
               src[["trial", "x", "y"]].itertuples(index=False) if int(t) in matcher.TI}
        print(f"reused {len(pos)} positions from {cfg.positions_from} (no re-matching)")
    else:
        pos = solve.backbone_chain(matcher, tile=cfg.tile)
        pos = solve.refine(matcher, pos, [tuple(s) for s in cfg.schedule], cfg.overlap,
                           tile=cfg.tile, ctr=cfg.ctr)

    posdf = pd.DataFrame([(t, pos[t][0], pos[t][1]) for t in sorted(pos)],
                         columns=["trial", "x", "y"])
    posdf.to_csv(out / "positions.csv", index=False)

    manifest = cfg.as_manifest()
    manifest["n_trials"] = len(pos)
    ext = solve._extent(pos, matcher.trials, cfg.tile)
    manifest["extent_px"] = [int(ext[0]), int(ext[1])]
    score = _placement_score(cfg, matcher, pos)         # the canonical geometry metric
    if score:
        manifest["placement_score"] = score
        print(f"placement: med NCC {score['med']:.3f}  frac_good {score['frac_good']:.2f}  "
              f"bad-tiles {score['n_bad_tiles']}/{score['n_tiles']}")
    (out / "build.json").write_text(json.dumps(manifest, indent=2, default=str))
    print("wrote", out / "positions.csv", "and build.json")

    _layout_plot(posdf, f"{cfg.build_id} -- layout ({len(posdf)} snapshots)", out, cfg.ctr, show)

    mosaic = None
    if cfg.render:
        posf = {int(t): (float(x), float(y)) for t, x, y in posdf.itertuples(index=False)}
        frame_of = _frame_provider(cfg, matcher)
        mosaic = render.render(posf, frame_of, tilesize=(cfg.tile, cfg.tile),
                               blend=cfg.blend, mode=cfg.render_mode)
        np.save(out / "mosaic.npy", mosaic.astype(np.float32))
        _mosaic_plot(mosaic, f"{cfg.build_id} -- mosaic ({len(posf)} snapshots)", out, show)
        print("saved:", out / "mosaic.png")

    _aggregate(cfg, out)                                # copy pngs into the _all_* galleries
    return {"pos": pos, "posdf": posdf, "mosaic": mosaic, "out_dir": out,
            "matcher": matcher, "score": score}


def _placement_score(cfg, matcher, pos):
    """Canonical placement quality (quality.score_positions). Best-effort: needs the raw
    frame stack -- use the matcher's if it has one, else the cached A frames.npy."""
    try:
        from . import quality
        frames = getattr(matcher, "frames", None)
        if frames is not None:
            bp = quality.band_pass(frames)
            trials = list(matcher.trials)
        else:
            bp, trials = quality._bp_and_trials()
        s = quality.score_positions(pos, bp, trials)
        s.pop("per_tile", None)
        return s
    except Exception as e:
        print("placement score skipped:", type(e).__name__, e)
        return None


def _aggregate(cfg, out):
    """Maintain two galleries next to the builds: every build's mosaic.png and
    layout_scatter.png, named <build_id>.png, so all results are viewable in one place."""
    import shutil
    from pathlib import Path
    root = Path(cfg.out_root)
    for src_name, gallery in [("mosaic.png", "_all_mosaics"),
                              ("layout_scatter.png", "_all_layouts")]:
        src = out / src_name
        if src.exists():
            g = root / gallery; g.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, g / f"{cfg.build_id}.png")


def _layout_plot(posdf, title, out, ctr, show):
    render.layout_png(posdf[["x", "y"]].to_numpy() + ctr, posdf.trial.to_numpy(),
                      out / "layout_scatter.png", title, show=show)


def _mosaic_plot(mosaic, title, out, show):
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(11, 14))
    lo, hi = np.percentile(mosaic[mosaic > 0], [1, 99]) if np.any(mosaic > 0) else (0, 1)
    ax.imshow(mosaic, cmap="gray", vmin=lo, vmax=hi); ax.axis("off")
    ax.set_title(title)
    fig.savefig(out / "mosaic.png", dpi=150, bbox_inches="tight")
    plt.show() if show else plt.close(fig)
