"""Loader — log.txt, frames, flat-field, the global tone window, the blank scan.

OWNER: agent 1. Nobody else edits this file.
CONTRACT: app/API.md §4 (session), §5 (pixels), §6 (tone), §9 (the blank scan).

⭐ THE 180-DEGREE FLIP IS VERIFIED (2026-07-12, `load_frame` below). `np.flip(np.flip(raw,1),0)` is
byte-identical BOTH to `analysis/texture/make_texture.py:37` AND to vscope's own display frame
(`vscope.load(xml).ccd["Cc"][0]`), on trials 11, 12, 166, 167, 347. It is a true 180 rotation
(`out[0,0] == raw[-1,-1]`), not a transpose, and it is NOT a no-op — an unflipped read returns
different pixels and would have looked perfectly plausible. Do not "simplify" it.

⛔⛔ **THE APP CARRIES NO KNOWLEDGE OF ANY DATASET.** (The user's ruling, 2026-07-14.) This module
loads EVERY genuine 512x512 snapshot it finds on disk. It knows no trial numbers, no experiment
names, no exclusion list. **The only things that may ever exclude a frame are (a) the human, in this
session, and (b) a project file he loaded** — neither of which lives here.

  · There WAS a hard-coded 26-trial exclusion list here, auto-applied when the loader recognised the
    dataset it belonged to. It is gone. It answered, on the user's behalf, the exact question the app
    exists to help him answer — he opened his data and 26 frames were already gone, before he had
    seen one of them, which short-circuits the Screen step and the `E` key, i.e. the whole app.
  · `analysis/ground_truth/excluded.py` still governs the ANALYSIS tree (the notebooks, t33, the
    benchmark, `test_mosaic_312.py`). It is untouched and it is not this app's business. The one
    thing imported from it is `gaps()` — a pure function of an arbitrary trial list, holding no
    dataset knowledge. **Do not import `EXCLUDED` / `BLANK` from it, ever.**
  · The blank scan (§9) still RECOMMENDS, from measurement, and never rejects. A measurement is not
    stored knowledge. And nothing, ever, auto-rejects on blur.

⚠️ NO DISK CACHE LIVES HERE. Loading 338 frames costs ~0.13 s; a cache would be all risk and no
reward. (And emphatically NOT `mosaic.io.load_frames`'s cache — io.py:23 validates only
`shape[0] == len(trials)`, so two DIFFERENT selections of the same size silently share an entry.)
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

# ⭐ `gaps()` ONLY — and deliberately imported by name, so nothing here can reach the dataset lists.
# `gaps(trials)` is a PURE FUNCTION of an arbitrary trial list (consecutive pairs that are not one
# acquisition step apart). It carries no dataset knowledge, it is load-bearing (the serpentine
# one-axis step prior does NOT hold across a gap), and there must be exactly one implementation of
# it in the repo. `EXCLUDED` / `BLANK` live in that same module and are 260620d's; they are the
# analysis tree's business and MUST NOT be imported here.
from analysis.ground_truth.excluded import gaps as _canonical_gaps   # noqa: E402

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


def detect_run(entries: list[LogEntry], data_dir: Path | None = None) -> dict:
    """The mosaic run = ⭐ THE LONGEST CONTIGUOUS BLOCK OF `Snapshot` TRIALS. Nothing hard-coded.

    On 260620d there are 342 Snapshot trials in exactly 3 contiguous blocks — (1), (5-7), (11-348)
    — and this rule yields **11-348, all 338 of them**.

    Returns the `run` block of `GET /api/session`:
        {"lo", "hi", "trials", "n", "n_in_range", "detected", "why", "why_detail", "blocks",
         "dropped", "n_dropped", "warnings"}
    where `trials` is `usable_trials(data_dir, lo, hi)` — every genuine 512x512 snapshot in range.
    Nothing is excluded by trial number: the app has no exclusion list.

    ⚠️ Validated on n = 1 dataset. The UI MUST show what was detected and let the user override
    (`PATCH /api/session/run`).
    """
    blocks = snapshot_blocks(entries)
    if not blocks:
        raise ValueError("log.txt contains no Snapshot trials")
    lo, hi = max(blocks, key=lambda b: b[1] - b[0])          # ties -> the first (earliest) block
    shown = ", ".join(f"{a}" if a == b else f"{a}-{b}" for a, b in blocks)
    why = f"longest run of Snapshot trials ({len(blocks)} block{'s' if len(blocks) != 1 else ''}: {shown})"
    detail = (f"The run is taken to be the longest contiguous block of `Snapshot` trials in log.txt. "
              f"{len(blocks)} block{'s' if len(blocks) != 1 else ''} found: {shown}; the longest is "
              f"{lo}-{hi}. Every genuine {TILE}x{TILE} snapshot in it is loaded — nothing is excluded "
              f"by trial number. Validated on one dataset: check it, and override it if it is wrong.")
    return _run_block(data_dir, lo, hi, detected=True, why=why, why_detail=detail,
                      blocks=[list(b) for b in blocks])


def _run_block(data_dir: Path | None, lo: int, hi: int, *, detected: bool,
               why: str, blocks: list[list[int]], why_detail: str = "") -> dict:
    part = partition_trials(data_dir, lo, hi)
    trials = part["trials"]
    n_in_range = hi - lo + 1
    return {"lo": lo, "hi": hi, "trials": trials, "n": len(trials), "n_in_range": n_in_range,
            "detected": detected, "why": why, "why_detail": why_detail or why, "blocks": blocks,
            #: everything in [lo, hi] that did NOT make it into `trials`, and WHY. The front end
            #: must be able to say why trial 021 of the sibling `260620` is missing.
            "dropped": part["dropped"],
            "n_dropped": sum(len(v) for v in part["dropped"].values()),
            "warnings": part["warnings"]}


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
        {"value", "detected", "why", "why_detail", "gap_s", "median_gap_s", "runner_up",
         "n_pass1", "n_pass2", "decisive"}
    `why` is one clause for the UI; `why_detail` is the full reasoning, for the hover tooltip.
    """
    MIN_SIDE_FRAC = 0.20      # each pass must hold >= 20 % of the run's steps

    # Snapshot trials inside the run, in acquisition order, with their timestamps.
    # ⚠️ Trials the gate dropped (an off-shape frame) ARE included here: they are still acquisition
    # EVENTS, and this is a rule about when the STAGE moved. Dropping them would fabricate gaps.
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
                "why": f"only {len(steps)} steps — too few to split. Assuming one pass.",
                "why_detail": (f"A pass boundary must have at least {MIN_SIDE_FRAC:.0%} of the run "
                               f"on each side of it, and this run has only {len(steps)} inter-trial "
                               f"steps, so no candidate qualifies. Treating it as a SINGLE pass. "
                               f"Override if that is wrong."),
                "gap_s": None, "median_gap_s": median_gap, "runner_up": None,
                "n_pass1": 0, "n_pass2": 0, "decisive": False}

    ranked = sorted(interior, key=lambda s: -s[1])
    after, gap = ranked[0]
    runner = ranked[1] if len(ranked) > 1 else None
    first_after, first_gap = steps[0]

    decisive = gap > 2.0 * median_gap and (runner is None or gap >= 2.0 * runner[1])
    why = f"{gap:g} s pause at {after}→{after + 1} (median {median_gap:g} s)"
    detail = (f"Largest interior inter-trial gap: {after}->{after + 1} is {gap:g} s, against a "
              f"median step of {median_gap:g} s — the stage driving back to the origin to re-scan "
              f"the same tissue. Candidates are restricted to steps with >= {MIN_SIDE_FRAC:.0%} of "
              f"the run on each side, which excludes the settling prefix: the block's first step "
              f"({first_after}->{first_after + 1}) is also {first_gap:g} s and would tie a naive "
              f"max-gap rule. `value` is the LAST TRIAL OF PASS 1, not the first of pass 2.")
    if not decisive:
        why += " — NOT DECISIVE, check it"
        detail += (f" ⚠️ NOT DECISIVE: the runner-up ({runner[0]}->{runner[0] + 1}, {runner[1]:g} s) "
                   f"is within 2x of the winner. This rule is validated on one dataset. Check it and "
                   f"override it if it is wrong.")

    # ⭐ counted over the run's ACTUAL trial list.
    keep = [e.trial for e in snaps] if usable is None else list(usable)
    n1 = sum(1 for t in keep if t <= after)
    n2 = sum(1 for t in keep if t > after)
    return {"value": after, "detected": True, "why": why, "why_detail": detail, "gap_s": gap,
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

    A raw disk inventory. Nothing is filtered out by trial number, here or anywhere else in the app.
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


def partition_trials(data_dir: Path | None, lo: int, hi: int) -> dict:
    """THE GATE, with its reasons. Splits `lo..hi` into what loads and what does not, and why.

        {"trials": [...],                       # what the app will actually open
         "dropped": {"off_shape": [{...}],      # a real snapshot, but not 512x512 -> unusable HERE
                     "not_snapshot": [...]},    # no .dat, a movie, a 2-frame "snapshot", bad XML
         "warnings": [str, ...]}

    ⛔⛔ **NOTHING IS DROPPED BY TRIAL NUMBER.** The two reasons above are the ONLY two, and both are
    facts about the file on disk. The app holds no exclusion list and never invents one: the human
    (with `E`) and a loaded project file are the only things that may ever exclude a frame.

    ⚠️ **SHAPE IS PER-TRIAL, NOT PER-DIRECTORY** (RECON:128). The sibling directory `260620` has
    trial 021 as a genuine `type="snapshot" frames="1"` at **parpix=128** — 512x128, 131,072 bytes.
    It is real data; it just cannot be a 512x512 mosaic tile (t33.TILE, t27.H/W and every ground
    truth hard-code 512). So it is DROPPED HERE, LOUDLY, by shape read from its own XML — never
    silently mis-read as 512x512, and never allowed to reach `load_frames`, which would raise.
    ⚠️ Dropping it opens an acquisition GAP (20 -> 22): `gaps()` recomputes, as it must.
    """
    rng = list(range(lo, hi + 1))

    if data_dir is None:                       # no disk to check against: take the range as given
        return {"trials": rng,
                "dropped": {"off_shape": [], "not_snapshot": []},
                "warnings": []}

    snaps = list_snapshots(data_dir)
    trials, off_shape, not_snap = [], [], []
    for t in rng:
        m = snaps.get(t)
        if m is None:
            not_snap.append(t)
        elif (m["h"], m["w"]) != (TILE, TILE):
            off_shape.append({"trial": t, "w": m["w"], "h": m["h"],
                              "reason": f"{m['w']}x{m['h']}, not {TILE}x{TILE}"})
        else:
            trials.append(t)

    warnings: list[str] = []
    if off_shape:
        shown = ", ".join(f"{d['trial']} ({d['w']}x{d['h']})" for d in off_shape)
        warnings.append(f"{len(off_shape)} snapshot(s) skipped — not {TILE}x{TILE}: {shown}. "
                        f"This opens a gap in the run.")
    return {"trials": trials,
            "dropped": {"off_shape": off_shape, "not_snapshot": not_snap},
            "warnings": warnings}


def usable_trials(data_dir: Path | None, lo: int, hi: int) -> list[int]:
    """THE GATE: every genuine 512x512 snapshot on disk in `[lo, hi]`. `partition_trials()["trials"]`.

    ⛔ **NO TRIAL IS EXCLUDED HERE, EVER.** Only the human and a loaded project file exclude frames.
    """
    return partition_trials(data_dir, lo, hi)["trials"]


def gaps(trials: list[int]) -> list[list[int]]:
    """Consecutive pairs in `trials` that are NOT one acquisition step apart.

    ⚠️ THE SERPENTINE ONE-AXIS STEP PRIOR DOES NOT HOLD ACROSS THESE. Any change to the trial
    selection or the excluded set MUST recompute this, or a multi-step stage jump is treated as one
    step and the whole tail is silently placed wrong.

    ⭐ Delegates to `analysis/ground_truth/excluded.py :: gaps()` — the ONE canonical implementation.
    It is a pure function of the list it is handed and knows nothing about any dataset. Do not
    reimplement it here, and do not import anything else from that module.
    """
    return [[a, b] for a, b in _canonical_gaps(list(trials))]


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


def load_frames(data_dir: Path, trials: list[int], progress=None) -> np.ndarray:
    """The stack: float32 (N, 512, 512), flipped, raw camera counts. Row i IS trial `trials[i]`.

    **338 frames in ~0.13 s** (0.37 ms/frame, warm cache). Loading is not the bottleneck; it is not
    optimised and it is NOT cached to disk.

    RAM: 1 frame float32 = exactly 1.00 MiB; 338 = **338 MiB**. Peak is 2-3x — the band-pass
    allocates a full second copy (>= 676 MiB). Budget ~1 GB host RAM.

    It loads exactly what it is asked for. There is no exclusion list and nothing to refuse.
    """
    snaps = list_snapshots(data_dir)
    missing = [t for t in trials if t not in snaps]
    if missing:
        raise ValueError(f"not snapshots in {data_dir}: {missing[:10]}")

    out = np.empty((len(trials), TILE, TILE), np.float32)
    for i, t in enumerate(trials):
        m = snaps[t]
        if (m["h"], m["w"]) != (TILE, TILE):
            # ⚠️ SHAPE IS PER-TRIAL (RECON:128 — sibling `260620` trial 021 is 512x128). The gate
            # (`partition_trials`) already drops these; reaching here means somebody bypassed it, so
            # FAIL LOUDLY rather than reshape 131,072 bytes into a 512x512 lie.
            raise ValueError(f"trial {t} is {m['w']}x{m['h']}, not {TILE}x{TILE} "
                             f"({m['dat'].name}). This app is {TILE}x{TILE} only.")
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
    precomputed `analysis/texture/260620d_texture.json` on every trial, to the stored 2 dp.
    """
    if band is not None:
        return {t: round(float(band[i].std()), 2) for i, t in enumerate(trials)}
    snaps = list_snapshots(data_dir)
    return {t: round(float(band_pass(load_frame(snaps[t])).std()), 2)
            for t in trials if t in snaps}


def blank_scan(texture: dict[int, float], pass1_trials: list[int]) -> dict:
    """-> the `GET /api/scan/blank` object (API.md §9).

    threshold = the **2nd percentile of PASS-1 texture** (pass 1 is the reference range). It is
    MEASURED from the frames in front of it, every time. Nothing is remembered between datasets.

    ⇒ **THE SCAN RECOMMENDS. THE USER TICKS. NOTHING IS AUTO-EXCLUDED.**

    ❌ **NO SLIDER. NO AUTO-REJECT. NO BLUR JUDGEMENT.** Across all 338 snapshots and 15 focus
    measures the best global blur threshold reaches F1 = 0.37; catching all 15 of the user's blurry
    frames also rejects 62 good ones, best case. **Variance-of-Laplacian scores WORSE THAN CHANCE**
    (it is dominated by sensor noise, identical in sharp and blurry frames). It must never appear in
    the UI. The user meets every tile again in the sweep and excludes it there with `E`.

    ⚠️ ZERO MARGIN AT THE BOUNDARY, and it matters. Measured on 260620d's texture:
        56 = 56.39 < [309 = 56.53] < 34 = 58.44 < [289 = 58.54] < 127 = 58.58 < 55 = 59.98
        < **[thr 60.11]** < 35 = 61.32
    Genuinely-blank frames and perfectly good ones INTERLEAVE below the threshold — the four in that
    list without brackets are ordinary tiles that pass 1 places correctly. That is exactly why this
    measure may only ever propose, and why the human decides.

    (The `blank` list is also what `engine.match_anchor` REFUSES — API.md §7.3. Refusing is not
    excluding: a blank tile the user keeps stays in the document, it just cannot be machine-matched.)
    """
    p1 = np.array([texture[t] for t in pass1_trials if t in texture], float)
    if len(p1) >= 20:
        thr = float(np.percentile(p1, BLANK_PCT))
        src = f"{BLANK_PCT:g}nd percentile of pass-1 texture (n={len(p1)})"
    else:
        thr = float("nan")
        src = f"undetermined — only {len(p1)} pass-1 trials. Nothing proposed."

    blank = sorted(t for t, v in texture.items() if math.isfinite(thr) and v < thr)

    # How close is the nearest KEPT trial to the threshold? This is the honesty number.
    above = [v for v in texture.values() if math.isfinite(thr) and v >= thr]
    margin_pct = (100.0 * (min(above) - thr) / thr) if above else float("nan")
    warn = f"nearest kept frame is only {margin_pct:.2f} % above the threshold"
    warn_detail = (f"The nearest non-blank trial sits {margin_pct:.2f} % above the threshold — good "
                   f"frames and blank ones interleave at the boundary. This measure is reliable for "
                   f"BLANK and useless for BLUR: never read anything into a near-threshold value, "
                   f"and never auto-reject on it. It proposes; you decide.")
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
        "margin_warning_detail": warn_detail,
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
    gaps: list[list[int]]           # e.g. [[283, 297]] once the user has excluded 284-296
    #: ⛔ WHAT THE **USER** HAS EXCLUDED. It starts EMPTY and the app never adds to it: the only
    #: things that may exclude a frame are the human (`E`) and a project file he loaded, and BOTH of
    #: those live in the front end's document, not here. `off_shape` is not an exclusion — it is a
    #: file on disk that is not a 512x512 tile.
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

    #: Anything the user MUST see about how this dataset was loaded (an off-shape trial dropped, and
    #: nothing else today). Surfaced at `GET /api/session`. Keep these SHORT.
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
            raise KeyError(trial)                     # -> 404: not in the run.
        return self.frames[self.row_of[trial]]

    def banded(self, trial: int) -> np.ndarray:
        if trial not in self.row_of:
            raise KeyError(trial)
        return self.band[self.row_of[trial]]

    # --- the display path (API.md §5, §6). Server: call THESE, not the free functions. -----
    def _u8_stack(self) -> np.ndarray:
        """Every display tile, uint8 (~85 MiB at n=338). Rebuilt ONLY when the tone version changes
        (0.9 s). This is what makes `PUT /api/tone` safe: there is exactly one cache and it is
        keyed on the version the front end also uses as its `?v=` cache-buster, so the two cannot
        drift apart."""
        if self._u8 is None or self._u8_version != self.tone.version:
            self._u8 = np.stack([to_u8(f, self.flat_n, self.tone) for f in self.frames])
            self._u8_version = self.tone.version
            self._thumbs = None                       # the sheet is downsampled from these
        return self._u8

    def tile_png(self, trial: int) -> bytes:
        """`GET /api/tile/{trial}.png` — 8-bit grayscale PNG, 512x512. ~4.5 ms warm.
        KeyError (-> 404) for anything not in `run.trials`."""
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

        ⛔ `excluded.trials` is **EMPTY** at open, on every dataset, always. The app excludes nothing
        on its own; the human and his project file are the only sources of an exclusion, and both of
        them live in the front end's document.
        """
        return {
            "data_dir": str(self.data_dir).replace("\\", "/"),
            #: the DIRECTORY NAME — a label a human typed. It is what the UI shows and what export
            #: basenames are built from. It is NOT the acquisition's identity, and nothing in this
            #: app may make any decision from it.
            "dataset": self.dataset,
            #: `log.txt`'s `New experiment:` name (falling back to the directory name only when the
            #: log has no such line). The acquisition's own record of itself; travels with the frames.
            "experiment": self.experiment,
            "opened_at": self.opened_at,
            #: the front end's cache-buster is `?v={nonce}.{tone.version}` — see `Session.nonce`.
            "nonce": self.nonce,
            "run": self.run,
            "pass_split": self.pass_split,
            "gaps": self.gaps,
            "excluded": self.excluded,
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

    if lo is None or hi is None:
        run = detect_run(entries, data_dir)
    else:
        run = _run_block(data_dir, lo, hi, detected=False,
                         why=f"you set the range to {lo}-{hi}",
                         why_detail=f"Detection was overridden: the run is trials {lo}-{hi}.",
                         blocks=[list(b) for b in snapshot_blocks(entries)])
    if not run["trials"]:
        raise ValueError(f"no usable snapshots in trials {run['lo']}-{run['hi']}")

    ps = detect_pass_split(entries, run["lo"], run["hi"], usable=run["trials"])
    if pass_split is not None:
        n1 = sum(1 for t in run["trials"] if t <= pass_split)
        ps = {**ps, "value": pass_split, "detected": False,
              "why": f"you set pass 1 to end at {pass_split}",
              "why_detail": f"Detection was overridden: pass 1 ends at trial {pass_split}.",
              "n_pass1": n1, "n_pass2": len(run["trials"]) - n1}
    check()

    trials = run["trials"]
    split = ps["value"] if ps["value"] is not None else run["hi"]
    pass1 = [t for t in trials if t <= split]

    # --- load_frames ----------------------------------------------------------------------
    emit("load_frames", 0.0, f"loading {len(trials)} frames")
    frames = load_frames(data_dir, trials,
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
    blank = blank_scan(texture, pass1)
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

    # ⛔⛔ NOTHING IS EXCLUDED AT OPEN. `excluded.trials` is EMPTY on every dataset, always — the
    # session has no opinion about which frames are bad, and it is not allowed to acquire one. The
    # human excludes with `E` and a project file he loads carries his earlier exclusions; both of
    # those live in the FRONT END's document. `locked` is False for the same reason: there is nothing
    # here for the UI to be forbidden to un-tick.
    # (`off_shape` is not an exclusion. It is a file on disk that is not a 512x512 tile.)
    warnings = list(run["warnings"])
    sess = Session(
        data_dir=data_dir, dataset=data_dir.name,
        opened_at=_iso(datetime.now(timezone.utc)),
        run=run, pass_split=ps, gaps=gaps(trials),
        excluded={"trials": [], "n": 0,
                  "source": "you — the app excludes nothing on its own",
                  "locked": False,
                  "off_shape": run["dropped"]["off_shape"]},
        warnings=warnings,
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
    ck("⛔ n usable == 338 — EVERY snapshot on disk. Nothing is excluded.", run["n"], 312 + 26)
    ck("nothing was dropped", run["n_dropped"], 0)
    ck("no gaps — nothing is excluded, so the run is contiguous", gaps(run["trials"]), [])
    print(f"       why       : {run['why']}")
    print(f"       why_detail: {run['why_detail']}")

    # --- 3. the pass split -----------------------------------------------------------------
    print("\n3. detect_pass_split — largest INTERIOR gap, first step IGNORED")
    ps = detect_pass_split(entries, run["lo"], run["hi"], usable=run["trials"])
    ck("value (LAST TRIAL OF PASS 1, not 167)", ps["value"], 166)
    ck("gap_s", ps["gap_s"], 20.0)
    ck("median_gap_s", ps["median_gap_s"], 2.0)
    ck("runner_up", (ps["runner_up"]["after_trial"], ps["runner_up"]["gap_s"]), (234, 8.0))
    ck("decisive (20.0s vs 8.0s = 2.5x)", ps["decisive"], True)
    ck("n_pass1 / n_pass2 (338 = 156 + 182)", (ps["n_pass1"], ps["n_pass2"]), (156, 182))
    print(f"       why       : {ps['why']}")
    print(f"       why_detail: {ps['why_detail']}")

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
    ck("frames.shape", s.frames.shape, (338, 512, 512))
    ck("band.shape", s.band.shape, (338, 512, 512))
    ck("row_of[11]", s.row_of[11], 0)
    ck("tiles n", len(s.tiles), 338)
    ck("⛔ excluded.n == 0 — the app excludes NOTHING at open", s.excluded["n"], 0)
    ck("⛔ excluded.trials is empty", s.excluded["trials"], [])
    ck("excluded.locked is False (there is nothing to lock)", s.excluded["locked"], False)
    ck("pass counts", (sum(1 for m in s.tiles.values() if m["pass"] == 1),
                       sum(1 for m in s.tiles.values() if m["pass"] == 2)), (156, 182))
    print(f"       tone: lo={s.tone.lo:.1f} hi={s.tone.hi:.1f} level={s.tone.level:.1f} "
          f"n_sample={s.tone.n_sample}")
    print(f"       open took {dt:.2f}s   RAM ~{(s.frames.nbytes + s.band.nbytes) / 2**20:.0f} MiB")

    # --- 5. the texture measure, vs the precomputed ground truth ---------------------------
    print("\n5. texture — bit-identical to analysis/texture/260620d_texture.json?")
    ref_p = _REPO / "analysis/texture/260620d_texture.json"
    import json
    ref = {int(k): v for k, v in json.loads(ref_p.read_text()).items()}
    diffs = [(t, s.texture[t], ref[t]) for t in s.texture if t in ref and s.texture[t] != ref[t]]
    ck("every trial matches the reference to 2 dp", len(diffs), 0)
    ck("...over all 338, not 312", len([t for t in s.texture if t in ref]), 338)
    if diffs:
        print(f"       first diffs: {diffs[:5]}")

    # --- 6. THE BLANK SCAN — it RECOMMENDS, from measurement. It never rejects. --------------
    print("\n6. blank_scan — a MEASUREMENT, not stored knowledge")
    b = s.blank
    ck("threshold", round(b["threshold"], 2), 60.11)
    ck("n_scanned == 338 — every frame was opened and measured", b["n_scanned"], 338)
    print(f"       proposal (n={b['n_blank']}): {b['blank']}")
    # ⭐ THE POINT: with nothing hard-coded, the measure FINDS 260620d's blanks by itself — it opened
    # all 338 frames, including the 11 the old hard-coded list used to hide from it. 289 and 300-309
    # are the genuinely blank ones; 34/55/56/127 are the near-threshold pass-1 trials that are
    # perfectly good (which is exactly why this may only ever propose).
    ck("the measure finds the blanks ITSELF (289, 300-309) + the 4 near-threshold pass-1 trials",
       b["blank"], [34, 55, 56, 127, 289] + list(range(300, 310)))
    ck("⛔ and NOTHING was excluded by it", s.excluded["trials"], [])
    ck("`scanned` preserves the proposal", b["scanned"], b["blank"])
    print(f"       margin : {b['margin_warning']}")

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
    ck("thumbs grid", grid, 19)                      # ceil(sqrt(338))
    ck("thumbs sheet shape", sh.shape, (18 * 64, 19 * 64))
    ck("thumbs.json", s.thumbs_json()["n"], 338)
    ck("session.tile_png(11) == tile_png(frame(11))", s.tile_png(11) == png, True)
    ck("⭐ trial 284 IS SERVED — the user must SEE it before he can judge it",
       len(s.tile_png(284)) > 0, True)
    ck("...and so is 304, the blankest frame in the run", len(s.tile_png(304)) > 0, True)

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

    # --- 9. ⛔⛔ THE APP KNOWS NOTHING ABOUT ANY DATASET (the user's ruling, 2026-07-14) --------
    print("\n9. ⛔⛔ no dataset knowledge: EVERY frame on disk is data until the HUMAN says otherwise")
    thrown_out = sorted(set(range(284, 297)) | {299} | set(range(300, 311)) | {348})   # the old list
    ck("the old hard-coded 26 are ALL in the trial list", [t for t in thrown_out
                                                           if t not in s.run["trials"]], [])
    ck("...all have loaded pixels", [t for t in thrown_out if t not in s.row_of], [])
    ck("...all are in `tiles`", [t for t in thrown_out if t not in s.tiles], [])
    ck("...all were measured by the texture scan", [t for t in thrown_out if t not in s.texture], [])
    ck("load_frames opens one without complaint", load_frames(D, [11, 284]).shape, (2, 512, 512))
    ck("no module constant names the dataset",
       [n for n in dir(sys.modules[__name__]) if "RULING" in n or n == "Ruling"], [])
    ck("`excluded` (EXCLUDED / BLANK) is NOT importable from this module's namespace",
       hasattr(sys.modules[__name__], "_excl"), False)

    # --- 10. JSON safety ---------------------------------------------------------------------
    print("\n10. GET /api/session is JSON-serialisable")
    js = json.dumps(s.to_json())
    ck("json.dumps(session)", len(js) > 1000, True)
    ck("json.dumps(log)", len(json.dumps(log_json(s.experiment, s.entries))) > 1000, True)
    ck("no `ruling` key in the session body", "ruling" in s.to_json(), False)
    print(f"       session body = {len(js) / 1024:.0f} KiB")

    # --- 11. ⭐ EXCLUDING A TILE OPENS A GAP — the one thing that MUST still work --------------
    # `gaps()` is load-bearing: the serpentine one-axis step prior does NOT hold across a gap, and a
    # solve that assumes it away places the whole tail wrong. The app no longer opens any gap BY
    # ITSELF (nothing is excluded at open) — so the gap machinery now exists purely to serve the
    # human's `E`, which is exactly the point.
    print("\n11. ⭐ the HUMAN excludes -> a gap opens")
    ck("no gaps at open", s.gaps, [])
    kept = [t for t in s.run["trials"] if t != 200]
    ck("exclude 200 by hand -> gap 199->201", gaps(kept), [[199, 201]])
    kept2 = [t for t in s.run["trials"] if t not in thrown_out]
    ck("exclude the old 26 by hand -> the two known gaps come back",
       gaps(kept2), [[283, 297], [298, 311]])
    ck("...and that leaves 312 — the number the ANALYSIS tree still uses", len(kept2), 312)
    print("       -> 312 is now a RESULT of the user's choices, not a premise of the app.")

    # --- 12. a DIFFERENT acquisition, and the per-trial shape drop (RECON:128) ----------------
    print("\n12. the sibling 260620 — off-shape drop, and its gap")
    S = _REPO / "data/drive/260620/260620_Imaging/260620"
    if not S.is_dir():
        print(f"  [skip] {S} not present")
    else:
        # ⚠️ RECON:128 — trial 021 is a GENUINE snapshot at 512x128. Shape is PER-TRIAL, and this is
        # the ONLY thing (besides the human) that removes a trial from a run.
        inv = list_snapshots(S)
        ck("021 is a genuine 1-frame snapshot on disk", 21 in inv, True)
        ck("...and its XML says 512x128", (inv[21]["w"], inv[21]["h"]), (512, 128))
        ck("...131,072 bytes, not 524,288", inv[21]["dat"].stat().st_size, 131072)
        s2 = open_session(S)
        ck("run", (s2.run["lo"], s2.run["hi"]), (13, 24))
        ck("021 was DROPPED by shape, not mis-read",
           [d["trial"] for d in s2.run["dropped"]["off_shape"]], [21])
        ck("...and it is not in the trial list", 21 in s2.run["trials"], False)
        ck("every loaded frame IS 512x512", s2.frames.shape[1:], (512, 512))
        ck("the shape drop opened a gap 20->22", s2.gaps, [[20, 22]])
        ck("nothing is excluded here either", s2.excluded["n"], 0)
        ck("session JSON serialises", len(json.dumps(s2.to_json())) > 500, True)
        for w in s2.warnings:
            print(f"       WARN: {w}")
        # and load_frames FAILS LOUDLY rather than mis-reading 131,072 bytes as 512x512
        e = _raises(lambda: load_frames(S, [13, 21]))
        ck("load_frames(21) fails LOUDLY (not silently mis-read)", isinstance(e, ValueError), True)
        print(f"       {e}")

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
