# Camea Mosaic Builder

A Windows desktop app for turning a directory of microscope snapshots into a **human-verified**
mosaic. It places every tile automatically, then walks you through confirming, correcting or
excluding each one in a fast keyboard sweep.

The point is the sweep. Everything else is scaffolding around it.

---

## What it does

Six steps, in order. A step unlocks when the one before it is done.

1. **Load** — point it at a vscope acquisition directory. (Or **Load a project…** to resume an
   earlier session — see *The project file* below.)
2. **Range** — the numbers, then one question: which trials are the mosaic? It parses `log.txt`,
   proposes the run (the longest contiguous block of `Snapshot` trials) and detects the pass
   boundary from the inter-trial timestamps. Both are proposals you can override.
3. **Screen** — which frames do you want thrown out? A scan *recommends* only the frames it is
   genuinely sure are unusable (blanks). Every box starts unticked. **It never auto-rejects
   anything.**
4. **Place** — one button. The solver places every tile.
5. **Sweep** ⭐ — the heart of it. One tile at a time, in acquisition order:
   - **`A`** anchor it (accept as ground truth — it joins the reference field)
   - **`E`** exclude it
   - **`Space`** advance to the next
   Each tile **fades in over a full second** on top of the field you have already certified.
   Watching it materialise is how you see whether it lines up.
6. **Mosaic** — build the outputs: 16-bit TIFF (+ coverage mask), display PNG, `positions.csv`,
   ground-truth JSON, and a QC report of what you changed.

Each tile is re-placed against **the anchors you have actually certified**, not against its
neighbours — so the sweep gets *more* accurate as it goes.

**Save… is in the top bar, on every screen** (`Ctrl+S`). An hour into a sweep is exactly when you
want it.

## Three design rules that are not negotiable

**The app knows nothing about your data, and the project file is its entire memory.** It ships with
no exclusion list, no per-dataset special cases, no "have I seen this directory before". The only
things that ever exclude a frame are *you*, in this session, or a project file you loaded. There is
no toggle for this. It matters because the exclusions *are* the research: an app that arrives already
knowing which of your frames are bad has short-circuited the one question it exists to help you
answer.

**Blur is never auto-rejected.** Across 15 focus measures the best global threshold reaches
F1 = 0.37, and variance-of-Laplacian — the textbook autofocus metric — performs *worse than chance*
on this data (it is dominated by sensor noise, which is identical in sharp and blurry frames).
Catching every blurry frame by threshold also throws away ~40% of the good ones. So the scan
recommends blanks only, and blur is your call, in the sweep, with `E`.

**When the matcher is not confident, it defers to the solver — and never anchors anything itself.**
Early in a sweep the anchor field is tiny, and a match against it can be confidently, spectacularly
wrong. Measured over three replayed 311-tile sweeps against a hand-authored ground truth:

| | tiles within 10 px of truth |
|---|---|
| deferring to the solver when evidence is thin | **310 / 311** |
| always trusting the matcher | **162 / 311** |

One bad early anchor poisons every tile judged against it. Nothing is ever anchored without you
pressing `A`.

## The project file

`*.camea.json` — one file, the whole run: the directory, the trial range, every exclusion you made,
every position, which tiles you anchored, where your cursor was, and the build it came from.

It is the app's **only** persistent memory. Save it and you can close the app mid-sweep and pick up
on the same tile later. The rolling autosave is a crash net, not a substitute — it is not a file you
control.

The schema is documented in [`app/project_schema.json`](app/project_schema.json).

## Install

Python **≥ 3.12** (mandatory — spectralign requires it).

```bash
pip install -r requirements.txt
python app/main.py
```

That opens the app. **Pick your acquisition directory on the Load screen** — hit **Browse…** for a
native folder picker, or paste a path. Nothing else is needed.

Optional GPU: `pip install cupy-cuda12x`. A 338-tile build is ~3 min with CUDA, ~8–10 min without.
The sweep itself — where you spend the hour — is only ~1.5× slower on CPU, because the inner loop
runs on the CPU either way. A CPU-only install is genuinely usable, not a consolation prize.

Development flags: `--data-dir DIR` skips straight past step 1, `--no-window` runs the server
headless, `--port N` pins the port.

## Data format

Snapshots are headerless raw `.dat`: little-endian `uint16`, 512×512, exactly 524,288 bytes, one per
trial, alongside a `log.txt` and per-trial XML.

⚠️ **The 180° flip is load-bearing.** The acquisition XML carries `ax=-1, ay=-1`, so the display
frame is the raw array rotated 180°:

```python
raw = np.fromfile(dat, "<u2").reshape(512, 512)
img = np.flip(np.flip(raw, 1), 0).astype(np.float32)
```

Every position the app produces lives in that flipped frame. Get it wrong and everything is 180° out
— and it will look completely plausible.

## Scale

**Exports are in pixels.** An optional µm/px field is provided, blank by default; physical units are
written only if you fill it in. There is no scale bar. The obvious way to calibrate here — measuring
the electrode-grid pitch — turns out to track *focus* rather than magnification, so it is not a
trustworthy ruler. Calibrate from the stage if you need real units.

## What this is not

The mosaic this produces is **a machine build that a human signed off on** — not an independent
ground truth. It must never be used to score the solver that produced it. That would be circular,
and the exported JSON says so, in the file, on purpose.

## Layout

```
app/
  main.py            entry point — FastAPI on 127.0.0.1 + a pywebview native window
  backend/           loader, engine adapter, server, exports, project file
  frontend/          the viewer (layered canvas) and the sweep
  API.md             the HTTP contract between the two
  PLAN.md            the spec
  RECON.md           the existing code's API surface, and ~20 traps
analysis/
  mosaic/            the placement engine — the app CALLS this, it does not fork it
  ground_truth/      the exclusion rule (the hand-authored ground truth is not published)
  benchmark/         the scorer
```

## License

**GPL-3.0-or-later.** The app links [spectralign](https://pypi.org/project/spectralign/), which is
GPL-3.0-or-later, so this is too.
