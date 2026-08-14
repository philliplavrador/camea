---
id: 002
title: Analyze MEA — put recordings on the shelf, open one, watch the chip light up, click a pad
status: queued # queued | active | done | abandoned
created: 2026-08-14
needs: dev server # none | frontend | dev server | engine — which gates this build owes
blocked-by: 001
resolves: none
---

# 002 — Analyze MEA — put recordings on the shelf, open one, watch the chip light up, click a pad

## What and why

[001](001-pick-a-task-at-project-creation.md) makes an `Analyze MEA` project you can create and
open. This is what it opens *to*.

You import as many MaxWell `.h5` recordings as you like into one project. You pick one. Camea
draws **the chip** — every pad that was actually recorded, at its real position, **coloured by
how much happened on it** — and clicking a pad shows you that pad's trace and its spikes. No
mosaic, no video, no calcium, no chip-seating question: this screen works entirely in the chip's
own frame, where the file states its own geometry and every id is certain.

Against [mea-calcium-goal.md](../../../utils/knowledge/mea-calcium-goal.md): this is not the
pairing, and it is not a step toward it. It is the electrical half **on its own terms** — the
screen you want when you are asking "is this recording any good, and where was the culture
alive?" before you spend an afternoon pairing it with calcium.

⭐ **The one big thing this gets for free:** the activity colouring and the spike ticks come from
MaxWell's **spike table**, which needs no proprietary decoder
([mea-recordings.md](../../../utils/knowledge/mea-recordings.md)). So the chip map is
**trustworthy on any machine**, even the ones where the raw waveform decodes to a flat line.

## Decisions

The interview, recorded (2026-08-14).

| Question | Answer |
|---|---|
| What is the main picture when you open a recording? | **The chip map, coloured by activity.** "Every recorded pad drawn as a dot where it actually sits on the chip, brighter/hotter where more was happening. Click a dot, read its trace." |
| Where does the `.h5` file live once added? | ⭐ **"Reference it until the copy is finished."** Usable the instant it is added, read from where it sits; a copy runs into the project in the background; when the copy lands the project reads its own copy from then on. |
| How do you add them? | **"Opens file explorer, can import multiple at a time."** Several recordings in one gesture. |
| Several recordings in one project — do you see them together? | No. "You pick one to load, and it opens it up." One at a time. |
| Is there calcium anywhere in this? | **No.** "This one will not have any calcium data to go along with it." |
| What does removing a recording do? | Forgets it and deletes **Camea's copy**. ⛔ The user's original file is never touched, and there is no confirm box for deleting a copy Camea made itself. |

**🔴 ADDED AFTER 001 SHIPPED (2026-08-14). THIS PLAN NOW OWNS THE CREATION WIZARD'S THIRD STEP.**

| Question | Answer |
|---|---|
| ⭐ When does an `Analyze MEA` project get its first recordings? | **At creation, in the wizard.** *"you create the project then you select what you want to do in this project ... then after that it asks you to upload the files you need for that task."* New project is **Name → Task → Files, for BOTH tasks.** He was shown side-by-side mockups and picked this over "open empty and add from inside" explicitly. |
| Does adding recordings from inside the project survive? | **Yes** — it is just no longer the only door. The shelf's **Add recordings** button does the same thing at any time; the wizard step is how the first ones arrive. |

⚠️ **This REVERSES the row in [001](001-pick-a-task-at-project-creation.md) § Decisions** that said
`Analyze MEA` asks for no data at creation. 001 shipped that (create immediately, empty shelf) and
was closed as **done** deliberately: it is an **intermediate state**, and the step-3 picker could not
be built there because it needs everything below — the import component, the `.h5` reading, and the
`paths` argument on create. Nothing 001 built is thrown away; this plan changes **when** the project
is created and **what is on it** when it is.

⛔ **AND IT MEANS `docs/BEHAVIOUR.md` NEEDS NOTHING.** R41 (*"a project is one dataset + one task"*)
and R44.2 (*"New project asks for ONE path"*) briefly stopped covering all three tasks while 001 was
the whole story. This restores both: every project asks for its data at creation, and creation asks
exactly one data question. ⛔ Do not add an exception for this task; do not re-open it.

**Explicitly rejected:**
- **Reusing the `col-row` electrode ids from the mosaic pipeline.** Those exist because the
  mosaic has to *guess* how the chip was seated under the microscope, which is
  [unresolved](../../../utils/knowledge/mea-recordings.md). Here there is no microscope: the file
  states its own `electrode`, `x_um`, `y_um`, so the ids are exact and the whole orientation
  problem is absent. ⛔ Do not import it into this feature "for consistency".
