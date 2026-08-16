"""dataset.py — a DATASET: **discover** it, **open** it, **describe** it.

A DATASET is a folder of `NNN.xml` + `NNN-ccd.dat` frames and a `log.txt`. It is the microscope's
own record of an acquisition.

⛔⛔ **A DATASET IS RAW, AND IT IS READ-ONLY.** Nothing in this module writes, creates, renames,
deletes or touches a byte inside one — and that is *enforced*, not merely intended:

  * there is no write API in this module, and `tests/unit/test_dataset.py` greps this file for one;
  * `Dataset` is a **frozen** dataclass — the description you get back cannot be edited into a lie;
  * `Dataset.refuse_write(path)` / `refuse_write(path, roots)` raise `DatasetIsReadOnly`, and are
    what `core.workspace` calls before it opens *anything* for writing. An analysis lands in the
    WORKSPACE the user chose. It never lands in the dataset and it never lands in the repo.

⛔⛔ **THE APP CARRIES NO KNOWLEDGE OF ANY DATASET.** (The user's ruling, 2026-07-14, enforced at
real cost.) This module reports **every** trial it finds on disk. It knows no trial numbers, no
experiment names, no exclusion list, and it has no opinion about which frames are good.

  · v1 hard-coded 26 excluded trials here and auto-applied them when it recognised "his" dataset.
    It answered, on the user's behalf, *the exact question the app exists to help him answer* — he
    opened his data and 26 frames were gone before he had seen one of them. It was ripped out.
    **Do not reintroduce it, in any form, including as a "sensible default" or a toggle.**
  · The ONLY thing importable from the exclusion module is `gaps()` — a pure function over an
    arbitrary trial list (below). Never `EXCLUDED` / `BLANK` / `BLURRY` / `usable_trials`.
  · The only things that may ever exclude a frame are (a) the human, in this session, and (b) a
    project file he loaded. Both live in the DOCUMENT, not here.

⛔ **AND CORE IS FEATURE-AGNOSTIC.** This module has never heard of a *tile*, an *anchor* or a
*pass*. It reports **shape groups**; it does not gate on 512x512 (that is the mosaic feature's
policy — 512 is `t33.TILE`). It reports **snapshot blocks**; it does not choose one (that is
`features/mosaic/run.py`). It reports the **timing split** measured from the timestamps; the word
"pass" is the mosaic feature's, not core's — see `detect_timing_split`.

Ported from `archive/app-v1/backend/loader.py` (READ-ONLY reference):
`_TRIAL_RE`/`_DATE_RE`/`_STAMP_RE`/`SNAPSHOT` (:71), `_iso` (:78), `LogEntry` (:86),
`parse_log` (:98), `log_json` (:165), `snapshot_blocks` (:176), `read_trial_meta` (:332),
`list_snapshots` (:369), `gaps` (:445), `Session.store_key` (:907), `detect_pass_split` (:231).
"""
from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import numpy as np

# ⭐ `check_cancelled` ONLY — the ONE `Cancelled` the job runner catches (a second one is how v1's
# cancelled `open` came back marked "failed, with a traceback"). `core.jobs` imports nothing of
# ours, so this does not close a loop.
from camea.core.jobs import check_cancelled

# ⭐ `gaps()` ONLY — and imported BY NAME, so nothing in this module can reach the dataset lists that
# live beside it. `gaps(trials)` is a PURE FUNCTION of an arbitrary trial list (consecutive pairs
# that are not one acquisition step apart). It holds no dataset knowledge, it is load-bearing (the
# serpentine one-axis step prior does NOT hold across a gap), and there must be exactly ONE
# implementation of it in the repo. `EXCLUDED` / `BLANK` / `BLURRY` / `usable_trials` are 260620d's
# and are the research tree's business. **They MUST NOT be imported here, ever.**
from camea.engine.excluded import gaps as _canonical_gaps

__all__ = [
    "SNAPSHOT",
    "Dataset",
    "DatasetIsReadOnly",
    "LogEntry",
    "ScanResult",
    "TimingSplit",
    "detect_timing_split",
    "gaps",
    "is_inside",
    "iso",
    "list_snapshots",
    "log_json",
    "longest_block",
    "open_dataset",
    "parse_log",
    "read_trial_meta",
    "refuse_write",
    "scan",
    "SCAN_WALK",
    "SCAN_OPEN",
    "snapshot_blocks",
    "store_key",
]

#: The one trial type this app has any interest in. It is a *label in log.txt*, not a judgement.
SNAPSHOT = "Snapshot"

