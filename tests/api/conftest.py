"""Fixtures for the API suite.

⭐ **THE FAST SUITE MUST NOT NEED THE 35 GB MIRROR.** `uv run pytest -q` runs on a clean clone, in
CI, on a box with no data and no GPU. So everything here is built against a **SYNTHETIC vscope
acquisition** written into `tmp_path`: real `NNN.xml`, real `NNN-ccd.dat`, real `log.txt`, cut from
one big source image at **known offsets**, so the matcher has a truth to be judged against.

The real-acquisition facts (338 trials, pass_split 166) are in `test_260620d.py` and are marked
`slow`, exactly like `tests/unit/test_dataset_260620d.py`.

⚠️ **THE SYNTHETIC DATASET DECLARES `ax=-1, ay=-1`** — like the real one — and its `.dat` bytes are
written **pre-flipped**, so the reader's conditional flip brings back the tile we cut. That is not a
trick to route around the flip: it is what exercises it. `test_core_routes.py` asserts the
`frame_note` says so, and `synth_noflip` is the same dataset with `ax=+1` to prove the note is
**read off the XML**, never asserted. (v1 hard-coded "180-degree-flipped" into the exported TIFF
header. On an acquisition that does not flip, that header is a lie about its own coordinate frame.)

⛔ **NO TRIAL NUMBER IS SPECIAL HERE EITHER.** The synthetic dataset has no "bad" frames, no
exclusions and no blanks. Tests that need an excluded tile press `E` themselves — through the API,
like the user.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

# =================================================================================================
# The synthetic acquisition
# =================================================================================================

TILE = 512  # ⭐ t33.TILE. The mosaic feature's gate is 512x512, so a mosaic fixture must be one.

#: The run: 20 contiguous Snapshot trials. Enough for `detect_timing_split` to have an interior
#: (it needs >= 20 % of the steps on each side of a candidate break), which is what makes the pass
#: split testable at all.
RUN_LO, RUN_HI = 11, 30

#: Where the synthetic scan "turns round and starts again". The timing split must FIND this from the
#: timestamps alone — it is never told.
SYNTH_PASS_SPLIT = 20

#: The stage step, in px, between consecutive tiles. 128 px of travel on a 512 px tile = 75 % overlap,
#: which is what makes an honest NCC possible (the real acquisition overlaps ~78 %).
STEP_Y = 128


def _source_image(h: int, w: int, seed: int = 11) -> np.ndarray:
    """A big field of synthetic "tissue": broadband texture the DoG(3,30) band-pass can actually see.

    ⚠️ It must have structure at BOTH ends of the band or the matcher has nothing to lock onto and
    `compute_tone`'s percentile window collapses. Fine grain (sigma ~1.5) + coarse blobs (sigma ~25)
    + a slow illumination ramp, in raw-camera-count units.
    """
    import cv2

    rng = np.random.default_rng(seed)
    fine = cv2.GaussianBlur(rng.standard_normal((h, w)).astype(np.float32), (0, 0), 1.5)
    coarse = cv2.GaussianBlur(rng.standard_normal((h, w)).astype(np.float32), (0, 0), 25.0)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    vignette = 1.0 - 0.15 * ((xx / w - 0.5) ** 2 + (yy / h - 0.5) ** 2)
    img = 3000.0 + 900.0 * fine / (fine.std() + 1e-6) + 700.0 * coarse / (coarse.std() + 1e-6)
    return np.clip(img * vignette, 0, 65535).astype(np.uint16)


_XML = """<?xml version="1.0"?>
<vsdscope>
  <info type="{typ}" trial="{trial:03d}" date="260620" time="{time}"/>
  <ccd>
    <camera frames="{frames}" serpix="{w}" parpix="{h}" typebytes="2" type="uint16">
      <transform ax="{ax}" ay="{ay}"/>
    </camera>
  </ccd>
