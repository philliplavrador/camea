---
id: 002
title: Analyze MEA — pick your recordings when you make the project, and they land on its shelf
status: queued # queued | active | done | abandoned
created: 2026-08-14
needs: dev server # none | frontend | dev server | engine — which gates this build owes
blocked-by: none
resolves: none
---

# 002 — Analyze MEA — pick your recordings when you make the project, and they land on its shelf

> ⚠️ **THIS PLAN WAS SPLIT ON 2026-08-14, AFTER 001 SHIPPED.** It was one plan covering the whole
> `Analyze MEA` feature — files *and* the chip map — and at 14 `Done when` boxes it was more than one
> session builds well. The seam is clean: this half is **getting recordings onto a project**, and
> [003](003-analyze-mea-chip-map-and-traces.md) is **looking at one**. They share nothing but
> `core/mearecording.py`. This half is the more urgent one — see § Deploy.

## What and why

[001](../done/001-pick-a-task-at-project-creation.md) made `Analyze MEA` a task you can pick, and it
creates an empty project. That was an **intermediate state**, shipped knowingly. What he actually
asked for is that making the project *asks you for the files*:

> *"you create the project then you select what you want to do in this project ... then after that
> it asks you to upload the files you need for that task."*

So: **Name → Task → Files**, for both tasks. This plan builds the Files step for `Analyze MEA`, the
picker behind it, and the shelf the chosen recordings land on — several MaxWell `.h5` at a time,
each usable the instant it is added while a copy is pulled into the project behind it.

Against [mea-calcium-goal.md](../../../utils/knowledge/mea-calcium-goal.md): this is the electrical
half **on its own terms**, with no calcium, no mosaic and no pairing. It is not a step toward the
pairing and must not grow into one.

## Decisions

The interview, recorded 2026-08-14.

| Question | Answer |
|---|---|
| ⭐ When does an `Analyze MEA` project get its first recordings? | **At creation, in the wizard.** *"you create the project then you select what you want to do in this project ... then after that it asks you to upload the files you need for that task."* He was shown side-by-side mockups and picked this over "open empty and add from inside" explicitly. |
| Does adding recordings from inside the project survive? | **Yes** — it is just no longer the only door. The shelf's **Add recordings** button does the same thing at any time; the wizard step is how the first ones arrive. |
| Where does the `.h5` file live once added? | ⭐ **"Reference it until the copy is finished."** Usable the instant it is added, read from where it sits; a copy runs into the project in the background; when the copy lands the project reads its own copy from then on. |
| How do you add them? | **"Opens file explorer, can import multiple at a time."** Several recordings in one gesture. |
| What does removing a recording do? | Forgets it and deletes **Camea's copy**. ⛔ The user's original file is never touched, and there is no confirm box for deleting a copy Camea made itself. |
| Is there calcium anywhere in this? | **No.** "This one will not have any calcium data to go along with it." |

⚠️ **The creation-order row REVERSES a row in [001](../done/001-pick-a-task-at-project-creation.md)
§ Decisions** which said `Analyze MEA` asks for no data at creation. 001 shipped that and was closed
as **done deliberately**: the step-3 picker could not be built there because it needs everything
below. Nothing 001 built is thrown away — this plan changes **when** the project is created and
**what is on it** when it is.

⛔ **AND IT MEANS `docs/BEHAVIOUR.md` NEEDS NOTHING.** R41 (*"a project is one dataset + one task"*)
and R44.2 (*"New project asks for ONE path"*) briefly stopped covering all three tasks while 001 was
the whole story. This restores both: every project asks for its data at creation, and creation asks
exactly one data question. ⛔ Do not add an exception for this task; do not re-open it.

**Explicitly rejected:**
- **Copy-only, or reference-only.** He asked for both in sequence, and the reason is real: the files
  are gigabytes, so a blocking copy would make importing feel broken, and a permanent reference
  would let a moved folder silently gut a project.
- **Two pickers** — one for the wizard, one for the shelf. See § Approach; this is the single most
  important structural instruction in the plan.
- **Comparing recordings, opening two at once.** "You pick one to load, and it opens it up." One at
  a time.

## Scope

**In:**
- ⭐ **A Files step in the creation wizard** — `NewProjectFlow` grows a third step for the `mea`
  task, and **creation moves to the END of it**. Today (001) the card click creates immediately;
  after this plan the project is created **with its first recordings already on it**, by one call.
  The `dataStep`/`createNow` seam 001 left in `TASKS` is where this hooks in.
- **The picker** — browse to a folder, see every recording under it with a tick box each, take
  several at once. One component, mounted twice (wizard + shelf).
