---
name: beat-challenge
description: Run the Camea mosaic placement challenge — spawn teams of subagents until ALL 312 usable snapshot tiles of trials 11–348 (both serpentine passes) are placed within 10 px of the hand-verified ground truth (100%), or a time budget runs out. Use when the user says "beat challenge", "beat the challenge", "run the challenge", or asks to continue/resume the placement challenge — including with a time budget and team count like "beat challenge try for 6 hours with 3 teams in parallel".
---

# Beat the challenge

**260620d is TWO serpentine scans of the same tissue, not one.**

**Goal:** **ALL 312** usable tiles of **trials 11–348** placed within 10 px of the hand-verified
ground truth. **312/312.** You orchestrate **teams** of subagents until that is met or the time
budget expires.

| range | tiles | T27 today |
|---|---|---|
| **pass 1** — 11–166 | **156** | **156/156 = 100 %** — **SOLVED. The CONTROL, not the target.** |
| **pass 2** — 167–348 | **156** | 58/156 = 37.2 % |
| **MERGED** — 11–348 | **312** | 124/312 = 39.7 % ← **THE TARGET** |

A method that **breaks pass 1 has broken something** — the pass-1 subset of every merged build is
the control, and the overview reports it. Never launder a build that wins on the merged score while
destroying pass 1.

Denominators are **156 / 156 / 312** — never 182, never 338. 26 snapshots are thrown out and are
not data.

---

## ⚠️ Token discipline — this is the whole job

You may run for **hours**. Your context window is the scarce resource, and if it fills, the run
dies. Every round must cost *you* almost nothing.

**NEVER read into your own context:** team scripts, `positions.csv`, `build.json`, `RESULTS.md`,
`REGISTRY.md`, `_settled.md`, `CHALLENGE.md`, figures, or workflow transcripts. The subagents read
those.

**ONLY read:** the output of `challenge.py status` and `challenge.py overview`. That is your entire
view of the world. All state lives on disk. You are a loop, a clock and a status line.

---

## Setup (once)

**1. Parse the two knobs from what the user said.** Both are theirs to set:

| knob | example | default if not said |
|---|---|---|
| **hours** | `"try for 6 hours"` | **unbounded** — run until 312/312 or stalled. Do **not** ask. |
| **teams in parallel** | `"with 3 teams"` | **1** |

**No time limit given → run until the challenge is beaten** (or it stalls, or the user interrupts).
Pass no `--hours`. Say so once, plainly, in the opening lines — an unbounded run keeps spending
until it wins, and the user should know that is what they asked for.

More teams = proportionally more tokens *and* more CPU/GPU contention. The box has 24 cores and one
RTX 3080 Ti, and each team runs `nMethods` builds at once, so **keep `teams × nMethods ≤ 8`**:

| teams | nMethods to pass |
|---|---|
| 1 | 4 |
| 2 | 4 |
| 3 | 3 |
| 4+ | 2 |

If the user asks for many teams, run it — just tell them once, in one line, what it will cost.

**2. Start the clock and the run-state.** Pass `--hours` only if the user gave one; **omit it
entirely for an unbounded run**:
```bash
cd d:/Projects/Camea && date "+%s"
... challenge.py run start --teams <N> --next-id 30 [--hours <H>]
... challenge.py rescore
```
(Prefix every python call with `cd d:/Projects/Camea && MPLBACKEND=Agg "C:/Users/phill/miniconda3/condabin/conda.bat" run -n camea python -s`.)

Team ids start at **T30** — the archived challenge used T01–T27, and the registry spans all time.

If `rescore` already says `*** BEATEN ***`, tell the user and stop.

**3. Print the first overview** (the command below), then launch the rounds.

---

## The overview — a standing requirement

**Print a full overview every ~15 minutes while anything is in flight, and on every round
completion.** Rounds run 25–45 min, so a quiet stretch without a heartbeat is indistinguishable
from a hung run, and results are the user's only signal that anything is alive.

**Assume the user has read NOTHING** — not the previous overview, not the earlier round updates.
They may be glancing at their screen for the first time in an hour. It must stand entirely on its
own: what the goal is, where the run is, what is running, what the best is, what is left, and
**what the pass-1 control is doing**.

It **always carries a `CLOCK` and an `ETA` line** — time left if they set a budget, otherwise "no
time limit", and in both cases a projected ETA to 312/312 based on the rate tiles are actually
being fixed at. The generator handles this; never hand-write it.

