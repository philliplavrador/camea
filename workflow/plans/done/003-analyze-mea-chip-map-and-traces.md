---
id: 003
title: Analyze MEA — open a recording, watch the chip light up, click a pad and read it
status: done # queued | active | done | abandoned
created: 2026-08-14
needs: dev server # none | frontend | dev server | engine — which gates this build owes
blocked-by: 002
resolves: none
---

# 003 — Analyze MEA — open a recording, watch the chip light up, click a pad and read it

> ⚠️ **SPLIT OUT OF [002](002-analyze-mea-standalone.md) ON 2026-08-14.** They were one plan
> covering the whole `Analyze MEA` feature, and at 14 `Done when` boxes it was more than one session
> builds well. 002 is **getting recordings onto a project**; this is **looking at one**. They share
> nothing but `core/mearecording.py`.

## What and why

[002](002-analyze-mea-standalone.md) puts recordings on a project's shelf. This is what happens when
you pick one.

Camea draws **the chip** — every pad that was actually recorded, at its real position, **coloured by
how much happened on it** — and clicking a pad shows that pad's trace and its spikes. No mosaic, no
video, no calcium, and ⭐ **no chip-seating question**: this screen works entirely in the chip's own
frame, where the file states its own geometry and every electrode id is *certain* rather than
provisional.

Against [mea-calcium-goal.md](../../../utils/knowledge/mea-calcium-goal.md): this is not the pairing
and it is not a step toward it. It is the electrical half on its own terms — the screen you want
when you are asking *"is this recording any good, and where was the culture alive?"* before you
spend an afternoon pairing it with calcium.

⭐ **The one big thing this gets for free:** the activity colouring and the spike ticks come from
MaxWell's **spike table**, which needs **no proprietary decoder**
([mea-recordings.md](../../../utils/knowledge/mea-recordings.md)). So the chip map is **trustworthy
on any machine**, including every one where the raw waveform decodes to a flat line. That is what
makes this screen worth building before the decoder problem is solved.

## Decisions

The interview, recorded 2026-08-14.

| Question | Answer |
|---|---|
| What is the main picture when you open a recording? | ⭐ **The chip map, coloured by activity.** "Every recorded pad drawn as a dot where it actually sits on the chip, brighter/hotter where more was happening. Click a dot, read its trace." |
| Several recordings in one project — do you see them together? | **No.** "You pick one to load, and it opens it up." One at a time. |
| Is there calcium anywhere in this? | **No.** "This one will not have any calcium data to go along with it." |

**Asked during the build (2026-08-14), because the plan was silent and he would have seen it:**

| Question | Answer |
|---|---|
| ⭐ **How the activity colour is scaled** (asked with ASCII mockups of all three) | 🔴 **HELD — he picked none and corrected the premise instead.** See § Open; the scale is isolated in one file, with an evidence-chosen provisional default. His correction — *"not all electrodes can be used at the same time on an MEA chip. of the neurons that are being used not all of them are near neurons"* — is a fact about the hardware and the biology, and its second half changed the **wording** of this whole screen (below). |
| **What a dead pad looks like** (hollow ring · flat grey · smaller dot, with mockups) | **Hollow ring.** *"up 2 u"* — taken as the recommendation, on the argument that a different **shape** can never be confused with a position on a colour range, and survives greyscale. |
| ⭐ **Whether the map shows the whole chip or just the recorded block** (mockups of both) | **The whole chip.** The outline is the chip; the recorded pads sit in their real place inside it, fitted on open. Measured on the mirror, this is the difference between seeing that 000690 recorded a 63 × 57 corner and 000691 recorded 216 × 111 — filling the window with the dots makes those two look identical. |