- **The shelf** — the project lists every recording it holds: label (`Network/000690`), duration,
  channel count, spike count, size, and **copy state** (referenced · copying N % · in the project ·
  original missing). Remove one.
- **The background copy**, and the document that records where each recording currently is.
- **The refusals, stated on screen, never as an empty row:** this file is not a MaxLab recording ·
  this recording is no longer where you left it.

**Out:**
- **Opening a recording** — the chip map, the activity colouring, the trace. That is
  [003](003-analyze-mea-chip-map-and-traces.md), and it is the other half of this feature. A
  recording on the shelf in this plan is a *row*, not a viewer.
- **Exporting anything.** No CSV, no figures. When he wants one it goes through the Outputs panel
  (R44/R47) and that is a separate plan.
- **Any pairing with calcium, any mosaic, any region.** This task exists precisely because it has
  none of that.
- **Editing the recording.** Read-only, always. ⛔ The `.h5` is evidence.

## Approach

### Backend — `src/camea/features/mea/`

`core/mearecording.py` already reads these files and is feature-agnostic. **Do not fork it and do
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
Nothing about *what is in* the recording is written down: not a channel list, not a spike count, not
a threshold. Every number on the screen is read off the file each time it is asked for.

**Where the copy goes.** `core/workspace.py` has `OUTPUTS = "outputs"` and `VIDEOS = "videos"` —
copied *inputs* already have a precedent, so add `RECORDINGS = "recordings"` beside `VIDEOS` and a
`recordings_dir` on `Project`/`ProjectSet` mirroring `videos_dir`. ⛔ The copy is written **inside
the project folder** and nowhere else (R44), and the source is opened **read-only** — nothing is
ever written next to the user's data.

🔴 **AND `own_entries()` MUST LEARN THE NEW NAME. This is the trap in this plan.**
[`core/project.py`](../../../src/camea/core/project.py) hard-codes
`names = {MARKER, DOCUMENT, AUTOSAVE, OUTPUTS, VIDEOS}` as the documented answer to *"every file in
this folder that is Camea's"*. Miss `RECORDINGS` and `move_to` leaves **gigabytes** behind, and
`delete()` on a pre-R44 folder does too. ⚠️ **It will not show up in testing**: the in-store case
(every project the app makes now) `rmtree`s the whole folder and is unaffected. Add it, and add a
test that asserts a recordings dir is in `own_entries()`.

`routes.py`, under `/api/mea/`:

| Route | What |
|---|---|
| ⭐ `POST /api/mea/projects` | **grows an optional `paths: [...]`** (001 built it name-only). Create-with-recordings is **ONE call, not create-then-add** — a second call that failed would strand a project he can see on the home screen and cannot use, and he would have to delete it himself to try again. The refusals 001 gave it (`_abandon` on a bad document, and the catch-all) must cover a bad path too: nothing on the list reads as a MaxLab recording ⇒ **no project is created**, and the refusal names the file. `paths` omitted ⇒ exactly 001's behaviour, which is the empty-shelf path and stays supported |
| `GET  /{id}/recordings` | the shelf, with live copy state |
| `POST /{id}/recordings` | `{paths: [...]}` — add several at once. Reads each header to confirm it is a MaxLab recording (refuse, by name, the ones that are not), records them as `referenced`, and **starts the copy job** |
| `DELETE /{id}/recordings/{rid}` | forget it, and delete the project's copy if there is one. Never touches the original |
| ⚠️ `GET  /api/mea/browse?path=` | **the one route with NO project** — the wizard calls it before a project exists. Every `data.raw.h5` under `path`, via `mearecording.find_recordings`, each with label/duration/size so he can tick the ones he means. It reads headers and nothing else; ⛔ it must not write, and must not be given a project id "for consistency" |

**The copy job** runs on the existing `core/jobs.py` infrastructure (as the video build does), one
job per recording, reporting bytes copied. Copy to a temp name in `recordings/<id>/` and rename on
completion, so a half-copied file can never be mistaken for a whole one. **On success the document
flips `copy` to `stored` and every later read uses `stored_path`; on failure it stays `referenced`
and says why.** A recording opened while its copy is still running reads the source — that is the
whole point of the answer he gave.

### Frontend

**`web/src/features/mea/ImportRecordings.tsx` — ⭐ ONE COMPONENT, TWO MOUNT POINTS.** This is the
point of the file, not a tidiness note. The wizard's Files step and the in-project **Add recordings**
button are the *same* tick-list, mounted twice. Two implementations of "browse a folder, tick the
recordings you mean" would drift within a week — one would grow the duration column, the other the
refusal-by-name — and he would meet a different picker depending on which door he came through.
⛔ Do not write a second one.

