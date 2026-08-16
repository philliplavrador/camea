"""The shelf — putting a MaxWell recording on a project, and pulling a copy of it in behind.

⭐ **HIS ANSWER, 2026-08-14, AND EVERYTHING HERE IS SHAPED BY IT:** *"reference it until the copy is
finished."* A recording is **usable the instant it is added** — read from wherever it sits on his
disk — and a background job pulls a copy into the project. When the copy lands, every later read
uses the project's own copy. Neither half on its own was acceptable to him and both reasons are
real: these files are gigabytes, so a blocking copy would make importing feel broken; and a
permanent reference would let a moved folder silently gut a project.

⛔ **THE SOURCE IS OPENED READ-ONLY AND IS NEVER MODIFIED OR MOVED.** This is the first thing in
Camea that copies *from* the 35 GB mirror, and the only file handle it ever takes on the user's own
data is `open(src, "rb")`. The copy is written into `<project>/recordings/<id>/` (R44) and nowhere
else; `core.workspace.refuse_write` is asked about the destination anyway, on the way past.

⛔ **AND NOTHING ABOUT WHAT IS IN A RECORDING IS EVER WRITTEN DOWN** (I1). The document keeps a
path, an id, and where the bytes currently are. Duration, channel count, spike count are read off
the file every time they are asked for (:func:`facts_of`). A cached channel count is dataset
knowledge with a timestamp on it, and it goes stale the first time a file changes under us.

---------------------------------------------------------------------------------------------
⭐ **`open_path` IS THE ONE PLACE THAT DECIDES WHICH FILE TO READ.**
---------------------------------------------------------------------------------------------
Source or the project's copy — one function answers it, for the shelf and for everything plan 003
adds (the layout, the activity tally, the trace). ⚠️ Three routes each deciding for themselves is
exactly how one of them ends up reading a stale copy while another reads the original, and the
symptom would be two screens disagreeing about the same recording.

---------------------------------------------------------------------------------------------
🔴 **THE STATE ON THE SHELF IS DERIVED, NOT TRUSTED.**
---------------------------------------------------------------------------------------------
`copy_state` in the document is the **last known** state. What :func:`shelf_entry` reports is worked
out from the disk and the job registry:

  * the copy is on disk           -> `stored`   (self-healing: a finished copy always reads as one)
  * a copy job for it is live     -> `copying`, with that job's percentage
  * the document says it failed   -> `failed`, with the reason, and it still reads the original
  * otherwise                     -> `referenced`

⚠️ **This is what a mid-copy restart needs.** The document would say `copying` for ever, because the
job that was going to change it died with the process. Derived, it reports `referenced` — which is
true, and which is a fully working recording rather than a stuck progress bar. (The half-written
`.part` file is left in the project's own folder and goes when the recording or the project does.)

---------------------------------------------------------------------------------------------
🔴 **EVERY DOCUMENT WRITE HERE IS UNDER `_DOC_LOCK`, AND IT IS NOT DECORATION.**
---------------------------------------------------------------------------------------------
Adding several recordings starts several copy jobs, and each one flips **its own** entry to
`stored` by load → change → save. `atomic_write_text` makes each *write* safe; it does nothing about
two jobs having read the same document a millisecond apart, in which case the second save silently
drops the first's flip and a recording that finished copying reports as `referenced` for ever. The
lock covers read-modify-write, which is the operation that actually has to be atomic.
"""

from __future__ import annotations

import os
import shutil
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np

from camea.core import jobs as core_jobs
from camea.core import mearecording as mr
from camea.core import workspace as core_workspace

#: The job kind for one recording's copy. `api.schemas.MeaCopyResult` discriminates on it.
COPY_JOB_KIND = "mea_copy"

#: The job kind for one recording's whole-recording envelope. `api.schemas.MeaEnvelopeResult`
#: discriminates on it.
ENVELOPE_JOB_KIND = "mea_envelope"

#: 8 MiB. Big enough that a multi-GB copy is not a syscall storm, small enough that cancel is felt
#: within a moment and the percentage moves visibly on a file of any size.
_CHUNK = 8 * 1024 * 1024

#: How many recordings one browse may list. A folder of thousands is a wrong turn, not a workload —
#: the UI says the list was cut rather than pretending it is all of them.
BROWSE_LIMIT = 200

#: ⏱️ How often the copy says where it has got to. At the 184 MB/s he gets off the SSD an 8 MiB
#: chunk lands 23 times a second, and a progress message per chunk is 23 lines a second into a
#: 200-line log tail for a number no client reads faster than every 2 s (R48: emit where the counter
#: advanced, at a cadence a human can read).
_COPY_SAY_EVERY_S = 0.2

_DOC_LOCK = threading.RLock()

#: `recording id -> job id` for the copies this process started. ⚠️ **Deliberately not persisted.**
#: It is a handle on a *running* job, and a job does not survive the process; the shelf falls back
#: to what is on disk, which is the durable answer. See the module docstring.
_COPY_JOBS: dict[str, str] = {}

