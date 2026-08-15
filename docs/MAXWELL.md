# MAXWELL.md — the MaxWell HD-MEA, and what it means for Camea

> **What this is.** A reference about MaxWell Biosystems' high-density microelectrode arrays — the
> chips that produced every `data.raw.h5` under `data/` — written because the author corrected a
> design question on 2026-08-14 and the correction turned out to be the whole shape of the problem:
>
> > *"not all electrodes can be used at the same time on an MEA chip. of the neurons that are being
> > used not all of them are near neurons."*
>
> He is right on both halves, and this file evidences both: the **routing limit** from MaxWell's own
> documents, the MaxLab Live manual, the chip's design paper and a peer-reviewed methods section; the
> **silence** from 33 of his own recordings, measured three times over by independent passes, plus
> four published measurements of how far an extracellular spike actually travels.
>
> ⚠️ *Evidenced*, not proved — that routed pads with no spikes are the ordinary case is **measured**,
> but the step from "this pad heard nothing" to "no cell was near it" is an **inference** (§1.4). §1.2
> now gives it a sourced physical basis it did not have on 2026-08-14; §8.1 says what is still missing.
>
> **Who it is for.** Anyone about to draw a chip, colour a pad, count a neuron, or word a tooltip.
> Read §1 and §7 before you write a line of MEA UI. Read §4 before you believe an "active electrode"
> number, including one MaxLab Live printed itself.
>
> ⛔ **THIS FILE IS A REFERENCE FOR HUMANS. NOTHING IN IT MAY BECOME A CONSTANT IN `src/camea/` OR
> `web/src/`.** Not 26,400, not 1,020, not 1,024, not 17.5, not 0.1 Hz, not 20 µV, not 6.294 µV, not
> 35 µm, not "0–62% silent". Camea derives everything from the file in front of it — that is invariant
> I1 and **R45.1** (*"the mapping is measured, never assumed"*), and the measurements below are the
> **argument for** deriving, not a table to hard-code. §7.4 says exactly where the line is and why
> the tempting exception is not one.
>
> ⚠️ **Cite R45.1, not R45.8, for that rule.** R45.8 is the *amendment* that goes the other way — it
> is what **permits** 220 × 120 and 17.5 µm to exist in `core.electrodegrid.DeviceSpec`, once the
> user has asserted the whole chip is in frame. A reader sent to R45.8 looking for "derive, never
> assume" finds the one ruling that licenses the opposite.

**Provenance legend — every claim below carries one, inline.** They are not interchangeable:

| Label | Means |
|---|---|
| *(vendor)* | Stated by a MaxWell document — a product page, the MaxLab Live manual, or the MaxLab Python API docs. Quoted, with the page. |
| *(paper)* | Measured in a peer-reviewed publication. Named, with a DOI or PMCID, **and with the hardware and preparation it was measured on**, because most of it is not a MaxOne. |
| *(measured here)* | Re-derived from files under `data/` for this document, read-only. Reproducible in under a minute each — see "how to re-derive" below. |
| *(community)* | An open-source reader, a maintainer, or a vendor engineer in a public issue thread. Named, with the URL. |
| *(inferred)* | A reading laid on top of evidence. Might be wrong. ⛔ Never quote one as a measurement. |
| *(unverified)* | Someone said it and nobody in this chain could check it. Treat as a lead, not a fact. |

**How the measurements were made.** Read-only throughout, on `d:\Projects\Camea\data\` (the 35 GB
mirror — ⛔ never written to), with `h5py`, `numpy`, `scipy` and `src/camea/core/mearecording.py`.
**Five independent research passes** measured the corpus; a sixth adversarial pass re-derived every
number from scratch rather than re-running the earlier scripts. Only numbers that reproduced survive
here. Claims that did not reproduce were dropped and the notable ones are named in §8.14 so nobody
re-derives them.

⚠️ **How to re-derive, and why you should not trust this file alone.** Every *(measured here)* number
costs seconds: open the file with `h5py`, read `data_store/dataNNNN/settings/mapping` and
`.../spikes`, and count. The adversarial pass found that the errors hardest to catch were **miscounts
of the author's own corpus wearing the `measured here` label** — "22 Network recordings" when there
are 26, "12 recordings with no silent pad" when there are 8, an arithmetic identity asserted rather
than evaluated. Those read as the most trustworthy line in the document and are the ones a future
session cannot check by reading. **If a number here matters to a decision, spend the minute.**

**Corpus, once, so §4 does not have to keep restating it** *(measured here)*: 33 `data.raw.h5` files
— **7 ActivityScan + 26 Network** — over **3 sessions** (260529: 15 files, 260620: 12, 260801: 6) and
**4 plates** (P002137, P002731, P003658, P003693). ⚠️ Run `000065` is absent from the mirror. Between
them the 33 files hold **57 routing configurations** and **49,367 mapping rows** (26,400 from the
seven scans + 22,967 from the 26 Network runs — the two independently-measured totals add up exactly,
which is the cheapest sanity check in this document).

---

## 1. ⭐ THE ANSWER: NOT ALL ELECTRODES AT ONCE, AND NOT ALL OF THEM NEAR A NEURON

Two separate facts. They compound, and confusing them is how a chip map ends up lying.

### 1.1 The routing limit — the chip has far more pads than ears

A MaxOne chip carries **26,400 electrodes**, each **11.5 × 11.5 µm**, at **17.5 µm** centre-to-centre
over a **3.85 × 2.10 mm** sensing area — **3,265 electrodes per mm²**, sampled at **20 kHz per
channel**, typical noise **2.2 µVrms per chip** *(vendor, verbatim from the MaxOne product page's spec
table)*. The geometry is independently confirmed in the chip's design paper and in a peer-reviewed
device paper — 26,400 electrodes, 3.85 × 2.10 mm², 17.5 µm pitch *(paper: Ballini et al. 2014; Müller
et al., Lab on a Chip 15:2767–2780, 2015 — "26 400 microelectrodes arranged at low pitch (17.5 µm)
within a large overall sensing area (3.85 × 2.10 mm²)")*. ⚠️ The **3,265/mm² density figure is
vendor-only** — it is not in Ballini's abstract, and an earlier draft of this file wrongly credited it
there.

It can listen to **1,020** of them at a time. Four independent vendor statements say so:

* *(vendor)* the product page's spec table — **"Number of recording channels: 1'020"**;
* *(vendor)* the MaxLab glossary — *"Around the periphery of the electrode array, there are 1020
  readout channels located which can be connected to arbitrary subsets of electrodes"*;
* *(vendor)* the MaxLab Live manual §3.1.1 — *"at most 1020 electrodes can be selected in a single
  configuration"*;
* *(vendor)* the MaxLab tutorial — *"The maximum allowed number of Recording Electrodes is 1020,
  corresponding to the number of recording channels"*.

The design paper counts **1,024** readout channels on the die *(paper: Ballini et al., IEEE J.
Solid-State Circuits 49(11):2705–2719, 2014, DOI 10.1109/JSSC.2014.2359219 — the title itself is "A
1024-Channel CMOS Microelectrode Array…")*, and MaxLab's own `group_define()` documents channel
values as *"range from 0 to 1023, which is the maximal number of recording channels"* *(vendor)*.

⭐ **The corpus resolves the 1,020-vs-1,024 gap to four specific channel ids.** Across all 57
configurations of all 33 files the mapping tables use exactly **1,020 distinct channel ids spanning
0–1023**, and ids **360, 361, 362 and 363 never appear in any mapping** — nor, and this is the
sharper half, **in any `spikes` table either** *(measured here)*. ⇒ *(inferred)* they are not
amplifiers that merely go unrouted; they appear not to exist as usable channels at all. **What they
are for is still unknown** (§8.2). The largest routed set anywhere in the mirror is **1,018**
electrodes (`000068`), the smallest **177** (`000049`) *(measured here)*.

⭐ **So one recording hears at most 3.9% of the chip, and at least 96.1% of the pads are not connected
to anything.** The 96.1% floor is general — forced by the 1,020-channel ceiling against 26,400 pads
*(vendor + arithmetic)*. The **upper** end is a property of this corpus, not of the chip: across the
26 Network recordings the routed set runs **177 to 1,018** electrodes, i.e. **0.67%–3.86%** routed and
**96.14%–99.33%** unconnected *(measured here)*. ⚠️ A configuration routing fewer pads would push that
further; nothing bounds it from above except zero.

**Why the limit exists — and this is now sourced, where an earlier draft of this file inferred it.**
The amplifiers are not under the electrodes. A **switch matrix** sits between them:

> *(vendor, verbatim, mxwbio.com/our-technology)* "The Switch-Matrix (SM) approach intelligently
> routes any selected set of electrodes to readout circuits via programmable switches." … "In this
> architecture, the electrodes and amplifiers are physically separated, enabling a more powerful
> amplifier design that minimizes noise." … "In MaxWell Biosystems HD-MEAs (MxW HD-MEAs), any of the
> 26,400 electrodes can be routed to up to 1,020 readout channels."

> *(paper, verbatim)* "The switches are used to wire electrodes to front-end amplifiers placed outside
> of the array, where sufficient area for the implementation of low-noise amplifiers is available."
> — Obien, Deligkaris, Bullmann, Bakkum & Frey, *Revealing neuronal function through microelectrode
> array recordings*, Front. Neurosci. 8:423 (2015), PMC4285113. ⚠️ **Scope:** that sentence is a
> statement about switch-matrix arrays as a class, not a MaxOne measurement — though the authors
> include the people who designed this chip lineage.

⇒ 26,400 low-noise amplifiers will not fit under an 8.09 mm² array; 1,024 sitting around its edge
will. The experimenter chooses the subset at acquisition, and nothing about that choice is recoverable
from biology — it is a decision, recorded in the file.

⚠️ **And not every subset is even possible.** *(vendor, verbatim, MaxLab Live manual v25.1, printed
page 69 — this sentence occurs exactly once in the 161-page manual):*

> "the number of selected electrodes may decrease after routing (not all selections of electrodes can
> be routed: the switch matrix beneath the electrode array, which connects electrodes to amplifiers,
> can assume only certain configurations)."

restated for the Stimulation assay on p.86: *"due to routing constraints, it is possible that certain
specified electrodes cannot be used for recording"* *(vendor)*. So the user draws a region, presses
**Route**, and gets back *fewer electrodes than they asked for* — the software says so on screen, and
the file records only the outcome. §2.3 has what that costs.

⭐ **How much freedom the router actually has, from the one peer-reviewed statement that quantifies
it** *(paper, verbatim, Duru, Küchler, Ihle, Forró, Bernardi, Girardin, Hengsteler, Wheeler, Vörös &
Ruff, "Engineered Biological Neural Networks on High Density CMOS Microelectrode Arrays", Front.
Neurosci. 16:829884, 2022, PMC8900719)*:

> "An almost arbitrary combination of up to 1,024 electrodes can be recorded from simultaneously.
> Electrode patches of 23 × 23 electrodes can almost always be routed completely and used as a dense
> recording site. In case larger electrode patches are selected, the number of routed electrodes is
> maximized using a routing algorithm that aims to maximize the number of electrodes that are
> connected via the switch-matrix to the 1024 available amplifiers."

and, from the same paper, the only **published routing yield** this document could find: of 760
selected microelectrodes, *"685 were successfully connected to the amplifying stage for signal
acquisition (90.1 %)"* *(paper)*. ⚠️ **Note what is and is not said.** 23 × 23 = 529 electrodes is a
*lower bound* on what the router can do densely — it is the size that "can almost always" be routed
completely. **Nothing in any source states what fraction of a larger dense patch routes**, and an
earlier draft's conclusion that a dense patch "cannot use the whole channel budget" was dropped as
unsupported (§8.14).

### 1.2 ⭐ The silence — how far can a pad actually hear?

The second half of his correction, and the one that decides the wording of every tooltip. **This is
the section that changed most since 2026-08-14**: the earlier draft said flatly *"NO DETECTION RADIUS
IS QUOTED HERE"* because no source had been retrieved. Four now have been.

An extracellular electrode does not "see" a neuron. It measures the voltage the surrounding medium
carries away from a firing cell, and that voltage falls off steeply with distance. A pad detects a
spike only when some part of a neuron — soma, axon, a large process — is close enough that its
potential clears the detector's threshold (§5.2). Everywhere else the pad measures the culture's noise
floor and reports nothing.

⭐ **The numbers, each with the hardware and preparation it was measured on, because none of them is a
MaxOne measurement:**

| Quantity | Value | Source, and what it was measured on |
|---|---|---|
| Somatic spike amplitude at the peak electrode | **0.02–1.7 mV** | *(paper)* Viswam et al., Front. Neurosci. 13:385 (2019) — **cortical cell cultures** |
| How fast a somatic signal falls off | *"they fall off quickly at 20 up to 100 µm radius from the peak (20% of the peak)"* | same |
| Axonal spike amplitude | **1–50 µV** | same |
| Axonal spatial extent | *"very localized within 20 to 30 µm along the axonal-arbor structure"* | same |
| Amplitude vs distance from the axon initial segment | strong dependence **only within 100 µm** (~350 µV average decrease over that 100 µm); **no strong decrease from 100 µm out to 1,400 µm** | *(paper)* Radivojevic et al., eLife 6:e30198 (2017) — rat cortical culture, **11,011-electrode 17.8 µm array with 126 simultaneous channels**, NOT a MaxOne |
| One neuron's full electrical image, axons included | spread over **1,200 electrodes** | same |
| Share of electrodes that pass a spike-detection constraint and are looking at a **soma** vs a **neurite** | **86% somatic / 14% neuritic**; median somatic spike-triggered-average amplitude **−171.46 µV** against **−73 µV** neuritic; 23 of 29 representative neuritic electrodes were **≥100 µm from the nearest soma** | *(paper)* Deligkaris, Bullmann & Frey, Front. Neurosci. 10:421 (2016) — dissociated rat cortical neurons E16–18 at 14–58 DIV, **11,011-electrode hexagonal 17.8 µm array**, NOT a MaxOne |

⚠️ **Read the Viswam and Radivojevic rows together or you will misuse both.** "≈100 µm" is the range
at which a signal is still *visible in a trace*, not the range at which a **detector fires**. A
somatic signal is already down to 20% of its peak by 20–100 µm; an axonal one is 1–50 µV to begin
with. ⇒ *(inferred, but it is the natural reading of the two)* **the radius over which a pad reliably
crosses a 5σ threshold on a soma is tens of micrometres, not hundreds** — and the corpus agrees:

🔴 ⭐ **MEASURED HERE, and it is the single best in-corpus answer to the author's point.** On
`260801/P002731/Network/000688` — the one recording whose routed set was **chosen by the software from
a prior activity scan**, i.e. 33 clusters of pads deliberately centred on places where a cell had
already been heard — firing rate relative to each cluster's own best pad, binned by distance from it:

| Distance from the cluster's peak pad | pads | median rate, relative to that peak | share of pads with **zero** spikes |
|---|---|---|---|
| 0–20 µm | 157 | **0.586** | 8% |
| 20–40 µm | 395 | **0.002** | 28% |
| 40–60 µm | 209 | 0.002 | 25% |
| >60 µm | 221 | 0.003 | 23% |

⚠️ The nearest bin's exact median depends on whether the peak pad itself is counted (an earlier pass
excluded it without saying so and reported 0.23 instead of 0.586). **Quote the pattern, not the
first-bin figure**: the collapse between the first and second bin is ~300×, and it happens over
**20 µm**.

⭐ **That is the physical answer to "why is a routed electrode usually silent", and it is measured on
his own chip:** past about 20 µm from the cell, the cell is gone. At a 17.5 µm pitch, "20 µm" is
roughly *one electrode over*.

**The complementary corpus measurement — how far one spike's footprint spreads across pads.** This is
a different quantity from the detection radius and must not be swapped for it:

🔴 In `260529/P002731/Network/000047` — 998 pads routed in dense clusters at 17.5 µm — **85.6% of
spikes have another spike within ±1 ms on a pad within 17.5 µm; 89.0% within 35 µm; 90.4% within
70 µm.** Under a control that shuffles pad positions among the same channels (same times, same counts)
those fall to **4.0% / 13.4% / 28.4%** *(measured here)*. `000042` gives **91.3%** real against ~8%
shuffled at 35 µm. On `000688` the same test gives **87.8%** real against **10.8%** shuffled, an
**8.1×** excess *(measured here, independently, with a different shuffle seed)*.

* ⭐ **One spike lands on several neighbouring pads.** Going from 17.5 µm to 35 µm adds 3.4 points;
  going on to 70 µm adds only 1.4 more. The footprint is mostly spent by **35 µm** *(measured here)*.
  ⚠️ *(inferred, and the corpus cannot settle it)*: that a cluster of near-simultaneous detections is
  **one neuron** is the standard reading, but this measurement cannot separate one cell's footprint
  from two coupled cells or a propagating axon. ⛔ **Do not write "neurons" where you measured pads.**
* ⭐ **Whether you can see a footprint at all is a routing choice, not a biological one.** In **19 of
  the 26** Network recordings **no two routed pads are adjacent at 17.5 µm at all** — they are sparse
  lattices at 35 µm or 87.5 µm *(measured here)*. On `000691`/`000692` the coincidence rate within
  35 µm and within 70 µm is **0.0%**, and it is **structurally impossible** for it to be anything
  else. A "no local structure" verdict on those files would be a statement about the experimenter's
  spacing, not about the culture. ⇒ On those 19 runs each pad is a **near-independent sample**, and a
  silent one means only that no cell sat under that particular 11.5 × 11.5 µm pad.

**And the cells move.** *(paper)* Habibey et al., Front. Neurosci. 16:951964 (2022), on a **MaxOne**:
904 tracked hiPSC-derived neurons had an average cumulative displacement of **224.00 ± 10.10 µm over
two months**. ⇒ A chip map is not a map of where the cells are. It is a map of where spikes were
detected, in this window.

### 1.3 What the silence actually looks like in his data

⭐ **Across the 26 Network recordings, the share of ROUTED pads that recorded exactly zero spikes runs
from 0.0% to 61.8%** *(measured here)*. **Eight** recordings have not a single silent pad; **eight**
sit between 0.1% and 2.3%; **ten** sit between 7.5% and 61.8%. Median across the 26 is **0.97%**,
mean **8.8%**. The worst has **625 of 1,012** silent.

⭐ **A softer and more useful cut than "exactly zero": how many routed pads fire at 0.1 Hz or less.**
Median across the 26 Network runs **56.6%**, range **26.6%–99.5%** *(measured here)*. ⇒ **In the
median recording, more than half the routed pads are effectively silent even though most of them did
fire once or twice.**

🔴 **And in the vendor's own screening assay — the ActivityScan, whose entire job is to find where the
cells are — 49.3% to 87.8% of the scanned pads heard nothing at all in their 30-second window**
*(measured here, all 7 scan files, on the union of each scan's configurations: 76.2 · 53.0 · 49.3 ·
87.8 · 76.1 · 81.7 · 87.4%)*. Per configuration the spread is wider still, **45.1%–97.4%**. On
`260801/P002731/ActivityScan/000687`, **87.41% of the 6,600 scanned pads recorded not one spike**, and
MaxLab Live's own summary for that run reads **"Active Area: 6.47%"** *(measured here; the 6.47% is the
vendor software's own number, read out of the run's `.mxassay` sidecar)*.

⇒ ⭐ **A routed electrode with zero spikes is the ordinary case in MaxWell's own assay, by MaxWell's
own numbers** *(measured here)*. It is not a dead pad, not a broken channel, not a failed experiment,
and not evidence of a quiet culture.

**And the literature says the quiet part out loud** *(paper, verbatim)*: "Often, such an approach is
sufficient to observe biological phenomena of interest, **as typically not all electrodes exhibit
activity**." — Obien et al. 2015, in the section on switch-matrix routing. ⚠️ It is a subordinate
clause in a review, not a measurement; an earlier pass quoted it as a standalone assertion.

### 1.4 ⚠️ "Heard nothing" → "no cell was near it" is an INFERENCE

*(inferred — the usual reading, the one §1.2 now gives a sourced physical basis, and the one the UI
ships.)* That the silence is **ordinary** is measured, corpus-wide and in the vendor's own scoring;
its **cause** in any individual case is not.

The alternative this document cannot exclude is a cell that **is** near the pad but whose spikes never
clear **this recording's** threshold. §5.2: the bar is 5× a per-recording noise estimate, so it is not
a fixed voltage and it moves between files and between channels. Three measurements make that
alternative concrete rather than theoretical:

* 🔴 **"Silent" is a statement about the WINDOW, and it saturates at different rates** *(measured
  here)*. `000688` falls **76.0% zero at 1 s → 43.3% at 30 s → 28.2% at 120 s → 23.0% at 180 s**.
  `000692` falls **82.2% at 30 s → 52.6% at 120 s → 41.2% at 180 s → 24.6% at 300 s**. But `000690`
  **plateaus**: 35.0% at 30 s, 28.7% at 60 s, and **28.7% still at 300 s**. ⇒ Two of the three were
  still recruiting pads when the recording ended; one was not. ⛔ **A "percent active" figure without
  its window length beside it is meaningless.**
* 🔴 **Move the bar and the picture inverts.** An arbitrary amplitude floor of **20 raw field units**
  (⚠️ = 20 µV under Reading B, ≈126 µV under Reading A — §5.1) takes `000042` from 18.2% silent to
  **93.3%**, `000688` from 23.0% to **94.0%**, `000047` from 7.5% to **79.0%** — while barely touching
  `000690` (28.7% → 32.4%), `000691` (61.8% → 62.5%) or `000692` (24.6% → 24.8%) *(measured here)*.
  ⛔ **That number is arbitrary and illustrative and must never enter the app** (§7.4). Its whole job
  is to show that "zero spikes" is not a sharp boundary.
* 🔴 **The same 1,012 pads, 2.75 minutes apart: 625 silent, then 249** — and every one of the 376 that
  changed changed in the same direction (§4.4). Silence is a property of the *recording*, not of the
  electrode.

⭐ **That is exactly why `SILENT_MEANING` says "most likely", and why it must keep saying it.**

⛔ **So no Camea surface may word it as a fault.** `web/src/features/mea/activityScale.ts ::
SILENT_MEANING` is the single sentence that says what it means, and it is already right:
*"no spikes — most likely no neuron near this pad"*. Keep it in one place; keep the shape different
from the ramp (`ChipMap` draws a hollow ring) so it can never be misread as a dim colour.

---

## 2. THE ARRAY AND THE SWITCH MATRIX

### 2.1 The layout, and why Camea derives it instead of writing it down

*(vendor / paper)* 26,400 platinum electrodes, **220 wide × 120 tall**, 17.5 µm pitch, 3.85 × 2.10 mm,
20 kHz per channel, 10-bit ADCs, 32 on-chip stimulation units *(paper: Ballini et al. 2014)*.
Electrodes are numbered row-major from the top-left:

⛔ **The rule is written with `stride` and `pitch` as symbols, deliberately — do not substitute the
numbers back in.** This is the form `core/mearecording.py` uses, and both symbols are **read out of
the file** (`derive_stride`, `derive_geometry`), never assumed:

```
electrode = ey * stride + ex        ex = x_um / pitch
                                    ey = y_um / pitch
