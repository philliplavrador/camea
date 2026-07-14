# BEHAVIOUR.md — the contract for the frontend rewrite

> **What this is.** The v1 frontend (`archive/app-v1/frontend/`) is being thrown away and rewritten in
> TypeScript/React. Everything in this file is a behaviour the user *paid for* — most of them with a
> day of his own testing, several with a benchmark he destroyed and had to rebuild. Every statement in
> §1 is phrased so that it **can fail**. They become Playwright tests.
>
> **How to use it.** Do not read this as background. Read it as a test list. If a line here is not
> true of the new frontend, the new frontend is wrong — even if it "looks fine", *especially* if it
> looks fine. Half the bugs below typechecked perfectly and were only caught by driving the real app.
>
> **Citations** are to the archived v1 tree, which is READ-ONLY. Cite them; never edit them.
> Paths are repo-relative from `d:\Projects\Camea`.

**Sources, read in full:** `archive/app-v1/FIXES.md` (the fix queue — 13 numbered rulings across three
"update app" passes, all shipped), `archive/app-v1/frontend/sweep.js` (3507 lines — the app's logic),
`archive/app-v1/frontend/viewer.js` (1325 lines — canvas/camera/selection),
`archive/app-v1/frontend/index.html` (603 lines — the six-step DOM),
`archive/app-v1/frontend/style.css`, `archive/app-v1/API.md` (the backend contract — **stale in
places, flagged inline below**), `archive/app-v1/SPEED.md`, `archive/app-v1/SCALE.md`.

---

## 0. THE THREE INVARIANTS THAT OUTRANK EVERYTHING ELSE

If a design decision in the rewrite collides with one of these, the design decision loses.

**I1. THE APP KNOWS NOTHING ABOUT ANY DATASET.** No exclusion list, no ruling, no "is this 260620d?"
detection, no auto-exclude — not even from the blank scan, which only *recommends*. The only things
that ever exclude a frame are (a) the human, in this session, and (b) a project file he loaded.
There is **no toggle**. *(FIXES.md ruling 2; sweep.js:12-19, 412-416, 455-459.)*

**I2. THE APP IS A TOOL, NOT AN EXPLAINER.** Every explanation lives behind a hover `?`. The page
shows the number, the label, the button. **The one exception is a LIVE WARNING ABOUT CURRENT STATE**
— see §5, which lists them exhaustively. *(FIXES.md ruling 3; sweep.js:21-31; style.css:380-387.)*

**I3. NOTHING IS EVER AUTO-ANCHORED.** Anchoring is the user pressing `A`. Not a build, not a
confident match, not a "high NCC" heuristic. Everything the machine places lands `unverified`.
*(sweep.js:118-122, 2890.)*

---

## 1. THE RULINGS

### R1 — The `.warn` banner must lay out as prose, not as flex items
**Statement that can fail:** A multi-sentence `.warn` banner containing inline `<b>` tags renders as
one flowing paragraph, not as separate boxed columns with gutters between the words.

**Why it exists.** `.warn { display: flex; gap: 8px }` made every child — including bare text nodes
between `<b>` tags — its own flex item with an 8 px gutter, so the "What was detected" banner read as
`Both rules below are` | `measured` | `, and both are validated on` | `n = 1 dataset` | `. Check them…`,
each in its own column, wrapping independently. Fixed to `display: block`.
*(FIXES.md #1; style.css:387-388, which now carries the comment "PROSE: it is `display: block`".)*

**Rewrite note.** Trivial in CSS-in-JS/Tailwind, but the *class of bug* is the point: a warning
component that an icon-slot design turns into a flex row will re-break it. If a `.warn` needs an icon,
wrap the text in a span — do not make the container flex.

---

### R2 — ⭐ THE APP CARRIES NO DATASET KNOWLEDGE. Exclusions live in the project file.
**His words, verbatim (2026-07-14):** *"I want the app to only remember data if I upload its like save
file for this run… it can also have the exclusions and everything. There should be no toggle. The app
itself shouldn't store the exclusions for this experiment."*

**Statements that can fail:**
- R2.1 Opening `260620d` fresh loads **338 of 338** trials in 11–348, with **0 excluded**. Trial 284
  is present, is `unplaced`, and is *not* auto-excluded.
- R2.2 The Load/Range screen never says "312 usable of 338 (26 thrown out)". There is no such line and
  no such number. *(sweep.js:2373-2376.)*
- R2.3 The Gaps field reads **none** on a fresh open, and only grows gaps when the *user* excludes
  something. *(sweep.js:596-602, 1702-1705.)*
- R2.4 A saved project file contains **no `EXCLUDED_TRIALS` block**. Loading an old file that has one
  and re-saving it **deletes** it — it must not be resurrected. *(sweep.js:1533-1538.)*
- R2.5 The **only** thing the app may import from the exclusion module is `gaps()` — a pure function
  over an arbitrary trial list. Never `EXCLUDED` / `BLANK` / `BLURRY` / `usable_trials`.
  *(FIXES.md #2; CLAUDE.md standing rule.)*
- R2.6 Saving, closing the app (kill the server), and loading the project file back restores:
  exclusions, every placement, which tiles were anchored, the cursor, and the build. Verified cold:
  toast reads *"Resumed — 1 anchored, 1 excluded."* and the cursor lands back on the trial he was on.
  *(FIXES.md:42; sweep.js:3181-3241.)*

**What broke.** The app hard-coded *his* answer to the exact question it exists to help him answer.
Opening his one dataset removed 26 frames before he had seen one, so the Screen step and `E` — the
whole point of the app — were short-circuited. He was testing it as a first-time user and could not.

**Expect the fresh-user build to be WORSE, and that is correct.** With the 26 back in the input the
solve degrades (the measured 19.2 % → 37.2 % effect, running backwards). He must be able to *see* it
being worse, exclude the blanks at Screen, `E` the blurry ones in the sweep, and rebuild.

---

### R3 — ⭐ STRIP THE PROSE. Explanations go behind a hover `?`.
**His words:** *"there's way too much information being presented on every single widget and page…
make it like a normal app with the buttons, where they expect the user to know what's going on — but
wherever it's important or helpful, have a little hover question mark… Assume the user knows. If they
don't, they have the option to hover."*

**Statements that can fail:**
- R3.1 No screen renders an explanatory *paragraph*. The page shows numbers, labels and controls.
- R3.2 There is exactly **one** help component, used everywhere: a 14 px muted circle whose body is a
  tooltip. Keyboard-focusable (`tabindex=0`), dismissed on blur and on `Escape`.
  *(style.css:419-442; sweep.js `Help`, 335-404.)*
- R3.3 A `?` with an **empty** body **hides itself** — a `?` never promises an explanation it cannot
  give. *(style.css:442; sweep.js:358.)*
- R3.4 The tooltip is **body-level and `position: fixed`**, by necessity: every pane and rail is
  `overflow: auto` and a bubble nested inside one is *clipped at the pane's edge*.
  *(sweep.js:333-334; index.html:596-597.)*
- R3.5 The tooltip hides on scroll — listener registered in the **capture** phase, because a scroll
  inside an `overflow:auto` pane does not bubble to `window`. *(sweep.js:382-385.)*
- R3.6 One **delegated** listener per event, never a per-node bind: the rails and the Screen card list
  are re-rendered constantly, so any `?` may be destroyed and rebuilt under your feet.
  *(sweep.js:331-333, 373-387.)*
- R3.7 Tooltip bodies are set as **text**, not HTML — a body can be a backend-measured `why` string,
  and a `"` in it would break out of an HTML attribute and mangle the page. `\n` is a real line break
  (`white-space: pre-wrap`). *(sweep.js:360-362, 2428-2431.)*
- R3.8 🔴 **THE ONE EXCEPTION — see §5.** A live warning about current state is not an explanation. It
  stays on the page.

---

### R4 — ⭐ ONE QUESTION PER SCREEN. Six steps, in order.
**His words:** *"make it more intuitive by making it more step by step. like first load the data. then
give the user a concise numerical data summary. then have the user select what snapshot range they
want. then tell them about recommended exclusions. then have them run the algorithm. then have them
build the mosaic."*

**Statements that can fail:**
- R4.1 The six steps are exactly **Load · Range · Screen · Place · Sweep · Mosaic**, in that order.
- R4.2 The step header is a **progress indicator, not a menu**: a step is *locked* until everything
  before it is ready, and clicking a locked step toasts *"Finish the step before it first."* and does
  nothing. *(sweep.js:2149-2194.)*
- R4.3 The gate function, exactly (sweep.js:2158-2173):
  - `load` / `range` / `screen` / `place` are ready iff **a session exists**.
  - `sweep` is ready iff **something has a position** (`anyPlaced()`).
  - `mosaic` is `true`.
  - Consequence, and get this right: **with a session but nothing placed, `sweep` is REACHABLE and
    `mosaic` is LOCKED.** (`unlockedThrough()` returns 4; `isLocked(name) = index > 4`.)
- R4.4 ⚠️ **Do not invent gates the workflow does not have.** There is no gate on "did he tick a
  Screen box" or "did he run the solver" — *not* ticking and *not* solving are both legitimate
  answers, and `Skip — place by hand` goes straight to a hand-placed sweep. A wizard that locks a step
  he is entitled to reach is worse than one that locks nothing. *(sweep.js:2152-2156.)*
- R4.5 Opening a directory **navigates to Range**. It does not reveal a result block in place. There
  is no `#load-result`. *(sweep.js:2403-2406, 3287.)*
- R4.6 The numeric summary is a facts strip: **Trials · Range · Pass split · Gaps**. Numbers only;
  every explanation behind its `?`. *(index.html:290-310.)*
- R4.7 The sweep is **not a pane** — it IS the stage (the canvas plus both rails). The other five
  screens are panes that cover the stage and hide the rails. *(sweep.js:2189-2215.)*
- R4.8 When a pane is showing, the stage's **overlays** (banner, the A/E/Space cluster, the camera and
  undo buttons) must be hidden too. Hiding the rails is not enough: the overlays sit at z-index 4 and
  the panes at 3, so without this they float on top of Load/Range/Screen/Place/Mosaic, obscure the
  text and swallow clicks in the corners. *(sweep.js:2207-2210; index.html:18-20.)*

---

### R5 — Save must be reachable from EVERY screen.
**His words:** *"make it so at any time in the process I can export the save file so I can resume
later."*

**Statements that can fail:**
- R5.1 `Save…` lives in the **top bar** and is visible and functional on all six steps.
  *(index.html:115.)*
- R5.2 `Ctrl+S` saves **from any screen** — it is handled *above* the `screen !== 'sweep'` gate in the
  key handler. An hour into a sweep is exactly when he wants it. *(sweep.js:1630-1634.)*
- R5.3 `Load a project…` lives on the **Load** screen, not on Mosaic — resuming is a way of *starting*.
  *(index.html:277.)*
- R5.4 The rolling **autosave** is separate, stays on Mosaic, and must not read as the same thing. It
  is a crash net; `Save…` is a file he controls. *(index.html:508-509.)*

**Why it matters more than it looks.** Since R2 the project file is the app's *only* memory. Burying
it behind the last step meant the one artefact that makes a session resumable was the one thing he
could not reach mid-session.

---

### R6 — The Screen step is ONE control with THREE buttons, not two checkboxes
**His words:** *"I want a keep button, an exclude button, and a hand place button."* — prompted by his
own question, *"what does `score it` mean?"*, which **is** the bug: the control could not be understood
from the page.

**Statements that can fail:**
- R6.1 Each scanned frame's card carries exactly three mutually-exclusive buttons —
  **`Keep` · `Hand place` · `Exclude`** — with **exactly one selected**. *(sweep.js:2543-2560;
  style.css:507-523.)*
- R6.2 **`Hand place` is the DEFAULT** on a scanned frame. That is the app saying *"I don't trust
  myself on this one — you do it"*, which is honest and is the whole reason the scan **recommends**
  rather than deletes. *(sweep.js:2551 — `// 🔴 HAND is the default. Deliberate.`)*
- R6.3 Semantics, unchanged from the checkbox era (this was a re-shaping, not new behaviour):

  | button | in the mosaic? | matcher places it? | mechanism |
  |---|---|---|---|
  | **Keep** | yes | **yes** | lifts the refusal (`PUT /api/scan/blank`) |
  | **Hand place** | yes | **no** — he positions it in the sweep, or it sits at the solver's guess | stays refused |
  | **Exclude** | **no** | — | tile state → `excluded` |

- R6.4 🔴 **THE TWO MECHANISMS STAY SEPARATE.** `Keep`/`Hand place` drives the **refusal list**;
  `Exclude` drives the **tile state**. Conflating them once silently lifted the refusal on **trial
  127** — the one frame in the list that genuinely misleads the matcher (**679 px out at NCC 0.66**).
  One control now drives both, but it still drives them as *two*. *(sweep.js:2537-2541.)*
- R6.5 The choice **applies immediately**. There is no Apply button and nothing to forget to press.
  *(sweep.js:2512-2516, 2562-2608.)*
- R6.6 🔴 **THE CARD MUST RE-DERIVE FROM LIVE STATE EVERY TIME HE ARRIVES ON THE SCREEN.** `show()`
  did not re-render the list, so pressing `E` on a scanned frame **in the sweep** left its card still
  reading `Hand place` for a frame that was by then **excluded** (measured: tile 289
  `status: "excluded"`, card `checked: "hand"`). This is *worse* than the old checkboxes — a checkbox
  only claimed to be a **request**; this control claims to be **the state**. Undo and resume have the
  same hole. *(sweep.js:2216-2228, 2545-2552; FIXES.md:76-80.)*
- R6.7 The refusal **must reach the server on every path out of the screen** — on any choice, and on
  the way to Place. `"Place the tiles →"` used to walk straight past it, so the raw scan governed the
  matcher for the whole session with no UI trace. *(sweep.js:2618-2622, 3374-3377.)*
- R6.8 The word **"refuse" / "refusal" is engine vocabulary and has left the UI.** The buttons are
  named after *his intent*, not the matcher's mechanism. (It survives in the evidence rail's `REFUSED`
  warning, which is a live warning about a fact, not a control — see §5.)

**R6b — The bulk buttons are GONE.** `Tick all` / `Tick none` / `Exclude the ticked` are deleted, as
is `applyBlank()`. They only ever drove the `exclude` box, they have no meaning for a three-way
selector, and **every flagged frame is meant to be LOOKED AT before it is judged** — which is the
entire point of the Screen step. 15 cards is few enough to decide one at a time.
🔴 **Do not bring back a bulk exclude.** A pre-ticked box under a primary button reading "Exclude the
ticked" **is** an auto-exclude: on 260620d the scan names 34, 55, 56 and 127, and **all four are
anchors in the hand-authored ground truth of the 100 %-solved pass 1**. One click once threw away four
tiles of real tissue. *(sweep.js:2673-2686; index.html:333-338.)*

---

### R7 — Every control that is not self-evident carries its own `?`
**His words** — after asking what `use cache` does, the *second* control in a row he had to ask about.
Ruling 3 moved every paragraph behind a `?` but never checked that every **control** has one. A control
with no explanation on the page **and** no `?` is the gap: he cannot find out what it does at all,
short of asking.

**Statements that can fail:**
- R7.1 **All seven sweep buttons carry a `?`**: `Anchor A` · `Exclude E` · `Next Space` · `Replay R` ·
  `Difference D` · `Alternatives V` · `Snap S`. All seven shipped **bare**, on the one screen he spends
  the hour in, and `Difference`, `Alternatives` and `Snap` are the least guessable controls in the app.
  *(index.html:219-239.)*
- R7.2 `use cache` carries a `?` saying it is a **speed** switch, not a correctness one: warm ≈ 25 s
  vs cold ≈ 3 min; t33's cache filename carries a hash of the **trial list + config** and a mismatch is
  **refused, not repaired** — so it cannot serve a stale answer for a different input.
  *(index.html:386-388.)*
- R7.3 The Tone controls (`tone-lo` / `tone-hi` / Apply / Auto) carry `?`s, and they say the tone
  window is **display only** and never touches the matcher. *(index.html:169-178.)*
- R7.4 Each Advanced knob (`pass_split`, `anchor_ncc`, `split_px`, `look`, `min_side`, `t27.conf`,
  `t27.run_conf`) carries **its own** `?`, and the drawer itself says *"Off the validated path. The
  shipped 312/312 build used the defaults."* *(index.html:437-464.)*
- R7.5 ⚠️ **Do not audit this with a proximity scan.** The v1 audit found "65 interactive controls, 25
  with no `?`" and the raw count *understated* it — proximity gives **false passes** (`in-usecache`
  looked covered only because the `?` on the adjacent `Skip` button was within range). Check each
  control's **own** label.
