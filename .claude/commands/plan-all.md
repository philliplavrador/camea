---
description: Plan a whole list at once — new work, the open issues, and repairs to the plans already queued, in one router session
allowed-tools: Bash, Read, Grep, Glob, Write, Edit, AskUserQuestion, Agent, Workflow, TodoWrite, SendMessage, TaskOutput, PushNotification
---

Plan **everything in $ARGUMENTS** — a list of changes, written in one go, straight into
[workflow/plans/queued/](../../workflow/plans/README.md).

If `$ARGUMENTS` is empty, say *"paste the list"* in one line and wait. He usually writes it
while clicking around the app, so expect it unordered, repetitive, jumping between screens,
mixing an engine change with a copy tweak, and trailing off mid-thought. That is the input
this command is built for.

`/plan-all list` · `/plan-all` *(then paste)* · `/plan-all <one long paragraph of everything>`

**This is [/plan](plan.md) done many times over, at the same standard** — same
[TEMPLATE.md](../../workflow/plans/TEMPLATE.md), same recorded decisions, same empty `Open`
section. What changes is the shape of the interview: instead of several rounds about one
feature, it is a few batched rounds across the whole list, with everything that isn't
waiting on an answer being written the entire time.

### Three inputs, one session

**His list is only one of them.** The reason this command exists rather than twenty
`/plan` runs is that all three of these want the same thing from him — his attention, on one
area, once — and he is only sitting here for one of them:

| Input | What it contributes | Where |
|---|---|---|
| **The list** | the new work he asked for | §2 |
| **`workflow/issues/`** | what's already wrong in the areas his list walks past | §3, §8 |
| **`workflow/plans/queued/`** | the plans already waiting, repaired before they are built | §3, §9 |

**The queue is not read-only background.** A plan queued three weeks ago can be malformed,
duplicated by another, contradicted by something he says today, or an uninterviewed stub
that `/build` will refuse — and tonight's build spends all of them. So this command
**repairs plans as well as writing them**, and a run with **no list at all** is legitimate:
it becomes a repair-and-spend-the-issues pass over what is already there.

**One boundary, and it is the only one that matters:** this command edits files under
`workflow/` and nowhere else. It writes no feature code, touches nothing under `src/` or
`web/`, and never runs a suite that writes. A defect outside `workflow/` becomes a plan or
an issue, never an inline fix — see §9.

---

## 1. You are a router — the economics, and why they are the whole design

**You never read a source file, never grep, never write a plan.** Every one of those is a
subagent's job. You have five jobs and no others:

1. Parse the list into numbered items.
2. Dispatch recon, then plan writers.
3. Put pooled questions in front of him with `AskUserQuestion`.
4. Relay answers back down.
5. Report the queue and offer to commit.

The reason is not tidiness. A sweep of twenty items is hours long, and **your context is
the only part of it that cannot be thrown away and re-made.** Every agent you spawn gets a
fresh window that dies when it returns; yours accumulates until the quality of every
remaining decision degrades. So the rule is absolute: **if you are about to open a file to
"just check something", dispatch instead.**

| Discipline | The rule |
|---|---|
| **Distil, don't relay** | An agent may burn 50k tokens and must return **≤40 words plus a file path**. Never a file's contents, never a diff, never a code block. If the evidence matters, it belongs *in the plan the agent writes*, not in your window. |
| **Disk is the context** | Every finding is written to `.scratch/sweeps/<date>/` and passed onward **as a path**. A plan writer opens the recon file itself. Nothing transits you twice. |
| **Brief in four parts** | Every agent gets: objective · exact output format · which sources to read · what is out of bounds. A vague brief is how two agents do the same work and neither does the gap between them. |
| **Append, never revisit** | Don't re-state the list, re-read your own notes, or re-summarise progress. Your turn should grow at the end and never in the middle — that is also what keeps the prompt cache warm across an hours-long run. |

**Schema'd returns, with one escape hatch.** Every agent returns the exact JSON in §3 —
plus a free-text `surprises` field capped at 40 words. The schema is what makes twenty
returns comparable without re-reading them; the escape hatch is what stops the schema
silently eating the one thing that mattered.