**⭐ HIS CORRECTION CHANGED THE WORDING, AND THAT PART WAS NOT PENDING ANYTHING.** *"Of the neurons
that are being used not all of them are near neurons"* means a routed pad with **zero spikes is the
ordinary, expected case** — there was simply no cell near it. ⛔ It is not a dead electrode, not a
fault, and not evidence of a quiet culture. So nothing on this screen calls such a pad *dead*,
*failed* or *silent*: `activityScale.ts :: SILENT_MEANING` is the single sentence, and a unit test
fails if it ever acquires one of those words. **This is the most likely thing for a later session to
"tidy" back, because "dead electrode" is the phrase the whole field uses.**

**Decided in the build, by reading the code rather than guessing:**

| Question | Answer |
|---|---|
| ⚠️ How to draw *the whole chip* when the file only states half of its size | The **width** is `stride`, which the file's numbering states and `derive_geometry` verifies against every routed pad. The **height** is not in the file at all — a recording that routed a corner evidences only that corner. So `core.electrodegrid.MAXWELL` (R45.8's single place for a device number, whose `axes` are deliberately orientation-free) is **consulted**: if the derived stride IS one of its axes, the other axis is the height. ⛔ **Consulted, never assumed** — a file whose stride disagrees is drawn as what it actually shows, and `chip_extent` says which answer you got. The 13 × 5 fixture takes the fallback, so the tests prove the honest arm rather than the happy path. |
| ⚠️ **`core/viewer/Viewer.tsx` turned out NOT to be reusable, and § Approach assumed it was** | It is built around image tiles and keys its lifecycle on image URLs; there is no image here, only points. Only `camera.ts`'s pure maths is shareable. The camera follows `features/videomosaic/PreviewViewer` (wheel-zoom at pointer, drag-pan, click-that-did-not-travel) and the drawing follows `features/electrodes/GridOverlay` (one canvas, never a DOM node per pad) — two conventions the repo already had, rather than a third. |
| A fourth module § Affected did not name | **`OpenRecording.tsx`** — loads the two GETs and lays out the chip beside the trace. `ChipMap` stays about drawing and `MeaTrace` about one pad, which is what let both be tested without a project. |
| R45.7's hit-radius lesson | Applied **up front** rather than rediscovered: the click radius grows to keep a usable on-screen target when zoomed out, capped at the cell circumradius so nearest-centre can never take a neighbour's ground. A world-unit radius becomes a sub-pixel target at fit zoom and the failures come in *bands* — which reads to a user as *"there are missing patches"*, the exact report that cost an afternoon on the electrode map. |

**Explicitly rejected:**
- **Reusing the `col-row` electrode ids from the mosaic pipeline.** Those exist because the mosaic
  has to *guess* how the chip was seated under the microscope, which is
  [unresolved](../../../utils/knowledge/mea-recordings.md). Here there is no microscope: the file
  states its own `electrode`, `x_um`, `y_um`, so the ids are exact and the whole orientation problem
  is absent. ⛔ Do not import it into this feature "for consistency", and ⛔ do not copy the video
  feature's *"the chip's seating is provisional"* warning — it would teach a doubt that does not
  exist here.
- **Comparing recordings side by side, overlaying two traces, averaging across pads.** Not asked
  for. One recording, one pad, one trace.

## Scope

**In:**
- **Open one** — pick a recording off the shelf; the rest of the screen is about that recording.
- **The chip map** — one dot per routed pad at its `x_um`/`y_um`, coloured by spikes-per-second,
  with a legend that names the scale in real units. Zoom/pan. Hover names the electrode.
- **Click a pad → the trace panel** — waveform + spike ticks, with the honest warnings.
- **The refusals, stated on screen, never as an empty chart:** the raw stream did not decode · this
  pad was never routed.

**Out:**
- **Spike sorting, bursts, rasters, cross-correlation, any analysis beyond "how many spikes".** Not
  asked for, and each is a project on its own. The activity colour is a **count**, and the legend
  says so.
- **Exporting anything.** No CSV, no figures. When he wants one it goes through the Outputs panel
  (R44/R47) and that is a separate plan.
- **Any pairing with calcium, any mosaic, any region.**
- **Fixing the MaxWell decoder.** Out of reach and out of scope — this plan *reports* the problem
  honestly and is designed so the screen is useful anyway.

