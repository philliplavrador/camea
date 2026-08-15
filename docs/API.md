# API.md — an orientation. **This file is NOT the contract.**

> # ⛔ THE CONTRACT IS `src/camea/api/schemas.py` AND THE OPENAPI SCHEMA GENERATED FROM IT.
> **THIS FILE IS PROSE AND IT MAY LAG.** It is here to tell you *why* the route surface has the shape
> it has. It is not authoritative about a single field name, type, default or status code. When this
> file and `schemas.py` disagree, **`schemas.py` is right and this file is stale** — fix this file.
>
> **Never let this document become normative again.** Its predecessor
> (`archive/app-v1/API.md`) was 1,023 hand-written lines that *were* the contract, and it drifted
> from `server.py` across three commits until it was actively wrong in three places — it still
> described 26 hard-coded exclusions, a fatal blank anchor and a `force` flag, none of which the
> server had done for weeks. Seven agents built against it. **Prose cannot be compiled.**
>
> **Where to actually look:**
> - the types — `src/camea/api/schemas.py`
> - the live schema — `GET /openapi.json`, or `/docs` in the browser
> - the TypeScript client — **generated** from that schema. Never hand-written.

---

## The one-paragraph model

**A DATASET is raw, read-only, and the app never writes to it.** An **ANALYSIS** is what you did to
one, and it lives in a **WORKSPACE** the user chooses — never inside the dataset, never inside the
repo. Opening a dataset creates a **SESSION**: its pixels in RAM, shared by every feature that is
looking at it. A session holds *no* analysis state — no tile states, no exclusions, no run, no pass
split. Those belong to a **DOCUMENT**, which a **FEATURE** owns. Mosaic is the first feature. It will
not be the last, and every core route below exists to be used by the second one unchanged.

## The four ideas worth knowing before you read a route name

**1. The app carries no dataset knowledge.** There is no exclusion list anywhere in the API, no trial
number is special, and nothing is auto-excluded — not even by the blank scan, which only *proposes*.
Exclusions are user input and they ride in the document. The single thing the app imports from the
exclusion module is `gaps()`, a pure function over a trial list, and you can see it at
`POST /api/mosaic/gaps`. There is no toggle.

**2. A dataset is read-only; long jobs never block.** `open`, `build`, `export` and `recheck` return
a `job_id` and you poll `GET /api/jobs/{id}` at 500 ms. A job may hold an **exclusive lease** (the
build takes `"gpu"`); anything else that wants it gets `409 busy`. Cancel is `POST .../cancel`.

**3. ⭐ `POST /api/mosaic/match/*` is a PURE FUNCTION of its request body — and that is a correctness
proof, not a taste.** The sweep prefetches the *next* tile's match while the current one is still
fading in, which means the prefetch has to **assume the user will press `A`** and include the tile
under judgement in the anchor set. (Prefetching without it disagrees with the truth in 18 % of
presses and is catastrophically wrong — up to 1,143 px — in 6 %.) The server memoises on a key that
**is** the anchor set and their positions, so pressing `E` instead changes the key, misses the memo,
and forces an honest recompute. **The trap is impossible to fall into as long as the server holds no
tile state to be out of sync with.** So it holds none. The refusal (blank) list therefore travels
*in the body*, not on the session — and `PUT /api/scan/blank`, which used to mutate it, is **gone**.

**4. The server owns the document.** In v1 the front end did, and reimplemented `new_doc` and
`seed_from_build` in JavaScript — which is how the divert counters were silently dropped on every
save, and how "Skip — place by hand" could erase the provenance stamp while every tile still sat
exactly where the solver put it. Creating, seeding, validating, stamping and discarding a document
are all server routes now.

---

## The route table

### CORE — feature-agnostic. Feature #2 reuses every one of these.

