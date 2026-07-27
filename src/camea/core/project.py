"""project.py — ⭐ **A PROJECT IS ONE FOLDER.** CORE. Feature-agnostic.

    DATASET = raw, untouched, read-only. A folder of .dat frames + log.txt.
    PROJECT = what you did to it. It lives in **a folder the user named, and it IS that folder.**
              It never lands inside the dataset and never inside the repo.

The layout, in full:

    <the folder he named>/
      camea-project.json        the manifest + the marker. "this folder is a Camea project."
      document.camea.json       ⭐ THE WORK. The file the scorer reads.
      autosave.camea.json       the crash net. Never the same file as the document.
      outputs/                  exports (TIFF, PNG, positions.csv, gt.json, qc.md)

⭐ **WHY THIS EXISTS — his ruling, 2026-07-25.** Until now every project lived in one app-managed
store, picked once, as `<store>/analyses/<uuid>/`. He asked for the opposite: *"I wanna put in where
I wanna pull the data from and where I wanna save the data into"* — a save path **per project**, and
the folder he names is the project, not a shelf holding a uuid-named sub-folder he cannot identify
in Explorer. `docs/BEHAVIOUR.md` R41.2 was rewritten to say so.

⛔ **NO DATASET KNOWLEDGE (HARD RULE 3 / BEHAVIOUR I1).** Unchanged and undented by this move. The
manifest records the dataset's *path, name and key* — those are paths and labels, not knowledge
about the data at them. It records **no trial number, no exclusion, no threshold, no pass split.**
Exclusions come from exactly two places, and neither is a manifest: the human in this session, and a
project file he loaded.

🔴 **THE RULES ARE NOT RE-DERIVED HERE.** The write guard (`refuse_write` — never on the evidence),
the slot guard (`guard_slot` — a document may only be written into the project it belongs to), the
atomic write, and the analysis reader all come from `core.workspace`, which holds the one
implementation of each. `workspace.py`'s docstring records that v1 had *three* copies of the write
guard and they had drifted; this module exists to add a second **layout**, never a second **rule**.

⚠️ **`analysis_id` is still the addressing token on the wire.** `core.document`, every feature and
the whole front end name a project by its id and must not learn that storage moved. `ProjectSet`
below is the registry that maps `analysis_id -> folder`, and it presents the same method surface
`core.document` already calls on a `Workspace`. That is what keeps this change out of the mosaic.
"""

from __future__ import annotations

import json
import shutil
import threading
from collections.abc import Mapping
from pathlib import Path

from camea.core.workspace import (
    AUTOSAVE,
    DOCUMENT,
    OUTPUTS,
    Analysis,
    NoSuchAnalysis,
    PathRefused,
    SlotMismatch,
    WorkspaceError,
    atomic_write_text,
    dumps,
    guard_slot,
    is_inside,
    new_analysis_id,
    read_analysis,
    refuse_write,
    repo_root,
)
from camea.core.workspace import _fwd as _fwd
from camea.core.workspace import _iso as _iso

__all__ = [
    "Project",
    "ProjectSet",
    "MARKER",
    "PROJECT_VERSION",
    "ProjectError",
    "NoSuchProject",
    # re-exported so callers need only this module for the whole storage story
    "NoSuchAnalysis",
    "PathRefused",
    "SlotMismatch",
    "WorkspaceError",
]

#: The manifest. It doubles as the marker: "this folder is a Camea project."
MARKER = "camea-project.json"

#: The project-folder format. Bump only if the LAYOUT changes — the document has its own
#: `schema_version`, and the two are not the same thing.
PROJECT_VERSION = 1


class ProjectError(WorkspaceError):
    """Anything this module refuses to do. -> 400 `bad_request` by default."""


class NoSuchProject(NoSuchAnalysis):
    """-> 404 `not_found`."""


# =================================================================================================
# ONE PROJECT
# =================================================================================================


class Project:
    """The folder the user named. It holds exactly one project's work."""

    def __init__(self, path: Path) -> None:
        self.path = path

    # ---------------------------------------------------------------------------------------------
    # open / create
    # ---------------------------------------------------------------------------------------------

    @classmethod
    def open(cls, path: str | Path, *, create: bool = False) -> Project:
        """Open (optionally create) the project folder at `path`.

        Refuses, loudly — **the same three refusals `Workspace.open` has always made**, at the one
        moment the user names the place:
          * a path inside a raw dataset, or inside `data/` (`refuse_write`). ⛔ **The app does not
            write on the evidence.** A dataset is recognised by its SHAPE (`log.txt` + `NNN.xml`),
            never by its name — so a project folder typed into an acquisition the app was never told
            about is refused too;
          * a path **inside the repo** — the user's work does not live in the app's source tree,
            where a `git clean` would take it;
          * an existing *file*.

        An existing non-empty folder with no marker is **adopted**, not rejected — he pointed at it
        deliberately, and refusing would only make him make another one beside it.
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
                f"a project may not live inside the Camea repo ({_fwd(root)}): {_fwd(rp)}. "
                f"Your work is not the app's source. Choose a folder outside it."
            )

        if rp.exists() and not rp.is_dir():
            raise PathRefused(f"not a directory: {_fwd(rp)}")

        if not rp.exists():
            if not create:
                raise ProjectError(f"no such project folder: {_fwd(rp)}")
            rp.mkdir(parents=True, exist_ok=True)

        return cls(rp)

    @classmethod
    def create(
        cls,
        path: str | Path,
        *,
        feature: str,
        name: str,
        dataset_key: str,
        dataset: str,
        data_dir: str | Path = "",
        analysis_id: str | None = None,
    ) -> Project:
        """Make the folder and write its manifest. **No document yet** — `core.document` authors
        that and hands it to `save_document`.

        ⭐ The document's `id` MUST equal the `analysis_id` recorded here. `guard_slot` enforces it
        on every write, and that is what makes v1's slot collision impossible rather than merely
        unlikely.

        ⛔ Refuses a folder that already holds a project. Overwriting one silently is how a day of
        sweeping disappears; the caller is told to pick another folder.
        """
        if not feature:
            raise ProjectError("a project must name its feature")

        pr = cls.open(path, create=True)
        if (pr.path / MARKER).is_file():
            existing = pr._read_manifest()
            raise ProjectError(
                f"{_fwd(pr.path)} already holds the project "
                f"{existing.get('name') or existing.get('analysis_id')!r}. "
                f"Choose an empty folder, or open that project instead."
            )

        aid = analysis_id or new_analysis_id(name)
        atomic_write_text(
            pr.path / MARKER,
            dumps(
                {
                    "camea_project": PROJECT_VERSION,
                    "analysis_id": aid,
                    "feature": feature,
                    "name": name or aid,
                    "dataset_key": dataset_key,
                    "dataset": dataset,
                    "data_dir": _fwd(data_dir) if data_dir else "",
                    "created": _iso(),
                    "note": "Camea keeps this project's work in this folder. The dataset is "
                    "elsewhere and is never written to.",
                }
            ),
        )
        return pr

    # ---------------------------------------------------------------------------------------------
    # paths
    # ---------------------------------------------------------------------------------------------

    @property
    def manifest_path(self) -> Path:
        return self.path / MARKER

    @property
    def document_path(self) -> Path:
        return self.path / DOCUMENT

    @property
    def autosave_path(self) -> Path:
        """The crash net. ⭐ **One slot per PROJECT**, never per dataset — in v1 the autosave was
        keyed on the dataset directory and two trial ranges of one dataset collided in it. Two
        ranges are two projects, and two projects are two folders."""
        return self.path / AUTOSAVE

    @property
    def outputs_dir(self) -> Path:
        d = self.path / OUTPUTS
        d.mkdir(parents=True, exist_ok=True)
        return d

    def is_project(self) -> bool:
        return self.manifest_path.is_file()

    # ---------------------------------------------------------------------------------------------
    # the manifest
    # ---------------------------------------------------------------------------------------------

    def _read_manifest(self) -> dict:
        p = self.manifest_path
        try:
            man = json.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError as e:
            raise NoSuchProject(f"not a Camea project folder: {_fwd(self.path)}") from e
        except (OSError, ValueError) as e:
            raise ProjectError(f"unreadable project manifest {_fwd(p)}: {e}") from e
        if not isinstance(man, dict):
            raise ProjectError(f"unreadable project manifest {_fwd(p)}")
        return man

    @property
    def analysis_id(self) -> str:
        return str(self._read_manifest().get("analysis_id") or "")

    def summary(self) -> Analysis:
        """`api.schemas.AnalysisSummary`'s source. Read off the FILES every time — no cache."""
        return read_analysis(
            self._read_manifest(),
            manifest_path=self.manifest_path,
            document_path=self.document_path,
            autosave_path=self.autosave_path,
            fallback_id=self.path.name,
        )

    def rename(self, name: str) -> Analysis:
        """Rewrites the manifest. ⭐ **The folder does not move and the id is forever** — a rename
        that moved the folder would break the slot guard and every path the document carries. (It
        would also silently relocate the user's work out from under an Explorer window he has open.)
        """
        man = self._read_manifest()
        man["name"] = name or man.get("name") or man.get("analysis_id")
        atomic_write_text(self.manifest_path, dumps(man))
        return self.summary()

    # ---------------------------------------------------------------------------------------------
    # writing
    # ---------------------------------------------------------------------------------------------

    def _guard(self, doc: Mapping | str) -> None:
        if isinstance(doc, str):
            return  # pre-serialised: the caller has already been through core.document
        guard_slot(self.analysis_id, doc, self._read_manifest())

    def save_document(self, doc: Mapping | str) -> dict:
        """Write the project's document. -> `{path, bytes, saved_at}` (`api.schemas.SaveResult`).

        ⚠️ It writes what it is given. Validate → normalise → stamp happen in `core.document`, **in
        that order**, before this is called. Storage does not second-guess the content; it guards
        the *place*.
        """
        self._guard(doc)
        return self._write(self.document_path, doc)

    def autosave(self, doc: Mapping | str) -> dict:
        """The crash net. Debounced 2 s by the front end, **plus unconditionally on every `A`/`E`**.

        🔴 **A FAILURE IS LOUD.** It raises, and is never swallowed — `localStorage` failed
        *silently* in the artefact sandbox and nearly cost a day's work, which is why this is a
        server file at all.

        It writes **beside** the document and never over it: recovery must be able to show the user
        both and let him choose.
        """
        self._guard(doc)
        return self._write(self.autosave_path, doc)

    @staticmethod
    def _write(p: Path, doc: Mapping | str) -> dict:
        refuse_write(p)
        text = doc if isinstance(doc, str) else dumps(doc)
        atomic_write_text(p, text)
        return {
            "path": _fwd(p),
            "bytes": len(text.encode("utf-8")),
            "saved_at": _iso(),
            "warnings": [],
        }

    def recovery(self) -> dict | None:
        """Is there an autosave NEWER than the saved document? -> `{path, saved_at, newer}` or None.
        An autosave older than the document is not a recovery prompt, it is noise."""
        a = self.autosave_path
        if not a.is_file():
            return None
        doc = self.document_path
        doc_mtime = doc.stat().st_mtime if doc.is_file() else 0.0
        return {
            "path": _fwd(a),
            "saved_at": _iso(a.stat().st_mtime),
            "newer": a.stat().st_mtime > doc_mtime,
        }

    # ---------------------------------------------------------------------------------------------
    # delete
    # ---------------------------------------------------------------------------------------------

    def delete(self) -> str:
        """Remove the project's files. -> the path.

        🔴 **THE FOLDER IS THE USER'S, NOT OURS.** Under the old layout this was an `rmtree` of a
        uuid-named directory Camea had made. Now the folder is one *he* named and may hold things we
        did not put there, so we delete **only Camea's own files** — the manifest, the document, the
        autosave, and `outputs/` — and then remove the folder itself **only if it is empty**. A
        stray PDF of his notes in that folder must survive his deleting the project.

        (This is the one operation in Camea that destroys the user's work. It does not get to be
        clever, and it does not get to be greedy.)
        """
        if not self.is_project():
            raise NoSuchProject(f"not a Camea project folder: {_fwd(self.path)}")

        outputs = self.path / OUTPUTS
        if outputs.is_dir():
            rd = outputs.resolve()
            # Re-checked AFTER resolving symlinks: the rmtree target must still be our own
            # `outputs/`, directly inside this project folder.
            if rd.parent != self.path.resolve() or rd.name != OUTPUTS:
                raise ProjectError(f"refusing to delete outside the project: {_fwd(rd)}")
            shutil.rmtree(rd)

        for f in (self.document_path, self.autosave_path, self.manifest_path):
            try:
                f.unlink()
            except FileNotFoundError:
                pass
            except OSError as e:
                raise ProjectError(f"could not delete {_fwd(f)}: {e}") from e

        try:
            self.path.rmdir()  # only if HE left nothing else in it
        except OSError:
            pass
        return _fwd(self.path)


