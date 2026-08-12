"""__main__.py — the `camea` command. **THREE MODES, AND THEY ARE NOT COSMETIC.**

    camea --window     ship. The pywebview / WebView2 native window.   (the default)
    camea --browser    dev.  Serve, print the URL, open the default browser. No pywebview.
    camea --headless   test. Serve the API only. No UI at all.

Every one of them runs **the same server** — `camea.api.app.create_app()`, bound to **127.0.0.1**
(never `0.0.0.0`: this process holds a filesystem browser and a document writer).

🔴 **THE ONE THING THAT DIFFERS, AND THE HOLE IT USED TO LEAVE.** Only `--window` has a pywebview
`Window`, so only `--window` can open a **native file dialog**. In the other two `/api/dialog/*`
honestly returns `501 no_window` — and v1 stopped there, which meant that in the two modes a
developer and a test actually run, **there was no way to choose a folder, and therefore nothing you
could do at all.** The way out is `GET /api/fs/list`: a served folder picker that lists a directory's
subfolders and marks which are datasets. It is mounted in **every** mode. There is no dead 501 path.

⚠️ **`--window` MUST OWN THE MAIN THREAD.** `webview.start()` is a native message loop. So the server
goes on a **daemon thread** and the window is the foreground; when the window closes, the process
ends and the daemon goes with it. `--browser` and `--headless` invert that: the server runs in the
foreground and `Ctrl-C` stops it.

⛔ **NO `--data-dir`.** v1 had one, and it opened a dataset on launch. This app does not know where
his data is, does not remember which dataset is "the" dataset, and does not open one behind his back.
He points at a folder; the app looks. (`--open` exists as a *developer* convenience below — it does
exactly what clicking the folder in the browser would do, and it is not a default.)
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
import webbrowser
from typing import Any

import camea

__all__ = ["main", "parse_args", "serve"]

#: ⛔ **127.0.0.1, AND IT IS NOT CONFIGURABLE.** This process browses the filesystem and writes
#: documents. It is a desktop app talking to itself; it is not a server, and it must not become one
#: by way of a flag somebody adds "just for testing on the laptop".
HOST = "127.0.0.1"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="camea",
        description="Camea — a microscopy analysis desktop app. Build mosaics, and more.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "modes:\n"
            "  --window     the native window (the default). Native file dialogs work here.\n"
            "  --browser    serve + open your browser. No native dialogs; use the served folder\n"
            "               picker (GET /api/fs/list), which the UI falls back to automatically.\n"
            "  --headless   serve the API only. What pytest and CI drive.\n"
        ),
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--window", action="store_true",
                      help="the pywebview / WebView2 native window (the default)")
    mode.add_argument("--browser", action="store_true",
                      help="serve, print the URL, and open the default browser. No pywebview.")
    mode.add_argument("--headless", action="store_true",
                      help="serve the API only, with no UI. Used by pytest and by CI.")

    p.add_argument("--port", type=int, default=0,
                   help="bind port. 0 (the default) = an ephemeral free port.")
    p.add_argument("--open", metavar="DIR", default=None,
                   help="a developer convenience: remember DIR as a dataset root at startup, exactly "
                        "as POST /api/datasets/scan would. It does NOT open a dataset — the app "
                        "carries no dataset knowledge and does not choose one for you.")
    p.add_argument("--debug", action="store_true", help="uvicorn access logs; devtools in --window")
    p.add_argument("--version", action="version", version=f"camea {camea.__version__}")
    return p.parse_args(argv)


def free_port() -> int:
    """An ephemeral port, bound and released. There is a theoretical race with another process
    grabbing it in between; on a desktop, with one app, it has never mattered."""
    with socket.socket() as s:
        s.bind((HOST, 0))
        return int(s.getsockname()[1])


def serve(app: Any, port: int, *, debug: bool = False) -> tuple[Any, threading.Thread]:
    """Start uvicorn on a **daemon thread**. -> `(server, thread)`. Does not wait for it to be up —
    `wait_until_up()` does that."""
    import uvicorn

    config = uvicorn.Config(app, host=HOST, port=port, log_level="info" if debug else "warning",
                            access_log=bool(debug))
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="camea-uvicorn", daemon=True)
    thread.start()
    return server, thread


def wait_until_up(server: Any, timeout: float = 30.0) -> None:
    """Block until uvicorn says it is listening. Raises on timeout — **never** hand a URL to a window
    or a browser before the socket is open: the page loads, fires its first request, and gets a
    connection refused it has no way to distinguish from a broken app."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if getattr(server, "started", False):
            return
        time.sleep(0.02)
    raise TimeoutError(f"the server did not start within {timeout:g} s")


def _remember_root(path: str) -> None:
    """`--open DIR` — put a path in `recent_datasets`, and nothing more.

    ⛔ It remembers a **path**. It does not open a dataset, does not pick one, and does not apply an
    exclusion. A remembered path is not knowledge about the data at that path.

    ⚠️ Since 2026-07-25 there is no root registry for this to add to (`settings.dataset_roots` is
    gone). It now seeds `recent_datasets`, which is what the *"Pull data from"* box offers back as a
    completion — so `--open` still means *"start me near here"*, and Playwright still gets a known
    path in the box without the app scanning anything on launch.
    """
    from camea.settings import SETTINGS

    SETTINGS.ensure_loaded().touch_dataset(path)
    print(f"[camea] remembered data folder: {path}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    from camea.api import routes_core
    from camea.api.app import create_app

    # ⚠️ Before `create_app()`: `POST /api/fs/reveal` opens a folder in the OS file manager, which
    # `--window` and `--browser` both should do (the server is on the user's own machine) and
    # `--headless` must never do. Unlike `/api/dialog/*` this needs no pywebview, so it cannot be
    # gated on `WINDOW` — the mode has to be told to it.
    routes_core.set_headless(args.headless)

    app = create_app()

    if args.open:
        _remember_root(args.open)

    port = args.port or free_port()
    url = f"http://{HOST}:{port}"

    server, _thread = serve(app, port, debug=args.debug)
    try:
        wait_until_up(server)
    except TimeoutError as e:
        print(f"[camea] {e}", file=sys.stderr)
        return 1

    print(f"[camea] {camea.__version__} — serving on {url}")
    print(f"[camea] API docs: {url}/docs      schema: {url}/openapi.json")

    if args.headless:
        # ⭐ What pytest and CI drive. Nothing opens; the server is the whole app.
        print("[camea] headless: the API only. No window, so /api/dialog/* returns 501 no_window —")
        print(f"[camea] use the served folder picker instead: {url}/api/fs/list?path=D:/")
        return _block(server)

    if args.browser:
        print("[camea] browser: no pywebview, so /api/dialog/* returns 501 no_window —")
        print("[camea] the UI falls back to the served folder picker (GET /api/fs/list).")
        try:
            webbrowser.open(url)
        except Exception as e:  # noqa: BLE001 — a headless box has no browser; that is not fatal
            print(f"[camea] could not open a browser ({e}). Go to {url} yourself.")
        return _block(server)

    # --- --window: the shipped mode. The window OWNS THE MAIN THREAD. -----------------------------
    from camea.shell import WindowUnavailable, run_window

    try:
        run_window(url, debug=args.debug)
    except WindowUnavailable as e:
        print(f"[camea] {e}", file=sys.stderr)
        return 1
    return 0


def _block(server: Any) -> int:
    """Hold the foreground until Ctrl-C. (The server itself is on the daemon thread.)"""
    try:
        while getattr(server, "started", False) or not getattr(server, "should_exit", False):
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("\n[camea] stopping.")
        server.should_exit = True
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
