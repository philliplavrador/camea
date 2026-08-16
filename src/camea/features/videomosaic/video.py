"""Video decode — probe metadata, stream frames, fetch chosen frames. cv2 only, never ffmpeg.exe.

Facts this module is built on (verified on this machine, 2026-08-07):
- cv2.VideoCapture's FFMPEG backend decodes H.264 mp4 fine (the bundled ffmpeg cannot *encode*
  H.264, which matters only to tools that write video — not us).
- `CAP_PROP_FRAME_COUNT` and `CAP_PROP_FPS` are estimates (phone video is often VFR): trust them
  for a receipt, never for arithmetic. Count frames as read.
- Seeking H.264 is unreliable and slow; the pipeline reads **sequentially** and uses
  `grab()` (decode without conversion) to skip cheaply — `read_frames_at` is a single forward
  pass whatever the indices.

The mosaic signal convention: `to_gray` reduces a BGR frame to one signal plane, and it assumes
NOTHING about which channel carries the signal — see its own docstring for why the reduction is a
max and not a mean. What colour the source *is* gets measured separately, at build time, by
`colour.py`; it never reaches registration.

⚠️ Do NOT reach for the raw decoder buffer via `cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)`. On these
H.264 files OpenCV warns "Unknown/unsupported picture format: yuvj420p, will be treated as 8UC1"
and hands back a plane that is NOT luma — it is high-pass-like (raw/G measures 0.0000 over the
smoothest bright regions), while on the MJPG test fixture the same call returns correct luma
(raw/G = 0.614). Building on it would make the tests pass and the real videos silently wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

import cv2
import numpy as np

from ...core.jobs import check_cancelled


class VideoError(Exception):
    """The video cannot be used, with the reason in one sentence (surfaces as the job error /
    a 400 at probe time)."""


@dataclass(frozen=True)
class VideoInfo:
    """The probe receipt — what the container *claims* (fps/frames are estimates on VFR video)."""

    path: str
    name: str
    width: int
    height: int
    fps: float
    n_frames: int
    duration_s: float
    size_bytes: int

    def to_json(self) -> dict:
        return {
            "path": self.path, "name": self.name, "width": self.width, "height": self.height,
            "fps": round(self.fps, 3), "n_frames": self.n_frames,
            "duration_s": round(self.duration_s, 2), "size_bytes": self.size_bytes,
        }


def open_capture(path: str | Path) -> "cv2.VideoCapture":
    """An opened capture, or `VideoError` with the reason. FFMPEG backend first — it is the one
    whose metadata we have characterised; MSMF reads fourcc as garbage and disagrees on counts."""
    p = Path(path)
    if not p.is_file():
        raise VideoError(f"no video file at {p.as_posix()}")
    cap = cv2.VideoCapture(p.as_posix(), cv2.CAP_FFMPEG)
    if not cap.isOpened():
        cap = cv2.VideoCapture(p.as_posix())  # any backend that will have it
    if not cap.isOpened():
        raise VideoError(
            f"could not decode {p.name} — not a video, or a codec this build of OpenCV "
            "cannot read")
    return cap


def probe(path: str | Path) -> VideoInfo:
    """Metadata + a decode proof: the first frame is actually read, so 'probed OK' means
    'this video will decode', not 'a header parsed'."""
    p = Path(path)
    cap = open_capture(p)
    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        ok, first = cap.read()
        if not ok or first is None:
            raise VideoError(f"{p.name} opened but no frame decodes — the stream is empty "
                             "or the codec is unsupported")
        if width <= 0 or height <= 0:
            height, width = first.shape[:2]
    finally:
        cap.release()
    duration = (n_frames / fps) if fps > 0 else 0.0
    return VideoInfo(path=p.resolve().as_posix(), name=p.name, width=width, height=height,
                     fps=fps, n_frames=n_frames, duration_s=duration,
                     size_bytes=p.stat().st_size)


def to_gray(frame_bgr: np.ndarray) -> np.ndarray:
    """BGR uint8 -> float32 signal plane. The per-pixel MAX over channels, not a mean and not
    BT.601 luma.

    A perceptual weighting is wrong here for the obvious reason (nothing about a fluorophore is
    perceptual). A *mean* is wrong for a subtler one: it divides by three whenever the signal lives
    in one channel, and by a different amount when it does not — an accidental gain that depends on
    the source's colour. Measured on a real green survey it cost 1.23 bits of the tracker's uint8
    range (163 levels -> 71), shrank the black-frame threshold's headroom from 1.67x to 1.24x, and
    quietly turned `f > 5.0` downstream into `f > 15`.

    The max equals the dominant channel exactly for a single-channel source (ratio 1.00000 measured
    across five real videos) and is never dimmer than the strongest channel of a white or true-RGB
    one. It carries no assumption about WHICH channel that is.
    """
    return frame_bgr.astype(np.float32).max(axis=2)


def iter_gray(path: str | Path, *,
              on_frame: Callable[[int, np.ndarray], None] | None = None,
              ) -> Iterator[tuple[int, np.ndarray]]:
    """Stream `(index, gray float32 full-res)` for every decodable frame, sequentially.
    One frame in memory at a time. The capture is released even if the consumer stops early."""
    cap = open_capture(path)
    try:
        i = 0
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            g = to_gray(frame)
            if on_frame is not None:
                on_frame(i, g)
            yield i, g
            i += 1
    finally:
        cap.release()


def read_frames_at(path: str | Path, indices: list[int],
                   consume: Callable[[int, np.ndarray], None],
                   *, progress: Callable[[int, int], None] | None = None,
                   colour: Callable[[int, np.ndarray], None] | None = None,
                   scanned: Callable[[int, int], None] | None = None,
                   cancel=None) -> list[int]:
    """One forward pass; `consume(index, gray)` fires for each requested index, in order.
    `grab()` skips the frames in between without the BGR conversion. Returns the indices that
    were actually reachable (a truncated stream shortens the list rather than raising).

    `colour(index, frame_bgr)`, if given, sees the frame BEFORE `to_gray` collapses it. That is the
    only seam where the source's colour still exists, and these are the very frames that become the
    mosaic's pixels — so the measured tint describes what is rendered, not what was skipped.

    ⏱️ **TWO counters, because they measure two different things (R48.3).**
    `progress(n_consumed, n_wanted)` counts what the CALLER asked for; `scanned(frames_passed,
    frames_to_pass)` counts what it COSTS — this is one forward pass, so the work is frames grabbed,
    and the last wanted index is where it ends. They diverge badly whenever the wanted indices are
    not evenly spread: the mosaic's keyframes are spaced by *travel*, so a dwell is thousands of
    frames that yield none and a bar driven by `progress` sits still through it. Drive the bar from
    `scanned`, and the sentence from `progress`.

    `cancel` is polled inside the skip loop as well — the gap between two wanted indices is
    otherwise the one stretch of this pass with no boundary to stop on, and on a long dwell that is
    thousands of frames of an unstoppable Stop button.
    """
    want = sorted(set(int(i) for i in indices))
    got: list[int] = []
    if not want:
        return got
    span = want[-1] + 1                              # the frames this forward pass must walk past
    cap = open_capture(path)
    try:
        pos = 0
        for n, target in enumerate(want):
            while pos < target:
                if not cap.grab():
                    return got
                pos += 1
                if pos % 128 == 0:                   # ~4 ms of grabbing between checks
                    check_cancelled(cancel, "video decode")
                    if scanned is not None:
                        scanned(pos, span)
            ok, frame = cap.read()
            if not ok or frame is None:
                return got
            pos += 1
            if colour is not None:
                colour(target, frame)
            consume(target, to_gray(frame))
            got.append(target)
            if progress is not None:
                progress(n + 1, len(want))
            if scanned is not None:
                scanned(pos, span)
        return got
    finally:
        cap.release()
