# Stack speed audit - is this the fastest viable stack?

> 4 measurement agents + adjudication, 2026-07-12. Numbers are MEASURED on this machine unless flagged.

## The straight answer

**Yes — with one exception, and it isn't the language.** The stack (Python engine + WebView2 front-end) is the fastest *viable* one, and here's the check you can run yourself: of a 230-second build, the Python interpreter accounts for **~2.4 seconds — 1.0%**. Everything else is already running as compiled C, C++ and CUDA inside numpy/scipy/cuFFT; Python is just the remote control pressing the buttons. A perfect rewrite of the whole orchestration in C++/C#/Rust would recover **2–4 seconds out of 230**. The exception is real, though, and it's in the front-end: the prior-art renderer redraws all 312 tiles every frame and measured **10 fps at 1:1 zoom** — your 1-second fade would be a slideshow. That is a *code-structure* bug, not a language bug: restructuring it (still in JavaScript) took the identical scene to **6.1 ms/frame, locked 60 fps**. So: keep the languages, fix that one file.

## Where the time actually goes

**A cold 312-tile build (229.9 s measured, RTX 3080 Ti):**

| | time | share |
|---|---|---|
| Compiled CPU numpy/scipy (C) | ~144–157 s | 63–68% |
| GPU cuFFT/CuPy (C/CUDA) | ~70–80 s | 31–35% |
| **CPython interpreter** | **~2.4 s** | **1.0%** |

The popular story — "it's all FFTs, which are already C" — is **false**: cuFFT is only **8.4%** of the build. The real hog is `t33.exact_ncc`: **62,946 calls, 106.4 s, 46% of the build**, pure CPU numpy, GPU idle. It is still compiled C, just *inefficient* compiled C (it builds five full-size temporary arrays per call and runs **6.7× off the memory bandwidth limit**).

The interpreter number is measured, not assumed: `exact_ncc` costs **28.3 µs** at a tiny 64×64 overlap — and that 28.3 µs contains the entire Python call, all 12 numpy dispatches, every branch. At full 512×512 overlap it costs **2,048 µs**. The Python glue doesn't grow; the arithmetic does. There is no 20% hiding in the interpreter. There is barely a 1%.

**One Space press in the sweep** (match the next tile against a 156-anchor composite):

- Match: **1,068 ms GPU / 1,562 ms CPU-only** — of which ~91% is CPU numpy, ~9% cuFFT
- Composite rebuild: **268 ms** (full) or **108 ms** (incremental)
- Python↔JavaScript round-trip: **0.63 ms** for the verdict, 0.71 ms for a 512 KB tile — **0.06% of the click**
- Canvas draw: **1.4–6.2 ms/frame** layered (60 fps), vs **89.5 ms** immediate-mode (10 fps)

**So the total "language tax" on a Space press is under 1 millisecond, out of ~1,300.**

## What C/C++/C#/Rust would and would not buy

**Where native genuinely wins — startup.** A C++/Qt or C#/WPF window paints in ~50–150 ms; pywebview takes ~500–900 ms. That **~550 ms is real and I'm not going to pretend it isn't.** But it's paid once, and it's invisible, because in *every* option the engine stays Python — and numpy+scipy+spectralign+CuPy take a measured **1,502 ms to import** before the app can touch a single frame. Worse, a native shell forces the engine into a separate process: you'd pay two startups plus an IPC handshake instead of one. Time-to-first-*useful*-action is ~1.5–2 s in all six options. Against a session where you spend an hour in the sweep, 550 ms of launch is ~0.15%.

**Where a rewrite buys nothing:**
- **The engine.** 2–4 s of 230. And it would discard `t33` — the only placement method you have that scores 312/312.
- **The canvas.** The frame budget at 60 fps is **16.7 ms**. Layered canvas2d costs **1.4–6.2 ms** — *with GPU compositing switched off*. A hand-written C++/Direct2D or Rust/wgpu renderer's floor, measured on this machine via WebGL, is **0.1 ms**. So the absolute ceiling a native renderer could buy is ~6 ms/frame **that you would perceive as 0 ms**, because we're already waiting on the monitor's refresh. You can't draw faster than the screen updates. Cost: the 2,149 lines of debugged bench interaction code you authored three ground truths with.
- **The transport.** 0.63 ms against a 1,000 ms match. Unmeasurable.

