"""settings.py — ⭐ **WHAT THE APP REMEMBERS BETWEEN LAUNCHES. AND IT IS ONLY PATHS.**

    {"projects": ["D:/work/retina-run", "E:/runs/cortex"],
     "recent_datasets": ["D:/.../260620d"]}

That is the whole file. It lives in the OS's app-data directory (`core.workspace.app_state_dir()` —
`%LOCALAPPDATA%/Camea` on Windows), **not** in a project folder and **never** in a dataset.

⭐ **`dataset_roots` and `workspace` were REMOVED on 2026-07-25** (his ruling — see
`core/project.py`). There is no root registry to scan on launch and no single app-managed store:
a project names **where its data comes from** and **where it is saved**, and the only thing kept
here is the list of folders he has actually saved into, so the home screen can list them.
`recent_datasets` survives — it is what offers his last data paths back as completions.

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
reset to defaults, loudly (`warnings`), and the app starts. Nothing the user has *made* lives here —
his work is in the project folders he named, each a real folder with a real name he chose. Losing
this file costs him the *list* on the home screen, never a project: point Camea at the folder again
and everything is there, because the truth is the manifest in the folder, not this index.
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

    #: Every folder the user has saved a project into. ⭐ An INDEX, not the truth — the truth is the
    #: `camea-project.json` in each folder. A folder that has moved simply drops out of the listing.
    projects: list[str] = field(default_factory=list)
    recent_datasets: list[str] = field(default_factory=list)

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

            self.projects = _dedup([r for r in (raw.get("projects") or [])
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
        """`api.schemas.Settings`. ⛔ Two keys. Both of them lists of paths."""
        with self._lock:
            return {
                "projects": list(self.projects),
                "recent_datasets": list(self.recent_datasets),
            }

    # ---------------------------------------------------------------------------------------------
    # mutation — every one of these persists immediately
    # ---------------------------------------------------------------------------------------------
    def add_project(self, path: str | Path) -> Settings:
        """Remember a folder the user saved a project into. Most recent first, so the *"Save into"*
        box can offer his last choice's neighbourhood back to him."""
        with self._lock:
            self.projects = _dedup([_fwd(path), *self.projects])
            return self.save()

    def forget_project(self, path: str | Path) -> Settings:
        """Drop a folder from the index. ⚠️ Forgetting is not deleting — `core.project.Project.delete`
        removes the files; this only stops listing the folder."""
        with self._lock:
            want = _fwd(path).rstrip("/").lower()
            self.projects = [r for r in self.projects if r.lower() != want]
            return self.save()

    def touch_dataset(self, path: str | Path) -> Settings:
        """Most-recently-opened first. ⛔ A path, and only a path — see the module docstring."""
        with self._lock:
            self.recent_datasets = _dedup([_fwd(path), *self.recent_datasets])[:MAX_RECENT]
            return self.save()

    def update(self, *, projects: list[str] | None = None,
               recent_datasets: list[str] | None = None) -> Settings:
        """`PUT /api/settings`. Only the fields that are given are touched; a field that is absent is
        left alone (that is what `SettingsUpdate`'s `None` defaults mean)."""
        with self._lock:
            if projects is not None:
                self.projects = _dedup(list(projects))
            if recent_datasets is not None:
                self.recent_datasets = _dedup(list(recent_datasets))[:MAX_RECENT]
            return self.save()

    def clear(self) -> Settings:
        """Reset to defaults **and persist**. The tests use it; so does a user with a broken file."""
        with self._lock:
            self.projects = []
            self.recent_datasets = []
            self.warnings = []
            return self.save()


#: THE settings. Import this; do not construct another. It is lazy — nothing is read from disk until
#: something asks (`ensure_loaded()`), so importing `camea.settings` touches no filesystem.
#:
#: ⚠️ `app_state_dir()` honours `CAMEA_STATE_DIR`, which the tests set — so a test process never
#: reads or writes the real user's settings. Do not cache `settings_path()` at import.
SETTINGS = Settings()