_TRIAL_RE = re.compile(
    r"^\s*(?:(\d\d)/(\d\d)/(\d\d)\s+)?(\d\d):(\d\d):(\d\d)\s+Trial\s+(\d+):\s*(.+?)\s*$"
)
_DATE_RE = re.compile(r"^\s*(\d\d)/(\d\d)/(\d\d)\s+(\d\d):(\d\d):(\d\d)\s+New experiment:\s*(\S+)")
_STAMP_RE = re.compile(r"^\s*(?:(\d\d)/(\d\d)/(\d\d)\s+)?(\d\d):(\d\d):(\d\d)\s")

#: `NNN.xml` — the trial files, and nothing else in the directory.
_XML_GLOB = "[0-9][0-9][0-9].xml"


def iso(dt: datetime) -> str:
    """A datetime -> the wire format. ISO-8601, UTC, ending in `Z`.

    ⚠️ ONE implementation. v1 had three (`loader:78`, `jobs:54`, `server:157`) and every file on
    disk says `Z` — a `+00:00` from a stray `datetime.isoformat()` does not round-trip against them.
    """
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _now() -> str:
    return iso(datetime.now(timezone.utc))


# =============================================================================
# READ-ONLY — enforced, not intended
# =============================================================================
class DatasetIsReadOnly(PermissionError):
    """Something tried to write inside a raw dataset.

    A dataset is the microscope's evidence. Camea reads it and never edits it: every artefact the
    app produces lands in the WORKSPACE the user chose. This is raised, not warned — a "write into
    the data mirror" is not a thing to recover from gracefully.
    """


def is_inside(target: str | os.PathLike[str], root: str | os.PathLike[str]) -> bool:
    """Is `target` `root` itself, or anywhere beneath it? Resolved, so `..` and symlinks cannot
    smuggle a path past the guard."""
    t = Path(target).expanduser().resolve()
    r = Path(root).expanduser().resolve()
    return t == r or r in t.parents


def refuse_write(
    target: str | os.PathLike[str], roots: Iterable[str | os.PathLike[str]]
) -> None:
    """⛔ Raise `DatasetIsReadOnly` if `target` would land inside any of `roots`.

    ⭐ This is the primitive `core.workspace` guards every output path with (v1 had three copies of
    it — `project:920`, `server:1055`, `export._guard_out_dir:298` — and they had drifted apart).
    Call it with the repo's `data/` mirror **and** every open dataset's own directory.
    """
    for r in roots:
        if is_inside(target, r):
            raise DatasetIsReadOnly(
                f"refusing to write to {Path(target)}: it is inside the dataset {Path(r)}, which is "
                f"RAW and READ-ONLY. Choose a project folder outside your data."
            )


# =============================================================================
# log.txt
# =============================================================================
@dataclass(frozen=True)
class LogEntry:
    """One `Trial NNN: <type>` line."""

    trial: int
    type: str  # only two appear on 260620d: "Snapshot" and "E'phys. + VSD"
    time: str  # ISO-8601 UTC
    gap_s: float | None  # seconds since the previous SNAPSHOT; None for the first / non-snapshots
    dt: datetime | None = None  # the parsed timestamp. Not serialised.

    def to_json(self) -> dict:
        return {"trial": self.trial, "type": self.type, "time": self.time, "gap_s": self.gap_s}


def parse_log(log_path: str | os.PathLike[str]) -> tuple[str, list[LogEntry]]:
    """Parse a vscope `log.txt` -> (experiment_name, entries in file order).

        06/20/26 15:46:58 New experiment: 260620d
                 15:47:05 Settings loaded: 250712-mosaic
                 15:47:05 Trial 001: Snapshot
                 ...
                 16:02:44 Trial 011: Snapshot

    ⚠️ THE DATE APPEARS ONLY ON `New experiment:` LINES. Every other line carries `HH:MM:SS` alone.
    We carry the date forward and roll it over whenever the clock goes BACKWARDS by more than a
    minute (a run can cross midnight). Getting this wrong corrupts the timing-split detection, which
    is a *time-gap* rule — a missed rollover would inject a -86,000 s gap.

    `gap_s` is measured between consecutive SNAPSHOT trials only: a 2-minute E'phys trial in the
    middle is not a stage move, and letting it contribute a gap would hand the split rule a spurious
    winner.
    """
    text = Path(log_path).read_text(encoding="utf-8", errors="replace")

    experiment = ""
    day: datetime | None = None  # midnight of the current date
    prev: datetime | None = None  # previous timestamp seen, for rollover detection
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
            continue  # continuation lines ("Note: ...")
        if st.group(1):  # an explicit date on some other line
            mm, dd, yy = (int(g) for g in st.groups()[:3])
            day = datetime(2000 + yy, mm, dd)
        if day is None:
            continue  # no date seen yet — cannot time it
        hh, mi, ss = (int(g) for g in st.groups()[3:6])
        dt = day + timedelta(hours=hh, minutes=mi, seconds=ss)
        # midnight rollover: the wall clock went backwards, so the day advanced.
        if prev is not None and dt < prev - timedelta(minutes=1):
            day = day + timedelta(days=1)
            dt = day + timedelta(hours=hh, minutes=mi, seconds=ss)
        prev = dt

        tm = _TRIAL_RE.match(line)
        if not tm:
            continue  # "Settings loaded", "Parameter change", ...
        trial, ttype = int(tm.group(7)), tm.group(8)
        gap = None
        if ttype == SNAPSHOT:
            if prev_snap is not None:
                gap = round((dt - prev_snap).total_seconds(), 1)
            prev_snap = dt
        entries.append(LogEntry(trial=trial, type=ttype, time=iso(dt), gap_s=gap, dt=dt))

    if not experiment:
        experiment = Path(log_path).parent.name
    return experiment, entries


