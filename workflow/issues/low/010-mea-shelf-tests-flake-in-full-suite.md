---
id: 010
title: Two MEA shelf API tests fail intermittently, but only in the whole-suite run
kind: defect
tier: low
status: open
found: 2026-08-15
found-while: adding rename-a-recording to Analyze MEA — the full suite was run as the gate
resolved-by: ~
---

# 010 — `test_removing_the_last_recording…` and `test_adding_a_bad_path…` flake in `uv run pytest`

Two tests in [`tests/api/test_mea_feature.py`](../../../tests/api/test_mea_feature.py) fail
intermittently, and **only** when the whole fast suite runs:

| test | line |
|---|---|
| `test_adding_a_bad_path_adds_none_of_them_and_names_it` | ~391 |
| `test_removing_the_last_recording_leaves_a_working_empty_project` | ~437 |

Observed across five runs on 2026-08-15:

| run | result |
|---|---|
| `uv run pytest -m "not slow"` | both failed (699 passed) |
| `uv run pytest tests/api` | all passed (152) |
| `uv run pytest -m "not slow"` | `test_removing_the_last…` failed (700 passed) |
| `uv run pytest -m "not slow"` | all passed (701) |
| `uv run pytest -m "not slow"` (`--tb=long`, to capture it) | all passed (701) — so no traceback was ever caught |

Both pass every time in isolation and every time in the `tests/api` run. Pytest here has no random
ordering and no `xdist` (`addopts = -m 'not slow and not legacy'`), so the order is identical in
both runs — what differs is **the machine being busy**, because ~550 other tests have run first.

## The likely mechanism, unproven

Both tests sit on the copy job: one adds recordings and then asserts the shelf, the other removes
the last recording (which cancels a live copy and `rmtree`s the folder) and then adds another. The
copy is a **thread job**, so under load its `_patch_recording` write-back can still be in flight
when the assertion runs. `recordings.forget` already swallows the `OSError` from an `rmtree` racing
a writer, so nothing crashes — the shelf just says something different for a moment.

⚠️ **This is a guess, and the run that was instrumented to catch it passed.** Nobody should fix it
from this note; the first job is to catch a traceback (run the fast suite in a loop with
`--tb=long`, or put the two tests under load deliberately).

## Why low

Nothing in the app is broken — it is the *tests* that race, not the shelf, and the behaviour they
cover (`removing a recording deletes Camea's copy and leaves his original`, which is the one that
must never regress) has its own tests that do not flake. The cost is a red gate that clears itself
on a rerun, which is exactly how a real failure gets waved through later.