- **Copy-only, or reference-only.** He asked for both in sequence, and the reason is real: the
  files are gigabytes, so a blocking copy would make importing feel broken, and a permanent
  reference would let a moved folder silently gut a project.
- **Comparing recordings side by side, overlaying two traces, averaging across pads.** Not asked
  for. One recording, one pad, one trace.

## Scope

**In:**
- ⭐ **A Files step in the creation wizard** — `NewProjectFlow` grows a third step for the `mea`
  task, and **creation moves to the END of it**. Today (001) the card click creates immediately;
  after this plan the project is created **with its first recordings already on it**, by one call.
  The `dataStep`/`createNow` seam 001 left in `TASKS` is where this hooks in.
- **Import** — multi-select, from the native dialog when Camea has a window, from Camea's own
  picker otherwise (see § Approach; both are needed, and the served one is the one *he* will see).
- **The shelf** — the project lists every recording it holds: label (`Network/000690`), duration,
  channel count, spike count, size, and **copy state** (referenced · copying N % · in the project ·
  original missing). Remove one.
- **Open one** — pick a recording; the rest of the screen is about that recording.
- **The chip map** — one dot per routed pad at its `x_um`/`y_um`, coloured by spikes-per-second,
  with a legend that names the scale in real units. Zoom/pan. Hover names the electrode.
- **Click a pad → the trace panel** — the existing waveform + spike ticks + the honest warnings,
  reused from `features/electrodes` and cut down (no "provisional identity" warning: the identity
  is not provisional here).
- **The refusals, stated on screen, never as an empty chart:** the raw stream did not decode ·
  this recording is no longer where you left it · this file is not a MaxLab recording.

**Out:**
- **Spike sorting, bursts, rasters, cross-correlation, any analysis beyond "how many spikes".**
  Not asked for, and each is a project. The activity colour is a *count*, and the plan says so.
- **Exporting anything.** No CSV, no figures. When he wants one, the Outputs panel is where it
  goes (R44/R47) and that is a separate plan.
- **Any pairing with calcium, any mosaic, any region.** [001](001-pick-a-task-at-project-creation.md)
  says why: this task exists precisely because it has none of that.
- **Editing the recording.** Read-only, always. ⛔ The `.h5` is evidence.

## Approach

### Backend — `src/camea/features/mea/`

`core/mearecording.py` already does the reading and is feature-agnostic. **Do not fork it and do
not "improve" it for this screen** — if it needs something new, add it there with its own test.

`document.py` — the document's `recordings` block, one entry per import:

```jsonc
{ "id": "…",              // minted, stable; never the path
  "label": "Network/000690", "run_id": "000690", "assay": "Network",
  "source_path": "D:/…/data.raw.h5",     // where it came from
  "stored_path": "recordings/<id>/data.raw.h5", // project-relative, once copied
  "copy": "referenced" | "copying" | "stored" | "failed",
  "bytes": 0, "added": "…" }
```

⛔ **`source_path` is a path, not dataset knowledge** — same standing as the manifest's `data_dir`.
Nothing about *what is in* the recording is written down: not a channel list, not a spike count,
not a threshold. Every number on the screen is read off the file each time it is asked for.

**Where the copy goes.** `core/workspace.py` has `OUTPUTS = "outputs"` and `VIDEOS = "videos"` —
copied *inputs* already have a precedent, so add `RECORDINGS = "recordings"` beside `VIDEOS` and a
`recordings_dir` on `Project`/`ProjectSet` mirroring `videos_dir`. ⛔ The copy is written **inside
the project folder** and nowhere else (R44), and the source is opened **read-only** — nothing is
ever written next to the user's data.

`routes.py` (all under `/api/mea/`, all guarded by the project store):

