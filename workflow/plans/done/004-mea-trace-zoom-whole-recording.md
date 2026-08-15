---
id: 004
title: The MEA trace shows the whole recording, and you drag a stretch to zoom into it
status: done # queued | active | done | abandoned
created: 2026-08-15
needs: dev server # none | frontend | dev server | engine — which gates this build owes
blocked-by: none
resolves: none
---

# 004 — The MEA trace shows the whole recording, and you drag a stretch to zoom into it

## What and why

Today `Analyze MEA` shows **one second** of a pad's voltage and a slider to move that second
through the recording. He said, plainly: *"I don't like the slider bar. What I want is the MEA
trace … more like the matplotlib, but the one where I have the interactive widget, so I have the
whole trace, and then I can make a rectangle around the area I want to zoom in, then I can go
back."*

So: the panel shows the **whole recording's voltage**, he **drags sideways** across it to zoom into
a stretch, and **Back** walks him out again — matplotlib's own navigation, ported. The slider goes.

**How it serves the goal.** Camea exists to pair an electrode's voltage with a neuron's calcium
trace ([utils/knowledge/mea-calcium-goal.md](../../../utils/knowledge/mea-calcium-goal.md)). Reading
a pad through a 1 s keyhole cannot answer *"is this electrode worth pairing?"* — that is a question
about the whole session's firing pattern, its bursts and its silences. This is the screen where he
decides which electrodes are worth the optical work, and it currently cannot show him the thing he
would decide on.

## Decisions

The interview, recorded 2026-08-15. Research behind it:
[utils/knowledge/mea-trace-zoom-design.md](../../../utils/knowledge/mea-trace-zoom-design.md).

| Question | Answer |
|---|---|
| On the whole-recording strip, spike marks or the voltage shape? | **"just the raw voltage trace"** — voltage, not marks. He accepted the wait this costs. |
| The close-up can only read ~30 s at once. What happens on a wider drag? | **"make it so it can go beyond the 30 sec limit"** — remove the ceiling. |
| Keep the auto-jump to where the pad first fired? | **Open at the start.** No jump. |
| The panel grows ~70 px in a column that cannot scroll. | **Let it be taller.** Check in preview; fold the facts row only if it genuinely overflows. |
| One picture that zooms, or two (strip + close-up)? | **Two pictures.** |
| When does the one-off ~20 s precompute run? | **At import.** |
| *(volunteered, mid-turn)* | **"run the loader on the MEAs I have already imported"** — the precompute must **backfill** recordings already in a project, not only new ones. He has 5 sitting in `p003658-19cc31` today. |

### Decided during the build, and told to him

| Question | Answer |
|---|---|
| The envelope build measured **37–70 s**, not the ~20 s quoted — exact per-channel health costs 38 s of it (measured: read 24 s, min/max 2.6 s, tally 38 s). Approximate it? | **No — keep it exact.** The number is printed in the "did not decode" warning, which is an honesty guarantee (R3.8). One background minute is the right thing to trade. He was told the corrected figure (~5½ min for his five, not 2¼). |
| The close-up's opening width, once the auto-jump was removed. | **The whole recording, in both pictures.** It is literally *"I have the whole trace, and then I make a rectangle around the area I want to zoom in"*, it teaches what the strip is for, and it makes "open at the start" moot. ⚠️ The one choice made **for** him — confirm in preview. |
| How to go past 30 s without a 10 MB response. | **A `max_points` query parameter and a reduced payload.** `MAX_TRACE_SECONDS` stays at 30.0 and still governs raw-sample requests, so the old contract and the videomosaic sibling are untouched. |
| Where the readout's numbers come from — the requested range or the served one. | **The served one**, the same range the chart is drawn from. They differ by up to one bucket when a wide view comes from the cache, and a caption disagreeing with its own chart is a small lie. |
| The spike row merged into a solid bar at full zoom (1166 ticks, ~530 px). | **Above one tick per pixel, stroke them separately at low alpha** so the row becomes a firing density. No spike is dropped at any zoom. |

### Measured on his own files, 2026-08-15 (`p003658-19cc31`)

`groups/routed/raw` is chunked `(n_channels, 200)`, gzip, on all five. One channel end to end costs
**12–23 s**; **all** 726–1015 channels cost **19–32 s** — a factor of **1.4**. That single ratio is
why the envelope is built for every channel in one pass and cached, rather than read per pad.

