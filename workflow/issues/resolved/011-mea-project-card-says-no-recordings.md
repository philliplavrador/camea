---
id: 011
title: An Analyze MEA project's card says "No recordings yet" no matter how many it has
kind: bug
tier: medium
confidence: high
status: fixed
found: 2026-08-15
found-while: building plan 004 — opening his real MEA project in a browser to check the trace panel
resolved-by: fixed on the spot, 2026-08-16 — the mea counts hook fills n_tiles from the shelf
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

## How it was resolved

Exactly the shape "Where to start" proposed, taking the existing per-feature count slot rather
than a new MEA-only field: `features/mea/document.py :: counts` now returns
`{"n_tiles": len(doc["recordings"])}` — **derived from the document's shelf when the summary is
built, never stored beside it** (I1) — and the card
([ProjectManager.tsx](../../../web/src/features/home/ProjectManager.tsx)) renders it in the
feature's own words: *"5 recordings"*, with *"No recordings yet"* kept for the genuinely empty
shelf (count 0), the state the line was written for. Proven by
`tests/api/test_mea_feature.py :: test_the_summary_counts_the_shelf_so_the_home_card_can_say_it`
(the count follows a remove, because nothing was stored) and the
`new-project-tasks.spec.ts` card test.
