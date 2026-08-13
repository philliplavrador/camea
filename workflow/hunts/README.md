# hunts/ — what the bug hunter has already looked at

`/bug-hunter 8 hours heavy` sweeps the repo for a fixed span and files what it confirms
into [issues/](../issues/README.md). This directory is its memory. Without it, a run every
night would check the same three things every night, and would keep re-investigating the
same candidate it already talked itself out of at 2am.

```
hunts/
├── coverage.json   per area: when last hunted, angles used up, what it found.
├── checked/        the full record: every file opened, every candidate, every reject.
├── reconsider/     questions for the author where a finding contradicts something he said.
└── log/            one report per run: YYYY-MM-DD-<duration>.md
```

## coverage.json is the index; checked/ is the record

These two do different jobs and you need both.

**`coverage.json` decides where to go next.** It is small, it is scanned first, and it
holds one entry per area. Three fields do the work:

- **`lastHunted`** — `null` means never, and never goes first. Otherwise the stalest area
  wins, so coverage spreads out on its own instead of following whatever the hunter found
  interesting last time.
- **`anglesUsed`** — the lenses already tried on that area. A re-check must pick an angle
  that isn't in the list until every angle has been used. Re-reading `src/camea/api/` for
  unvalidated input a second time finds the same nothing; re-reading it for writes outside
  `<project>/outputs/` doesn't.
- **`lastResult`** — `found`, `dry`, or `skipped`. A skipped area must never look like a
  clean one; if `ui` was skipped because the backend wouldn't start, the next run needs to
  know that nobody actually looked.

Yield can override staleness — an area that produced a confirmed `high` last time is
worth going back to sooner. The run log says when that call was made.

**`checked/` stops the same non-issue being re-investigated.** One file per round,
`YYYY-MM-DD-HHMM-<area>-<angle-slug>.md`, written *before* that round's issues are filed
so a crash keeps the record of the work. Each one lists every file actually opened and
what was being looked for in it, every candidate raised and its verdict, and every path
swept clean — plus the section that earns the directory, **every candidate that was
rejected and the specific reason it died**.

That last section is the point. A finding that three skeptics killed cost a whole panel to
kill. Without a record, the next run raises it again, spends another panel, and reaches
the same answer. So before raising a candidate, grep `checked/` for it: a candidate already
rejected under the same angle does not get a second panel unless the code has changed
since — and if it has, say which commit changed it.

**Dry rounds are results and are recorded.** "`core` came back clean under the
cancellation lens" is exactly what the next run needs in order not to repeat it.

## The areas

Camea's, not a generic list. `coverage.json` is seeded with exactly these.

