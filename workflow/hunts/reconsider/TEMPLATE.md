---
title: <one line — the thing he may want to revisit>
raised: YYYY-MM-DD
raised-by: /bug-hunter <area>/<angle>
you-said: <one line quote>
you-said-when: YYYY-MM-DD
you-said-where: <plans/done/007 Decisions | commit a32a768 | utils/knowledge/worklog.md>
confidence: medium # high | medium | low — how sure the hunter is this is worth revisiting
status: open # open | kept | changed
---

# <title>

## What you said

The quote, with enough of its surroundings to make sense a month later, and where it came
from. Say when — a statement from last week and a statement from last spring are not the
same weight, and a statement that couldn't be dated at all is a hint rather than a
decision. If you had to paraphrase, say that you paraphrased.

## What the hunter saw

The screen or the flow, and what a first-time user actually hits there. Name the screen and
quote the literal wording on it. This is the half he can't check without you being
specific, so be specific.

## Why it might be different now

What has changed since you said it — a feature landed, a decision was reversed, the app
grew, the thing you were describing no longer exists in that shape. Camea has moved fast:
the project-manager reframe and the Recompute tool landed 2026-07-24, and R44 reversed
R42/R43 on 2026-08-10. A statement made before one of those is about a different app.

If the statement is under 30 days old, lead with the likelier explanation: the hunter
misread the screen and you were right. **Never write this section as though the statement
can't be wrong** — the author asked not to be taken on faith. Just make contradicting him
cost a question rather than silence.

## If nothing has changed, ignore this

One line saying what "nothing has changed" would look like here, so the file is cheap to
dismiss. `/resolve` will ask about this file and mark it `kept` — after which the hunter
must not raise it again — or `changed`, which turns it into a `kind: ux` issue or a plan.
Either way the file stays put as the record of the answer.
