---
description: Hunt for bugs, UX problems and contradictions for a fixed span, filing what it confirms
allowed-tools: Bash, Read, Grep, Glob, Write, Edit, Agent, Workflow, AskUserQuestion, TodoWrite, Skill, WebFetch, PushNotification
---

Hunt this repo for things that are **wrong** — bugs, contradictions, gaps between what
the docs claim and what the code does — and for things that merely **cost the user more
than they should**, for the span named in `$ARGUMENTS`. File what survives into
[workflow/issues/](../../workflow/issues/README.md).

`/bug-hunter 8 hours` · `/bug-hunter overnight heavy` · `/bug-hunter 90m api behaviour` ·
`/bug-hunter 2h ux max`

**This command runs unattended.** He is asleep or out. That shapes every rule below:
nobody is available to answer a question, approve a commit, or notice that you have
gone quiet for two hours.

## The five hard rules

1. **Write no code.** The only files this command creates or edits are
   `workflow/issues/**`, `workflow/hunts/**` and `workflow/said/**`. Not a single fix,
   not even a one-line obvious one — a fix nobody reviewed, committed at 3am, is worse
   than the bug. Fixing is [/resolve](resolve.md)'s job, with him in the room.
2. **Never commit, never push.** There is nobody to ask. Issues on disk survive fine;
   he commits them in the morning.
3. **Land findings as you go, never at the end.** Write each round's record and issues
   and update the coverage log *before* starting the next round. A run killed at hour 6
   must keep everything it found in hours 1–5. Treat every round as if it were the last.
4. **Never touch the main checkout's tracked files.** Code hunting happens in the
   hunter's own worktree (step 2), because a `/build` session may be editing the same
   files underneath you and a finding cited against a half-written file is noise. You
   read from the worktree and you write into the **main checkout by absolute path** —
   `workflow/issues/`, `workflow/hunts/`, `workflow/said/` and nothing else.
5. ⭐ **Never run the 312/312 guard.** `tests/slow/test_solver_312.py` needs the 35 GB
   mirror and a GPU, takes ~130 s, and its failure is the one result in this repo that must
   stop everything and be looked at by a person. An unattended run that trips it at 3am and
   files an issue has buried the most important thing of the night in a queue. If you
   believe you have found engine drift, file it as a `high` naming the exact bytes, and
   **lead the push notification with it.**

## 1. Work out the deadline and the intensity, and commit to both

Parse a duration, an optional intensity word, and an optional area list from
`$ARGUMENTS`. They may appear in any order: `/bug-hunter 8h heavy api ux` is eight
hours, heavy, areas `api` and `ux`. `overnight` means 8h. Bare numbers mean hours.
If **no** duration is given, he is at the keyboard — ask him once with
`AskUserQuestion` (1h / 4h / 8h), then proceed.

Stamp the clock and hold the deadline in your head for the whole run:

```bash
date +%s && date '+%Y-%m-%d %H:%M'
```

`DEADLINE = start + duration`. Before every round, re-run `date +%s` and compare —
never trust elapsed-time intuition across a long run, because you do not have one.

**Reserve the last 15 minutes for wrap-up.** If under 15 minutes remain, stop hunting
and go to step 11. If a round would obviously overrun the deadline, don't start it;
start a narrower one instead.

**Do not stop early.** If a round finds nothing, that is information, not a finish
line — record the dry round and move to the next-stalest area with a *different*
angle. Use the whole span he asked for.

### The intensity dial

One word. Default `normal` when absent. It moves everything at once, so he only has to
think about one number:

| Level | Areas swept at once | Finders per area | Skeptics per finding |
|---|---|---|---|
| `light` | 1 | 3 | 1 |
| `normal` | 2 | 5 | 3 |
| `heavy` | 4 | 8 | 3 |
| `max` | 6 | 12 | 5 |

Two rules hold at every level:

- **Skeptic count is a panel size; the bar is always a majority.** At `light` one
  refutation kills a finding. At `normal` and `heavy` it takes 2 of 3 skeptics failing
  to refute. At `max`, 3 of 5. The bar never moves — only how many people it asks.
- **Concurrency is capped by the Workflow runtime at `min(16, cores-2)` per workflow.**
  At `max` some agents will queue rather than run at once. Say so in the log rather
  than pretending the fleet was bigger than it was.

