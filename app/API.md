# API.md — the contract

> **This file is the contract.** Seven agents implement against it in parallel, without talking to
> each other. Where it says MUST, it means it. Where a number appears, use that number.
> If you think the contract is wrong, **say so in your report** — do not "fix" it locally, because
> the other six agents are still building against what is written here.
>
> Read [PLAN.md](PLAN.md) (what the app is) and [RECON.md](RECON.md) (the API surface + the traps)
> first. This file only says *how the two halves talk*.

---

## 0. Architecture, in one picture

```
app/main.py                  pywebview native window (WebView2). Starts uvicorn on a thread,
                             binds 127.0.0.1:<random free port>, then opens the window on it.
   │
   ├── app/backend/server.py FastAPI. Owns the SESSION (data_dir, run, frames, tone, texture,
   │                         build result, job registry). Serves app/frontend/ as static files.
   │      │
   │      ├── loader.py      log.txt parse, frame IO (numpy, flipped), flat-field, tone, blank scan
   │      ├── engine.py      calls analysis/mosaic/{t27,t33,render}. NEVER forks them.
   │      ├── jobs.py        the async job registry (open / build / export)
   │      ├── project.py     the project file (read/write/validate) — project_schema.json
   │      └── export.py      TIFF / PNG / positions.csv / GT JSON / QC report
   │
   └── app/frontend/         index.html + viewer.js (canvas) + sweep.js (the sweep) + style.css
```

**The backend is almost stateless with respect to the document.** The *document* (tile states,
positions, exclusions, cursor) is owned by the **front end** — it has the undo/redo stack — and is
posted **whole** to the backend whenever the backend needs it (save, autosave, export). The backend
owns only what is expensive: the pixels, the tone window, the texture scan, the build result, and
the jobs.

Consequence, and it is deliberate: **`POST /api/match/anchor` is a pure function of its request
body.** It does not read server-side tile state. That is what makes the A-branch prefetch (§7.4)
correct *by construction* rather than by discipline.

---

## 1. Conventions

| | |
|---|---|
| **Base URL** | `http://127.0.0.1:<port>` — the front end reads it from `window.CAMEA_API` (injected by `main.py`) and falls back to `location.origin`. |
| **Prefix** | Every JSON endpoint is under `/api/`. Static files are served from `/`. |
| **Encoding** | `application/json; charset=utf-8` in and out, except the pixel endpoints (§5). |
| **Trial ids** | Integers everywhere in request/response **arrays**. In JSON **object keys** they are decimal strings without padding (`"11"`, `"348"`) — JSON has no integer keys. Never zero-pad a key. |
| **Positions** | `[x, y]` — **float**, the **TOP-LEFT CORNER** of the tile, in world pixels. ⚠️ **NOT the centre.** Anything that draws a centre adds +256. |
| **Orientation** | Every pixel, every position, every dx/dy in this API is in the **180°-flipped display frame** (§3). There is no other frame. |
| **Errors** | Non-2xx returns `{"error": {"code": "...", "message": "...", "detail": {...}}}`. Codes used: `no_session`, `bad_request`, `not_found`, `busy`, `job_failed`, `refused`, `io_error`. |
| **Time** | ISO-8601 UTC strings with `Z`. |
| **CORS** | Not needed (same origin). Do **not** add a permissive CORS policy. Bind `127.0.0.1` only — never `0.0.0.0`. |

### 1.1 Constants that MUST NOT diverge

Both halves hard-code these. They are copied here so nobody has to go looking.

```
TILE              = 512            # px, square. t33.TILE, t27.H/W.
FADE_MS           = 1000           # the placement fade, transparent -> opaque
DOG_LO, DOG_HI    = 3, 30          # the band-pass everything matches on
FLAT_SIGMA        = 15.0           # vignette = Gaussian(sigma=15) of the per-pixel median
TONE_PCT_LO       = 0.5            # global tone window percentiles, AFTER flat-fielding
TONE_PCT_HI       = 99.6
TONE_N_SAMPLE     = 96             # frames sampled (evenly) to estimate flat + tone
BLANK_PCT         = 2.0            # blank threshold = this percentile of PASS-1 texture
BLANK_THRESHOLD   = 60.1           # the value that yields on 260620d; RECOMPUTED per dataset
SNAP_RADIUS       = 64             # default local-search radius, px
ANCHOR_KPK        = 8              # t33.match kpk for a single-tile anchor
ANCHOR_MINFRAC    = 0.0            # ⚠️ exactly t33.place's tile-anchor call (t33.py:732)
ANCHOR_MINABS     = 120000.0       # ⚠️  ditto. Do not "improve" these.
MATCH_CACHE_SIZE  = 32             # LRU entries for the anchor-match memo (§7.4)
```

---

## 2. The tile state machine — **defined once, here**

Shared by the front end, the backend, the project file and the exports. There are **four** states.

| `state` | position | in the **anchor field**? | drawn as | exported | GT `status` |
|---|---|---|---|---|---|
| `unplaced` | `null` | no | not drawn; appears in the queue / rescue list | no | `"unplaced"` |
| `unverified` | yes | **NO** | **55 % opacity + dashed outline**, above the anchor layer | yes, flagged | `"unverified"` |
| `anchored` | yes | **YES** | 100 % opacity, **bottom layer** | yes | `"anchor"` |
| `excluded` | `null` | no | **not drawn, not matched, not rendered, not exported** | no | `"excluded"` |

⭐ **`Space` without a decision leaves the tile `unverified`: placed, drawn dimmer, NOT part of the
anchor field, and it does not block progress.** Deferring a hard tile must never stall the sweep.
The header shows an outstanding-`unverified` counter.

### 2.1 Transitions — the complete table. No others exist.

| trigger | from | to | position |
|---|---|---|---|
| session open | — | `unplaced` | `null` |
| session open, tile in the blank scan **and** the user accepted the recommendation | — | `excluded` | `null` |
| a build finishes | `unplaced` | `unverified` | the build's position |
| a build finishes, tile not placed by the solver | `unplaced` | `unplaced` | `null` |
| **`A`** (anchor) | any of `unplaced` / `unverified` / `anchored` | `anchored` | if it had none, first run `POST /api/match/anchor` and take `candidates[0]`. If **no tile anywhere has a position yet**, this tile is the origin and gets `[0, 0]`. |
| **`E`** (exclude) | any | `excluded` | `null` (the old value is kept in `last_xy` so undo restores it) |
| **`Space`** (advance) | `unplaced` | `unverified` | `POST /api/match/anchor` → `candidates[0]`. If the match is **refused** (§7.3) or returns no candidates, the tile stays `unplaced` and the cursor still advances. |
| **`Space`** | `unverified` / `anchored` | **unchanged** | unchanged |
| drag, snap, arrow-key nudge | `unplaced` | `unverified` | the new position |
| drag, snap, arrow-key nudge | `unverified` / `anchored` | **unchanged** | the new position |
| un-exclude (from the exclusion panel) | `excluded` | `unverified` if `last_xy` exists, else `unplaced` | `last_xy` or `null` |