```

On every file in this mirror those resolve to `stride = 220` and `pitch = 17.5 µm`, giving
`ex ∈ [0, 219]` and `ey ∈ [0, 119]` — **derived on each open, never typed.** ⚠️ A MaxTwo, a future
array, or a partially-populated chip may resolve differently, which is the entire reason the symbols
stay symbols. ⛔ If you came here to grep the numbering rule, copy the block above, not this
paragraph.

*(vendor, verbatim, MaxLab Live manual §3.1)*: *"The origin (zero-position) is in the top left corner
of the array… The numbering starts with 0 and from the top left corner. The number increases by one
moving rightwards. At the end of the row, the numbering continues with the leftmost electrode in the
subsequent row below."* The MaxLab Python API's `Config` constructor says the same for its
configuration string `<channel>(<electrode>)<X>/<Y>`, adding that X and Y are **µm** and that
*"The position `<X>=0` and `<Y>=0` represents the top left corner of the array"* *(vendor)*.

⚠️ **220 × 120 is not printed anywhere in the manual.** It is forced arithmetic — 3.85 mm / 17.5 µm =
220 and 2.10 mm / 17.5 µm = 120, and 220 × 120 = 26,400 exactly — and it is stated in the literature
*(paper: Habibey et al. 2022, "26,400 electrodes arranged in a 120 × 220 configuration")*. An earlier
draft attributed it to the manual; that was wrong.

⭐ **The rule is verified exhaustively on his own files: `electrode == round(y_µm/17.5) × 220 +
round(x_µm/17.5)` holds for 49,367 of 49,367 mapping rows — 100.0000%, zero residual — across 33
files, 57 configurations and 4 different chips** *(measured here)*.

⭐ **You can also check it by eye in one line.** The routed-electrode list in
`260801/P002731/Network/000689`'s `.mxassay` sidecar begins, literally:

```
0(9545)1487.5/752.5;1(10885)1837.5/857.5;…
```

`9545 = 43×220 + 85`, and `85×17.5 = 1487.5`, `43×17.5 = 752.5`. Second entry: `10885 = 49×220 + 105`,
`105×17.5 = 1837.5`, `49×17.5 = 857.5` *(measured here — the sidecar text is measured, the arithmetic
you can do yourself)*.

⛔ **None of those numbers is written down in Camea, and none may be.** `derive_geometry()` in
`src/camea/core/mearecording.py` solves `pitch × electrode − stride × y = x` by least squares over
every routed electrode and then **verifies it exactly**; a file that fails the check is **refused**
rather than guessed at. That is **R45.1** and it is not negotiable — a silently transposed chip pairs
every electrode with the wrong neuron and nothing on screen would look wrong.

⭐ **The corpus is the evidence that deriving costs nothing.** Over all **57 routing configurations**,
`derive_geometry()` returns `stride = 220` **exactly**, every time, and never once raised
*(measured here)*.

⚠️ **What is proven and what is merely observed, because the distinction is load-bearing.** The
*stride* is proven — the identity is checked electrode by electrode. The **120-row height** and the
**1,024-channel ceiling** are only *observed maxima* over 57 configurations (max `ey` = 119, max
channel id = 1,023); a row 120 that no configuration ever routed would be invisible to every file
here. ⛔ Do not let "the corpus proved 26,400" become an argument for a constant. It proved the
numbering rule.

⚠️ **And "a scan file will always show you the full extent" is false.** Exactly two files in the
mirror reach both `ex = 219` and `ey = 119` on their own: the Sparse7x scan `000687` and — a Network
run — `000047`. **All six Sparse4x scans stop at `ex = 218` / `ey = 118`** *(measured here)*. ⇒ Any
"is this the whole chip?" test must look at the recorded extent it actually has, never branch on
assay type.

⚠️ **`pitch = 17.5` is a computed float, not an exact equality.** The 57 configurations give 20
distinct float64 values spanning `17.49999999999954` to `17.50000000000014` *(measured here)*. A
future session re-running the derivation and seeing 20 values has not found a bug.

### 2.2 What the file records about the switch matrix

Each Network recording folder carries a `.mxassay` sidecar next to `data.raw.h5`, and inside its
`electrodes` key is the literal switch-matrix bitstream as a base64+gzip payload *(measured here)*.
Decompressed, `260801/P002731/Network/000688` gives **66,713 bytes / 397 lines**:

* **139** × `cmdSelWL <n>`, with `n` running 0…138 — word-line select;
* **129** × `cmdFillBL1 <bits>` and **129** × `cmdFillBL2 <bits>` — bit-line fill, every bit string
  exactly **240** characters of `0`/`1`;
* no other command types.

`000689`, `000691` and `000692` also decompress to 66,713 bytes; `000690` to 65,705 bytes (139 / 127 /
127) — so the payload length is configuration-dependent *(measured here)*.

⚠️ **The semantics of BL1 vs BL2 are inference and are not vendor-documented.** ⛔ Do not build on the
interpretation. The useful fact is only that the *routing itself* is a hardware program, which is why
"not all selections can be routed" is a real constraint and not a software preference.

⛔ **The ActivityScan sidecar has no such payload** — no `electrodes` key at all, only `configs`,
`record_time` and `spike_only`, because that assay references saved `.cfg` files by path
*(measured here)*.

⭐ **The HDF5 itself also records the achieved configuration, for every Network run.**
`assay/inputs/electrodes` is a JSON string of the form `{"electrodes":{"<well>":[id, id, …]}}`, keyed
by well. Parsed properly and compared against the union of that file's `settings/mapping`, the two
sets are **identical in all 26 Network files** — zero dropped, zero added *(measured here)*.
⚠️ **Trap:** a naive integer-scrape of that string picks up the well key `"0"` as a 27th electrode id
and reports a spurious one-electrode mismatch in every file. Parse the JSON. The 7 ActivityScan files
carry no `electrodes` field at all — they carry `assay/inputs/configs` naming a preset instead.

### 2.3 Routing yield: two different reasons you get fewer pads than you drew

The routed sets in this corpus sit on regular lattices that are only partly filled:

| Recording | lattice spanning its bbox | routed | fill | channel slots used (of the 1,020 ceiling) |
|---|---|---|---|---|
| `260801/P003658/Network/000690` | 32 × 29 at step 2 (35 µm) = 928 | 726 | 78.23% | 726 — **294 unused** |
| `260801/P002731/Network/000689` | 41 × 33 at step 2 (35 µm) = 1,353 | 1,015 | 75.02% | 1,015 |
| `260801/P003693/Network/000691`, `000692` | 44 × 23 at step 5 (87.5 µm) = 1,012 | 1,012 | 100.00% | 1,012 |

*(measured here)*

⚠️ ⛔ **The denominators are INFERRED, not measured, and this is the most important caveat in §2.**
Nothing in these files records what the experimenter *requested*. The `.mxassay` stores a QVariant
explicitly typed `RoutedElectrodes` whose list is byte-for-byte identical to the HDF5
`settings/mapping`, and `assay/inputs/electrodes` matches the mapping exactly in **all 26** Network
files (§2.2) — every recorded artefact stores the **outcome**, never the request *(measured here)*.
⇒ **"The routing lost 25% of what he drew" is a story, not a measurement, and a "routing success rate"
cannot be computed from any file in this mirror.** The only routing yield this document can offer is a
published one: **90.1%** (685 of 760) in Duru et al. 2022 *(paper, §1.1)*.

⭐ **The two shortfalls above do have different available explanations, which matters if you ever
reason about them.** `000689`'s hypothetical full 1,353-pad lattice exceeds the 1,020-channel ceiling
— no amount of switch-matrix luck could have routed it, and it in fact used 1,015 slots. That is the
**amplifier budget**. `000690` is the only candidate for a **switch-matrix** loss: it sits well under
the ceiling and left 294 slots unused *(inferred, from measured slot occupancy)*.

⚠️ **A third explanation is live for `000690` and was wrongly excluded by an earlier pass.** Its
occupancy map alternates in the upper-left (every 2nd comb point = every 4th electrode = 70 µm) and is
solid in the lower-right. The earlier argument — "no hand tool draws a region that alternates between
35 and 70 µm" — is contradicted by the manual: the **Sparse 1000** tool *"drag[s] to select 1000
electrodes sparsely distributed across the chosen area"* *(vendor, Table 7)*, and a fixed budget spread
over an area that does not divide evenly produces exactly that mixed spacing. A fourth candidate — an
activity threshold — was **tested and rejected**: in `000689` the skipped in-box pads were slightly
*more* active in the plate's prior scan than the routed ones *(measured here)*. ⇒ **Three live
explanations, none provable from a file that stores only the post-routing set.** The measurement stays;
the causal attribution does not.

⛔ Do not generalise "routing yield depends on geometry" from this handful. The step-5 lattice routed
100% partly because 1,012 fits under the ceiling.

⭐ **The router is a constrained optimiser with priorities, not a lookup** *(vendor)*:
`Array.select_electrodes` takes a **weight** — *"By passing a weight parameter, the routing priority
for the electrodes can be adjusted. The higher the weight, the higher the routing priority during
routing"*. ⚠️ The often-quoted warning *"Make sure not to select more than 1020 of these electrodes.
Otherwise, routing will not work (converge) well"* belongs to **`select_stimulation_electrodes`**, not
to recording selection — an earlier pass mis-attributed it and a future session citing the wrong method
would be contradicted.

### 2.4 The three shapes a routed set comes in

⭐ *(measured here — all 26 Network runs, 8-connected component analysis on the 120 × 220 lattice)*

**(A) Scatter across the whole array — 7 runs, all 180.05 s.** 938–1,006 pads in **27–40** dense
8-connected clusters (median cluster 27–29 pads; largest single cluster 117, on `000057`) flung across
a bounding box up to the full 220 × 120, filling only **3.8%–6.5%** of that box. **98.6%–99.9%** of
their pads have an orthogonal neighbour at 17.5 µm — ⚠️ not 100%: `000047` contains one fully isolated
pad, so a tile map can legitimately show a lone dot. Members: `000042, 000047, 000052, 000057, 000060,
000066, 000688`.

**(B) Decimated patch — 17 runs, all 300.05/300.06 s.** 177–1,018 pads, **every pad its own connected
component** (n_components == n_pads, exactly, on all 17). Median nearest-neighbour 35.0 µm on most;
⚠️ four are ragged at the edges — `000049` (min 35.0 / median 49.5 / **max 178.5 µm**), `000045` (max
78.3 µm), `000055` (max 99.0 µm). Box fill **4.0%–24.9%**.

**(C) Uniform coarse lattice — 2 runs.** `000691` and `000692`: exactly 44 × 23 = **1,012** pads on a
perfect 5-cell (87.5 µm) lattice spanning 216 × 111 cells (98% of the array in x, 92% in y), **100.0%
of the lattice filled with not a single hole**, 4.2% box fill. ⭐ *(inferred, but hard to escape)*: no
activity-driven selection method can fill a 1,012-point lattice completely when **62% of those points
went on to record nothing** — MaxLab's Network Selection and Feature Maximization draw only from
electrodes the scan found active (§3.3). This is a geometric selection with no activity input.

⚠️ ⛔ **Box fill does NOT separate the families** — `000691`/`000692` sit at 4.2%, inside family A's
3.8–6.5% band. An earlier draft implied it did. **The discriminator is the component count**: family A
is dense clusters, families B and C are all singletons.

⚠️ **`260801/P003658/Network/000690` is not "a 63 × 57 block".** Its bounding box is 63 × 57 chip cells
at the chip origin, but only **726 of those 3,591 cells are routed** — 20.2% fill on a step-2 lattice
*(measured here)*. Physically the box spans 1,085 × 980 µm centre-to-centre of the outermost pads. ⛔
Any "is this pad inside the routed region" test must use the **actual set**, never the bounding box.
The orientation-by-coverage argument in the repo's notes still holds — the pads *are* confined to one
corner — but the shape is a sparse lattice.

⭐ **Two groups of runs share a byte-identical routing configuration** — `000061`/`000062`/`000063`
(1,013 electrodes) and `000691`/`000692` (1,012). In both, the electrode **set** and the full
**electrode→channel pairing** are identical, not merely the count and bounding box *(measured here)*.
⇒ **Those are the only runs in the mirror that may legitimately be compared pad-by-pad.** For
`000691`/`000692` the selection timestamps are 512 s apart; the recordings started 495 s apart and each
runs 300 s, so only **165 s (2.75 min)** of dead time separates them. §4.4 is about what changed in
those 165 seconds, and it is not what it looks like.

⚠️ **Largest solid rectangle anywhere in the corpus: 9 × 6 = 54 pads (`000057`)** *(measured here)*.
Nothing here exercises a large dense patch, so nothing here says anything about how one routes.

---

## 3. CHOOSING A CONFIGURATION — THE ACTIVITY SCAN AND THE ASSAY TYPES

This is the part a Camea developer never sees and must nonetheless understand, because it decides what
is in the file.

### 3.1 The ActivityScan: survey the array in pieces, then pick

*(vendor, verbatim, MaxLab Live manual §7.1)*: *"The assay sequentially records from different
configurations of electrodes, thereby scanning the entire electrode array for action potentials. Its
output can be understood as an electrical image of the cells on the electrode array"* … and it is
*"typically the first step of an experiment"*. Its outputs *(vendor, §7.1.2)* are **Firing Rate [Hz]**,
**Spike Amplitude [V]** (the 90th percentile of negative-peak amplitudes), **Active Area** (a binary
map) and **Configs used**.

*(vendor: manual v25.1, Table 20, printed page 66)*, for a MaxOne:

| Preset | Configs | Electrodes | Area covered | Density | "Spatial resolution" | Duration |
|---|---|---|---|---|---|---|
| Sparse 4x | 4 | 3,300 (12.5%) | 2.1 × 3.85 mm | 408 els·mm⁻² | 52.5 µm | 2.6 min |
| Sparse 7x | 7 | 6,600 (25.0%) | 2.1 × 3.85 mm | 816 els·mm⁻² | 35 µm | 5.1 min |
| Checkerboard | 14 | 12,980 (49%) | 2 × 3.85 mm | 1,633 els·mm⁻² | ~25 µm | 9.6 min |
| Blocks | 25 | 20,000 | 1.8 × 3.85 mm | 3,265 els·mm⁻² | 17.5 µm | 17.4 min |
| Full | 29 | 26,400 (100%) | 2.1 × 3.85 mm | 3,265 els·mm⁻² | 17.5 µm | 20.3 min |

The manual ties the durations to a 30 s window on the facing page *(vendor, verbatim, p.67)*: *"if the
recording time per configuration is set at 30 seconds: a Sparse 7x scan, which includes seven
sequential configurations, will last approximately 5 minutes… a Full scan, on the other hand, will
require 20 minutes"*, and notes that *"the Checkerboard and the Block configurations do not cover the
complete electrode array area"*.

⭐ **Read the top row again: covering 100% of the chip costs 29 recordings and 20 minutes.** That is
the vendor's own answer to "why not just record everything". *(paper)* Habibey et al. 2022 confirm the
workflow in practice on a MaxOne — a Full scan whose *"process iterates 29 times"* at 30 s each, then
*"we selected up to 1,024 of the most active electrodes and ran a Network Assay to simultaneously
record from these electrodes for 5 min."* ⚠️ Note the paper says 1,024 where the vendor caps recording
selection at 1,020; and this is **one lab, one cell type** — it is not the field's norm.

⚠️ **The "spatial resolution" column is not an isotropic spacing, and taking it literally will mislead
a UI.** Sparse 7x really is 35 µm on both axes (110 × 60 = 6,600 — measured). But Sparse 4x's 52.5 µm
is not a lattice constant: 3,300 pads only come out of a **staggered** arrangement, and the measured
nearest-neighbour distance for every Sparse4x pad is exactly **49.5 µm** (= 35√2, diagonal), with
**70 µm** along the axes. Checkerboard's "~25 µm" is likewise the diagonal step, 17.5√2 = 24.7 µm
*(arithmetic and measurement here)*.

**What his own scans did** *(measured here)*:

* `260801/P002731/ActivityScan/000687` used **Sparse7x**, `record_time=30`, `spike_only=true`,
  `script_id=ActivityScan_v1.0`. Its seven configurations cover exactly **6,600 unique electrodes =
  25.00%** of 26,400, with **zero overlap** (the seven config sizes sum to exactly the union size).
  Their union is exactly the **odd-column × odd-row** positions — 110 × 60 — a perfect 35 µm lattice.
* The other six ActivityScan files used **Sparse4x**: 4 configurations, 720 + 960 + 960 + 660 =
  **3,300** electrodes = 12.5%, again with zero overlap.
* ⚠️ **The two presets sit on OFFSET sublattices and share no pad at all.** Sparse4x's `ex`/`ey` are
  all **even**; Sparse7x's are all **odd**. Running Sparse7x does *not* subsume a Sparse4x scan, and a
  pad surveyed by one was never surveyed by the other.
* ⚠️ ⭐ **Both presets sweep the chip LEFT TO RIGHT in contiguous vertical stripes.** Sparse4x's four
  configurations are stripes at `ex` 0–46, 48–110, 112–174, 176–218, each a checkerboard filling
  exactly half its stripe's 35 µm grid (`ex/2 + ey/2` even in every row — measured). Sparse7x's
  configurations 1–6 are stripes at `ex` 15–45, 47–77, 79–109, 111–141, 143–173, 175–205, each a
  **completely filled** 35 µm grid of 960 pads; its configuration **0** is the odd one out — the two
  leftover **edge margins** (`ex` 1–13 and 207–219, 14 × 60 = 840 pads), i.e. two narrow bars at
  opposite sides with 1,178 electrode-widths of nothing between them.
  ⇒ ⭐ **A chip map built from an ActivityScan is a set of vertical bands recorded minutes apart.**
  That is the vendor's layout, not a bug, and Obien et al. 2015 describe exactly this protocol
  *(paper, verbatim)*: *"first scan the entire array in static mode, i.e., record from each rectangular
  sub block for, e.g., a few minutes"*.

**What a scan costs in wall-clock**: `000687` ran **390 s** (`started=1785605995`,
`finished=1785606385`, against the file's own `expected_runtime=392`) for **7 × 30 s = 210 s** of
actual recording. Its seven stores start **55.10 s apart** and each is 30.03–30.04 s long
*(measured here)*. So **46% of the run was overhead** — seven separate offset-compensation passes plus
six configuration switches, each visible in the run log *(measured here; the attribution to offset
compensation and switching is inference from the log's own repeated `Downloading util → Running offset
compensation → Started recording → Done recording` cycle)*.

⭐ **Every store also carries `start_time`/`stop_time` as absolute epoch milliseconds** — `000690`:
`1785614684905 → 1785614984984` = 300.079 s; the seven `000687` stores run `1785606025146 →
1785606385786` *(measured here)*. **This is a wall-clock anchor that needs no decoder**, and it is not
mentioned anywhere in the repo's existing notes. See §7.6 for why that matters to the calcium↔MEA
alignment problem.

### 3.2 ⚠️ THE TRAP THAT WILL BITE ANY MULTI-STORE READER

⭐ **The seven `data_store/data0000…data0006` groups in an ActivityScan file are the seven scan
CONFIGURATIONS, not seven wells.** ⭐ **The vendor says so outright**, which an earlier draft settled
only by measurement *(vendor, MaxLab Live manual, recording-metadata table §8)*: *"Number of
Configurations — Number of configurations in a single recording file (for example, 7 configurations
for a 7X Sparse ActivityScan Assay)."*

Four independent measured confirmations back it *(measured here)*: the sidecar's `[options]
configs=Sparse7x` naming `Sparse7xScan/000.cfg…006.cfg`; `[wells] rows=1, columns=1, info\size=1` with
the run log reading `Wells = 0`, `Selected wells: [0]`, `# of recordings = 7`; the seven mappings being
disjoint and summing to 6,600; and the log showing exactly seven record cycles. All 33 files carry
`wellplate/version = "MaxOne Single Well MEA"`, a single `wells/well000`, and
`n_recordings == n_data_store == n_configs` (4 = 4 = 4, 7 = 7 = 7, 1 = 1 = 1).

