"""Loader — log.txt, frames, flat-field, the global tone window, the blank scan.

OWNER: agent 1. Nobody else edits this file.
CONTRACT: app/API.md §4 (session), §5 (pixels), §6 (tone), §9 (the blank scan).

⭐ THE 180-DEGREE FLIP IS VERIFIED (2026-07-12, `load_frame` below). `np.flip(np.flip(raw,1),0)` is
byte-identical BOTH to `analysis/texture/make_texture.py:37` AND to vscope's own display frame
(`vscope.load(xml).ccd["Cc"][0]`), on trials 11, 12, 166, 167, 347. It is a true 180 rotation
(`out[0,0] == raw[-1,-1]`), not a transpose, and it is NOT a no-op — an unflipped read returns
different pixels and would have looked perfectly plausible. Do not "simplify" it.

⛔ THE 26 THROWN-OUT SNAPSHOTS ARE NOT DATA (284-296, 299, 300-310, 348) **ON 260620d**. On that
dataset this module NEVER opens their .dat files, for any purpose — not for the texture scan, not for
the tone sample, not for a thumbnail. See `usable_trials()`.

⭐ AND THE RULING IS SCOPED TO 260620d (the user's ruling #2, 2026-07-12). `analysis/ground_truth/
excluded.py` carries 26 bare trial NUMBERS with **no dataset tag**; applied to any other acquisition
they are 26 perfectly good frames, silently deleted for no reason. So the gate is scoped HERE, at the
loader: `detect_ruling()` decides — from `log.txt`'s `New experiment:` name, falling back to the
directory name — whether the open directory IS 260620d. On 260620d: exactly as before (312 usable,
locked, un-untickable). On anything else: **no hard-coded exclusion at all**, everything loads, and a
warning says so. `analysis/ground_truth/excluded.py` is NOT edited — the benchmark, the 312/312 solve
and `test_mosaic_312.py` all import it and it is 260620d's own file.

⚠️ NO DISK CACHE LIVES HERE. Loading 312 frames costs 0.12 s; a cache would be all risk and no
reward. (And emphatically NOT `mosaic.io.load_frames`'s cache — io.py:23 validates only
`shape[0] == len(trials)`, so two DIFFERENT 312-trial selections silently share an entry.)
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

import cv2
import numpy as np
from PIL import Image

# --- the analysis tree is the engine; the app CALLS it, never forks it ---------------------
_REPO = Path(__file__).resolve().parents[2]          # .../Camea
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from analysis.ground_truth import excluded as _excl   # noqa: E402  THE ruling. One place.

# --- API.md §1.1 — constants that MUST NOT diverge ----------------------------------------
TILE = 512
DOG_LO, DOG_HI = 3, 30
FLAT_SIGMA = 15.0
TONE_PCT_LO, TONE_PCT_HI = 0.5, 99.6
TONE_N_SAMPLE = 96
BLANK_PCT = 2.0

_TRIAL_RE = re.compile(r"^\s*(?:(\d\d)/(\d\d)/(\d\d)\s+)?(\d\d):(\d\d):(\d\d)\s+Trial\s+(\d+):\s*(.+?)\s*$")
_DATE_RE = re.compile(r"^\s*(\d\d)/(\d\d)/(\d\d)\s+(\d\d):(\d\d):(\d\d)\s+New experiment:\s*(\S+)")
_STAMP_RE = re.compile(r"^\s*(?:(\d\d)/(\d\d)/(\d\d)\s+)?(\d\d):(\d\d):(\d\d)\s")

SNAPSHOT = "Snapshot"


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# =============================================================================
# ⭐⭐ THE RULING, AND WHICH DATASET IT BELONGS TO  (the user's ruling #2, 2026-07-12)
# =============================================================================
#: The one acquisition the 26-trial ruling was made about. `analysis/ground_truth/excluded.py` does
#: not record this — it is a bare list of trial NUMBERS — which is exactly the hole this closes.
RULING_DATASET = "260620d"

_EXPERIMENT_RE = re.compile(r"New experiment:\s*(\S+)")


@dataclass(frozen=True)
class Ruling:
    """WHICH EXCLUSION REGIME IS IN FORCE, and how we decided. One object, threaded everywhere.

    ⛔ `applies=True`  -> this IS 260620d. `excluded` is the 26. They are NOT DATA: never loaded,
       never matched, never rendered, never scored. `locked=True` — the UI must not let the user
       un-tick them.
    ✅ `applies=False` -> ANY other acquisition. `excluded` is **empty**. Everything on disk loads.
       The 26 numbers mean nothing here; the blank scan (§9) and the user's eye (`E` in the sweep)
       build this dataset's own exclusion list from scratch. `warning` says so, and the API carries
       it to the front end.
    """
    regime: str                     # "260620d" | "none"
    applies: bool
    dataset: str                    # the dataset the RULING belongs to ("260620d"), always
    excluded: frozenset             # the 26, or empty
    blank: frozenset                # the 11 measured blanks, or empty
    locked: bool                    # may the user un-tick them? (never, on 260620d)
    source: str
    why: str                        # HOW we decided this directory is / is not 260620d
    warning: str | None
    evidence: dict

    def to_json(self) -> dict:
        return {
            "regime": self.regime,
            "applies": self.applies,
            "ruling_dataset": self.dataset,
            "excluded": sorted(self.excluded),
            "n_excluded": len(self.excluded),
            "blank": sorted(self.blank),
            "locked": self.locked,
            "source": self.source,
            "why": self.why,
            "warning": self.warning,
            "evidence": self.evidence,
        }


def log_experiment(log_path: Path) -> str | None:
    """The name on `log.txt`'s `New experiment:` line, or None if there is no such line.

    ⚠️ NOT `parse_log`'s `experiment`, which FALLS BACK to the directory name (loader.py:143). For
    deciding whether a directory is 260620d we must be able to tell "the log says 260620d" from "the
    log says nothing and the folder happens to be called 260620d" — they are different evidence and
    the response reports which one fired.
    """
    try:
        text = Path(log_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = _EXPERIMENT_RE.search(text)
    return m.group(1).strip() if m else None


def detect_ruling(data_dir: Path | None, log_name: str | None = None) -> Ruling:
    """⭐ **IS THIS DIRECTORY 260620d?** Decided FROM THE DATA, and the answer is reported verbatim.

    Evidence, in priority order:
      1. **`log.txt`'s `New experiment:` name.** This is written by the acquisition software and it
         travels with the frames — a copied / renamed / re-exported folder still carries it. It wins.
      2. **The directory name**, used ONLY when the log carries no `New experiment:` line at all
         (a truncated or hand-made log).

    A directory *called* `260620d` whose log says it is some other experiment does **NOT** get the
    ruling: the log is the acquisition's own record of itself, the folder name is a label a human
    typed. That case is reported in `why` rather than silently resolved.

    ⛔ IF IT MATCHES: nothing about 260620d's behaviour changes. 312 usable, the 26 locked.
    ✅ IF IT DOES NOT: `excluded` is EMPTY, everything loads, and `warning` is non-null.
    """
    data_dir = Path(data_dir) if data_dir is not None else None
    dir_name = data_dir.name if data_dir is not None else None
    if log_name is None and data_dir is not None:
        log_name = log_experiment(data_dir / "log.txt")

    dir_hit = dir_name is not None and dir_name.strip().lower() == RULING_DATASET
    log_hit = log_name is not None and log_name.strip().lower() == RULING_DATASET

    if log_name is not None:
        applies = log_hit
        matched_on = "log.txt `New experiment:` line"
    elif dir_name is not None:
        applies = dir_hit
        matched_on = "directory name (log.txt carries no `New experiment:` line)"
    else:
        applies = False
        matched_on = "nothing — no directory and no log to identify the acquisition"

    evidence = {
        "log_experiment": log_name,
        "dir_name": dir_name,
        "matched_on": matched_on,
        "log_says_260620d": log_hit,
        "dir_says_260620d": dir_hit,
    }

    if applies:
        why = (f"this acquisition IS {RULING_DATASET}: identified from the {matched_on} "
               f"(log.txt says {log_name!r}; the directory is named {dir_name!r}). The 26-trial "
               f"ruling of analysis/ground_truth/excluded.py is 260620d's, so it is IN FORCE.")
        warn = None
        if log_hit and dir_name is not None and not dir_hit:
            warn = (f"The directory is named {dir_name!r} but its log.txt says this is "
                    f"{RULING_DATASET}. Trusting the log — these are 260620d's frames, so the "
                    f"26-trial ruling applies.")
        return Ruling(regime="260620d-exclusions", applies=True, dataset=RULING_DATASET,
                      excluded=frozenset(_excl.EXCLUDED), blank=frozenset(_excl.BLANK),
                      locked=True,
                      source="hard-coded ruling (analysis/ground_truth/excluded.py)",
                      why=why, warning=warn, evidence=evidence)

    named = log_name if log_name is not None else dir_name
    why = (f"this acquisition is {named!r}, not {RULING_DATASET} — decided from the {matched_on}. "
           f"The 26-trial exclusion list in analysis/ground_truth/excluded.py is a list of bare "
           f"trial NUMBERS with no dataset tag, and it was made about {RULING_DATASET} only. It is "
           f"NOT applied here.")
    warn = (f"⚠️ EXCLUSION RULING NOT APPLIED. The 26 thrown-out trials "
            f"(284-296, 299, 300-310, 348) are {RULING_DATASET}'s blank and blurry frames — they "
            f"mean nothing in {named!r}, so nothing is being removed from this dataset. Every "
            f"snapshot on disk is loaded. Build this dataset's own exclusion list: the blank scan "
            f"recommends, and you exclude with `E` in the sweep.")
    if dir_hit and not log_hit:
        warn += (f"  (NOTE: this directory is NAMED {RULING_DATASET}, but its log.txt says "
                 f"{log_name!r}. The log is the acquisition's own record and it wins. If the folder "
                 f"name is right and the log is wrong, fix the log — do not assume.)")
    return Ruling(regime="none", applies=False, dataset=RULING_DATASET,
                  excluded=frozenset(), blank=frozenset(), locked=False,
                  source=f"none — no exclusion ruling exists for {named!r}",
                  why=why, warning=warn, evidence=evidence)


# =============================================================================
# log.txt
# =============================================================================
@dataclass
class LogEntry:
    """One `Trial NNN: <type>` line."""
    trial: int
    type: str            # only two appear on 260620d: "Snapshot" and "E'phys. + VSD"
    time: str            # ISO-8601 UTC
    gap_s: float | None  # seconds since the previous SNAPSHOT; None for the first / non-snapshots
    dt: datetime | None = None   # parsed timestamp (not serialised)

    def to_json(self) -> dict:
        return {"trial": self.trial, "type": self.type, "time": self.time, "gap_s": self.gap_s}


def parse_log(log_path: Path) -> tuple[str, list[LogEntry]]:
    """Parse a vscope `log.txt` -> (experiment_name, entries in file order).

        06/20/26 15:46:58 New experiment: 260620d
                 15:47:05 Settings loaded: 250712-mosaic
                 15:47:05 Trial 001: Snapshot
                 ...
                 16:02:44 Trial 011: Snapshot

    ⚠️ THE DATE APPEARS ONLY ON `New experiment:` LINES. Every other line carries `HH:MM:SS` alone.
    We carry the date forward and roll it over whenever the clock goes BACKWARDS by more than a
    minute (a run can cross midnight). Getting this wrong corrupts the pass-split detection, which
    is a *time-gap* rule — a missed rollover would inject a -86,000 s gap.

    `gap_s` is measured between consecutive SNAPSHOT trials only: a 2-minute E'phys trial in the
    middle is not a stage move, and letting it contribute a gap would hand the pass-split rule a
    spurious winner.
    """
    text = Path(log_path).read_text(encoding="utf-8", errors="replace")

    experiment = ""
    day: datetime | None = None      # midnight of the current date
    prev: datetime | None = None     # previous timestamp seen, for rollover detection
    entries: list[LogEntry] = []
    prev_snap: datetime | None = None

    for line in text.splitlines():
        m = _DATE_RE.match(line)
        if m:
            mm, dd, yy, hh, mi, ss = (int(g) for g in m.groups()[:6])
            experiment = experiment or m.group(7)
            day = datetime(2000 + yy, mm, dd)
            prev = day + timedelta(hours=hh, minutes=mi, seconds=ss)
            continue

        st = _STAMP_RE.match(line)
        if not st:
            continue                                    # continuation lines ("Note: ...")
        if st.group(1):                                 # an explicit date on some other line
            mm, dd, yy = (int(g) for g in st.groups()[:3])
            day = datetime(2000 + yy, mm, dd)
        if day is None:
            continue                                    # no date seen yet — cannot time it
        hh, mi, ss = (int(g) for g in st.groups()[3:6])
        dt = day + timedelta(hours=hh, minutes=mi, seconds=ss)
        # midnight rollover: the wall clock went backwards, so the day advanced.
        if prev is not None and dt < prev - timedelta(minutes=1):
            day = day + timedelta(days=1)
            dt = day + timedelta(hours=hh, minutes=mi, seconds=ss)
        prev = dt

        tm = _TRIAL_RE.match(line)
        if not tm:
            continue                                    # "Settings loaded", "Parameter change", ...
        trial, ttype = int(tm.group(7)), tm.group(8)
        gap = None
        if ttype == SNAPSHOT:
            if prev_snap is not None:
                gap = round((dt - prev_snap).total_seconds(), 1)
            prev_snap = dt
        entries.append(LogEntry(trial=trial, type=ttype, time=_iso(dt), gap_s=gap, dt=dt))

    if not experiment:
        experiment = Path(log_path).parent.name
    return experiment, entries


def log_json(experiment: str, entries: list[LogEntry]) -> dict:
    """The `GET /api/session/log` body (API.md §4.4)."""
    n_snap = sum(1 for e in entries if e.type == SNAPSHOT)
    return {
        "experiment": experiment,
        "entries": [e.to_json() for e in entries],
        "n_snapshot": n_snap,
        "n_other": len(entries) - n_snap,
    }


def snapshot_blocks(entries: list[LogEntry]) -> list[tuple[int, int]]:
    """Contiguous runs of `Snapshot` trials, by trial number. On 260620d: [(1,1),(5,7),(11,348)]."""
    snaps = sorted(e.trial for e in entries if e.type == SNAPSHOT)
    blocks: list[tuple[int, int]] = []
    for t in snaps:
        if blocks and t == blocks[-1][1] + 1:
            blocks[-1] = (blocks[-1][0], t)
        else:
            blocks.append((t, t))
    return blocks


def detect_run(entries: list[LogEntry], data_dir: Path | None = None,
               ruling: Ruling | None = None) -> dict:
    """The mosaic run = ⭐ THE LONGEST CONTIGUOUS BLOCK OF `Snapshot` TRIALS. Nothing hard-coded.

    On 260620d there are 342 Snapshot trials in exactly 3 contiguous blocks — (1), (5-7), (11-348)
    — and this rule yields **11-348 (338 trials)**, which is exactly right. 338 - 26 excluded = 312.

    Returns the `run` block of `GET /api/session`:
        {"lo", "hi", "trials", "n", "n_in_range", "detected", "why", "blocks",
         "dropped", "n_dropped", "warnings"}
    where `trials` is `usable_trials(data_dir, lo, hi, ruling)` — already free of every non-snapshot,
    of every off-shape snapshot, and (ON 260620d ONLY) of the 26 thrown-out snapshots.

    `ruling=None` -> `detect_ruling(data_dir)`; the caller does not get to forget it.

    ⚠️ Validated on n = 1 dataset. The UI MUST show what was detected and let the user override
    (`PATCH /api/session/run`).
    """
    blocks = snapshot_blocks(entries)
    if not blocks:
        raise ValueError("log.txt contains no Snapshot trials")
    lo, hi = max(blocks, key=lambda b: b[1] - b[0])          # ties -> the first (earliest) block
    shown = ", ".join(f"{a}" if a == b else f"{a}-{b}" for a, b in blocks)
    why = (f"longest contiguous block of Snapshot trials "
           f"({len(blocks)} block{'s' if len(blocks) != 1 else ''} found: {shown})")
    return _run_block(data_dir, lo, hi, detected=True, why=why, blocks=[list(b) for b in blocks],
                      ruling=ruling)


def _run_block(data_dir: Path | None, lo: int, hi: int, *, detected: bool,
               why: str, blocks: list[list[int]], ruling: Ruling | None = None) -> dict:
    if ruling is None:
        ruling = detect_ruling(data_dir)
    part = partition_trials(data_dir, lo, hi, ruling)
    trials = part["trials"]
    n_in_range = hi - lo + 1
    return {"lo": lo, "hi": hi, "trials": trials, "n": len(trials), "n_in_range": n_in_range,
            "detected": detected, "why": why, "blocks": blocks,
            # --- ADDED (API.md §4.2 keeps every field above; these are new) -------------------
            #: everything in [lo, hi] that did NOT make it into `trials`, and WHY. The front end
            #: must be able to say why trial 284 (or trial 021 of the sibling `260620`) is missing.
            "dropped": part["dropped"],
            "n_dropped": sum(len(v) for v in part["dropped"].values()),
            "warnings": part["warnings"],
            "regime": ruling.regime}


def detect_pass_split(entries: list[LogEntry], lo: int, hi: int,
                      usable: list[int] | None = None) -> dict:
    """⭐ `pass_split` (the LAST TRIAL OF PASS 1) = the trial before the largest INTERIOR
    inter-snapshot time gap — IGNORING THE BLOCK'S FIRST STEP.

    260620d is two serpentine scans of the same tissue. Median snapshot-to-snapshot gap is **2 s**;
    **166 -> 167 is 20 s** — the stage driving back to the origin to start pass 2. So t33's
    `pass_split`, which the method itself cannot measure and which nothing in the repo reads from
    XML, is MEASURABLE from the timestamps.

    ⚠️ THE GOTCHA THAT MAKES A NAIVE MAX-GAP RULE A COIN-FLIP: **11 -> 12 is ALSO 20.0 s** (settling
    right after `Settings loaded`) — it TIES the true boundary exactly, and on a tie a naive argmax
    takes the FIRST one and silently returns pass_split = 11.

    ⚠️⚠️ AND THE SPEC UNDERSTATES IT. PLAN.md and API.md say "the next-largest interior gap is only
    8 s" (API.md's example: `runner_up = {after_trial: 233, gap_s: 8.0}`). **MEASURED, THAT IS
    WRONG.** Dropping only the first step leaves **13 -> 14 at 13.0 s** (step #2 — still settling)
    as the runner-up, which is a mere 1.54x below the winner. The full measured distribution over
    the 337 steps of 11-348: median 2.0 s, 99th pct 8.0 s, and the only gaps above 8 s are
    11->12 (20.0, step #0), 13->14 (13.0, step #2) and 166->167 (20.0, step #155).

    ⇒ SO THE RULE HERE IS PHYSICAL, NOT A HACK ON THE FIRST STEP. A pass boundary is the stage
    driving all the way back to the origin to re-scan **the same tissue** — so it must (a) be far
    larger than any within-scan step, and (b) SPLIT THE RUN INTO TWO SUBSTANTIAL HALVES. Candidates
    are therefore restricted to steps with at least `MIN_SIDE_FRAC` of the trials on each side.
    That guard excludes the whole settling prefix — 11->12 AND 13->14 — for a reason, instead of by
    special case, and it leaves the true runner-up at 234->235 = 8.0 s: a clean **2.5x** margin.
    (The block's first step is ALSO dropped explicitly, belt-and-braces, because the spec says so.)

    ⚠️ `value` is the LAST TRIAL OF PASS 1 (166 on 260620d), because t33 hard-partitions on
    `t <= cfg.pass_split`. The *boundary* is 166->167; the *value* is 166. DO NOT PASS 167 TO t33.

    ⚠️ Validated on n = 1 dataset. Always a PROPOSAL; always overridable.

    `usable` — the run's ACTUAL trial list (`run["trials"]`), used only to count `n_pass1`/`n_pass2`.
    Pass it. Omitting it counts every snapshot in range, including ones the gate dropped.

    Returns the `pass_split` block of `GET /api/session`:
        {"value", "detected", "why", "gap_s", "median_gap_s", "runner_up", "n_pass1", "n_pass2",
         "decisive"}
    """
    MIN_SIDE_FRAC = 0.20      # each pass must hold >= 20 % of the run's steps

    # Snapshot trials inside the run, in acquisition order, with their timestamps.
    # ⚠️ Trials the gate dropped (the 26 on 260620d; an off-shape frame anywhere) ARE included here:
    # they are still acquisition EVENTS, and this is a rule about when the STAGE moved. Dropping
    # them would fabricate multi-step gaps.
    snaps = [e for e in entries if e.type == SNAPSHOT and lo <= e.trial <= hi and e.dt is not None]
    snaps.sort(key=lambda e: e.trial)

    steps = [(a.trial, round((b.dt - a.dt).total_seconds(), 1))
             for a, b in zip(snaps, snaps[1:])]                # (after_trial, gap_s)
    median_gap = float(np.median([g for _, g in steps])) if steps else 0.0

    # the candidate window: drop the block's first step, and require a substantial pass on each side
    m = max(1, int(round(MIN_SIDE_FRAC * len(steps))))
    interior = [s for i, s in enumerate(steps) if i >= max(1, m) and i < len(steps) - m]

    if not interior:
        return {"value": None, "detected": False,
                "why": (f"only {len(steps)} inter-trial steps in the run — too few to place a pass "
                        f"boundary with {MIN_SIDE_FRAC:.0%} of the run on each side. "
                        f"Assuming a SINGLE pass; override if that is wrong."),
                "gap_s": None, "median_gap_s": median_gap, "runner_up": None,
                "n_pass1": 0, "n_pass2": 0, "decisive": False}

    ranked = sorted(interior, key=lambda s: -s[1])
    after, gap = ranked[0]
    runner = ranked[1] if len(ranked) > 1 else None
    first_after, first_gap = steps[0]

    decisive = gap > 2.0 * median_gap and (runner is None or gap >= 2.0 * runner[1])
    why = (f"largest interior inter-trial gap: {after}->{after + 1} is {gap:g} s "
           f"(median {median_gap:g} s). Candidates are restricted to steps with >= "
           f"{MIN_SIDE_FRAC:.0%} of the run on each side, which excludes the settling prefix — "
           f"the block's first step ({first_after}->{first_after + 1}) is also {first_gap:g} s and "
           f"would tie a naive max-gap rule")
    if not decisive:
        why += (f". ⚠️ NOT DECISIVE — the runner-up "
                f"({runner[0]}->{runner[0] + 1}, {runner[1]:g} s) is within 2x of the winner. "
                f"This rule is validated on n=1 dataset. CHECK IT AND OVERRIDE IF WRONG.")

    # ⭐ counted over the run's ACTUAL trial list — NOT over `_excl.EXCLUDED`, which is 260620d's.
    keep = [e.trial for e in snaps] if usable is None else list(usable)
    n1 = sum(1 for t in keep if t <= after)
    n2 = sum(1 for t in keep if t > after)
    return {"value": after, "detected": True, "why": why, "gap_s": gap,
            "median_gap_s": median_gap,
            "runner_up": ({"after_trial": runner[0], "gap_s": runner[1]} if runner else None),
            "n_pass1": n1, "n_pass2": n2, "decisive": decisive}


# =============================================================================
# Frames — the numpy reader. vscope is DROPPED (native byte order; "<u2" is strictly safer,
# 4x faster, and dropping it deletes cairo + salpa + ppersist + physfit from the installer).
# =============================================================================
def read_trial_meta(xml_path: Path) -> dict | None:
    """Parse a trial's XML -> its metadata, or None if it is not a genuine 1-frame snapshot.

    Lifted from `utils/artifact/build_page.py:80`. Returns:
        {"trial", "time", "w", "h", "bytes", "dtype", "flip_x", "flip_y"}

    ⚠️ SHAPE IS PER-TRIAL, NOT PER-DIRECTORY. Sibling dir `260620` trial 021 is a genuine
    `type="snapshot" frames="1"` at parpix=128 (131,072 bytes). Inferring the shape from the file
    size would crash on it. **Parse the XML.** And trial 008 is a 2-frame "snapshot" — reject
    anything with `frames != 1`.
    """
    try:
        root = ElementTree.parse(xml_path).getroot()
    except (ElementTree.ParseError, OSError):
        return None
    info, ccd = root.find("info"), root.find("ccd")
    if info is None or ccd is None or info.get("type") != "snapshot":
        return None
    cam = ccd.find("camera")
    if cam is None or int(cam.get("frames", 1)) != 1:
        return None                                   # trial 008 is a 2-frame "snapshot"
    xf = cam.find("transform")
    # <info date="260620" time="160244"> -> 2026-06-20T16:02:44Z
    d, t = info.get("date", ""), info.get("time", "")
    iso = ""
    if len(d) == 6 and len(t) == 6:
        iso = f"20{d[0:2]}-{d[2:4]}-{d[4:6]}T{t[0:2]}:{t[2:4]}:{t[4:6]}Z"
    return {
        "trial": int(info.get("trial")),
        "time": iso,
        "w": int(cam.get("serpix")), "h": int(cam.get("parpix")),
        "bytes": int(cam.get("typebytes")), "dtype": cam.get("type"),
        "flip_x": xf is not None and int(xf.get("ax", 1)) < 0,
        "flip_y": xf is not None and int(xf.get("ay", 1)) < 0,
    }


def list_snapshots(data_dir: Path) -> dict[int, dict]:
    """{trial: meta} for every genuine 1-frame snapshot on disk whose .dat size matches its XML.

    ⛔ The 26 thrown-out trials are DELIBERATELY still listed here — this is a raw disk inventory,
    and `usable_trials()` is the gate. Nothing downstream of that gate ever sees them.
    """
    out: dict[int, dict] = {}
    for xml_path in sorted(Path(data_dir).glob("[0-9][0-9][0-9].xml")):
        dat = xml_path.with_name(xml_path.stem + "-ccd.dat")
        if not dat.exists():
            continue
        meta = read_trial_meta(xml_path)
        if meta is None:
            continue
        if dat.stat().st_size != meta["w"] * meta["h"] * meta["bytes"]:
            continue                                  # movies (375 frames) fail here
        meta["dat"] = dat
        out[meta["trial"]] = meta
    return out


def partition_trials(data_dir: Path | None, lo: int, hi: int,
                     ruling: Ruling | None = None) -> dict:
    """⛔ THE GATE, with its reasons. Splits `lo..hi` into what loads and what does not, and why.

        {"trials": [...],                       # what the app will actually open
         "dropped": {"ruling": [...],           # ON 260620d ONLY: the 26. NOT DATA.
                     "off_shape": [{...}],      # a real snapshot, but not 512x512 -> unusable HERE
                     "not_snapshot": [...]},    # no .dat, a movie, a 2-frame "snapshot", bad XML
         "warnings": [str, ...]}

    ⭐ THE RULING IS SCOPED. `_excl.EXCLUDED` is 26 bare trial NUMBERS, made about **260620d**. This
    gate applies it **iff `ruling.applies`** — i.e. iff `detect_ruling()` says this directory IS
    260620d. On every other acquisition `ruling.excluded` is EMPTY and nothing is removed by number.
    (`analysis/ground_truth/excluded.py :: usable_trials` is the canonical rule for 260620d, but it
    hard-codes `DATA_DIR` (excluded.py:32) and a 512x512 shape (excluded.py:53), so it cannot be
    used against an arbitrary directory at all. `_selftest` ASSERTS the two agree exactly on
    260620d — 156 / 156 / 312.)

    ⚠️ **SHAPE IS PER-TRIAL, NOT PER-DIRECTORY** (RECON:128). The sibling directory `260620` has
    trial 021 as a genuine `type="snapshot" frames="1"` at **parpix=128** — 512x128, 131,072 bytes.
    It is real data; it just cannot be a 512x512 mosaic tile (t33.TILE, t27.H/W and every ground
    truth hard-code 512). So it is DROPPED HERE, LOUDLY, by shape read from its own XML — never
    silently mis-read as 512x512, and never allowed to reach `load_frames`, which would raise.
    ⚠️ Dropping it opens an acquisition GAP (20 -> 22): `gaps()` recomputes, as it must.
    """
    if ruling is None:
        ruling = detect_ruling(data_dir)

    rng = list(range(lo, hi + 1))
    banned = [t for t in rng if t in ruling.excluded]

    if data_dir is None:                       # no disk: the ruling is all we can apply
        return {"trials": [t for t in rng if t not in ruling.excluded],
                "dropped": {"ruling": banned, "off_shape": [], "not_snapshot": []},
                "warnings": ([ruling.warning] if ruling.warning else [])}

    snaps = list_snapshots(data_dir)
    trials, off_shape, not_snap = [], [], []
    for t in rng:
        if t in ruling.excluded:
            continue                           # ⛔ NOT DATA. Never opened.
        m = snaps.get(t)
        if m is None:
            not_snap.append(t)
        elif (m["h"], m["w"]) != (TILE, TILE):
            off_shape.append({"trial": t, "w": m["w"], "h": m["h"],
                              "reason": f"{m['w']}x{m['h']}, not {TILE}x{TILE}"})
        else:
            trials.append(t)

    warnings: list[str] = []
    if ruling.warning:
        warnings.append(ruling.warning)
    if off_shape:
        shown = ", ".join(f"{d['trial']} ({d['w']}x{d['h']})" for d in off_shape)
        warnings.append(
            f"⚠️ {len(off_shape)} trial(s) in {lo}-{hi} are genuine snapshots but are NOT "
            f"{TILE}x{TILE} and cannot be mosaic tiles: {shown}. Their shape was read from their "
            f"own XML (shape is per-trial, not per-directory) and they are dropped from the run — "
            f"NOT mis-read as {TILE}x{TILE}. This opens an acquisition gap; `gaps` reflects it.")
    return {"trials": trials,
            "dropped": {"ruling": banned, "off_shape": off_shape, "not_snapshot": not_snap},
            "warnings": warnings}


def usable_trials(data_dir: Path | None, lo: int, hi: int,
                  ruling: Ruling | None = None) -> list[int]:
    """⛔ THE GATE. `partition_trials(...)["trials"]` — see it for the whole story.

    On 260620d: `== analysis/ground_truth/excluded.py :: usable_trials(lo, hi)`, exactly (asserted).
    On anything else: every genuine 512x512 snapshot in range, with **NO** hard-coded exclusion.
    """
    return partition_trials(data_dir, lo, hi, ruling)["trials"]


def gaps(trials: list[int]) -> list[list[int]]:
    """Consecutive pairs in `trials` that are NOT one acquisition step apart. On 11-348:
    [[283,297],[298,311]].

    ⚠️ THE SERPENTINE ONE-AXIS STEP PRIOR DOES NOT HOLD ACROSS THESE. Any change to the trial
    selection or the excluded set MUST recompute this, or a multi-step stage jump is treated as one
    step and the whole tail is silently placed wrong.
    """
    return [[a, b] for a, b in _excl.gaps(list(trials))]


def load_frame(meta: dict) -> np.ndarray:
    """One raw .dat -> float32 (h, w) in vscope's DISPLAY orientation. THE reader.

    ⭐⭐ THE 180-DEGREE FLIP IS LOAD-BEARING, AND IT IS VERIFIED (see the module docstring):
    byte-identical to make_texture.py AND to vscope itself. XML `ax=-1, ay=-1` => the display frame
    is the raw array **rotated 180 degrees**. Every existing position, every SWIM dx/dy, and ALL
    THREE GROUND TRUTHS live in this flipped frame. Get it wrong and the app is 180 out from every
    prior result — **and it will look plausible.**
    """
    if meta["dtype"] != "uint16" or meta["bytes"] != 2:
        raise ValueError(f"trial {meta['trial']}: unsupported pixel type "
                         f"{meta['dtype']}/{meta['bytes']}B (only little-endian uint16 is read)")
    raw = np.fromfile(meta["dat"], dtype="<u2")
    want = meta["h"] * meta["w"]
    if raw.size != want:
        raise ValueError(f"trial {meta['trial']}: {meta['dat'].name} has {raw.size} px, "
                         f"XML says {meta['h']}x{meta['w']} = {want}")
    raw = raw.reshape(meta["h"], meta["w"])
    if meta["flip_x"]:
        raw = np.flip(raw, 1)
    if meta["flip_y"]:
        raw = np.flip(raw, 0)
    return np.ascontiguousarray(raw, dtype=np.float32)


def load_frames(data_dir: Path, trials: list[int], progress=None,
                ruling: Ruling | None = None) -> np.ndarray:
    """The stack: float32 (N, 512, 512), flipped, raw camera counts. Row i IS trial `trials[i]`.

    **312 frames in ~0.12 s** (0.37 ms/frame, warm cache). Loading is not the bottleneck; it is not
    optimised and it is NOT cached to disk.

    RAM: 1 frame float32 = exactly 1.00 MiB; 312 = **312 MiB**. Peak is 2-3x — the band-pass
    allocates a full second copy (>= 624 MiB). Budget ~1 GB host RAM.

    ⛔ BELT AND BRACES: **on 260620d** this function REFUSES to open one of the 26, whoever asks and
    whatever list they hand it. `ruling=None` -> `detect_ruling(data_dir)`, so the guard still fires
    for callers that do not know the ruling exists (`engine.py:1335` — the build child process — is
    one, and it must keep working unchanged). On any other acquisition there is nothing to refuse.
    """
    if ruling is None:
        ruling = detect_ruling(data_dir)
    snaps = list_snapshots(data_dir)
    missing = [t for t in trials if t not in snaps]
    if missing:
        raise ValueError(f"not snapshots in {data_dir}: {missing[:10]}")
    banned = [t for t in trials if t in ruling.excluded]
    if banned:      # ⛔ on 260620d these are NOT DATA. Never opened, for any purpose.
        raise ValueError(f"⛔ refusing to load thrown-out snapshots of {ruling.dataset}: {banned}")

    out = np.empty((len(trials), TILE, TILE), np.float32)
    for i, t in enumerate(trials):
        m = snaps[t]
        if (m["h"], m["w"]) != (TILE, TILE):
            # ⚠️ SHAPE IS PER-TRIAL (RECON:128 — sibling `260620` trial 021 is 512x128). The gate
            # (`partition_trials`) already drops these; reaching here means somebody bypassed it, so
            # FAIL LOUDLY rather than reshape 131,072 bytes into a 512x512 lie.
            raise ValueError(
                f"trial {t} is {m['w']}x{m['h']} ({m['dat'].name}, "
                f"{m['w'] * m['h'] * m['bytes']} bytes), not {TILE}x{TILE}. This app is "
                f"{TILE}x{TILE} only (t33.TILE, t27.H/W and every ground truth hard-code it). "
                f"Shape is PER-TRIAL, read from that trial's own XML — it was not inferred and it "
                f"was not mis-read. Drop this trial from the run (the loader's gate already does) "
                f"or narrow the run range.")
        out[i] = load_frame(m)
        if progress and (i % 32 == 0):
            progress(i, len(trials))
    return out


# =============================================================================
# Flat-field + THE GLOBAL TONE WINDOW
# =============================================================================
@dataclass
class Tone:
    """The GLOBAL tone window (API.md §6). `version` increments on every change so the front end
    can bust its tile-bitmap cache via `?v=`."""
    lo: float
    hi: float
    level: float
    flat_sigma: float = FLAT_SIGMA
    pct_lo: float = TONE_PCT_LO
    pct_hi: float = TONE_PCT_HI
    n_sample: int = TONE_N_SAMPLE
    auto: bool = True
    version: int = 1

    def to_json(self) -> dict:
        return {"lo": round(float(self.lo), 2), "hi": round(float(self.hi), 2),
                "level": round(float(self.level), 2), "flat_sigma": float(self.flat_sigma),
                "pct_lo": float(self.pct_lo), "pct_hi": float(self.pct_hi),
                "n_sample": int(self.n_sample), "auto": bool(self.auto),
                "version": int(self.version)}


def compute_flat(frames: np.ndarray, sigma: float = FLAT_SIGMA) -> np.ndarray:
    """The vignette: normalised Gaussian(sigma=15) of the per-pixel median. build_page.py:134."""
    flat = np.median(np.asarray(frames, np.float32), axis=0)
    flat = cv2.GaussianBlur(flat, (0, 0), float(sigma))
    return (flat / float(flat.mean())).astype(np.float32)


def flat_correct(frame: np.ndarray, flat_n: np.ndarray, level: float) -> np.ndarray:
    """build_page.py:140, verbatim. `frame / flat_n`, renormalised to the common `level`."""
    c = np.asarray(frame, np.float32) / np.maximum(flat_n, 1e-3)
    return c * (level / max(float(np.median(c)), 1e-3))


def compute_tone(data_dir: Path, trials: list[int],
                 frames: np.ndarray | None = None) -> tuple[Tone, np.ndarray]:
    """-> (Tone, flat_n). Sample <= 96 frames EVENLY across `trials`; estimate the vignette and ONE
    window for the whole dataset.

        flat_n = normalise(GaussianBlur(median(sample, axis=0), sigma=15))   # mean 1
        level  = median of the per-frame medians          (exposure varies ~2.4x across the run)
        lo, hi = percentile(flat_corrected_sample, [0.5, 99.6])

    ⚠️⚠️ **TONE-MAP GLOBALLY, NEVER PER-TILE.** A per-tile percentile stretch over-brightens
    near-empty frames and makes overlapping tiles disagree in brightness — **which destroys the
    Difference-mode check the entire verification loop depends on.** There is no per-tile path in
    this module and there must never be one, not even for a thumbnail.

    Tone is DISPLAY ONLY. It never touches the matcher (which works on the band-passed,
    mean-subtracted stack) and never touches the exported TIFF.
    """
    if not trials:
        raise ValueError("compute_tone: no trials")
    step = max(1, len(trials) // TONE_N_SAMPLE)
    idx = list(range(0, len(trials), step))[:TONE_N_SAMPLE]

    if frames is not None:
        sample = frames[idx]
    else:
        sample = load_frames(data_dir, [trials[i] for i in idx])

    flat_n = compute_flat(sample)
    level = float(np.median([np.median(f) for f in sample]))
    corrected = np.stack([flat_correct(f, flat_n, level) for f in sample])
    lo, hi = (float(v) for v in np.percentile(corrected, [TONE_PCT_LO, TONE_PCT_HI]))
    del corrected
    if not math.isfinite(lo) or not math.isfinite(hi) or hi <= lo:
        raise ValueError(f"degenerate tone window [{lo}, {hi}]")
    return Tone(lo=lo, hi=hi, level=level, n_sample=len(idx)), flat_n


def to_u8(frame: np.ndarray, flat_n: np.ndarray, tone: Tone) -> np.ndarray:
    """Flat-field + the GLOBAL window -> uint8 (h, w). Every displayed pixel goes through this: the
    tile PNGs, the thumbnails and the exported display PNG. ONE window for all. build_page.py:520."""
    c = flat_correct(frame, flat_n, tone.level)
    return np.clip((c - tone.lo) * (255.0 / (tone.hi - tone.lo)), 0, 255).astype(np.uint8)


def _png(u8: np.ndarray) -> bytes:
    buf = BytesIO()
    Image.fromarray(np.ascontiguousarray(u8), "L").save(buf, "PNG", optimize=False, compress_level=1)
    return buf.getvalue()


def tile_png(frame: np.ndarray, flat_n: np.ndarray, tone: Tone) -> bytes:
    """-> 8-bit grayscale PNG bytes, 512x512. Served by `GET /api/tile/{trial}.png`."""
    return _png(to_u8(frame, flat_n, tone))


def tile_raw(frame: np.ndarray) -> bytes:
    """-> exactly 524,288 bytes: uint16 LITTLE-ENDIAN, 512x512 row-major, ALREADY FLIPPED, RAW
    camera counts (no flat-field, no tone). Served by `GET /api/tile/{trial}.raw`.

    `frames` are stored float32 but hold integral counts, so the round-trip is exact. Pixel range:
    uint16, but only ~1/20 of the range is used (global max across all 338 snapshots = 18,022 /
    65,535). Saturated fraction is exactly 0.0 in every frame — clipping here can never bite.
    """
    return np.ascontiguousarray(np.clip(frame, 0, 65535).astype("<u2")).tobytes()


def thumb_sheet(frames: np.ndarray, flat_n: np.ndarray, tone: Tone,
                cell: int = 64) -> tuple[bytes, int]:
    """The contact sheet -> (png_bytes, grid). `grid = ceil(sqrt(n))`, row-major in `trials` order.
    Same GLOBAL window — a per-tile stretch here would make the contact sheet lie about which
    frames are dim. Served by `GET /api/thumbs.png`."""
    n = len(frames)
    grid = int(math.ceil(math.sqrt(n))) if n else 1
    rows = int(math.ceil(n / grid)) if n else 1
    sheet = np.zeros((rows * cell, grid * cell), np.uint8)
    for i in range(n):
        small = cv2.resize(to_u8(frames[i], flat_n, tone), (cell, cell),
                           interpolation=cv2.INTER_AREA)
        r, c = divmod(i, grid)
        sheet[r * cell:(r + 1) * cell, c * cell:(c + 1) * cell] = small
    return _png(sheet), grid


# =============================================================================
# THE BLANK SCAN  —  the ONLY thing the app is allowed to be sure about
# =============================================================================
def band_pass(frames: np.ndarray) -> np.ndarray:
    """DoG(3, 30) — identical to `mosaic.quality.band_pass` / `t27.band_pass` (same cv2 calls, same
    order), which is what the matcher consumes, and identical to `make_texture.band_pass`, which is
    what the blank measure consumes. ONE array serves both. Verified bit-identical to both.

    ⚠️ **KEEP OPENCV.** Swapping to `scipy.ndimage.gaussian_filter` shifts the blank metric by
    **0.32 %** against a threshold whose nearest margin is **0.13 %** — it can flip a blank
    classification. Saving 85 MB of installer is not worth a wrong answer.
    """
    f = np.asarray(frames, np.float32)
    if f.ndim == 2:
        return cv2.GaussianBlur(f, (0, 0), DOG_LO) - cv2.GaussianBlur(f, (0, 0), DOG_HI)
    return np.stack([cv2.GaussianBlur(x, (0, 0), DOG_LO) - cv2.GaussianBlur(x, (0, 0), DOG_HI)
                     for x in f]).astype(np.float32)


def texture_map(data_dir: Path, trials: list[int],
                band: np.ndarray | None = None) -> dict[int, float]:
    """{trial: std of DoG(sigma=3, sigma=30) of the FLIPPED frame}. `texture/make_texture.py:47`.

    3.0 s for 342 frames from disk — but if the caller already has the band-passed stack (which
    `open_session` does, because the matcher needs it anyway), this is FREE and bit-identical: the
    texture measure IS `band_pass(frame).std()`, the very same array. Verified equal to the
    precomputed `analysis/texture/260620d_texture.json` on all 312 trials, to the stored 2 dp.

    ⛔ Scans `trials` only. The 26 thrown-out snapshots are never opened.
    """
    if band is not None:
        return {t: round(float(band[i].std()), 2) for i, t in enumerate(trials)}
    snaps = list_snapshots(data_dir)
    return {t: round(float(band_pass(load_frame(snaps[t])).std()), 2)
            for t in trials if t in snaps}


def blank_scan(texture: dict[int, float], pass1_trials: list[int],
               ruling: Ruling | None = None) -> dict:
    """-> the `GET /api/scan/blank` object (API.md §9).

    threshold = the **2nd percentile of PASS-1 texture** (pass 1 is the known-good, fully-solved
    range). On 260620d that recomputes to **60.1136**.

    ❌ **NO SLIDER. NO AUTO-REJECT. NO BLUR JUDGEMENT.** Across all 338 snapshots and 15 focus
    measures the best global blur threshold reaches F1 = 0.37; catching all 15 of the user's blurry
    frames also rejects 62 good ones, best case. **Variance-of-Laplacian scores WORSE THAN CHANCE**
    (it is dominated by sensor noise, identical in sharp and blurry frames). It must never appear in
    the UI. The user meets every tile again in the sweep and excludes it there with `E`.

    ⚠️ ZERO MARGIN AT THE BOUNDARY, and it matters:
        usable 56 = 56.39 < [blank 309 = 56.53] < usable 34 = 58.44 < [blank 289 = 58.54]
        < usable 127 = 58.58 < usable 55 = 59.98 < **[thr 60.11]** < usable 35 = 61.32
    The usable and the blank frames INTERLEAVE below the threshold. So over 11-348 this measure
    proposes the four PASS-1 trials 34, 55, 56, 127 — all of which are usable and all of which are
    correctly placed in the 100 %-solved pass 1. (It cannot propose 289/300-309: those are among the
    26 and are never loaded. `known_blank` reports them as integers so the UI can say why.)

    ⇒ **THE SCAN RECOMMENDS. THE USER TICKS. NOTHING IS AUTO-EXCLUDED.**

    (The `blank` list is also what `engine.match_anchor` REFUSES — API.md §7.3. Refusing is not
    excluding: a blank tile the user keeps stays in the document, it just cannot be machine-matched.)
    """
    p1 = np.array([texture[t] for t in pass1_trials if t in texture], float)
    if len(p1) >= 20:
        thr = float(np.percentile(p1, BLANK_PCT))
        src = f"{BLANK_PCT:g}th percentile of PASS-1 texture (the known-good range, n={len(p1)})"
    else:
        thr = float("nan")
        src = (f"UNDETERMINED — only {len(p1)} pass-1 trials, too few for a {BLANK_PCT:g}th "
               f"percentile. Nothing is proposed as blank.")

    blank = sorted(t for t, v in texture.items() if math.isfinite(thr) and v < thr)

    # How close is the nearest KEPT trial to the threshold? This is the honesty number.
    above = [v for v in texture.values() if math.isfinite(thr) and v >= thr]
    margin_pct = (100.0 * (min(above) - thr) / thr) if above else float("nan")
    warn = (f"The nearest non-blank trial sits {margin_pct:.2f} % above the threshold. "
            f"This measure is reliable for BLANK and USELESS for BLUR — do not read anything into a "
            f"near-threshold value, and never auto-reject on it.")

    # ⛔ 260620d's 11 MEASURED blanks. They live inside its 26 and are never re-loaded, so they are
    # reported as integers only, so the UI can say WHY trial 304 is missing. On ANY OTHER dataset
    # this list is EMPTY — those trial numbers are not that dataset's blanks, and the scan above
    # (which DID open every frame there) is the only blank evidence that exists for it.
    known = sorted(ruling.blank) if ruling is not None else sorted(_excl.BLANK)
    if ruling is not None and not ruling.applies:
        known_src = (f"none — the measured blank list in analysis/ground_truth/excluded.py belongs "
                     f"to {ruling.dataset} and is NOT applied here. Every frame of this dataset was "
                     f"loaded and measured; `blank` above is the whole of what is known.")
    else:
        known_src = ("analysis/ground_truth/excluded.py :: BLANK (measured 2026-07-11; "
                     "these trials are among the 26 thrown out and are never re-loaded)")
    return {
        "threshold": round(thr, 2) if math.isfinite(thr) else None,
        "threshold_source": src,
        "measure": "std of DoG(sigma=3, sigma=30) of the flipped frame",
        "texture": {str(t): v for t, v in sorted(texture.items())},
        "blank": blank,
        # ⭐ WHAT THE MEASURE SAID, PRESERVED FOR EVER. `PUT /api/scan/blank` overwrites `blank` with
        # the list the HUMAN wants the matcher to refuse, so after one overrule the measure's own
        # proposal would otherwise be gone from the session — and the Screen page, which must go on
        # showing every frame it recommended (with its tick state), would silently drop the frames the
        # user just overruled off the screen. `blank` is a DECISION and it moves; `scanned` is a
        # MEASUREMENT and it does not.
        "scanned": list(blank),
        "n_blank": len(blank),
        "n_scanned": len(texture),
        "margin_warning": warn,
        "known_blank": known,
        "n_known_blank": len(known),
        "known_blank_source": known_src,
    }


# =============================================================================
# The session's loaded state
# =============================================================================
@dataclass
class Session:
    """Everything a loaded acquisition directory gives you. Owned by `server.py`; built here.

    ⚠️ THE DOCUMENT (tile states, positions, exclusions, cursor) IS **NOT** IN HERE. The front end
    owns it — it has the undo/redo stack — and posts it whole when the backend needs it (save,
    autosave, export). That is what makes `/api/match/anchor` a pure function of its request body,
    which in turn is what makes the A-branch prefetch correct BY CONSTRUCTION (API.md §7.4).
    """
    data_dir: Path
    dataset: str
    opened_at: str
    run: dict                       # detect_run()'s output
    pass_split: dict                # detect_pass_split()'s output
    gaps: list[list[int]]           # [[283, 297], [298, 311]]
    excluded: dict
    tiles: dict[int, dict]          # per-trial metadata (NOT tile state)
    frames: np.ndarray              # (N, 512, 512) float32, flipped, raw counts
    band: np.ndarray                # (N, 512, 512) float32, DoG(3,30) — THE match input
    flat_n: np.ndarray
    tone: Tone
    texture: dict[int, float]
    blank: dict
    row_of: dict[int, int]          # trial -> row index into frames/band
    experiment: str = ""
    entries: list[LogEntry] = field(default_factory=list)
    project_path: str | None = None

    #: ⭐ WHICH EXCLUSION REGIME IS IN FORCE (the user's ruling #2). `Ruling.applies` is True iff
    #: this directory IS 260620d. Everything that filters by trial number reads it from here.
    ruling: Ruling | None = None
    #: Anything the user MUST see about how this dataset was loaded: the ruling not being applied,
    #: off-shape trials dropped, a folder/log name disagreement. Surfaced at `GET /api/session`.
    warnings: list[str] = field(default_factory=list)

    #: ⭐ A FRESH IDENTITY FOR EVERY OPEN. Two things needed one and were faking it:
    #:   * `engine._token` keyed the composite cache and the match memo on `id(session.band)` —
    #:     and CPython RECYCLES `id()` (measured: 4 of 5 same-size allocations reused an address),
    #:     so two sessions of the same dataset with the same tile count collided.
    #:   * the front end's `?v={tone.version}` cache-buster RESETS TO 1 on every open, while the
    #:     pixels behind that URL change (a narrower run = a different tone window) — and the URL is
    #:     served `Cache-Control: immutable, max-age=1yr`. Same URL, different bytes, cached for a
    #:     year. Open a second acquisition directory and the canvas can show the FIRST one's pixels.
    #: The nonce goes into both, so neither can happen. It is not a secret and it is not stable
    #: across restarts by design.
    nonce: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    # display caches, rebuilt whenever `tone.version` changes. Not part of the API.
    _auto_tone: tuple[float, float] = (0.0, 0.0)     # the lo/hi `auto: true` resets to
    _u8: np.ndarray | None = None                    # (N,512,512) uint8 = 78 MiB
    _u8_version: int = -1
    _thumbs: tuple[bytes, int] | None = None
    _thumbs_version: int = -1

    # --- pixel accessors: the ONLY way anything else gets at a frame -----------------------
    def frame(self, trial: int) -> np.ndarray:
        if trial not in self.row_of:
            raise KeyError(trial)                     # -> 404. Includes all 26 excluded.
        return self.frames[self.row_of[trial]]

    def banded(self, trial: int) -> np.ndarray:
        if trial not in self.row_of:
            raise KeyError(trial)
        return self.band[self.row_of[trial]]

    # --- the display path (API.md §5, §6). Server: call THESE, not the free functions. -----
    def _u8_stack(self) -> np.ndarray:
        """All 312 display tiles, uint8 (78 MiB). Rebuilt ONLY when the tone version changes
        (0.82 s). This is what makes `PUT /api/tone` safe: there is exactly one cache and it is
        keyed on the version the front end also uses as its `?v=` cache-buster, so the two cannot
        drift apart."""
        if self._u8 is None or self._u8_version != self.tone.version:
            self._u8 = np.stack([to_u8(f, self.flat_n, self.tone) for f in self.frames])
            self._u8_version = self.tone.version
            self._thumbs = None                       # the sheet is downsampled from these
        return self._u8

    def tile_png(self, trial: int) -> bytes:
        """`GET /api/tile/{trial}.png` — 8-bit grayscale PNG, 512x512. ~4.5 ms warm.
        KeyError (-> 404) for anything not in `run.trials`, which includes all 26 excluded."""
        if trial not in self.row_of:
            raise KeyError(trial)
        return _png(self._u8_stack()[self.row_of[trial]])

    def tile_raw(self, trial: int) -> bytes:
        """`GET /api/tile/{trial}.raw` — exactly 524,288 bytes, uint16 LE, ALREADY FLIPPED, RAW
        counts. No flat-field, no tone: this is the 16-bit pixel data, not a picture."""
        return tile_raw(self.frame(trial))

    def thumbs(self, cell: int = 64) -> tuple[bytes, int]:
        """`GET /api/thumbs.png` -> (png, grid). Cached on the tone version (1.4 s to rebuild)."""
        if self._thumbs is None or self._thumbs_version != self.tone.version:
            u8 = self._u8_stack()
            n = len(u8)
            grid = int(math.ceil(math.sqrt(n))) if n else 1
            rows = int(math.ceil(n / grid)) if n else 1
            sheet = np.zeros((rows * cell, grid * cell), np.uint8)
            for i in range(n):
                r, c = divmod(i, grid)
                sheet[r * cell:(r + 1) * cell, c * cell:(c + 1) * cell] = cv2.resize(
                    u8[i], (cell, cell), interpolation=cv2.INTER_AREA)
            self._thumbs = (_png(sheet), grid)
            self._thumbs_version = self.tone.version
        return self._thumbs

    def thumbs_json(self, cell: int = 64) -> dict:
        """`GET /api/thumbs.json` — the sprite sheet's index."""
        _, grid = self.thumbs(cell)
        return {"grid": grid, "cell": cell, "trials": self.run["trials"],
                "n": len(self.run["trials"]), "version": self.tone.version}

    def set_tone(self, lo: float | None = None, hi: float | None = None,
                 auto: bool = False) -> Tone:
        """`PUT /api/tone`. Bumps `version`, which invalidates every display cache above.

        ⚠️ GLOBAL ONLY. There is no per-tile path here and there must never be one — a per-tile
        stretch makes overlapping tiles disagree in brightness and destroys Difference mode.
        Tone NEVER touches `band` (the matcher) or `frames` (the exported TIFF).
        """
        if auto:
            new_lo, new_hi = self._auto_tone
            is_auto = True
        else:
            new_lo = float(self.tone.lo if lo is None else lo)
            new_hi = float(self.tone.hi if hi is None else hi)
            is_auto = False
        if not (math.isfinite(new_lo) and math.isfinite(new_hi)) or new_hi <= new_lo:
            raise ValueError(f"bad tone window [{new_lo}, {new_hi}]: hi must exceed lo")
        self.tone = Tone(lo=new_lo, hi=new_hi, level=self.tone.level,
                         flat_sigma=self.tone.flat_sigma, pct_lo=self.tone.pct_lo,
                         pct_hi=self.tone.pct_hi, n_sample=self.tone.n_sample,
                         auto=is_auto, version=self.tone.version + 1)
        return self.tone

    @property
    def frame_note(self) -> str:
        """WHICH PIXEL FRAME THE POSITIONS ARE IN — **read off this acquisition's XML**, not assumed.

        ⚠️ `load_frame` flips CONDITIONALLY (`ax=-1` -> flip x, `ay=-1` -> flip y). That is right: it
        honours the file. But `project.COORDINATES` and the exported TIFF's ImageDescription both
        stated "180-degree-flipped display frame" **UNCONDITIONALLY**. On 260620d all 342 XMLs are
        `ax=-1, ay=-1`, so the two agree and nothing can go wrong today. On an acquisition whose
        `<transform>` is absent or says `ax=+1`, the reader returns an UNFLIPPED frame — the mosaic
        would still be self-consistently correct (matcher, canvas and export all agree) — but every
        exported artefact would carry a **false claim about its own coordinate frame**, on the one
        axis this project has been burned by, in the file most likely to be handed to someone else.
        Metadata, not pixels; and it is derived, not asserted.
        """
        fx = [m["flip_x"] for m in self.tiles.values()]
        fy = [m["flip_y"] for m in self.tiles.values()]
        if not fx:
            return "unknown pixel frame (no tiles loaded)"
        if all(fx) and all(fy):
            return "the vscope-displayed (180deg-flipped: XML ax=-1, ay=-1) frame"
        if not any(fx) and not any(fy):
            return "the RAW sensor frame (this acquisition's XML declares NO flip: ax=+1, ay=+1)"
        if all(fx) and not any(fy):
            return "the horizontally-mirrored frame (XML ax=-1, ay=+1)"
        if all(fy) and not any(fx):
            return "the vertically-mirrored frame (XML ax=+1, ay=-1)"
        return ("a MIXED frame - the trials in this run do not agree on their XML <transform>. "
                "That is not something this app can express in one coordinate note; check the XMLs")

    @property
    def coordinates(self) -> str:
        return ("RELATIVE. Tile TOP-LEFT in px (NOT the centre), measured FROM `origin_trial` at "
                f"(0,0), in {self.frame_note}. Absolute position is meaningless; a scorer must slide "
                "a build onto this with a CONSENSUS translation before measuring.")

    @property
    def store_key(self) -> str:
        """⚠️ THE ON-DISK KEY FOR THIS ACQUISITION — **not** its basename.

        The t33 cache filename already carries the trial-membership hash and the config hash, but
        nothing that identifies the PIXELS: the only thing separating two acquisitions is the cache
        *directory*, which was `<appdata>/cache/<basename>`. Two directories both called `260620d`
        under different parents — a re-export, a copy on another drive, a re-acquisition — share the
        directory, the trial numbers and the config, so they collide on the identical filename, and
        `t33._load_checked` (which only compares the CONFIG) would happily accept the first
        acquisition's layout as a warm build of the second. The autosave file
        (`<basename>.camea.json`) collided the same way, and `project.load`'s guard compares
        `dataset` + `trial_range`, so it could not catch it either.

        So the key is the basename PLUS a hash of the RESOLVED directory. Same folder -> same key ->
        the warm cache still works. Different folder -> different key -> no collision, ever.
        """
        h = hashlib.sha1(str(self.data_dir.resolve()).lower().encode("utf-8")).hexdigest()[:8]
        return f"{self.dataset}-{h}"

    def autosave_path(self) -> str:
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData/Local"))
        return str(base / "Camea" / "autosave" / f"{self.store_key}.camea.json").replace("\\", "/")

    def to_json(self) -> dict:
        """The `GET /api/session` body (API.md §4.2). Never includes pixels.

        `gpu` and `build` are filled in by server.py (they are not the loader's business).

        ⭐ ADDED, never removed (API.md §4.2's shape is intact): **`ruling`** — which exclusion
        regime is in force and how it was decided — and **`warnings`**, the list the header must
        show. `excluded` keeps its four documented keys and gains `regime` / `applies` / `warning`,
        so a front end that only knows the old contract still works and one that knows the new one
        can say "no ruling applies to this dataset".
        """
        return {
            "data_dir": str(self.data_dir).replace("\\", "/"),
            # ⚠️ `dataset` is the DIRECTORY NAME — a label a human typed. It is what the UI shows and
            # what export basenames are built from. It is NOT the acquisition's identity, and nothing
            # may decide the 26-snapshot ruling from it: a restored backup called `260620d` whose
            # log says otherwise, or the real 260620d opened through a junction called `mosaic_work`,
            # both make it lie. `experiment` (below) is the acquisition's own record of itself, and
            # it is what `detect_ruling()` decides on. The document carries BOTH.
            "dataset": self.dataset,
            #: ⭐ `log.txt`'s `New experiment:` name (falling back to the directory name only when the
            #: log has no such line). THE ACQUISITION'S IDENTITY. Travels with the frames.
            "experiment": self.experiment,
            "opened_at": self.opened_at,
            #: the front end's cache-buster is `?v={nonce}.{tone.version}` — see `Session.nonce`.
            "nonce": self.nonce,
            "run": self.run,
            "pass_split": self.pass_split,
            "gaps": self.gaps,
            "excluded": self.excluded,
            # ⭐ WHICH REGIME IS IN FORCE — the front end shows this, and it must.
            "ruling": self.ruling.to_json() if self.ruling is not None else None,
            "warnings": list(self.warnings),
            "tiles": {str(t): m for t, m in sorted(self.tiles.items())},
            "tone": self.tone.to_json(),
            # DERIVED FROM THIS ACQUISITION'S XML — see `frame_note`. Everything that writes a
            # coordinate note (the project file, the GT JSON, the TIFF header) reads it from here
            # rather than hard-coding "180-degree-flipped".
            "frame_note": self.frame_note,
            "coordinates": self.coordinates,
            "blank": self.blank,
            "gpu": {},
            "build": None,
            "project_path": self.project_path,
            "autosave_path": self.autosave_path(),
        }


_OPEN_PHASES = ["scan_dir", "parse_log", "load_frames", "flat_field", "tone", "texture", "done"]


def _reporter(report):
    """Adapt to jobs.Progress without hard-importing jobs.py (agent 2 owns it)."""
    def emit(phase: str, pct: float, message: str = "") -> None:
        if report is None:
            return
        i = _OPEN_PHASES.index(phase) + 1
        try:
            from .jobs import Progress                     # type: ignore
            report(Progress(phase=phase, phase_index=i, n_phases=len(_OPEN_PHASES),
                            pct=float(pct), message=message))
        except Exception:
            report({"phase": phase, "phase_index": i, "n_phases": len(_OPEN_PHASES),
                    "pct": float(pct), "message": message})
    return emit


class Cancelled(Exception):
    """The open job saw its cancel event."""


def open_session(data_dir: Path, report=None, cancel=None,
                 lo: int | None = None, hi: int | None = None,
                 pass_split: int | None = None) -> Session:
    """The `open` job. Phases: scan_dir -> parse_log -> load_frames -> flat_field -> tone ->
    texture -> done. 2-6 s.

    `lo`/`hi`/`pass_split` override the detection (`PATCH /api/session/run`); None = detect.

    ⚠️ `band = band_pass(frames)` allocates a full second copy of the stack (624 MiB at n=312). It
    is done ONCE, here, and handed to the engine — never per match. The texture scan then rides on
    it for free (the blank measure IS that array's per-frame std), which is why `open` is ~5 s and
    not ~8 s.
    """
    emit = _reporter(report)

    def check():
        if cancel is not None and cancel.is_set():
            raise Cancelled()

    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        raise FileNotFoundError(f"no such directory: {data_dir}")

    # --- scan_dir -------------------------------------------------------------------------
    emit("scan_dir", 0.0, f"scanning {data_dir.name}")
    snaps = list_snapshots(data_dir)
    if not snaps:
        raise ValueError(f"no 1-frame snapshots found in {data_dir}")
    check()

    # --- parse_log ------------------------------------------------------------------------
    emit("parse_log", 0.0, "parsing log.txt")
    log_path = data_dir / "log.txt"
    if not log_path.exists():
        raise FileNotFoundError(f"no log.txt in {data_dir} — the run cannot be detected without it")
    experiment, entries = parse_log(log_path)

    # ⭐⭐ WHICH DATASET IS THIS? Decided from the data (log.txt's `New experiment:` name, else the
    # directory name) — and it decides whether the 26-trial ruling is in force AT ALL. On 260620d:
    # exactly as before. On anything else: nothing is removed by trial number, and `ruling.warning`
    # says so, loudly, all the way out to `GET /api/session`.
    ruling = detect_ruling(data_dir, log_name=log_experiment(log_path))

    if lo is None or hi is None:
        run = detect_run(entries, data_dir, ruling=ruling)
    else:
        run = _run_block(data_dir, lo, hi, detected=False,
                         why=f"user override: trials {lo}-{hi}",
                         blocks=[list(b) for b in snapshot_blocks(entries)], ruling=ruling)
    if not run["trials"]:
        raise ValueError(f"no usable snapshots in trials {run['lo']}-{run['hi']}")

    ps = detect_pass_split(entries, run["lo"], run["hi"], usable=run["trials"])
    if pass_split is not None:
        n1 = sum(1 for t in run["trials"] if t <= pass_split)
        ps = {**ps, "value": pass_split, "detected": False,
              "why": f"user override: pass 1 ends at trial {pass_split}",
              "n_pass1": n1, "n_pass2": len(run["trials"]) - n1}
    check()

    trials = run["trials"]
    split = ps["value"] if ps["value"] is not None else run["hi"]
    pass1 = [t for t in trials if t <= split]

    # --- load_frames ----------------------------------------------------------------------
    emit("load_frames", 0.0, f"loading {len(trials)} frames")
    frames = load_frames(data_dir, trials, ruling=ruling,
                         progress=lambda i, n: (check(), emit("load_frames", 100.0 * i / n,
                                                              f"loaded {i}/{n} frames")))
    row_of = {t: i for i, t in enumerate(trials)}
    check()

    # --- flat_field + tone ----------------------------------------------------------------
    emit("flat_field", 0.0, "estimating the vignette")
    tone, flat_n = compute_tone(data_dir, trials, frames=frames)
    emit("tone", 100.0, f"global window [{tone.lo:.0f}, {tone.hi:.0f}]")
    check()

    # --- texture (rides on the band-passed stack the matcher needs anyway) -----------------
    emit("texture", 0.0, "band-passing the stack")
    band = band_pass(frames)
    check()
    texture = texture_map(data_dir, trials, band=band)
    blank = blank_scan(texture, pass1, ruling=ruling)
    emit("texture", 100.0, f"{blank['n_blank']} blank of {len(trials)} scanned")

    # --- assemble -------------------------------------------------------------------------
    tiles: dict[int, dict] = {}
    for t in trials:
        m = snaps[t]
        tiles[t] = {
            "trial": t, "time": m["time"],
            "pass": 1 if t <= split else 2,
            "w": m["w"], "h": m["h"], "bytes": m["bytes"], "dtype": m["dtype"],
            "flip_x": m["flip_x"], "flip_y": m["flip_y"],
            "texture": texture.get(t),
            "blank": t in blank["blank"],
            "dat": m["dat"].name,
        }

    # ⛔ `excluded` = what the RULING removed, and it is empty unless this dataset IS 260620d.
    # API.md §4.2's four keys (trials / n / source / locked) are all still here; `regime`,
    # `applies`, `warning` and `off_shape` are ADDED so the front end can explain itself.
    excl_in_range = sorted(t for t in range(run["lo"], run["hi"] + 1) if t in ruling.excluded)
    warnings = list(run["warnings"])
    sess = Session(
        data_dir=data_dir, dataset=data_dir.name,
        opened_at=_iso(datetime.now(timezone.utc)),
        run=run, pass_split=ps, gaps=gaps(trials),
        excluded={"trials": excl_in_range, "n": len(excl_in_range),
                  "source": ruling.source,
                  "locked": ruling.locked,
                  "regime": ruling.regime,
                  "applies": ruling.applies,
                  "why": ruling.why,
                  "warning": ruling.warning,
                  # genuine snapshots that are not 512x512 — dropped by SHAPE, not by the ruling.
                  "off_shape": run["dropped"]["off_shape"]},
        ruling=ruling, warnings=warnings,
        tiles=tiles, frames=frames, band=band, flat_n=flat_n, tone=tone,
        texture=texture, blank=blank, row_of=row_of,
        experiment=experiment, entries=entries,
        _auto_tone=(tone.lo, tone.hi),          # what `PUT /api/tone {"auto": true}` restores
    )
    emit("done", 100.0, f"{len(trials)} tiles ready")
    return sess


# =============================================================================
# Self-test — RUN IT. `conda run -n camea python -s app/backend/loader.py`
# =============================================================================
def _selftest() -> int:
    import time
    D = _REPO / "data/drive/260620/260620_Imaging/260620d"
    fails: list[str] = []

    def ck(name, got, want):
        ok = got == want
        print(f"  [{'ok ' if ok else 'FAIL'}] {name}: {got!r}" + ("" if ok else f"  want {want!r}"))
        if not ok:
            fails.append(name)

    # --- 0. THE FLIP. Everything downstream is wrong if this is wrong. --------------------
    print("\n0. the 180-degree flip (vs make_texture AND vs vscope)")
    meta = read_trial_meta(D / "011.xml")
    meta["dat"] = D / "011-ccd.dat"
    f = load_frame(meta)
    raw = np.fromfile(meta["dat"], "<u2").reshape(512, 512).astype(np.float32)
    ck("== np.flip(np.flip(raw,1),0)", bool(np.array_equal(f, np.flip(np.flip(raw, 1), 0))), True)
    ck("== rot90(raw, 2)", bool(np.array_equal(f, np.rot90(raw, 2))), True)
    ck("flip is not a no-op", bool(not np.array_equal(f, raw)), True)
    ck("dtype/shape", (str(f.dtype), f.shape), ("float32", (512, 512)))
    try:
        import vscope  # noqa
        v = vscope.load(str(D / "011.xml")).ccd["Cc"][0]
        ck("== vscope display frame", bool(np.array_equal(f, v.astype(np.float32))), True)
    except Exception as e:                                   # vscope is optional; we dropped it
        print(f"  [skip] vscope cross-check unavailable: {e}")

    # --- 1. the log ------------------------------------------------------------------------
    print("\n1. log.txt")
    exp, entries = parse_log(D / "log.txt")
    ck("experiment", exp, "260620d")
    ck("n_snapshot", sum(1 for e in entries if e.type == SNAPSHOT), 342)
    ck("trial types", sorted({e.type for e in entries}), ["E'phys. + VSD", "Snapshot"])
    ck("trial 11 time", next(e.time for e in entries if e.trial == 11), "2026-06-20T16:02:44Z")
    ck("blocks", snapshot_blocks(entries), [(1, 1), (5, 7), (11, 348)])

    # --- 2. the run ------------------------------------------------------------------------
    print("\n2. detect_run — the LONGEST CONTIGUOUS BLOCK of Snapshot trials")
    run = detect_run(entries, D)
    ck("lo, hi", (run["lo"], run["hi"]), (11, 348))
    ck("n_in_range", run["n_in_range"], 338)
    ck("n usable", run["n"], 312)
    ck("gate == excluded.usable_trials(11,348)",
       run["trials"] == _excl.usable_trials(11, 348), True)
    ck("no thrown-out trial survived", [t for t in run["trials"] if t in _excl.EXCLUDED], [])
    ck("gaps", gaps(run["trials"]), [[283, 297], [298, 311]])
    print(f"       why: {run['why']}")

    # --- 3. the pass split -----------------------------------------------------------------
    print("\n3. detect_pass_split — largest INTERIOR gap, first step IGNORED")
    ps = detect_pass_split(entries, run["lo"], run["hi"], usable=run["trials"])
    ck("value (LAST TRIAL OF PASS 1, not 167)", ps["value"], 166)
    ck("gap_s", ps["gap_s"], 20.0)
    ck("median_gap_s", ps["median_gap_s"], 2.0)
    ck("runner_up", (ps["runner_up"]["after_trial"], ps["runner_up"]["gap_s"]), (234, 8.0))
    ck("decisive (20.0s vs 8.0s = 2.5x)", ps["decisive"], True)
    ck("n_pass1 / n_pass2", (ps["n_pass1"], ps["n_pass2"]), (156, 156))
    print(f"       why: {ps['why']}")

    # THE TRAPS, demonstrated rather than asserted.
    snaps_in = sorted([e for e in entries if e.type == SNAPSHOT and 11 <= e.trial <= 348],
                      key=lambda e: e.trial)
    steps = [(a.trial, (b.dt - a.dt).total_seconds()) for a, b in zip(snaps_in, snaps_in[1:])]
    naive = max(steps, key=lambda s: s[1])          # argmax takes the FIRST of a tie
    print(f"       trap A — naive argmax over ALL steps = after trial {naive[0]} @ {naive[1]:g}s: "
          f"11->12 TIES the true boundary at 20.0s and wins the tie. Avoided.")
    ck("trap A is real (naive max-gap picks 11, not 166)", naive[0], 11)
    drop1 = max(steps[1:], key=lambda s: s[1])
    second = sorted(steps[1:], key=lambda s: -s[1])[1]
    print(f"       trap B — dropping ONLY the first step leaves runner-up "
          f"{second[0]}->{second[0] + 1} @ {second[1]:g}s (spec claims 8s: WRONG), "
          f"a margin of only {drop1[1] / second[1]:.2f}x. The min-side guard removes it.")
    ck("trap B is real (spec's '8 s runner-up' is actually 13 s)", second[1], 13.0)

    # --- 4. open_session --------------------------------------------------------------------
    print("\n4. open_session")
    t0 = time.time()
    s = open_session(D)
    dt = time.time() - t0
    ck("frames.shape", s.frames.shape, (312, 512, 512))
    ck("band.shape", s.band.shape, (312, 512, 512))
    ck("row_of[11]", s.row_of[11], 0)
    ck("tiles n", len(s.tiles), 312)
    ck("excluded.n", s.excluded["n"], 26)
    ck("pass counts", (sum(1 for m in s.tiles.values() if m["pass"] == 1),
                       sum(1 for m in s.tiles.values() if m["pass"] == 2)), (156, 156))
    print(f"       tone: lo={s.tone.lo:.1f} hi={s.tone.hi:.1f} level={s.tone.level:.1f} "
          f"n_sample={s.tone.n_sample}")
    print(f"       open took {dt:.2f}s   RAM ~{(s.frames.nbytes + s.band.nbytes) / 2**20:.0f} MiB")

    # --- 5. the texture measure, vs the precomputed ground truth ---------------------------
    print("\n5. texture — bit-identical to analysis/texture/260620d_texture.json?")
    ref_p = _REPO / "analysis/texture/260620d_texture.json"
    import json
    ref = {int(k): v for k, v in json.loads(ref_p.read_text()).items()}
    diffs = [(t, s.texture[t], ref[t]) for t in s.texture if t in ref and s.texture[t] != ref[t]]
    ck("312/312 trials match the reference to 2 dp", len(diffs), 0)
    if diffs:
        print(f"       first diffs: {diffs[:5]}")

    # --- 6. THE BLANK SCAN -----------------------------------------------------------------
    print("\n6. blank_scan")
    b = s.blank
    ck("threshold", round(b["threshold"], 2), 60.11)
    ck("n_scanned", b["n_scanned"], 312)
    print(f"       proposed blank (over the 312 USABLE trials): {b['blank']}")
    print(f"       known blank (the 11, from the ruling; never re-loaded): {b['known_blank']}")
    ck("known_blank is the 11", b["n_known_blank"], 11)
    ck("proposed blanks are the 4 near-threshold pass-1 trials", b["blank"], [34, 55, 56, 127])
    # ...and the measure DOES reproduce the 11, as the reference JSON proves without loading them:
    below = sorted(t for t in _excl.BLANK if ref[t] < b["threshold"])
    ck("all 11 known blanks are below the threshold in the reference texture",
       below, sorted(_excl.BLANK))
    print(f"       -> the measure is sound: it puts all 11/11 known blanks under {b['threshold']:.2f} "
          f"(from the precomputed JSON — those .dat files are NOT opened).")

    # --- 7. pixels -------------------------------------------------------------------------
    print("\n7. pixel endpoints")
    png = tile_png(s.frame(11), s.flat_n, s.tone)
    ck("tile PNG is a PNG", png[:8], b"\x89PNG\r\n\x1a\n")
    im = np.asarray(Image.open(BytesIO(png)))
    ck("tile PNG shape/dtype", (im.shape, str(im.dtype)), ((512, 512), "uint8"))
    rawb = tile_raw(s.frame(11))
    ck("tile RAW bytes", len(rawb), 524288)
    ck("tile RAW round-trips the flipped frame",
       bool(np.array_equal(np.frombuffer(rawb, "<u2").reshape(512, 512).astype(np.float32),
                           s.frame(11))), True)
    sheet, grid = s.thumbs()
    sh = np.asarray(Image.open(BytesIO(sheet)))
    ck("thumbs grid", grid, 18)
    ck("thumbs sheet shape", sh.shape, (18 * 64, 18 * 64))
    ck("thumbs.json", s.thumbs_json()["n"], 312)
    ck("session.tile_png(11) == tile_png(frame(11))", s.tile_png(11) == png, True)
    ck("session.tile_png(284) raises (the 26 are not served)",
       isinstance(_raises(lambda: s.tile_png(284)), KeyError), True)

    # PUT /api/tone must bump the version AND invalidate the display caches
    v0, p0 = s.tone.version, s.tile_png(11)
    s.set_tone(lo=90.0, hi=2400.0)
    ck("set_tone bumps version", s.tone.version, v0 + 1)
    ck("set_tone sets auto=False", s.tone.auto, False)
    ck("set_tone INVALIDATES the tile cache (pixels actually changed)",
       s.tile_png(11) != p0, True)
    s.set_tone(auto=True)
    ck("set_tone(auto=True) restores the measured window", s.tone.auto, True)
    ck("...and the original pixels come back", s.tile_png(11) == p0, True)
    ck("set_tone rejects hi <= lo", isinstance(_raises(lambda: s.set_tone(lo=9, hi=9)), ValueError),
       True)
    ck("band (the matcher's input) is untouched by tone",
       bool(np.array_equal(s.banded(11), band_pass(s.frame(11)))), True)

    # --- 8. the tone window is GLOBAL, not per-tile -----------------------------------------
    # THE DISCRIMINATING TEST: under a GLOBAL window a near-empty frame must STAY DIM. A per-tile
    # percentile stretch would over-brighten it to the same contrast as a rich frame — which is
    # exactly what makes overlapping tiles disagree in brightness and DESTROYS Difference mode.
    print("\n8. tone is GLOBAL, not per-tile (Difference mode depends on this)")
    rich, empty = 21, 127          # texture 344.09 vs 58.58 — a rich frame and a near-blank one
    g_std, p_std = {}, {}
    for t in (rich, empty):
        c = flat_correct(s.frame(t), s.flat_n, s.tone.level)
        g_std[t] = float(to_u8(s.frame(t), s.flat_n, s.tone).std())
        plo, phi = np.percentile(c, [TONE_PCT_LO, TONE_PCT_HI])          # the FORBIDDEN per-tile way
        p_std[t] = float(np.clip((c - plo) * (255.0 / (phi - plo)), 0, 255).astype(np.uint8).std())
    g_ratio = g_std[rich] / g_std[empty]
    p_ratio = p_std[rich] / p_std[empty]
    print(f"       GLOBAL window : trial {rich} u8 std {g_std[rich]:.1f} vs trial {empty} "
          f"{g_std[empty]:.1f}  -> ratio {g_ratio:.2f}x  (the near-blank frame STAYS DIM ✓)")
    print(f"       per-tile (BAD): trial {rich} u8 std {p_std[rich]:.1f} vs trial {empty} "
          f"{p_std[empty]:.1f}  -> ratio {p_ratio:.2f}x  (both flattened to the same contrast ✗)")
    ck("global window keeps the near-blank frame >=3x dimmer", g_ratio >= 3.0, True)
    ck("a per-tile stretch would flatten them to <1.5x (which is why we do not do it)",
       p_ratio < 1.5, True)

    # --- 9. the 26 are never opened ---------------------------------------------------------
    print("\n9. ⛔ the 26 are not data")
    try:
        load_frames(D, [11, 284])
        ck("load_frames refuses a thrown-out trial", "no exception", "ValueError")
    except ValueError as e:
        ck("load_frames refuses a thrown-out trial", "ValueError" in type(e).__name__, True)
        print(f"       {e}")
    ck("no excluded trial in tiles", [t for t in s.tiles if t in _excl.EXCLUDED], [])
    ck("no excluded trial in texture", [t for t in s.texture if t in _excl.EXCLUDED], [])
    ck("session.frame(284) raises", isinstance(_raises(lambda: s.frame(284)), KeyError), True)

    # --- 10. JSON safety ---------------------------------------------------------------------
    print("\n10. GET /api/session is JSON-serialisable")
    js = json.dumps(s.to_json())
    ck("json.dumps(session)", len(js) > 1000, True)
    ck("json.dumps(log)", len(json.dumps(log_json(s.experiment, s.entries))) > 1000, True)
    print(f"       session body = {len(js) / 1024:.0f} KiB")

    # --- 11. ⭐ THE RULING IS SCOPED TO 260620d (the user's ruling #2) -------------------------
    print("\n11. ⭐ regime A — 260620d: the ruling IS in force (nothing may change)")
    r = s.ruling
    ck("regime", r.regime, "260620d-exclusions")
    ck("applies", r.applies, True)
    ck("locked (the UI may not un-tick them)", r.locked, True)
    ck("decided from the log, not the folder name", r.evidence["matched_on"],
       "log.txt `New experiment:` line")
    ck("excluded == the 26", sorted(r.excluded), sorted(_excl.EXCLUDED))
    ck("no warning on 260620d", r.warning, None)
    ck("session.excluded.n", s.excluded["n"], 26)
    ck("session.warnings is empty", s.warnings, [])
    ck("GET /api/session carries the regime", s.to_json()["ruling"]["regime"],
       "260620d-exclusions")
    print(f"       why: {r.why}")

    print("\n12. ✅ regime B — a DIFFERENT acquisition: the ruling is NOT applied")
    S = _REPO / "data/drive/260620/260620_Imaging/260620"      # the sibling. NOT 260620d.
    if not S.is_dir():
        print(f"  [skip] {S} not present")
    else:
        r2 = detect_ruling(S)
        ck("regime", r2.regime, "none")
        ck("applies", r2.applies, False)
        ck("excluded is EMPTY", sorted(r2.excluded), [])
        ck("locked", r2.locked, False)
        ck("identified from log.txt as '260620'", r2.evidence["log_experiment"], "260620")
        ck("a warning is raised", bool(r2.warning), True)
        print(f"       why : {r2.why}")
        print(f"       WARN: {r2.warning}")

        # the 26 are NOT removed — proven on the range where they live, over the SAME gate.
        no_ruling = usable_trials(S, 284, 348, r2)
        with_ruling = usable_trials(S, 284, 348, detect_ruling(D))
        print(f"       gate over 284-348 on the sibling: {len(no_ruling)} usable "
              f"(all its snapshots survive; it has none up there — see the synthetic test below)")
        ck("the ruling would have deleted trials here; it did not",
           set(with_ruling) <= set(no_ruling), True)

        # ⚠️ RECON:128 — trial 021 is a GENUINE snapshot at 512x128. Per-trial shape.
        print("\n       ⚠️ per-trial shape (RECON:128): sibling trial 021 is 512x128, not 512x512")
        inv = list_snapshots(S)
        ck("021 is a genuine 1-frame snapshot on disk", 21 in inv, True)
        ck("...and its XML says 512x128", (inv[21]["w"], inv[21]["h"]), (512, 128))
        ck("...131,072 bytes, not 524,288", inv[21]["dat"].stat().st_size, 131072)
        s2 = open_session(S)
        ck("open_session(260620) does not crash", s2.run["n"] > 0, True)
        ck("run", (s2.run["lo"], s2.run["hi"]), (13, 24))
        ck("021 was DROPPED by shape, not mis-read",
           [d["trial"] for d in s2.run["dropped"]["off_shape"]], [21])
        ck("...and it is not in the trial list", 21 in s2.run["trials"], False)
        ck("...and it is not in tiles", 21 in s2.tiles, False)
        ck("every loaded frame IS 512x512", s2.frames.shape[1:], (512, 512))
        ck("the shape drop opened a gap 20->22", s2.gaps, [[20, 22]])
        ck("no ruling in force", s2.excluded["n"], 0)
        ck("session.excluded.locked is False", s2.excluded["locked"], False)
        ck("the warnings reach GET /api/session", len(s2.to_json()["warnings"]) >= 2, True)
        ck("known_blank is EMPTY (260620d's blanks are not this dataset's)",
           s2.blank["known_blank"], [])
        ck("session JSON serialises", len(json.dumps(s2.to_json())) > 500, True)
        for w in s2.warnings:
            print(f"       WARN: {w}")
        # and load_frames FAILS LOUDLY rather than mis-reading 131,072 bytes as 512x512
        e = _raises(lambda: load_frames(S, [13, 21]))
        ck("load_frames(21) fails LOUDLY (not silently mis-read)", isinstance(e, ValueError), True)
        print(f"       {e}")

    # --- 13. THE DISCRIMINATING TEST: the same trial numbers, a different experiment ----------
    # 260620's trials only reach 26, so it cannot by itself show the 26 surviving. Copy 260620d's
    # frames into a scratch directory whose log.txt says a DIFFERENT experiment, and open it:
    # the 26 must come back as data, and the run must be 338, not 312.
    print("\n13. ⭐⭐ the same 338 frames, log.txt says '260620x' -> the 26 are NOT removed")
    import shutil
    import tempfile
    tmp = Path(tempfile.gettempdir()) / "camea_ruling_scope_test" / "260620x"
    try:
        if tmp.exists():
            shutil.rmtree(tmp)
        tmp.mkdir(parents=True)
        for t in range(11, 349):
            for suf in (".xml", "-ccd.dat"):
                src = D / f"{t:03d}{suf}"
                if src.exists():
                    shutil.copy2(src, tmp / src.name)
        log = (D / "log.txt").read_text(encoding="utf-8", errors="replace")
        (tmp / "log.txt").write_text(log.replace("New experiment: 260620d",
                                                 "New experiment: 260620x"), encoding="utf-8")
        r3 = detect_ruling(tmp)
        ck("regime", r3.regime, "none")
        ck("log_experiment", r3.evidence["log_experiment"], "260620x")
        s3 = open_session(tmp)
        ck("run 11-348", (s3.run["lo"], s3.run["hi"]), (11, 348))
        ck("⭐ n = 338, NOT 312 — the 26 are DATA here", s3.run["n"], 338)
        ck("all 26 are in the trial list", [t for t in sorted(_excl.EXCLUDED)
                                            if t not in s3.run["trials"]], [])
        ck("all 26 have loaded pixels", [t for t in sorted(_excl.EXCLUDED)
                                         if t not in s3.row_of], [])
        ck("trial 304 (260620d's blank) is servable here", len(s3.tile_png(304)) > 0, True)
        ck("no gaps — the run is contiguous again", s3.gaps, [])
        ck("session.excluded.n == 0", s3.excluded["n"], 0)
        ck("pass_split still detected", s3.pass_split["value"], 166)
        # 11-166 = 156 trials; 167-348 = 182. 156 + 182 = 338 — and 182, not 156, is exactly the
        # "pass 2 = 182" number the ruling reduces to 156 on 260620d. Both regimes are consistent.
        ck("n_pass1 / n_pass2 (338 = 156 + 182)",
           (s3.pass_split["n_pass1"], s3.pass_split["n_pass2"]), (156, 182))
        ck("the blank scan found 260620d's blanks ITSELF, by measurement",
           [t for t in sorted(_excl.BLANK) if t not in s3.blank["blank"]], [])
        print(f"       the scan's OWN proposal (n={s3.blank['n_blank']}): {s3.blank['blank']}")
        print(f"       -> the user's eye + `E` build this dataset's exclusion list from scratch.")
        ck("...and it is a PROPOSAL: nothing was auto-excluded", s3.excluded["trials"], [])
        # ⛔ and 260620d itself is STILL untouched by any of this
        ck("⛔ 260620d is unchanged: still 312", len(usable_trials(D, 11, 348)), 312)
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)

    print("\n" + "=" * 78)
    if fails:
        print(f"*** {len(fails)} FAILED: {fails}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


def _raises(fn):
    try:
        fn()
    except Exception as e:
        return e
    return None


if __name__ == "__main__":
    raise SystemExit(_selftest())
