---
id: 006
title: Card's `interactive` prop promises behaviour and delivers only appearance — every caller hand-patches the same three lines
kind: defect
tier: medium
status: open
found: 2026-08-14
found-while: building plan 001 — reviving the Task step shipped a screen that was keyboard-dead, and the fix was three lines copied off another caller
resolved-by: ~
---

# 006 — `<Card interactive>` looks clickable and is not

[`web/src/design/primitives/Card.tsx`](../../../web/src/design/primitives/Card.tsx) renders a plain
`<div>`. Its `interactive` prop is documented as *"Turns on hover/focus affordance for a clickable
card"* and does exactly one thing: adds a CSS class. It adds **no `role`, no `tabIndex` and no key
handler**. So a `<Card interactive onClick={…}>` is:

- **invisible to Tab** — a keyboard user cannot reach it at all;
- **deaf to Enter and Space** — even if focus arrives some other way;
- **silent to a screen reader** — a `div` with a click handler announces as nothing.

The name is the trap. `interactive` reads as *"this card is a control"*; it means *"this card is
painted like one"*.

## The evidence, and it is not a hypothetical

There are exactly **two** `interactive` call sites in the live tree, and **both** hand-patch the same
three lines to make the card work:

| call site | what it patches on |
|---|---|
| [`ProjectManager.tsx:243`](../../../web/src/features/home/ProjectManager.tsx#L243) (the project cards) | `role="button"` · `tabIndex={0}` · `onKeyDown` for Enter/Space |
| [`NewProjectFlow.tsx:339`](../../../web/src/features/home/NewProjectFlow.tsx#L339) (the task cards) | the same three, **added 2026-08-14** |

⭐ **The second one shipped without them and stayed broken.** The task cards were written when the
Task step had two tasks, then mothballed for a year when it dropped to one — unreachable, so nobody
noticed. Plan 001 put a second task back in `TASKS`, and the step became **the only door to either
task**: for the length of one commit, a keyboard-only user could not create a project at all. It was
caught by a review, not by a test, and not by the type checker — `CardProps extends
HTMLAttributes<HTMLDivElement>`, so `onClick` on a div is perfectly well typed.

Two for two is a small sample and a loud one: **every caller that has ever wanted a clickable card
has needed the same fix, and one of them forgot.**

## The fix, roughly

Inside `Card`, when `interactive` **and** `onClick` are both present, default `role="button"`,
`tabIndex={0}` and an Enter/Space handler that calls `onClick` — all overridable by a caller that
means something else (a link card, a card inside a `<li role="option">`). Then delete the patches
from both call sites. About 15 lines, plus a unit test in `web/src/design/` that a click handler
implies a focusable, key-operable control.

⚠️ **It is not a one-liner, which is why it is filed rather than done.** It needs a sweep of every
`<Card>` in the tree — including the retired snapshot lane under `web/src/legacy/mosaic/` — to be
sure nothing quietly gains a `role="button"` it should not have (a card that is a *container* with a
button inside it must not become a button containing a button; that is the same invalid-nesting trap
[`PipelineNav.tsx`](../../../web/src/features/videomosaic/PipelineNav.tsx) documents and refuses).

## Why medium

It cannot lose work or touch the science, and the two known call sites are both correct today. It is
medium because it is a **primitive that invites the bug**: the next person to write a clickable card
will read the prop name, believe it, and ship the same hole — and the failure mode is invisible to
anyone using a mouse, which is everyone who tests it by hand.
