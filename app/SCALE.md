# Scale & the pass-magnification scare - RESOLVED

> **2026-07-12. RULING: there is NO magnification difference between the passes. T33's 312/312 is
> honest.  is sound - do NOT rebuild it, do NOT add a scale term.**
>
> A calibration study measured the MEA electrode-grid pitch at 14.15 px in pass 1 vs 13.805 px in
> pass 2 and inferred a 2.5% magnification change. **That inference was wrong.** The grid pitch
> tracks **FOCUS**, not stage magnification. The tissue itself images at the same scale in both
> passes to within 0.1%. Four independent teams, all with positive controls that DID recover an
> injected 1.025 stretch.
>
> ⭐ The user's own remark - *"the focus of the lens can change from snapshot to snapshot"* - is what
> pointed at the answer. The 20 s pause at trial 166->167 was a REFOCUS.

## The ruling

**The 2.5 % difference is REAL in the electrode-grid pitch and FALSE as a magnification difference** — the passes image tissue at the same scale to within 0.1 %, so the "2.5 % magnification change" does not exist.

The four tests do not disagree. All four independently (a) reproduced SCALE.md's pitch numbers exactly (pass 1 ≈ 14.16 px, pass 2 ≈ 13.82 px, ratio 1.025, including the monotone within-pass-1 drift) and (b) measured the *tissue* scale and got 1.000–1.004. The broken step is the inference "a pitch ratio in pixels **is** a magnification ratio."

Why I believe the tissue, not the grid:

- **Positive controls.** Every estimator was fed a synthetically pre-scaled tile and recovered the injected 1.025 (returns of 1.0260, 1.0305, 1.0250, 1.0276). They are not blind to a 2.5 % stretch; it simply is not in the data.
- **Long-lever geometry.** Over the mosaic's 1741 × 3338 px extent a 2.5 % scale demands 44 px (x) / 83 px (y) of residual fan across cross-pass links. Observed residual spans: 12 px and 17 px. Fitted cross-pass scale = 1.0000 ± 0.0002 (three independent machineries). That is >80–150 σ from 1.025.
- **The direct test.** Rescaling pass-2 tiles by the claimed 1.025 and re-matching makes the correlation *worse* (0.836 → 0.773), 0/10 tiles improved. If the correction were right it had to help.
- **The pass-boundary dwell — the killer.** Trials 166 (pass 1) and 167–170 (pass 2) are a dwell on the *same field* (tissue NCC 1.000/0.999/0.998/0.996/0.984, translation < 1 px). Across those five frames the grid pitch goes **14.22 → 14.31 → 14.20 → 13.93 → 13.84** while the fitted tissue scale stays flat at 1.0010 ± 0.0001. Trial **167 is a pass-2 frame reading the pass-1 pitch (14.31)**. A pitch that swings 3.5 % in four frames, on a stationary stage, over unchanged tissue, is not magnification.

⚠️ **Two arguments in the original brief are unsound and must not be reused.** (1) "Median anchor NCC 0.815 is too high for a 2.5 % stretch" — false; an uncorrected 2.5 % stretch costs only ~0.10 of NCC, so 0.815 is perfectly survivable under it. (2) "Four measurements agree to 0.4 px" — near-worthless; all four are *global consensus* estimators, so a scale error biases them identically rather than making them disagree. The right answer was reached, but the published reasons were weak. The real evidence lives in the *within-method* per-sample spread, which nobody had looked at.

## Is 312/312 still safe?

**Yes. T33's 100 % is honest, and I confirmed it with the canonical scorer** (`analysis/benchmark/score.py`, `robust_align` imported, not reimplemented): 312/312, median 1.82 px, max 9.94 px, residual rotation −0.007°.

- **No radial fan.** corr(distance, radial error) = −0.244 — the *wrong sign* for a scale error. d(radial)/d(dist) = −0.0014 (implied scale −0.14 %). Full affine build→GT: sx = 1.00086, sy = 1.00120.
- **The 10 px bar cannot hide 2.5 %.** Inject a real s = 1.025 into T33's pass-2 tiles and re-score: **176/312 = 56.4 %**, max error 46.7 px. s = 1.010 → 89.4 %. The largest scale error 10 px can mask is ~0.5 %.
- **The 9.9 px worst tile is already explained.** Trial 127 (pass 1) sits inside the ~12 px *local* warp around pass-1 tiles 126–130 that `merge_passes.py` records verbatim as `known_local_disagreement`. It is at only the 70th percentile of distance from centre.
- Error magnitude does grow with distance from the mosaic centre (corr +0.505; 1.37 → 3.93 px by quintile), but radial and tangential grow *together* — that is isotropic random-walk accumulation of registration noise, not a directed scale fan.

**What the grid-pitch measurement was actually seeing:** a real periodicity in the pixels whose *apparent period tracks focus, not stage magnification.*

