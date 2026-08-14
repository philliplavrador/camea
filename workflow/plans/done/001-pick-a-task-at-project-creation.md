---
id: 001
title: A new project asks what you want to do — and "Analyze MEA" is a real answer
status: done # queued | active | done | abandoned
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
| Does `Analyze MEA` ask for data at creation time? | ⚠️ **REVERSED LATER THE SAME DAY — see the row below.** As interviewed: *"You create the project, you pick Analyze MEA, and you go into the project, you can add however many H5 files you want."* Name → Task → created; no Data step. **That is what this plan shipped, and it is an intermediate state.** |
| Does it have calcium/mosaic/regions? | **No.** "This one will not have any calcium data to go along with it." No mosaic, no video, no regions, no chip-seating question. |

**🔴 REVERSED BY HIM, 2026-08-14, after seeing it built** (asked again with side-by-side mockups):

| Question | Answer |
|---|---|
| ⭐ Does `Analyze MEA` ask for its recordings at creation after all? | **Yes.** *"you create the project then you select what you want to do in this project ... then after that it asks you to upload the files you need for that task."* New project is **Name → Task → Files, for BOTH tasks.** `Analyze MEA` gains a step 3 that picks the `.h5` files, and the project is created **at the end of the wizard, with those recordings already on its shelf.** He picked this over "open empty and add from inside" explicitly. Adding more from inside the project stays — it is just no longer the only door. |

⚠️ **SO WHAT 001 SHIPPED IS AN INTERMEDIATE STATE, NOT THE FINAL SHAPE**, and it is being closed as
**done** deliberately rather than held. The step-3 picker cannot be built here: it needs the import
component, the `.h5` reading and the `paths` argument on create, all of which are
[002](002-analyze-mea-standalone.md)'s work. 002 now owns the wizard step and says so. Everything
001 built — the Task step, the second task, the feature package, the gate arm, the shell — is
required by that shape and none of it is thrown away; the only thing 002 changes is **when** the
project is created and **what is on it** when it is.