## Approach

### Backend — `src/camea/features/mea/routes.py`

`core/mearecording.py` already does all the reading. **Do not fork it and do not "improve" it for
this screen** — if it needs something new, add it there with its own test.

| Route | What |
|---|---|
| `GET /{id}/recordings/{rid}/layout` | the routed pads: `channel, electrode, x_um, y_um` + header facts + `stride`/`pitch_um` |
| `GET /{id}/recordings/{rid}/activity` | per-pad spike count and spikes/s, from `MeaRecording.spikes()` — one pass over the spike table, ⭐ **no raw decode** |
| `GET /{id}/recordings/{rid}/trace?channel=&t0=&t1=` | ⭐ by **channel**, not by `col-row`. Otherwise the same payload as the video feature's trace route, **minus `orientation`** |

⭐ **The existing trace route is the model, not the target.**
[`get_mea_trace`](../../../src/camea/features/videomosaic/routes.py) does the same job for the
mosaic pipeline, and two thirds of it is resolving a clicked `col-row` through the chip's seating to
a channel. **All of that disappears here** — the click already knows its channel. Read it for the
window clamping, the `MAX_TRACE_SECONDS` guard, the spike window, `first_spike_s`, `trace_health`
and the `RawUndecodable` arm, and reproduce those; ⛔ do not reproduce the orientation half, and do
not refactor the video route to share (they answer different questions and the shared thing —
`core/mearecording.py` — is already shared).

⚠️ **`layout` and `activity` on a 300 s recording are a full pass over the spike table.** Measure it
in the build: if either is slow enough to block the screen, it becomes a **job** like the copy, not
a spinner on a GET. Say what you measured.

⚠️ A recording whose `copy` state is `referenced` is read from `source_path`; one that is `stored`
is read from the project's own copy. That resolution lives in **one** place in the feature — do not
let three routes each decide it.

### Frontend — `web/src/features/mea/`

- **`ChipMap.tsx`** — canvas, not SVG: ~1024 dots is fine either way, but the click-to-select and
  the zoom want a canvas, and `web/src/core/viewer/` already holds the pan/zoom the mosaic uses.
  ⚠️ **THAT LAST CLAUSE WAS WRONG, AND THE BUILD FOUND IT.** `core/viewer/Viewer.tsx` is built
  around **image tiles** and keys its whole lifecycle on image URLs; there is no image on this
  screen, only points, so it cannot be mounted here. Only `core/viewer/camera.ts`'s pure maths is
  shareable. What shipped follows the two conventions the repo already had —
  `features/videomosaic/PreviewViewer` for the gestures and `features/electrodes/GridOverlay` for
  drawing N dots on one canvas — rather than inventing a third.
- **Colour.** A perceptually ordered ramp with a legend in spikes/s, and ⭐ a **distinct,
  unmistakable colour for zero spikes** — a dead pad must not look like a slightly dim live one. The
  scale is computed from the recording in front of it, every time (⛔ I1: no dataset knowledge, no
  fixed maximum).
- **Reuse `TraceChart`, do not copy it.** It lives in `web/src/features/electrodes/` and ⛔ features
  must not import each other ([FeatureGate](../../../web/src/app/FeatureGate.tsx) is the only seam
  that names features). So **move `TraceChart.tsx` + its CSS to `web/src/core/trace/`** and repoint
  its one existing importer (`MeaTracePanel`). That move is part of this plan and is the right kind
  of small: it makes the second user legal. (002 moves `FolderPicker` for the same reason; if 002
  has landed, follow the layout it chose.)
- **The trace panel here is `MeaTracePanel` minus one warning.** Read
  [MeaTracePanel](../../../web/src/features/electrodes/MeaTracePanel.tsx) — it is the same job with
  the same three live warnings, and the chip-seating one **must not come with it** (see § Decisions).
  Whether that is a shared component or a second one is a judgement call: they diverge on the
  identity question, which is the panel's whole reason for existing, so **a second panel that shares
  `TraceChart` is the expected answer**. Say which you did.