**Fan out only on read-only work, and only when the parts are genuinely disjoint.** Recon
is perfectly parallel — every agent reads, none writes. Plan writing is parallel *only*
because each writer owns exactly one file that `claim-number.js` created for it. That is
the entire safety argument, so do not weaken it: no writer edits a second file, ever.

**Recon agents may run on a cheaper model; plan writers inherit this session's.** Recon is
extraction and the schema catches a weak answer. A plan is a document a build session will
follow at 3am with nobody awake to correct it.

### The sweep directory

Create it first, before anything else runs:

```bash
mkdir -p ".scratch/sweeps/$(date +%Y-%m-%d)"   # add -b, -c … if the day already has one
```

| File | Written by | Holds |
|---|---|---|
| `link-check.txt` | you, at §2 | `node scripts/check-links.js` output — part of the repair worklist |
| `list.md` | you, at §2 | the numbered parse — **written before a single agent starts** |
| `NN-recon.json` | each recon agent | one item's findings, in the §3 schema |
| `issues.json` | the issue sweep | what the open queue has to say about the list |
| `plans-audit.json` | the queue sweep | what is wrong with the plans already queued |
| `answers.md` | you, as he answers | every question and his answer, appended |
| `plans.md` | you, at §10 | the closing table |

`.scratch/` is gitignored, so none of this is committed. **It is also the resume point** —
if this session dies at item 14, the next one reads the directory and carries on rather
than re-interviewing him.

## 2. Take the queue's temperature, then parse the list

**Run the link check before anything else** and tee it to `link-check.txt`. It is one cheap
command and every dangling link it names in `workflow/plans/queued/` is a repair you would
otherwise pay a fleet of agents to rediscover.

```bash
node scripts/check-links.js 2>&1 | tee ".scratch/sweeps/$(date +%Y-%m-%d)/link-check.txt"
```

Camea has no `queue:check` equivalent, so the rest of the queue's health is the queue
sweep's job (§3) rather than a script's. Note the broken-link count in one line — *"link
check: N broken, folded into this run"* — and carry on. §9 is where it is spent.

Then split the list into discrete items and show him:

```
 1. [big]     the sweep should show which tiles are anchored
 2. [small]   "Recompute" reads as if it redoes everything
 3. [unclear] "and the thing on the left is weird"
```

- **One item = one outcome he asked for.** Grouping into plans is §6; do not do it here.
- **Never invent an item.** A fragment too vague to act on is `[unclear]` with **his words
  verbatim** — not your best guess at what he meant.
- **Mark duplicates** (`same as 4`) rather than silently dropping them. He repeats himself
  when something matters, and a repeat is a signal about priority, not noise.
- `[big]` touches the engine, changes a flow, or affects more than one screen.
  `[small]` is copy, styling, one component, one route.

Write it to `list.md`, show it, and **stop.** Nothing else runs until he says go or
corrects you. A misread item costs a whole recon agent and, worse, a plan built overnight
that nobody wanted.

**An empty list is a valid run.** Write `list.md` saying so, skip the confirmation, and go
straight to §3 with the issue sweep and the queue sweep only.

## 3. Recon — one agent per item, plus a sweep of the open issues

Spawn one agent per confirmed item, in parallel, in a single message. `[unclear]` items get
a recon agent too: its job is to find the two or three things he *could* have meant and
turn them into a question, which is far better than asking him what he meant with no
context attached.

Each agent grounds the item in the real repo — [docs/BEHAVIOUR.md](../../docs/BEHAVIOUR.md)
for any ruling it lands on, [utils/knowledge/INDEX.md](../../utils/knowledge/INDEX.md) to
route to the right note, [docs/](../../docs/) for the toolchain and the contract, and the
dated handoffs at the top of `utils/knowledge/worklog.md` for what the last session knew.

It writes `.scratch/sweeps/<date>/NN-recon.json`:

```json
{
  "item": 7,
  "headline": "one line — what changes for a person using Camea",
  "today": "what the app does right now, in one or two sentences",
  "files": ["web/src/features/mosaic/Sweep.tsx — the tile rail"],
  "docs": ["docs/BEHAVIOUR.md R21"],
  "rulings": [21, 33],
  "conflicts": [{ "what": "plan 142", "overlap": "covers this already" }],
  "closes": [191, 204],
  "adjacent": [{ "issue": 233, "why": "same component, one line, free while we're here" }],
  "needs": "none | frontend | dev server | engine",
  "datasetKnowledgeRisk": "none | <the number or special case this design would need>",
  "dependsOn": [3],
  "size": "S | M | L",
  "questions": [{ "header": "…", "question": "…", "options": [], "recommend": "…", "why": "…" }],
  "surprises": "≤40 words, anything the schema had no room for"
}
```