## 2. Set up the private copy — before any hunting

```bash
git worktree add ../Camea-hunt HEAD --detach
```

Detached at `HEAD` means you read **the last committed version**, and detached means there
is no branch — nothing to merge, nothing to review, one `git worktree remove` to clean up.
That matters because `/build` may be committing to `master` in this checkout all night, and
a hunter reading half-saved files reports bugs that were never real. Record the sha in the
run log so every finding can be traced to the code it was found in.

**No setup script is needed and you must not run one.** The worktree has no `.venv` and no
`web/node_modules`, and that is correct: this copy is for *reading*. It cannot run the
suites and it is not supposed to. The two areas that need a running app (`ui`, `ux`) use
the main checkout's dev servers — see step 4.

⚠️ **`data/`, `archive/` and `utils/` are gitignored and are therefore ABSENT from the
worktree.** That is fine for every code area. It means the worktree cannot check engine
drift against `archive/analysis/mosaic/`, and cannot read the knowledge base — do both of
those against the **main checkout, read-only**, and say in the round record that you did.

If `git worktree add` fails because a stale `../Camea-hunt` is left over from a killed
run, remove it and retry once. If it still fails, hunt the main checkout read-only and
**say so in the log** — a finding read cold in the morning needs to carry the caveat that
a build may have been mid-write.

Tear it down at wrap-up:

```bash
git worktree remove ../Camea-hunt --force
```

## 3. Read the coverage log — it decides what you look at

```bash
cat workflow/hunts/coverage.json
ls workflow/hunts/log/ workflow/hunts/checked/
```

[coverage.json](../../workflow/hunts/README.md) records, per area: when it was last
hunted, which **angles** have been used on it, and what came out. It exists so that a
run every night for two weeks doesn't check the same three things fourteen times.

Pick the round order:

- **Stalest first** — the area with the oldest `lastHunted` (`null` = never, goes first).
- **But weight by yield**: an area that produced a confirmed `high` last time is worth
  revisiting sooner than its date alone suggests. Say when you override staleness.
- **Never repeat an angle** listed under that area until every other angle has been tried.

Run as many areas at once as the dial allows. If `$ARGUMENTS` names areas, hunt only
those, still stalest-angle-first within them.

