---
description: Triage the issues sessions have filed, fix the trivial ones, plan the rest
allowed-tools: Bash, Read, Grep, Glob, Write, Edit, AskUserQuestion, Agent, TodoWrite
---

Work through the issues in [workflow/issues/](../../workflow/issues/README.md).

`$ARGUMENTS` may narrow it — a tier (`high`), an issue number (`014`), or part of a
slug. Empty means everything open, highest tier first.

## 1. Read the pile

```bash
ls workflow/hunts/reconsider/
ls workflow/issues/high/ workflow/issues/medium/ workflow/issues/low/
ls workflow/plans/queued/ workflow/plans/active/
ls -t workflow/hunts/log/ | head -3
```

Say in the report how many you left untouched in each tier.

**Start with the reconsider pile, before you read a single issue.** Each open file in
`workflow/hunts/reconsider/` is a question for *him* — `/bug-hunter` found something that
contradicts a decision he already made, and filed a question instead of a finding. Ask
about those first, with `AskUserQuestion`, because one answer can settle several UX issues
further down the pile and you'd rather not ask him about the consequences before the cause.
See [workflow/hunts/README.md](../../workflow/hunts/README.md).

Each one ends up in one of two states, and you set it in the file's frontmatter:

- **`kept`** — he still means it. Refresh that statement's date in
  [workflow/said/ledger.md](../../workflow/said/ledger.md) so it reads as re-confirmed
  today, and leave the reconsider file at `status: kept`. The hunter checks for that and
  will not raise the question again.
- **`changed`** — he's changed his mind. Mark the ledger entry `Superseded by:` the new
  answer (never delete it), and turn the reconsider file into a `kind: ux` issue or a queued
  plan, whichever step 3 would have chosen.

Either way, **leave the file where it is.** It is the record of what he answered, and a
question with no visible answer gets asked again.

**If the pile is large, read the newest hunt log first.** A `/bug-hunter` run files without
a cap, so most of a big pile can arrive in one night — and its log already ranks that
night's findings worst-first and says which areas came back clean.

Read every issue in scope, completely. **Read the `kind: bug` ones first, then the
`kind: ux` ones, highest `confidence:` first.** A UX issue is filed against a deliberately
low bar — he chose to do the filtering himself rather than have the hunter throw away
opinions it wasn't sure about — so the pile of them is long and unevenly good. Reading down
the confidence order means you spend his attention on the strong ones while he still has
patience for it.

Then read [workflow/issues/README.md](../../workflow/issues/README.md) for what the tiers
mean. Camea has no users, so the ruler is **the science and the hours of hand-verification
sitting in a saved project** — not how alarming the code looks.

**Read the plan queue too.** [/plan](plan.md) checks `workflow/issues/` before writing a
plan; this command owes the queue the same courtesy in reverse.

If nothing is open, say so and stop.

## 2. Verify before you trust

**An issue is a claim by a session that is no longer running.** The repo has moved since
it was filed. Before it costs him a single question, check it yourself:

- Does the `file:line` in `Evidence` still say what the issue says it says?
- Does the reproducing command still reproduce?
- Has something else already fixed it?

Dispatch subagents in parallel — one per issue — for anything beyond a couple of files.
This is the step that makes `/resolve` worth running rather than just reading the
directory yourself.

⭐ **An issue claiming engine drift gets verified before it gets a question, and the
verification is a diff, not a reading.** `src/camea/engine/{t27,t33,quality,render}.py` is
supposed to be byte-identical to `archive/analysis/mosaic/`:

```bash
for f in t27 t33 quality render; do diff -q "src/camea/engine/$f.py" "archive/analysis/mosaic/$f.py"; done
```

If they differ, that is a `high` and it is real. If they don't, the issue is wrong and
saying so is worth more than asking him about it.

Report what you found:

- **Already fixed** → move it to `resolved/`, `status: resolved`, with the commit that
  did it. Don't ask about it; just say it happened.
- **Evidence is wrong** → say so plainly and say what's actually true. A bad issue is
  worth deleting from the queue as much as a good one is worth fixing.
- **Mis-tiered** → move it to the right tier and say why. You have more context now than
  the session that filed it in passing.
- **Duplicates, or one root cause behind several** → group them. Several issues becoming
  one plan is the normal, good outcome. Check `resolved/` as well as the open tiers.
- **Already covered by a queued plan** → say which plan, and move the issue to
  `resolved/` with `resolved-by: plan NNN`. Add its evidence to that plan's `Verify`
  block, so the plan actually proves the bug is gone.

## 3. Ask him, issue by issue