**A drag never demotes an anchor.** If the user moves an anchored tile, he is *correcting* it and it
stays anchored. The UI must then badge the tiles that were matched against the field *before* the
move as possibly stale (see §7.5). Do not silently demote — that loses his decision.

⚠️ **Any change to the `excluded` set MUST recompute the acquisition gaps** (`t33.breaks` /
`excluded.gaps`) before the next build, or the serpentine one-step prior is applied across a
multi-step jump and the solve is silently poisoned. See `GET /api/session` → `gaps`.

### 2.2 `Space` skips excluded tiles

The cursor advances to the **next trial in `run.trials` whose state is not `excluded`**, wrapping is
**not** allowed (at the end, the sweep is done). `run.trials` is already free of the 26 thrown-out
snapshots — those never enter the session at all (§4.2).

---

## 3. Coordinates, orientation, and the composite arithmetic

**Read this section before writing any position code.** Every number below is load-bearing.

### 3.1 The 180° flip

A snapshot on disk is a headerless raw `.dat`: **uint16, little-endian, 512×512, exactly 524,288
bytes**. The trial XML carries `ax=-1, ay=-1`, so the *display* frame is the raw array **rotated
180°**. Load it **exactly** like this and nothing else:

```python
raw = np.fromfile(dat, "<u2").reshape(512, 512)
img = np.flip(np.flip(raw, 1), 0).astype(np.float32)     # analysis/texture/make_texture.py:37
```

Every existing position, every SWIM `dx`/`dy`, and **all three ground truths** live in the flipped
frame. Get it wrong and the app is 180° out from every prior result — **and it will look plausible.**
The loader MUST assert the flip against a known frame before anything else runs.

### 3.2 World coordinates

`position[t] = [x, y]` = the **top-left corner** of tile `t` on a common canvas, in px, floats.
The world origin is arbitrary (a layout is defined only up to a translation). The exporter
normalises it: it subtracts `position[origin_trial]`, where `origin_trial = min(anchored trials)`,
so the exported GT has that tile at exactly `[0, 0]` — matching `analysis/ground_truth/`.

Canvas geometry, for a set of positions `P`:
```
W = ceil(max(P.x) - min(P.x)) + 512
H = ceil(max(P.y) - min(P.y)) + 512
```

### 3.3 ⭐ The composite ↔ world conversion (get this wrong and everything is 512-ish px off)

`t33.composite(B, rows, local) -> (img, mask, m0)` where **`m0 = local.min(0)`** — the world
position of the composite image's own `(0,0)` pixel. So:

```
tile inside the composite   :  local - m0
composite pixel -> world    :  world = composite_px + m0
```

`t33.match(A, MA, Bi, MB) -> [(ncc, dx, dy, npix)]` with **`(dx, dy) == originB - originA`**.
For a single tile matched against an anchor composite we call it as `match(IMG, MSK, tile, TMSK)`,
i.e. **A = the composite, B = the tile**. Therefore:

```
                      ⭐  world_topleft(tile) = m0 + (dx, dy)  ⭐
```

and, going the other way, to score a human-dragged world position `p` with `t33.exact_ncc`:

```
dx = round(p.x - m0.x)          # exact_ncc takes INTEGER offsets
dy = round(p.y - m0.y)
ncc, npix = t33.exact_ncc(IMG, MSK, tile, TMSK, dx, dy)
```

**The backend does this conversion. The API only ever speaks world coordinates.** `dx`/`dy` and
`m0` never cross the wire except as debug fields. This is deliberate: it is the single easiest
place for seven implementations to diverge.

### 3.4 The tile the matcher sees

The matcher's tile is **band-passed and mean-subtracted**, exactly as `t33.place` prepares it
(`t33.py:730-731`):

```python
B    = t27.band_pass(frames)          # DoG 3/30 over the whole stack, once, at load
tile = B[row].astype(np.float32)
tile = tile - tile.mean()
TMSK = np.ones((512, 512), bool)
```

The composite is built from the **same band-passed stack** `B`, never from raw or tone-mapped pixels.
Tone mapping (§6) is for the **display only** and must never touch the matcher.

### 3.5 Sub-pixel refinement — **specified here so it cannot diverge**

`t33.match` and `t33.exact_ncc` are integer-only. The snap must be sub-pixel. The backend refines
the winning **integer** offset `(dx, dy)` with a separable parabola over the exact-NCC 3×3
neighbourhood — 8 extra `exact_ncc` calls, ~30 ms:

```python
def _subpixel(IMG, MSK, tile, TMSK, dx, dy):
    """(dx, dy) integer winner -> (fx, fy) float. Separable parabolic peak fit."""
    def s(ex, ey):
        v, _ = t33.exact_ncc(IMG, MSK, tile, TMSK, dx + ex, dy + ey, stride=1)
        return v if np.isfinite(v) else -1.0
    c = s(0, 0)
    def delta(a, b):                       # a = s(-1), b = s(+1)
        den = a - 2.0 * c + b
        if den >= 0.0:                     # not a peak -> do not interpolate
            return 0.0
        return float(np.clip(0.5 * (a - b) / den, -0.5, 0.5))
    ddx = delta(s(-1, 0), s(1, 0))
    ddy = delta(s(0, -1), s(0, 1))
    return dx + ddx, dy + ddy
```

This is **additive** — it does not change `t33` and cannot affect `analysis/tests/test_mosaic_312.py`.
It is applied to `candidates[0]` only (the alternatives stay on integers; nobody drags to an
alternative and then trusts its third decimal).

---

## 4. Session — open a directory, get the run

### 4.1 `POST /api/session/open` → a **job**

Loading is 2–6 s (frames + flat-field + tone + the 3.0 s texture scan), so it is a job (§8).

**Request**
```json
{
  "data_dir": "D:/Projects/Camea/data/drive/260620/260620_Imaging/260620d",
  "project_path": null
}
```
`project_path` — optional. If given, that project file is loaded **after** the directory and its
`run`/`pass_split`/tile states override the detected ones.

**Response** `202`
```json
{"job_id": "job_7f3a1c", "kind": "open"}
```

Job phases: `scan_dir` → `parse_log` → `load_frames` → `flat_field` → `tone` → `texture` → `done`.

On success the job's `result` is the same object as `GET /api/session`.

### 4.2 `GET /api/session` → everything the front end needs to draw

`404 {"error": {"code": "no_session"}}` before a successful open.