- R7.6 Explicitly **FINE without a `?` — do not add noise**: the six wizard step buttons, `Fit`, `1:1`,
  the export directory field, its Browse button, and the basename field. These say what they do.
- R7.7 The audit must cover **JS-built** controls too, not just static markup — the Screen cards and
  the evidence rail are built in JS.

---

### R8 — Step 4 · Place — the ETA counts down every second. It must never freeze.
**His words:** *"upgrade the progress bar. make it constantly update the time remaining."*

**Statements that can fail:**
- R8.1 During a build the ETA text changes **every second** (`2m 06s → 2m 05s → 2m 04s …`). It is never
  frozen for more than ~2 s. *(Measured after the fix: longest frozen stretch 9 s → 2 s; distinct
  values while counting 7/30 → 30/35.)*
- R8.2 🔴 **RE-ANCHOR ONLY WHEN THE SERVER'S VALUE ACTUALLY CHANGES.** The poll fires every 500 ms
  with a job object that carries the *last* `eta_s` — the same number over and over until the child
  next prints. Re-anchoring on every tick resets the clock, `left` recomputes to the same number
  forever, and **the countdown never moves.** This bug was introduced *while fixing the original bug*
  and reproduced it one layer up. Compare against the **raw server number**, not against what you
  render. *(sweep.js:2841-2855, `etaSync`; FIXES.md:71-75.)*
- R8.3 Clamp at **0**. Below ~1 s left, show `almost there…` — never `-437 s left`, which reads as a
  hang, the exact failure this mechanism exists to prevent. *(sweep.js:2857-2865.)*
- R8.4 An **upward jump is honest and is allowed.** When a long-silent phase finally reports, the true
  estimate may be *worse*. Take the server's number. A smooth lie is worse than a visible correction.
- R8.5 The progress bar itself glides (`transition: width`), it does not step. *(style.css:526.)*
- R8.6 Format: `901 → "15m 01s"`, `47 → "47 s"`. Minutes matter on the CPU path; seconds on the GPU.
  *(sweep.js:2867-2874.)*
- R8.7 The log tail shows the **last 8 lines** of the job's narration. *(sweep.js:2780.)*

**Why the number was frozen, not slow.** The frontend already polled at 500 ms and dutifully re-rendered
`job.eta_s` — but `eta_s` is only **recomputed when the child process prints a recognised stdout line**.
His own screenshot is the proof: `[swim] 12,090 pairs in 205.9s (CPU)` is **one line, emitted after
205.9 s of total silence.** Nothing on screen could move during it.

⚠️ **R8b — the BACKEND half is deliberately NOT done, and must stay not-done until the estimator is
fixed.** A heartbeat would make it *worse*: `eta = elapsed * (100 - pct) / pct`, so during a silent
phase `pct` is pinned and re-emitting with a growing `elapsed` makes the ETA **count UP**. It is only
safe once the global linear extrapolation is replaced by a phase-weighted one — which must be
re-driven on the ~10-minute CPU path. **Do not add a heartbeat as a "nice fix".**

🔴 **And do not regress what this machinery already fixed:** `pass1` and `backbone` once emitted no
`frac` at all, so `pct` was pinned and `eta_s` was `None`. On the **CPU-only path — the default
install — the bar sat at 0.0 %, with no ETA, for 3 min 40 s**, with a Cancel button to hand. *"A
lab-mate who cancels that has cancelled a build that would have produced 312/312."*

---

### R9 — ⭐ THE SWEEP DRAWS ONLY WHAT HE HAS CERTIFIED. The canvas starts EMPTY.
**His words:** *"the yellow boxes make it really hard to see anything… when i begin placing tiles i
want none of the tiles placed and only tiles that i anchor get placed so it should start with 0 tiles
placed then i add tile 11 and anchor it, then i move onto 12 and if its good i anchor it."*

**🔴 THIS IS NOT A DECLUTTER. THE DISPLAY WAS LYING ABOUT WHAT THE SWEEP DOES.** The matcher matches
against **anchors only** (`anchors: anchored()`), so with nothing anchored the reference field is
**EMPTY** — yet the canvas showed him **338 tiles**. His header read `0 anchored · 338 unverified`.
The picture and the algorithm were telling him different stories, and the picture was the confident
one. And the two complaints are **one complaint**: the yellow dashed boxes **ARE** the unverified
tiles — the outline code outlines *only* `unverified` ones. Draw only what he certified and the cage
disappears on its own.

**The model, made exact:**
```
canvas = [ the anchors he has certified ]  +  [ the ONE tile under judgement ]

  start      : EMPTY. 0 tiles drawn.
  trial 11   : fades in over nothing.  A -> field = {11}
  trial 12   : fades in ON TOP OF {11}. A -> field = {11,12}
  trial 13   : Space (unsure)          -> 13 is NOT drawn. It keeps its machine position.
  trial 14   : fades in on top of {11,12}
```

**Statements that can fail:**
- R9.1 With 0 anchored, the sweep canvas draws **nothing** except the one floating tile under
  judgement. **No yellow cage.** *(Measured: `anchorLayerDrawn: 0`.)*
- R9.2 `A` bakes the tile into the anchor layer; the next `Space` fades the next tile in **on top of
  it**. After 10 anchors, `anchorLayerDrawn: 10`.
- R9.3 The unverified layer is **still maintained** (a tile can be anchored later, and un-anchoring
  puts one back) — it is only **NOT DRAWN**. *(viewer.js:140-142, 651.)*
- R9.4 The switch is **one flag, default OFF for the sweep, and there is no toggle unless he asks.**
  *(viewer.js:1310-1312 `setShowUnverified`; sweep.js:2295-2307.)*
- R9.5 The dashed outlines are gated on the **same** flag: outlining an invisible layer would leave
  dashed rectangles floating over *nothing* — the cage, minus the mosaic. *(viewer.js:717-721.)*
- R9.6 ⚠️ **The fade must keep working.** The cursor is a *float*, not a layer member, so it is
  untouched by this — but **drive it and confirm**, because the fade is the heart of the app.

**⭐ The app already believed his rule — in Difference mode.** viewer.js:643-648 already says the
destination *must* be the anchor field alone. The normal view simply did not follow it.

**R9b — `Space` still records the machine's position.** *(Same breath; asked and confirmed.)* Deferring
keeps the solver's answer and the tile stays `unverified` — it is simply **not in the reference field
and not drawn**. This preserves his 2026-07-12 ruling (*"Space ALWAYS places it"*) and means nothing is
lost if he never returns: the Mosaic step's **`include unverified`** checkbox can still put those tiles
in the final image. **Deferring must never destroy tissue.** *(sweep.js:1061-1067; FIXES.md:185-189.)*

---

### R10 — ⭐ THE ANCHORS BLEND INTO EACH OTHER.
**His words:** *"as i confirm anchor i want anchors to blend together."*

Follows straight from R9: once the canvas shows **only** what he has certified, that canvas **is** his
mosaic-in-progress — so it should look like one, not like a stack of pasted rectangles. The export has
feathered all along (`analysis/mosaic/render.py`); **the mosaic he ships was seamless and the one he was
building was not.**

**Statements that can fail:**
- R10.1 The certified field renders as a **continuous strip** — no hard rectangular seams between
  anchored tiles. *(Measured on 10 anchors.)*
- R10.2 The floating tile under judgement stays **crisp**. ⚠️ **DO NOT FEATHER IT.** Softening the very
  tile he is inspecting would blur the misalignment he is looking for. **Feather the CERTIFIED FIELD;
  leave the candidate crisp. Layers feather; floats do not. That is the whole rule.**
  *(viewer.js:222-224.)*
