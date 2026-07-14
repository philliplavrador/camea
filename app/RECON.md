# Recon brief — what the app reuses

> Auto-generated 2026-07-12 by a 6-agent recon over the existing Camea code tree.
> Signatures cited file:line. Verify before trusting; the code moves.

# Camea Mosaic App — Reuse Brief

## What already exists (and its exact API)

### Trial selection (mandatory gate)
`analysis/ground_truth/excluded.py`
- `usable_trials(lo, hi) -> list[int]` (:56) — the canonical trial list. `(11,166)→156`, `(167,348)→156`, `(11,348)→312`. Filters the 26 excluded **and** non-snapshots.
- `is_snapshot(t) -> bool` (:50) — `dat.stat().st_size == 512*512*2`. Hard-codes `DATA_DIR` (:32) and 512×512. **Not generic** (a 512×128 binned snapshot exists in sibling dir `260620`).
- `gaps(trials) -> [(a,b)]` (:65) — non-one-step consecutive pairs. On 11–348: `[(283,297), (298,311)]`.
- `EXCLUDED` (26), `BLANK` (11), `BLURRY` (15), `PASS1=(11,166)`, `PASS2=(167,348)`, `MERGED=(11,348)` (:35–47).

### Frame loading
- `mosaic.io.load_frames(data_root, date_dir, trials, ccd_key="Cc", frame_idx=0, cache=None) -> float32 (N,512,512)` (`analysis/mosaic/io.py:17`). Uses vscope (lazy import at :28). **Cache bug (:23): validates only `shape[0] == len(trials)`** — a different trial list of the same length silently reuses the wrong pixels.
- **vscope-free loader, already in production and verified byte-identical:**
  `analysis/texture/make_texture.py:37` — `np.fromfile(dat, "<u2").reshape(512,512)` → `np.flip(np.flip(raw,1),0)` → float32. Same recipe at `utils/artifact/build_page.py:116` (`load_frame`), which also has `read_trial_meta(xml)` (:80) and `list_snapshots(dir)` (:100) — ElementTree parse of `serpix/parpix/frames/typebytes/ax/ay`. **Lift these three and vscope leaves the graph entirely.**
- `mosaic.io.compute_flat(frames, sigma=15.0)` (:65), `flat_level(frames)` (:74), `flat_correct(frame, flat_n, level)` (:80). Vignette = Gaussian(σ=15) of the per-pixel median across **all** frames, normalised to mean 1; level = median of per-frame medians (exposure varies ~2.4×).

### Placement
- `mosaic.t33.place(trials, frames, cfg=None, cache=None) -> (pos, info)` (`t33.py:597`). **THE shipped method** — 312/312 on 11–348. `pos = {trial: np.array([x,y])}` = **top-left corners**, not centres. `cache` is a **directory**.
- `t33.Config(pass_split=166, anchor_ncc=0.30, split_px=12.0, look=3, min_side=2, t27=None, verbose=False)` (:112). Unknown kwarg → TypeError.
- `t33.match(A, MA, Bi, MB, kpk=10, minfrac=0.10, minabs=40000.0) -> [(ncc, dx, dy, npix)]` (:436) — **public, returns a RANKED list of distinct candidate peaks** (>24 px apart), best first. ~1 s/tile on GPU. This is the "did you mean here instead?" primitive.
- `t33.exact_ncc(A, MA, Bi, MB, dx, dy, stride=1) -> (ncc, npix)` (:400) — score an arbitrary (e.g. human-dragged) offset.
- `t33.composite(B, rows, local) -> (img, mask, m0)` (:274) — rebuild the frozen pass-1 reference field.
- `t33.breaks(trials, pass_split) -> [(row, ta, tb, why)]` (:234) — pure function of trial numbers; callable **before** loading pixels.
- `t33.pass2_backbone(cfg, B2, p2_trials, swim_cache) -> (fsx, fsy, fncc, step, cut_thr)` (:528).
- `mosaic.t27.place(trials, frames, cfg=None, swim_cache=None) -> (pos, info)` (`t27.py:765`) — single serpentine pass. `swim_cache` is a **file** (.npz), not a directory. Prints unconditionally, no verbose flag.
- `t27.Config(conf=0.62, run_conf=0.55, span=340, band_pad=4, r0=40.0, gain=0.05, gate_tol=60.0, topn=6, null_q=99.5, null_n=3000, r_drop=25.0, irls_iters=6, control=True, seed=11)` (:85).
- `t27.on_gpu() -> bool` (:153), `t27.xp() -> cupy|numpy` (:135), `t27._cuda_dll_dance()` (:120).

### Render
- `mosaic.render.render(pos, frame_of, tilesize=(512,512), blend=0, mode="alpha"|"feather"|"median") -> 2D float array of RAW CAMERA COUNTS` (`render.py:61`). `frame_of(t)` is a callback. Background is exactly `0.0`; no alpha, no clipping, no bit-depth conversion.
- `render._canvas(pos, tilesize) -> (trials, P, H, W)` (:81) — canvas geometry **without touching pixels**. Use this to size a viewport.
- `render._feather(h,w)` (:94) — separable triangular weight, floor 1e-3.
- `render.layout_png(xy, trials, path, title, *, color_of=None, show=False)` (:22) — calls `matplotlib.use("Agg")` when `show=False`.

