---
description: End the session in one sentence — or a question, if something needs deciding
allowed-tools: Bash, Read, Grep, Glob, AskUserQuestion, Edit, Write
---

You are closing out this session. **He has not read a word of it and is not going to.**
Everything above this point is now invisible; only what you say next exists.

Two outcomes. There is no third.

| | |
|---|---|
| **Clean** | one sentence of what you did, then tell him he can close the session |
| **Not clean** | `AskUserQuestion`. Never prose. |

`$ARGUMENTS`, if he typed any, is the thing he actually wants to know — answer that in
the sentence.

## 1. Check before you speak

Don't declare it clean from memory. Cheap checks only — this is a check on your own turn,
not a fresh audit of the repo.

```bash
git status --short      # work you said you'd commit, still sitting there?
git log --oneline -5    # did the commits you claimed actually land?
```

- If a `.py` changed and nothing ran, run `uv run ruff check .` now.
- If anything under `web/src/` changed, run `cd web && npm run lint`.
- ⭐ **If any of `src/camea/engine/{t27,t33,quality,render}.py` changed, that outranks
  everything else in this command.** Say so in the first line, say whether the 312/312
  guard was run, and if it wasn't, this session is **not clean** — go to §3.
- Anything still in flight — a background command, a subagent, a check you started and
  never read the result of?
- Re-read **his original request**, not your summary of it. Is every part done?

## 2. Clean → one sentence

Clean means what he asked for is done, it's verified, and nothing is waiting on him.

> Renamed the Recompute button to "Re-place the rest" across the three screens; lint
> passes. Nothing for you here — you can close this session.

- **One sentence**, plus the close line. A second only if you filed an issue or wrote a
  handoff that's worth a clause.
- No file list, no bullets, no "Summary" heading, no recap of how you got there.
- No "let me know if you'd like…" — if there were something to know, this would be a
  question instead.
- Name the outcome, not the process. "Fixed X", not "I searched, read, then edited".
- Session was just reading or talking? Say that in a clause and close it the same way.

## 3. Not clean → ask, don't explain

Any of these makes it not clean:

- A test or lint fails — or never ran on code you changed.
- ⭐ The engine was touched and the 312/312 guard was not run, or was red.
- Part of what he asked isn't done.
- You guessed at something ambiguous and he hasn't seen the guess.
- You changed something he didn't ask about.
- A BEHAVIOUR ruling moved and its e2e test didn't.
- Work is uncommitted, or something is still running or unverified.

Then it's `AskUserQuestion` — the question **is** the output. The problem goes in the
question, so he never has to scroll up; the fix you'd pick goes first in the options.
Then cut every word that doesn't change which option he picks
([workflow/README.md § Asking the author a question](../../workflow/README.md#asking-the-author-a-question)).

**One question. Two at the absolute most.** Three problems is not three questions — ask
about the one that blocks him and fold the rest into the options.

Finding a bug is not a question. File it ([workflow/issues/](../../workflow/issues/README.md)),
and it becomes one clause in the clean sentence: *"…and I filed issue 041 for the stale
tile count."*

When he answers, do the thing, then finish with the § 2 sentence.

## 4. Never buy the brevity with honesty

The failure this command invites is a tidy "done" laid over something that isn't done.
That costs him more than the wall of text he's avoiding — he'll believe it and close the
session. **If you aren't sure it's clean, it isn't. Ask.**

Never write "you can close this session" while anything is running, unverified or undone.
