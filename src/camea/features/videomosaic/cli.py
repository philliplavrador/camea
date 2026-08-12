"""Developer CLI — run the video→mosaic pipeline on one file, no app, no project.

    uv run python -m camea.features.videomosaic.cli <video> <out_dir> [key=value ...]

The key=value pairs override `VideoConfig` fields (ints/floats/bools parsed by eval-free
coercion). This is the harness the pipeline is tuned and debugged with; the app calls the
same `pipeline.build`.
"""

from __future__ import annotations

import sys
from dataclasses import fields

from .config import VideoConfig
from .pipeline import build


def _coerce(name: str, raw: str):
    kind = {f.name: f.type for f in fields(VideoConfig)}.get(name)
    if kind is None:
        raise SystemExit(f"unknown config key {name!r}")
    if kind == "bool":
        return raw.lower() in ("1", "true", "yes")
    if kind == "int":
        return int(raw)
    return float(raw)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    overrides = {}
    for pair in argv[2:]:
        k, _, v = pair.partition("=")
        overrides[k] = _coerce(k, v)
    cfg = VideoConfig.from_overrides(overrides)

    def report(p) -> None:
        eta = f"  eta {p.eta_s:.0f}s" if p.eta_s else ""
        print(f"\r[{p.phase:>9}] {p.pct:5.1f}%  {p.message}{eta}          ",
              end="", flush=True)

    def log(line: str) -> None:
        print("\n" + line, flush=True)

    # `diagnostics=True`: this is the DEV harness, so the extra files (the estimated background)
    # are wanted here. The app leaves them off — its output folder is one the user named and opens.
    result = build(argv[0], argv[1], cfg, diagnostics=True, report=report, log=log)
    print("\nDONE")
    print(f"  mosaic:  {result['outputs']['mosaic']}")
    print(f"  stats:   {result['outputs']['build']}")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")     # cp1252 console kills the arrows
    except Exception:                                # noqa: BLE001
        pass
    raise SystemExit(main(sys.argv[1:]))
