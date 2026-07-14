# Camea Mosaic Builder — app plan

> **Spec complete, 2026-07-12.** Fleshed out interactively with the user. A later Claude session
> builds the app from this file + **[RECON.md](RECON.md)** (exact signatures, measured numbers, traps).
> **Everything for this app lives in `app/`.**
>
> **Read [RECON.md](RECON.md) before writing a line of code.** It has the API surface, the arithmetic,
> and ~20 traps that will otherwise bite you (the 180° flip, the +256 top-left/centre bug, the unsafe
> `io.load_frames` cache, the silent CUDA-detection failure, the dead `quality.score_build`).

---

## What it is

A Windows desktop app that takes a directory of microscope snapshots and walks a user through
building a **human-verified** mosaic:

1. **Load** — point at a vscope acquisition directory; the app finds the mosaic run and loads it.
2. **Screen** — a scan recommends only the snapshots it is *genuinely sure* are unusable.
3. **Build** — one button. The solver places every tile and produces the evidence for step 4.
4. **Verify** — ⭐ *the heart of the app.* A fast keyboard sweep: the user confirms, corrects, or
   excludes each tile in acquisition order, building an anchor field as they go.
5. **Export** — TIFF, PNG, positions, and a QC report of what the human changed.

**Design north star (his words): fast, agile, good UX.** But when they conflict: **correct beats
fast** — his explicit ruling on the snap.

---

## Settled decisions

| Question | Decision |
|---|---|
| **Audience** | Lab-mates. Ships as a **Windows installer** — no Python, no conda on the target machine. |
| **Where it runs** | On the **same machine** as the data. Remote SSH is not a consideration; a native window is fine. |
| **Input** | A **vscope acquisition directory** (trial subdirs of headerless raw `.dat` + `log.txt`). |
| **Geometry** | **Serpentine only.** The app is a tool for *this kind of run*. t33's 312/312 leans entirely on the serpentine prior; do not chase arbitrary scan patterns. |
| **Engine** | **Python.** t33 is numpy/scipy/CuPy over spectralign. Not rewritten in C#/C++ — that discards the only validated placement we have. |
| **Shell** | **Python backend + HTML/JS front-end in a native window** (pywebview → WebView2, preinstalled on Win 11). No browser chrome, no visible port, one runtime. Reuses ~2,100 lines of debugged bench interaction code (render loop, 100-deep undo/redo, session serializer, Difference mode, keyboard map) that Qt would force a rewrite of. |
| **Packaging** | **PyInstaller + Inno Setup.** ⚠️ PyInstaller **breaks `t27._cuda_dll_dance()`** (`sys._MEIPASS` ≠ `sysconfig purelib`) — it must be rewritten for the frozen layout. See RECON.md. |
| **Installer** | **Lean, CPU-only by default (~2 GB).** The 707 MB CUDA payload is an **optional GPU add-on** offered when the app detects an NVIDIA card. |
| **No-GPU machines** | **Run anyway, warn honestly.** State the real cost up front: **~8–10 min** for 312 tiles on CPU vs **~3 min** on GPU. Progress + cancel. Never silently degrade the result. |
| **License** | **Keep spectralign (GPL-3.0). This is an open-source tool.** No need to reimplement `Placement.rigid`. |
| **vscope** | **Dropped.** Only 2 call sites (`io.py:28`, `match.py:153`), both just reading pixels; a proven vscope-free reader exists (`texture/make_texture.py:37`). Removing it deletes cairo + salpa + ppersist + physfit from the installer. ⚠️ vscope reads with *native* byte order; the explicit `"<u2"` path is strictly safer. |
| **Build controls** | **One button.** t33's shipped 312/312 config is the default and stays that way. A collapsed **Advanced** drawer holds the knobs, warning they are off the validated path. |
| **Project state** | **One project file, user chooses where.** Autosaves during the sweep. `data/` is **never** written to. |
| **Exports** | **All four:** 16-bit TIFF, display PNG, positions + GT JSON, and a QC report. |

⚠️ **Do not fork the engine into `app/`.** The app *calls* `analysis/mosaic/` (vendored into the
installer at build time). Two copies of t33 = a silent regression waiting to happen. The
**`analysis/tests/test_mosaic_312.py`** regression guard (~180 s cold, asserts 312/312) must still
pass after any change the app forces on t27/t33.

---

## Step 1 — Load

