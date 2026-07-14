# SPLIT.md — cutting the 6,801-line backend into CORE + the MOSAIC feature

**Status:** normative. Implementation agents follow this literally.
**Source of truth for the old code:** `archive/app-v1/backend/` (READ-ONLY — never edit it).
**Every `file:line` below points into `archive/app-v1/backend/` or `archive/analysis/` unless stated.**

---

## 0. The five rules this split is built on

1. **The app carries no dataset knowledge.** The only symbol importable from the exclusion module is
   `gaps()` — a pure function over a trial list (`archive/analysis/ground_truth/excluded.py:65`).
   Never `EXCLUDED` / `BLANK` / `BLURRY` / `usable_trials` / `DATA_DIR`. There is no toggle.
2. **The 312/312 guard is sacred.** `engine/` files (`t27` `t33` `render` `quality` `excluded`
   `score`) move **byte-identical**. Do not reformat, do not "improve", do not merge.
3. **A DATASET is raw and is never written to.** Analyses land in the WORKSPACE.
4. **CORE may not import from `features/`.** Ever. The dependency arrow is one-way:
   `api → features → core → engine`. `core` may import `engine.quality` (band_pass) and
   `engine.excluded.gaps` and nothing else from `engine`.
5. **Only `features/mosaic/solve.py` may import `t27` / `t33` / `render`.** This is the rule
   `engine.py:6-9` enforced today. Keep it.

---

## 1. THE SYMBOL TABLE

Legend for **new home**:
`core/dataset` `core/frames` `core/workspace` `core/document` `core/jobs` ·
`mosaic/*` = `src/camea/features/mosaic/*` · `engine/*` = `src/camea/engine/*` ·
`api/*` = `src/camea/api/*` · **DEAD** = nothing calls it today ·
**DUP** = a second implementation of something that already exists.

---

### 1.1 `__init__.py` (72 lines) — shared constants + the tile state machine

| old symbol | new home | notes |
|---|---|---|
| `__version__` (`:40`) | `camea/__init__.py` | already exists (`0.2.0`). Delete the old one. |
| `TILE = 512` (`:45`) | `mosaic/__init__.py` | **MOSAIC.** 512 is `t33.TILE` (`archive/analysis/mosaic/t33.py:108`). Core must not assume a tile size — a frame store holds frames of whatever shape the XML says. |
| `FADE_MS = 1000` (`:46`) | frontend | UI constant. Not backend. |
| `DOG_LO, DOG_HI = 3, 30` (`:47`) | **DELETE** | DUP. The DoG lives in `engine/quality.py:17` and its sigmas are that function's defaults. Three copies today (`__init__.py:47`, `loader.py:65`, and quality's own defaults). See §3. |
| `FLAT_SIGMA = 15.0` (`:48`) | `core/frames` | vignette sigma. Generic imaging. |
| `TONE_PCT_LO/HI`, `TONE_N_SAMPLE` (`:49-51`) | `core/frames` | the global tone window. Generic. |
| `BLANK_PCT = 2.0` (`:52`) | `mosaic/blank` | the threshold **policy**, not the measure. See §5. |
| `BLANK_THRESHOLD = 60.1` (`:53`) | ⛔ **DELETE** | **DATASET KNOWLEDGE.** `60.11` is 260620d's measured number, sitting in the app as a "fallback". It is exactly the thing rule 4 forbids. It is already unused (`loader.blank_scan:671` recomputes). Do not carry it over, not even as a comment default. |
| `SNAP_RADIUS = 64` (`:54`) | `mosaic/solve` | and the ⚠️: never let the UI exceed 128 — the electrode grid repeats every 256 px. |
| `ANCHOR_KPK/MINFRAC/MINABS` (`:57-59`) | `mosaic/solve` | exactly `t33.py:732`. Do not "improve". |
| `MATCH_CACHE_SIZE = 32` (`:60`) | `mosaic/solve` | |
| `THIN_MARGIN = 0.10` (`:61`) | `mosaic/solve` | DUP of `engine.py:222 MARGIN_THIN`. One name: `MARGIN_THIN`. |
| `TILE_STATES` (`:63`) | `mosaic/document` | DUP of `project.py:88 STATES`. |
| `STATE_TO_STATUS` / `STATUS_TO_STATE` (`:66-72`) | `mosaic/document` | DUP of `project.py:91-93`. **One definition.** |

> **The whole file is duplicate constants.** It exists because seven agents needed a shared header.
> In the new tree each constant lives with the one module that owns it. Nothing re-exports.

---

### 1.2 `loader.py` (1,378 lines) — log, .dat IO, flat-field, tone, blank scan

