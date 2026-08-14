---
id: 001
title: A new project asks what you want to do — and "Analyze MEA" is a real answer
status: active # queued | active | done | abandoned
created: 2026-08-14
needs: dev server # none | frontend | dev server | engine — which gates this build owes
blocked-by: none
resolves: none
---

# 001 — A new project asks what you want to do — and "Analyze MEA" is a real answer

## What and why

Today every project is the same thing: point Camea at a survey video and it builds a mosaic.
That pipeline exists to serve one experiment — a chip recorded **electrically** while a
microscope records a few fields **optically** — and the author now wants that named for what
it is (**"Simultaneous MEA + 2P"**) and a **second, unrelated task beside it**: open a MaxWell
recording on its own, with no calcium anywhere in sight, and look at it.

This plan brings back the **"what do you want to do?"** step, puts the two tasks on it, and
makes an `Analyze MEA` project a thing you can create and open. It opens to an empty screen
that says "add a recording" — [002](002-analyze-mea-standalone.md) is what fills that screen.

Against [mea-calcium-goal.md](../../../utils/knowledge/mea-calcium-goal.md): the pairing task is
untouched and keeps its whole pipeline. The new task serves it **sideways** — it is how you
look at a chip's electrical record without first having to build a mosaic for it, which is
what you want when you are deciding whether a recording is worth pairing at all.

## Decisions

The interview, recorded (2026-08-14).

| Question | Answer |
|---|---|
| Should project creation ask which task? | Yes. Two tasks now, so the question is real. |
| What are the two called? | **"Simultaneous MEA + 2P"** (the existing video→mosaic→regions pipeline) and **"Analyze MEA"** (the new one). His words, verbatim. |
| Does the existing feature key change? | **No.** The manifest key stays `videomosaic`; only the label he reads changes. Projects already in the store keep opening. |
| Does `Analyze MEA` ask for data at creation time? | **No.** "You create the project, you pick Analyze MEA, and you go into the project, you can add however many H5 files you want." Name → Task → created. No Data step. |
| Does it have calcium/mosaic/regions? | **No.** "This one will not have any calcium data to go along with it." No mosaic, no video, no regions, no chip-seating question. |

**Explicitly rejected:**
- **Making `Analyze MEA` a mode of the existing pipeline.** It shares `core/mearecording.py` and
  nothing else. Bolting it onto `videomosaic` would drag the mosaic, the electrode map and the
  unresolved chip seating into a screen that needs none of them.
- **Asking for the first H5 during creation.** He described the opposite order on purpose: the
  project is a *shelf* you put recordings on, not a wrapper around one file.
- **Renaming the `videomosaic` feature key to match its new label.** Every project manifest in
  `%LOCALAPPDATA%/Camea/projects/` carries the old key. A label is free; a key is a migration.

## Scope