**Parse `log.txt`.** It is fully machine-readable and answers more than expected (measured on 260620d,
2026-07-12):

```
06/20/26 15:46:58 New experiment: 260620d
         15:47:05 Settings loaded: 250712-mosaic
         15:47:05 Trial 001: Snapshot
         ...
         16:02:44 Trial 011: Snapshot
```

- Only two trial types appear: **`Snapshot`** and **`E'phys. + VSD`**.
- 260620d has **342 Snapshot trials in exactly 3 contiguous blocks**: `(1)`, `(5–7)`, `(11–348)`.
- ⭐ **Rule for the mosaic run: the longest contiguous block of `Snapshot` trials.** That yields
  **11–348 (338 trials)** — exactly right, nothing hard-coded. (338 − 26 excluded = **312**.)
- ⭐ **The pass boundary is measurable from the timestamps.** Median snapshot-to-snapshot gap is
  **2 s**; **166 → 167 is 20 s** — the stage driving back to the origin to start pass 2. So t33's
  `pass_split` can be **measured, not hard-coded**.
  - ⚠️ **Gotcha:** `11 → 12` is *also* 20 s (settling right after `Settings loaded`). **Ignore the
    first step of the block.** The next-largest interior gaps are only 8 s, so the signal is clean —
    but this is validated on **n = 1 dataset**. Always show the detected split and let the user
    override it.

**Then:** show a **contact sheet** of everything loaded. Show the detected run and split; let the
user adjust before proceeding.

**Frame format** (RECON.md has the verification): headerless little-endian **uint16, 512×512**,
exactly 524,288 bytes. ⚠️ **The 180° flip is load-bearing** — XML `ax=-1, ay=-1` means the display
frame is the raw array rotated 180°. Every existing position, every SWIM dx/dy, and all three ground
truths live in the **flipped** frame. Get it wrong and the app is 180° out from every prior result —
*and it will look plausible.*

**Cost:** 312 frames = **312 MiB** float32; **~0.12 s** to load with the numpy reader. Budget **~1 GB**
host RAM peak (band-pass and flat-field each allocate a full second copy).

---

## Step 2 — Screen

❌ **No slider. No threshold. No auto-reject.**

**Why — this is quantified, not a hunch.** Across all 338 snapshots and **15 focus measures**, the
best global threshold reaches **F1 = 0.37**. Catching all 15 of the user's blurry frames also rejects
**62 good ones, best case**; sorted worst-first by the best-behaved measure, those 15 land at ranks
**8…140** — a threshold that catches them all throws away **41 % of the data**. **Variance-of-Laplacian
— the textbook autofocus metric — scores *worse than chance*** (it is dominated by sensor noise, which
is identical in sharp and blurry frames). **It must never appear in the UI.**

So the scan **recommends only what the code is genuinely sure of**:

- ✅ **Blanks** — band-passed (DoG σ3/30) std of the flipped frame, threshold ≈ **60.1** (the 2nd
  percentile of pass-1 texture). This measure *works*. `texture/make_texture.py:47`; **3.0 s for all
  342 frames**, CPU, no GPU needed.
- ❌ **Blur is not judged.** The user meets every tile again in step 4 and excludes it there with `E`.

**The exclusion list is live for the whole session** — a tile can be excluded at any point.

⚠️ **Blank frames must be REFUSED by the matcher, not merely scored.** Two blank frames **136 trials
apart** correlate **+0.43 at zero shift** (honest noise floor: 0.115) because what they share is
fixed-pattern *sensor* structure, which does not move with the stage. **They register confidently and
wrongly.** The bench already refuses them (`template.html:1536`). Keep that.

---

## Step 3 — Build

**One button.** `t33.place(trials, frames, cfg, cache) -> (pos, info)`.

- ⚠️ **Positions are TOP-LEFT corners, not centres.** Everything that plots them adds +256. Off-by-256
  is the classic bug here.
- ⚠️ **No progress callback exists anywhere.** t33's only signal is a `print` behind `cfg.verbose`.
  Placement runs **25 s – 10 min synchronously** and **must** be off the UI thread. Either capture
  stdout on a worker thread or add a real callback.
- ⚠️ **`info["config"]` is not JSON-serializable** (nested `t27.Config`). `json.dumps` crashes. Use
  `build_mosaic.ipynb`'s `jsonable()`.
