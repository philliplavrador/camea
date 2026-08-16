"""migrate.py — ⭐ **BRINGING PRE-R44 PROJECTS HOME.** CORE. Feature-agnostic. Runs once, at launch.

**His ruling, 2026-08-10 (BEHAVIOUR R44):** *"camea saves project-specific files to its own repo
automatically"*, and — asked what should happen to the projects already sitting in folders he named
— *"migrate it all if possible"*.

So on the first launch after R44 this module walks every project the old layouts could have left
behind and moves it into `core.project.store_root()`:

  1. the folders in the pre-R44 `settings.projects` index (R42/R43: *"Save into"*);
  2. anything left in `app_state_dir()/drafts/` (R43's unsaved video builds — which under R44 are
     just projects, so they are kept rather than swept);

and, inside each, brings the video feature's flat artifacts (`<project>.png`, `-preview.png`,
`-positions.csv`, `-build.json`) into `outputs/`, rewriting the document's `build.outputs` to match.

🔴 **THE FOUR RULES THIS MODULE OBEYS.** Migration touches the user's real work, unattended, before
he has clicked anything. It is the most dangerous code in the app after `Project.delete`.

  1. ⛔ **NOTHING OF HIS IS TAKEN.** Only Camea's own files move out of a folder he named — the
     manifest, the document, the autosave, `outputs/`, and the video artifacts the document itself
     names. A thesis PDF he kept beside his mosaic stays exactly where it is, and the folder is
     removed only if it ends up empty (`Project.move_to`, then an `rmdir` that is allowed to fail).
  2. ⛔ **IT NEVER DESTROYS TO MAKE ROOM.** A destination id already in the store, an unreadable
     manifest, a locked file, an unplugged drive — every one of them **skips that project and
     reports it**. A half-migrated project is left where it was, still openable by the old path.
  3. ⛔ **IT IS IDEMPOTENT AND IT IS NOT A LOOP.** A folder already in the store is skipped; a
     project that fails is reported and left for the next launch to try again. Running it twice on
     the same disk does nothing the second time.
  4. ⛔ **IT NEVER FAILS A LAUNCH.** Every unit of work is wrapped. The worst outcome is a report
     with entries in `failed` and an app that starts.

⚠️ **`settings.projects` is drained only when nothing failed.** If a drive was unplugged this
launch, the index survives so the next launch can finish the job — that list is the only record of
where those folders were.
"""

from __future__ import annotations

import json
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from camea.core.jobs import eta_from_counts
from camea.core.project import (
    MARKER,
    Project,
    ProjectError,
    in_store,
    store_root,
)
from camea.core.workspace import (
    OUTPUTS,
    app_state_dir,
    atomic_write_text,
    dumps,
)
from camea.core.workspace import _fwd as _fwd

__all__ = ["MigrationReport", "migrate_to_store", "LEGACY_DRAFTS"]

#: R43's draft area. Its contents are real projects under R44 and are kept, not swept.
LEGACY_DRAFTS = "drafts"


@dataclass
class MigrationReport:
    """What the launch migration did. Rendered once on the home screen, then forgotten."""

    #: `{"name": ..., "from": ..., "to": ...}` per project that came home.
    migrated: list[dict] = field(default_factory=list)
    #: `{"path": ..., "reason": ...}` per project that did not. It is still where it was.
    failed: list[dict] = field(default_factory=list)

    @property
    def ran(self) -> bool:
        return bool(self.migrated or self.failed)

    def to_json(self) -> dict:
        return {"migrated": list(self.migrated), "failed": list(self.failed)}


def _legacy_draft_folders() -> list[str]:
    """R43's `app_state_dir()/drafts/<id>/`, if any survived the change."""
    d = app_state_dir() / LEGACY_DRAFTS
    try:
        return sorted(p.as_posix() for p in d.iterdir() if p.is_dir())
    except OSError:
        return []