🔴 **AND CHANNEL IDS ARE REUSED ACROSS CONFIGURATIONS, MEANING DIFFERENT ELECTRODES IN EACH.** Of the
780 channel ids present in both `data0000` and `data0001`, **exactly zero** map to the same electrode.
Channel 5 is electrode 14951 in `data0000` and electrode 11253 in `data0001`. Extended to all 21 store
pairs: the maximum number of channels mapping to the same electrode across **any** pair is **0**
*(measured here)*.

⛔ **So a channel id is meaningless without its store.** Never pool spikes across `data_store` groups by
channel; join through that store's own `settings/mapping` to an electrode first. `mearecording.py`
currently reads `data_store/data0000` only (`_STORE`), which is safe but shows **one seventh** of an
ActivityScan — 801 of 22,597 spikes over 840 of 6,600 electrodes, and specifically only the **two thin
edge strips** of the chip, the least representative slice available (§3.1). See issue 007 and §7.6.

⚠️ **The same file is reachable by three paths, as HDF5 hard links.** In these version-`20190530`
files, `/data_store/dataNNNN/…`, `/wells/wellNNN/recNNNN/…` and `/recordings/recNNNN/wellNNN/…` resolve
to the **same objects** — `h5py.getlink` returns `HardLink`, and two of the paths land on the identical
file offset *(measured here)*. ⇒ Enumerate multi-configuration scans through `/data_store`; it is the
only path that exposes `dataNNNN` per configuration.

⚠️ ⛔ **BUT "STORES ARE CONFIGURATIONS" IS A MaxONE CONCLUSION AND MUST NOT BE GENERALISED.** On a
**MaxTwo** the same 26,400 electrode ids repeat in **each** well, so an electrode id is meaningless
without its well, a store may genuinely *be* a well, and pairing an electrode with the wrong well is
exactly R45.1's class of silent mis-numbering. The current MaxTwo spec table offers **6-Well Plate**
(Platinum Black electrodes, 12.0 × 8.8 µm²) and **24-Well Plate+** (PEDOT, 11.5 × 11.5 µm²), *"Ready
for the upcoming 96-Well Plate format"*, each with **1,020 recording channels per well** and totals of
*"6 × 26'400"* / *"24 × 26'400"*, *"All 6 wells in parallel"* / *"All 24 wells in parallel"*
*(vendor)*. Multiplying out — **arithmetic, not a vendor figure** — that is 6,120 and 24,480
simultaneous channels.
⇒ **Read `[wells]` in the sidecar (and the run log's `Wells =` line) before assuming either.**
⚠️ The repo's `utils/knowledge/maxwell-ids.md` says "MaxTwo = 6 wells"; that is incomplete.

🔴 ⚠️ **AND MaxTwo'S SAMPLING RATE IS A VENDOR SELF-CONTRADICTION.** The MaxTwo spec table reads
**"Sampling rate: 10.0 kHz/channel"** for both plate formats, while MaxTwo prose elsewhere on the same
site and on distributor pages says **20 kHz** *(vendor, both)*. MaxOne is consistently 20 kHz, and the
manual says *"10 kHz for the MaxTwo System or 20 kHz for the MaxOne System"*. ⛔ **Read
`settings/sampling` from the file. Never assume 20 kHz.**

⚠️ **And `data_store/dataNNNN` is not the only layout a MaxLab file uses** *(community:
`neo/rawio/maxwellrawio.py`, `probeinterface/io.py::read_maxwell`)*. Three are known: the **old**
`20160704` files (`/mapping`, `/sig`, `/settings`); the **current + all MaxTwo** form
(`/wells/<wellNNN>/<recNNNN>/settings/mapping`, `…/groups/routed/raw`); and the `data_store/dataNNNN`
form that all 33 recordings in this mirror use (every one stamped `version 20190530`,
`mxw_version 22.2.22`, `hdf_version 1.8.21` — *measured here*). ⛔ Camea's `_STORE` hard-codes the
third. A file in either of the other two would be refused, and that refusal is correct only for as long
as nobody needs to read one.

### 3.3 Picking the recording electrodes from a scan

A Network assay's electrodes come from exactly three sources in the UI *(vendor, verbatim, manual
§7.2.1, p.68)*: **"Use ActivityScan"** (algorithmic selection from a prior scan), **"Load Current
Configs"** (*"This option uses the currently routed electrode configuration for the recording"* —
typically hand-drawn), or **"Load Config File"** (a saved configuration). *"The minimum recording time
per electrode configuration is 10 s."*

⭐ **Two of those three involve no activity data at all.** A Network file therefore carries no guarantee
that its electrodes were chosen because cells were there — which is precisely the author's point.

Under "Use ActivityScan" there are five methods *(vendor, manual §7.2.3 and Table 21, p.70–71,
quoted)*:

| Method | What the manual says |
|---|---|
| **Network Selection** | *"designed to maximize the number of cells to be recorded with a single configuration… a subset is defined so that the distance between the individual electrodes is maximized"* |
| **Neuronal Units** | *"Local clusters of electrodes are selected with the same number of electrodes per group. This is ideal for subsequent spike sorting analyses"* — *"The selected electrodes will be arranged as small round groups of neighboring electrodes"* |
| **Feature Maximization** | *"Electrodes with the highest amplitude or firing rate are selected"* |
| **Hot-spots** | *"the user specifies the number of groups… while the number of electrodes per group is automatically set"* |
| **Python Script** | *"Any electrode selection can be automatically implemented using a customized Python script"* |

with per-method parameters *(vendor, Table 21)*: Selection preference (Spike Amplitude / Firing Rate /
Random), Minimum Spike Amplitude (V), Minimum Firing Rate (Hz), Number of electrodes to select, Number
of electrodes per group, Maximum number of units.

⭐ **Two of the five deliberately route pads that were never recorded in the scan** *(vendor, verbatim,
p.71, restated for the Stimulation assay on p.86)*:

> "Both Network Selection and Feature Maximization methods only select electrodes that were recorded
> during the ActivityScan Assay, whereas Neuronal Units and Hot-spots methods can also select other
> electrodes that were not previously recorded."

with the consequence the manual states itself: *"The output of the network recording for these methods
will therefore also depend on the spatial resolution of the ActivityScan Assay."*

⇒ ⭐ **A pad in a Neuronal Units or Hot-spots configuration may never have been listened to before it
was recorded.** Nobody ever had evidence there was a cell under it. Expecting it to fire is expecting
something no one promised.

⭐ **And Network Selection fills a quota by lowering its bar** *(vendor, verbatim, p.70, §7.2.3,
Step 3)*:

> "Once no new electrode can be selected due to the distance threshold constraint, the distance
> threshold is automatically reduced and the iterative electrode selection procedure resumes. This
> procedure is repeated until the specified number of electrodes is reached or until no further
> electrode can be selected."

⇒ **The tail of a Network Selection set is weak by design.** The method is asked for N electrodes and
relaxes until it has N. The last ones in are the ones it least wanted.

### 3.4 The manual selection palette is geometry, not activity