- ⚠️ **CUDA detection must EXECUTE A REAL OP.** `import cupy` *succeeds* on a broken CUDA install; it
  is `cupy.zeros(1)+1` that raises. A naive `try: import cupy` guard **does not work**. **Reuse
  `t27.xp()` verbatim** (`t27.py:135`).
- ⚠️ **Excluding tiles opens gaps** in acquisition order (283→297, 298→311 on this data), where the
  serpentine one-step prior does **not** hold. Any exclusion toggle **must recompute `gaps()`** or it
  silently poisons the solve.

The build's real job is to produce **a good starting point and the evidence for step 4** — because
step 4 re-places every tile against the anchor field anyway.

---

## ⭐ Step 4 — The verification sweep (the heart of the app)

A fast, keyboard-driven, one-tile-at-a-time pass through the snapshots in acquisition order, where
the human confirms or fixes what the solver did.

### The loop
1. The user **picks the first snapshot** they want. It lands on a **blank canvas** and defines the
   origin. They press `A`.
2. For the tile currently under judgement:
   - **`A` — anchor it.** *Accept as ground truth.* It joins the anchored background everything after
     it is judged against.
   - **`E` — exclude it.** Dropped. (Too blurry, blank, whatever the user's eye says.)
   - **`Space` — advance** to the next consecutive snapshot, **skipping any already excluded**.
3. `Space` places the next snapshot and **fades it in over a full 1 second — transparent → opaque.**
   ⭐ *This fade is the whole point:* watching the tile materialise on top of the anchored background
   is how the user sees whether it lines up.
4. Repeat. `A` / `E` / `Space` — **a very quick verification rhythm.**

### Tile states
| State | Meaning | Drawn as |
|---|---|---|
| **anchored** | user pressed `A` — ground truth, part of the reference field | solid, full opacity, bottom layer |
| **unverified** | user pressed `Space` without deciding | dimmer / dashed outline. **Does not** join the anchor field. Counter shows how many are outstanding. |
| **excluded** | user pressed `E` | not drawn, not matched, not exported |

Deferring a hard tile must never stall the sweep.

### When the solver got a tile wrong
5. **Drag and drop** it roughly onto the correct area of the anchored background.
6. Press the **snap** button → it becomes **sub-pixel-perfect** against the anchored background.

### Interrogation keys on the current tile
- **Replay the 1 s fade** — you will want this constantly.
- **`D` — Difference mode.** `|tile − background|` in the overlap; misalignment shows as bright
  doubling. This is the check he relied on in the bench.
- **Show the alternatives** — the solver's runner-up candidate positions ("did you mean here
  instead?").
- *(No manual opacity scrub — he didn't want one.)*

### ⭐⭐ The core primitive: match against the ANCHOR COMPOSITE

His instruction for an unplaced tile — *"run the solver on it again using the newly placed anchors"* —
is the same mechanism that won 312/312, and it collapses **four** features into one call:

| Feature | Call |
|---|---|
| **Place the next tile** (on `Space`) | whole-plane match against the anchor composite; the batch solve is the fallback / cross-check |
| **Snap** (after a drag) | local refine against the anchor composite, near the drop point |
| **Show alternatives** | the *ranked* peak list the same whole-plane match already returns |
| **Solver couldn't place this tile** | the same whole-plane match; take the top candidate, badge it |

**Why this is the right primitive, not just a convenient one — aperture is everything.** Measured on
this data: of 719 genuinely-overlapping **tile-pairs**, the exact NCC argmax is **>20 px wrong for 38
of them (5 %), at scores up to 0.760.** Canonical case: 222 vs 250 — the **0.760 winner is 757 px
wrong**, and the truth is the *runner-up* at 0.677. The **same tile matched against the pass-1
composite** scores 0.654 vs 0.416 next-best and lands **1.7 px** from the human. A big trusted
reference field does not lie the way a 0.5 Mpx tile-pair does. **The anchor composite the user is
building is exactly such a field — and it is human-certified, which is better than anything the batch
solve has.**

**Decision (his): re-place each tile against the anchors as you reach it.** The sweep gets *more
accurate as it goes*. Cost ~1 s per `Space`; accepted.

⚠️ **But the aperture is small at the start.** With one anchor down, "match against the anchor
composite" *is* a tile-pair — the weak case above. What saves the opening is that **consecutive**
snapshots overlap ~78 %, and consecutive whole-frame matches are the alias-robust ones (the bench's
"kind 0" links). So the opening is fine — but **surface the evidence**: show the anchor-composite
area, the NCC, and the best-vs-second **margin** on every placement, so the user can watch the
evidence strengthen rather than take it on faith. Flag loudly when the margin is thin (the shipped
build's worst run margin is **0.081**, against ~0.47 typical).

### The primitives all exist and are validated
- `t33.composite()` (`t33.py:274`) — rebuild a reference field from a set of placed tiles.
- `t33.match()` (`t33.py:436`) — **public**, returns the **ranked** list of distinct peaks
  `[(ncc, dx, dy, npix)]`, best first. `place()` computes this and throws all but the winner away.
- `t33.exact_ncc()` (`t33.py:400`) — score an arbitrary human-dragged offset. *"You dropped it here;
  here's what the pixels say."*

### The snap engine
**Correct beats fast (his ruling).** → **real spectralign SWIM on 16-bit pixels, on GPU**, against the
anchor composite. ~1 s per click is accepted. **Do not** ship the browser-side JS NCC as the
authority — it is alias-safe only within ~±48 px (the electrode grid repeats every **256 px**) and can
lock onto a confident, wrong grid alias.

### ⚠️ The anchoring hazard — say it out loud in the export
Pass 1's ground truth got tiles **128/129/130/148 wrong** *precisely because* it was seeded from a
build and the human deferred to it. It was caught only because pass 2 was later authored blind. The
user has chosen the fast path — show the machine's answer and confirm it — which is **the right call
for a mosaic-building tool**. But it means the output is **"a build a human signed off on", not an
independent ground truth**, and it **must never be used to score the solver that produced it.**
This project has already destroyed one benchmark exactly this way (`analysis/archive/.../ground_truth/260620d.json`
is T27's own output). **Stamp the provenance into the exported JSON.**

---

## Step 5 — Export

All four, as separate files:

| Output | Notes |
|---|---|
| **16-bit TIFF** of the full mosaic | The real deliverable — opens in Fiji/ImageJ at full depth. **Nothing in the repo writes one today.** ⚠️ **13.1 % of the canvas is background encoded as exactly `0.0`**, indistinguishable from a legitimately black pixel, and there is **no alpha channel**. Carry a **coverage mask** (free: `wsum > 0` in the feather path) or it merges. |
| **Display PNG**, 8-bit | For figures/slides. ⚠️ **Tone-map GLOBALLY** — one 0.5/99.6-percentile window across all frames after flat-fielding. A **per-tile** stretch over-brightens near-empty frames and makes overlapping tiles disagree in tone, **which destroys the Difference-mode check.** |
| **positions.csv + GT JSON** | Every tile's final position and status (anchored / unverified / excluded). Write in the **existing GT schema** (`analysis/ground_truth/`) so it is interoperable and scoreable by `benchmark/score.py`. ⚠️ **Do not reimplement `score.robust_align`** — a reimplementation with a different tie-break scored the same positions 152/156 where the canonical one gives 155/156. **Import it.** |
| **QC report** | What the human did vs what the machine said: tiles accepted unchanged, tiles moved (and by how far), tiles excluded, tiles still unverified. This is also the honest provenance record for the hazard above. |

Rendering: `render.render(pos, frame_of, tilesize, blend, mode)` (`render.py:61`) returns raw camera
counts. `feather` and `median` are pure numpy; `alpha` needs spectralign **and silently returns
float64 on a canvas 1 px larger in each dimension** — a mode switch invalidates cached viewport
geometry. `median` emits a cosmetic `All-NaN slice` warning. Mosaic is **8.7 Mpx** — one texture, no
pyramid needed.

---

## ⚡ Performance — measured, not assumed

**Full audit: [SPEED.md](SPEED.md)** (4 measurement agents, 2026-07-12). The headline:

### The stack is right, and the language is not the bottleneck anywhere
Of a **229.9 s** cold 312-tile build: **compiled CPU numpy/scipy ~63–68 %**, **GPU cuFFT/CuPy ~31–35 %**,
and the **CPython interpreter 2.4 s = 1.0 %**. A perfect C++/C#/Rust rewrite of the orchestration
recovers **2–4 s out of 230** — and discards the only method that scores 312/312. **Python stays.**

⚠️ **The "it's all FFTs, which are already C" story is FALSE.** cuFFT is only **8.4 %** of the build.
The real hog is **`t33.exact_ncc`: 62,946 calls, 106.4 s, 46 % of the build** — pure CPU numpy, GPU
idle, building five full-size temporaries per call and running **6.7× off the memory-bandwidth limit**.

Per **Space press**: match = **1,068 ms GPU / 1,562 ms CPU**. The Python↔JS round-trip is **0.63 ms —
0.06 % of the click.** The total "language tax" on a keystroke is **under 1 ms out of ~1,300.**

### 🔴 The one thing that was actually broken
**The bench's renderer is 10 fps at 1:1 zoom** (89.5 ms/frame — it redraws all 312 tiles every frame).
**The 1-second fade would have been a slideshow.** This is a code-structure bug, not a language bug:

> **Layered canvas is MANDATORY, not an optimisation.** Bake anchored tiles into one offscreen
> background canvas; per frame draw *one* `drawImage` + the fading tile. Measured: **89.5 ms → 6.1 ms
> per frame; 10 fps → locked 60 fps.** ~40 lines. Appending a tile on `A` costs 0.1 ms. Difference
> mode comes free via `globalCompositeOperation = 'difference'` (verified pixel-exact, +0.6 ms).
> *(Measured with GPU compositing **disabled** — i.e. a worst case. Layered holds 60 fps even there.)*

WebGL/WebGPU would take 1.4 ms → 0.1 ms: **zero perceived gain** (you cannot draw faster than the
monitor refreshes) for a second renderer to maintain. **Not doing it.**

### ⭐ Prefetch — how the sweep feels instant without being less correct
Today every `Space` = a dead keyboard for **1.3–1.9 s**. Fire the match for tile **N+1** the instant
tile N is judged, on a worker; it hides inside the 1 s fade *and* the user's own think-time.
**Perceived latency → ~0 ms**, with the slow-but-correct GPU snap fully intact.

> 🔴 **CORRECTNESS TRAP — prefetch the `A`-branch.** The prefetch must use the composite
> **INCLUDING the tile currently under judgement** (i.e. assume the user will press `A`) — that is
> exact by construction. Prefetching from the composite **without** it **disagrees with the truth in
> 18 % of presses, and is catastrophically wrong (up to 1,143 px) in 6 %.** If the user presses `E`
> instead, **throw the prefetch away and recompute.** This is a correctness requirement, not a
> performance choice.

### The rest of the wins (ranked, with the risk stated)
| # | Change | Win | Risk |
|---|---|---|---|
| 1 | **Prefetch the next tile's match** (A-branch only) | 1,300 ms → **~0 ms perceived** | none, *if* the A-branch rule is obeyed |
| 2 | **Layered canvas** | 89.5 → **6.1 ms/frame** (10 → 60 fps) | none. **Mandatory** |
| 3 | **Incremental anchor composite** (keep running arrays, don't rebuild) | 268 → **108 ms** at 156 anchors | none — **bit-identical** output |
| 4 | **Memoise the pooled reference + its FFTs** in the build's anchor loop (the same array is re-pooled and re-transformed 156× identically) | **−25 s off a 230 s build (11 %)** | none — **bit-identical** |
| 5 | **GPU warm-up on a worker at app load** | −497 ms off the first match | none |
| 6 | *(optional)* **Batch `exact_ncc`'s 49 offsets onto the GPU** | 106 s → ~5 s — **halves the build** | ⚠️ **the one risky item.** Changes float reduction order (not FFT sizes). t33's failure mode is a *silent* lock onto the wrong peak. **Gate it on `analysis/tests/test_mosaic_312.py`; if the guard wobbles at all, REVERT.** 312/312 is worth more than 100 seconds. |

⚠️ **Do not touch `_smooth()` or any FFT size.** Every change above keeps the FFT grid at exactly
**2160×1350** as shipped. Changing an FFT size changes the numbers, for a speedup you do not need.

⚠️ **Keep OpenCV, despite it being 111 MB / 45 % of the installer.** The obvious swap to scipy shifts
the blank-detection metric by **0.32 %** against a threshold whose nearest margin is **0.13 %** — **it
can flip a blank classification.** An 85 MB saving is not worth a wrong answer.

### This changes how good the CPU-only install is
**The GPU buys 8× on the one-button build but only 1.46× on the interactive sweep** (1,068 vs
1,562 ms), because `exact_ncc` runs on the CPU either way. **The part the user spends an hour in is
only 1.5× slower with no GPU at all.** The lean CPU-only default is a much better product than it
looked.

### Why not a native shell
C#/WPF or C++/Qt paints a window in ~50–150 ms vs pywebview's ~500–900 ms. That **~550 ms is real.**
But it is paid **once**, and it is invisible: in *every* option the engine stays Python, and
numpy+scipy+spectralign+CuPy take a measured **1,502 ms to import** before the app can touch a frame.
A native shell also forces the engine into a *separate process* — two startups plus an IPC handshake.
Time-to-first-useful-action is **~1.5–2 s in all six options**. Against an hour in the sweep, 550 ms of
launch is **0.15 %**. (pywebview is also the *smallest*: **248 MB** installer vs Electron's ~400 MB.)

---

## Build order (suggested)

1. **Loader + log.txt parser + contact sheet.** Verify the 180° flip against a known frame *first* —
   everything downstream is wrong if this is wrong.
2. **The verification sweep, against the batch positions from `build_mosaic.ipynb`.** This is the
   whole app; build it before the wrapper around it. Prove the `A`/`E`/`Space` rhythm and the fade
   feel right on real tiles.
3. **The anchor-composite primitive** (`composite` / `match` / `exact_ncc` over HTTP) — snap,
   alternatives, re-place.
4. **The blank scan**, the build button, progress + cancel, the project file.
5. **Exports.**
6. **Packaging** — leave it last; it's the part that bites (`_cuda_dll_dance` under PyInstaller,
   SmartScreen on an unsigned EXE).

## 📏 Physical scale (µm/px) — **RESOLVED. Export pixels only; one scale, never two.**

Full ruling: **[SCALE.md](SCALE.md)**. Short version:

A calibration measured the MEA electrode-grid pitch at **14.15 px in pass 1 vs 13.805 px in pass 2** and
inferred a **2.5 % magnification difference** between the passes. **That inference was WRONG.** The grid
pitch tracks **FOCUS**, not stage magnification.

**The killer evidence — the pass-boundary dwell.** Trials 166–170 sit on the **same field**
(tissue NCC 1.000 / 0.999 / 0.998 / 0.996 / 0.984, translation < 1 px — a stationary stage). Across those
five frames the grid pitch swings **14.22 → 14.31 → 14.20 → 13.93 → 13.84** while the fitted **tissue
scale stays flat at 1.0010 ± 0.0001**. A pitch that moves 3.5 % on a stationary stage over unchanged
tissue is not magnification. (⭐ The user's own remark — *"the focus of the lens can change from snapshot
to snapshot"* — is what pointed here. **The unlogged 20 s pause at 166→167 was a refocus.**)

- ✅ **No magnification difference.** Cross-pass tissue scale = **1.0000 ± 0.0002** (three independent
  machineries), > 80 σ from 1.025. Every estimator's **positive control DID recover an injected 1.025** —
  they are not blind to a stretch; it simply isn't there.
- ✅ **T33's 312/312 is honest**, confirmed with the canonical scorer: **312/312, median 1.82 px, max
  9.94 px.** No radial fan (the correlation has the *wrong sign* for a scale error). Inject a real
  s = 1.025 and it collapses to **176/312 = 56.4 %** — **the largest scale error a 10 px bar can hide is
  ~0.5 %.** The 9.9 px worst tile is the already-documented `known_local_disagreement` at pass-1 tiles
  126–130, not a scale artefact.
- ✅ **`analysis/ground_truth/` is SOUND. Do not rebuild it. Do not add a scale term.** The translation
  tie `pass1 = pass2 + (−133.5, −205.1)` at scale 1.000 is right to ~0.02 %.

### What the app writes
> **Leave the TIFF resolution tags UNSET.** Provide an **optional µm/px field**, blank by default.
> **If a value is given, use ONE value for both passes** — a two-scale figure would be *actively wrong*.
> A single scale bar spanning both passes **is safe**.
>
> ❌ **1.237 µm/px (pass 1) is WRONG — never use it.** It came from the broken inference.
> ⚠️ **1.268 µm/px (pass 2) is *probably* right** (that grid is in focus, 78× SNR, position-independent)
> — but it rests on the *same* inference we just proved can be corrupted by focus. **Provisional, ±3 %.**

**The clean fix, when someone wants it:** calibrate µm/px from the **stage** (commanded µm per trial vs
measured pixel displacement), not from the electrode grid. Same stage in both passes, no focus
dependence, no periodic-object optics. Neither this nor the open question of *why* the pitch tracks focus
blocks the app, the mosaic, or T33.
