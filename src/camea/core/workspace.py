"""workspace.py — ⭐ **WHERE THE ANALYSES LIVE.** CORE. Feature-agnostic.

    DATASET  = raw, untouched, read-only. A folder of .dat frames + log.txt.
    ANALYSIS = what you did to it. It lives HERE, in a folder the user chose.
               It never lands inside the dataset and never inside the repo.

This module is the **filesystem**. It owns paths, guards and bytes-on-disk. It does **not** own
document *content*: `core.document` validates / normalises / stamps, and hands the result here to be
written. That line is deliberate — it is what lets a second feature reuse every byte of this file.

WHAT IT IS FOR, IN ONE SENTENCE
------------------------------
It must be able to answer the dataset browser's question without opening a pixel:

    "which analyses exist for dataset X, and when were they last touched?"

    ->  Workspace.by_dataset()[dataset_key]  ->  [Analysis, ...]   newest first.

THE THREE THINGS THIS FILE EXISTS TO PREVENT
--------------------------------------------
1. ⛔ **WRITING INTO THE DATA.** `data/` is a 35 GB read-only mirror and a dataset directory is raw
   evidence. v1 had **three** copies of this guard (`project._refuse_data_dir`,
   `server._refuse_data_dir`, `export._guard_out_dir`) which had already drifted apart — one of them
   read a `DATA_DIR` constant out of the *exclusion* module, i.e. it was dataset knowledge sitting in
   a path guard. There is exactly **one** guard now: `refuse_write()`.

2. 🔴 **TWO CONCURRENT WRITERS DESTROYING EACH OTHER.** `os.replace` is atomic, but on Windows it is
   *not* safe against a second replace landing on the same target at the same instant: the loser gets
   `PermissionError: [WinError 5]`. Two autosaves ARE routinely in flight at once (the 2 s debounce
   fires into the unconditional save on `A`), and the loser's document was **silently lost**
   (reproduced: 4 concurrent autosaves -> 1 failed). `atomic_write_text` holds a process-wide lock,
   fsyncs, and retries the replace. Every write in the app goes through it. (`export._atomic_bytes`
   had no lock, no fsync and no retry. It is gone.)

3. 🔴 **ONE AUTOSAVE SLOT SWALLOWING ANOTHER DOCUMENT.** In v1 the autosave filename was keyed on the
   *dataset directory*, so two different trial ranges of one dataset collided — and that is not
   hypothetical: **pass 2's autosave silently overwrote pass 1's ground-truth records.** The guard
   written in response (`project.autosave`) was never wired up; nothing called it.

   Here the slot is keyed on the **ANALYSIS**, not the dataset — two ranges of one dataset are two
   analyses with two directories, so the collision is structurally impossible. The guard is ported
   anyway, in its generic form (`_guard_slot`): a document may only be written into the analysis
   whose `id`/`dataset_key` it carries. Belt *and* braces, because this one already cost real data.

⛔ **NO DATASET KNOWLEDGE.** Nothing here knows a trial number, an exclusion, a tile or a pass split.
   `dataset_key` and `dataset` are opaque strings that arrive from `core.dataset`. The per-feature
   counts on the browser card come from a registered **hook** (`register_feature`), never from this
   module reaching into a payload it does not own.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
import time as _time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

# ⭐ ONE containment check, ONE dataset predicate, ONE "you tried to write on the evidence" error.
# `core.dataset` owns them and says so at its own `refuse_write` ("this is the primitive
# core.workspace guards every output path with"). v1 had THREE copies of this guard and they had
# already drifted — one of them read a `DATA_DIR` constant out of the *exclusion* module, i.e. it
# was dataset knowledge sitting inside a path guard. Importing beats copying. (`core.dataset` does
# not import `core.workspace`: the arrow only points this way.)
from camea.core.dataset import DatasetIsReadOnly, is_inside
from camea.core.dataset import _looks_like_a_dataset as looks_like_a_dataset
from camea.core.dataset import iso as _iso_dt
from camea.core.dataset import refuse_write as _refuse_write_into

__all__ = [
    # the workspace
    "Workspace",
    "Analysis",
    "new_analysis_id",
    # feature hooks — how a browser card gets its numbers without core knowing what a tile is
    "register_feature",
    "registered_features",
    "FeatureHooks",
    # ⛔ the guards. ONE of each.
    "refuse_write",
    "DatasetIsReadOnly",  # re-exported: it is what `refuse_write` raises. -> 409
    "safe_basename",
    "repo_root",
    "guard_slot",  # 🔴 the slot guard, shared with `core.project`. -> SlotMismatch
    # reading an analysis off disk — shared with `core.project`, which stores one per folder
    "read_analysis",
    "summarise_analysis",
    "MANIFEST",
    "DOCUMENT",
    "AUTOSAVE",
    "OUTPUTS",
    # 🔴 atomic IO. Everything the app writes goes through these.
    "atomic_write_text",
    "atomic_write_bytes",
    "dumps",
    "file_entry",
    # app state — NOT the workspace. `core.settings` lives here.
    "app_state_dir",
    # errors
    "WorkspaceError",
    "PathRefused",
    "SlotMismatch",
    "NoSuchAnalysis",
]

# =================================================================================================
# Names on disk. The layout, in full:
#
#   <workspace>/
#     camea-workspace.json                 the marker. "this folder is a Camea workspace."
#     analyses/
#       <analysis_id>/                     ⭐ the id IS the directory name. A rename does not move it.
#         analysis.json                    identity: feature, name, dataset, created
#         document.camea.json              ⭐ THE ANALYSIS. The file the scorer reads.
#         autosave.camea.json              the crash net. Never the same file as the document.
#         outputs/                         exports (TIFF, PNG, positions.csv, gt.json, qc.md)
#
# The document keeps the `.camea.json` suffix v1 shipped, unchanged: it is what `Save…` produces,
# what the benchmark scorer is pointed at, and what is on the user's disk already.
# =================================================================================================

MARKER = "camea-workspace.json"
ANALYSES_DIR = "analyses"
MANIFEST = "analysis.json"
DOCUMENT = "document.camea.json"
AUTOSAVE = "autosave.camea.json"
OUTPUTS = "outputs"
VIDEOS = "videos"
"""⭐ The project's own copies of the videos it was built from (2026-08-11).

