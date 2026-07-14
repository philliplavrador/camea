# Fix queue — user's testing pass (2026-07-14)

The user is driving the app on his laptop and reporting bugs/changes as he goes.
**Nothing here is applied until he says "update app"** — then all of it lands in one
pass and gets pushed.

Status: `[ ]` queued · `[x]` done & pushed

---

## ✅ ALL FIVE SHIPPED — 2026-07-14

He said "update app". All five landed in one pass.

**Verified by the user, driving the real window:** 338 trials load (not 312), pass split 166, 0
excluded; hover `?` shows the full explanation; the Screen step proposes 15 blanks, every box
unticked; ticking 289 printed `cut 288 -> 290  EXCLUSION GAP`; the solver ran 338/338 in 180 s;
the sweep held 0.7 ms/frame @ 59 fps; Ctrl+S and the top-bar Save both wrote a project file with
338 tiles, no `EXCLUDED_TRIALS` block, and trial 284 present and **not** auto-excluded.

**Verified afterwards, driving the shipped code against the shipped backend** (a Node `vm` running
the real `sweep.js` + `main.py --no-window`; this session had no desktop, so no pixels):

| what | result |
|---|---|
| `pytest analysis/tests/test_mosaic_312.py` — **the non-negotiable one** | **PASSES**, 193 s. The analysis tree still solves 312/312; `excluded.py` untouched. |
| 🔴 the `Esc` fix | **14/14** — Esc no longer nulls the cursor; Space/A/E all still work after it; `exportDoc().cursor` is non-null |
| Save (Ctrl+S) → **warm** resume | **20/20** — exclusions, anchors, cursor, gaps, build id, positions all restore |
| Save → **cold** resume (server with *no session*) | **7/7** — bootstraps a session from the file's own `data_dir` |
| Step 6 — Mosaic / export | **10/10** — 7 files; `positions.csv` 337 rows w/ 1 excluded; GT stamped `independent_of_method: false` |
| `node --check app/frontend/sweep.js` | clean; no debug probe left in `#cb-hint` |

✅ **That gap is now CLOSED (re-verified 2026-07-14, in a real browser).** The `vm`+stub harness above
could only prove the *handler*. The shipped `index.html`/`sweep.js`/`viewer.js` were then driven in a
real Chromium DOM against `main.py --no-window`, with **real key events**:

| what | result |
|---|---|
| `pytest analysis/tests/test_mosaic_312.py`, re-run from scratch | **PASSES** — `1 passed in 189.33s`, real exit code 0 |
| 🔴 physical `Escape` keypress | footer still reads **`trial 11`**, not `trial —`. Then **`Space` advanced 11→12**, **`A` anchored 12**, **`E` excluded 13**. All three survive an Esc. |
| cursor into the saved file | pressed `Escape` immediately before `Ctrl+S` → file records **`cursor: 14`** (Int32, **top-level**, not under `sweep`), not `null` |
| Save → **kill the server** → cold Load → resume | toast **"Resumed — 1 anchored, 1 excluded."**, cursor restored to **trial 14** |
| Step 6 — Mosaic / export, driven in the UI | **7 files** written (tif 18.2 MB, png 3.72 MB, coverage, gt.json, positions.csv, qc.json, qc.md). Mosaic renders real tissue — **and you can SEE the blanks poisoning it.** |

🔑 **How, with no desktop:** headless `/api/dialog/*` returns **501**, and `saveProject()`/`loadProject()`
both fall back to `window.prompt()` — which Playwright can answer. So the *whole* save→resume round-trip
is drivable. Caveat: **Chromium, not WebView2** (same engine; proves the JS, not the native dialogs).

---

## ✅ 6 · 6b · 7 · 8 SHIPPED — 2026-07-14 (his second "update app")

All four landed in one pass. **Front end only — no `.py` changed.** `test_mosaic_312.py` re-run
anyway: **PASSES** (`1 passed in 196.86s`).

**Driven in a real browser against the real backend. Not a typecheck.**