**In:**
- A second entry in `TASKS` — which by construction brings back the whole `task` phase, its
  stepper step and its Back button ([NewProjectFlow.tsx:222](../../../web/src/features/home/NewProjectFlow.tsx#L222)
  keeps them alive for exactly this).
- The label change: `videomosaic` reads **"Simultaneous MEA + 2P"**.
- A third phase outcome: picking `mea` **creates immediately** and navigates, with no Data step.
- `POST /api/mea/projects` — name only. Creates in the store with `feature: "mea"`, writes the
  document, returns the summary.
- A `FeatureGate` arm for `feature === 'mea'`, mounting a `MeaFeature` shell that renders the
  **empty state**: the project's name, and one button that does nothing yet but say what comes.
- The home screen shows an `Analyze MEA` project like any other card, with an honest subtitle
  where a video's filename would be.

**Out:**
- Everything you can actually *do* with a recording — adding files, the chip map, traces. That
  is [002](002-analyze-mea-standalone.md), and it is a session's worth of work on its own.
- Deleting or renaming tasks. `mosaic` (the retired snapshot builder) stays exactly as it is:
  off the chooser, still openable through the gate.
- Any change to the video pipeline's behaviour. Only its label moves.

## Approach

**Backend — a new feature package, deliberately thin at first.**

`src/camea/features/mea/` (`__init__.py`, `routes.py`, `document.py`), modelled on
`features/videomosaic/` and wired the same way in `src/camea/api/app.py`: the router is included
and handed `SESSIONS.get`/the store setter through the same seam
(`routes.set_store`, see [videomosaic/routes.py:115](../../../src/camea/features/videomosaic/routes.py#L115)).

`FEATURE = "mea"`. `POST /api/mea/projects` takes `{name}` and does what
[`post_video_project`](../../../src/camea/features/videomosaic/routes.py#L172) does minus the probe:

```python
pr = core_project.Project.create_in_store(
    feature=FEATURE, name=name or "Untitled MEA project",
    dataset_key="", dataset="", data_dir="",
)
```

⚠️ **The empty `dataset_key` is the one thing to get right.** `Project.create` requires only
`feature`; `dataset_key`/`dataset`/`data_dir` are strings and may be empty. Check what
`ProjectSet.analyses()` and `AnalysisSummary` do with an empty key **before** relying on it —
`by_dataset()` groups on it, and the home screen renders it. If an empty key turns out to poison
the listing, mint one from the analysis id rather than from anything about the data (⛔ no dataset
knowledge — a key is an address, not a fact about what is at it). Whatever is chosen, say so in
the module docstring; a future session will ask.

The document is authored by `core_document.new_document(feature="mea", …)` with an empty
`source`, then `save_analysis`. Failing that, `_abandon(pr)` exactly as the video route does — a
half-made project must not reach the home screen.

**Frontend.**

- [NewProjectFlow.tsx](../../../web/src/features/home/NewProjectFlow.tsx): add
  `{ key: 'mea', label: 'Analyze MEA', blurb: '…' }` to `TASKS` and retitle the video entry.
  `ONLY_TASK` goes `null` on its own and the phase machinery wakes up — **do not rewrite it**,
  that is what it was left mounted for. The `dataset` phase must not be reached for `mea`: the
  task card's `onClick` creates and navigates instead of advancing the phase. The `STEPS` array
  is per-task now (Name · Task for `mea`; Name · Task · Video for `videomosaic`).
- `web/src/features/mea/MeaFeature.tsx` + module CSS — the shell and its empty state.
- [FeatureGate.tsx:76](../../../web/src/app/FeatureGate.tsx#L76): one more arm, `mea` →
  `<MeaFeature project={project} />`, taking the summary the gate already holds (as
  `VideoMosaicFeature` does).
- `npm run gen:api` after the route lands — ⛔ never hand-write the client type.

**Blurb wording.** Keep it to what he gets, in his words, no jargon:
*"Open a MaxWell recording on its own — click an electrode, read what it recorded."*

## Rulings this touches

- **R44 (storage — Camea owns the projects).** Upheld and, in fact, taken further: this task asks
  **zero** path questions at creation. The project is made in the store; the user names only the
  project.
- **R3 (no explanations on screen).** The task cards carry a one-line blurb each, which is the
  shape that screen already had before the chooser was mothballed. Nothing new is introduced.
- The new-project flow's e2e coverage lives in
  [web/tests/e2e/videomosaic.spec.ts](../../../web/tests/e2e/videomosaic.spec.ts) and
  [pages.ts](../../../web/tests/e2e/pages.ts), which drive `np-name` → `np-next` → the video
  paths. **Those specs assume the Task step does not exist** and will break the moment `TASKS`
  gets a second entry — fixing them is part of this plan, not a follow-up.

No ruling is changed. If the Task step turns out to need a BEHAVIOUR entry of its own, that is a
question for him, asked with the tool.

## Affected

- `src/camea/features/mea/{__init__,routes,document}.py` — new; the create route and `FEATURE`.
- `src/camea/api/app.py` — include the new router, hand it the store.
- `src/camea/api/schemas.py` — `CreateMeaProjectRequest`. Response is the existing `AnalysisSummary`.
- `web/src/features/home/NewProjectFlow.tsx` (+ its CSS if the cards need it) — the chooser.
- `web/src/features/mea/MeaFeature.tsx` (+ CSS) — new; shell and empty state.
- `web/src/app/FeatureGate.tsx` — the `mea` arm.
- `web/src/api/schema.d.ts` — regenerated, never edited.
- `web/tests/e2e/{pages.ts,videomosaic.spec.ts}` — the flow now has a Task step.
- `tests/api/` — a test that a `mea` project creates, lists and opens.

## Done when

- [ ] `New project` → type a name → **Next** lands on a screen offering exactly two tasks,
      labelled **Simultaneous MEA + 2P** and **Analyze MEA**.
- [ ] Clicking **Simultaneous MEA + 2P** reaches the video path box, and creating a video
      project still works end to end, unchanged.
- [ ] Clicking **Analyze MEA** creates the project and lands on `/project/:id` with no path
      question of any kind asked.
- [ ] That project appears on the home screen, can be renamed, can be deleted, and reopens.
- [ ] Its folder in the store holds a manifest with `"feature": "mea"` and a document, and
      nothing was written outside `%LOCALAPPDATA%/Camea/projects/<id>/`.
- [ ] A project created before this change (`feature: videomosaic` or `mosaic`) still opens.
- [ ] `npm run check:api` is clean — the client was regenerated, not typed by hand.

## Verify

```bash
uv run ruff check . && uv run mypy
uv run pytest -q -m "not slow"
cd web && npm run lint && npx tsc -b --noEmit && npm test && npm run check:api
cd web && npm run e2e            # the flow specs above change in this plan
node scripts/check-links.js
```

Then run it and look at it: `uv run camea` (or `/dev`), make one project of each task, and open
both. `needs: dev server` is not a formality here — the whole plan is a screen.

## Deploy

Nothing — this lands on `master` and that is all.

**Ordering:** this plan comes **before** [002](002-analyze-mea-standalone.md), which fills the
screen this one puts up. 002 is unbuildable without it.

## Roll back

`git revert`. The one thing that does not come back: any project created as `feature: "mea"`
will, after a revert, hit the gate's "Unknown task" card. It is not lost and nothing of the
user's data is touched — the folder sits in the store and re-appears when the code returns. Say
so in the commit message. No engine, no saved anchors, no export is in scope here.

## Open

- Empty `dataset_key` versus a minted one — decided **in the build**, by reading what
  `ProjectSet.analyses()`, `by_dataset()` and the home-screen card actually do with `""`. Both
  answers are acceptable; guessing is not.