*(vendor, manual §3.1.1, Table 7, printed pages 23–24)*: **Sparse 1000** (*"Drag to select 1000
electrodes sparsely distributed across the chosen area"*, shortcut `s`), **Sparse** (distributed
according to the sparsity set in the X and Y boxes, `n`), **Block 23×23** (a high-density block centred
on the selected electrode, `b`), **Rectangle** (`r`), **Circle** (`c`), **Pen** (freehand, `o`). The
manual is explicit that selecting is not routing: *"the button Route needs to be clicked to generate a
configuration"*, and routed electrodes *"turn green"*. §4.2 of the manual documents a **Predefined**
sub-tab of saved configurations (*"the same standard configurations that the user can select when
running an ActivityScan assay"*) and a **Custom** sub-tab.

⇒ ⭐ **A hand-drawn configuration carries no activity information whatsoever.** It is a region and a
sparsity. Family C above (the perfect 87.5 µm lattice) is exactly this shape.

### 3.5 What the file records about *why* those pads

⭐ **The HDF5 records the selection provenance in `assay/inputs/electrodes`'s attributes, and it is a
positive record — not merely the absence of one** *(measured here)*:

| Run | `selection_algorithm` | `scan_assay_id` | other |
|---|---|---|---|
| `000688` | **`3`** | **`000687`** | `result_type='Firing Rate'`, `no_islands='40'`, `max_electrodes='1020'` |
| `000689`, `000690`, `000691`, `000692` | `0` | *(empty)* | — |

The same provenance is duplicated in `000688`'s `.mxassay` sidecar, in UTF-16LE inside the decoded
`RoutedElectrodes` blob: `project_0031`, `000687`, `result_type = Firing Rate`, plus `no_islands`,
`must_include` and `max_electrodes`. The other four blobs have a different header shape and contain no
UTF-16 strings beyond the electrode list *(measured here)*.

⚠️ **What that does and does not establish.** It establishes that `000688` was derived from scan
`000687` and that the other four reference **no scan**. It does **not** establish which method — the
integer→method mapping for `selection_algorithm` is not documented anywhere read for this file. ⛔ "The
other four were hand-drawn" remains an inference from shape and from the empty `scan_assay_id`.

⭐ **There is a free, near-decisive test of which method FAMILY was used, and it works** *(measured
here)*: intersect the routed set with the plate's own scan set.

* `000688`: 982 pads routed, only **303 (30.9%)** were inside the plate's Sparse7x scan — **69% were
  never scanned**. ⇒ Only **Neuronal Units** or **Hot-spots** are permitted to do that (§3.3). Its
  shape agrees: **33 dense 8-connected clusters** across the whole array, sizes 9–78, **median 29**,
  modal bounding box **7 × 7** (17 of the 33) — *"small round groups of neighboring electrodes"*,
  the manual's own words for Neuronal Units.
* `000689`: 1,015 pads routed, **1,015 (100%)** inside the scan set. ⚠️ **Suggestive, not decisive** —
  a step-2 comb starting on an odd electrode lands on the Sparse7x odd sublattice automatically, so
  geometry alone would produce this. And `000689` is *measurably* activity-blind (§2.3): its skipped
  in-box pads were slightly more active in the scan than its routed ones.

⭐ **The 180 s scatter runs really do sit on pads the scan found active — on 5 of the 7** *(measured
here)*. Cluster centroid to nearest scan-active pad: median **0.0–2.1 µm**, with **91%–100%** of
clusters within 35 µm. ⚠️ **Against a permutation baseline** (200 random equal-size subsets of the same
plate's scan lattice) the observed median is far outside the null on `000042`, `000057`, `000060`,
`000066` and `000688`; it is **marginal on `000047`** and **not significant on `000052`**, because on
those two plates ~half the scan lattice fired and landing on an active pad is close to chance.
⛔ An earlier draft compared instead against "distance to the nearest **silent** scan pad, 35–49.5 µm";
that comparison is near-tautological — 35 µm and 49.5 µm **are** the scan lattices' own
nearest-neighbour spacings — and it was dropped. ⚠️ One alternative cannot be excluded: that MaxLab's
tile generator snaps candidate positions to the scan lattice by construction.

⭐ **A pattern across the whole corpus** *(inferred, from measured file inventory and family
membership)*: **7 of the 9 plate-sessions** run one ActivityScan → one 180 s scatter (family A) → one
to three 300 s decimated patches. `000041→000042`, `000046→000047`, `000051→000052`, `000056→000057`,
`000059→000060`, `000064→000066`, `000687→000688`. ⚠️ **Two plate-sessions do not** — `260801/P003658`
(`000690` alone) and `260801/P003693` (`000691`, `000692`) have **no ActivityScan and no 180 s run in
the mirror at all**, and those are the runs Camea is currently built against. Within the 26 Network
runs the duration↔shape correspondence *is* exact: `assay/inputs/record_time` is `180` for exactly the
seven clustered configurations and `300` for exactly the nineteen singleton ones. ⛔ **A pattern in his
data, never a rule, and never code — do not branch on duration.** If a UI needs the shape, derive it
from the mapping (component count, nearest-neighbour spacing), exactly as stride and pitch are derived.

### 3.6 The other assay types, briefly

*(vendor, manual)* — because a `data.raw.h5` from any of them can land in `data/`:

* **ActivityScan** — sequential configurations covering the array, tens of seconds each; output is an
  activity image. `spike_only=true` and `script_id=ActivityScan_v1.0` on all seven of his.
* **Network** — one simultaneous configuration of up to 1,020 pads, minutes to hours; output is
  population/network dynamics. `spike_only=false`, `script_id=NetworkRecord_v1.0` on all 26 of his.
  ⭐ **That flag pair is the file's own declaration of its assay type** — use it rather than inferring
  from an empty `groups/` or a store count *(measured here)*.
* **AxonTracking** (p.75–76, Table 22) — *"Define a selection of electrodes (default, 3x3 electrodes
  block) at each neuronal unit, set to be recorded in every configuration (termed 'fixed
  electrodes')"*, with the remaining channels swept across the array in many configurations. Scanning
  area is **Full Array / Array Section (Center, Left Half, Right Half, Custom) / Blocks around each
  unit**, at density **Full / Checkerboard / Sparse**. Guidance: *"Optimal spike counts (>50) from each
  neuron per recording configuration ensure good quality electrical signal reconstruction"*.
  ⚠️ *(inferred)* an AxonTracking file would therefore have **many** data stores, like an ActivityScan.
* **Record** (p.73) — load a saved configuration and record: *"The user can set the recording time
  (between 1 and 10000 mins)"* over *"the number of recording cycles (between 1 and 50 cycles)"*.
* **Stimulation** — adds stimulation-electrode selection on top of the same recording selection.
  ⭐ **This answers a question the earlier draft left open (old §8.14).** *(vendor)* There are **32
  on-chip stimulation units**, *"flexibly assigned to any of the 26,400 electrodes"* and connectable to
  *"arbitrary subsets of the electrodes"*; the tutorial caps *"the maximum number of Stimulation
  Electrodes… at 32, in line with the available Stimulation Units"*. And the API is explicit
  *(vendor, `connect_electrode_to_stimulation`)*: **"For this method to work, the selected electrode ID
  needs already be routed to an amplifier."** ⇒ **A stimulation electrode consumes one of the 1,020
  recording channels.** §7.1's three-state taxonomy therefore stands; a stimulation pad is a *routed*
  pad with an extra role, not a fourth state. ⚠️ Unmeasured: whether the spike table on such a pad is
  usable during stimulation. **No Stimulation file exists in this mirror.**

⚠️ Only ActivityScan and Network appear in this repo's mirror. Anything else is untested against
`mearecording.py`.

### 3.7 ⭐ MaxLab already solves Camea's chip-in-image alignment problem — by asking a human

*(vendor, verbatim, manual §3.1.2 "Background Image")*: the user can load a `.png`, `.xpm` or `.jpg`
behind the electrode array and click **Align**; *"The user needs to click on the four corner electrodes
in the external image, starting with the one on the top left and proceeding in the clockwise
direction. Once the four corner electrodes are selected, the software computes and applies an affine
transformation matrix to the image… Once the alignment is finished, the aligned image is generated and
saved with the file extension '.align'. This image file can then be directly loaded without the need to
repeat the alignment."*

⇒ ⭐ **The vendor's own answer to "how does the chip sit in the microscope image" is: a human clicks
four corners.** There is no automatic registration. ⚠️ **And what is saved is the aligned IMAGE, not
the matrix** — the manual says the *image file* is what gets reloaded. An earlier draft of this
document claimed a `.align` file would "settle the seating question outright"; it would not. It would
let the transform be *recovered* by comparing the warped image with the original, which is a step
short. ⇒ **Worth asking the author whether an `.align` file was ever made during acquisition** (§8.12).

---

## 4. YIELD AND SILENCE — WHAT FRACTION IS "ACTIVE", AND WHAT THE RATES LOOK LIKE

⚠️ **EVERY ABSOLUTE µV IN THIS SECTION ASSUMES READING A** — that the spike table's `amplitude` field
is in ADC counts and must be multiplied by `settings/lsb` (6.2942 µV/count). §5.1 sets out why the
evidence now **tilts toward Reading A** but does not close it. ⛔ **No absolute µV figure below may be
quoted on its own; always carry "(Reading A)" with it.**

What survives *either* reading: everything that is a **rate** (all of §4.3's silence columns, all of
§4.5, and §4.2's reproduction of the vendor's 427 from the firing-rate test alone), and any
**comparison of amplitudes within one file** (§4.4's point 4 — the ratio is unit-free whatever the
unit is).

### 4.1 The vendor's definition of an active electrode

*(vendor, verbatim, manual p.67)*:

> "An electrode is considered an Active Electrode if it has a firing rate larger than 0.1 Hz and a
> spike amplitude greater than 20 µV"

with spike amplitude defined on the same page as *"the 90th percentile of the amplitude distribution
for all detected spikes on that electrode. For every spike, only the amplitude of the negative peak is
considered."* And **Active Area** *(vendor, p.105, the export tables)* is *"Percentage of active
electrodes with respect to the total number of recorded electrodes"* — ⚠️ **out of the pads recorded in
the scan, not out of 26,400.**

⚠️ **Published work uses similar rules with different numbers and different statistics, which is why no
"percent active" figure is comparable across papers:**

| Rule | Source, and preparation |
|---|---|
| FR > **0.1 Hz** AND **90th-percentile** negative-peak amplitude > **20 µV** | *(vendor)* MaxLab Live manual p.67 |
| FR > **0.1 Hz** AND **average** AP amplitude > **20 µV** | *(paper)* Habibey et al., Front. Neurosci. 16:951964 (2022) — hiPSC iNGN neurons on a **MaxOne**, ~30,000 cells on 3.85 × 2.10 mm (~3,700 cells/mm²) |
| FR > **0.02 Hz** plus an amplitude threshold | *(paper)* Sato et al., Front. Neurosci. 16:943310 (2023) — rat cortical, 530 cells/mm², 10–14 DIV. ⚠️ **Not verified** that the array was a MaxWell |
| ≥ **5 spikes/min** (= 0.083 Hz) | *(unverified)* Axion Biosystems application note — could not be retrieved |

⭐ **A five-fold difference in the rate threshold alone.** ⛔ Camea must state its own rule beside any
"active electrodes" figure it shows, and must **never** be tuned to match a number quoted from a paper
with a different rule.

### 4.2 🔴 The vendor's own number, reproduced — and what that does NOT prove

⭐ **MaxLab Live scored `000687` "Active Area: 6.47%", and recomputing the vendor definition from the
raw spike table reproduces it exactly: 427 of 6,600 = 6.4697% → 6.47%** *(measured here)*. Only 427 of
the 6,600 pads MaxWell's own screening assay listened to cleared MaxWell's own bar.

⚠️ **But that agreement does not validate the amplitude handling, and it is important that nobody
believes it does.** On this data the amplitude criterion is **non-binding**: the firing-rate test alone
(FR > 0.1 Hz) also yields exactly 427, and so does FR > 0.1 Hz combined with the *mean*, *median*,
*10th-percentile*, *90th-percentile* **or** *maximum* amplitude > 20 µV. Only the minimum-amplitude
variant differs, at 425. Every pad clearing 0.1 Hz in this scan also clears 20 µV — the all-spike
amplitude median is 47.3 µV **(Reading A; 7.5 in raw field units)** *(measured here)*.

⇒ ⭐ **On this corpus, MaxWell's two-part "active" test reduces to a firing-rate threshold wearing an
amplitude criterion.** Do not describe it to the author as a two-part test, and do not cite the 6.47%
reproduction as proof that any µV conversion is right (see §5.1, and §8.3 for the narrower thing it
*may* be able to say).

⛔ **And if the author ever asks for MaxWell's active count, both thresholds arrive as inputs the caller
supplies** — with the vendor's definition quoted beside them so he can see whose convention it is — and
with **no default**. §7.4 has the rule; there is no version of this where `0.1` or `20` is written into
`src/camea/` or `web/src/`.

### 4.3 The measured table — and why it is an argument against constants, not a source of them

⭐ *(measured here; "active" = FR > 0.1 Hz **and** p90(|amplitude| × lsb) > 20 µV — Reading A)*

| Run | Plate | Routed | Duration | Zero-spike | "Active" |
|---|---|---|---|---|---|
| `000687` ActivityScan | P002731 | 6,600 (7 × 30 s) | 210 s recorded | **87.41%** | 6.47% |
| `000688` | P002731 | 982 | 180.05 s | 23.01% | 41.55% |
| `000689` | P002731 | 1,015 | 300.05 s | **0.00%** | **0.49%** |
| `000690` | P003658 | 726 | 300.05 s | 28.65% | 3.31% |
| `000691` | P003693 | 1,012 | 300.05 s | **61.76%** | 17.29% |
| `000692` | P003693 | 1,012 | 300.05 s | 24.60% | **50.99%** |

Three caveats travel with that table, and they must travel with it wherever it is copied:

* ⚠️ In all six files the amplitude half of the "active" test excludes **zero** pads, so these are
  effectively "FR > 0.1 Hz" figures (§4.2).
* ⚠️ `000690`'s row is computed on the **70.1%** of its spikes that can be assigned to an electrode —
  29.86% sit on channels absent from `settings/mapping` (§5.3).
* ⚠️ `000691` and `000692` are the **same 1,012 pads** minutes apart, and their 33.7-point spread is
  **not** known to be biological (§4.4).

🔴 **`000689` is the single cleanest demonstration that the metric decides the picture.** It has
**zero** pads with zero spikes — every one of the 1,015 fired at least once — and yet only **5 pads
(0.49%)** meet the vendor's active bar. Median per-pad firing rate **0.010 Hz** = 3 spikes in 300 s;
maximum **0.307 Hz** *(measured here)*. **812 of the 1,015 pads carry only 2–4 detections in the whole
five minutes**, and the minimum on any pad is 2, never 1.

🔴 ⭐ **And the busiest pads in `000689` carry the SMALLEST deflections** — median |amplitude| by
detection count: **18.09** (pads with 2–4), 16.34 (1–5), 7.13 (6–10), 5.19 (11–49), 6.07 (≥50)
*(measured here, raw field units)*. ⚠️ Only 3 pads have ≥50 detections, so that last bin alone is thin;
the **monotonic trend across all five bins** is the evidence. ⇒ *(inferred)* this is what a threshold
sitting in the noise looks like. **"Has any spike" and "is active" are not the same question, and a map
that answers one while labelling the other is wrong on this file by a factor of 200.**

**And the whole corpus, all 26 Network runs** *(measured here)* — routed / zero-spike / % silent:

| Run | Routed | Silent | % | Run | Routed | Silent | % |
|---|---|---|---|---|---|---|---|
| `000042` | 996 | 181 | 18.2 | `000058` | 955 | 0 | 0.0 |
| `000043` | 950 | 0 | 0.0 | `000060` | 947 | 78 | 8.2 |
| `000044` | 900 | 10 | 1.1 | `000061` | 1013 | 0 | 0.0 |
| `000045` | 433 | 3 | 0.7 | `000062` | 1013 | 0 | 0.0 |
| `000047` | 998 | 75 | 7.5 | `000063` | 1013 | 0 | 0.0 |
| `000048` | 853 | 5 | 0.6 | `000066` | 938 | 170 | 18.1 |
| `000049` | 177 | 1 | 0.6 | `000067` | 882 | 0 | 0.0 |
| `000050` | 950 | 1 | 0.1 | `000068` | 1018 | 0 | 0.0 |
| `000052` | 1006 | 105 | 10.4 | `000688` | 982 | 226 | 23.0 |
| `000053` | 936 | 11 | 1.2 | `000689` | 1015 | 0 | 0.0 |
| `000054` | 976 | 8 | 0.8 | `000690` | 726 | 208 | 28.7 |
| `000055` | 306 | 7 | 2.3 | `000691` | 1012 | 625 | 61.8 |
| `000057` | 960 | 206 | 21.5 | `000692` | 1012 | 249 | 24.6 |

**And the ActivityScans, per configuration** *(measured here — % of that configuration's recorded pads
that heard nothing in 30 s)*:

| File | Per-configuration silence |
|---|---|
| `000041` Sparse4x | 74.9 · 82.0 · 76.9 · 68.0 |
| `000046` Sparse4x | 53.6 · 52.0 · 51.7 · 55.6 |
| `000051` Sparse4x | 45.1 · 48.2 · 52.7 · 50.5 |
| `000056` Sparse4x | 91.2 · 73.3 · 93.5 · 96.5 |
| `000059` Sparse4x | 90.3 · 61.0 · 70.9 · 89.8 |
| `000064` Sparse4x | 77.9 · 65.2 · 91.8 · 95.0 |
| `000687` Sparse7x | 92.9 · 84.7 · 82.0 · 76.7 · 84.3 · 94.7 · **97.4** (935 of 960) |

⭐ **Even where the software deliberately aimed at a cell, a quarter of the pads hear nothing.** On
`000688` — 33 clusters each centred on a hot spot — **226 of 982 pads (23.0%) recorded nothing in
180 s**, yet **not one of the 33 clusters was silent** (median cluster peak rate 8.18 Hz), and the
within-cluster silent share has median **23%** (p25 15%, p75 34%) *(measured here)*. ⇒ **The silence is
inside the units**, exactly as §1.2's distance table says.

⛔ **THE RANGES ARE THE POINT, AND THEY ARE ALL ORDINARY.** 0%–62% silent on a real recording;
45%–97% silent per scan configuration; 0.5%–51% "active". ⇒ **There is no expected value.** That is
precisely why none of these numbers may be a constant, a default, a threshold or a warning trigger in
`src/camea/` or `web/src/`. ⚠️ And note honestly: 33 recordings from 4 plates in 3 sessions from one lab
is a thin basis for any *general* claim about MaxWell chips. These ranges are a demonstration that no
expected value exists — not an estimate of what a chip looks like.

**For scale, what other labs report** — ⚠️ each on different hardware, cells, age and threshold, so
these are context, not comparators:

| Reported | Source |
|---|---|
| **85.9 ± 23.7** active electrodes per network (n = 31), at FR > 0.02 Hz, 10–14 DIV | *(paper)* Sato et al. 2023 |
| **272 → 613 → 870** active neurons per HD-MEA at 22 → 49 → 83 dpi; mean AP frequency 1.55 → 2.69 → 1.96 Hz | *(paper)* Habibey et al. 2022, **MaxOne** |
| **390 ± 49** of 4,096 electrodes active (9.5%) on planar, vs **790 ± 62** with protruding 3D electrodes (n = 6, p = 0.0006) | *(paper)* Mapelli et al., PLOS One 20:e0328903 (2025) — **3Brain** 64 × 64 array, acute cerebellar slices |
| **46,630** of 236,880 electrodes (19.7%) carrying activity, at ±5.0σ | *(paper)* Yokoi et al., Front. Neurosci. 19:1634582 (2025) — organoids on a 32.45 mm² sensor. ⚠️ The tissue covers only part of the sensor, so this is partly a coverage figure |

⭐ **Culture age dominates.** A mostly-silent chip in a young culture is a young culture, not a broken
chip — Habibey's own MaxOne time course above is the verified evidence for that, and it is the first
thing a biologist would check before suspecting hardware.

### 4.4 🔴 The same 1,012 pads, 2.75 minutes apart, look like different chips

*(measured here)* Across the identical 1,012-pad configuration of `000691` and `000692` — identical
electrode set **and** identical electrode→channel pairing (§2.4):

* pads with **zero spikes** fell from **61.76% (625)** to **24.60% (249)**;
* pads meeting the active bar rose from **17.29% (175)** to **50.99% (516)**;
* with **2.75 min** between the end of the first recording and the start of the second.

⭐ **The design conclusion is untouched and is the one the author asked for: the same physical electrode
reads silent in one recording and active in the next, so silence must never be coloured as a fault.**
Any UI that had marked a pad *dead* on `000691` would have libelled **376 working electrodes**.

⚠️ **But the CAUSE is not established, and four measured properties of the change point away from
biology** *(measured here)*:

1. The change is **strictly one-directional** — 376 pads gained their first spike and **zero** lost
   their last; the 249 pads silent in `000692` are a strict subset of the 625 silent in `000691`. 195
   crossed into "active" and zero crossed out.
2. The newly-active pads are spread over **43 of the 44** lattice columns and **23 of 23** rows — the
   entire array, not a local network region.
3. Total spikes rose only **4.4%** (75,661 → 79,022 assignable), so the same quantity of spikes was
   spread across roughly twice as many pads. 131 pads' rates actually **fell**.
4. The newly-active pads have a **higher** median spike amplitude in `000692` (566 µV) than the
   already-active ones (411 µV) — the opposite of weak neurons newly crossing threshold. ⚠️ Both
   figures are **Reading A** and neither may be quoted alone; the *comparison* is unit-free.

⭐ **One confound was tested and rejected, and the control is worth recording so nobody re-opens it.**
The repo documents `000692` as **54%** 2P-lamp-artefact contaminated against `000691`'s **8.7%** — the
direction that would manufacture this exact result if a lamp flash were being detected as a spike on
every channel at once. It is not: **no 1 ms bin in either file contains spikes from as many as 100
distinct channels**, and discarding every spike in a 1 ms bin with ≥20 distinct channels (2.7% of
`000691`'s spikes, 1.3% of `000692`'s) leaves the result **completely unchanged** — still 625 and 249
silent, still 376 recovered and 0 lost. The 376 recovered pads carry a median of 31 spikes each, none
in high-coincidence bins *(measured here)*.
⚠️ ⛔ **That does NOT clear the lamp.** The documented artefact is *sustained episodes lasting seconds*,
and a 1 ms coincidence test is blind to those by construction — the same mistake §8.14 records an
earlier pass making. The control rules out **instantaneous mass synchrony**, nothing more.

⇒ *(inferred)* An array-wide, one-directional, large-amplitude broadening is the signature of a change
in **recording conditions**, not of a culture waking up. ⛔ **Do not describe the 691/692 difference as
a biological change in activity.**

🔴 **AND THAT DIRECTLY CONTRADICTS THE REPO'S MOST-READ NOTE, WHICH A SessionStart HOOK PUTS IN FRONT
OF EVERY NEW CHAT.** `utils/knowledge/mea-recordings.md` says, immediately under his correction: *"The
23–62 % zero-spike fractions above are **biology**, not hardware failure."*
⭐ **The first half is right and is the whole design conclusion — it is not a fault, and no surface may
word it as one.**
⛔ **But *"is biology"* is not established by anything measured here**, and §4.4 measures **against** it
on exactly the pair that produces the 62% end of that very range: same 1,012 pads, 2.75 minutes apart,
four properties pointing at recording conditions.
⇒ **The note's sentence should be corrected** to say what is actually known — silence is ordinary and
is not a fault — and to stop at that. Also the range is this document's **0%–62% across 26 runs**, not
23–62% across five. See §8.13.

⚠️ And the same-plate pair `000688`/`000689`, 20.4 minutes apart, differ by **113×** in mean per-pad
rate (1.3851 Hz vs 0.0123 Hz) *(measured here)*. Whatever the cause, a fixed colour-scale ceiling would
be wrong on one of them.

### 4.5 The shape of the rate distribution — the number that kills a linear colour ramp

⭐ *(measured here, 26 Network runs)* The spike distribution across routed pads is severely skewed in
nearly every recording:

* **Gini coefficient**: median **0.691**, range **0.146–0.906**. It exceeds 0.6 on **22 of the 26**
  runs; the four that do not are `000058` (0.146), `000689` (0.273), `000047` (0.562) and `000068`
  (0.586).
* **Half of all spikes come from a median of 8.9% of the routed pads** (range 0.6%–39.9%).
* **90% of spikes come from a median of 42.6%** (range 11.8%–87.4%).
* The busiest **10%** of pads carry **19.9%–85.0%** of all spikes; the busiest **1%** carry
  **4.9%–64.0%**.
* Extreme case `000690`: **4 pads of 726 (0.55%) carry 50% of the spikes**; the top pad has 4,167
  spikes against a median of 6. Median-to-maximum ratio **694×**, and unbounded on `000691` where the
  median is 0.

Per-pad rate percentiles, for the three recordings the repo already works with *(measured here)*:

| Run | min | q25 | median | mean | q75 | p90 | p99 | max |
|---|---|---|---|---|---|---|---|---|
| `000690` | 0.0000 | 0.0000 | 0.0200 | 0.0720 | 0.0333 | 0.0500 | 0.4933 | 13.8877 |
| `000691` | 0.0000 | 0.0000 | **0.0000** | 0.2492 | 0.0200 | 0.8032 | 3.6702 | 16.5806 |
| `000692` | 0.0000 | 0.0067 | 0.1033 | 0.2602 | 0.2200 | 0.6799 | 2.5478 | 12.2813 |

🔴 **In `000691` the median AND the 25th percentile are both exactly zero while the maximum is
16.6 Hz.** The mean (0.2492 Hz) sits *above* the 75th percentile (0.0200 Hz). ⛔ **Mean rate is a
meaningless summary for these files.** Corpus-wide the median-pad rate spans 0.0000–1.0108 Hz and the
mean-pad rate spans 0.0123–2.1111 Hz — a **171×** spread *(measured here)*.

⚠️ **And the distribution FAMILY is not stable either, which is the argument for a rank scale rather
than a log one.** In the busy recordings the live-pad rate distribution is close to log-normal — skew
of log₁₀(rate) is 0.078 (`000688`), 0.237 (`000691`), 0.322 (`000692`), 0.554 (scan `000687`) against
raw-rate skew of 1.78–15.00. But `000689` gives log-skew **1.591** and `000690` **2.316**
*(measured here)*. ⇒ Log-normal is a property of the *busy* recordings, not of the chip.

⭐ **Skewed, log-normal-like distributions of firing rate are described as the norm throughout the
nervous system rather than a culture artefact** *(paper: Buzsáki & Mizuseki, "The log-dynamic brain:
how skewed distributions affect network operations", Nat. Rev. Neurosci. 15:264–278, 2014)*. ⚠️ The
often-quoted one-liner about "a minority of neurons doing most of the work" could not be verified
against the full text in this chain — cite the paper for the phenomenon, not for a quotation.

---

## 5. THE SIGNAL AND THE SPIKE TABLE

### 5.1 ⚠️ The `amplitude` field is negative, and its unit is not stated in the file

*(measured here)* `data_store/dataNNNN/spikes` has dtype
`[('frameno','<i8'), ('channel','<i4'), ('amplitude','<f4')]`, written **uncompressed with no HDF5
filter**. In all 26 Network recordings **100.00%** of amplitude values are **negative** — the field is
a signed trough, not a magnitude. ⚠️ **Sign checked on all 26; the totals below are the 260801 subset
only**: 425,963 spikes across the five 260801 Network runs (`000688` 244,925; `000689` 3,770; `000690`
22,367; `000691` 75,661; `000692` 79,240) plus 22,597 across the seven stores of `000687`.

⛔ **Any UI that sorts or colours by amplitude without `abs()` gets the order backwards: the "biggest"
spike is the most negative one.**

It corresponds to the on-chip `maxlab::SpikeEvent`, which the MaxLab C++ reference defines as
`{unsigned long frameNo (8 bytes); float amp (4 bytes); uint16_t channel (2 bytes); unsigned char
wellId (1 byte)}`, with `frameNo` the frame *"at which a spike is detected (typically at the maximal
value of the spike)"* and `amp` documented only as *"4 bytes - Amplitude of the detected spike"* —
**no unit given** *(vendor)*. ⚠️ It is **not** that struct serialised verbatim: the on-disk field order
is frameno/channel/amplitude, `channel` is widened to int32, and `wellId` has no on-disk counterpart.

⚠️ **The unit is an open question, and the two readings differ by 6.294×.**

* **Reading A (counts).** The value is in ADC counts and must be multiplied by `settings/lsb`
  (`6.29425039733178e-06` V = 6.2942 µV/count) to be compared with the vendor's 20 µV bar.
* **Reading B (already µV).** Nothing in the HDF5 labels the field, and `MeaRecording.spikes()`
  (`src/camea/core/mearecording.py:598-616`) copies it straight into a column named **`amplitude_uv`**
  with no `lsb` applied and no `abs()` *(measured here, by reading the code)*.

⭐ **The evidence now tilts hard toward Reading A, on an argument that needs nothing but the file
itself.** The on-chip detector fires at 5× a per-channel noise estimate (§5.2), so the **smallest**
amplitude seen on a channel is roughly 5σ for that channel. Measured per-channel min|amplitude| over
channels with ≥20 spikes, median per file: **3.94** (`000688`), **4.79** (`000689`), **5.23**
(`000690`), **4.76** (`000691`), **6.53** (`000692`) *(measured here)*. Divide by 5.0:

| Reading | implied σ | in LSB (6.294 µV) | verdict |
|---|---|---|---|
| **A — counts** | 0.79–1.31 **counts** = **5.0–8.2 µV** | 0.79–1.31 LSB | plausible: noise straddling ~1 LSB, above Ballini's 2.4 µVrms bench floor as a real culture must be |
| **B — µV** | 0.79–1.31 **µV** | **0.13–0.21 LSB** | 🔴 **impossible**: a σ one fifth of the quantisation step cannot be estimated from a 10-bit integer stream — the digitised signal would simply be constant. It is also below the quantisation floor alone (lsb/√12 = 1.82 µV rms) and below the 2.2 µVrms the vendor prints |

⭐ **And the argument survives its own main bias**: with only tens of spikes per channel the observed
minimum *overstates* the threshold, so true σ is if anything **lower**, which makes Reading B worse.

⚠️ **The honest counter-pull, which an earlier draft under-weighted.** Under Reading A the median
detected spike is 42–82 µV on 22 of the runs — comfortably inside the published somatic range of
0.02–1.7 mV *(paper: Viswam et al. 2019)* — but **305–446 µV on four of them**, and the largest single
events reach **4.55 mV** (723 counts, `000692`), above that published ceiling. Those four are among the
most artefact-contaminated files in the mirror, which is a satisfying story rather than a proof.

⚠️ **A test that looks decisive and is NOT: "the values aren't integers".** `|amp − round(amp)|` is
uniform at 0.250 and the gaps between distinct values are float32 ULPs *(measured here)* — amplitude is
a continuous float in **either** unit, because it is a peak taken off a filtered stream and is not bound
by raw ADC code arithmetic. An earlier pass used non-integrality as evidence against Reading A; it is
neutral.

⇒ ⭐ **Practical ruling until it is settled (§8.3): `amplitude_uv` is probably misnamed and probably
owes a `× lsb`. ⛔ Camea must print NO µV figure derived from this field, and must take `abs()`
regardless.**

⚠️ **And do not quote a typical amplitude — the corpus splits 22-versus-4 and the split follows
nothing.** Median |amplitude| over mapped spikes, in raw field units: **6.7–13.1 on 22 of the 26
Network runs**, and **48.5–70.9 on exactly four** — `000058` (62.7), `000690` (48.5), `000691` (67.2),
`000692` (70.9) *(measured here)*.
🔴 **That is NOT a session or an "era".** `000058` is from session 260620 while the other three are
260801, and the other two 260801 runs (`000688` 7.6, `000689` 13.1) sit firmly in the low band. Every
acquisition setting is identical across the whole corpus (§5.2), so the split follows **no** session,
plate, assay, duration or setting. ⚠️ An earlier draft of this file called it "two eras"; that is wrong
and is contradicted by its own table. The cause is unknown (§8.5). In the low band the median detection
is ~1.2 LSB: on `000042`, **81.6%** of all detections are below 2 LSB and 94.4% below 3 LSB.
⚠️ These medians are over **mapped** spikes only; including unmapped channels moves some runs
(`000058` 62.7 → 60.7).

⚠️ **A contradiction with the repo's own notes, recorded so it gets resolved rather than propagated:**
`utils/knowledge/mea-recordings.md` states *"MaxWell's own detector, median spike amplitude 211 µV"*.
That is not reproducible as a median in field units — `000690` is 46.79, `000691` 67.18, `000692`
70.82, and per-channel-median recipes give 49.6 / 74.1 / 89.1. A search over every simple statistic on
all 26 Network runs for a value in 200–222 found only near-misses: `000691` p95 = 217.6, `000068`
p95 = 213.9, `000692` p90 = 216.0, `000043` p99 = 203.5 *(measured here)*. ⇒ It looks like a high
percentile quoted as a median, and the "13× too big" decoder argument that leans on it may rest on a
different statistic than the one it names. The decoder verdict itself does **not** depend on that
comparison (§6).

### 5.2 The on-chip detector

*(measured here)* `settings/spike_threshold = 5.0` is present in the settings group of **all 33 files**,
Network and ActivityScan alike, alongside `sampling` (20,000 Hz), `lsb`
(`6.29425039733178e-06` V), `gain` (512.0) and `hpf` (300.0 Hz) — **exactly one distinct value each,
across all 57 configurations of all 33 files.**
⚠️ This contradicts the repo's note, which lists `spike_threshold` as present only in ActivityScan
settings. It is in all 33.

⭐ **5.0 is a multiple of the channel's own noise standard deviation, not a voltage — and this is
vendor-documented, where an earlier draft inferred it.** *(vendor, MaxLab Python API)*
`maxlab.util.set_event_threshold(threshold: float)` takes *"The threshold value to set, in standard
deviations away from the mean"*, with *"the default value of 5.0"*; the tutorial's `set_event_threshold(8.5)`
is described as *"setting the detection threshold to 8.5 times the standard deviation of the noise"*.
⇒ ⛔ **Two recordings' spike tables are not on a common absolute scale, and neither are two channels
within one recording.** A spike count is "crossings of this pad's own 5σ line", not "neural activity in
µV".

**What the noise floor actually is** *(paper, Ballini et al. 2014, verbatim)*: input-referred noise of
the full readout chain **including the ADC** is **5.9 µVrms** over 1 Hz–10 kHz, **5.4 µVrms** in the
LFP band (1–300 Hz), **2.4 µVrms** in the AP band (300 Hz–10 kHz) and **1.8 µVrms** in the 500 Hz–3 kHz
spike-detection band; spectral density 39 nV/√Hz at 1 kHz. ⚠️ **Scope: that is a bench characterisation
of the electronics, not a chip with a culture on it.** The electrode–electrolyte interface and
biological background add on top — Ballini notes the Pt electrodes alone contribute ~80 nV/√Hz at
1 kHz. ⇒ **Use 2.4 µVrms only as a lower bound**; the vendor's product-page "typical noise per chip
2.2 µVrms" is the same kind of number.

**The digitiser** *(paper, Ballini 2014, verbatim)*: *"Amplified and filtered signals are digitized by
10 bit parallel single-slope ADCs at 20 kSamples/s."* ⚠️ The often-quoted "±3.2 mV range, 6.3 µV LSB" is
**not** an independent published spec — it is arithmetic on the file's own numbers: `lsb = 3.3 V /
(1024 × gain)`, so at gain 512 lsb = 6.294 µV and full scale = 6.445 mV, i.e. ±3.22 mV about midscale
512. ⭐ **And the stored `lsb` is bit-for-bit equal to `float32(3.3) / (1024 × 512)`** — evaluated in
double precision the same formula gives `6.29425048828125e-06`, differing by 1.4e-8 relative
*(measured here)*. ⇒ The firmware holds 3.3 as a single-precision constant. ⛔ **The fallback formula in
`utils/knowledge/maxwell-ids.md` agrees to 8 significant figures, which is far more than enough for
microvolts — but it is NOT an equality, and a test asserting `==` would fail.**

⚠️ **`lsb` is not a constant across experiments, because gain is a setting.** *(vendor, MaxLab API
`Amplifier.set_gain`)*: *"Possible gain values are: 1, 7, 112, 512, 1024, 1025, 2048"*, and *"Other
values are not valid and will raise an exception"*. ⛔ **Always read `lsb` and `gain` from the file.**
*(community: braingeneers/braindance documents only 512/1024/2048 as selectable in its own wrapper — a
subset, not a contradiction.)*

⭐ **The spike table is the trustworthy half of the file.** It is written by the on-chip detector at
acquisition and stored uncompressed, so it needs no proprietary plug-in and is entirely unaffected by
the raw-decode problem in §6. Everything in §4 was measured off it.

⚠️ **But a threshold detector systematically UNDER-COUNTS during network bursts** *(paper)*:
Zegers-Delgado, Renegar, Pathirage, Horiuchi, Abshire & Araneda, "A fast and simple algorithm for
accurate spike detection in HD-MEA recordings", J. Neurosci. Methods 431:110750 (2026) report that
during burst periods their scaled-median-absolute-deviation detector found **over half of the spikes
the RMS-based method missed**, because *"the adaptive RMS estimate lacks sensitivity during periods of
high network bursting activity"*. ⚠️ **Scope:** MaxOne, cortical cultures, one laboratory — enough to
support the qualitative point, not enough to quantify the bias on another culture. MaxWell links the
paper from its own resources page.

### 5.3 🔴 SPIKES ON CHANNELS THE RECORDING'S OWN MAPPING DOES NOT LIST

⭐ *(measured here)* **25 of the 26 Network recordings contain spikes on channel ids absent from
`settings/mapping`.** Usually it is negligible — median **0.13%**, only six runs above 1%. But:

| Run | Unassignable spikes | Of total | Orphan channels | Routed |
|---|---|---|---|---|
| `000690` | 6,679 | **29.86%** | 111 | 726 |
| `000049` | 3,290 | 12.31% | 678 | 177 |
| `000045` | 1,320 | 10.10% | 444 | 433 |
| `000055` | 2,490 | 4.80% | 591 | 306 |
| `000058` | — | 1.66% | — | 955 |
| `000691` | 0 | 0.00% | 0 | 1,012 |

The orphan-channel count ranges **0 to 678** across the 26 runs, and it never exceeds `1024 −
n_routed` — ⛔ **which is a tautology, not evidence**: the ids are ≤1023 and disjoint from the routed
set, so there can be at most that many by counting alone. An earlier pass offered it as proof; it
cannot be. ⚠️ The relationship with routed-set size is a **tendency, not a rule** — three files routing
853–955 pads exceed 1%, and the corpus maximum is on the 726-pad file, not the 177-pad one.

They are **not** a pre-roll artefact: in `000690` the unmapped spike times run from −0.1075 s to
299.8895 s with a median of 109.25 s, and only 3 of the 6,679 fall before t = 0 *(measured here)*. In
`000690` they are also highly concentrated — 5 of the 111 channels carry 80.0% of the 6,679, the
busiest logging 1,958 crossings in 300 s (6.53 Hz), brisker than most real electrodes in the same
file. And their amplitudes are **indistinguishable from routed ones**: median |amplitude| 45.9 vs 48.5
*(measured here)*.

⭐ **The vendor names the mechanism** *(vendor, MaxLab glossary)*: *"**Floating amplifier**: An
amplifier that is not physically connected to an electrode. Floating amplifiers tend to exhibit higher
noise levels because they capture environmental noise due to their lack of grounding."*
⇒ *(inferred, and now much better supported than in the earlier draft)* the on-chip detector runs on
**all** amplifiers, including floating ones, and a floating amplifier's higher noise is exactly what
produces threshold crossings with no cell anywhere near.

⭐ **Nothing proves "a detection is not a neuron" better than a threshold crossing on a channel wired to
nothing.** In the sparsest recording (`000049`, 177 routed) **678 of the 1,018 channels in the spikes
table have no place on the chip map at all.**

⛔ **What Camea must do about it.** `MeaRecording.activity()` already refuses to credit these spikes to
an innocent electrode (its `searchsorted` confirm-the-hit check), but it **silently drops them**. So a
chip map's total will not equal `info().n_spikes` — off by 29.86% on `000690` and by under 0.5% on
twenty of the twenty-six. ⚠️ **A UI that prints "22,367 spikes" and colours 15,688 of them is lying by
omission, and the size of the lie is per-recording.** Compute it; surface it; never assume it is small.
⛔ And never size the warning off the 29.86% outlier — the median is 0.13%, a 200× difference.

🔴 **This is not hypothetical: Camea ships it today, and §7.6 names the two lines.** `000690` is one of
the two attached projects, so the screen currently prints 22,367 against 15,688 coloured.

### 5.4 A spike is not a unit

⭐ Covered in §1.2 and worth restating here because it is where counting goes wrong. Three independent
strands say the same thing:

* *(measured here)* In the densely-routed configurations — `000047` (89.0%), `000042` (91.3%),
  `000688` (87.8%) — that share of spikes has a near-simultaneous partner on a pad within 35 µm,
  8–11× above the position-shuffled control. ⚠️ The shuffled figure moves a point or two between
  seeds — read it as "about 10%", not as a fixed number.
* *(paper)* A single reconstructed neuron's electrical image, axons included, *"spread over 1200
  electrodes"* — Radivojevic et al. 2017, on an 11,011-electrode 17.8 µm array.
* *(paper)* Only **86%** of electrodes passing a spike-detection constraint are looking at a soma at
  all; **14%** are on neurites, at less than half the amplitude — Deligkaris et al. 2016. ⚠️ Both are
  a different array and preparation from a MaxOne.

⚠️ **And the community is trying to fix it in software.** Zegers-Delgado et al. 2026 add an explicit
step to *"de-duplicate spikes recorded on multiple electrodes"*; SpikeInterface PR #4018 proposed
removing *"duplicates where multiple MaxWell channels [are] connected to the same electrode"*
*(community)*.

⇒ ⛔ **"Number of active electrodes" is not "number of neurons", and a chip map coloured by spike count
shows ELECTRODE activity. Label it that way.** Any future spike-sorting or "how many cells" feature
must inspect the routing geometry **first**: on the 19 singleton-lattice runs no algorithm can merge
duplicate detections because there are no adjacent pads to merge, and on `000047` one that does not
merge will over-count badly.

⛔ **And never divide a pad count by a "typical electrodes per neuron" figure.** The one published
multiplicity number — *"the activity of each RGC on 14 ± 7 electrodes"* *(paper: Fiscella et al.,
J. Neurosci. Methods 211:103–113, 2012 — mouse retinal ganglion cells, whole-mount retina, a
126-channel array)* — comes with the same paper's *"multiple, highly overlapping RGCs"*, so the per-cell
electrode sets overlap and the division does not hold. An earlier pass used it to estimate "tens of
neurons" per configuration; that estimate is invalid and was removed.

### 5.5 ⚠️ And "has spikes everywhere" can also be an illusion

🔴 `260620/P002137/Network/000058` has just **14 population events in 300 s carrying 81% of its 16,505
spikes**, and a Gini of only **0.146** — near-uniform across the array. Yet its coincidence rate within
1 ms / 35 µm (**59.2%**) is **indistinguishable from, indeed slightly below, its position-shuffled
control (61.2%)** *(measured here)*. The synchrony is global with **no local footprint**. `000689` is
the same shape: its 2,032 coincident events (53.9% of 3,770) resolve to exactly **two instants** —
t = 143.279 s (1,014 events) and t = 167.829 s (1,018 events) on a run that routed 1,015 pads — with
median |amplitude| 38.1 against ~5 for everything else.

⚠️ **The discriminator is the shuffle control and nothing else.** `000047` — the run with the
*strongest* local footprint — also has 82.3% of its spikes inside population events. The in-event spike
fraction does not separate the two cases. ⇒ A naive "population event" detector says almost nothing on
its own.

⇒ A map coloured by raw spike count would paint `000058`'s entire array as uniformly "active" when the
whole signal is 14 array-wide events. ⭐ **The zero-count is not the only misleading number; a small
uniform non-zero count is equally so.** That is a strong argument for showing the author the
distribution, not just a colour.

### 5.6 ⭐ TIMING — and one hardware timestamp nobody had noticed

*(measured here)*

* `groups/routed/frame_nos` is **fully contiguous** in every Network recording — maximum consecutive
  difference exactly 1, no dropped samples.
* ⚠️ **Spikes are logged before the first stored sample**: 91 (`000688`), 0 (`000689`), 3 (`000690`),
  9 (`000691`), 21 (`000692`). ⇒ A `(frameno − frame_nos[0]) / fs` time origin produces **negative**
  times. Clamp, or report them; do not be surprised by them.
* ⛔ **`data_store/…/events` is present but EMPTY** — shape `(0,)`, dtype
  `(frameno, eventtype, eventid, eventmessage)` — in all six of the 260801 files.

🔴 ⭐ **BUT THE TOP-LEVEL `bits` GROUP IS WHERE MaxWell WRITES DIGITAL INPUT, AND ONE FILE HAS ONE.**
`260801/P002731/Network/000689` carries `bits/0000` = `[(frameno 53167027, bits 6), (frameno 53169027,
bits 0)]` — a **100.0 ms digital pulse** at t = **167.8997–167.9997 s** relative to the first stored
sample *(measured here)*. The `bits` group is empty in the other five 260801 files. ⚠️ **The other 27
files were not checked for it.**

⚠️ This is what spikeinterface's `MaxwellEventExtractor` reads — *"Class for reading TTL events from
Maxwell files"*, `bits = h5_file['bits']; bit_states = bits['bits']` *(community)*. ⛔ On these files it
would **raise**, because `bits` here is a *group* keyed `'0000'` rather than a dataset with a `'bits'`
field. That is a format mismatch, not an absent signal — and an earlier pass, having checked only
`data_store/…/events`, concluded that no external marker exists anywhere. **It does.**

⭐ **Why this matters more than anything else in §5.** The MEA↔calcium alignment problem (issue 003) is
currently being attacked by finding 2P-lamp episodes *in a trace Camea cannot decode*. A **sample-accurate,
decoder-free external timestamp** sits in `000689`. ⚠️ It lands 70.7 ms after that file's second
whole-array spike instant (t = 167.829 s); ⛔ **do not assert they are the same event** — record that
both exist and are 70.7 ms apart. The epoch-millisecond `start_time` (§3.1) is a second decoder-free
anchor, coarser but present in every store of every file.

---

## 6. THE RAW STREAM AND ITS PROPRIETARY DECODER

Stated plainly, because it changes what a Camea screen is allowed to claim.

* `groups/routed/raw` is `(n_channels, n_samples)` **uint16** at 20 kHz, chunked `(n_channels, 200)`
  with fill value 0, compressed with **MaxWell's own HDF5 filter, id 401 (`mxw-data`)** followed by
  **deflate at level 0** *(measured here, from the dataset creation property list)*. ⇒ The compression
  ratio is filter 401's own work; deflate contributes nothing. HDF5 loads the filter from a plug-in
  library at read time; it is not part of the file and is not open source.
* Without the plug-in, `h5py` raises `OSError: Can't synchronously read data (can't open directory)` on
  the raw dataset — while **mapping, settings and spikes read fine** *(measured here)*. ⭐ **A chip map,
  an electrode layout and a spike-rate view are all reachable with no decoder at all.** Only waveforms
  need it.
* 🔴 **Measured on this project's data (2026-08-13, recorded in the repo): the public plug-in does not
  reconstruct these files.** 98% of samples come back as the constant **1023** = 2¹⁰−1 — the top of the
  10-bit ADC, the *rail* — and the dataset's real HDF5 fill value is `0`, so this is not HDF5
  substituting for absent chunks. Every chunk is allocated; the stream stores 1.59 GB against 12.15 GB
  uncompressed (**7.6:1**, the same ratio on both files measured). ⇒ **The bytes are there. It is a
  decode failure, not a recording mode** — and `assay/inputs/spike_only` is `false` on every Network
  file, i.e. a full continuous trace *was* recorded.
* ⭐ **The plug-in is 10 KB and self-contained, so "a missing sibling DLL" is ruled out.** The installed
  copy is `compression.dll`, **10,752 bytes**, MD5 `b9037dda7b710b2bfd92de1b6c0d9576`, dated
  2025-09-08, in `C:\Users\phill\hdf5_plugin_path_maxwell`. It exports `H5PLget_plugin_info` /
  `H5PLget_plugin_type`, contains the string `mxw-data`, and imports **only** `KERNEL32.dll`,
  `VCRUNTIME140.dll` and the UCRT — no zlib, no lz4, no vendor DLL *(measured here)*.
* ⚠️ ⭐ **IMPORTANT SCOPING CORRECTION — the public decoder is NOT known-broken in general.** A search of
  SpikeInterface's issues (all Maxwell-tagged, #3385–#4546), python-neo, the HDF forum and the open web
  found **no public report of the plug-in returning a near-constant stream** *(community)*. The Maxwell
  issues that do exist are about the old `20160704` header format (#3775), 24-well stream ids (#3608)
  and plug-in installation (#460, #3961). SpikeInterface's own CI downloads the plug-in and runs Maxwell
  tests. ⇒ **The failure is on THESE files (writer `mxw_version 22.2.22`, format `20190530`), not on the
  ecosystem.** Whatever `docs/` says about it should be scoped that way, or a future session will
  conclude the world is broken when it is not. *(One weak datum for the scoping argument: the
  `ephy_testing_data` MaxOne fixtures are dated 2021-05-10, predating this writer.)*
* ⭐ **All 7 ActivityScan files carry `spike_only = 'true'` and an empty `groups/` in every store; all 26
  Network files carry `spike_only = 'false'` and a populated `groups/routed/{raw,channels,frame_nos}`
  with shapes from (177, 6,001,000) to (1,018, 6,001,200)** *(measured here)*. ⇒ ⚠️ **"No trace" means
  two completely different things in the two assays**, and a UI must not word them alike: on an
  ActivityScan no trace was ever written (a fact about the assay); on a Network run the trace exists and
  cannot currently be read (a fact about this machine).
* ⛔ **Never present a trace as clean without consulting `trace_health()`.** A railed window looks
  exactly like a genuinely silent electrode, and silently drawing a flat rail as a voltage is the
  laundered machine answer this project refuses.
* ⭐ **The 2P lamp episodes in the trace are a SYNC SIGNAL, not a defect** — the people who collected
  this data toggled the lamp deliberately so the calcium and MEA clocks could be aligned. Treat them as
  signal; never "clean" them away. See §4.4 for why they nonetheless matter to the spike table, and
  §5.6 for a marker that needs no trace at all.

**Where the plug-in comes from** *(community: `neo/rawio/maxwellrawio.py ::
auto_install_maxwell_hdf5_compression_plugin`)*: an unversioned Seafile share,
`https://share.mxwbio.com/d/7f2d1e98a1724a1b8b35/files/?p=%2FWindows%2Fcompression.dll&dl=1` (with
`/Linux/libcompression.so` and `/MacOS/Mac_{arm64,x86_64}/libcompression.dylib`). neo downloads it into
`~/hdf5_plugin_path_maxwell` and sets `HDF5_PLUGIN_PATH`; since SpikeInterface PR #3961 (merged
2025-05-30) that download runs by default. ⚠️ **There is no version in the URL and no newer public build
to chase** — consistent with the repo's finding that a re-download was byte-identical. The remaining
hunt is for MaxLab Live's own copy.