| what | result |
|---|---|
| Screen step: 15 cards, three-way control | every card renders `Keep · Hand place · Exclude`, **exactly one selected**, default **Hand place** |
| `Exclude` on 289 | 337 unplaced · 1 excluded · gaps **288→290** |
| `Keep` on 289 | un-excluded (gaps **none**) **and** refusal lifted on the server — list 15 → **14**, no longer contains 289 |
| `Hand place` on 289 | back in the refusal list (**15**), still in the mosaic |
| bulk buttons | **gone** (`Tick all` / `Tick none` / `Exclude the ticked`) |
| ⏱️ ETA, cold GPU build | ticks down **every second**: `2m 06s → 2m 05s → 2m 04s …`. Longest frozen stretch **9 s → 2 s**; distinct values while counting **7/30 → 30/35** |
| 7 sweep buttons | all 7 now carry a `?` (they shipped bare) |
| sweep still works | `Esc`→`Space` 11→12 · `Esc`→`A` anchored 12 · `Esc`→`E` excluded 13 |
| save → kill server → cold Load | **all three choices restore**: `Keep [300]`, `Exclude [289]`, `Hand place` ×13 |

**🔴 TWO REAL BUGS FOUND *WHILE DRIVING*, both mine, both fixed before commit:**
1. **The ETA still froze — for 9 s at a stretch.** `pollJob` fires `onTick` every 500 ms with the job
   object, which always carries the LAST `eta_s`. I re-anchored the countdown on *every* tick, so
   `etaAt = now` reset the clock and `left` recomputed to the same number forever. **The bug I was
   fixing, faithfully reproduced one layer up.** Fix: only re-anchor when the server's value actually
   *changes* (`sweep.js`, `etaSync`).
2. **The three-way control LIED about the frame's state.** `show()` never re-rendered the Screen list,
   so pressing `E` on a scanned frame *in the sweep* left its card still reading **"Hand place"** for a
   frame that was by then **excluded** (measured: tile 289 `status: "excluded"`, card `checked: "hand"`).
   Worse than the old checkboxes — a checkbox only claimed to be a *request*; this control claims to be
   **the state**. Fix: re-derive the cards on arrival (`sweep.js`, `show()`).

⚠️ **8(b) — the BACKEND half of the ETA — is deliberately NOT done.** A heartbeat would make it
*worse*: `eta = elapsed * (100 - pct) / pct`, so during a silent phase `pct` is pinned and re-emitting
with a growing `elapsed` makes the ETA **count UP**. It is only safe once the global linear
extrapolation is replaced by a phase-weighted one — which must be re-driven on the ~10-minute CPU path.
The front end delivers what he asked for ("constantly update the time remaining") without it.

---

## Shipped (detail, second pass)

### [x] 6. The Screen step's two tickboxes should be ONE control with three buttons
**His ruling, 2026-07-14:** *"I want a keep button, an exclude button, and a hand place button."*
Prompted by his own question — *"what does `score it` mean?"* — which is the bug: **the control cannot
be understood from the page.**

**Two problems, one cause.**
1. **One of the four combinations is a silent no-op.** `exclude` + `score it` does nothing, because an
   excluded frame has nothing to score. Two checkboxes offer 4 states; only **3** are real. That is the
   signature of a control that should be a **single-select**.
2. 🔴 **The default state is INVISIBLE.** Today "refused" is *the absence of two ticks* — it has no
   label, no box, no name anywhere on screen. The thing `score it` overrules is never shown. This is
   what made the tooltip load-bearing, and **ruling 3 says the control should carry the meaning, not
   the hover text.**

**The fix — three mutually exclusive buttons per card, named by HIS INTENT, not by the matcher's
mechanism.** "Refuse" is internal vocabulary (`engine._refusal`) that leaked into the UI. It goes.

| button | in the mosaic? | matcher places it? | today's equivalent |
|---|---|---|---|
| **Keep** | yes | **yes** | `score it` ticked |
| **Hand place** | yes | **no** — he positions it in the sweep, or it sits at the solver's guess | *neither ticked* (the unnamed default) |
| **Exclude** | **no** | — | `exclude` ticked |

* **`Hand place` stays the default** on a scanned blank. That is the app saying *"I don't trust myself
  on this one — you do it"*, which is honest and is the whole reason the scan **recommends** rather
  than deletes. It just finally says so out loud.
