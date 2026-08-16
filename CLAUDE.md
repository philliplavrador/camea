# Camea — project conventions

**Camea is a Windows desktop app for microscopy analysis.** It opens on a **project manager**
("what do you want to do today?" — create / open / rename / delete projects). A **project = one
dataset + one task**; the first task is a **human-verified mosaic builder** (machine places a first
draft → sweep to confirm/correct/exclude → **Recompute** re-places the rest against your anchors →
export), the second is a fully automatic **video mosaic**. More tasks will follow (segmentation,
annotation); they share a common core. ⚠️ **The project-manager reframe + the Recompute tool landed
2026-07-24 (branch `revamp`)** — read `utils/knowledge/mosaic-builder-direction.md` first for the
current shape and the *why*.

⭐ **STORAGE — HIS RULING OF 2026-08-10 (BEHAVIOUR R44). Read R44 before touching anything that
writes.** *"Camea saves project-specific files to its own repo automatically, and if users want to
browse their project data they have to do it through the app itself."* A project lives in
**`%LOCALAPPDATA%/Camea/projects/<analysis_id>/`** and the user is **never** asked where it goes — he
names one path, the **data**. Everything a feature builds lands in `<project>/outputs/`, and the
**Outputs panel** is the only way to browse it: tick files, name a folder, take a copy. ⛔ There is
no "Open folder", no `fs/reveal`, no save-folder box, and no drafts. **This reverses R42/R43** — do
not "restore" a save path you find referenced in an older note.

The active work is **developing this app**. This is a **public git repo** (GPL-3.0-or-later,
GitHub `philliplavrador/camea` — formerly `camea-mosaic-builder`). The tree you work in *is* the
repo you publish: no deny-all allowlist, just a normal `.gitignore`.

## ❓ ASK WITH THE `AskUserQuestion` TOOL — not in the chat body.
**His rule, 2026-07-12.** Whenever you need a decision from him, put it through the **AskUserQuestion
tool**, not a numbered list in prose. He wants to *click*, not compose replies. Applies to every
question you'd otherwise ask in the message body — design forks, clarifications, "which of these do
you want". Batch them (the tool takes up to 4 at a time) and keep firing follow-up calls rather than
dumping a wall of prose questions. Give real options with real trade-offs in the `description`; lead
with your recommendation and mark it `(Recommended)`.
**Keep the jargon out of the question itself** — he is a biologist with little maths, and
*serpentine*, *homography*, *phase correlation*, *idempotent*, *anchor* and *lease* each cost a round
trip. The technical reasoning goes in the prose above, where reading it is optional. If he asks what a
word means, define it and **re-ask** — don't answer and move on as though it were settled.
The long form, with the words that have actually tripped him up, is in
[workflow/README.md § Asking the author a question](workflow/README.md#asking-the-author-a-question).
Prose is still right for a *statement* he needs to read (a caveat, a correction, a result).

## ✂️ ANSWER CONCISELY. The user asks for detail if he wants it.
**His rule, 2026-07-12.** Lead with the result. Cut the background, the caveats, the alternatives
considered, the reasoning tour — he will ask. A few lines beats a few paragraphs, every time.
Exception: **never** hide a caveat that changes what he'd *do* (a refused action, an unverified
number, a broken control). State it in one line, not five.

## ⛔ THE APP CARRIES NO DATASET KNOWLEDGE.
**His standing ruling — enforced at real cost.** The app must know *nothing* about any particular
dataset. No hard-coded trial numbers, ranges, or counts; no exclusion list; no per-dataset special
cases. It opens a dataset as *N frames on disk* and derives nothing. The only things that exclude a
frame are the user (this session) or an analysis he loaded.
- This is **structural**, not conventional: `src/camea/engine/excluded.py` contains only `gaps()`
  (a pure function of trial numbers). Never import `EXCLUDED`/`BLANK`/`BLURRY`/`usable_trials` into
  app code. Tests assert 260620d opens as **338 trials / split 166 / 0 excluded**; **312 is
  something the *user* produces** by pressing `E`, never a default.
- Numbers inside `tests/` and inside `src/camea/engine/` (the guarded science) are fine. In the app,
  a hard-coded dataset number is a violation.