| | route | body → response |
|---|---|---|
| **health** | `GET /api/health` | → `HealthResponse` |
| | `GET /api/gpu` | → `GpuInfo` — detection **executes a real op**; there is exactly one detector |
| **settings** | `GET` · `PUT /api/settings` | `SettingsUpdate` → `Settings` — ⛔ **two keys, both lists of paths**: `projects`, `recent_datasets` |
| **datasets** | `POST /api/datasets/at` | `DatasetAtRequest` → `DatasetListResponse` — *"what is in THIS folder"*. ⛔ Remembers nothing, looks no deeper than one level (R42) |
| | `GET /api/datasets/{key}` | → `DatasetDetail` — trials, timestamps, snapshot blocks, shapes |
| | `GET /api/datasets/{key}/thumbnail.png` | → PNG. One frame, **no session** — the receipt must not cost 5 s |
| **sessions** | `POST /api/sessions` | `OpenSessionRequest` → `202 JobRef` → `OpenJobResult` |
| *(an open dataset)* | `GET /api/sessions` · `GET /api/sessions/{id}` | → `SessionListResponse` · `SessionResponse` |
| | `DELETE /api/sessions/{id}` | → `OkResponse` — frees the stack |
| | `GET /api/sessions/{id}/log` | → `LogResponse` |
| | `GET /api/sessions/{id}/texture` | → `TextureResponse` — the per-frame **measurement**. No threshold, no policy |
| | `GET` · `PUT /api/sessions/{id}/tone` | `ToneUpdate` → `Tone` — **global, never per-tile** |
| **tiles** | `GET /api/sessions/{id}/tiles/{trial}.png?v=` | → 8-bit PNG, flat-fielded, through the global tone window |
| *(pixels)* | `GET /api/sessions/{id}/tiles/{trial}.raw` | → 16-bit little-endian, raw camera counts, no tone |
| | `GET /api/sessions/{id}/thumbs.png?v=` · `.json` | → sprite sheet · `ThumbsResponse` |
| **projects** | `GET /api/projects` | → `AnalysisListResponse` — the home screen, read off **Camea's store** (R44). Carries `unreadable` (a corrupt manifest) and, once, `migration` (the one-time move into the store) |
| *(one project = one folder, and **Camea owns it** — R44)* | `POST /api/projects` | `CreateAnalysisRequest` (⛔ **no `folder`**) → `AnalysisSummary` — **the server authors the doc**, in `store_root()/<analysis_id>/`. The user is never asked where it goes |
| | `GET /api/projects/{id}` | → `AnalysisSummary` — ONE project, what `/project/:id` opens with |
| | `PATCH /api/projects/{id}` | `RenameAnalysisRequest` → `AnalysisSummary` — manifest only; the folder never moves, the id is forever |
| | `DELETE /api/projects/{id}` | → `OkResponse`. ⭐ **Delete means delete** (R44.8): the project and everything in it, outputs included. `delete_files` is gone with R42.8's Remove |
| **outputs** | `GET /api/projects/{id}/outputs` | → `OutputListResponse` — ⭐ **the only door to a project's files** (R44.5). Read off the DIRECTORY, never the document. Empty is a normal answer, not a 404 |
| *(browse it in the app, or not at all)* | `GET /api/projects/{id}/outputs/{name}?download=` | The bytes. `no-store`. `download=true` sets a `Content-Disposition` attachment. ⚠️ `name` goes through `safe_basename` and is re-checked to sit in this project's `outputs/` |
| | `POST /api/projects/{id}/outputs/copy` | `CopyOutputsRequest` → `CopyOutputsResponse` — ⭐ **the one way work leaves Camea** (R44.6). A **copy**: the project keeps its files. `409 refused` into a dataset, or over a name already at the destination (**the whole request**, naming the files) |
| **documents** | `GET` · `PUT /api/analyses/{id}/document` | `SaveDocumentRequest` → `DocumentResponse` · `SaveResult` |
| | `POST /api/analyses/{id}/autosave` | `AutosaveRequest` → `SaveResult` — **a failure is LOUD** |
| | `POST /api/documents/load` | `LoadDocumentRequest` → `LoadDocumentResponse` — works **cold** |
| | `POST /api/documents/save-as` | `SaveDocumentRequest` → `SaveResult` — `Save…`, reachable from every screen |
| | `POST /api/documents/validate` | `ValidateDocumentRequest` → `ValidationReport` |
| **jobs** | `GET /api/jobs` · `GET /api/jobs/{id}` | → `JobListResponse` · `Job` |
| | `POST /api/jobs/{id}/cancel` | → `JobCancelResponse` |
| **dialogs** | `POST /api/dialog/open-directory` · `open-file` · `save-file` | → `DialogPathResponse`. **501 when headless** — and the UI must fall back to something Playwright can answer, or there are no end-to-end tests |

