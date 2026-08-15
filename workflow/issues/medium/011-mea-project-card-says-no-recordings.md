---
id: 011
title: An Analyze MEA project's card says "No recordings yet" no matter how many it has
kind: bug
tier: medium
confidence: high
status: open
found: 2026-08-15
found-while: building plan 004 — opening his real MEA project in a browser to check the trace panel
resolved-by: ~
---

# 011 — An Analyze MEA project's card says "No recordings yet" no matter how many it has

## What's wrong

On the project manager — the first screen he sees — an `Analyze MEA` project **always** shows
*"No recordings yet"*, even when it holds five. Open the same project and the very next screen says
*"5 recordings"*. The card is stating something false about a project's state, on the screen whose
whole job is telling him what state his projects are in.

The line is not a bug in itself: it exists because `Analyze MEA` is a shelf filled from *inside* the
project, so the card would otherwise have a blank where every other task shows its dataset's name,
and a blank reads as a card that failed to load. The bug is that nothing ever replaces it, because
**`AnalysisSummary` carries no recording count** — `dataset` and `dataset_key` are deliberately empty
for MEA projects (a recording is a file on the shelf, not the project's dataset), and there is no
other field to fall back on.

It should say how many recordings are on the shelf, and keep *"No recordings yet"* for the genuinely
empty case — which is a real state, and the one it was written for.

## Evidence

The constant, and the only thing that decides the line:

- [ProjectManager.tsx:50](../../../web/src/features/home/ProjectManager.tsx#L50) —
  `const NO_INPUT_YET: Record<string, string> = { mea: 'No recordings yet' };`

The summary the card is built from has nothing to count. Measured against his own project, which has
five recordings on its shelf:

```console
$ curl -s http://127.0.0.1:8000/api/projects | python -c "...filter feature=='mea'..."
{'analysis_id': 'p003658-19cc31', 'feature': 'mea', 'n_tiles': None, 'dataset': '', 'dataset_key': ''}

$ curl -s http://127.0.0.1:8000/api/mea/p003658-19cc31/recordings | grep -c '"recording_id"'
5
```

`n_tiles` is `None` and `dataset` is `''`, so every branch the card could use is empty. Seen in the
browser at `http://127.0.0.1:5173/` on 2026-08-15: the card read *"MEA Viewer · Analyze MEA · No
recordings yet"*, and clicking it landed on *"5 RECORDINGS"*.

## Where to start

`AnalysisSummary` would need a count the MEA feature fills in — the mosaic tasks already put their
own number in `n_tiles`, so there is a precedent for a per-feature count on that model rather than a
new MEA-only field. ⚠️ It must be **derived when the summary is built, not stored in the document**
— I1, and `features/mea/recordings.py`'s own header is explicit that nothing about what is *in* a
recording is ever written down.

Not caused by plan 004 and not touched by it; this has been true since the shelf existed
(plan 002/003). Filed rather than fixed because it is outside that plan's scope and changing a
shared API response model deserves its own change.