### Quality
- `quality.band_pass(frames, lo=3, hi=30)` (`quality.py:17`) — DoG; allocates a **full second copy** of the stack.
- `quality.overlap_ncc(A, B, sx, sy, minov=3600, minside=40) -> float|nan` (:23).
- `quality.score_positions(pos, bp, trials, near=480) -> dict(..., per_tile={trial: median_link_ncc})` (:40).
- `quality.quality_plot(...)` (:139) — scatter coloured by per-tile NCC.
- ☠️ `quality.score_build` (:120) and `quality.leaderboard` (:131) are **DEAD** — `MROOT` (:84) points at a directory that no longer exists.

### Scoring (260620d only)
- `benchmark/score.py`: `load_gt(path, rng)` (:96), `robust_align(build, gt, max_iter=20)` (:134), `score(build, gt, build_id, tol=10.0, rng)` (:208) → includes `per_tile={trial:{err}}`, `wrong=[...]`, `rule_break`. **Do not reimplement `robust_align`** — a reimplementation with a different tie-break scored the same positions 152/156 where this gives 155/156.

### Blank/focus scan
- `texture/make_texture.py:47` — `texture_map(data_dir) -> {trial: band_passed_std}`. **3.0 s for all 342 frames** (9 ms/frame, CPU, no GPU/vscope/spectralign).
- `analysis/texture/260620d_texture.json` — precomputed, 4.2 KB.
- `utils/artifact/build_page.py:371` — `load_texture(...) -> {thr, std, blank:[...], reason:{t:'blank'|'blurry'}}`. **This is the exact UI contract the app needs** (two channels: measured vs. human-asserted).

### The bench (browser prior art)
`utils/artifact/template.html` (2149 lines, one vanilla-JS IIFE, zero deps). Input contract = one global `const DATA` spliced at `/*__DATA__*/` (:563).
- `refineOne(mov, R)` (:1496) — JS overlap-NCC "SWIM": band-pass (gray − 25 px box mean), reference = **placed anchors only**, coarse step-4 over ±R → fine ±5 → parabolic sub-pixel. Constants: `SWIM_MINOVL=6000`, `SWIM_COARSE=4`, `SWIM_BPR=12`.
- `runSwim(targets)` (:1527) — **refuses blank/blurry tiles outright** (:1536).
- `gtDoc()` (:1350) — the GT export; preserves unknown per-tile fields verbatim.
- `pushUndo/snapshot/restore/undo/redo` (:1649/1625/1634/1658/1664) — 100-deep document snapshot stack, tagged folding within 700 ms, drag pushes once on first pointermove.
- `serializeSession/applySession` (:1986/2007) — localStorage keyed `camea-bench-<dateDir>-<lo>-<hi>`; **rejects a session whose range differs** (:2012).
- `render()` (:834) — immediate-mode canvas2d, per-tile ImageBitmap, rAF-coalesced, anchors forced to bottom layer, smoothing off above 2× zoom.

---

## Hard numbers

**Frame.** `NNN-ccd.dat` = headerless little-endian uint16, row-major `(frames, parpix, serpix)` = `(1,512,512)`. **Exactly 524,288 bytes = 512·512·2.** XML transform `ax=-1, ay=-1` ⇒ display frame = raw array **rotated 180°**. Verified: `np.array_equal(vscope.load(xml).ccd["Cc"][0], np.flip(np.flip(np.fromfile(dat,"<u2").reshape(512,512),1),0)) → True`.

**Pixel range.** uint16 but only ~1/20 of range used. Global max across all 338 snapshots = 18,022 / 65,535 (27 %). **Saturated fraction is exactly 0.0 in every frame.**

**RAM.**
- 1 frame float32 = 512·512·4 = 1,048,576 B = **exactly 1.00 MiB**.
- 312 frames float32 = **312 MiB** (327,155,712 B; `frames.npy` on disk = 327,155,840 B).
- As uint16: 156 MiB. As uint8 display textures: 78 MiB.
- **Peak is 2–3×, not 1×:** t27 band-passes the whole stack into a second float32 array (`t27.py:789`) → ≥624 MiB; `io.compute_flat` does `np.median` over the full stack (`io.py:69`) → another copy. **Budget ~1 GB host RAM** for a 312-tile run (~1.4 GiB if median render).
- GPU: t27 device peak ~1.0 GB @156 tiles, ~2.0 GB @312. Tight on a 4 GB card.

**Load cost** (warm page cache, local D:). Pure numpy: **312 frames in 0.12 s** (0.37 ms/frame). vscope: 1.6 ms/frame ⇒ ~0.5 s for 312. **numpy is ~4× faster.** Total bytes = 312 × 524,288 = 163.6 MB, so cold off a 100 MB/s disk is bounded at ~2 s. **Loading is not the bottleneck.**

**Build runtime (t33, 312 tiles).**
- GPU cold (`cache=None`): **~180–200 s**. Of which the per-tile anchor loop is **~150 s** — 156 *sequential* whole-plane matches (`t33.py:729-739`).
- GPU warm (backbone + anchors cached): **~25 s** (~5 s to STEP 5, then ~20 s for the 11 run-vs-pass-1 composite matches).
- CPU-only: **never measured end-to-end.** Kernel-rate extrapolation: batched SWIM 4,367 pairs/s GPU vs 135/s CPU (32.4×); NCC scan 5.23 M evals/s GPU vs 1.22 M/s CPU (4.3×). ⇒ n=312 (48,516 pairs, 45.1 M evals) ≈ **397 s kernel + overhead ≈ 8–10 min**. n=156 ≈ 2–3 min. **CPU-only is shippable.**