- R10.3 The implementation is a **pre-baked alpha ramp** (cosine falloff over the outer 40 px of 512,
  separable — the same shape `render.py` uses), multiplied into the tile's bitmap on a **reused scratch
  canvas**, so a layer bake is still exactly **one `drawImage` per tile**. *(viewer.js:226-271, 300-315.)*
- R10.4 🔴 **DO NOT ACCUMULATE A WEIGHT BUFFER PER FRAME.** A true normalised weighted mean
  (`Σ w·I / Σ w`) needs a second accumulation buffer and a per-frame divide, and it **will** break the
  frame budget. The naive path measured **89.5 ms/frame = 10 fps** — *"the 1-second fade would be a
  SLIDESHOW."* The frame stays: `fill + drawImage(L_anchor) + one floating tile + chrome`.
  *(viewer.js:212-215; SPEED.md.)*
- R10.5 The **removal / un-anchor repair path must feather too**, or the patched rect comes back with
  hard edges while the rest of the field is blended — a visible bright seam exactly where a tile was
  just removed. *(viewer.js:341-344.)*

⚠️ **CAVEAT THAT CHANGES WHAT HE SHOULD TRUST.** Pre-multiplied alpha under `source-over` is **not**
the export's normalised feather: where many tiles overlap, alpha compounds and brightness drifts from
the final render (260620d averages **10.89 deep, max 31**). **The live view is a faithful guide to
GEOMETRY, not to PHOTOMETRY.** Say so. **Judge alignment in the sweep; judge tone on the Mosaic step.**
A tile with nothing under it also keeps a soft dark rim (only 4.8 % of the canvas is depth-1) — which
is why the ramp is narrow.

---

### R11 — `A` on an already-anchored tile UN-ANCHORS it. `A` is a toggle.
**His words:** *"if i click a on a snapshot that is already anchored i want it to unanchor it."*

It used to be a **silent no-op**, and there was **no way to take an anchor back** except `Ctrl+Z`, and
only if it was the last thing he did.

**The model.** `A` toggles CERTIFICATION, not position:
```
unverified --A--> anchored     certify it, at the position it is at
anchored   --A--> unverified   un-certify it. IT KEEPS ITS POSITION.
```

**Statements that can fail:**
- R11.1 `A` on an `anchored` tile makes it `unverified` and **keeps its position**. Not `unplaced` —
  un-certifying must never throw away a position. *(sweep.js:899-914, 924-925.)*
  *(Measured: 16 `anchor` → `unverified`, position kept at (1, 733); 10 anchored → 9.)*
- R11.2 It **vanishes from the canvas**, because the canvas draws only the certified field (R9). That
  is the feedback.
- R11.3 🔴 **UN-ANCHORING MARKS DOWNSTREAM TILES STALE.** Every tile judged *after* this one was matched
  against a composite that **contained** it. Same rule as excluding an anchor, same rule as moving one.
  Banner: *"Un-anchored 16. It keeps its position. **5 tiles flagged stale** — they were matched against
  a field that contained it."* *(sweep.js:906-913, `markStaleAfter`.)*
  - *Self-limiting in the common case:* un-anchoring the tile he **just** anchored has the highest
    `seq`, so nothing is flagged. The cascade only fires when he reaches back to an **early** anchor —
    which is precisely when he needs to be told.
- R11.4 ⚠️ **THE ORIGIN TRAP — DO NOT LET HIM STRAND HIMSELF.** If he un-anchors down to **zero
  anchors**, `A` on a *positionless* tile must still be able to re-establish an origin. The old code
  took the `!anyPlaced()` branch only if *nothing* was placed at all — but the un-anchored tile still
  holds its position, so `anyPlaced()` was true, it fell through to a match, got `refused: no_anchors`,
  and **there was no way back**. The shipped fix: a loud toast that names *both* exits — *"press A on a
  tile that already has a position to certify it, or drag this one into place, then A"* — plus a live
  warning the moment the anchor set empties: *"**No anchors left** — press A on a placed tile to certify
  one."* **Drive this case; it is not hypothetical once `A` is a toggle.** *(sweep.js:949-958, 911-912.)*
- R11.5 **`doc.origin_trial` STAYS.** Un-anchoring the origin moves **nothing** — every tile already
  carries world coordinates, and (0,0) was only ever a *frame*, not a claim about that tile.
  **Un-anchoring changes CERTIFICATION, not COORDINATES.** Do not clear it, do not re-base the field,
  do not shift a single tile. *(sweep.js:896-898.)*

---

### R12 — `1`–`9` jump the tile to the Nth-best computed position
**His words:** *"when i click any of the numbers 1-9 itll place the snapshot at the best position.
clicking 1 places the snapshot at its best computer position, pressing 2 places the snapshot at its 2nd
best computed position and so on until 9… or until 5 if only 1-5 are available but if 1-9 are available
do 1-9."*

**Statements that can fail:**
- R12.1 `1` moves the tile to the **best** peak, `2` to the runner-up, … `9` to the ninth. *(Measured:
  `2` with no prior `V` matched first, then moved trial 19 from (1,1210) to (−268,432) = the 2nd peak;
  `1` restored it; `9` reached the 9th.)*
- R12.2 **Live keys = candidates actually returned, and no more.** If a tile has 5 peaks, `1`–`5` work
  and `6`–`9` produce a **quiet toast**, not a beep: *"only 5 candidates. Press 1–5."*
  *(sweep.js:1981-1986.)*
- R12.3 🔴 **THE OFF-BY-ONE. The rail must print `#1`–`#9`, not `#0`–`#8`.** `rank` is 0-indexed
  internally, and the Alternatives rail literally printed `#0, #1, #2` while his ruling binds `1` to
  the best. **The number he READS and the number he PRESSES must agree** — on the exact screen where he
  is choosing between near-tied aliases. Display = `rank + 1`. *(sweep.js:1909-1917 `altKey`.)*
- R12.4 **Storage stays 0-indexed.** `alt_rank` is in the QC report and the exported record — do not
  churn the format. Instead the human-readable `source` string carries **both** conventions:
  `"moved by hand to alternative 2 of the anchor-composite search (rank 1; rank 0 was a thin-margin
  alias)"`. **A reader must never have to guess which convention a bare number is in.**
  *(sweep.js:1895-1902.)*
- R12.5 `MAX_CANDIDATES` is **9**, not 8, or key `9` can never fire. *(sweep.js:208-210.)*
- R12.6 **`0` is TAKEN** — it is the viewer's 1:1 zoom. His `1`–`9` scheme avoids it. **Do not add `0`.**
- R12.7 Digits must not fire while focus is in a text input — the key handler returns early inside
  `INPUT|TEXTAREA|SELECT`. *(sweep.js:1626-1628.)*
- R12.8 **If no candidates are loaded yet, MATCH FIRST, then jump** (~1 s) — same as `V` does. He must
  never have to press `V` before a number. *(sweep.js:1969-1980.)*
- R12.9 ⚠️ **Read the candidates from the per-tile evidence store, not from a single global
  `lastCandidates` slot** — one slot for the whole app will happily serve another tile's list.
  *(sweep.js:1948-1950.)*
- R12.10 A jump is a **human move**: it routes through the same `move()` path, so it pushes an undo
  entry, flags the placement `human`, and `Ctrl+Z` works for free. **It does NOT anchor** — he still
  presses `A`. *(sweep.js:1883-1907.)*

---

### R13 — An opacity slider for the tile under judgement
**His words:** *"when im hand placing a snapshot its a bit hard to see if it lines up so add an opacity
slider."*

He is right, and the old code said so out loud: once the 1-second fade ends, the floating tile is drawn
at **alpha 1.0** — he was positioning an **opaque rectangle over the very thing he was trying to line it
up with.**

**Statements that can fail:**
- R13.1 A slider on the sweep's **left rail**, next to Tone (both are display controls; neither touches
  the data). Range **15 %–100 %**, step 5, **default 100 %** (today's behaviour, unchanged unless he
  moves it). *(index.html:157-166.)*
- R13.2 It applies to the **floating tile only** — never the anchor field, never the chrome.
  *(viewer.js:656-670.)*
- R13.3 ⚠️ **IT MUST NOT FIGHT THE FADE.** With a user opacity the fade ramps **`0 → userAlpha`**, not
  `0 → 1`. At `userAlpha = 1` this is **bit-identical to before**. Do not shorten or skip the fade to
  make room for it (`FADE_MS = 1000`; *"Do not shorten it 'to feel snappier'."*).
  *(viewer.js:669-670, 73.)*
- R13.4 ⚠️ **DIFFERENCE MODE (`D`) MUST IGNORE IT.** In diff mode the composite op is `'difference'`;
  scaling the tile's alpha would drag the result toward the background and **weaken the very doubling
  that is the signal.** Force `a = 1` when `diff` is on. *(Measured: tile-centre brightness 59.4 → 33.4
  → 27.9 at 100/30/15 % in normal mode; **42.5 at both 15 % and 100 % in difference mode.**)*
  *(viewer.js:669.)*
- R13.5 ⚠️ **IT MUST SURVIVE `Space`.** It is a *session* display preference, not a fact about a tile —
  it must not reset on every advance, or it is useless. *(sweep.js:3405-3417.)*
- R13.6 ⚠️ **AND IT MUST NOT GO INTO THE PROJECT FILE.** `.camea.json` records the mosaic, not the
  operator's viewing preferences. (Tone **is** in the doc, because it is global and reproducible; an
  opacity he nudges per tile is not.)
- R13.7 `[` / `]` to step it were a nice-to-have only. ⚠️ `+`/`-` are the viewer's **zoom** and `0` is
  1:1 — **do not take those.**

---

## 1B. THE STANDING RULINGS — earlier, and just as load-bearing

These predate the fix queue and are *already* embedded in the shipped code. They cost as much as R1–R13
and a rewrite is exactly as likely to break them.

### R14 — 🔴 `Esc` must NOT kill the sweep
**Statement that can fail:** Pressing `Escape` in the sweep clears the marquee selection and the
alternative ghosts, and **leaves the cursor exactly where it was**. `Space` still advances, `A` still
anchors, `E` still excludes. The status bar still reads `trial 11`, not `trial —`. The saved project
file records `cursor: 14` (an integer, **top-level**), never `null`.

**What broke.** The viewer's `Escape` reports a deselect as `onSelect(null)`, and sweep.js passed that
straight into `setCursor(null)`. The cursor **is** the tile under judgement, so `advance()`, `anchor()`
and `exclude()` all begin `if (cursor === null) return` — and Space/A/E did **nothing, silently**. The
only way back was to click a trial in the queue. It also wrote `cursor: null` into the project file, so
a **resume landed back at the top of the run**. Driven on the real app: Esc, then three Spaces, and the
status bar read `trial —` with the sweep frozen.
**The fix:** `onSelect: (t) => { if (t !== null) setCursor(t); }` — Esc deselects; it does not abandon
the tile you are judging. *(sweep.js:2274-2283; viewer.js:1236-1240.)*
*(Verified with real key events in a real DOM: Escape → footer still `trial 11`; then Space advanced
11→12, `A` anchored 12, `E` excluded 13.)*

### R15 — ⭐ `Space` ALWAYS places the tile. The rhythm never stalls.
**His words (2026-07-12):** *"i still want it to place at where the solver thinks it is but i dont want
it to anchor it without user approval"*

**The solver-fallback rule** (`decidePlacement`, sweep.js:746-782):
- Match **confident** → use it. The anchor field is human-certified and has the bigger aperture.
- Match **not confident** AND it **disagrees with the solver by > 10 px** → place at the **SOLVER's**
  position, fade it in, and **SAY SO, loudly**, with the evidence (ncc · margin · aperture · px gap).
- Match not confident but **agrees** with the solver → no-op; the match stands.
- **No solver position at all** → use the match anyway and say so. A tile with no position is useless.
- ⛔ **NOTHING IS EVER AUTO-ANCHORED.** A diverted tile lands `unverified`. He can always drag, `S`-snap
  or `V` an alternative to overrule it.

