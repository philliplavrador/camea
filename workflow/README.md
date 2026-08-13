# workflow/ — how work gets from an idea to a commit

Everything about *how* work happens here, in one place. Two halves are the work itself —
one you chose, one that chose you — and the rest is the machinery that runs it.

```
workflow/
├── plans/    features, interviewed before anyone writes code.
├── issues/   bugs and inconsistencies — tripped over in passing, or hunted deliberately.
├── hunts/    what /bug-hunter has already swept, so the next run looks somewhere new.
│   ├── coverage.json   the index: where it has been, under which angle.
│   ├── checked/        the record: every file opened, every candidate, every reject.
│   ├── reconsider/     questions for you, where a finding contradicts something you said.
│   └── log/            one report per run.
└── said/     the dated record of what you've said — decisions, rules, preferences.
```

This system was imported from the Labstock repo on **2026-08-13**, at your request, and
adapted to Camea's stack and rulings. The shape is the same; the facts are Camea's.

**[plans/](plans/README.md)** is deliberate. You have an idea, `/plan` interviews you
properly, and the answers sit in `queued/` until a `/build` session spends them. The
recorded decisions are the whole point — a plan written three weeks ago has to still
make sense to a session that wasn't there for the conversation.

**[issues/](issues/README.md)** is incidental. A session fixing the Outputs panel notices
that a route writes outside `<project>/outputs/`. That is not what it was asked to
do, and dropping it into the chat means it dies when the session does. So it files the
issue, in one file, with the evidence, and carries on. Later, `/resolve` reads the pile
and turns it into plans.

## The whole loop

| | |
|---|---|
| `/plan <feature>` | Interviews you, writes `plans/queued/NNN-slug.md`. No code. |
| `/plan-all [list]` | The same, for a whole list in one session — a recon agent per item, batched question rounds, a plan per outcome. Also spends the open issues your list walks past (closing them `resolved-by: plan NNN`) and **repairs the plans already queued**. An empty list makes it a repair pass. No code. |
| *(any session, unprompted)* | Files `issues/<tier>/NNN-slug.md` when it finds something unrelated. Tells you in one line. |
| `/bug-hunter <duration>` | Goes looking, unattended, for the span you name. Files bugs it can confirm and UX problems it can argue for, and raises a **reconsider** question when a finding contradicts something you've said. No code, no commits. |
| `/resolve` | Reads the reconsider questions first, then the issues, and closes each one of three ways: fixed on the spot, turned into a plan, or won't-fix. |
| `/build [NNN\|all]` | Builds one plan in this checkout, verifies it, and commits it to `master`. `all` does the same for the whole queue, one plan after another. |
| `/start-work` | Interview + build in one session, on a **pile** of its own. For work you asked for by name. |
| `/preview` | Runs a pile on localhost, in a working copy of its own, so you can look at it. |
| `/commit-work` | You like how it looks — marks the pile `ready`. |
| `/show-commits` | The board: every pile, and ship now / leave it. |

Issues feed plans. Plans feed commits. Nothing is deleted at any step — a rejected idea
and a won't-fix bug are both records worth keeping.

## Two ways an issue gets filed

Most arrive **incidentally** — a session doing something else notices a route that
doesn't validate its input, files it, and carries on.

**[hunts/](hunts/README.md)** is the deliberate way. `/bug-hunter 8 hours` sweeps for a
fixed span while nobody is watching, verifies each candidate against a panel of skeptics
before it earns a file, and records in `coverage.json` which areas it swept under which
angle — so a nightly run keeps finding new things instead of re-reading the same three
files. It writes no code and commits nothing, because nobody is awake to review a fix at
3am.

Both land in the same pile, and `/resolve` doesn't care which door they came through.

The hunter also judges the app itself, not only its code — a flow with more steps than the
task needs, wording that assumes you know what a serpentine pass is, a screen with no
obvious next action. Those file as `kind: ux` issues. Before one of them files, it is
checked against **[said/](said/README.md)**, the dated record of what you've already told
the repo you want. If you have said something that contradicts the finding, nothing is
filed against you: it becomes a question in `hunts/reconsider/` asking whether you still
mean it, and `/resolve` puts those in front of you first.

## `master` is the trunk, and Camea ships nothing

Camea has no deployment. There is no Railway, no live server, no lab using it right now —
so `master` protects no user, and a commit landing there deploys nothing.

What `master` does protect is **the science**. `tests/slow/test_solver_312.py` is the only
thing between a refactor and silently breaking the placement engine, and it cannot run in
CI: it needs the 35 GB mirror and a GPU, so it runs on your machine in about 130 seconds.
A build that lands on `master` without it is a build nobody proved.

So the rules here are Labstock's, minus the deploy:

