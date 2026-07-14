"""mosaic -- boustrophedon snapshot-mosaic pipeline for Camea.

A build is a sequence of six stages; only stage (3) differs between builds:

    (1) load frames            io.load_frames        shared
    (2) band-pass              io.bandpass           shared
    (3) measure pairwise shift match.*Matcher        <-- the swappable part
    (4) backbone chain         solve.backbone_chain  shared
    (5) refine (loop+IRLS)     solve.refine          shared
    (6) render                 render.render         shared

Define a build with `BuildConfig` and run it with `build(cfg)`; every output dir gets a
`build.json` manifest recording exactly which steps + params produced it. See
`builds/REGISTRY.md` for the table of builds.
"""
from .config import BuildConfig
from .run import build, make_matcher
from . import io, match, solve, render

__all__ = ["BuildConfig", "build", "make_matcher", "io", "match", "solve", "render"]
