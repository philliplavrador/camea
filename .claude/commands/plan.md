---
description: Interview the author about a feature, then write it to the plan queue
allowed-tools: Bash, Read, Grep, Glob, Write, Edit, AskUserQuestion, Agent, TodoWrite
---

Interview the author about **$ARGUMENTS**, then write a plan to
[workflow/plans/queued/](../../workflow/plans/README.md).

**Write no feature code in this command.** The only file you create is the plan.

## 1. Ground yourself first

Do not interview from a blank page — questions written without reading the code are
generic, and the author has to do the work of explaining his own repo back to you.

- **Read [docs/BEHAVIOUR.md](../../docs/BEHAVIOUR.md)** for any ruling the request lands
  on. It is the testable contract — ~44 numbered decisions he paid days to discover, each
  backed by a Playwright test in `web/tests/e2e/`. A request that contradicts one is a
  conversation, not a plan.
- **Read [utils/knowledge/INDEX.md](../../utils/knowledge/INDEX.md)** and the topic files
  it points at. `mea-calcium-goal.md` is the why behind the whole app;
  `mosaic-builder-direction.md` is the current shape of the first task. The dated handoffs
  at the top of `worklog.md` are what the last session knew.
- Route through [docs/](../../docs/) — [API.md](../../docs/API.md),
  [FRONTEND.md](../../docs/FRONTEND.md), [SPLIT.md](../../docs/SPLIT.md).
- Find the real files. Name them in your questions.
- Check `workflow/plans/` — an existing plan may already cover or conflict with this.
- Check [workflow/issues/](../../workflow/issues/README.md) — a session may already have
  filed the bug this feature is really a reaction to.

Dispatch subagents to explore in parallel if the area is large.

## 2. Interview — several rounds, not one

**This is the command's actual job.** A plan is only worth writing if it captures
decisions that would otherwise be re-litigated three weeks from now.

Use `AskUserQuestion`. Keep going until you can write "Done when" as checkable
statements. **Two rounds minimum**, more when the answers open new ground — a later
round should build on the earlier answers, not repeat them.

**Keep every question to one or two plain sentences, with no jargon in the question
itself** — put the reasoning in the prose above it, where it is optional reading. He is a
biologist with little maths: *serpentine*, *homography*, *phase correlation*, *idempotent*
and *anchor* are all words that cost a round trip. The full rule is in
[workflow/README.md § Asking the author a question](../../workflow/README.md#asking-the-author-a-question).

Cover, adapted to the feature:

- **The user and the moment.** Who hits this, and what were they doing just before? The
  answer is usually *a researcher who has just come back from the microscope with a folder
  of frames and wants a mosaic out of it.*
- **What "done" looks like**, concretely enough to test.
- **Scope boundaries.** The adjacent thing you are *not* building. Ask directly —
  this is the question that most often prevents wasted work.
- **Edge cases**: zero frames, exactly one, thousands, a dataset with no split, a job
  cancelled halfway, every tile excluded, a project deleted while something runs.
- **What it writes, and where.** Everything a feature builds lands in
  `<project>/outputs/` and the user is never asked for a path — **BEHAVIOUR R44**. If the
  feature seems to need a save dialog, that is a question for him, not an exception.
- ⛔ **Dataset knowledge.** Does the design need a number, a range, a count or a special
  case that only makes sense for one dataset? If so the design is wrong — say so before
  planning around it. The app opens a dataset as *N frames on disk* and derives nothing.
- **Does it touch the engine?** `src/camea/engine/{t27,t33,quality,render}.py` is
  byte-identical to the research original and under the 312/312 guard. If the answer is
  yes, that changes `needs:` and it changes the risk.
- **Existing behavior it changes.** Anything that breaks a ruling is a decision, not a
  detail.

Ask about **trade-offs you actually found while reading** — a question that proves
you read the code is worth ten generic ones. When you hit a genuine fork, present
the options with their costs and give a recommendation.

**Push back when you should.** If the request conflicts with a repo rule, a BEHAVIOUR
ruling, or an already-queued plan, say so rather than planning around it silently.
The author would rather hear it now.

## 3. Write it

Slug: short, kebab-case, from the title. Claim the number with the script — it takes the
next free one and creates the file atomically, so a concurrent `/resolve` or `/build all`
can't collide with you (never hand-count "highest plus one" — you'd both pick the same):

```bash
node scripts/claim-number.js plan <slug>   # prints the claimed path; write the plan into it
```

Write `workflow/plans/queued/NNN-slug.md` from
[TEMPLATE.md](../../workflow/plans/TEMPLATE.md).

- **Fill `Decisions` from the real interview.** Every non-obvious answer, in his
  words where it matters. A build session was not there and cannot infer them.
- **Record what was rejected and why**, so a build session doesn't re-propose it.
- **Fill `Rulings this touches`** with the BEHAVIOUR numbers, or `none`. A build session
  needs to know which tests it is standing on before it writes a line.
- **`Open` should be empty or near-empty.** Every item there is a question you could
  have asked and didn't. If it's long, go back to step 2.
- **`Done when` must be checkable.** No "works well".
- **Set `needs:`** — `none`, `frontend`, `dev server`, or `engine`. It decides which gates
  the build owes, not where it happens. Anything you have to *look at* in a browser is
  `dev server`; anything touching the four guarded engine files is `engine` and owes the
  312/312 guard by hand. When unsure, say `frontend` — the cost of being wrong that way is
  running a gate you didn't need.
- Reference real paths. **A plan sits at `workflow/plans/queued/`**, three levels under the
  root, so its links out start with `../../../`. `node scripts/check-links.js` will tell you
  if you got it wrong.

## 4. Hand it back

Show him the path, the title, and the queue depth. Offer to commit it — do not
commit unprompted; `workflow/plans/` is tracked, and the commit is his call.

Then stop. Building it is [/build](build.md)'s job, in its own session.