- `npm run gen:api` — ⛔ every type on the wire is generated.

### What must be said on screen, not swallowed

Two, and both are learned the hard way in the video feature:

1. ⚠️ **The waveform may not have decoded.** MaxWell compresses the raw stream with a proprietary
   filter and the publicly available decoder does not reconstruct this project's files (measured:
   98 % of samples come back as one fill value). `health.flat` says so — **state it and dim the
   trace**, because a railed window looks *exactly* like a genuinely silent electrode. The spike
   ticks are still exactly right and are drawn anyway.
2. **"never recorded" is the ordinary answer** — ~1k of 26,400 pads are routed. The chip map only
   *draws* routed pads, which mostly removes the question; keep the wording for the case where a
   click resolves to nothing.

🔴 **BOTH STAY ON THE PAGE AS `LiveWarning`. ⛔ NEITHER GOES BEHIND A `?`.** 001 moved a line of
prose behind the `?` on his instruction, and it would be easy to read that as "explanations go
behind the `?` on this screen". **It is the opposite instruction.** What went behind the `?` was
*"this part of Camea is not written yet"* — a fact about the **app**. These are facts about **his
data, right now**, which is precisely R3's standing exception (W1–W11), and a fact he must not be
able to miss cannot live somewhere he has to hover to find. The distinction is written into
`MeaFeature.tsx :: WHY_OFF`; keep it true.

## Rulings this touches

- **R3 (no explanations on screen)** — with its standing exception for a **live warning**, which is
  what the two above are. Not dismissible, not behind a `?`.
- **I1 / no dataset knowledge.** ⛔ Nothing here knows a plate, a run, a channel count, an expected
  spike rate, or which electrodes matter. The colour scale is computed from the recording in front
  of it, every time.
- **R44 / R47.** This screen writes nothing and shows no Outputs drawer, because it produces no
  outputs.

No ruling changes. New e2e coverage is needed; whether any of it earns a numbered BEHAVIOUR ruling
is a question for him, asked with the tool, once he has used it.

## Affected

- `src/camea/features/mea/routes.py` — the three routes, `_recording_path`/`_open` (the one place
  they decide which file to read) and `_chip_rows`. ⚠️ **No `activity.py`**: the tally belongs in
  core (§ Open), so the feature had nothing left to put in a second module.
- `src/camea/core/mearecording.py` — ⭐ **`MeaRecording.activity()`**, with 6 unit tests. The per-pad
  tally is a fact about the file, not about the screen.
- `src/camea/api/schemas.py` — `MeaChipPad`, `MeaChipLayout`, `MeaPadActivity`, `MeaChipActivity`,
  `MeaChannelTrace`. ⛔ Not one of them carries an `orientation`.
- `web/src/features/mea/{MeaFeature,ChipMap,MeaTrace,OpenRecording}.tsx` + CSS, and
  `RecordingShelf.tsx` (an **Open** button, off on a row whose file is at neither address).
  ⭐ **A fourth file § Affected did not name**: `OpenRecording.tsx` loads the two GETs and lays the
  chip out beside the trace, which is what keeps `ChipMap` about drawing and `MeaTrace` about a pad.
- ⭐ `web/src/features/mea/activityScale.ts` (+ tests) — **the one place a rate becomes a colour**,
  and the only file a settled colour scale has to touch. See § Open.
- `web/src/api/meaproject.ts` — three typed wrappers.
- `web/src/core/trace/TraceChart.tsx` — **moved** from `features/electrodes/`, importer repointed.
  Its own commit (`2c07adf`), so the move is reviewable apart from the screen that needed it.
- `web/src/api/schema.d.ts` + `docs/openapi.json` — regenerated, never edited.
- `docs/API.md` — three rows, and what was measured.
- `tests/api/test_mea_feature.py` — extended (001 created it, 002 grew it): **17 new**, 47 in file.
- `web/tests/e2e/{analyze-mea.spec.ts,pages.ts}` — extended (002 created it): **7 new**, 18 in file.