A project HOLDS its files: the survey the mosaic came from and every region recording located
against it are copied in here, so a project is self-contained and survives the originals being
moved, renamed or deleted. It is an INPUT folder and the Outputs panel does not list it —
`outputs/` is what the user made, `videos/` is what he gave the app.
"""

#: The workspace format. Bump only if the LAYOUT changes — the document has its own schema_version.
WORKSPACE_VERSION = 1


# =================================================================================================
# Errors
# =================================================================================================


class WorkspaceError(Exception):
    """Anything this module refuses to do. The API maps it to 400 `bad_request` by default."""


class PathRefused(WorkspaceError):
    """⛔ The WORKSPACE may not live here (inside the repo; not a directory). -> 409 `refused`.

    ⚠️ Distinct from `core.dataset.DatasetIsReadOnly`, which is the other half of the same rule and
    is re-exported from this module: *that* one means **you tried to write on the raw evidence**.
    There is exactly one of each. The API maps both to 409.
    """


class SlotMismatch(WorkspaceError):
    """This document does not belong in this analysis. -> 409 `range_mismatch`.

    The generic descendant of v1's autosave range guard. It is **not merged, not renamed, not
    "repaired"** — it is refused, and the caller is told which document belongs where.
    """


class NoSuchAnalysis(WorkspaceError):
    """-> 404 `not_found`."""


# =================================================================================================
# Time.  (⚠️ `_iso` was DUPLICATED THREE WAYS in v1 — loader, jobs, server. It is private here and
# should move to a shared `core` util the moment one exists; see the report. `Z`, never `+00:00`:
# every file already on the user's disk says `Z`.)
# =================================================================================================


def _iso(ts: float | None = None) -> str:
    return _iso_dt(datetime.fromtimestamp(ts, UTC) if ts is not None else datetime.now(UTC))


def _fwd(p: Path | str) -> str:
    """A path as the front end should see it. Forward slashes: a Windows path in JSON is a wall of
    escaped backslashes, and the UI prints these."""
    return str(p).replace("\\", "/")


# =================================================================================================
# ⛔ THE GUARD.  ONE implementation. (v1 had three, and they had drifted.)
# =================================================================================================


def repo_root() -> Path | None:
    """The checkout, if we are running from one. `None` in a frozen/installed build — where there is
    no repo, and so nothing to protect from.

    We look for the markers, not a fixed number of `.parent`s: this file is
    `src/camea/core/workspace.py` today and must not silently stop guarding if it moves.
    """
    for d in Path(__file__).resolve().parents:
        if (d / "pyproject.toml").is_file() and (d / "src" / "camea").is_dir():
            return d
    return None


def refuse_write(path: str | Path, *, dataset_dir: str | Path | None = None) -> Path:
    """⛔ **THE ONE WRITE GUARD.** Every output path in the app goes through it.
    -> the resolved path, or raises `DatasetIsReadOnly`.

    Refused:
      * anything inside the repo's `data/` — a 35 GB rclone mirror of a public Drive folder,
        read-only by construction;
      * anything inside `dataset_dir`, when the caller names the dataset it has open;
      * anything inside **any** directory on the way up that *is* a raw acquisition — recognised by
        its **shape** (`log.txt` + `NNN.xml`), never by its name. So a `Save…` typed into a dataset
        folder the app was never told about is refused too. **A dataset is the microscope's evidence.
        The app does not write on the evidence.**

    ⚠️ It does NOT refuse the repo generally: root `output/` is a real, user-facing destination and
    exports have always been allowed to land there. The **workspace** carries the stronger rule —
    never inside the repo at all — and `Workspace.open` is where it is enforced.
    """
    p = Path(path).expanduser()
    try:
        rp = p.resolve()
    except OSError:  # a path we cannot even resolve is not a path we will write to blind
        rp = p.absolute()

    roots: list[Path] = []
    root = repo_root()
    if root is not None:
        roots.append(root / "data")
    if dataset_dir is not None:
        roots.append(Path(dataset_dir).expanduser())
    # ...and any acquisition folder at or above the target, named or not.
    roots += [d for d in (rp, *rp.parents) if looks_like_a_dataset(d)]

    _refuse_write_into(rp, roots)  # -> DatasetIsReadOnly
    return rp


def safe_basename(basename: str) -> str:
    """A user-typed export basename -> itself, or `ValueError`. No separators, no drive letters, no
    directory traversal. (`export._safe_basename`, verbatim in behaviour.)"""
    b = (basename or "").strip().strip(". ")
    if not b or any(c in b for c in '\\/:*?"<>|'):
        raise ValueError(f"bad basename: {basename!r}")
    return b


def guard_slot(analysis_id: str, doc: Mapping, man: Mapping) -> None:
    """🔴 **THE SLOT GUARD** — the generic descendant of v1's autosave range guard.

    A document may only be written into the analysis it belongs to. If the envelope's `id` or
    `dataset_key` disagrees with the slot's manifest, the write is **REFUSED** — not merged, not
    renamed, not "repaired". Pass 2's autosave once silently overwrote pass 1's ground-truth records;
    this is the door that was left open.

    (It reads only ENVELOPE keys — `id`, `dataset_key`. Those are `core.document`'s, not any
    feature's. Core still knows nothing about a trial range, and it does not need to: a different
    range is a different analysis, and a different analysis is a different **folder**.)

    ⚠️ ONE implementation, called by both storage layers — `Workspace._guard_slot` (the v1 layout,
    `analyses/<id>/`) and `core.project.Project` (one folder per project, the layout the user chose
    on 2026-07-25). The module docstring's warning about three drifted copies of the write guard
    applies here with equal force: do not inline a second copy of this.
    """
    did = doc.get("id")
    dkey = doc.get("dataset_key")
    if did and did != analysis_id:
        raise SlotMismatch(
            f"this document belongs to analysis {did!r}, not {analysis_id!r}. "
            f"Refusing to overwrite {man.get('name') or analysis_id!r}."
        )
    if dkey and man.get("dataset_key") and dkey != man["dataset_key"]:
        raise SlotMismatch(
            f"this document is for dataset {dkey!r}; analysis {analysis_id!r} holds "
            f"{man['dataset_key']!r}. Refusing to overwrite it."
        )


# =================================================================================================
# 🔴 ATOMIC WRITES.  Every byte the app writes goes through here.
# =================================================================================================

#: 🔴 **SERIALISES EVERY WRITE IN THE PROCESS.** See the module docstring, point 2. The writes are
#: milliseconds, so contention is irrelevant; a lost document is not.
_WRITE_LOCK = threading.Lock()


def atomic_write_bytes(path: str | Path, data: bytes) -> None:
    """temp file in the same directory + `os.replace`, under `_WRITE_LOCK`, fsynced, with a retry.

    A crash never leaves a half-written document, and two concurrent savers never destroy each
    other's write. The lock covers *this* process; `os.replace` can still lose to an **external**
    holder of the target (an antivirus scanner, an editor, a second Camea) — so the replace is
    retried briefly rather than failing the save on a transient share violation.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with _WRITE_LOCK:
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".camea-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            last: OSError | None = None
            for attempt in range(6):  # ~0.31 s worst case: 10, 20, 40, 80, 160 ms
                try:
                    os.replace(tmp, p)  # atomic on Windows and POSIX
                    return
                except PermissionError as e:  # WinError 5 / 32: someone else holds the target
                    last = e
                    _time.sleep(0.01 * (2**attempt))
            raise last  # type: ignore[misc]
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def atomic_write_text(path: str | Path, text: str) -> None:
    """UTF-8, LF. (`newline="\\n"` mattered: a document round-tripped through a CRLF writer is a
    diff against every copy of it anyone else holds.)"""
    atomic_write_bytes(path, text.encode("utf-8"))


