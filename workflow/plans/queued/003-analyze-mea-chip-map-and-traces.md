---
id: 003
title: Analyze MEA — open a recording, watch the chip light up, click a pad and read it
status: queued # queued | active | done | abandoned
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

- `src/camea/features/mea/{routes,activity}.py` — the three routes and the per-pad tally.
- `src/camea/core/mearecording.py` — **only if** the per-channel spike tally belongs there rather
  than in the feature. With a test, or not at all.
- `web/src/features/mea/{MeaFeature,ChipMap,MeaTrace}.tsx` + CSS.
- `web/src/core/trace/TraceChart.tsx` — **moved** from `features/electrodes/`, importer repointed.
- `web/src/api/schema.d.ts` — regenerated, never edited.
- `tests/api/test_mea_feature.py` — extended (001 created it, 002 grew it).
- `web/tests/e2e/analyze-mea.spec.ts` — extended (002 created it).

## Done when

- [ ] Picking a recording off the shelf draws **one dot per routed pad**, positioned by the file's
      own µm coordinates.
- [ ] The dots are coloured by spikes/s, with a legend in real units.
- [ ] A pad with **zero spikes is visually unmistakable** from a live one.
- [ ] Clicking a dot shows that pad's trace and spike ticks, and names the electrode.
- [ ] Hover names the electrode without a click.
- [ ] ⭐ **With no MaxWell decoder present**, the chip map and the spike ticks are **fully correct**,
      and the waveform *says it did not decode* instead of drawing a flat line.
- [ ] A click that resolves to an unrouted pad says "never recorded" as a fact, not as an error.
- [ ] The chip map's colour scale is derived from the open recording — **no constant anywhere** in
      `src/camea/` or `web/src/` describes how active a chip should be.
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

Three judgement calls, each with its criterion:

- **`activity` as a GET or a job** — measure it on a real 300 s recording and say the number.
- **Where the per-channel spike tally lives** — `core/mearecording.py` with a test, or the feature.
  It is a pure function of the spike table, which argues for core.
- **One trace panel or two** — see § Approach; a second panel sharing `TraceChart` is the expected
  answer, because the two diverge exactly on the identity question that panel exists to state.
