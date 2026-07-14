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

⚠️ IMPORTS ARE LAZY (PEP 562), and that is load-bearing for the app.
`run.py` imports **pandas** at module level, and `match`/`quality` import it too. The
Mosaic Builder app only ever needs `t33`, `t27` and `render` — so eagerly importing
`.run` here forced every user of the app to install pandas (~50 MB) to run code they
never call. Worse, it made `import analysis.mosaic.t33` fail outright with
`ModuleNotFoundError: No module named 'pandas'` on a clean install.

Everything below still resolves exactly as before on first attribute access, so
`from mosaic import BuildConfig, build` and `mosaic.io.load_frames(...)` are unchanged
for the notebooks. The only difference is *when* the submodule is imported.
"""
from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

__all__ = ["BuildConfig", "build", "make_matcher", "io", "match", "solve", "render"]

# attribute -> the submodule that defines it. Submodules map to themselves.
_LAZY = {
    "BuildConfig":  ".config",
    "build":        ".run",
    "make_matcher": ".run",
    "io":           ".io",
    "match":        ".match",
    "solve":        ".solve",
    "render":       ".render",
}


def __getattr__(name: str):
    """Import the submodule that owns `name` on first access, then cache it."""
    try:
        where = _LAZY[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    mod = importlib.import_module(where, __name__)
    val = mod if where.lstrip(".") == name else getattr(mod, name)
    globals()[name] = val          # cache: __getattr__ is only consulted on a miss
    return val


def __dir__():
    return sorted(__all__)


if TYPE_CHECKING:                  # keep type-checkers and IDEs seeing the real names
    from .config import BuildConfig
    from .run import build, make_matcher
    from . import io, match, solve, render