#: `recording id -> job id` for the envelope builds this process started. Same reasoning as
#: `_COPY_JOBS`: a handle on a running job, never persisted. The durable answer is whether
#: `envelope.npz` is on disk and loads.
_ENVELOPE_JOBS: dict[str, str] = {}


def shown_name(path: str | Path) -> str:
    """What a refusal calls this file. ⭐ `parent.name` too when it is the MaxLab `data.raw.h5`:
    every recording on his disk is called that, so the run folder is the only part of the name
    that identifies one."""
    p = Path(str(path).replace("\\", "/"))
    return f"{p.parent.name}/{p.name}" if p.name == mr.MEA_FILENAME else p.name


class NotARecording(Exception):
    """This file cannot go on the shelf. ⭐ Carries the path so the refusal can NAME it — a file
    silently dropped from an import is the failure this plan calls out by name.

    ⚠️ **The sentence and the reason are separate on purpose.** `str(e)` is the one line he reads —
    *"notes.jpg is not a MaxLab recording"* — and `.reason` is the technical tail (h5py's *"file
    signature not found"*, a refused chip geometry) that goes in the error envelope's `detail` and
    on the greyed row of the tick-list. Splicing the tail into the sentence gives him a parenthesis
    about HDF5 signatures in the middle of a refusal about a file he can see on his desk.

    ⭐ **AND THE SENTENCE MAY BE OVERRIDDEN, because "is not a MaxLab recording" is sometimes a
    lie** (issues 007/008). A real ActivityScan and a real Network file whose chip layout cannot
    be derived are both genuine MaxLab files this shelf refuses — each gets a sentence that says
    what is actually true, through `sentence=`, while the default stays what it always was for the
    JPEG someone renamed.
    """

    def __init__(self, path: str | Path, reason: str = "", sentence: str = "") -> None:
        self.path = str(path).replace("\\", "/")
        self.reason = reason
        self.shown = shown_name(self.path)
        super().__init__(sentence or f"{self.shown} is not a MaxLab recording")


# =================================================================================================
# Reading a file — the facts, every time, never remembered
# =================================================================================================


def facts_of(path: str | Path) -> dict:
    """Header facts for one `data.raw.h5`. -> `{label, run_id, assay, duration_s, ...}`.

    Raises :class:`NotARecording` for anything this reader cannot work with — a JPEG someone
    renamed, a truncated file, an HDF5 file with no `data_store` group. ⛔ It never returns a
    half-filled dict: a row of blanks on the screen reads as a bug in Camea rather than as a fact
    about the file.

    ⭐ **IT TOUCHES THE MAPPING TOO, AND THAT IS ISSUE 008'S FIX.** The chip's geometry is derived
    in `mapping()`, and `derive_geometry` refuses by design for real cases it cannot explain —
    every routed pad on one array row, a non-integer stride. Before this, such a file imported
    cleanly and refused one click later, on Open; now one function decides "is this a recording
    Camea can work with" and the answer is the same at every door. The tick-list still LISTS the
    file (`candidates` catches this and greys the row) — refused at the door is not dropped from
    the list.

    ⭐ **AND A GENUINE MaxLab FILE IS NEVER CALLED NOT-A-RECORDING** (issue 007). A spike-only
    ActivityScan and an underivable layout each get a sentence saying what is actually true;
    "is not a MaxLab recording" is kept for files that genuinely are not.

    ⚠️ It does **not** touch the raw stream, so it works on every machine, decoder or no decoder
    (`utils/knowledge/mea-recordings.md`).
    """
    p = Path(path)
    if not p.is_file():
        raise NotARecording(p, "there is no file there")
    try:
        with mr.MeaRecording(p) as rec:
            i = rec.info()
            try:
                rec.mapping()                            # the chip too, so a bad file fails HERE
            except mr.MeaError as e:
                raise NotARecording(
                    p, str(e),
                    sentence=f"Camea cannot work out the chip layout for {shown_name(p)}: {e}",
                ) from e
            return {
                "label": i.label,
                "run_id": i.run_id,
                "assay": i.assay,
                "duration_s": round(i.duration_s, 3),
                "n_channels": i.n_channels,
                "n_samples": i.n_samples,
                "n_spikes": i.n_spikes,
            }
    except NotARecording:
        raise                                            # already carries its honest sentence
    except mr.UnsupportedAssay as e:
        # ⭐ Issue 007: it IS a MaxLab file. Say what it is — the reader already read the file's
        # own declaration — instead of the lie the generic arm would produce.
        raise NotARecording(p, str(e),
                            sentence=f"{shown_name(p)} is {e}") from e
    except mr.MeaError as e:
        raise NotARecording(p, str(e)) from e
    except Exception as e:                                   # noqa: BLE001
        # h5py raises OSError on a file that is not HDF5 at all, and KeyError/ValueError on one
        # whose groups are not where a MaxLab file puts them. All of them mean the same thing to
        # the user, and all of them must be a refusal by name rather than a 500.
        raise NotARecording(p, f"{type(e).__name__}: {e}") from e