## Done when

- [x] Picking a recording off the shelf draws **one dot per routed pad**, positioned by the file's
      own µm coordinates.
      *(`GET .../layout` returns only the routed set; `ChipMap` draws at `x_um`/`y_um`. Verified on
      REAL data: P003658/000690's 726 pads land as a block spanning x 0–1085 µm, y 0–980 µm inside a
      3833 × 2083 µm chip — i.e. the corner block `utils/knowledge/mea-recordings.md` records for
      that culture, measured off the screenshot at 205 × 184 px against a predicted 204 × 184.
      e2e: `picking a recording draws the chip…`; api:
      `test_layout_draws_one_pad_per_ROUTED_channel_at_the_files_own_coordinates`.)*
- [x] The dots are coloured by spikes/s, with a legend in real units.
      *(⚠️ The **scale** is HELD — see § Open. The legend is in spikes/s and was read on real data:
      `0.003 · 0.017 · 0.027 · 0.040 · 14 spikes/s` for 000690.)*
- [x] A pad with **zero spikes is visually unmistakable** from a live one.
      *(A **hollow ring** — his call, 2026-08-14, from three mockups. A different SHAPE, so it can
      never be misread as a dim colour, and it survives greyscale. 208 of 726 rings on 000690, 625
      of 1012 on 000691, both confirmed on screen.)*
- [x] Clicking a dot shows that pad's trace and spike ticks, and names the electrode.
      *(Real data: electrode **2674**, channel 844, 595/210 µm, 9 spikes, 0.030 spikes/s. Spike
      ticks confirmed **drawn** by counting canvas pixels — 20 red px for the 2 spikes in view.)*
- [x] Hover names the electrode without a click.
      *(`mea-chip-hover`, nearest-pad within the R45.7 hit radius.)*
- [x] ⭐ **With no MaxWell decoder present**, the chip map and the spike ticks are **fully correct**,
      and the waveform *says it did not decode* instead of drawing a flat line.
      *(🔴 The one that matters most, and it is proven on real data rather than on the fixture: this
      machine has no working decoder, `health.flat` came back `true` with `fill_fraction 1.000`, the
      `LiveWarning` said so on the page — and the tally still agreed with the file on **726 of 726
      pads**. e2e: `🔴 with no decoder the waveform SAYS SO…`, which also asserts the warning is an
      announced `role="status"` region with **no button inside it**, i.e. not behind a `?`.)*
- [x] A click that resolves to an unrouted pad says "never recorded" as a fact, not as an error.
      *(200 with `recorded: false`, never a 404 —
      `test_trace_of_a_channel_that_was_never_routed_is_a_FACT_not_an_error`. ⭐ The wording was
      changed by his correction: it now says only some of the chip's pads **can be recorded at
      once**, which is the true reason.)*
- [x] The chip map's colour scale is derived from the open recording — **no constant anywhere** in
      `src/camea/` or `web/src/` describes how active a chip should be.
      *(`activityScale(rates)` takes the recording's own rates and nothing else. Three tests:
      `test_the_scale_is_the_recordings_own_and_nothing_declares_a_maximum` (api),
      `takes its maximum from THIS recording and nothing else` (unit), and an e2e that opens both
      fixture recordings and requires their legends to differ. Seen on real data: 000690 tops out at
      14 spikes/s and 000691 at 17, with different ramps.)*
- [x] `npm run check:api` clean. *(And the client was regenerated, never typed by hand.)*

## What the reviews found

Four passes — `api-contract-guard`, `dataset-knowledge-guard`, `frontend-conventions`,
`behaviour-guard`. Two clean, two with real bugs. ⭐ **Both of the real ones were things the tests
were happy with**, which is the argument for running them at all.

