# ENGINE MOVE — `analysis/mosaic/` → `src/camea/engine/`

**Status:** plan. Nothing has been moved yet.
**Audience:** the implementation agents. Read all of it before you move one file.
**Scope:** what moves, what dies, what breaks, and how the 312/312 guard survives.

> **THE ONE RULE.** `t27.py`, `t33.py`, `quality.py`, `render.py` carry the science. They move
> **byte-identically**. Not reformatted. Not "cleaned". Not re-ordered. If the diff of those four
> files against `archive/analysis/mosaic/` is anything other than empty, you have done it wrong.
> Everything else in this document exists to make a byte-identical move *possible*.

---

## 0. Executive summary

| # | Question | Answer |
|---|---|---|
| 1 | Which modules move? | **`t27` `t33` `quality` `render`** only. `io` `match` `solve` `run` `config` `__init__` **stay archived**. |
| 2 | The vscope problem | The new guard loads frames with **the app's own numpy `.dat` reader**, not `mio.load_frames`. vscope never enters the uv env. Certified once, against all 312 frames, from the existing vscope-written cache. |
| 3 | `score.py`'s paths | `score.py` **does not ship**. It becomes test-support (`tests/guard/score.py`). GT dir comes from **`CAMEA_GT_DIR`** via a `conftest` fixture that fails loudly. |
| 4 | The private reaches | **All six stay private.** One new adapter module (`engine/adapters.py`) is the only thing in the repo allowed to touch them. Zero edits to t27/t33/render. |
| 5 | The 5 `sys.path` bootstraps | All five die on `uv pip install -e .`. **`project.py:76-78` is the hard one** — it puts a *research data directory* on `sys.path` and imports a **flat top-level module named `excluded`**. |
| 6 | The CUDA dances | `t27._cuda_dll_dance` **survives byte-identically** (it is inside t27). `engine._predance_cuda_dlls` **survives, frozen-only**. `engine._predance_env_dlls` — the conda half **dies**, the frozen half **survives**. |
| 7 | Manifest | §7. |

**Two decisions in here deviate from the target layout you were handed** (`engine/ … excluded score`).
Both are called out in §3 and §7 and both are reversible. Read them; do not silently ignore them.

---

## 1. WHICH MODULES MOVE

### 1.1 The four that move: they are a closed set

The science modules import **nothing from the rest of `mosaic/`**. Verified exhaustively — the only
intra-package imports in the four files are:

```
archive/analysis/mosaic/t33.py:105     from . import t27
archive/analysis/mosaic/t27.py:179     from . import quality        (inside band_pass)
archive/analysis/mosaic/t27.py:413     from . import quality        (inside NccBank.validate)
archive/analysis/mosaic/render.py      — none
archive/analysis/mosaic/quality.py     — none
```

So the live chain the task names is real and it is the *whole* graph:

```
t33.place()  →  t33.py:665  t27.band_pass(frames)
             →  t27.py:175  band_pass()  →  t27.py:179  from . import quality
             →  quality.py:17  quality.band_pass()  →  cv2.GaussianBlur   (DoG 3-30)
```

`t33` also reaches `t27.swim_all`, `t27.NccBank`, `t27.dealias`, `t27.precheck`,
`t27.fix_backbone`, `t27.permutation_floor`, `t27.place`, `t27.xp`, `t27.on_gpu`, `t27._free`,
`t27.WHT`, `t27._np`. All siblings. **`from . import t27` and `from . import quality` resolve
unchanged inside `src/camea/engine/` because they are relative.** That is the entire reason a
byte-identical move works.

Third-party imports, and *when* they happen:

| module | module-level | deferred (inside a function) |
|---|---|---|
| `t27.py` | `glob os time collections numpy` | `spectralign` (`_swim_reference`, `solve_rigid`), `cupy` (`xp()`), `quality` |
| `t33.py` | `hashlib json os time contextlib io pathlib numpy` + `. import t27` | — |
| `quality.py` | `pathlib numpy os` | `cv2`, `pandas`, `matplotlib` |
| `render.py` | `numpy` | `matplotlib`, `spectralign` |

**Importing `camea.engine` costs numpy and nothing else.** No cv2 until the first band-pass, no
cupy until the first `xp()`, no spectralign until the first solve, no matplotlib ever unless you
ask for a layout PNG. Keep it that way.

### 1.2 The five that stay archived

Does the app need any of them? **No.** `archive/app-v1/backend/engine.py` — the only module in the
old app permitted to touch the engine — imports exactly this and nothing more:

```
archive/app-v1/backend/engine.py:192   from analysis.mosaic import render as mrender
archive/app-v1/backend/engine.py:193   from analysis.mosaic import t27, t33
```

| module | verdict | why |
|---|---|---|
| `io.py` | **stays archived** | It is the vscope frame reader (`io.py:28 import vscope`) plus a DoG and the flat-field. The app already owns all three (§2). Moving it re-introduces vscope **and** a second frame reader. Its cache check (`io.py:23`) validates *only* `shape[0] == len(trials)` — a cache keyed by count alone, which is exactly the bug class `t33._tag` was rewritten to kill. It must not come near the new tree. |
| `run.py` | **stays archived** | `run.py:8 import pandas as pd` **at module level**. pandas is **not** in the uv env (confirmed: `.venv/Lib/site-packages` has no `pandas`). It is the notebook build pipeline (`BuildConfig` → `build()`), which the app never calls. |
| `match.py` | **stays archived** | The old swappable matchers (Fullframe/Subregion/Fused). Only `run.py` calls them. `match.py:75` imports pandas. |
| `solve.py` | **stays archived** | `backbone_chain` / `refine` — only `run.py` calls them. t27 has its own `solve_rigid` / `solve_irls`. |
| `config.py` | **stays archived** | `BuildConfig` for the old six-stage pipeline. Dead in the new app. |