## ⛔ 26 SNAPSHOTS ARE THROWN OUT — for the RESEARCH tree, never used for anything.
**His ruling, 2026-07-11:** trials `284 285 286 287 288 289 290 291 292 293 294 295 296 299 / 300 301
302 303 304 305 306 307 308 309 310 348` are **not data** — never loaded, scored, or rendered in the
*analysis/research* work. Get the trial list from `usable_trials(lo, hi)` in
`archive/analysis/ground_truth/excluded.py`; never hard-code a range. Canonical counts: pass 1 =
**156**, pass 2 = **156**, 11–348 = **312**. (11 are blank — fixed-pattern sensor structure that
registers confidently and wrongly at zero shift; 15 are too blurry by his eye, which no automatic
metric reproduces. 297/298 sit in the blurry run but he judged them usable — they stay.) Trial
number is acquisition *order* but not contiguous — gaps open at 283→297 and 298→311.
⚠️ This governs the **research tree under `archive/`**. The **app** stopped consulting it (see the
ruling above); that is deliberate and correct — they are two different rules for two different trees.

## The 312/312 solver guard is sacred.
`tests/slow/test_solver_312.py` (marked `@slow`) runs the placement engine cold and asserts 312/312
tiles within 10 px of the hand-authored ground truth, and pass-1 deviation exactly 0. It needs the
35 GB data mirror + a GPU, so it **cannot run in CI** — it runs locally (~130 s). It is the only
thing between a refactor and silently breaking the science. **If it goes red, stop — do not fix
forward.** The engine (`src/camea/engine/{t27,t33,quality,render}.py`) is byte-identical to the
research original; do not reformat or "improve" it.

