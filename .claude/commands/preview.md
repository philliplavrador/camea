---
description: Run a pile on localhost so you can look at it before it lands
allowed-tools: Bash, Read, Glob, Grep, AskUserQuestion
---

# See it before you land it

**Ask which one. Never take it from the command line.** His instruction: *"when i run a
/preview I want to have to select which branch im looking at."*

```bash
node scripts/piles.js          # what there is
node scripts/preview.js list   # what is already running
```

Show both, then **`AskUserQuestion`** with one option per pile — label it with the slug, and
put its state and gates in the description. Include anything already running, so picking it
just hands back the address.

Then:

```bash
node scripts/preview.js start <slug>
```

It prints the address. **Give it a few seconds to boot before you hand him the link.**

## An `in progress` pile is previewable

That is the point of it — he is looking *in order to* decide whether to run
[/commit-work](commit-work.md). Only **landing** requires `ready`.

## What it does, so you can explain it in one line if asked

- **Its own working copy**, outside the repo at `../.camea-previews/<slug>`, checked out
  detached at the pile's ref. It **never** switches this checkout's branch — several
  sessions share this tree and changing its branch under them is the same damage as
  `git restore`.
- **Its own ports.** Web from 5200 upward, ten apart; the backend on the next number up.
  **5173 and 8000 are his own dev servers and are deliberately never used.**
- **The committed synthetic fixture** at `tests/fixtures/` (~5.6 MB) as its data — passed
  to the backend as `--open`, which puts a path in `settings.recent_datasets` and nothing
  else. **It never touches `data/`**, the read-only 35 GB mirror, so a preview works on a
  machine that has never synced it.
- **Nothing to restore and no database**, because Camea has neither.

⚠️ **The first start of a pile is slow** — a fresh worktree has no `web/node_modules` and no
`.venv`, so it installs both. Say that rather than letting him think it hung. Every start
after that reuses what is there.

## Stopping

```bash
node scripts/preview.js stop <slug>            # removes the worktree too
node scripts/preview.js stop <slug> --keep     # keeps it, so restarting is fast
node scripts/preview.js stop-all
```

Use `--keep` when he is going to look again in a minute; the reinstall is the expensive part.

## Looking at it yourself

Drive at the viewport the e2e suite uses (`devices['Desktop Chrome']`, per
`web/playwright.config.ts`), so what you see is what the tests see. Screenshots go to your
scratchpad or `.scratch/`, **never the repo root** — a hook will refuse a bare filename.

## If it will not boot

```bash
tail -40 ../.camea-previews/<slug>/.preview-logs/api.log
tail -40 ../.camea-previews/<slug>/.preview-logs/web.log
```

The usual causes: the install did not finish, or the port it wanted was taken by something
outside the preview system. `preview.js list` shows which ports it allocated.