### 1.3 `__init__.py` — do NOT move the PEP 562 shim

`archive/analysis/mosaic/__init__.py` is a lazy-attribute shim whose entire purpose is documented in
its own docstring (lines 16-25): stop `import mosaic` from eagerly importing `.run`, which imports
pandas, which "made `import analysis.mosaic.t33` fail outright with `ModuleNotFoundError: No module
named 'pandas'` on a clean install".

**Once `run.py` / `match.py` do not move, there is nothing left to be lazy about.** The shim solves a
problem that no longer exists, and it costs real clarity (`_LAZY` dict, `__getattr__`, `TYPE_CHECKING`
block). Write a fresh `src/camea/engine/__init__.py`:

```python
"""The placement engine. t27/t33/quality/render are moved BYTE-IDENTICALLY from
archive/analysis/mosaic/ and are under the 312/312 regression guard (tests/slow/).
Do not edit them. Everything the app needs that is not public API lives in adapters.py."""
from . import dll          # side effect: the frozen-only DLL pre-dance. MUST be first. See §6.
dll.predance()

from . import excluded, quality, render, t27, t33   # noqa: E402
from .adapters import canvas, free_gpu, read_anchors, build_memo   # noqa: E402

__all__ = ["t27", "t33", "quality", "render", "excluded",
           "canvas", "free_gpu", "read_anchors", "build_memo"]
```

⚠️ `dll.predance()` **must run before anything imports cupy or calls `numpy.linalg`**, and it must run
in the **spawned build child** too (spawn re-imports the module). Module scope of
`camea/engine/__init__.py` is the one place that guarantees both. This mirrors what
`archive/app-v1/backend/engine.py:165-166` did, and it did it for a measured reason (§6).

---

## 2. 🔴 THE vscope PROBLEM

### The problem, precisely

`archive/analysis/mosaic/io.py:28` does `import vscope`, and the old guard
(`archive/analysis/tests/test_mosaic_312.py:69`) calls `mio.load_frames(...)`.

**vscope cannot be pip-installed.** It declares `Requires-Dist: cairo`; there is no package named
`cairo` on PyPI. It is therefore not in `.venv` and it never will be. If the new guard calls
`mio.load_frames`, it dies at import.

### The answer

**The guard loads frames with the app's own numpy `.dat` reader. `io.py` never moves. vscope never
enters the uv env.**

The reader already exists and is already proven:

```
archive/app-v1/backend/loader.py:460   load_frame(meta)   -> float32 (h,w), vscope DISPLAY orientation
archive/app-v1/backend/loader.py:484   load_frames(dir, trials) -> float32 (N,512,512), row i IS trials[i]
```

It ports to `src/camea/core/frames.py` (that is another agent's file — this doc only depends on the
function existing there with that behaviour).

### Why this is correct, not merely convenient

1. **It is byte-identical to vscope, and that is asserted, not asserted-in-a-comment.**
   `archive/app-v1/backend/loader.py:1140-1142`:
   ```python
   import vscope
   v = vscope.load(str(D / "011.xml")).ccd["Cc"][0]
   ck("== vscope display frame", bool(np.array_equal(f, v.astype(np.float32))), True)
   ```
   and `loader.py:7-8` records it verified on trials 11, 12, 166, 167, 347.

2. **The dtype path is identical too.** `io.load_frames` does
   `frames[i] = np.asarray(vs.ccd[k][0], float)` into a preallocated `np.float32` array — a
   float64→float32 cast of integer-valued uint16 (≤ 65535 < 2²⁴, exactly representable). The numpy
   reader produces float32 of the same integers directly. **Same bits.**

3. **⭐ THE 180° FLIP IS LOAD-BEARING.** vscope returns the *display* frame; the XML says
   `ax=-1, ay=-1`, so the raw array is rotated 180°. `loader.load_frame` reproduces that from
   `meta["flip_x"] / meta["flip_y"]`. **Every SWIM dx/dy and all three ground truths live in the
   flipped frame.** A reader that skips the flip produces a mosaic that is 180° out from every prior
   result *and it will look plausible*. Do not write a naive `np.fromfile().reshape(512,512)`.

4. **It deletes the frame cache and the whole stale-cache failure mode.** `loader.py:484` measures
   **338 frames in ~0.13 s**. There is no reason to cache. So:
   - `FRAME_CACHE` (`test_mosaic_312.py:56`) — **gone**.
   - `--cold-frames` (`test_mosaic_312.py:30`) — **gone**; every run *is* cold-frames.
   - `archive/analysis/output/tests/frames_011-348_n312.npy` (327 MB) — **not used by the new
     guard**, and not copied into the repo (`.gitignore` blocks `*.npy` anyway).

### Certify it once, against all 312 frames — then never think about it again

The existing cache **is vscope's own output for exactly the 312 trials the guard uses**. That makes a
decisive, zero-vscope certification available for free. Do it as a one-shot `slow` test:

`tests/slow/test_reader_matches_vscope.py`
```python
"""The numpy .dat reader IS vscope. Proven on all 312 guard frames, not on 5.

archive/analysis/output/tests/frames_011-348_n312.npy was written by mosaic.io.load_frames,
i.e. BY VSCOPE, over usable_trials(11, 348). If our reader reproduces it bit-for-bit, the guard
may drop vscope entirely. Runs only if that cache is on disk; it is not a repo artefact.
"""
def test_reader_is_vscope(dataset_dir, gt_dir, vscope_cache):
    trials = load_excluded(gt_dir).usable_trials(11, 348)
    ours = frames.load_frames(dataset_dir, trials)          # camea.core.frames
    theirs = np.load(vscope_cache)                          # vscope, 312 x 512 x 512 float32
    assert ours.shape == theirs.shape == (312, 512, 512)
    assert np.array_equal(ours, theirs), "the numpy reader is NOT vscope. STOP."
