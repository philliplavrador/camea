---
id: 004
title: The video create route garbles its own refusal message, and can strand a half-made project
kind: defect
tier: medium
status: open
found: 2026-08-14
found-while: building plan 001 (Analyze MEA) — the review of the new create route caught both in the code it was modelled on
resolved-by: ~
---

# 004 — `POST /api/videomosaic/projects` garbles its refusal, and its cleanup has a gap

Two small things in `src/camea/features/videomosaic/routes.py :: post_video_project`, found by
reading it closely while modelling `POST /api/mea/projects` on it (plan 001). Neither is new; both
were copied forward once already, and the copy has been fixed — so this is the original.

## 1. The message is joined character by character

[`routes.py:212-215`](../../../src/camea/features/videomosaic/routes.py#L212):

```python
except core_document.ValidationError as e:
    _abandon(pr)
    raise ApiError(400, "bad_request",
                   "; ".join(e.args[0]) if e.args else str(e)) from e
```

`ValidationError.__init__` ([`core/document.py:129`](../../../src/camea/core/document.py#L129))
**has already joined** `.problems` into one string and handed it to `super().__init__`. So
`e.args[0]` is that string, and `"; ".join()` over a string iterates its **characters**:

    "source: a probed video receipt is required"
      ->  "s; o; u; r; c; e; :;  ; a; ...; d"

Measured, not inferred. The fix is `str(e)` (or `"; ".join(e.problems[:6])`).

## 2. An unexpected failure mid-save leaves the project behind

The route catches `ValidationError` and `DocumentError` and calls `_abandon(pr)` for each — but
nothing else. An `OSError` in `save_analysis` (an unwritable store, a full disk) escapes with the
manifest already written, so a project the user never finished creating appears on his home screen
with no document in it.

`features/mea/routes.py` carries the same two handlers **plus** a catch-all
`except Exception: _abandon(pr); raise _project_error(e)`, which is what closes this. Backporting
those three lines is the whole fix.

## Why medium

Neither can lose work: `_abandon` deletes only a project the user has not seen yet, and the failure
modes are rare. But the first makes a refusal unreadable exactly when the user needs to read it —
this repo's standing rule is that a refusal is shown **whole and verbatim** — and the second puts a
broken card on the home screen with no way to tell why it is broken.

## Out of scope of the plan that found it

Plan 001 § Scope says *"Any change to the video pipeline's behaviour"* is **out**, and both of these
change what that pipeline does. So they are filed rather than fixed in that build. The `mea` copies
are correct as written.