* **Behaviour is UNCHANGED** — this is a *renaming and re-shaping of the control*, not new semantics.
  `Keep` → `putRefusals()` lifts the refusal (matcher scores it; its pixels rejoin the composite).
  `Hand place` → the frame stays refused (`Space`/snap dead on it; pixels dropped from every composite).
  `Exclude` → `applyBlank()` as today.
* ⚠️ **Keep the two code paths SEPARATE.** `sweep.js:2425` warns that `applyBlank()` deliberately no
  longer touches the refusal list — conflating them once silently lifted the refusal on **trial 127**,
  the one frame in the list that genuinely misleads the matcher (**679 px out at NCC 0.66**). A single
  3-way control must still drive the *two* existing mechanisms, not merge them.
* ⚠️ **The overrule must still reach the server on EVERY path out of the screen** (`putRefusals` fires
  on any tick, on Apply, and on the way to Place). Do not regress that.

**[x] 6b. Drop the bulk buttons.** *His ruling, same breath.* `Tick all` / `Tick none` / `Exclude the
ticked` go. They only ever drove the `exclude` box, they have no natural meaning for a 3-way selector,
and **every flagged frame is meant to be LOOKED at before it is judged** — which is the entire point of
the Screen step. 15 cards is few enough to decide one at a time.

---

