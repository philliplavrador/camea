---
id: 002
title: 13 of the 48 rulings in BEHAVIOUR.md are cited by no Playwright test
kind: bug
tier: low
status: open
found: 2026-08-13
found-while: importing the Labstock workflow — writing scripts/check-rulings.js
resolved-by: ~
---

# 002 — 13 of the 48 rulings in BEHAVIOUR.md are cited by no Playwright test

## What's wrong

`CLAUDE.md` states the contract plainly: the rulings *"are captured there as testable
statements, **each backed by a Playwright test in `web/tests/e2e/`**."*

Thirteen are not. Nothing in `web/tests/e2e/` mentions their numbers at all, so there is no
test to find from the ruling and no ruling to find from a test.

## Evidence

```
$ node scripts/check-rulings.js
13 of 48 rulings are not cited by any e2e test:

  R1      The `.warn` banner must lay out as prose, not as flex items
  R16     ⛔ Blank frames are REFUSED, not scored. There is no force flag.
  R18     The tone window is GLOBAL. Never per-tile.
  R25     The re-check is GLOBAL, and it is allowed to say NO
  R26     🔴 A re-solve must not destroy the human's work
  R30     📏 PIXELS ONLY. No scale bar by default.
  R31     Cache-busting is a session nonce, not the tone version
  R32     THE SCRIPTS MUST BE CACHE-BUSTED
  R34     A tile that leaves `excluded` must stop claiming it was thrown out
  R35     The exclusion must reach the SOLVER
  R36     Undo is 100 deep, tag-folded at 700 ms, and a drag pushes ONCE
  R39     What we are NOT rewriting, and why *(SPEED.md, settled)*
  R45.9   A DIM PATCH OF THE ARRAY IS STILL THE ARRAY *(2026-08-11)*
```

⚠️ **This is a citation check, not a coverage check.** It proves nobody connected the
ruling to a test; it cannot prove the behaviour is untested. Some of these may well be
exercised by a spec that never names the number — `R31`/`R32` (cache-busting) and `R36`
(undo depth) are the likeliest. **Establishing which is the first half of the work**, and
it is cheaper than writing thirteen tests.

Two are probably not tests at all and should be reclassified rather than covered:
**R39** is *"what we are NOT rewriting, and why"* — a scope decision, with nothing to
assert — and **R30**'s "no scale bar by default" may be a design note.

## Why this tier

`low`. Nothing is broken right now and no user is affected — Camea has none. What it costs
is future silence: an uncited ruling is one a refactor can contradict without anything going
red, and three of these guard things that matter.

**R26** (*a re-solve must not destroy the human's work*) and **R35** (*the exclusion must
reach the solver*) are the two to cover first. R26 is the exact failure the whole
hand-verification workflow exists to prevent — it would be a `high` as a *defect*, and only
the absence of a test is `low`.

## What it would take

Not one job. Three, in order, and the first is an afternoon rather than a week:

1. **Triage the thirteen.** For each: already tested but uncited (add the number to the
   existing spec — minutes) · genuinely untested (needs a spec) · not testable (R39, maybe
   R30 — mark it in BEHAVIOUR.md as a scope note rather than a ruling, so the checker stops
   counting it).
2. **Write the missing specs**, R26 and R35 first.
3. **Lower the ratchet as each lands.** The gate in
   [.claude/hooks/stop-gates.js](../../../.claude/hooks/stop-gates.js) runs
   `check-rulings.js --max 13`; every ruling covered should drop that number by one, so the
   debt can only shrink.

The ratchet already protects the thing that matters most: a **new** ruling cannot be added
without a test.

`needs:` for the eventual plan is `dev server` — writing e2e specs means running them.

## Not investigated

Which of the thirteen are already covered by an uncited spec. Nobody read the specs looking
for uncited assertions; the check only greps for the ruling numbers.
