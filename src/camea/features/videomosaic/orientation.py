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
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

__all__ = [
    "SEATINGS",
    "SeatingScore",
    "align_offset",
    "combined_correlation",
    "intervals_to_mask",
    "null_correlations",
    "pearson",
    "population_rate",
    "score_seatings",
    "seating_rate",
    "video_activity",
]

#: Bin width for both time series. 100 ms is well below the seconds-long calcium transients this
#: compares and well above the jitter any clock alignment here can promise.
BIN_S = 0.1

#: The four candidate seatings, as ``(flip_x, flip_y)``, **in the one order every list in this
#: module uses**. :func:`score_seatings` returns them in this order for every region, which is what
#: lets a caller zip per-region score lists together seat by seat without matching on flags.
SEATINGS: tuple[tuple[bool, bool], ...] = ((False, False), (True, False), (False, True),
                                           (True, True))


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


def video_activity(path: str | Path, bin_s: float = BIN_S, *,
                   progress: Callable[[int, int], None] | None = None,
                   report_every_s: float = 0.25) -> tuple[np.ndarray, float]:
    """Mean frame brightness of a recording, binned. -> ``(values, fps)``.

    Whole-field, not per neuron: segmenting cells is a different feature, and the population
    calcium signal is what a population spike rate can honestly be compared against.

    ⚠️ Reads every frame — minutes for a 300 s recording. Callers run it in a job and cache it.
    cv2 is imported inside so this module stays importable by the route layer.

    ``progress(frames_done, frames_total)`` is the whole reason this is bearable to wait through:
    the DECODED FRAME is the countable unit (BEHAVIOUR R48.3) and the container's own frame count
    is the denominator. ``frames_total`` is **0** when the container will not admit a length —
    honest, and a caller must treat it as "no denominator" rather than divide by it.
    ⭐ It is also the CANCEL seam: this loop has no other natural boundary, so a caller that wants
    a Stop button raises out of the callback (R48.7).

    ``report_every_s`` throttles the callback — measured decode is ~235 fps, and reporting every
    frame would be hundreds of messages a second for a bar that moves 0.004 % each time.
    """
    import cv2  # noqa: PLC0415

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise FileNotFoundError(f"cannot open {path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS)) or 1.0
    # ⚠️ A CLAIM, not a fact — some containers report 0 or a count the stream does not honour, so
    # this is only ever the ETA's denominator, never a loop bound. The loop still stops on `ok`.
    n_claimed = max(0, int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0))
    means: list[float] = []
    last_said = time.monotonic()

    def say() -> None:
        # ⚠️ 0 means "no denominator", and it must stay 0 — reporting `done` as the total would
        # read as 100 % on every single frame. When the stream OUTRUNS the container's claim the
        # count so far becomes the denominator instead: honest ("at least this far"), never > 1.
        if progress is not None:
            progress(len(means), max(n_claimed, len(means)) if n_claimed else 0)

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
            means.append(float(g.mean()))
            if progress is not None and time.monotonic() - last_said >= report_every_s:
                last_said = time.monotonic()
                say()
    finally:
        cap.release()
    say()
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


def _parse_ids(region_electrodes: list[str]) -> list[tuple[int, int]]:
    """``"col-row"`` strings to ``(col, row)`` pairs, skipping anything malformed."""
    parsed: list[tuple[int, int]] = []
    for e in region_electrodes:
        try:
            c, r = (int(v) for v in e.split("-", 1))
        except ValueError:
            continue
        parsed.append((c, r))
    return parsed


def seating_rate(
    region_electrodes: list[str],
    *,
    flip_x: bool,
    flip_y: bool,
    cols: int,
    rows: int,
    stride: int,
    channel_of: dict[int, int],
    spikes_of: dict[int, np.ndarray],
    duration_s: float,
    offset_s: float = 0.0,
    bin_s: float = BIN_S,
) -> tuple[np.ndarray, int, int, int]:
    """The binned spike rate ONE seating puts under one region.

    -> ``(rate, n_recorded, n_region, n_spikes)``. The series half of :func:`score_seatings`,
    split out so a caller that already knows which seating it cares about (the chance-level test)
    can get its series back without recomputing all four.
    """
    from camea.core.mearecording import Orientation  # noqa: PLC0415

    parsed = _parse_ids(region_electrodes)
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
    return rate, n_recorded, len(parsed), int(allt.size)


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
    """Score all four seatings for one located region, in :data:`SEATINGS` order.

    ``channel_of`` maps a MaxWell electrode id to its routed channel (absent = never recorded);
    ``spikes_of`` maps a channel to its spike times in seconds. Both are handed in so this stays
    pure and testable — the caller does the HDF5 reading.

    ``offset_s`` shifts the MEA clock onto the video's. Ranking is left to the caller: this reports
    coverage, spikes and correlation, and refuses to invent a correlation where there is nothing to
    correlate (see :class:`SeatingScore`).
    """
    out: list[SeatingScore] = []
    for flip_x, flip_y in SEATINGS:
        rate, n_recorded, n_region, n_spikes = seating_rate(
            region_electrodes, flip_x=flip_x, flip_y=flip_y, cols=cols, rows=rows,
            stride=stride, channel_of=channel_of, spikes_of=spikes_of,
            duration_s=duration_s, offset_s=offset_s, bin_s=bin_s)
        corr = pearson(rate, calcium) if n_recorded else None
        out.append(SeatingScore(flip_x=flip_x, flip_y=flip_y, n_recorded=n_recorded,
                                n_region=n_region, n_spikes=n_spikes, correlation=corr))
    return out


