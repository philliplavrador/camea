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

⚠️ **The one thing NOT re-verified in pixels:** the physical `Esc` keypress travelling
WebView2 → viewer.js → `onSelect(null)`. That hop was already *proven live* — it is how the bug was
found — and only the sweep.js handler on the far end changed, which is what the 14/14 above executes.

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
