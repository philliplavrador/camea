---
id: NNN
title: <one line, what is wrong — not what to do about it>
kind: bug # bug | ux
tier: medium # high | medium | low
confidence: high # high | medium | low — required for kind: ux, optional for bug
status: open # open | resolved | wont-fix
found: YYYY-MM-DD
found-while: <what the session was actually doing when it hit this>
resolved-by: ~ # plan NNN, or a commit sha — set when it moves to resolved/
---

# NNN — <title>

## What's wrong

Two or three sentences. What the code does, and what it should do instead. Write it so
it still makes sense to someone who wasn't in the session that found it.

**If this is `kind: ux`**, name a real screen or flow, say what a first-time user actually
experiences there, and propose in one sentence the alternative you think is better. Without
all three it can't be acted on — "this is awkward" leaves the next session nothing to
compare against. Remember who uses this: a biologist with little maths, who has never seen
the word *serpentine*.

## Evidence

**This section is the one that matters.** An issue without it is a rumour, and a future
session has to redo the investigation before it can trust the file.

- A `file:line` as a markdown link. **An issue sits one level deeper than this
  template**, so its links out of `workflow/issues/<tier>/` start with `../../../` —
  link text `t33.py:88`, target `../../../src/camea/engine/t33.py#L88`.
- A command that reproduces it, and what it printed
- A number, and how you measured it

**A measured number beats a read of the code**, especially here — the placement engine's
behaviour is not obvious from reading it, and several confident readings have been wrong.
If you can run it, run it.

## Why this tier

One line. Camea has no users yet, so the ruler is not somebody's morning — it is
[the two things this repo protects](README.md#the-tiers-concretely): the science, and the
hours of hand-verification sitting in a saved project. If the honest answer is "nothing
happens", it's `low`.

If this is one of the [four that are always `high`](README.md#the-four-that-are-always-high)
— dataset knowledge in the app, a write to `data/`, a change to the guarded engine, or a
write outside `<project>/outputs/` — say which, and stop there. That is the whole
justification.

## What it would take

A rough shape, not a plan. Which files, and whether the fix is obvious or has a real
decision hiding in it. If there's a decision, say what the options are — `/resolve`
will ask about it, and it helps to know the fork exists before the conversation starts.

**Say whether the fix would need the 312/312 guard** (`needs: engine`). A fix that touches
the solver costs ~130 s of GPU time to prove, and that changes whether `/resolve` fixes it
inline or writes a plan.

## Not investigated

What you deliberately didn't chase, because you were in the middle of something else.
Being honest here stops the next session from assuming this file is exhaustive.