| Route | What |
|---|---|
| `GET  /{id}/recordings` | the shelf, with live copy state |
| `GET  /browse?path=` | ⭐ the **served** picker's file half: every `data.raw.h5` under `path`, via `mearecording.find_recordings`, each with label/duration/size so he can tick the ones he means |
| `POST /{id}/recordings` | `{paths: [...]}` — add several at once. Reads each header to confirm it is a MaxLab recording (refuse, by name, the ones that are not), records them as `referenced`, and **starts the copy job** |
| ⭐ `POST /api/mea/projects` | **grows an optional `paths: [...]`** (001 built it as name-only). Create-with-recordings is **ONE call, not create-then-add** — a second call that failed would strand a project he can see on the home screen and cannot use, and he would have to delete it himself to try again. The two refusals it already has (`_abandon` on a bad document, and the catch-all) must cover a bad path too: nothing on the list reads as a MaxLab recording ⇒ **no project is created**, and the refusal names the file. `paths` omitted ⇒ exactly today's behaviour, which is the empty-shelf path and stays supported |
| `DELETE /{id}/recordings/{rid}` | forget it, and delete the project's copy if there is one. Never touches the original |
| `GET  /{id}/recordings/{rid}/layout` | the routed pads: `channel, electrode, x_um, y_um` + header facts + `stride`/`pitch_um` |
| `GET  /{id}/recordings/{rid}/activity` | per-pad spike count and spikes/s, from `MeaRecording.spikes()` — one pass over the spike table, **no raw decode** |
| `GET  /{id}/recordings/{rid}/trace?channel=&t0=&t1=` | ⭐ by **channel**, not by `col-row`. Otherwise the same payload shape as the video feature's trace route, minus `orientation` |

**The copy job** runs on the existing `core/jobs.py` infrastructure (as the video build does), one
job per recording, reporting bytes copied. Copy to a temp name in `recordings/<id>/` and rename on
completion, so a half-copied file can never be mistaken for a whole one. **On success the document
flips `copy` to `stored` and every later read uses `stored_path`; on failure it stays `referenced`
and says why.** A recording opened while its copy is still running reads the source — that is the
whole point of the answer he gave.

⚠️ `layout` and `activity` on a 300 s recording are a full pass over the spike table. Measure it
in the build: if either is slow enough to block the screen, it becomes a job like the copy, not a
spinner on a GET.

### Frontend — `web/src/features/mea/`

- `MeaFeature.tsx` grows from 001's empty state into: **shelf** (left rail) · **chip map**
  (centre) · **trace** (bottom, appears on click). No pipeline stepper — this is not a pipeline,
  it is a shelf and a viewer. ⛔ Do not import `PipelineNav`.
  ⚠️ **And 001's `?` becomes a lie the moment import works.** The empty state's help reads *"this
  button turns on when it lands"* (`MeaFeature.tsx :: WHY_OFF`). **Replace it with what the button
  actually does, or remove it** — an enabled button whose `?` says it is not built yet is worse than
  no `?` at all.