### [x] 7. Controls with NO `?` and no obvious meaning — ruling 3 is half-applied
**His ruling, 2026-07-14**, after asking what `use cache` does — the second control in a row he had to
ask about (see [#6](#6)). Ruling 3 moved every *paragraph* behind a `?`, but it never checked that
every **control** has one. A control with **no explanation on the page AND no `?`** is the gap: the
user cannot find out what it does at all, short of asking.

**Audited `index.html`: 65 interactive controls, 25 with no `?` nearby.** But the raw count understates
it — ⚠️ **the proximity heuristic gives FALSE PASSES**: `in-usecache` looked "covered" only because the
`?` on the adjacent `Skip — place by hand` button was within range. It has none of its own. **Do not
re-run a proximity scan and trust it. Check each control's own label.**

**The ones that actually matter** (opaque, and the user cannot guess them):

| where | controls | why it matters |
|---|---|---|
| 🔴 **5 · Sweep** — the heart of the app | `Anchor A` · `Exclude E` · `Next Space` · `Replay R` · **`Difference D`** · **`Alternatives V`** · **`Snap S`** (`index.html:197-203`) | **All 7 are bare.** `Difference`, `Alternatives` and `Snap` are the least guessable controls in the app and they sit on the screen he spends the hour in. Fix these first. |
| 4 · Place | **`use cache`** (`index.html:359`) | The one that triggered this. It is a **speed** switch, not a correctness one: warm ≈ **25 s** vs cold ≈ **3 min**. Safe to leave on — t33's cache filename carries a hash of the **trial list + config** and a mismatch is **refused, not repaired** (`t33.py:177`), so excluding a frame changes the key and forces a recompute. It **cannot** serve a stale answer for a different input. Untick only to force a cold rebuild. |
| Tone (top bar) | `tone-hi` · `btn-tone` · `btn-tone-auto` (`:160-162`) | What the tone window *is*, and that a reload invalidates it. |
| 4 · Place → Advanced | `cfg-look` · `cfg-min-side` · `cfg-t27-conf` · `cfg-t27-runconf` (`:416-419`) | Raw t33 knobs. The drawer already warns they are off the validated path; each still needs its own `?`. |

**Explicitly FINE without a `?` — do not add noise:** the 6 wizard step buttons, `Fit`, `1:1`,
`in-exportdir`, `btn-export-dir`, `in-basename`. These say what they do.

⚠️ **Scope note:** this is `index.html` only. `sweep.js` builds the Screen cards and the evidence rail
**in JS** (e.g. the `score it` tooltip is a bare `title=` attribute at `sweep.js:2353`, not the `.help`
component) — so a `?` audit must cover the **JS-built** controls too, not just the static HTML.

---

### [x] 8. Step 4 · Place — the ETA is FROZEN, not slow. Make it count down continuously.
**His ruling, 2026-07-14:** *"upgrade the progress bar. make it constantly update the time remaining."*

**The bar is not lying — it is stuck.** The front end already polls **every 500 ms**
(`POLL_MS = 500`, `sweep.js:213`) and dutifully re-renders `job.eta_s` (`sweep.js:2555`). But
**`eta_s` is only RECOMPUTED when the child process prints a recognised stdout line**
(`engine.py:1300`, inside `_progress`, which is called only from the stdout parser). Between two
narration lines the value is **constant**, so the UI redraws the identical `~901 s left` twice a second
for minutes.

His screenshot is the proof: `[swim] 12,090 pairs in 205.9s (CPU)` is **ONE line, emitted after 205.9 s
of total silence.** Nothing on screen could move during it.

**Second flaw — the estimate itself is naive.** `engine.py:1300`:
```py
eta = (el * (100.0 - pct) / pct) if pct > 2.0 and pct < 100.0 else None
```
A whole-job linear extrapolation: it assumes the remainder runs at the *average rate so far*. The
phases have very different rates (CPU SWIM vs the anchor loop vs the composite matches), and `pct` is
already **phase-weighted** (`self.w`) — so crossing a phase boundary makes the ETA **jump**.

**The fix — two independent halves. (a) alone satisfies his ask and needs NO backend change.**

**(a) FRONT END — tick it down locally between polls.** The server already returns **`eta_s` *and*
`elapsed_s`** (`jobs.py:122-123`). On each poll, store `(eta_s, receivedAtMs)`. Run a **1 Hz local
ticker** that renders `max(0, eta_s - (now - receivedAtMs)/1000)`, and **re-sync** whenever a fresh
server value arrives. The number then moves every second and can never look frozen.
* Clamp at **0** — never show a negative. When it hits 0 and the job is still running, show
  `almost there…`, not `-437 s left`.
* Re-sync on *every* new `eta_s`, including a **jump upwards** — an honest revision beats a smooth lie.
* Also give `#build-fill` a CSS `transition: width .5s` so the **bar glides** instead of stepping.

**(b) BACK END — make the estimate honest (optional, do it second).**
* **Heartbeat.** Emit a `progress` message on a timer (~2 s) even when the child prints nothing, so
  `elapsed` advances and `eta_s` is recomputed. Today the ETA is a pure function of stdout.
* **Phase-weighted remainder.** Stop extrapolating globally. `self.w` already encodes the expected
  shape of the build, and `engine.py:1511` **already selects a different curve for GPU vs CPU** — use
  elapsed-within-phase plus the remaining phase weights instead of `el * (100-pct)/pct`.

🔴 **DO NOT REGRESS THE THING THIS MACHINERY ALREADY FIXED.** `engine.py:1144` documents it: `pass1`
and `backbone` once emitted **no `frac` at all**, so `pct` was pinned and `eta_s` was `None` (the ETA
needs `pct > 2`). On the **CPU-only path — the shipped default install — the bar sat at 0.0 %, with no
ETA, for 3 min 40 s**, with a Cancel button to hand. *"A lab-mate who cancels that has cancelled a
build that would have produced 312/312."* The ETA is parsed from **t33's stdout narration** and is
fragile by construction. Any change here must be re-driven on the **CPU** path, not just the GPU one.

---

## Shipped (detail)

### [x] 1. The yellow "What was detected" banner has broken spacing
**Where:** `app/frontend/style.css:376` (`.warn`), used by `app/frontend/index.html:230`.

**Symptom:** the banner reads as disjoint blocks — `Both rules below are` | `measured` |
`, and both are validated on` | `n = 1 dataset` | `. Check them…` — each in its own column
with a gap, wrapping independently.

**Cause:** `.warn { display: flex; gap: 8px; }`. Flex makes every child (including the two
`<b>` tags and the bare text nodes between them) a **flex item**, so each gets its own box
and an 8px gutter. The flex layout was for an icon+text warning; this banner is plain prose.

**Fix:** `.warn` → `display: block`. Check the other `.warn` / `.warn.loud` / `.warn.info`
call sites (sweep evidence panel, export) still look right — if any relies on flex for an
icon, wrap its text in a `<span>` instead of keeping flex on the container.

---

### [x] 2. ⭐ THE APP MUST CARRY NO DATASET KNOWLEDGE. Exclusions live in the project file.
**His ruling, 2026-07-14, verbatim:** *"I want the app to only remember data if I upload
its like save file for this run. Like, the save file should be with also exported so I can
resume the session at another time, but it can also have the exclusions and everything.
There should be no toggle. The app itself shouldn't store the exclusions for this
experiment."*

**Why this is a real bug, not a preference.** The app hard-codes *his* answer to the exact
question it exists to help him answer. Open 260620d today and 26 frames are gone before he
has seen one — so the Screen step and `E` (the whole point of the app) are short-circuited on
the one dataset he has. He is testing it as a first-time user and cannot.

**What must change — it is mostly DELETION.** The app is a general tool; the only thing that
may ever exclude a frame is (a) the human, in this session, or (b) a project file he loaded.

* `app/backend/loader.py` — delete `class Ruling` (:84), `detect_ruling()` (:138) and
  `RULING_DATASET`. `usable_trials(...)` (:587) returns **every trial in range that is on
  disk**. The session's `ruling` / `excluded` blocks go, or go empty.
* `app/backend/project.py` — delete `RULING_DATASET` (:204), `doc_ruling_applies()` (:207),
  `doc_excluded()` (:245), `stamp_ruling()` (:268), `EXCLUDED_RULING` (:98), the
  `hard_excluded` seeding in `new_doc()` (:405-438), the whole `EXCLUDED_TRIALS` block
  (:460-488), and the hard validation *"tile 284 must be state 'excluded'"* (:964-970).
  In `_human_edits` (:748), `ruled_out` disappears — **every** exclusion is now a human edit,
  which is finally true.
  ⚠️ **KEEP** `import excluded as _excluded` for `_excluded.gaps()` only. That is a pure
  function of an arbitrary trial list (it finds non-consecutive pairs); it holds no dataset
  knowledge and `compute_gaps()` must keep delegating to it, never reimplement it.
* `app/backend/server.py` — drop `ruling` from the session body (:397-400 area).
* `app/frontend/` — the Load card must stop saying "312 usable of 338 (26 thrown out)". With
  no exclusions it reads 338 of 338. The gaps card correctly goes to "none" until he excludes
  something.

**What must KEEP working (verify by driving it):**
* `analysis/ground_truth/excluded.py` is **untouched**, and `analysis/tests/test_mosaic_312.py`
  **must still pass**. The ruling stands for the analysis tree — the notebooks, t33, the
  benchmark. It is only the *app* that stops consulting it. `t33` takes its trial list as an
  argument and hard-codes nothing, so it is unaffected.
* **Save → close → Load → resume** must restore exclusions, placements, cursor and the build.
  The plumbing already exists (`POST /api/project/save` / `/load`, `Save project…` /
  `Load project…` on the Export screen, plus the rolling autosave) — but it now carries the
  *whole* memory of a run, so re-verify the round-trip end to end.
* Excluding a tile still opens an acquisition gap and still marks the build **stale**
  (`mark_stale_if_input_changed`). That machinery is generic and stays.

**Expect the fresh-user build to be WORSE, and that is correct.** With the 26 back in the
input, the solve degrades (this is the measured 19.2 % → 37.2 % effect, running backwards).
He should be able to *see* it being worse, tick the blanks at Screen, `E` the blurry ones in
the sweep, and rebuild.

---

### [x] 3. ⭐ STRIP THE PROSE. Explanations go behind a hover `?`, not on the page.
**His ruling, 2026-07-14:** *"all over the app, there's way too much information being
presented on every single widget and page. Instead just make it like a normal app with the
buttons, where they expect the user to know what's going on — but wherever it's important or
helpful, have a little hover question mark where the user can read exactly what this button
does. That way, when an experienced user is using it, it's not so much information presented
all the time. Assume the user knows. If they don't, they have the option to hover."*

**The rule.** Every explanatory paragraph currently rendered on the page becomes the *body of
a tooltip* on a small `?` next to the thing it explains. Nothing is deleted — it moves. The
page shows the **number, the label, the button**; the `?` shows the *why*.

**Build one component, use it everywhere:** `<span class="help" data-help="…">?</span>` —
an 14px muted circle, CSS/JS tooltip (no library), keyboard-focusable, dismissed on blur/Esc.
Must work in WebView2. Put it in `style.css` + a tiny helper in `sweep.js`.

**Worked example — the Load screen** (the worst offender, ~32 prose blocks across the app):

| now | after |
|---|---|
| "A vscope acquisition directory: trial `.dat` files plus `log.txt`. Nothing in it is ever written to." | *(gone from the page — `?` on the DIRECTORY label)* |
| the whole yellow "Both rules below are measured…" banner | *(gone — a `?` next to the "What was detected" heading)* |
| "longest contiguous block of Snapshot trials (3 blocks found: 1, 5-7, 11-348)" | *(behind the `?` on THE MOSAIC RUN)* |
| "largest interior inter-trial gap: 166->167 is 20 s (median 2 s). Candidates are restricted to…" | *(behind the `?` on PASS SPLIT)* |
| "Consecutive pairs that are not one acquisition step apart. The serpentine one-axis step prior…" | *(behind the `?` on ACQUISITION GAPS)* |
| "A reload invalidates the build, the tone window and the scan." | *(behind a `?` on the **Apply & reload** button)* |
| **11–348**, **166**, **283→297 298→311**, the field boxes, the buttons | **stay — these are the data**|

Apply the same treatment to Screen, Build, Sweep (the right-hand evidence rail is dense) and
Export.

**🔴 THE ONE EXCEPTION — a LIVE WARNING ABOUT THE CURRENT STATE IS NOT AN EXPLANATION, AND IT
STAYS ON THE PAGE.** These fire only when something is actually wrong, they change what he
would *do*, and burying them behind a hover would be a regression, not a decluttering:

* **`build is STALE`** + its reason (he excluded a tile; the positions were solved on a
  different input — he must re-solve or knowingly not).
* **`margin_thin` (< 0.10)** on a placement — the signature of a surviving alias. `.warn.loud`
  keeps pulsing.
* **the divert banner** (the matcher was overruled by the solver on this tile).
* **`autosave: FAILED`.**
* the **provenance warning** on a GT export.

The *background* to each of those may go behind a `?` on the warning itself; the fact that it
is happening, right now, may not.

**Scope:** `index.html` (555 lines, ~32 prose blocks), `style.css` (the `.help` component),
`sweep.js` (the rail + toasts). Nothing in the backend changes.

---

### [x] 4. ⭐ ONE QUESTION PER SCREEN. Six steps, in order.
**His ruling, 2026-07-14:** *"make it more intuitive by making it more step by step. like first
load the data. then give the user a concise numerical data summary. then have the user select
what snapshot range they want. then tell them about recommended exclusions. then have them run
the algorithm. then have them build the mosaic."*

The old Load screen asked everything at once — directory, range, pass split, and a contact sheet
— in one wall. Split it. **The step header becomes a progress indicator, not a menu: a step is
locked until the one before it is reachable.**

| # | screen | the ONE question it asks |
|---|---|---|
| 1 | **Load** | which directory? (…or resume: **Load a project…**) |
| 2 | **Range** | the numbers, then: which trials are the mosaic? |
| 3 | **Screen** | which frames do you want thrown out? (the scan recommends; he ticks) |
| 4 | **Place** | run the solver |
| 5 | **Sweep** | ⭐ the heart — A / E / Space over the 1 s fade |
| 6 | **Mosaic** | build the outputs |

Renames: `screen-build` → `screen-place`, `screen-export` → `screen-mosaic`; new `screen-range`
carved out of `screen-load`. `#load-result` is gone — opening a directory now *navigates* to
Range. `btn-load` ("Load a project…") moves to **Load**, because resuming a session is a way of
*starting*, not a way of exporting.

The numeric summary is a `.facts` strip: **Trials · Range · Pass split · Gaps**. Numbers only;
every explanation behind its `?`.

---

### [x] 5. Save must be reachable from EVERY screen.
**His ruling, 2026-07-14:** *"make it so at any time in the process I can export the save file so
I can resume later."*

`btn-save` moves from the Mosaic screen into the **top bar**, where it is visible on all six
steps, plus **`Ctrl+S`**. `btn-load` ("Load a project…") stays on the **Load** screen — resuming
is a way of *starting*.

**Why it matters more than it looks:** since [#2](#2) the project file is the app's *only* memory.
Burying it behind the last step meant the one artefact that makes a session resumable was the one
thing he could not reach mid-session. An hour into a sweep is exactly when he wants it.

The rolling autosave stays where it is and keeps its own note on Mosaic — it is a crash net, not
a file he controls. Do not let the two read as the same thing.