```

If this passes, the vscope question is closed permanently. If it fails, **stop the whole migration** —
you have found a real orientation/dtype bug, and every number downstream is wrong.

> The guard's own 312/312 assertion is itself a second, independent proof: t33 on differently-decoded
> pixels would not land 312 tiles inside 10 px of a hand-placed truth. But do not rely on that alone —
> it tells you *that* something broke, not *what*.

---

## 3. 🔴 `score.py`'s PATHS

### The problem, precisely

```python
archive/analysis/benchmark/score.py:50-55
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                                   # analysis/
GT_DIR = ROOT / "ground_truth"
sys.path.insert(0, str(GT_DIR))
from excluded import EXCLUDED, usable_trials, gaps   # ← FLAT top-level module
```
```python
archive/analysis/benchmark/score.py:69-79
RANGES = {
  "pass1":  dict(..., gt=GT_DIR / "260620d_pass1_11-166.json", ...),
  "pass2":  dict(..., gt=GT_DIR / "260620d_pass2_167-348.json", ...),
  "merged": dict(..., gt=GT_DIR / "260620d_merged_11-348.json", ...),
}
```

Three things are broken by the move, and one of them is not a path problem at all:

1. **`GT_DIR` is derived from `__file__`.** Move `score.py` anywhere and it points at nothing.
2. **The GT JSONs are unpublishable.** They are the hand-authored answer key. `.gitignore` excludes
   `/archive/` wholesale and they are not tracked (`git ls-files archive/analysis/ground_truth/` →
   empty). **They must never be committed.** A packaged `score.py` whose module-level constants are
   `Path`s into a gitignored directory is a landmine: it imports fine and fails at the first
   `load_gt()`.
3. **`score.py` is dataset knowledge, in code.** `RANGES` hard-codes `lo=11 hi=166 n=156`,
   `lo=167 hi=348 n=156`, `lo=11 hi=348 n=312`, and the filenames `260620d_*`. It imports `EXCLUDED`.
   That is the 260620d ruling, spelled out.

### 🟡 DECISION — `score.py` DOES NOT SHIP

**It moves to `tests/guard/score.py`, not `src/camea/engine/score.py`.** This deviates from the target
layout you were handed. The reason is hard rule #4:

> *"⛔ THE APP MUST CARRY NO DATASET KNOWLEDGE. … It answered, on the user's behalf, the exact
> question the app exists to help him answer."*

`score.py` is a scorer **for one acquisition's answer key**. Its denominators (156/156/312), its trial
ranges (11/166/167/348) and its `EXCLUDED` import are 260620d, and nothing else. Putting it in
`src/camea/engine/` puts all of that inside a pip-installable wheel, and it puts an
`EXCLUDED`/`usable_trials` import back into the app's import graph — the exact thing that was ripped
out at real cost. `archive/app-v1/backend/engine.py:1644` already knew this: `score_against_gt` is
labelled *"OPTIONAL, dev-only … 260620d only"*. Dev-only code belongs in `tests/`, where the rule
does not apply and where it cannot be shipped by accident.

**If the parent overrules this**, the fallback is `src/camea/engine/score.py` with all GT paths made
lazy (`_gt_path(rng)` reading `CAMEA_GT_DIR` at call time, never at import) and `EXCLUDED` loaded
lazily by path — but understand that you are then shipping the answer key's schema, its denominators
and its trial ranges inside the app.

### 🟡 DECISION — `excluded.py` SPLITS

Same reasoning, and it is the cleaner half of the same cut.

| goes to | contents | why |
|---|---|---|
| **`src/camea/engine/excluded.py`** (new file) | **`gaps()` and nothing else** — the body copied verbatim from `archive/analysis/ground_truth/excluded.py:65-68`, plus a docstring saying why the rest is absent. | The app needs exactly one function, it is pure, and there must be exactly one implementation of it in the repo. |
| **stays in `archive/analysis/ground_truth/excluded.py`** | `DATA_DIR`, `EXCLUDED`, `BLANK`, `BLURRY`, `PASS1/PASS2/MERGED`, `is_snapshot()`, `usable_trials()` | It is 260620d's ruling. The guard reads it **from `CAMEA_GT_DIR`, by path** — the same directory that holds the answer key it belongs to. |

This makes rule #4 **structural** instead of conventional: the app cannot import `EXCLUDED` because
`camea.engine.excluded` does not have one. Note the collateral benefit: `excluded.py:32` hard-codes
`DATA_DIR = Path(r"D:/Projects/Camea/data/drive/260620/260620_Imaging/260620d")` — a path on the
user's machine — and `usable_trials()` calls `is_snapshot()` against it. That absolutely cannot ship
in a wheel.

### The mechanism: `CAMEA_GT_DIR` + a conftest fixture

`tests/slow/conftest.py` (new):

```python
import os, importlib.util
from pathlib import Path
import pytest

DEFAULT_GT   = Path("D:/Projects/Camea/archive/analysis/ground_truth")
DEFAULT_DATA = Path("D:/Projects/Camea/data/drive/260620/260620_Imaging/260620d")

