"""What colour is this video — measured, never assumed.

The mosaic composites a single-channel signal (see `video.to_gray`), so the built image is one
plane of numbers. That is right: the *data* is intensity. But a microscope's own picture is not
grey — a fluorescence survey is green, or red, and a mosaic that comes out white looks nothing like
the footage it was built from.

So the display colour is a **palette**, and the palette is **measured from the video at hand**.
Green in, green out; red in, red out; white in, grey out. The index plane written to the PNG is
byte-identical to the grey composite, so a scientist loses nothing — the pixel values still *are*
the data, and a look-up table is the ordinary Fiji/ImageJ convention for exactly this.

⛔ NOTHING HERE KNOWS WHAT ANY PARTICULAR VIDEO LOOKS LIKE. That matters more than it sounds: the
first draft of this reasoning was "the real videos are green fluorescence", and it was *wrong* —
`VID_0001.mp4` in the same acquisition folder is red-and-blue dominant in every one of its 250
frames (max green = 2), and a second survey is green-dominant in only 78 % of frames once dark ones
are counted. A brightness filter had hidden both. Hence two defences below: measure on ON pixels
only, and refuse to tint anything that is not *actually* single-channel.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .config import VideoConfig


@dataclass
class ColourStats:
    """Per-channel evidence accumulated over sampled frames, cheap enough to ride along with a
    decode pass that is happening anyway.

    The statistic is the mean *chromaticity* — each ON pixel normalised to unit length, so
    brightness drops out and only hue is left. Its resultant length then answers "is this all one
    colour?" directly. (A colour covariance was the first attempt and it does not work: once the
    hue is fixed, what remains to vary is the codec's chroma noise, so a genuinely pure-green
    survey scored only 0.956 and would have been rendered grey.)
    """

    n_frames: int = 0
    chroma_sum: np.ndarray = field(default_factory=lambda: np.zeros(3, np.float64))   # BGR
    n_px: int = 0

    def offer(self, frame_bgr: np.ndarray, cfg: VideoConfig) -> None:
        """Add one frame's evidence. ON pixels only — the darkness between cells carries the codec's
        chroma noise and nothing else. ⚠️ That is not fastidiousness: measured on a real survey the
        channel ordering *inverts* in the dark, so a mean over the whole frame reports a green video
        as red."""
        if frame_bgr.ndim != 3 or frame_bgr.shape[2] != 3:
            return
        f = frame_bgr[::cfg.tint_stride, ::cfg.tint_stride].astype(np.float32)
        flat = f.reshape(-1, 3)
        peak = flat.max(axis=1)
        if float(peak.max()) < cfg.tint_min_level:
            return                                   # a black or near-black frame votes on nothing
        thr = max(float(np.percentile(peak, cfg.tint_on_pct)), float(cfg.tint_min_level))
        on = flat[peak >= thr]
        if on.shape[0] < 64:
            return
        self.n_frames += 1
        self.n_px += on.shape[0]
        norm = np.linalg.norm(on, axis=1, keepdims=True)
        self.chroma_sum += (on / np.maximum(norm, 1e-6)).sum(axis=0, dtype=np.float64)

    def to_json(self, cfg: VideoConfig) -> dict:
        """The forensic record: what was measured, and what it decided. `tint_bgr: null` means the
        source was not single-channel enough to tint and the mosaic went out grey."""
        t = tint_of(self, cfg)
        return {"frames_sampled": self.n_frames, "pixels_sampled": int(self.n_px),
                "chromaticity_bgr": [round(float(v), 4) for v in self._chroma()],
                "hue_concentration": round(self.hue_concentration(), 6),
                "tint_bgr": None if t is None else [round(float(v), 4) for v in t]}

    def _chroma(self) -> np.ndarray:
        """The mean unit-colour direction (not itself unit length — its shortfall IS the spread)."""
        if self.n_px == 0:
            return np.zeros(3)
        return self.chroma_sum / float(self.n_px)

    def hue_concentration(self) -> float:
        """Resultant length of the mean chromaticity, in [0, 1]. 1.0 = every ON pixel is the same
        hue; lower means the frame holds several (two fluorophores, say), where a single averaged
        tint would describe nothing that is actually in the picture."""
        if self.n_px < 64:
            return 0.0
        return float(min(1.0, np.linalg.norm(self._chroma())))


def tint_of(stats: ColourStats, cfg: VideoConfig) -> tuple[float, float, float] | None:
    """The source's colour as a BGR weight vector normalised to max 1 — or `None` when the video is
    not effectively single-channel and must stay grey.

    Two conditions, both required. `pc1_share` says the ON pixels lie on one line through colour
    space (one hue). `min/max` says that line is actually off-grey — a white source passes the
    first test trivially and must fail here, or every neutral video would be tinted by whatever
    noise happened to dominate.
    """
    c = stats._chroma()
    hi = float(c.max())
    if stats.n_frames < 1 or hi <= 1e-6:
        return None
    t = c / hi
    if stats.hue_concentration() < cfg.tint_hue_min:
        return None                                  # more than one hue — a real colour image
    if float(t.min()) > cfg.tint_chroma_max:
        return None                                  # near-neutral — grey is the honest rendering
    return (float(t[0]), float(t[1]), float(t[2]))


def palette_rgb(tint_bgr: tuple[float, float, float] | None) -> bytes:
    """The 256-entry PNG palette for a tint: entry *i* is the grey level *i* painted in the source's
    colour. `None` gives the identity ramp, so an untinted build is byte-for-byte what a grayscale
    PNG would have shown.

    ⚠️ Entry 0 stays black either way — `render` writes 0 for uncovered canvas, and that must not
    become a visible colour.
    """
    ramp = np.arange(256, dtype=np.float32)
    if tint_bgr is None:
        rgb = np.repeat(ramp[:, None], 3, axis=1)
    else:
        b, g, r = tint_bgr
        rgb = ramp[:, None] * np.array([r, g, b], np.float32)[None, :]
    return np.clip(np.rint(rgb), 0, 255).astype(np.uint8).tobytes()


__all__ = ["ColourStats", "tint_of", "palette_rgb"]