def file_entry(kind: str, path: str | Path) -> dict:
    """`{kind, path, bytes}` — one line of an export manifest. (`export._entry`.)"""
    p = Path(path)
    return {"kind": kind, "path": _fwd(p), "bytes": p.stat().st_size}


def dumps(doc: Mapping) -> str:
    """A document -> the exact text that goes on disk. 2-space indent, real UTF-8, trailing newline.

    ⚠️ It does **not** coerce. `t33`'s `info["config"]` holds a nested `t27.Config` and `json.dumps`
    **crashes** on it — run the document through core's `jsonable()` first. Failing loudly here is
    the point: v1's third copy of that coercer existed because somebody had already been bitten.
    """
    try:
        return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    except TypeError as e:
        raise WorkspaceError(
            f"this document is not JSON-serialisable ({e}). Coerce it with core's `jsonable()` "
            f"before handing it to the workspace — do not stringify it here."
        ) from e


def _as_text(doc: Mapping | str) -> str:
    return doc if isinstance(doc, str) else dumps(doc)


# =================================================================================================
# App state — NOT the workspace.
# =================================================================================================


def app_state_dir() -> Path:
    """`%LOCALAPPDATA%/Camea` (or `$XDG_STATE_HOME/Camea`, or `~/.local/state/Camea`).

    ⭐ **Under R44 (2026-08-10) this is where the user's PROJECTS live too** — `projects/<id>/`, the
    app-managed store (`core.project.store_root`). It also holds the app's own settings (the recent
    datasets). `CAMEA_STATE_DIR` overrides it (the tests set it; so can a portable install), which is
    what gives every test process and the e2e harness its own store.

    ⚠️ **The v1 trap this must not re-open.** In v1 the *autosave* lived here keyed on the DATASET
    DIRECTORY, and two trial ranges of one dataset collided in it — pass 2 silently overwrote pass
    1's ground-truth records. What is keyed here is the **project id**, never the dataset: two ranges
    are two projects, two ids, two folders. Nothing in this directory is ever keyed on the data.
    """
    override = os.environ.get("CAMEA_STATE_DIR")
    if override:
        d = Path(override)
    else:
        base = (
            os.environ.get("LOCALAPPDATA")
            or os.environ.get("XDG_STATE_HOME")
            or str(Path.home() / ".local" / "state")
        )
        d = Path(base) / "Camea"
    d.mkdir(parents=True, exist_ok=True)
    return d


