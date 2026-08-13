---
description: Finish the current pile — he likes how it looks, so mark it ready to land
allowed-tools: Bash, Read, Grep, Glob, AskUserQuestion
---

# Finish it

He has looked at it and he likes it. This marks the pile **ready**.

**It lands nothing.** Nothing is on `master` until [/show-commits](show-commits.md) puts it
there.

## First, be sure it is actually finished

```bash
node scripts/work.js where     # which pile, and what is uncommitted
uv run ruff check . && uv run pytest -q -m "not slow"
cd web && npm run lint && npm test
```

**A red test does not block this** — a pile is allowed to be finished and wrong, and the
gate that matters is at ship time, against the *merged* result ([ship.js](../../scripts/ship.js)
runs the gates on the merge and aborts it if they are red). But **say so plainly** if
something is red, because he is about to put it on the board as ready.

⭐ **If the pile touches `src/camea/engine/{t27,t33,quality,render}.py`, say so in your
first line**, and say what it costs: the 312/312 guard is ~130 s, needs the 35 GB mirror and
a GPU, and `ship.js` will refuse the pile until a human has run it and passed
`--guard-was-green`. `node scripts/piles.js --slug <slug>` shows it as `⛔ ENGINE`.

## Then

```bash
node scripts/work.js finish
```

Which: commits anything outstanding, renames `wip/<slug>` → `ready/<slug>`, pushes it,
deletes the old `wip` ref on GitHub, and puts this checkout back on `master`.

## Report, in about three lines

- what the pile is called and that it is **ready**
- what it changes — file count, and **which gates it owes** (the board's middle column)
- that it is **not on `master`**, and `/show-commits` is what lands it

## If it refuses

- **"not a pile"** — this checkout is on `master`. The work is somewhere else, or
  [/start-work](start-work.md) was never run.
- **"already finished"** — it is on `ready/` already and is on the board.

**Never** stash, reset, restore or force anything to make it proceed.
