"""Fixtures for the whole suite. The interesting ones are the guard's, and they FAIL, never SKIP.

WHY FAIL AND NOT SKIP
---------------------
`pyproject.toml` sets `addopts = "-m 'not slow'"`, so the 312/312 guard is **off by default** and
pytest never even instantiates these fixtures on a plain `uv run pytest`. A contributor with no data
mirror still gets a green fast suite — that is already true, for free, from the marker.

Which means the ONLY way `dataset_dir` / `gt_dir` are ever asked for is that a human typed `-m slow`.
At that moment a `skip` would be a **green tick that measured nothing**, on the one test standing
between a refactor and silently breaking the science. So: `pytest.fail`, loudly, with the exact
env var to set.

WHAT THE GUARD NEEDS ON DISK, AND WHY NONE OF IT IS IN THE REPO
--------------------------------------------------------------
  * the 35 GB read-only data mirror  -> `CAMEA_DATA_DIR`
  * the hand-authored answer key     -> `CAMEA_GT_DIR`   ⛔ NEVER COMMIT THESE JSONs. Committing the
    answer key destroys the benchmark for everyone who clones. They live under `archive/`, which
    `.gitignore` excludes wholesale. Keep it that way.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from xml.etree import ElementTree

import numpy as np
import pytest

TILE = 512

DEFAULT_DATA = Path("D:/Projects/Camea/data/drive/260620/260620_Imaging/260620d")
DEFAULT_GT = Path(__file__).resolve().parents[1] / "archive" / "analysis" / "ground_truth"

_MISSING = """
{what} IS NOT ON THIS MACHINE — the guard cannot run.

  looked in : {path}
  set it    : {env}=<dir>          (PowerShell:  $env:{env} = '<dir>')

{extra}
This is a HARD FAILURE, not a skip. You asked for `-m slow`; the 312/312 guard is the only thing
standing between a refactor and silently breaking the science, and a green run that quietly measured
nothing is worse than a red one.
"""

_GT_EXTRA = """That directory must contain the hand-authored answer key and the exclusion ruling:
    260620d_pass1_11-166.json
    260620d_pass2_167-348.json
    260620d_merged_11-348.json
    excluded.py

⛔ These files are NOT in the repo and MUST NEVER BE COMMITTED.
"""

_DATA_EXTRA = """That is the raw dataset directory (NNN.xml + NNN-ccd.dat + log.txt). It is a
read-only mirror; nothing in this repo may ever write to it.
"""


def _dir(env: str, default: Path, what: str, extra: str) -> Path:
    p = Path(os.environ.get(env) or default)
    if not p.is_dir():
        pytest.fail(_MISSING.format(what=what, path=p, env=env, extra=extra), pytrace=False)
    return p


@pytest.fixture(scope="session")
def dataset_dir() -> Path:
    """The raw 260620d dataset. READ-ONLY. `CAMEA_DATA_DIR` overrides."""
    return _dir("CAMEA_DATA_DIR", DEFAULT_DATA, "THE DATA MIRROR", _DATA_EXTRA)


@pytest.fixture(scope="session")
def gt_dir() -> Path:
    """The hand-authored ground truth + the exclusion ruling. `CAMEA_GT_DIR` overrides."""
    p = _dir("CAMEA_GT_DIR", DEFAULT_GT, "THE GROUND TRUTH", _GT_EXTRA)
    for f in ("260620d_merged_11-348.json", "excluded.py"):
        if not (p / f).exists():
            pytest.fail(_MISSING.format(what="THE GROUND TRUTH", path=p, env="CAMEA_GT_DIR",
                                        extra=_GT_EXTRA) + f"\n  missing: {f}\n", pytrace=False)
    return p


@pytest.fixture(scope="session")
def gt_excluded(gt_dir: Path):
    """The research tree's `excluded.py`, loaded **BY PATH**, under a private module name.

    ⛔ Never `sys.path.insert(gt_dir)`. That is what the old scorer did (score.py:54), and it leaks a
    FLAT, TOP-LEVEL module named `excluded` into every other test in the session — any other
    `excluded.py` earlier on the path silently shadows it. It also puts a *data directory* on the
    import path.

    ⛔ And never import it from `camea.*`. `camea.engine.excluded` has `gaps()` and nothing else, on
    purpose: the app carries no dataset knowledge. This module is the **260620d ruling**, it belongs
    next to the answer key it justifies, and it is test-only.
    """
    spec = importlib.util.spec_from_file_location("_camea_gt_excluded", gt_dir / "excluded.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# =============================================================================
# The frame reader.
# =============================================================================
# 🔴 TEMPORARY — DELETE THIS BLOCK the moment `camea.core.frames.load_frames` lands (it is another
# agent's file). `load_frames` below tries that import FIRST and only falls back to the port. Two
# frame readers in one repo is exactly the bug class this project keeps paying for, so this fallback
# exists to unblock the guard, not to live.
#
# ⭐⭐ THE 180-DEGREE FLIP IS LOAD-BEARING, AND IT IS VERIFIED. vscope returns the *display* frame;
# the XML says `ax=-1, ay=-1`, so the raw array is rotated 180 degrees. **Every SWIM dx/dy and all
# three ground truths live in the flipped frame.** A naive `np.fromfile().reshape(512,512)` produces
# a mosaic 180 degrees out from every prior result — AND IT WILL LOOK PLAUSIBLE.
# (Ported byte-for-byte in behaviour from archive/app-v1/backend/loader.py:332-509, which asserts
#  equality with `vscope.load(xml).ccd["Cc"][0]` at loader.py:1140-1142. And `tests/slow/
#  test_reader_matches_vscope.py` re-proves it here, on all 312 guard frames.)
def _read_trial_meta(xml_path: Path) -> dict | None:
    """A trial's XML -> its metadata, or None if it is not a genuine 1-frame snapshot.

    ⚠️ SHAPE IS PER-TRIAL, NOT PER-DIRECTORY. Parse the XML; do not infer the shape from the file
    size (the sibling dir `260620` has trial 021 as a genuine snapshot at 512x128). And trial 008 is
    a 2-frame "snapshot" — reject anything with `frames != 1`.
    """
    try:
        root = ElementTree.parse(xml_path).getroot()
    except (ElementTree.ParseError, OSError):
        return None
    info, ccd = root.find("info"), root.find("ccd")
    if info is None or ccd is None or info.get("type") != "snapshot":
        return None
    cam = ccd.find("camera")
    if cam is None or int(cam.get("frames", 1)) != 1:
        return None
    xf = cam.find("transform")
    return {
        "trial": int(info.get("trial")),
        "w": int(cam.get("serpix")), "h": int(cam.get("parpix")),
        "bytes": int(cam.get("typebytes")), "dtype": cam.get("type"),
        "flip_x": xf is not None and int(xf.get("ax", 1)) < 0,
        "flip_y": xf is not None and int(xf.get("ay", 1)) < 0,
    }


def _list_snapshots(data_dir: Path) -> dict[int, dict]:
    """{trial: meta} for every genuine 1-frame snapshot whose .dat size matches its XML.

    A raw disk inventory. **Nothing is filtered out by trial number, here or anywhere else.**
    """
    out: dict[int, dict] = {}
    for xml_path in sorted(Path(data_dir).glob("[0-9][0-9][0-9].xml")):
        dat = xml_path.with_name(xml_path.stem + "-ccd.dat")
        if not dat.exists():
            continue
        meta = _read_trial_meta(xml_path)
        if meta is None:
            continue
        if dat.stat().st_size != meta["w"] * meta["h"] * meta["bytes"]:
            continue                                   # movies (375 frames) fail here
        meta["dat"] = dat
        out[meta["trial"]] = meta
    return out


def _load_frame(meta: dict) -> np.ndarray:
    """One raw .dat -> float32 (h, w) in vscope's DISPLAY orientation. THE reader."""
    if meta["dtype"] != "uint16" or meta["bytes"] != 2:
        raise ValueError(f"trial {meta['trial']}: unsupported pixel type "
                         f"{meta['dtype']}/{meta['bytes']}B (only little-endian uint16 is read)")
    raw = np.fromfile(meta["dat"], dtype="<u2")
    want = meta["h"] * meta["w"]
    if raw.size != want:
        raise ValueError(f"trial {meta['trial']}: {meta['dat'].name} has {raw.size} px, "
                         f"XML says {meta['h']}x{meta['w']} = {want}")
    raw = raw.reshape(meta["h"], meta["w"])
    if meta["flip_x"]:
        raw = np.flip(raw, 1)
    if meta["flip_y"]:
        raw = np.flip(raw, 0)
    return np.ascontiguousarray(raw, dtype=np.float32)


