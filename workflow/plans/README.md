# plans/ — the feature queue

A plan is a feature, interviewed into a document before anyone writes code. You
stack them up when you have the ideas; you spend them later, one session per plan.

```
workflow/plans/
├── queued/   written, waiting. Pick from here.
├── active/   a session is building this right now.
├── parked/   kept, but not buildable yet — see parked/README.md.
└── done/     shipped. Kept as the record of what was decided and why.
```

This is one half of [workflow/](../README.md). The other half is
[issues/](../issues/README.md) — the bugs sessions trip over on their way to something
else. Issues become plans via `/resolve`; plans become commits via `/build`.

## The commands

| | What it does |
|---|---|
| `/plan <feature>` | Interviews you — properly, in several rounds — then writes `queued/NNN-slug.md`. Writes no code. |
| `/plan-all [list]` | The same thing for a whole list at once. One router session that reads nothing itself: a recon agent per item, batched question rounds, one writer per plan file, the open [issues](../issues/README.md) your list walks past folded in and closed, and **`queued/` audited and repaired**. An empty list makes it a pure repair pass. |
| `/build [NNN]` | Takes a plan off `queued/`, asks anything the plan left open, builds it, verifies it, commits it. |
| `/build all` | Takes **every** eligible plan off `queued/` and builds them one after another. The session itself builds nothing — it dispatches a team per plan and stays free to ask you questions. |

`/resolve` also writes here — it turns filed [issues](../issues/README.md) into plans.
Whichever door a plan came through, it is held to the same standard.

**A plan's state is its directory.** Moving the file *is* the claim, so two sessions
cannot start the same plan: `/build` moves it to `active/` before it writes a line
of code, and the move is committed immediately so a parallel session sees it.

## Running several — one after another

`/build` works in this checkout, on `master`, and commits there. No branch is cut, no
worktree is created, nothing is merged. `/build all` reads the whole queue and builds every
eligible plan the same way: **serially, one plan finished before the next is started.**

There is one working tree, so there is one build. Do not reintroduce parallelism by putting
a second team somewhere else; there is nowhere else. (`/bug-hunter` and `/preview` each get
a working copy, but neither writes code — see [workflow/README.md](../README.md).)

The `/build all` session still writes no code itself and still dispatches a team per plan,
because only the main session can put a question in front of you.

### What `needs:` means

`needs:` says which gates the build owes before it may call a plan done. Every plan builds
in this checkout; the field decides what has to be green, not where the work happens.

| `needs:` | What the build owes |
|---|---|
| `none` | `uv run ruff check .` · `uv run mypy` · `uv run pytest -q -m "not slow"` · `node scripts/check-links.js` |
| `frontend` | those, plus `cd web && npm run lint && npx tsc -b --noEmit && npm test`. Plus `npm run check:api` if anything under `src/camea/api/` moved. |
| `dev server` | those, plus running the app and driving the change in a browser — actually looking at it. Plus `cd web && npm run e2e` when a [BEHAVIOUR](../../docs/BEHAVIOUR.md) ruling is in scope. |
| ⭐ `engine` | those, **plus the 312/312 guard, by hand**: `uv run pytest tests/slow/test_solver_312.py -q -m slow -s`. ~130 s, needs the 35 GB mirror and a GPU, so it can never run in CI and no hook will run it for you. |

A missing field reads as `frontend`. An absent value means nobody judged it, and the safe
guess is the one that makes a build run more gates rather than fewer.

**`needs: engine` is not a formality.** `src/camea/engine/{t27,t33,quality,render}.py` is
byte-identical to the research original and is under the 312/312 guard
([CLAUDE.md](../../CLAUDE.md)). A plan that touches it — or that touches anything the
solver calls — owes the guard, and **if the guard goes red the build stops. Do not fix
forward.**

## Where finished builds land

On `master`, as the work happens. A build commits straight to the trunk, so there is nothing
to merge, nothing to review before merging, and nothing left behind to clean up.