⛔ **`POST /api/fs/reveal` was DELETED on 2026-08-10 (R44.7).** It opened a project folder in
Explorer, and his ruling is that the app is the only way to browse project data. What replaced it is
`POST /api/projects/{id}/outputs/copy`: a copy of what he chose, where he chose, deliberately.
⛔ **`GET /api/projects/folder` went the same day** — there is no save folder to ask about.

### MOSAIC — the feature. Everything under `/api/mosaic`.

| step | route | body → response |
|---|---|---|
| **2 · Range** | `POST /api/mosaic/run` | `RunDetectRequest` → `RunDetection` — the run + the pass split, **measured**, always overridable. Not a session reload |
| | `POST /api/mosaic/document/rescope` | `RescopeRequest` → `RescopeResponse` — ⭐ `Apply`, made to stick: **the server re-authors the tile set** to the trials in range. Keeps every surviving tile's work; a dropped trial is **not** an exclusion |
| | `POST /api/mosaic/gaps` | `GapsRequest` → `GapsResponse` — the *only* touch of the exclusion module |
| **3 · Screen** | `POST /api/mosaic/screen/propose` | `BlankProposeRequest` → `BlankProposal` — **it recommends; the human ticks** |
| **4 · Place** | `POST /api/mosaic/build` | `BuildStartRequest` → `202 JobRef` → `BuildResult`. Takes the `gpu` lease |
| | `GET /api/mosaic/builds/{build_id}` | → `BuildResult` |
| | `POST /api/mosaic/seed` | `SeedRequest` → `SeedResponse` — **a re-solve must not destroy the human's work** |
| | `POST /api/mosaic/document/machine-evidence` | → `MachineEvidenceResponse` — derived from HISTORY, never from what the doc claims |
| | `POST /api/mosaic/document/discard-machine` | `DiscardMachineRequest` → `DiscardMachineResponse` — "Skip" is **destructive, or it is nothing** |
| **5 · Sweep** | `POST /api/mosaic/match/anchor` | `MatchAnchorRequest` → `MatchResult` — ⭐ the primitive. Place, alternatives, rescue and snap are all this one call |
| | `POST /api/mosaic/match/score` | `MatchScoreRequest` → `ScoreResult` — "you dropped it here; what do the pixels say?" |
| | `POST /api/mosaic/recheck` | `RecheckRequest` → `202 JobRef` → `RecheckResult` — **global**, and allowed to say **no** |
| **6 · Mosaic** | `POST /api/mosaic/export` | `ExportRequest` (⛔ **no `dir`** — R44: it writes into `<project>/outputs/`; `basename` names the files) → `202 JobRef` → `ExportResult` — 7 files; the coverage mask is **mandatory** |
| | `POST /api/mosaic/qc` | `QcRequest` → `QcReport` — every number states its denominator |

### VIDEOMOSAIC — the second feature. Everything under `/api/videomosaic`.

⭐ **NO folder question at all (R44).** Create takes one path — the video — and makes the project in
Camea's store; the build writes its artifacts into that project's `outputs/`, named after the
project. **There is no save route and no export route.** Getting a copy out is core's
`POST /api/projects/{id}/outputs/copy`, which every feature shares.

⚠️ R43 (2026-08-07) had this feature defer its folder question to the finished screen, as a draft in
`app_state_dir()/drafts/<id>/`. R44 removed the question instead of moving it again; drafts are gone.

| | route | body → response |
|---|---|---|
| **probe** | `POST /api/videomosaic/probe` | `VideoProbeRequest` → `VideoSource` — decodes a real frame, so "probed OK" means it will open. `fps`/`n_frames` are what the container CLAIMS |
| **create** | `POST /api/videomosaic/projects` | `CreateVideoProjectRequest` (**no `folder`**) → `AnalysisSummary`. The server authors the doc **in the store** (R44) and the project is listed from that moment — there are no drafts |
| **build** | `POST /api/videomosaic/build` | `VideoBuildRequest` → `202 JobRef` → `VideoMosaicBuildResult`. Cancellable; one `videomosaic` lease. `outputs` are **filenames**, not paths (a saved project moves) |
| **outputs** | `GET /api/videomosaic/{id}/outputs/{name}?v=` | The **logical** name (`mosaic.png` · `preview.png` · `positions.csv` · `build.json`), resolved through the doc's `build.outputs` to a real file in `<project>/outputs/`. `v` = `built_at`; the response is `no-store`. ⚠️ This is the feature's own `<img src>`; **browsing** a project is core's `GET /api/projects/{id}/outputs` |

