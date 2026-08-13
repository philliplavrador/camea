---
description: Build queued plans — one, or the whole queue one after another
allowed-tools: Bash, Read, Grep, Glob, Write, Edit, AskUserQuestion, Agent, Workflow, TodoWrite, Skill, SendMessage, TaskOutput, PushNotification
---

Build queued plans. There are two modes, and the argument picks between them.

- **`/build 007`** or **`/build outputs-panel`** — build that one plan, in this session,
  yourself. This is the ordinary path. **Part A** below.
- **`/build all`** — dispatcher mode: every eligible plan, one after another, each with its
  own team, and this session doing nothing but answering their questions. **Part B** below.

`/build` with no argument shows the queue and asks which — and "all" is one of the
choices, which is the other way into dispatcher mode.

## `/build` works in this checkout, on `master`

No branch, no worktree, no review branch, no merge — **for this command.** You work in this
checkout, on `master`, and you commit there as you go. Builds are therefore serial: one
working tree, one build.

(Piles are a different flow: work he asked for by name goes on `wip/<slug>` via
[/start-work](start-work.md). `/build` is not that. See
[workflow/README.md](../../workflow/README.md).)

**If `master` is not the checked-out branch, say so and stop** rather than creating one.

---

# Part A — building one plan

## 1. Pick, and claim it

```bash
ls workflow/plans/queued/ workflow/plans/active/
```

If nothing is queued, say so and stop — [/plan](plan.md) writes them.

With no argument, list the queued plans with their titles **and their `needs:` field**,
and let him choose. **If `active/` is non-empty, say what is already in flight and stop
there** — there is one working tree, so nothing else can start until that plan finishes or
is abandoned.

Read the plan **completely** before touching anything.

**Claim it by moving it, before writing any code.** The move is the lock — two
sessions cannot hold the same plan.

`/plan` does not commit unprompted, so a fresh plan is often still untracked, and
`git mv` fails outright on an untracked file (`fatal: not under version control`).
Handle both:

```bash
git mv workflow/plans/queued/NNN-slug.md workflow/plans/active/NNN-slug.md 2>/dev/null \
  || mv workflow/plans/queued/NNN-slug.md workflow/plans/active/NNN-slug.md
```

Set `status: active` in the frontmatter, then commit the claim immediately — an
uncommitted claim is not a lock, because a parallel session cannot see it:

```bash
git commit -m "chore(plans): claim NNN — <title>" -- workflow/plans/active/NNN-slug.md
```

## 2. Take the lock

You are about to edit files in the only working tree there is, so say so. Writing
`workflow/.locks/main-checkout.json` is what tells a concurrent `/resolve` or
`/bug-hunter` to stay off the code.

```bash
mkdir -p workflow/.locks   # gitignored, absent in a fresh clone — create it first
cat > workflow/.locks/main-checkout.json <<'EOF'
{ "holder": "/build", "plan": "NNN",
  "since": "<ISO8601 now>", "note": "needs: frontend" }
EOF
```

**Every build takes it**, whatever the plan's `needs:` says. The lock guards the files, and
every build writes files. You release it at close-out (§6).

**If the lock already exists and names a plan still in `active/`, say so and stop.** Do not
work around it and do not delete it. If the lock is there and nothing is running, a session
died holding it: show its `plan` and `since` and **ask before removing it**.

### `needs:` decides your gates

| `needs:` | Adds to the standard gates |
|---|---|
| `none` | nothing. |
| `frontend` | `cd web && npm run lint && npx tsc -b --noEmit && npm test`, plus `npm run check:api` if `src/camea/api/` moved. |
| `dev server` | those, plus running the app and driving the change in a browser. Plus `npm run e2e` when a BEHAVIOUR ruling is in scope. |
| ⭐ `engine` | those, **plus the 312/312 guard, by hand.** See §5. |
| *missing* | Treat as `frontend`. Say the field is missing, and add it. |

## 3. Ask — up front, and then keep asking