The gates therefore do not stand between a build and the trunk — they stand between a build
and *your knowledge of what it did*. So run all of them anyway: the lint, the suites, the
link check, the plan's own `Verify` block, and the review subagents for whatever was
touched. **A build that fails a gate says so, with the output, and leaves its plan in
`active/`.** Finishing quietly on a red gate is the one failure this model can produce that
a branch-and-merge one could not, and it is the thing to guard against.

Commit in pieces as you go rather than in one lump at the end. A half-finished plan sitting
visible on `master` is the deal; a day's work sitting uncommitted when a session runs out of
budget is not.

Nothing is pushed and no PR is opened — that stays your call, per
[CLAUDE.md](../../CLAUDE.md).

## The lock

`workflow/.locks/main-checkout.json` says one thing: **two sessions writing the same files
at once corrupt each other's work.** There is one working tree, so that is the ordinary
case, not the exception.

`/build` writes it before it edits anything and deletes it at close-out. `/resolve` will not
fix code inline while it exists. `/bug-hunter` will not start or restart the dev servers
while it exists. `/start-work` warns on it. The file is gitignored; it is machine state, not
a record.

If you find the lock sitting there with no build running, the session died holding it. That
is a real failure mode and not a thing to clean up silently: the lock names its plan and
its `since` time, and you should be asked before it is removed.

## Why the interview matters

Both commands are deliberately question-heavy, and they ask about different things:

- `/plan` asks **what and why** — scope, edge cases, what "done" looks like, what
  you explicitly do *not* want. It records your answers in the plan.
- `/build` asks **how**, and only about things the plan genuinely left open. It
  should not re-ask a question the plan already answers; if it does, the plan was
  too thin and that is worth fixing.

The recorded answers are the point. A plan you wrote three weeks ago has to still
make sense to a session that wasn't there for the conversation.

## Conventions

- **Numbering** is zero-padded and never reused: `007-outputs-panel-multi-select.md`.
  Claim it with `node scripts/claim-number.js plan <slug>`, which creates the file
  atomically and hands back the next free number — **never by counting the directory
  yourself**, because `/build all`, `/resolve` and `/bug-hunter` may all be filing at the
  same moment, and two sessions that each read "highest plus one" get the same answer.
  Plan numbers and [issue](../issues/README.md) numbers are separate sequences — say
  "plan 007" or "issue 007", never just "007".
- **There is no `branch:` or `worktree:` frontmatter.** A plan is built on `master`, in this
  checkout. Work you want on a branch is a **pile** (`/start-work`), not a plan.
- **Nothing is deleted.** A plan you change your mind about moves to `done/` with
  its status set to `abandoned` and a line saying why. The record of a rejected
  idea is worth as much as a shipped one.
- **`parked/` is for a plan that must not be built yet** — not one that is merely low
  priority (that is the bottom of `queued/`), but one where building it would mean
  inventing answers you have not given. It leaves by being interviewed back into
  `queued/`, never by being built from where it sits. Because a plan's state is its
  directory and `/build` enumerates `queued/` and `active/` only, a parked file is out of
  the run by construction rather than by everyone remembering to skip it. Full rules:
  [parked/README.md](parked/README.md).
- **`resolves:` names the issues a plan closes.** Optional front-matter, default `none`,
  value is one or more issue numbers: `resolves: 191, 204`. Those issues move to
  `issues/resolved/` with `resolved-by: plan NNN` when the plan is *written*, not when it is
  built — becoming a plan is one of an issue's three exits.
- **`blocked-by:` is the machine-readable form of a hold.** Optional front-matter,
  default `none`, value is a plan number: `blocked-by: 043`. A queued plan naming a plan
  that is not yet in `done/` is not eligible for `/build all`, which means the hold
  **clears with no edit to the plan** the moment the named plan lands. The *reasoning* for
  a hold belongs in prose in § Deploy.
- **Plans are committed.** They travel with the repo, so any machine — or any
  session — sees the same queue.
- Start from [TEMPLATE.md](TEMPLATE.md).