## Environment — uv, not conda.
Python is managed with **uv** (Python ≥ 3.12 — mandatory; spectralign needs it). From the repo root:
`uv sync --extra gpu` then `uv run camea` / `uv run pytest`. **The GPU extra must be
`cupy-cuda12x[ctk]`** (what `--extra gpu` installs) — plain `cupy-cuda12x` silently falls back to
NumPy. Proven: `uv run` gives `t27.on_gpu() == True` with no DLL surgery.
⭐ **THE BACKEND DOES NOT PICK UP YOUR CHANGES BY ITSELF — start it with `--reload`.**
uvicorn watches nothing: a running `camea` serves the Python it imported at startup, so after an
edit under `src/camea/` the app answers happily *in the old code*, and the only symptom is that
what you changed appears not to have happened. **Always start the dev backend as
`uv run camea --headless --reload --port 8000`** — that watches `src/camea/` and restarts the
server itself. `--reload` works in **all three modes**, `--window` included (it reloads the
backend; the window's UI is the built bundle in `web/dist`, which it does not rebuild). The Stop hook's **`stale-app`** gate is the backstop: it blocks the turn
when a backend is listening but started before your newest change, and when the Vite server is up
with no backend behind it — a page that loads, paints, and answers nothing. Never tell him something
is done off a click-through against a stale server. (The frontend needs none of this; Vite
hot-reloads. The rule was written 2026-08-15, after a session shipped a whole feature and left the
backend stopped — his first words on looking at it were *"i dont see the updates"*.)

The frontend (`web/`) is TypeScript + React + Vite; Node 22. Its API client is **generated** from
the backend's OpenAPI schema (`cd web && npm run gen:api`; `npm run check:api` fails on drift) —
never hand-write a backend-owned type. Dev loop and stack are in `docs/FRONTEND.md`.

## Where things go
```
src/camea/       the app (one installable package)
  core/          the shared core every feature reuses: dataset · frames · workspace · document · jobs
  engine/        the placement science (t27/t33) — the guarded, byte-identical original
  features/      what you can DO to a dataset; mosaic/ is the first. New features go here.
  api/           FastAPI + schemas.py (the contract the TS client is generated from)
web/             the frontend (TS/React/Vite). Feature UIs under web/src/features/.
tests/           unit · api · slow (the guard) · fixtures/ (a committed ~5.6 MB synthetic dataset)
docs/            BEHAVIOUR.md (the ~44 rulings) · MAXWELL.md (the MEA hardware reference —
                 read before any activity/silence/geometry work) · SPLIT.md · ENGINE_MOVE.md ·
                 API.md · FRONTEND.md
workflow/        ⭐ how work gets from an idea to a commit: plans · issues · hunts · said. TRACKED.
scripts/         the small node tools the workflow runs (claim-number, check-links, ship, …). TRACKED.
.claude/         slash commands · review subagents · gate hooks. TRACKED (settings.local.json is not).
archive/         finished research + the previous app (app-v1). GITIGNORED, kept for reference.
utils/           Claude's infrastructure (knowledge base, vendored refs, rclone). GITIGNORED.
data/            the ~35 GB read-only rclone mirror. GITIGNORED. NEVER WRITE HERE.
```
Keep the repo root clean. Claude's **notes and scratch** go under `utils/`, never at the root —
but the **workflow** (`workflow/`, `scripts/`, `.claude/`) is tracked and public on purpose: a plan
queue that doesn't survive a clone isn't a queue. See the section below.
The old research tree (`analysis/`) and the old vanilla-JS app (`app/`) now live under `archive/` —
they are reference, not live code. Don't edit them; the live engine is `src/camea/engine/`.

## ⭐ `workflow/` — plans, issues, hunts. Imported 2026-08-13.
**Read [workflow/README.md](workflow/README.md) before filing anything.** The system came over from
the Labstock repo at the author's request and is adapted to Camea's stack and rulings.

**A feature is a plan; a defect is an issue; both are files in directories, and the directory IS the
state.** `/plan` interviews him and queues one; `/build` takes it, builds it in this checkout on
`master`, and commits as it goes; `/resolve` triages the issue pile; `/bug-hunter` sweeps unattended
overnight and files what a panel of skeptics could not refute. `/start-work` → `/preview` →
`/commit-work` → `/show-commits` is the **pile** flow for work he asks for by name.

**Any session may file an issue without asking** — that is what the directory is for. Claim the
number with the script, never by counting the directory:
```bash
node scripts/claim-number.js issue <high|medium|low> <slug>    # prints the path it created
node scripts/claim-number.js plan <slug>
```
Then say in one line that you filed it. Don't file what you can fix in the same turn, and don't file
a feature request — that's a plan.

**Tiers are judged against the two things this repo protects**: the science, and the hours of
hand-verification sitting in a saved project. Camea has no users, so severity is never "somebody's
morning". [Four things are always `high`](workflow/issues/README.md#the-four-that-are-always-high):
dataset knowledge in the app · a write to `data/` · a change to the guarded engine · a write outside
`<project>/outputs/`.

**Branches:** no long-lived fork off `master` to build one feature and merge back, no shared review
branch, and **no worktree a session invents for itself**. The two that exist are created and removed
by their own tooling — `/bug-hunter`'s read-only snapshot and `/preview`'s working copy.

**The gates run themselves.** A Stop hook runs the checks your changes make relevant and blocks the
turn on a red one. The Python suites (3m26s) are too expensive per-turn, so they are reported as
**owed** rather than run — `/build` and `scripts/ship.js` run them. Nothing ever runs the 312/312
guard automatically; `scripts/check-engine.js` does the cheap half instead (53 ms) by proving the
four guarded files are still byte-identical to `archive/analysis/mosaic/`.

## The rulings live in `docs/BEHAVIOUR.md`.
The ~44 decisions the user paid days to discover (Esc must not kill the sweep; the solver-fallback
constants; blanks refused not scored; the prefetch must not be client-cached; difference mode clears
to black; save from any screen; …) are captured there as testable statements, each backed by a
Playwright test in `web/tests/e2e/`. Read it before touching the mosaic UI. Do not "improve" a
ruling away; if one seems wrong, ask (via the tool) — don't silently change it.

## Read the knowledge base first
Cross-session shared memory lives at **`utils/knowledge/`** (gitignored). A SessionStart hook
injects its `INDEX.md` + the latest `worklog.md` handoffs into every new chat. If you don't see them,
read `utils/knowledge/INDEX.md` and the top of `utils/knowledge/worklog.md` yourself before starting.
⚠️ Notes written before the 2026-07-14 revamp describe the *old* `app/` + `analysis/` layout (now
under `archive/`) and conda — treat their paths and env instructions as historical; the current
truth is this file. **While working:** record durable facts in the relevant `utils/knowledge/` file;
**leaving off:** add a short dated handoff to the top of `utils/knowledge/worklog.md`.
