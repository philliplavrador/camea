---
id: 009
title: recovery() decides "is the autosave newer?" with a strict > on mtimes that are usually equal
kind: bug
tier: medium
status: open
found: 2026-08-14
found-while: running the full python suite at the end of plan 003 — an unrelated test went red
resolved-by: ~
---

# 009 — `recovery()` compares two timestamps that are usually the same number

## What is wrong

[`core/project.py :: Project.recovery`](../../../src/camea/core/project.py) decides whether to offer
him a recovery like this:

```python
"newer": a.stat().st_mtime > doc_mtime,
```

A **strict `>`** on a filesystem timestamp. Measured on this machine, 200 pairs of back-to-back
writes:

> **188 / 200 shared (or inverted) their `st_mtime`.**

So whenever the document and the autosave are written close together, `newer` is `False` and no
recovery is offered — not because the autosave is stale, but because the clock could not tell the
two apart.

## How it showed up

`tests/unit/test_project.py :: test_the_autosave_lands_BESIDE_the_document_never_over_it` writes a
document and an autosave one line apart and asserts `rec["newer"] is True`. It **passes when the
file is run alone and fails in the full suite** — the two writes land in the same clock tick often
enough that suite timing decides the outcome. ⚠️ It is therefore a **latent flake that has been in
the suite all along**, not a regression: nothing plan 003 touched is imported by that test, and the
mechanism above is independent of it. It surfaced now only because adding tests shifted the timing.

## Why `medium` and not `high`

Nothing is destroyed and nothing is lost: the autosave file is still on disk, it is simply not
*offered*. And in real use a document save and an autosave are normally seconds or minutes apart, so
their mtimes differ and the prompt appears correctly — the pathological case needs both writes inside
one clock tick, which the app does not normally produce.

What it does cost today is a **flaky suite**, which is its own kind of expensive: a red run that is
not a real failure trains everyone to re-run instead of read.

## The fix, when someone takes it

⛔ **Not simply `>=`** — that inverts the intent. An autosave *older* than the document is
deliberately not a recovery prompt ("it is noise", says the docstring), and `>=` would make an
equal-mtime pair always offer one, which is the same coin flip pointing the other way.

Better candidates, in rough order of preference:

1. **Stop asking the filesystem.** Both files are Camea's own JSON — write a `saved_at` into the
   autosave payload and compare *that* against the document's, so the ordering is recorded by the
   writer rather than inferred from the disk. This is the only option that is actually exact.
2. Keep mtimes but treat "equal" as **newer**, on the argument that an autosave is only ever written
   *after* the save it follows, so a tie means "written second".
3. Give the test a real gap (`time.sleep`) — ⛔ this fixes the *test* and leaves the *product* rule
   depending on clock resolution, so it is the worst of the three and is only worth taking if the
   author wants the behaviour left exactly as it is for now.

⚠️ Whichever is chosen, this sits on the path that protects **hours of hand-verification**, so it
wants a test that fails against the current code rather than a change made by eye.
