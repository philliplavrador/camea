"""A synthetic survey VIDEO with a known truth — the videomosaic suite's answer key.

Same philosophy as the snapshot fixture (`tests/api/conftest.py::_write_dataset`): frames are
crops cut from ONE generated world image at known top-left offsets, so the pipeline's output
can be judged against where the crops actually came from. Encoded MJPG into an .avi —
intra-only (no codec state to corrupt), shipped in every OpenCV build, and decoded content is
stable enough to register sub-pixel even though the BYTES are not identical across encoders
(assert on decoded geometry, never on file bytes).

The world texture is multi-scale blobs — structure at several octaves, which is what
`cv2.phaseCorrelate` needs (pure blurred noise measurably does not lock; this composition was
validated against the sign-convention experiments the pipeline is built on).
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def survey_world(h: int = 1400, w: int = 2400, seed: int = 7) -> np.ndarray:
    """Synthetic tissue: sparse bright blobs at three scales over a dark field, 0–~180 gray."""
    rng = np.random.default_rng(seed)
    world = np.zeros((h, w), np.float32)
    for sigma, n, amp in ((40, 120, 1.0), (12, 900, 1.5), (4, 3600, 2.0)):
        im = np.zeros_like(world)
        ys = rng.integers(0, h, n)
        xs = rng.integers(0, w, n)
        im[ys, xs] = rng.random(n).astype(np.float32) * amp
        world += cv2.GaussianBlur(im, (0, 0), sigma) * sigma
    world -= world.min()
    world = world / max(float(world.max()), 1e-6) * 170.0 + 8.0
    return world.astype(np.float32)


def serpentine_path(world_hw: tuple[int, int], frame_hw: tuple[int, int], *,
                    rows: int = 3, step: int = 16, dwell: int = 12,
                    margin: int = 8) -> list[tuple[int, int]]:
    """Top-left (x, y) per frame: serpentine rows, a settle-dwell at each row end."""
    H, W = world_hw
    fh, fw = frame_hw
    x0, x1 = margin, W - fw - margin
    row_pitch = 0 if rows <= 1 else min(int(fh * 0.55), (H - fh - 2 * margin) // (rows - 1))
    pts: list[tuple[int, int]] = []
    y = margin
    for r in range(rows):
        xs = list(range(x0, x1 + 1, step)) if r % 2 == 0 else list(range(x1, x0 - 1, -step))
        pts.extend((x, y) for x in xs)
        pts.extend([(xs[-1], y)] * dwell)
        if r < rows - 1:
            pts.extend((xs[-1], yy) for yy in range(y + step, y + row_pitch + 1, step))
            y += row_pitch
            pts.extend([(xs[-1], y)] * dwell)
    return pts


def write_survey_video(path: str | Path, *, frame_hw: tuple[int, int] = (320, 480),
                       rows: int = 3, step: int = 16, dwell: int = 12,
                       black_gap: tuple[float, int] | None = None,
                       gain_drift: bool = True, seed: int = 7, fps: float = 30.0) -> dict:
    """Write the video; return `{"truth": {frame_idx: (x, y)}, "n_frames", "frame_hw"}`.

    `black_gap=(frac, n)` splices n lights-off frames at `frac` of the way through, padded
    with stationary frames on both sides — the stage holds still through the outage, so a
    bridge across it is *possible* (the mechanism under test), never luck.
    Black frames carry no `truth` entry: they are not data.
    """
    p = Path(path)
    world = survey_world(seed=seed)
    fh, fw = frame_hw
    pts = serpentine_path(world.shape, frame_hw, rows=rows, step=step, dwell=dwell)

    events: list[tuple[str, tuple[int, int] | None]] = [("f", pt) for pt in pts]
    if black_gap is not None:
        frac, nb = black_gap
        i = max(1, min(len(events) - 1, int(len(events) * frac)))
        pos = events[i][1]
        pad: list[tuple[str, tuple[int, int] | None]] = [("f", pos)] * 6
        events = events[:i] + pad + [("b", None)] * nb + pad + events[i:]

    vw = cv2.VideoWriter(p.as_posix(), cv2.VideoWriter_fourcc(*"MJPG"), fps, (fw, fh), True)
    if not vw.isOpened():
        raise RuntimeError("cv2.VideoWriter could not open an MJPG .avi — no codec?")
    truth: dict[int, tuple[float, float]] = {}
    try:
        for idx, (kind, pt) in enumerate(events):
            if kind == "b":
                img = np.zeros((fh, fw), np.float32)
            else:
                x, y = pt  # type: ignore[misc]
                img = world[y:y + fh, x:x + fw].copy()
                if gain_drift:
                    img *= 1.0 + 0.25 * float(np.sin(3.0 * idx / max(60, len(events))))
                truth[idx] = (float(x), float(y))
            g = np.clip(img, 0, 255).astype(np.uint8)
            vw.write(cv2.merge([(g * 0.06).astype(np.uint8), g, (g * 0.03).astype(np.uint8)]))
    finally:
        vw.release()
    return {"truth": truth, "n_frames": len(events), "frame_hw": frame_hw}