| old symbol | new home | notes |
|---|---|---|
| `TILE/DOG_LO/DOG_HI/FLAT_SIGMA/TONE_*/BLANK_PCT` (`:64-69`) | see §1.1 | mirrored constants. Do not mirror again. |
| `_TRIAL_RE/_DATE_RE/_STAMP_RE/SNAPSHOT` (`:71-75`) | **core/dataset** | log.txt grammar. |
| `_iso` (`:78`) | `core/` shared util | DUP ×3 (`loader:78`, `jobs:54`, `server:157`). One. |
| `LogEntry` (`:86`), `.to_json` (`:94`) | **core/dataset** | |
| `parse_log` (`:98`) | **core/dataset** | ⚠️ The midnight-rollover carry-forward (`:143-146`) is load-bearing — the date appears only on `New experiment:` lines. Move verbatim. |
| `log_json` (`:165`) | **DEAD** | Never called (`server.get_session_log:449` reimplements it inline). Delete one, keep one: put it in `core/dataset` as `Dataset.log_json()` and have the route call it. |
| `snapshot_blocks` (`:176`) | **core/dataset** | "contiguous runs of Snapshot trials". Generic; a browser feature wants it too. |
| `detect_run` (`:188`) | **mosaic/run.py** | 🔶 **The judgement call, made explicitly:** "longest contiguous Snapshot block" is generic, but this function also applies the **512×512 gate** and returns a mosaic-shaped `run` block. Split it: `core/dataset` exposes `snapshot_blocks()` + `longest_block()`; **mosaic** owns "the run = the longest block, restricted to 512×512 frames". A future segmentation feature will want a different selection rule on the same dataset. |
| `_run_block` (`:217`) | **mosaic/run.py** | assembles `{lo,hi,trials,dropped,warnings,why,why_detail}`. Mosaic's shape. |
| `detect_pass_split` (`:231`) | **mosaic/run.py** | ⭐ **Pure mosaic.** `pass_split` is `t33.Config.pass_split` (`t33.py:120`). Keep the `MIN_SIDE_FRAC = 0.20` guard verbatim (`:273`): without it a naive argmax returns **11**, because 11→12 is *also* 20.0 s and ties the true boundary. `value` is the **LAST TRIAL OF PASS 1** (166), never 167. |
| `read_trial_meta` (`:332`) | **core/dataset** | ⚠️ **Shape is PER-TRIAL, not per-directory** (`:337-341`). Parse the XML; never infer shape from file size. Reject `frames != 1`. |
| `list_snapshots` (`:369`) | **core/dataset** | the raw disk inventory. `{trial: meta}`. Filters nothing by trial number. |
| `partition_trials` (`:389`) | **mosaic/run.py** | THE 512×512 GATE + its reasons (`off_shape` / `not_snapshot`). It is mosaic's gate: 512 is `t33.TILE`. ⛔ Nothing is dropped by trial number. |
| `usable_trials` (`:437`) | **DEAD** | Never called. And the *name* collides with `excluded.usable_trials` — the one symbol rule 4 forbids. **Do not port a function with this name.** |
| `gaps` (`:445`) | **core/dataset** | a 3-line delegation to `engine/excluded.py:65`. Keep it as `core.dataset.gaps(trials)` — the ONE place the app touches that module, and it imports **only** `gaps`, by name (`loader.py:61`). |
| `load_frame` (`:459`) | **core/frames** | ⭐⭐ **THE 180° FLIP IS LOAD-BEARING AND VERIFIED.** `flip_x`/`flip_y` come from XML `ax`/`ay`. It flips **conditionally**. Get it wrong and every position, every SWIM dx/dy and all three ground truths are 180° out — **and it will look plausible.** Move verbatim. |
| `load_frames` (`:484`) | **core/frames** | ⚠️ raises loudly on an off-shape trial (`:503-508`) rather than reshaping 131,072 bytes into a 512×512 lie. Keep. **No disk cache** (`:28-30`) — `mosaic.io.load_frames`' cache validates only `shape[0] == len(trials)`, so two different selections of the same size silently share an entry. Do not resurrect it. |
| `Tone` dataclass (`:518`), `.to_json` (`:532`) | **core/frames** | `version` is the front end's `?v=` cache-buster. |
| `compute_flat` (`:540`) | **core/frames** | |
| `flat_correct` (`:547`) | **core/frames** | ⚠️ note the **per-tile gain** `level / median(frame)`. It is right for a picture, wrong for a measurement — see `engine.render_mosaic`'s `flat` flag (`engine.py:1552-1568`). |
| `compute_tone` (`:553`) | **core/frames** | ⚠️⚠️ **GLOBAL, NEVER PER-TILE.** A per-tile stretch destroys Difference mode. There is no per-tile path and there must never be one. |
| `to_u8` (`:590`), `_png` (`:597`), `tile_png` (`:603`), `tile_raw` (`:608`), `thumb_sheet` (`:619`) | **core/frames** | the display path. |
| **`band_pass` (`:639`)** | ⛔ **DUP — DELETE.** | **See §3.** It reimplements `archive/analysis/mosaic/quality.py:17` and its own docstring admits it. |
| `texture_map` (`:655`) | **core/frames** | **CORE.** `{trial: std(band[i])}` — a per-frame number, not a mosaic concept. Free when core owns the band stack. See §5. |
| `blank_scan` (`:671`) | **mosaic/blank.py** | the THRESHOLD + PROPOSAL. See §5. Keep the `scanned` vs `blank` distinction (`:719-725`) — a MEASUREMENT that never moves, and a DECISION that does. |
| `Session` (`:736`) | **split — see §2** | |
| `Session.frame` (`:792`) / `.banded` (`:797`) | **core/frames** | DEAD as wired (server reaches into `s.frames[row]` at `server.py:495`), but the *shape* is right. In the new tree these accessors are the **only** way anything gets a frame. |
| `Session._u8_stack` (`:803`), `.tile_png` (`:814`), `.tile_raw` (`:821`), `.thumbs` (`:826`), `.thumbs_json` (`:842`) | **core/frames** | ⚠️ **DEAD + DUP.** The server never calls them — it calls the free functions and keeps its **own** caches (`server.py:90-91 _PNG_CACHE/_THUMB_CACHE`, `:492-498`, `:522-539`). Two caches for the same pixels. Keep exactly ONE, on the frame store, keyed on `tone.version`. |
| `Session.set_tone` (`:848`) | **core/frames** | **DEAD + DUP.** `server.put_tone:551-585` mutates `s.tone.lo/hi/version` **by hand** instead of calling this — and so skips its `hi > lo` validation and its cache invalidation, doing both itself. One implementation. |
| `Session._auto_tone` (`:785`) | **core/frames** | DUP of `server.py:87 _AUTO_TONE`. |
| `Session.frame_note` (`:871`) | **core/frames** | ⭐ **Derived from THIS acquisition's XML, never asserted.** Read by `export._tiff_description:447`. Do not hard-code "180-degree-flipped" anywhere. |
| `Session.coordinates` (`:900`) | **mosaic/document** | it talks about `origin_trial` and tile top-left corners. Mosaic's sentence. |
| `Session.store_key` (`:907`) | **core/dataset** | ⭐ basename + sha1 of the resolved directory. **Keep it.** Two folders both called `260620d` under different parents share a t33 cache filename and an autosave slot; `t33._load_checked` compares only the CONFIG and would accept the wrong acquisition's layout as warm. |
| `Session.autosave_path` (`:926`) | **DEAD + DUP** | of `project.autosave_path:1093`. The server uses project's (`server.py:418`). Delete loader's. Autosave paths belong to **core/workspace**. |
| `Session.nonce` (`:782`) | **core/frames** | ⭐ a fresh identity per open. `id()` **is recycled** (measured: 4 of 5 same-size allocations reused an address), which collided the composite cache and the match memo across sessions. Keep. |
| `Session.to_json` (`:930`) | `api/schemas` | the `GET /api/session` body. Assembled by the API from core + feature parts, not by the loader. |
| `_OPEN_PHASES` (`:971`), `_reporter` (`:974`) | **core/jobs** | the progress adapter. `_reporter` exists only because "agent 2 owns jobs.py" — that reason is gone. Import `jobs.Progress` directly. |
| `Cancelled` (`:990`) | ⛔ **DELETE — see the bug in §6.1** | It is a **different class** from `jobs.Cancelled` (`jobs.py:155`), so `jobs.submit_thread:271` never catches it: cancelling an `open` job marks it **`failed`**, with a traceback, not `cancelled`. One `Cancelled`, in `core/jobs`. |
| `open_session` (`:994`) | **split** | Becomes `core.dataset.open()` (inventory + log) + `core.frames.FrameStore.load()` (pixels, flat, tone, band, texture) + `mosaic.run.detect()` (run, pass_split, gate) + `mosaic.blank.propose()`. The *job* that chains them lives in `api/` or `mosaic/routes.py`. |
| `_selftest` (`:1118`) / `_raises` (`:1369`) | **tests/** | 260 lines of genuinely good assertions. Port them into `tests/unit/` + `tests/slow/`, don't leave them in a `__main__` block. ⚠️ `_selftest` hard-codes `260620d` paths and the old 26-trial list (`:1298`) — that is fine **in a test**, and forbidden in `src/`. |

---

### 1.3 `project.py` (1,339 lines) — the project file. **See §4 for the line.**

| old symbol | new home | notes |
|---|---|---|
| `_HERE/_ROOT/_GT_DIR` + `import excluded as _excluded` (`:76-81`) | **core/dataset** | ⚠️ **sys.path surgery.** In the new tree `engine.excluded` is a real module: `from camea.engine.excluded import gaps`. Nothing else. |
| `SCHEMA_VERSION` (`:83`) | `core/document` | rename: `camea-document-1.0`. Bump; migrate the old string. |
| `APP_NAME`/`APP_VERSION` (`:84-85`) | `camea/__init__` | one `__version__`. |
| `TILE_PX = 512` (`:86`) | `mosaic/document` | |
| `STATES`/`PLACED_STATES`/`STATE_TO_STATUS`/`STATUS_TO_STATE` (`:88-93`) | **mosaic/document** | the tile state machine. **The canonical copy.** |
| `R_PLACED`/`R_UNPLACED`/`MOVED_EPS` (`:95-97`) | **mosaic/document** | |
| `COORDINATES` (`:99`) | **mosaic/document** | ⚠️ it says "180deg-flipped" **unconditionally** while `load_frame` flips **conditionally**. **Fix on the way over:** build the string from `frames.frame_note` (`loader.py:871`). Metadata that lies about its own coordinate frame is the one thing this project has been burned by. |
| `TOLERANCE_PX` (`:103`) | **mosaic/document** | ⛔ `region_default` is REQUIRED — `score.load_gt()` reads it. |
| `PROVENANCE_WARNING` (`:105`) | **core/document** | ⭐ **CORE.** Verbatim, never paraphrased. It must apply to every future feature, not just mosaic. |
| `ProjectError`/`ValidationError`/`RangeMismatch` (`:115-133`) | **core/document** | rename `ProjectError` → `DocumentError`. `RangeMismatch` stays (it is the guard that kept pass 2's autosave from overwriting pass 1's ground truth). |
| `_now` (`:139`) | core util | |
| `_jsonable` (`:143`) | **core/** shared util | **DUP ×3**: `project:143`, `engine.jsonable:380`, `export._jsonable:568`. One implementation, in core, and it must handle `t27.Config` (`json.dumps(info)` **crashes** without it). |
| `_get` (`:172`) | delete | reads a dict-or-object. In the new tree the types are known. |
| `_trials` (`:181`), `_state_of` (`:186`) | **mosaic/document** | ⚠️ `_state_of` is **DUP** of `export.py:133`, and the two **DISAGREE**: export's returns `str(status)` for an unknown status (so a bench GT row with `status: "region"` becomes state `"region"` and is silently not rendered), project's maps unknown+placed → `"unverified"`. **One.** Use project's. |
| `active_trials` (`:201`) | **mosaic/document** | everything not `excluded`. This is the solver's input list. |
| `compute_gaps` (`:211`) | **mosaic/document** | ⚠️ DERIVED. **Must be recomputed on every change to the excluded set.** Delegates to `gaps()`. |
| `_pass_of` (`:223`), `_dist` (`:229`), `_median` (`:233`) | **mosaic/document** | |
| `new_doc` (`:245`) | **mosaic/document** | **DEAD** — the front end builds the doc in JS. **This is a bug, not a design.** Re-wire it: the server creates the document. |
| `seed_from_build` (`:340`) | **mosaic/document** | **DEAD** — same. The front end reimplements it in `sweep.js`, which is how `human_edits`' divert keys got dropped (`project.py:585-597`). |
| `mark_stale_if_input_changed` (`:406`) | **mosaic/document** | 🔴 Keep the "unknown is not the same as unchanged" fix (`:418-428`) — the old fallback compared the current trial list **with itself** and never fired. |
| `is_build_stale` (`:469`) | **mosaic/document** | |
| `normalise` (`:480`) | **mosaic/document** | origin pinned at (0,0); the **same translation** applied to `machine` and `last_xy` so `moved_px` stays meaningful. Mosaic geometry, top to bottom. |
| `_human_edits` (`:555`) | **mosaic/document** | ⭐ counts the **diverted** tiles (`:585-614`). They sit at the solver's position and therefore land inside `accepted_unchanged` — say so next to the number they contaminate. |
| `machine_evidence` (`:622`) | **split — see §4.3** | The *rule* ("a document seeded by a machine must say so, derived from HISTORY not from self-declaration") is **CORE**. The *evidence* (`doc["build"]`, tiles carrying a `machine` position) is **MOSAIC**. Core calls a feature hook. |
| `stamp` (`:668`) | **core/document** | ⚠️ **NOT DECORATION.** Any machine evidence ⇒ `independent_of_method: false` + the warning, verbatim. This project has already destroyed one benchmark exactly this way. |
| `_problems` (`:715`) | **split** | the generic half (schema_version, created, provenance, dataset match) → core; the tile/state/gaps/origin half → mosaic, via a `validate(payload) -> [(kind, msg)]` hook. ⛔ Keep the comment at `:775-779`: **no trial number is special.** The guard that used to live there made the user's own session unsaveable the moment he anchored 284. |
| `validate` (`:859`) | **core/document** + hook | |
| `_structural_problems` (`:873`) | **core/document** + hook | ⛔ "Nothing here may reject a document for WHICH trials it placed." |
| `save` (`:888`) | **core/document** | ⚠️ **ORDER: structural-validate → normalise → stamp → full-validate → write.** Not `validate → normalise` — the derived fields are *exactly* the ones that drift when the user excludes a tile, and normalise is what repairs them. |
| `_refuse_data_dir` (`:920`) | **core/workspace** | **DUP ×3**: `project:920`, `server:1055`, `export._guard_out_dir:298`. One. ⚠️ project's reads `_excluded.DATA_DIR` (`:927`) — **dataset knowledge**. Drop that branch; guard the repo's `data/` and the open dataset's own directory. |
| `_WRITE_LOCK` (`:945`) / `_atomic_write` (`:948`) | **core/workspace** | 🔴 Keep the lock. On Windows two concurrent `os.replace` on one target → `WinError 5`, and the loser's document was **silently lost** (reproduced: 4 concurrent autosaves → 1 failed). Keep the retry loop too. |
| `load` (`:980`) | **core/document** | ⚠️ **UNKNOWN KEYS ARE PRESERVED VERBATIM**, per tile and at the top level. A lossy round-trip destroys a hand-written note — and this file is also somebody's ground truth. **This is now doubly load-bearing: see §4.2.** |
| `_migrate` (`:1029`) | **core/document** + hook | generic keys in core; tile-status migration in mosaic. |
| `autosave_path` (`:1093`) | **core/workspace** | ⚠️ takes `dataset` but the server passes `store_key` (`server.py:1034`). Rename the parameter. |
| `autosave` (`:1102`) | **DEAD** — and its guard with it | 🔴 The server calls `project.save(autosave_path(...), ...)` (`server.py:1038`), **not** `project.autosave()`. So the **trial-range overwrite guard** (`:1119-1130`) — the thing written *because* pass 2's autosave silently overwrote pass 1's ground-truth records — **never runs.** `store_key` keys on the directory, not the range, so two ranges of the same dataset still collide. **Port the guard and wire it up.** |
| `to_gt` (`:1143`) | **mosaic/export** | |
| `to_positions_csv` (`:1157`) | **mosaic/export** | header **exactly** `trial,x,y,state`. `score.load_positions` DictReads the first three. |
| `qc_report` (`:1176`) | **mosaic/export** | every number states its denominator. |

---

### 1.4 `jobs.py` (475 lines) — the async job registry

**Almost all CORE, and it moves nearly intact.** The mosaic-shaped bits are three.

| old symbol | new home | notes |
|---|---|---|
| `JobState` (`:47`) | **core/jobs** | verbatim |
| **`JobKind = Literal["open","build","export"]` (`:48`)** | **core/jobs — GENERALISE** | 🔶 `"build"` is mosaic's word. Make `kind: str`; features register their own kinds. |
| `LOG_TAIL_MAX` (`:51`), `_iso` (`:54`) | **core/jobs** | |
| `Progress` (`:59`) | **core/jobs** | ⚠️ its docstring (`:62-70`) is the **mosaic build's** phase weighting. Move that prose to `mosaic/solve.py`; the dataclass is generic. |
| `Job` (`:80`) + `to_json`/`_set`/`_log`/`_finish` (`:100-152`) | **core/jobs** | verbatim. `_finish` makes a terminal state **final** — a late queue message must never resurrect a cancelled job. Keep. |
| `Cancelled` (`:155`) | **core/jobs** | **the only one.** Delete `loader.Cancelled` (§6.1). |
| `Busy` (`:159`), `NotCancellable` (`:163`) | **core/jobs** | |
| `_process_entry` (`:170`) | **core/jobs** | ⚠️ must stay module-level (spawn pickles it by qualified name) and close over nothing. ⚠️ `sys_path` is re-inserted in the child **on purpose** — do not "simplify" it away; it is what makes a frozen build work. |
| `JobRegistry` (`:197`), `_new_job` (`:216`) | **core/jobs** | |
| **`_guard_build` (`:235`)** | **core/jobs — GENERALISE** | 🔶 "one build at a time; it owns the GPU" is a **mosaic policy hard-coded into the registry**, and it is also applied to *thread* jobs (`:257`), which is why `open`/`export` are refused while a build runs. Replace with an **exclusive-resource lease**: `submit(..., exclusive="gpu")` ⇒ no other job may start while it holds it. Without this, a future segmentation GPU job and a mosaic build run concurrently and OOM a 4 GB card. |
| `submit_thread` (`:241`) | **core/jobs** | |
| `submit_process` (`:291`) | **core/jobs** | ⚠️ `target` is a dotted path (`server.py:881`: `"app.backend.engine.build_worker"`) → becomes `"camea.features.mosaic.solve.build_worker"`. ⚠️ `repo_root = parents[2]` (`:317`) is wrong for `src/` layout — under `uv` the package is installed, so pass `sys.path` as-is plus the src root. |
| `_apply` (`:397`) | **core/jobs** | the child→parent message protocol. |
| the exit-code hint block (`:356-387`) | **core/jobs** | 🔴 **KEEP EVERY WORD.** `0xC06D007F` is `STATUS_DELAY_LOAD_FAILED` (not `0xC0000409`), and both signednesses are carried because `Process.exitcode` returns a signed int. This is what numpy's delay-loaded BLAS does when its DLLs are not on the search path. Genericise "the build process" → "the job's child process"; keep the diagnosis. |
| `get`/`list`/`cancel`/`running` (`:421-471`) | **core/jobs** | `cancel` marks the job cancelled **before** `terminate()`, so the drain thread does not call it a crash. Keep the order. |
| `JOBS` (`:475`) | **core/jobs** | one registry, module-level. |

---

### 1.5 `server.py` (1,153 lines) — FastAPI

| old symbol | new home | notes |
|---|---|---|
| `REPO_ROOT` (`:49`), `FRONTEND_DIR` (`:65`) | `api/app` | |
| `SESSION` (`:70`) | **core/session (new)** | see §2. |
| `WINDOW` (`:71`) | `shell.py` | injected. |
| **`BUILD` (`:72`)** | **mosaic/routes** | ⛔ the last build's result, held as module state on the server. **Feature state on the core server.** Move it into the mosaic feature's own state (or, better, into the document). |
| `BASE_URL` (`:74`), `LAUNCH_DATA_DIR` (`:80`) | `api/app` | |
| `PROJECT_PATH` (`:75`) | **core/document** registry | "which file is open" is generic. |
| `_STARTED` (`:82`), `_LOCK` (`:84`) | `api/app` | |
| `_AUTO_TONE` (`:87`) | **DUP** | of `Session._auto_tone` (`loader.py:785`). Delete the server's. |
| `_PNG_CACHE` (`:90`), `_THUMB_CACHE` (`:91`) | **DUP** | of `Session._u8`/`_thumbs` (`loader.py:786-788`). Delete the server's; use the frame store's. |
| `_GPU_INFO` (`:92`) | **DUP** | of `engine.py:259 _GPU_INFO`. Delete the server's; `engine.gpu.gpu_info()` is already memoised under a lock. |
| `_BUILD_JOB_SEEN` (`:95`) / `_hoist_build` (`:757`) | **mosaic/routes** | a lazy "did a build finish?" poller, because the registry has no completion callback. Consider adding an `on_done` hook to `core/jobs` instead. |
| `ApiError` (`:104`), `_err` (`:113`), the three exception handlers (`:120-133`) | **api/app** | keep the `{"error": {"code","message","detail"}}` envelope. |
| `_need_session` (`:136`), `_need_jobs` (`:142`) | **api/app** | |
| **`_need_no_build` (`:151`)** | **api/app — GENERALISE** | 409 busy while the GPU lease is held (not "while a `build` runs"). |
| `_iso` (`:157`) | **DUP ×3** | one. |
| `_report_adapter` (`:161`) | **core/jobs** | DUP of `loader._reporter:974`. |
| `create_app` (`:197`), `serve` (`:222`) | **api/app** | 🔴 Keep `SO_EXCLUSIVEADDRUSE` on Windows (`:239-242`). `SO_REUSEADDR` on Windows lets a **second** socket bind a port a **live** process is listening on, and the OS keeps routing to the old one — a stale server served a different session's pixels. |
| `get_index` (`:270`) | `shell.py` / `api/app` | 🔴 Keep the mtime script cache-bust (`:292-309`). A new `index.html` loading a cached old `viewer.js` produced a blank canvas and a dead sweep. |
| `get_health` (`:316`) | **api/** core routes | |
| `get_gpu` (`:327`) | **api/** core routes | 🔴 Detection MUST execute a real op. **There is exactly one detector: `t27.xp()`.** `import cupy` succeeds on a broken CUDA install. Never write a second. |
| `_open_job` (`:344`), `post_session_open` (`:376`) | **api/** core routes | ⚠️ `engine.reset_caches()` on every open (`:365`) — the composite cache and the match memo were carrying the previous session's arrays across an open. |
| `get_session` (`:390`) | **api/** core routes | assembles core + feature blocks. |
| `patch_session_run` (`:424`) | **mosaic/routes** | it changes `lo/hi/pass_split` — mosaic's selection. A **full reload**, not an in-place patch, because `gaps` must be recomputed. |
| `get_session_log` (`:449`) | **api/** core routes | → `core.dataset.log_json()`. |
| `_frame_row` (`:467`) | **core/frames** | |
| `get_tile_png` (`:475`), `get_tile_raw` (`:503`), `get_thumbs_png` (`:517`), `get_thumbs_json` (`:531`) | **api/** core routes | ⚠️ `?v=` must identify the **session**, not just the tone: `{nonce}.{tone.version}`. `tone.version` is a dataclass default and **resets to 1 on every open**, while the pixels behind an `immutable, max-age=1yr` URL change. |
| `get_tone` (`:545`), `put_tone` (`:551`) | **api/** core routes | ⚠️ call `frames.set_tone()`; do not mutate the dataclass by hand. |
| `get_scan_blank` (`:591`) | **mosaic/routes** | see §5. |
| **`put_scan_blank` (`:602`)** | ⛔ **DELETE THE ENDPOINT** | see §2.4 and §5 — the accepted blank list moves into the **document** and into the **match request body**. Mutating session state to change what a "pure function" returns is the bug. |
| `_parse_positions` (`:652`), `_validate_match` (`:666`) | **mosaic/routes** | ⚠️ radius clamped to ≤ 256 (UI ≤ 128): the electrode grid repeats every 256 px and a wide **local** search locks onto a grid alias. |
| `post_match_anchor` (`:716`), `post_match_score` (`:739`) | **mosaic/routes** | ⭐ plain `def`, not `async def` — Starlette runs them in its thread pool, which is what stops a prefetch blocking the foreground request. |
| `get_job` (`:773`), `get_jobs` (`:783`), `post_job_cancel` (`:790`) | **api/** core routes | |
| `_validate_config` (`:813`) | **mosaic/routes** | validates by **constructing** a `t33.Config` (it raises `TypeError` on an unknown knob itself). Do not hard-code the knob list. |
| `post_build_start` (`:833`), `_build_trials` (`:892`), `get_build_result` (`:922`) | **mosaic/routes** | ⭐ `trials` is the **document's active list** — this is the ONLY way a frame ever leaves a build. Hard-wiring `s.run["trials"]` here meant a user's `E` never reached the solver. |
| `_appdata` (`:940`) | **core/workspace** | |
| `post_project_save` (`:946`), `post_project_load` (`:981`), `post_project_autosave` (`:1022`) | **api/** core routes | ⚠️ `RangeMismatch`/`ValidationError` are `ProjectError`s, **not** `ValueError`s — catching only `ValueError` turned a refused document into an opaque **500** on every 2-second autosave. Get the except-ladder right. |
| `_refuse_data_dir` (`:1055`) | **DUP** | → `core/workspace`. |
| `post_export` (`:1066`) | **mosaic/routes** | |
| `_need_window` (`:1104`), `_file_types` (`:1110`), `_first` (`:1117`), the three dialog routes (`:1125/1135/1145`) | **api/** core routes + `shell.py` | 501 when headless. |

---

### 1.6 `engine.py` (1,660 lines) — the only module that imports t27/t33

**Everything here is MOSAIC except the GPU layer and the JSON coercer.**

| old symbol | new home | notes |
|---|---|---|
| `_predance_cuda_dlls` (`:54`) | **engine/gpu.py** | 🔴 Under PyInstaller `purelib` resolves inside `_MEIPASS` and t27's own dance finds **nothing** → "No usable CUDA GPU" on a machine with a good card. **Not in t27** (t27 is under the guard). Must run at import in the **parent AND the spawned child**. |
| `_predance_env_dlls` (`:99`) | **engine/gpu.py** | 🔴 `np.linalg.solve` delay-loads BLAS; an unactivated launch fast-fails the child with `0xC06D007F`, killing every **cold** build (a warm one skips pass 1 and never calls BLAS). Under `uv`'s venv the conda branches are a harmless no-op — **keep them anyway** for the frozen build. |
| `_repo_root` (`:172`) / `REPO_ROOT` (`:188`) / the sys.path insert (`:189`) | **DELETE** | `camea` is an installed package under `uv`. No path surgery. |
| the imports (`:192-200`) | **mosaic/solve.py** | ⛔ **THE ONLY MODULE THAT MAY IMPORT `t27`/`t33`/`render`.** And `from camea.engine.excluded import gaps` — **only** `gaps` (the comment at `:194-199` explains why re-exporting `EXCLUDED` was "a loaded gun"). |
| `TILE`/`ANCHOR_*`/`MATCH_CACHE_SIZE`/`SNAP_RADIUS`/`MARGIN_THIN`/`NMS_PX`/`GPU_NOTE` (`:216-227`) | **mosaic/solve.py** | the canonical copy. |
| `PHASES`/`PHASE_WEIGHT_GPU`/`PHASE_WEIGHT_CPU`/`PHASE_INDEX`/`N_PHASES` (`:244-252`) | **mosaic/solve.py** | 🔴 **TWO tables, and there have to be.** On CPU pass1+backbone = 75 % of the build; on GPU the anchor loop = 53 %. One GPU-calibrated table told a CPU user "873 s left" when 368 s remained. |
| `_gpu_failure_reason` (`:267`), `gpu_info` (`:287`), `warm_gpu` (`:339`), `release_gpu` (`:368`) | **engine/gpu.py** | 🔴 **ONE DETECTOR: `t27.xp()`.** `reason` is a *string*, never a verdict. `warm_gpu` is worth −497 ms off the first match and surfaces a broken CUDA install at launch. ⚠️ `cupy.random` is broken in this env — seed from numpy. |
| `jsonable` (`:380`) | **core/** shared util | **DUP ×3** (§1.3). Must coerce `t27.Config` — `json.dumps(info)` **crashes** otherwise. |
| `_CompositeCache` (`:415`), `_COMPOSITE` (`:544`) | **mosaic/solve.py** | ⭐ bit-identical by construction (append-only in `k` order + a pure integer paste). Move **verbatim**, including all three precondition checks. 268 ms → 108 ms at 156 anchors. |
| `composite_of` (`:547`), `_token` (`:557`), `_pos` (`:575`), `reset_caches` (`:583`) | **mosaic/solve.py** | ⚠️ `_token` must use `frames.nonce`, never `id(band)`. |
| `Candidate` (`:594`), `MatchResult` (`:609`) | **mosaic/solve.py** + `api/schemas` | |
| `_MEMO`/`_MEMO_LOCK`/`_INFLIGHT`/`_COMPUTE_LOCK` (`:649-656`) | **mosaic/solve.py** | ⚠️ `score_at` is **deliberately NOT** under `_COMPUTE_LOCK` (`:1043-1050`) — it used to wait out a whole `match_anchor`, so the live NCC under the cursor was up to a full match out of date. |
| **`cache_key` (`:659`)** | **mosaic/solve.py** | ⭐⭐ **THE PREFETCH'S CORRECTNESS GUARANTEE.** The key **IS the anchor set + their positions**. Prefetching from a composite *without* the tile under judgement disagrees with the truth in **18 %** of presses and is catastrophically wrong (up to 1,143 px) in **6 %**. Press `E` instead of `A` ⇒ different key ⇒ honest recompute. **Never invent a second cache keyed on the trial number.** ⚠️ **It must also key on the refusal set — see §2.4.** |
| `_blank_list` (`:687`), `_texture_of` (`:692`) | **mosaic/solve.py — CHANGE SIGNATURE** | they read `session.blank` / `session.texture` (hidden mutable state). They must read the **request**. §2.4. |
| `_refusal` (`:698`), `_blank_anchors` (`:740`) | **mosaic/solve.py** | ⛔ Blank **TARGET** = refused. Blank **ANCHOR** = dropped from the composite, never fatal. The API.md clause that made a blank anchor fatal would have killed the sweep at tile 35. Keep it as written. |
| `_tile_for_match` (`:746`) | **mosaic/solve.py** | band-passed + mean-subtracted, exactly `t33.py:730-731`. Tone never touches this path. |
| `_subpixel` (`:755`), `_local_search` (`:783`) | **mosaic/solve.py** | additive; they cannot affect the 312/312 guard. |
| `match_anchor` (`:830`), `_match_compute` (`:961`), `score_at` (`:1013`) | **mosaic/solve.py** | ⭐ `world_topleft = m0 + (dx, dy)`. Positions are **TOP-LEFT corners, not centres**. ⚠️ t33's tier-A candidates carry `npix = 0` = "not measured", **not** "no overlap" — pass them through untouched. |
| `enable_build_memo` (`:1075`) | **mosaic/solve.py** | bit-identical: it caches the real `t33._pool`'s own **output object**, keyed on **identity**. Child process only. |
| `disable_build_memo` (`:1114`) | **DEAD** (keep) | never called, but it is the A/B verification's escape hatch. Keep it and add the A/B test. |
| `_ProgressSink` (`:1126`) | **mosaic/solve.py** | 🔴 the stdout scraper — t33 has **no** progress callback. Keep `_enter`'s never-go-backwards guard (`:1200-1217`): **t33 runs t27 inside itself**, and t27 prints its own `[done] placed 156 snapshots` a third of the way in — scraped naively it sends the bar to 100 % and back to 20 %. Keep `SUBSTEPS` (`:1162-1175`): without them a CPU build sat at **0.0 %, no ETA, for 3 m 40 s**. |
| `_make_config` (`:1307`) | **mosaic/solve.py** | ⚠️ `cfg.pass_split` MUST be the **detected** split, not t33's literal 166. |
| `_load_frames` (`:1324`) | **mosaic/solve.py** → `core.frames.load_frames` | ⭐ **ONE READER.** The old inline shim flipped **unconditionally** while the canonical reader flips **conditionally on the XML** — the child would have solved on 180°-rotated frames while the UI used un-rotated ones, and every tile would still have looked plausible. ⛔ **No fallback.** |
| `read_anchors` (`:1344`) | **mosaic/solve.py** | uses `t33._tag` / `t33._cache_key` / `t33._load_checked` (**private**). Degrades to `{}` on any failure, never to wrong data. |
| `build_result` (`:1378`) | **mosaic/solve.py** | ⭐ writes `trials` + `gaps` — **what the solver was actually given**. Without them `mark_stale_if_input_changed` never fires. 🔴 **Pass-1 tiles have NO per-tile confidence at all**, and the worst tile in the shipped 312/312 build (127, 9.94 px) is a pass-1 tile. Absence of a warning ≠ a clean bill of health. |
| `_config_effective` (`:1450`) | **mosaic/solve.py** | ⚠️ a **warm cache hit hands back a plain dict**, not a `t33.Config` — keying the fix on `hasattr(cfg, "t27_config")` made it no-op on every cached build, which is the common case. |
| `build_worker` (`:1483`) | **mosaic/solve.py** | the spawn target. New dotted path: `camea.features.mosaic.solve.build_worker`. |
| `render_mosaic` (`:1548`) | **mosaic/export.py** | ⭐ **`flat` decides what the pixels ARE.** `flat=True` = picture (per-tile gain). `flat=False` = **raw camera counts** = the TIFF. The TIFF was rendered `flat=True` while its header said RAW: trial 11's median went 2111 → 3435 (×1.63). ⚠️ **The coverage mask is not optional** — 13.1 % of the canvas is background encoded as exactly `0.0` and there is no alpha channel. |
| `_RenderSink` (`:1620`) | **mosaic/export.py** | |
| `score_against_gt` (`:1643`) | **DEAD (dev only)** → `tests/slow/` | ⛔ **Never reimplement `score.robust_align`** — a reimplementation with a different tie-break scored the same positions **152/156** where the canonical one gives **155/156**. ⛔ Never score a project this app produced against the method that seeded it: 100 % by construction. |

---

### 1.7 `export.py` (724 lines)

| old symbol | new home | notes |
|---|---|---|
| `APP_VERSION` (`:57`), `REPO_ROOT` (`:58`) | delete | |
| `OUTPUT_KINDS` (`:61`) | **mosaic/export** | |
| `PROVENANCE_WARNING` (`:64`) | re-export from **core/document** | never paraphrased. |
| `_is_cancelled` (`:70`), `_check` (`:81`), `_say` (`:86`) | **core/jobs** | generic job plumbing. |
| `_atomic_bytes` (`:93`), `_atomic_text` (`:99`) | **core/workspace** | ⚠️ **weaker than `project._atomic_write`** (`project.py:948`): no lock, no fsync, no retry. Use **project's** everywhere. |
| `_entry` (`:103`) | **core/workspace** | `{kind, path, bytes}`. |
| `_tone_lohi` (`:107`) | **core/frames** | |
| `_ASCII_FOLD` (`:118`), `_ascii` (`:123`) | **mosaic/export** | TIFF's `ImageDescription` is an ASCII tag; the provenance warning has an em-dash. **Fold, do not drop** — the text is the point. |
| `_tiles` (`:129`) | **mosaic/document** | |
| `_state_of` (`:133`) | **DUP — DELETE** | disagrees with `project._state_of:186`. See §1.3. |
| `render_positions` (`:145`) | **mosaic/export** | `anchored` always; `unverified` iff asked. `excluded`/`unplaced` **never**. |
| `export_all` (`:167`) | **mosaic/export** | ⭐⭐ **TWO RENDERS** when both TIFF and PNG are asked for. They are different pixels. 🔴 It must describe the document **AS EXPORTED** (the *stamped* doc), not as posted — a laundered doc once produced a GT JSON saying "NOT AN INDEPENDENT GROUND TRUTH" beside a TIFF header saying "hand-placed from scratch". |
| `_safe_basename` (`:291`) | **core/workspace** | |
| `_guard_out_dir` (`:298`) | **DUP** → **core/workspace** | third copy of `_refuse_data_dir`. |
| `_render` (`:318`), `_render_cb` (`:352`) | **mosaic/export** | |
| `write_tiff` (`:371`) | **mosaic/export** | ⛔ **DO NOT PASS THE DISPLAY RENDER IN HERE.** ⚠️⚠️ the coverage sidecar PNG is **mandatory**. |
| `_tiff_description` (`:429`) | **mosaic/export** | ⚠️ **asks the session, which asked the XML** (`frame_note`). It used to assert "180-degree-flipped" unconditionally. |
| `write_png` (`:480`), `_write_png_u8` (`:518`) | **mosaic/export** | ONE global window. Never per-tile. |
| `write_positions` (`:528`) | **mosaic/export** | header exactly `trial,x,y,state`. |
| `write_gt` (`:547`), `_assert_scoreable` (`:580`) | **mosaic/export** | ⭐ the two lines `score.load_gt()` actually reads, checked before the file leaves the process. **Keep this assertion.** |
| `_jsonable` (`:568`) | **DUP ×3** → core | |
| `write_qc` (`:608`), `_qc_export_markdown` (`:637`) | **mosaic/export** | |
| `scale_metadata` (`:696`) | **mosaic/export** | ⛔ **PIXELS ONLY** unless the user typed a µm/px in. ❌ Never 1.237 µm/px — it came from a broken inference. There is **no** magnification difference between the passes (cross-pass tissue scale 1.0000 ± 0.0002); the MEA grid pitch tracks **focus**, not magnification. |

---

## 2. THE SESSION PROBLEM

### 2.1 What today's Session actually is

`loader.Session` (`loader.py:736-968`) is **five unrelated things in one mutable dataclass**, owned by
a module-level global (`server.py:70`):

| # | fields | what it really is |
|---|---|---|
| 1 | `data_dir`, `dataset`, `experiment`, `entries`, `tiles`, `store_key`, `opened_at` | **dataset identity + inventory** — facts about disk |
| 2 | `frames`, `row_of` | **the pixel stack** |
| 3 | `flat_n`, `tone`, `_u8`, `_thumbs`, `_auto_tone`, `nonce` | **display state** |
| 4 | `band` | **a derived representation** (DoG 3-30) — the matcher's input *and* the texture measure's |
| 5 | `run`, `pass_split`, `gaps`, `texture`, `blank`, `excluded`, `warnings`, `project_path` | **analysis state — mosaic's, and a mutable copy of decisions** |

Rows 1–4 are core. **Row 5 is the problem.**

### 2.2 The half that SURVIVES, and must

> **The server does not own the document. `POST /api/match/*` is a pure function of its request body.**
> (`server.py:14-20`)

**Keep this.** It is not a stylistic preference; it is `cache_key`'s correctness argument
(`engine.py:659-684`). The front end prefetches tile N+1's match the instant tile N is judged, and
that prefetch **must assume the user will press `A`** — i.e. it must include the tile currently under
judgement in the composite. Prefetching without it **disagrees with the truth in 18 % of presses and
is catastrophically wrong (up to 1,143 px) in 6 %.** Because the memo key **is** the anchor set and
their positions, a user who presses `E` produces a *different key*, the memo misses, and the server
recomputes honestly. **The trap is structurally impossible to fall into — as long as the server holds
no tile state to be out of sync with.**

⇒ **Do not add server-side tile state to make the match endpoints "convenient".**

### 2.3 The half that DOES NOT survive

"The **front end** owns the document" does not survive, for two reasons.

1. **It has already cost.** `project.new_doc` (`project.py:245`) and `project.seed_from_build`
   (`project.py:340`) are **DEAD** — the front end reimplemented both in `sweep.js`. That is how
   `human_edits`' divert keys got silently dropped on every save (`project.py:585-597`, "the one
   place the numbers were supposed to survive — the file — was the one place they did not"), and it
   is why `skipBuild` could null `seeded_from` and delete the provenance warning while every tile
   still sat exactly where t33 put it (`project.py:622-641`).
2. **With two features open on one dataset, "the document" is not one thing.** Mosaic has a document.
   Segmentation will have a different one. A single POSTed blob cannot mean both.

### 2.4 What the core's session SHOULD be

Split "who owns the **undo stack**" (the front end — a UI concern) from "who is **authoritative**"
(the server).

```
core/session.py            DatasetSession — ONE per open DATASET, shared by every open feature.
                             .dataset   : core.dataset.Dataset      (identity, log, inventory)
                             .frames    : core.frames.FrameStore    (pixels, flat, tone, band, texture)
                           IMMUTABLE except for display state (tone). NO analysis state. NO
                           tile states. NO exclusions. NO blank list. NO run. NO pass_split.

core/document.py           DocumentStore — the open documents, keyed by id.
                             .feature   : "mosaic" | ...
                             .dataset_id: which DatasetSession it is bound to
                             .payload   : the feature's own document (opaque to core)
                           save / load / autosave / migrate / validate — all via feature hooks.

features/mosaic/*          holds the mosaic's selection (run, pass_split, gate) and its document
                           payload. Two mosaic documents on one dataset is legal.
```

**The three things that MUST move off the session, and why each is a bug today:**

| moves off | today | why |
|---|---|---|
| `Session.blank` (`loader.py:761`) | mutated by `PUT /api/scan/blank` (`server.py:639-646`) and read by `engine._blank_list` (`engine.py:687`) | 🔴 **This makes `POST /api/match/anchor` NOT a pure function of its request body — contrary to the claim at `server.py:16-20`.** The refusal set is a hidden input. That is exactly why the server has to call `engine.reset_caches()` on every `PUT /api/scan/blank` (`server.py:645`). **Fix:** the accepted blank list lives in the mosaic **document** (`blank_scan.blank`, `project.py:316-321`) and is sent in the match request body as `refuse: [trials]`. Add it to `cache_key` (`engine.py:674-683`). Then delete `PUT /api/scan/blank`. |
| `Session.excluded` (`loader.py:755`) | starts empty; the app never adds to it | It is *already* only a mirror of the document. Delete the field — do not give a future agent a place to put an exclusion. |
| `Session.run` / `.pass_split` / `.gaps` | detected at open (`loader.py:1031-1051`) | These are **mosaic's selection of the dataset**, not properties of it. They belong to the mosaic feature's state, computed when mosaic opens and re-computed on `PATCH .../run`. |

`Session.texture` **stays in core** (see §5). `Session.band` **stays in core**, as a lazily-computed,
memoised derived array on the `FrameStore` — because two consumers need it (the texture measure and
the matcher) and the whole reason `open` is ~5 s and not ~8 s is that **one array serves both**
(`loader.py:1002-1005`, `loader.py:658-663`).

### 2.5 Concurrency

`_LOCK` (`server.py:84`) is an `RLock` around every session mutation. Keep an equivalent on
`DatasetSession`. The `FrameStore`'s caches must be atomic in themselves (as `_CompositeCache` already
is, `engine.py:455`), because `score_at` runs **concurrently** with `match_anchor` on purpose
(`engine.py:1043-1050`) and must not wait for it.

---

## 3. THE DUPLICATE `band_pass`

### 3.1 The finding

There are **four** DoG(3,30) implementations in the repo today:

| # | where | shape |
|---|---|---|
| 1 | `archive/analysis/mosaic/quality.py:17` | **the canonical one.** `t27.band_pass` (`t27.py:175-180`) *delegates* to it: `from . import quality; return quality.band_pass(frames, lo, hi)`. It is therefore **under the 312/312 regression guard**. |
| 2 | `archive/app-v1/backend/loader.py:639` | a reimplementation. Its own docstring: *"DoG(3, 30) — identical to `mosaic.quality.band_pass` / `t27.band_pass` (same cv2 calls, same order) … Verified bit-identical to both."* |
| 3 | `archive/analysis/mosaic/io.py:46` | a third (`sigma_lo`/`sigma_hi`, 2-D only). **Stays in archive** — `io.py` is not ported. |
| 4 | `archive/analysis/texture/make_texture.py:44` | a fourth. **Stays in archive.** |

**Two implementations of the DoG that EVERYTHING is matched on, with nothing asserting they agree.**
Nothing in the repo tests #1 against #2. The "verification" is a comment.

They *are* equal today — same two `cv2.GaussianBlur` calls, same order, same sigmas (`quality`'s
defaults are `lo=3, hi=30`, and `loader.DOG_LO/DOG_HI` are `3, 30`). The only real difference:
`loader.band_pass` adds a **2-D branch** (`loader.py:649-650`) that `quality.band_pass` does not have
(quality's list-comp iterates the first axis, so a 2-D input would iterate *rows*). That branch is
genuinely used — `texture_map` (`loader.py:667`) calls it per-frame.

### 3.2 The single one

> **`camea/engine/quality.py :: band_pass` is THE band-pass. There is no other.**

- `engine/quality.py` is moved **byte-identical** (rule 2). It is load-bearing for 312/312 via
  `t27.band_pass`. **Do not touch it.**
- `core/frames.py` **imports** it. It does not wrap it, re-derive it, or re-tune it:

  ```python
  # src/camea/core/frames.py
  from camea.engine.quality import band_pass          # THE band-pass. Never a second one.

  def band_pass_one(frame):
      """One 2-D frame -> its DoG. Bit-identical by construction: it IS band_pass, on a
      1-frame stack. Do not inline the two cv2 calls here — that is how the fork came back."""
      return band_pass(frame[None])[0]
  ```
  `band_pass(f[None])[0]` applies exactly the same two `cv2.GaussianBlur` calls to exactly the same
  2-D array, so it is bit-identical to `loader.band_pass`'s 2-D branch **by construction**, not by
  assertion.
- ⚠️ **KEEP OPENCV.** Swapping to `scipy.ndimage.gaussian_filter` shifts the blank metric by
  **0.32 %** against a threshold whose nearest margin is **0.13 %** — it can flip a blank
  classification (`loader.py:644-646`, and `pyproject.toml`'s `opencv-python` comment).

### 3.3 The test that pins it — `tests/unit/test_band_pass_is_singular.py`

Four assertions. All four are required; #2 is the one that actually stops the fork coming back.

```python
# 1. IDENTITY, not equality. core re-exports the engine's function object.
def test_frames_reexports_the_engine_band_pass():
    from camea.core import frames
    from camea.engine import quality
    assert frames.band_pass is quality.band_pass

# 2. ⭐ THE SOURCE-LEVEL GUARD. Exactly ONE file under src/camea may contain a Gaussian DoG.
#    This is what prevents a well-meaning agent from "inlining a two-liner" ever again.
def test_only_quality_py_contains_a_gaussian_blur():
    hits = [p for p in (SRC / "camea").rglob("*.py")
            if "GaussianBlur" in p.read_text(encoding="utf-8")]
    assert [p.name for p in hits] == ["quality.py"], hits
    # (flat-field's GaussianBlur in core/frames is a VIGNETTE, sigma=15, not a DoG — if you keep
    #  it there, tighten this to a regex for the DoG pair and leave the vignette out.)

# 3. The 2-D convenience path is the 3-D path. Bit-for-bit, on random data. No mirror needed.
def test_band_pass_one_is_the_stack_path():
    import numpy as np
    from camea.core.frames import band_pass, band_pass_one
    f = np.random.default_rng(7).normal(2000, 300, (512, 512)).astype(np.float32)
    assert np.array_equal(band_pass_one(f), band_pass(f[None])[0])

# 4. @pytest.mark.slow — the DoG still produces the texture numbers the project's own record
#    holds. This is the assertion nobody ever wrote.
def test_texture_matches_the_recorded_reference():
    ref = json.loads(Path("archive/analysis/texture/260620d_texture.json").read_text())
    #  for every trial in ref: round(band_pass_one(load_frame(t)).std(), 2) == ref[str(t)]
```

Assertion 4 pins **the DoG, the 180° flip and the reader** in one number, against a file that was
written before any of this code existed. `loader.py:660-662` claims it holds "on every trial, to the
stored 2 dp". **Make it a test, not a comment.**

---

## 4. WHAT IS MOSAIC-SHAPED IN THE DOCUMENT

`project.py` is 1,339 lines, and roughly **1,050 of them are mosaic.** But the machinery that keeps a
document *honest* is generic and must stay generic, or every future feature re-opens the hole.

### 4.1 The line

**CORE (`core/document.py`) — the envelope. What every analysis has, whatever it is.**

| key | from |
|---|---|
| `schema_version` | `project.py:83` |
| `app: {name, version}` | `project.py:84-85` |
| `id`, `feature` (`"mosaic"`) | **new** — there was no notion of "which feature" |
| `dataset`, `experiment`, `data_dir`, `dataset_key` (`store_key`) | `project.py:292-295`, `loader.py:907` |
| `created`, `modified` | `project.py:296-297` |
| `provenance: {authored_by, app_version, workflow, seeded_from, independent_of_method, warning, scale}` | `project.py:322-331` |
| **behaviour:** `save` (`:888`), `load` (`:980`), `autosave` (`:1102`), `autosave_path` (`:1093`), `_migrate` (`:1029`), `_atomic_write` (`:948`), `_WRITE_LOCK` (`:945`), `validate` (`:859`), `stamp` (`:668`), `ValidationError`/`RangeMismatch` (`:119-133`), `PROVENANCE_WARNING` (`:105`) | |

**MOSAIC (`features/mosaic/document.py`) — the payload.**

| key | from |
|---|---|
| `tiles: {trial: {status, state, x, y, r, pass, machine, moved_px, ncc, margin, n_anchors, blank, texture, judged_at, diverted, rejected_match, last_xy, source, note}}` | `project.py:273-285` |
| the 4-state machine + `STATE_TO_STATUS` / `STATUS_TO_STATE` | `project.py:88-93` |
| `trial_range`, `pass_split`, `origin_trial`, `tile_px`, `coordinates`, `tolerance_px` | `project.py:298-303` |
| `gaps`, `unusable_tiles` (both **derived**) | `project.py:300`, `:306` |
| `cursor` (the sweep position) | `project.py:305` |
| `blank_scan: {threshold, measure, blank, accepted}` | `project.py:316-321` |
| `run: {detected, why, pass_split_detected, pass_split_why, n_trials}` | `project.py:307-313` |
| `build: {...}` + staleness | `project.py:373-389`, `:406`, `:469` |
| `tone` (a *display* snapshot, so a reload resumes) | `project.py:314-315` — core owns tone, the doc just records it |
| **behaviour:** `new_doc` (`:245`), `seed_from_build` (`:340`), `normalise` (`:480`), `active_trials` (`:201`), `compute_gaps` (`:211`), `_human_edits` (`:555`), `machine_evidence` (`:622`), `to_gt` (`:1143`), `to_positions_csv` (`:1157`), `qc_report` (`:1176`) | |

### 4.2 🔴 THE CONSTRAINT THAT FORBIDS THE OBVIOUS SCHEMA

The obvious envelope is `{..., "feature": "mosaic", "payload": {...}}`.
**Do not do this.** `analysis/benchmark/score.py :: load_gt()` reads, at the **top level**:

```
doc["tiles"][k]["status"] == "anchor"   and   x / y
doc["tolerance_px"]["region_default"]
```

(`project.py:6-13`, and `export._assert_scoreable:580-602` checks exactly these two before the file
leaves the process.) **A project the scorer cannot read is a project that cannot be checked.**

⇒ **The mosaic payload is written FLAT, at the top level, beside the envelope keys.** `core.document`
owns *only the keys it names* and **must preserve unknown top-level keys and unknown per-tile keys
verbatim** (`project.py:992-993` already does this — for a different reason, and it is now doubly
load-bearing). Encode the feature in `"feature": "mosaic"` and route on that; do not nest.

### 4.3 The provenance hook — the one thing core must NOT delegate

`stamp()` (`project.py:668`) enforces:

> **ANY machine evidence ⇒ `independent_of_method: false` AND the warning, verbatim.**
> The verdict is derived from the document's **HISTORY**, never from what the document says about
> itself — because `seeded_from` is front-end-writable and "Skip — place from scratch" *erased it*
> while every tile kept t33's position. Scoring t33 against that gives ~100 % **by construction**.
> **This project has already destroyed one benchmark exactly this way**
> (`analysis/archive/challenge_2026-07/benchmark/ground_truth/260620d.json` **is T27's own output**).

Split it exactly here:

```python
# core/document.py — the RULE. No feature may opt out.
def stamp(doc, evidence_fn):
    ev = evidence_fn(doc)                 # the feature answers: "was a machine involved?"
    if ev:
        prov["seeded_from"] = ev
        prov["independent_of_method"] = False
        prov["warning"] = PROVENANCE_WARNING      # verbatim. Never paraphrased.
    else:
        prov["seeded_from"] = None
        prov["independent_of_method"] = True
        prov.pop("warning", None)

# features/mosaic/document.py — the EVIDENCE. (project.py:622 machine_evidence, verbatim.)
def machine_evidence(doc):  # -> seeded_from | None
    # provenance.seeded_from  OR  a `build` block  OR  a single tile still carrying `machine`
```

Same split for `validate()`: core checks the envelope; the feature returns
`[(kind, message)]` for its payload (`project._problems:715` → two functions).
⛔ **Keep `project.py:775-779` verbatim**: *no trial number is special.* The guard that used to live
there ("tile 284 is THROWN OUT and carries a position") made the user's own test session
**unsaveable** the moment he anchored 284.

---

## 5. THE BLANK SCAN — core or mosaic?

### 5.1 The case for MOSAIC

- **The only consumer is the matcher.** `engine._refusal` (`engine.py:698`) refuses a blank *target*
  and drops blank *anchors*. Nothing else in the app reads the list.
- **The reason it exists is a correlation artefact.** Two blank frames **136 trials apart** correlate
  **+0.43 at zero shift** (honest noise floor 0.115) because what they share is fixed-pattern
  **sensor** structure, which does not move with the stage. That is a statement about NCC
  registration — i.e. about the mosaic method — not about the frame.
- **The threshold is defined in mosaic's terms:** "the 2nd percentile of **pass-1** texture"
  (`loader.py:697`), and `pass 1` only exists because `pass_split` does.
- The user's tick lands in the mosaic document (`project.py:316-321`).

### 5.2 The case for CORE

- **The MEASURE is a property of the FRAME, not of the mosaic.** `std(DoG(3,30))` answers "how much
  texture is in this image". Every future feature asks that: a segmentation feature must not segment
  glare; a dataset browser must be able to say "these 11 frames are empty".
- **It is free if core owns the band stack, and 3.0 s if it does not.** `texture_map` (`loader.py:655`)
  is *bit-identical* whether it reads the band stack or reloads from disk — and the only reason `open`
  is ~5 s and not ~8 s is that the matcher's DoG stack and the texture measure are **the same array**
  (`loader.py:1068-1074`, `loader.py:658-663`). Push the measure into a feature and you either
  duplicate the array (+624 MiB) or duplicate the compute (+3.0 s).
- **The Screen step of the wizard is a DATASET step.** "Look at every frame; decide which are junk"
  is true whatever you do next.

### 5.3 THE DECISION

**Split it on the line the code already draws** — `blank_scan` itself distinguishes a MEASUREMENT
that never moves (`scanned`) from a DECISION that does (`blank`), `loader.py:719-725`. Cut there:

| layer | owns | new home |
|---|---|---|
| **MEASUREMENT** | `texture: {trial: round(std(band[i]), 2)}`. A pure per-frame number. **No threshold, no list, no policy.** | **`core/frames.py :: FrameStore.texture()`** (from `loader.texture_map:655`) |
| **PROPOSAL** | `threshold = pct(reference_texture, 2.0)`; `proposed = [t for t,v in texture if v < thr]`; `margin_warning`. Needs `pass_split` (mosaic) to pick its reference set. **Recommends. Never rejects.** | **`features/mosaic/blank.py :: propose()`** (from `loader.blank_scan:671`) |
| **DECISION** | the list the human ticked, which the matcher will refuse. | **the mosaic DOCUMENT** (`blank_scan.blank`) — and it travels **in the match request body**, never on the session. §2.4. |

**So: the blank scan is a CORE measurement with a MOSAIC policy on top, and the answer belongs to
neither — it belongs to the document.**

Three things that must survive the move, word for word:

1. ⇒ **THE SCAN RECOMMENDS. THE USER TICKS. NOTHING IS AUTO-EXCLUDED.** (`loader.py:677`)
2. ⚠️ **ZERO MARGIN AT THE BOUNDARY.** Genuinely-blank frames and perfectly good ones **interleave**
   below the threshold: `56 = 56.39 < [309 = 56.53] < 34 = 58.44 < [289 = 58.54] < 127 = 58.58 <
   55 = 59.98 < [thr 60.11] < 35 = 61.32` (`loader.py:686-690`). Measured with the refusal lifted:
   trials **34, 55, 56** land 0.24 / 0.18 / 2.07 px from the human truth — they are **ordinary tiles**
   — while **127** lands **679 px wrong** (`server.py:612-621`). One of four. That is exactly why the
   measure may only ever *propose*.
3. ❌ **NO BLUR JUDGEMENT. EVER.** Across all 338 snapshots and 15 focus measures, the best global
   blur threshold reaches **F1 = 0.37**; catching all 15 of the user's blurry frames also rejects 62
   good ones, best case. **Variance-of-Laplacian scores WORSE THAN CHANCE.** No slider. No number in
   the UI. The user meets every tile again in the sweep and excludes it with `E`. (`loader.py:679-683`)

And the rule that makes all of it legal under rule 4: **a measurement is not stored knowledge.** The
scan opens every frame it is given, measures it, and proposes. It remembers nothing between datasets,
and `BLANK_THRESHOLD = 60.1` (`__init__.py:53`) — 260620d's number, sitting in the app as a
"fallback" — **is deleted, not ported.**

---

## 6. BUGS FOUND WHILE SPLITTING (do not lose these)

**6.1 `loader.Cancelled` is never caught.** `loader.Cancelled` (`loader.py:990`) and `jobs.Cancelled`
(`jobs.py:155`) are **different classes**. `open_session`'s `check()` raises loader's;
`jobs.submit_thread` catches jobs' (`jobs.py:271`). So a cancelled `open` falls through to
`except BaseException` (`jobs.py:274`) and the job is marked **`failed`**, with a traceback, instead
of `cancelled`. `export.py` imports the right one (`export.py:53`). **One `Cancelled`, in `core/jobs`.**

**6.2 The autosave range guard is dead code.** `project.autosave()` (`project.py:1102`) carries the
guard written *because* pass 2's autosave silently overwrote pass 1's ground-truth records
(`:1106-1112`). **Nothing calls it** — `server.post_project_autosave` (`server.py:1038`) calls
`project.save()` into `project.autosave_path(store_key)`. `store_key` keys on the **directory**, not
on the **trial range**, so two ranges of one dataset still collide. **Port the guard and wire it up.**

**6.3 `POST /api/match/anchor` is not a pure function of its body** (contrary to `server.py:16-20`) —
it reads `session.blank`, which `PUT /api/scan/blank` mutates. See §2.4.

**6.4 Two of everything.** Duplicated, silently divergent, and each pair is a latent bug:
`_iso` ×3 · `_jsonable` ×3 · `_refuse_data_dir` ×3 · `_state_of` ×2 (**and they disagree**) ·
`STATE_TO_STATUS` ×2 · `TILE`/`DOG_*`/`SNAP_RADIUS`/`MARGIN_THIN` ×2–3 · the tone/PNG/thumb caches ×2
(`Session._u8`/`_thumbs` vs `server._PNG_CACHE`/`_THUMB_CACHE`) · `_auto_tone` ×2 · `band_pass` ×2
(§3) · `_atomic_write` vs `export._atomic_bytes` (**export's has no lock, no fsync, no retry**).

**6.5 `export._state_of` (`export.py:133`) mis-handles a bench-written GT.** For a row whose `status`
is `"region"` or `"pending"` it returns that string as the *state*, which is in neither
`{"anchored","unverified"}` — so `render_positions` (`export.py:145`) silently **does not render it**.
`project._state_of` (`project.py:186`) maps the same row to `"unverified"` (placed ⇒ unverified).
Use project's everywhere.
