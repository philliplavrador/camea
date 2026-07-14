"""Stages (1)-(2): load raw snapshot frames and (optionally) band-pass them.

Shared by every build. Frames are loaded once via vscope and cached to `frames.npy`
so re-runs and the render stage are instant.
"""
from pathlib import Path
import numpy as np


def list_trials(data_root, date_dir, trial_min, trial_max):
    """Trials whose `.xml` exists on disk, in acquisition order (= trial number)."""
    root = Path(data_root) / date_dir
    return [t for t in range(trial_min, trial_max + 1)
            if (root / f"{t:03d}.xml").exists()]


def load_frames(data_root, date_dir, trials, ccd_key="Cc", frame_idx=0, cache=None):
    """Load frame `frame_idx` of each trial's CCD stack as a float32 (N,512,512) array.

    If `cache` (a path) exists and matches len(trials), it is loaded instead of re-read.
    """
    cache = Path(cache) if cache else None
    if cache and cache.exists() and np.load(cache, mmap_mode="r").shape[0] == len(trials):
        frames = np.load(cache)
        print("loaded cached frames", frames.shape)
        return frames

    import vscope
    root = Path(data_root) / date_dir
    frames = np.zeros((len(trials), 512, 512), np.float32)
    for i, t in enumerate(trials):
        vs = vscope.load(str(root / f"{t:03d}.xml"))
        frames[i] = np.asarray(vs.ccd[ccd_key][frame_idx], float)
        if i % 50 == 0:
            print(f"  loaded {i}/{len(trials)}")
    if cache:
        np.save(cache, frames)
        print("cached frames", frames.shape)
    return frames


def dog(im, sigma_lo, sigma_hi):
    """Difference-of-Gaussians band-pass g(sigma_lo) - g(sigma_hi): suppresses the
    periodic electrode grid + slow vignette before matching."""
    import cv2
    return cv2.GaussianBlur(im, (0, 0), sigma_lo) - cv2.GaussianBlur(im, (0, 0), sigma_hi)


def bandpass(frames, sigmas):
    """DoG every frame if `sigmas`=(lo,hi) is given, else return the raw frames (as a
    list). This is exactly `[_dog(f) for f in frames] if USE_BANDPASS else [f ...]`."""
    if sigmas is None:
        return [f for f in frames]
    return [dog(f, sigmas[0], sigmas[1]) for f in frames]


# --- flat-fielding (render stage only) ------------------------------------------------
# The single biggest visual win: every raw 512x512 snapshot has the same camera-fixed
# illumination vignette (bright centre, dark edges). Placing raw frames makes the mosaic
# a quilt of bright-centred diamonds with hard seams. The tissue/grid MOVE between frames
# (the camera translates over a fixed sample) but the vignette does NOT -> the per-pixel
# median across all frames is a clean estimate of that vignette. Divide it out and the
# overlapping tiles match, so the mosaic reads as one continuous field.

def compute_flat(frames, sigma=15.0):
    """Global illumination field = smoothed per-pixel median across all frames,
    normalised to mean 1.0. Divide a frame by this to remove the vignette."""
    import cv2
    flat = np.median(np.asarray(frames, np.float32), axis=0)
    flat = cv2.GaussianBlur(flat, (0, 0), float(sigma))
    return (flat / float(flat.mean())).astype(np.float32)


def flat_level(frames):
    """Common target level = median of the per-frame medians (frames vary ~2.4x in
    exposure on 260620d); used to bring every corrected frame to the same brightness."""
    return float(np.median([np.median(f) for f in frames]))


def flat_correct(frame, flat_n, level=None):
    """Divide out the vignette `flat_n`; if `level` given, rescale so this frame's median
    matches the common level (kills the 2.4x per-frame exposure spread)."""
    c = np.asarray(frame, np.float32) / np.maximum(flat_n, 1e-3)
    if level is not None:
        c = c * (level / max(float(np.median(c)), 1e-3))
    return c