def log_json(experiment: str, entries: Sequence[LogEntry]) -> dict:
    """The `LogResponse` body. (v1 had this function *and* a second copy inlined in the route.)"""
    n_snap = sum(1 for e in entries if e.type == SNAPSHOT)
    return {
        "experiment": experiment,
        "entries": [e.to_json() for e in entries],
        "n_snapshot": n_snap,
        "n_other": len(entries) - n_snap,
    }


def snapshot_blocks(entries: Sequence[LogEntry]) -> list[tuple[int, int]]:
    """Contiguous runs of `Snapshot` trials, by trial number. On 260620d: [(1,1),(5,7),(11,348)].

    ⛔ Core *reports* the blocks. It does not pick one: "the run is the longest block, restricted to
    512x512 frames" is the **mosaic feature's** selection rule (`features/mosaic/run.py`), and the
    next feature will want a different one over the same dataset.
    """
    snaps = sorted(e.trial for e in entries if e.type == SNAPSHOT)
    blocks: list[tuple[int, int]] = []
    for t in snaps:
        if blocks and t == blocks[-1][1] + 1:
            blocks[-1] = (blocks[-1][0], t)
        else:
            blocks.append((t, t))
    return blocks


def longest_block(blocks: Sequence[tuple[int, int]]) -> tuple[int, int]:
    """The longest contiguous block; ties -> the first (earliest). Raises on an empty list."""
    if not blocks:
        raise ValueError("no Snapshot trials: there are no blocks to choose from")
    return max(blocks, key=lambda b: b[1] - b[0])


def gaps(trials: Iterable[int]) -> list[tuple[int, int]]:
    """Consecutive pairs in `trials` that are NOT one acquisition step apart.

    ⚠️ THE SERPENTINE ONE-AXIS STEP PRIOR DOES NOT HOLD ACROSS THESE. Any change to the trial
    selection or to the excluded set MUST recompute this, or a multi-step stage jump is treated as
    one step and the whole tail is silently placed wrong.

    ⭐ Delegates to `camea.engine.excluded.gaps` — the ONE canonical implementation, and **the only
    symbol this app may import from that module.** Do not reimplement it here, and do not import
    anything else from there.
    """
    return list(_canonical_gaps(list(trials)))


# =============================================================================
# The trial files — geometry, per trial, read from the XML
# =============================================================================
def read_trial_meta(xml_path: str | os.PathLike[str]) -> dict | None:
    """Parse a trial's XML -> its metadata, or None if it is not a genuine 1-frame snapshot.

    Returns the dict `core.frames.load_frame()` consumes:
        {"trial", "time", "w", "h", "bytes", "dtype", "flip_x", "flip_y"}   (+ "dat", added below)

    ⚠️ **SHAPE IS PER-TRIAL, NOT PER-DIRECTORY.** The sibling directory `260620` has trial 021 as a
    genuine `type="snapshot" frames="1"` at parpix=128 — 512x128, 131,072 bytes. **Parse the XML**;
    inferring the shape from the file size would reshape those bytes into a 512x512 lie.
    And trial 008 is a 2-frame "snapshot": reject anything with `frames != 1`.

    ⭐ `flip_x`/`flip_y` come from the XML `<transform ax ay>` and are what makes the reader flip
    **conditionally**. They are load-bearing: every position, every SWIM dx/dy and all three ground
    truths live in the flipped frame. Nothing anywhere may assert a flip; it is read off the file.
    """
    try:
        root = ElementTree.parse(os.fspath(xml_path)).getroot()
    except (ElementTree.ParseError, OSError):
        return None
    info, ccd = root.find("info"), root.find("ccd")
    if info is None or ccd is None or info.get("type") != "snapshot":
        return None
    cam = ccd.find("camera")
    if cam is None or int(cam.get("frames", 1)) != 1:
        return None  # trial 008 is a 2-frame "snapshot"
    xf = cam.find("transform")
    # <info date="260620" time="160244"> -> 2026-06-20T16:02:44Z
    d, t = info.get("date", ""), info.get("time", "")
    stamp = ""
    if len(d) == 6 and len(t) == 6:
        stamp = f"20{d[0:2]}-{d[2:4]}-{d[4:6]}T{t[0:2]}:{t[2:4]}:{t[4:6]}Z"
    return {
        "trial": int(info.get("trial")),
        "time": stamp,
        "w": int(cam.get("serpix")),
        "h": int(cam.get("parpix")),
        "bytes": int(cam.get("typebytes")),
        "dtype": cam.get("type"),
        "flip_x": xf is not None and int(xf.get("ax", 1)) < 0,
        "flip_y": xf is not None and int(xf.get("ay", 1)) < 0,
    }