```json
{
  "data_dir": "D:/Projects/Camea/data/drive/260620/260620_Imaging/260620d",
  "dataset": "260620d",
  "opened_at": "2026-07-12T14:03:11Z",

  "run": {
    "lo": 11,
    "hi": 348,
    "trials": [11, 12, 13, "...", 347],
    "n": 312,
    "n_in_range": 338,
    "detected": true,
    "why": "longest contiguous block of Snapshot trials (3 blocks found: 1, 5-7, 11-348)",
    "blocks": [[1, 1], [5, 7], [11, 348]]
  },

  "pass_split": {
    "value": 166,
    "detected": true,
    "why": "largest interior inter-trial gap: 166->167 is 20.0 s (median 2.0 s); the block's first step (11->12, 20.0 s) was ignored",
    "gap_s": 20.0,
    "median_gap_s": 2.0,
    "runner_up": {"after_trial": 233, "gap_s": 8.0},
    "n_pass1": 156,
    "n_pass2": 156
  },

  "gaps": [[283, 297], [298, 311]],

  "excluded": {
    "trials": [284, 285, "...", 348],
    "n": 26,
    "source": "hard-coded ruling (analysis/ground_truth/excluded.py)",
    "locked": true
  },

  "tiles": {
    "11": {
      "trial": 11,
      "time": "2026-06-20T16:02:44Z",
      "pass": 1,
      "w": 512, "h": 512,
      "bytes": 2, "dtype": "uint16",
      "flip_x": true, "flip_y": true,
      "texture": 132.4,
      "blank": false,
      "dat": "011-ccd.dat"
    }
  },

  "tone":  { "...": "see GET /api/tone" },
  "blank": { "...": "see GET /api/scan/blank" },
  "gpu":   { "available": true, "backend": "cupy", "name": "NVIDIA GeForce RTX 4070" },

  "build": null,
  "project_path": null,
  "autosave_path": "C:/Users/phill/AppData/Local/Camea/autosave/260620d.camea.json"
}
```

**`run.trials` is THE trial list and it is already filtered.** It is `usable_trials(lo, hi)` from
`analysis/ground_truth/excluded.py` — the 26 thrown-out snapshots and every non-snapshot are gone.
⛔ **The excluded 26 are never loaded, never in `tiles`, never served as pixels, never matched,
never rendered.** They appear only as integers in `excluded.trials`, so the UI can say *why* trial
284 is missing.

**Detection rules** (loader; both must be *measured*, never hard-coded):
- **Run** = the **longest contiguous block of `Snapshot` trials** in `log.txt`. On 260620d: 11–348.
- **`pass_split`** = the trial *before* the **largest interior inter-trial time gap**, **ignoring the
  block's first step** (11→12 is also 20 s — settling right after `Settings loaded` — and would win
  a naive max-gap rule). On 260620d: 166.
- ⚠️ `log.txt` prints the date **only** on `New experiment:` lines; every other line carries
  `HH:MM:SS` alone. Carry the date forward and handle midnight rollover.
- ⚠️ Both rules are validated on **n = 1 dataset**. Always show them, always let the user override.

### 4.3 `PATCH /api/session/run` — the user overrides the detection

**Request** (any subset; omitted fields keep their current value)
```json
{"lo": 11, "hi": 348, "pass_split": 166}
```
**Response** `202` `{"job_id": "job_9b2e04", "kind": "open"}` — a reload. It invalidates the build
result, the tone window and the texture scan. **The front end MUST warn if a document exists**
(tile states are keyed on trial, so they survive, but positions from a stale build do not).

### 4.4 `GET /api/session/log` — the raw parsed log, for the "is this the right run?" panel

```json
{
  "experiment": "260620d",
  "entries": [
    {"trial": 1,  "type": "Snapshot",     "time": "2026-06-20T15:47:05Z", "gap_s": null},
    {"trial": 2,  "type": "E'phys. + VSD","time": "2026-06-20T15:48:54Z", "gap_s": null},
    {"trial": 11, "type": "Snapshot",     "time": "2026-06-20T16:02:44Z", "gap_s": 20.0}
  ],
  "n_snapshot": 342,
  "n_other": 6
}
```
`gap_s` is the seconds since the previous **Snapshot** (null for the first one and for non-snapshots).

---

## 5. Pixels

### 5.1 `GET /api/tile/{trial}.png?v={tone_version}`
The display tile. **8-bit grayscale PNG, 512×512**, flat-fielded and mapped through the **global**
tone window (§6). This is what the canvas draws.
- `v` is `tone.version` (§6). It exists **only** to bust the browser cache. The server ignores its
  value and always renders with the current tone.
- Response headers: `Content-Type: image/png`, `Cache-Control: public, max-age=31536000, immutable`.
- `404` if `trial` is not in `run.trials` (this includes every one of the 26 excluded).

### 5.2 `GET /api/tile/{trial}.raw`
The **16-bit** pixels. `Content-Type: application/octet-stream`, exactly **524,288 bytes**, uint16
**little-endian**, 512×512 row-major, **already flipped** (§3.1), **raw camera counts** (no
flat-field, no tone). Headers: `X-Camea-Shape: 512,512`, `X-Camea-Dtype: <u2`.

### 5.3 `GET /api/thumbs.png?v={tone_version}` + `GET /api/thumbs.json`
The contact sheet (step 1). One sprite sheet, 8-bit grayscale PNG, `grid × grid` cells of
`cell` px each, in `trials` order, row-major.
```json
{"grid": 18, "cell": 64, "trials": [11, 12, "...", 347], "n": 312, "version": 3}
```
Cell `i` of trial `trials[i]` sits at `(x, y) = ((i % grid) * cell, (i // grid) * cell)`.

---

## 6. The global tone window

⚠️ **Tone-map GLOBALLY, never per-tile.** A per-tile percentile stretch over-brightens near-empty
frames and makes overlapping tiles disagree in brightness, **which destroys the Difference-mode
check the whole verification loop depends on.**

### 6.1 `GET /api/tone`
```json
{
  "lo": 118.4,
  "hi": 1902.7,
  "level": 861.0,
  "flat_sigma": 15.0,
  "pct_lo": 0.5,
  "pct_hi": 99.6,
  "n_sample": 96,
  "auto": true,
  "version": 1
}
```
Computed at load from up to `TONE_N_SAMPLE = 96` frames sampled evenly across `run.trials`:
vignette `flat_n` = normalised Gaussian(σ=15) of the per-pixel median; `level` = median of the
per-frame medians; then `lo`/`hi` = the 0.5 / 99.6 percentiles of the flat-corrected sample.

Display mapping, applied identically to **every** tile and to the export PNG:
```python
c = flat_correct(load_frame(t), flat_n, level)                 # utils/artifact/build_page.py:140
u8 = np.clip((c - lo) * (255.0 / (hi - lo)), 0, 255).astype(np.uint8)
```

