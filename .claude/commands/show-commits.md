---
description: What work is sitting around, and pick what lands on master
allowed-tools: Bash, Read, Grep, Glob, AskUserQuestion
---

# The board

Everything in flight, and what you want done with it.

```bash
node scripts/piles.js
```

**Print that, then ask.** Do not summarise it in prose first — the table *is* the answer,
and a paragraph above it is a paragraph he has to read twice.

## What a row means

```
  outputs-multiselect   3 commits   lint tsc vitest              ready
  sweep-anchor-badge    1 commit    lint tsc vitest e2e          ready         ⚠ shares Sweep.tsx
  recompute-window     11 commits   ⛔ ENGINE (1 guarded file)   in progress
  old-panel-tidy        2 commits   links                        ready         untouched 8 days
```

| Column | Reading it |
|---|---|
| state | **`ready`** — [/commit-work](commit-work.md) was run, it may land. **`in progress`** — still being worked on, **cannot land** |
| gates | which suites this pile owes before anyone believes it. **`⛔ ENGINE` means a human must run the 312/312 guard first** |
| ⚠ | two piles touch one file. Not a conflict — worth knowing before landing both |
| untouched N days | seven days or more. Sorted to the bottom. **Never binned for him** |
| behind master | the trunk moved since this was branched. Handled at ship time by re-running the gates on the merged result |

## Then ask what he wants

**`AskUserQuestion`, never prose.** One question per pile he is deciding on, or one question
listing the ready piles if he is picking among them. Two actions:

- **land it** → `node scripts/ship.js <slug>`
- **leave it**

**Only offer landing on a `ready` pile.** An `in progress` one is not finished; offering it
is offering to land something he has not looked at.

**There is no schedule option, and that is not an omission.** Landing a Camea pile is a
merge into `master` and nothing else — there is no deployment, so there is nothing to wait
for. If Camea ever grows a release step,
[ship.js](../../scripts/ship.js) is the one place that changes.

## What landing actually does

`ship.js` merges with `--no-commit`, **runs the pile's gates on the MERGED tree**, and
commits the merge only if they pass — otherwise it aborts the merge and `master` is exactly
as it was. That check is the one thing a per-pile gate run cannot give you: **two piles that
each pass alone can fail together**, and the merged result is the only place that shows up.

It pushes nothing. That stays his call.

## The one refusal that is not negotiable

⭐ **A pile touching the guarded engine is refused** until a human has run the 312/312 suite
and landed it with `--guard-was-green`:

```bash
uv run pytest tests/slow/test_solver_312.py -q -m slow -s
node scripts/ship.js <slug> --guard-was-green
```

No script may claim that suite ran — it needs the 35 GB mirror and a GPU, and it is the only
thing between a refactor and silently breaking the science. **If it is red: stop. Do not fix
forward.** Say that in one line if he asks why the board is blocking him.

## If he asks what a pile actually changes

```bash
node scripts/piles.js --slug <slug>        # the full record as JSON
git diff master...<ref> --stat             # what it touches
git log master..<ref> --oneline            # what happened in it
```

Show the file list or the log, not a retelling of it.