⛔ The decoder is MaxWell's licensed artefact: **never commit it** to this GPL-3.0 public repo, and never
download one silently on the author's behalf.

⚠️ **What neo and spikeinterface do and do not give you** *(community)*: neo reads the raw stream (with
the plug-in), the mapping/probe, `gain_to_uV`, and handles both the `20160704` and later formats — but
*"This implementation does not handle spikes at the moment"* and it returns an empty `spike_channels`.
spikeinterface reads TTL events from `bits` (§5.6). PR #4018, which would have added MaxWell spike and
stimulation events plus channel de-duplication, was **closed unmerged** on 2025-08-09 with 6 of its 13
checks failing. ⇒ **There is no upstream implementation to defer to on the amplitude-unit question, and
Camea's spike reader is not duplicating one.**

---

## 7. ⭐ WHAT THIS MEANS FOR CAMEA

The section to act on. Everything above is why.

### 7.1 A pad has THREE states, not two

⛔ **`not routed` · `routed, no spikes detected` · `routed, active`.** They are different facts and must
be different *shapes* on screen, not different shades:

| State | Share of the chip | What it means | What it must never say |
|---|---|---|---|
| **not routed** | ≥96.1% of 26,400 always; 96.1%–99.3% across this corpus *(§1.1)* | Nothing was connected to it. No evidence either way. | "0 spikes", "inactive", or a colour on the ramp |
| **routed, nothing heard** | 0%–62% of the routed set *(measured here)*; 45%–97% on a scan configuration | Listened to; no spike cleared **this recording's** threshold in **this window**. Most likely no cell near it — *(inferred, §1.4; the shipped wording keeps the hedge)*. | "dead", "silent", "failed", "flat", "broken" |
| **routed, fired** | the rest | This pad detected spikes. Not "this is a neuron". | "N neurons" |

