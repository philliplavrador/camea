---
id: 007
title: A real MaxLab ActivityScan is refused as "not a MaxLab recording"
kind: defect
tier: medium
status: open
found: 2026-08-14
found-while: building plan 002 — the import tick-list was pointed at the real 260801 MEA folder and one of the six rows came back refused
resolved-by: ~
---

# 007 — `ActivityScan/000687` is a genuine MaxLab file, and Camea says it is not one

## What's wrong

Pointing the new import tick-list at `data/drive/260801/MEA` lists **six** recordings. Five read
fine. The sixth is greyed with the words **"not a MaxLab recording"**:

```
000687                                              not a MaxLab recording
Network/000688      3m 0s · 982 channels · 244,925 spikes · 1.04 GB
Network/000689      5m 0s · 1015 channels · 3,770 spikes · 1.78 GB
Network/000690      5m 0s · 726 channels · 22,367 spikes · 1.11 GB
Network/000691      5m 0s · 1012 channels · 75,661 spikes · 1.53 GB
Network/000692      5m 0s · 1012 channels · 79,240 spikes · 1.55 GB
```

⭐ **It is a MaxLab recording.** `data/drive/260801/MEA/P002731/ActivityScan/000687/data.raw.h5`
carries `mxw_version`, `wellplate`, `wells`, `assay/run_id` — everything a MaxLab file carries. The
refusal is a **lie about his data**, which is the one class of failure this app exists not to
commit.

## Why it happens

An **ActivityScan** is a spike-only assay. It has **seven** data stores rather than one, and
`data0000/groups` is **empty** — there is no continuous raw stream at all:

```
data_store/          data0000 … data0006          (seven, not one)
data0000/groups      []                            <- no `routed/raw`
data0000/settings    gain hpf lsb mapping sampling spike_threshold
data0000/spikes      present
```

[`core/mearecording.py`](../../../src/camea/core/mearecording.py) hard-codes
`_STORE = "data_store/data0000"` (fine here) and `MeaRecording.info()` reads
`g["groups/routed/raw"]` to get `n_channels` / `n_samples` off its **shape**. There is no such
dataset, so h5py raises `KeyError: 'Unable to synchronously open object (component not found)'`,
which `features/mea/recordings.facts_of` turns into `NotARecording`.

## ⭐ Why this is worth more than a wording fix

**The file has `settings/mapping` and `spikes`.** Those are exactly — and only — what
[plan 003](../../plans/queued/003-analyze-mea-chip-map-and-traces.md)'s chip map and activity
colouring need, and 003's whole selling point is that they *"need no proprietary decoder"*. So an
ActivityScan is not a file Camea can merely tolerate: it is a file for which **the entire 003
screen would work perfectly**, minus the trace panel, which has nothing to draw anyway on a machine
where the decoder does not work.

Refusing it at import means he cannot get it onto a shelf to look at it.

## What "fixed" looks like

⛔ **Not** a special case in `features/mea/`. This belongs in `core/mearecording.py`, with its own
test, exactly as plan 002 § Approach says: *"if it needs something new, add it there."*

1. `info()` should fall back when `groups/routed/raw` is absent: `n_samples = 0`, and
   `n_channels` from `settings/mapping`'s length. A spike-only recording has no sample count, and
   `0` said plainly beats a refusal.
2. `trace()` / `trace_health()` / `sync_episodes()` must then refuse **by name** for such a file —
   *"this recording has no continuous trace"* — which is a different and more useful sentence than
   *"the decoder is missing"*.
3. ⚠️ **The seven data stores are a separate question and probably a separate issue.** Reading only
   `data0000` of a seven-store scan may be showing one well of seven. Nobody has checked which.
   Do not quietly widen `_STORE` without deciding what a "recording" means when a file holds seven.

## Why medium, not high

It refuses real data he has, which is worse than cosmetic — but it refuses it **honestly and
visibly**, by name, on the list (plan 002's tick-list lists unreadable files rather than dropping
them). Nothing is lost, nothing is corrupted, and the five recordings he actually asked about all
work. It is not one of the four that are always high: no dataset knowledge, no write to `data/`, no
engine change, no write outside `<project>/outputs/`.