</vsdscope>
"""


@dataclass(frozen=True)
class Synth:
    """A synthetic acquisition on disk, and the truth about where each tile came from."""

    path: Path
    trials: list[int]
    #: `{trial: (x, y)}` — the tile's TOP-LEFT in the source image. **The answer key for the matcher.**
    origin: dict[int, tuple[int, int]]
    pass_split: int
    flipped: bool

    def truth(self, target: int, anchor: int) -> tuple[float, float]:
        """The world top-left of `target` when `anchor` sits at (0, 0). What a match must return."""
        ax, ay = self.origin[anchor]
        tx, ty = self.origin[target]
        return float(tx - ax), float(ty - ay)


#: ⚠️ A genuine `type="snapshot" frames="1"` trial that is **512x128, not 512x512**. It is real data
#: and it is not a mosaic tile. The mosaic's shape gate must drop it **by shape, loudly** —
#: `off_shape`, with its measured w/h — and never silently reshape those bytes into a 512x512 lie.
#: (The sibling acquisition `260620` really has one of these: trial 021.)
OFF_SHAPE_TRIAL = 9
OFF_SHAPE = (512, 128)

#: Snapshots outside the run, so "the run is the LONGEST contiguous block" has something to choose
#: between. Blocks on disk: (5), (7-9), (11-30) — the same shape as the real (1), (5-7), (11-348).
STRAY_SNAPSHOTS = [5, 7, 8]


def _write_dataset(root: Path, *, flip: bool = True, name: str = "synth") -> Synth:
    root.mkdir(parents=True, exist_ok=True)

    n = RUN_HI - RUN_LO + 1
    src = _source_image(TILE + STEP_Y * (n - 1) + 8, TILE + 16)

    origin: dict[int, tuple[int, int]] = {}
    lines = [f"06/20/26 15:46:58 New experiment: {name}", "         15:47:05 Settings loaded: synth"]
    ax = -1 if flip else 1

    def write_frame(trial: int, tile: np.ndarray, w: int, h: int) -> None:
        raw = np.flip(np.flip(tile, 0), 1) if flip else tile   # the reader flips it BACK.
        np.ascontiguousarray(raw, dtype="<u2").tofile(root / f"{trial:03d}-ccd.dat")
        (root / f"{trial:03d}.xml").write_text(
            _XML.format(typ="snapshot", trial=trial, frames=1, w=w, h=h, ax=ax, ay=ax,
                        time="154700"),
            encoding="utf-8")

    # --- the non-snapshot trials, and the strays -------------------------------------------------
    lines.append("         15:47:10 Trial 001: E'phys. + VSD")
    lines.append("         15:47:20 Trial 002: E'phys. + VSD")
    for t in STRAY_SNAPSHOTS:
        write_frame(t, src[0:TILE, 0:TILE], TILE, TILE)
        lines.append(f"         15:47:{30 + t:02d} Trial {t:03d}: Snapshot")

    # ⛔ real data, wrong shape. Dropped by SHAPE, with a reason. Never by its trial number.
    ow, oh = OFF_SHAPE
    write_frame(OFF_SHAPE_TRIAL, src[0:oh, 0:ow], ow, oh)
    lines.append(f"         15:47:45 Trial {OFF_SHAPE_TRIAL:03d}: Snapshot")

    # --- the run ---------------------------------------------------------------------------------
    t_s = 0  # seconds past 15:48:00
    for i, trial in enumerate(range(RUN_LO, RUN_HI + 1)):
        x, y = 4, 4 + i * STEP_Y
        origin[trial] = (x, y)
        tile = src[y:y + TILE, x:x + TILE]
        assert tile.shape == (TILE, TILE)
        write_frame(trial, tile, TILE, TILE)

        mm, ss = 48 + t_s // 60, t_s % 60
        lines.append(f"         15:{mm:02d}:{ss:02d} Trial {trial:03d}: Snapshot")

        # ⭐ THE TIMING SPLIT, PLANTED IN THE CLOCK AND NOWHERE ELSE. 2 s between tiles, and one 40 s
        # pause where the stage drives back to the origin. `detect_timing_split` must FIND it, from
        # the timestamps alone. Nothing tells it.
        t_s += 40 if trial == SYNTH_PASS_SPLIT else 2

    (root / "log.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return Synth(path=root, trials=list(range(RUN_LO, RUN_HI + 1)), origin=origin,
                 pass_split=SYNTH_PASS_SPLIT, flipped=flip)


@pytest.fixture(scope="session")
def synth(tmp_path_factory) -> Synth:
    """A synthetic vscope acquisition, `ax=-1 ay=-1` like the real one. Session-scoped: ~20 MB and
    ~1 s to write, and every test reads it read-only."""
    return _write_dataset(tmp_path_factory.mktemp("data") / "synthd", flip=True)


@pytest.fixture(scope="session")
def synth_noflip(tmp_path_factory) -> Synth:
    """The same acquisition with `ax=+1, ay=+1`. ⭐ Its only job is to prove that `frame_note` is
    **read off the XML** and never asserted."""
    return _write_dataset(tmp_path_factory.mktemp("data_nf") / "synthn", flip=False)


# =================================================================================================
# The app
# =================================================================================================


@pytest.fixture()
def state_dir(tmp_path, monkeypatch) -> Path:
    """⭐ **ISOLATE THE APP-DATA DIRECTORY.** `core.workspace.app_state_dir()` honours
    `CAMEA_STATE_DIR`, so a test process never reads or writes the real user's settings, recents or
    solve cache. Set it BEFORE anything asks for the settings."""
    d = tmp_path / "state"
    monkeypatch.setenv("CAMEA_STATE_DIR", str(d))
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture()
def client(state_dir) -> TestClient:
    """A fresh app per test, with the module-level singletons reset.

    ⚠️ `SESSIONS`, `SETTINGS`, `JOBS` and the mosaic router's finished-build register are
    process-level, so a test that opened a session would otherwise leak it into the next one. Reset
    them here rather than making every test remember to.

    🔴 `JOBS` matters across FILES, not just tests: `tests/unit/test_mosaic_routes.py` submits into the
    module-level registry a job whose fn returns a bool, and a leaked job whose `result` the API's
    discriminated union cannot serialise makes `GET /api/jobs` 500 here — a failure that appears only
    when `tests/unit` happens to run first. (`test_jobs.py` states the rule: never the module-level
    `JOBS`. This fixture is the safety net for when something does anyway.)
    """
    from camea.api import routes_core
    from camea.api.app import create_app
    from camea.core.document import DOCUMENTS
    from camea.core.jobs import JOBS
    from camea.features.mosaic import routes as mosaic_routes
    from camea.settings import SETTINGS

    routes_core.SESSIONS.clear()
    routes_core.set_window(None)
    routes_core._DATASET_PATHS.clear()
    routes_core._THUMB_CACHE.clear()
    mosaic_routes._BUILDS.clear()
    JOBS.forget_finished()
    DOCUMENTS.clear()
    SETTINGS.clear()                      # resets AND persists into the isolated state_dir

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture()
def workspace(tmp_path) -> Path:
    """A place to put project folders — outside the repo and outside any dataset.

    ⚠️ Since 2026-07-25 there is no app-managed store to choose: a project names **its own** folder
    (`core.project`). This fixture is just a tmp parent to mint those folders under; nothing is
    written and nothing is registered until a project is actually created in one.
    """
    d = tmp_path / "work"
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_project(client: TestClient, session_id: str, folder, *, feature: str = "mosaic",
                name: str = "p", trials=None):
    """`POST /api/projects` — one project, in the folder it names. -> the raw response.

    ⭐ `folder` is required by the contract on purpose: *where to save* is the user's choice, and a
    default would be the app choosing for him. Tests name it too.
    """
    body: dict = {"session_id": session_id, "feature": feature, "name": name,
                  "folder": str(folder)}
    if trials is not None:
        body["trials"] = trials
    return client.post("/api/projects", json=body)


# =================================================================================================
# Helpers
# =================================================================================================


def run_job(client: TestClient, job_id: str, timeout: float = 300.0) -> dict:
    """Poll a job to a terminal state. -> the finished `Job`. **Fails loudly**, with the child's own
    traceback — a job that failed for a reason nobody printed is the worst kind of red test."""
    import time

    t0 = time.time()
    while time.time() - t0 < timeout:
        r = client.get(f"/api/jobs/{job_id}")
        assert r.status_code == 200, r.text
        j = r.json()
        if j["state"] in ("done", "failed", "cancelled"):
            if j["state"] == "failed":
                err = j.get("error") or {}
                raise AssertionError(f"job {job_id} FAILED: {err.get('message')}\n"
                                     f"{err.get('traceback', '')}")
            return j
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish in {timeout:g} s")


def open_session(client: TestClient, path: Path | str, trials: list[int] | None = None) -> dict:
    """Open a dataset and return the `SessionResponse`."""
    r = client.post("/api/sessions", json={"path": str(path), "trials": trials})
    assert r.status_code == 202, r.text
    return run_job(client, r.json()["job_id"])["result"]["session"]


def err(r) -> dict:
    """The `ErrorEnvelope`'s inner body. Every non-2xx in this app has one."""
    body = r.json()
    assert "error" in body, f"not an ErrorEnvelope: {body}"
    return body["error"]
