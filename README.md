# Camea

A Windows desktop app for microscopy analysis. It opens on a **project manager** — "what do you want
to do today?" — where you create, open, rename and delete **projects** that persist across sessions.
A **project = one dataset + one task**; the first task it ships with is a **human-verified mosaic
builder**: it places every snapshot tile automatically as a first draft, then walks you through
confirming, correcting, or excluding each one in a fast keyboard sweep — and a **Recompute** button
re-places everything else against the tiles you've anchored.

Mosaic building is the first task, not the whole app. The shell — projects, opening datasets, viewing
images, saving your work, running long jobs — is shared, so the next task (segmentation, annotation,
…) builds on the same core.

A **dataset** is raw and read-only. A **project** is what you did to it, saved in an app-managed store
folder you point at **once** — never inside the dataset, never inside this repo. **Auto-save is the
save**: your work is written continuously; there is no Save button (a quiet "Saved" indicator instead).

---

## The mosaic feature — six steps

A step unlocks when the one before it is done. Your work **auto-saves** continuously (`Ctrl+S` forces
a save now); an hour into a sweep, nothing is ever lost.

1. **Load** — the dataset attached to this project (a vscope acquisition directory).
2. **Range** — which trials are the mosaic? It parses `log.txt` and proposes the run (which you can
   override). The two serpentine passes are detected internally for the solver; you don't manage them.
3. **Screen** — which frames get thrown out? A scan *recommends* only the frames it is genuinely
   sure are unusable (blanks). It never auto-rejects anything.
4. **Place** — one button. The solver places every tile.
5. **Sweep** ⭐ — the heart of it. One tile at a time, in acquisition order: **`A`** anchor it
   (accept as ground truth — it joins the reference field), **`E`** exclude it, **`Space`** advance.
   Each tile fades in over a second on top of the field you have already certified; watching it
   materialise is how you see whether it lines up.
6. **Mosaic** — build the outputs: 16-bit TIFF (+ coverage mask), display PNG, `positions.csv`,
   ground-truth JSON, and a QC report.

Each tile is re-placed against **the anchors you have actually certified**, not against its
neighbours — so the sweep gets *more* accurate as it goes.

## Three design rules that are not negotiable

**The app knows nothing about your data.** It ships with no exclusion list, no per-dataset special
cases, no "have I seen this directory before". The only things that ever exclude a frame are *you*,
in this session, or an analysis you loaded. There is no toggle for this. It matters because the
exclusions *are* the research: an app that arrives already knowing which of your frames are bad has
short-circuited the one question it exists to help you answer. This is enforced structurally, and by
tests — the app opens a dataset as N-frames-on-disk and derives nothing.

**Blur is never auto-rejected.** Across 15 focus measures the best global threshold reaches
F1 = 0.37, and variance-of-Laplacian — the textbook autofocus metric — performs *worse than chance*
on this data (it is dominated by sensor noise, identical in sharp and blurry frames). So the scan
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

## Install

Python **≥ 3.12** (mandatory — spectralign requires it) and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --extra gpu     # drop --extra gpu on a machine with no NVIDIA card
uv run camea            # opens the desktop app
```

Camea opens on the project manager. On first run it asks you once to choose a folder where your
projects are kept (never inside a dataset or this repo). Then click **New project**, name it, pick the
task, and attach a dataset (point it at a folder of acquisition directories and pick one).

**GPU note:** the GPU extra must be `cupy-cuda12x[ctk]`, which `--extra gpu` installs — plain
`cupy-cuda12x` silently falls back to CPU. A build is ~3 min with CUDA, ~8–10 min without; the sweep
itself (where you spend the hour) is only ~1.5× slower on CPU, so a CPU-only install is genuinely
usable.

Modes: `uv run camea --window` (default, native window) · `--browser` (dev: opens in your browser,
best DevTools + testing loop) · `--headless` (server only, for tests/CI). `--open <root>` remembers
a dataset root; `--port N` pins the port.

### Developing the frontend

The UI is a TypeScript/React app in [`web/`](web/), served by the Python backend. Two terminals:

```bash
uv run camea --headless --port 8000 --open <dataset-root>   # backend
cd web && npm install && npm run dev                        # UI at :5173, proxies to :8000
```

The API client (`web/src/api/schema.d.ts`) is **generated** from the backend's OpenAPI schema
(`npm run gen:api`); `npm run check:api` fails if it drifts. See [`docs/FRONTEND.md`](docs/FRONTEND.md).

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

## What this is not

The mosaic this produces is **a machine build that a human signed off on** — not an independent
ground truth. It must never be used to score the solver that produced it. That would be circular,
and the exported JSON says so, in the file, on purpose.

## Layout

```
src/camea/            the app — one installable Python package
  core/               the shared core: dataset · frames · workspace · document · jobs
  engine/             the placement science (t27/t33) — under a 312/312 regression guard
  features/mosaic/    the mosaic feature: solve · document · export · routes
  api/                FastAPI; the OpenAPI schema the TS client is generated from
web/                  the frontend — TypeScript + React + Vite (project manager + mosaic wizard)
tests/                unit · api · slow (the 312/312 guard) · fixtures (a tiny synthetic dataset)
docs/                 BEHAVIOUR.md (the rulings) · SPLIT.md · API.md · FRONTEND.md · openapi.json
archive/              finished research + the previous app (not published; kept for reference)
```

## Tests

```bash
uv run pytest                       # fast backend suite (no data mirror needed)
cd web && npm test && npx playwright test   # frontend unit + the rulings-as-e2e suite
uv run pytest -m slow                # the 312/312 solver guard — needs the real data + a GPU
```

The whole fast suite and the e2e rulings run against a committed ~5.6 MB synthetic fixture, so CI
needs neither the raw data nor a GPU. The 312/312 guard is the one exception and runs locally.

## License

**GPL-3.0-or-later.** The app links [spectralign](https://pypi.org/project/spectralign/), which is
GPL-3.0-or-later, so this is too.