**Do not compose it yourself.** Re-score first so it reflects anything that just landed, then print
the generator's output **verbatim**:
```bash
... challenge.py rescore
... challenge.py overview
```
That keeps it compact, consistent, and free for you.

---

## The loop

Keep **`teams` rounds in flight at all times** until beaten, out of time, or stalled.

1. **Check the clock.** A round takes ~25–45 min. If the user set a budget and less than ~45 min
   remains, launch nothing new — let the in-flight rounds finish, then go to *Finish*. If the run
   is **unbounded**, keep launching; only *beaten* or *stalled* stops it.

2. **Launch rounds to fill the parallel slots.** Each is one tool call. To launch several, put them
   in **one message** so they run concurrently:
   ```
   Workflow({
     scriptPath: "d:/Projects/Camea/analysis/builds/challenge/round.workflow.js",
     args: { round: <n>, nMethods: <see table>, idBase: <base> }
   })
   ```
   **`idBase` must differ for every concurrent round** — each round owns the block
   `T<idBase> .. T<idBase + nMethods - 1>`, so two teams can never write the same file. Claim a
   block and get its base with:
   ```bash
   ... challenge.py run update --claim-ids <nMethods>     # prints "NEXT_ID <base>"
   ```
   Teams also claim their *ideas* in `analysis/benchmark/_claims.md`, so two concurrent scouts
   cannot invent the same method.

   Each round scouts (reading `REGISTRY.md` and `_settled.md` so it never repeats a method),
   implements and scores its methods in parallel, **adversarially verifies** the best — because the
   two cheapest ways to "win" are to read the answer key and to hard-code the cross-pass tie, so no
   winner is trusted on its own say-so — and then a **historian** logs everything.

3. **When a round returns**, record it and re-score (this is all you read):
   ```bash
   ... challenge.py rescore
   ... challenge.py run update --done --running "<still-in-flight labels>" --methods "<ids tried>" --tokens <round tokens> --note "R<n> · <winner> <pct>% — <one line why>"
   ```

4. **Print the full overview**, **then report that round in ≤ 4 lines**, then immediately launch a
   replacement round to refill the slot:
   ```
   R3 done · T33_twopass_tie 79.5% (248/312) [+39.8] ✓ verified · pass-1 control 156/156 held · ~380k tok
     also: T34_cycle_gate 61.2% (triangles pruned 3k links, pass 2 still splits), T35_notch failed
     overall 79.5% — 64 tiles left, all in pass 2 · R4, R5 still running · launched R6
   ```
   **Always state what the winner did to the pass-1 control.** A build that gains on the merged
   score while dropping pass 1 below 156/156 has broken the one thing that already worked — say so
   plainly.

   If the verifier said the winner was **not** trustworthy, say so plainly and state the result was
   rejected. **Never launder an unverified score into the running best.**

   A round that **crashed or produced nothing** still gets its overview and its ≤ 4 lines — say so
   plainly ("R4 died, no method scored") rather than staying silent.

5. **Stall check.** If **5 consecutive rounds** produce no improvement, stop and tell the user it
   has plateaued and what has been ruled out. Burning their tokens on a plateau helps nobody.

---

## Finish

Stop on: **100 % (312/312)**, **deadline passed** (if one was set), or **stalled**. An unbounded run
stops only on *beaten* or *stalled*. Let in-flight rounds finish first, then print a **final
overview** (same command) plus:
- the winning approach, its pass-1 control, and whether the challenge was **beaten**
- the one-line idea that made it work
- rounds run, methods tried, total tokens
- `analysis/benchmark/RESULTS.md` — every approach and its accuracy, in one place

Then **stop**. Do not launch another round.

---

## Notes

- **Resuming is free.** All state is on disk (`state.json`, `run.json`, `RESULTS.md`,
  `REGISTRY.md`). If the session dies — or the user hits their usage limit — nothing is lost.
  `beat challenge` again picks up with every scored method remembered. **The user's network drops
  the session regularly**, so keep rounds short and results landing on disk early.
- **You cannot read the user's subscription usage.** No API or file exposes it. Do not pretend to.
  Report token spend (the overview does) and respect the deadline they set.
- **Accuracy against the ground truth is the only measure.** Do not tune toward the overlap-NCC
  `med` score. It is actively misleading: it ranked one build best-in-project while that build
  placed 1 of 48 tail tiles correctly, and it *rejected* what later became the best method in the
  project. Overlap-NCC is a way to **build**, never a way to **measure**.