### 6.2 `PUT /api/tone` — the live window/level he has never had
**Request** `{"lo": 90.0, "hi": 2400.0}` (either may be omitted to keep it; `{"auto": true}` resets)
**Response** the full tone object with `version` **incremented** and `auto: false`.

⚠️ On a `version` change the front end MUST re-request every tile PNG with the new `?v=` and rebuild
the baked background canvas. Tone **never** affects matching (§3.4) or the exported TIFF.

---

## 7. ⭐⭐ The anchor-composite primitive — the heart of the app

**One endpoint powers four features.** `POST /api/match/anchor` takes the currently **anchored**
tiles plus a target, builds the anchor composite, matches the target against it over the whole
plane, and returns a **ranked** candidate list with NCC and margin.

| feature | how |
|---|---|
| **place the next tile** (`Space`) | `mode: "global"`; take `candidates[0]` |
| **show ranked alternatives** ("did you mean here?") | the *same response* — `candidates[1..]` |
| **rescue a tile the solver could not place** | the *same call*, on an `unplaced` tile |
| **snap a human's drag** | `mode: "local"` + `near` = the drop point |

*Why this is the right primitive, not just a convenient one:* of 719 genuinely-overlapping tile
**pairs** on this data, the exact-NCC argmax is **>20 px wrong for 38 (5 %), at scores up to 0.760**
(222 vs 250: the 0.760 winner is **757 px wrong**; the truth is the runner-up at 0.677). The **same
tile against a composite** scores 0.654 vs 0.416 next best and lands **1.7 px** from the human.
**Aperture is everything**, and the anchor field the user is building is a big, human-certified one.

### 7.1 `POST /api/match/anchor`

**Request**
```json
{
  "target": 168,
  "anchors": [11, 12, 13, 14, 15],
  "positions": {
    "11": [0.0, 0.0],
    "12": [0.0, 180.0],
    "13": [0.0, 360.0],
    "14": [0.0, 540.0],
    "15": [1.0, 719.0]
  },
  "mode": "global",
  "near": null,
  "radius": 64,
  "max_candidates": 8
}
```

| field | type | meaning |
|---|---|---|
| `target` | int | the tile to place. MUST be in `run.trials`. |
| `anchors` | int[] | the tiles forming the reference field. **Order is irrelevant** (the server sorts). MUST be non-empty and MUST NOT contain `target`. |
| `positions` | {str: [f,f]} | world top-left of **every** trial in `anchors`. Extra keys are ignored. A missing anchor is a `400`. |
| `mode` | `"global"` \| `"local"` | `global` = whole-plane FFT (`t33.match`, ~1 s). `local` = exhaustive `exact_ncc` inside `radius` of `near` (~0.2 s). |
| `near` | [f,f] \| null | REQUIRED when `mode == "local"`: the world top-left the user dropped the tile at. |
| `radius` | int | `local` only. Default `64`. Clamped to `[8, 256]`. ⚠️ **Never widen this past 128 in the UI**: the electrode grid repeats every **256 px**, and a wide *local* search will confidently lock onto a grid alias. To search wide, use `mode: "global"` — the FFT + margin is what survives the aliases. |
| `max_candidates` | int | default 8, clamped `[1, 16]`. |

**Response** `200`
```json
{
  "target": 168,
  "mode": "global",
  "n_anchors": 5,
  "composite": {"w": 1536, "h": 1231, "valid_px": 984320, "m0": [0.0, 0.0]},
  "candidates": [
    {"rank": 0, "x": 512.37, "y": 180.12, "ncc": 0.8137, "npix": 218432, "subpixel": true},
    {"rank": 1, "x": 268.00, "y": 434.00, "ncc": 0.5761, "npix": 197004, "subpixel": false},
    {"rank": 2, "x": 768.00, "y": -76.00, "ncc": 0.4160, "npix": 143221, "subpixel": false}
  ],
  "best": {"rank": 0, "x": 512.37, "y": 180.12, "ncc": 0.8137, "npix": 218432, "subpixel": true},
  "margin": 0.2376,
  "margin_thin": false,
  "refused": null,
  "gpu": true,
  "elapsed_ms": 1068,
  "cached": false,
  "cache_key": "a3f19c2e8b6d0417"
}
```

- `candidates[i].x/y` are **world top-left positions** — not `dx`/`dy`. The server has already done
  the `m0 + (dx, dy)` conversion (§3.3). **The front end never sees a composite coordinate.**
- `candidates` is sorted by `ncc` descending, peaks ≥ 24 px apart (t33's NMS). May be **empty**.
- `best` = `candidates[0]`, or `null` if there are none.
- `margin` = `candidates[0].ncc - candidates[1].ncc`; `null` if there is only one candidate.
- `margin_thin` = `margin is not None and margin < 0.10`. ⚠️ **The UI MUST flag it loudly.** The
  shipped build's worst *run* margin is **0.081** against a ~0.47 typical — a thin margin is exactly
  what a surviving alias looks like.
- ⚠️ **The aperture is small at the start.** With one anchor down this call *is* a tile-pair — the
  weak case above. It works anyway because **consecutive snapshots overlap ~78 %**, and consecutive
  whole-frame matches are the alias-robust ones. **But surface the evidence** — show `n_anchors`,
  `composite.valid_px`, `ncc` and `margin` on every placement, so the user watches the evidence
  strengthen instead of taking it on faith.

**Under the hood** (engine.py — do exactly this):
```python
rows   = [row_of[t] for t in sorted(anchors)]
local  = np.array([positions[t] for t in sorted(anchors)], float)
IMG, MSK, m0 = t33.composite(B, rows, local)            # t33.py:274
tile   = B[row_of[target]].astype(np.float32); tile -= tile.mean()
TMSK   = np.ones((512, 512), bool)
c = t33.match(IMG, MSK, tile, TMSK,                     # t33.py:436 — already returns the ranked list
              kpk=ANCHOR_KPK, minfrac=ANCHOR_MINFRAC, minabs=ANCHOR_MINABS)
# world = m0 + (dx, dy)
```
For `mode: "local"`: skip `t33.match`; sweep `exact_ncc` over the integer offsets within `radius` of
`near - m0` (stride 4, then stride 1 in ±4 of the coarse winner), then §3.5's sub-pixel fit. Return
the top `max_candidates` distinct (≥24 px apart) peaks in the same shape.

### 7.2 `POST /api/match/score` — "you dropped it *here*; what do the pixels say?"

One `exact_ncc`, no search. Used live during a drag (debounced) and to label the alternatives.

**Request**
```json
{"target": 168, "anchors": [11, 12, 13], "positions": {"11":[0,0], "12":[0,180], "13":[0,360]},
 "at": [512.0, 180.0]}
```
**Response**
```json
{"target": 168, "at": [512.0, 180.0], "ncc": 0.8129, "npix": 218432,
 "refused": null, "elapsed_ms": 31}
```
`ncc` is `null` when the overlap is below `t33.exact_ncc`'s floor (< 3000 valid px, or < 64 px on a
side) — the honest answer is "not measurable", never `0.0`.