Use `AskUserQuestion` — one or two plain sentences per question, no jargon in the
question itself, reasoning in the prose above it. See
[workflow/README.md § Asking the author a question](../../workflow/README.md#asking-the-author-a-question).

For each surviving issue — or each group — give him the three real options with a
recommendation:

- **Fix it now** — see the bar in step 4.
- **Plan it** — it goes to `workflow/plans/queued/` and a [/build](build.md) session does it.
- **Won't fix** — moves to `resolved/` with `status: wont-fix` and the reason.

Lead with **what it costs if nobody fixes it** — a lost afternoon of hand-verification, a
figure that is quietly wrong, a rule the app is no longer keeping. That is the thing he is
actually deciding, and it is usually not obvious from the issue title.

**For a `kind: ux` issue the three doors are the same, but the recommendation usually
isn't.** A UX finding is far more often a plan or a won't-fix than an inline fix, because
what it asks you to change is what a user sees — and that is explicitly not a decision
this command gets to make (step 4). Lead with the alternative the issue proposed, say what
a first-time user hits today, and let him pick between the two.

Ask about the **fork inside the fix**, not just whether to fix it. Most issues worth a
plan have one — two reasonable repairs that differ in something he'd have to live with.

## 4. Fix the trivial ones — and hold the line on "trivial"

**First, check whether a build owns the working tree:**

```bash
cat workflow/.locks/main-checkout.json 2>/dev/null
```

If that file exists, a `/build` team is mid-plan in this checkout and **you do not edit
code.** There is nowhere to get out of its way — two sessions writing the same files at
once corrupt each other's work, and the build has the harder job to redo. Say which plan
holds the lock and how long it has held it, then offer him the two things you *can* still
do: hold the trivial fixes until the build finishes, or plan them instead (step 5).
Everything else here works normally under the lock — reading, verifying, asking, writing
plans and moving issue files touch nothing a build is editing. One caveat when you *do*
commit an issue move under the lock: a build committing at the same moment collides with
you on `.git/index.lock`. Nothing is lost — retry the git command once after a second.

If there is no build running but the lock file is still there, a session died holding it.
Say so, show its `plan` and `since`, and ask before removing it.

**This command is not a build session.** The bar for fixing something here is all of:

- One file, or a handful of mechanical edits across a few.
- ⛔ **Nothing under `src/camea/engine/`.** Ever. Not a rename, not a comment, not a
  reformat. Those four files are byte-identical to the research original and a change to
  one owes the 312/312 guard — which is ~130 s of GPU time and is not something a triage
  session runs on the side.
- ⛔ **No change to a BEHAVIOUR ruling**, and no change that a ruling's e2e test covers
  unless you run that test.
- ⛔ **No change to what a saved project looks like on disk.** That has a roll-back story
  and it belongs in a plan.
- **No decision a user would see.** Copy, labels, empty states, keybindings — those get
  planned, not guessed.
- Provable by `uv run ruff check .`, `uv run pytest -q -m "not slow"`, an existing test, or
  one shell command.

**If a fix grows past that bar while you're in it, stop and write a plan instead.** Say
that it grew. Half a fix committed under `/resolve` is the worst outcome available.

Fix them, run the gates the change actually implicates, then move each to `resolved/` and
set `status: resolved`.

An issue is often **untracked** — filed by a session that never committed it — and
`git mv` fails outright on an untracked file. Use the both-ways form:

```bash
git mv workflow/issues/<tier>/NNN-slug.md workflow/issues/resolved/NNN-slug.md 2>/dev/null \
  || mv workflow/issues/<tier>/NNN-slug.md workflow/issues/resolved/NNN-slug.md
```

**Do not commit unprompted** — step 6 offers the commit. Propose this message and let
him say go:

```
fix(area): <what is no longer wrong>

Resolves workflow/issues/resolved/NNN-slug.md.
```

## 5. Plan the rest

For each issue — or group — going to the queue, claim the number with the script rather
than reading the directory and adding one:

```bash
node scripts/claim-number.js plan <slug>    # prints the claimed path
```

`/bug-hunter` may be filing at this exact moment, and a `/build` session may be moving
plans between directories; anyone who picks a number by looking at the queue is reading a
snapshot that is already stale.

You have already done the interview in step 3, so **fill `Decisions` from it** — in his
words where it matters. A plan written by `/resolve` is held to exactly the same
standard as one written by [/plan](plan.md): `Open` near-empty, `Done when` checkable.
Carry the issue's `Evidence` into the plan; it is the best `Verify` block you will get,
because it is a command already known to demonstrate the bug.

Then retire the issue — the plan is now the live document:

```bash
git mv workflow/issues/<tier>/NNN-slug.md workflow/issues/resolved/NNN-slug.md 2>/dev/null \
  || mv workflow/issues/<tier>/NNN-slug.md workflow/issues/resolved/NNN-slug.md
```

Set `status: resolved` and `resolved-by: plan NNN`. **`resolved/` means "closed", not
"fixed"** — the plan is where the work lives, and a file in two places rots in one of them.

## 6. Hand it back

One short table: each issue, and what happened to it — fixed, planned as `NNN`, won't
fix, or already gone. Then the new queue depth.

Offer to commit the moves and the new plans; do not push. Both are his call, per
[CLAUDE.md](../../CLAUDE.md).