def candidates(root: str | Path, *, limit: int = BROWSE_LIMIT) -> tuple[list[dict], bool]:
    """Every `data.raw.h5` under `root`, as tick-list rows. -> `(rows, truncated)`.

    ⭐ **A file that does not open is LISTED, not dropped** (`readable: false` + why). Dropping it
    would make the folder look emptier than it is, and the one thing worse than a refusal is a
    refusal you never saw.

    ⛔ Reads only. This is the route that runs *before a project exists*, so it has nothing to write
    into and must never acquire one "for consistency".
    """
    found = mr.find_recordings(root, limit=limit + 1)
    truncated = len(found) > limit
    rows: list[dict] = []
    for p in found[:limit]:
        row: dict[str, Any] = {
            "path": p.as_posix(),
            "bytes": _size(p),
            "readable": True,
            "problem": "",
            "label": "",
            "run_id": "",
            "assay": "",
            "duration_s": None,
            "n_channels": None,
            "n_spikes": None,
        }
        try:
            f = facts_of(p)
        except NotARecording as e:
            row["readable"] = False
            row["problem"] = e.reason or "this file is not a MaxLab recording"
            # ⚠️ Still give it a label, or the row is a bare path in a list of names.
            row["label"] = p.parent.name
        else:
            row.update({k: f[k] for k in ("label", "run_id", "assay", "duration_s",
                                          "n_channels", "n_spikes")})
        rows.append(row)
    return rows, truncated