**Where your instinct is right — but Python still wins.** `exact_ncc` really is 6.7× slower than physics allows. I measured the same maths four ways: shipped numpy **3,205 µs** → numpy+BLAS 2,547 µs → CuPy one offset 1,194 µs → **CuPy batching all 49 offsets in one kernel: 114 µs/offset (28×)**. A hand-written C loop would get you maybe 4–6×. **The GPU batching — ~30 lines of Python — beats it by 5×.** C++ would buy a *fraction* of a win that CuPy hands you for free.

## The changes worth making

Ranked by what you'd actually feel.

1. **Prefetch the next tile's match behind the fade.** ⭐ Biggest UX win by far. Today every Space press = a dead keyboard for **1.3–1.9 s**. Fire the match for tile N+1 the instant tile N is judged, on a worker thread, and it hides inside the 1 s fade + your own think time. **Perceived latency → ~0 ms.** ⚠️ **Must prefetch the A-branch** (composite *including* tile N where you're looking at it) — that's exact by construction. Prefetching from the composite *without* tile N disagrees with the truth in 18% of presses and is catastrophically wrong (up to 1,143 px) in 6%. That one is a correctness trap, not a speed choice.
2. **Layered canvas.** Bake anchored tiles into one offscreen background canvas; draw one `drawImage` + the fading tile per frame. **89.5 ms → 6.1 ms/frame. 10 fps → 60 fps.** ~40 lines. Appending a tile on 'A' costs 0.1 ms. Difference mode comes free via `globalCompositeOperation='difference'` (verified pixel-exact, +0.6 ms).
3. **Incremental anchor composite.** Keep the running arrays instead of rebuilding: **268→108 ms** at 156 anchors (432→113 ms at 250). Saves 160–320 ms per keystroke, and stops the cost growing as the mosaic fills. Bit-identical output.
4. **Memoise the pooled reference + its FFTs in the build's anchor loop.** The same array gets re-pooled and re-transformed 156 times identically. **~25 s off a 230 s build (11%), bit-identical, zero risk.**
5. **GPU warm-up on a worker at load.** 497 ms off the first match. Free.
6. **Then, optionally: batch `exact_ncc`'s 49 offsets onto the GPU.** 106 s → ~5 s; roughly halves the build. ⚠️ **This is the one risky item on the list.** It changes float reduction order. It does *not* change FFT sizes, but it *does* change the numbers in the last bits, and t33's failure mode is a silent lock onto the wrong correlation peak. **Gate it on `analysis/tests/test_mosaic_312.py`. If the guard wobbles at all, revert — 312/312 is worth more than 100 seconds.**

⚠️ **Do not touch `_smooth()` or any FFT size.** Everything above keeps the FFT grid at exactly 2160×1350 as shipped. Anything that changes an FFT size changes the numbers for a speedup you don't need.

## What we are NOT doing, and why

- **No native shell (C#/WPF, C++/Qt, Tauri, Electron).** Buys ~550 ms of launch, once, and costs a second language, a second process, and a sidecar lifecycle. Also: pywebview is the *smallest* of the six (installer 248 MB vs Electron's ~400 MB).
- **No WebGL/WebGPU.** 1.4 ms → 0.1 ms, i.e. zero perceived gain, in exchange for a second renderer to maintain — and a GPU process that crashed twice during this audit.
- **No engine rewrite.** 2–4 s of 230, and it would throw away the only 312/312 placement you have.
- **Not optimising the frame loader** (312 frames in 0.135 s — 0.06% of a build; threading makes it *slower*) **or the transport** (0.06% of a click). Effort there is effort not spent on the 1.3 s you actually feel.
- **Keeping OpenCV even though it's 111 MB — 45% of the installer.** The obvious swap to scipy shifts the blank-detection metric by 0.32% against a threshold whose nearest margin is 0.13%. **It can flip a blank classification.** An 85 MB installer is fine. Correct beats small.
- **Two honest caveats.** (a) The 229.9 s build was measured on a busy machine — the *ratios* hold, the absolute seconds are inflated ~15%. (b) The canvas numbers were measured with GPU compositing *disabled*, so they're a worst case — which is the point: layered holds 60 fps even there, immediate mode does not.

**Bottom line: the GPU buys 8× on the one-button build but only 1.46× on the interactive sweep** (1,068 vs 1,562 ms), because `exact_ncc` runs on the CPU either way. That makes the lean CPU-only default install a much better product than it looks: the part you spend an hour in is only 1.5× slower without a GPU.