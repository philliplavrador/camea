---
id: 013
title: recovery() compares mtimes strictly, so a fast save+autosave pair flakes the "newer" test
kind: defect
tier: low
status: open
found: 2026-08-15
found-while: extending the chip-orientation test — the full unit+api run was the gate
resolved-by: ~
---

# 013 — `test_the_autosave_lands_BESIDE_the_document_never_over_it` flakes on an mtime tie

Observed once on 2026-08-15, in `uv run pytest tests/unit tests/api -q` (535 passed, this one
failed). It passes in isolation and in a `tests/unit`-only run, both tried immediately after.

## The mechanism (read off the code, not proven under a debugger)

`tests/unit/test_project.py::test_the_autosave_lands_BESIDE_the_document_never_over_it` does

```python
pr.save_document({...})     # writes document.camea.json
pr.autosave({...})          # writes autosave.camea.json, back-to-back
assert pr.recovery()["newer"] is True
```

and `Project.recovery()` (`src/camea/core/project.py:551`, same again in
`core/workspace.py:821`) decides `newer` with a **strict** comparison:

```python
"newer": a.stat().st_mtime > doc_mtime,
```

When both writes land inside one filesystem-timestamp tick — easy on NTFS under load, where the
two calls are microseconds apart — the mtimes are **equal**, `newer` is `False`, and the test
fails. Nothing is wrong with the autosave itself; the file is beside the document with the right
contents. It is the tie-break that has no answer.

## Why it is `low`

No science and no saved verification is at risk: the recovery prompt is a UI convenience, and in
real use a document save and an autosave are never microseconds apart. The cost is a red gate on
an innocent turn, which is exactly what issue 010 documents for the copy-job tests.

## Possible fixes (pick one, not all)

* The app: treat a tie as newer (`>=`) — an autosave written at the same instant as the save is
  not stale, and the user choosing between two identical-age files is harmless.
* The test: force distinct stamps (`os.utime` the document a second into the past after saving)
  so the assertion tests the comparison, not the filesystem's clock granularity.
