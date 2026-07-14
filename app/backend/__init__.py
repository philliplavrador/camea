"""Camea Mosaic Builder — backend package.

THE CONTRACT IS `app/API.md`. Read it before touching anything in here. It defines every HTTP
endpoint, the tile state machine, and the composite<->world arithmetic. Seven agents build against
it in parallel; a local "improvement" that diverges from it is a bug.

⛔ THE APP CALLS `analysis/mosaic/`. IT NEVER FORKS IT.
   Two copies of t33 is a silent regression waiting to happen, and
   `analysis/tests/test_mosaic_312.py` (~180 s cold, asserts 312/312) is the only thing standing
   between this project and one. It must still pass after anything the app forces on t27/t33.

Layout
------
    jobs.py     the async job registry. Placement runs 25 s - 10 min SYNCHRONOUSLY with no
                progress callback of any kind, so every long operation is start -> job id -> poll.
    loader.py   log.txt parsing, frame IO (numpy, 180-deg flipped), flat-field, the GLOBAL tone
                window, the blank scan.
    engine.py   the only module that imports t27/t33/render. Owns the anchor-composite primitive.
    project.py  the project file: read / write / validate / migrate. It IS a ground-truth document.
    export.py   16-bit TIFF (+ coverage mask), display PNG, positions.csv, GT JSON, QC report.
    server.py   FastAPI. Owns the session; wires the rest together.

The five things that have already bitten someone here
-----------------------------------------------------
1. THE 180-DEGREE FLIP IS LOAD-BEARING. XML ax=-1, ay=-1 => the display frame is the raw array
   rotated 180. Every existing position, every SWIM dx/dy and all three ground truths live in the
   FLIPPED frame. Get it wrong and the app is 180 out from every prior result -- AND IT WILL LOOK
   PLAUSIBLE.
2. POSITIONS ARE TOP-LEFT CORNERS, NOT CENTRES. Everything that plots them adds +256.
3. CUDA DETECTION MUST EXECUTE A REAL OP. `import cupy` SUCCEEDS on a broken CUDA install; only
   `cupy.zeros(1) + 1` raises. A `try: import cupy` guard DOES NOT WORK. Reuse `t27.xp()`.
4. BLANK FRAMES REGISTER CONFIDENTLY AND WRONGLY (+0.43 at zero shift, 136 trials apart) because
   they share fixed-pattern SENSOR structure, not scene. The matcher REFUSES them, it does not
   score them.
5. THE 26 THROWN-OUT SNAPSHOTS ARE NOT DATA. Never load them, for any purpose. Get the trial list
   from `analysis/ground_truth/excluded.py :: usable_trials(lo, hi)`. Never hard-code a range.
"""
from __future__ import annotations

__version__ = "1.0.0"

# --- Constants shared by BOTH halves of the app. Mirrored in app/API.md §1.1. -------------
# If you change one of these, change API.md and tell the other agents. Do not fork them.

TILE = 512                    # px, square. t33.TILE, t27.H/W. 512 is hard-coded through the stack.
FADE_MS = 1000                # the placement fade, transparent -> opaque. THE point of the sweep.
DOG_LO, DOG_HI = 3, 30        # the band-pass everything matches on (mosaic/quality.py:band_pass)
FLAT_SIGMA = 15.0             # vignette = Gaussian(sigma=15) of the per-pixel median
TONE_PCT_LO = 0.5             # GLOBAL tone window percentiles, AFTER flat-fielding
TONE_PCT_HI = 99.6
TONE_N_SAMPLE = 96            # frames sampled (evenly) to estimate the flat + tone
BLANK_PCT = 2.0               # blank threshold = this percentile of PASS-1 texture
BLANK_THRESHOLD = 60.1        # the value 260620d yields. RECOMPUTED per dataset; this is a fallback.
SNAP_RADIUS = 64              # default local-search radius, px. NEVER let the UI exceed 128:
                              # the electrode grid repeats every 256 px and a wide LOCAL search
                              # locks onto a grid alias. Search wide with mode="global" instead.
ANCHOR_KPK = 8                # t33.match kpk for a single-tile anchor -- exactly t33.py:732
ANCHOR_MINFRAC = 0.0          # exactly t33.py:732. Do not "improve" these.
ANCHOR_MINABS = 120000.0      # exactly t33.py:732. ~half a tile of real overlap.
MATCH_CACHE_SIZE = 32         # LRU entries for the anchor-match memo. See API.md §7.4.
THIN_MARGIN = 0.10            # below this, best-minus-second is the signature of a surviving alias

TILE_STATES = ("anchored", "unverified", "unplaced", "excluded")

#: app state  ->  ground-truth `status`. The GT files spell it "anchor", so the wire does too.
STATE_TO_STATUS = {
    "anchored": "anchor",
    "unverified": "unverified",
    "unplaced": "unplaced",
    "excluded": "excluded",
}
STATUS_TO_STATE = {v: k for k, v in STATE_TO_STATUS.items()}