Read `Open` and ask all of it up front, with `AskUserQuestion` — one or two plain
sentences each, no jargon in the question itself. See
[workflow/README.md § Asking the author a question](../../workflow/README.md#asking-the-author-a-question).

Then ask anything else you genuinely need — but **do not re-ask what the plan
already decided.** `Decisions` and `Explicitly rejected` are settled; reopening them
wastes his time and is the main way this workflow goes bad. If a decision now looks
wrong, say why and let him choose, rather than quietly doing something else.

**Asking is not a phase you finish here — it runs the whole build.** A plan is
written before the code is understood, so it *will* be incomplete in places nobody
could have predicted. He would much rather answer a question mid-build than review
something built on a guess. Stop and ask whenever:

- The plan is silent on something you are about to decide, and the choice is visible
  to a user — copy, a label, what an empty state says, a keybinding, where something
  lives on screen.
- Two reasonable implementations differ in a way he would notice or have to live with.
- The code contradicts what the plan assumed — a helper that already does this, a shape
  that isn't what the plan described.
- Finishing properly means touching something outside the plan's `Scope`. Never
  silently widen scope; ask, and say what it costs to leave it.
- ⛔ **The only way you can see to finish it is to teach the app something about a
  particular dataset.** That is HARD RULE 3 and it is never yours to trade away.
- ⛔ **You are about to touch a BEHAVIOUR ruling.** Do not "improve" one away.
- You're about to do anything hard to undo — changing what a saved project looks like
  on disk, rewriting a shared component, editing the engine.
- A `Done when` box cannot be ticked as written.

Ask **as you hit it**, not batched at the end — an answer that arrives after the
code is written is a rework order. Two or three good questions during a build is
normal and expected, not a sign the plan failed.

When you ask, give a recommendation and the trade-off, not a blank prompt. And
record any answer that changes the design in the plan's `Decisions` table before you
close it out.

## 4. Build it

Follow [CLAUDE.md](../../CLAUDE.md) and [docs/](../../docs/).

- Keep a `TodoWrite` list mirroring `Done when` so progress is visible.
- Fan out subagents for separable chunks — 2+ independent pieces means parallel. Give each
  writing agent a **disjoint set of files**; there is one checkout and no worktree to
  absorb a collision.
- **Never hand-write a backend-owned type.** `web/src/api/schema.d.ts` is generated:
  `cd web && npm run gen:api`. `npm run check:api` fails on drift, in both directions.
- **A BEHAVIOUR ruling in scope needs its e2e test to still pass** — and a *new* ruling
  needs a new test. A ruling with no test is not a ruling, it is a hope.
- Record anything you established **by measurement** in the relevant
  `utils/knowledge/` file, and add a dated handoff to the top of
  `utils/knowledge/worklog.md` when you leave off.

## 5. Verify — actually run it

Run the plan's `Verify` block, plus:

```bash
uv run ruff check . && uv run mypy
uv run pytest -q -m "not slow"
node scripts/check-links.js
cd web && npm run lint && npx tsc -b --noEmit && npm test
```

Add whatever else §2's `needs:` table says you owe.

⭐ **If the plan is `needs: engine`, or if you touched any of
`src/camea/engine/{t27,t33,quality,render}.py`, the 312/312 guard is not optional:**

```bash
uv run pytest tests/slow/test_solver_312.py -q -m slow -s
```

~130 s, and it needs the 35 GB mirror and a GPU, so nothing runs it for you. **If it goes
red: STOP. Do not fix forward.** Report it, leave the plan in `active/`, and say so in your
first line — that suite is the only thing between a refactor and silently breaking the
science, and a red one outranks everything else in the session.

**Run the gates before you say you are done, and report a red one as red, with output.**
Since you commit to `master` as you go, the gates no longer stand between your work and the
trunk — they stand between your work and his knowledge of what it did. Finishing quietly on
a red gate is the one failure this model can produce that a branch-and-merge one could not.

For UI, drive a browser and **look at it**. Exercise a backend change from the shell rather
than asserting it works. Dispatch the review subagents for the areas touched —
`engine-guard`, `behaviour-guard`, `api-contract-guard`, `frontend-conventions`.

**Report failures as failures, with output.** A plan that is 90% done is 90% done.

## 6. Close it out

Tick every `Done when` box. If one cannot be ticked, say so — don't quietly drop it.

```bash
git mv workflow/plans/active/NNN-slug.md workflow/plans/done/NNN-slug.md
```

Set `status: done`. Then commit the work with the plan — **never `git add -A` bare.** A
`/bug-hunter` running at the same time writes into `workflow/issues/`, `workflow/hunts/`
and `workflow/said/` in this same checkout, and `-A` would fold its half-finished work into
your feature commit.

> **Use the one-step form: `git commit -m "…" -- <paths>`.** It stages and commits
> atomically and cannot pick up anyone else's work. `git add` followed by a separate
> `git commit` is unsafe whenever anything else might commit in the gap: the index is
> shared, so the other party's commit picks up **your** staged files under **its** message.
> Nothing fails and nobody notices until someone reads the log.
>
> **For a NEW file** the one-step form has one hole: `git commit -- <path>` matches its
> pathspec against files git already knows, so a brand-new file fails with *"pathspec did
> not match"* — **after** committing any tracked paths listed alongside it. Stage exactly
> it and nothing else, then commit with the same pathspec:
> `git add -- <newpath>` then `git commit -m "…" -- <newpath> <trackedpath>`.

**A commit message in this repo quotes code, and `git commit -m "…"` in bash eats it.**
Inside double quotes a backtick opens command substitution and `$` expands a variable, so a
message saying ``the `--open` flag`` silently loses the word. Write the message to a
scratchpad file with a `<<'EOF'` heredoc (the single quotes are what disable expansion) and
use `git commit -F <file> -- <paths>`.

```
feat(mosaic): <what a user gets>

Implements workflow/plans/done/NNN-slug.md.
<what changed, and anything the plan got wrong>

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

**Release the lock** — the build is committed and the checkout is free:

```bash
rm -f workflow/.locks/main-checkout.json
```

**Do not push and do not open a PR** — his call, per [CLAUDE.md](../../CLAUDE.md).

Finish with: what was verified and how, what you'd want reviewed, and anything the plan
assumed that turned out to be wrong. That last one is the most useful thing you can
report — it is how the next plan gets written better.

---

# Part B — `/build all`, the dispatcher

Everything in Part A still applies to each individual build. What changes is who runs
them and who does the talking.

## 1. This session builds nothing

**The session running `/build all` is the orchestrator, and it writes no code at all.**

The reason is narrow and it is the whole design: **a subagent cannot show an
`AskUserQuestion` prompt — only the main session can.** If this session were also
building, it would be head-down in an edit while a team sat blocked on a fork, and
he would find out about it twenty minutes late.

```
orchestrator (this session)
└── one team at a time → this checkout, on master, holding the lock
    003 → 011 → 019 → …
```

## 2. Start the batch — one plan at a time

**`/build all` is serial.** There is one working tree, so exactly one team may be building
at any moment. Read the whole queue, decide the order, and say the order up front so he can
reorder it.

**Do not fake parallelism.** Two teams in one tree overwrite each other's files, and a
second worktree for a *writing* agent is not something a session may invent.

**Skip a plan whose `blocked-by:` names a plan not yet in `done/`.** The hold clears with no
edit the moment the blocker lands, so a plan blocked by one earlier in tonight's order will
become eligible during the run — say which ones those are.

**Order the queue deliberately.** Two things decide it, in this order:

1. **Any `Deploy` section that names an ordering constraint wins.**
2. Otherwise, small fixes before large features — more plans survive if the session runs
   out of budget partway. **Put `needs: engine` plans last**, and tell him: each one costs
   ~130 s of guard on top of everything else, and a red guard stops the whole batch.

**Claim each plan as you start it**, not the whole queue up front. **Take the lock** before
the team starts, and release it when that team finishes and before the next one is spawned.

**Spawn each team as a background agent** (`Agent`, `run_in_background: true`), told which
plan it is building and the question protocol in §3. Do **not** pass
`isolation: "worktree"` — a team in its own worktree has no `.venv` and no `node_modules`.
The team works in this checkout.

**Tell each team to pass its constraints down.** A constraint you give a team does not
reach the subagents that team spawns — a reviewer dispatched by a build team arrives with
the repo's instructions and none of the batch's. If you tell a team "do not run the slow
guard" or "do not touch these files", tell it to say so to everything it dispatches.

Then **stay awake**: collect questions, ask him, resume the team, start the next plan when
the current one closes. Never go quiet while a team is waiting.

## 3. The question protocol

**A build team never asks the author anything directly.** It has no way to. When it hits a
fork it stops and returns a structured block:

```json
{
  "status": "blocked",
  "plan": "007",
  "questions": [
    { "header": "<=12 chars", "question": "one or two plain sentences, no jargon",
      "options": [ { "label": "...", "description": "..." } ],
      "recommend": "<label>", "why": "one sentence, the trade-off" }
  ],
  "progress": "what is done so far, and what is half-done",
  "safeToPark": true
}
```

The orchestrator then:

1. **Pushes it to his phone.** Call `PushNotification` the moment a blocked block arrives —
   **the orchestrator sends it, never the team.** **Put the question itself in the body,
   with its plan number** — *"007: should excluding a tile also drop its neighbours from the
   recompute, or only itself?"*, not *"plan 007 is blocked"*. A push he cannot answer off a
   lock screen buys nothing.
2. **Collects.** Wait briefly — up to about two minutes — in case a second question arrives.
   Batching beats interrupting him twice for the same thirty seconds of attention.
3. **Asks with `AskUserQuestion`, up to 4 questions in one call.** Each question carries its
   plan number. The rules in
   [workflow/README.md § Asking the author a question](../../workflow/README.md#asking-the-author-a-question)
   apply in full. If he asks what a word means, define it and **re-ask**.
4. **Resumes the team** with `SendMessage`, carrying his answer. The agent's context is
   intact, so it picks up where it stopped.
5. **Records the answer** in that plan's `Decisions` table before the plan closes.

**Asking a lot is correct here.** He would much rather answer questions than review
something built on a guess. **A team that finished a plan without asking anything is more
suspicious than one that asked five times.** But **never re-litigate the plan** —
`Decisions` and `Explicitly rejected` are settled, and the team was not present for the
interview that settled them.

## 4. Parking — what happens while he's away

- A blocked team **freezes exactly where it is.** It does not guess, does not pick a safe
  default, and does not carry on with the parts it thinks are unaffected.
- **A parked team keeps the lock and keeps the checkout.** Nothing else starts. With one
  working tree there is no free slot to fill, so the honest move is to wait.
- When he answers, the parked team **resumes where it stopped**.
- If a team is parked and he is away, say so plainly: which plan, what it is waiting on,
  and what is left in the queue behind it. Then stop. Do not spin.

## 5. The lock

`workflow/.locks/main-checkout.json` — gitignored, because it is machine state, not history.
`workflow/.locks/` is **absent in a fresh clone**, so `mkdir -p` before the first write.

**One thing the lock does *not* guard: the git index.** Two `git commit`s in this checkout
at the same moment collide on `.git/index.lock` — one fails with *"Unable to create
'.git/index.lock': File exists."* Neither loses data; retry the failed git command once
after a second. This bites when `/resolve` commits an issue move while a build commits.

- **`/build`** will not start a second team while it exists.
- **`/resolve`** will not edit code while it exists.
- **`/bug-hunter`** never edits code anyway — it reads a detached snapshot — but it must not
  start the dev servers while a team holds them.

**A stale lock is a real failure mode.** If the lock exists but no build is running, say so,
show its `since` and `plan`, and **ask before removing it.**

## 6. Gates

Each team runs the Part A §5 set for its plan's `needs:`, plus the plan's own `Verify`
block, plus the review subagents for the areas touched.

**Measure the gates after your last edit.** A suite run before the closing commit is not a
gate on what landed.

⭐ **The 312/312 guard is the orchestrator's call, not a team's.** It is ~130 s of GPU time
and it must not be run twice by two teams in a row for no reason. If several plans in the
batch are `needs: engine`, have each team say so and **run the guard once, at the end of the
batch, yourself** — and if it is red, say which plans are in the suspect range. A red guard
stops the batch.

**Report failures as failures, with output.**

## 7. Landing — there is nothing to land

Each team commits straight to `master` as it works. There is no branch to merge and nothing
waiting for you at the end. That removes the whole class of problems a review branch existed
to surface, and it removes the protection along with them: **a red build is already on
`master`.** So the batch protects itself two ways instead:

- **Serial order is the protection.** Each plan is built against the finished state of the
  one before it.
- **A team that fails a gate stops and says so**, with output, and its plan **stays in
  `active/`.** The orchestrator does not start the next plan on top of an unreported
  failure. Tell him at once rather than at the end of the batch.

**Do not push and do not open a PR.**

## 8. Closing out

Per plan, as in Part A §6. Then one table for the batch:

| Plan | Gates | Questions asked |
|---|---|---|

Plus what is still queued and in what order, anything parked and what it waits on, whether
the 312/312 guard was run and what it said, and — the most useful line in the report —
anything a plan assumed that turned out to be wrong.
