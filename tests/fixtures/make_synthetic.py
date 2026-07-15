"""Materialise the committed synthetic dataset at ``tests/fixtures/synthetic/``.

⭐ WHY THIS EXISTS. Playwright and CI must run **without** the 35 GB data mirror. The backend already
knows how to fabricate a real vscope acquisition on disk — the fast API suite is built on it — in
``tests/api/conftest.py::_write_dataset`` (real ``NNN.xml`` + ``NNN-ccd.dat`` + ``log.txt``, tiles cut
from one source image at **known offsets**, so the matcher has a truth to be judged against). This
script **REUSES that exact generator** and writes a trimmed copy into the repo so it can be committed.

Nothing here is a second frame writer: it loads the conftest module **by path** and calls its
``_write_dataset``, having only nudged three module constants to shrink the run to ~10 tiles.

Run it with the project env (it needs numpy + cv2, both project deps)::

    uv run python tests/fixtures/make_synthetic.py

The result is deterministic (fixed RNG seed in the generator), so re-running produces byte-identical
frames and the git diff stays empty. Point the backend at it with::

    uv run camea --headless --port 8000 --open tests/fixtures
    #                                          ^ a dataset ROOT; `synthetic/` is the dataset under it
    #  (the backend has NO --data-dir flag — it remembers roots and GET /api/datasets lists them)
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

# --- locate the tree ------------------------------------------------------------------------------
REPO = Path(__file__).resolve().parents[2]
CONFTEST = REPO / "tests" / "api" / "conftest.py"
TARGET = REPO / "tests" / "fixtures" / "synthetic"

# --- the trimmed shape of the committed fixture ---------------------------------------------------
# The full API-suite synth is 20 run tiles (~12 MB); that is more raw binary than belongs in git.
# We keep a 10-tile serpentine strip (trials 11–20) plus one stray snapshot and one off-shape frame,
# so the fixture still exercises: block selection (the run is the LONGEST contiguous block), the
# 512×512 shape gate (the off-shape frame must be reported and refused by shape, not by number), the
# 180° conditional flip (ax=-1/ay=-1), and the timing-split detector (a planted 40 s pause).
RUN_HI = 20               # run = trials 11..20  → 10 tiles, 128 px overlap step
SYNTH_PASS_SPLIT = 16     # the planted stage-return pause sits on an INTERIOR step (13..17 qualify)
STRAY_SNAPSHOTS = [5]     # one 512×512 snapshot outside the run → a second block to choose against


def _load_conftest():
    """Load ``tests/api/conftest.py`` as a private module, by path. (Same trick the suite uses to
    load the research tree's ``excluded.py`` without leaking a top-level ``conftest`` module.)"""
    if not CONFTEST.is_file():
        sys.exit(f"cannot find the generator to reuse: {CONFTEST}")
    spec = importlib.util.spec_from_file_location("_camea_synth_generator", CONFTEST)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    # Register before exec: the module defines a @dataclass, whose processing looks the class's
    # __module__ up in sys.modules. Without this it raises AttributeError on a NoneType module.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    # The generator's `why` strings contain a `→`; Windows consoles default to cp1252.
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass
    gen = _load_conftest()

    # Shrink the run by overriding the generator's module-level constants BEFORE calling it.
    # `_write_dataset` reads these as globals at call time, so this is a genuine reuse, not a fork.
    gen.RUN_HI = RUN_HI
    gen.SYNTH_PASS_SPLIT = SYNTH_PASS_SPLIT
    gen.STRAY_SNAPSHOTS = list(STRAY_SNAPSHOTS)

    if TARGET.exists():
        shutil.rmtree(TARGET)
    TARGET.mkdir(parents=True, exist_ok=True)

    synth = gen._write_dataset(TARGET, flip=True, name="synthetic")

    # --- self-check: the backend's own reader must accept what we just wrote ----------------------
    from camea.core.dataset import open_dataset

    ds = open_dataset(TARGET)
    dats = sorted(TARGET.glob("*-ccd.dat"))
    total = sum(p.stat().st_size for p in dats)

    print(f"wrote synthetic dataset -> {TARGET}")
    print(f"  experiment       : {ds.experiment}")
    print(f"  trials in log.txt : {len(ds.entries)}  (snapshots: {len(ds.snapshot_trials)})")
    print(f"  readable frames   : {len(ds.readable_trials)}  {ds.readable_trials}")
    print(f"  blocks            : {ds.blocks()}   longest={ds.longest_block()}")
    print(f"  shape groups      : {[(g['w'], g['h'], g['n']) for g in ds.shape_groups()]}")
    split = ds.timing_split()
    print(f"  timing split      : value={split.value} detected={split.detected} ({split.why})")
    print(f"  run truth (11..20 top-left): {synth.origin}")
    print(f"  .dat files        : {len(dats)}   total {total/1_048_576:.2f} MiB")
    if ds.warnings:
        print(f"  warnings          : {list(ds.warnings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