**The three constants are load-bearing and were derived from 411 real matches scored against the human
GT.** *(sweep.js:169-202.)*
```
SOLVER_MARGIN_MIN  = 0.20    SOLVER_NCC_MIN = 0.65    SOLVER_DISAGREE_PX = 10.0
```
🔴 **THE TWO TESTS ARE NOT REDUNDANT. NEITHER MAY BE REMOVED.** On the real defer flow's 298 wrong
matches: 286 trip both, **4 trip ONLY margin** (t105: 353 px wrong at NCC 0.7450 — sails past the NCC
gate), **8 trip ONLY ncc** (t182: **2,042 px wrong** at margin 0.3230 — sails past the margin gate), 0
trip neither. Delete `SOLVER_NCC_MIN` as "dead weight" and **trial 182 is judged CONFIDENT and placed
2,042 px from the human with no banner and no warning.**
With the fallback **removed** entirely: **162/311** (t119 anchors 798 px wrong and the field cascades).
It is load-bearing. **Do not re-tune these from a vibe.**

**R15b — a diverted tile must LOOK diverted.** It carries a **magenta** outline on the canvas, a
`diverted` count in the header (hidden at zero), a loud block in the evidence rail, and a banner. In the
defer flow that is **302 of 311 tiles** sitting on the solver's answer — without this the mosaic looks
exactly like a confidently-matched one. *(index.html:122-128; viewer.js:712-716, 730; sweep.js:1827-1852.)*

**R15c — a diverted tile's NCC is measured WHERE IT ACTUALLY SITS.** On a divert the tile is *not* at
`res.best`, so writing `res.best.ncc` onto it would attribute the **rejected alias's** score to the
position that shipped. The app throws that number away and re-measures with one `POST /api/match/score`
(~31 ms). The rejected match is kept in full under `rejected_match` — it is the *evidence for* the
divert and the QC report needs it. `tiles[*].ncc` is defined by the schema as **the NCC at the tile's
final position**, and that definition holds on every path. *(sweep.js:784-844.)*

### R16 — ⛔ Blank frames are REFUSED, not scored. There is no force flag.
Two blank frames **136 trials apart** correlate **+0.43 at zero shift** (honest noise floor 0.115),
because what they share is *fixed-pattern sensor structure*, which does not move with the stage. **They
register confidently and wrongly.**

- The matcher **refuses** a blank *target*: empty candidate list, `best: null`, a populated `refused`
  block. Snap, place-on-Space and score all refuse.
- A blank **anchor** is **DROPPED from the composite**, not fatal. *(Corrected 2026-07-12 after driving
  it: the old "any blank anchor is an error" rule dead-ended the app — the moment he anchored trial 34,
  every subsequent `Space` and snap refused **forever** and the sweep died at tile 35.)*
- **Every anchor blank** → `refused: {reason: "no_anchors"}`.
- **The human eye may still place a blank tile by hand.** A human is allowed to do what the correlator
  must not. It gets **no NCC**, because there is no honest one. *(sweep.js:1272-1293.)*
