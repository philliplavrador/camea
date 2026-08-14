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
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from camea.core import jobs as core_jobs
from camea.core import mearecording as mr
from camea.core import workspace as core_workspace

#: The job kind for one recording's copy. `api.schemas.MeaCopyResult` discriminates on it.
COPY_JOB_KIND = "mea_copy"

#: 8 MiB. Big enough that a multi-GB copy is not a syscall storm, small enough that cancel is felt
#: within a moment and the percentage moves visibly on a file of any size.
_CHUNK = 8 * 1024 * 1024

#: How many recordings one browse may list. A folder of thousands is a wrong turn, not a workload —
#: the UI says the list was cut rather than pretending it is all of them.
BROWSE_LIMIT = 200

_DOC_LOCK = threading.RLock()

#: `recording id -> job id` for the copies this process started. ⚠️ **Deliberately not persisted.**
#: It is a handle on a *running* job, and a job does not survive the process; the shelf falls back
#: to what is on disk, which is the durable answer. See the module docstring.
_COPY_JOBS: dict[str, str] = {}


class NotARecording(Exception):
    """This file is not a MaxLab recording. ⭐ Carries the path so the refusal can NAME it — a file
    silently dropped from an import is the failure this plan calls out by name.

    ⚠️ **The sentence and the reason are separate on purpose.** `str(e)` is the one line he reads —
    *"notes.jpg is not a MaxLab recording"* — and `.reason` is the technical tail (h5py's *"file
    signature not found"*, a refused chip geometry) that goes in the error envelope's `detail` and
    on the greyed row of the tick-list. Splicing the tail into the sentence gives him a parenthesis
    about HDF5 signatures in the middle of a refusal about a file he can see on his desk.
    """

    def __init__(self, path: str | Path, reason: str = "") -> None:
        self.path = str(path).replace("\\", "/")
        self.reason = reason
        # ⭐ `parent.name` too when the file is the MaxLab `data.raw.h5`: every recording on his disk
        # is called that, so the run folder is the only part of the name that identifies one.
        p = Path(self.path)
        self.shown = f"{p.parent.name}/{p.name}" if p.name == mr.MEA_FILENAME else p.name
        super().__init__(f"{self.shown} is not a MaxLab recording")


# =================================================================================================
# Reading a file — the facts, every time, never remembered
# =================================================================================================


def facts_of(path: str | Path) -> dict:
    """Header facts for one `data.raw.h5`. -> `{label, run_id, assay, duration_s, ...}`.

    Raises :class:`NotARecording` for anything this reader cannot make sense of — a JPEG someone
    renamed, a truncated file, an HDF5 file with no `data_store` group. ⛔ It never returns a
    half-filled dict: a row of blanks on the screen reads as a bug in Camea rather than as a fact
    about the file.

    ⚠️ It does **not** touch the raw stream, so it works on every machine, decoder or no decoder
    (`utils/knowledge/mea-recordings.md`).
    """
    p = Path(path)
    if not p.is_file():
        raise NotARecording(p, "there is no file there")
    try:
        with mr.MeaRecording(p) as rec:
            i = rec.info()
            return {
                "label": i.label,
                "run_id": i.run_id,
                "assay": i.assay,
                "duration_s": round(i.duration_s, 3),
                "n_channels": i.n_channels,
                "n_samples": i.n_samples,
                "n_spikes": i.n_spikes,
            }
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

    job = core_jobs.JOBS.submit_thread(COPY_JOB_KIND, guarded)
    _COPY_JOBS[rid] = job.job_id
    return job.job_id


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
    try:
        with open(src, "rb") as fin, open(part, "wb") as fout:
            while True:
                core_jobs.check_cancelled(cancel, "copy")
                chunk = fin.read(_CHUNK)
                if not chunk:
                    break
                fout.write(chunk)
                done += len(chunk)
                emit(phase="copy", pct=(100.0 * done / total if total else 100.0),
                     message=f"{done // (1024 * 1024)} MB")
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
           "new_id", "open_path", "record_for", "shelf", "shelf_entry", "start_copy"]