# =================================================================================================
# FEATURE HOOKS — how the browser card gets its numbers without core knowing what a tile is.
# =================================================================================================


@dataclass(frozen=True)
class FeatureHooks:
    """What a feature teaches the workspace about its own documents. Both are optional; an
    unregistered feature simply lists with `None` counts, which is honest."""

    #: `doc -> {"n_tiles": int, "n_anchored": int, "n_excluded": int}`. Any subset. Cheap: it runs
    #: once per analysis per listing.
    counts: Callable[[Mapping], Mapping[str, int]] | None = None

    #: `doc -> seeded_from | None`. ⚠️ **Derived from the document's HISTORY** (a build block, a tile
    #: still carrying a `machine` position) — never from what the document *says about itself*. This
    #: hook is why the browser card can be trusted: `seeded_from` is writable, and "Skip — place from
    #: scratch" once erased it while every tile kept the solver's answer. **This project has already
    #: destroyed one benchmark exactly that way.**
    machine_evidence: Callable[[Mapping], object | None] | None = None


_FEATURES: dict[str, FeatureHooks] = {}


def register_feature(
    feature: str,
    *,
    counts: Callable[[Mapping], Mapping[str, int]] | None = None,
    machine_evidence: Callable[[Mapping], object | None] | None = None,
) -> None:
    """Called once, at import, by the feature package (`features/mosaic/__init__.py`).

    ⛔ Core must never grow an `if feature == "mosaic"`. This registry is the reason it does not
    have to."""
    _FEATURES[feature] = FeatureHooks(counts=counts, machine_evidence=machine_evidence)


def registered_features() -> list[str]:
    return sorted(_FEATURES)


# =================================================================================================
# An analysis
# =================================================================================================