- **There is no `force` flag and there will not be one.**
- 🔴 **A blank tile stays blank when you come back to it.** The refusal is a standing fact about the
  pixels, not a transient event. Clicking back onto trial 34 from the queue must re-assert the warning —
  it previously showed a tile with a position and **no warning at all**, which matters *more* now that
  the tile has a position (the solver's) and therefore *looks* placed and settled.
  *(sweep.js:1808-1818.)*
- ⚠️ A refused-but-placed tile keeps its evidence rail. "Refused" must not read as "and so nothing
  happened", because something did. *(sweep.js:1233-1236, 1252-1256.)*

### R17 — ❌ NO BLUR SCORE. ANYWHERE. EVER.
No slider, no auto-reject, no blur judgement, **no variance-of-Laplacian number anywhere in the UI**.
Across all 338 snapshots and **15 focus measures**, the best global blur threshold reaches **F1 = 0.37**;
variance-of-Laplacian — the textbook autofocus metric — scores **worse than chance** (it is dominated by
sensor noise, which is identical in sharp and blurry frames). Catching all 15 of his blurry frames also
rejects **62 good ones, best case.**
**So the scan recommends only what the code is genuinely sure of: blanks.** Blur is his eye, in the
sweep, with `E`. *(sweep.js:1619-1624; index.html:342; API.md §9.)*

### R18 — The tone window is GLOBAL. Never per-tile.
Tiles arrive from the server already flat-fielded and windowed. **Never apply a per-tile
brightness/contrast in JS, not even to a thumbnail.** A per-tile percentile stretch over-brightens
near-empty frames and makes overlapping tiles disagree in brightness, **which destroys the
Difference-mode check the whole verification loop depends on.** There is no `ctx.filter` call anywhere
in viewer.js and **there must never be one.** Tone is display-only: it never touches the matcher and
never touches the exported TIFF. *(viewer.js:61-65; API.md §6.)*

### R19 — Positions are TOP-LEFT CORNERS, not centres.
Every marker, label or crosshair adds **+256**. Off-by-256 is the classic bug in this project. In
viewer.js every one of them is spelled `HALF`. The status bar says `top-left` explicitly.
*(viewer.js:58-60, 72; sweep.js:1716-1718.)*

### R20 — 🔴 LAYERED CANVAS IS MANDATORY.
The bench's immediate-mode renderer redraws all 312 tiles every frame: **89.5 ms/frame = 10 fps at 1:1
zoom. The 1-second fade would be a slideshow.** Bake the anchored tiles into one offscreen canvas; per
frame draw *one* `drawImage` per layer + the fading tile + vector chrome. Measured **89.5 ms → 6.1
ms/frame, locked 60 fps.** Appending a tile on `A` costs **0.1 ms**; removing one is a local
clip-and-redraw repair, never a rebake. A full rebake happens **only** on `setTiles` / undo / tone
change (257 ms for 312 tiles — fine there, catastrophic in the loop).
**⚠️ Never call `setTiles()` for a single-tile change.** *(viewer.js:21-48, 361-367; SPEED.md.)*
- The status bar carries a live **ms/frame** readout. **It MUST read ~6 ms.** ~90 ms means the
  background is being rebaked every frame — that is the bug this architecture exists to prevent.
  *(index.html:589-590; viewer.js:1037-1039.)*
- The 312 unverified outlines are **ONE `Path2D` + ONE stroke**, not 312 strokes. *(viewer.js:722-740.)*
- The source rect handed to `drawImage` is **clipped to the viewport** (9.5 ms → 2.6 ms/frame at 1:1).
  *(viewer.js:556-583.)*

### R21 — 🔴 THE PREFETCH, AND THE CORRECTNESS TRAP IN IT
Every `Space` costs **1,068 ms (GPU) / 1,562 ms (CPU)**. The next tile's match is fired the instant the
current one is **displayed** (not judged — *displayed*), so it hides inside the 1 s fade and the user's
own think-time. Perceived latency → **~0 ms**.

🔴 **THE PREFETCH MUST INCLUDE THE TILE CURRENTLY UNDER JUDGEMENT IN `anchors`** — i.e. it must assume
the user will press `A`. That branch is **exact by construction**. Prefetching from the composite
**WITHOUT** the current tile **disagrees with the truth in 18 % of presses and is catastrophically wrong
(up to 1,143 px) in 6 %.**

**How the code obeys it without having to think:** *there is no client-side prefetch cache.* The
prefetch fires the *same* POST the foreground will fire and **throws the answer away**. The server
memoises on a hash of the anchor set, so the foreground call is a ~1 ms memo **hit** when — and only
when — the anchor set it sends is the one the prefetch assumed. Press `E`, or defer with `Space`, and
the anchor set genuinely differs → the key differs → the memo misses → the server recomputes honestly.
**A wrong-composite answer can never be shown, because nothing on this side ever stores one.**

⇒ **NEVER add a `Map` keyed on the trial number.** That is precisely how the trap gets sprung, and it
would look like a harmless optimisation in review. *(sweep.js:57-81, 653-694; SPEED.md.)*

### R22 — Evidence is stamped with the anchor field it was measured against
There **is** a per-trial evidence store — and it very nearly sprang R21's trap. `V` served that list,
and **clicking a candidate MOVES THE TILE THERE.** The candidates are **world coordinates computed
against the anchor field as it was**. Move an anchor afterwards and every one of them is a lie:
measured on a 5-anchor field, after correcting a 400 px mis-anchor, the cached list's rank 0 was a
confident **NCC 0.9298 at 399.7 px from the truth**, while an honest recompute put rank 0 **0.9 px**
from it. Every candidate in the served list was 186–606 px out.

⇒ **Every entry is stamped with a signature of the anchor field it was measured against, and anything
that would ACT on it (`V`, `1`–`9`) re-fetches unless the field is bit-for-bit the one it assumed.** The
server memo makes that re-fetch ~1 ms when nothing has changed. **Never trust a trial number; key on the
field.** *(sweep.js:236-250, 513-535, 1424-1446, 1961-1968.)*
- When the rail *displays* numbers from an older field it must **say so**: the "took" line appends
  ` · AN EARLIER ANCHOR FIELD`. *(sweep.js:1775-1781.)*

### R23 — Correct beats fast: the snap is the server's answer, not the browser's
A browser-side JS NCC is alias-safe only within **~±48 px** — the electrode grid repeats every **256 px**
— and past that it locks onto a confident, **wrong** alias. The committed number is the server's: real
spectralign-grade SWIM on 16-bit pixels. **~1 s per click is accepted — his ruling.** A JS pre-snap for
instant feedback is fine *as a preview*; the committed number is the server's.
Local-mode radius is clamped and **must never be widened past 128 in the UI** — to search wide, use
global mode, where the FFT + margin is what survives the aliases. *(sweep.js:1387-1391; API.md §7.1, §15.2.)*

### R24 — A drag NEVER demotes an anchor
If the user moves an anchored tile he is **correcting** it — he is the authority — and it **stays
anchored**. Only `A` and `E` change state. But every tile matched against the field *after* that anchor
was placed was matched against a field that no longer exists: **mark them stale and offer a re-check.**
*(sweep.js:1324-1361; API.md §2.1.)*

**R24b — A tile the human has moved is NEVER re-matched over.** `advance()` protects `anchored` tiles
*and* tiles flagged `human`. It used to protect only `anchored` — so a tile he dragged, snapped, and
then **deferred** with Space (which is exactly the prescribed flow for a hard tile) was **silently
re-placed on the next visit**, throwing the hand-placement away and leaving `source` claiming the
matcher had put it there. Demonstrated: 13 hand-moved to the ground truth, `back` then `Space` → snapped
straight back to the matcher's answer. **When he drags a tile it is usually *because the matcher was
wrong*; re-running the matcher puts it straight back on the wrong answer.**
*(sweep.js:1126-1143.)*

### R25 — The re-check is GLOBAL, and it is allowed to say NO
The staleness re-check must match **globally** and must **never move the tile** — it only measures it.
Anything that disagrees with where the tile sits by more than **5 px (`RECHECK_TOL_PX`) STAYS FLAGGED.**

**What broke.** It fired a *local* match (±64 px) and then cleared `stale` unconditionally. But a tile
knocked off by a moved anchor is off by **hundreds** of px — failure on this data is **binary**,
sub-pixel-right or wildly wrong — so a ±64 px window is *structurally blind* to the one error the panel
exists for. Measured: a tile **380 px** from the truth re-checked locally to `ncc -0.0678`, was not
moved, and had its flag **cleared**; the same tile re-checked globally found the truth at `ncc 0.9394`,
**0.9 px** out. The loud "N tiles may be stale" panel **disappeared** and the tile stayed 380 px wrong,
with a **negative NCC** recorded in the document as its evidence. *(sweep.js:2030-2105.)*

### R26 — 🔴 A re-solve must not destroy the human's work
`loadBuildResult()` **keeps** every tile that is `anchored` **or** flagged `human`, and seeds everything
else *around* them. And it **translates the build onto the human's field** by the **median** offset over
the protected tiles — a median, not a mean, because a tile the human corrected *because t33 was wrong*
is precisely an outlier, and one 2,969 px correction would drag a mean into nonsense. If **none** of the
human's tiles are in the build, the two frames cannot be tied together and the app **refuses to seed**
rather than guess. *(sweep.js:2889-2940.)*

**What broke.** `setState` was called unconditionally on every non-excluded tile, so every `anchored`
tile reverted to `unverified` at t33's position. **And the app routes the user into this**: excluding a
tile mid-sweep raises "THE BUILD IS STALE … Re-solve", whose button opens the Place screen. Sweep 150
tiles, hand-correct the aliases (the 797 px fix on 119, the 2,969 px fix on 128), press `E` on one bad
frame, take the app's own advice — and **all 150 judgements, including the three catastrophic
corrections, are gone**, with the autosave writing the wiped document straight over the crash-recovery
file.

### R27 — 🔴 "Skip — place by hand" is DESTRUCTIVE, or it is nothing
If anything in the document came from a machine, `Skip` **discards every position and the build**, after
a confirm that names the count. Otherwise it launders a machine build into an "independent ground truth":
it used to null `build`, null `seeded_from`, set `independent_of_method: true`, delete the warning — and
**not touch a single tile.** Every tile kept t33's position. The path was: build 312/312 → seed → sweep →
click step 4 → click Skip → export a file that says, in writing, that it is a hand-authored independent
truth. **Score t33 against it and it gets ~100 % by construction. That is the exact mechanism that
already destroyed one benchmark in this project.** *(sweep.js:3064-3113.)*

### R28 — The provenance stamp is derived from the document's HISTORY, never from what it claims
A `build` block, **or a single tile still carrying a `machine` position**, means every position started
as a solver's answer — whatever `seeded_from` says. The panel must never show "Independent" over a
seeded document. *(sweep.js:2107-2131.)*

Pass 1's ground truth got tiles **128/129/130/148 wrong** *precisely because* it was seeded from a build
and the human deferred to it. It was only caught because pass 2 was later authored blind. So:
- A seeded document is stamped **NOT AN INDEPENDENT GROUND TRUTH** — *"It MUST NEVER be used to score
  t33 or any method derived from it — the score would be 100 % by construction."*
- ⚠️ **The anchoring hazard, said out loud, per tile:** when a tile is still sitting *exactly* where the
  machine put it (< 0.5 px), the rail says so — *"At the machine's position, **untouched**"*. It does not
  let *"I looked at it"* and *"I agreed with it"* blur together. *(sweep.js:1821-1866.)*
- ⚠️ **A diverted tile is NOT "the human accepted the machine"** — it is "the app never gave the matcher
  a vote here". It lands in `accepted_unchanged` (it *is* at the machine's position), which would read as
  agreement, so it is counted **separately** in `human_edits` with a `diverted_note` that says so.
  *(sweep.js:1589-1609.)*

### R29 — Autosave is a server file, and a failure is LOUD
Autosave is `POST /api/project/autosave` — **not `localStorage`**, which in the artifact sandbox failed
**silently** and nearly cost him a day's work. Debounced **2 s**, plus **unconditionally on every `A`
and `E`**. **Never swallow a failure**: it toasts `AUTOSAVE FAILED: … — save by hand.` *and* the Mosaic
note reads `autosave: FAILED`. *(sweep.js:1508-1528.)*

### R30 — 📏 PIXELS ONLY. No scale bar by default.
`um_per_px` is `null` by default and the exporter writes **pixels only**: no scale bar, no OME-TIFF
`PhysicalSizeX/Y`. If the user types a number in, it is written **and stamped "user-supplied by hand,
not measured"**.
**There is NO magnification difference between the passes** (cross-pass tissue scale 1.0000 ± 0.0002) —
so **one** scale bar spanning both passes is safe and a **two-scale** figure would be actively wrong. But
the *absolute* number is not yet safe to write: **1.237 µm/px is wrong — delete it**; 1.268 µm/px is
*probably* right but rests on the same inference that demonstrably fails by 2.5 % in pass 1.
*(SCALE.md; index.html:500-502; API.md §12.2.)*

### R31 — Cache-busting is a session nonce, not the tone version
`?v=` used to be the tone version alone — and the tone version is a fresh-dataclass default, so it
**resets to 1 on every session open and every run change**, while the pixels behind the URL change. Tile
PNGs are served `Cache-Control: immutable, max-age=1y`: **same URL, different bytes, and the browser will
not revalidate for a year.** Open a second acquisition directory whose trial numbers overlap and the
mosaic renders the **first dataset's pixels** — and this whole app is "the human looks at the pixels".
The buster is `{session_nonce}.{tone_version}`. *(sweep.js:226-234; server.py:477-483.)*
**And the bitmap cache must be flushed on a session open / run change, not only on a tone change** — the
viewer's cache is keyed on the trial number alone and was cleared only inside `setToneVersion()`, which
early-returns when the value has not changed. *(sweep.js:2361-2371; viewer.js:1018-1035.)*

### R32 — ⭐ THE SCRIPTS MUST BE CACHE-BUSTED (this one nearly shipped a half-old app)
`index.html` was `no-store`, but `<script src="/viewer.js">` carried **no version**. So a **new
`index.html` could load an OLD `viewer.js`.** It hit exactly that: fresh `sweep.js` called
`Viewer.setShowUnverified()`, the cached `viewer.js` had never heard of it, the mount died —
*"Viewer.setShowUnverified is not a function"* — **a dead sweep from a pure cache artefact. WebView2
caches too.** The server now stamps each asset with its own **mtime** (`?v=…`), so the URL changes exactly
when the file does. *(server.py:301-309; FIXES.md:109-115.)*
**Rewrite note:** a bundler with content-hashed filenames satisfies this. **Verify it in WebView2, not
just in the dev server.**

### R33 — The judgement keys are DEAD while a placement is in flight, and the cursor does not move until the answer is in hand
`_advance()` awaits a match that costs 0.4–1.1 s on a memo miss, and it used to move `cursor` to the next
tile **before** that await. So for up to a second the canvas showed the *previous* tile as the cursor
while `A`/`E`/`S`/`V` acted on a tile the user could not see; and when the response landed it **silently
overwrote the judgement the user had just made**. Driven, real HTTP: `Space` then `E` at +120 ms → the
tile came back `unverified`, on the canvas, still carrying `excluded: true`. `Space` then `A` → the tile
came back `unverified`, the anchor counter fell back, and **the tile he had CERTIFIED was dropped from
the exported GT** (`score.load_gt` keeps only `status == "anchor"`) and from the field every later match
is measured against.

**Two rules, both required:**
- The cursor is committed only at the point of **display** — the only moment "the tile under judgement"
  and "the tile on the screen" are the same tile. *(sweep.js:1113-1117.)*
- A judgement offered mid-flight is **refused out loud** (`"Still placing — anchor ignored."`), never
  applied to the wrong tile. *(sweep.js:1039-1059 `busyPlacing`.)*
- A second `Space` inside the ~1 s match must not start a second advance. **One flag.**
  *(sweep.js:1069-1081.)*

With the A-branch prefetch warm this window is normally invisible; it only opens when the memo genuinely
misses — **which is exactly when it is unsafe.**

### R34 — A tile that leaves `excluded` must stop claiming it was thrown out
`setState` wrote `state`/`status`/`x`/`y` and left `excluded` / `excluded_reason` / `unusable_reason`
behind, so `E` then `A` on the same tile produced a record reading
`status: "anchor"  excluded: true  excluded_reason: "the user's eye"` — and `score.load_gt` keeps every
`status == "anchor"`, so **that self-contradicting tile went into the exported ground truth still
asserting it was unusable.** The claim is a judgement; it dies with the judgement.
⚠️ **`blank` is NOT cleared** — that is a *measurement* about the pixels, not a judgement.
*(sweep.js:543-557.)*
Symmetrically: a hand move (`setPos`) **kills the divert claim** — `diverted`, `divert_reason`,
`rejected_match` — at the single place a position is rewritten. Leave it and the rail keeps shouting
"THIS IS THE SOLVER'S POSITION" over a tile the user has just dragged somewhere else.
*(sweep.js:572-583.)*

### R35 — The exclusion must reach the SOLVER
`/api/build/start` used to be handed the session's full trial list regardless — so pressing `E` and then
"re-solve" re-solved the **identical problem** and put the excluded frame straight back into the chain.
The build is given `activeTrials()` = everything the user has **not** excluded.
*(sweep.js:2708-2714, 2763-2769.)*

### R36 — Undo is 100 deep, tag-folded at 700 ms, and a drag pushes ONCE
One undo entry per **gesture**. A drag pushes on its first `pointermove` and not again on drop. A held
arrow key folds into a single step. **The evidence store is part of the snapshot** — restoring the
document while leaving `evidence` untouched left the rail, and `V`'s candidate list, describing a field
the document no longer had. *(sweep.js:1469-1506.)*

### R37 — The export is 7 files, and the coverage mask is MANDATORY
`tiff` (16-bit), **`coverage` (its mandatory companion)**, `png` (8-bit, the global tone window),
`positions.csv`, `gt.json`, `qc.json`, `qc.md`. **13.1 % of the canvas is background encoded as exactly
`0.0`, indistinguishable from a legitimately black pixel, and a TIFF has no alpha channel.** Without the
mask, "empty" and "black" merge forever. *(index.html:488; API.md §12.1.)*
- Rendered: `anchored` + `unverified` **iff `include unverified`**. `excluded` and `unplaced` are
  **never** rendered.
- `render_mode` default **feather** — the only interactive one (feather 1.11 s; median 41.7 s; alpha 74 s).
- Positions normalised so `origin_trial` sits at exactly `(0, 0)`, matching `analysis/ground_truth/`.

### R38 — Headless must stay drivable, or there are no Playwright tests
In headless mode `/api/dialog/*` returns **501**, and `saveProject()` / `loadProject()` both fall back to
`window.prompt()` — **which Playwright can answer**. That is the *only* reason the whole
save → kill-server → cold-load → resume round-trip is drivable at all, and it is how R2.6, R14 and the
export were verified. **Keep a headless-answerable path for both dialogs.**
*(sweep.js:3155-3161, 3184-3188; FIXES.md:45-47.)*

### R39 — What we are NOT rewriting, and why *(SPEED.md, settled)*
- **No native shell** (C#/WPF, Qt, Tauri, Electron). Buys ~550 ms of launch, once; costs a second
  language, a second process and a sidecar lifecycle.
- **No WebGL/WebGPU renderer.** 1.4 ms → 0.1 ms/frame = **zero perceived gain** (you cannot draw faster
  than the monitor refreshes), for a second renderer to maintain.
- **No engine rewrite.** The CPython interpreter is **1.0 %** of a 230 s build. A perfect C++/Rust
  rewrite recovers 2–4 s of 230 — and would discard the only method that scores 312/312.
- **Do not optimise the frame loader or the transport.** 0.135 s of a build; 0.63 ms of a click.

---

## 2. THE SIX STEPS

The step header is a progress indicator, not a menu (R4.2). The exact gate is in R4.3.

### 1 · Load — *"which directory?"*
`index.html:251-281`

| | |
|---|---|
| **He sees** | A `directory` text field (typeable), `Browse…` (native dialog via `POST /api/dialog/open-directory`), `Open`. A progress bar + phase message while it opens. A **Resume** section: `Load a project…` plus *"…or open a directory above to start fresh."* |
| **Unlocks** | Always reachable — it is step 1. |
| **Does** | `POST /api/session/open` → a job (2–6 s: frames + flat-field + tone + the 3 s texture scan). Phases: `scan_dir → parse_log → load_frames → flat_field → tone → texture → done`. |
| **Writes** | The **session** (server-side): trial list, tone window, blank scan, GPU probe. Then a **fresh document** (client-side) in which **every trial is `unplaced`** (R2). |
| **Then** | **Navigates to Range.** *(sweep.js:2403-2406.)* |
| **Also** | `--data-dir` launch: the open job is already in flight when the page loads, so `init()` must **attach to the pending open job** rather than take the 404 and park on Load forever. Driven: it sat on "Open an acquisition directory" with the path already typed in, and nothing but a second click would move it. *(sweep.js:3436-3469.)* |
| **Also** | `Load a project…` is reachable **cold** (no session). It bootstraps a session from the file's own `data_dir`, then **re-reads the file** so the range guard actually runs against the session it belongs to. *(sweep.js:3169-3218.)* |

### 2 · Range — *"which trials are the mosaic?"*
`index.html:285-330`

| | |
|---|---|
| **He sees** | A `.facts` strip: **Trials** (count, `?` = the measured `why`), **Range** (`11–348`), **Pass split** (value + `n_pass1 · n_pass2`, `?` = the measured `why`), **Gaps** (`none`, or `283→297, 298→311`). Then `lo` / `hi` / `pass split` inputs + `Apply`. Then the **contact sheet** (one sprite sheet; clicking a cell sets the cursor and jumps to the Sweep). |
| **Unlocks** | A session exists. |
| **Does** | `Apply` → `PATCH /api/session/run` → a **reload**. ⚠️ **Destructive**: it invalidates the build, the tone window and the scan. If anything is placed, **confirm first** — *"Reloading discards the build and every position in it. Continue?"* *(sweep.js:2446-2457.)* |
| **Writes** | A new session + a new document. |
| **Numbers, not prose** | The two detections (run = the longest contiguous block of Snapshot trials; pass split = the trial before the largest *interior* inter-trial gap, ignoring the block's first step) are **measured**, are validated on **n = 1 dataset**, and are always overridable. Their reasoning lives on the `?`. |
| **Gaps are LIVE** | Recomputed on **every** exclusion, from live tile state. This used to be written once at load from the session's list and never again — while the `?` promised it was recomputed. *(sweep.js:1699-1705, 596-602.)* |

### 3 · Screen — *"which frames do you want thrown out?"*
`index.html:339-371`

| | |
|---|---|
| **He sees** | Facts: **Recommended** (count, `?` = the measure + threshold source + margin warning), **Threshold**, and "Your call, per frame — keep · hand place · exclude". Then a **grid of cards**, one per scanned frame: the trial number, a **thumbnail**, its texture value, and the **three-way control**. |
| **Unlocks** | A session exists. |
| **Does** | Each choice **applies immediately** (R6.5). `Keep` lifts the refusal (`PUT /api/scan/blank`); `Hand place` (the default) leaves it refused; `Exclude` sets the tile state and **recomputes the gaps**. |
| **Writes** | `doc.tiles[t].state`, `doc.unusable_tiles`, `doc.gaps`, `doc.blank_scan.{blank, scanned, overruled_by_user, accepted}`; and the server's refusal list. |
| **Rules** | R6 in full. The scan **recommends**; **he decides**. Nothing is auto-excluded, ever. No slider. No blur score (R17). |
| **Re-derive on arrival** | R6.6 — the cards must be re-rendered from live state every time he lands here. |
| **On the way out** | `"Place the tiles →"` fires `putRefusals()` **first**, then navigates. *(sweep.js:3374-3377.)* |

### 4 · Place — *"run the solver"*
`index.html:374-466`

| | |
|---|---|
| **He sees** | An honest cost line (`GPU · <name> — ~3 min cold, ~25 s cached.` / `**No GPU** — ~8–10 min. The result is identical.`). A big `Run`. A `Cancel` (during a build). A `use cache` chip (`?` per R7.2). `Skip — place by hand`. During a build: progress bar, phase, message, **ticking ETA**, last-8-lines log. After: **Placed** / **Took** / **Build id**, and a **"Look here first"** worklist. An `Advanced` `<details>` drawer with 7 knobs. |
| **Unlocks** | A session exists. |
| **Does** | `POST /api/build/start` with `{config, use_cache, trials: activeTrials()}` (R35) → a job. `config: null` = t33's shipped 312/312 defaults, and that is the one-button path. |
| **Writes** | `doc.build` (id, method, created, seconds, gpu, n_placed, config, **translated** positions, `seed_translation`, **`trials`**, `gaps`), `doc.provenance` (→ machine-seeded, `independent_of_method: false`, + the warning), and each tile's `machine` position + `unverified` state — **except** anchored and human tiles, which are kept (R26). |
| **The worklist is "go look", not a verdict** | Sorted by `anchor_residual_px`, top 12, plus every thin-margin tile. ⛔ **NOT** built on `quality.score_positions` — on the ground-truth-perfect 312/312 build that flags 11 tiles and **all 11 are false positives (precision 0/11)**. And it is **blind to pass 1**: t27's info is aggregate-only, and **the worst tile in the shipped 312/312 build (trial 127, 9.94 px) is a pass-1 tile.** The panel says so, loudly — *"N pass-1 tiles have no per-tile confidence. They cannot appear here at all."* **The absence of a warning is not a clean bill of health.** *(sweep.js:3011-3062.)* |
| **GPU** | If there is no GPU, **run anyway** and state the real cost. Never degrade the result silently. And **say WHY there is no GPU** — a CUDA DLL-path problem is *fixable* and is not the same thing as "no card". *(sweep.js:2409-2443.)* |
| **`Skip`** | R27 — destructive, or it is nothing. |

### 5 · Sweep — ⭐ the heart. `A` / `E` / `Space` over the 1 s fade.
The sweep **is the stage**: the canvas plus both rails. It has no pane.

| region | contents |
|---|---|
| **Canvas** | The certified field (feathered, R10) + the one floating tile under judgement (crisp, R10.2). Starts **empty** (R9). |
| **Overlay, top-left** | The **banner** (`#banner`) — the loud running commentary: divert notices, thin-margin warnings, un-anchor/stale counts, "no anchors left", end-of-run. |
| **Overlay, bottom-left** | The seven action buttons: **Anchor `A` · Exclude `E` · Next `Space` · Replay `R` · Difference `D` · Alternatives `V` · Snap `S`** — all seven with a `?` (R7.1). Wraps rather than clipping: **losing one off the edge is not acceptable.** *(index.html:57.)* |
| **Overlay, top-right** | `Fit F` · `1:1 0` · `Undo` · `Redo`. |
| **Left rail** | **Queue** (every trial as a chip, coloured by state, `cursor` outlined, `stale` dashed; `◀ back`; an `outstanding only` filter; `n / total`). **Rescue** (every `unplaced` tile, each with a `Rescue` button). **Opacity** (R13). **Tone** (R18; display only). **Keys** (the cheat-sheet). |
| **Right rail** | **Evidence**: the refusal panel, **NCC** + its meter, **margin**, **anchors**, **composite area**, **overlap**, **took**; the **THIN MARGIN** warning; the **small-aperture** warning; the machine/divert note. **Alternatives**: the ranked list, numbered **1–9** (R12.3). **Staleness** panel. **Build-stale** panel. |
| **Status bar** | `trial <n>` · a state **badge** · `pass <n>` (+ `blank (measured)`) · **`top-left <x, y>`** (R19) · a hint · **ms/frame · fps** (R20). |
| **Unlocks** | A session exists (R4.3). |
| **Writes** | Everything. Every judgement autosaves (R29). |

### 6 · Mosaic — *"build the outputs"*
`index.html:469-525`

| | |
|---|---|
| **He sees** | Output `directory` + `Browse…` + `basename`. Five output chips: **16-bit TIFF · display PNG · positions.csv · ground-truth JSON · QC report** (+ the coverage-mask `?`). `render` select (feather / median / alpha, with their real costs in the labels). `include unverified` (checked). `µm/px` (blank). `Export`. The `autosave: …` note. The **Provenance** panel. |
| **Unlocks** | **Something has a position** (`anyPlaced()`). This is the *only* real gate past a session. |
| **Does** | `POST /api/export` → a job → a list of written files with sizes. |
| **Writes** | 7 files (R37). Nothing in `data/` is ever written to. |
| **Provenance** | R28. It is a **live warning** and it stays on the page (§5). |

---

## 3. KEYBINDINGS — exhaustive

### 3.1 The global guard *(sweep.js:1626-1638)*
1. If focus is inside `INPUT` / `TEXTAREA` / `SELECT` or a `contentEditable`, **the handler returns
   immediately**. Nothing below fires. (This is why the digits `1`–`9` do not fight the tone and range
   fields — R12.7.)
2. `Ctrl/⌘ + S` · `Ctrl/⌘ + Z` · `Ctrl/⌘ + Y` are handled **first, on every screen**.
3. Any other `Ctrl` / `⌘` / `Alt` combination is **ignored**.
4. **Everything below this line only fires when `screen === 'sweep'`.**

### 3.2 Works on EVERY screen
| key | action | cite |
|---|---|---|
| `Ctrl+S` / `⌘S` | **Save the project file.** Opens the native save dialog; falls back to `window.prompt()` when headless (R38). | sweep.js:1634 |
| `Ctrl+Z` / `⌘Z` | Undo (100 deep, tag-folded — R36). | sweep.js:1635 |
| `Ctrl+Y` / `⌘Y` | Redo. | sweep.js:1636 |
| `Escape` | **Also** dismisses the help tooltip — a separate, document-level listener that runs regardless of screen. | sweep.js:381 |

### 3.3 The sweep's own keys — handled by sweep.js
| key | action | notes | cite |
|---|---|---|---|
| `Space` | **ADVANCE.** Place the current tile if it is `unplaced`; then place the next non-excluded tile and **fade it in over 1 s**; then prefetch the one after (A-branch). | Always places (R15/R9b). Never wraps — at the end, the sweep is done. Refused mid-flight (R33). **NOT a pan modifier** (R‑neg, §6). | sweep.js:1644, 1061-1196 |
| `A` / `a` | **ANCHOR — a TOGGLE.** `unverified`/`unplaced` → `anchored`. **`anchored` → `unverified`, keeping its position** (R11). If nothing anywhere is placed, this tile is the **origin at (0,0)** and `origin_trial` is set. If it has no position, match first (through `decidePlacement`) and anchor where that lands. | Autosaves unconditionally. Prefetches the next tile. | sweep.js:1645, 916-983 |
| `E` / `e` | **EXCLUDE.** Any state → `excluded`, position → `null`, old position kept in `last_xy` for undo. **Recomputes the gaps** and says so. If it was an **anchor**, marks every later-judged tile **stale**. | Autosaves unconditionally. | sweep.js:1646, 985-1029 |
| `R` / `r` | **REPLAY the fade** on the tile under judgement. Changes nothing. He will want this constantly. | The fade tick is keyed on a unique fade **id**, not the trial — a trial-keyed guard lets a superseded tick fire `onFadeEnd` **twice** (a double autosave and a double advance). | sweep.js:1647; viewer.js:948-955, 925-945 |
| `V` / `v` | **ALTERNATIVES** — toggle the ranked runner-up ghosts on the canvas and the list in the rail. | 🔴 **Must not serve a list measured against a field that no longer exists** (R22). Clicking a ghost **moves the tile there**. | sweep.js:1648, 1422-1446 |
| `S` / `s` | **SNAP** — re-run the matcher **locally** (radius 64) around where the tile now sits, against the anchors certified *so far*. | ~1 s. The committed number is the **server's** (R23). A **blank tile refuses to snap**. Flags the tile `human`. | sweep.js:1649, 1387-1420 |
| `1`…`9` | **Jump to the Nth-best computed position** (R12). `1` = best. Matches first if needed. Out-of-range → a quiet toast. | Routes through `move()` → undoable, flagged `human`, **does not anchor**. | sweep.js:1653-1660, 1941-1988 |

### 3.4 Delegated to the viewer — camera & selection *(viewer.js `handleKey`, 1214-1244)*
sweep.js mounts the viewer with **`bindKeys: false`** and calls `Viewer.handleKey(e)` itself. 🔴 **This
is load-bearing:** if the viewer binds its own `window` keydown as well, every one of these is
double-handled — `D` toggles Difference twice and lands back where it started. **One dispatch point.**
*(sweep.js:2238-2242.)*

| key | action | cite |
|---|---|---|
| `←` `↑` `↓` `→` | **Nudge 1 px** in world coordinates. **Shift = 10 px.** Moves the cursor tile, or the whole selection if there is one. Reports through `onDragEnd` so it folds into **one** undo step. | viewer.js:1227-1229, 1001-1016 |
| `F` / `f` | **Fit** the whole placed bbox to the viewport (48 px pad, scale clamped 0.02–16). | viewer.js:1232, 454-462 |
| `0` | **1:1** zoom, keeping the view centre put. **`0` is not an alternatives key** (R12.6). | viewer.js:1233, 475-476 |
| `D` / `d` | **Difference mode** toggle. `globalCompositeOperation = 'difference'` on the floating tile: `|tile − field|`. Misalignment shows as **bright doubling**. | viewer.js:1234, 957-965 |
| `G` / `g` | Toggle the 512-px world grid. (Hidden in Difference mode.) | viewer.js:1235, 543-554 |
| `Escape` | Clear the marquee selection and the alternative ghosts. **R14: it MUST NOT clear the cursor.** | viewer.js:1236-1240; sweep.js:2274-2283 |
| `+` / `=` | Zoom in ×1.3. | viewer.js:1241 |
| `-` / `_` | Zoom out ÷1.3. | viewer.js:1242 |
| `Space` | ⛔ **Explicitly NOT handled by the viewer — it returns `false` immediately.** The bench used hold-Space as a pan modifier; here `Space` is **ADVANCE**, the most-pressed key in the product. It is also a trap: with `bindKeys:false` the viewer's `keyup` is never registered, so a `spaceDown` flag would **never be cleared** and every subsequent left-drag would silently become a pan. | viewer.js:1219-1225 |

### 3.5 Difference-mode invariants
- The clear colour **must be black** in Difference mode. `difference` composites `|tile − destination|`,
  and where the anchor field does not cover the tile the destination **is** the clear colour. In the
  light theme `--canvas` is `#dfe4ea` (223), so without this **half of what he is looking at, in the one
  check the whole verification loop depends on, is a photographic negative of the tile.** Black is the
  only destination for which "no reference here" reads as "no difference here". *(viewer.js:626-635.)*
- In Difference mode the destination **must be the ANCHOR FIELD ALONE**. An `unverified` tile is by
  definition not a trusted reference, and blending it in at 55 % would muddy the very pixels he is
  judging. *(viewer.js:643-651.)*
- Difference mode **ignores the opacity slider** (R13.4).

### 3.6 Pointer bindings *(viewer.js:1106-1203)*
| gesture | action |
|---|---|
| Left-click on an **alternative ghost** | `onAlternativePick` → **moves the tile there**, through the *same* path as the rail's list (R‑below). |
| Left-drag on a tile | Move it. Pushes **one** undo entry on the first `pointermove`. Live NCC scored at 150 ms debounce. **Shift = axis lock.** A drag never demotes an anchor (R24). |
| `Ctrl`/`⌘` + click a tile | Toggle it in the selection. |
| Middle-mouse drag, or `Alt` + drag, or drag on empty space | **Pan.** |
| Right-button drag, or `Shift` + drag | **Marquee select.** (`Ctrl` = additive.) |
| Wheel | Zoom about the pointer. |
| Right-click | Context menu suppressed. |

🔴 **THE EVIDENCE MUST FOLLOW THE TILE ON BOTH ROUTES.** There are two ways to pick an alternative — the
rail list and a click on the **ghost rectangle on the canvas** (which is the primary affordance, and the
one a user actually reaches for). The rail's handler recorded the peak's `ncc`/`npix`/`rank`; the
canvas's called only `move()`, so the tile kept **rank 0's NCC at rank 1's position**. Driven on trial 28
(margin 0.026 — a textbook alias): after clicking the canvas ghost, the tile sat **2,113 px away still
carrying `ncc: 0.4477`**, with `alt_rank` and `npix` undefined. **ONE helper; both call sites use it.**
*(sweep.js:1868-1907.)*

---

## 4. THE TILE STATE MACHINE

**Four states. There are no others.** *(API.md §2; sweep.js `setState`, 537-570.)*

| `state` | `status` (on disk) | position | in the **anchor field**? | drawn in the sweep | exported |
|---|---|---|---|---|---|
| `unplaced` | `"unplaced"` | `null` | no | **no** — it is in the rescue queue | no |
| `unverified` | `"unverified"` | yes | **NO** | **NO — R9.** (It is in `L_unver`, which is maintained but not drawn.) | yes, **iff** `include unverified` |
| `anchored` | `"anchor"` | yes | **YES** | **yes** — feathered into the certified field | yes |
| `excluded` | `"excluded"` | `null` (old value in `last_xy`) | no | **no** — not drawn, not matched, not rendered, not exported | no |

⚠️ **`status` is the on-disk name and `state` is the in-memory name, and they differ for `anchored` /
`"anchor"`.** `benchmark/score.py :: load_gt` keeps every tile whose `status == "anchor"` — get this
mapping wrong and either nothing or everything lands in the exported ground truth. `setState` is the
**only place a tile's state is ever written**, and it writes both. On load, `state` wins if present, else
it is derived from `status`. *(sweep.js:540, 3226-3230.)*

### 4.1 Transitions — the complete table

| trigger | from | to | position | side effects |
|---|---|---|---|---|
| session open | — | `unplaced` | `null` | **every** trial. Nothing is excluded (R2). |
| a build finishes | `unplaced` | `unverified` | the build's (translated) position | `machine` recorded; `source = 't33 build, not yet judged'` |
| a build finishes | `anchored`, or any `human` tile | **unchanged** | **unchanged** | R26 — only `machine` + `moved_px` are written |
| a build finishes, tile not placed by the solver | `unplaced` | `unplaced` | `null` | stays in the rescue queue |
| **`A`**, nothing anywhere is placed | `unplaced` | `anchored` | **`[0, 0]`** | `origin_trial = t`; `source = 'origin tile'`; **it fades in** |
| **`A`**, tile has no position | `unplaced` | `anchored` | `decidePlacement()` — the match, or the **solver's** position if the match is not confident (R15) | fades in; announced loudly either way |
| **`A`** | `unverified` | `anchored` | **unchanged** | `stale = false`; `judged_at` |
| **`A`** ⭐ | `anchored` | **`unverified`** | **KEPT** (R11) | downstream tiles → `stale`; warns if no anchors are left |
| **`E`** | any | `excluded` | `null` (old → `last_xy`) | **recompute gaps**; if it was an anchor → downstream `stale`; `unusable_reason` = `blank` \| `other` |
| **`Space`** | `unplaced` | `unverified` | `decidePlacement()` | if there is no match *and* no solver position, it **stays `unplaced` and the cursor still advances** |
| **`Space`** | `unverified` / `anchored` | **unchanged** | **unchanged** | the cursor moves on; deferring never stalls the sweep |
| drag / `S` / arrow nudge / `V` pick / `1`–`9` | `unplaced` | `unverified` | the new position | `human = true` |
| drag / `S` / arrow nudge / `V` pick / `1`–`9` | `unverified` / `anchored` | **unchanged** | the new position | `human = true`. **A drag never demotes an anchor** (R24). If it *was* an anchor → downstream `stale`. |
| Screen step: `Exclude` | any | `excluded` | `null` (old → `last_xy`) | as `E` |
| Screen step: `Keep` / `Hand place` on an excluded frame | `excluded` | `unverified` **if `last_xy` exists**, else `unplaced` | `last_xy` or `null` | ⚠️ read `last_xy` **before** `setState`, which deletes it |
| rescue (from the rescue list) | `unplaced` | `unverified` | `decidePlacement()` | a rescue is a **placement**, never a judgement |
| hand-place a refused (blank) tile | `unplaced` | `unverified` | dropped on the previous placed tile | `human = true`; `ncc = null` — there is no honest NCC |
| `Skip — place by hand` (confirmed) | any non-excluded | `unplaced` | `null` | **destructive** (R27): clears `machine`, `ncc`, `margin`, `seq`, `human`, `source` |

### 4.2 Cursor movement
- `Space` advances to the **next trial in the run whose state is not `excluded`**. **No wrapping** — at
  the end, the sweep is done and the banner says how many are still unverified. *(sweep.js:604-616.)*
- ⚠️ **Trial numbers are acquisition ORDER but are NOT contiguous** once anything is excluded. A
  "consecutive" pair across a gap is a multi-step jump and the serpentine one-axis step prior does
  **not** hold there. **Any change to the `excluded` set MUST recompute the gaps** before the next
  build, or the solve is silently poisoned. *(sweep.js:592-602; CLAUDE.md.)*

### 4.3 Facts that are NOT states
These attach to a tile and must not be modelled as states, or the counters and the exports go wrong.

| fact | meaning | lifetime |
|---|---|---|
| `blank` | **MEASURED** — the band-passed std is below the scan's threshold. It is what the *matcher refuses* (R16). **It excludes nothing and it never will.** | Never cleared, not even by `E` → `A`. It is a measurement, not a judgement. *(sweep.js:551.)* |
| `diverted` | The tile is on the **SOLVER's** position because the matcher was not trustworthy there (R15). **Not a state** — a fact about an `unverified` tile. It must be **countable** (in the defer flow it can be 302 of 311 tiles) and **visible** (magenta outline). | Dies the instant a **hand** rewrites the position (R34). An **anchored** tile *keeps* its divert record — that is its provenance, and the QC export counts it — but it stops nagging from the header (only still-`unverified` diverts are counted). *(sweep.js:500-507.)* |
| `human` | A hand put this position here. **`advance()` will never re-match over it** (R24b). | Set by drag / `S` / nudge / `V` / `1`–`9` / hand-place. |
| `stale` | This tile was matched against an anchor field that has since changed. | Cleared only by a **global** re-check that agrees within 5 px (R25), or by `V`/`1`–`9` re-matching it against the current field. |
| `machine` | What the solver said, **translated into the document's frame**. A fact, recorded either way. | Its presence is what makes the provenance stamp non-independent (R28). |
| `seq` | Judgement order. The staleness cascade is `seq > oldSeq`. | Bumped on every `anchored`/`unverified` write. |
| `alt_rank` | Which peak the human chose. **0-indexed in storage; displayed as +1** (R12.4). | |

---

## 5. THE LIVE-WARNING EXCEPTION — the exhaustive list

> **The rule (R3.8).** *"A LIVE WARNING ABOUT THE CURRENT STATE IS NOT AN EXPLANATION."* These fire
> **only when something is actually wrong**, they **change what he would do**, and burying them behind a
> hover would be a regression, not a decluttering.
>
> **The BACKGROUND to each of them may go behind a `?` ON the warning. The fact that it is FIRING may
> not.** Do not "tidy" one of these into a tooltip. Every one of them is here because it — or its
> absence — has already cost this project real work.

**FIXES.md ruling 3 names five.** The shipped code fires **eleven** — the extra six all carry an
explicit "this is a live warning, it stays" comment at the site. All eleven are contract.

| # | warning | fires when | why it may not become a tooltip | cite |
|---|---|---|---|---|
| **W1** | **`THE BUILD IS STALE.`** + the reason (*"3 excluded since the build (289, 300, 301)"*) | The current active trial list ≠ the list the build was solved on. **A build with no recorded `trials` is treated as STALE** — the backend refuses to guess. | The positions were solved on a **different input**. The tiles either side of an excluded one were placed **through** it, and the serpentine one-step prior does not hold across the gap that just opened. He must re-solve, or knowingly not. Nothing read this before — the machinery existed but was never given `build.trials` to compare against. | sweep.js:2716-2761; index.html:573-578 |
| **W2** | **`THIN MARGIN. best − second < 0.10`** (+ the NCC meter turns red) | `margin_thin`, or `margin < 0.10`. | **This is what a surviving grid alias looks like** — the correlator found a second position almost as good as the first and may have picked the wrong one. The shipped build's worst run margin is **0.081** against a ~0.47 typical. It changes what he does: check `D`, look at `V`, before he anchors. | sweep.js:1783-1786; index.html:548-551 |
| **W3** | **The DIVERT block** — `SOLVER'S POSITION, NOT THE MATCHER'S.` + the reason + *"matcher wanted (x, y) — N px away, NCC …"* — **plus** the banner, **plus** the header's `diverted` count, **plus** a **magenta outline** on the canvas | A tile is sitting on the solver's answer because the match was not confident **and** disagreed by > 10 px (R15). | Without it the tile reads *"At the machine's position, untouched"* — **true, and completely missing the point**: the app actively *refused* the matcher's answer here. In the defer flow this is **302 of 311 tiles**, and the mosaic would look exactly like a confidently-matched one. | sweep.js:1827-1852, 846-872; viewer.js:712-716 |
| **W4** | **`autosave: FAILED`** — a red toast **and** the Mosaic note | Any autosave POST throws. | A silent autosave failure has burned him before and **nearly cost a day's work**. Never swallow it. | sweep.js:1517-1528 |
| **W5** | **The PROVENANCE stamp** — `NOT AN INDEPENDENT GROUND TRUTH. Every position started as t33's output. Never score t33 with this.` | Any tile carries a `machine` position, or a `build` block exists — **derived from history, never from what the document claims about itself** (R28). | **This project has already destroyed one benchmark exactly this way**, and pass 1's ground truth got tiles 128/129/130/148 wrong for precisely this reason. It goes into every exported file. | sweep.js:2107-2131; index.html:518-519 |
| **W6** | **`REFUSED — blank.`** *The matcher gets no vote here.* + `texture N < threshold M` + `Drop it by hand` / `Exclude it` — and, when it was placed anyway, *"**Placed anyway, at the solver's position** (x, y). Unverified, and it will not `S`-snap."* | The tile under judgement is in the blank list. | The refusal is a **standing fact about the pixels**, not a transient event, and it must be **re-asserted every time he returns to the tile** — otherwise a blank tile that now *has* a position (the solver's) looks placed and settled, with no warning at all. | sweep.js:1225-1270, 1808-1818; index.html:534 |
| **W7** | **`Small aperture (N anchors).`** *Check it in Difference (D) before you anchor.* | `n_anchors ≤ 2` on the tile under judgement. | At tile-pair aperture the exact-NCC winner is **> 20 px wrong 5 % of the time, at scores up to 0.760** (one measured pair scores 0.760 and is **757 px wrong**; the truth is the runner-up at 0.677). It fires only when the aperture is genuinely thin. | sweep.js:1788-1805; index.html:553 |
| **W8** | **`N stale`** — *matched against an anchor field that has since changed* + `Re-check` — and after a re-check, **`N disagree by > 5 px — go and look:`** with a clickable button per tile | Any tile is flagged `stale`. | These tiles are **still wrong and have NOT been moved**. The re-check is allowed to say **no** (R25). | sweep.js:2030-2105; index.html:568-571 |
| **W9** | **`N pass-1 tiles have no per-tile confidence. They cannot appear here at all.`** | Always, on the Place screen's worklist, whenever pass-1 tiles exist. | **The absence of a warning is not a clean bill of health.** t27's info is aggregate-only, and the **worst tile in the shipped 312/312 build (trial 127, 9.94 px) is a pass-1 tile.** This is a fact about the result in front of him, not a lecture. | sweep.js:3047-3055 |
| **W10** | **`No anchors left` — press A on a placed tile to certify one.** | The anchor set has just become empty (via un-anchor, R11.4). | With no anchors the matcher has **nothing to match against**. Without this he is one keypress from a dead sweep with no way out. | sweep.js:911-912 |
| **W11** | **`the anchor field disagrees with the solver by N px, but the match is confident (NCC …, margin …) — so the field wins. Check it (D) before you anchor.`** | A **confident** match lands > 20 px from the solver's answer. | One of the two is wrong and the app has just chosen. He is entitled to know it chose, and to look. | sweep.js:1169-1174 |

**Everything else is a `?`.** In particular: what the tone window *is*; why blanks are refused; what the
electrode grid does to aliases; why the app cannot judge blur; what `use cache` does; what each Advanced
knob does; the measured `why` behind the run detection and the pass split; and every paragraph that used
to sit on the Load screen.

---

## 6. WHAT WAS DELIBERATELY REMOVED — do not helpfully add it back

### 6.1 ⛔ THE APP'S KNOWLEDGE OF HIS 26 EXCLUDED TRIALS — above all
Deleted, at real cost, and **it must never come back in any form.** *(FIXES.md #2; CLAUDE.md.)*
- `class Ruling`, `detect_ruling()`, `RULING_DATASET` — gone from the loader.
- `doc_ruling_applies()`, `doc_excluded()`, `stamp_ruling()`, `EXCLUDED_RULING`, the `hard_excluded`
  seeding in `new_doc()`, the whole `EXCLUDED_TRIALS` block, and the hard validation *"tile 284 must be
  state 'excluded'"* — gone from the project module.
- `ruling` — gone from the session body and from `GET /api/session`.
- **"312 usable of 338 (26 thrown out)"** — gone from the UI. It reads **338 of 338**.
- `ruled_out` — gone from `_human_edits`. **Every** exclusion is now a human edit, which is finally true.
- ✅ **KEEP `gaps()`, and only `gaps()`** — a pure function over an arbitrary trial list. `compute_gaps()`
  must keep delegating to it and must never reimplement it.
- **There is no toggle.**
- ⚠️ **API.md is STALE here.** Its §4.2 example still shows `"excluded": {"trials": [284, …], "n": 26,
  "source": "hard-coded ruling", "locked": true}` and says *"`run.trials` is `usable_trials(lo, hi)`…
  the 26 thrown-out snapshots are never loaded"*. **That is the pre-ruling contract. It is wrong. Do not
  implement it.** The session serves **every** trial on disk in range.

### 6.2 The Screen step's bulk actions
`Tick all` · `Tick none` · `Exclude the ticked` · `applyBlank()` · the Apply button. **Gone** (R6b).
🔴 **A pre-ticked box under a primary button reading "Exclude the ticked" IS an auto-exclude.**

### 6.3 Any measure of blur, anywhere
No slider. No auto-reject. No "sharpness" number. **No variance-of-Laplacian value anywhere in the UI**
(R17). It scores **worse than chance** on this data.

### 6.4 The matcher's internal vocabulary
`refuse` / `refusal` / `score it` have left the **controls** (R6.8). The `REFUSED` *warning* (W6) stays —
that is a fact about the pixels, not a control.

### 6.5 A `force` flag on the blank refusal
**There is none and there will not be one.** A human may drag a blank tile by hand; the correlator may
not score it (R16).

### 6.6 DOM that must not come back *(sweep.js:3285-3291)*
`#load-result` (opening a directory **navigates**) · `#run-why` / `#split-why` (moved to `?`) ·
`#run-n-excluded` / `#run-n-in-range` (**the app excludes nothing at load**) · `#blank-measure` /
`#blank-thrsrc` / `#blank-margin` (folded into one `?`) · `#screen-build` / `#screen-export` (renamed
`place` / `mosaic`).

### 6.7 Space-to-pan
The bench had it. **This app does not**, and must not: `Space` is ADVANCE, the most-pressed key in the
product — and with `bindKeys:false` a `spaceDown` flag would never be cleared and every subsequent
left-drag would silently become a pan. Pan is middle-mouse, `Alt`+drag, or a drag on empty space
(viewer.js:1219-1225).

### 6.8 A client-side prefetch cache keyed on the trial number
**NEVER.** It is precisely how R21's correctness trap gets sprung, and it would look like a harmless
optimisation in review.

### 6.9 The backend ETA heartbeat (R8b)
Deliberately **not done**. With the current global-linear estimator a heartbeat makes the ETA **count
UP**. Do not add one until the estimator is phase-weighted **and re-driven on the CPU path**.

### 6.10 Dead engine calls
- ⛔ `quality.score_build()` and `quality.leaderboard()` **are dead** (`MROOT` points at a deleted
  directory). **They raise. Never call them.**
- ⛔ **Do NOT build the worklist on `quality.score_positions`** — on the ground-truth-perfect 312/312
  build it flags 11 tiles and **all 11 are false positives (precision 0/11)**. It is a tile-pair overlap
  NCC, the exact aperture t33 exists to escape.

### 6.11 `localStorage` as the autosave
It failed **silently** in the artifact sandbox and nearly cost him a day (R29). Autosave is a server file.

### 6.12 Per-tile tone
Never, not even for a thumbnail (R18).

### 6.13 Stack changes that were considered and settled NO *(SPEED.md)*
No native shell. No WebGL/WebGPU. No engine rewrite. No frame-loader or transport optimisation. And
**keep OpenCV even though it is 111 MB** — the obvious swap to scipy shifts the blank metric by 0.32 %
against a threshold whose nearest margin is **0.13 %**, and **it can flip a blank classification**.
Correct beats small.

### 6.14 Scale *(SCALE.md)*
No per-pass scale bar. No default `µm/px`. **Delete 1.237 µm/px** — it is the broken inference. Pixels
only, unless he types a number in, and then it is stamped **user-supplied by hand** (R30).

---

## 7. CONSTANTS THAT MUST NOT DIVERGE

Both halves hard-code these. *(API.md §1.1; sweep.js:156-216; viewer.js:71-73, 226.)*

```
TILE               = 512      px, square
FADE_MS            = 1000     the placement fade. THE FADE IS THE POINT — do not shorten it.
THIN_MARGIN        = 0.10     margin below this = the signature of a surviving alias. LOUD.
SNAP_RADIUS        = 64       local-search radius. NEVER widen past 128 in the UI (the grid aliases at 256).
MAX_CANDIDATES     = 9        ⭐ 9, not 8 — or key `9` can never fire.
UNDO_DEPTH         = 100
FOLD_MS            = 700      tagged undo folding
AUTOSAVE_MS        = 2000     debounce; PLUS unconditionally on every A and E
SCORE_DEBOUNCE     = 150      live NCC during a drag
POLL_MS            = 500      job polling
RECHECK_TOL_PX     = 5.0      the stale re-check's agreement tolerance
SOLVER_MARGIN_MIN  = 0.20   ⎫
SOLVER_NCC_MIN     = 0.65   ⎬  R15 — all three load-bearing, all three measured. Do not re-tune.
SOLVER_DISAGREE_PX = 10.0   ⎭
FEATHER_PX         = 40       the anchor-field alpha ramp (of 512). Floats are NEVER feathered.
FLOAT_ALPHA        = 1.00     default; slider range 0.15–1.00, step 0.05
UNVERIFIED_ALPHA   = 0.55     the layer's alpha IF it is ever drawn (in the sweep it is NOT — R9)
```

---

## 8. A PLAYWRIGHT SMOKE PATH THAT TOUCHES MOST OF THIS

The v1 verification runs did roughly this, in a real browser against the real backend. Reproduce it.

1. Open `data/drive/260620/260620_Imaging/260620d` → **338 trials, split 166, 0 excluded, gaps: none** (R2).
2. Hover a `?` → the tooltip appears, is not clipped by the pane, and `Escape` dismisses it (R3).
3. Screen: **15 cards**, each with three buttons, **exactly one selected**, default **Hand place** (R6).
4. `Exclude` on 289 → *337 unplaced · 1 excluded*, gaps **288→290** (R2.3, R6).
   `Keep` on 289 → un-excluded, gaps **none**, and the server's refusal list drops from 15 to 14 (R6.3).
5. Place → Run. The **ETA ticks down every second** and never freezes > 2 s (R8).
6. Sweep: canvas is **empty** (R9). `A` on 11 → origin (0,0). `Space` → 12 fades in **on top of** it.
7. Press **`Escape`**. Footer still reads `trial 12`. Then `Space` advances, `A` anchors, `E` excludes.
   **All three survive an Esc** (R14).
8. `A` on an already-anchored tile → it becomes `unverified`, **keeps its position**, and the banner
   names the stale count (R11).
9. `2` with no prior `V` → the tile matches first, then moves to the **2nd** peak; the rail reads `#2`;
   `1` restores it (R12).
10. Drag the opacity slider to 15 % → the floating tile dims. Press `D` → **the difference image does not
    dim** (R13.4).
11. `Ctrl+S` (headless: answer the `window.prompt`) → a project file with the cursor as an **integer**,
    **no `EXCLUDED_TRIALS` block**, and trial 284 present and **not** excluded (R2.4, R14).
12. **Kill the server.** Cold-start, `Load a project…` → *"Resumed — N anchored, M excluded."*, cursor
    restored, and the sweep continues (R2.6, R38).
13. Mosaic → Export → **7 files**, `positions.csv` row count = tiles − excluded, GT stamped
    `independent_of_method: false` (R28, R37).

---

*Sources: `archive/app-v1/FIXES.md`, `archive/app-v1/frontend/{sweep.js,viewer.js,index.html,style.css}`,
`archive/app-v1/{API.md,SPEED.md,SCALE.md}`. The archive is read-only; cite it, never edit it.*
