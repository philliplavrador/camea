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
- `ImportRecordings.tsx` — the import gesture. **Two doors, and they are not equivalent:**
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
- `web/src/core/trace/TraceChart.tsx` — **moved** from `features/electrodes/`, importer repointed.
- `web/src/api/schema.d.ts` — regenerated.
- `tests/api/test_mea_feature.py` — new; against the committed fixture (see § Verify).
- `web/tests/e2e/analyze-mea.spec.ts` — new.

## Done when

- [ ] In an `Analyze MEA` project, **Add recordings** lets you pick **several at once** and they
      all appear on the shelf.
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

**Ordering:** strictly after [001](001-pick-a-task-at-project-creation.md), which creates the
project type and the shell this fills.

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
three judgement calls left (`activity` as a GET or a job, the fixture `.h5`, where the spike tally
lives) are the build's to make and are written above with the criterion for each.