@dataclass
class Analysis:
    """One analysis in the workspace. Bound to exactly ONE dataset.

    `to_json()` is `api.schemas.AnalysisSummary`, key for key.
    """

    analysis_id: str
    feature: str
    name: str
    dataset_key: str
    dataset: str
    #: ⭐ **The DOCUMENT file** — the thing you load, the thing the scorer reads. Not the directory.
    #: (`bytes` is this file's size, so the two agree.) The directory is `.dir`.
    path: Path
    created: str
    modified: str
    bytes: int = 0
    n_tiles: int | None = None
    n_anchored: int | None = None
    n_excluded: int | None = None
    independent_of_method: bool | None = None
    #: Set when the document on disk could not be read. The analysis still LISTS — one corrupt file
    #: must never blank the browser.
    warnings: list[str] = field(default_factory=list)
    #: Recorded so a "Load a project…" can bootstrap the session cold, from the file alone.
    data_dir: str = ""

    @property
    def dir(self) -> Path:
        return self.path.parent

    @property
    def outputs_dir(self) -> Path:
        return self.dir / OUTPUTS

    @property
    def autosave_path(self) -> Path:
        return self.dir / AUTOSAVE

    @property
    def has_document(self) -> bool:
        return self.bytes > 0

    def to_json(self) -> dict:
        return {
            "analysis_id": self.analysis_id,
            "feature": self.feature,
            "name": self.name,
            "dataset_key": self.dataset_key,
            "dataset": self.dataset,
            "path": _fwd(self.path),
            # ⭐ Where the project lives (Camea's store, R44) and the data it was built on — he chose
            # the second, never the first. (`dir` is the document's parent, which under
            # `core.project`'s layout IS the project folder.)
            "folder": _fwd(self.dir),
            "data_dir": self.data_dir,
            "created": self.created,
            "modified": self.modified,
            "bytes": self.bytes,
            "n_tiles": self.n_tiles,
            "n_anchored": self.n_anchored,
            "n_excluded": self.n_excluded,
            "independent_of_method": self.independent_of_method,
        }

    def to_ref(self) -> dict:
        """`api.schemas.AnalysisRef` — the smaller card on the dataset tile in the browser."""
        return {
            "analysis_id": self.analysis_id,
            "feature": self.feature,
            "name": self.name,
            "modified": self.modified,
            "n_anchored": self.n_anchored,
            "n_excluded": self.n_excluded,
        }


_SLUG_BAD = re.compile(r"[^a-z0-9]+")


def _slug(name: str) -> str:
    s = _SLUG_BAD.sub("-", (name or "").strip().lower()).strip("-")
    return s[:40].strip("-") or "analysis"


def new_analysis_id(name: str) -> str:
    """`pass-1-11-166-3f9a2c`. Legible, unique, and **stable**: renaming an analysis rewrites its
    manifest, never its directory. A path in a log or a bookmark keeps working."""
    return f"{_slug(name)}-{uuid.uuid4().hex[:6]}"


# =================================================================================================
# THE WORKSPACE
# =================================================================================================


