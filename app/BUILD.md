# How to build this app — fan out, don't grind

> For the session that builds the app. Read **[PLAN.md](PLAN.md)** (the spec) and
> **[RECON.md](RECON.md)** (the API surface + the traps) first. Then run the workflow below.

## The rule that makes parallelism work here

**Contract first, then fan out on disjoint files.**

Six agents let loose on "build the app" write six incompatible halves. So:

1. **One agent, alone, writes the contract** — `app/API.md` (every HTTP endpoint, its request and
   response JSON, verbatim) plus the empty module skeleton and the project-file schema. Nothing else
   starts until this exists.
2. **Then everything else fans out**, each agent owning **files nobody else touches**. They code
   against `API.md`, not against each other.
3. **Integrate, then verify by driving the real app** — not by reading the diff.
4. **Adversarially review** the things that are quietly easy to get wrong (the flip, the +256, the
   caches, the GPU detection).

⚠️ **Camea is not a git repo**, so `isolation: 'worktree'` is unavailable. **File ownership is the
only thing preventing collisions.** Respect the ownership table below absolutely.

---

## Work packages (disjoint file ownership)

| # | Package | Owns | Depends on |
|---|---|---|---|
| **0** | **The contract** | `app/API.md`, `app/backend/__init__.py`, empty module stubs, `app/project_schema.json` | — |
| **1** | **Loader** | `app/backend/loader.py` | 0 |
| **2** | **Engine adapter** | `app/backend/engine.py` | 0 |
| **3** | **Server + native window** | `app/backend/server.py`, `app/main.py` | 0 |
| **4** | **Canvas / viewer** | `app/frontend/viewer.js`, `app/frontend/style.css` | 0 |
| **5** | **The sweep** ⭐ | `app/frontend/sweep.js`, `app/frontend/index.html` | 0 |
| **6** | **Exports** | `app/backend/export.py` | 0 |
| **7** | **Project file** | `app/backend/project.py` | 0 |
| **8** | **Packaging** | `app/packaging/` | 1–7 done |

### 1 — Loader (`loader.py`)
Parse `log.txt`; take the **longest contiguous block of `Snapshot` trials** as the mosaic run; detect
`pass_split` from the **largest interior inter-trial time gap, ignoring the block's first step**.
Load frames with the **numpy** reader (`np.fromfile(dat,"<u2").reshape(512,512)` then
`np.flip(np.flip(raw,1),0)`) — **not vscope**. Blank scan via band-passed std (DoG σ3/30, thr ≈ 60.1).
- ⚠️ **The 180° flip is load-bearing.** Verify it against a known frame **before writing anything
  else** — every existing position and all three ground truths live in the flipped frame, and getting
  it wrong looks plausible.
- ⚠️ **Do not copy `mosaic.io.load_frames`'s cache.** It validates only `shape[0] == len(trials)`, so
  two different 312-trial selections share an entry. Copy **t33's** model: hash in the filename,
  refuse a mismatch rather than repair it.

### 2 — Engine adapter (`engine.py`)
Wrap `t33.place / composite / match / exact_ncc`. **Call `analysis/mosaic/`; never fork it.**
- Placement runs **25 s – 10 min synchronously → must be off the UI thread.** No progress callback
  exists; capture stdout on a worker or add one.
- ⚠️ **GPU detection must execute a real op** — `import cupy` *succeeds* on a broken CUDA install; only
  `cupy.zeros(1)+1` raises. **Reuse `t27.xp()` verbatim.**
- ⚠️ Positions are **top-left corners**, not centres (+256).
- ⚠️ `info["config"]` is **not JSON-serializable** (nested `t27.Config`).
- Expose the ⭐ **anchor-composite primitive**: `composite(anchored_tiles)` → match a tile against it
  → **ranked candidates**. This one call powers place-next, snap, alternatives, and rescue.

### 5 — The sweep (`sweep.js`) ⭐ **the actual app**
`A` anchor / `E` exclude / `Space` next. 1 s transparent→opaque fade on placement. Tile states
anchored / unverified / excluded. Replay-fade, `D` difference, show-alternatives. Drag → snap.
**Port the bench's engine rather than reinventing it** (`utils/artifact/template.html`): the render
loop (:834), pan/zoom (:919–1014), the 100-deep undo/redo with tagged folding (:1649), the session
serializer (:1986). It is debugged and he authored three ground truths in it.

---

## Verification is not optional

The build is done when the app **runs on `data/drive/260620/260620_Imaging/260620d/`** and:
- the loader finds **exactly trials 11–348** and a pass split at **167**;
- the blank scan proposes **11** blanks;
- a build places **312** tiles and `analysis/tests/test_mosaic_312.py` **still passes**;
- the sweep's `A`/`E`/`Space` rhythm works on real tiles and the fade is visible;
- a drag + snap lands sub-pixel on the anchor composite.

**Drive it. Don't just typecheck it.**

---

## The workflow

Run it: `Workflow({ scriptPath: "d:/Projects/Camea/app/build_workflow.js" })`

It is contract-first, then a 7-way fan-out, then integration, then an adversarial review pass
targeting the specific traps in RECON.md. Edit the script and re-run with `resumeFromRunId` to iterate
without re-doing completed stages.