⚠️ **The wizard mount has no project yet**, and that shapes the contract: the component hands back
**a list of chosen paths and nothing else** — no `analysis_id`, no POST of its own, no document. The
*caller* decides what to do with the list: the wizard passes it to `POST /api/mea/projects` as
`paths`; the shelf passes it to `POST /{id}/recordings`. A picker that creates or mutates anything
itself cannot be mounted in the wizard at all.

**Two doors to the files, and they are not equivalent:**
- `POST /api/dialog/open-file` with **`allow_multiple=True`** (hard-coded `False` today —
  [routes_core.py:1470](../../../src/camea/api/routes_core.py#L1470) — so this is a small,
  deliberate backend change: add the flag to `DialogOpenFileRequest`, default `False`). Only exists
  when Camea runs with `--window`.
- Otherwise Camea's own picker: `FolderPicker` to choose a folder, then `GET /api/mea/browse` lists
  every recording underneath **with a tick box each**. ⭐ **This is the one he will actually use** —
  he drives Camea over VSCode remote, where there is no desktop and the native dialog returns
  `501 no_window`. Build it first and treat the native path as the bonus.

🔴 **`FolderPicker` MOVES TO `web/src/core/`.** It lives in `features/home/` today and
`features/outputs/OutputsPanel.tsx` already reaches across to it — a violation of the rule that
**features must not import each other** ([FeatureGate](../../../web/src/app/FeatureGate.tsx) is the
only seam that names features). This plan would be the third offender, so it fixes the cause
instead: move `FolderPicker.tsx` + its CSS to `web/src/core/picker/`, repoint both existing
importers, and note it in the move commit. (Found by the 001 team; the same argument moves
`TraceChart` in [003](003-analyze-mea-chip-map-and-traces.md).)

**`web/src/features/mea/MeaFeature.tsx`** grows from 001's empty state into the shelf. ⛔ Do not
import `PipelineNav` — this is not a pipeline, it is a shelf.

⚠️ **001's `?` becomes a lie the moment import works.** The empty state's help reads *"this button
turns on when it lands"* (`MeaFeature.tsx :: WHY_OFF`). **Replace it with what the button actually
does, or remove it** — an enabled button whose `?` says it is not built yet is worse than no `?`.

`npm run gen:api` after any change under `src/camea/api/` — ⛔ every type on the wire is generated.

### What must be said on screen, not swallowed

Two here (the third, *the waveform did not decode*, arrives with the trace in
[003](003-analyze-mea-chip-map-and-traces.md)):

1. **this file is not a MaxLab recording** — refused **by name** at import, not silently dropped
   from the tick-list.
2. **the original moved** — a `referenced` recording whose source has vanished says so **on the
   shelf**, and refuses to open, rather than showing an empty row.

🔴 **BOTH STAY ON THE PAGE AS `LiveWarning`. ⛔ NEITHER GOES BEHIND A `?`.**

001 moved a line of prose behind the `?` on his instruction, and it would be very easy to read that
as "explanations go behind the `?` on this screen" and hide these with it. **It is the opposite
instruction.** What went behind the `?` there was *"this part of Camea is not written yet"* — a fact
about the **app**. These are facts about **his data, right now**: his recording is not where he left
it; his file is not what he thinks it is. That is precisely R3's standing exception (W1–W11), and a
fact he must not be able to miss cannot live somewhere he has to hover to find. The distinction is
written into `MeaFeature.tsx :: WHY_OFF`; keep it true.

## Rulings this touches

- **R41 / R44.2 — restored, not changed.** Every project asks for its data at creation; creation
  asks exactly one data question. ⛔ Do not add an exception for this task (see § Decisions).
- **R44 (Camea owns the projects).** Upheld. The only path the user names is where a recording comes
  *from*; the copy lands in `<project>/recordings/` and nothing is written anywhere else. ⛔ No "open
  folder", no reveal, no save-folder box.
- **R3 (no explanations on screen)** — with its standing exception for a **live warning**, which is
  what the two above are.
- **I1 / no dataset knowledge.** ⛔ Nothing here knows a plate, a run, a channel count or which
  recordings matter. It lists what is in the folder he pointed at.

No ruling changes. New e2e coverage is needed; whether any of it earns a numbered BEHAVIOUR ruling
is a question for him, asked with the tool, once he has used it.

## Affected

- `src/camea/core/workspace.py` — `RECORDINGS` constant.
- `src/camea/core/project.py` — `recordings_dir` on `Project`/`ProjectSet`; 🔴 `own_entries()`.
- `src/camea/features/mea/{routes,document}.py` — the routes above and the `recordings` block.
- `src/camea/api/{schemas.py,routes_core.py}` — wire models; `allow_multiple` on the open-file dialog.
- `web/src/features/mea/{MeaFeature,ImportRecordings,RecordingShelf}.tsx` + CSS.
  ⭐ `ImportRecordings` is mounted **twice** — here and in the wizard. One component.
- `web/src/features/home/NewProjectFlow.tsx` — the `mea` task's `dataStep` stops being `null` and
  its `createNow` moves to the end of the Files step. ⚠️ 001 left the invariant *"`dataStep: null`
  and `createNow` being set are the same fact said twice, and they must agree"* — this plan makes
  both change together.
- `web/src/core/picker/FolderPicker.tsx` — **moved** from `features/home/`; both importers repointed.
- `web/src/api/schema.d.ts` — regenerated, never edited.
- `tests/api/test_mea_feature.py` — **extended** (001 created it).
- `web/tests/e2e/analyze-mea.spec.ts` — new.

## Done when

- [ ] ⭐ **New project → name → Analyze MEA → a Files step** that lets him pick **several `.h5` at
      once**, and **Create** at the end of it makes the project **with those recordings already on
      the shelf**. One call — there is no moment where a project exists with nothing on it because a
      second call failed.
- [ ] The **empty-shelf path still works**: a project whose recordings he has all removed shows
      001's empty state and its **Add recordings** button, and adding from there works.
- [ ] The empty state's `?` no longer says the button is unbuilt — it says what the button does, or
      it is gone.
- [ ] **Add recordings** inside the project shows **the same picker the wizard showed him**, not a
      second one. (Check by reading the imports, not by eye.)
- [ ] While copying, the shelf shows progress; when it finishes the entry reads as stored and the
      project's own copy is in `<project>/recordings/`. Nothing was written outside it.
- [ ] Removing a recording deletes the project's copy and **leaves the original untouched**.
- [ ] Moving the original of a `referenced` recording makes the shelf say so; it does not crash.
- [ ] A file that is not a MaxLab recording is refused **by name** at import.
- [ ] `own_entries()` includes the recordings dir, with a test that fails without it.
- [ ] `npm run check:api` clean.

## Verify

```bash
uv run ruff check . && uv run mypy
uv run pytest -q -m "not slow"
cd web && npm run lint && npx tsc -b --noEmit && npm test && npm run check:api
cd web && npm run e2e
node scripts/check-links.js
```

⚠️ `uv run mypy` is **already red** on the invocation `pyproject.toml` configures (missing
`py.typed`); `.claude/hooks/stop-gates.js` documents and defers it. Use `uv run mypy src/camea` and
report only what your change adds.

**And on real data, by hand.** `uv run camea`, make an `Analyze MEA` project through the wizard
against the MaxWell folder under `data/`, watch a copy finish, remove one, and confirm the original
is still on disk. ⛔ Then check `data/` is byte-unchanged — this plan is the first thing in Camea
that copies from it.

⚠️ **The `tests/fixtures/` dataset has no `.h5`** — it is a synthetic *frame* dataset. Add a tiny
synthetic MaxLab-shaped `.h5` (headers + mapping + a handful of spikes; **no raw stream**, so no
proprietary filter is needed and it stays small). **Prefer the fixture over skipping** — it is what
makes this feature testable in CI at all, it is a few kilobytes, and
[003](003-analyze-mea-chip-map-and-traces.md) needs it too.

## Deploy

Nothing — this lands on `master` and that is all.

**Ordering:** after [001](../done/001-pick-a-task-at-project-creation.md) (**done**, 2026-08-14).
⭐ **Before [003](003-analyze-mea-chip-map-and-traces.md)**, and it is the more urgent half: until
this lands, `Analyze MEA` is the one task that asks for no data at creation, which is not what he
asked for. 003 has nothing to open until this puts something on the shelf.

## Roll back

`git revert` takes the code back. What it does not take back: **a project's `recordings/` folder and
its `recordings` document block.** After a revert those files sit in the store unread — harmless,
but they are gigabytes and the user cannot see them without the feature that lists them. Say so in
the commit message.

⛔ No engine, no solver, no saved anchors, no mosaic, no export is in scope — a revert cannot cost
verification hours, because this plan collects none. **The user's own `.h5` files are never modified
or moved under any circumstance**, so there is no data-loss path to roll back from.

## Open

Three judgement calls, each with its criterion:

- **The fixture `.h5`** — build the tiny synthetic one (strongly preferred, see § Verify).
- **Whether the wizard's Files step lets him create with nothing picked.** ⛔ Not a free choice: the
  empty-shelf path must keep working (it is a `Done when` box), so the question is only whether the
  *wizard* offers it or insists on at least one file. Decide by what the step looks like with an
  empty tick-list, and say which you chose.
- **Whether the copy job is one job per recording or one per import.** Per recording reports
  progress better; per import is one row in the jobs list. Either is fine — say which and why.