Six fields carry the weight:

- ⭐ **`rulings`** — which numbered [BEHAVIOUR](../../docs/BEHAVIOUR.md) decisions this item
  lands on. A plan that changes a ruling without saying so is the worst thing this command
  can produce, because the ruling's e2e test then fails at 3am and reads like a bug.
- ⭐ **`datasetKnowledgeRisk`** — whether the obvious implementation would need the app to
  know something about a particular dataset. If it would, **that is a question for him, not
  a design decision for a writer.** HARD RULE 3 is structural and it is never traded away
  quietly.
- **`needs`** — and `engine` is not a guess. It is `engine` if and only if the item touches
  `src/camea/engine/{t27,t33,quality,render}.py`.
- **`conflicts`** — anything in `plans/queued/`, `active/` or `parked/` that already covers
  or contradicts this, **by number**.
- **`closes` / `adjacent`** — the issue queue. See §8.
- **`dependsOn`** — item numbers this one must follow. `/build all` is serial, so ordering
  is a real constraint and not a preference.

**A question earns its place only when two coherent answers produce genuinely different
code.** "Which shade of grey" does not qualify; the agent picks, and records the choice in
`Decisions` so nobody re-opens it. But a `[big]` item that silently invents a structural
decision he never made is exactly what this command exists to prevent, so on anything that
changes a flow, a ruling, what a user is allowed to do, or what lands on disk — **ask.**

Each agent returns to you **only**: `item`, `size`, `needs`, `dependsOn`, the question
count, any conflict numbers, any non-`none` `datasetKnowledgeRisk`, and the path.

### The issue sweep — the same wave, aimed at the queue

In the **same message**, spawn agents over `workflow/issues/high|medium|low/` — one per
tier, splitting a tier that holds more than ~50 files into halves by number. They are cheap
because they **read frontmatter first** (`title`, `kind`, `tier`, `confidence`) across the
whole tier and open a body only for something that matches. Give them `list.md`: the
question they answer is *"which of these issues does his list already walk past?"*

They write one shared `.scratch/sweeps/<date>/issues.json`, each agent appending its block:

```json
{
  "attached":    [{ "item": 7, "issues": [191, 204], "why": "same screen, same component" }],
  "clusters":    [{ "name": "outputs panel drift", "issues": [88, 130, 176], "size": "M" }],
  "contradicts": [{ "item": 3, "issue": 233, "what": "one sentence — what he can't have" }],
  "undecided":   [{ "item": 5, "issue": 247, "question": "the open question, verbatim" }],
  "read": 127, "matched": 19
}
```

Four outputs, in descending order of how much they are worth:

- **`contradicts`** is the reason this sweep exists. An open issue saying the thing he wants
  to build is already broken in a specific way changes what the plan has to do — and finding
  that out *after* the overnight build is finding it out too late. Every entry becomes a
  question in §5.
- **`undecided`** — an open issue that is *itself an unanswered question* rather than a
  defect. **He is right here.** Ask it now, verbatim. That is the single highest-value thing
  this hybrid does, because those issues exist precisely because nobody could reach him.
- **`attached`** — issues in a file a plan is already opening. Free work; §8 says how.
- **`clusters`** — issues nobody's item covers, but which are one coherent plan between
  them. Propose the strong ones as extra items; **do not queue them silently.**

**Do not let the sweep read the whole backlog deeply.** It matches against his list and
stops. An issue that matches nothing is left exactly where it is, untouched and still open,
for [/resolve](resolve.md) — and `read` / `matched` is how you prove at close-out how much
of the queue was actually considered.

### The queue sweep — auditing the plans already waiting

