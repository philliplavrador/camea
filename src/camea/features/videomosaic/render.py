"""Rendering — global bounds, exposure gains, feathered compositing, tone, files on disk.

The canvas is computed from the solved positions, never guessed. Every contributing frame is
background-subtracted (the static-glow model from pass 1) and gain-matched (one scalar per frame —
illumination drifts ~2× over a survey; ZNCC registration never saw it, but a composite
would). Blending is the house feather: a bilinear tent per frame, sum(w·I)/sum(w) — overlap
seams cross-fade instead of stepping. Alignment does the heavy lifting; the blend just keeps
honest joins quiet.

Tone follows core's convention (percentile window, 8-bit, grayscale PNG). The raw float
composite is not kept — the mosaic's truth is the positions table, which is what exports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import cv2
import numpy as np

from ...core.jobs import check_cancelled
from .config import VideoConfig


class RenderError(Exception):
    """The mosaic cannot be rendered, with the reason in one sentence."""


@dataclass
class RenderResult:
    canvas_w: int
    canvas_h: int
    origin_x: float                      # world coordinate of canvas (0,0)
    origin_y: float
    coverage_frac: float
    mosaic_u8: np.ndarray                # (H,W) uint8 — toned display mosaic
    tone_lo: float
    tone_hi: float
    gains: dict[int, float] = field(default_factory=dict)   # keyframe list index -> gain
    stats: dict = field(default_factory=dict)


def background_full(bg_small: np.ndarray | None, wh: tuple[int, int],
                    cfg: VideoConfig) -> np.ndarray | None:
    """The full-resolution static background from pass 1's track-scale median, or None.
    Smoothed at track scale so it keeps the glow (vignette, sensor offset) and never the
    electrode grid. ⚠️ This is SUBTRACTED, never divided: fluorescence background is
    additive; dividing by a near-black median amplifies dark-region noise and decorrelates
    overlapping crops (measured on the real videos — it halved registration NCC)."""
    if bg_small is None:
        return None
    f = cv2.GaussianBlur(bg_small, (0, 0), cfg.bg_sigma)
    f = cv2.resize(f, wh, interpolation=cv2.INTER_LINEAR)
    return f.astype(np.float32)


def subtract_background(gray: np.ndarray, bg: np.ndarray | None) -> np.ndarray:
    """One frame, static glow removed (or a plain copy when there is no model)."""
    if bg is None:
        return gray.astype(np.float32, copy=True)
    return np.maximum(gray - bg, 0.0).astype(np.float32)


def _tent(h: int, w: int) -> np.ndarray:
    """The bilinear tent window (t33's feather, restated for an arbitrary frame size)."""
    wx = 1.0 - np.abs(np.linspace(-1.0, 1.0, w, dtype=np.float32))
    wy = 1.0 - np.abs(np.linspace(-1.0, 1.0, h, dtype=np.float32))
    return np.maximum(np.outer(wy, wx), 1e-3)


def exposure_gains(levels: dict[int, float], cfg: VideoConfig) -> dict[int, float]:
    """One scalar per frame: reference (the median frame level) / frame level, clamped.
    Levels are measured by the caller on background-subtracted pixels (a robust upper-mid
    percentile of the on-signal pixels)."""
    vals = [v for v in levels.values() if v > 1e-3]
    if not vals:
        return {k: 1.0 for k in levels}
    ref = float(np.median(vals))
    return {k: (float(np.clip(ref / v, cfg.gain_lo, cfg.gain_hi)) if v > 1e-3 else 1.0)
            for k, v in levels.items()}


def render(positions: dict[int, tuple[float, float]],
           fetch: Callable[[int], np.ndarray],
           frame_wh: tuple[int, int],
           gains: dict[int, float],
           cfg: VideoConfig, *,
           progress: Callable[[int, int], None] | None = None,
           cancel=None) -> RenderResult:
    """Composite `fetch(k)` (full-res background-subtracted float32) for every keyframe k in
    `positions`.

    `positions` are world top-left corners (any gauge — the canvas re-zeros them).
    """
    if not positions:
        raise RenderError("nothing to render — no placed keyframes")
    w, h = frame_wh
    xs = np.array([p[0] for p in positions.values()])
    ys = np.array([p[1] for p in positions.values()])
    ox, oy = float(xs.min()), float(ys.min())
    W = int(np.ceil(xs.max() - ox)) + w
    H = int(np.ceil(ys.max() - oy)) + h
    mpx = W * H / 1e6
    if mpx > cfg.max_canvas_mpx:
        raise RenderError(
            f"the solved mosaic canvas would be {W}×{H} px ({mpx:.0f} Mpx) — beyond the "
            f"{cfg.max_canvas_mpx:.0f} Mpx guard. This usually means registration ran away; "
            "see the rejected-link diagnostics.")

    num = np.zeros((H, W), np.float32)
    den = np.zeros((H, W), np.float32)
    tent = _tent(h, w)
    order = sorted(positions)
    for n_done, k in enumerate(order):
        check_cancelled(cancel, "mosaic render")
        img = fetch(k)
        g = float(gains.get(k, 1.0))
        x = int(round(positions[k][0] - ox))
        y = int(round(positions[k][1] - oy))
        num[y:y + h, x:x + w] += tent * (img * g)
        den[y:y + h, x:x + w] += tent
        if progress is not None:
            progress(n_done + 1, len(order))

    mask = den > 1e-3
    # in place from here down — the peak must stay ≈ the two accumulators, not 3× them
    np.divide(num, den, out=num, where=mask)
    del den
    covered = num[mask]
    if covered.size == 0:
        raise RenderError("the composite is empty — no frame contributed any pixels")
    lo = float(np.percentile(covered, cfg.tone_lo_pct))
    hi = float(np.percentile(covered, cfg.tone_hi_pct))
    del covered
    if hi - lo < 1e-6:
        hi = lo + 1.0
    np.subtract(num, lo, out=num)
    np.multiply(num, 255.0 / (hi - lo), out=num)
    np.clip(num, 0, 255, out=num)
    u8 = num.astype(np.uint8)
    del num
    u8[~mask] = 0

    return RenderResult(
        canvas_w=W, canvas_h=H, origin_x=ox, origin_y=oy,
        coverage_frac=float(mask.mean()), mosaic_u8=u8, tone_lo=lo, tone_hi=hi,
        gains={k: round(float(gains.get(k, 1.0)), 4) for k in order},
        stats={"canvas_w": W, "canvas_h": H, "canvas_mpx": round(mpx, 1),
               "coverage_frac": round(float(mask.mean()), 4),
               "frames_rendered": len(order)})


def preview_of(mosaic_u8: np.ndarray, cfg: VideoConfig) -> np.ndarray:
    """The mosaic shrunk so its longest side fits `preview_max_px` (never enlarged)."""
    H, W = mosaic_u8.shape
    s = cfg.preview_max_px / max(H, W)
    if s >= 1.0:
        return mosaic_u8
    return cv2.resize(mosaic_u8, (max(1, int(W * s)), max(1, int(H * s))),
                      interpolation=cv2.INTER_AREA)