- `ImportRecordings.tsx` — the import gesture.

  ⭐ **ONE COMPONENT, TWO MOUNT POINTS — and this is the point of the file, not a tidiness note.**
  The wizard's Files step and the in-project **Add recordings** button are the *same* tick-list,
  mounted twice. Two implementations of "browse a folder, tick the recordings you mean" would drift
  within a week: one would grow the duration column, the other the refusal-by-name, and he would
  meet a different picker depending on which door he came through. ⛔ Do not write a second one.

  ⚠️ **The wizard mount has no project yet**, and that shapes the component's contract: it must hand
  back **a list of chosen paths** and nothing else — no `analysis_id`, no POST of its own, no
  document. The *caller* decides what to do with the list: the wizard passes it to
  `POST /api/mea/projects` as `paths` (one call — see the route table above); the shelf passes it to
  `POST /{id}/recordings`. A picker that creates or mutates anything itself cannot be mounted in the
  wizard at all.

  **Two doors to the files themselves, and they are not equivalent:**
  - `POST /api/dialog/open-file` with **`allow_multiple=True`** (it is hard-coded `False` today —
    [routes_core.py:1470](../../../src/camea/api/routes_core.py#L1470) — so this is a small,
    deliberate backend change: add the flag to `DialogOpenFileRequest`, default `False`).
    Only exists when Camea runs with `--window`.
  - Otherwise Camea's own picker: [FolderPicker](../../../web/src/features/home/FolderPicker.tsx)
    to choose a folder, then `GET /api/mea/browse` lists every recording underneath **with a tick
    box each**. ⭐ **This is the one he will actually use** — he drives Camea over VSCode remote,
    where there is no desktop and the native dialog returns `501 no_window`. Build it first and
    treat the native path as the bonus.
- `ChipMap.tsx` — canvas, not SVG: ~1024 dots is fine either way, but the click-to-select and the
  zoom want a canvas, and `web/src/core/viewer/` already holds the pan/zoom the mosaic uses.
  Colour: a **perceptually ordered ramp** with a legend in spikes/s, and a distinct, unmistakable
  colour for "zero spikes" — a dead pad must not look like a slightly dim live one.
- **Reuse `TraceChart`**, do not copy it. It lives in `web/src/features/electrodes/` and
  ⛔ features must not import each other ([FeatureGate](../../../web/src/app/FeatureGate.tsx) is
  the only seam that names features). So **move `TraceChart.tsx` + its CSS to
  `web/src/core/trace/`** and repoint the one existing importer (`MeaTracePanel`). That move is
  part of this plan and is the right kind of small: it makes the second user legal.
- `npm run gen:api` — ⛔ every type on the wire is generated.

### What must be said on screen, not swallowed

Three, and they are the same three the video feature learned the hard way
([MeaTracePanel](../../../web/src/features/electrodes/MeaTracePanel.tsx)):
1. **"never recorded" is the ordinary answer** — ~1k of 26,400 pads are routed. Here the chip map
   only *draws* routed pads, which mostly removes the question; keep the wording for the case
   where a click resolves to nothing.
2. **the waveform may not have decoded** — `health.flat`, stated, trace dimmed. The spike ticks
   are still exactly right and are drawn anyway.
3. **the original moved** — a `referenced` recording whose source has vanished says so on the
   shelf and refuses to open, rather than showing an empty chart.

The third warning from the video feature — *the chip's seating is provisional* — **must not be
copied here.** There is no seating question in the chip's own frame, and importing the warning
would teach a doubt that does not exist.

🔴 **ALL THREE STAY ON THE PAGE AS `LiveWarning`. ⛔ NONE OF THEM GOES BEHIND A `?`.**

001 moved a line of prose behind the `?` on his instruction, and it would be very easy to read that
as "explanations go behind the `?` on this screen" and hide these with it. **It is the opposite
instruction.** What went behind the `?` there was *"this part of Camea is not written yet"* — a fact
about the **app**. These three are facts about **his data, right now**: his waveform did not decode,
his recording is not where he left it, his file is not a MaxLab recording. That is precisely R3's
standing exception (W1–W11), and a fact he must not be able to miss cannot live somewhere he has to
hover to find. The distinction is written into `MeaFeature.tsx :: WHY_OFF`; keep it true.

## Rulings this touches

- **R44 (Camea owns the projects).** Upheld. The only path the user names is where a recording
  comes *from*; the copy lands in `<project>/recordings/` and nothing is written anywhere else.
  ⛔ No "open folder", no reveal, no save-folder box.
- **R47 (Outputs is a drawer, and the only door to a project's files).** This feature produces no
  outputs, so it shows no Outputs drawer — and when it eventually exports something, that is where
  it goes, not a save dialog.
- **R3 (no explanations on screen)** — with its standing exception for a **live warning**, which
  is what the three above are. They are not dismissible and not behind a `?`.
- **I1 / no dataset knowledge.** ⛔ Nothing here knows a plate, a run, a channel count, an expected
  spike rate or which electrodes matter. The colour scale is computed from the recording in front
  of it, every time.

No ruling changes. New e2e coverage is needed for this screen (there is none — it does not exist
yet); whether any of it earns a numbered BEHAVIOUR ruling is a question for him, asked with the
tool, once he has used it.

## Affected

- `src/camea/core/workspace.py` — `RECORDINGS` constant.
- `src/camea/core/project.py` — `recordings_dir` on `Project` and `ProjectSet` (mirrors `videos_dir`).
- `src/camea/core/mearecording.py` — **only if** a per-channel spike tally wants to live there
  rather than in the feature. With a test, or not at all.
- `src/camea/features/mea/{routes,document,activity}.py` — the feature.
- `src/camea/api/{schemas.py,routes_core.py}` — the wire models; `allow_multiple` on the open-file
  dialog.
- `web/src/features/mea/{MeaFeature,ImportRecordings,RecordingShelf,ChipMap}.tsx` + CSS.
  ⭐ `ImportRecordings` is mounted **twice** — here and in the wizard. One component.
- `web/src/features/home/NewProjectFlow.tsx` — the `mea` task's `dataStep` stops being `null` and
  its `createNow` moves to the end of the Files step. ⚠️ 001 left the invariant *"`dataStep: null`
  and `createNow` being set are the same fact said twice, and they must agree"* — this plan makes
  both change together.
- `web/src/core/trace/TraceChart.tsx` — **moved** from `features/electrodes/`, importer repointed.
- `web/src/api/schema.d.ts` — regenerated.
- `tests/api/test_mea_feature.py` — new; against the committed fixture (see § Verify).
- `web/tests/e2e/analyze-mea.spec.ts` — new.

## Done when

- [ ] ⭐ **New project → name → Analyze MEA → a Files step** that lets him pick **several `.h5` at
      once**, and **Create** at the end of it makes the project **with those recordings already on
      the shelf**. One call — there is no moment where a project exists with nothing on it because
      the second call failed.
- [ ] The **empty-shelf path still works**: a project whose recordings he has all removed shows
      001's empty state and its **Add recordings** button, and adding from there works. (`paths`
      omitted on create is the same path, and is what keeps this honest.)
- [ ] The empty state's `?` no longer says the button is unbuilt — it says what the button does, or
      it is gone.
- [ ] In an `Analyze MEA` project, **Add recordings** lets you pick **several at once** and they
      all appear on the shelf — **the same picker the wizard showed him**, not a second one.
- [ ] A recording is **openable immediately**, before its copy has finished.
- [ ] While copying, the shelf shows progress; when it finishes the entry reads as stored, and
      the project's own copy is in `<project>/recordings/`. Nothing was written outside it.
- [ ] Opening a recording draws one dot per routed pad, positioned by the file's own µm
      coordinates, coloured by spikes/s, with a legend in real units.
- [ ] Clicking a dot shows that pad's trace and spike ticks, and names the electrode.
- [ ] A pad with zero spikes is visually unmistakable from a live one.
- [ ] With no MaxWell decoder present, the chip map and the spike ticks are still **fully
      correct**, and the waveform says it did not decode instead of drawing a flat line.
- [ ] Removing a recording deletes the project's copy and **leaves the original untouched**.
- [ ] Moving the original of a `referenced` recording makes the shelf say so; it does not crash
      and does not show an empty chart.
- [ ] A file that is not a MaxLab recording is refused **by name** at import.
- [ ] `npm run check:api` clean.

## Verify

```bash
uv run ruff check . && uv run mypy
uv run pytest -q -m "not slow"
cd web && npm run lint && npx tsc -b --noEmit && npm test && npm run check:api
cd web && npm run e2e
node scripts/check-links.js
```

**And on real data, by hand — this is the gate that matters.** `uv run camea`, make an
`Analyze MEA` project, import from the MaxWell folder under `data/`, and confirm the chip map's
live region matches what he already knows about that culture. A chip map that looks plausible but
is wrong is exactly the failure this app exists to prevent, so check at least one clicked pad's
spike count against `MeaRecording.spikes_of_channel` directly.

⚠️ **The `tests/fixtures/` dataset has no `.h5`** — it is a synthetic *frame* dataset. Either add
a tiny synthetic MaxLab-shaped `.h5` to the fixtures (headers + mapping + a handful of spikes; **no
raw stream**, so no proprietary filter is needed and it stays small), or mark the API tests to skip
without one. **Prefer the fixture** — it is what makes this feature testable in CI at all, and it
is a few kilobytes.

## Deploy

Nothing — this lands on `master` and that is all.

**Ordering:** strictly after [001](001-pick-a-task-at-project-creation.md) — **done**, 2026-08-14 —
which created the project type, the Task step and the shell this fills. ⭐ This plan also **finishes**
001: 001 shipped create-immediately-with-an-empty-shelf as an intermediate state, and the Files step
here is the shape he actually asked for. Until this lands, `Analyze MEA` is the one task that asks
for no data at creation.

## Roll back

`git revert` takes the code back. Two things it does not take back:

- **A project's `recordings/` folder and its `recordings` document block.** After a revert those
  files sit in the store unread — harmless, but they are gigabytes, and the user cannot see them
  without the feature that lists them. Say so in the commit message.
- **Nothing else.** ⛔ No engine, no solver, no saved anchors, no mosaic, no export is in scope
  here — a revert cannot cost verification hours, because this feature does not collect any.

The user's own `.h5` files are never modified or moved by this feature under any circumstance, so
there is no data-loss path to roll back from.

## Open

Empty. The interview settled the view, the file handling, the import gesture and the naming; the
creation order was settled on 2026-08-14 after 001 shipped (see § Decisions). The **four** judgement
calls left are the build's to make and each is written above with its criterion:

- `activity` as a GET or a job — measure it on a 300 s recording.
- the fixture `.h5` — add a tiny synthetic one (preferred) or skip the API tests without it.
- where the per-channel spike tally lives — `core/mearecording.py` with a test, or the feature.
- whether the wizard's Files step lets him create with **nothing** picked. ⛔ Not a free choice: the
  empty-shelf path must keep working (it is a `Done when` box), so the question is only whether the
  *wizard* offers it or insists on at least one file. Decide it by what the step looks like with an
  empty tick-list, and say which you chose.