class Workspace:
    """The folder the user chose. Create it, open it, list what is in it, delete one.

    ⛔ **NEVER inside a dataset. NEVER inside the repo.** Both are enforced in `open()`, at the one
    moment the user names the place — not scattered across the callers.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    # ---------------------------------------------------------------------------------------------
    # open / create
    # ---------------------------------------------------------------------------------------------

    @classmethod
    def open(cls, path: str | Path, *, create: bool = True) -> Workspace:
        """Open (and by default create) the workspace at `path`.

        Refuses, loudly:
          * a path inside a raw dataset, or inside `data/`   (`refuse_write`);
          * a path **inside the repo** — a workspace under the checkout would be committed,
            `.gitignore`d, or blown away by a clean. The user's work does not live in the source
            tree. This is the rule the task states outright and it has no exceptions;
          * an existing *file*.

        An existing non-empty folder with no marker is **adopted**, not rejected — the user pointed
        at it deliberately, and refusing would just make him make a new one next to it.
        """
        p = Path(path).expanduser()
        try:
            rp = p.resolve()
        except OSError:
            rp = p.absolute()

        refuse_write(rp)  # data/ and any raw acquisition folder -> DatasetIsReadOnly

        root = repo_root()
        if root is not None and is_inside(rp, root):
            raise PathRefused(
                f"the workspace may not live inside the Camea repo ({_fwd(root)}): {_fwd(rp)}. "
                f"Analyses are your work, not the app's source. Choose a folder outside it."
            )

        if rp.exists() and not rp.is_dir():
            raise PathRefused(f"not a directory: {_fwd(rp)}")

        if not rp.exists():
            if not create:
                raise WorkspaceError(f"no such workspace: {_fwd(rp)}")
            rp.mkdir(parents=True, exist_ok=True)

        ws = cls(rp)
        if create:
            ws._ensure_marker()
            (rp / ANALYSES_DIR).mkdir(parents=True, exist_ok=True)
        return ws

    def _ensure_marker(self) -> None:
        m = self.path / MARKER
        if m.exists():
            return
        atomic_write_text(
            m,
            dumps(
                {
                    "camea_workspace": WORKSPACE_VERSION,
                    "created": _iso(),
                    "note": "Camea writes every analysis under analyses/. The datasets are "
                    "elsewhere and are never written to.",
                }
            ),
        )

    # ---------------------------------------------------------------------------------------------
    # info
    # ---------------------------------------------------------------------------------------------

    @property
    def analyses_root(self) -> Path:
        return self.path / ANALYSES_DIR

    def exists(self) -> bool:
        return self.path.is_dir()

    def writable(self) -> bool:
        """Proved, not assumed: a read-only or vanished drive must show up on the Load screen as
        `writable: false`, not as a 500 an hour into a sweep."""
        if not self.exists():
            return False
        try:
            fd, tmp = tempfile.mkstemp(dir=str(self.path), prefix=".camea-probe-")
            os.close(fd)
            os.unlink(tmp)
            return True
        except OSError:
            return False

    def info(self) -> dict:
        """`api.schemas.WorkspaceInfo`, key for key."""
        return {
            "path": _fwd(self.path),
            "exists": self.exists(),
            "writable": self.writable(),
            "n_analyses": len(self.analyses()),
        }

    # ---------------------------------------------------------------------------------------------
    # paths
    # ---------------------------------------------------------------------------------------------

    def dir_of(self, analysis_id: str) -> Path:
        """The analysis's own folder. ⚠️ `analysis_id` is a directory name and arrives over HTTP —
        it is validated, never trusted. `../../Windows` does not get to be an id."""
        a = str(analysis_id)
        if not _SAFE_ID.fullmatch(a):
            raise WorkspaceError(f"bad analysis id: {analysis_id!r}")
        return self.analyses_root / a

    def document_path(self, analysis_id: str) -> Path:
        return self.dir_of(analysis_id) / DOCUMENT

    def autosave_path(self, analysis_id: str) -> Path:
        """The crash net. ⭐ **One slot PER ANALYSIS**, never per dataset — see the module docstring,
        point 3. Two trial ranges of one dataset are two analyses and cannot collide."""
        return self.dir_of(analysis_id) / AUTOSAVE

    def outputs_dir(self, analysis_id: str) -> Path:
        d = self.dir_of(analysis_id) / OUTPUTS
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ---------------------------------------------------------------------------------------------
    # create / rename / delete
    # ---------------------------------------------------------------------------------------------

    def create_analysis(
        self,
        *,
        feature: str,
        name: str,
        dataset_key: str,
        dataset: str,
        data_dir: str | Path = "",
        analysis_id: str | None = None,
    ) -> Analysis:
        """Make the folder and its manifest. **No document yet** — `core.document` authors that and
        hands it to `save_document`.

        ⭐ The document's `id` MUST equal the `analysis_id` returned here. `_guard_slot` enforces it
        on every write, and that is what makes the slot collision of v1 impossible rather than merely
        unlikely.
        """
        if not feature:
            raise WorkspaceError("an analysis must name its feature")
        aid = analysis_id or new_analysis_id(name)
        d = self.dir_of(aid)
        if d.exists():
            raise WorkspaceError(f"analysis already exists: {aid}")
        d.mkdir(parents=True)
        now = _iso()
        atomic_write_text(
            d / MANIFEST,
            dumps(
                {
                    "analysis_id": aid,
                    "feature": feature,
                    "name": name or aid,
                    "dataset_key": dataset_key,
                    "dataset": dataset,
                    "data_dir": _fwd(data_dir) if data_dir else "",
                    "created": now,
                }
            ),
        )
        return self.get(aid)

    def rename(self, analysis_id: str, name: str) -> Analysis:
        """Rewrites the manifest. **The directory does not move** — an id is forever."""
        man = self._manifest(analysis_id)
        man["name"] = name or man.get("name") or analysis_id
        atomic_write_text(self.dir_of(analysis_id) / MANIFEST, dumps(man))
        return self.get(analysis_id)

    def delete(self, analysis_id: str) -> str:
        """Remove the analysis and everything in it — document, autosave, exports. -> the path.

        ⚠️ The `rmtree` target is re-checked to be a direct child of `<workspace>/analyses/` **after**
        resolving symlinks. This is the one operation in Camea that destroys the user's work; it does
        not get to be clever.
        """
        d = self.dir_of(analysis_id)
        if not d.is_dir():
            raise NoSuchAnalysis(f"no such analysis: {analysis_id}")
        rd = d.resolve()
        root = self.analyses_root.resolve()
        if rd.parent != root:
            raise WorkspaceError(f"refusing to delete outside the workspace: {_fwd(rd)}")
        shutil.rmtree(rd)
        return _fwd(d)

    # ---------------------------------------------------------------------------------------------
    # writing
    # ---------------------------------------------------------------------------------------------

    def _guard_slot(self, analysis_id: str, doc: Mapping | str) -> None:
        """This workspace's slot guard. The rule itself is `guard_slot` — see there."""
        if isinstance(doc, str):
            return  # pre-serialised: the caller has already been through core.document
        guard_slot(analysis_id, doc, self._manifest(analysis_id))

    def save_document(self, analysis_id: str, doc: Mapping | str) -> dict:
        """Write the analysis's document. -> `{path, bytes, saved_at}` (`api.schemas.SaveResult`).

        ⚠️ It writes what it is given. Validate → normalise → stamp happen in `core.document`, **in
        that order**, before this is called. The workspace does not second-guess the content; it
        guards the *place*.
        """
        self._guard_slot(analysis_id, doc)
        p = self.document_path(analysis_id)
        refuse_write(p)
        text = _as_text(doc)
        atomic_write_text(p, text)
        return {
            "path": _fwd(p),
            "bytes": len(text.encode("utf-8")),
            "saved_at": _iso(),
            "warnings": [],
        }

    def autosave(self, analysis_id: str, doc: Mapping | str) -> dict:
        """The crash net. Debounced 2 s by the front end, **plus unconditionally on every `A`/`E`**.

        🔴 **A FAILURE IS LOUD.** It raises. It is never swallowed — `localStorage` failed *silently*
        in the artefact sandbox and nearly cost a day's work, which is why this is a server file at
        all.

        It writes to `autosave.camea.json`, **beside** the document and never over it: recovery must
        be able to show the user both and let him choose.
        """
        self._guard_slot(analysis_id, doc)
        p = self.autosave_path(analysis_id)
        refuse_write(p)
        text = _as_text(doc)
        atomic_write_text(p, text)
        return {"path": _fwd(p), "bytes": len(text.encode("utf-8")), "saved_at": _iso(),
                "warnings": []}

    def recovery(self, analysis_id: str) -> dict | None:
        """Is there an autosave NEWER than the saved document? -> `{path, saved_at, newer}` or None.

        The Load screen asks this. An autosave that is older than the document is not a recovery
        prompt, it is noise.
        """
        a = self.autosave_path(analysis_id)
        if not a.is_file():
            return None
        doc = self.document_path(analysis_id)
        doc_mtime = doc.stat().st_mtime if doc.is_file() else 0.0
        return {
            "path": _fwd(a),
            "saved_at": _iso(a.stat().st_mtime),
            "newer": a.stat().st_mtime > doc_mtime,
        }

    # ---------------------------------------------------------------------------------------------
    # reading / listing  — ⭐ the dataset browser's question
    # ---------------------------------------------------------------------------------------------

    def _manifest(self, analysis_id: str) -> dict:
        p = self.dir_of(analysis_id) / MANIFEST
        try:
            man = json.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError as e:
            raise NoSuchAnalysis(f"no such analysis: {analysis_id}") from e
        except (OSError, ValueError) as e:
            raise WorkspaceError(f"unreadable analysis manifest {_fwd(p)}: {e}") from e
        if not isinstance(man, dict):
            raise WorkspaceError(f"unreadable analysis manifest {_fwd(p)}")
        return man

    def get(self, analysis_id: str) -> Analysis:
        return self._read(self.dir_of(analysis_id))

    def analyses(self, dataset_key: str | None = None, feature: str | None = None) -> list[Analysis]:
        """Every analysis in the workspace, **newest touch first**.

        `dataset_key` is the dataset browser's filter: *"which analyses exist for dataset X?"*
        `modified` is the answer to *"...and when were they last touched?"* — and it is taken from the
        FILES (document, autosave, manifest), not from a field somebody has to remember to update. A
        stale timestamp on that card is a lie about whether work is safe.

        One unreadable analysis never blanks the list: it comes back with `warnings` and `None`
        counts. (v1 had no listing at all; this is a new concept.)
        """
        root = self.analyses_root
        if not root.is_dir():
            return []
        out: list[Analysis] = []
        for d in sorted(root.iterdir()):
            if not d.is_dir() or not (d / MANIFEST).is_file():
                continue
            try:
                a = self._read(d)
            except WorkspaceError:
                continue
            if dataset_key is not None and a.dataset_key != dataset_key:
                continue
            if feature is not None and a.feature != feature:
                continue
            out.append(a)
        out.sort(key=lambda a: a.modified, reverse=True)
        return out

    def by_dataset(self) -> dict[str, list[Analysis]]:
        """⭐ The browser's index: `{dataset_key: [Analysis, ...]}`, newest first within each dataset.
        Datasets with no analyses simply do not appear — core does not enumerate datasets."""
        idx: dict[str, list[Analysis]] = {}
        for a in self.analyses():
            idx.setdefault(a.dataset_key, []).append(a)
        return idx

    def _read(self, d: Path) -> Analysis:
        return read_analysis(
            self._manifest(d.name),
            manifest_path=d / MANIFEST,
            document_path=d / DOCUMENT,
            autosave_path=d / AUTOSAVE,
            fallback_id=d.name,
        )

    def _summarise(self, a: Analysis, doc_path: Path) -> None:
        summarise_analysis(a, doc_path)