**Render canvas (shipped 312-tile build).** x ∈ [−770.30, +968.99] (span 1739.28), y ∈ [−1593.54, +1735.96] (span 3329.50). Plus 512 px tile ⇒ **H=3841, W=2251 = 8,646,091 px**, tall portrait 1.71:1. float32 = **32.98 MiB**. Both dims < 8192 ⇒ **fits one GPU texture. No pyramid, no tiling, no memmap needed.**
- Redundancy: 312 × 512² = 81.8 Mpx of tile pixels into 8.65 Mpx of canvas = **9.46×**. Coverage: 13.1 % empty, 4.8 % depth-1, 2.1 % depth-2, **80.0 % depth ≥3; max depth 31; mean 10.89**.
- ⚠️ `mode="alpha"` returns **float64 on 3842×2252** — one px larger each dimension than feather/median's 3841×2251.

**Render times** (CPU, 312 flat-fielded frames in RAM): **feather 1.11 s**, median 41.71 s (~800 MiB peak: a 452.8 MiB band strip + a 312 MiB frame copy), alpha 74.02 s. Flat-field prep adds 1.79 s, once. **Only feather is interactive.**

**Export sizes at true 2251×3841** (measured): 8-bit PNG 3.54 MiB; **16-bit PNG 8.01 MiB**; 8-bit WebP q82 0.41 MiB; raw uint16 (uncompressed TIFF) 16.49 MiB; float32 .npy 32.98 MiB. **BigTIFF is irrelevant** — 16.49 MiB vs a 4 GiB limit.

**⚠️ The shipped `mosaic.png` is NOT the mosaic.** It is a matplotlib figure: 1416×2426 (0.629× linear, 40 % of the pixels), 8-bit RGBA, 1–99 percentile stretch baked in, **title drawn on**. And `SAVE_MOSAIC_NPY` defaults to False — **the shipped output dir contains no full-resolution mosaic data at all.**

**Blank threshold = 60.1** (`build_page.py:75`) = the 2.0th percentile of pass-1 texture; recomputed exactly **60.1136**. Texture = std of DoG(σ=3, σ=30) of the frame.
- ⚠️ **Applied to 11–348 it flags 15 trials, not 11**: adds pass-1 trials **34, 55, 56, 127** — all usable and all correctly placed in the 100 %-solved pass 1. The clean "exactly {289, 300–309}" result only holds because `build_page.py` was invoked with `--trial-min 167`.
- ⚠️ **Zero margin at the boundary:** usable 56 = 56.39 < blank 309 = 56.53 < usable 34 = 58.44 < blank 289 = 58.54 < usable 127 = 58.58 < usable 55 = 59.98 < **[60.11]** < usable 35 = 61.32.
- Better (unshipped): `bp_over_std` = band-passed std / raw std. At ≤0.107 it catches 10/11 blanks with **zero** false positives (F1 0.952 vs 0.917).

**Scan cost.** Full texture scan of 342 frames = **3.0 s**, single-threaded CPU, numpy+cv2 only. Not a performance problem.

**Score of the shipped build** (`score.json`): 312/312 within 10 px = **100.0 %**, median err **1.82 px**, max **9.94 px** (trial 127, a *pass-1* tile), rot −0.0069°. Tolerance ladder is **flat** from 10 px to 256 px ⇒ **failure is binary**, not drift: a tile is right within a few px or hundreds of px wrong.

**Env** (`camea`, 2.73 GB): Python 3.12.13, numpy 2.4.6, scipy 1.17.1, opencv 4.13.0, pandas 3.0.3, matplotlib 3.11.0, cupy 13.6.0 (CUDA rt 12.9), Pillow 12.2.0, **PySide6 6.11.1 already installed**, spectralign 0.4.2, vscope 1.1.0. CUDA payload (nvidia 573 MB + cupy 134 MB) = **707 MB = 26 % of the env**. **Absent:** tifffile, imageio, skimage, zarr, torch, fastapi, flask, pyqtgraph, napari.

---

## Load-bearing constraints

**1. spectralign is a hard dep — and it is GPL-3.0-or-later.** The only irreplaceable call is `Placement.rigid` (`utils/vendor/spectralign/spectralign/placement.py:79`, used by `t27.solve_rigid` t27.py:689) — ~55 lines of pure numpy (weighted graph Laplacian + a Lagrange row forcing sum(X)=0, then `np.linalg.solve` on a dense 313×313). `t27.swim_all(validate=True)` also cross-checks against `spectralign.swim.Swim` (can be disabled with `validate=False`). `render mode="alpha"` needs `spectralign.Renderer`; **feather/median are pure numpy**. Net: reimplementing `Placement.rigid` (~25 lines) removes GPL from the shipping graph in ~1 day. **The license, not the wheel, is the distribution constraint.**

**2. Both "vendored" packages ARE on PyPI.** spectralign 0.4.2 and vscope 1.1.0 both publish `py3-none-any` wheels (51 KB / 28 KB, zero compiled extensions). The real blocker is that **vscope declares `Requires-Dist: cairo`, and a package named `cairo` does not exist on PyPI (404)** — so `pip install vscope` fails outright; it needs `--no-deps` + conda-forge `pycairo`.

**3. vscope is droppable and should be dropped.** It appears in exactly two places (`io.py:28`, `match.py:153`), both doing only `vscope.load(xml).ccd["Cc"][i]`. It plays **no** part in placement. The repo already ships a proven vscope-free reader. Dropping it deletes **cairo, salpa, ppersist, physfit** from the graph in one move. (vscope also reads with *native* byte order — `loader.py:149` — so the explicit `"<u2"` path is strictly safer.)

