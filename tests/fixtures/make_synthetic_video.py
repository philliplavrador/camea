"""Regenerate the committed synthetic survey VIDEO (tests/fixtures/survey.avi).

    uv run python tests/fixtures/make_synthetic_video.py

Same philosophy as `make_synthetic.py`: a tiny, fake, committed asset so the e2e suite can
drive the REAL video→mosaic flow on a clean clone with no data mirror. Frames are crops cut
from one generated world at known offsets (`videosynth.write_survey_video`); MJPG in an .avi
because it is intra-only and present in every OpenCV build. ⚠️ The ENCODED BYTES are not
identical across OpenCV builds — regenerating may produce a different file that decodes to
the same geometry; commit a regeneration only when the content actually changed.

The pipeline must succeed on this file with SHIPPED DEFAULT config (the UI sends no
overrides) — that is what makes it an honest e2e fixture. Geometry facts a spec may assert
are in web/tests/e2e/fixture.ts (`VIDEO_FIXTURE`).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    spec = importlib.util.spec_from_file_location("videosynth", HERE / "videosynth.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    out = HERE / "survey.avi"
    v = mod.write_survey_video(out, rows=2, step=16, dwell=12, seed=7)
    mb = out.stat().st_size / 1e6
    xs = [p[0] for p in v["truth"].values()]
    ys = [p[1] for p in v["truth"].values()]
    print(f"wrote {out} — {v['n_frames']} frames, {mb:.2f} MB, "
          f"survey extent {max(xs) - min(xs)}×{max(ys) - min(ys)} px")


if __name__ == "__main__":
    main()