def list_snapshots(data_dir: str | os.PathLike[str]) -> dict[int, dict]:
    """{trial: meta} for every genuine 1-frame snapshot on disk whose .dat size matches its XML.

    A raw disk inventory, and nothing more. ⛔ **Nothing is filtered out by trial number, here or
    anywhere else in the app.** Nothing is filtered out by *shape* either — an off-shape frame is
    real data, and refusing it is a *feature's* policy, made with its reason in hand.
    """
    out: dict[int, dict] = {}
    for xml_path in sorted(Path(data_dir).glob(_XML_GLOB)):
        dat = xml_path.with_name(xml_path.stem + "-ccd.dat")
        if not dat.exists():
            continue
        meta = read_trial_meta(xml_path)
        if meta is None:
            continue
        if dat.stat().st_size != meta["w"] * meta["h"] * meta["bytes"]:
            continue  # movies (375 frames) fail here
        meta["dat"] = dat
        out[meta["trial"]] = meta
    return out


def store_key(data_dir: str | os.PathLike[str]) -> str:
    """⚠️ THE ON-DISK KEY FOR AN ACQUISITION — **not** its basename.

    The t33 cache filename carries the trial-membership hash and the config hash, but nothing that
    identifies the PIXELS: the only thing separating two acquisitions was the cache *directory*,
    named after the basename. **Two folders both called `260620d` under different parents** — a
    re-export, a copy on another drive, a re-acquisition — share the basename, the trial numbers and
    the config, so they collide on the identical cache filename, and `t33._load_checked` (which
    compares only the CONFIG) would happily accept the first acquisition's layout as a warm build of
    the second. The autosave slot (`<basename>.camea.json`) collided the same way.

    So the key is the basename PLUS a hash of the RESOLVED directory. Same folder -> same key -> the
    warm cache still works. Different folder -> different key -> no collision, ever.
    """
    p = Path(data_dir)
    h = hashlib.sha1(str(p.resolve()).lower().encode("utf-8")).hexdigest()[:8]
    return f"{p.name}-{h}"


# =============================================================================
# ⭐ THE TIMING SPLIT — measured from the timestamps. NEVER a hard-coded 166.
# =============================================================================
#: Each side of the break must hold at least this fraction of the run's steps. ⚠️ Load-bearing —
#: see `detect_timing_split`. Without it a naive argmax returns the FIRST step of the block.
MIN_SIDE_FRAC = 0.20


@dataclass(frozen=True)
class TimingSplit:
    """Where the acquisition *stopped and went back*, measured from log.txt alone.

    `value` is the **LAST TRIAL BEFORE THE BREAK** (166 on 260620d), never the first one after it.
    """

    value: int | None
    detected: bool
    why: str
    why_detail: str
    gap_s: float | None
    median_gap_s: float
    runner_up: tuple[int, float] | None  # (after_trial, gap_s)
    n_before: int
    n_after: int
    decisive: bool

    def to_json(self) -> dict:
        return {
            "value": self.value,
            "detected": self.detected,
            "why": self.why,
            "why_detail": self.why_detail,
            "gap_s": self.gap_s,
            "median_gap_s": self.median_gap_s,
            "runner_up": (
                None
                if self.runner_up is None
                else {"after_trial": self.runner_up[0], "gap_s": self.runner_up[1]}
            ),
            "n_before": self.n_before,
            "n_after": self.n_after,
            "decisive": self.decisive,
        }


