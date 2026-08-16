---
id: 008
title: MEA import accepts a file whose chip layout cannot be derived — it lands on the shelf and then refuses to open
kind: bug
tier: medium
status: fixed
found: 2026-08-14
found-while: the api-contract-guard review of plan 003 (the chip map and pad traces)
resolved-by: fixed 2026-08-16 — facts_of touches the mapping too, so the refusal is at the door, and the tick-list still lists the file greyed with the reason
---

# 008 — Import accepts a recording that cannot then be opened

## What happens

`features/mea/recordings.py :: facts_of` decides whether a file is a MaxLab recording, and it reads
**only the header** — `MeaRecording.info()`, which touches `settings/*` and the raw stream's
*shape*. It never touches `settings/mapping`.

But the chip's geometry is derived in `MeaRecording.mapping()`, and `derive_geometry` **refuses by
design** for cases it cannot explain:

* every routed pad on one array row (the stride is then unconstrained by the data);
* electrode ids that are not a consistent `row × stride + column` numbering;
* positions that are not whole multiples of one pitch.

So a file with a good header and an underivable mapping **imports cleanly** — it is accepted at
`POST /api/mea/projects`, a project is created, and it sits on the shelf with its duration, channel
count and spike count all showing. It is only when he clicks **Open** that Camea refuses.

## Why it is `medium` and not `high`

It costs nothing irreversible: no dataset knowledge is written, nothing lands in `data/`, no
verification hours are at risk, and the refusal on opening is now honest and specific (plan 003
made it a `422 refused` naming the real reason — *"the routed electrodes all sit on one array row"* —
rather than the `500` it used to be). The damage is that he is told **twice** and told **late**:
the shelf implies a working recording, and the refusal arrives one click further in than it needed
to.

## Why it was not fixed in plan 003

`facts_of` is plan 002's module and is not in 003's § Affected. Changing what the importer accepts
changes 002's tested contract in a way that wants its own thinking — in particular whether a file
Camea can *read* but cannot *lay out* should be refused at the door at all, or whether the shelf
should show it and mark it un-openable. **That is a real design question, not a typo**, and it is
adjacent to [007](007-activityscan-refused-as-not-maxlab.md), which is the mirror image: a genuine
MaxLab file the reader refuses for a different missing piece.

## Repro

`tests/api/test_mea_feature.py :: test_a_file_whose_CHIP_LAYOUT_cannot_be_derived_is_refused_not_a_500`
builds exactly this file (four pads, all on row 0) and asserts the *opening* refusal. Its first
line notes that the import succeeds — that line is this issue.

## The fix, when someone takes it

Probably: have `facts_of` touch `mapping()` as well as `info()`, so one function decides "is this a
recording Camea can work with" and the answer is the same at every door. ⚠️ Check what that does to
`GET /api/mea/browse` first — a file that becomes un-tickable in the picker must still be **listed**
with `readable: false` and a reason, never silently dropped, which is the rule 002 built the
tick-list around.

⚠️ And decide it together with [007](007-activityscan-refused-as-not-maxlab.md). Both are *"a real
MaxLab file that this reader will not open"*, and answering them separately is how the app ends up
with two different sentences for the same situation.

## How it was resolved

Exactly the shape § "The fix, when someone takes it" proposed, decided together with
[007](../resolved/007-activityscan-refused-as-not-maxlab.md) so the app has one sentence per
situation rather than two. `features/mea/recordings.facts_of` now touches **`mapping()` as well as
`info()`**, so one function decides "is this a recording Camea can work with" and the answer is
the same at every door: the import (both doors — creation and add-to-shelf) refuses **before**
anything is made, with

> *"Camea cannot work out the chip layout for 000009/data.raw.h5: the routed electrodes all sit on
> one array row, so the chip's layout cannot be derived from this file"*

— the reader's own reason, the same wording the open-time refusal already used, and never *"not a
MaxLab recording"* (it **is** one). The ⚠️ this issue flagged is honoured: `GET /api/mea/browse`
still **lists** such a file, greyed with `readable: false` and the derive reason as its `problem`
— refused at the door is not dropped from the list. The open-time 422 arm stays, because a file
can change under an existing shelf entry, and the repro test now proves that path by corrupting
the project's own copy after a clean import. Proven by
`tests/api/test_mea_feature.py :: test_a_file_whose_CHIP_LAYOUT_cannot_be_derived_is_refused_AT_THE_DOOR`
and `:: test_a_recording_whose_layout_BREAKS_AFTER_IMPORT_still_refuses_by_name_not_a_500`.
