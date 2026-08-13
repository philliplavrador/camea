# issues/ — what sessions find on the way to something else

A session is halfway through a frontend change and notices the backend route it's
calling writes outside `<project>/outputs/`. That's real, it's worth fixing, and it is
**not** what the session was asked to do. Saying it in the chat doesn't work — the chat
ends.

So it writes it down here, with evidence, and gets back to the actual task.

```
issues/
├── high/       fix before that feature is used. Lost work, a wrong answer trusted, or the science broken.
├── medium/     wrong, but survivable. There's a workaround or nobody hits it yet.
├── low/        inconsistency, dead code, confusing copy. Nothing breaks.
└── resolved/   closed: fixed, handed to a plan, or decided against. Kept either way.
```

## Two kinds live here: `bug` and `ux`

Every issue carries a `kind:`. A file without one is read as `bug`.

**`kind: bug`** is the original thing — a gap between what the repo says it does and what
it actually does. The evidence bar below applies in full: a `file:line`, a command that
reproduces it, or a number and how you measured it.

**`kind: ux`** is "this works, but it may not be the best way to do it" — a step that
costs the user more than it should, wording that assumes they know what a serpentine pass
is, a decision they shouldn't have to make, a dead end with no obvious next action.

**The UX bar is deliberately low, and it is meant to stay low.** The author decided he
would rather do the filtering himself than have the bar do it for him, so these file
cheaply and he throws out the ones he disagrees with. Don't tighten this later because
the pile looks noisy — the noise is the design. A UX finding still has to name a real
screen or flow, say what a first-time user experiences there, and propose the better
alternative in one sentence; "this is awkward" with nothing to compare against is not a
finding. What it does *not* need is a measured number or a refute panel, because an
opinion can't be refuted.

Since they file cheaply, UX findings carry **`confidence: high | medium | low`** — how
sure the finder is that this is genuinely worse than the alternative it proposed.
`/resolve` reads the high-confidence ones first, which is the entire reason the field
exists: a low bar only works if the strong findings can be read before the weak ones.

A `kind: ux` issue defaults to `tier: low`. It goes `medium` only when a real user is
blocked or led into a wrong action, and it is never `high`.

## The tiers, concretely

**Camea has no users yet and no deployment**, so severity is not measured against
somebody's morning. It is measured against the two things this repo actually protects:
**the science**, and **the work a person has already done by hand.**

A mosaic is hand-verified. Somebody swept 338 frames, pressed `E` on the bad ones, and
corrected the placements the machine got wrong. That is hours of irreplaceable judgement
sitting in `%LOCALAPPDATA%/Camea/projects/<analysis_id>/`, and it is the thing a `high`
destroys.

| Tier | The test | Examples |
|---|---|---|
| **high** | Verified work is lost or silently changed · a wrong answer is presented as a verified one · the guarded engine's behaviour moves · anything writes into the read-only mirror. | An export that writes a stale placement over a corrected one. A recompute that overrides an anchor the user confirmed. A reformat of `src/camea/engine/t27.py`. A write anywhere under `data/`. Dataset knowledge hard-coded into the app (HARD RULE 3). |
| **medium** | Genuinely wrong, but there's a workaround, or it only bites an edge case. | A progress bar that lies about a job. A route that 500s on a dataset with one frame. A [BEHAVIOUR](../../docs/BEHAVIOUR.md) ruling the code states and doesn't enforce. |
| **low** | Nothing breaks. It's untidy, inconsistent, or confusing. | Dead code. Copy using words a biologist wouldn't. Two components solving the same problem differently. |

**When you're between two tiers, file the higher one.** `/resolve` re-tiers freely and
it costs nothing; a `high` that was really a `low` wastes a minute of triage, while a
`low` that was really a `high` is found by a wrong figure in a paper.

### The four that are always `high`

These are Camea's standing rulings and violating one is never a `medium`:

1. **Dataset knowledge in the app.** A hard-coded trial number, range or count; an
   exclusion list; a per-dataset special case; an import of `EXCLUDED`/`BLANK`/`BLURRY`
   into app code. See [CLAUDE.md](../../CLAUDE.md) — this is structural, not conventional.
2. **A write to `data/`.** It is a read-only 35 GB rclone mirror. Nothing writes there.
3. **A change to `src/camea/engine/{t27,t33,quality,render}.py`.** Byte-identical to the
   research original and under the 312/312 guard. Even a reformat.
