"""Pass 1 — coarse whole-video tracking and automatic keyframe selection.

One sequential decode of the entire video at `cfg.track_scale`, chaining
`cv2.phaseCorrelate` frame to frame. Sign convention (verified empirically, see the unit
tests): `phaseCorrelate(a, b)` returns the shift of b's *content* relative to a's, and a
frame's world position is where its top-left sits on the mosaic canvas, so

    pos_b = pos_a - phaseCorrelate(a, b)          (all in full-resolution pixels)

Keyframes are chosen by MOTION, never by a quality score:
- every `keyframe_spacing_px` of accumulated travel (a fast pan samples often, a dwell not
  at all),
- the midpoint of every settled dwell (the stage has stopped — those frames are sharp
  *because the stage is still*, no sharpness metric consulted; R17 stays intact),
- the first and last trackable frame of every segment (so black gaps cost the gap, not the
  neighbourhood).

Black frames (illumination off) split the video into SEGMENTS; tracking never chains across
one. The ±`black_margin_frames` shoulder around a black stretch rides the illumination ramp
and is ineligible for keyframes.

This pass also collects the background model: the per-pixel MEDIAN of a few hundred moving
frames. The scene moves under a static glow (vignette, sensor offset), so the median keeps
the glow and lets the tissue average away. It is SUBTRACTED downstream, never divided —
fluorescence background is additive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import cv2
import numpy as np

from ...core.jobs import check_cancelled
from .config import VideoConfig
from .video import VideoInfo, iter_gray


@dataclass(frozen=True)
class Keyframe:
    """One selected frame: where pass 1 thinks it sits (the PRIOR — pass 2 refines it)."""

    index: int          # frame number in the video
    x: float            # world top-left, full-res px (pass-1 estimate)
    y: float
    segment: int        # tracking segment (black gaps / breaks separate segments)
    reason: str         # travel | dwell | segment-start | segment-end

    def to_json(self) -> dict:
        return {"index": self.index, "x": round(self.x, 2), "y": round(self.y, 2),
                "segment": self.segment, "reason": self.reason}


@dataclass
class TrackResult:
    n_read: int
    pos: np.ndarray                 # (N,2) float64 world top-left per frame; NaN = untracked
    valid: np.ndarray               # (N,) bool — tracked frames
    black: np.ndarray               # (N,) bool
    response: np.ndarray            # (N,) float32 — phase response of the step INTO frame i
    mean_gray: np.ndarray           # (N,) float32
    segment_of: np.ndarray          # (N,) int32; -1 = none
    keyframes: list[Keyframe] = field(default_factory=list)
    bg_small: np.ndarray | None = None     # track-scale median background (float32), or None
    stats: dict = field(default_factory=dict)


class _BackgroundSampler:
    """Deterministic, bounded, evenly-spread sample of moving frames (stored u8 to stay small).

    Grows freely to 2×cap, then halves and doubles its stride — the survivors stay evenly
    spaced across everything seen so far, with no RNG (tests want byte-stable pipelines).
    """

    def __init__(self, cap: int) -> None:
        self.cap = max(8, int(cap))
        self.stride = 1
        self.seen = 0
        self.frames: list[np.ndarray] = []

    def offer(self, small_gray: np.ndarray) -> None:
        if self.seen % self.stride == 0:
            self.frames.append(np.clip(small_gray, 0, 255).astype(np.uint8))
            if len(self.frames) >= 2 * self.cap:
                self.frames = self.frames[::2]
                self.stride *= 2
        self.seen += 1

    def median(self) -> np.ndarray | None:
        if len(self.frames) < 8:
            return None
        return np.median(np.stack(self.frames), axis=0).astype(np.float32)


def track(path: str, info: VideoInfo, cfg: VideoConfig, *,
          progress: Callable[[int, int], None] | None = None,
          cancel=None) -> TrackResult:
    """Track the whole video. `progress(frames_done, frames_expected)` fires every ~100 frames."""
    n_hint = max(1, info.n_frames)
    # Container counts lie in BOTH directions (video.py: "never for arithmetic"). Undercount is
    # handled by the growth path below; overcount must not become a multi-GB allocation off a
    # corrupt header — clamp the up-front size, growth covers any genuinely huge video.
    cap_n = min(int(n_hint * 1.5) + 64, 200_000)
    pos = np.full((cap_n, 2), np.nan)
    valid = np.zeros(cap_n, bool)
    black = np.zeros(cap_n, bool)
    response = np.zeros(cap_n, np.float32)
    mean_gray = np.zeros(cap_n, np.float32)
    segment_of = np.full(cap_n, -1, np.int32)

    scale = float(cfg.track_scale)
    fps = info.fps if info.fps > 1 else 30.0
    dwell_min_frames = max(2, int(round(cfg.dwell_min_s * fps)))
    # geometry thresholds, resolved against THIS video's width (config is width-relative)
    keyframe_spacing_px = cfg.keyframe_spacing_frac * info.width
    dwell_min_travel_px = cfg.dwell_min_travel_frac * info.width
    max_step_px = cfg.max_step_frac * info.width

    win: np.ndarray | None = None
    prev: tuple[int, np.ndarray] | None = None      # (index, small gray) — last tracked frame
    prev2: tuple[int, np.ndarray] | None = None     # the one before it (retry target)
    segment = -1
    seg_first = -1                                   # first frame of the open segment
    seg_last = -1                                    # latest tracked frame of the open segment

    keyframes: list[Keyframe] = []
    kf_at: set[int] = set()
    travel = 0.0                                     # px since last keyframe
    trigger_armed = False                            # spacing reached inside a black margin
    dwell_start = -1
    total_path = 0.0
    n_breaks = 0
    bg = _BackgroundSampler(cfg.bg_samples)

    def eligible(i: int) -> bool:
        """A keyframe may not sit on/near a black frame (illumination ramp)."""
        lo = max(0, i - cfg.black_margin_frames)
        hi = min(len(black), i + cfg.black_margin_frames + 1)
        return bool(valid[i]) and not black[lo:hi].any()

    def emit(i: int, reason: str) -> bool:
        nonlocal travel, trigger_armed
        if i < 0 or i in kf_at or not eligible(i):
            return False
        keyframes.append(Keyframe(index=i, x=float(pos[i, 0]), y=float(pos[i, 1]),
                                  segment=int(segment_of[i]), reason=reason))
        kf_at.add(i)
        travel = 0.0
        trigger_armed = False
        return True

    def close_dwell(end_i: int) -> None:
        """A dwell just ended (or the segment did). Its midpoint earns a keyframe if the view
        actually travelled here since the last one."""
        nonlocal dwell_start
        start = dwell_start
        dwell_start = -1
        if start < 0 or (end_i - start) < dwell_min_frames:
            return
        if travel < dwell_min_travel_px:
            return
        emit((start + end_i) // 2, "dwell")

    def close_segment(last_i: int) -> None:
        nonlocal seg_first, seg_last
        close_dwell(last_i)
        if last_i >= 0 and travel > dwell_min_travel_px:
            # The frame RIGHT before a black gap sits inside the gap's margin and is refused —
            # walk back to the newest eligible frame so the segment's tail is still covered
            # ("black gaps cost the gap, not the neighbourhood" — the end side of that promise).
            for j in range(last_i, max(-1, last_i - cfg.black_margin_frames - 15), -1):
                if emit(j, "segment-end"):
                    break
        seg_first = seg_last = -1

    n_read = 0
    for i, gray in iter_gray(path):
        if i >= len(pos):                            # the container lied by >50 %; grow
            grow = len(pos) // 2 + 64
            pos = np.vstack([pos, np.full((grow, 2), np.nan)])
            valid = np.concatenate([valid, np.zeros(grow, bool)])
            black = np.concatenate([black, np.zeros(grow, bool)])
            response = np.concatenate([response, np.zeros(grow, np.float32)])
            mean_gray = np.concatenate([mean_gray, np.zeros(grow, np.float32)])
            segment_of = np.concatenate([segment_of, np.full(grow, -1, np.int32)])
        n_read = i + 1
        if i % 64 == 0:
            check_cancelled(cancel, "video tracking")
        if progress is not None and i % 100 == 0:
            progress(i, max(n_hint, i + 1))

        small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        if prev is not None and small.shape != prev[1].shape:
            # mid-video resolution change: not registrable across the seam — break, don't crash
            n_breaks += 1
            close_segment(seg_last)
            prev = prev2 = None
            win = None
        m = float(small.mean())
        mean_gray[i] = m
        if m < cfg.black_mean:
            black[i] = True
            if prev is not None:                     # black gap: the segment ends here
                close_segment(seg_last)
                prev = prev2 = None
            continue

        if win is None:
            win = cv2.createHanningWindow((small.shape[1], small.shape[0]), cv2.CV_32F)

        if prev is None:                             # first trackable frame of a new segment
            segment += 1
            seg_first = seg_last = i
            pos[i] = (0.0, 0.0) if not keyframes else pos[keyframes[-1].index] + 0.0
            # Each segment gets its own gauge anchored where the last one left off — purely a
            # starting guess; segments are tied (or not) by pass 2's cross links.
            if np.isnan(pos[i]).any():
                pos[i] = (0.0, 0.0)
            valid[i] = True
            segment_of[i] = segment
            prev = (i, small)
            if not emit(i, "segment-start"):
                trigger_armed = True                 # post-black ramp: first eligible frame wins
            continue

        (sx, sy), resp = cv2.phaseCorrelate(prev[1], small, win)
        step = None
        if resp >= cfg.min_track_response:
            step = (prev[0], -sx / scale, -sy / scale, resp)
        elif prev2 is not None:                      # weak step — retry over a 2-frame gap
            (sx2, sy2), resp2 = cv2.phaseCorrelate(prev2[1], small, win)
            if resp2 >= cfg.min_track_response:
                step = (prev2[0], -sx2 / scale, -sy2 / scale, resp2)
        if step is not None:
            base, dx, dy, resp_used = step
            if float(np.hypot(dx, dy)) > max_step_px * max(1, i - base):
                step = None                          # a jump, not motion
            else:
                pos[i] = pos[base] + (dx, dy)
                valid[i] = True
                segment_of[i] = segment
                response[i] = resp_used
                d = float(np.hypot(*(pos[i] - pos[seg_last])))
                total_path += d
                travel += d
                speed = d / max(1, i - seg_last)
                if speed < cfg.dwell_speed_px:
                    if dwell_start < 0:
                        dwell_start = i
                else:
                    close_dwell(i)
                    bg.offer(small)
                seg_last = i
                prev2, prev = prev, (i, small)
                if travel >= keyframe_spacing_px:
                    trigger_armed = True
                if trigger_armed:
                    emit(i, "travel")                # fires now, or first eligible frame after
        if step is None:                             # untrackable — break the chain here
            n_breaks += 1
            close_segment(seg_last)
            prev = prev2 = None
            # the frame itself is not lost: it becomes the start of the next segment
            segment += 1
            seg_first = seg_last = i
            pos[i] = (0.0, 0.0)
            valid[i] = True
            segment_of[i] = segment
            prev = (i, small)
            if not emit(i, "segment-start"):
                trigger_armed = True

    close_segment(seg_last)
    if progress is not None:
        progress(n_read, n_read)

    pos, valid, black = pos[:n_read], valid[:n_read], black[:n_read]
    response, mean_gray, segment_of = response[:n_read], mean_gray[:n_read], segment_of[:n_read]
    keyframes.sort(key=lambda k: k.index)

    # Emission is causal, but black stretches are not: a keyframe emitted just BEFORE the lights
    # went out sits on the dimming ramp. Re-check every keyframe against the finished black map.
    def _clean(k: Keyframe) -> bool:
        lo = max(0, k.index - cfg.black_margin_frames)
        hi = min(n_read, k.index + cfg.black_margin_frames + 1)
        return not black[lo:hi].any()

    keyframes = [k for k in keyframes if _clean(k)]

    measured = response[(response > 0) & valid[:len(response)]]
    stats = {
        "frames_read": int(n_read),
        "frames_black": int(black.sum()),
        "frames_tracked": int(valid.sum()),
        "segments": int(segment + 1),
        "tracking_breaks": int(n_breaks),
        "total_path_px": round(float(total_path), 1),
        "median_track_response": round(float(np.median(measured)), 4) if measured.size else 0.0,
        "keyframes": len(keyframes),
        "keyframe_reasons": {r: sum(1 for k in keyframes if k.reason == r)
                             for r in ("travel", "dwell", "segment-start", "segment-end")},
    }
    return TrackResult(n_read=n_read, pos=pos, valid=valid, black=black, response=response,
                       mean_gray=mean_gray, segment_of=segment_of, keyframes=keyframes,
                       bg_small=bg.median(), stats=stats)