- **No long-lived fork off `master` to build one feature and merge back.** No shared review
  branch. That is the ceremony you said you were tired of.
- **No worktree a session invents for itself.** The two that exist are deliberate:
  `/bug-hunter` hunts in one detached at the last commit, and `/preview` runs a pile in
  one. Both are created and removed by their own tooling.
- **`/build` works in this checkout, on `master`,** and commits there as it goes. Builds
  are serial: one working tree, one build.
- **Work you ask for by name goes on a pile** — `/start-work` opens `wip/<slug>`,
  `/commit-work` renames it `ready/<slug>`, and `/show-commits` is where you decide what
  lands. **Shipping is a merge into `master` and nothing else** — there is nowhere else for
  it to go yet. If Camea ever grows a release step, that is the one place that changes.

Nothing is pushed and no PR is opened unless you ask — per [CLAUDE.md](../CLAUDE.md).

## Running all three at once

`/bug-hunter`, `/build` and `/resolve` can be running at the same moment, and that is the
point — a hunt overnight, a build beside it, and you triaging in the morning. Three things
make that safe, and none of them is a rule asking sessions to be careful.

**The hunter reads its own copy.** It hunts in a worktree detached at the last commit — a
read-only snapshot, with no branch, nothing to merge and nothing to review. A build spends
the night committing to `master` in the one checkout the hunter would otherwise be reading,
and a hunter that catches a file half-written files bugs that were never there.

**Numbers are claimed by a script**, not by counting the directory —
[scripts/claim-number.js](../scripts/claim-number.js) creates the file with an
exclusive-create flag and retries when it loses, so two commands filing in the same second
get different numbers rather than both writing `013`.

**The checkout is locked while somebody is writing code**, in
`workflow/.locks/main-checkout.json`. It says one thing: *someone is editing files here
right now.* `/resolve` reads it and holds its inline fixes, and `/bug-hunter` reads it and
won't start the dev servers. [plans/ § The lock](plans/README.md#the-lock) has the detail.

What's left is you. Questions still arrive one at a time in a single session, which is
what the next section is about.

## Asking the author a question

Every command here interviews him — `/plan` before anything is written, `/build` when a
plan left something open, `/resolve` on each surviving issue. The rules below govern all of
them. None is a style preference; each one was learned by stalling a conversation.

Under `/build all` a build team can't reach him at all, so every team's questions are
routed back through the orchestrating session and asked there — which is why these rules
still hold, and why he is asked in batches rather than by six agents at once.

**Always ask with `AskUserQuestion` — never in prose.** A question buried in a paragraph
is easy to skim past and cannot be answered with one keystroke. If you want an answer,
use the tool, every time. This is also [CLAUDE.md](../CLAUDE.md)'s standing rule.

**As few words as the question needs, and not one more.** He said it three times on
2026-07-31 — *"im not reading all that"*, then *"its still way too verbose"* about a round
that already followed the old wording, then this, when the fix came back as a table of word
counts: *"it doesnt have to be hard limits it needs to be adaptable but just tell them to
use as little as possible words unless I ask for more detail."*

So there is no number to hit. Write the question and the options, then **delete every word
that does not change which one he picks** — the label, the description, and the prose above
it. A one-word option beats four when one is clear; a description that repeats its own label
should not be there at all. Some questions genuinely need a sentence of setup, and those get
it. The test is never length, it is whether the word is doing work.

**Expand only when he asks for detail.** He will, and then you give him all of it.

**Confused about what he wants — or *why* he wants it that way? Ask instead of guessing.**
His standing instruction (2026-08-10): *"the more you understand why i want something a
certain way the more you can properly make things in line with my expectations."* The why
behind a request is always a legitimate question — a wrong guess costs him a rebuild, a
question costs him one keystroke.

**Keep the jargon out of the question itself.** No `file:line` citations, no internal
vocabulary, no term that isn't everyday English. He is a biologist; *serpentine pass*,
*homography*, *phase correlation* and *idempotent* are all words that cost a round trip.
Explain in the prose above the question, where reading it is optional.

**Recommend one, first, marked `(Recommended)`.** He asks for a pick, not a menu. If he
asks what a term means, define it and **re-ask** — don't answer and move on as though the
question were settled.

## Why both are directories, not lists

**State is the directory, in both halves.** A plan's state is `queued/` → `active/` →
`done/`; an issue's tier is `high/` → `medium/` → `low/`, and resolving it moves it to
`resolved/`. Moving the file *is* the change, which means it shows up in `git status`,
survives a session ending badly, and — for plans — acts as a lock that two parallel
sessions cannot both hold.

A single running `TODO.md` would be lighter to write and would conflict every time two
sessions filed at once. One file per thing doesn't.
