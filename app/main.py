"""Camea Mosaic Builder — the entry point.

OWNER: agent 3 (with app/backend/server.py). Nobody else edits this file.
CONTRACT: app/API.md §13 (native dialogs), §14 (GPU warm-up).

    python -s app/main.py [--data-dir DIR] [--no-window] [--port N]

WHAT IT DOES
------------
1. Start uvicorn on a **daemon thread**, bound to **127.0.0.1** and a **free port** (never 0.0.0.0).
2. Create a pywebview window on that URL (WebView2 — preinstalled on Windows 11, so there is no
   browser chrome, no visible port and one runtime).
3. Hand the Window to `server.WINDOW` so `/api/dialog/*` can open native file pickers — the WebView
   cannot open one itself.
4. Inject `window.CAMEA_API = "http://127.0.0.1:<port>"` into the page before it loads. (server.py
   splices it into `<head>` on the way out, which is race-free in a way that a post-load
   `evaluate_js` is not.)
5. Kick `engine.warm_gpu()` on a worker thread (server.create_app does it): it is worth **-497 ms
   off the first match**, and it surfaces a broken CUDA install at launch instead of 40 minutes into
   a sweep.

`--no-window` runs headless (pytest, CI). `/api/dialog/*` then returns 501 and the tests pass paths
directly.

STARTUP BUDGET — and why the shell choice does not matter
---------------------------------------------------------
pywebview paints in ~500-900 ms where C#/WPF paints in ~50-150 ms. That ~550 ms is real, but it is
paid ONCE and it is invisible: in *every* option the engine stays Python, and
numpy + scipy + spectralign + CuPy take a measured **1,502 ms to import** before the app can touch a
frame. Time-to-first-useful-action is **~1.5-2 s in all of them**. Against an hour in the sweep,
550 ms of launch is **0.15 %**. (pywebview is also the smallest: a **248 MB** installer vs Electron's
~400 MB.) Do not relitigate this.

⚠️ PACKAGING (agent 8, and it is the part that bites): PyInstaller **BREAKS
`t27._cuda_dll_dance()`** — it globs `sysconfig.get_paths()["purelib"]/nvidia/*/bin`, which does not
exist under `sys._MEIPASS`. It must be rewritten for the frozen layout. And an unsigned PyInstaller
EXE reliably trips SmartScreen.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

#: The repo root — the directory containing `analysis/`. Under PyInstaller this becomes
#: `Path(sys._MEIPASS)`. One constant, so agent 8 has exactly one thing to redirect.
REPO_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """--data-dir (open it immediately) | --no-window (headless) | --port (default: free)"""
    p = argparse.ArgumentParser(prog="camea", description="Camea Mosaic Builder")
    p.add_argument("--data-dir", default=None,
                   help="a vscope acquisition directory; opened immediately on launch")
    p.add_argument("--no-window", action="store_true",
                   help="headless: serve the API only (pytest / CI). /api/dialog/* returns 501.")
    p.add_argument("--port", type=int, default=0,
                   help="bind port (default 0 = an ephemeral free port)")
    p.add_argument("--host", default="127.0.0.1",
                   help="bind host. 127.0.0.1 ONLY — never 0.0.0.0.")
    return p.parse_args(argv)


def _post(url: str, body: dict, timeout: float = 10.0) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _open_data_dir_async(base_url: str, data_dir: str) -> None:
    """Fire POST /api/session/open at ourselves so `--data-dir` takes exactly the same code path the
    UI does. On a thread: the open job is 2-6 s and must not delay the window."""
    def go():
        try:
            job = _post(f"{base_url}/api/session/open", {"data_dir": data_dir, "project_path": None})
            print(f"[camea] opening {data_dir} -> {job.get('job_id')}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[camea] --data-dir open failed: {e}", file=sys.stderr, flush=True)
    threading.Thread(target=go, name="autoload", daemon=True).start()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.host != "127.0.0.1":
        print("[camea] refusing to bind anything but 127.0.0.1", file=sys.stderr)
        return 2

    from app.backend import server

    server.create_app(REPO_ROOT, window=None)

    # The page must know what we were launched with BEFORE it is served — index.html is spliced on
    # the way out, and the open job below lands ~9 s after the page has already loaded.
    if args.data_dir:
        server.LAUNCH_DATA_DIR = str(Path(args.data_dir))

    base_url, uv = server.serve(host=args.host, port=args.port)
    print(f"[camea] API on {base_url}", flush=True)

    if args.data_dir:
        _open_data_dir_async(base_url, str(Path(args.data_dir)))

    if args.no_window:
        print("[camea] headless (--no-window). Ctrl-C to stop.", flush=True)
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        return 0

    import webview

    window = webview.create_window(
        "Camea Mosaic Builder",
        base_url,
        width=1600, height=1000,
        min_size=(1100, 700),
        background_color="#101214",
        text_select=False,
        confirm_close=True,
    )
    # /api/dialog/* proxies pywebview's native pickers — the WebView cannot open one itself.
    server.WINDOW = window

    webview.start(gui="edgechromium", private_mode=False)
    return 0


if __name__ == "__main__":
    # spawn (the build child) re-imports this module as __mp_main__; freeze_support keeps that sane
    # under PyInstaller too.
    import multiprocessing
    multiprocessing.freeze_support()
    raise SystemExit(main())