| Found | What it was | Done |
|---|---|---|
| 🔴 A bad chip mapping **500'd** | `_open` claimed to fail fast on a bad file but only touched `info()` (the header). The geometry is derived in `mapping()`, and `derive_geometry` refuses **by design** for cases it cannot explain — so that refusal escaped as an unhandled error. | Fixed + regression test. ⛔ And fixing it exposed worse: the refusal reused `NotARecording`, i.e. said *"this is not a MaxLab recording"* about a file whose header had just read fine — **the exact lie recorded against ActivityScan/000687**. It now names what actually failed. |
| ⚠️ The same gap at **import** | `facts_of` reads the header only, so such a file lands on the shelf and refuses one click later. 002's module, outside § Affected. | **[Issue 008](../../issues/medium/008-mea-import-accepts-a-file-whose-chip-layout-cannot-be-derived.md)**, with the note that it wants deciding **alongside 007** — both are *"a real MaxLab file this reader will not open"*. |
| 🔴 The chip map was **squeezed into an 880 px column** | `.pane` capped the whole feature at a readable measure — right for 002's shelf (a list), wrong the moment a **picture** went in it. On a 1600 px window the canvas was ~480 px with the trace packed beside it. ⚠️ **It is visible in the screenshots I took before the review and I did not see it.** | Fixed with the split `VideoMosaicFeature` already uses. Measured after: canvas **480 → 1040 px**, page no longer scrolls. |
| ⚠️ Every pad click fetched the trace **twice** | `jumped` was state, written by the fetch effect *and* in that effect's dependencies. | Now a ref — it is never read during render, so it was never state's job. |
| ⚠️ The hit radius had **no test and no stated reason** | It differs from `features/electrodes/lookup.ts` deliberately (0.5 vs 0.30 × pitch) because this screen is a **viewer**, not an identity surface — but nothing said so and nothing pinned either bound. | Its own module, the argument written down, **6 tests** — including that a real gap still selects nothing. |
| ⚠️ `role="application"` takes the keyboard | …and the pad's facts landed only in the trace panel, outside the widget an assistive-tech user is locked into. | A visually hidden live region announces the selection where the keystroke happened. |

⛔ **One warning NOT taken**, recorded so the dissent is not lost: dropping `chip_cols` as a
duplicate of `stride`. They are equal by construction today but are not the same concept — `stride`
is a property of the electrode **numbering**, `chip_cols` is **how many columns to draw** — and the
`chip_cols`/`chip_rows` pair reads better at the call site than `stride`/`chip_rows`.

⚠️ **And one pre-existing flake surfaced, unrelated to this plan:**
[issue 009](../../issues/medium/009-recovery-compares-mtimes-that-are-usually-equal.md). The full
Python suite went red on `test_the_autosave_lands_BESIDE_the_document_never_over_it`, which passes
alone. `core/project.py :: recovery()` decides *"is the autosave newer?"* with a strict `>` on
filesystem mtimes — and **188 of 200 back-to-back writes share an mtime on this machine** (measured).
Nothing this plan touched is imported by that test; adding tests only shifted the timing enough to
expose it.

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

🔴 **And on real data, by hand — this is the gate that matters, and it is not a formality.**
`uv run camea`, open a real MaxWell recording from under `data/`, and confirm the chip map's live
region matches what he already knows about that culture. **A chip map that looks plausible but is
wrong is exactly the failure this app exists to prevent**, so check at least one clicked pad's spike
count against `MeaRecording.spikes_of_channel` directly, and check a second pad at the *other* end
of the colour scale. Report both numbers.

⚠️ Needs the tiny synthetic MaxLab-shaped `.h5` fixture that [002](002-analyze-mea-standalone.md)
adds. If 002 skipped it, this plan builds it — the feature is not testable in CI without one.

## Deploy

Nothing — this lands on `master` and that is all.

**Ordering:** strictly after [002](002-analyze-mea-standalone.md). There is nothing to open until
recordings can be put on a shelf.

## Roll back

`git revert`, and nothing else is owed. This plan **writes nothing**: it reads recordings the
project already holds and draws them. ⛔ No engine, no solver, no saved anchors, no export, no
change to any project's on-disk shape — so a revert cannot cost verification hours and cannot
strand a project. The user's own `.h5` files are opened read-only and are never modified.

