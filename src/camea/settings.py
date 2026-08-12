"""settings.py — ⭐ **WHAT THE APP REMEMBERS BETWEEN LAUNCHES. AND IT IS ONLY PATHS.**

    {"recent_datasets": ["D:/.../260620d"]}

That is the whole file. It lives in the OS's app-data directory (`core.workspace.app_state_dir()` —
`%LOCALAPPDATA%/Camea` on Windows), **not** in a project folder and **never** in a dataset.

⭐ **`projects` was REMOVED on 2026-08-10** (his ruling, BEHAVIOUR R44 — see `core/project.py`).
Projects live in Camea's own store now, so **the store IS the index**: to list them you read
`core.project.store_root()`, and there is nothing to keep in sync. (`dataset_roots` and `workspace`
went on 2026-07-25 for a different reason and are not coming back either.) What is left is
`recent_datasets` — the one thing the app cannot re-derive, because the data is the user's and lives
wherever he keeps it. It offers his last data paths back as completions.

⚠️ **`legacy_projects` is read but never written.** The pre-R44 `projects` key names folders the
user saved into under R42/R43; `core.migrate` reads it once, brings those projects into the store,
and the next `save()` drops the key. It is deliberately **not** on the wire — nothing in the app may
start depending on it again.

⛔ **NO DATASET KNOWLEDGE. THIS FILE IS WHERE IT WOULD BE MOST TEMPTING TO PUT SOME.**
A remembered *path* is not knowledge *about the data at that path*. So:

  * ✅ "the user last pointed at D:/…/260620" — a path. Fine.
  * ⛔ a trial number. An exclusion. A blank list. A threshold. A pass split. A "known bad frames"
    map keyed on dataset. **None of that may ever be persisted here**, not even "for convenience",
    not even behind a flag. The app opened his data once with 26 frames already gone before he had
    seen one of them, and it was ripped out at real cost. A settings file that remembers exclusions
    is that same bug wearing a hat: the second time he opens the dataset, the app has once again
    answered — on his behalf — the exact question the app exists to help him answer.

    Exclusions come from exactly two places, and neither of them is a settings file: **the human, in
    this session**, and **a project file he loaded.**

**A CORRUPT OR UNREADABLE SETTINGS FILE IS NOT A FATAL ERROR.** It is a convenience cache. It is
reset to defaults, loudly (`warnings`), and the app starts. ⭐ Under R44 losing this file costs the
user **nothing but his recent-dataset completions** — not even the home screen, because the projects
are read from the store, not from here. (Before R44 it held the list of project folders, and losing
it cost him that list.) The truth was always the manifest in the folder; now the folder is ours too.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from camea.core.workspace import app_state_dir, atomic_write_text, dumps

__all__ = ["Settings", "SETTINGS", "settings_path", "MAX_RECENT"]

#: The file, inside `app_state_dir()`.
FILENAME = "settings.json"

#: How many recently-opened datasets we keep. A list, not a science.
MAX_RECENT = 12


def settings_path() -> Path:
    return app_state_dir() / FILENAME


def _fwd(p: str | Path) -> str:
    """Forward slashes on the wire and on disk. A Windows path in JSON is a wall of escapes, and the
    UI prints these."""
    return str(p).replace("\\", "/")


def _dedup(paths: list[str]) -> list[str]:
    """Order-preserving, case-insensitively de-duplicated (Windows). Nothing is resolved: a UNC path
    or a drive that is currently unplugged must still round-trip."""
    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        s = _fwd(str(p)).rstrip("/")
        k = s.lower()
        if s and k not in seen:
            seen.add(k)
            out.append(s)
    return out


@dataclass
class Settings:
    """The persisted user settings. `api.schemas.Settings`, key for key.

    ⚠️ Thread-safe: the API serves from a thread pool, and the settings are touched on every scan.
    """

    recent_datasets: list[str] = field(default_factory=list)

    #: ⚠️ **PRE-R44 ONLY. Read from disk, never written, never on the wire.** The folders the user
    #: saved projects into under R42/R43. `core.migrate` drains this once; see the module docstring.
    legacy_projects: list[str] = field(default_factory=list, repr=False, compare=False)

    #: Set when the file on disk could not be read. Surfaced, never swallowed — but never fatal.
    warnings: list[str] = field(default_factory=list, repr=False, compare=False)

    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)
    _loaded: bool = field(default=False, repr=False, compare=False)

    # ---------------------------------------------------------------------------------------------
    # disk
    # ---------------------------------------------------------------------------------------------
    def load(self) -> Settings:
        """Read the file. A missing one is the normal first-run case and is not a warning."""
        with self._lock:
            self._loaded = True
            self.warnings = []
            p = settings_path()
            if not p.is_file():
                return self
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raise ValueError("the JSON root is not an object")
            except (OSError, ValueError) as e:
                # It is a cache of the user's *convenience*, not his work. Say so and carry on.
                self.warnings.append(f"could not read {_fwd(p)} ({e}) — starting with defaults")
                return self

            self.legacy_projects = _dedup([r for r in (raw.get("projects") or [])
                                           if isinstance(r, str)])
            self.recent_datasets = _dedup([r for r in (raw.get("recent_datasets") or [])
                                           if isinstance(r, str)])[:MAX_RECENT]
            return self

    def save(self) -> Settings:
        """Atomically (`core.workspace.atomic_write_text` — temp + `os.replace`, fsynced, locked)."""
        with self._lock:
            atomic_write_text(settings_path(), dumps(self.to_json()))
            return self

    def ensure_loaded(self) -> Settings:
        with self._lock:
            return self if self._loaded else self.load()

    # ---------------------------------------------------------------------------------------------
    # the wire
    # ---------------------------------------------------------------------------------------------
    def to_json(self) -> dict[str, Any]:
        """`api.schemas.Settings`. ⛔ ONE key, and it is a list of paths.

        ⚠️ `legacy_projects` is deliberately absent — writing it back would resurrect the pre-R44
        index the store replaced. Persisting these settings is what finally drops the old key.
        """
        with self._lock:
            return {"recent_datasets": list(self.recent_datasets)}

    # ---------------------------------------------------------------------------------------------
    # mutation — every one of these persists immediately
    # ---------------------------------------------------------------------------------------------
    def drop_legacy_projects(self) -> Settings:
        """Forget the pre-R44 folder index, once `core.migrate` has drained it."""
        with self._lock:
            self.legacy_projects = []
            return self.save()

    def touch_dataset(self, path: str | Path) -> Settings:
        """Most-recently-opened first. ⛔ A path, and only a path — see the module docstring."""
        with self._lock:
            self.recent_datasets = _dedup([_fwd(path), *self.recent_datasets])[:MAX_RECENT]
            return self.save()

    def update(self, *, recent_datasets: list[str] | None = None) -> Settings:
        """`PUT /api/settings`. Only the fields that are given are touched; a field that is absent is
        left alone (that is what `SettingsUpdate`'s `None` defaults mean)."""
        with self._lock:
            if recent_datasets is not None:
                self.recent_datasets = _dedup(list(recent_datasets))[:MAX_RECENT]
            return self.save()

    def clear(self) -> Settings:
        """Reset to defaults **and persist**. The tests use it; so does a user with a broken file.

        ⛔ It does **not** touch the store — deleting the user's projects is `Project.delete`'s job
        and nothing else's. Clearing settings has never been able to cost him work, and under R44 it
        costs him even less than it did.
        """
        with self._lock:
            self.recent_datasets = []
            self.legacy_projects = []
            self.warnings = []
            return self.save()


#: THE settings. Import this; do not construct another. It is lazy — nothing is read from disk until
#: something asks (`ensure_loaded()`), so importing `camea.settings` touches no filesystem.
#:
#: ⚠️ `app_state_dir()` honours `CAMEA_STATE_DIR`, which the tests set — so a test process never
#: reads or writes the real user's settings. Do not cache `settings_path()` at import.
SETTINGS = Settings()
