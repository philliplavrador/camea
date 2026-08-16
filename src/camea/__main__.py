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

⭐ **`--reload` — the dev loop's fourth word, and the reason it exists.** uvicorn does not watch its
own files, so without it a change to `src/camea/` is not live until somebody restarts the process —
and *nothing says so*. The app keeps answering, in the old code, and the only symptom is that what
you changed did not happen. (2026-08-15: a whole feature was built, verified and committed against a
backend that had been stopped; the author's first words on seeing it were *"i dont see the
updates"*.) `--reload` puts uvicorn's watcher on `src/camea/` and restarts the server itself.
`scripts/check-app-fresh.js` is the belt to this braces — it blocks a turn that leaves a stale or
dead backend behind. **`--reload` needs `--headless` or `--browser`**: see `serve_reloading`.

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
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path
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
    p.add_argument("--reload", action="store_true",
                   help="dev: watch src/camea and restart the server when it changes. Requires "
                        "--headless or --browser (see the docstring for why not --window).")
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


def _reload_target() -> Any:
    """The uvicorn **factory** the reloader calls — in its CHILD process, on every restart.

    ⚠️ This is why `--reload` needs a factory rather than `camea.api.app:APP`. The child
    re-imports the app from scratch, so everything `main()` does *before* `create_app()` has to
    happen again here or it silently does not apply. Today that is exactly one thing, and it is
    a safety switch: `set_headless()` is what stops `POST /api/fs/reveal` opening a folder in a
    mode with no window. Pointing the reloader at the module-level `APP` would leave it unset in
    every reloaded child, so the flag would hold until the first edit and then quietly stop.
    """
    from camea.api import routes_core
    from camea.api.app import create_app

    routes_core.set_headless(os.environ.get("CAMEA_HEADLESS") == "1")
    return create_app()


#: `--reload` polling interval. uvicorn's own StatReload uses 0.25 s; `src/camea` is ~60 files, so
#: a stat sweep is far too cheap to matter and this is set for *responsiveness*, not for cost.
RELOAD_POLL_S = 0.4


def newest_source_mtime(root: Path) -> float:
    """Newest mtime of any `.py` under `root`, in epoch seconds. 0.0 if there are none."""
    newest = 0.0
    for p in root.rglob("*.py"):
        try:
            newest = max(newest, p.stat().st_mtime)
        except OSError:
            continue  # raced with a save; the next sweep sees it
    return newest


def serve_reloading(port: int, *, headless: bool, debug: bool = False) -> int:
    """`--reload`: watch `src/camea` and restart the server on a change. Blocks until Ctrl-C.

    The ordinary path puts uvicorn on a daemon thread (see `serve`); a reloader cannot live there,
    because reloading means replacing a *process*. That is why `--reload` refuses `--window`:
    pywebview also demands the main thread, and only one of them can have it.

    🔴 **WHY THIS IS HAND-ROLLED AND NOT `uvicorn --reload`.** Measured 2026-08-15 on Windows,
    uvicorn 0.51.0. Its reloader detects the change and logs *"WatchFiles detected changes in … .
    Reloading…"* — and then never replaces the worker. The old process serves the old code forever,
    having announced in the log that it would not. Read
    `uvicorn/supervisors/basereload.py :: BaseReload.restart`:

        if sys.platform == "win32":
            os.kill(self.process.pid, signal.CTRL_C_EVENT)
        else:
            self.process.terminate()
        self.process.join()

    On Windows it asks the worker to stop by raising a **Ctrl-C console event** — which is
    delivered through a console the process must be attached to — and then blocks on `join()`
    waiting for a death that, with no console, never comes. A server launched from a terminal
    survives this; one launched with its output redirected (a background task, a CI step, an agent
    session — every way this repo actually starts it) hangs on the first change and stays hung.

    So: our own supervisor. `Popen` + `terminate()` is `TerminateProcess`, which needs no console
    and cannot be ignored, and an mtime sweep needs no optional dependency. ~30 lines, and it
    restarts in every mode this app is started in.

    ⚠️ **A dead worker is not fatal here.** A syntax error kills the child on startup; this keeps
    watching so that *fixing* the file brings it back, which is the whole point of a reload loop.

    Watching `src/camea` and nothing else is deliberate. `web/` is Vite's job and it hot-reloads
    already; `tests/` and `docs/` cannot change what the server serves.
    """
    import subprocess

    watch = Path(camea.__file__).resolve().parent
    # Read back by `_reload_target()` in the child, which does not get our argv.
    env = {**os.environ, "CAMEA_HEADLESS": "1" if headless else "0"}
    argv = [
        sys.executable, "-m", "uvicorn",
        "camea.__main__:_reload_target", "--factory",
        "--host", HOST, "--port", str(port),
        "--log-level", "info" if debug else "warning",
    ]
    if debug:
        argv.append("--access-log")

    def start() -> tuple[Any, float]:
        # The stamp is taken BEFORE the spawn, so a save that lands while the server is still
        # starting up is still newer than it and gets picked up on the next sweep.
        stamp = newest_source_mtime(watch)
        return subprocess.Popen(argv, env=env), stamp

    def stop(child: Any) -> None:
        child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()

    print(f"[camea] --reload: watching {watch} — the server restarts itself when it changes.")
    child, stamp = start()
    try:
        while True:
            time.sleep(RELOAD_POLL_S)
            if child.poll() is not None:
                print(f"[camea] the server exited ({child.returncode}). Still watching — save a "
                      f"file under {watch} and it will start again.")
                while child.poll() is not None and newest_source_mtime(watch) <= stamp:
                    time.sleep(RELOAD_POLL_S)
            elif newest_source_mtime(watch) <= stamp:
                continue
            else:
                print("[camea] --reload: a source file changed. Restarting the server.")
                stop(child)
            child, stamp = start()
    except KeyboardInterrupt:
        print("\n[camea] stopping.")
        if child.poll() is None:
            stop(child)
        return 0


def open_when_up(url: str, port: int, timeout: float = 30.0) -> None:
    """Open a browser once `port` answers — from a daemon thread, because the caller is about to
    block in uvicorn's reloader and there is no `server.started` to poll in that mode."""

    def wait_then_open() -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with socket.socket() as s:
                s.settimeout(0.25)
                if s.connect_ex((HOST, port)) == 0:
                    break
            time.sleep(0.1)
        try:
            webbrowser.open(url)
        except Exception as e:  # noqa: BLE001 — a headless box has no browser; not fatal
            print(f"[camea] could not open a browser ({e}). Go to {url} yourself.")

    threading.Thread(target=wait_then_open, name="camea-open-browser", daemon=True).start()


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

    if args.reload and not (args.headless or args.browser):
        print("[camea] --reload needs --headless or --browser: the reloader restarts a child "
              "process and the native window owns the main thread, so they cannot share one.",
              file=sys.stderr)
        return 2

    from camea.api import routes_core
    from camea.api.app import create_app

    if args.open:
        _remember_root(args.open)

    port = args.port or free_port()
    url = f"http://{HOST}:{port}"

    # ⭐ The reloader builds its own app, in its own child, on every restart — `_reload_target()`
    # is that build. Nothing below this line applies to it, which is why the headless switch is
    # handed over through the environment rather than set here.
    if args.reload:
        print(f"[camea] {camea.__version__} — serving on {url}")
        print(f"[camea] API docs: {url}/docs      schema: {url}/openapi.json")
        if args.browser:
            open_when_up(url, port)
        return serve_reloading(port, headless=args.headless, debug=args.debug)

    # ⚠️ Before `create_app()`: `POST /api/fs/reveal` opens a folder in the OS file manager, which
    # `--window` and `--browser` both should do (the server is on the user's own machine) and
    # `--headless` must never do. Unlike `/api/dialog/*` this needs no pywebview, so it cannot be
    # gated on `WINDOW` — the mode has to be told to it.
    routes_core.set_headless(args.headless)

    app = create_app()

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
