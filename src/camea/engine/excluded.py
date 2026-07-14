"""`gaps()`. That is the whole module, and the emptiness is the point.

⛔ **THE APP CARRIES NO KNOWLEDGE OF ANY DATASET.** (The user's standing ruling.) The research
tree's `excluded.py` — the one under `archive/analysis/ground_truth/` — also holds `EXCLUDED`,
`BLANK`, `BLURRY`, `PASS1/PASS2/MERGED`, `is_snapshot()` and `usable_trials()`. Those are the
**260620d ruling**: 26 specific trial numbers the human threw out of one specific acquisition, plus
a `DATA_DIR` hard-coded to a path on his machine. An earlier version of this app imported them and
auto-applied them, and *"it answered, on the user's behalf, the exact question the app exists to
help him answer"* — he opened his data and 26 frames were already gone before he had seen one of
them. It was ripped out at real cost.

**They are not absent here by convention. They are absent here structurally.** The app cannot
import `EXCLUDED` from `camea.engine.excluded`, because `camea.engine.excluded` does not have one.
Do not add one. There is no toggle for this.

Exclusions come from exactly two places, neither of which is code: **the human, in this session**,
and **a project file he loaded**.

`gaps()` is the one thing that may cross the line, because it is a **pure function of the trial
list it is handed** and holds no dataset knowledge whatsoever. It is also load-bearing (see below),
and there must be exactly one implementation of it in the repo — this one.
"""
from __future__ import annotations


def gaps(trials: list[int]) -> list[tuple[int, int]]:
    """Consecutive pairs in `trials` that are NOT one acquisition step apart, because some trial
    between them is missing (excluded by the human, dropped by the shape gate, or never acquired).

    ⚠️ **THE SERPENTINE ONE-AXIS STEP PRIOR DOES NOT HOLD ACROSS THESE.** Trial number is still
    acquisition ORDER, but it is no longer CONTIGUOUS: a "consecutive" pair either side of a gap is
    really a multi-step stage jump. A method that assumes `t` and `t+1` are one step apart will
    silently place the whole tail wrong. Detect the gaps; do not assume them away.

    Any change to the trial selection MUST recompute this.
    """
    return [(a, b) for a, b in zip(trials, trials[1:]) if b != a + 1]
