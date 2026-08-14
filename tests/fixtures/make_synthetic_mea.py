"""Regenerate the committed synthetic MEA session (tests/fixtures/mea/).

    uv run python tests/fixtures/make_synthetic_mea.py

Same philosophy as `make_synthetic.py` and `make_synthetic_video.py`: a tiny, fake, committed asset
so the e2e suite can drive the REAL import flow on a clean clone with no 35 GB mirror and no MaxWell
file. The shape on disk is a MaxLab session — `<plate>/<assay>/<run>/data.raw.h5` — because the
import screen browses a folder and lists every recording underneath it, which is only a meaningful
gesture when there is more than one.

The content, and why it is the size it is, is in `measynth.py`. The short version: the raw stream is
declared but unallocated, so the header facts are real and the bytes are not there.

Facts a spec may assert are in `web/tests/e2e/fixture.ts` (`MEA_FIXTURE`).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    spec = importlib.util.spec_from_file_location("measynth", HERE / "measynth.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    out = HERE / "mea"
    written = mod.write_session(out)
    for p in written:
        print(f"wrote {p.relative_to(HERE)} — {p.stat().st_size / 1024:.1f} kB")


if __name__ == "__main__":
    main()