**The area table lives in [workflow/hunts/README.md § The areas](../../workflow/hunts/README.md#the-areas)**
— read it there rather than duplicating it here, so there is one place it can drift out of.
The three starred areas — `dataset-knowledge`, `storage` and `behaviour` — are Camea's own,
they are where its standing rulings live, and a finding in one of them is almost always a
`high`. On a first-ever run, hunt those three first regardless of what staleness says.

## 4. The browser, and the port rule

`ui` and `ux` want the running app, and this is the one documented exception to the
private copy — the worktree has no `node_modules` and cannot serve anything.

```bash
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:5173
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/openapi.json
```

- **Something is listening** → use it. Do not restart it. A `/build` session may own those
  servers. Check `workflow/.locks/main-checkout.json` — if it exists, a build holds the main
  checkout and the servers are its.
- **Nothing is listening** → you may start them yourself from the main checkout, and you
  **must stop them at wrap-up** if you were the one who started them. Record that you did.

  ```bash
  uv run camea --headless --port 8000 --open tests/fixtures
  cd web && npm run dev
  ```

  `tests/fixtures` holds the committed synthetic dataset (~5.6 MB). Use it. **Never point
  the app at `data/`** — that is the read-only 35 GB mirror, and an unattended session has
  no business anywhere near it.
- **They won't start** → skip `ui` and `ux`, record `skipped` (not `dry`) in coverage,
  and take the next area. A skipped area must never read like a clean one.

Drive at the viewport the e2e suite uses (`devices['Desktop Chrome']`, per
`web/playwright.config.ts`) so what you see is what the tests see. Screenshots go to your
scratchpad or `.scratch/`, **never the repo root**.

## 5. Each round is a Workflow, and it forks by area

The slash command you were invoked by is the opt-in for the `Workflow` tool — use it.
A round is one Workflow call: fan out finders across the area, then run the candidates
through a panel. Finder and skeptic counts come from the dial in step 1.

Which panel depends on the area:

- **Code and doc areas** (`dataset-knowledge`, `storage`, `engine`, `core`, `api`,
  `features`, `frontend`, `behaviour`, `docs-vs-code`, `knowledge-base`, `claude-md`,
  `edge-cases`, `workflow`, and anything in `ui` that is actually *broken*) run
  **find → refute**. A finding files only if a majority of skeptics *failed* to refute it.
  Skeptics read the real files and default to refuted when uncertain.
- **UX areas** (`ux`, and the merely-worse half of `ui`) run **find → rate**. You cannot
  refute an opinion, so the panel scores it instead: is this genuinely worse than the
  alternative proposed, and would a first-time user actually hit it? The panel's agreement
  becomes the finding's `confidence:` — unanimous is `high`, a majority is `medium`, a
  split is `low`. **All three still file.** He asked to filter these himself.

```js
export const meta = {
  name: 'bug-hunt-round',
  description: 'Find and judge candidates in one area',
  phases: [{ title: 'Find' }, { title: 'Judge' }],
}
const { finders, skeptics } = DIAL[intensity]   // §1: light/normal/heavy/max
const LENSES = ANGLES_FOR_AREA.slice(0, finders)
const REFUTE_LENSES = [            // distinct ways to kill a finding; the dial picks how many
  'does the cited line actually say this', 'is this reachable in real use',
  'has something else already handled it', 'does the repo already test or guard this',
  'is the cited file even the one that runs at that path',
]
const results = await pipeline(
  LENSES,
  l => agent(l.prompt, { label: `find:${l.key}`, phase: 'Find', schema: FINDINGS }),
  found => parallel(found.findings.map(f => () => (
    f.kind === 'ux'
      // Rate: how sure are we this is genuinely worse, and would a real user hit it?
      ? parallel(Array.from({ length: skeptics }, () => () =>
          agent(`RATE this UX candidate against the alternative it proposes.\n\n` +
                `${JSON.stringify(f)}\n\nWould a first-time user hit it?`,
                { phase: 'Judge', schema: RATING })))
          .then(rs => ({ ...f, survives: true, confidence: agreement(rs) }))
      // Refute: run `skeptics` distinct refuters (the dial sets the count); a majority
      // must FAIL to kill it — 1 refuter at light, 2 of 3 at normal/heavy, 3 of 5 at max.
      : parallel(Array.from({ length: skeptics },
                 (_, i) => REFUTE_LENSES[i % REFUTE_LENSES.length]).map(lens => () =>
          agent(`Try to REFUTE this finding via: ${lens}\n\n${JSON.stringify(f)}\n\n` +
                `Read the real files. Default to refuted=true when uncertain.`,
                { phase: 'Judge', schema: VERDICT })))
          .then(vs => ({ ...f,
            survives: vs.filter(Boolean).filter(v => !v.refuted).length > skeptics / 2 }))
  )))
)
return results.flat().filter(Boolean).filter(f => f.survives)
```

**The refute pass is not optional and not a formality.** An unattended hunter's
characteristic failure is a pile of confident, plausible, wrong findings — and he reads
them cold in the morning with no way to tell which is which.

Have finders return, for every candidate: the screen or the exact `file:line`, the
literal text there, what is wrong (or what is worse), what a real user experiences today,
a proposed tier, and — for UX only — **the alternative it thinks is better, in one
sentence**. "This is awkward" with no alternative is not a finding. A *bug* candidate with
no `file:line`, no reproducing command and no measured number does not survive. A *UX*
candidate's bar is deliberately lower — a real screen, and what a first-time user hits.

⭐ **A `dataset-knowledge` candidate needs the literal token quoted.** "This looks
dataset-specific" is not a finding; `src/camea/features/mosaic/x.py:44 hard-codes 338` is.
The one legitimate place for numbers is `tests/` and `src/camea/engine/` — a finding
against either of those is wrong, and the panel should kill it.

Rounds are typically 20–45 minutes; prefer more rounds over one enormous one, because a
round is the unit that survives a crash.

## 6. The said-check — every UX candidate, before it becomes anything

A UX candidate is an opinion about how the app should work, and he has already stated a
lot of opinions about that. Check each one against
[workflow/said/ledger.md](../../workflow/said/README.md) — the dated record of what he
has said, which this command also grows as it goes (step 11).

Search the ledger for statements on the candidate's topic, then:

- **Nothing on the topic** → file it as a normal `kind: ux` issue.
- **A statement that agrees** → file it, cite the statement as supporting evidence, and
  raise `confidence:` one level.
- **A statement that contradicts it** → **do not file an issue.** Write a reconsider
  file instead (step 7).

**Recency is trust, but it is not proof.** Weight a statement by its date, per the table in
[said/README.md § Trust decays with age](../../workflow/said/README.md#trust-decays-with-age).
Camea has moved fast — the project-manager reframe landed 2026-07-24, and R44 reversed
R42/R43 on 2026-08-10 — so a statement about where a project saves, made in July, is about
an app that no longer exists.

**Never treat a statement as unfalsifiable.** He said explicitly not to trust everything
he has said. The rule is only that contradicting one costs a *question* rather than silence.

**A statement in `CLAUDE.md` or in [docs/BEHAVIOUR.md](../../docs/BEHAVIOUR.md) is a rule,
not an opinion.** Those aren't reconsider material. If the repo violates one, that is a
`kind: bug` issue in the `claude-md` or `behaviour` area; if you think the rule itself is
wrong, say so in the run log and leave it alone.

## 7. The reconsider pile — the only thing you write addressed to him

`workflow/hunts/reconsider/YYYY-MM-DD-<slug>.md`, from
[TEMPLATE.md](../../workflow/hunts/reconsider/TEMPLATE.md). Date-named rather than
numbered, so it needs no lock and can never collide with an issue or a plan number.

Four body sections, all required: **What you said** · **What the hunter saw** · **Why it
might be different now** · **If nothing has changed, ignore this** (an explicit escape
hatch, always present, so the file costs him five seconds to dismiss).

[/resolve](resolve.md) reads this pile and asks about each one. He answers `kept` (the
statement's date is refreshed and you must not raise it again) or `changed` (the ledger
entry is superseded and the file becomes a `kind: ux` issue or a plan).

**A `kept` reconsider is binding on you.** Check `reconsider/` for `status: kept` before
raising anything, exactly as you check `resolved/` for `wont-fix`.

## 8. Write down everything you checked

Every round writes `workflow/hunts/checked/YYYY-MM-DD-HHMM-<area>-<angle-slug>.md`
**before that round's issues are filed**, so a crash keeps the record of the work even
when it loses the conclusions.

```markdown
---
run: YYYY-MM-DD-<duration>
area: api
angle: writes outside outputs/
intensity: heavy
finders: 8
snapshot: <sha the hunt worktree is detached at>
started: HH:MM
ended: HH:MM
---

## Files opened
One line each: path, and what was being looked for in it. Every file a finder actually
read — not the ones it globbed past.

## Candidates raised
A table: what · where · verdict (`filed NNN` / `refuted` / `duplicate of NNN` /
`covered by plan NNN` / `already resolved` / `wont-fix, see NNN`).

## Rejected, and why
Every candidate that did not file, with the specific reason it died — which skeptic
killed it and with what.

## Nothing was found in
Paths swept clean under this angle.
```

The `Rejected` section is the point of the whole file: **it is what stops the next run
re-finding the same non-issue and spending another panel on it.** So use it — before
raising a candidate, grep this directory. A candidate already rejected under the same
angle does not get a second panel unless the code has changed since, and if it has, say
which commit changed it.

## 9. Dedup before you write — this is what makes a nightly run bearable

Without this step, night three refiles everything night one found.

```bash
ls workflow/issues/high/ workflow/issues/medium/ workflow/issues/low/ workflow/issues/resolved/
grep -ril "<the file or symbol>" workflow/issues/ workflow/hunts/checked/ workflow/hunts/reconsider/
```

Drop a finding if:

- An **open** issue already covers it. Don't file a second; if you learned something
  new, append it to the existing issue's `Evidence` and say you did.
- A **`resolved/` issue** covers it. Check the `status:` — **`wont-fix` means he
  already decided, and refiling it wastes the same conversation twice.**
- A **queued or active plan** already fixes it.
- A **`reconsider/` file with `status: kept`** covers it.
- A **prior round rejected the same candidate under the same angle** (step 8), and the
  code hasn't changed since.
- It's a **feature request**. "It would be nice if…" is a [plan](plan.md), never an
  issue — and that holds for UX findings too.
- You'd have fixed it in one line if you were allowed to. You aren't allowed to here,
  so it does get filed — but as `low`, and say it's a one-liner.

## 10. File them — the number comes from a script, the body comes from you

He asked for **no cap**, so every confirmed finding gets a file. That makes two things
load-bearing.

**Numbering is yours alone**, and it comes from
[claim-number.js](../../scripts/claim-number.js). Picking a number by reading the
directory races with `/resolve` and with a `/build` session filing at the same moment:

```bash
node scripts/claim-number.js issue <tier> <slug>   # prints the claimed path
```

Subagents return findings as data; **you** claim the numbers, one at a time, and write
the body into the path the script printed. Never let a parallel agent claim one.

**Rank before you write.** Write in descending severity so the numbers themselves carry
the reading order for the night. Tier by
[issues/README.md](../../workflow/issues/README.md): measured against **the science and the
hours of hand-verification sitting in a saved project**, not against how alarming the code
looks. Between two tiers, file the higher one. The
[four that are always `high`](../../workflow/issues/README.md#the-four-that-are-always-high)
are not judgement calls.

Each file comes from [TEMPLATE.md](../../workflow/issues/TEMPLATE.md), with
`found-while: /bug-hunter <date> — <area>/<angle>` so `/resolve` knows it came from a
machine sweep. Note in `Evidence` how many skeptics tried to refute it and failed (bugs),
or how the rating panel split (UX).

A `kind: ux` finding defaults to **`tier: low`**. It may be `medium` only if a real user
is *blocked* or led into a wrong action, and it is **never `high`** — nothing that merely
costs a user time outranks something that loses their afternoon's verification.

## 11. Wrap up — the log is what he actually reads first

Write `workflow/hunts/log/YYYY-MM-DD-<duration>.md`:

- What you ran: start, end, duration asked vs. actually used, intensity, rounds
  completed, **the snapshot sha** the hunt worktree was detached at, and whether a
  `/build` was running against the main checkout at the same time.
- **A ranked table of everything filed** — number, tier, kind, one line, the file it's
  in. This is the morning's reading order, and with no cap it may be the only thing he
  reads end to end. Put the highs at the top and make each line stand alone.
- **Reconsider questions raised**, listed separately from the issues.
- Areas hunted, with the angle used on each, and what each round yielded.
- **Dry rounds, named.** "`core` came back clean under the cancellation lens" is a real
  result and stops the next run repeating it.
- **Coverage delta** — which `checked/` files this run added.
- **What you did not get to**, and why. Never let a skipped area look like a clean one.
- Whether you started the dev servers, and whether you stopped them.
- Anything you saw that isn't an issue but is worth his attention.

Then, in order:

1. **Grow the ledger.** Scan for statements newer than `lastScanned` in
   [workflow/said/ledger.md](../../workflow/said/README.md) and append what you find,
   dated from git, never invented. Update `lastScanned` and `lastScannedSha`. **The first
   run does a full pass over `docs/BEHAVIOUR.md`, `CLAUDE.md`, the git log and the dated
   handoffs in `utils/knowledge/worklog.md`, which is slow — budget for it.**
2. **Update `coverage.json`**: `lastHunted`, the angle used, findings by tier and kind,
   `lastResult` (`found` / `dry` / `skipped`), and the run's row. **Update it even for a
   dry round.**
3. **Tear down the hunt worktree** (`git worktree remove ../Camea-hunt --force`).
4. **Stop any dev servers you started.** Leave alone any you didn't.

If you established a **non-obvious fact by measurement** along the way, record it in the
relevant `utils/knowledge/` file with its evidence, per [CLAUDE.md](../../CLAUDE.md). A
*bug* is an issue; a *fact about the repo* is knowledge. Don't confuse them.

Finish with a short message he'll read on his phone: hours run, issues filed by tier and
kind, reconsider questions raised, the single worst thing you found, and `/resolve` as
the next step.

**Send that message as an actual `PushNotification`, not only as terminal text** — the run
ends while he is asleep. **The body leads with the single worst thing you found, named** —
*"014 high: recompute re-places a tile the user anchored"* — never *"11 issues filed"*; a
count is nothing he can act on from a lock screen. ⭐ **If you found suspected engine
drift, that goes first, always**, whatever else the night turned up.
