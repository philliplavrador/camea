"""orientation.py — scoring the four ways the chip could sit in the mosaic.

THE PROBLEM
-----------
Camea numbers electrodes on the IMAGE (120 across x 220 down); MaxWell numbers them on the CHIP
(220 x 120). The quarter turn between the two is forced by the shapes, but **which corner of the
mosaic the chip's origin landed in is a fact about the microscope, and no file records it** — which
leaves four seatings. Pick wrong and every neuron is paired with the wrong electrode, silently.

THE TEST
--------
A located region recording watched one field optically while the MEA recorded it electrically. So
for each seating we can ask: *do the electrodes that seating puts under this field actually fire
when the field lights up?*

    region's Camea electrode ids --(seating)--> chip ids --> routed channels --> spike trains
    region video ---------------------------------------> calcium activity over time
    score = correlation of the two, on a common clock

Two things separate the seatings, and both are reported because they fail differently:

* **Coverage.** Only ~1k of 26,400 pads are routed, and on P003658 they sit in one corner block. A
  seating that puts *no recorded electrode* under a field the experimenter deliberately aimed at
  active tissue is unlikely to be right — and it cannot be scored at all, which is not the same as
  scoring badly and must not be reported as if it were.
* **Coincidence.** Among seatings that do have electrodes, the right one should show spikes rising
  when the calcium does.

🔴 **THE RESULT IS UNVALIDATED, AND THE CALLER MUST SAY SO** (issue 003, his instruction 2026-08-13).
The clock alignment leans on the 2P-lamp marks, and those marks **did not survive checking** against
the calcium video: 70 MEA episodes against 5 video dark stretches, no consistent offset, and a
confound where the "episodes" may just be where the broken decoder emitted anything at all. He asked
for this built anyway. So it computes and ranks, it never *confirms*: `Orientation.confirmed` is set
only by a human, and the UI carries the caveat. Re-run this once the real MaxLab decoder is in
place — the arithmetic does not change, only whether its input means anything.

⛔ NO DATASET KNOWLEDGE. Nothing here knows a plate, a run, a trial or a count. It is handed a
region's electrode ids, a recording and a video, and it reports numbers.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path

import numpy as np

__all__ = [
    "SeatingScore",
    "align_offset",
    "intervals_to_mask",
    "pearson",
    "population_rate",
    "score_seatings",
    "video_activity",
]

#: Bin width for both time series. 100 ms is well below the seconds-long calcium transients this
#: compares and well above the jitter any clock alignment here can promise.
BIN_S = 0.1


@dataclass(frozen=True)
class SeatingScore:
    """One candidate seating, and how well it explains the data."""

    flip_x: bool
    flip_y: bool
    #: How many of the region's pads this seating maps onto electrodes that were actually recorded.
    n_recorded: int
    #: How many pads the region covers at all (same for every seating — the denominator).
    n_region: int
    n_spikes: int
    #: Spike rate vs calcium activity. **None when there is nothing to correlate** — never 0.0,
    #: because "no electrodes under this field" and "electrodes that did not match" are different
    #: answers and collapsing them would rank an untested seating against a tested one.
    correlation: float | None

    @property
    def scorable(self) -> bool:
        return self.correlation is not None

    def as_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["scorable"] = self.scorable
        d["coverage"] = (self.n_recorded / self.n_region) if self.n_region else 0.0
        return d


# ── time series ─────────────────────────────────────────────────────────────────────────────────


def population_rate(spike_times: np.ndarray, t0: float, t1: float,
                    bin_s: float = BIN_S) -> np.ndarray:
    """Spikes per bin across a set of channels — the electrical activity of a patch of tissue."""
    if t1 <= t0:
        return np.zeros(0)
    n = max(1, int(round((t1 - t0) / bin_s)))
    if spike_times.size == 0:
        return np.zeros(n)
    counts, _ = np.histogram(spike_times, bins=n, range=(t0, t1))
    return counts.astype(np.float64)


def video_activity(path: str | Path, bin_s: float = BIN_S) -> tuple[np.ndarray, float]:
    """Mean frame brightness of a recording, binned. -> ``(values, fps)``.

    Whole-field, not per neuron: segmenting cells is a different feature, and the population
    calcium signal is what a population spike rate can honestly be compared against.

    ⚠️ Reads every frame — minutes for a 300 s recording. Callers run it in a job and cache it.
    cv2 is imported inside so this module stays importable by the route layer.
    """
    import cv2  # noqa: PLC0415

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise FileNotFoundError(f"cannot open {path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS)) or 1.0
    means: list[float] = []
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
            means.append(float(g.mean()))
    finally:
        cap.release()
    if not means:
        return np.zeros(0), fps
    m = np.asarray(means, dtype=np.float64)
    per = max(1, int(round(bin_s * fps)))
    usable = m.size // per * per
    if usable == 0:
        return m.mean(keepdims=True), fps
    return m[:usable].reshape(-1, per).mean(axis=1), fps


def intervals_to_mask(intervals: list[tuple[float, float]], duration_s: float,
                      bin_s: float = BIN_S) -> np.ndarray:
    """A boolean indicator over binned time — used to align the two clocks by their lamp marks."""
    n = max(1, int(round(duration_s / bin_s)))
    mask = np.zeros(n, dtype=bool)
    for a, b in intervals:
        i, j = int(round(a / bin_s)), int(round(b / bin_s))
        mask[max(0, i):max(0, j)] = True
    return mask


def align_offset(mea_mask: np.ndarray, video_mask: np.ndarray, *, bin_s: float = BIN_S,
                 max_shift_s: float = 120.0) -> tuple[float, float]:
    """Best constant clock offset between two event indicators. -> ``(offset_s, jaccard)``.

    ⚠️ **Read the Jaccard, not just the offset.** Two mostly-on signals overlap substantially at any
    shift, so a high number is not by itself evidence of alignment — on this project's data the best
    score was 0.65 between signals of 60% and 80% duty, which is chance (issue 003). The caller
    reports this number so a human can judge it.
    """
    if mea_mask.size == 0 or video_mask.size == 0:
        return 0.0, 0.0
    best = (0.0, 0.0)
    span = int(round(max_shift_s / bin_s))
    for shift in range(-span, span + 1):
        rolled = np.roll(video_mask, shift)
        n = min(mea_mask.size, rolled.size)
        a, b = mea_mask[:n], rolled[:n]
        union = int((a | b).sum())
        if not union:
            continue
        j = float((a & b).sum()) / union
        if j > best[1]:
            best = (shift * bin_s, j)
    return best


def pearson(a: np.ndarray, b: np.ndarray) -> float | None:
    """Correlation of two series, or None when either is flat (undefined, not zero)."""
    n = min(a.size, b.size)
    if n < 3:
        return None
    a, b = a[:n].astype(np.float64), b[:n].astype(np.float64)
    if a.std() < 1e-12 or b.std() < 1e-12:
        return None
    return float(np.corrcoef(a, b)[0, 1])


# ── the scoring ─────────────────────────────────────────────────────────────────────────────────


def score_seatings(
    region_electrodes: list[str],
    *,
    cols: int,
    rows: int,
    stride: int,
    channel_of: dict[int, int],
    spikes_of: dict[int, np.ndarray],
    calcium: np.ndarray,
    duration_s: float,
    offset_s: float = 0.0,
    bin_s: float = BIN_S,
) -> list[SeatingScore]:
    """Score all four seatings for one located region.

    ``channel_of`` maps a MaxWell electrode id to its routed channel (absent = never recorded);
    ``spikes_of`` maps a channel to its spike times in seconds. Both are handed in so this stays
    pure and testable — the caller does the HDF5 reading.

    ``offset_s`` shifts the MEA clock onto the video's. Ranking is left to the caller: this reports
    coverage, spikes and correlation, and refuses to invent a correlation where there is nothing to
    correlate (see :class:`SeatingScore`).
    """
    from camea.core.mearecording import Orientation  # noqa: PLC0415

    parsed: list[tuple[int, int]] = []
    for e in region_electrodes:
        try:
            c, r = (int(v) for v in e.split("-", 1))
        except ValueError:
            continue
        parsed.append((c, r))

    out: list[SeatingScore] = []
    for flip_y in (False, True):
        for flip_x in (False, True):
            o = Orientation(flip_x=flip_x, flip_y=flip_y)
            times: list[np.ndarray] = []
            n_recorded = 0
            for c, r in parsed:
                chip = o.chip_electrode(c, r, cols=cols, rows=rows, stride=stride)
                ch = channel_of.get(chip)
                if ch is None:
                    continue
                n_recorded += 1
                st = spikes_of.get(ch)
                if st is not None and st.size:
                    times.append(st)
            allt = np.concatenate(times) if times else np.zeros(0)
            # The MEA clock moved onto the video's, so both series index the same moments.
            rate = population_rate(allt - offset_s, 0.0, duration_s, bin_s)
            corr = pearson(rate, calcium) if n_recorded else None
            out.append(SeatingScore(flip_x=flip_x, flip_y=flip_y, n_recorded=n_recorded,
                                    n_region=len(parsed), n_spikes=int(allt.size),
                                    correlation=corr))
    return out