**4. GPU is optional, but detection must EXECUTE A REAL OP.** `import cupy` **succeeds** on a broken CUDA install (only a UserWarning); it is `cupy.zeros(1)+1` that raises `RuntimeError: failed to load nvrtc64_120_0.dll`. `t27.xp()` (:135) does exactly this and falls back to numpy on any Exception. **A naive `try: import cupy / except ImportError` guard does not work.** Reuse `t27.xp()` verbatim.
- `_cuda_dll_dance()` (:120) must run **before** `import cupy`, **in-process**: it `os.add_dll_directory()`s each `site-packages/nvidia/*/bin` (Python 3.8+ ignores PATH for a .pyd's dependent DLLs) **and** prepends them to `os.environ["PATH"]` (NVRTC loads its companion `nvrtc-builtins64_*.dll` via plain LoadLibrary, which does use PATH). This is a **process-global side-effect** a GUI must tolerate, and it **breaks under PyInstaller** (`sys._MEIPASS` ≠ `sysconfig.get_paths()["purelib"]`).

**5. t33 bakes in serpentine + exactly two passes.**
- Serpentine, twice: via `t27.place` (pass 1's whole solve) and via `t33.pass2_backbone → t27.precheck/fix_backbone`. The axis-manifold search, the near-zero veto (`r0=40`), and the column gate (`gate_tol=60`) are all serpentine-specific.
- **It degrades silently, not loudly.** `t27.precheck` raises only if *no* consecutive step reaches `conf=0.62`. Otherwise the axis band is **measured** from the confident steps — so one freak step inflates it. Pass 2's 204→205 step took the band from ~18 px to **233 px = 89 % of the plane**: the prior switched itself off without saying so. *A prior that one outlier can disable is not a prior.*
- `cfg.pass_split` is a **required input the method cannot measure**. Nothing in the repo reads it from XML or log.txt. (In the log the 166→167 gap is 20 s — but so is 11→12, so a max-gap rule is a coin-flip.) **Three or more passes are unsupported and there is no knob** — the code hard-partitions on `t <= pass_split`.
- t33 **stands on pass 1 being right**, and nothing checks that. `info["pass1_max_dev"]` only proves t33 *didn't move* pass 1, not that t27 got it right.
- The two passes must **overlap substantially**: pass 2 re-images 95.6 % of pass 1's area.

**6. 512×512 is hard-coded** in `t33.TILE=512` (:108), `t27.H=W=512, PAD=1024` (:77-78), `io.py:30`, `excluded.py:53`. And **shape is per-trial, not per-directory**: sibling dir `260620` trial 021 is a genuine `type="snapshot" frames="1"` at parpix=128 (131,072 B) — `is_snapshot()` would reject it and `load_frames` would crash. A general app **must parse the XML**, not infer shape from bytes.

**7. ⛔ The 26 excluded snapshots (284–296, 299, 300–310, 348) are not data.** Never load, render, match, score. Removing them **from the input** took T27 from 19.2 % → 37.2 % on pass 2. Consequence: **trial number is acquisition order but is not contiguous** — gaps at **283→297** and **298→311**, where the serpentine one-axis prior does not hold. t33 cuts a run at each; t27 only *warns* (`t27.py:779`). **Any app that lets the user toggle exclusions must recompute `gaps()`** or it silently poisons placement.

**8. Blur is NOT auto-detectable. This is now quantified, not just asserted.** Over all 338 snapshots in 11–348 with 15 focus measures, the **best global threshold on the best measure reaches F1 = 0.37**. To catch all 15 blurry frames you must also reject **62/312 usable ones (best case, Brenner)**, 71/312 with texture, 109/312 with bp_over_std. **Variance-of-Laplacian — the textbook autofocus metric — is the WORST performer** (AUC 0.602; contrast-normalised varlap is 0.358, *worse than chance*): it barely moves across the blur transition (283 sharp = 222,668; 284 blurry = 223,332) because it is dominated by sensor noise, which is identical in blurry and sharp frames. **Do not put a Laplacian-variance number in front of the user.**
- The best signal found (locally-normalised electrode-grid FFT peak, F1 = 0.640) **gets the hardest call exactly backwards**: trial 347 (KEPT) scores 3.03, trial 348 (EXCLUDED) scores 7.52.
- Rank-and-review cost: sorted worst-first by normalised Tenengrad, the 15 blurry frames land at ranks 8…140 — **the user must review the worst 140 of 338 (41 %)** to surface them all.
- ⇒ **The focus scan must be a ranked review UI with a user-swept threshold, never an auto-reject.**

**9. Blank/blurry frames must be REFUSED by the matcher, not scored.** Two blank frames **136 trials apart** correlate **+0.43 at zero shift** (vs a 0.115 honest noise floor) because what they share is fixed-pattern *sensor* structure, which does not move with the stage. They register **confidently and wrongly**. The bench already disables SWIM for them (`template.html:1536`) — keep that.

**10. Tone mapping must stay GLOBAL.** One 0.5/99.6-percentile window across all frames after flat-fielding. A **per-tile** percentile stretch over-brightens near-empty frames and makes overlapping tiles disagree in tone — which destroys the Difference-mode check the user relies on to verify a placement.

**11. Positions are TOP-LEFT corners, not centres.** Everything that plots them adds +256 (`quality.py:145`, notebook layout cell). Off-by-256 is the classic bug here.

**12. No progress callback anywhere.** t33's only signal is `print` behind `cfg.verbose` ("anchored q/156 tiles", every 30 tiles, `t33.py:737`). t27 prints unconditionally with no flag. A GUI must capture stdout on a worker thread, or the API needs a callback added. **Placement runs 25 s – 10 min synchronously and MUST be off the UI thread.**

**13. `info["config"]` is not JSON-serializable** — it holds a nested `t27.Config` object. `json.dumps(info, default=float)` **crashes**. Use `build_mosaic.ipynb`'s `jsonable()` (`default=lambda o: vars(o)`).

**14. Python ≥ 3.12 is mandatory** across the stack (spectralign requires it; `salpa` ships cp312/313/314 wheels with **no sdist**). No 3.11 fallback exists.

**15. O(n²) pairs.** 312 tiles = 48,516 pairs. Runtime and the ~2 GB device footprint both scale quadratically. Do not advertise unbounded tile counts; beyond ~500 tiles this hurts.

---

## Per-tile confidence signals available after a build

| Signal | Source | Coverage | Trustworthy? |
|---|---|---|---|
| **Anchor NCC (`ancv`)** + **anchor position (`anc`)** — each pass-2 tile's *independent* absolute match against the frozen 7.0 Mpx pass-1 composite | computed at `t33.py:727-741`; persisted to `T33_anchors_<tag>_<hash>.npz` | **pass 2 only** (156/312) | **The best signal there is.** 156/156 reached NCC ≥ 0.30; median 0.815. The 7 Mpx aperture is what escapes the tile-pair false-confidence trap. |
| **Anchor residual** = `\|(anc[q] + M1) − pos[t]\|` (M1 = min over pass-1 positions, recoverable from `pos` alone) | **does not exist — one subtraction away** | pass 2 only | **Probably THE number to sort a "check these first" list on.** It caught trial 311 at 2706 px while its run agreed to 4.4 px. But it has fired exactly **once**, its false-positive rate is unmeasured, and t33's own design treats a lone disagreeing anchor as an **outlier to discard**. Present as "go look", never as a verdict. |
| **Run margin** (best − second masked NCC of the run's composite vs pass 1) | `info["runs"][k]["margin"]`, `info["margins"]` | pass 2, per run (inherit to tiles) | Good. Shipped build: R0 0.473 … **min_margin 0.081** (R1). The three 2-tile runs (R1, R2, R9) carry the thinnest margins — a 2-tile run is only a ~0.5 Mpx aperture. All 6 of their tiles were nonetheless correct. |
| **Run overlap_px** | `info["runs"][k]["overlap_px"]` | pass 2, per run | 262 k – 2,394 k px. Low overlap = thin evidence. Honest. |
| **Backbone step NCC (`fncc`)** | `t33.pass2_backbone`, cached in `T33_backbone_*.npz` | pass 2 steps | ⚠️ **This is precisely the quantity T33 exists to distrust.** Step 311→312 scores **0.983 and is wrong by 2708 px.** Useful only for flagging LOW values; **worthless as positive confidence.** |
| **`quality.score_positions` per-tile median overlap NCC** | `quality.py:40` | **all 312** | ⚠️ **Smoke alarm only, and a bad one.** On the 312/312 ground-truth-perfect build it flags **11 tiles** below 0.3 (119 @0.127, 127 @0.137, 233 @0.159, 208 @0.178, 120, 77, 232, 126, 79, 141, 204). **All 11 are false positives — precision 0/11 = 0 %.** It is an overlap-NCC on tile *pairs* — the exact aperture T33 escapes. |
| **Texture (band-passed std)** | `260620d_texture.json` | all | Reliable for **blank**; near-useless for **blur** (§8). |
| **Ground-truth error** | `benchmark/score.py` `per_tile[t]["err"]` | 260620d only | Exact — but **a new dataset has no ground truth, so none of this exists there.** |
| **Pass-1 per-tile confidence** | **NONE EXISTS** | — | ⚠️ **t27's `info` is aggregate-only.** And the worst tile in the shipped build (**127 @ 9.94 px**) is a **pass-1** tile. A UI built only on t33's pass-2 signals is blind to exactly the tile most at risk. The material exists: `t27.solve_irls` **returns its kept link set** (`t27.py:715`) and `solve_positions` **throws it away** (`t27.py:750`) — exposing it would give per-tile link count, per-link residuals, and which links IRLS dropped. That is a real code change to t27, which sits under a 312/312 regression guard. |

### Alternative candidate positions per tile — **YES, directly supported**
`t33.match()` (`t33.py:436`) **already returns a ranked list of distinct peaks** `[(ncc, dx, dy, npix)]`, ≥24 px apart, best first. **`place()` discards all of it** — it takes `c[0]` and `c[1][0]` (for the margin scalar) at lines 732-736 and 833-838.

Two ways to get alternatives:
- **Per tile** (~1 s/tile GPU): re-call `t33.match(IMG1, MSK1, tile_bandpassed_meansubtracted, np.ones((512,512),bool), kpk=8, minfrac=0.0, minabs=120000.0)` — the exact call `place()` makes. Yields ~8–13 ranked alternatives. Rebuild `IMG1/MSK1` with `t33.composite()`.
- **Per run**: `t33.match(run_img, run_msk, IMG1, MSK1)` gives alternative **run origins** (10 NCC peaks + 5 phase-correlation peaks). Moving a run moves all its tiles rigidly.
- **Score a human's drag**: `t33.exact_ncc(IMG1, MSK1, tile, TMSK, dx, dy)` — "you dragged it here; here's what the pixels say."

**Decision:** capture the full candidate lists during `place()` (cheap, changes nothing numerically) **or** recompute on demand in the UI (zero risk to the shipped numbers). Recommend on-demand — the shipped build is under a regression guard.

**Calibration warning for any of these:** the measured false-confidence rate at *tile-pair* aperture is **5 %** — of 719 genuinely-overlapping non-consecutive pass-2 pairs, the exact whole-plane masked-NCC argmax is >20 px wrong for **38**, at scores up to **0.760**. Canonical: 222 vs 250 — the winner (0.760) is **757 px wrong** and the truth is only the runner-up (0.677). The **same tile against the pass-1 composite**: 0.654 vs 0.416 next best (margin 0.238), landing **1.7 px** from the human. *Aperture is everything.*

---

## Reuse from the hand-placement bench

**Transfers essentially whole** (dependency-free, data-source-agnostic vanilla JS; the 2026-07-10 revamp rebuilt CSS+markup and kept the engine **byte-for-byte**, proving the separation):
- The entire render/pointer/camera loop (`render()` :834, pan/zoom/marquee handlers :919–1014, anchors forced to bottom layer, smoothing off >2×, feathered backdrop).
- The undo/redo engine (:1649) — production-grade: 100-deep, tagged folding, drag pushes once on first pointermove.
- The session serializer (:1986) — **including the range-in-the-key guard** (:2012), which exists because pass 2's autosave once silently overwrote pass 1's GT records.
- The GT export (`gtDoc()` :1350) — deep-copies each tile so unknown fields survive the round-trip.
- The two-channel unusable model (`blank` = measured; `blurry` = human-asserted) and the SWIM refusal (:1536).
- The keyboard map: arrows nudge 1 px (shift 10), Del, Esc, F fit, 0 = 1:1, **D = Difference**, L lock, `[`/`]`, Ctrl+Z/Y.
- `build_page.load_frame` / `compute_flat` / `flat_correct` / the **global** tone window (:507-522) — reuse verbatim as the app's tile provider.
- `build_links` (:173) — kind 0 = consecutive whole-frame spectralign SWIM (~78 % overlap, alias-robust, the good links); kind 1 = subregion pairs. Every link carries a band-passed overlap NCC; the UI colours >0.50 trustworthy / <0.30 aliased. **`snr` alone is not a safe filter** (an snr-31.5 link is a real alias).

**Does not transfer / must be replaced:**
- The bake step. `srcPx == tilePx == 512` — **there is no spatial downsampling**; the 16 MiB artifact cap is paid entirely in **bit depth and lossy compression** (uint16 → uint8 global window → WebP q80, ~24 KB base64/tile). A local backend serves 16-bit pixels on demand.
- The in-browser SWIM. It is **not spectralign** — a JS reimplementation (band-pass = gray − 25 px box mean; reference = placed **anchors only**; coarse step-4 over ±R subsampling 2×; fine ±5; parabolic sub-pixel). At R=48 that is **~74 M inner-loop iterations per tile**. It is **verified sub-pixel-exact** (tile 116 recovered to (402,478) vs true (401,478) from two different starts, match 0.79) but is **alias-safe only because ±48 px is far inside the electrode grid's 256 px period** — widen past ~128 and a grid alias wins. Its runtime is **nowhere measured**.

**What a real desktop/local app unlocks** (every one of these is an artifact-sandbox artifact, not a design constraint):
- 16-bit full-res pixels with a **live window/level** control (he has never had the choice — the baked 8-bit window was forced by the cap, not chosen).
- **The real spectralign SWIM at click time**, on 16-bit pixels, with GPU.
- **`t33.match()` alternatives on demand** — the "did you mean here?" button, impossible in a static page.
- Genuine autosave + crash recovery (localStorage is blocked and **fails silently** in the sandbox).
- **Downloads** — currently **silently blocked** (no `allow-downloads` on the iframe sandbox; `<a download>.click()` is dropped with **no catchable error**). This nearly cost him a day's work.
- Direct writes to the GT file — killing the Copy-JSON-and-paste round-trip entirely.
- No 16 MiB cap, no CSP block on fetch/XHR/WebSocket.

**⚠️ The bench's `region` and `pending` statuses are dead in practice.** The live GT docs contain **zero** of each: pass1 = 156 anchor; pass2 = 156 anchor + 26 excluded; merged = 312 anchor + 26 excluded. He SWIM-anchored everything he could and threw out the rest. And `excluded` was added to the JSON **after** the bench was written — the bench has no first-class concept of it: it falls through `gtDoc()`'s unknown-status branch (:1383), **draws no ring, and is still selectable and draggable**.

---

## Packaging recommendation

**Recommend: a localhost web app on the Windows host — Python/FastAPI backend + the existing bench's HTML/JS front end — reached through VSCode Remote SSH's automatic port forwarding.**

Rationale, in order of weight:
1. **It matches how he actually works.** He drives Camea over **VSCode Remote SSH**: the browser runs on his laptop, the data lives on the Windows host's `D:`. His standing memory note is *"deliver visual output inline in cells, never GUI windows/browser popups."* **A native Qt window on the remote host is invisible to him unless he RDPs in.** This is the single most decisive fact in the whole recon.
2. **The front end already exists, is debugged, and is proven** — he authored all three ground truths in it. Porting the render/pointer/undo/session engine to Qt is re-doing solved work.
3. Every artifact limitation (16 MiB cap, no fetch, silent localStorage failure, silently blocked downloads) dissolves at once.
4. The mosaic is **8.7 Mpx** — one GPU texture, no pyramid. The canvas2d immediate-mode renderer already proves 312 tiles redraw interactively with **zero pre-composite**.
5. Python stays where the science is (`t33.place`, `t33.match`, `exact_ncc`, `score.robust_align`) and is called over HTTP/IPC per click.

**Trade-off accepted:** you must run a local server process and manage its lifecycle (start/stop, port, worker thread for the 25 s–10 min placement job); a stray `localhost:PORT` is a small attack surface (bind `127.0.0.1` only); and there is no single-file `.exe` to double-click. FastAPI is **not currently in the env** — one `pip install`.

**Runner-up: native PySide6 desktop app.** **PySide6 6.11.1 is already installed**, it would be a true single Windows app, and `render.layout_png` already uses Agg (render-to-buffer, blit into canvas) which is the correct Qt pattern. **It lost on the Remote-SSH fact alone** — a native window on the host is invisible to his actual workflow. Secondary strikes: it means reimplementing the bench's render/pointer/undo engine from scratch; `matplotlib.use("Agg")` inside `layout_png` is a **backend-switch hazard** once a Qt backend is live; and packaging it with PyInstaller **breaks `_cuda_dll_dance()`** (`sysconfig.get_paths()["purelib"]/nvidia/*/bin` does not exist under `sys._MEIPASS` — the dance must be rewritten for a frozen layout), plus an unsigned PyInstaller EXE reliably trips SmartScreen/AV.

**Third: ship nothing.** For this one user on this one machine, `analysis/build_mosaic.ipynb` (config cell → Run All) **already works and costs zero.** The entire packaging exercise is only justified if the target is other people or other labs. **See Q1.**

**Env delivery, either way:** conda-pack or a CPU-only frozen env. Ship **CPU-only by default** (~2.0 GB) and offer GPU as an optional add-on — the CUDA payload is **707 MB / 26 % of the env**, and CPU-only is a shippable ~8–10 min for 312 tiles. ⚠️ **conda-pack relocatability of the pip-installed cupy/`nvidia-*-cu12` wheels is untested** — conda-pack fixes *conda* packages' absolute paths, not pip ones.

---

## Open questions that only the user can answer

1. **Who is the app for?** If it is only him on this machine, `build_mosaic.ipynb` already does the job and the whole exercise is unjustified. Everything below is downstream of this.
2. **Native window on the Windows host, or localhost web app port-forwarded through VSCode?** He works over Remote SSH today, so a native window would require RDP. This determines the entire shell. *(The recommendation above assumes web; confirm before committing.)*
3. **260620d viewer, or generic acquisition-directory tool?** If generic: the 26-trial exclusion list, `PASS_SPLIT=166`, the 512×512 shape, the 60.1 blank threshold, the DoG(3,30) band, and the serpentine prior **all become per-dataset config with no way to derive them** — and the 15 blur exclusions are a human judgement **no metric reproduces**. This roughly doubles scope.
4. **Is the last step AUTHORING ground truth (place from scratch, what the bench does today) or VERIFYING a machine build (accept/reject/correct each solved tile)?** These are different UIs. The verification flow — a per-tile accept/reject queue, an "N tiles disagree" worklist, an error map — **does not exist yet**.
5. **If verifying: should the app show the machine's answer while he checks?** It is the obvious UX and it is **exactly how pass 1's truth got 4 tiles wrong** (128/129/130/148 — seeded from the R2T1 build, the human deferred to it; caught only because pass 2 was authored from scratch with no seed). If yes, the design needs an explicit anti-anchoring measure (hide the machine answer until he commits, then diff).
6. **Should the exclusion list be editable in the GUI?** His ruling is that the 26 frames are *"never used for any purposes whatsoever"* — but an app that lets a user tick tiles back on directly contradicts it. Locked for 260620d, editable for a new dataset? And should the 26 even *appear* in a review list?
7. **Must the app be closed-source?** If GPL-3.0 is fine (likely, academic), keep spectralign. If not, budget ~1 day to reimplement `Placement.rigid` and drop to feather/median rendering.
8. **Does the target machine have an NVIDIA GPU?** Determines whether to ship the 707 MB CUDA payload. CPU-only is ~8–10 min for 312 tiles.
9. **Which export first — a display PNG for a figure, or a 16-bit TIFF for Fiji/ImageJ?** The repo currently produces **neither correctly** (the PNG is downsampled + captioned; there is no TIFF writer in the env at all). He will probably want both, as separate files.
10. **What is the physical pixel size (µm/px)?** **Not present anywhere in the repo.** Needed for a scale bar, for OME-TIFF `PhysicalSizeX/Y`, and for any measurement tool. Only he knows it.
11. **Does the app re-run placement, or only ever load an existing `positions.csv`?** `BuildConfig.positions_from` already skips match+solve and just renders — the hand-correction round-trip exists. Re-running means shipping a working CuPy/CUDA path (or accepting 8–10 min CPU).
12. **Should live SWIM call real spectralign (16-bit, GPU, ~1 s round-trip) or keep the JS NCC search (verified sub-pixel-exact, zero round-trip)?** Unmeasured: whether a Python round-trip per click feels interactive.
13. **When "point at a directory of snapshots" — what does the app select?** The dir has **342** snapshots; the mosaic is **312** (the 11–348 burst, minus 26). Auto-take the largest time-burst (a >30 s inter-snapshot gap cut works perfectly on 260620d, unvalidated elsewhere), show all and let him pick a range, or both with the burst as default?
14. **Keep the `region` status at all?** The UI supports it, the schema documents it, and he shipped **exactly zero** across three ground truths.

---

## Risks / traps

- **The 180° flip is load-bearing.** `ax=-1, ay=-1` ⇒ display frame = raw array **rotated 180°**. Every `positions.csv` coordinate, every SWIM dx/dy, and all three ground truths live in the **flipped** frame. Get it wrong and the app is 180° out from every existing result — and it will *look* plausible.
- **`mosaic.io.load_frames`'s cache is unsafe as written** (`io.py:23`): it validates only `shape[0] == len(trials)`. **Two different 312-trial selections share a cache entry.** Copy t33's model instead (`t33.py:177`: range + config hash **in the filename**; `_load_checked` at :214 **refuses** a key mismatch rather than repairing it).
- **Residual cache hole even in t33: nothing hashes the PIXELS.** If the frames change (different `ccd_key`, `frame_idx`, a re-decode) but the trial list, first/last/n and config are identical, **every cache file is silently reused**.
- **This exact class of bug already shipped and was caught by three independent reviewers (2026-07-12):** the t33 cache was keyed on the trial list alone, so a warm re-run with changed knobs returned the **old** numbers while `info["config"]` and `results.json` recorded the **new** ones. Reproduced: warm cache + `run_conf=0.95` gave `cut_thr=0.550` (an honest recompute must give ≥0.95) with bit-identical positions. Now fixed — **do not regress it.**
- **Ground-truth contamination is a live, previously-realised hazard.** The archived GT at `analysis/archive/challenge_2026-07/benchmark/ground_truth/260620d.json` **is T27's own output** — never use it as a reference. This project already destroyed one benchmark by overwriting it with an algorithm's output, after which that algorithm scored 100 % by construction. **A verification UI that shows the machine's answer and lets the user click "accept" is structurally the same hazard.** (See Q5.)
- **Do not reimplement `score.robust_align`.** A reimplementation with a different tie-break scored the same T27 positions **152/156** where the canonical one gives **155/156**. Import it.
- **`t27.precheck` degrades silently on a non-serpentine scan** rather than raising. It raises only if *no* step reaches `conf=0.62`. Otherwise the measured band inflates and the prior turns itself off with no warning (233 px = 89 % of the plane on pass 2).
- **`quality.score_build()` and `quality.leaderboard()` are dead** — module-level `MROOT` (`quality.py:84`) points at `output/mosaic/trials_015-166_n152`, which no longer exists. Both raise. Call `score_positions()` directly.
- **`mode="alpha"` silently returns float64 on a canvas 1 px larger in each dimension** than feather/median, despite the docstring claiming they match. A mode switch invalidates cached viewport geometry and doubles canvas memory.
- **13.1 % of the canvas is background encoded as exactly `0.0`** — indistinguishable from a legitimately black pixel. **There is no alpha/mask channel.** Export to plain PNG/TIFF merges them. Carry the coverage mask (free: `wsum > 0` in the feather path, or `render._canvas` + tile rects).
- **`mode="median"` emits `RuntimeWarning: All-NaN slice encountered`** on the last band (cosmetic bug, `render.py:117-133`). Suppress or fix.
- **`render.layout_png` calls `matplotlib.use("Agg")` when `show=False`.** Calling it from inside a live Qt app is a backend-switch hazard.
- **matplotlib DLL trap (Windows):** calling `envs/camea/python.exe` directly **without** the env's `Library/bin` on PATH makes Agg die with a delay-load DLL failure (`0xC06D007F`) **at draw/savefig time — imports succeed**, so it looks mysterious. Use `conda.bat run -n camea python -s script.py` with `MPLBACKEND=Agg`.
- **User-site leak:** a separate Python 3.13 at `D:/Apps/python3.13.7` has a user site-packages (`%APPDATA%/Python/Python313`) that bleeds into `camea` and can shadow imports. **Every documented run uses `python -s`.**
- **BLAS/CuPy clash:** `np.corrcoef` **after** importing cupy caused a silent native crash (exit 127, no traceback) in this env. Relevant to any long-lived process that imports both. *(Corrected: the old "avoid `np.linalg.svd`" caveat no longer reproduces on numpy 2.4.6 — `np.linalg.solve(313×313)`, what `Placement.rigid` uses, is fine.)*
- **GPU denormal trap (already fixed in t27, do not undo):** GPUs flush float32 denormals to zero, so spectralign's divide-guard `+1e-40` becomes 0 → `0**(wht/2) = inf` → `0*inf = NaN`, smearing NaN across the whole correlogram (~3–4 % of comparisons before the fix). t27 uses `EPS32 = 1e-30` (`t27.py:80`). **CPU x86 does not flush denormals, so CPU and GPU need different epsilons.**
- **`cupy.random` is broken in the `camea` env** (missing cuRAND DLL). t27/t33 seed with numpy and `cp.asarray`, so they are unaffected — anything new must do the same.
- **The unsourced number:** `excluded.py:19` claims sharpness "declines smoothly 7.7 → 6.5" across the blurry run. **No code in the repo produces those figures**, and 15 standard focus measures failed to reproduce them. Treat that sentence as unsourced.
- **Excluding a good frame is not free, and nobody has measured it.** T27's sensitivity to removing an *arbitrary good* frame is unknown (only removing the 26 bad ones has been tested, and it helped a lot). Any toggle-exclusions UI should warn — and **must recompute `gaps()`**, or it will silently poison the next solve.
- **The near-duplicate pair 284/285** (mean abs diff 0.89 % of signal — essentially the same frame twice) is already excluded. A duplicate check is cheap and worth shipping but finds nothing new on 260620d.