- It is not a peak-fit artefact of blur: in pass 1, corr(log grid-SNR, pitch) = +0.017, and the sharpest-grid quartile reads the same 14.17 as the blurriest.
- It is not position-dependent optics: across 127 coincident pass-1/pass-2 pairs in 18 mosaic cells, pass 1 reads **+0.39 px coarser than pass 2 at the same chip location, in every cell**. Both passes at the same place must read the same value if pitch were a function of position. They do not.
- It is not a camera-fixed pattern: a phase-rigidity test says the lattice is **chip-rigid** in both passes (median |phase error| 24° / 16° chip-fixed vs 115° / 112° camera-fixed).
- It **is** locked to focus: the unlogged 20 s pause at 166→167 was a refocus, and the pitch settles 14.3 → 13.8 over the next four frames on a stationary stage; pass 1's monotone 14.02 → 14.30 ramp is a focus drift over the pass. Pass 1's grid is also ~30–100× weaker (ACF ripple 0.06 vs 0.49). The physical mechanism is most likely defocus of a periodic object under partially coherent illumination changing the *observed fringe period* (Talbot-like self-imaging), but **I did not confirm the mechanism** — and one test found that a different, equally reasonable estimator (radial peak/background on co-located patches) puts pass 1's strongest peak at 13.838 px, *identical to pass 2*. Two defensible estimators on the same pass-1 pixels disagree by 2.5 %. **Pass 1's pitch number is not a trustworthy physical measurement.**

## What it means for the ground truth

**`analysis/ground_truth/` is sound. Do not rebuild it. Do not add a scale term.**

`pass1 = pass2 + (−133.5, −205.1)` at scale 1.000 is correct to within ~0.02 %. A translation-only tie reproduces independently at median residual 1.5–1.8 px, max 11.2 px over the whole 3800 px mosaic — which is exactly the noise floor T33's 9.9 px worst tile sits against.

The only real residual is a ~0.1 % anisotropy/skew (+0.16 % in x, −0.06 % in y; slopes +0.0012 and −0.0007, distinguishable from the within-pass controls at 0.0000). That is worth ~2 px across the full mosaic — 25× smaller than the claim, and far inside tolerance. Not actionable.

*Optional, not required:* fitting the small real scale (s ≈ 1.0025) to T33's pass-2 residuals explains 62 % of their variance and drops T33's worst tile from 9.53 → 6.33 px. Nice headroom under a 10 px bar; purely cosmetic.

## What it means for the app

**Write ONE scale value for both passes, or write none.** The magnification is confirmed common across the passes to within 0.1 % (three independent estimates: 1.0000, 0.99934, 1.0037). **One scale bar on a figure spanning both passes is safe.** A *two-scale* figure would be actively wrong.

**But the absolute number is not yet safe to write.**
- **1.237 µm/px (pass 1) is wrong — delete it.** It is 17.5 µm ÷ 14.16 px, which is the broken inference.
- **1.268 µm/px (pass 2) is *probably* right** — pass 2's grid is in focus, 78× SNR, flat, position-independent — but it rests on the *same* inference that we just proved can be corrupted by focus. I can show the inference fails by 2.5 % in pass 1; I cannot show it is exact in pass 2.

**Recommendation for the exporter:** either (a) leave the TIFF resolution tags **unset** for now, or (b) write 1.268 µm/px for *both* passes and label it explicitly as provisional (±3 % systematic). Do not ship a per-pass scale.

**The clean fix is cheap:** calibrate µm/px from the **stage**, not the grid. The stage commanded known micrometre moves between trials; measure the corresponding pixel displacement (already done implicitly — that's the "long-lever" machinery). Same stage in both passes, no focus dependence, no periodic-object optics. That gives an absolute µm/px with no reliance on the electrode lattice, and it settles the scale bar for good.

## Confidence, and what would still change my mind

| Claim | Confidence |
|---|---|
| No magnification difference between passes (relative scale = 1.000 ± 0.002) | **Very high.** Four independent teams, mutually independent estimators, all with positive controls that *did* recover an injected 1.025. |
| T33's 312/312 is real, not a tolerance artefact | **Very high.** Re-scored with the canonical scorer; an injected 1.025 collapses it to 56 %. |
| Merged GT needs no scale term | **Very high.** |
| The grid pitch difference is real in the pixels | **Very high** — it reproduces on four independent FFT implementations. |
| The pitch difference is caused by focus | **Medium.** Strongly implied by the 166→170 dwell, but the mechanism is not proven and pass-1's own pitch estimate is estimator-dependent (13.84 vs 14.15 on the same pixels). |
| 1.268 µm/px is the right absolute scale for both passes | **Low–medium.** Untested against a non-grid reference. |

**What would change my mind on the ruling:** essentially nothing short of showing that *all four* scale estimators are simultaneously blind to a 2.5 % stretch — which their positive controls directly refute — or that the tissue signal used for registration is somehow not the tissue. I do not consider this open.

**What is still open, and the experiment that closes it:**
1. **Absolute µm/px** — calibrate from commanded stage displacement in µm vs measured pixel displacement, independently per pass. If the two passes return the same µm/px (they must, given scale = 1.000), that is the number to write into the TIFF, and the electrode grid is retired as a calibration source.
2. **The pitch mechanism** — image the *same* field through a deliberate focus sweep and plot apparent lattice pitch vs focus. If the pitch moves with focus while the tissue scale does not, the story is closed and `SCALE.md` can be rewritten. This is a 20-minute acquisition and it is the only thing standing between "we know it isn't magnification" and "we know what it is."

Neither of these blocks the mosaic, the ground truth, or T33.