### 7.3 ⛔ Refusal — blank tiles are REFUSED, not scored

Two **blank** frames **136 trials apart** correlate **+0.43 at zero shift** (honest noise floor
0.115) because what they share is *fixed-pattern sensor structure*, which does not move with the
stage. **They register confidently and wrongly.**

If **`target`** is in the blank scan's `blank` list (§9), the match endpoints return `200` with:

```json
{
  "target": 304,
  "candidates": [],
  "best": null,
  "margin": null,
  "refused": {
    "reason": "blank",
    "trials": [304],
    "texture": 41.83,
    "threshold": 60.11,
    "message": "Trial 304 is near-featureless glare. Any match it scores is fixed-pattern sensor structure, not the scene — it would register confidently and wrongly. Place it by hand, or exclude it."
  }
}
```

**There is no `force` flag and there will not be one.** The user may still *drag* a blank tile into
place by hand (a human eye is allowed to do what the correlator must not), but **snap, place-on-Space
and score all refuse.** A blank tile the user does not exclude simply stays `unverified`.

#### ⚠️ A blank ANCHOR is DROPPED, not fatal — corrected 2026-07-12, after driving it

This section used to say "**or** if any tile in `anchors` is". **That was wrong on this data and it
dead-ended the app.** It was written assuming the blank list is the **11** known blanks — every one
of which lives inside the thrown-out 26 and so can never *be* an anchor, making the branch
unreachable by construction. But the scan is only allowed to look at the **312 usable** trials (the
26 are not data and are never loaded), and over those it proposes **{34, 55, 56, 127}** — the four
near-threshold trials RECON calls *usable false positives*. The user anchors in trial order, so the
moment he anchored **34**, every subsequent `Space` and snap refused forever and the sweep died at
tile 35. Caught by driving the real sweep; it typechecked perfectly.

The rule is now:

| | |
|---|---|
| **`target` is blank** | **REFUSE.** `candidates: []`, `best: null`, `refused` populated. Unchanged — this is the real hazard: the tile under judgement would register confidently and wrongly on fixed-pattern sensor structure. |
| **an `anchor` is blank** | **DROP it from the composite** and list it in `dropped_anchors`. Not an error. |
| **every anchor is blank** | `refused: {"reason": "no_anchors"}` — there is no scene texture to match against. |

Dropping is **strictly safer** on the axis the trap cares about: a blank frame's fixed-pattern
structure now contributes **no pixels to any correlation at all**, where the old rule would have
included them the moment the refusal was bypassed. If the target's only overlap was with a dropped
anchor, `npix` falls below `exact_ncc`'s floor and the honest answer is `ncc: null` — *not
measurable* — never `0.0`.

The memo is keyed on the **effective** (post-drop) anchor set, so the A-branch prefetch remains
correct by construction.

### 7.4 ⭐ Prefetch — and the correctness trap that makes it free

Every `Space` costs **1,068 ms (GPU) / 1,562 ms (CPU)**. Fire the *next* tile's match the instant
the current one is judged, and it hides inside the 1 s fade and the user's own think-time.
Perceived latency → **~0 ms**.

**There is no prefetch endpoint.** `POST /api/match/anchor` is **memoised** on the server:

```
cache_key = sha1(canonical_json({
    "target": target,
    "anchors": [[t, round(x, 3), round(y, 3)] for t in sorted(anchors)],
    "mode": mode,
    "near": [round(nx, 3), round(ny, 3)] if mode == "local" else None,
    "radius": radius if mode == "local" else None,
    "max_candidates": max_candidates,
    "tone_independent": true
}))
```
LRU, `MATCH_CACHE_SIZE = 32`. A repeat POST with the same body returns in ~1 ms with
`"cached": true`. **The prefetch is literally the same POST, fired early.**

> 🔴 **THE TRAP. The prefetch MUST include the tile currently under judgement in `anchors`** — i.e.
> it must assume the user will press **`A`**. That branch is **exact by construction**. Prefetching
> from the composite **WITHOUT** the current tile **disagrees with the truth in 18 % of presses and
> is catastrophically wrong (up to 1,143 px) in 6 %.**
>
> **If the user presses `E` instead, the anchor set is different, so the cache key is different, so
> the memo MISSES and the server recomputes.** The trap is structurally impossible to fall into —
> *provided the front end sends the anchor set it actually means*. **Never hand-roll a client-side
> prefetch cache keyed on the trial number.** Key on nothing; just re-POST and let the server memo
> answer.

The server MUST serve match requests from a thread pool of **≥ 2** workers so a prefetch in flight
never blocks the foreground request the user is waiting on.

### 7.5 Staleness (a UI concern, stated here so both halves agree)

If an **anchored** tile's position changes after other tiles were matched against the field, those
matches were made against a field that no longer exists. The front end MUST mark every tile judged
*after* that anchor's first placement as `stale: true` in its own model and show a
"re-check N tiles" affordance. The backend does not track this — the memo key already guarantees
that any *new* request gets an honest recompute.

### 7.6 `409 busy`

While a **build** job is `running`, `POST /api/match/*` returns `409 {"error": {"code": "busy"}}`.
The build owns the GPU. The UI disables the sweep during a build.

---

## 8. Jobs — `open`, `build`, `export`

Placement runs **25 s – 10 min synchronously with no progress callback of any kind**. It MUST be off
the UI thread, and the API is therefore **start → job id → poll**.

### 8.1 `GET /api/jobs/{job_id}`
```json
{
  "job_id": "job_7f3a1c",
  "kind": "build",
  "state": "running",
  "phase": "anchors",
  "phase_index": 4,
  "n_phases": 6,
  "pct": 42.3,
  "message": "anchored 60/156 tiles",
  "started_at": "2026-07-12T14:07:02Z",
  "elapsed_s": 91.4,
  "eta_s": 118.0,
  "log_tail": [
    "[   61.2s] STEP 3 — PER-TILE ANCHORS: each pass-2 tile matched against the frozen pass-1 composite",
    "[   88.9s]     anchored 30/156 tiles (28s)"
  ],
  "result": null,
  "error": null,
  "cancellable": true
}
```
`state` ∈ `queued` | `running` | `done` | `failed` | `cancelled`.
`result` is `null` until `state == "done"`. `error` is `{"code","message","traceback"}` on `failed`.
`eta_s` may be `null`. **Poll every 500 ms.** (No websocket — it is one client on localhost and
polling is 0.6 ms.)