| run | shape | one ch | all ch | build (with tally) | cache | ch-0 most-repeated |
|---|---|---|---|---|---|---|
| 000688 | 982 × 3.60 M (180 s) | 12.1 s | 19.3 s | 37 s | 32.2 MB | **1.1 %** — clean |
| 000689 | 1015 × 6.00 M (300 s) | 23.0 s | 32.1 s | — | 33.3 MB | **4.4 %** — clean |
| 000690 | 726 × 6.00 M | 17.9 s | 21.8 s | — | 23.8 MB | 96.5 % — railed |
| 000691 | 1012 × 6.00 M | 22.1 s | 31.5 s | 70 s | 33.2 MB | 100 % — railed |
| 000692 | 1012 × 6.00 M | 19.7 s | 29.4 s | — | 33.2 MB | 93.9 % — railed |

⭐ **The rail is three recordings, not the decoder** — which contradicts what `docs/MAXWELL.md` §6
said and has been corrected there. The recording he was looking at when he asked for this (000688)
is one of the clean ones.

**Explicitly rejected:**

- **A whole-recording strip of spike marks instead of voltage.** It was the recommendation — instant,
  decoder-free, correct even on the three railed plates — and he turned it down. He wants the raw
  voltage. Do not quietly substitute marks because the voltage is expensive.
- **One picture.** Offered as closest to matplotlib and to his own words; he chose two. The strip is
  not a slider and must not grow slider affordances (no handle, no track, not draggable as an object).