| Area | What's in it | Angles to rotate through |
|---|---|---|
| ⭐ `dataset-knowledge` | **everything under `src/camea/` and `web/src/`** | a hard-coded trial number, range or count · an exclusion list · a per-dataset special case · a default that only makes sense for 260620d · an import of `EXCLUDED`/`BLANK`/`BLURRY`/`usable_trials` into app code |
| ⭐ `storage` | anything that writes | a write outside `<project>/outputs/` · a path the user is asked for · an "Open folder" or reveal · a draft file · a write under `data/` — all of these reverse **R44** |
| `engine` | `src/camea/engine/` — **read-only, never edited** | drift from `archive/analysis/mosaic/` · a caller assuming a return shape `t27`/`t33` doesn't have · a device (CPU/GPU) assumption · a constant duplicated instead of imported |
| `core` | `src/camea/core/` — dataset · frames · workspace · document · jobs | a job that can't be cancelled · a document write that isn't atomic · a path escaping the project dir · a frame index assumed contiguous |
| `api` | `src/camea/api/` + `schemas.py` | a route with no response model · a shape the generated TS client cannot express · an unvalidated path parameter · a long call with no job · an error shape that differs from its neighbours |
| `features` | `src/camea/features/` | a feature reaching into another's state · logic that belongs in `core/` · an output written somewhere other than `outputs/` |
| `frontend` | `web/src/` | a raw `fetch` instead of the generated client · a hand-written backend-owned type · a re-render inside the 60 fps sweep loop (**R20**'s ~6 ms budget) · unhandled loading/error state · a stale closure in the key handler |
| ⭐ `behaviour` | [docs/BEHAVIOUR.md](../../docs/BEHAVIOUR.md) against the code and `web/tests/e2e/` | a ruling with no e2e test · a test that no longer proves the ruling it names · code contradicting a ruling · a ruling superseded by a later one but still stated flatly |
| `docs-vs-code` | `docs/` against reality | a documented rule the code doesn't enforce · a documented path that doesn't exist · a claim that was true three refactors ago |
| `knowledge-base` | `utils/knowledge/` internally | two notes contradicting each other · a note written before the 2026-07-14 revamp describing the old `app/`+`analysis/` layout as current · a topic with two homes |
| `claude-md` | every `CLAUDE.md` | a rule the repo violates · a stale path · an instruction that expired by date · a rule contradicting `docs/` |
| `ui` | the running app, as it looks | empty states · a canvas that clears to the wrong colour (**R31**) · unreadable contrast · a control that gives no feedback when pressed · a layout that breaks at 1440×900 |
| `ux` | the running app, as it *works* | more steps than the task needs · a decision the user shouldn't have to make · no way back, no undo · a wait with no feedback · wording that assumes maths or microscopy training · a dead end with no next action · a first-time user's very first project, end to end |
| `edge-cases` | anywhere | zero frames · exactly one · thousands · a dataset with no split · a recompute cancelled halfway · a project deleted while a job runs · every tile excluded |
| `workflow` | [workflow/](../README.md) and `.claude/` | a command referencing a path that moved · a convention two commands state differently · a broken link · a gate in the Stop hook that cannot run |

**`ui` is what you can see; `ux` is the shape of the work.** A canvas clearing to white
instead of black is `ui` and it is broken (**R31**). A sweep that makes you re-find your
place after every correction is `ux` and it works fine — it just costs the user more than
it should. The split matters because they file differently.

**The three starred areas are Camea's own.** They have no Labstock equivalent, they are
where its standing rulings live, and a finding in one of them is almost always a `high`.
Hunt them early and often.

## reconsider/ is a question for him, not an issue

Everything else the hunter produces is addressed to `/resolve`. This directory is
addressed to the author personally.

When a UX finding contradicts something he has said — a decision recorded in a plan's
`Decisions` table, a reason he gave for a won't-fix, a rule he stated in passing — the
hunter does not file it as a finding against him. It writes
`reconsider/YYYY-MM-DD-<slug>.md` instead: here is what you said, here is what the hunter
saw, here is why it might be different now, and if nothing has changed, ignore this. Files
are date-named rather than numbered, so they need no number-claim lock and can never
collide with an issue or a plan.

A contradiction is more often the hunter misreading a screen than the author having been
wrong, especially when the statement is recent — so the cost of contradicting him is a
question, not a silent finding and not silence.

**`status: kept` on a reconsider file is binding on future runs.** When `/resolve` asks
about a file and he says he still means it, the file is marked `kept` and the hunter must
not raise that question again — it checks `reconsider/` for `kept` exactly as it checks
`issues/resolved/` for `wont-fix`. The other two outcomes are `changed` (he's changed his
mind, and the file becomes a `kind: ux` issue or a plan) and `open` (still waiting on him).

**A ruling in [docs/BEHAVIOUR.md](../../docs/BEHAVIOUR.md) is not reconsider material
either.** Those are rules, not opinions. If the code violates one, that is a `kind: bug`
issue in the `behaviour` area. If the ruling itself looks wrong, say so in the run log and
leave it alone — [CLAUDE.md](../../CLAUDE.md) is explicit that a ruling is never silently
changed.

Start from [TEMPLATE.md](reconsider/TEMPLATE.md).

## The log is the morning read

A run files issues as it goes, so an 8-hour hunt killed at hour 6 keeps everything from
hours 1–5. The report in `log/` is written last and ranks everything filed that night,
worst first — with no cap on how many issues a run may file, that ranking is often the
only thing read end to end.

It also records the snapshot sha the run hunted against, whether a `/build` was running at
the same time, which `checked/` files this run added, and — listed separately from the
issues, because they need him rather than `/resolve` — the reconsider questions raised.

## What it doesn't do

The hunter **writes no code and commits nothing** — it runs while nobody is awake to
review a fix or approve a commit. Everything it produces is a file in `issues/` or here.
Fixing is [/resolve](../issues/README.md)'s job, with the author in the room.

**It never runs the 312/312 guard.** That suite needs the 35 GB mirror and a GPU, takes
~130 s, and its failure is the one thing in this repo that must stop everything and be
looked at by a person. An unattended run that trips it at 3am and files an issue about it
has buried the most important result of the night in a queue. If a hunter believes it has
found engine drift, that is a `high` issue naming the exact bytes — and the hunter says so
in the push notification, first line.

It also files no features. "It would be nice if…" is a [plan](../plans/README.md). A
`kind: bug` issue is a gap between what the repo says it does and what it does; a
`kind: ux` issue is a flow that works but costs the user more than it should, and it must
name the better alternative. Neither is a request for something that doesn't exist yet.