⭐ `ChipMap`'s hollow ring for the middle state is right: a different shape can never be misread as a dim
colour, and it survives being printed in black and white. `SILENT_MEANING` is the single sentence so the
legend and the hover cannot drift.

⭐ **A stimulation pad is not a fourth state** — §3.6: the vendor requires an electrode to be routed to
an amplifier *before* it can be attached to a stimulation unit, so it is a routed pad with an extra
role.

### 7.2 The colour scale — the decision `activityScale.ts` is waiting on

The three options he was shown, against what is now measured:

* ⛔ **Linear (busiest pad sets the top).** Refuted by measurement, twice over. Median Gini 0.691; half
  the spikes come from ~9% of the pads; in `000691` the median *and* q25 pad rate are exactly 0.0000 Hz
  against a 16.6 Hz maximum. The repo's own earlier pass measured **72%–99% of live pads landing in the
  darkest tenth** — `000688` **72%**, `000689` 99%, `000690` 99%, `000691` 90%, `000692` 96% *(cited:
  `utils/knowledge/mea-recordings.md`, which covered five of the 33 files)*. Even at the 72% end the
  picture is very nearly one flat colour, which hides the structure the screen exists to show.
  ⚠️ **That note's prose, and `activityScale.ts`'s header, both summarise this as "90–99 % … on every
  one of his recordings"; the note's own table says 72% for `000688`.** The argument against a linear
  ramp is untouched — 72% in the darkest tenth is still a flat picture — but both summaries are wrong
  and should be corrected. See §8.13.
* ⚠️ **Square root.** Better, and **recording-dependent** — still 96% of live pads in the darkest tenth
  on `000690` while `000692` comes out well at 41%. A ramp that fixes some files and not others is not
  a fix.
* ⚠️ **Log.** Tempting given §4.5, and wrong for the same reason: log-normality is a property of the
  *busy* recordings only (log-skew 0.078–0.554 on four files, but **1.591** on `000689` and **2.316** on
  `000690`). ⛔ Do not choose a ramp whose assumption the corpus breaks on a third of its files.