In the **same message** again, spawn agents over `workflow/plans/queued/` and `parked/` —
one per ~8 plans. Each is handed `link-check.txt` and `list.md`, and reads only frontmatter
plus `## Open`, `## Rulings this touches`, `## Affected` and `## Deploy`. **Unlike the issue
sweep, this one reads every plan in its slice**, because a plan that nothing in the list
matches is still going to be built tonight.

They append to `.scratch/sweeps/<date>/plans-audit.json`:

```json
{
  "broken":     [{ "plan": 139, "fail": "needs: missing; touches engine/t33.py", "repair": "mechanical", "fix": "set needs: engine" }],
  "stub":       [{ "plan": 141, "why": "body says DO NOT BUILD IT" }],
  "superseded": [{ "plan": 142, "item": 3, "what": "one sentence — how his list changes it" }],
  "duplicate":  [{ "plans": [107, 127], "overlap": "both rework the same panel" }],
  "stale":      [{ "plan": 130, "why": "premise reversed by BEHAVIOUR R44" }],
  "outside":    [{ "fail": "docs/BEHAVIOUR.md R31 has no e2e test", "where": "web/tests/e2e/" }],
  "clean":      [123, 129, 136],
  "read": 25
}
```

⭐ **The single most valuable thing this sweep finds is a plan whose premise a later ruling
reversed.** R44 (2026-08-10) reversed R42/R43 on where things save, so any plan written
before that date which mentions a save path, a folder prompt or a draft is `stale` and must
not be built as written. Check the date on every plan against the rulings it touches.

Every entry carries **`repair: mechanical | decision | outside`** — that classification is
the whole output, and §9 says what each one means. Getting it wrong in the safe direction
costs a question; getting it wrong the other way rewrites a plan he never agreed to change,
so **when a repair is arguable, it is `decision`.**

`clean` and `read` matter as much as the findings: a queue sweep that names five broken
plans and cannot account for the other twenty has not audited the queue, it has skimmed it.

## 4. Split the wave — the clear items start writing immediately

Partition on `questions.length`, counting the issue sweep's `contradicts` and `undecided`
entries as questions against the items they name, and counting any non-`none`
`datasetKnowledgeRisk` as a question:

- **Clear** → dispatch their plan writers **now**, in the background, before he has
  answered anything.
- **Blocked** → pool their questions for §5.

**Every `repair: mechanical` entry is clear by definition** — it has no question in it, so
its repair writer goes out in this same first wave.

**Do not hold the clear items behind the question rounds.** They share no files with the
blocked ones and depend on none of the answers. By the time he has answered round one, half
the queue should already be written.

## 5. The question protocol — batched, plain, and never in prose