def read_analysis(
    man: Mapping,
    *,
    manifest_path: Path,
    document_path: Path,
    autosave_path: Path,
    fallback_id: str,
) -> Analysis:
    """A manifest + the three paths that go with it -> an `Analysis`.

    ⚠️ ONE implementation, called by both storage layouts (`Workspace`'s `analyses/<id>/` and
    `core.project.Project`'s one-folder-per-project). The paths are passed in precisely *because*
    the two layouts put these files in different places; everything else about reading an analysis
    is identical and must stay that way.
    """
    # `modified` = the last time anything in this analysis was TOUCHED, taken from the filesystem.
    # The autosave counts: an hour of sweeping that was only ever autosaved is still an hour of
    # work, and a card that says "3 days ago" would be a lie.
    stamps = [_mtime(manifest_path), _mtime(document_path), _mtime(autosave_path)]
    modified = _iso(max(stamps)) if any(stamps) else man.get("created") or _iso()

    a = Analysis(
        analysis_id=man.get("analysis_id") or fallback_id,
        feature=man.get("feature") or "",
        name=man.get("name") or fallback_id,
        dataset_key=man.get("dataset_key") or "",
        dataset=man.get("dataset") or "",
        path=document_path,
        created=man.get("created") or modified,
        modified=modified,
        bytes=document_path.stat().st_size if document_path.is_file() else 0,
        data_dir=man.get("data_dir") or "",
    )
    if a.bytes:
        summarise_analysis(a, document_path)
    return a


