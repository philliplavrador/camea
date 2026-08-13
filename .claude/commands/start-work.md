---
description: Interview him about a piece of work, build it, and keep it on its own pile
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion, Agent, TodoWrite
---

# Start something

Interview, then build, in **one session**. He looks at it here and iterates here; when he
likes it he runs [/commit-work](commit-work.md).

## 1. Ask what it is — before touching anything

**One `AskUserQuestion` round, short.** Enough to name the work and know what "done" looks
like. Not a full [/plan](plan.md) interview — that command still exists for work he wants
queued and thought about first; this one is for getting on with it.

What you actually need:

- **what he wants** (in his words — this becomes the pile's name)
- **anything you would otherwise guess at** and that would change the result

Then turn his answer into a slug and open the pile:

```bash
node scripts/work.js start <slug>
```

**Read back the slug you chose** in one line, so a bad guess is cheap to correct.

## 2. It refuses on a dirty tree, and that refusal is correct

Several sessions share this checkout. Switching its branch with uncommitted files in it
would carry somebody else's work onto your pile. If it refuses:

- **Never** `git stash`, `git reset`, `git checkout --` or `git restore` to clear the way.
  Those discard other sessions' work.
- Find out whose the files are and commit them where they belong.

It also **warns** when `workflow/.locks/main-checkout.json` is held. A clean tree means it
proceeds anyway — but if that session is genuinely still running, wait for it.

## 3. Build it

Ordinary work: read the conventions that apply, write it, run the tests. Read
[CLAUDE.md](../../CLAUDE.md) and, for anything a user sees,
[docs/BEHAVIOUR.md](../../docs/BEHAVIOUR.md) — the rulings hold on a pile exactly as they
hold on `master`.

The one difference is **save as you go**:

```bash
node scripts/work.js save "what just got done"
```

That commits *and pushes*. He never reads those commits — they exist so a session that dies
or gets closed loses nothing. **Save after any meaningful chunk**, not just at the end.

⭐ **If the work touches `src/camea/engine/{t27,t33,quality,render}.py`, say so out loud in
your first message after you find out.** Those four files are byte-identical to the research
original and under the 312/312 guard; a pile that edits one cannot land without ~130 s of
GPU time and a human saying the guard was green. He should know that before he watches you
build for an hour, not at ship time.

## 4. Show him

**Do not describe it — let him look at it.**

```bash
node scripts/preview.js start <slug>
```

Give him the address. The first start of a pile installs `web/node_modules` in its own
working copy and takes a few minutes — **say that**, or he will think it hung. Then iterate
here on what he says.

## 5. Hand over

When he is happy, tell him in one line to run **`/commit-work`**. Do not run it for him —
the whole design hangs on *"once I like how it looks"* being his judgement, not yours.

## What this command must not do

- **Never merge to `master`.** Work goes on the pile; landing it is
  [/show-commits](show-commits.md).
- **Never mark it ready.** That is [/commit-work](commit-work.md).
- **Never take the build lock.** That lock is `/build`'s, and a pile is not a build.
