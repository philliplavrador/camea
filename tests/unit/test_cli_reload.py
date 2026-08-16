"""`camea --reload` — the dev switch that keeps a running server from serving old code.

The failure it exists for is quiet by construction: uvicorn watches nothing, so after an edit the
process answers happily out of the Python it imported at startup, and the only symptom is that the
change appears not to have happened. See `camea.__main__.serve_reloading` for the measured reason
this is hand-rolled rather than `uvicorn --reload`, and `scripts/check-app-fresh.js` for the gate
that catches a stale server when nobody used the switch.

What is worth testing here is the part with no server in it: the flag's parsing, its one refusal,
the mtime sweep the supervisor loops on, and the factory's handover of the headless switch — which
is a safety setting that would otherwise be silently dropped in every reloaded child.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from camea import __main__ as cli


def test_reload_is_off_by_default() -> None:
    assert cli.parse_args(["--headless"]).reload is False


def test_reload_parses() -> None:
    args = cli.parse_args(["--headless", "--reload", "--port", "8000"])
    assert args.reload is True
    assert args.headless is True


@pytest.mark.parametrize("argv", [["--reload"], ["--reload", "--window"]])
def test_reload_refuses_the_native_window(argv: list[str], capsys: pytest.CaptureFixture) -> None:
    """`--window` (the default mode) and the reloader both demand the main thread — pywebview for
    its message loop, the supervisor to own the child process. Refused, with a reason, rather than
    started in a configuration where one of them silently loses."""
    assert cli.main(argv) == 2
    assert "--reload needs --headless or --browser" in capsys.readouterr().err


def test_newest_source_mtime_ignores_everything_that_is_not_python(tmp_path: Path) -> None:
    """The sweep is what decides a restart, so a file the server cannot import must not trigger
    one — otherwise every log write and every `.pyc` would bounce the app."""
    old = tmp_path / "a.py"
    old.write_text("x = 1\n")
    import os

    os.utime(old, (1_000_000_000, 1_000_000_000))
    (tmp_path / "notes.txt").write_text("newer, and irrelevant\n")

    assert cli.newest_source_mtime(tmp_path) == pytest.approx(1_000_000_000, abs=1)


def test_newest_source_mtime_finds_the_newest_nested_file(tmp_path: Path) -> None:
    (tmp_path / "old.py").write_text("x = 1\n")
    nested = tmp_path / "deep" / "deeper"
    nested.mkdir(parents=True)
    time.sleep(0.01)
    new = nested / "new.py"
    new.write_text("y = 2\n")

    assert cli.newest_source_mtime(tmp_path) == pytest.approx(new.stat().st_mtime, abs=0.001)


def test_newest_source_mtime_of_nothing_is_zero(tmp_path: Path) -> None:
    assert cli.newest_source_mtime(tmp_path) == 0.0


def test_the_reload_factory_carries_the_headless_switch_into_the_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """⭐ The reason `--reload` needs a factory at all.

    The reloaded child re-imports the app from scratch and never sees our argv, so anything
    `main()` does *before* `create_app()` has to happen again in the factory. Today that is
    `set_headless()`, which is what stops a mode with no window opening a folder in the OS file
    manager. Pointed at the module-level `APP` instead, the flag would hold until the first edit
    and then quietly stop.
    """
    from camea.api import routes_core

    was = routes_core.HEADLESS
    try:
        monkeypatch.setenv("CAMEA_HEADLESS", "1")
        cli._reload_target()
        assert routes_core.HEADLESS is True

        monkeypatch.setenv("CAMEA_HEADLESS", "0")
        cli._reload_target()
        assert routes_core.HEADLESS is False
    finally:
        routes_core.set_headless(was)