- **Raising or deleting `MAX_TRACE_SECONDS`.** He asked to go past 30 s, and the answer is a
  *reduced* payload, not a bigger one. The constant stays at 30.0 and keeps governing raw-sample
  requests — including the videomosaic sibling route, whose duplication is deliberate
  ([routes.py:470-486](../../../src/camea/features/mea/routes.py#L470-L486)).
- **Auto-jump to first spike.** Deleted, per his answer. `first_spike_s` stays on the payload
  (free, already computed) but this screen stops acting on it.

## Scope

**In:**

- A **min/max envelope** of every channel, computed once per recording, cached beside it, covering
  the recording end to end.
- Computed **at import**, and **backfilled** for recordings already imported.
- A trace route that can serve **any width** by returning a reduced picture instead of raw samples.
- An **overview strip** (whole recording, voltage) above the existing close-up chart, with a
  rectangle showing where the close-up sits.
- **Drag-to-zoom** on either picture, and **Home / ← Back / Forward →** where the slider was.
- Keyboard equivalents and a screen-reader announcement, in the same pass.

**Out:**

- **Spike marks on the strip** — he chose voltage. The strip is a layered canvas so they could be
  added later, but nothing draws them now.
- **Removing the spike ticks under the close-up.** They stay. They are the half that remains correct
  when the waveform does not decode, and he did not ask for them gone (stated to him, uncontradicted).
- **Any change to `MeaTracePanel`** (the video pipeline's electrode panel, the other `TraceChart`
  consumer). It keeps its slider and its own `WINDOW_S`. It also keeps the `jumped`-as-state
  double-fetch bug `MeaTrace` already fixed — **do not fix it as a drive-by**; it has zero test
  coverage, so the fix is unverifiable today. File it as an issue instead.
- **Ctrl+wheel zoom.** Genuinely optional and the only piece that can be cut if the build runs long.
  The bare wheel is never bound — this panel lives in the right rail, the one scroller on the screen
  under R47.1.
- **A numbered BEHAVIOUR ruling.** No ruling covers the MEA screen today and three candidates are
  already waiting unasked (`worklog.md:59-62`). Ask **after** he has used it, with the tool.

## Approach

### 1. The envelope, and why it must be precomputed

MaxWell's HDF5 stores `groups/routed/raw` chunked as `(n_channels, 200)`. Reading **one** channel's
full length therefore decompresses **every** channel over that range. Measured: **14.8 s for one
channel, 19.9 s for all 726.** No reduction helps — this is I/O, not transport.

That single measurement decides the architecture: a per-pad, on-demand whole-recording read is
unaffordable (15 s per click), and an all-channels pass is affordable exactly once. So compute the
envelope for **every channel in one pass** and cache it.

**Format.** For each channel, `B` buckets spanning `[0, duration_s)`, each holding the **min and max**
of the samples inside it. Min/max, never sub-sampling: a spike is 5–16 samples wide at 20 kHz and
stride decimation would drop it and draw a calm line over a burst — the rule
[TraceChart.tsx:17-20](../../../web/src/core/trace/TraceChart.tsx#L17-L20) already states for the
client, now also binding on the server.

`B` is chosen from the file, never written down (I1): enough buckets that the widest useful view has
more buckets than pixels. `B = 8192` with `int16` costs `8192 × 2 × 2 B × n_channels` ≈ **32 MB** for
a 1000-channel recording — the same order as the research's 48 MB estimate. Store the µV scale
factor alongside rather than inflating to float.

**Where.** `<project>/recordings/<id>/envelope.npz`, beside the `data.raw.h5` already there —
following `recordings.py`, **not** `outputs/`. R44: everything Camea writes is inside the project,
and `outputs/` is the user-browsable panel, which a cache is not.

**Health travels with it.** A railed window is indistinguishable from a silent electrode, and the
rail fraction *changes with window length* (measured 1.000 at 1 s, 0.827 at 30 s on 000690). So the
cache stores its own whole-recording health per channel; it may not borrow a window's.

**Files with `n_samples == 0`** (the 7 ActivityScan recordings, currently refused — issue 007) have
no continuous trace at all. Skip them without an envelope and without an error; that is a fact about
the assay, not a failure.

### 2. When it runs — import, and a backfill

**At import**, inside the existing copy path in
[src/camea/features/mea/recordings.py](../../../src/camea/features/mea/recordings.py), as a step
after the file lands. It is where he is already waiting, and it means every pad is instant by the
time he reaches this screen.

**Backfill, and it is not optional** — he asked for it by name. On opening a recording whose
`envelope.npz` is missing or was written by an older format version, build it then, as a
`core.jobs` job (`JobRegistry.submit_thread`, [core/jobs.py:405](../../../src/camea/core/jobs.py#L405))
with progress, not a blocking request. His 5 recordings under `p003658-19cc31` all take this path.

The envelope file carries a **version integer**. A bump rebuilds; it never silently serves a stale
shape.

### 3. The route

Extend the existing trace route rather than adding a second one:

```
GET /api/mea/{analysis_id}/recordings/{recording_id}/trace?channel=&t0=&t1=&max_points=N
```

- **`max_points` absent** → today's behaviour exactly, raw samples, still capped by
  `MAX_TRACE_SECONDS`. Every existing caller and every existing test is untouched.
- **`max_points` present** → the response is a **reduced** picture and the 30 s cap does not apply.
  The server picks its source by width: narrow enough for a cheap live read → read the HDF5 and
  reduce; wider → serve from the cached envelope.

The response gains `resolution: "samples" | "envelope"` and, on the envelope path, `min_uv` / `max_uv`
arrays instead of `trace_uv`. Two arrays, not interleaved pairs — the chart draws them without
re-deriving anything.

⚠️ **The client must label its axis from the returned `t0_s`/`t1_s`, never from what it asked for.**
Asking wider than the cap does not refuse — [routes.py:723](../../../src/camea/features/mea/routes.py#L723)
**silently clamps**, and only an empty or inverted window 422s.

**Free fix, first, before anything leans on it:** `MeaRecording.trace_window(channel, t0, t1)`
returning the µV array **and** the health from **one** read. `trace()`
([mearecording.py:690](../../../src/camea/core/mearecording.py#L690)) and `trace_health()`
([:711](../../../src/camea/core/mearecording.py#L711)) each slice `raw[row, a:b]`
independently and the route calls both — measured 1.05 s + 1.06 s on a 30 s window. Leave both
methods in place for their other callers; switch only `get_mea_channel_trace`.

### 4. The frontend

**`core/trace/viewStack.ts`** — matplotlib's `cbook._Stack`, ported, pure, no React:
`push` truncates the forward branch (typing a new URL after Back); `back`/`forward` clamp and never
wrap; **`home` is itself a push**, so Home is undoable with one Back. Nothing he presses can lose a
place he had.

**`core/trace/useTimeBrush.ts`** — pointer capture; a full-height band, x-only (matplotlib's
`SpanSelector`, not `RectangleSelector` — a box with a height would pretend the voltage axis was
being zoomed too); release within **5 px** of the press is a click, not a zoom, and pushes nothing;
a press starting in the 46 px left number gutter is ignored, because that x is not a time; a stretch
narrower than ~20 stored samples is refused the same way, derived from `sampling_hz` on the payload.

**`features/mea/Overview.tsx`** — the strip. Axis always `0 → duration_s`. Draws the whole-recording
envelope and the current view as a filled rectangle with a **2 px minimum width** so it can never
vanish at deep zoom. No y axis, no gridlines.

**`TraceChart`** gains **optional** `minUv`/`maxUv` props; absent, it behaves exactly as today. Plus
three fixes that help both consumers and change no prop and no drawing: export the padding constants
(the brush needs the same `xOf` inverse), hoist the `syncEpisodes = []` default to a module constant
(it currently mints a fresh array every render, so the dep array never matches and the canvas repaints on
*every* parent render — much worse once a parent re-renders during a drag), and add a
`ResizeObserver` (`clientWidth` is read once inside the effect, so a container resize neither
repaints nor refits — which would leave pointer→time silently wrong).

**`features/mea/MeaTrace.tsx`** — delete `WINDOW_S` and its six uses, the slider, both step buttons
and the `jumped` ref. Add the view stack, the debounced + abortable + sequence-guarded fetch, the nav
row, and the readout. Rewrite the `Panel help=` string — it says *"over a one-second window"* and
*"Use the slider"*, both false the moment this lands.

**The opening view is the whole recording**, in both pictures: the strip's rectangle covers
everything, and shrinks as he zooms. That is the clearest possible teaching of what the strip is
for, and it is literally *"I have the whole trace, and then I make a rectangle around the area I
want to zoom in"*. It also satisfies his **open at the start** answer without a separate rule.
Confirm it in preview; it is the one choice made for him rather than by him.

**Keyboard, same pass, not a follow-up.** ←/→ slide by half a width; `+`/`-` widen/narrow about the
centre (the house meanings, R12.6/R13.7 — not a third vocabulary); `Backspace` = Back. `Esc` cancels
a drag in flight **and nothing else**, scoped the way R45.3 scoped Esc; R14 is untouched. `0` is
deliberately not taken — it means 1:1 in the viewer and 1:1 has no meaning on a time axis. A visually
hidden `role="status"` region announces each new range. This app has shipped a keyboard-dead canvas
once and review caught a second; it does not get deferred.

## Rulings this touches

- **R3.8 / R47.7 — warnings about his data stay on the page, never behind the `?`.** Upheld, and it
  is *why* there are two pictures. The "did not decode" warning is driven by `data.health?.flat`
  ([MeaTrace.tsx:110](../../../web/src/features/mea/MeaTrace.tsx#L110)), and health only exists for a
  window actually read. A design that showed the whole recording with no close-up fetched would have
  `health == null` and **silently stop warning him** — an honesty regression, not a red test. Two
  pictures means a close-up is always open, so the warning always has something to say. On the
  envelope path the cache supplies its own health, so this holds at every zoom level.
- **R44 — everything Camea writes goes inside the project.** Upheld. `envelope.npz` sits at
  `<project>/recordings/<id>/`, never in `outputs/`, never outside the project.
- **R47.1 — the rail is the only scroller.** Upheld: the panel grows taller (his answer) and the bare
  wheel is not bound.
- **R7 — a new mode control earns a `?`.** No mode is added; drag-to-zoom is always on. Nav buttons
  are navigation, not a mode, and `Fit`/`1:1` are already exempt under R7.6.
- **R12.6 / R13.7 — `+`/`-` are zoom.** Upheld by reusing them rather than inventing keys.
- **R45.3 — `Esc` is scoped explicitly.** Followed: `Esc` cancels a drag and nothing else. **R14 is
  untouched** — Esc must still not kill the sweep.
- **I1 — no dataset knowledge.** Every number comes from the payload: bucket count from
  `duration_s`/`sampling_hz`, the zoom floor from `sampling_hz`, the raw-sample ceiling from
  `max_window_s`. Nothing hard-codes 20 kHz, 300 s, 1024 channels, or a bucket count.

**No ruling changes, and no new one is minted here.** Ask him after he has used it.

## Affected

- `src/camea/core/mearecording.py` — `trace_window()` (one read, not two); the envelope builder;
  envelope read-back. ⚠️ It is **`core/`, not `features/mea/`** — shared with the videomosaic
  electrode panel, so every addition here is additive and nothing existing changes signature.
- `src/camea/features/mea/recordings.py` — build the envelope at import; detect a missing/stale one.
- `src/camea/features/mea/routes.py` — `max_points` on the trace route; the envelope source; the
  backfill job. `MAX_TRACE_SECONDS` unchanged.
- `src/camea/api/schemas.py` — `resolution`, `min_uv`, `max_uv`, `max_window_s` on `MeaChannelTrace`.
- `docs/openapi.json`, `web/src/api/schema.d.ts` — **regenerated, never hand-edited**.
- `web/src/core/trace/viewStack.ts`, `useTimeBrush.ts` — new, pure, unit-tested.
- `web/src/core/trace/TraceChart.tsx` — optional envelope props + three inert fixes.
- `web/src/features/mea/Overview.tsx` — new.
- `web/src/features/mea/MeaTrace.tsx` — the bottom half rewritten.
- `web/tests/e2e/pages.ts`, `analyze-mea.spec.ts` — testids and five new cases.
- `docs/API.md`, `docs/MAXWELL.md` — the route, and the §6 correction below.

⛔ **Not touched:** `src/camea/engine/*` · `tests/slow/test_solver_312.py` ·
`src/camea/features/videomosaic/routes.py` · `web/src/features/electrodes/MeaTracePanel.tsx`.

## Done when

- [x] Clicking a pad shows the **whole recording's voltage** in both pictures, with no wait.
- [x] Dragging sideways on **either** picture zooms the close-up to that stretch; the strip's
      rectangle shrinks to match. *(Both drivable in a browser; e2e covers the close-up.)*
- [x] A drag wider than 30 s **works** and is not clamped or trimmed. *(A 45 s recording comes back
      whole with `t1_s > MAX_TRACE_SECONDS` — `tests/api/test_mea_feature.py`.)*
- [x] `← Back` returns to the previous view; `Forward →` returns to the one after; zooming after a
      Back clears the forward history; `Home` returns to the whole recording and is itself undoable
      with one Back. *(21 unit cases + 3 e2e; browser: 180 → 45 → 5.4 → 0.65 s, Home, Back → 0.65 s.)*
- [x] A click (release < 5 px from press) changes nothing and adds no history entry.
- [x] The slider, both step buttons and `WINDOW_S` are gone from `MeaTrace.tsx`.
- [x] The panel opens at the **start** of the recording — no jump to the first spike. *(e2e asserts
      the readout begins `0.00–`.)*
- [x] The five recordings under `p003658-19cc31` get envelopes **without being re-imported**, and
      the job reports progress rather than blocking. *(Run for real, 2026-08-15: all five ready,
      23.8–33.3 MB each.)*
- [x] A newly imported recording has its envelope before the screen is first opened.
- [x] The "did not decode" warning still appears immediately on a railed pad, on the page, at
      **every** zoom level. *(Driven on 000691: present at 300 s, 60 s, 9 s and 0.63 s, as a
      `role="status"` with no buttons inside.)*
- [x] The spike ticks still draw at full strength under the close-up when the waveform is dimmed.
- [x] Every control is reachable and operable by keyboard, and each new range is announced.
- [x] `MeaTracePanel` and the videomosaic electrodes screen are visually unchanged. *(Comment-only
      edit; every new `TraceChart` prop optional. ⚠️ One knowing exception, recorded in that file's
      header: the spike-density switch is not gated behind a prop and can reach it.)*

## Verify

```bash
uv run ruff check . && uv run mypy
uv run pytest -q -m "not slow"
node scripts/check-links.js && node scripts/check-engine.js
cd web && npm run lint && npx tsc -b --noEmit && npm test && npm run check:api
cd web && npm run e2e
```

Then **run the app and drive it** (`needs: dev server`): open `p003658-19cc31`, watch the backfill,
click a pad, drag, Back, Home. Look at the videomosaic electrodes screen too — it is the other
`TraceChart` consumer and **nothing would catch a regression there**.

`needs:` is not `engine`; the 312/312 guard is not owed. Nothing here goes near `src/camea/engine/`.

## Deploy

Nothing — this lands on `master` and that is all.

**Ordering:** none. It depends on no other plan and blocks none.

## Roll back

`git revert` returns the code. Two things it does not undo:

- **`envelope.npz` files written beside imported recordings.** They are a **cache, not data** — a
  reverted build simply ignores them, and the old code never looks for them. Safe to delete by hand;
  nothing a user authored is in there. No saved project's shape changes: `document.camea.json` is
  not touched, and no verified anchor is at risk.
- **Nothing in the engine**, so nothing to re-run.

## Open — both closed during the build

- [x] **Does the taller panel actually fit?** **Yes — measured, not guessed.** At 1900×1000,
      1500×800, 1280×720 and 1100×650 the nav row is fully inside the viewport, the rail is not
      clipped (`scrollHeight === clientHeight`) and the document does not scroll. His "let it be
      taller" holds and the facts row does **not** need folding. R47.1 intact.
- [x] **`docs/MAXWELL.md` §6 overstates the decode failure.** Confirmed and corrected (`0100e25`) —
      and the plan's own figure was wrong too. Measured exactly, per channel, over the whole of each
      of his five: 000690/691/692 rail at 96.5 / 100 / 93.9 %, while **000688 (1.1 %) and 000689
      (4.4 %) decode cleanly**. Corrected in `MAXWELL.md`, `core/mearecording.py`'s header,
      `api/schemas.py`'s contract note and `MeaTracePanel.tsx`'s header.

## What the review found — six real defects, all fixed before close-out

Four guards ran. `dataset-knowledge-guard` was clean. The rest:

| # | Found by | Defect |
|---|---|---|
| 1 | api-contract | A **corrupt envelope cache raised a 500.** `load_envelope` caught three exception types; a file truncated mid-write makes numpy raise `zipfile.BadZipFile`, a plain `Exception`. Now catches `Exception`, verified against truncated/garbage/empty/missing/directory. |
| 2 | api-contract | **"Read it now" never noticed the job finished** — the POST returns on submit, so the button looked done while the read had barely started, and a minute later the panel still said "not read yet". Now polls and refetches. |
| 3 | api-contract | `resolution` unset on the `RawUndecodable` arm — reported `samples` for an envelope request. |
| 4 | api-contract | `MeaEnvelopeStatus.started` claimed more than it did. Reworded. |
| 5 | frontend | **The strip repainted on every parent render**, including every pointermove of a drag on the *other* chart — the exact defect `TraceChart` records fixing for its own default, reintroduced one level up. |
| 6 | frontend | **A boundary keypress pushed a duplicate view.** `vs.push` always returns a new stack, so the no-op guard never fired; ArrowLeft on the opening view lit up Back and fetched the identical window. |

The e2e suite separately caught **two more** in already-committed code: a duplicate
`data-testid="mea-trace-chart"` (two mounts, strict-mode failure — two *pre-existing* assertions
were already red), and the strip announcing **"0 spikes"** for a pad that fired 1,166 times.

And the API tests caught the last one: the decode warning said *"N% of this recording"* while
quoting a **window's** figure on the live path. `health_scope` now travels with the payload and the
sentence names what it measured.

## Not built, and why

- **No e2e for the envelope-cache path or the "Read it now" button.** The committed fixture is 3.0 s
  at 20 kHz — always inside `LIVE_READ_MAX_SAMPLES`, so the cache is never consulted and the 409
  never fires. Covered in `tests/api/` instead, where the recording can be made big enough.
- **No test for the `RawUndecodable` arm.** The synthetic fixture's raw stream reads back as zeros
  rather than raising; a real undecodable stream needs a real MaxWell file.
- **The `MeaTracePanel` double-fetch bug is still there**, untouched and deliberately so — it has no
  coverage, so a fix is unverifiable today. Worth an issue.

## To ask him, now he can use it

1. **Does any of this earn a numbered BEHAVIOUR ruling?** No ruling covers the MEA screen at all,
   and three candidates already sit unasked (`worklog.md:59-62`). The two new testable patterns here
   are (a) Home being a *push* so it is undoable with one Back, and (b) drag-to-zoom with a 5 px
   click threshold that pushes no history. ⛔ Ask with the tool; never mint one unilaterally.
2. **The close-up opens showing the whole recording** — the one choice made *for* him.