⛔ **`POST /api/videomosaic/save` was DELETED on 2026-08-10 (R44.9).** There is nothing to save into:
the project has been in Camea's store since Create, and its mosaic is in that project's `outputs/`.

### ANALYZE MEA — the third feature. Everything under `/api/mea`.

⭐ **ONE data question, and it names the recordings he is bringing IN** — the video task names its
video, the snapshot task names its dataset folder, and this one names **several `.h5` files at
once**. ⚠️ **Updated 2026-08-14 (plan 002).** For one day this section read *"ZERO path questions"*,
because plan 001 shipped an intermediate state in which the project was created empty and filled
from inside. He reversed that the same day — *"you create the project then you select what you want
to do in this project ... then after that it asks you to upload the files you need for that task"* —
so the project is now created **with its recordings already on its shelf**. That restores R41 and
R44.2 rather than excepting them.

The project is still a *shelf*: several recordings, added at creation or later, each removable.

⚠️ **Not to be confused with `/api/videomosaic/.../mea/*`.** Those routes attach an electrical
recording to an *optical* project and resolve a `col-row` grid id through a chip seating nobody has
established yet. This feature has no microscope in it: the file states its own `electrode`, `x_um`
and `y_um`, so there is no seating question and it must not grow one.

| | route | body → response |
|---|---|---|
| **create** | `POST /api/mea/projects` | `CreateMeaProjectRequest` (`name` + an optional `paths`) → `AnalysisSummary`. ⭐ **Create-with-recordings is ONE call**: every path is read **before** the project is created, so a file that is not a MaxLab recording means the refusal **names it** and *no project exists* to clean up. `paths` omitted ⇒ the empty shelf, which is still a real state (it is what he is left with after removing his last recording). `dataset_key`/`dataset`/`data_dir` stay **empty on purpose** — a recording is a file on the shelf, not the project's dataset; `src/camea/features/mea/routes.py` records what was read to decide that |
| **browse** | `GET /api/mea/browse?path=` | → `MeaBrowseResult`. ⭐ **The one route in the app with NO project id**, and it must not be given one "for consistency": the wizard calls it *before a project exists*, which is exactly what lets one import component be mounted both there and inside a project. Every `data.raw.h5` under `path`, each with its own header facts. ⛔ Reads; never writes. A file that does not open is **listed** with `readable: false` and why — never dropped |
| **shelf** | `GET /api/mea/{id}/recordings` | → `MeaShelf`. ⚠️ `copy_state` is **derived from the disk and the job registry**, not echoed from the document, so a copy interrupted by a restart reports as `referenced` (which it is) rather than a `copying` that will never finish. Every number is read off the file on the way past — ⛔ nothing about what is *in* a recording is stored (I1) |
| **add** | `POST /api/mea/{id}/recordings` | `AddMeaRecordingsRequest` → `MeaShelf`, 201. Several at once; **all or nothing**, and the refusal names the file. Each lands as `referenced` and gets its own copy job (`mea_copy`, one **per recording** so the shelf can show a percentage per row) |
| **remove** | `DELETE /api/mea/{id}/recordings/{rid}` | → `MeaShelf`. Forgets it and deletes **Camea's copy**. ⛔ **The user's original is never touched, under any circumstance** |
| **the chip** | `GET /api/mea/{id}/recordings/{rid}/layout` | → `MeaChipLayout`. Every **routed** pad at the file's own `x_um`/`y_um`, plus `stride`/`pitch_um` **derived from the file's numbering and verified against every pad** (never a datasheet number, and never measured from the routed spacing — one of this project's recordings routed every other pad). ⛔ Only routed pads: a pad that was never routed is the *absence* of a measurement, not a silent one. ⭐ `chip_cols`/`chip_rows` size **the whole chip**, so the map can show which part of it was recorded (his answer, 2026-08-14) — the width is the derived stride; the height is not in the file, so it is the other axis of `core.electrodegrid.MAXWELL` when the stride matches one of them and otherwise only what the file evidences. `chip_extent` says which, because the device is **consulted, never assumed** |
| **activity** | `GET /api/mea/{id}/recordings/{rid}/activity` | → `MeaChipActivity`. Per-pad spike count and spikes/s, one row per pad in `layout` order. ⭐ **From the spike table, so no proprietary decoder is involved** — the chip map is trustworthy on every machine, including the ones where the waveform is a rail. ⛔ A count, not a verdict: `max_rate_hz` is the busiest pad *in this recording*, and no number anywhere says how active a chip should be (I1) |
| **one pad's trace** | `GET /api/mea/{id}/recordings/{rid}/trace?channel=&t0=&t1=&max_points=` | → `MeaChannelTrace`. ⭐ **By `channel`, because the click already knows its channel** — the chip map was drawn from the file's own coordinates, so nothing has to be resolved. ⛔ No `orientation` and no `chip_electrode`: there is no seating question here. `health.flat` says the waveform did not decode; the spikes are returned and correct either way. ⭐ **`max_points` is how a window wider than 30 s is asked for.** Omit it and you get raw samples, still capped at `MAX_TRACE_SECONDS` — the original contract, unchanged. Pass it (the number of columns you can draw) and the server returns a **min/max envelope** in `min_uv`/`max_uv` with `resolution: "envelope"`, and **the cap does not apply**, so the whole recording costs the same as a second of it. ⚠️ **Label your axis from the returned `t0_s`/`t1_s`**: the raw path clamps silently to the cap and the envelope path snaps to stored bucket edges. Windows narrow enough to read cheaply (`LIVE_READ_MAX_SAMPLES`, compared against a sample count derived from the file's own `sampling_hz`) are still read live; wider ones come from the precomputed envelope, and a **409 `refused` with `detail.needs: "envelope"`** means that one-off read has not happened for this recording yet |
| **whole-recording reads** | `GET`/`POST /api/mea/{id}/recordings/envelopes` | → `MeaEnvelopeStatus`. Which recordings can be shown whole yet, and the way to start the one-off pass for the ones that cannot. ⭐ **Why it is a job and not a request:** `groups/routed/raw` is chunked `(n_channels, 200)`, so reading ONE channel end to end decompresses every channel — measured 12–23 s for one against 19–32 s for all of them, and 37–70 s once the exact per-channel health tally is included. Every channel is done in one pass, once, and cached at `<project>/recordings/<id>/envelope.npz` (**R44** — inside the project, never in `outputs/`, because a cache is not something he asked Camea to make). New recordings get this at import; the `POST` is the **backfill** for anything already in a project (his instruction, 2026-08-15). ⚠️ `ready: false` never means a recording is broken — only that the whole of it cannot be drawn at once yet |

⭐ **Where the bytes are.** A recording is usable the instant it is added, read from wherever it
sits; a background job copies it into `<project>/recordings/<rid>/` (R44 — inside the project and
nowhere else, source opened read-only) and every later read uses that copy.
`features/mea/recordings.py :: open_path` is the **one** place that decides which of the two to
read, and everything added later must call it rather than deciding again. ⭐ The three routes above
reach it through `routes.py :: _recording_path`, so *"source or copy?"* is answered once for the
whole screen — three routes each deciding for themselves is how one half of a screen ends up on a
stale copy while the other is on the original.

⭐ **`layout` and `activity` are plain GETs, and that was measured, not assumed** (plan 003 § Open).
One pass over the spike table of a real recording from the mirror costs **2.3–21 ms** end to end —
the worst case being 982 channels against 244,925 spikes. Nothing here needs a spinner, let alone a
job, so the screen draws on its first paint.

---

## Three things that will look like bugs and are not

**The blank list is in the match request body, not on the server.** It looks redundant to send it on
every call. It is idea 3 above: the moment the server remembers a refusal set, the match endpoint
stops being a pure function of its body and the prefetch's correctness argument collapses.

**A blank ANCHOR is dropped, not fatal; a blank TARGET is refused.** These are not symmetric and must
not be made so. Making a blank anchor an error dead-ended the whole app: the moment the user anchored
the first near-threshold frame, every subsequent `Space` refused *forever* and the sweep died one
tile later.

**`state` and `status` differ, for exactly one value:** in memory a tile is `anchored`; on disk its
`status` is `"anchor"`. The benchmark scorer keeps every tile whose `status == "anchor"` — get the
mapping wrong and either nothing or everything lands in the exported ground truth.

---

## Reading order for the rest

`docs/SPLIT.md` — the normative core/mosaic split, symbol by symbol.
`docs/BEHAVIOUR.md` — what the UI must do, written so that every statement can *fail*.
`src/camea/api/schemas.py` — **the contract.** Every field carries the reason it is shaped that way.