`GET /api/jobs` → `{"jobs": [ ...the same objects, newest first... ]}`.

### 8.2 `POST /api/jobs/{job_id}/cancel` → `202 {"job_id": "...", "state": "cancelling"}`
Idempotent. A `done` job returns `409`.

⚠️ **`t33.place` cannot be interrupted cooperatively — it has no callback and no check.** So:
**the build job MUST run in a child process** (`multiprocessing`, `spawn`), and cancel = `terminate()`.
The child re-loads the frames itself from `data_dir` (**0.12 s** for 312 with the numpy reader — do
**not** build a shared-memory apparatus for this) and streams progress back over an `mp.Queue`.
`open` and `export` jobs run on a thread (they are seconds, and they are cancellable by a flag).

### 8.3 Progress from a library that has no progress callback

`t33` narrates to **stdout** when `cfg.verbose = True`, and that is the only signal there is. The
child sets `verbose=True`, wraps `t33.place` in `contextlib.redirect_stdout` to a line sink, and maps
each line to a phase with these rules — **use exactly these**:

| line matches | phase | `phase_index` | pct within phase |
|---|---|---|---|
| `STEP 1 — PASS 1` | `pass1` | 1 | indeterminate |
| `STEP 2 — PASS 2 backbone` | `backbone` | 2 | indeterminate |
| `pass-1 composite ... px` | `composite` | 3 | 100 % |
| `STEP 3 — PER-TILE ANCHORS` | `anchors` | 4 | 0 % |
| `anchored (\d+)/(\d+) tiles` | `anchors` | 4 | `100*a/b` |
| `STEP 4 — RE-CUT` | `recut` | 5 | — |
| `STEP 5 — COMPOSITE-TO-COMPOSITE` | `runs` | 5 | — |
| `^R\d+\s` (a run's margin row) | `runs` | 5 | count rows / `n_runs` |
| `[done] placed (\d+) snapshots` | `done` | 6 | 100 % |

Overall `pct` = a fixed weighting, because the phases are wildly unequal on a **cold** cache
(measured: 230 s total, of which the anchor loop is ~150 s):
```
pass1 0.20 | backbone 0.08 | composite 0.02 | anchors 0.55 | recut 0.01 | runs 0.14
```
On a **warm** cache the whole thing is ~25 s and the first four phases are skipped — the job will
jump straight to `runs`. That is correct; do not "smooth" it.

Keep the last **200** log lines in `log_tail` (the UI shows the last ~8 in a drawer).

---

## 9. The blank scan

❌ **No slider. No auto-reject. No blur judgement. No Laplacian-variance number anywhere in the UI.**
Across all 338 snapshots and **15 focus measures**, the best global blur threshold reaches **F1 =
0.37**; variance-of-Laplacian — the textbook autofocus metric — scores **worse than chance**.
Catching all 15 of the user's blurry frames also rejects **62 good ones, best case.**
So the scan recommends **only what the code is genuinely sure of: blanks.**

### 9.1 `GET /api/scan/blank`
Computed during `session/open` (3.0 s for 342 frames, CPU, single-threaded — not a bottleneck).

```json
{
  "threshold": 60.11,
  "threshold_source": "2.0th percentile of PASS-1 texture (the known-good range)",
  "measure": "std of DoG(sigma=3, sigma=30) of the flipped frame",
  "texture": {"11": 132.4, "12": 128.9, "304": 41.83},
  "blank": [289, 300, 301, 302, 303, 304, 305, 306, 307, 308, 309],
  "n_blank": 11,
  "n_scanned": 312,
  "margin_warning": "The nearest usable trial sits 0.13 % below the threshold. This measure is reliable for BLANK and useless for BLUR — do not read anything into a near-threshold value."
}
```

- The scan runs over **`run.trials` only** — the 26 thrown-out snapshots are never loaded.
- ⚠️ On 260620d **with pass 1 in the range**, this threshold flags **15**, not 11 — it adds pass-1
  trials **34, 55, 56, 127**, all of which are usable and all correctly placed in the 100 %-solved
  pass 1. The clean "exactly 11" result only holds when the threshold is applied to pass 2.
  **Therefore: the scan REPORTS the list and the UI RECOMMENDS it; the user ticks. Nothing is
  auto-excluded.** `blank` above is what the measure says; it is a *proposal*.
- The **blank** list is what the matcher refuses (§7.3), regardless of whether the user excluded it.
- The exclusion list is **live for the whole session** — a tile can be excluded at any point, from
  any screen, and doing so **recomputes `gaps`**.

---

## 10. Build

### 10.1 `POST /api/build/start` → a job

**Request**
```json
{
  "config": null,
  "use_cache": true
}
```
`config: null` = **t33's shipped 312/312 defaults**, and that is the one-button path. The Advanced
drawer may send an override object; every key MUST be a real `t33.Config` knob (an unknown key is a
`TypeError` in t33 → return `400`):
```json
{
  "config": {
    "pass_split": 166,
    "anchor_ncc": 0.30,
    "split_px": 12.0,
    "look": 3,
    "min_side": 2,
    "t27": {"conf": 0.62, "run_conf": 0.55, "span": 340, "control": false}
  },
  "use_cache": true
}
```
⚠️ **`pass_split` defaults to the session's *detected* value, not to t33's literal `166`.**
⚠️ The Advanced drawer MUST say, in the drawer: *"These are off the validated path. The shipped
312/312 build used the defaults."*

**Response** `202 {"job_id": "job_1b04ff", "kind": "build"}`. `409 busy` if a build is already running.

**Cache.** `use_cache: true` points `t33.place(cache=...)` at
`<appdata>/Camea/cache/<dataset>/`. t33's own cache is safe — the config **hash is in the filename**
and a mismatched load is **refused, not repaired** (`t33.py:177`, `:214`). ⚠️ **Do NOT copy
`mosaic.io.load_frames`'s cache** (`io.py:23`): it validates only `shape[0] == len(trials)`, so two
*different* 312-trial selections silently share an entry. Any cache the app adds MUST use t33's
model: the key in the filename, refuse on mismatch.

### 10.2 `GET /api/build/result`
`404` before a build has completed.
```json
{
  "build_id": "260620d__t33__20260712T140702Z",
  "created": "2026-07-12T14:10:52Z",
  "positions": {"11": [0.0, 0.0], "12": [0.0, 180.0], "347": [-289.0, 1451.0]},
  "n_placed": 312,
  "unplaced": [],
  "info": { "...": "t33's info dict, made JSON-safe — see below" },
  "seconds": 229.9,
  "gpu": true,
  "per_tile": {
    "168": {"anchor_ncc": 0.815, "anchor_residual_px": 2.1, "run": "R0", "run_margin": 0.473, "pass": 2},
    "11":  {"anchor_ncc": null,  "anchor_residual_px": null, "run": null, "run_margin": null, "pass": 1}
  }
}
```

⚠️ **`info["config"]` is NOT JSON-serializable** — it holds a nested `t27.Config` object and
`json.dumps(info)` **crashes**. Serialize with `default=lambda o: vars(o)` (`build_mosaic.ipynb`'s
`jsonable()`).

**`per_tile` is a "go look here first" list, not a verdict.** What is honest:
- `anchor_ncc` — **pass 2 only**; the best signal there is (156/156 reached ≥ 0.30, median 0.815).
- `anchor_residual_px` = `|(anc[q] + M1) − pos[t]|` — **probably THE number to sort a worklist on**.
  It caught trial 311 at 2,706 px. But it has fired exactly **once**, its false-positive rate is
  unmeasured, and t33's own design treats a lone disagreeing anchor as an outlier to *discard*.
  **Present as "go look", never as a verdict.**
- **Pass-1 tiles have NO per-tile confidence.** `t27`'s `info` is aggregate-only — and the worst tile
  in the shipped build (**127, at 9.94 px**) is a **pass-1** tile. Say so in the UI. Do not let the
  absence of a warning read as a clean bill of health.
- ⛔ **Do NOT build the worklist on `quality.score_positions`.** On the *ground-truth-perfect* 312/312
  build it flags 11 tiles below 0.3 and **all 11 are false positives — precision 0/11.** It is a
  tile-pair overlap NCC, the exact aperture t33 exists to escape.
- ⛔ `quality.score_build()` and `quality.leaderboard()` are **DEAD** (`quality.py:84`, `MROOT` points
  at a deleted directory). They raise. Never call them.

The build's real job is to produce **a good starting point and the evidence for the sweep** — the
sweep re-places every tile against the anchor field anyway (§7).

---

## 11. Project file — save / load / autosave

The project file **IS a ground-truth document with extra keys** (§ `app/project_schema.json`). One
file, two uses: the app round-trips it, and `analysis/benchmark/score.py` can score it unchanged
(`load_gt` reads `doc["tiles"][k]["status"] == "anchor"` and its `x`/`y`).

### 11.1 `POST /api/project/save`
**Request** `{"path": "D:/work/260620d.camea.json", "doc": { ...the whole document... }}`
**Response** `{"path": "...", "bytes": 91204, "saved_at": "2026-07-12T15:22:04Z"}`

The backend **validates against `project_schema.json`, fills the derived fields, and stamps the
provenance** (§11.4) before writing. It writes atomically (temp file + `os.replace`).

### 11.2 `POST /api/project/load`
**Request** `{"path": "D:/work/260620d.camea.json"}` → **Response** `{"doc": {...}, "warnings": []}`

⚠️ **Guard the range, as the bench does** (`template.html:2012`): if the document's
`run.lo/hi/dataset` differ from the open session's, **refuse** and return
`409 {"error": {"code": "bad_request", "message": "this project is for trials 167-348 of 260620d; the open session is 11-348"}}`. Pass 2's autosave once silently overwrote pass 1's GT records. Do not
re-open that hole.

### 11.3 `POST /api/project/autosave`
**Request** `{"doc": {...}}` → **Response** `{"path": "...", "saved_at": "..."}`
Writes to `session.autosave_path`. The front end calls this **debounced at 2 s** after any document
change, and unconditionally on `A` / `E`. Never blocks the UI. `data/` is **never** written to.

### 11.4 ⚠️ Provenance — mandatory, and not decoration

Pass 1's ground truth got tiles **128/129/130/148 wrong** *precisely because* it was seeded from a
build and the human deferred to it. It was caught only because pass 2 was later authored blind. The
user has chosen the fast path — show the machine's answer and confirm it — which is **the right call
for a mosaic-building tool**. But it means the output is **"a build a human signed off on", not an
independent ground truth**, and it **must never be used to score the solver that produced it.**

So `project.py` **MUST** stamp, on every save and every GT export:

```json
"provenance": {
  "authored_by": "Camea Mosaic Builder",
  "app_version": "1.0.0",
  "workflow": "machine-seeded verification sweep",
  "seeded_from": {"method": "t33", "build_id": "260620d__t33__20260712T140702Z", "config": {}},
  "independent_of_method": false,
  "warning": "NOT AN INDEPENDENT GROUND TRUTH. Every position here started as t33's output and was confirmed or corrected by a human who could see it. It MUST NEVER be used to score t33 or any method derived from it — the score would be 100 % by construction. This project has already destroyed one benchmark exactly this way.",
  "human_edits": {"accepted_unchanged": 288, "moved": 19, "excluded": 3, "unverified": 2, "median_move_px": 1.4, "max_move_px": 41.2}
}
```

If `seeded_from` is `null` (the user placed from scratch — no build ever ran), set
`"independent_of_method": true` and **omit** `warning`. That document *is* an honest truth.

---

## 12. Exports

### 12.1 `POST /api/export` → a job
**Request**
```json
{
  "dir": "D:/work/out",
  "basename": "260620d_mosaic",
  "doc": { "...": "the whole document" },
  "outputs": ["tiff", "png", "positions", "gt", "qc"],
  "render_mode": "feather",
  "include_unverified": true,
  "um_per_px": null
}
```
**Response** `202 {"job_id": "job_c31a70", "kind": "export"}`. Job result:
```json
{"files": [
  {"kind": "tiff",      "path": "D:/work/out/260620d_mosaic.tif",           "bytes": 17293312},
  {"kind": "coverage",  "path": "D:/work/out/260620d_mosaic_coverage.png",  "bytes": 62114},
  {"kind": "png",       "path": "D:/work/out/260620d_mosaic.png",           "bytes": 3712204},
  {"kind": "positions", "path": "D:/work/out/260620d_mosaic_positions.csv", "bytes": 8940},
  {"kind": "gt",        "path": "D:/work/out/260620d_mosaic_gt.json",       "bytes": 84112},
  {"kind": "qc",        "path": "D:/work/out/260620d_mosaic_qc.json",       "bytes": 12043},
  {"kind": "qc",        "path": "D:/work/out/260620d_mosaic_qc.md",         "bytes": 4310}
]}
```

**What is rendered:** tiles with state `anchored`, plus `unverified` **iff** `include_unverified`.
`excluded` and `unplaced` are never rendered. `render_mode` default `feather` — **the only
interactive mode** (measured: feather **1.11 s**, median 41.7 s, alpha 74.0 s).
⚠️ `mode="alpha"` silently returns **float64 on a canvas 1 px larger in each dimension**; it needs
spectralign. `median` emits a cosmetic `All-NaN slice` warning — suppress it.

| kind | notes |
|---|---|
| **tiff** | **16-bit** (uint16), full resolution (~2251×3841 on this data = 8.7 Mpx, ~16.5 MiB). Raw camera counts from `render.render(...)`, clipped to `[0, 65535]`. `tifffile.imwrite(path, img.astype(np.uint16))`. **BigTIFF is irrelevant** at this size. |
| **coverage** | ⚠️ **MANDATORY companion to the TIFF.** **13.1 % of the canvas is background encoded as exactly `0.0`**, indistinguishable from a legitimately black pixel, and there is **no alpha channel**. Write the mask as a sidecar 8-bit PNG (0 = no data, 255 = covered). It is free — `wsum > 0` in the feather path. Without it, "empty" and "black" merge forever. |
| **png** | 8-bit display, **the GLOBAL tone window** (§6) — never a per-tile stretch. |
| **positions** | `positions.csv`, header exactly `trial,x,y,state` — the first three column names are what `benchmark/score.py :: load_positions` reads. Positions are normalised so `origin_trial` is at `(0,0)`. |
| **gt** | The ground-truth JSON (§11, `project_schema.json`). Scoreable by `benchmark/score.py` unchanged. **Do NOT reimplement `score.robust_align`** — a reimplementation with a different tie-break scored the same positions 152/156 where the canonical one gives **155/156**. Import it. |
| **qc** | What the human did vs what the machine said: accepted-unchanged, moved (and by how far, per tile), excluded, still-unverified, plus the provenance of §11.4. Both `.json` and a human-readable `.md`. |

### 12.2 📏 Physical scale — **PIXELS ONLY. This is not negotiable yet.**

`um_per_px` is `null` by default and the exporter writes **pixels only**: no scale bar, no OME-TIFF
`PhysicalSizeX/Y`. The grid pitch measures **13.805 px in pass 2 but 14.15 px in pass 1** — a **2.5 %
magnification difference between the passes** that is **not yet resolved** (see `SCALE.md`).

> **Never put a single scale bar on a figure spanning both passes.** At best it is right for one pass
> and 2.5 % wrong for the other.

If the user fills in `um_per_px`, write physical units **and** a note recording that the value was
supplied by hand, not measured.

---

## 13. Native dialogs (pywebview)

The WebView cannot open a Windows file dialog. The backend proxies pywebview's.

- `POST /api/dialog/open-directory` `{"title": "Pick an acquisition directory"}`
  → `{"path": "D:/..."}` or `{"path": null}` if cancelled.
- `POST /api/dialog/save-file` `{"title": "...", "default_name": "260620d.camea.json", "filters": ["Camea project (*.camea.json)"]}`
  → `{"path": "..."}` or `{"path": null}`.
- `POST /api/dialog/open-file` `{"title": "...", "filters": ["Camea project (*.camea.json)"]}`
  → `{"path": "..."}` or `{"path": null}`.

`main.py` sets a module-level reference to the pywebview `Window` that `server.py` calls into. When
the app runs **headless** (pytest, or `--no-window`), these return `501 {"error": {"code":
"bad_request", "message": "no window"}}` — the tests pass paths directly.

---

## 14. Health / GPU

- `GET /api/health` → `{"ok": true, "version": "1.0.0", "python": "3.12.13", "uptime_s": 41.2}`
- `GET /api/gpu` →
```json
{"available": true, "backend": "cupy", "name": "NVIDIA GeForce RTX 4070",
 "cupy": "13.6.0", "cuda_runtime": 12090,
 "note": "GPU: a 312-tile build takes ~3 min. Without it, ~8-10 min — and the interactive sweep is only 1.46x slower (1,068 vs 1,562 ms per Space), because exact_ncc runs on the CPU either way."}
```

🔴 **CUDA detection MUST EXECUTE A REAL OP.** `import cupy` **succeeds** on a broken CUDA install
(only a UserWarning); it is `cupy.zeros(1) + 1` that raises. **A `try: import cupy / except
ImportError` guard DOES NOT WORK.** **Reuse `t27.xp()` verbatim** (`t27.py:135`) — it already does
exactly this and falls back to numpy on any exception. Call it **once, at startup, on a worker
thread** (it also warms the GPU: −497 ms off the first match).

⚠️ `t27._cuda_dll_dance()` (`t27.py:120`) is a **process-global side-effect** (`os.add_dll_directory`
+ a `PATH` prepend) that the GUI process must tolerate. It **breaks under PyInstaller**
(`sys._MEIPASS` ≠ `sysconfig.get_paths()["purelib"]`) — packaging (agent 8) must rewrite it for the
frozen layout.

---

## 15. Front-end obligations that the backend cannot enforce

These are part of the contract because breaking them breaks the product.

1. 🔴 **LAYERED CANVAS IS MANDATORY.** The bench's immediate-mode renderer is **10 fps at 1:1 zoom**
   (89.5 ms/frame — it redraws all 312 tiles every frame). **The 1-second fade would be a
   slideshow.** Bake the **anchored** tiles into ONE offscreen background canvas; per frame draw
   *one* `drawImage` + the fading tile. Measured: **89.5 ms → 6.1 ms/frame, locked 60 fps.** ~40
   lines. Appending a tile on `A` costs 0.1 ms. Difference mode comes free via
   `globalCompositeOperation = 'difference'` (verified pixel-exact, +0.6 ms).
2. **Do not ship the browser-side JS NCC as the authority.** It is alias-safe only within ~±48 px —
   the electrode grid repeats every **256 px** — and past that it locks onto a confident, wrong
   alias. The snap is `POST /api/match/anchor` with `mode: "local"`: **real spectralign-grade SWIM,
   16-bit pixels, on the GPU.** ~1 s per click is **accepted** — *correct beats fast* (his ruling).
   A JS pre-snap for instant feedback is fine **as a preview**, but the committed number is the
   server's.
3. **Never show a variance-of-Laplacian number, a blur score, or a "sharpness" slider.** §9.
4. **The tone window is global.** Never stretch a tile individually, not even for a thumbnail.
5. **Positions are top-left corners.** Add +256 to draw a centre, a marker or a label. Off-by-256 is
   the classic bug here.
6. The keyboard map (ported from the bench, `utils/artifact/template.html`):
   `A` anchor · `E` exclude · `Space` next · `R` replay the fade · `D` Difference ·
   `V` show alternatives · `S` snap · arrows nudge 1 px (Shift = 10) · `F` fit · `0` 1:1 ·
   `Ctrl+Z`/`Ctrl+Y` undo/redo (100-deep, tagged folding, a drag pushes once on first pointermove) ·
   `Esc` deselect.
