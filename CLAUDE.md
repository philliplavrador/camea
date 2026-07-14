# Camea — project conventions

Microscopy / optical-imaging analysis (**vscope** + **spectralign**). The active work is
aligning and stitching snapshot subregions into a mosaic via spectralign **SWIM**.
Windows; Python via **conda** (env `camea`). Not a git repo.

## ❓ ASK WITH THE `AskUserQuestion` TOOL — not in the chat body.
**His rule, 2026-07-12.** Whenever you need a decision from him, put it through the **AskUserQuestion
tool**, not a numbered list in prose. He wants to *click*, not compose replies. Applies to every
question you'd otherwise ask in the message body — design forks, clarifications, "which of these do
you want". Batch them (the tool takes up to 4 at a time) and keep firing follow-up calls rather than
dumping a wall of prose questions. Give real options with real trade-offs in the `description`; lead
with your recommendation and mark it `(Recommended)`.
Prose is still right for a *statement* he needs to read (a caveat, a correction, a result) — the rule
is about **questions**.

## ✂️ ANSWER CONCISELY. The user asks for detail if he wants it.
**His rule, 2026-07-12.** Lead with the result. Cut the background, the caveats, the alternatives
considered, the reasoning tour — he will ask. A few lines beats a few paragraphs, every time.
Exception: **never** hide a caveat that changes what he'd *do* (a refused action, an unverified
number, a broken control). State it in one line, not five.

## ⛔ 26 SNAPSHOTS ARE THROWN OUT. NEVER USE THEM. FOR ANYTHING.

**The user's ruling, 2026-07-11: _"i want these tiles to be thrown out and to never be used for any
purposes whatsoever"_.**

```
284 285 286 287 288 289 290 291 292 293 294 295 296 299
300 301 302 303 304 305 306 307 308 309 310 348
```

This is stronger than "don't score them". **These frames are not data.** Never load them, never feed
them to a placement method, never let them vote in a solve, never render them into a mosaic, never
"rescue" them with a clever metric.

- **Get the trial list from `analysis/ground_truth/excluded.py`** — `usable_trials(lo, hi)`. Never
  hard-code a range. Canonical counts: pass 1 = **156**, pass 2 = **156** (not 182), 11–348 = **312**
  (not 338). Every score must state its denominator.
- **Why:** 11 are **blank** (near-featureless glare; what two blank frames share is *fixed-pattern
  sensor structure*, which does not move with the stage — so they correlate at zero shift no matter
  where the microscope was, and register *confidently* and *wrongly*). 15 are **too blurry** — the
  user's eye, and **no automatic sharpness measure reproduces that call**, so do not "correct" the
  list from a metric. (297 and 298 sit inside the blurry run but he judged them usable. They stay.)
- **This is not cosmetic.** Feeding them in was actively poisoning the solve: removing them from the
  *input* took T27 from **19.2 % → 37.2 %** on pass 2 and **23.4 % → 39.7 %** on 11–348.
- ⚠️ **Consequence:** trial number is still acquisition *order* but is no longer *contiguous* — gaps
  open at **283→297** and **298→311**. A "consecutive" pair across a gap is a multi-step jump and the
  serpentine one-axis step prior does **not** hold there. Detect the gaps; don't assume them away.

## Read the knowledge base first
This project keeps a cross-session knowledge base at **`utils/knowledge/`** — shared
memory between all Claude chats on Camea. A SessionStart hook auto-injects its `INDEX.md`
plus the latest `worklog.md` handoffs into every new chat. **If you don't see them at the
top of the session, read `utils/knowledge/INDEX.md` and the top of
`utils/knowledge/worklog.md` yourself before starting** — build on prior work, don't restart it.

- ⭐ **Pass 1 is solved; the mosaic as a whole is NOT** (2026-07-11). 260620d is **two serpentine scans
  of the same tissue**: pass 1 = trials 11–166, pass 2 = 167–348. `analysis/mosaic/t27.py`
  (`t27.place(trials, frames)`) scores **156/156 = 100 % on pass 1** — but only **37.2 % on pass 2**
  and **39.7 % on 11–348**. To build a mosaic: **`analysis/build_mosaic.ipynb`**.
  - **The ground truth is `analysis/ground_truth/`** — three human-authored truths (pass 1, pass 2,
    merged 11–348), hand-placed by the user, tied together by a translation **measured from pixels
    four ways**. Read its `README.md` before touching any of it. The **archived** GT under
    `analysis/archive/challenge_2026-07/benchmark/ground_truth/260620d.json` is **T27's own output** —
    never use it as a reference.
  - **A NEW CHALLENGE IS LIVE**: `analysis/benchmark/` (scorer + anti-cheat gate + results) and
    `analysis/builds/` (team brief + round harness). Target: **312/312 on trials 11–348**. Say
    `beat challenge`. The *old* challenge (11–166) is archived at
    `analysis/archive/challenge_2026-07/` and is history — don't restart it.
  - Read `utils/knowledge/pass2-and-11-348.md` before ANY placement work.
- **While working:** record durable facts (structure, decisions, data formats, gotchas,
  the *why*) in the relevant `utils/knowledge/` file — capture liberally; the user does not
  browse it. Prefer updating an existing note over duplicating; delete notes proven wrong.
  Skip secrets and anything the code already makes obvious.
- **Leaving off:** add a short dated handoff to the **top** of `utils/knowledge/worklog.md`
  (what you did / decided / what's next), so the next chat continues from there.

## Where things go
Keep the repo root clean. Files land by kind:
- **`utils/`** — Claude's infrastructure. `knowledge/` (the KB above), `vendor/` (vendored
  reference packages + wheels), `tools/` (e.g. the rclone data sync), `artifact/` (the
  hand-placement bench page builder). **All notes, plans, and scratch analysis go here** —
  never at the project root.
- **`analysis/`** — the working code tree (shared by user + Claude). **`build_mosaic.ipynb`** (⭐ the
  shipped mosaic builder — config cell → Run All), `run_swim.ipynb` (the SWIM subregion pipeline),
  the `mosaic/` package (`io`/`match`/`solve`/`render`/`quality`/`run` + **`t27.py`**, the placement
  method), `archive/` (finished work — incl. `challenge_2026-07/`, the whole placement challenge:
  team scripts, harness, benchmark, ground truth, build outputs), and its own `output/` (runs land here).
- **`learn/`** — beginner-friendly plain-language explainers the user loves (analogy-first,
  jargon on hover; he's a biologist with little math). Read `learn/README.md` and use the
  `/learn-add` command before building or extending one.
- **`output/`** (root) — a few user-facing rendered PNGs. **`data/`** — the raw data mirror
  (rclone mirror of a public Google Drive folder, ~35 GB); **never write here**.

The old convention called Claude's directory `cl/`; it was renamed to `utils/`. Don't
recreate `cl/`. (Dated worklog entries still mention `cl/` as a historical record — that's fine.)

## Environment
- Python is managed with **conda**; the working env is **`camea`** (Python 3.12; has
  spectralign + vscope + CuPy installed). `conda` is not on PATH, and activation is finicky
  on Windows (matplotlib/CUDA DLL-load gotchas). **Read `utils/knowledge/environment.md`
  before running Python** — it has the exact activation recipe and headless-run pattern.
- The vendored `spectralign` / `vscope` under `utils/vendor/` are references (source +
  wheels) and are also installed in `camea`. `vscope` has no upstream docs, so its vendored
  source *is* the documentation — see `utils/vendor/README.md` for the API index.