* ⭐ **Rank / "spread them out" (the current provisional default).** Every live pad's colour is its
  position in the order, so the picture uses the full range whatever the recording. It is the only one
  of the four that measured well on all of his recordings, and it is the **assumption-free** choice
  precisely because the distribution family is not stable (§4.5). §4.5 also explains why any absolute
  mapping is wrong on most of the corpus: a 171× corpus-wide spread in mean rate and 113× between two
  runs of the *same plate*.
  ⚠️ Its cost is real and must stay on the legend, as it already does: **equal steps of colour are not
  equal steps of rate.** `SCALE_CAVEAT` says so; keep it.

⇒ **The evidence supports keeping the rank ramp as the default.** ⛔ But the choice is the author's, not
this document's — put it to him with `AskUserQuestion`, and if he wants an absolute scale, it must still
be derived per recording and the legend must name real rates at each stop (which `activityScale.ts`
already does by inverting the rank map).

⭐ **A better option this document opens up, worth offering him**: because `000058`-style recordings
exist (uniform low counts that are entirely 14 array-wide events, §5.5) and `000689`-style ones do too
(every pad fired, almost none is "active", §4.3), **the honest screen shows the distribution, not only
the colour** — a small histogram or the five legend rates plus "N pads heard nothing". The colour
answers "where"; the distribution answers "how much, really".

### 7.3 Numbers a UI must compute and show, never assume

⭐ Four of these five already ship; **one does not**, and it is the one that makes the screen wrong.

* ✅ **How many routed pads heard nothing** — ordinary, and it ranges 0%–62%. *Ships:* `n_silent`,
  `routes.py`'s activity route.
* 🔴 **How many spikes could not be placed** — §5.3. Ranges 0%–29.86% and cannot be guessed. **NOT
  BUILT, and the number that replaces it today is wrong** — §7.6 names the two lines.
* ✅ **Which assay and how long** — a 30 s ActivityScan window and a 300 s Network run are not
  comparable, and a "silent" verdict from the former is nearly meaningless. *Ships:* `assay`,
  `duration_s`. ⚠️ But see §7.6: `duration_s` is `0.0` on exactly the assay this caveat is about.
  ⭐ **And §1.4's window measurement makes this stronger than a caveat**: `000688` reads 43.3% silent at
  30 s and 23.0% at 180 s. **The window length must sit beside the silent count, always.**
* ✅ **The scale's own maximum** — derived from this recording, every time. *Ships:* `max_rate_hz`, and
  `activityScale.ts` derives the whole ramp from the rates it is handed.
* ⚠️ **Which configuration, when there is more than one** — an ActivityScan is 4 or 7 vertical bands
  recorded minutes apart (§3.1). A chip map from one must say which, or say it is a union.

⭐ **This is cheap.** The repo's own timing pass measured `layout` + `activity` end-to-end over the whole
spike table at **2.3 ms–21.0 ms** per recording (worst case `000688`, 244,925 spikes). There is no
performance argument for caching a scale or hard-coding a ceiling.

### 7.4 ⛔ NONE OF THESE NUMBERS MAY BECOME A CONSTANT

Invariant I1, restated for this material specifically. In `src/camea/` and `web/src/` there must be
**no**:

* expected or "healthy" firing rate, no default colour ceiling, no fixed maximum;
* expected silent fraction, expected active fraction, or threshold that triggers a warning about one;
* electrode count, channel count, row count, column count or pitch written as a literal — the geometry
  is derived by `derive_geometry()` and a file that fails the check is **refused**. ⚠️ **With exactly
  one carve-out, and it is a real one: `core.electrodegrid.DeviceSpec` / `MAXWELL`**, where
  `axes = (120, 220)` and `pitch_um = 17.5` are written down on purpose. R45.1's 2026-08-11 amendment
  (R45.8) makes that *the single place in app code those numbers may appear*, because there they are
  knowledge the **user asserts** by declaring the whole chip imaged, and even then they only *check
  and complete* a fit that was measured first. ⛔ Do not "clean it up" on the strength of this
  section — `tests/unit/test_electrodegrid.py` and `tests/api/test_core_routes.py` assert those
  literals, and UI prose still reads the device over the wire rather than repeating them;
* sampling rate, `lsb`, `gain`, `hpf` or `spike_threshold` written as a literal. All five are identical
  across all 33 files in this mirror (§5.2), which is exactly the trap: code that hard-codes 20 kHz or
  gain 512 passes on every file here and fails on someone else's. ⚠️ MaxTwo may be 10 kHz (§3.2);
  MaxLab offers seven gain values (§5.2).
* ⛔ **`0.1` or `20` anywhere at all** — not as a literal, not as a default, not behind a tooltip that
  calls it MaxWell's. It is *MaxWell's convention*, not a fact about a chip; published work uses 0.02 Hz
  and 0.083 Hz for the same word (§4.1); and on this data it reduces to a bare rate threshold (§4.2). If
  the author ever asks for MaxWell's active count, **both thresholds arrive as request parameters the
  caller supplies, with the vendor's definition quoted beside the input, defaulting to nothing** — the
  request is refused if either is absent.
  ⚠️ *(An earlier draft of this bullet forbade only presenting the rule "as truth" and told the reader
  to "compute it from the recording". Both were wrong: the first licenses the literal so long as a label
  sits next to it, and **you cannot derive a threshold from a file** — a threshold is a convention
  somebody chose. The rule is the one above.)*
* ⛔ **`512`, the ADC midscale, is the one literal with a defensible case — and even it should not be
  written.** `trace()` owes a midscale subtraction (§7.6); subtracting the window's **own median** is
  better than writing 512 down, and it is correct for any bit depth.

⚠️ **The one device fact the repo does consult** is `core.electrodegrid.MAXWELL`, and only under R45.8's
rule: consulted when the *derived* stride matches one of its axes, never assumed, with the alternative
being to report the recorded extent (`chip_extent: "recorded"`). ⭐ That pattern is the model.
**Derive, verify, and refuse — never write the number down.**

### 7.5 Wording rules that fall out of the evidence

⛔ Forbidden on any MEA surface: *dead* · *silent electrode* · *failed* · *flat* · *broken* · *inactive*
(of a routed pad) · *N neurons* (of a spike or pad count) · *the culture is quiet* (of a low count in one
window).

⭐ Safe, and each backed above: *"no spikes — most likely no neuron near this pad"* · *"not recorded in
this configuration"* · *"N pads listened to, M heard something"* · *"N spikes could not be placed on the
chip"* · *"electrode activity"* rather than *"neural activity"* · *"in this 30 s window"* attached to
any silent count.

### 7.6 The concrete code consequences

* 🔴 **Issue 007 is real, and it is THREE failures, not one. Fixing the one it names leaves the screen
  wrong in a worse way than the refusal it replaces.** All three verified by reading the code against
  §6's measured fact that `groups/` is **empty in every store of all 7 ActivityScan files**:
  1. `MeaRecording.info()` reads `groups/routed/raw`'s shape for `n_channels`/`n_samples`
     (`src/camea/core/mearecording.py:516`) — the one issue 007 names. **7 of 33 recordings (21%)**, and
     precisely the files carrying the array-wide silence evidence this document is built on.
     🔴 The failure is a bare `KeyError: 'Unable to synchronously open object (component not found)'`
     from h5py, **NOT** the `"not a MaxLab recording?"` message the repo's notes attribute to it
     *(measured here)* — `_grp()` never fires, because these files *do* have `data_store/data0000`.
     ⇒ A caller cannot catch `MeaError` to handle this.
  2. ⛔ **`spikes()` breaks too, independently** — `mearecording.py:610` reads
     `g["groups/routed/frame_nos"][0]` to get the first stored frame. Same missing group, same
     `KeyError`. So **the spike table — the "trustworthy half" the whole of §4 rests on — is unreadable
     through Camea's own API on an ActivityScan for a second reason**, and issue 007's fix to `info()`
     alone does not touch it. It needs a `frame_nos`-absent path (times relative to the first spike
     frame in the table).
  3. 🔴 **Issue 007's stated fix, `n_samples = 0`, silently zeroes every rate.** `duration_s` is
     `n_samples / sampling_hz` (`mearecording.py:175`) and `activity()` divides by it with
     `if dur > 0 else zeros` (`mearecording.py:668`). ⇒ With 1 and 2 fixed and `n_samples = 0` left
     standing, an ActivityScan returns `rate_hz = 0.0` for **every** pad and `max_rate_hz = 0.0`, and the
     chip map renders MaxWell's own 6,600-pad survey as a **uniformly dead chip**. That is the exact
     failure this whole document exists to prevent, arriving by way of its fix.
  ⇒ ⭐ **The real requirement: an ActivityScan's duration must not come from a raw-stream shape.** Three
  sources are available and all three are evidenced here — the run's `.mxassay` sidecar records
  `record_time` (30 s on `000687`), the HDF5's own `assay/inputs/record_time` records the same, and each
  store's `start_time`/`stop_time` epoch-ms pair gives 30.03–30.04 s measured per configuration (§3.1).
  ⭐ **`assay/inputs/record_time` is inside the HDF5 and is the obvious choice** — the sidecar may be
  absent. ⛔ What is **not** open is shipping `0.0`: a duration of zero must refuse by name, never
  divide.
* ⚠️ **Multi-store files.** Six ActivityScan files have 4 stores, one has 7, and `_STORE` reads only
  `data0000` — which on `000687` is the **two thin edge strips**, the least representative slice of the
  chip. Widening it requires deciding what "a recording" means; §3.2 forbids pooling by channel id
  across stores, and the vendor's own metadata table confirms stores are configurations.
* 🔴 **THE UNPLACED-SPIKE COUNT IS ALREADY BEING PRINTED WRONG.** Both MEA routes return
  `"n_spikes": info.n_spikes` — the **file total** — (`src/camea/features/mea/routes.py:615` in `layout`,
  `:650` in `activity`) alongside a `pads[]` tally that omits every spike on an unmapped channel, and
  `web/src/features/mea/OpenRecording.tsx:74` prints it verbatim as `{layout.n_spikes} spikes`. On
  `000690` — one of the two attached projects — the header says **22,367** while **15,688** are coloured
  *(§5.3, measured here)*. ⇒ Add an explicit unplaced count to `MeaChipActivity` (`n_spikes_unplaced`,
  or return the placed total beside the file total) and show it whenever it is non-zero. ⛔ Do not "fix"
  this by printing only the placed total — that hides a real fact about the file; the point is that the
  two differ and by how much.
* 🔴 **`trace()` owes a midscale subtraction, and the bug is currently masked by the broken decoder.**
  `src/camea/core/mearecording.py:697` is `return counts * info.lsb_uv`. The raw uint16 stream is
  **offset-binary with midscale 512** — spikeinterface's `unsigned_to_signed` computes
  `offset = 2 ** (nbits - 1)` (512 at bit depth 10) and braingeneers/braindance sets `sig_offset = 512`
  explicitly *(community)*. ⇒ Every returned trace carries a **+3,222 µV DC offset** (512 × 6.294 µV).
  Today the rail 1023 reads as 6.44 mV instead of +3.21 mV, so it looks merely wrong; the day a working
  codec arrives every trace sits 3.2 mV off zero. ⛔ Fix as `counts − median(window)`, not
  `counts − 512` (§7.4).
* ⚠️ **`amplitude_uv` is probably misnamed** (§5.1). The quantisation argument now favours ADC counts.
  ⛔ Decide the unit before any UI sorts, colours or labels by it; take `abs()` regardless; print no µV
  from it in the meantime.