_MISSING_GT = """
THE 312/312 GUARD CANNOT RUN: the ground truth is not on this machine.

  looked in: {path}
  set it   : CAMEA_GT_DIR=<dir>            (PowerShell: $env:CAMEA_GT_DIR = '<dir>')

That directory must contain the hand-authored answer key and the exclusion ruling:
    260620d_pass1_11-166.json
    260620d_pass2_167-348.json
    260620d_merged_11-348.json
    excluded.py

⛔ These files are NOT in the repo and MUST NEVER BE COMMITTED. They are the human's answer key;
   committing them destroys the benchmark for everyone who clones. They live under archive/,
   which .gitignore excludes wholesale. Keep it that way.

This is a HARD FAILURE, not a skip. You asked for `-m slow`; the guard is the only thing standing
between a refactor and silently breaking the science, and a green run that quietly measured nothing
is worse than a red one.
"""

def _dir(env, default, msg):
    p = Path(os.environ.get(env, default))
    if not p.is_dir():
        pytest.fail(msg.format(path=p), pytrace=False)
    return p

@pytest.fixture(scope="session")
def gt_dir():
    p = _dir("CAMEA_GT_DIR", DEFAULT_GT, _MISSING_GT)
    for f in ("260620d_merged_11-348.json", "excluded.py"):
        if not (p / f).exists():
            pytest.fail(_MISSING_GT.format(path=p) + f"\n  missing: {f}", pytrace=False)
    return p

@pytest.fixture(scope="session")
def dataset_dir():
    return _dir("CAMEA_DATA_DIR", DEFAULT_DATA, _MISSING_DATA)   # same shape of message