def summarise_analysis(a: Analysis, doc_path: Path) -> None:
    """Fill the card's numbers from the document ON DISK.

    ⚠️ **No cache.** The counts are re-derived from the file every listing, because the one thing
    this project cannot afford is a summary that disagrees with the document it describes. A
    312-tile document parses in ~2 ms; a stale `n_anchored` on the browser card is a bug that would
    take a week to find.
    """
    try:
        doc = json.loads(doc_path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            raise ValueError("not an object")
    except (OSError, ValueError) as e:
        a.warnings.append(f"could not read the document: {e}")
        return

    hooks = _FEATURES.get(a.feature)

    if hooks is not None and hooks.counts is not None:
        try:
            c = hooks.counts(doc) or {}
            a.n_tiles = _int_or_none(c.get("n_tiles"))
            a.n_anchored = _int_or_none(c.get("n_anchored"))
            a.n_excluded = _int_or_none(c.get("n_excluded"))
        except Exception as e:  # noqa: BLE001 — a feature hook must not break the browser
            a.warnings.append(f"{a.feature}: could not count this document: {e}")

    # ⚠️ **HISTORY, NOT SELF-DECLARATION.** If the feature can tell us whether a machine touched
    # this document, its answer WINS over the document's own `independent_of_method` — because that
    # field is writable, and a document that laundered a solver build into an "independent ground
    # truth" would otherwise sit on the browser card claiming to be one. This project has already
    # destroyed one benchmark exactly that way.
    if hooks is not None and hooks.machine_evidence is not None:
        try:
            a.independent_of_method = hooks.machine_evidence(doc) is None
            return
        except Exception as e:  # noqa: BLE001
            a.warnings.append(f"{a.feature}: could not derive provenance: {e}")

    prov = doc.get("provenance")
    if isinstance(prov, dict):
        v = prov.get("independent_of_method")
        a.independent_of_method = bool(v) if isinstance(v, bool) else None


#: An analysis id is a directory name that arrives over HTTP. Slug + short hex, and nothing else:
#: no dots (so no `..`), no separators, no drive letters, no spaces.
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def _int_or_none(v: object) -> int | None:
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