## Open

**All three are answered. One NEW thing is open, and it is his to settle — see the box below.**

| Asked | Answer | Where it lives |
|---|---|---|
| **`activity` as a GET or a job** | ⭐ **A GET, measured not guessed.** One pass over the spike table of a real recording costs **2.3–21 ms** end to end *including* the layout, across all five readable recordings in the mirror — worst case 982 channels × 244,925 spikes at 21 ms (000688); 000690 is 2.8 ms and 000691 5.7 ms. Nothing here wants a spinner, let alone a job, so the screen draws on first paint and there is no progress bar to write. | `routes.py :: get_mea_activity` docstring; `docs/API.md` |
| **Where the per-channel spike tally lives** | ⭐ **`core/mearecording.py`, with tests** — as § Open suspected. It is a pure function of the spike table and the routed set, i.e. a fact about the *file*, and the screen that draws it is only its first caller. 6 unit tests, two of which pin silent failures: a routed pad that heard nothing must come back **0 rather than absent**, and `searchsorted` must **confirm the hit** or a spike on an unrouted channel is credited to an innocent pad. | `MeaRecording.activity()`, `tests/unit/test_mearecording.py` |
| **One trace panel or two** | ⭐ **Two, sharing `TraceChart`** — the expected answer, and reading them side by side confirmed it. They diverge on **the identity question**, which is that panel's whole reason for existing: `MeaTracePanel` must say *"which electrode this is has not been established"*; this screen works in the chip's own frame where the file states its own ids. A shared panel would need a flag meaning *"am I allowed to be certain"*, and a component that can be told to doubt its own subject is the wrong shape. | `features/mea/MeaTrace.tsx` header |

---

### 🔴 NEWLY OPEN — the colour scale, and it is HELD deliberately

He was shown three ways of handing out the colours (straight · square-root · spread-them-out) and
**picked none**. He corrected the premise instead:

> *"not all electrodes can be used at the same time on an MEA chip. of the neurons that are being
> used not all of them are near neurons. Do some research on Maxwell MEA chips and keep a knowledge
> base on it in the repo"*

So the decision waits on **`docs/MAXWELL.md`** (being written separately — ⛔ not by this plan).
What that means for the code, and what a later session must not undo:

- **The scale is isolated in ONE file**, `web/src/features/mea/activityScale.ts`. Its header records
  all three options with the measurements. ⭐ **Settling it is a one-file edit**: `ChipMap` asks for
  a number 0–1 or `null` and draws that; it cannot be changed by the answer.
- **The provisional default is "spread them out"**, marked provisional, chosen only on evidence:
  measured, a **straight scale puts 90–99 % of live pads in the darkest tenth** on every one of his
  five recordings (99 % on 000690), and the square-root compromise is recording-dependent (96 % on
  000690, 41 % on 000692). ⛔ It is a placeholder, not an approved design.
- ⭐ **The second half of his correction is NOT pending and is already built in.** Among the pads
  that *were* routed, many are not near a neuron — so a routed pad with zero spikes is the
  **ordinary, expected** case, not a dead or failed electrode. The wording was changed everywhere:
  `SILENT_MEANING` (*"no spikes — most likely no neuron near this pad"*) is the single sentence, used
  by the legend and the hover, and a unit test **fails if it ever contains "dead", "failed",
  "broken", "faulty" or "bad"**. The trace panel states it as a plain fact styled quietly —
  deliberately not a `LiveWarning`, because nothing is wrong.

⚠️ **What a settled scale would still not change:** nothing outside `activityScale.ts`. The ring, the
legend's structure, the hover, the whole-chip framing and every test above are independent of it.
The one thing that would need a look is the legend's swatch *labels* — with the provisional scale
they read `0.003 · 0.017 · 0.027 · 0.040 · 14`, which is honest (the distribution really is that
skewed) but bunched, and a different scale would space them differently.