@pytest.fixture(scope="session")
def gt_excluded(gt_dir):
    """archive's excluded.py, loaded BY PATH. Never sys.path.insert — that leaks a top-level
    module named `excluded` into every other test in the session (see §5, project.py)."""
    spec = importlib.util.spec_from_file_location("_camea_gt_excluded", gt_dir / "excluded.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
```

Rules this encodes, and each one is deliberate:

- **`pytest.fail`, never `pytest.skip`.** `pyproject.toml` already has `addopts = "-m 'not slow'"`, so
  the guard is off by default and CI never sees it. The *only* way it runs is that someone explicitly
  asked for it. A skip at that point is a green tick that measured nothing.
- **Load `excluded.py` by path, not by `sys.path.insert`.** `spec_from_file_location` under a private
  name (`_camea_gt_excluded`). This is the difference between the new guard and `score.py:54`.
- **`score.py` takes `GT_DIR` as an argument.** In `tests/guard/score.py`, `RANGES` becomes a function
  `ranges(gt_dir)` and `load_gt(gt_dir, rng=...)` takes it explicitly. **`robust_align` (score.py:134)
  and `score()` (score.py:208) are copied BYTE-FOR-BYTE.** score.py:24-27 is not decoration: a
  reimplementation with a different tie-break scored the same T27 positions **152/156 where this one
  gives 155/156**.
- **`DATA_DIR` mismatch is caught, not silent.** If `CAMEA_DATA_DIR` points somewhere other than
  `excluded.DATA_DIR`, `usable_trials()` still consults `excluded.DATA_DIR` via `is_snapshot()`. The
  guard's `assert len(trials) == 312` catches it. Add one more free assertion:
  `assert set(trials) == set(gt)` — the trial list and the answer key must describe the same tiles.

---

## 4. THE PRIVATE REACHES

I grepped every `t27.` / `t33.` / `mrender.` in `archive/app-v1/backend/engine.py` and separated the
call sites from the docstring mentions. **`t33._surfaces`, `t27.solve_rigid` and `t27._cuda_dll_dance`
are named only in prose** (engine.py:1092, :112, :56-58) — they are never called. The real list is
six.

| # | reach | where | what it is | **verdict** |
|---|---|---|---|---|
| 1 | `t33._pool` (monkey-patch) | `engine.py:1099-1118` | Memoise the pooled pass-1 composite across the 156-call anchor loop. | **KEEP PRIVATE. Keep the patch.** |
| 2 | `t33._tag` | `engine.py:1360` | Cache-name for a trial *set* (sha1 of membership). | **KEEP PRIVATE. Adapter.** |
| 3 | `t33._cache_key` | `engine.py:1359` | `(json, sha1)` of the config the cached arrays depend on. | **KEEP PRIVATE. Adapter.** |
| 4 | `t33._load_checked` | `engine.py:1363` | Load an npz, **refuse** it if the config hash differs. | **KEEP PRIVATE. Adapter.** |
| 5 | `t27._free` | `engine.py:361, 372, 1001` | `cupy.get_default_memory_pool().free_all_blocks()`. | **KEEP PRIVATE. Adapter.** |
| 6 | `render._canvas` | `engine.py:1602` | Integer tile top-lefts + (H, W) on the union canvas. Pure geometry. | **KEEP PRIVATE. Adapter.** |

### Why "keep private" for all six, when we now own the engine

Because **renaming any of them means editing a file under the guard, and buys nothing.**
`_tag` → `tag` is three edits in t33.py; `_pool` → `pool` is a `def` plus two call sites inside
`match()`; `_canvas` → `canvas` is a `def` plus two call sites in render.py. Every one of those is a
byte-change to a file whose contract is *"byte-identical or you have broken the science"*, in exchange
for a leading underscore. Rule #5 says renaming is *the most* you may propose — it does not say you
should. **Don't.**

The correct move is one new file — **`src/camea/engine/adapters.py`** — which is the **only** place in
the repo permitted to touch an underscore on t27/t33/render. It is not under the guard, so it can be
edited freely; and if some future agent ever *does* rename something in t33, exactly one file breaks,
loudly, at import.

```python
"""The ONE module allowed to touch t27/t33/render privates.

t27/t33/quality/render are byte-identical from archive/analysis/mosaic/ and are under the 312/312
guard (tests/slow/test_mosaic_312.py). We do NOT rename their internals to make them public: a rename
is a byte-change to guarded code in exchange for an underscore. Instead every private reach lives
here, behind a public name, and there are exactly six of them.
"""
from contextlib import contextmanager
from pathlib import Path
import numpy as np
from . import render, t27, t33

_TILE = 512

# --- 6. render._canvas ------------------------------------------------------------------
def canvas(pos, tilesize=(_TILE, _TILE)):
    """(trials, P, H, W) — the integer tile top-lefts on the union canvas. Pure geometry; no
    pixels touched. Feeds the coverage mask (13.1% of the canvas is background encoded as
    exactly 0.0 and there is no alpha channel — the mask is NOT optional)."""
    return render._canvas(pos, tilesize)

# --- 5. t27._free -----------------------------------------------------------------------
def free_gpu():
    """Release CuPy's block pool. No-op on CPU."""
    t27._free()

# --- 2/3/4. t33._tag + _cache_key + _load_checked ---------------------------------------
def read_anchors(cache_dir, trials, cfg) -> dict:
    """The per-tile anchors t33 cached but did not return -> {trial: {"anc":[x,y], "ncc":v}}.

    Verbatim in behaviour from engine.py:1344-1374, including the on-any-failure `return {}`:
    if t33 ever renames these, this degrades to "no per-tile confidence", NEVER to wrong data.
    """
    ...   # port engine.py:1344-1374 unchanged; t33._cache_key / t33._tag / t33._load_checked

# --- 1. t33._pool -----------------------------------------------------------------------
@contextmanager
def build_memo(max_entries: int = 2):
    """Memoise t33._pool on the REFERENCE side of the anchor loop. BIT-IDENTICAL by construction:
    it caches the real function's own OUTPUT OBJECT, keyed by array IDENTITY (`is`), holding strong
    refs so an id() cannot be recycled. It does not reimplement _pool, does not touch _smooth() and
    does not change any FFT size (the grid stays 2160x1350).

    ⚠️ A CONTEXT MANAGER, not the old enable/disable pair, so it CANNOT leak out of the build child
    and be live when the guard runs. The guard must see an unpatched t33 — assert it (see below).
    """
    ...   # port engine.py:1076-1122 unchanged, restoring t33._pool in a finally:
```

### One assertion the guard must gain

The old code was `enable_build_memo()` / `disable_build_memo()` — a global, permanent monkey-patch on
a module the guard also imports. Nothing enforced that it was off. Add, to the guard:

```python
assert t33._pool.__module__ == t33.__name__, \
    "t33._pool is monkey-patched. The guard must measure the UNPATCHED engine."
```

Cheap, and it closes the one way the memo could ever contaminate the number that matters.

---

## 5. THE 5 `sys.path` BOOTSTRAPS

All five exist for one reason: **`analysis/` and `app/` were sibling directories under a repo root
that was never on `sys.path`.** `uv pip install -e .` (or `uv sync`, which does it) puts
`src/camea` on the path as a real, importable, installed package. Every one of these then dies —
**not "can be removed", but is actively wrong**, because a stale `sys.path.insert` would let a
*second* copy of the engine be importable and that is a silent regression.

| # | site | what it does now | why it dies |
|---|---|---|---|
| 1 | `archive/app-v1/main.py:51-53` | `REPO_ROOT = _MEIPASS or parent.parent`; `sys.path.insert(0, REPO_ROOT)` | `src/camea/__main__.py` is the console-script entry point (`[project.scripts] camea = "camea.__main__:main"`, already in `pyproject.toml`). The package is installed. **Dies.** |
| 2 | `archive/app-v1/backend/server.py:49-51` | same, to import `app.backend.*` and `analysis.*` | `src/camea/api/app.py` does `from camea.core import …`, `from camea.features.mosaic import …`. **Dies.** |
| 3 | `archive/app-v1/backend/engine.py:172-193` | `_repo_root()` (+ `CAMEA_REPO_ROOT` env override) → `sys.path.insert` → `from analysis.mosaic import t27, t33, render` | `from camea.engine import t27, t33, render`. **Dies — and so does `CAMEA_REPO_ROOT`.** Delete that env var; a "point the app at a different copy of the engine" knob is a loaded gun now that the engine is *in* the app. |
| 4 | `archive/app-v1/backend/loader.py:51-61` | `sys.path.insert(repo_root)` → `from analysis.ground_truth.excluded import gaps as _canonical_gaps` | `from camea.engine.excluded import gaps`. **Dies.** |
| 5 | `archive/app-v1/backend/project.py:76-78` | `sys.path.insert(analysis/ground_truth)` → `import excluded as _excluded` | `from camea.engine.excluded import gaps`. **Dies. See below.** |

*(There is a sixth, and it is the guard's: `archive/analysis/benchmark/score.py:54`. Same flat-import
disease. Handled in §3 by `importlib.util.spec_from_file_location`.)*

### 🔴 `project.py:76-78` — the single hardest blocker to packaging

```python
archive/app-v1/backend/project.py:76-78
_GT_DIR = _ROOT / "analysis" / "ground_truth"
if str(_GT_DIR) not in sys.path:
    sys.path.insert(0, str(_GT_DIR))
import excluded as _excluded                          # noqa: E402  gaps() ONLY
```

This is worse than the other four, and it is worse in **four independent ways**:

1. **It puts a DATA DIRECTORY on the import path.** Not a code tree — the directory that holds the
   hand-authored answer key (`260620d_*.json`) and rendered PNGs. The app's ability to *import* is
   made conditional on a research artefact being present on disk. That is the coupling rule #4 exists
   to forbid, expressed as an import statement.
2. **It imports a FLAT, TOP-LEVEL module named `excluded`.** That name is global to the interpreter.
   Any other `excluded.py` anywhere earlier on `sys.path` — a test fixture, another package, a
   notebook's scratch file — shadows it, and the app silently gets a *different* `gaps()`. There is no
   namespace to protect it.
3. **setuptools cannot package it.** `[tool.setuptools.packages.find] where = ["src"]`. A loose module
   sitting in a data directory outside `src/` is not a package, is not a module of a package, and has
   no `__init__.py` anywhere in its lineage. There is **no** `pip install` that carries it. The old
   app worked only because it was never installed — it was run from a checkout.
4. **Under PyInstaller the directory does not exist at all.** `_ROOT` becomes `sys._MEIPASS`;
   `<_MEIPASS>/analysis/ground_truth` is whatever agent 8 remembered to vendor in. The shipped app's
   `gaps()` would be one forgotten `--add-data` away from an `ImportError` at startup.

It dies the instant `gaps()` has a real, packaged home:

```python
from camea.engine.excluded import gaps      # one import. no sys.path. no data directory.
```

**This is the load-bearing reason `excluded.py` must split (§3).** As long as the *only* home of
`gaps()` is a file inside `analysis/ground_truth/`, some module somewhere has to reach into that
directory to get it — and every route into that directory is one of the four failures above.

---

## 6. THE CUDA DLL DANCES

There are **three** dances, not two. Two are in `engine.py`; one is inside t27 itself.

| dance | where | verdict |
|---|---|---|
| `t27._cuda_dll_dance()` | `archive/analysis/mosaic/t27.py:120`, called from `t27.xp()` (t27.py:141) | **SURVIVES — byte-identically. It is inside t27. You could not remove it if you wanted to.** |
| `_predance_cuda_dlls()` | `archive/app-v1/backend/engine.py:54-96`, run at module scope (`:165`) | **SURVIVES, but FROZEN-ONLY.** Dead weight under uv; still mandatory for PyInstaller. |
| `_predance_env_dlls()` | `archive/app-v1/backend/engine.py:99-163`, run at module scope (`:166`) | **The conda half DIES. The frozen half SURVIVES.** |

### `t27._cuda_dll_dance` — survives, and under uv it is *sufficient on its own*

It globs `sysconfig.get_paths()["purelib"] / nvidia/*/bin`, `os.add_dll_directory`s each, and prepends
them to `PATH` (both mechanisms are needed and they are not the same one: `add_dll_directory` for the
`.pyd`'s dependent DLLs, `PATH` for NVRTC's plain `LoadLibrary` of `nvrtc-builtins`).

In a **uv venv**, `purelib` is `.venv/Lib/site-packages`, and `cupy-cuda12x[ctk]` populates
`site-packages/nvidia/*/bin` there. Confirmed on this machine: `.venv/Lib/site-packages/nvidia/` and
eight `nvidia_*_cu12` dist-infos are present. And `pyproject.toml` already records the verification:

> *"Verified 2026-07-14 under a clean uv venv: `t27.on_gpu()=True`, xp=cupy, CuPy 14.1.1, CUDA runtime
> 12090. Without `[ctk]`: 0 nvidia/*/bin dirs, xp=numpy."*

**So for `uv run` — dev, test, and the guard — no pre-dance is needed at all.** t27 does it itself.

### `_predance_cuda_dlls` — survives, gated on `sys._MEIPASS`

The reason it exists is airtight and it is not about uv (engine.py:58-64): under PyInstaller
`sys.prefix` **is** `sys._MEIPASS`, so `purelib` resolves to `<_MEIPASS>/Lib/site-packages`, **which
does not exist**. t27's own dance globs an empty path, finds nothing, `cupy.zeros(1)+1` raises
`CuPy failed to load nvrtc64_120_0.dll`, and **the shipped app reports "No usable CUDA GPU" on a
machine with a perfectly good card** — every build 8-10 min instead of 3, forever, with nothing in the
UI hinting the cause is a search path.

So keep it, but make its frozen-only nature explicit rather than incidental:

`src/camea/engine/dll.py` (new)
```python
"""The DLL pre-dance. FROZEN BUILDS ONLY.

Under `uv run` this is a NO-OP and it must stay one: t27._cuda_dll_dance() (t27.py:120) already
globs the uv venv's site-packages/nvidia/*/bin, and t27.on_gpu() is True with no help. Verified
2026-07-14 (pyproject.toml, the [gpu] extra).

Under PyInstaller, sys.prefix IS sys._MEIPASS, so t27's dance globs a directory that does not
exist and finds NOTHING -> "No usable CUDA GPU" on a machine with a good card. That is what this
is for, and ONLY that.

⚠️ MODULE SCOPE OF camea/engine/__init__.py, before the first t27.xp() and before the first
numpy.linalg call — and it must run in the SPAWNED BUILD CHILD too (spawn re-imports the module).
"""
def predance() -> list[str]:
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return []                        # uv: t27 handles itself. Do nothing.
    return _cuda_dlls(meipass) + _blas_dlls(meipass)
```

Idempotent, exactly as before: if it has already added a directory, t27's dance re-adds the same one
(harmless).

### `_predance_env_dlls` — the conda half dies, the frozen half must not

This one is **not** about CUDA. Read engine.py:99-120: `numpy.linalg` **delay-loads** its BLAS. Started
from `<conda-env>/python.exe` *without the env activated*, that delay-load fails and Windows
**fast-fails the process with 0xC0000409 / exit 3228369023** — a native crash, no Python exception,
nothing to catch. It killed the build child ~20 s in, every cold build, because
`t27.solve_rigid` (t27.py:693 → `spectralign.placement.rigid` → `np.linalg.solve`) is on the cold path
and only the cold path. A *warm* build survived, because the cache skips pass 1 and never calls BLAS.
The job reported only `"the build process exited with code 3228369023"`.

- **The conda roots die.** `<sys.prefix>/Library/bin`, `Library/mingw-w64/bin`, `Library/usr/bin`,
  `DLLs` are **conda layout**. A uv venv has none of them; the loop is already a no-op there. And
  numpy's PyPI wheel ships its BLAS in `numpy.libs/` and registers that directory itself in
  `numpy/__init__.py`. **Delete the conda branch. Do not port it.**
- **The frozen roots survive.** Under PyInstaller, native DLLs get flattened to the bundle root and
  `numpy.libs/` may or may not survive as a directory. So keep exactly the `_MEIPASS` candidates:
  `_MEIPASS`, `_MEIPASS/numpy.libs`, `_MEIPASS/numpy/.libs`, `_MEIPASS/scipy.libs`,
  `_MEIPASS/_internal`.

**⭐ THE PROOF IS FREE, AND YOU MUST TAKE IT.** The failing call is `np.linalg.solve`, on the *cold*
path, inside `t27.solve_rigid`. **The 312/312 guard runs t33 fully cold (`cache=None`), so it calls
`solve_rigid` twice.** If the guard is green under `uv run pytest -m slow`, the BLAS delay-load under
uv is *proven fine* and `_predance_env_dlls`'s conda half is proven dead. Do not reason about it —
run the guard.

And the frozen half is **not** proven by anything yet. `archive/app-v1/backend/engine.py:130-136` says
so itself: *"this needs a real freeze + a real cold build to prove — a REQUIRED smoke test, not a
note."* Carry that requirement forward verbatim into the packaging work. The failure is invisible
until someone builds a dataset for the first time, **which is every user, once.**

---

## 7. THE EXACT FILE MANIFEST

### 7.1 Moves

| old path | new path | verdict |
|---|---|---|
| `archive/analysis/mosaic/t27.py` (832) | `src/camea/engine/t27.py` | **BYTE-IDENTICAL.** `from . import quality` (t27.py:179, :413) resolves as a sibling. |
| `archive/analysis/mosaic/t33.py` (911) | `src/camea/engine/t33.py` | **BYTE-IDENTICAL.** `from . import t27` (t33.py:105) resolves as a sibling. |
| `archive/analysis/mosaic/quality.py` | `src/camea/engine/quality.py` | **BYTE-IDENTICAL.** See the caveat in §7.4 — move it anyway, do not trim it in this commit. |
| `archive/analysis/mosaic/render.py` | `src/camea/engine/render.py` | **BYTE-IDENTICAL.** matplotlib (`:33`) and spectralign (`:72`) are both lazy and both are declared deps. |
| `archive/analysis/ground_truth/excluded.py :: gaps()` (lines 65-68) | `src/camea/engine/excluded.py` | **NEW FILE, function body verbatim.** `gaps()` **only**. §3. |
| `archive/analysis/benchmark/score.py` | `tests/guard/score.py` | **EDITED** — and **not shipped**. §3. Deletes `:50-55` (the `sys.path.insert` + flat `from excluded import`); `RANGES` becomes `ranges(gt_dir)`; `load_gt` takes `gt_dir`. **`robust_align` (`:134-183`) and `score()` (`:208-259`) are copied byte-for-byte** — score.py:24-27: a reimplementation with a different tie-break scored the same positions **152/156 where this one gives 155/156**. |
| `archive/analysis/tests/test_mosaic_312.py` | `tests/slow/test_mosaic_312.py` | **EDITED.** §7.3. |

### 7.2 New files

| path | why |
|---|---|
| `src/camea/engine/__init__.py` | Fresh. Calls `dll.predance()` at module scope, then re-exports. **Not** the PEP 562 shim (§1.3). |
| `src/camea/engine/adapters.py` | The ONE module allowed to touch t27/t33/render privates: `canvas`, `free_gpu`, `read_anchors`, `build_memo` (§4). |
| `src/camea/engine/dll.py` | The frozen-only pre-dance (§6). No-op under uv. |
| `tests/slow/conftest.py` | `gt_dir` / `dataset_dir` / `gt_excluded` fixtures; **`pytest.fail`, never `skip`** (§3). |
| `tests/slow/test_mosaic_312.py` | THE GUARD. |
| `tests/slow/test_reader_matches_vscope.py` | One-shot certification: the numpy reader == vscope, on **all 312** guard frames (§2). |
| `tests/guard/score.py` (+ `__init__.py`) | The canonical scorer, as test support. |

### 7.3 The new guard, precisely

Four assertions in, four assertions out. Every edit below is plumbing; **not one of them touches what
is measured.**

| old (`archive/analysis/tests/test_mosaic_312.py`) | new | why |
|---|---|---|
| `:42-45` three `sys.path.insert`s | **deleted** | the package is installed (§5) |
| `:47` `from mosaic import io as mio, t27, t33` | `from camea.engine import t27, t33` + `from camea.core import frames` | io.py does not move; vscope is gone (§2) |
| `:48` `import score as bscore` | `from tests.guard import score as bscore` | §3 |
| `:49` `from excluded import EXCLUDED, MERGED, PASS1, usable_trials` | `gt_excluded` fixture (by path, from `CAMEA_GT_DIR`) | §3 |
| `:51-52` `DATA_ROOT` / `DATE_DIR` literals | `dataset_dir` fixture (`CAMEA_DATA_DIR`) | §3 |
| `:56` `FRAME_CACHE` + `:70` `cache=` + `:30` `--cold-frames` | **deleted** | frames are read raw every run, ~0.13 s (§2) |
| `:69` `mio.load_frames(DATA_ROOT, DATE_DIR, trials, cache=…)` | `frames.load_frames(dataset_dir, trials)` | §2 |
| `:73-75` `t33.Config(pass_split=166, t27=t27.Config(control=False))`; `t33.place(..., cache=None)` | **unchanged** | ⚠️ `cache=None` is **THE** point: a guard that reads back its own previous answer is not a guard |
| `:85-103` the four checks | **unchanged** | 312 placed · `pass1_max_dev == 0.0` · 312/312 within 10 px · `not rule_break` |
| — | **+** `assert t33._pool.__module__ == t33.__name__` | the memo must not be live (§4) |
| — | **+** `assert set(trials) == set(gt)` | the trial list and the answer key describe the same tiles (§3) |
| `:136` `def test_merged_312()` | keep, `@pytest.mark.slow` | `pyproject.toml` already declares the marker and `addopts = "-m 'not slow'"` |

Run it: `uv run pytest -m slow tests/slow/test_mosaic_312.py -s` — ~130 s, needs the GPU and the
mirror. **If it goes red: STOP. Do not fix forward.**

### 7.4 Stays archived — and one caveat you must not "fix"

`io.py`, `match.py`, `solve.py`, `run.py`, `config.py`, `mosaic/__init__.py`,
`archive/analysis/ground_truth/excluded.py` (the ruling), the three GT JSONs,
`archive/analysis/output/tests/frames_011-348_n312.npy`. All read-only reference. §1.2, §3.

⚠️ **`quality.py` carries dead weight, and you move it anyway.**

- `quality.py:83` — `_MBASE = Path("D:/Projects/Camea/analysis/output/mosaic")`, a hard-coded absolute
  path to a directory that **no longer exists** (it is under `archive/` now).
- `quality.py:120-136` — `score_build()` / `leaderboard()` import **pandas**, which is **not in the uv
  env**.

Both are **inert**. `_MBASE` is a `Path(...)` construction at import (never touched), `MROOT` reads
`CAMEA_MOSAIC_ROOT` with it as a default, and the pandas imports are *inside* the functions. Nothing
in `t27` / `t33` / `render` or in the app calls `_bp_and_trials`, `score_build`, `leaderboard` or
`quality_plot`. The module imports clean and the only thing the engine uses from it is
`quality.band_pass` (`:17`) — via `t27.band_pass` — and `quality.overlap_ncc` (`:23`) via
`NccBank.validate`.

**Do not trim it during the move.** Rule #5. If we want the convenience layer gone, that is a separate
commit, gated on a green guard, and it is worth about ten minutes of nobody's time.

---

## 8. Risks the move does not cause but will be blamed for

Two of these are the same shape: *the uv env is not the conda env, and the science was measured in the
conda env.*

1. **🔴 opencv version.** The uv env has **`opencv-python 5.0.0.93`**. The conda `camea` env that
   produced 312/312 has OpenCV 4.x. **`cv2.GaussianBlur` is the DoG (3, 30) that every single number in
   this project is measured on** — `quality.band_pass` → `t27.band_pass` → `t33.place`. The
   `pyproject.toml` comment already warns that swapping cv2 for scipy shifts a metric by 0.32 % against
   a 0.13 % margin. A major-version bump is a smaller risk than that, but it is not zero. **Run the
   guard under uv before you declare the move done.** If it is red, suspect this first, and pin
   `opencv-python>=4.10,<5` to bisect.
2. **numpy 2.5.1 / scipy 1.18 / Python 3.13** in `.venv` (`pyproject` says `>=3.12`). Same argument,
   same answer: the guard is the arbiter.
3. **`t27` has two self-checks that will catch a numeric drift for you, loudly, inside `place()`:**
   `swim_all(validate=True)` cross-checks the batched SWIM against **spectralign's own `Swim`** and
   raises `RuntimeError: batched SWIM disagrees with spectralign by … px` (t27.py:287); and
   `NccBank.validate` re-derives the NCC via `quality.overlap_ncc`. Both run in the guard. If they fire,
   your environment changed the maths — the move did not.
4. **Order of operations.** Move the four files **first**, wire the guard **second**, get it green
   **third**, and only then let anyone touch `features/mosaic/`. A guard that has never run green in
   the new tree proves nothing about the new tree.

---

## 9. Checklist for the implementing agent

- [ ] `git mv`-equivalent (copy; `archive/` is read-only) the four science files. **Diff them against
      the originals and confirm the diff is empty.** `fc /b` or `git diff --no-index`.
- [ ] Write `engine/__init__.py`, `engine/dll.py`, `engine/adapters.py`, `engine/excluded.py`.
- [ ] `uv pip install -e .` → `uv run python -c "from camea.engine import t27; print(t27.on_gpu())"`
      → must print **`True`** with no pre-dance and no conda.
- [ ] Port `score.py` → `tests/guard/score.py`. **Byte-copy `robust_align` and `score()`.**
- [ ] Write `tests/slow/conftest.py`. Verify it **fails** (not skips) with `CAMEA_GT_DIR` unset and
      pointing nowhere.
- [ ] `uv run pytest -m slow tests/slow/test_reader_matches_vscope.py` → **312/312 frames equal**.
- [ ] `uv run pytest -m slow tests/slow/test_mosaic_312.py -s` → **312/312, `pass1_max_dev == 0.0`**.
- [ ] Confirm `git status` shows **no** `*.json` under `ground_truth/`, no `*.npy`, nothing from
      `archive/`. The answer key must not be committed. Ever.