def detect_timing_split(
    entries: Sequence[LogEntry],
    lo: int,
    hi: int,
    trials: Sequence[int] | None = None,
) -> TimingSplit:
    """⭐ The trial before the largest INTERIOR inter-snapshot time gap — the moment the stage drove
    all the way back to the origin and started over.

    ⛔ **THIS IS THE MECHANISM, AND CORE OWNS IT. THE NAME "pass split" IS THE MOSAIC FEATURE'S.**
    `features/mosaic/run.py` must WRAP this (`pass_split = detect_timing_split(...).value`), not
    fork it: `t33.Config.pass_split` is the *consumer*, and one detector with one set of traps in it
    is the whole point. Two implementations of a rule this delicate is exactly the bug class this
    project keeps paying for.

    ⭐ **NEVER A HARD-CODED 166.** t33's literal default is 166 and it is *this dataset's* number.
    Hand a solver the wrong split and the two scans are solved against the wrong reference.

    ⚠️ **THE GOTCHA THAT MAKES A NAIVE MAX-GAP RULE A COIN-FLIP.** On 260620d the median
    snapshot-to-snapshot gap is **2.0 s** and **166 -> 167 is 20.0 s** — but **11 -> 12 is ALSO
    20.0 s** (settling, right after `Settings loaded`). It TIES the true boundary exactly, and on a
    tie a naive argmax takes the FIRST one and silently returns **11**.

    ⚠️⚠️ AND DROPPING ONLY THE FIRST STEP IS NOT ENOUGH. It leaves **13 -> 14 at 13.0 s** (step #2 —
    still settling) as the runner-up: a mere 1.54x margin. (v1's spec claimed the runner-up was 8 s.
    Measured, that was wrong.)

    ⇒ SO THE RULE IS PHYSICAL, NOT A HACK ON THE FIRST STEP. A real break is the stage driving back
    to re-scan the same tissue, so it must (a) be far larger than any within-scan step, and (b)
    **SPLIT THE RUN INTO TWO SUBSTANTIAL HALVES**. Candidates are therefore restricted to steps with
    at least `MIN_SIDE_FRAC` of the trials on each side. That guard excludes the whole settling
    prefix — 11->12 AND 13->14 — *for a reason* rather than by special case, and it leaves the true
    runner-up at 234->235 = 8.0 s: a clean **2.5x** margin. (The block's first step is dropped
    explicitly as well, belt-and-braces.)

    ⚠️ Validated on **n = 1 dataset**. It is always a PROPOSAL and it must always be overridable —
    show the number, put `why_detail` behind the `?`.

    `trials` — the caller's ACTUAL selection, used only to count `n_before`/`n_after`. Pass it.
    Omitting it counts every snapshot in range, including ones the caller's own gate dropped.
    """
    # Snapshot trials inside [lo, hi], in acquisition order, with their timestamps.
    # ⚠️ Trials a caller's gate would drop (an off-shape frame) ARE included here: they are still
    # acquisition EVENTS, and this is a rule about when the STAGE moved. Dropping them fabricates
    # gaps that were never pauses.
    snaps = [e for e in entries if e.type == SNAPSHOT and lo <= e.trial <= hi and e.dt is not None]
    snaps.sort(key=lambda e: e.trial)

    steps = [
        (a.trial, round((b.dt - a.dt).total_seconds(), 1))  # type: ignore[operator]
        for a, b in zip(snaps, snaps[1:])
    ]  # (after_trial, gap_s)
    median_gap = float(np.median([g for _, g in steps])) if steps else 0.0

    # the candidate window: drop the block's first step, and require a substantial side on each side
    m = max(1, int(round(MIN_SIDE_FRAC * len(steps))))
    interior = [s for i, s in enumerate(steps) if i >= max(1, m) and i < len(steps) - m]

    keep = [e.trial for e in snaps] if trials is None else list(trials)

    if not interior:
        return TimingSplit(
            value=None,
            detected=False,
            why=f"only {len(steps)} steps — too few to split. Assuming one scan.",
            why_detail=(
                f"A break must have at least {MIN_SIDE_FRAC:.0%} of the run on each side of it, and "
                f"this run has only {len(steps)} inter-trial steps, so no candidate qualifies. "
                f"Treating it as a SINGLE scan. Override if that is wrong."
            ),
            gap_s=None,
            median_gap_s=median_gap,
            runner_up=None,
            n_before=len(keep),
            n_after=0,
            decisive=False,
        )

    ranked = sorted(interior, key=lambda s: -s[1])
    after, gap = ranked[0]
    runner = ranked[1] if len(ranked) > 1 else None
    first_after, first_gap = steps[0]

    decisive = gap > 2.0 * median_gap and (runner is None or gap >= 2.0 * runner[1])
    why = f"{gap:g} s pause at {after}→{after + 1} (median {median_gap:g} s)"
    detail = (
        f"Largest interior inter-trial gap: {after}->{after + 1} is {gap:g} s, against a median step "
        f"of {median_gap:g} s — the stage driving back to the origin to re-scan the same tissue. "
        f"Candidates are restricted to steps with >= {MIN_SIDE_FRAC:.0%} of the run on each side, "
        f"which excludes the settling prefix: the block's first step ({first_after}->"
        f"{first_after + 1}) is also {first_gap:g} s and would tie a naive max-gap rule. `value` is "
        f"the LAST TRIAL BEFORE THE BREAK, not the first one after it."
    )
    if not decisive:
        why += " — NOT DECISIVE, check it"
        detail += (
            f" ⚠️ NOT DECISIVE: the runner-up ({runner[0]}->{runner[0] + 1}, {runner[1]:g} s) is "  # type: ignore[index]
            f"within 2x of the winner. This rule is validated on one dataset. Check it and override "
            f"it if it is wrong."
        )

    n_before = sum(1 for t in keep if t <= after)
    return TimingSplit(
        value=after,
        detected=True,
        why=why,
        why_detail=detail,
        gap_s=gap,
        median_gap_s=median_gap,
        runner_up=runner,
        n_before=n_before,
        n_after=len(keep) - n_before,
        decisive=decisive,
    )


