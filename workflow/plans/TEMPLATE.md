---
id: NNN
title: <one line, what a user gets — not what the code does>
status: queued # queued | active | done | abandoned
created: YYYY-MM-DD
needs: frontend # none | frontend | dev server | engine — which gates this build owes
blocked-by: none # optional: a plan number this one waits on, or none. Prose reasoning goes in § Deploy
resolves: none # optional: issue numbers this plan closes, e.g. 191, 204. Those issues carry resolved-by: plan NNN
---

# NNN — <title>

> **Copying this?** A plan lives one directory deeper than this template —
> `workflow/plans/queued/NNN-slug.md` — so every relative link below needs **one more
> `../`** once you have copied it. The links here are written for the template's own
> location so that they work when you are reading it.

## What and why

Two or three sentences. What changes for the person using Camea, and what makes it worth
doing. If this section is hard to write, the feature is not understood yet and the plan is
not ready.

Camea exists to pair an electrode's voltage with a neuron's calcium trace — see
[utils/knowledge/mea-calcium-goal.md](../../utils/knowledge/mea-calcium-goal.md). If you
cannot say how this feature serves that, say so here rather than leaving it implied.

## Decisions

The interview, recorded. This is the section that makes a stale plan usable — a
`/build` session was not there for the conversation and cannot infer these.

| Question | Answer |
|---|---|
| … | … |

**Explicitly rejected:** what was considered and turned down, and why. Prevents a
build session from "improving" the plan back into a shape you already refused.

## Scope

**In:**
- …

**Out:** (each with a reason — "out" without a reason gets re-litigated)
- …

## Approach

How to build it, in enough detail that a fresh session doesn't have to re-derive
the design — but not so much that it can't use judgement. Name the real files.

## Rulings this touches

Which of [docs/BEHAVIOUR.md](../../docs/BEHAVIOUR.md)'s numbered rulings this feature
lands on, and whether it upholds them or changes one. **Do not "improve" a ruling away** —
if one looks wrong, that is a question for him, asked with the tool, not a silent edit.
Every ruling is backed by a Playwright test in `web/tests/e2e/`; a change to a ruling is a
change to its test.

Write `none` if it touches none. That is a real answer and a common one.

## Affected

- `src/camea/…` — what changes
- `web/src/…` — what changes
- …

## Done when

Checkable statements, not vibes. "The Outputs panel lists every file under
`<project>/outputs/` and nothing above it" is checkable; "the panel feels right" is not.

- [ ] …

## Verify

Exact commands, and what a pass looks like. Anything a reviewer would want to see
before trusting this.

```bash
uv run ruff check . && uv run mypy
uv run pytest -q -m "not slow"
cd web && npm run lint && npx tsc -b --noEmit && npm test
```

⭐ **If `needs: engine`, the 312/312 guard goes here and it is not optional:**

```bash
uv run pytest tests/slow/test_solver_312.py -q -m slow -s   # ~130 s, needs the mirror + a GPU
```

## Deploy

Camea deploys nothing — there is no server and no release step. **"Nothing — this lands on
`master` and that is all" is the expected answer**, and you should write that line rather
than invent ceremony around it.

What this section is still for: **ordering**. If this plan has to land before or after
another one — a schema the frontend reads, an engine change a feature depends on — say
which, and say it here. `/build all` reads this section to order the queue.

## Roll back

What you do when this turns out to be wrong. Code goes back with one `git revert`. Two
things do not:

- **A change to a saved project's on-disk shape.** Projects live in
  `%LOCALAPPDATA%/Camea/projects/<analysis_id>/` and a user's verified anchors are in
  there. Say what a project written by the new code does when the old code opens it, or say
  plainly that it is one-way.
- **A change to the engine.** Reverting the code does not un-ring the bell if a wrong
  mosaic was exported in between. Say what would have to be re-run.

## Open

Things `/build` must ask before starting. Empty is good — it means the interview
was thorough. Anything listed here is a question the plan could not answer.

- …