⛔ **AND `docs/BEHAVIOUR.md` NEEDS NOTHING. DO NOT RE-OPEN THIS.** The question this plan raised was
whether his new task broke R41 (*"a project is one dataset + one task"*) and R44.2 (*"New project
asks for ONE path"*), and whether to record an exception. His answer **restores both rulings instead
of breaking them**: every project asks for its data at creation, and creation asks exactly one data
question. There is no exception to note and no ruling to amend. The temporary window in which
`Analyze MEA` asked for nothing closes with 002.

**Decided in the build (2026-08-14), by reading the code rather than guessing:**

| Question | Answer |
|---|---|
| ⭐ § Open — empty `dataset_key`, or one minted from the analysis id? | **Empty**, and `dataset`/`data_dir` with it. Read all four consumers: `analyses()` filters on it *only when a caller passes one*, so a blank is never filtered off the home screen; `by_dataset()`'s `""` bucket is only ever read by key, so nobody asks for it; `guard_slot` and `Scope.agrees_with` both **abstain on a blank**, which is what a project whose contents arrive later needs; `read_analysis` passes it through and the card renders the blank as words. A minted key buys one private bucket in an index nobody reads, at the price of the app claiming there is a dataset at an address that resolves to nothing. The reasoning is in `features/mea/routes.py`'s module docstring, where the next session will look. |
| Where does the empty payload live — an empty `source` (as § Approach guessed), or something else? | **`recordings: []`.** `source` is `videomosaic`'s key for the one file its project wraps; this project wraps nothing, and 002's shelf is a list. Same emptiness, right name, and 002 grows into it instead of migrating away from it. |
| What does the stepper say before he has picked a task? | The third step is **shown but unnamed** ("Data"). Found by running it: the stepper read *"3 Video"* while he was looking at a card called `Analyze MEA`, because `task` is still the default until he answers. Showing it keeps the count from ever *under*stating what is left; leaving it neutral stops it naming something he has not chosen. |
| What sits on the home card where a video's filename sits? | *"No recordings yet"*, faint and italic. A blank line there reads as a card that failed to load rather than one that is new. |
| 🔴 The task cards were unreachable by keyboard | `Card` renders a plain `<div>`, so the cards had a bare `onClick`: untabbable, deaf to Enter and Space. Harmless while the step was skipped; **the moment it renders, step 2 is the only door to either task and the app is keyboard-dead there.** Fixed with the same `role`/`tabIndex`/`onKeyDown` the home screen's project cards carry, and an e2e test that drives it by keyboard alone. |

**Explicitly rejected:**
- **Making `Analyze MEA` a mode of the existing pipeline.** It shares `core/mearecording.py` and
  nothing else. Bolting it onto `videomosaic` would drag the mosaic, the electrode map and the
  unresolved chip seating into a screen that needs none of them.
- ~~**Asking for the first H5 during creation.**~~ ⚠️ **Un-rejected the same day** — see the
  reversal above. What survives of the reasoning: the project is still a *shelf*, not a wrapper
  around one file (you pick **several** at step 3, and you can add more later). What does not: the
  order. He wants the files asked for at creation, like every other task.
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

- [x] `New project` → type a name → **Next** lands on a screen offering exactly two tasks,
      labelled **Simultaneous MEA + 2P** and **Analyze MEA**.
      *(Driven in a browser and asserted in `new-project-tasks.spec.ts`, which also pins the count
      at two and the retired snapshot card at zero.)*
- [x] Clicking **Simultaneous MEA + 2P** reaches the video path box, and creating a video
      project still works end to end, unchanged.
      *(The `@slow video build` spec now runs THROUGH the reintroduced Task step and is green:
      create → build → preview → outputs → copy out.)*
- [x] Clicking **Analyze MEA** creates the project and lands on `/project/:id` with no path
      question of any kind asked. *(And no path BOX exists on the step to begin with — asserted.)*
- [x] That project appears on the home screen, can be renamed, can be deleted, and reopens.
- [x] Its folder in the store holds a manifest with `"feature": "mea"` and a document, and
      nothing was written outside `%LOCALAPPDATA%/Camea/projects/<id>/`.
      *(`test_create_takes_a_name_and_nothing_else` asserts the folder's contents EXACTLY:
      `camea-project.json` + `document.camea.json`, and nothing else.)*
- [x] A project created before this change (`feature: videomosaic` or `mosaic`) still opens.
      *(Both driven by hand in the browser against a store holding one of each: the video pipeline
      opens on its Mosaic step, the retired snapshot builder opens on its wizard.)*
- [x] `npm run check:api` is clean — the client was regenerated, not typed by hand.

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

- ~~Empty `dataset_key` versus a minted one~~ — **decided in the build: empty.** See the second
  Decisions table above, and `features/mea/routes.py`'s module docstring for the four things that
  were read to decide it.

Three things were put to him at the end of the build. **All three came back. Nothing is open.**

| Asked | His answer | Done |
|---|---|---|
| The `Analyze MEA` screen carries one line of prose under a disabled button, against R3. Keep it, drop it, or put it behind the `?`? | **"Behind the ?"** | ✅ The line moved into a `Help` beside the button — the app's one explanation surface, the same pair the video screen's **Build mosaic** makes. The empty state is now a heading, a greyed-out button and a `?`. ⛔ The `?` is a **sibling** of the button, never a child (a `Help` trigger is itself a `<button>`; the trap `PipelineNav` documents), and it matters more here than anywhere: the button beside it is disabled, so it takes no focus, and the `?` is the only thing on the screen a Tab can land on. Asserted structurally and driven by keyboard in `new-project-tasks.spec.ts`. |
| The video task's blurb still describes the mechanism while its name now describes the experiment. Change it? | **"Leave it"** | ✅ Untouched, verbatim. |
| `docs/BEHAVIOUR.md`'s R41 (*"one dataset + one task"*) and R44.2 (*"asks for ONE path"*) stopped covering all three tasks. Note the exception? | **Neither** — he changed the app instead: *"you create the project then you select what you want to do in this project ... then after that it asks you to upload the files you need for that task."* | ✅ ⛔ **`docs/BEHAVIOUR.md` is NOT edited, and this must not be re-opened.** His answer **restores** both rulings rather than breaking them — every project asks for its data at creation, and creation asks exactly one data question. There is no exception to record. The window in which `Analyze MEA` asked for nothing is temporary and closes with [002](002-analyze-mea-standalone.md). See the reversal row in § Decisions. |

**How the third one landed, because the first answer read the other way.** Asked whether to note an
exception to R41/R44.2, he first said *"change the behavior so a project starts by itself and files
are written into the project after its created"* — which reads as an instruction to break the rule,
and possibly to make the **video** task create from a name alone too. Asked again with side-by-side
mockups it came back the opposite way: **Name → Task → Files, for both tasks**, with `Analyze MEA`
gaining a step 3 and being created at the end of the wizard with its recordings already on it.

⛔ **The lesson, for whoever reads this next: a ruling that looks outgrown may just be ahead of the
app.** The right move was to leave `docs/BEHAVIOUR.md` alone and ask — not to record the exception
the code seemed to have earned.