# =============================================================================
# THE DATASET
# =============================================================================
@dataclass(frozen=True)
class Dataset:
    """One acquisition directory, described. **Frozen: a description of raw data cannot be edited.**

    It holds no pixels (that is `core.frames.FrameStore`), no analysis state, and no opinion. It is
    what the browser renders a card from and what a session is opened on.
    """

    path: Path  # RESOLVED. The identity.
    name: str  # the directory's basename — a label a human typed. NOTHING may branch on it.
    experiment: str  # log.txt's `New experiment:` name — the acquisition's record of ITSELF.
    entries: tuple[LogEntry, ...]  # every trial in log.txt, of any type, in file order
    snapshots: dict[int, dict]  # {trial: meta} — the raw disk inventory (read_trial_meta + "dat")
    #: What the user MUST see about how this loaded. Keep them SHORT. ⛔ A warning is not an
    #: exclusion: nothing in the app acts on one.
    warnings: tuple[str, ...] = ()
    scanned_at: str = field(default_factory=_now)

    # --- identity ---------------------------------------------------------------------------
    @property
    def key(self) -> str:
        """`store_key(self.path)` — basename + sha1 of the resolved directory. See `store_key`."""
        return store_key(self.path)

    # --- the trials -------------------------------------------------------------------------
    @property
    def trials(self) -> list[int]:
        """Every trial in log.txt, of any type, in acquisition order."""
        return [e.trial for e in self.entries]

    @property
    def snapshot_trials(self) -> list[int]:
        """Every trial log.txt calls a Snapshot. ⛔ Not gated on shape and not gated on anything
        else: an off-shape or unreadable trial is still a snapshot the microscope took."""
        return sorted(e.trial for e in self.entries if e.type == SNAPSHOT)

    @property
    def readable_trials(self) -> list[int]:
        """Every genuine 1-frame snapshot actually on disk, of ANY shape. The inventory's keys."""
        return sorted(self.snapshots)

    def entry(self, trial: int) -> LogEntry | None:
        return next((e for e in self.entries if e.trial == trial), None)

    def meta(self, trial: int) -> dict:
        """The frame metadata `core.frames.load_frame()` wants. KeyError -> 404: not on disk."""
        return self.snapshots[trial]

    def blocks(self) -> list[tuple[int, int]]:
        return snapshot_blocks(self.entries)

    def longest_block(self) -> tuple[int, int]:
        return longest_block(self.blocks())

    def shape_groups(self) -> list[dict]:
        """Snapshot trials grouped by frame shape, biggest group first.

        ⛔ Core **reports** shapes; it does not gate on one. "512x512 only" is the mosaic feature's
        policy (512 is `t33.TILE`), and a future feature may happily take the 512x128 frame that
        mosaic must refuse.
        """
        groups: dict[tuple[int, int], list[int]] = {}
        for t, m in sorted(self.snapshots.items()):
            groups.setdefault((int(m["w"]), int(m["h"])), []).append(t)
        return [
            {"w": w, "h": h, "n": len(ts), "trials": ts}
            for (w, h), ts in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        ]

    def timing_split(
        self, lo: int | None = None, hi: int | None = None, trials: Sequence[int] | None = None
    ) -> TimingSplit:
        """The timing split over `[lo, hi]` (default: the longest snapshot block). See
        `detect_timing_split` — and note that naming it a "pass split" is the mosaic feature's job,
        not core's."""
        if lo is None or hi is None:
            blo, bhi = self.longest_block()
            lo = blo if lo is None else lo
            hi = bhi if hi is None else hi
        return detect_timing_split(self.entries, lo, hi, trials)

    def gaps(self, trials: Iterable[int] | None = None) -> list[tuple[int, int]]:
        """Acquisition gaps in a trial list — `engine.excluded.gaps`, the one implementation."""
        return gaps(self.snapshot_trials if trials is None else trials)

    # --- read-only, enforced ----------------------------------------------------------------
    def refuse_write(self, target: str | os.PathLike[str]) -> None:
        """⛔ Raise `DatasetIsReadOnly` if `target` is inside this dataset. Every writer calls this."""
        refuse_write(target, [self.path])

    def contains(self, target: str | os.PathLike[str]) -> bool:
        return is_inside(target, self.path)

    # --- the wire ---------------------------------------------------------------------------
    def log_json(self) -> dict:
        """`LogResponse`."""
        return log_json(self.experiment, self.entries)

    def trial_rows(self) -> list[dict]:
        """`list[TrialMeta]` — the log line and the XML, merged, one row per trial.

        Trials with no readable frame on disk still get a row (with `w`/`h`/`dat` null). ⛔ The
        browser shows everything the microscope recorded; it hides nothing and it judges nothing.
        """
        rows: list[dict] = []
        seen: set[int] = set()
        for e in self.entries:
            seen.add(e.trial)
            rows.append(self._row(e.trial, e.type, e.time, e.gap_s))
        for t in sorted(set(self.snapshots) - seen):  # on disk, but not in log.txt
            rows.append(self._row(t, "", self.snapshots[t].get("time") or None, None))
        rows.sort(key=lambda r: r["trial"])
        return rows

    def _row(self, trial: int, ttype: str, time: str | None, gap_s: float | None) -> dict:
        m = self.snapshots.get(trial, {})
        dat = m.get("dat")
        return {
            "trial": trial,
            "type": ttype,
            "time": time,
            "gap_s": gap_s,
            "w": m.get("w"),
            "h": m.get("h"),
            "dtype": m.get("dtype"),
            "bytes": m.get("bytes"),
            "flip_x": m.get("flip_x"),
            "flip_y": m.get("flip_y"),
            "dat": Path(dat).name if dat else None,
        }

    def summary(
        self,
        *,
        thumbnail_url: str | None = None,
        analyses: Sequence[dict] = (),
        last_opened: str | None = None,
    ) -> dict:
        """`DatasetSummary` — one card in the browser, with no pixel loaded."""
        return {
            "key": self.key,
            "name": self.name,
            "path": self.path.as_posix(),  # forward slashes on the wire, on every OS
            "experiment": self.experiment,
            "n_trials": len(self.entries),
            "n_snapshots": len(self.snapshot_trials),
            "first_at": self.entries[0].time if self.entries else None,
            "last_at": self.entries[-1].time if self.entries else None,
            "shapes": self.shape_groups(),
            "thumbnail_url": thumbnail_url,
            "analyses": list(analyses),
            "last_opened": last_opened,
            "warnings": list(self.warnings),
        }

    def detail(self, **kw) -> dict:
        """`DatasetDetail` — everything sayable about a dataset without loading a pixel."""
        return {
            "summary": self.summary(**kw),
            "trials": self.trial_rows(),
            "blocks": [{"lo": a, "hi": b, "n": b - a + 1} for a, b in self.blocks()],
        }