def _load_frames_fallback(data_dir: Path, trials: list[int]) -> np.ndarray:
    """float32 (N, 512, 512), flipped, raw camera counts. Row i IS trial `trials[i]`.

    338 frames in ~0.13 s. Loading is not the bottleneck and it is **not cached** — every guard run
    reads the pixels cold. (The old guard cached the decode to a 327 MB .npy. A cache keyed on
    anything less than the exact trial list is a silent-wrong-answer machine, and it bought 0.13 s.)
    """
    snaps = _list_snapshots(Path(data_dir))
    missing = [t for t in trials if t not in snaps]
    if missing:
        raise ValueError(f"not snapshots in {data_dir}: {missing[:10]}")
    out = np.empty((len(trials), TILE, TILE), np.float32)
    for i, t in enumerate(trials):
        m = snaps[t]
        if (m["h"], m["w"]) != (TILE, TILE):
            raise ValueError(f"trial {t} is {m['w']}x{m['h']}, not {TILE}x{TILE} "
                             f"({m['dat'].name}). This is a {TILE}x{TILE}-only pipeline.")
        out[i] = _load_frame(m)
    return out


@pytest.fixture(scope="session")
def load_frames():
    """-> `f(data_dir, trials) -> float32 (N,512,512)`. The app's reader if it exists, else the port.

    The guard MUST measure the reader the app actually ships. So this prefers `camea.core.frames`
    and says which one it used.
    """
    try:
        from camea.core.frames import load_frames as f      # the app's ONE reader
        return f
    except Exception:                                       # noqa: BLE001 — not written yet
        return _load_frames_fallback


@pytest.fixture(scope="session")
def videosynth():
    """The synthetic survey-video helper (`tests/fixtures/videosynth.py`), loaded by path so it
    imports the same whether or not the tests tree is treated as a package."""
    spec = importlib.util.spec_from_file_location(
        "videosynth", Path(__file__).resolve().parent / "fixtures" / "videosynth.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def measynth():
    """The synthetic MaxLab-recording helper (`tests/fixtures/measynth.py`), loaded the same way.

    ⭐ **This is what makes `Analyze MEA` testable on a clean clone.** `tests/fixtures/synthetic/` is
    a frame dataset and `survey.avi` is a video; neither is a `data.raw.h5`, so before this the
    import, the copy and the shelf could only be exercised against the 35 GB mirror. See the module
    for why the chip in it is 13×5 on a 12.5 µm pitch and not a MaxWell.
    """
    spec = importlib.util.spec_from_file_location(
        "measynth", Path(__file__).resolve().parent / "fixtures" / "measynth.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod
