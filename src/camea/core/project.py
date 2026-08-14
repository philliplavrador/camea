"""project.py — ⭐ **A PROJECT IS ONE FOLDER, AND CAMEA OWNS IT.** CORE. Feature-agnostic.

    DATASET = raw, untouched, read-only. A folder of .dat frames + log.txt. **The user names this.**
    PROJECT = what you did to it. It lives in **Camea's own store**, in a folder named after its id.
              The user never names it, never browses to it, and never has to keep track of it.

The layout, in full:

    store_root()/<analysis_id>/       %LOCALAPPDATA%/Camea/projects/<analysis_id>/
      camea-project.json        the manifest + the marker. "this folder is a Camea project."
      document.camea.json       ⭐ THE WORK. The file the scorer reads.
      autosave.camea.json       the crash net. Never the same file as the document.
      outputs/                  ⭐ everything a feature builds. The ONLY door to these is the app.

⭐ **WHY THIS EXISTS — his ruling, 2026-08-10 (BEHAVIOUR R44).** *"I want things changed to where
camea saves project-specific files to its own repo automatically, and if users want to browse their
project data they have to do it through the app itself."* The app now asks **one** path question —
where the data comes **from** — and answers the other one itself.

⚠️ **This REVERSES R42 (2026-07-25) and most of R43 (2026-08-07),** which asked the user for a save
folder per project and made the video task ask for it last. Both are retired, deliberately and by
his instruction; `docs/BEHAVIOUR.md` R44 carries the current rule and says what it supersedes. The
things those rulings bought that survive: the folder is still *one* folder, its files still sit
directly in it, and the id is still forever.

⭐ **WHY THE ID IS THE FOLDER NAME.** Nobody reads this path, so it does not need to be legible — it
needs to be **collision-free and stable**. A rename rewrites the manifest and never moves the folder
(a move would break the slot guard and every path the document carries), and two projects with the
same name are two ids and therefore two folders.

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
`core.document` already calls on a `Workspace`. That is what keeps this change out of the mosaic —
and it is why moving the store under R44 touched neither feature's document code.

⚠️ **A `ProjectSet` still takes a LIST OF FOLDERS**, because two callers need one over a folder that
is not (yet) the store's business: `ProjectSet([pr.path])` scopes a create to the project just made,
and `core.migrate` reads a project out of an old user-named folder. Everything the app serves comes
from `ProjectSet.of_store()`.
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
    RECORDINGS,
    VIDEOS,
    Analysis,
    NoSuchAnalysis,
    PathRefused,
    SlotMismatch,
    WorkspaceError,
    app_state_dir,
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
    # ⭐ THE STORE (R44)
    "STORE",
    "store_root",
    "store_folders",
    "in_store",
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

#: The store's subdirectory of the app-state dir.
STORE = "projects"


# =================================================================================================
# ⭐ THE STORE — where every project lives now (R44)
# =================================================================================================


def store_root() -> Path:
    """`%LOCALAPPDATA%/Camea/projects` — created on demand.

    ⭐ **THE STORE IS THE INDEX.** There is no remembered list of folders any more: to list the
    user's projects you read this directory. `settings.projects` existed only because projects were
    scattered across folders he named, and it is gone with them — a settings file that got wiped
    used to cost him the *list*, and now it cannot.

    ⚠️ `app_state_dir()` honours `CAMEA_STATE_DIR`, so a test process, the e2e harness and a
    portable install each get their own store for free. Do not cache this.
    """
    d = app_state_dir() / STORE
    d.mkdir(parents=True, exist_ok=True)
    return d


def store_folders() -> list[str]:
    """Every project folder in the store, sorted. One unreadable entry never fails the listing."""
    try:
        return sorted(d.as_posix() for d in store_root().iterdir() if d.is_dir())
    except OSError:
        return []


def in_store(path: str | Path) -> bool:
    """Is this folder one of the store's own project folders? ⭐ The one question `delete()` asks
    before it is allowed to be thorough — see there."""
    try:
        return Path(path).resolve().parent == store_root().resolve()
    except OSError:
        return False


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

        An existing non-empty folder with no marker is **adopted**, not rejected — under R44 the app
        only opens folders it made, but `core.migrate` still opens the user-named folders of old
        projects, and those may hold his own files beside ours.

        ⚠️ **ONE EXEMPTION, and only from the repo rule: Camea's own state directory** — which under
        R44 is where the **store** lives, so this is the normal path, not an edge case. The repo
        refusal protects *his work* from a `git clean`; `app_state_dir()` is the app's by
        construction, and a dev install may put it beside the checkout (`CAMEA_STATE_DIR`; the e2e
        harness does exactly this). ⛔ `refuse_write` is **not** exempted: the app does not write on
        the evidence, here or anywhere.
        """
        p = Path(path).expanduser()
        try:
            rp = p.resolve()
        except OSError:
            rp = p.absolute()

        refuse_write(rp)  # data/ and any raw acquisition folder -> DatasetIsReadOnly

        root = repo_root()
        if root is not None and is_inside(rp, root) and not is_inside(rp, app_state_dir()):
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

        ⚠️ Most callers want `create_in_store` (R44). This one takes an explicit path and is what
        that is built on; `core.migrate` is the only other caller.

        ⭐ The document's `id` MUST equal the `analysis_id` recorded here. `guard_slot` enforces it
        on every write, and that is what makes v1's slot collision impossible rather than merely
        unlikely.

        ⛔ Refuses a folder that already holds a project. Overwriting one silently is how a day of
        sweeping disappears; the caller is told so by name.
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
                    "elsewhere and is never written to. Browse this project from inside Camea.",
                }
            ),
        )
        return pr

    @classmethod
    def create_in_store(
        cls,
        *,
        feature: str,
        name: str,
        dataset_key: str,
        dataset: str,
        data_dir: str | Path = "",
        analysis_id: str | None = None,
    ) -> Project:
        """⭐ **THE ONLY WAY THE APP MAKES A PROJECT (R44).** `store_root()/<analysis_id>/`.

        The id is minted here if the caller did not bring one, and it *is* the folder name — so
        there is no path to choose, nothing to refuse, and no way for two projects to collide. The
        user is never asked where this goes, because the answer is never interesting to him.
        """
        aid = analysis_id or new_analysis_id(name)
        return cls.create(
            store_root() / aid,
            feature=feature,
            name=name,
            dataset_key=dataset_key,
            dataset=dataset,
            data_dir=data_dir,
            analysis_id=aid,
        )

    # ---------------------------------------------------------------------------------------------
    # move — ⭐ HOW A PRE-R44 PROJECT GETS INTO THE STORE  (`core.migrate`)
    # ---------------------------------------------------------------------------------------------

    def move_to(self, dest: str | Path) -> Project:
        """Move this project into `dest`. -> the project, at its new home.

        ⭐ **Its one caller is now `core.migrate`** (R44): every project the user saved into a folder
        he named under R42/R43 comes home to `store_root()/<id>/` through here, once, on the first
        launch after the change. (It was written for R43's draft→named-folder save, which R44
        retires; the mechanics were right and are reused rather than rewritten.)

        🔴 **THE REFUSALS ARE `open`'s, UNCHANGED.** A destination inside a dataset or inside the
        repo is refused here exactly as it would have been at create time, and a destination that
        already holds a project is refused rather than merged.

        ⚠️ **It moves the CONTENTS, not the folder.** `shutil.move(dir, dir)` would nest us inside an
        existing destination, and `open()`'s standing rule is that a non-empty folder the user
        deliberately pointed at is *adopted*, not rejected. Per entry: a rename on the same volume, a
        copy across drives. Anything already there under one of our names is refused before a single
        byte moves — the destination is the user's folder, and this never overwrites his files.

        🔴 **IT MOVES ONLY WHAT CAMEA OWNS** (`own_entries`) — not everything in the folder. Under
        R43 the source was always a draft folder Camea had made, so "move the contents" and "move
        our files" were the same set. Migration made them different: the source is now a folder the
        **user** named, and it may hold a thesis PDF he keeps beside his mosaic. Taking that with us
        would be the app quietly relocating his files, which is precisely what R44 must not do.
        """
        if not self.is_project():
            raise NoSuchProject(f"not a Camea project folder: {_fwd(self.path)}")

        target = Project.open(dest, create=True).path      # the three refusals, verbatim
        if target.resolve() == self.path.resolve():
            return self
        if (target / MARKER).is_file():
            existing = Project(target)._read_manifest()
            raise PathRefused(
                f"{_fwd(target)} already holds the project "
                f"{existing.get('name') or existing.get('analysis_id')!r}. "
                f"Choose an empty folder, or open that project instead."
            )

        moving = self.own_entries()
        clashes = [e.name for e in moving if (target / e.name).exists()]
        if clashes:
            raise PathRefused(
                f"{_fwd(target)} already contains {', '.join(sorted(clashes))}. Camea will not "
                f"write over what is already in your folder — choose another one."
            )

        for entry in moving:
            shutil.move(str(entry), str(target / entry.name))
        try:
            self.path.rmdir()
        except OSError:
            pass                                          # a lock on the husk is not a failed save

        moved = Project(target)
        man = moved._read_manifest()
        if man.pop("draft", None) is not None:
            # A pre-R44 draft (R43's unsaved video build). In the store there is no such thing as a
            # project without a home, so the flag is dropped as it arrives.
            atomic_write_text(moved.manifest_path, dumps(man))
        return moved

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

    @property
    def videos_dir(self) -> Path:
        """The project's own copies of its input videos. See `workspace.VIDEOS`."""
        d = self.path / VIDEOS
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def recordings_dir(self) -> Path:
        """The project's own copies of its MEA recordings. See `workspace.RECORDINGS`.

        ⚠️ Mirrors `videos_dir` deliberately, down to creating on demand: the two answer the same
        question ("where does the project keep the file the user gave it?") and the day they stop
        agreeing is the day one of them gets forgotten by `own_entries`."""
        d = self.path / RECORDINGS
        d.mkdir(parents=True, exist_ok=True)
        return d

    def is_project(self) -> bool:
        return self.manifest_path.is_file()

    def own_entries(self) -> list[Path]:
        """🔴 **EVERY FILE IN THIS FOLDER THAT IS CAMEA'S, AND NOTHING ELSE.** Sorted, existing only.

        This is the answer to the one question `move_to` and `delete` must never get wrong when the
        folder belongs to the **user**: the manifest, the document, the autosave, `outputs/`,
        `videos/`, `recordings/` — and the files the **document itself names** in `build.outputs`,
        because the video feature wrote its artifacts flat into the project folder before R44 and
        those are ours too.

        ⚠️ **The document is the authority on the build's files, never a glob.** `*.png` in that
        folder would sweep up a screenshot the user dropped there; `build.outputs` is what the app
        actually wrote, recorded by the code that wrote it.

        🔴 **EVERY NEW INPUT FOLDER MUST BE ADDED HERE, AND THE COST OF FORGETTING IS GIGABYTES.**
        `recordings/` (2026-08-14, plan 002) holds copies of MaxWell `.h5` files — a few GB each.
        Left out of this set, `move_to` would migrate a pre-R44 project and leave them behind in the
        user's folder, and `delete()` on that same folder would too. ⚠️ **Neither shows up in
        ordinary testing**: every project the app makes today is `in_store`, and that branch
        `rmtree`s the whole folder without consulting this method at all. So the guard is a test —
        `tests/unit/test_project.py :: test_own_entries_includes_every_folder_camea_writes_into`,
        which enumerates the constants rather than listing names by hand, and goes red the moment a
        seventh name is added to storage without being added here.
        """
        names = {MARKER, DOCUMENT, AUTOSAVE, OUTPUTS, VIDEOS, RECORDINGS}
        try:
            doc = json.loads(self.document_path.read_text(encoding="utf-8"))
            outputs = ((doc.get("build") or {}).get("outputs") or {}) if isinstance(doc, dict) else {}
            names |= {Path(v).name for v in outputs.values() if isinstance(v, str) and v}
        except (OSError, ValueError):
            pass                     # no document, or an unreadable one: our four names still hold
        return sorted(p for p in (self.path / n for n in names) if p.exists())

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
        """Remove the project. -> the path.

        🔴 **THIS IS THE ONE OPERATION IN CAMEA THAT DESTROYS THE USER'S WORK.** It does not get to
        be clever, and it does not get to be greedy. There are two cases and they are not the same:

        * **In the store** (`in_store`, the R44 normal case): the folder is Camea's, made by Camea,
          named after an id. Everything in it is the project, including outputs the user may never
          have copied out — so it goes whole. ⚠️ The target is re-checked to be a **direct child of
          `store_root()` after resolving symlinks**, because this is an `rmtree`.
        * **Anywhere else** (a pre-R44 folder the user named, met by `core.migrate` or by a project
          whose migration failed): only **Camea's own files** go — the manifest, the document, the
          autosave, `outputs/` — and the folder itself only if it is then empty. A stray PDF of his
          notes in that folder must survive his deleting the project.
        """
        if not self.is_project():
            raise NoSuchProject(f"not a Camea project folder: {_fwd(self.path)}")

        if in_store(self.path):
            rp = self.path.resolve()
            if rp.parent != store_root().resolve():
                raise ProjectError(f"refusing to delete outside the store: {_fwd(rp)}")
            shutil.rmtree(rp)
            return _fwd(self.path)

        # ⚠️ `own_entries()` is read BEFORE anything is removed — it consults the document to learn
        # which flat artifacts are the build's, and the document is one of the things going.
        ours = self.own_entries()

        for f in ours:
            if f.is_dir():
                rd = f.resolve()
                # Re-checked AFTER resolving symlinks: an rmtree target must still be directly
                # inside this project folder.
                if rd.parent != self.path.resolve():
                    raise ProjectError(f"refusing to delete outside the project: {_fwd(rd)}")
                shutil.rmtree(rd)
                continue
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
    """A set of project folders, addressed by `analysis_id`. ⭐ Normally **the store** (`of_store`).

    ⭐ **This is the `Workspace` shape, kept deliberately.** `core.document` calls `document_path`,
    `autosave_path`, `save_document`, `autosave`, `recovery`, `get` and `outputs_dir` on a workspace;
    this class answers all of them by looking the id up in its folders first. The mosaic feature, the
    save/load routes and the whole front end therefore never learn that storage changed — which is
    exactly what let R44 move every project into an app-owned store without touching a feature.

    The folder list is not the truth: the truth is the manifest in each folder. A folder that has
    vanished under us simply drops out of the listing rather than failing it.
    """

    def __init__(self, folders: list[str]) -> None:
        self._folders = folders
        self._by_id: dict[str, str] = {}
        self._lock = threading.RLock()

    @classmethod
    def of_store(cls) -> ProjectSet:
        """⭐ **THE APP'S PROJECTS (R44).** Read fresh off `store_root()` per call, so a project
        created or deleted in another tab (or by another Camea instance) is picked up without a
        restart. It never raises: an empty store is the honest first-run answer, not an error."""
        return cls(store_folders())

    # --- resolution -------------------------------------------------------------------------

    def _lookup(self, analysis_id: str) -> Project:
        """`analysis_id` -> its `Project`. Reads the manifests once, then caches.

        ⚠️ In the store the folder name IS the id, so this could be a single `is_dir()` — it is not,
        on purpose. The manifest stays the authority on which project a folder holds, so a folder
        renamed by hand, or one migrated in from a pre-R44 layout, resolves by what it *says* it is.

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

    def videos_dir(self, analysis_id: str) -> Path:
        return self._lookup(analysis_id).videos_dir

    def recordings_dir(self, analysis_id: str) -> Path:
        return self._lookup(analysis_id).recordings_dir

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
        """Every project in this set, **newest touch first**.

        One unreadable or vanished folder never blanks the list — it is skipped. A single corrupt
        manifest must cost the user that project's card, never his home screen.
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
