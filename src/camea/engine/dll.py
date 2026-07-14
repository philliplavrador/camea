"""The DLL pre-dance. FROZEN BUILDS ONLY.

Under `uv run` this is a **NO-OP, and it must stay one**: `t27._cuda_dll_dance()` (t27.py:120)
already globs the uv venv's `site-packages/nvidia/*/bin`, and `t27.on_gpu()` comes back True with
no help at all. Verified 2026-07-14 under a clean uv venv (see the `[gpu]` extra in pyproject.toml:
CuPy 14.1.1, CUDA runtime 12090).

Under **PyInstaller**, `sys.prefix` IS `sys._MEIPASS`, so `sysconfig.get_paths()["purelib"]`
resolves to `<_MEIPASS>/Lib/site-packages` — **which does not exist**. t27's own dance then globs
nothing, `cupy.zeros(1)+1` raises `CuPy failed to load nvrtc64_120_0.dll`, and the shipped app
reports **"No usable CUDA GPU" on a machine with a perfectly good card**: every build 8-10 min
instead of 3, forever, with nothing in the UI hinting the cause is a search path. That, and only
that, is what this module is for.

There is a second, nastier frozen failure and it is not about CUDA at all. `numpy.linalg`
**delay-loads** its BLAS. When that delay-load fails, Windows **fast-fails the process with
0xC0000409 / exit 3228369023** — a native crash, no Python exception, nothing to catch. It killed
the old app's build child ~20 s in on every COLD build, because `t27.solve_rigid`
(t27.py:693 -> spectralign.placement.rigid -> np.linalg.solve) is on the cold path and only the
cold path; a WARM build survived because the cache skips pass 1 and never calls BLAS. The job
reported only "the build process exited with code 3228369023".

  · The old code's **conda** roots (`<sys.prefix>/Library/bin`, `Library/mingw-w64/bin`,
    `Library/usr/bin`, `DLLs`) are DEAD and are deliberately not ported: a uv venv has none of
    them, and numpy's PyPI wheel ships its BLAS in `numpy.libs/` and registers that directory
    itself from `numpy/__init__.py`. **Proven by the 312/312 guard**, which runs t33 fully cold
    under `uv run` and therefore calls `np.linalg.solve` twice: it is green.
  · The **frozen** roots survive, below. ⚠️ They are NOT proven by anything yet. A real freeze +
    a real COLD build is a REQUIRED smoke test for whoever does the packaging, not a note.

⚠️ `predance()` runs at MODULE SCOPE of `camea/engine/__init__.py` — before the first `t27.xp()`
and before the first `numpy.linalg` call, and in the SPAWNED BUILD CHILD too (spawn re-imports the
module). That is the one place that guarantees both. Do not move it into a function the app has to
remember to call.

Idempotent: when it has already added a directory, t27's own dance re-adds the same one (harmless).
"""
from __future__ import annotations

import glob
import os
import sys
import sysconfig
from pathlib import Path


def _cuda_dll_dirs(meipass: str) -> list[str]:
    """`<_MEIPASS>/nvidia/*/bin` — where PyInstaller lands the pip `nvidia-*-cu12` wheels."""
    bases = [Path(meipass)]
    try:
        bases.append(Path(sysconfig.get_paths()["purelib"]))
    except Exception:  # noqa: BLE001
        pass
    dirs: list[str] = []
    for base in bases:
        for d in sorted(glob.glob(str(base / "nvidia" / "*" / "bin"))):
            if os.path.isdir(d) and d not in dirs:
                dirs.append(d)
    return dirs


def _blas_dll_dirs(meipass: str) -> list[str]:
    """Where numpy's delay-loaded BLAS ends up in a frozen bundle. PyInstaller routinely FLATTENS
    native DLLs to the bundle root; `numpy.libs/` may or may not survive as a directory."""
    m = Path(meipass)
    cand = [m, m / "numpy.libs", m / "numpy" / ".libs", m / "scipy.libs", m / "_internal"]
    return [str(d) for d in cand if d.is_dir()]


def predance() -> list[str]:
    """Put the frozen bundle's native-DLL directories on the search path. Returns what it added.

    Under `uv run` (not frozen) this returns `[]` and does nothing — t27 handles itself.

    Both mechanisms below are needed and they are NOT the same one:
      * `os.add_dll_directory` — for a `.pyd`'s dependent DLLs (py3.8+ ignores PATH for those);
      * `PATH` — NVRTC loads `nvrtc-builtins` at runtime with a plain `LoadLibrary`, which uses PATH.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return []                              # uv / a normal venv: t27's own dance is sufficient.

    dirs: list[str] = []
    seen: set[str] = set()
    path_now = os.environ.get("PATH", "").lower()
    for d in _cuda_dll_dirs(meipass) + _blas_dll_dirs(meipass):
        if d.lower() in seen:
            continue
        seen.add(d.lower())
        try:
            os.add_dll_directory(d)            # Windows only; the cookie is kept by the OS
        except (AttributeError, OSError):
            pass
        if d.lower() not in path_now:
            dirs.append(d)
    if dirs:
        os.environ["PATH"] = os.pathsep.join(dirs) + os.pathsep + os.environ.get("PATH", "")
    return dirs