def combined_correlation(parts: list[tuple[float | None, int]]) -> float | None:
    """One correlation for a seating scored against SEVERAL regions. ``parts`` is per region
    ``(correlation, n_recorded)``.

    ⭐ **WHY A WEIGHTED MEAN AND NOT ONE LONG CORRELATION.** Each region recording is its own video
    on its own clock, aligned to the MEA independently — so the per-region series cannot be laid on
    one axis without inventing a relative clock between videos that nothing measured. What CAN be
    combined honestly is the per-region correlations, weighted by how many recorded pads the
    seating actually has under each region: a region with more pads under it contributes a steadier
    estimate and proportionally more evidence, and a region with none (correlation ``None``)
    contributes **nothing** rather than an invented zero — the same refusal
    :class:`SeatingScore` makes for a single region.
    """
    num = 0.0
    den = 0.0
    for corr, weight in parts:
        if corr is None or weight <= 0:
            continue
        num += corr * weight
        den += weight
    return (num / den) if den else None


# ── the honesty meter: what a WRONG clock produces ──────────────────────────────────────────────

#: How many deliberately-wrong clock offsets the chance level is measured from. Enough that a 95th
#: percentile is a real quantile (10 tail samples), cheap enough to ride inside the job.
NULL_SHIFTS = 200

#: Fixed on purpose: the chance level is part of the reported result, and two runs over the same
#: data must state the same number. (Python's numpy RNG — the repo's Date/random discipline is a
#: frontend rule; what binds here is plain reproducibility.)
NULL_SEED = 7

#: Shifts closer than this to zero (mod the series length) are NOT deliberately wrong: the calcium
#: transients are seconds long and the alignment itself is only good to a bin or two, so a shift
#: inside this band could still be the true clock and would poison the null with real signal.
NULL_GUARD_S = 10.0

#: The percentile of |null correlation| reported as the chance level.
CHANCE_PERCENTILE = 95.0


def null_correlations(
    pairs: list[tuple[np.ndarray, np.ndarray, int]],
    *,
    n_shifts: int = NULL_SHIFTS,
    seed: int = NULL_SEED,
    guard_s: float = NULL_GUARD_S,
    bin_s: float = BIN_S,
) -> np.ndarray:
    """|combined correlation| at deliberately-wrong clock offsets — the null the real one must beat.

    ``pairs`` is per region ``(rate, calcium, weight)`` for ONE seating — the same weights
    :func:`combined_correlation` uses for the real number, so the null is judged by the same rule
    it must beat. Each draw circularly shifts every region's spike-rate series by its own random
    number of bins (outside a guard band around zero — see :data:`NULL_GUARD_S`), recomputes the
    per-region correlations, combines them, and keeps the absolute value.

    ⭐ **WHY THIS EXISTS.** A correlation's usual significance arithmetic assumes independent
    samples, and these series are anything but: calcium transients smear over many bins, so a
    modest-looking r can be pure autocorrelation luck. Re-scoring the SAME series under clocks
    known to be wrong measures exactly what luck produces here, on this data — and a winner that
    a wrong clock could match is not evidence of anything.
    """
    usable = [(np.asarray(r, dtype=np.float64), np.asarray(c, dtype=np.float64), int(w))
              for r, c, w in pairs
              if w > 0 and min(np.asarray(r).size, np.asarray(c).size) >= 3]
    if not usable:
        return np.zeros(0)
    # ⚠️ One independent stream PER pair (seeded by position), not one shared stream: with a
    # shared one, adding a second region would reshuffle the first region's shifts and move a
    # published chance level for a reason that has nothing to do with the data.
    shifts: list[np.ndarray] = []
    for idx, (rate, calcium, _w) in enumerate(usable):
        rng = np.random.default_rng([seed, idx])
        n = min(rate.size, calcium.size)
        guard = min(max(1, int(round(guard_s / bin_s))), max(1, n // 4))
        if n - 2 * guard >= 1:
            shifts.append(rng.integers(guard, n - guard + 1, size=n_shifts))
        else:
            shifts.append(rng.integers(1, n, size=n_shifts))
    out: list[float] = []
    for j in range(n_shifts):
        parts: list[tuple[float | None, int]] = []
        for (rate, calcium, w), ks in zip(usable, shifts):
            n = min(rate.size, calcium.size)
            parts.append((pearson(np.roll(rate[:n], int(ks[j])), calcium[:n]), w))
        combined = combined_correlation(parts)
        if combined is not None:
            out.append(abs(combined))
    return np.asarray(out, dtype=np.float64)