* ⭐ **`mapping` is clean on this corpus — and the guard must test BOTH directions anyway.** Across all
  57 configurations no electrode and no channel is ever listed twice, and there are **zero** negative
  (sentinel) channel ids *(measured here)*. But MaxWell's own engineer says why it can happen
  *(community, python-neo #1703, verbatim)*: *"Due to the flexibility of the switch matrix design, it is
  possible to configure it such that one electrode connects to multiple readout channels, or multiple
  electrodes share the same readout channel. This can occur unintentionally during stimulation routing…
  The MxW H5 mapping structure does not support a mapping of one readout channel to a list of
  electrodes. Instead, one-to-many mappings appear as multiple rows in the mapping table."* He adds that
  the electrode-shared-by-several-channels case is safe to collapse, while the
  channel-shared-by-several-electrodes case *"should be preserved if possible, as they reflect actual
  electrical connections and may affect data interpretation"*. ⛔ **A guard that only checks
  `unique(mapping['channel']).size != len(mapping)` misses half the failure mode.** Check both columns,
  and report which.
* ⭐ **Read the file's own declaration of its assay type** — `assay/inputs/spike_only` and
  `assay/script_id` (§3.6) — rather than inferring from an empty `groups/` or a store count.
* ⭐ **`bits` is worth reading before another trace-based sync attempt** (§5.6). It is free, it needs no
  decoder, and one file in the mirror has a real 100 ms pulse in it.

---

## 8. WHAT IS STILL UNKNOWN

Honest gaps. An honest gap is worth more than a confident guess, and future sessions cannot re-check
what is asserted here.

1. ⚠️ **The detection radius — now sourced, but not on this chip.** §1.2 gives four peer-reviewed
   figures, and this closes the flat gap the 2026-08-14 draft had. ⛔ **But every one of them is a
   different array, a different preparation, or both**: Viswam 2019 is cortical culture (hardware not
   established in this chain); Radivojevic 2017 and Deligkaris 2016 are an 11,011-electrode 17.8 µm
   array with 126 channels, not a MaxOne. **No MaxOne-specific detection radius was found.** The
   in-corpus corroboration (§1.2's 20 µm collapse on `000688`) is a *rate* falloff within selected
   clusters, not a detection radius. If you find a MaxOne figure, add it with its citation.
2. ⚠️ **1,020 vs 1,024 channels — sharpened, not closed.** The product page, the glossary, the manual
   and the tutorial all say 1,020; the design paper and MaxLab's `group_define()` say 1,024; ids
   **360–363** never appear in any mapping *or any spikes table* in this corpus, and the largest routed
   set is 1,018 *(measured here)*. ⇒ The four are identified but their purpose (reference? calibration?
   test?) is not established anywhere read for this file.
3. ⚠️ **The unit of the spike `amplitude` field** (§5.1). The quantisation argument now tilts strongly
   toward **Reading A (ADC counts)**, and the counter-pull is confined to four artefact-heavy files —
   but nothing in the file labels it, and Camea's own API calls it `amplitude_uv`. Two tests would
   settle it and neither has been run:
   * ⭐ **Recompute MaxLab Live's own 6.47% under Reading B.** Under Reading A the 20 µV bar excludes no
     pad and the count lands on the vendor's 427 exactly; under Reading B every amplitude is 6.294×
     smaller (the whole range in `000687/data0003` would be 3.08–47.20 rather than 19.40–297.07), so a
     20 µV bar would bind hard and the count would fall well below 427. ⚠️ **This has not been run**, and
     it assumes MaxLab Live scored Active Area from this same field.
   * ⭐ **Decode one channel and compare a trough to the table.** Blocked by §6.
4. ⚠️ **The "211 µV median amplitude" in the repo's notes** does not reproduce as a median and looks like
   a high percentile (§5.1). The decoder verdict does not depend on it, but the note should be corrected.
5. 🔴 **The 22-versus-4 amplitude split has no explanation.** `000058`, `000690`, `000691` and `000692`
   detect at 48.5–70.9 raw field units while the other 22 sit at 6.7–13.1 — and the split follows no
   session, plate, assay, duration or acquisition setting, all of which are identical corpus-wide
   *(measured here)*. This is the most puzzling unexplained measurement in the document.
6. ⚠️ **What the experimenter actually requested** in each configuration. Every recorded artefact — the
   sidecar's `RoutedElectrodes` blob and the HDF5's `assay/inputs/electrodes` — stores the routed
   **outcome**, byte-identical to `settings/mapping`. ⇒ **Routing yield cannot be measured from these
   files at all** (§2.3). The only figure available is Duru et al.'s published 90.1%.
7. ⚠️ **Selection method for four of the five 260801 Network runs.** `000688` records
   `selection_algorithm=3` and `scan_assay_id=000687`; the other four record `selection_algorithm=0` and
   an empty `scan_assay_id`, which establishes only that **no scan was referenced**. The integer→method
   mapping is undocumented. "Hand-drawn" remains an inference from shape (§3.5).
8. ⚠️ **BL1 vs BL2 in the switch-matrix bitstream** (§2.2) — undocumented; the interpretation is
   inference and nothing should be built on it.
9. 🔴 **The cause of the `000691` → `000692` shift** (§4.4). Four measured properties point at recording
   conditions rather than biology, and the lamp-episode fractions (8.7% vs 54%) are consistent with
   that. The 1 ms mass-synchrony control rules out instantaneous coincidence only — ⛔ **it does not
   clear the lamp**, whose documented artefact is seconds-long episodes.
10. ⚠️ **Does `bits` carry a TTL in the other 27 files?** Only the six 260801 files were checked (§5.6).
    ⭐ Cheap to answer and directly useful to issue 003.
11. ⚠️ **Is the decoder failure specific to writer `22.2.22` / format `20190530`?** No public report of
    this failure mode exists anywhere (§6), and SpikeInterface's CI runs Maxwell tests against 2021
    fixtures. ⇒ The scope of the failure is unestablished, and "the public plug-in is broken" is a claim
    this document deliberately does **not** make in general.
12. ⚠️ **How the chip sits in the mosaic** — which corner of the image the chip's origin landed in. Four
    seatings; nothing in any file records it; two attempts to resolve it from data came back null.
    Separate problem, tracked in issue 003.
    ⭐ **What this document adds. First: MaxWell's own answer is a human clicking four corners** (§3.7).
    There is no automatic registration in the vendor's software either, which is worth knowing before
    another automatic attempt. ⚠️ If an `.align` file was made during acquisition it holds the **warped
    image**, not the matrix — the transform would have to be recovered by comparing it against the
    original. **Worth asking him whether one exists.**
    ⭐ **Second: for P003693 the null is now explained rather than merely observed.**
    `orientation.py`'s strong half is *coverage* — which seatings put routed pads under the imaged
    region — and it settled P003658 outright (1 of 4 seatings, 210 pads) while P003693 returned "cannot
    tell", margin 0.004 *(cited: `utils/knowledge/mea-recordings.md`)*. §2.4 family C says why:
    `000691`/`000692` route a **perfectly uniform 87.5 µm lattice spanning 216 × 111 of the chip's
    220 × 120 cells**, so every seating puts a comparable number of pads under any region — the note
    measured ~85 each, for all four. ⛔ **Coverage cannot discriminate a near-full uniform configuration,
    by construction, and no amount of correlation rescues it.**
    ⚠️ Worse, the degeneracy is close to exact. From the measured spans (`ex` 2–217 and `ey` 4–114, in
    steps of 5): a left–right flip maps `ex → 219 − ex`, which carries {2, 7, …, 217} onto **itself** —
    the two left–right seatings are *identically* covered. A top–bottom flip (`ey → 119 − ey`) carries
    {4, 9, …, 114} to {5, 10, …, 115} — offset by **one chip cell, 17.5 µm**, against an 87.5 µm lattice
    *(arithmetic from spans measured here; the row count it depends on is an observed maximum, §2.1)*.
    ⇒ *(inferred)* All four seatings of P003693 are separated by at most one chip cell of coverage
    difference. ⭐ **`orientation.py` should detect near-uniform full-array coverage and refuse by name**
    — *"this configuration carries no orientation evidence"* — rather than returning a thin margin that
    reads like a weak measurement. Corner-block configurations (P003658-style) remain the only ones where
    coverage can decide.
13. ⛔ **CORRECTIONS OWED TO THE REPO'S OWN NOTES — this document contradicts them and is right.** They
    matter more than the usual note drift because `utils/knowledge/mea-recordings.md` is **injected into
    every new chat by a SessionStart hook**, so an uncorrected sentence there outvotes a correct one here
    by default.
    * 🔴 *"The 23–62 % zero-spike fractions above are **biology**, not hardware failure."* — the "not a
      fault" half is right and is the design conclusion; **"is biology" is not established**, and §4.4
      measures against it on the very pair at the 62% end. Also the range is this document's **0%–62%**
      across 26 runs, not 23–62% across five.
    * ⚠️ *"90–99 % of live pads land in the darkest tenth on every one of his recordings"* — the note's
      **own table** says 72% for `000688`, so the range is **72%–99%** across the five files it covered
      (§7.2). `web/src/features/mea/activityScale.ts`'s header repeats the same wrong summary and needs
      the same edit. The conclusion (linear is refuted) is untouched.
    * ⚠️ *"MaxWell's own detector, median spike amplitude 211 µV"* (§8.4) and the
      `spike_threshold`-is-ActivityScan-only claim (§5.2).
    * ⚠️ **The open question "are the multiple data stores wells or configurations?" is CLOSED** — the
      vendor's own metadata table says configurations (§3.2).
    * ⚠️ *"MaxTwo = 6 wells"* is incomplete: 6-Well and 24-Well+ ship, 96-Well is announced (§3.2).
    * ⚠️ The `gain_uV = 3.3/(1024*gain)*1e6` fallback in `maxwell-ids.md` agrees with the stored `lsb`
      to **8 significant figures, not exactly** — the firmware's 3.3 is a float32 (§5.2). A test
      asserting equality would fail.
    ⛔ **Six corrections, one file, none of them applied yet** — this document cannot apply them; whoever
    reads it next should.
14. ⛔ **CLAIMS THAT WERE DROPPED IN VERIFICATION AND MUST NOT BE RESURRECTED.** Each was in an earlier
    pass, each failed a check, and each is the kind of thing a future session would otherwise re-derive:
    * *"The 691/692 swing is not an artefact of the 2P lamp"* on the strength of a ±1 ms mass-synchrony
      test. Wrong timescale — the lamp artefact is *sustained episodes lasting seconds*, which a 2 ms
      coincidence test is blind to by construction. **The lamp is not ruled out.**
    * *"The routed 4% is the best 4% by construction"* — true of the MaxLab workflow Habibey describes,
      **false of his files**: 19 of 26 are geometric lattices with no activity input (§2.4).
    * *"A fully dense contiguous patch cannot use the whole channel budget."* Unsupported by any source
      — Duru's 23 × 23 guarantee is a *lower* bound on routability, not an upper one (§1.1).
    * *"Each ActivityScan config is a perfect checkerboard on the even sublattice at 35 µm."* False for
      Sparse7x (odd sublattice, fully filled) and wrong even for Sparse4x, whose checkerboard leaves
      neighbours 49.5 µm apart diagonally and 70 µm axially (§3.1).
    * *"Sparse7x config 0 is a full-width comb."* It is two 7-column bars at opposite edges (§3.1).
    * *"Amplitude is not LSB-quantised, therefore it is not ADC counts."* Neutral — the field is a
      continuous float in either unit (§5.1).
    * *"The unmapped-spike fraction rises as the routed set shrinks"* as a rule. It is a tendency with
      counter-examples (§5.3).
    * *"The 22–25% missing lattice points in `000689`/`000690` are almost certainly switch-matrix
      losses."* Three explanations are live and none is provable from these files (§2.3).
    * *"MaxOne chips, not MaxTwo"* presented as measured. No file names a device model; `wellplate/version
      = "MaxOne Single Well MEA"` is a **wellplate** string, and the inference is a good one but is an
      inference.
    * ⚠️ Three **citation swaps** that would send a reader to a paper that does not exist under that name:
      Front. Neurosci. 16:829884 is **Duru** et al., not Girardin; 16:943310 is **Sato** et al. (2023),
      not Duru; 10:421 is **Deligkaris, Bullmann & Frey**, not Bakkum. The content of all three verified;
      the attributions did not.

---

## 9. SOURCES

**Vendor.**
* **MaxWell Biosystems, MaxOne product page** (mxwbio.com/products/maxone-mea-system-microelectrode-array),
  retrieved 2026-08-14. Source of: 26,400 electrodes, **1,020 recording channels**, 17.5 µm pitch,
  11.5 × 11.5 µm electrode, 3,265 electrodes/mm², 3.85 × 2.10 mm² sensing area, 20 kHz per channel,
  2.2 µVrms typical noise, and the MaxOne+ PEDOT variant.
* **MaxWell Biosystems, MaxTwo product page** (mxwbio.com/products/maxtwo). 6-Well Plate (Platinum
  Black, 12.0 × 8.8 µm²) and 24-Well Plate+ (PEDOT, 11.5 × 11.5 µm²), *"Ready for the upcoming 96-Well
  Plate format"*, 1'020 channels **per well**, "6 × 26'400" / "24 × 26'400", all wells in parallel.
  ⚠️ Its spec table says **10.0 kHz/channel** while MaxTwo prose elsewhere on the same site says 20 kHz.
* **MaxWell Biosystems, "Our Technology"** (mxwbio.com/our-technology). The switch-matrix description
  quoted verbatim in §1.1, and *"Up to 32 stimulation buffers on each MxW HD-MEA can be flexibly assigned
  to any of the 26,400 electrodes"*.
* **MaxLab Live user manual, v25.1** — 161-page PDF, retrieved 2026-08-14 from integra-biosciences.com
  (a MaxWell distributor) and text-extracted so every quote here could be checked word for word. Pages
  cited by **printed page number**: p.23–24 (Table 7, selection tools) · §3.1 (numbering and origin) ·
  §3.1.1 ("at most 1020 electrodes") · **§3.1.2 (Background Image, the four-corner Align, `.align`)** ·
  §4.2 (Predefined/Custom configurations) · §5.2 ("not all 1020 recoding channels are always connected")
  · §7.1 and p.66 (Table 20, scan presets) · §7.1.2 (scan outputs) · p.67 (active-electrode definition,
  spike-amplitude p90, scan durations) · p.68 (the three electrode sources, 10 s minimum) · **p.69 (the
  switch-matrix routing constraint — occurs exactly once in the manual)** · p.70 (§7.2.3, Table 21,
  Network Selection step 3) · p.71 (which methods may select unrecorded electrodes) · p.73 (Record assay
  limits) · p.75–76 and Table 22 (AxonTracking) · §7.5.2 and p.86 (Stimulation routing constraints) ·
  §8 metadata table (**"Number of Configurations"** — the sentence that settles §3.2) · p.105 (Active
  Area export definition).
* **MaxLab Live Python API docs** (api-docs.mxwbio.com) — `Config` constructor (the
  `<channel>(<electrode>)<X>/<Y>` string and the top-left origin) · `Array.select_electrodes` (the weight
  parameter) · `Array.select_stimulation_electrodes` (the 1,020 convergence warning — ⚠️ **stimulation**,
  not recording) · `connect_electrode_to_stimulation` (*"needs already be routed to an amplifier"*) ·
  `Amplifier.set_gain` (the seven valid gains) · `maxlab.util.set_event_threshold` (*"in standard
  deviations away from the mean"*, default 5.0) · `group_define` (channels 0–1023) · the C++
  `maxlab::SpikeEvent` struct · the **glossary** (1020 readout channels around the periphery; 32
  stimulation units; **"Floating amplifier"**) · the tutorial (1020 recording / 32 stimulation electrode
  caps, `set_event_threshold(8.5)`).
* **MaxWell's decoder plug-in share** — `https://share.mxwbio.com/d/7f2d1e98a1724a1b8b35/`, unversioned.
  ⛔ Never commit the binary to this repo.
* **MaxWell resources page** — links Zegers-Delgado et al. 2026 (below) as a MaxOne study.

**Papers.** ⚠️ **Read the hardware column in §1.2 before transferring any of these to a MaxOne.**
* **M. Ballini et al., "A 1024-Channel CMOS Microelectrode Array With 26,400 Electrodes for Recording and
  Stimulation of Electrogenic Cells In Vitro," IEEE J. Solid-State Circuits 49(11):2705–2719, 2014.
  DOI 10.1109/JSSC.2014.2359219, PMID 28502989, PMCID PMC5424881.** The chip's design paper — 1,024
  on-chip readout channels, 26,400 Pt electrodes, 3.85 × 2.10 mm², 17.5 µm pitch, 10-bit single-slope
  ADCs at 20 kS/s, gain to 78 dB, 32 stimulation units, 75 mW, and the noise figures in §5.2.
  ⚠️ Full text unreachable (Europe PMC returns 404 for the XML) — abstract verified verbatim.
* **J. Müller et al., "High-resolution CMOS MEA platform to study neurons at subcellular, cellular, and
  network levels," Lab on a Chip 15:2767–2780, 2015.** Independent statement of the array geometry.
* **M. E. J. Obien, K. Deligkaris, T. Bullmann, D. J. Bakkum & U. Frey, "Revealing neuronal function
  through microelectrode array recordings," Front. Neurosci. 8:423, 2015. PMC4285113.** The switch-matrix
  architecture rationale; *"typically not all electrodes exhibit activity"*; the scan-then-select protocol.
* **J. Duru, J. Küchler, S. J. Ihle, C. Forró, A. Bernardi, S. Girardin, J. Hengsteler, S. Wheeler,
  J. Vörös & T. Ruff, "Engineered Biological Neural Networks on High Density CMOS Microelectrode
  Arrays," Front. Neurosci. 16:829884, 2022. PMC8900719.** *"An almost arbitrary combination of up to
  1,024 electrodes"*; the 23 × 23 patch guarantee; **685 of 760 routed (90.1%)**.
  ⚠️ Frequently mis-cited as "Girardin et al." — Girardin is the sixth of ten authors.
* **R. Habibey et al., Front. Neurosci. 16:951964, 2022.** hiPSC-derived iNGN neurons on a **MaxOne**;
  the 29-configuration Full scan → 1,024-electrode Network workflow; the 22/49/83 dpi time course;
  neuron migration of 224.00 ± 10.10 µm over two months; and the *"more than 0.1 Hz AP frequency and
  average AP amplitude more than 20 μV"* active-electrode criterion. ⚠️ Uses the **mean** amplitude, not
  the manual's 90th percentile.
* **V. Viswam et al., "Optimal Electrode Size for Multi-Scale Extracellular-Potential Recording From
  Neuronal Assemblies," Front. Neurosci. 13:385, 2019.** Somatic amplitudes 0.02–1.7 mV falling to 20%
  of peak by 20–100 µm; axonal 1–50 µV localised within 20–30 µm. **Cortical cell cultures**; the array
  model was not established in this chain.
* **M. Radivojevic et al., "Tracking individual action potentials throughout mammalian axonal arbors,"
  eLife 6:e30198, 2017.** Amplitude–distance dependence only within 100 µm of the AIS; no strong decay
  100–1,400 µm; one neuron's image over 1,200 electrodes. **11,011-electrode, 17.8 µm, 126 channels.**
* **K. Deligkaris, T. Bullmann & U. Frey, "Extracellularly Recorded Somatic and Neuritic Signal Shapes
  and Classification Algorithms for High-Density Microelectrode Array Electrophysiology,"
  Front. Neurosci. 10:421, 2016.** 86% somatic / 14% neuritic; −171.46 µV vs −73 µV. **Rat cortical
  E16–18, 14–58 DIV, 11,011-electrode hexagonal 17.8 µm array.** ⚠️ Often mis-cited as "Bakkum et al."
* **M. Fiscella et al., "Recording from defined populations of retinal ganglion cells using a
  high-density CMOS-integrated microelectrode array with real-time switchable electrode selection,"
  J. Neurosci. Methods 211:103–113, 2012.** *"the activity of each RGC on 14 ± 7 electrodes"*, with
  *"multiple, highly overlapping RGCs"*. **Mouse retina, 126-channel array.** ⛔ Not a per-cell divisor.
* **J. Zegers-Delgado, N. Renegar, K. Pathirage, T. K. Horiuchi, P. Abshire & R. C. Araneda, "A fast and
  simple algorithm for accurate spike detection in HD-MEA recordings," J. Neurosci. Methods 431:110750,
  2026.** RMS-threshold detectors under-count during bursts. **MaxOne, cortical cultures, one lab.**
  ⚠️ An earlier pass cited this as "Cuevas-Diaz et al." — that name appears nowhere in connection with it.
* **Y. Sato et al., Front. Neurosci. 16:943310, 2023.** 85.9 ± 23.7 active electrodes per network
  (n = 31) at FR > 0.02 Hz. ⚠️ **Not verified** that the array was a MaxWell.
* **G. Buzsáki & K. Mizuseki, "The log-dynamic brain: how skewed distributions affect network
  operations," Nat. Rev. Neurosci. 15:264–278, 2014.** Cited for the phenomenon, ⚠️ not for a quotation —
  full text was unreachable.
* **L. Mapelli et al., PLOS One 20:e0328903, 2025** (3Brain 64 × 64 planar vs 3D, acute slices) and
  **R. Yokoi et al., Front. Neurosci. 19:1634582, 2025** (236,880-electrode array, organoids). Context
  only, in §4.3's comparison table.
* ⚠️ **UNVERIFIED — JoVE 68493 / PMC12710770 / PMID 40658718** (retinal-wave HD-MEA protocol), cited
  elsewhere for an 87.5 µm default spacing. Could not be retrieved by three routes. Do not quote it as
  read. ⭐ The number itself does not need it: the arithmetic is forced (26,400 / 1,020 ≈ 26, and a 5 × 5
  subsample gives 1,056 positions, just over the ceiling) and `000691`/`000692` route a measured, exact
  5-step lattice of 1,012.

**Community — open-source readers and public issue threads.**
* `neo/rawio/maxwellrawio.py` — the three file layouts, the `gain_uV` fallback,
  `auto_install_maxwell_hdf5_compression_plugin` and the plug-in URLs, and *"This implementation does not
  handle spikes at the moment"*.
* `spikeinterface` — `MaxwellEventExtractor` (reads the top-level `bits` group), `unsigned_to_signed`
  (`offset = 2 ** (nbits - 1)`), PR **#3961** (merged 2025-05-30, auto-installs the plug-in), PR **#4018**
  (MaxWell spike/stimulation events + channel de-duplication, **closed unmerged** 2025-08-09).
* `probeinterface/io.py::read_maxwell` · `braingeneers/braindance` (`sig_offset = 512`; gain options
  512/1024/2048) · `project-hal.github.io/electrode_map.html` · four independent code bases that agree on
  row-major-over-220 (`nomuwill/SynapSideKick`, `LoaloaF/ephysVR`, `braingeneers/braindance`,
  `hornauerp/axon_tracking`).
* **python-neo issue #1703** — a MaxWell engineer on duplicate mapping rows, quoted verbatim in §7.6.

**Measured here.** `d:\Projects\Camea\data\` — 33 `data.raw.h5` recordings (26 Network, 7 ActivityScan;
57 routing configurations; 49,367 mapping rows) across sessions **260529**, **260620**, **260801** and
plates **P002137**, **P002731**, **P003658**, **P003693**, plus their `.mxassay` sidecars and run logs.
Read-only, 2026-08-13/14, with `h5py`, `numpy`, `scipy` and `src/camea/core/mearecording.py`.
⛔ `data/` is a read-only mirror and nothing in this work wrote to it.

**In this repo.** `src/camea/core/mearecording.py` (the module header is the short form of §6) ·
`src/camea/features/mea/routes.py` · `web/src/features/mea/activityScale.ts` (the scale this document
unblocks) · `web/src/features/mea/OpenRecording.tsx` · `docs/BEHAVIOUR.md` (invariant I1, R45.1 as amended by R45.8) ·
`workflow/issues/medium/007-activityscan-refused-as-not-maxlab.md` ·
`workflow/issues/high/003-mea-lamp-sync-does-not-validate.md` · `utils/knowledge/mea-recordings.md` and
`utils/knowledge/maxwell-ids.md` (⛔ six corrections owed — §8.13).