def _looks_like_a_dataset(d: Path) -> bool:
    """A `log.txt` and at least one `NNN.xml`. Cheap: it does not parse anything."""
    if not (d / "log.txt").is_file():
        return False
    return next(d.glob(_XML_GLOB), None) is not None


def open_dataset(path: str | os.PathLike[str]) -> Dataset:
    """Open a dataset directory: parse `log.txt`, inventory the trial XMLs. **No pixels.** ~0.2 s.

    ⛔ Read-only. It opens `log.txt` and the `NNN.xml` files for READING and touches nothing else —
    it does not create a cache, a marker, a thumbnail or a `.camea` anything inside the folder.

    Raises `FileNotFoundError` (no directory / no log.txt) or `ValueError` (no readable snapshot).
    """
    d = Path(path).expanduser()
    if not d.is_dir():
        raise FileNotFoundError(f"no such directory: {d}")
    d = d.resolve()

    log_path = d / "log.txt"
    if not log_path.is_file():
        raise FileNotFoundError(f"no log.txt in {d} — this is not a dataset directory")
    experiment, entries = parse_log(log_path)

    snaps = list_snapshots(d)
    if not snaps:
        raise ValueError(f"no readable 1-frame snapshots in {d}")

    warnings: list[str] = []
    # log.txt says Snapshot, but there is no readable 1-frame .dat/.xml pair on disk. That is a fact
    # about the directory the user is entitled to see — it is NOT an exclusion and NOTHING acts on it.
    missing = [t for t in (e.trial for e in entries if e.type == SNAPSHOT) if t not in snaps]
    if missing:
        shown = ", ".join(str(t) for t in missing[:10]) + (" …" if len(missing) > 10 else "")
        warnings.append(
            f"{len(missing)} snapshot trial(s) in log.txt have no readable frame on disk: {shown}"
        )
    orphans = sorted(set(snaps) - {e.trial for e in entries})
    if orphans:
        shown = ", ".join(str(t) for t in orphans[:10]) + (" …" if len(orphans) > 10 else "")
        warnings.append(f"{len(orphans)} frame(s) on disk have no log.txt line: {shown}")

    return Dataset(
        path=d,
        name=d.name,
        experiment=experiment,
        entries=tuple(entries),
        snapshots=snaps,
        warnings=tuple(warnings),
    )


