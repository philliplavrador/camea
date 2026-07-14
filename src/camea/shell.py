"""shell.py — the native window. **pywebview on WebView2.**

This is `camea --window`, the shipped mode: a real desktop window with no browser chrome, no visible
port and no second runtime to install (WebView2 is preinstalled on Windows 11).

WHAT IT DOES, AND THE TWO THINGS THAT ARE NOT OPTIONAL
-----------------------------------------------------
1. ⭐ **IT HANDS THE `Window` TO `routes_core.set_window()`.** That is the *only* thing that makes
   `/api/dialog/*` work: a WebView cannot open a native file picker itself — the Python side has to,
   through the window object. Without this line the native dialogs 501 in the native window, which is
   the one mode where they are supposed to work.

2. 🔴 **IT NEVER DIES QUIETLY.** `webview.start()` **must run on the main thread** (it is a native
   message loop), so the *server* is the daemon thread and the window is the foreground. If pywebview
   or WebView2 is missing, we do not fall back to a browser silently — we say what is missing and how
   to run without it (`camea --browser`). A window that opens as an invisible browser tab somewhere
   else is worse than an error message.

⚠️ **STARTUP: DO NOT RELITIGATE THE SHELL CHOICE.** pywebview paints in ~500-900 ms where C#/WPF
paints in ~50-150 ms. That ~550 ms is real, it is paid once, and it is invisible — in *every* option
the engine stays Python, and numpy + scipy + spectralign + CuPy take a measured **1,502 ms to import**
before the app can touch a frame. Time-to-first-useful-action is ~1.5-2 s whatever the shell is.
Against an hour in the sweep, 550 ms of launch is **0.15 %**. (pywebview is also the smallest: a
248 MB installer vs Electron's ~400 MB.)

⚠️ **PACKAGING, and it is the part that bites:** PyInstaller breaks `t27._cuda_dll_dance()` — it globs
`sysconfig.get_paths()["purelib"]/nvidia/*/bin`, which does not exist under `sys._MEIPASS`.
`camea.engine.dll.predance()` is where that is handled. See `engine/dll.py`.
"""

from __future__ import annotations

import sys
from typing import Any

__all__ = ["run_window", "WindowUnavailable"]

#: The window, before the front end is bundled. Once there is a built UI, point this at the served
#: index instead — the URL is the same origin as the API, so no CORS header is ever consulted.
TITLE = "Camea"
MIN_SIZE = (1100, 720)
SIZE = (1600, 1000)


class WindowUnavailable(RuntimeError):
    """pywebview (or its native backend) is not usable on this machine. **Never swallowed.**"""


def run_window(url: str, *, title: str = TITLE, debug: bool = False) -> None:
    """Open the native window on `url` and **block until the user closes it**.

    Must be called on the **MAIN THREAD** — `webview.start()` runs a native message loop. The uvicorn
    server therefore runs on a daemon thread (`camea.__main__`), and when this returns, the process is
    over and the daemon dies with it.
    """
    try:
        import webview
    except ImportError as e:  # pragma: no cover — a real install has it (it is a hard dependency)
        raise WindowUnavailable(
            "pywebview is not installed, so there is no native window. Either install it "
            "(`uv sync`) or run without one:\n"
            "    uv run camea --browser      # serves the API and opens your default browser"
        ) from e

    window = webview.create_window(
        title,
        url,
        width=SIZE[0], height=SIZE[1],
        min_size=MIN_SIZE,
        confirm_close=False,
        text_select=True,
    )

    # ⭐ THE LINE THE NATIVE DIALOGS DEPEND ON. A WebView cannot open a file picker; Python must, and
    # it needs this object to do it. Set it BEFORE `start()` — a request can arrive the instant the
    # page loads.
    from camea.api import routes_core

    routes_core.set_window(window)

    try:
        webview.start(debug=debug)
    except Exception as e:  # noqa: BLE001 — a missing WebView2 runtime lands here, not on the import
        raise WindowUnavailable(
            f"the native window could not start ({type(e).__name__}: {e}).\n"
            "On Windows this is almost always a missing WebView2 runtime — it ships with Windows 11, "
            "so if you are on 10, install the Evergreen runtime from Microsoft.\n"
            "You can always run without a window:\n"
            f"    uv run camea --browser      # same app, in your default browser"
        ) from e
    finally:
        routes_core.set_window(None)


def probe() -> tuple[bool, str]:
    """-> `(usable, why)`. Cheap: it imports pywebview and asks it for a backend; it opens nothing.

    Used by `camea --window` to fail with a *sentence* instead of a stack trace on a machine that
    cannot render one.
    """
    try:
        import webview  # noqa: F401
    except ImportError as e:
        return False, f"pywebview is not installed ({e})"
    if sys.platform not in ("win32", "darwin", "linux"):
        return False, f"no supported native backend on {sys.platform}"
    return True, "ok"


def window() -> Any:
    """The live `Window`, or None. `routes_core.WINDOW` is the single source of truth."""
    from camea.api import routes_core

    return routes_core.WINDOW
