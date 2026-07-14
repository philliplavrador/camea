"""A build = a choice at each pipeline stage + its params, in one object.

`BuildConfig` IS the build's documentation. It is frozen into `build.json` beside every
output, so any mosaic you find later is self-describing: read its build.json to know
exactly which steps + params produced it.
"""
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class BuildConfig:
    build_id: str                      # names the output dir, e.g. "260620d__A_fullframe"
    match: str                         # (3) shift source: "fullframe" | "subregion" | "fused"

    # --- (1) data ---
    data_root: str
    date_dir: str
    ccd_key: str = "Cc"

    # --- challenge metadata (for the multi-team placement challenge; see ledger.py) ---
    team: str | None = None            # which team produced this build, e.g. "T03"
    informed: bool | None = None       # was this team given the border/white-bar briefing?
    method_name: str | None = None     # short canonical name of the placement method
    method_steps: str | None = None    # one-line fingerprint of the approach (for dedup)
    frame_idx: int = 0
    trial_min: int = 12
    trial_max: int = 166

    # --- (2) preprocess (fullframe only) ---
    dog: tuple | None = (3, 30)        # DoG band-pass sigmas g(lo)-g(hi); None = raw
    use_bandpass: bool = True

    # --- (3) subregion source (subregion only) ---
    run_dir: str | None = None         # a run_swim output dir with comparisons/results.csv
    clus_tol: float = 8.0              # subregion shifts within this (px) = same cluster
    prior_tol: float = 55.0            # consensus must agree with the prior within this (px)
    min_sup: int = 2                   # need >= this many agreeing pairings to trust a pair

    # --- (3)-(5) match / refine ---
    snr_min: float = 6.0               # gate SWIM matches
    overlap: float = 400.0             # px: pairs closer than this may overlap (loop search)
    schedule: tuple = ((90, 80), (55, 55), (40, 40))   # (agreement-tol, IRLS-drop) per round
    fuse_tol: float = 30.0             # (fused only) full-frame & subregion must agree within this (px)

    # --- placement source: reuse an already-solved layout instead of re-matching ---
    positions_from: str | None = None  # path to a positions.csv; if set, skip match+solve, just render it

    # --- (6) render ---
    render: bool = True
    render_mode: str = "alpha"         # "alpha" (spectralign) | "feather" (linear) | "median" (robust)
    blend: int = 0                     # alpha mode: 0 = hard seams; >1 = butterworth blend
    flatfield: str | None = None       # None = raw frames; "global" = divide out the vignette before render
    flat_sigma: float = 15.0           # smoothing of the global flat field
    level_norm: bool = True            # also match per-frame brightness (kills ~2.4x exposure spread)

    # --- output geometry ---
    out_root: str = "D:/Projects/Camea/analysis/output/mosaic"
    ctr: int = 256
    tile: int = 512

    def out_dir(self):
        return Path(self.out_root) / self.build_id

    def stages(self):
        """Human-readable one-liner per stage -- the 'what steps' summary in build.json."""
        pre = f"DoG{tuple(self.dog)}" if (self.use_bandpass and self.dog) else "raw"
        match3 = {
            "fullframe": "full-frame SWIM",
            "subregion": f"subregion consensus (snr>={self.snr_min}, sup>={self.min_sup})",
            "fused": f"fused full-frame SWIM & subregion consensus (agree within {self.fuse_tol}px)",
        }.get(self.match, self.match)
        if self.positions_from:                            # render-only build
            solve = f"reused positions from {self.positions_from} (no re-matching)"
            match3 = solve
            backbone = refine = solve
        else:
            backbone = "consecutive-shift chain"
            refine = (f"loop-closure + Placement.rigid + IRLS, schedule={self.schedule}, overlap={self.overlap}"
                      if self.schedule else "skipped (raw backbone chain only, no loop-closure/rigid/IRLS)")
        flat = (f"flat-field ({self.flatfield}, sigma={self.flat_sigma}"
                f"{', level-norm' if self.level_norm else ''}) + " if self.flatfield else "")
        render6 = (f"{flat}render_mode={self.render_mode}"
                   + (f", blend={self.blend}" if self.render_mode == "alpha" else "")) if self.render else "skipped"
        return {
            "1_load": f"{self.date_dir} trials {self.trial_min}-{self.trial_max} (frame {self.frame_idx})",
            "2_preprocess": pre if self.match == "fullframe" else "(band-pass done in run_swim)",
            "3_match": match3,
            "4_backbone": backbone,
            "5_refine": refine,
            "6_render": render6,
        }

    def as_manifest(self):
        m = asdict(self)
        m["stages"] = self.stages()
        return m