def _own_bytes(pr: Project) -> int:
    """How many bytes of this folder are **Camea's** — the denominator the migration divides by.

    ⛔ Deliberately `own_entries()` and not the folder: a thesis PDF the user keeps beside his mosaic
    is not going anywhere, so counting it would make the bar promise work that will never happen.
    """
    total = 0
    for entry in pr.own_entries():
        try:
            if entry.is_dir():
                total += sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
            elif entry.is_file():
                total += entry.stat().st_size
        except OSError:
            pass                                        # unreadable is not un-migratable
    return total


def _human_bytes(n: int) -> str:
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.1f} GB"
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.0f} MB"
    return f"{n / 1024:.0f} KB"


def _console(line: str) -> None:
    """⚠️ Wrapped, and **ASCII only** at the call sites: a launch is not failable, and that includes
    a closed stdout in a frozen build *and* a cp1252 console that cannot render an em dash. (The
    lines the API sends travel as JSON and are under no such restriction.)"""
    try:
        print(line, flush=True)
    except Exception:                                   # noqa: BLE001
        pass


def migrate_to_store(legacy_folders: list[str],
                     progress: Callable[[str], None] | None = None) -> MigrationReport:
    """Move every pre-R44 project into the store. -> what happened. **Never raises.**

    `legacy_folders` is the old `settings.projects` list; R43's drafts are found here rather than
    passed in, because nothing outside this module should still know that directory existed.

    ⏱️ **IT NARRATES ITSELF TO THE CONSOLE (BEHAVIOUR R48), AND THAT IS THE HALF-MEASURE IT IS.**
    This runs *inside* `create_app()`, so the server accepts no connection until it returns — and a
    multi-GB `shutil.move` across drives can hold that for minutes with no HTTP surface in existence
    to serve a bar. Until it moves behind a startup event, the console is the only place a waiting
    human can be told anything, so it is told: the count, the bytes, and an estimate.

    ⏱️ **The countable unit is BYTES OF CAMEA'S OWN FILES**, summed up front across every project
    that will actually move. ⚠️ It advances **per project**, because `shutil.move` has no callback —
    so a single large project cannot anchor an estimate at all (2 % is never reached until it is
    100 % done) and prints its size instead of a countdown. That is honest; it is not sufficient,
    and the fix is the startup event, not a fake number.

    `progress` takes one line of plain text. It defaults to printing.
    """
    report = MigrationReport()
    say = _console if progress is None else progress
    seen: set[str] = set()

    # --- pass 1: WHAT is moving, and HOW BIG is it -------------------------------------------
    # ⭐ The filtering here is exactly `_migrate_one`'s first two early returns (not a project;
    # already home), lifted so the work can be counted before it starts. Anything this pass cannot
    # judge is kept and handed to `_migrate_one`, which owns every refusal and every `failed` entry.
    todo: list[tuple[Path, int]] = []
    for folder in [*legacy_folders, *_legacy_draft_folders()]:
        key = folder.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        pth = Path(folder)
        try:
            pr = Project(pth)
            if not pr.is_project() or in_store(pth):
                continue
            todo.append((pth, _own_bytes(pr)))
        except Exception:                               # noqa: BLE001 — a launch is not failable
            todo.append((pth, 0))                       # let `_migrate_one` produce the real reason

    if not todo:
        return report                                   # ⭐ every launch after the first: silent

    # --- pass 2: move them, saying so ---------------------------------------------------------
    total = sum(b for _, b in todo)
    t0 = time.monotonic()
    done = 0
    say(f"Camea: bringing {len(todo)} project(s) home into its own store "
        f"({_human_bytes(total)}). The app starts when this finishes.")

    for i, (pth, nbytes) in enumerate(todo):
        eta = eta_from_counts(time.monotonic() - t0, done, total)
        left = f", about {int(eta)} s left" if eta is not None else ""
        say(f"  [{i + 1}/{len(todo)}] {int(100 * done / total) if total else 100}% - "
            f"moving {pth.name} ({_human_bytes(nbytes)}){left}")
        try:
            _migrate_one(pth, report)
        except Exception as e:                          # noqa: BLE001 — a launch is not failable
            report.failed.append({"path": _fwd(pth), "reason": f"{type(e).__name__}: {e}"})
        done += nbytes

    say(f"Camea: {len(report.migrated)} project(s) came home, {len(report.failed)} did not, "
        f"in {time.monotonic() - t0:.1f} s.")
    return report


