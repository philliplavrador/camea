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
| **settings** | `GET` · `PUT /api/settings` | `SettingsUpdate` → `Settings` — workspace, dataset roots, recents |
| **datasets** | `GET /api/datasets` | → `DatasetListResponse` — **the home screen.** Everything under the remembered roots |
| *(the browser)* | `POST /api/datasets/scan` | `DatasetScanRequest` → `DatasetListResponse` — "point me at a folder" |
| | `GET /api/datasets/{key}` | → `DatasetDetail` — trials, timestamps, snapshot blocks, shapes |
| | `GET /api/datasets/{key}/thumbnail.png` | → PNG. One frame, **no session** — the browser card must not cost 5 s |
| **sessions** | `POST /api/sessions` | `OpenSessionRequest` → `202 JobRef` → `OpenJobResult` |
| *(an open dataset)* | `GET /api/sessions` · `GET /api/sessions/{id}` | → `SessionListResponse` · `SessionResponse` |
| | `DELETE /api/sessions/{id}` | → `OkResponse` — frees the stack |
| | `GET /api/sessions/{id}/log` | → `LogResponse` |
| | `GET /api/sessions/{id}/texture` | → `TextureResponse` — the per-frame **measurement**. No threshold, no policy |
| | `GET` · `PUT /api/sessions/{id}/tone` | `ToneUpdate` → `Tone` — **global, never per-tile** |
| **tiles** | `GET /api/sessions/{id}/tiles/{trial}.png?v=` | → 8-bit PNG, flat-fielded, through the global tone window |
| *(pixels)* | `GET /api/sessions/{id}/tiles/{trial}.raw` | → 16-bit little-endian, raw camera counts, no tone |
| | `GET /api/sessions/{id}/thumbs.png?v=` · `.json` | → sprite sheet · `ThumbsResponse` |
| **workspace** | `GET` · `PUT /api/workspace` | `WorkspaceSetRequest` → `WorkspaceInfo` |
| | `GET /api/workspace/analyses` | → `AnalysisListResponse` |
| | `POST /api/workspace/analyses` | `CreateAnalysisRequest` → `AnalysisSummary` — **the server authors the doc** |
| | `DELETE /api/workspace/analyses/{id}` | → `OkResponse` |
| **documents** | `GET` · `PUT /api/analyses/{id}/document` | `SaveDocumentRequest` → `DocumentResponse` · `SaveResult` |
| | `POST /api/analyses/{id}/autosave` | `AutosaveRequest` → `SaveResult` — **a failure is LOUD** |
| | `POST /api/documents/load` | `LoadDocumentRequest` → `LoadDocumentResponse` — works **cold** |
| | `POST /api/documents/save-as` | `SaveDocumentRequest` → `SaveResult` — `Save…`, reachable from every screen |
| | `POST /api/documents/validate` | `ValidateDocumentRequest` → `ValidationReport` |
| **jobs** | `GET /api/jobs` · `GET /api/jobs/{id}` | → `JobListResponse` · `Job` |
| | `POST /api/jobs/{id}/cancel` | → `JobCancelResponse` |
| **dialogs** | `POST /api/dialog/open-directory` · `open-file` · `save-file` | → `DialogPathResponse`. **501 when headless** — and the UI must fall back to something Playwright can answer, or there are no end-to-end tests |

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
| **6 · Mosaic** | `POST /api/mosaic/export` | `ExportRequest` → `202 JobRef` → `ExportResult` — 7 files; the coverage mask is **mandatory** |
| | `POST /api/mosaic/qc` | `QcRequest` → `QcReport` — every number states its denominator |

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