`AskUserQuestion`, every time. One or two plain sentences, no jargon, no `file:line`, no
internal vocabulary *in the question itself*; the reasoning goes in the message above it
where it is optional reading. Terse options, recommendation first. The full rule and the
words that trip him up are in
[workflow/README.md § Asking the author a question](../../workflow/README.md#asking-the-author-a-question).

**Batch up to four at a time, grouped so they read as one screen's worth of thinking** —
all the sweep questions together, all the project-manager ones together. Two fat rounds beat
six thin ones: each round is a context switch for him, and he answers quickly and in volume
when the questions are short and related.

`PushNotification` when a round is ready and he may have walked away. Append every question
and its answer to `answers.md` **as it arrives** — that file, not your context, is what the
plan writers read.

**Issue-derived questions read exactly like the others.** Put the issue number in the prose
above, never in the question. An `undecided` question is asked **in its own words**.

⭐ **A `datasetKnowledgeRisk` question is asked as a design question, never as a permission
request.** Not *"may we hard-code 338?"* — the answer to that is always no and asking it
wastes a round. Ask *"the app can't know how many frames a dataset has ahead of time — should
it count them when the folder is opened, or ask you to confirm the number?"*

**Where an item isn't ready to plan, offer "file it as an issue instead"** as one of the
options, worded plainly. That is a real answer for anything he raised in passing and hasn't
thought through, and offering it makes deferring the cheap default. Say which items went
that way at close-out.

## 6. Group — you decide, but announce the split first

He asked for this call to be yours. Make it, then show it as one line per plan **before any
writer starts**, so objecting costs him a sentence rather than a rewrite.

**Default to one plan per item.** Merge two only when they touch the same files — a split
there means a second serial build re-opening code the first one just closed. **Never merge
across subsystems because the items sound related.**

Split an item the other way when it hides two independent outcomes with different `needs:`.
⭐ **Never fold an `engine` change into a plan that is otherwise `frontend`** — it drags the
whole plan behind a ~130 s hardware-bound guard, and a build team that fails the guard
abandons the frontend half too.

**An issue cluster he accepted becomes its own plan**, never a rider on one of his.

## 7. Write — one agent, one file, no exceptions

One writer per plan file. Each one:

- **Claims its own number**: `node scripts/claim-number.js plan <slug>`, which prints
  the path it created. Never hand-count — the script is atomic and parallel writers are
  safe only because they use it.
- **Reads its inputs from disk** — `NN-recon.json`, `list.md`, `answers.md`, `issues.json`.
  You do not paste any of that into its brief; you pass the paths.
- **Reads the body of every issue it closes**, so the plan carries that evidence forward.
- **Owns exactly one file.** It edits nothing else. It never runs `git stash`, `git reset`,
  `git checkout -- <path>`, `git restore`, or `git clean` — any one of those destroys every
  other writer's work in this checkout.
- Writes from [TEMPLATE.md](../../workflow/plans/TEMPLATE.md), fills `Decisions` with his
  actual answers in his words where the wording matters **plus every choice recon made on
  his behalf**, and fills **Explicitly rejected** with anything he ruled out in §5.
- ⭐ **Fills `Rulings this touches`** from recon's `rulings`, or writes `none`. If the plan
  changes a ruling, `Done when` must include updating its e2e test.
- **Leaves `Open` empty.** Anything that would land there is a question §5 should have
  asked; a writer that finds one **reports it back rather than writing it down**.
- Sets `needs:` honestly (`frontend` when unsure, `engine` when the four guarded files are
  touched), `blocked-by:` from the dependency graph, and `resolves:` from `closes` (§8).
- Writes `Verify` as exact commands and `Done when` as checkable statements.
- **Gets its link depth right.** A plan sits at `workflow/plans/queued/`, three levels under
  the root, so links out start with `../../../`.

**A repair writer is the same agent with an older file.** It owns one existing plan, is
handed `plans-audit.json` and the entry it is fixing, and obeys every rule above. Two
additions, because it is editing something somebody already agreed to:

- **Change the least that closes the fault.** A mechanical repair adds the missing line and
  stops. It does not restructure the plan, re-word its `Decisions`, or "improve" anything it
  was not sent for — those were his answers in an earlier interview, and rewriting them
  silently is how a recorded decision turns into an invented one.
- **Append a dated line to `Decisions`** saying what was repaired and why: `| Repaired
  2026-08-13 | Set needs: engine — the plan edits t33.py |`.

## 8. Issues — the half of `/resolve` this command does

| Where it came from | What happens |
|---|---|
| His item **is** a filed issue (`closes`) | The plan closes it. Not optional — he asked for it. |
| An issue **contradicts** an item | Becomes a question in §5. His answer goes in the plan's `Decisions`, and the issue closes with it. |
| An **`undecided`** issue blocks an item | Asked verbatim. Settled → closes. Not settled → the item is planned around it or dropped, and the issue stays open. |
| An **adjacent** or **clustered** issue | *Offered*, never assumed. See below. |
| Anything else in the queue | **Left open and untouched.** |

**Two exits, not three.** [/resolve](resolve.md) can fix an issue inline; this command
cannot, because it writes no code — so an issue either becomes a plan here or stays where it
is. **Never fix one "while you're passing".** And never mark an issue `wont-fix` on your own
reading: that is a decision, and it needs him to say it.

**Closing is yours, not a writer's.** The plan writer records the numbers in `resolves:` and
names them in `Done when`; **you** move the files, so two agents never touch one:

```bash
git mv workflow/issues/<tier>/NNN-slug.md workflow/issues/resolved/NNN-slug.md 2>/dev/null \
  || mv workflow/issues/<tier>/NNN-slug.md workflow/issues/resolved/NNN-slug.md
```

…then set `status: resolved` and `resolved-by: plan NNN`. Re-check the file is still in its
tier directory immediately before moving it: a concurrent `/resolve` may have closed it
first, and if so, skip it and say so.

**If a plan is later abandoned, its issues come back.** `resolves:` is what makes that
recoverable.

**Adjacent issues and clusters are offered in one round, not assumed.** A single multi-select
near the end — adjacent ones as *"these small ones are in files we're already opening — fold
any in?"*, clusters as one line each with their size. **Order that list by what it costs to
leave undone**, not by how easy it is.

**Anything recon noticed that he did not ask for and that isn't adjacent gets filed as a new
issue**, with evidence — never smuggled into a plan as a bonus.

**The line between this and [/resolve](resolve.md):** `/plan-all` spends the issues his list
walks past, while he is here to decide them. `/resolve` still owns the rest of the queue.

## 9. Repairs — the plans that were already waiting

### `mechanical` — the plan is right, the file is malformed

Repair inline, no question, in the first wave. The test is strict: **would he recognise the
repaired plan as the one he agreed to?** If yes it is mechanical; if you have to think about
it, it is a `decision`.

| The fault | The repair |
|---|---|
| `needs:` missing, or wrong for what the plan does | set it; `frontend` when unsure, `engine` when it edits a guarded file |
| `blocked-by:` names a plan now in `done/` | drop the hold — it has cleared |
| a dangling link, or a link at the wrong depth | fix it (`node scripts/check-links.js` names them) |
| `Rulings this touches` absent, and recon found rulings | fill it in from recon |

**One trap, and it is the one that looks most like a repair.** A queued plan whose
`blocked-by:` names a plan that is *also still queued* is **not broken** — the hold is doing
its job and clears with no edit the moment the blocker lands. **Never repair that by
deleting the hold.** Say in one line which of these will self-clear during tonight's run.

### `decision` — the plan's content is in question

These get a question in §5, and there are only ever three answers:

- **Interview it back into shape** — a repair writer rewrites the plan from his answer. This
  is the only exit for a `stub`; a plan that says `DO NOT BUILD IT` is a plan nobody ever
  finished interviewing, and finishing it is exactly what this session is for.
- **Park it** — `git mv` to `parked/`, with the reason in the file.
- **Abandon it** — `git mv` to `done/`, `status: abandoned`, and a line saying why. Its
  `resolves:` issues come back out of `resolved/` in the same breath.

`superseded`, `duplicate` and `stale` are always `decision`. ⭐ A plan made stale by a
**ruling reversal** is the case to bring to him first, worded as *what changed*, not as
*what is wrong with the plan* — the plan was right when it was written.

**Nothing is ever deleted.**

### `outside` — the fault is not in `workflow/`

The sweep can name a defect in the repo rather than in a plan — a BEHAVIOUR ruling with no
e2e test, a doc that contradicts the code. **Do not fix it here.** It becomes a plan if it
needs building, or an issue with its evidence if it does not, and either way it is named at
close-out. The line holds even when the fix is one obvious line: this command's whole safety
argument is that it writes nothing outside `workflow/`.

## 10. Close out

- **Run the link check again** and diff it against `link-check.txt`. **A sweep that ends
  redder than it started has to say so in its first line.**
- **One table**, also written to `plans.md`. `New?` distinguishes what this run wrote from
  what it repaired:

  | Plan | Title | New? | `needs` | `blocked-by` | Rulings | Size | Closes |
  |---|---|---|---|---|---|---|---|

- **What the repair pass did**: `N read` from `plans-audit.json`, then plans repaired
  mechanically (one line each), plans re-interviewed, plans parked or abandoned and why,
  holds left standing because they self-clear tonight, and faults handed outward. **Every
  plan in `queued/` is accounted for.**
- **The intended build order**, from the dependency graph. ⭐ **Say where the `needs: engine`
  plans sit** — they belong last, and each costs ~130 s of guard on top of everything else.
- **What the issue queue did**: `N read, M matched`, then issues closed (with the plan that
  closed each), issues he declined to fold in, open questions he settled here, and new issues
  filed. **The queue must balance.**
- **Items filed as issues instead of planned**, and items dropped, each with the reason.
- **Say plainly if the queue is bigger than one night of serial building**, and name which
  plans to cut or park.
- **Offer to commit.** `workflow/` is tracked and the commit is his call — do not commit
  unprompted.

Then stop. Building them is [/build](build.md)'s job, in its own session.