#: `camea.core.dataset.open(path)` reads well from the outside; `open_dataset` is the honest name and
#: is what this module uses internally. Both are the same function. (Defined last, so nothing above
#: can shadow the builtin by accident.)
open = open_dataset  # noqa: A001


# =============================================================================
# DISCOVERY — the user points at a folder; we find the datasets under it
# =============================================================================
@dataclass(frozen=True)
class ScanResult:
    root: Path
    datasets: list[Dataset]
    skipped: list[dict]  # [{"path": str, "reason": str}] — looked like one, could not be read


#: ⏱️ The two stages `scan` reports, and they are **not** interchangeable (BEHAVIOUR R48.9). The
#: WALK has no denominator until it returns — the tree's breadth is the user's disk — so it counts
#: up ("14 datasets so far") and offers no estimate. The OPENS do: every candidate found is ~0.2 s
#: of `log.txt` + XML, so `i / n` is a real fraction and the bar is a real bar.
SCAN_WALK = "scan_dirs"
SCAN_OPEN = "open_datasets"


def scan(root: str | os.PathLike[str], depth: int = 3,
         progress: Callable[[str, int, int], None] | None = None,
         cancel: Any = None) -> ScanResult:
    """Find the datasets under a folder **the USER pointed at**. Read-only; no pixels; ~0.2 s each.

    `depth` is how many directory levels below `root` to look (1 = `root` itself only). A directory
    that *is* a dataset is not descended into.

    ⛔ Nothing here recognises a dataset by name, and nothing is skipped for being "the wrong one".
    A folder is a dataset iff it has a `log.txt` and at least one `NNN.xml`. That is the whole rule.

    ⏱️ `progress(stage, done, total)` is called with `SCAN_WALK` (`total = 0` — there is no
    denominator yet) while the tree is being walked, and with `SCAN_OPEN` once the candidates are
    known and each is being read. `cancel` is polled at both boundaries.

    ⭐ **THE WALK AND THE OPENS ARE NOW TWO PASSES, DELIBERATELY.** They used to be one — `walk`
    opened each dataset the moment it recognised it — which meant the expensive half had no total
    to divide by even after every candidate was known. Collecting the paths first costs one extra
    `_looks_like_a_dataset` per directory (a `stat` and a `glob`) and buys an honest bar.
    """
    r = Path(root).expanduser()
    if not r.is_dir():
        raise FileNotFoundError(f"no such directory: {r}")
    r = r.resolve()

    candidates: list[Path] = []
    found: list[Dataset] = []
    skipped: list[dict] = []

    def walk(d: Path, level: int) -> None:
        check_cancelled(cancel, "scan")
        # ⏱️ Per DIRECTORY, not per dataset found: a walk of ten thousand folders holding nothing
        # would otherwise report nothing at all, and a count-up that never counts is the blank slot
        # R48.4 was written against. `total` is 0 — there is no denominator here and there will not
        # be one until this returns.
        if progress is not None:
            progress(SCAN_WALK, len(candidates), 0)
        if _looks_like_a_dataset(d):
            candidates.append(d)
            if progress is not None:
                progress(SCAN_WALK, len(candidates), 0)
            return  # a dataset does not contain another dataset
        if level >= depth:
            return
        try:
            children = sorted(c for c in d.iterdir() if c.is_dir())
        except OSError as e:
            skipped.append({"path": d.as_posix(), "reason": str(e)})
            return
        for c in children:
            if c.name.startswith((".", "$")):
                continue
            walk(c, level + 1)

    walk(r, 1)

    n = len(candidates)
    for i, d in enumerate(candidates):
        check_cancelled(cancel, "scan")
        if progress is not None:
            progress(SCAN_OPEN, i, n)
        try:
            found.append(open_dataset(d))
        except (OSError, ValueError) as e:
            skipped.append({"path": d.as_posix(), "reason": str(e)})
    if progress is not None:
        progress(SCAN_OPEN, n, n)

    found.sort(key=lambda ds: ds.name)
    return ScanResult(root=r, datasets=found, skipped=skipped)
