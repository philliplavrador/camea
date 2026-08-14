---
id: 003
title: The 2P-lamp sync signal does not validate against the calcium video — orientation test blocked
kind: finding
tier: high
status: open
found: 2026-08-13
found-while: building the MEA voltage panel, then starting the chip-orientation test he approved
resolved-by: ~
---

# 003 — The 2P-lamp sync signal does not validate against the calcium video

## Why this is high

It sits directly on the thing this repo protects: **which electrode a neuron's calcium trace is
paired with.** The planned orientation test would settle that pairing, and it was about to be built
on a signal that does not survive checking. A test built on it would return a confident-looking
winner from noise — a laundered machine guess, in the one place the project least tolerates one.

## What was expected

His account, 2026-08-13:

> *"the people who collected this data turned on and off the 2P lamp a lot to cause artifacts on the
> MEA trace, that way the calcium trace and the MEA traces could be synced."*

If so, the MEA's synchronous artefacts and the calcium video's illumination should line up at one
constant clock offset — which would align the two clocks and let the four chip seatings be scored by
spike/calcium coincidence. That is the approach he chose.

## What was actually measured

**1. The MEA side does show synchronous episodes.** Hundreds of channels leave the rail in the same
instant (P003658: 442 channels at t≈25 s). Detected by `MeaRecording.sync_episodes`.

| Recording | Sustained episodes (>0.5 s) | Coverage |
|---|---|---|
| P003658/000690 | 2 (24.8–33.5 s, 45.9–54.3 s) | 5.7% |
| P003693/000691 | 30 | 8.7% |
| P003693/000692 | 70 | 54% |

**2. The video side does not match them.** Whole-frame brightness, dark = lamp off:

| Video | Duration | Dark intervals |
|---|---|---|
| P003658 activity.mp4 | 297.9 s | 2 — `0–3.37 s`, `13.09–21.85 s` |
| P003693 activity.mp4 | **416.3 s** | 5, one of them **72 s** (`46.85–119.02`) |

P003693/000692 has **70** MEA episodes and its video has **5** dark intervals. Those cannot be the
same events. (P003693's video is also 416 s against a 300 s MEA recording, so the two are not
even the same span — worth resolving separately.)

**3. No constant offset aligns them.** Scanning offsets ±120 s and scoring Jaccard overlap of the
two indicator signals:

```
P003693/000691   best vs video DARK  : 0.169 at +98.5s
                 best vs video BRIGHT: 0.192 at  +1.4s
P003693/000692   best vs video DARK  : 0.332 at +120.9s
                 best vs video BRIGHT: 0.646 at -87.5s
```

0.646 sounds high until you notice 000692's episodes cover 60% of its recording and video-bright
covers 80% — two mostly-on signals overlap that much by chance. And the best offsets disagree by
over 200 s between two recordings of the same session, so there is no consistent clock relationship.

The one genuine near-miss: P003658's video dark interval is **8.76 s** and its first MEA episode is
**8.67 s**, at an offset of ~11.7 s. Durations agreeing to 0.09 s is suggestive — but the *second*
MEA episode has no counterpart in the video at that offset, so a single coincidence is all it is.

## ⭐ The confound that probably explains it

`sync_episodes` counts **channels whose sample differs from the rail value**. But the raw stream does
not decode (see `utils/knowledge/mea-recordings.md`): 98% of samples come back as one fill value. So
"off-rail" largely measures *where the decoder emitted anything at all*, and that tracks signal
complexity — which is exactly what a partial decoder would do. Supporting number: spiking channels
are 30.9% non-fill against 1.5% for silent channels in the same window.

**So the "synchronous episodes" may be an artefact of the broken decode rather than the lamp**, and
there is currently no way to tell the two apart.

## Built anyway, on his instruction (2026-08-13)

He was shown all of the above and chose to have the test built regardless. It is
`features/videomosaic/orientation.py` + `POST /api/videomosaic/mea/orientation`, and it carries the
caveat above verbatim on screen, never behind a `?`.

⭐ **One good thing came out of it that does not depend on any of the doubts here.** The test scores
*coverage* as well as correlation, and on P003658 exactly one of the four seatings puts any recorded
electrode under the located region (210 of 1304 pads; the other three put zero). That is geometry —
independent of the clock alignment AND of the decode — so it is the strongest evidence available,
and it decided that project. P003693 routed nearly the whole chip, so coverage separates nothing
there and its four correlations land within 0.004: the job reports **cannot tell** and offers no
winner rather than crowning noise.

So the correlation half of the test remains untrustworthy until the decoder is fixed; the coverage
half is sound today. Nothing is confirmed on either project — the flow was verified and then reset.

## What unblocks it

Get the real decoder — `compression.dll` from the acquisition PC's MaxLab Live install (files stamp
`mxw_version 22.2.22`) — and re-run the three measurements above. With a correctly reconstructed
trace, a lamp artefact is an unmistakable full-array excursion and this becomes easy. Until then the
orientation test cannot be validated, and `Orientation.confirmed` correctly stays `false`.

Reproduce: `scratchpad/align_check.py`, `probe_video_lamp.py`, `dark_intervals.py` from the
2026-08-13 session (method fully described above).