# =================================================================================================
# THE REGISTRY — `analysis_id` -> the folder it lives in
# =================================================================================================


class ProjectSet:
    """Every project folder the user has saved into, addressed by `analysis_id`.

    ⭐ **This is the `Workspace` shape, kept deliberately.** `core.document` calls `document_path`,
    `autosave_path`, `save_document`, `autosave`, `recovery`, `get` and `outputs_dir` on a workspace;
    this class answers all of them by looking the id up in the remembered folders first. The mosaic
    feature, the save/load routes and the whole front end therefore never learn that storage changed.

    The folder list is a plain list of PATHS in `camea.settings` — see that module's standing rule.
    It is a convenience index, not the truth: the truth is the manifest in each folder, and a folder
    the user has moved or deleted simply drops out of the listing rather than failing it.
    """

    def __init__(self, folders: list[str]) -> None:
        self._folders = folders
        self._by_id: dict[str, str] = {}
        self._lock = threading.RLock()

    # --- resolution -------------------------------------------------------------------------

    def _lookup(self, analysis_id: str) -> Project:
        """`analysis_id` -> its `Project`. Reads the manifests once, then caches.

        ⚠️ `analysis_id` arrives over HTTP. It is never used to build a path here — it is *matched*
        against the ids the manifests declare — so `../../Windows` cannot become a directory.
        """
        with self._lock:
            hit = self._by_id.get(analysis_id)
        if hit is not None:
            pr = Project(Path(hit))
            if pr.is_project():
                return pr
            with self._lock:  # it moved or was deleted under us; re-scan rather than 500
                self._by_id.pop(analysis_id, None)

        for folder in self._folders:
            pr = Project(Path(folder))
            if not pr.is_project():
                continue
            try:
                aid = pr.analysis_id
            except (ProjectError, NoSuchProject):
                continue
            if aid:
                with self._lock:
                    self._by_id[aid] = pr.path.as_posix()
            if aid == analysis_id:
                return pr

        raise NoSuchProject(f"no project with id {analysis_id!r} in the folders Camea remembers")

    def get(self, analysis_id: str) -> Analysis:
        return self._lookup(analysis_id).summary()

    def folder_of(self, analysis_id: str) -> Path:
        return self._lookup(analysis_id).path

    # --- the `Workspace` surface `core.document` calls ----------------------------------------

    def document_path(self, analysis_id: str) -> Path:
        return self._lookup(analysis_id).document_path

    def autosave_path(self, analysis_id: str) -> Path:
        return self._lookup(analysis_id).autosave_path

    def outputs_dir(self, analysis_id: str) -> Path:
        return self._lookup(analysis_id).outputs_dir

    def save_document(self, analysis_id: str, doc: Mapping | str) -> dict:
        return self._lookup(analysis_id).save_document(doc)

    def autosave(self, analysis_id: str, doc: Mapping | str) -> dict:
        return self._lookup(analysis_id).autosave(doc)

    def recovery(self, analysis_id: str) -> dict | None:
        return self._lookup(analysis_id).recovery()

    def rename(self, analysis_id: str, name: str) -> Analysis:
        return self._lookup(analysis_id).rename(name)

    def delete(self, analysis_id: str) -> str:
        pr = self._lookup(analysis_id)
        path = pr.delete()
        with self._lock:
            self._by_id.pop(analysis_id, None)
        return path

    # --- listing ------------------------------------------------------------------------------

    def analyses(
        self, dataset_key: str | None = None, feature: str | None = None
    ) -> list[Analysis]:
        """Every remembered project, **newest touch first**.

        One unreadable or vanished folder never blanks the list — it is skipped. A drive that is
        unplugged must cost the user his *listing of that project*, not his home screen.
        """
        out: list[Analysis] = []
        seen: set[str] = set()
        for folder in self._folders:
            pr = Project(Path(folder))
            if not pr.is_project():
                continue
            try:
                a = pr.summary()
            except (ProjectError, NoSuchProject, OSError):
                continue
            if a.analysis_id in seen:
                continue  # the same folder remembered twice must not list twice
            seen.add(a.analysis_id)
            with self._lock:
                self._by_id[a.analysis_id] = pr.path.as_posix()
            if dataset_key is not None and a.dataset_key != dataset_key:
                continue
            if feature is not None and a.feature != feature:
                continue
            out.append(a)
        out.sort(key=lambda a: a.modified, reverse=True)
        return out

    def by_dataset(self) -> dict[str, list[Analysis]]:
        """`{dataset_key: [Analysis, ...]}`, newest first within each dataset. Datasets with no
        project simply do not appear — core does not enumerate datasets."""
        idx: dict[str, list[Analysis]] = {}
        for a in self.analyses():
            idx.setdefault(a.dataset_key, []).append(a)
        return idx

    def data_dirs(self) -> list[str]:
        """⭐ Every dataset folder a remembered project was built on.

        This is how `GET /api/datasets/{key}` finds a dataset again on a cold start now that there
        is no root registry to re-scan: a project records its `data_dir`, so opening last week's
        project still works without the app remembering anything *about* the data.
        """
        out: list[str] = []
        for a in self.analyses():
            if a.data_dir and a.data_dir not in out:
                out.append(a.data_dir)
        return out
