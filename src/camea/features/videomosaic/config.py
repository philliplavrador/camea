"""The video pipeline's tunables — every constant in one place, none of them per-dataset.

⛔ THE APP CARRIES NO DATASET KNOWLEDGE. Everything here is an *algorithm* parameter with a
default chosen to be safe across ordinary survey videos (they were sanity-checked against the
first real ones, but nothing below names a video, a frame count, a duration, or a scene).
A normal user never sees or edits these; the API accepts an override dict so development and
tests can probe the edges without a code change.

Units: pixels are FULL-RESOLUTION video pixels unless a name says otherwise; times are seconds.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields


@dataclass(frozen=True)
class VideoConfig:
    # ---- pass 1: tracking ------------------------------------------------------------------
    track_scale: float = 0.25
    """Downscale factor for the coarse per-frame tracker. 0.25 keeps a 1080p video ~real-time."""

    black_mean: float = 3.0
    """A frame whose mean gray (0–255) is below this is 'black' (illumination off): untrackable,
    never a keyframe. Segments split here."""

    black_margin_frames: int = 5
    """Frames adjacent to a black stretch ride the illumination ramp — excluded from keyframes."""

    min_track_response: float = 0.30
    """Minimum cv2.phaseCorrelate response for a trusted frame-to-frame step. Below it the
    tracker retries against an earlier frame, then declares a break."""

    max_step_frac: float = 0.0625
    """A single-frame displacement above this fraction of the frame WIDTH is not camera motion
    (it is a glitch or a scene cut) — treated as a tracking break, never accumulated.
    (Geometry parameters are width-relative so the same defaults serve any resolution —
    0.0625 × 1920 = the 120 px the real videos validated.)"""

    # ---- pass 1: keyframe selection ----------------------------------------------------------
    keyframe_spacing_frac: float = 0.234375
    """Emit a keyframe every this fraction of the frame WIDTH of accumulated travel (~77 %
    sequential overlap, whatever the resolution; × 1920 = the 450 px the real videos
    validated). Motion-driven, not time-driven: a dwell emits nothing, a fast pan often."""

    dwell_speed_px: float = 0.5
    """Below this speed (px/frame) the stage is considered dwelling."""

    dwell_min_s: float = 0.5
    """A dwell must last this long before its midpoint earns a keyframe (the stage has settled —
    the sharpest frames money can buy without ever *scoring* sharpness)."""

    dwell_min_travel_frac: float = 0.0625
    """No dwell keyframe unless the view moved at least this fraction of the frame width
    since the last keyframe."""

    # ---- background model ----------------------------------------------------------------
    bg_samples: int = 256
    """Moving, non-black frames sampled (at track scale) for the per-pixel median background.
    In sparse fluorescence the static field (vignette glow, sensor offset) is ADDITIVE — the
    model is SUBTRACTED, never divided (division is brightfield physics; here it amplifies
    dark-region noise and decorrelates overlaps — measured, not theorised)."""

    bg_sigma: float = 25.0
    """Gaussian smoothing (in track-scale px) of the median background, so the model keeps the
    smooth glow but never the electrode grid."""

    # ---- pass 2: registration ----------------------------------------------------------------
    min_overlap_frac: float = 0.06
    """Minimum predicted overlap (fraction of frame area) for a pair to be worth a link."""

    cross_overlap_frac: float = 0.12
    """Minimum predicted overlap for a NON-adjacent (drift-correcting) link."""

    max_cross_links_per_keyframe: int = 6
    """Cross links kept per keyframe (closest first). Bounds the graph; sequential links are
    always kept."""

    register_scale: float = 0.5
    """Overlap crops are registered at this scale (phase correlation is sub-pixel; ×2 at 0.5
    still lands ~1 px). Full resolution doubles the cost for accuracy the seams don't show."""

    min_link_response: float = 0.08
    """Minimum phase-correlation response for a link measurement to count at all."""

    min_link_ncc: float = 0.30
    """Minimum zero-normalised cross-correlation over the actual overlap at the measured offset.
    The arbiter that catches a confident-but-wrong phase peak (the electrode grid's comb)."""

    verify_highpass_sigma: float = 48.0
    """The verification ZNCC is computed on high-passed crops (x − Gauss(x, σ), full-res px):
    smooth junk — background residue, illumination ramps — must not be able to move the
    arbiter either way. Correct pairs score ~0.6+, misregistered ones ~0.05 (measured)."""

    max_correction_seq_px: float = 100.0
    """A sequential link may correct the tracked prior by at most this much."""

    max_correction_cross_px: float = 300.0
    """A cross link may correct its prior by at most this much (priors carry accumulated drift)."""

    refine_rounds: int = 1
    """After the first global solve, re-measure links at the solved positions this many times.
    Cross links whose priors were drift-poisoned get a second, better-seeded chance."""

    # ---- global solve ------------------------------------------------------------------------
    irls_iters: int = 12
    """Reweighting iterations of the translation-only least squares. Convergence is geometric
    but not fast: at 4 iterations a gross outlier still bleeds tens of px into its honest
    neighbours' residuals, and the hard gate then drops THEM (measured — it fragmented the
    graph). At 12 the honest residuals are sub-px before the gate ever fires."""

    huber_px: float = 3.0
    """Residual scale (px) where a link's influence starts shrinking."""

    max_residual_px: float = 15.0
    """Links whose residual exceeds this after IRLS are dropped outright and the solve repeats."""

    # ---- render ------------------------------------------------------------------------------
    gain_lo: float = 0.4
    gain_hi: float = 2.5
    """Per-keyframe exposure gain clamp (illumination drifts ~2× over a long survey)."""

    tone_lo_pct: float = 0.5
    tone_hi_pct: float = 99.6
    """Display tone window percentiles — the house convention (core.frames.Tone uses the same)."""

    preview_max_px: int = 2048
    """Longest side of the preview PNG — the instant fit view. The viewer loads the full-resolution
    `mosaic.png` when the user zooms, so this is a first-paint budget, not the deliverable."""

    png_compress_level: int = 6
    """PNG deflate level for the full mosaic. Measured on a real 40 Mpx build: level 1 = 25.1 MB in
    0.4 s, level 6 = 16.1 MB in 0.9 s, level 9 = 14.8 MB in 5.3 s. 6 is where the curve turns."""

    # ---- display colour (a measured palette, never an assumption) --------------------------------
    tint_samples: int = 8
    """Keyframes sampled for the source-colour measurement, spread across the video. They ride the
    decode pass that already happens — no extra read."""

    tint_stride: int = 4
    """Pixel decimation while sampling colour. A hue needs statistics, not every pixel."""

    tint_on_pct: float = 98.0
    """Colour is measured on the brightest this-percentile of pixels. ⚠️ NOT a cosmetic choice: in
    the dark between cells the channel ordering INVERTS (codec chroma noise), and averaging that in
    is precisely how a green video measures as grey."""

    tint_min_level: float = 12.0
    """A pixel must reach this on its strongest channel to vote on colour, and a frame must contain
    at least one such pixel to be sampled at all. Below it the 'colour' is codec quantisation — an
    all-but-black video would otherwise report a confident hue built from nothing."""

    tint_hue_min: float = 0.985
    """Minimum resultant length of the mean ON-pixel chromaticity before a tint is allowed. 1.0
    means every lit pixel is the same hue; a scene holding two fluorophores falls below it and is
    rendered grey rather than painted a colour that is in none of it."""

    tint_chroma_max: float = 0.30
    """A tint is applied only if its weakest channel is below this fraction of its strongest. A
    white or neutral source is perfectly hue-concentrated and must be caught here instead."""

    # ---- resource guards -----------------------------------------------------------------------
    max_canvas_mpx: float = 160.0
    """Refuse to allocate a mosaic canvas beyond this many megapixels (≈1.3 GB of accumulators).
    A runaway solve must fail with a sentence, not an OOM."""

    max_keyframe_cache_mb: float = 2048.0
    """Keyframes are cached flattened at float16 for registration + render. Beyond this budget
    the build refuses with advice (longer spacing / shorter video) instead of thrashing."""

    min_keyframes: int = 2
    """Fewer usable keyframes than this is not a mosaic — fail with the reason."""

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_overrides(cls, overrides: dict | None) -> "VideoConfig":
        """A config from the defaults + a partial override dict. Unknown keys are refused loudly —
        a typo that silently does nothing is worse than a 400."""
        if not overrides:
            return cls()
        known = {f.name for f in fields(cls)}
        bad = sorted(set(overrides) - known)
        if bad:
            raise ValueError(f"unknown VideoConfig keys: {bad}; known: {sorted(known)}")
        return cls(**overrides)
