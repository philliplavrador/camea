# said/ — the record of what you've said, with dates on it

`/bug-hunter` files UX findings: *this works, but it may not be the best way to do it.*
That kind of finding is only useful if it can be checked against what you already decided.
Otherwise the hunter spends a night carefully re-proposing something you considered and
rejected in July, and you spend a morning saying no again.

The problem is that nothing holds your decisions in one place. They're real, and they're
written down — in `docs/BEHAVIOUR.md`, in plan `Decisions` tables, in won't-fix reasons, in
commit messages, in the dated handoffs at the top of `utils/knowledge/worklog.md` — but
they're scattered with no dates you can compare and no way to search them by topic.

That is what [ledger.md](ledger.md) is. A dated list of things you've said, mined from
the repo, each one citing where it came from.

```
said/
├── README.md   this file — what it is, how it grows, how much to trust it.
└── ledger.md   the entries. Append-only.
```

## The one thing to keep in mind

**This is evidence about you, not instructions from you.** Every entry is somebody's
reading of something you wrote, and a reading can be wrong — wrong about what you meant,
wrong about the version of the app you meant it about, or right at the time and stale
now. It is useful because it cites its evidence, not because it is authoritative.

So anything built on the ledger that actually matters gets **asked about, not assumed**.
The ledger is what makes the question a good one; it is never the answer.

## How it grows

It is built as the hunter goes, not maintained by hand. Each `/bug-hunter` run scans for
statements newer than the ledger's `lastScanned` date and appends what it finds; the
first run does a full pass over everything. That way the cost is paid a little at a time,
in a session that is already reading the repo anyway.

## Where statements come from, and how each is dated

| Source | The statement | Its date |
|---|---|---|
| [docs/BEHAVIOUR.md](../../docs/BEHAVIOUR.md) rulings | the ~44 decisions you paid days to discover | the commit that added the line (`git log -L`) |
| `workflow/plans/**` `Decisions` tables | the answer you gave in the interview | the plan's `created:` |
| `workflow/plans/**` `Explicitly rejected` | what you turned down, and why | the plan's `created:` |
| `workflow/issues/resolved/*` with `status: wont-fix` | the reason you gave | the file's `found:`, or the commit that resolved it |
| git commit messages | what a change was for, in your words | the commit date |
| `CLAUDE.md` | rules, not opinions — see below | the commit that added the line |
| root `docs/` | ground truth, outranks everything | the commit that added the line |
| `utils/knowledge/worklog.md` handoffs | what a session recorded you deciding | ⚠️ **the date written in the entry's own heading** — `utils/` is gitignored, so `git log` knows nothing about it |
| `workflow/hunts/reconsider/` with `status: kept` | you re-confirmed it | the date you confirmed it |

Dates come from `git log`, never from guessing — a guessed date is worse than no date,
because the recency rules below then weight it as though it were established:

```bash
git log -1 --format=%ad --date=short -- <path>          # file's last change
git log -L '<start>,<end>:<path>' --format=%ad          # a specific line's origin
```

⚠️ **`utils/` and `archive/` are gitignored**, so neither command returns anything for a
path inside them. `worklog.md` writes its own dates into its headings and those are usable;
anything else under `utils/` is recorded as `date: unknown` unless the note says when.

A statement whose date can't be established is recorded as `date: unknown` and sits in
the weakest tier of trust.

## The entry format

```markdown
### <topic slug> — <one line summary>
- **He said:** "<quote, or a faithful one-line paraphrase marked as such>"
- **When:** YYYY-MM-DD  (`unknown` if it could not be dated)
- **Where:** <plans/done/007 Decisions | commit a32a768 | docs/BEHAVIOUR.md R44>
- **Topics:** storage, outputs-panel, project-manager
- **Weight:** rule | decision | preference | passing-remark
- **Superseded by:** ~   (set when a later statement or a `changed` reconsider replaces it)
```

The file's header carries `lastScanned: YYYY-MM-DD` and `lastScannedSha: <sha>`, which is
where the next run starts from.

**`Weight` matters as much as the date**, and flattening the two into one number is the
main way this file could go wrong. A **rule** in `CLAUDE.md` or a numbered ruling in
`docs/BEHAVIOUR.md` is binding — contradicting it is a `kind: bug`
[issue](../issues/README.md), not a question for you. A **decision** in a plan's
`Decisions` table was made deliberately, with the trade-off in front of you. A
**preference** is how you'd like things done. A **passing-remark** in a commit message
is a hint and nothing more. A hint and a rule are not the same evidence, and the ledger
must not let them look the same.

**`docs/BEHAVIOUR.md` outranks everything here**, and so does `CLAUDE.md`. If a ledger
entry contradicts one, the ruling wins and the entry is what's wrong.

## Trust decays with age

An entry is not a standing order. Weight it by how old it is:

| Age of the statement | How to treat it |
|---|---|
| under 30 days | Strong. Assume it still holds. A contradiction is almost certainly the hunter being wrong — say so, and lead with the possibility that the finding is simply mistaken. |
| 30–90 days | Holds, but the code may have moved under it. Check whether what you were describing still exists in that shape. |
| over 90 days | Context, not instruction. Say what has changed since, and what would make you decide differently now. |
| undated | Weakest. A statement that couldn't be dated is a hint. Say that it's undated. |

Note what this scale is measuring: not whether you were right, but how likely it is that
the world the statement was made about is still the world we're in. **Camea has moved
fast** — the project-manager reframe landed 2026-07-24, and R44 reversed R42/R43 on
2026-08-10 — so a statement about "where the project saves" made in July is about an app
that no longer exists, not about this one.

## What happens when a finding contradicts an entry

The hunter does **not** file the finding as an issue. It writes a question into
`workflow/hunts/reconsider/` instead — see [hunts/](../hunts/README.md) — and `/resolve`
puts those in front of you before it gets to the issues. A contradiction is a question for
you, not a finding against you.

Two things follow from that. If you say **kept**, the statement's date is refreshed here
and the hunter must never raise it again. If you say **changed**, the entry gets a
`Superseded by:` line and the question becomes a UX issue or a plan.

## The rules

- **Never invent a statement.** Every entry cites a real path or sha. An entry nobody can
  check will be trusted anyway, because checking is work and trusting is free.
- **Never delete an entry.** A superseded one gets `Superseded by:` and stays. The record
  of a changed mind is worth as much as the decision — it's the thing that tells a future
  session the question was already live once. **R42 → R44 is the worked example**: the
  reversal is more informative than either ruling alone.
- **Newer beats older on the same topic, but show both.** The hunter shows you the
  history, not its conclusion. You're the one who knows whether the old reason still
  applies.
- **A `CLAUDE.md` or `docs/BEHAVIOUR.md` statement is a rule, not an opinion.** Don't file
  a reconsider question against one; if the repo violates it, that's a bug, and if the rule
  itself looks wrong, say so in the run log rather than quietly working around it.
- **Never treat an entry as unfalsifiable.** A statement can be wrong, or about an older
  version of the app, or made before something else changed underneath it. Contradicting
  one costs a *question* — it is never grounds for silence.
