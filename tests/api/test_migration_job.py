"""The launch migration runs as a JOB (R48, 2026-08-16) — the server answers while projects move.

Until 2026-08-16 `core.migrate` ran *inside* `create_app()`, so a multi-GB move across drives held
every connection — including the one that would have shown a progress bar — for minutes, with the
server console as the only narration. Now the lifespan plans cheaply and, only when there is work,
submits `core.migrate.migration_job` to the registry: `GET /api/projects` names the job while it
runs and states the report once when it is done.

⚠️ These tests drive the REAL lifespan (`with TestClient(...)` runs it), a real legacy project on
disk, and the real settings file — nothing is monkeypatched, because the thing under test is the
wiring itself.
"""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from camea.core.project import Project, store_root
from camea.settings import SETTINGS, settings_path


@pytest.fixture()
def fresh_singletons(state_dir):
    """The slice of the `client` fixture this file needs — everything except the app itself,
    because these tests must control what is on disk BEFORE the lifespan runs."""
    from camea.api import routes_core
    from camea.core.document import DOCUMENTS
    from camea.core.jobs import JOBS

    routes_core.SESSIONS.clear()
    JOBS.forget_finished()
    DOCUMENTS.clear()
    SETTINGS.clear()                      # resets AND persists into the isolated state_dir
    return state_dir


def legacy_project(path, name="pass 1"):
    """A project as R42/R43 left it: in a folder the USER named, outside the store."""
    pr = Project.create(path, feature="mosaic", name=name, dataset_key="k1", dataset="260620d",
                        data_dir="D:/data/260620d")
    pr.save_document({"id": pr.analysis_id, "dataset_key": "k1", "tiles": {}})
    return pr


def listing_after_migration(client: TestClient, deadline_s: float = 10.0) -> dict:
    """Poll `GET /api/projects` until the migration report lands. ⭐ The polling IS the point: the
    listing answers while the move is still running — the pre-R48 wiring could not answer at all."""
    t0 = time.monotonic()
    while True:
        body = client.get("/api/projects").json()
        if body["migration_job_id"] is None and body["migration"] is not None:
            return body
        assert time.monotonic() - t0 < deadline_s, "the migration job never reported"
        time.sleep(0.05)


def test_the_server_answers_while_projects_come_home(fresh_singletons, tmp_path):
    from camea.api.app import create_app

    pr = legacy_project(tmp_path / "his folder")
    aid = pr.analysis_id
    # the pre-R44 index, exactly as R42/R43 wrote it. ⚠️ Written AFTER the fixture's
    # `SETTINGS.clear()` persisted (clear would erase the key), then reloaded explicitly —
    # `ensure_loaded` on an already-loaded singleton would not re-read the file.
    settings_path().write_text(json.dumps({"projects": [pr.path.as_posix()]}), encoding="utf-8")
    SETTINGS.load()

    with TestClient(create_app()) as c:
        # ⭐ The first answer arrives while (or before) the job runs — the launch is not held.
        assert c.get("/api/health").status_code == 200

        body = listing_after_migration(c)
        assert [m["name"] for m in body["migration"]["migrated"]] == ["pass 1"]
        assert body["migration"]["failed"] == []
        assert body["migration"]["stopped"] is False
        # the project is home, listed, and its folder is in the store
        assert (store_root() / aid / "document.camea.json").is_file()
        assert aid in [a["analysis_id"] for a in body["analyses"]]

    # ⚠️ drained ONLY because everything came home — the old index was the only record of where
    # those folders were.
    on_disk = json.loads(settings_path().read_text(encoding="utf-8"))
    assert "projects" not in on_disk


def test_an_ordinary_launch_reports_no_migration_and_starts_no_job(fresh_singletons):
    from camea.api.app import create_app

    with TestClient(create_app()) as c:
        body = c.get("/api/projects").json()
        assert body["migration"] is None
        assert body["migration_job_id"] is None