4. **A write outside `<project>/outputs/`, or a path prompt** — a save-folder box, an
   "Open folder", an `fs/reveal`, a draft file. All four reverse BEHAVIOUR **R44**.

## Filing one

Any session may file an issue **without asking first** — that is the point of the
directory. Claim a number, which prints the path it created, write the body into that file
from [TEMPLATE.md](TEMPLATE.md), and **mention it in one line at the end of the turn** so
it isn't a surprise later.

```bash
node scripts/claim-number.js issue <tier> <slug>
```

Two rules make the difference between a useful pile and a pile:

- **Evidence, not suspicion — for `kind: bug`.** A `file:line`, a command that
  reproduces it, or a number and how you measured it. "The recompute looks wrong here" is
  not an issue; `[recompute.py:212](../../../src/camea/features/mosaic/recompute.py#L212)`
  *re-places an anchored tile because it filters on `placed`, not `anchored`* is. A
  `kind: ux` finding answers to the lower bar above instead — a screen, what a first-time
  user hits there, and a better alternative.
- **Don't file what you can fix in the same turn.** If it's a one-line fix inside code
  you're already editing, just fix it and say so. The queue is for things that would
  derail the task, not things that are merely adjacent to it.

**Don't file a feature.** "It would be nice if the sweep had a minimap" is a
[plan](../plans/README.md), not an issue. An issue is something that is *wrong* — a gap
between what the repo says it does and what it does.

`kind: ux` does not loosen that; it moves the line rather than erasing it. **"Add a minimap
to the sweep" is a plan. "Correcting a tile makes you re-find your place in the sweep" is a
`kind: ux` issue.** The test is whether you are describing something the app already does
badly, or something the app doesn't do at all — the first belongs here, the second gets an
interview.

**Check `resolved/` as well as the open tiers** before writing — someone may have filed
it already, or the author may have already decided not to fix it, and a refiled
won't-fix wastes the same conversation twice. This matters most for `/bug-hunter`, which
sweeps the same repo night after night and would otherwise refile every won't-fix it
ever found.

**A ruling in [docs/BEHAVIOUR.md](../../docs/BEHAVIOUR.md) is not a bug.** If the code
violates a ruling, that is a `kind: bug` issue and a good one. If the *ruling itself* looks
wrong, that is a question for him, asked with the tool — see
[workflow/README.md](../README.md). Do not file an issue against a ruling.

## Getting them fixed

`/resolve` reads every open issue, re-tiers what's mis-tiered, and asks you what you
want done with each. There are three ways out, and all three end in `resolved/`:

- **Fixed on the spot** — trivial only; the bar is in [resolve.md](../../.claude/commands/resolve.md).
- **Turned into a plan** in [plans/queued/](../plans/README.md) — a fix with a real
  decision in it deserves the same interview a feature gets.
- **Won't fix** — `status: wont-fix`, with the reason. A decision not to fix something is
  a decision, and it stops the next session refiling it.

`resolved/` therefore means **closed, not fixed**. The `resolved-by:` line says which of
the three it was.

**`/plan-all` closes issues too, and only the middle one of the three.** When a sweep plans
a list of changes, it reads this queue alongside the list and folds in what the plans are
already walking past. Those leave as `resolved-by: plan NNN`. It cannot fix inline and
cannot rule won't-fix, so the rest of the pile is still `/resolve`'s.

## Conventions

- **Numbering** is zero-padded and never reused, shared across all four directories:
  `014-recompute-overrides-anchor.md`. **Claim it with
  `node scripts/claim-number.js issue <tier> <slug>`, never by reading the directory
  and adding one** — `/bug-hunter`, `/build` and `/resolve` can all be filing at the same
  moment, and two sessions that each count the highest number get the same answer. The
  script creates the file atomically and retries on collision, so exactly one caller wins
  each number; it prints the path it claimed and leaves the file empty for you to fill in.
- **Numbers are independent of plan numbers.** Issue `007` and plan `007` are unrelated;
  refer to them as `issue 007` and `plan 007`.
- **Re-tiering is `git mv`.** Nothing is rewritten but the `tier:` line.
- **Nothing is deleted.** Won't-fix moves to `resolved/` with `status: wont-fix` and a
  line saying why. A decision not to fix something is worth as much as the fix.
- **Issues are committed.** They travel with the repo, so every machine and every
  session sees the same pile.