def _size(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return 0


# =================================================================================================
# Putting one on the shelf
# =================================================================================================


def new_id() -> str:
    """`rec_3f9a2c`. ⛔ Minted, never derived from the path: he may add the same file twice, and the
    project's copy of each has to live somewhere that cannot collide."""
    return f"rec_{uuid.uuid4().hex[:6]}"


def record_for(path: str | Path) -> dict:
    """One document entry for `path`, as `referenced`. Raises :class:`NotARecording`.

    ⛔ It writes nothing and starts nothing — the caller decides whether this entry is going into a
    document at all. That is what lets `POST /api/mea/projects` validate every path **before** it
    creates the project, so a bad file means no project rather than an unusable one.
    """
    p = Path(path).expanduser()
    f = facts_of(p)
    return {
        "id": new_id(),
        "label": f["label"],
        "run_id": f["run_id"],
        "assay": f["assay"],
        "source_path": p.as_posix(),
        "stored_path": "",
        "copy_state": "referenced",
        "copy_error": "",
        "bytes": _size(p),
        "added": core_workspace._iso(),
    }


def open_path(project_dir: str | Path, rec: Mapping) -> Path | None:
    """⭐ **WHICH FILE TO READ FOR THIS RECORDING** — the project's copy if it is there, else the
    original. `None` when neither is: that is the *"this recording is no longer where you left it"*
    case, and it must be said on the shelf rather than turned into an empty row.

    ⚠️ **ONE implementation, and plan 003's layout/activity/trace routes call this one too.** Three
    routes each deciding for themselves is how one ends up on the copy while another is on the
    original, and the symptom is two screens disagreeing about the same recording.
    """
    stored = str(rec.get("stored_path") or "")
    if stored:
        p = Path(project_dir) / stored
        if p.is_file():
            return p
    src = str(rec.get("source_path") or "")
    if src:
        sp = Path(src)
        if sp.is_file():
            return sp
    return None


def shelf_entry(project_dir: str | Path, rec: Mapping) -> dict:
    """One document entry -> the row the shelf shows. **Derived from disk + the job registry.**

    See the module docstring for why the document's own `copy_state` is not simply echoed back.
    """
    project_dir = Path(project_dir)
    rid = str(rec.get("id") or "")
    stored = str(rec.get("stored_path") or "")
    stored_here = bool(stored) and (project_dir / stored).is_file()

    state = "referenced"
    pct = 0.0
    error = str(rec.get("copy_error") or "")
    if stored_here:
        state = "stored"
        error = ""
    else:
        job = _live_copy_job(rid)
        if job is not None:
            state, pct = "copying", float(job.to_json().get("pct") or 0.0)
        elif str(rec.get("copy_state") or "") == "failed":
            state = "failed"

    path = open_path(project_dir, rec)
    # ⭐ **STAT'ED NOW, NEVER CACHED FROM IMPORT TIME.** An unplugged drive comes back, and a
    # recording that quietly kept claiming his file was gone would put a confirm box in front of a
    # remove that destroys nothing. See `shelf_entry`'s caller and `RecordingShelf.tsx`.
    src = str(rec.get("source_path") or "")
    source_present = bool(src) and Path(src).is_file()
    out: dict[str, Any] = {
        "id": rid,
        "label": str(rec.get("label") or ""),
        "run_id": str(rec.get("run_id") or ""),
        "assay": str(rec.get("assay") or ""),
        "source_path": str(rec.get("source_path") or ""),
        "stored_path": stored if stored_here else "",
        "copy_state": state,
        "copy_pct": round(pct, 1),
        "copy_error": error,
        "added": str(rec.get("added") or ""),
        "bytes": int(rec.get("bytes") or 0),
        "missing": path is None,
        "source_present": source_present,
        "duration_s": None,
        "n_channels": None,
        "n_samples": None,
        "n_spikes": None,
    }
    if path is None:
        return out
    try:
        f = facts_of(path)
        # ⭐ **ONLY THE MEASUREMENTS COME OFF THE FILE HERE.** `label`/`run_id`/`assay` stay as the
        # document recorded them at import, because a MaxLab file names itself partly by the folders
        # holding it (`<assay>/<run>/data.raw.h5`) — and once we have copied it into
        # `recordings/<id>/` those folders are OURS. Re-deriving would rename `Network/000690` to
        # `recordings/rec_3f9a2c` the moment the copy landed, i.e. the row would change its name
        # under him for no reason he could see. Identity is recorded once, from where it came from;
        # duration, channels and spikes are read every time.
        out.update({k: f[k] for k in ("duration_s", "n_channels", "n_samples", "n_spikes")})
        for k in ("label", "run_id", "assay"):
            if not out[k]:
                out[k] = f[k]
    except NotARecording:
        # ⚠️ The file is there and no longer reads. That is not `missing` — it is a file that has
        # changed under him — but the honest rendering is the same: no numbers, and a row that says
        # so instead of showing zeros that look like a silent chip.
        out["missing"] = True
    out["bytes"] = _size(path) or out["bytes"]
    return out


def shelf(project_dir: str | Path, doc: Mapping) -> list[dict]:
    """Every row of one project's shelf, in the order they were added."""
    recs = doc.get("recordings")
    return [shelf_entry(project_dir, r) for r in (recs if isinstance(recs, list) else [])
            if isinstance(r, Mapping)]


def _live_copy_job(recording_id: str) -> core_jobs.Job | None:
    jid = _COPY_JOBS.get(recording_id)
    if not jid:
        return None
    j = core_jobs.JOBS.get(jid)
    if j is None or j.state not in ("queued", "running"):
        return None
    return j


# =================================================================================================
# The copy — one job per recording
# =================================================================================================
#
# ⭐ **PER RECORDING, NOT PER IMPORT** (plan 002 § Open asked; this is the answer and the reason).
# The shelf shows a percentage against each row, which a single job for the whole batch could only
# report as one number for all of them — and the rows finish at wildly different times, because the
# files are wildly different sizes. It also means one unreadable or vanished source fails ONE row
# and leaves the others copying, instead of taking the batch down with it.
#
# A thread job, not a process: `shutil` is interruptible at every chunk boundary, so cancel is
# cooperative and there is nothing here that would OOM a GPU. No lease — copies are I/O and may
# happily run beside each other and beside a mosaic build.


def start_copy(project_dir: str | Path, analysis_id: str, rec: Mapping,
               save: Callable[[str, dict], None]) -> str | None:
    """Start the background copy for one recording. -> the job id, or `None` if there is nothing
    to do (the copy is already there, or the source has vanished).

    `save(recording_id, changes)` is how the job writes its outcome back into the document — passed
    in rather than reached for, so this module never learns what a `ProjectSet` is.
    """
    project_dir = Path(project_dir)
    rid = str(rec.get("id") or "")
    if not rid:
        return None
    dest = project_dir / core_workspace.RECORDINGS / rid / mr.MEA_FILENAME
    if dest.is_file():
        save(rid, {"stored_path": _rel(project_dir, dest), "copy_state": "stored",
                   "copy_error": ""})
        return None
    src = Path(str(rec.get("source_path") or ""))
    if not src.is_file():
        save(rid, {"copy_state": "failed",
                   "copy_error": "the original is not where it was when it was added"})
        return None

    def fn(report, cancel) -> dict:
        n = _copy_file(src, dest, report=report, cancel=cancel)
        save(rid, {"stored_path": _rel(project_dir, dest), "copy_state": "stored",
                   "copy_error": "", "bytes": n})
        return {"kind": COPY_JOB_KIND, "analysis_id": analysis_id, "recording_id": rid,
                "stored_path": _rel(project_dir, dest), "bytes": n}

    def guarded(report, cancel) -> dict:
        try:
            return fn(report, cancel)
        except core_jobs.Cancelled:
            raise
        except Exception as e:                               # noqa: BLE001
            # ⭐ The recording keeps working — it is read from the original — so a failed copy is a
            # line on its row, not a broken project. Record why, then let the job fail honestly.
            save(rid, {"copy_state": "failed", "copy_error": f"{type(e).__name__}: {e}"})
            raise

    # ⭐ The label is the plain words a refusal would name this job by ("…while copying a
    # recording in"). Forbidden-words rule (MAXWELL §7.5) applies to labels like any surface.
    job = core_jobs.JOBS.submit_thread(COPY_JOB_KIND, guarded, label="copying a recording in")
    _COPY_JOBS[rid] = job.job_id
    return job.job_id


# ── the whole-recording envelope ────────────────────────────────────────────────────────────────
#
# ⭐ **WHY THIS IS A JOB AND NOT A REQUEST.** `groups/routed/raw` is chunked across every channel, so
# reading ONE channel end to end decompresses ALL of them. Measured on his five recordings
# (2026-08-15): one channel 12-23 s; all 726-1015 channels 19-32 s, and 37-70 s once the exact health
# tally is included. A factor of 1.4 between one and all is why every channel is done in a single
# pass, and 37-70 s is why it cannot sit inside a GET.
#
# ⭐ **AND WHY IT IS BACKFILLED, NOT ONLY BUILT AT IMPORT.** His instruction, 2026-08-15: *"go ahead
# and run the loader on the MEAs I have already imported."* A precompute that only ran on the way in
# would leave every recording already in a project permanently without one.
#
# 🔴 R44: it is written to `<project>/recordings/<id>/`, beside the copy, and never to `outputs/` —
# `outputs/` is the panel he browses, and a cache is not something he asked Camea to make.


def envelope_path(project_dir: str | Path, rec: Mapping) -> Path:
    """Where this recording's envelope cache lives. **Always inside the project** (R44), even for a
    `referenced` recording whose `data.raw.h5` sits somewhere else entirely — the cache is Camea's,
    not his, so it goes where Camea's things go."""
    rid = str(rec.get("id") or "")
    return Path(project_dir) / core_workspace.RECORDINGS / rid / mr.ENVELOPE_FILENAME


def load_envelope_for(project_dir: str | Path, rec: Mapping) -> mr.Envelope | None:
    """This recording's envelope, or None when it has not been built (or was built by an older
    Camea). None is a cache miss, never an error."""
    return mr.load_envelope(envelope_path(project_dir, rec))


def envelope_version_on_disk(path: str | Path) -> int | None:
    """The `version` stamped in an envelope cache, **without materialising its arrays**.

    ⚠️ **THIS EXISTS BECAUSE ASKING `load_envelope` A YES/NO QUESTION COST 33 MB.** That builds a
    whole `Envelope` — every `lo`/`hi` row off the disk, 22-29 ms measured — and `has_envelope` threw
    all of it away to return a bool, once every 2 s **per recording**, while the backfill it reports
    was reading those same files. `np.load` on an `.npz` is lazy: opening it reads the zip's
    directory, and indexing one 8-byte member reads one 8-byte member.

    `None` = there is no cache, it will not open, or it stamps no version — all of which mean "not
    built" to every caller, exactly as `mr.load_envelope` returning None does.
    """
    try:
        with np.load(Path(path)) as z:
            return int(z["version"])
    except Exception:                                        # noqa: BLE001
        # As wide as `mr.load_envelope`'s catch, and for its reason: a cache truncated mid-write
        # reaches `zipfile.BadZipFile`, a plain `Exception`, and a cache miss must never become a
        # 500 on a screen whose whole job is to say "not read yet" honestly. Do not narrow it.
        return None


def _envelope_ready(path: Path) -> bool:
    """Is there a **current** envelope at `path`? 🔴 A cache written by an older Camea is NOT ready:
    `ENVELOPE_VERSION` is the whole reason a changed layout rebuilds instead of being reinterpreted,
    and answering yes here would serve the stale shape for ever. Same rule `mr.load_envelope`
    enforces by returning None — only without reading the arrays to find out.

    ⚠️ The one case this reads differently from a full load: an `.npz` that opens but whose *arrays*
    are corrupt now reports ready, and the trace's 409 says so rather than the backfill rebuilding
    it. `save_envelope` writes to `.part` and renames, so the file at this path is either whole or
    is not there at all — which is what makes that trade affordable."""
    return path.is_file() and envelope_version_on_disk(path) == mr.ENVELOPE_VERSION


def has_envelope(project_dir: str | Path, rec: Mapping) -> bool:
    """Can this recording be shown whole yet? **Polled every 2 s per recording** by the envelope
    status route — see `envelope_version_on_disk` for why that makes the cost of the answer matter
    more than the answer."""
    return _envelope_ready(envelope_path(project_dir, rec))


def live_envelope_job(recording_id: str) -> core_jobs.Job | None:
    """The envelope job running for this recording right now, if there is one."""
    jid = _ENVELOPE_JOBS.get(recording_id)
    if not jid:
        return None
    return core_jobs.JOBS.get(jid)


# ── one recording is read at a time, and the ones behind it say so ──────────────────────────────
#
# 🔴 **h5py SERIALISES THESE READS WHETHER OR NOT CAMEA DOES, SO CAMEA DOES IT HONESTLY.**
# `start_envelopes` submits one thread per recording, and h5py holds a global lock across the whole
# of each block read — so five of them do not finish five times sooner. They finish at the same wall
# clock with **five bars each crawling at a fifth of the speed**, and each bar's linear ETA is then a
# lie that revises *down* every time a sibling drops out. Measured 2026-08-16: one reader alone
# 0.96 s; three concurrent, 2.59 s each. Queued, every running ETA is the truth and every waiting one
# says it is waiting (R48.3/R48.4).
#
# ⚠️ **AND IT IS NOT `submit_thread(exclusive=...)`, DELIBERATELY.** The registry's lease does not
# queue — `JobRegistry._claim` raises `Busy` on the spot — so a lease here would let the backfill
# start ONE recording and refuse the other four, and `routes._start_copies` swallows that refusal, so
# four recordings would silently never get an envelope at all. `start_envelopes`' contract is *submit
# them all*; this turnstile keeps it and makes the queue visible instead of inventing a 409 nobody
# asked for.
#
# ⛔ **Interactive reads do NOT queue behind this.** A pad click reads a narrow window in ~0.5 s
# (`routes.get_mea_trace`); making that wait out a four-minute backfill would be a worse app than the
# one this fixes.

#: How often a waiting read looks up to see whether its turn has come. Short enough that Stop is felt
#: while it is still queued (R48.7), cheap enough to be free.
_TURN_POLL_S = 0.5

#: …and how often it says so. Every client that watches this polls at 2 s; talking faster than the
#: listener listens is churn in the log tail and nothing else.
_TURN_SAY_EVERY_S = 2.0

_READ_LOCK = threading.RLock()

#: `[recording id, file bytes]` for every envelope read waiting or running, oldest first — index 0 is
#: the one actually reading. ⚠️ Not persisted, same reasoning as `_COPY_JOBS`: it is a handle on
#: running work, and running work does not survive the process.
_READ_QUEUE: list[list] = []

#: Bytes of `data.raw.h5` per second, as measured by whichever read is running. It is what lets the
#: ones behind it estimate their own wait. ⛔ Not dataset knowledge: it is a property of this disk on
#: this run, re-measured from zero every time the app starts, and 0.0 means *nobody has measured yet,
#: so say nothing* rather than a guess.
_READ_BYTES_PER_S = 0.0


def _note_read_rate(nbytes: float, frac: float, elapsed_s: float) -> None:
    """Record what the running read is achieving, in bytes of source file per second."""
    global _READ_BYTES_PER_S
    if nbytes <= 0 or elapsed_s <= 0 or frac < core_jobs.ETA_MIN_FRACTION:
        return
    _READ_BYTES_PER_S = float(nbytes) * float(frac) / float(elapsed_s)


def _place_in_queue(entry: list) -> int:
    """How many reads are in front of `entry`; -1 once it has left the queue. ⚠️ Identity, never the
    recording id — `start_envelope` can in principle be raced into submitting two jobs for the same
    recording, and matching by id would put both of them at position 0, which is the exact
    trampling this queue exists to stop."""
    with _READ_LOCK:
        for i, q in enumerate(_READ_QUEUE):
            if q is entry:
                return i
    return -1


def _queued_eta(entry: list) -> float | None:
    """⏱️ Seconds until **this** read is finished, counted through everything in front of it.

    ⭐ The whole wait, not the wait until its turn. A countdown that reached zero as the turn came
    and then jumped back up to a full read would be counting down to the wrong event — he is waiting
    for his recording, not for a queue position.

    `None` until *something* has measured a read rate (the first read's first 2 %, a second or two).
    That is R48.4's case, not R48.9's: the client says *"working out how long this will take…"*
    beside a running elapsed clock, which is true and is what it is for.
    """
    with _READ_LOCK:
        idx = _place_in_queue(entry)
        if idx <= 0:
            return None                     # gone, or it IS the reader — its own progress says
        head, head_bytes = str(_READ_QUEUE[0][0]), float(_READ_QUEUE[0][1])
        # Everything from the one behind the reader up to and including this one: none of them has
        # started, so each still costs a whole read of its own file.
        not_started = [float(q[1]) for q in _READ_QUEUE[1:idx + 1]]
        rate = _READ_BYTES_PER_S
    if rate <= 0:
        return None
    job = live_envelope_job(head)
    p = job.progress if job is not None else None
    # 🔴 **ONLY A READ'S OWN ESTIMATE COUNTS, AND `phase` IS HOW WE KNOW IT IS ONE.** A job that has
    # just taken the turn is still carrying the `queued` Progress it emitted up to
    # `_TURN_SAY_EVERY_S` ago — whose eta included the read that has since FINISHED — and it keeps
    # carrying it until its own first block clears `ETA_MIN_FRACTION`. Borrowing that made every
    # waiter's countdown jump **UP** at each hand-over (measured: C 20.1 s -> 22.0 s against a truth
    # of 20.0 s), which is precisely the shape R48b exists to forbid, reached by a different road.
    # A head with nothing of its own to say is worth its file over the measured rate — which is also
    # why a waiter now keeps a number through the hand-over instead of blanking (R48.3).
    ahead_s = p.eta_s if p is not None and p.phase == "envelope" else None
    if ahead_s is None:
        ahead_s = head_bytes / rate
    return float(ahead_s) + sum(not_started) / rate


@contextmanager
def read_turn(recording_id: str, nbytes: int, cancel: Any,
              emit: Callable[..., None]) -> Iterator[None]:
    """Wait until this recording is the one being read, then hold the turn for the body.

    Public, and named without a leading underscore on purpose: this is the *app's* turnstile, not
    this module's. Any other whole-recording h5 read that ships — videomosaic builds an envelope of
    its own — must take the same turn, or the honesty this buys is undone by a job that queues
    against nothing.
    """
    entry: list = [str(recording_id), float(nbytes)]
    with _READ_LOCK:
        _READ_QUEUE.append(entry)
    try:
        said = 0.0
        while True:
            ahead = _place_in_queue(entry)
            if ahead <= 0:
                break
            core_jobs.check_cancelled(cancel, "envelope")     # R48.7 — stoppable while it waits, too
            now = time.monotonic()
            if now - said >= _TURN_SAY_EVERY_S:
                said = now
                # ⚠️ **This is not the heartbeat R48b forbids.** That one re-derives an ETA from a
                # PINNED `pct` and a growing elapsed, so it counts UP. This number is read off the
                # job in front and gets smaller every time that one advances; `pct` is not an input
                # to it at all, and there is genuinely new information at every emit.
                emit(phase="queued", pct=0.0, eta_s=_queued_eta(entry),
                     message=("waiting for the recording in front of it to be read"
                              if ahead == 1 else
                              f"waiting for {ahead} recordings in front of it to be read"))
            time.sleep(_TURN_POLL_S)
        yield
    finally:
        with _READ_LOCK:
            for i, q in enumerate(_READ_QUEUE):
                if q is entry:
                    del _READ_QUEUE[i]
                    break


def start_envelope(project_dir: str | Path, analysis_id: str, rec: Mapping, *,
                   n_buckets: int, force: bool = False) -> str | None:
    """Build one recording's envelope in the background. -> the job id, or `None` when there is
    nothing to do.

    `None` covers four honest cases, none of which is a failure: it is already built; a job for it is
    already running; the file is not where it was left; or the recording stores no continuous trace
    at all (an ActivityScan — a fact about the assay, not a broken file).
    """
    project_dir = Path(project_dir)
    rid = str(rec.get("id") or "")
    if not rid:
        return None
    live = live_envelope_job(rid)
    if live is not None and live.state in ("queued", "running"):
        return live.job_id
    dest = envelope_path(project_dir, rec)
    if not force and _envelope_ready(dest):
        return None
    path = open_path(project_dir, rec)
    if path is None:
        return None
    nbytes = _size(path)

    def fn(report, cancel) -> dict:
        emit = core_jobs.report_adapter(report)
        # 🔴 **THE FILE IS OPEN ONLY WHILE IT IS ACTUALLY BEING READ — the header peek closes before
        # the turnstile and the read re-opens after it.** ⚠️ Waiting for a turn with the handle still
        # open put a Windows share-lock on `data.raw.h5` for the whole queue: the fourth recording of
        # a backfill held one for minutes while reading nothing, so deleting the original — the very
        # thing a `stored` recording is supposed to survive — and `forget()`'s rmtree of the
        # project's own copy both failed with `WinError 32`. (Caught by
        # `test_a_stored_recording_survives_the_original_being_deleted` and
        # `test_all_three_routes_read_the_PROJECTS_OWN_COPY_once_it_has_landed`.) The second open
        # costs one header read, ~20 ms once per recording; the lock cost minutes of someone else's
        # file.
        with mr.MeaRecording(path) as opened:
            if opened.info().n_samples == 0:
                # No continuous trace was ever recorded. Nothing to reduce, and nothing wrong.
                # ⭐ Answered BEFORE it takes a turn: a recording with nothing to read must not sit
                # behind four that do in order to say so.
                return {"kind": ENVELOPE_JOB_KIND, "analysis_id": analysis_id,
                        "recording_id": rid, "built": False, "n_buckets": 0}

        # Turn first, THEN the handle — and on the way out the handle closes before the turn is
        # released, so the next in the queue never overlaps this one's open file.
        with read_turn(rid, nbytes, cancel, emit), mr.MeaRecording(path) as opened:
            t0 = time.monotonic()

            def on_progress(frac: float) -> None:
                core_jobs.check_cancelled(cancel, "envelope")
                elapsed = time.monotonic() - t0
                _note_read_rate(nbytes, frac, elapsed)
                # ⏱️ **R48.3 — THE COUNTABLE UNIT IS THE BLOCKS OF THE RAW STREAM ALREADY
                # DECOMPRESSED.** `build_envelope` calls this once per block with `k/n_buckets`,
                # and this read is one phase with nothing silent in it, so `frac` **is** the
                # overall fraction (R48.5) and the plain estimator is exactly right — no span
                # table, no weighting. Measured 2026-08-16 on a 1.64 GB file: 249 uniform
                # blocks, 0.208 s apart, elapsed at a quarter / half / three quarters =
                # 13.1 / 26.1 / 39.2 s of a 52 s read. This is the screenshot that said
                # "Reading…" with no bar and no number; the fraction was on the wire the whole
                # time and only the estimate was missing.
                emit(phase="envelope", pct=100.0 * frac,
                     message=f"{int(frac * 100)}% of the recording read",
                     eta_s=core_jobs.eta_from_fraction(elapsed, frac))

            env = opened.build_envelope(n_buckets, progress=on_progress)
        core_workspace.refuse_write(dest)            # belt and braces: never outside the project
        mr.save_envelope(dest, env)
        return {"kind": ENVELOPE_JOB_KIND, "analysis_id": analysis_id, "recording_id": rid,
                "built": True, "n_buckets": int(env.n_buckets)}

    job = core_jobs.JOBS.submit_thread(ENVELOPE_JOB_KIND, fn,
                                       label="reading the recording end to end")
    _ENVELOPE_JOBS[rid] = job.job_id
    return job.job_id


def start_envelopes(project_dir: str | Path, analysis_id: str, doc: Mapping, *,
                    n_buckets: int, force: bool = False) -> list[str]:
    """⭐ **THE BACKFILL.** Every recording in the project that has no envelope yet gets one. The
    jobs are submitted together and the registry runs them; each is skipped in `start_envelope` if it
    turns out to be unnecessary, so calling this repeatedly is free.

    ⚠️ **Submitted together, but READ ONE AT A TIME** — see `read_turn`. All of them get a job id and
    a row, exactly as before; the difference is that four of them start out saying they are waiting
    instead of four bars crawling at a fifth speed while h5py's own lock does the queueing invisibly.
    ⛔ Nothing here raises `Busy`: the contract is *submit them all*, and it is kept."""
    out: list[str] = []
    for rec in list(doc.get("recordings") or []):
        jid = start_envelope(project_dir, analysis_id, rec, n_buckets=n_buckets, force=force)
        if jid:
            out.append(jid)
    return out


def _rel(project_dir: Path, p: Path) -> str:
    return p.relative_to(project_dir).as_posix()


def _copy_file(src: Path, dest: Path, *, report: Any = None, cancel: Any = None) -> int:
    """Copy `src` to `dest`, reporting bytes. -> bytes copied.

    ⭐ **A TEMP NAME, THEN A RENAME.** A half-copied `data.raw.h5` sitting at the final name is
    indistinguishable from a whole one — and the shelf treats "the copy is on disk" as proof that
    the copy finished, so a truncated file at that path would make the app read a broken recording
    for ever and call it `stored`. `os.replace` is atomic, so the final name only ever exists once
    all the bytes are through it.

    ⛔ The source is opened `"rb"`. Camea does not write on the evidence, and this is the one place
    in the app that reads from the user's own data folder at all.
    """
    core_workspace.refuse_write(dest)                        # belt and braces: never outside ours
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    total = _size(src)
    done = 0
    emit = core_jobs.report_adapter(report)
    t0 = time.monotonic()
    said = 0.0
    try:
        with open(src, "rb") as fin, open(part, "wb") as fout:
            while True:
                core_jobs.check_cancelled(cancel, "copy")
                chunk = fin.read(_CHUNK)
                if not chunk:
                    break
                fout.write(chunk)
                done += len(chunk)
                now = time.monotonic()
                # Throttled, except for the chunk that finishes it — 100 % must be said the moment
                # it is true, never up to a fifth of a second after the file is whole.
                if now - said < _COPY_SAY_EVERY_S and not (0 < total <= done):
                    continue
                said = now
                elapsed = now - t0
                # ⏱️ **R48.3 — THE COUNTABLE UNIT IS BYTES, and this loop was already counting them
                # for the percentage.** ⭐ The measured rate goes in the message beside them because
                # it is free at this line and it is the one number that explains the wait: the same
                # gigabytes off his SSD and off a mounted share are the same bar moving ten times
                # slower, and only the rate says which one he is looking at.
                emit(phase="copy", pct=(100.0 * done / total if total else 100.0),
                     message=(f"{done // (1024 * 1024)} MB"
                              + (f" · {done / elapsed / (1024 * 1024):.0f} MB/s"
                                 if elapsed > 0 else "")),
                     eta_s=core_jobs.eta_from_counts(elapsed, done, total))
            fout.flush()
            os.fsync(fout.fileno())
        os.replace(part, dest)
    except BaseException:
        try:
            part.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return done


def forget(project_dir: str | Path, rec: Mapping) -> None:
    """Remove the project's own copy of one recording, and nothing else.

    ⛔ **THE USER'S ORIGINAL IS NEVER TOUCHED, UNDER ANY CIRCUMSTANCE.** The only thing deleted is
    inside `<project>/recordings/<id>/`, and the folder name is checked to be exactly that before
    anything goes — this is an `rmtree`, and it does not get to be clever. There is no confirm box
    because there is nothing of his to lose: it is a copy Camea made itself.
    """
    rid = str(rec.get("id") or "")
    if not rid:
        return
    j = _live_copy_job(rid)
    if j is not None:
        try:
            core_jobs.JOBS.cancel(j.job_id)
        except core_jobs.NotCancellable:
            pass
    _COPY_JOBS.pop(rid, None)

    root = Path(project_dir) / core_workspace.RECORDINGS
    d = root / rid
    if not d.is_dir():
        return
    try:
        rd = d.resolve()
        if rd.parent != root.resolve():
            return                                           # a symlink out of the project: leave it
        shutil.rmtree(rd)
    except OSError:
        pass                                                 # a locked copy is not a failed remove


__all__ = ["BROWSE_LIMIT", "COPY_JOB_KIND", "NotARecording", "candidates", "facts_of", "forget",
           "new_id", "open_path", "record_for", "shelf", "shelf_entry", "shown_name",
           "start_copy"]