def _migrate_one(folder: Path, report: MigrationReport) -> None:
    """One folder -> the store. Anything that is not a project is silently not our business."""
    pr = Project(folder)
    if not pr.is_project():
        return                                          # moved, deleted, or never was one
    if in_store(folder):
        return                                          # ⭐ idempotent: already home

    try:
        man = pr._read_manifest()
    except ProjectError as e:
        report.failed.append({"path": _fwd(folder), "reason": str(e)})
        return

    aid = str(man.get("analysis_id") or "").strip()
    if not aid:
        report.failed.append({
            "path": _fwd(folder),
            "reason": "this project's manifest carries no analysis_id — Camea will not guess one",
        })
        return

    dest = store_root() / aid
    if (dest / MARKER).is_file():
        report.failed.append({
            "path": _fwd(folder),
            "reason": f"a project with the id {aid!r} is already in Camea's store; "
                      f"this folder was left alone",
        })
        return

    try:
        moved = pr.move_to(dest)
    except Exception as e:                              # noqa: BLE001
        report.failed.append({"path": _fwd(folder), "reason": f"{type(e).__name__}: {e}"})
        return

    # The folder he named is now empty of ours. If it holds nothing else, take it; if it holds his
    # files, leave it standing. (`move_to` already tries this for the drafts case; a folder the user
    # named is the case it cannot assume.)
    try:
        folder.rmdir()
    except OSError:
        pass

    try:
        _collect_flat_outputs(moved)
    except Exception as e:                              # noqa: BLE001
        # The project IS migrated — it opens, it lists, its document is intact. Only the artifact
        # tidy-up failed, and the outputs route still resolves a name in the project folder.
        report.failed.append({
            "path": _fwd(moved.path),
            "reason": f"moved into the store, but its built files could not be tidied into "
                      f"outputs/ ({type(e).__name__}: {e})",
        })

    report.migrated.append({
        "name": str(man.get("name") or aid),
        "from": _fwd(folder),
        "to": _fwd(moved.path),
    })


def _collect_flat_outputs(pr: Project) -> None:
    """⭐ **R43's flat video artifacts -> `outputs/`.**

    R43.5 wrote `<project>.png` and friends directly into the folder, because that folder was the
    export and opening it had to show him his mosaic. Under R44 nobody opens it — the app browses
    `outputs/` — so every feature's built files belong in the one place the browser reads.

    ⚠️ **The document is the authority on which files are the build's**, not a glob: only names
    listed in `build.outputs` move, so a file of the user's that happens to sit beside them is not
    swept up. `build.outputs` records **filenames, never paths** (R43.7), and it keeps doing so —
    the outputs route resolves them against `outputs/` now.
    """
    doc_path = pr.document_path
    if not doc_path.is_file():
        return
    try:
        doc = json.loads(doc_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(doc, dict):
        return

    outputs = ((doc.get("build") or {}).get("outputs") or {})
    if not isinstance(outputs, dict) or not outputs:
        return

    out_dir = pr.path / OUTPUTS
    moved_any = False
    for logical, recorded in list(outputs.items()):
        if not isinstance(recorded, str) or not recorded:
            continue
        name = Path(recorded).name
        flat = pr.path / name
        if not flat.is_file():
            continue                                    # already in outputs/, or never written
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / name
        if target.exists():
            continue                                    # ⛔ never overwrite what is already there
        shutil.move(str(flat), str(target))
        moved_any = True

    if moved_any:
        # ⚠️ The document is rewritten UNCHANGED — `build.outputs` holds bare filenames and those
        # did not move. The write exists so the project's `modified` reflects that it was touched,
        # and it goes through `atomic_write_text` like every other byte the app writes.
        atomic_write_text(doc_path, dumps(doc))
