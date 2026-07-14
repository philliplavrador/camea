"""THE excluded-trial list. One place. Everything imports it from here.

The user's ruling, 2026-07-11:

    "i want these tiles to be thrown out and to never be used for any purposes whatsoever"

That is stronger than "never scored". These frames are **not data**. They must never be loaded,
never fed to a placement method, never allowed to vote in a solve, never rendered into a mosaic.

WHY (measured, not assumed):
  * 11 are BLANK -- near-featureless glare (289, 300-309; trial 304 is a literally blank vignette
    blob). What two blank frames share is FIXED-PATTERN SENSOR STRUCTURE, which does not move with
    the stage -- so they correlate at ZERO shift no matter where the microscope actually was. Two
    blank frames 136 trials apart still score +0.43, where two textured frames that far apart sit at
    the ~0.10 noise floor. Any confident registration of a blank tile is a lie, and a *confident* one.
  * 15 are TOO BLURRY (284-296, 299, 310, 348) -- the user's call, by eye, and his eye is the
    authority here. NO automatic measure reproduces it: neither Laplacian-variance sharpness nor the
    electrode-grid FFT peak flags this run against a pass-1-derived threshold (sharpness declines
    smoothly 7.7 -> 6.5 across it, with no cliff). Do not "correct" this list from a metric.
  * 297 and 298 sit inside the blurry run but he judged them sharp enough, and placed them. They are
    NOT excluded.

⚠️ CONSEQUENCE FOR THE SERPENTINE PRIOR. With these trials removed, trial number is still acquisition
ORDER but it is no longer CONTIGUOUS. A "consecutive" pair either side of a gap is really a multi-step
jump, and the one-axis step prior does NOT hold across it. A method that assumes `t` and `t+1` are one
acquisition step apart will silently place the whole tail wrong. Detect the gaps; do not assume them
away. (This is also why removing these frames HELPS: two of T27's eight unresolvable backbone steps,
289->290 and 299->300, were inside this run and existed only because of it.)
"""
from pathlib import Path

DATA_DIR = Path(r"D:/Projects/Camea/data/drive/260620/260620_Imaging/260620d")

# 26 trials. Blank by measurement + too blurry by eye. NOT DATA.
EXCLUDED = frozenset(
    list(range(284, 297))       # 284-296  blurry
    + [299]                     #          blurry
    + list(range(300, 311))     # 300-310  blank (300-309) + blurry (310)
    + [348]                     #          blurry
)
BLANK = frozenset([289] + list(range(300, 310)))         # 11, by measurement
BLURRY = EXCLUDED - BLANK                                 # 15, by the user's eye

# the canonical ranges
PASS1 = (11, 166)
PASS2 = (167, 348)
MERGED = (11, 348)


def is_snapshot(t: int) -> bool:
    """A real 1-frame snapshot on disk (the movies fail the byte-size check)."""
    dat = DATA_DIR / f"{t:03d}-ccd.dat"
    return dat.exists() and dat.stat().st_size == 512 * 512 * 2


def usable_trials(lo: int, hi: int) -> list[int]:
    """THE trial list. Every build and every scorer must get its trials from here.

    Nobody hard-codes a range: an excluded frame that slips into a build's input can displace
    every tile downstream of it.
    """
    return [t for t in range(lo, hi + 1) if t not in EXCLUDED and is_snapshot(t)]


def gaps(trials: list[int]) -> list[tuple[int, int]]:
    """Consecutive pairs in `trials` that are NOT one acquisition step apart, because an excluded
    trial sits between them. The serpentine one-axis prior does not hold across these."""
    return [(a, b) for a, b in zip(trials, trials[1:]) if b != a + 1]


if __name__ == "__main__":
    for name, (lo, hi) in (("pass 1 ", PASS1), ("pass 2 ", PASS2), ("merged ", MERGED)):
        ts = usable_trials(lo, hi)
        g = gaps(ts)
        print(f"{name} {lo}-{hi}: {len(ts):3d} usable trials"
              f"   ({len([t for t in range(lo, hi+1) if t in EXCLUDED])} excluded)"
              f"   gaps: {g}")
    print(f"\nEXCLUDED ({len(EXCLUDED)}): {sorted(EXCLUDED)}")
    print(f"  blank  ({len(BLANK)}): {sorted(BLANK)}")
    print(f"  blurry ({len(BLURRY)}): {sorted(BLURRY)}")
