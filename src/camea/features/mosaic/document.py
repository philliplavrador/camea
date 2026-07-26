"""document.py — ⭐ **THE MOSAIC DOCUMENT PAYLOAD.** The tiles, their four states, and every
derived field that must be recomputed when the human changes his mind.

It is the *payload* half of an analysis document. `core.document` owns the envelope (schema, app,
dataset, provenance, save/load/autosave/validate/migrate); this module owns everything that is about
a **mosaic**: tiles, positions, anchors, exclusions, gaps, the cursor, the blank scan's decision, the
run, the build and the pass split. Core reaches it through `MosaicHooks` — registered once, at the
bottom of this file — and never imports it.

Ported from the mosaic-shaped ~1,050 lines of `archive/app-v1/backend/project.py` (READ-ONLY).

---------------------------------------------------------------------------------------------------
THE FIVE THINGS THAT MUST SURVIVE ANY REWRITE OF THIS FILE
---------------------------------------------------------------------------------------------------

1. ⛔ **THIS FILE CARRIES NO DATASET KNOWLEDGE. NONE.** There is no exclusion list here, no trial
   number is special, and nothing is ever excluded on the user's behalf — not by the blank scan, not
   by a "recommended" list, not by a validator. **Every trial in a new document starts `unplaced`;
   NOTHING starts `excluded`.** A frame becomes `excluded` only when the human presses `E`, or when a
   project file he loaded says so. (v1 hard-coded his 26 rulings and auto-applied them: it answered,
   on his behalf, the exact question the app exists to help him answer. It was ripped out at real
   cost. There is no toggle.) The one symbol this feature may take from the exclusion module is
   `gaps()`, and it takes it through `core.dataset.gaps` — a pure function over a trial list.

2. ⭐ **THIS DOCUMENT *IS* A GROUND-TRUTH DOCUMENT.** The benchmark scorer (`tests/guard/score.py ::
   load_gt()`) reads it **unchanged**, at the TOP level:

       doc["tiles"][k]["status"] == "anchor"   and   x / y   (and `r`, defaulting to)
       doc["tolerance_px"]["region_default"]

   So the payload is written **FLAT, beside the envelope keys** — never under a `payload:` — and
   `status`/`state` are both written on every tile, by one writer. Get that mapping wrong and either
   nothing or everything lands in the exported ground truth.

3. ⚠️ **THE PROVENANCE STAMP AND ITS WARNING MUST SURVIVE EXACTLY.** They live in `core.document`
   (`stamp`, `PROVENANCE_WARNING`), and the *verdict* is derived from this payload's HISTORY by
   `machine_evidence()` below — a build block, or a single tile still carrying a `machine` position —
   **never** from what the document says about itself. This project has already destroyed one
   benchmark by laundering a machine build into a "hand-placed ground truth" while every tile kept
   the solver's position. See `discard_machine()`: it is destructive, or it is nothing.

4. ⚠️ **`gaps` IS DERIVED AND MUST BE RECOMPUTED ON EVERY CHANGE TO THE EXCLUDED SET.** Excluding a
   tile removes a frame from the solver's input and opens a hole in acquisition order — and **the
   serpentine one-axis step prior does NOT hold across a hole.** A build that assumes it away places
   the whole tail wrong, silently. `normalise()` recomputes `gaps`, and any build solved on a
   different trial list or different gaps is marked **STALE** (`mark_stale_if_input_changed`).

5. ⛔ **UNKNOWN KEYS ROUND-TRIP VERBATIM**, per tile and at the top level. A saved document is also
   somebody's ground truth and may carry a hand-written note. Nothing here rebuilds a tile from
   scratch: it deep-copies and edits, and it only ever touches the keys it names. (The **one**
   exception is `EXCLUDED_TRIALS` — see `migrate()`. A block of dataset knowledge is not a note.)
"""

from __future__ import annotations

import copy
import math
import re
from typing import Any

from camea.core import document as core

# ⭐ THE ONE FUNCTION THE APP MAY IMPORT FROM THE EXCLUSION MODULE — and it comes through core, which
# is the single place the app touches it. Never `EXCLUDED` / `BLANK` / `BLURRY` / `usable_trials`:
# those are one acquisition's ruling, and the app knows nothing about any acquisition.
from camea.core.dataset import gaps as _gaps
from camea.core.document import Problem

# =================================================================================================
# Constants
# =================================================================================================

#: The feature's name. It is written into every document's envelope and is what core routes on.
FEATURE = "mosaic"

#: 512 is `t33.TILE`. It is the MOSAIC's tile size, not the app's: core holds frames of whatever
#: shape the XML says, and the 512x512 gate is this feature's policy (`mosaic/run.py`).
TILE_PX = 512

# --- the four-state machine. There are no others. ------------------------------------------------
#
# | state      | status (on disk) | position          | in the anchor field? | drawn | exported  |
# |------------|------------------|-------------------|----------------------|-------|-----------|
# | unplaced   | "unplaced"       | null              | no                   | no    | no        |
# | unverified | "unverified"     | yes               | NO                   | NO ⭐ | iff asked |
# | anchored   | "anchor"    ⚠️   | yes               | YES                  | yes   | yes       |
# | excluded   | "excluded"       | null (-> last_xy) | no                   | no    | no        |
#
# ⚠️ `state` and `status` DIFFER for anchored/"anchor" — the ground truths say `"anchor"` where the
# app says `"anchored"`, and `score.load_gt()` keeps every tile whose **`status == "anchor"`**. Write
# BOTH on every tile so no reader ever has to reverse-map; on load, `state` wins if it is present.
STATES = ("anchored", "unverified", "unplaced", "excluded")
PLACED_STATES = ("anchored", "unverified")
STATE_TO_STATUS = {"anchored": "anchor", "unverified": "unverified",
                   "unplaced": "unplaced", "excluded": "excluded"}
STATUS_TO_STATE = {v: k for k, v in STATE_TO_STATUS.items()}

#: The per-tile scoring radius written into a tile. ⚠️ NOT decoration: `score.load_gt()` reads `r` as
#: that tile's own tolerance, falling back to `tolerance_px.region_default`. An existing `r` is never
#: overwritten — a hand-authored truth's radii are the human's, not ours.
R_PLACED = 96
R_UNPLACED = 256

#: < 0.5 px from the machine's answer == "accepted unchanged". See `human_edits`.
MOVED_EPS = 0.5

#: ⛔ `region_default` is **REQUIRED** — `score.load_gt()` reads it, at the top level, and the
#: exporter asserts it is there before the file leaves the process.
TOLERANCE_PX = {"anchor": 96, "region_default": 256, "grading": 10}

#: The blank scan's measure, recorded in the document so the number can be re-derived later.
#: ⚠️ It is a MEASUREMENT of the frame **as the reader produced it** — never "of the flipped frame",
#: which v1 asserted unconditionally while the reader flips conditionally on the XML.
BLANK_MEASURE = "std of DoG(sigma=3, sigma=30) of the frame as read"

#: A thin best-minus-second NCC margin is the signature of a surviving grid alias. Look at these
#: first. (The shipped 312/312 build's worst run margin is 0.081 against a ~0.47 typical.)
THIN_MARGIN = 0.10


def coordinates(frame_note: str = "") -> str:
    """⚠️ **THE COORDINATE NOTE IS BUILT FROM THIS ACQUISITION'S XML — NEVER ASSERTED.**

    `frame_note` is `core.frames.FrameStore.frame_note`: what the reader *actually did* to these
    pixels, read off the trial XML's `ax`/`ay`. The reader flips **conditionally**; v1's `COORDINATES`
    constant said "180deg-flipped" **unconditionally**. On an acquisition that declares no flip, every
    exported artefact would then carry a false claim about its own coordinate frame — on the one axis
    this project has been burned by, in the file most likely to be handed to somebody else.
    **Do not hard-code a flip here. Pass the note in.**
    """
    note = (frame_note or "").strip() or "the frame as the reader produced it (see `frame_note`)"
    return (f"RELATIVE. Tile TOP-LEFT in px, measured FROM `origin_trial` at (0,0), in {note}. "
            "Absolute position is meaningless; a scorer must slide a build onto this with a CONSENSUS "
            "translation before measuring.")


# =================================================================================================
# Errors
# =================================================================================================
class SeedRefused(core.DocumentError):
    """`seed_from_build` cannot tie the build's frame to the human's. -> HTTP 409 `refused`.

    Raised when the document holds tiles the human placed or anchored but **none of them is in the
    build** — the two coordinate frames have nothing in common, and the honest answer is to refuse
    rather than to guess a translation. (Guessing would slide the human's whole field.)
    """


# =================================================================================================
# Reading a document — the primitives every other mosaic module uses
# =================================================================================================
def tiles_of(doc: dict) -> dict[str, dict]:
    """The tiles map, `{"11": {...}}`. Trial ids are decimal STRINGS in JSON — never zero-padded."""
    t = doc.get("tiles")
    return t if isinstance(t, dict) else {}


def trials_of(doc: dict) -> list[int]:
    """Every trial in the document, sorted."""
    return sorted(int(k) for k in tiles_of(doc))


def state_of(tile: dict) -> str:
    """⭐ **THE ONE READER OF A TILE'S STATE.** `state` wins if present; otherwise derive it from
    `status` (a bench-written ground truth has no `state` field at all).

    ⚠️ v1 had a second copy of this in `export.py` and **the two disagreed**: export's returned
    `str(status)` for an unknown status, so a GT row with `status: "region"` became state `"region"`,
    which is in neither `{"anchored", "unverified"}` — and the tile was silently **not rendered**.
    This one maps a legacy row by its POSITION: placed => `unverified`, else `unplaced`. There is
    exactly one of these. Import it; never write a second.
    """
    st = tile.get("state")
    if st in STATES:
        return st
    status = tile.get("status")
    if status in STATUS_TO_STATE:
        return STATUS_TO_STATE[status]
    if tile.get("x") is not None and tile.get("y") is not None:
        return "unverified"
    return "unplaced"


def trials_in_state(doc: dict, *states: str) -> list[int]:
    """Sorted trials whose state is one of `states`."""
    return sorted(int(k) for k, v in tiles_of(doc).items()
                  if isinstance(v, dict) and state_of(v) in states)


def anchored_trials(doc: dict) -> list[int]:
    """The certified field — **the ONLY thing the matcher matches against**, and the only thing the
    sweep canvas draws."""
    return trials_in_state(doc, "anchored")


def placed_trials(doc: dict) -> list[int]:
    """Everything with a position: `anchored` + `unverified`."""
    return trials_in_state(doc, *PLACED_STATES)


def excluded_trials(doc: dict) -> list[int]:
    """⛔ **THE HUMAN'S EXCLUSIONS, AND NOTHING ELSE.** The app seeds none, so every one of these got
    here because he pressed `E` — in this session, or in the one this file was saved from."""
    return trials_in_state(doc, "excluded")


def active_trials(doc: dict) -> list[int]:
    """The trials that are still INPUT to the solver: everything not `excluded`.

    `unplaced` counts — it has no position yet, but it is still a frame the build will be given. Only
    `excluded` leaves the input, and that is exactly what opens a gap.
    """
    return sorted(int(k) for k, v in tiles_of(doc).items()
                  if isinstance(v, dict) and state_of(v) != "excluded")


def positions(doc: dict, *, include_unverified: bool = True) -> dict[int, tuple[float, float]]:
    """`{trial: (x, y)}` — **world TOP-LEFT corners, never centres.** Off-by-256 is the classic bug in
    this project. `excluded` and `unplaced` are absent: they have no position."""
    want = PLACED_STATES if include_unverified else ("anchored",)
    out: dict[int, tuple[float, float]] = {}
    for k, tile in tiles_of(doc).items():
        if state_of(tile) in want and tile.get("x") is not None and tile.get("y") is not None:
            out[int(k)] = (float(tile["x"]), float(tile["y"]))
    return out


def refusal_set(doc: dict) -> list[int]:
    """🔴 **THE REFUSAL SET — the blank list the human left standing.** It lives HERE, in the document,
    and it travels to the matcher **in the request body** (`MatchAnchorRequest.refuse`), where it is
    part of `cache_key`.

    It is *not* server state. In v1 it was — `PUT /api/scan/blank` mutated it and the matcher read it
    — which is precisely what made `POST /api/match/anchor` **not** a pure function of its body, and
    is why the server had to reset its caches on every tick of a checkbox. That endpoint is gone.

    ⚠️ **REFUSING IS NOT EXCLUDING.** A refused tile stays in the document and stays in the mosaic;
    the correlator simply may not place it, because two blank frames correlate **+0.43 at zero shift**
    on fixed-pattern *sensor* structure, which does not move with the stage. They register
    **confidently and wrongly**. The human may still place one by hand — he is allowed to do what the
    correlator must not — and it gets no NCC, because there is no honest one.
    """
    bs = doc.get("blank_scan")
    if not isinstance(bs, dict):
        return []
    return sorted({int(t) for t in (bs.get("blank") or [])})


def compute_gaps(doc: dict) -> list[list[int]]:
    """⚠️ **DERIVED. RECOMPUTED ON EVERY CHANGE TO THE EXCLUDED SET.**

    Consecutive pairs in the *active* trial list that are NOT one acquisition step apart. **The
    serpentine one-axis step prior does NOT hold across these.** A build that assumes them away
    silently places the whole tail wrong.

    Delegates to `core.dataset.gaps` -> `engine.excluded.gaps` — the one canonical rule, and a pure
    function of a trial list. Never a local reimplementation.
    """
    return [[int(a), int(b)] for a, b in _gaps(active_trials(doc))]


def pass_of(trial: int, pass_split: Any) -> int | None:
    """⭐ `pass_split` is the **LAST TRIAL OF PASS 1** (166 on 260620d), never the first of pass 2."""
    if pass_split is None:
        return None
    return 1 if int(trial) <= int(pass_split) else 2


def cursor_of(doc: dict) -> int | None:
    """The sweep position. 🔴 An **integer**, never null-on-Escape: `Esc` deselects the marquee; it
    does not abandon the tile you are judging. A `cursor: null` in the file resumed a session at the
    top of the run."""
    c = doc.get("cursor")
    return None if c is None else int(c)


def _dist(ax, ay, bx, by) -> float:
    return float(math.hypot(float(ax) - float(bx), float(ay) - float(by)))


def _median(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    return float(s[mid]) if n % 2 else float(0.5 * (s[mid - 1] + s[mid]))


def _placed_radius(tile: dict) -> float:
    """The `r` a PLACED tile carries.

    ⚠️ **`r` IS NOT DECORATION.** `score.load_gt()` reads it as *that tile's own tolerance*, falling
    back to `tolerance_px.region_default` (256). Every anchor in all three hand-authored ground truths
    carries exactly **96**.

    `R_UNPLACED` (256) is not a radius — it is the "no radius yet" marker every fresh tile is born
    with. A tile that has since been placed must not inherit it, or an exported anchor is scored at a
    **256 px** tolerance and a build 200 px wrong passes. So: keep a deliberately *tighter* radius
    (a hand-authored truth's own), and otherwise give a placed tile the placed default. The error
    direction is deliberate — a radius that is too tight fails an honest tile loudly; one that is too
    loose passes a wrong one silently.
    """
    r = tile.get("r")
    if isinstance(r, (int, float)) and not isinstance(r, bool) and 0 < float(r) < R_UNPLACED:
        return float(r)
    return float(R_PLACED)


def _xy(v: Any) -> tuple[float, float] | None:
    """A `[x, y]` pair, or None. Tolerant of tuples, of `None`, and of a half-written pair."""
    if isinstance(v, (list, tuple)) and len(v) == 2 and v[0] is not None and v[1] is not None:
        try:
            x, y = float(v[0]), float(v[1])
        except (TypeError, ValueError):
            return None
        if math.isfinite(x) and math.isfinite(y):
            return x, y
    return None


# =================================================================================================
# new_payload — ⭐ THE SERVER CREATES THE DOCUMENT
# =================================================================================================
def new_payload(doc: dict, *, trials: list[int] | tuple[int, ...] = (), lo: int | None = None,
                hi: int | None = None, pass_split: int | None = None, frame_note: str = "",
                run: dict | None = None, tone: dict | None = None, blank: dict | None = None,
                texture: dict | None = None, tile_px: int = TILE_PX, **_ignored: Any) -> dict:
    """The mosaic's keys, added **FLAT** to a fresh envelope. -> the whole document.

    ⛔ **EVERY TRIAL STARTS `unplaced`. NOTHING STARTS `excluded`.** The app has no built-in exclusion
    list and no per-dataset special case. A frame becomes `excluded` only when the human presses `E`,
    or when a project file he loaded says so.

    The blank scan may still **recommend** frames (`blank_scan.blank`, and the per-tile `blank` flag)
    — a recommendation, sitting on a tile that is otherwise ordinary `unplaced` data. It **excludes
    nothing, and it never will.** It only stops the *correlator* placing them, which is the default
    (`Hand place`) until the human presses `Keep` on the Screen step.

    🔴 In v1 this function was **DEAD** — the front end built the document in JS. That is how
    `human_edits`' divert counters were dropped on every save, and how "Skip — place by hand" could
    erase `seeded_from` while every tile still sat exactly where t33 put it. The document is authored
    on the server.

    Arguments come from the mosaic's own detection (`mosaic.run`) and the core session; this module
    reads no disk and holds no session.
    """
    run = dict(run or {})
    tone = dict(tone or {})
    blank = dict(blank or {})

    ts = sorted({int(t) for t in (trials or run.get("trials") or [])})
    lo = int(lo if lo is not None else (run.get("lo") if run.get("lo") is not None
                                        else (ts[0] if ts else 0)))
    hi = int(hi if hi is not None else (run.get("hi") if run.get("hi") is not None
                                        else (ts[-1] if ts else 0)))
    split = None if pass_split is None else int(pass_split)

    # The scan PROPOSES (`BlankProposal.proposed`; v1 spelled it `blank`). Accept either.
    proposed = sorted({int(t) for t in (blank.get("proposed") or blank.get("blank") or [])})
    tex = {int(k): float(v) for k, v in (texture or blank.get("texture") or {}).items()}

    doc = copy.deepcopy(doc)
    doc["tiles"] = {
        str(t): {
            "status": "unplaced", "state": "unplaced", "x": None, "y": None,
            "r": float(R_UNPLACED),
            "pass": pass_of(t, split),
            "machine": None, "moved_px": None,
            "ncc": None, "margin": None, "n_anchors": None,
            # a MEASUREMENT about the pixels, not a judgement. Never cleared.
            "blank": t in proposed,
            "texture": tex.get(t),
            "judged_at": None,
        }
        for t in ts
    }
    doc["trial_range"] = [lo, hi]
    doc["pass_split"] = split
    doc["origin_trial"] = ts[0] if ts else lo
    doc["tile_px"] = int(tile_px)
    doc["coordinates"] = coordinates(frame_note)
    doc["tolerance_px"] = dict(TOLERANCE_PX)
    doc["gaps"] = []                                     # filled by normalise()
    doc["unusable_tiles"] = []                           # filled by normalise()
    doc["cursor"] = ts[0] if ts else None                # the sweep starts at the first tile
    doc["blank_scan"] = {
        "threshold": blank.get("threshold"),
        "measure": blank.get("measure") or BLANK_MEASURE,
        # the DECISION, and it starts as the proposal because `Hand place` is the DEFAULT on a
        # scanned frame — the app saying "I do not trust myself on this one; you do it".
        "blank": list(proposed),
        # ⭐ THE MEASUREMENT, PRESERVED FOR EVER. `blank` moves when he presses Keep; `scanned` does
        # not — without it the Screen step would silently drop the frames he just overruled off the
        # page, because it has nothing left to list.
        "scanned": list(proposed),
        "accepted": False,                               # the scan RECOMMENDS; the user ticks.
        "overruled_by_user": [],
    }
    doc["run"] = {
        "detected": bool(run.get("detected", True)),
        "why": str(run.get("why") or ""),
        "pass_split_detected": bool(run.get("pass_split_detected", True)),
        "pass_split_why": str(run.get("pass_split_why") or ""),
        "n_trials": len(ts),
    }
    doc["tone"] = {k: v for k, v in tone.items()
                   if k in ("lo", "hi", "level", "flat_sigma", "pct_lo", "pct_hi", "auto")}
    doc["build"] = None
    return doc


# =================================================================================================
# rescope — ⭐ "which trials are the mosaic?", answered a SECOND time, without losing the work
# =================================================================================================
def rescope(doc: dict, trials: list[int] | tuple[int, ...], *, lo: int | None = None,
            hi: int | None = None, pass_split: int | None = None,
            texture: dict | None = None, run: dict | None = None) -> tuple[dict, dict]:
    """Re-scope an EXISTING document to `trials`. -> `(doc, info)`.

    The Range step's `Apply`. A project opens on every square snapshot the dataset holds — which on a
    real acquisition includes the stray snapshots taken **before the mosaic scan started** (three
    lone blocks on 260620d: `1`, `5-7`, then the run at `11-348`). They are not tiles of this mosaic
    and they must not be swept, solved or exported as if they were. The user says which range IS the
    mosaic; this rewrites the tile set to exactly that.

    ⛔ **THE APP STILL CARRIES NO DATASET KNOWLEDGE.** `trials` is the caller's list — measured by
    the route from `log.txt` + the per-trial XML shape, or typed by the user. No number is named here
    and none is defaulted. Nothing is *excluded*: an out-of-range trial is not "thrown out", it was
    never part of this mosaic. (`unusable_tiles` stays the human's own `E` presses, and `human_edits`
    keeps counting only those.)

    🔴 **IT KEEPS THE WORK ON EVERY SURVIVING TILE.** A tile still in range comes through byte-for-byte
    — its position, its state, its anchor, its `machine`, its `judged_at`. Rebuilding the tile dict
    from scratch (the obvious implementation) would silently wipe a half-swept run the moment the user
    nudged `hi`. Only tiles that LEAVE the range are dropped, and `info` reports how much placed work
    went with them so the caller can confirm first.

    ⚠️ A changed trial list is a **different problem** for the solver: `normalise()` recomputes `gaps`
    and `mark_stale_if_input_changed()` flags the build. That is the whole reason this is one function
    on the server rather than three edits in the browser.
    """
    ts = sorted({int(t) for t in trials})
    if not ts:
        raise core.DocumentError(
            "a mosaic needs at least one trial: the range you asked for is empty"
        )

    doc = copy.deepcopy(doc)
    old = tiles_of(doc)
    keep = {str(t) for t in ts}

    removed = sorted(int(k) for k in old if k not in keep)
    added = [t for t in ts if str(t) not in old]
    n_placed_removed = sum(1 for t in removed if state_of(old[str(t)]) in PLACED_STATES)

    scan = doc.get("blank_scan") if isinstance(doc.get("blank_scan"), dict) else {}
    scanned = {int(t) for t in (scan.get("scanned") or [])}
    tex = {int(k): float(v) for k, v in (texture or {}).items()}
    split = None if pass_split is None else int(pass_split)

    tiles: dict[str, dict] = {}
    for t in ts:
        k = str(t)
        if k in old:
            tiles[k] = old[k]                            # ⭐ the human's work, untouched
        else:
            tiles[k] = {
                "status": "unplaced", "state": "unplaced", "x": None, "y": None,
                "r": float(R_UNPLACED), "pass": pass_of(t, split),
                "machine": None, "moved_px": None,
                "ncc": None, "margin": None, "n_anchors": None,
                "blank": t in scanned,                   # a measurement, if the scan ever saw it
                "texture": tex.get(t),
                "judged_at": None,
            }
    doc["tiles"] = tiles

    doc["trial_range"] = [int(lo) if lo is not None else ts[0],
                          int(hi) if hi is not None else ts[-1]]
    doc["pass_split"] = split
    if doc.get("origin_trial") not in ts:
        doc["origin_trial"] = ts[0]
    if doc.get("cursor") not in ts:
        doc["cursor"] = ts[0]

    # The blank scan's lists are about frames; a frame that is no longer in the mosaic is no longer
    # its business. (`scanned` is the measurement's own record and is pruned the same way — a card for
    # a trial that is not in the document would render against a tile that does not exist.)
    if scan:
        for key in ("blank", "scanned", "overruled_by_user"):
            if isinstance(scan.get(key), list):
                scan[key] = [int(t) for t in scan[key] if int(t) in set(ts)]

    r = dict(run or {})
    block = doc.get("run") if isinstance(doc.get("run"), dict) else {}
    doc["run"] = {**block,
                  "detected": bool(r.get("detected", False)),
                  "why": str(r.get("why") or block.get("why") or ""),
                  "pass_split_detected": bool(r.get("pass_split_detected",
                                                    block.get("pass_split_detected", False))),
                  "pass_split_why": str(r.get("pass_split_why")
                                        or block.get("pass_split_why") or ""),
                  "n_trials": len(ts)}

    doc = normalise(doc)                                 # gaps, pass, unusable_tiles, build staleness
    return doc, {"n_trials": len(ts), "added": added, "removed": removed,
                 "n_added": len(added), "n_removed": len(removed),
                 "n_placed_removed": n_placed_removed}


# =================================================================================================
# seed_from_build — 🔴 A RE-SOLVE MUST NOT DESTROY THE HUMAN'S WORK
# =================================================================================================
def seed_from_build(doc: dict, build: dict) -> tuple[dict, dict]:
    """Apply a build's positions to the document. -> `(doc, {"n_seeded", "n_protected",
    "seed_translation"})`.

    Every tile the solver placed that the human has **not** ruled on becomes `unverified` at the
    build's position, with `machine` = that position. Tiles the solver could not place stay
    `unplaced` — they go on the rescue list, and the sweep places them with the same anchor-composite
    call as everything else.

    🔴 **IT KEEPS EVERY `anchored` OR `human` TILE, AND SEEDS AROUND THEM.** v1 called `setState`
    unconditionally on every non-excluded tile, so a 150-tile sweep with three catastrophic hand
    corrections in it was **wiped** by taking the app's own advice to re-solve — and the autosave then
    wrote the wiped document over the crash-recovery file.

    ⭐ **THE TRANSLATION IS A MEDIAN, NOT A MEAN.** The build lands in its own frame, so it is slid
    onto the human's by the median offset over the protected tiles. A tile the human corrected
    *because the solver was wrong* is precisely an outlier — one 2,969 px correction would drag a mean
    into nonsense. If the human has placed tiles and **none** of them is in the build, the two frames
    cannot be tied together and this **refuses** (`SeedRefused` -> 409) rather than guess.

    ⚠️ It flips the provenance: `stamp()` will find the build block and force
    `independent_of_method: false` + the warning, verbatim. There is no way to seed a document and
    have it still claim to be an independent truth.
    """
    doc = copy.deepcopy(doc)
    build = core.jsonable(build or {})
    raw: dict[int, tuple[float, float]] = {}
    for k, v in (build.get("positions") or {}).items():
        xy = _xy(v)
        if xy is not None:
            raw[int(k)] = xy

    tiles = tiles_of(doc)

    # PROTECTED: the human's own answers. `anchored` = he certified it; `human` = a hand put the
    # position there (`advance()` must never re-match over one — when he drags a tile it is usually
    # *because the matcher was wrong*).
    protected = sorted(
        int(k) for k, tile in tiles.items()
        if isinstance(tile, dict)
        and state_of(tile) in PLACED_STATES
        and (state_of(tile) == "anchored" or tile.get("human"))
        and _xy([tile.get("x"), tile.get("y")]) is not None)

    shared = [t for t in protected if t in raw]
    if protected and not shared:
        raise SeedRefused(
            f"this document holds {len(protected)} tile(s) the human placed or anchored, and the "
            f"build placed none of them ({len(raw)} positions). The build's frame and the human's "
            "cannot be tied together, and sliding his whole field onto a guessed translation would "
            "destroy his work. Re-solve with those trials in the input, or discard the build.")

    if shared:
        dx = _median([tiles[str(t)]["x"] - raw[t][0] for t in shared])
        dy = _median([tiles[str(t)]["y"] - raw[t][1] for t in shared])
    else:
        dx = dy = 0.0                                    # a fresh document: the build IS the frame

    n_seeded = 0
    for k, tile in tiles.items():
        t = int(k)
        if t not in raw:
            continue
        mx, my = raw[t][0] + dx, raw[t][1] + dy          # the machine's answer, in the human's frame
        if t in protected or state_of(tile) == "excluded":
            # the human already ruled on this tile. Record what the machine said; change nothing else.
            # ⭐ Recording it is not cosmetic: `machine` is what makes `moved_px` — and the whole QC
            # report — meaningful, and its mere presence is machine evidence for `stamp()`.
            tile["machine"] = [mx, my]
            continue
        tile["state"] = "unverified"
        tile["status"] = "unverified"
        tile["x"] = float(mx)
        tile["y"] = float(my)
        tile["r"] = _placed_radius(tile)
        tile["machine"] = [mx, my]
        tile.setdefault("source", "t33 build (unverified)")
        n_seeded += 1

    doc["build"] = {
        "build_id": build.get("build_id"),
        "method": build.get("method", "t33"),
        "created": build.get("created") or core.iso_now(),
        "seconds": build.get("seconds"),
        "gpu": build.get("gpu"),
        "n_placed": build.get("n_placed", len(raw)),
        "config": (build.get("info") or {}).get("config") or build.get("config") or {},
        "info": build.get("info") or {},
        # ⭐ THE MACHINE'S UNTOUCHED ANSWER, in the build's own frame. `normalise()` slides the TILES;
        # it never slides this. The difference between the two is the record of what the human did.
        "positions": {str(t): [p[0], p[1]] for t, p in sorted(raw.items())},
        # ⭐ WHAT THE SOLVER WAS ACTUALLY GIVEN. Without these two the staleness check degenerates
        # into comparing the current trial list with itself, and never fires. See
        # `mark_stale_if_input_changed`.
        "trials": active_trials(doc),
        "gaps": compute_gaps(doc),
        "stale": False,
        "stale_reason": None,
    }
    return normalise(doc), {"n_seeded": n_seeded, "n_protected": len(protected),
                            "seed_translation": (float(dx), float(dy))}


def place_against_anchors(doc: dict, placed: dict) -> tuple[dict, dict]:
    """⭐ **RECOMPUTE's write** — land the machine placements that `POST /api/mosaic/recompute`
    measured against the FROZEN anchor field. -> `(doc, {"n_placed"})`.

    `placed = {trial: (x, y)}` are the positions `solve.match_anchor` returned for the non-anchored
    targets. ⭐ **They need NO translation.** Unlike a cold build (which lands in its own frame and
    `seed_from_build` slides onto the human's by a median offset), the recompute composite is built
    from the **anchors' own document positions**, so `match_anchor`'s world coords are already in the
    document's frame. Sliding them would be a bug.

    Each placed tile becomes `unverified` at that position, carrying `machine` — which is what makes it
    re-placeable, keeps `moved_px` / the QC report meaningful, and (via `stamp()`) forces
    `independent_of_method: false`.

    🔴 **It NEVER touches an `anchored`, `human`, or `excluded` tile** — those are the frozen reference
    and the human's own work. The route already filters them out of the targets; this is that same
    guard restated where the write happens. (A re-solve that wipes the human's work is exactly the bug
    `seed_from_build` exists to prevent — this shares its rule. Nothing is ever auto-anchored: I3.)
    """
    doc = copy.deepcopy(doc)
    tiles = tiles_of(doc)
    n_placed = 0
    for t, xy in (placed or {}).items():
        tile = tiles.get(str(int(t))) or tiles.get(int(t))
        if not isinstance(tile, dict):
            continue
        # Defensive: never overwrite the frozen reference or a hand placement.
        if state_of(tile) == "excluded" or state_of(tile) == "anchored" or tile.get("human"):
            continue
        x, y = float(xy[0]), float(xy[1])
        tile["state"] = "unverified"
        tile["status"] = "unverified"
        tile["x"] = x
        tile["y"] = y
        tile["r"] = _placed_radius(tile)
        tile["machine"] = [x, y]
        # A fresh machine placement: it carries no divert history and is not stale.
        tile["diverted"] = False
        tile.pop("divert_reason", None)
        tile.pop("rejected_match", None)
        tile["stale"] = False
        tile["source"] = "recompute (re-placed against the anchor composite)"
        n_placed += 1
    return normalise(doc), {"n_placed": n_placed}


# =================================================================================================
# discard_machine — 🔴 IT IS DESTRUCTIVE, OR IT IS NOTHING
# =================================================================================================
def discard_machine(doc: dict) -> tuple[dict, dict]:
    """*"Skip — place by hand"*. -> `(doc, {"n_positions_discarded", "had_build"})`.

    🔴 If anything in this document came from a machine, this discards **every position and the
    build** — and `machine`, `ncc`, `margin`, `seq`, `human`, `source`, `diverted` and the rest of the
    machine's fingerprints with them. Every placed tile goes back to `unplaced`.

    **Anything less launders a machine build into an "independent ground truth".** v1's front end
    nulled `build`, nulled `seeded_from`, set `independent_of_method: true` and deleted the warning —
    **without touching a single tile.** Every tile kept t33's position and t33's answer. Score t33
    against that document and it gets ~100 % **by construction**. That is the exact mechanism that
    already destroyed `analysis/archive/challenge_2026-07/benchmark/ground_truth/260620d.json`, which
    is T27's own output.

    ⚠️ Exclusions are the HUMAN's and are kept. `blank` and `texture` are MEASUREMENTS about the
    pixels, not the machine's opinion, and are kept. `note` is his and is kept.
    """
    doc = copy.deepcopy(doc)
    had_build = isinstance(doc.get("build"), dict) and bool(doc.get("build"))
    n = 0
    for tile in tiles_of(doc).values():
        if not isinstance(tile, dict):
            continue
        st = state_of(tile)
        if st in PLACED_STATES:
            n += 1
            tile["state"] = "unplaced"
            tile["status"] = "unplaced"
        tile["x"] = None
        tile["y"] = None
        tile["machine"] = None
        tile["moved_px"] = None
        for key in ("ncc", "margin", "npix", "n_anchors", "seq", "human", "source", "stale",
                    "diverted", "divert_reason", "rejected_match", "alt_rank", "last_xy",
                    "judged_at"):
            tile.pop(key, None)
    doc["build"] = None
    prov = doc.get("provenance")
    if isinstance(prov, dict):
        prov["seeded_from"] = None                       # `stamp()` re-derives it from the HISTORY
    return normalise(doc), {"n_positions_discarded": n, "had_build": had_build}


# =================================================================================================
# staleness — ⚠️ EXCLUDING A TILE CHANGES THE INPUT TO THE SOLVER
# =================================================================================================
def mark_stale_if_input_changed(doc: dict) -> dict:
    """If the active trial list or the gaps have changed since the build ran, the build was solved on
    a **DIFFERENT PROBLEM**. Mark it stale. (In place; returns `doc`.)

    Excluding a tile removes a frame from the solver's input and opens a gap in acquisition order, and
    **the serpentine one-step prior does not hold across a gap.** The app must OFFER A RE-SOLVE. It
    must never keep using the old positions as if nothing happened.

    (The gap check alone is not enough: excluding the FIRST or LAST trial of the run opens no gap but
    still changes the input. So the trial list is compared too.)

    🔴 **UNKNOWN IS NOT THE SAME AS UNCHANGED.** v1 fell back to `b.get("trials") or now_trials` — so
    when the build block did not record what it was solved on, it compared the current trial list
    **with itself**, found them equal, and never fired. And the build block was written by the front
    end, which never wrote `trials` or `gaps`, so the whole apparatus was inert: the user could press
    `E` on trial 200 mid-sweep, open a gap at 199->201, and the app would keep — and autosave, and
    export — the positions of 200's neighbours, which had been solved THROUGH it, while asserting
    `stale: false`. **A build with no recorded input is STALE.**
    """
    b = doc.get("build")
    if not isinstance(b, dict) or not b:
        return doc

    now_trials = active_trials(doc)
    now_gaps = compute_gaps(doc)

    if b.get("trials") is None:
        b["stale"] = True
        b["stale_reason"] = ("this build does not record which trials it was solved on, so it cannot "
                             "be checked against the current input. Re-solve.")
        return doc

    was_trials = [int(t) for t in b.get("trials")]
    was_gaps = [[int(a), int(c)] for a, c in (b.get("gaps") or [])]

    reasons = []
    if now_trials != was_trials:
        dropped = sorted(set(was_trials) - set(now_trials))
        added = sorted(set(now_trials) - set(was_trials))
        bits = []
        if dropped:
            bits.append(f"{len(dropped)} trial(s) excluded since the build: "
                        + " ".join(map(str, dropped[:12])) + (" ..." if len(dropped) > 12 else ""))
        if added:
            bits.append(f"{len(added)} trial(s) un-excluded since the build: "
                        + " ".join(map(str, added[:12])) + (" ..." if len(added) > 12 else ""))
        reasons.append("; ".join(bits) or "the trial list changed since the build")
    if now_gaps != was_gaps:
        reasons.append(f"the gaps changed since the build ({was_gaps} -> {now_gaps})")

    if reasons:
        b["stale"] = True
        b["stale_reason"] = " | ".join(reasons) + " — solved on a different input. Re-solve."
    else:
        b.setdefault("stale", False)
        b.setdefault("stale_reason", None)
    return doc


def is_build_stale(doc: dict) -> tuple[bool, str | None]:
    """-> (stale?, why). The UI shows `why` next to a "re-solve" button."""
    b = doc.get("build")
    if not isinstance(b, dict) or not b:
        return False, None
    return bool(b.get("stale")), b.get("stale_reason")


# =================================================================================================
# normalise — the derived fields, repaired
# =================================================================================================
def normalise(doc: dict) -> dict:
    """Pin `origin_trial` at exactly `[0.0, 0.0]` and recompute every derived field: both spellings of
    the state, `r`, `moved_px`, `unusable_tiles`, **`gaps`**, `pass`, and the build's staleness.

    A layout is defined only up to a **global translation**, so pinning the origin loses nothing — and
    it makes an exported ground truth directly comparable with `analysis/ground_truth/`, which has
    trial 11 at (0, 0).

    ⚠️ **THE SAME TRANSLATION IS APPLIED TO `machine` AND `last_xy`**, so `moved_px = |final -
    machine|` stays meaningful. That number is the entire basis of the QC report. `build.positions`
    keeps the machine's untouched answer, in the build's own frame.

    ⛔ It touches **no envelope key** — provenance is core's, and `human_edits` is recomputed by
    `stamp()` through the hook below.
    """
    doc = copy.deepcopy(doc)
    tiles = doc.setdefault("tiles", {})

    # 1. every tile carries BOTH spellings and a sane `r`.
    for tile in tiles.values():
        if not isinstance(tile, dict):
            continue
        st = state_of(tile)
        tile["state"] = st
        tile["status"] = STATE_TO_STATUS[st]
        if st in PLACED_STATES:
            tile["r"] = _placed_radius(tile)
        else:
            tile["x"] = None
            tile["y"] = None
            tile["r"] = float(tile.get("r") or R_UNPLACED)
        if st == "excluded":
            tile["excluded"] = True
        else:
            # ⚠️ A tile that LEAVES `excluded` must stop claiming it was thrown out, or it goes into
            # the exported ground truth reading `status: "anchor", excluded: true`. The judgement dies
            # with the judgement. (`blank` does NOT: it is a measurement about the pixels.)
            if "excluded" in tile:
                tile["excluded"] = False
            tile.pop("excluded_reason", None)
            tile.pop("unusable_reason", None)

    # 2. origin: min(anchored), else min(placed). Everything shifts so it sits at exactly [0, 0].
    anchored = anchored_trials(doc)
    placed = placed_trials(doc)
    origin = anchored[0] if anchored else (placed[0] if placed else None)
    if origin is not None:
        ox = float(tiles[str(origin)].get("x") or 0.0)
        oy = float(tiles[str(origin)].get("y") or 0.0)
        doc["origin_trial"] = origin
        if ox or oy:
            for tile in tiles.values():
                if not isinstance(tile, dict):
                    continue
                if tile.get("x") is not None:
                    tile["x"] = float(tile["x"]) - ox
                    tile["y"] = float(tile["y"]) - oy
                for key in ("machine", "last_xy"):
                    p = _xy(tile.get(key))
                    if p is not None:
                        tile[key] = [p[0] - ox, p[1] - oy]
        tiles[str(origin)]["x"] = 0.0                    # kill -0.0
        tiles[str(origin)]["y"] = 0.0

    # 3. moved_px = |final - machine|  (both now in the same frame)
    for tile in tiles.values():
        if not isinstance(tile, dict):
            continue
        m = _xy(tile.get("machine"))
        if state_of(tile) in PLACED_STATES and m is not None:
            tile["moved_px"] = round(_dist(tile["x"], tile["y"], m[0], m[1]), 4)
        else:
            tile["moved_px"] = None

    # 4. the derived lists. ⚠️ `gaps` is NOT cosmetic — see compute_gaps().
    doc["unusable_tiles"] = excluded_trials(doc)
    doc["gaps"] = compute_gaps(doc)
    doc.setdefault("pass_split", None)
    doc.setdefault("tile_px", TILE_PX)
    doc.setdefault("build", None)
    # 🔴 the cursor is an INTEGER or null — never a string, and never `null` because `Esc` was
    # pressed. A `cursor: null` in the file resumed the session at the top of the run.
    c = doc.get("cursor")
    try:
        doc["cursor"] = None if c is None or isinstance(c, bool) else int(c)
    except (TypeError, ValueError):
        doc["cursor"] = None
    tol = doc.get("tolerance_px")
    doc["tolerance_px"] = tol = dict(tol) if isinstance(tol, dict) else {}
    for k, v in TOLERANCE_PX.items():
        tol.setdefault(k, v)                             # region_default is REQUIRED by score.load_gt
    if doc.get("pass_split") is not None:
        for k, tile in tiles.items():
            if isinstance(tile, dict):
                tile["pass"] = pass_of(int(k), doc["pass_split"])

    mark_stale_if_input_changed(doc)
    return doc


# =================================================================================================
# human_edits — the honest record of what the human actually did
# =================================================================================================
def human_edits(doc: dict) -> dict:
    """-> `provenance.human_edits`. Recomputed by `stamp()` on every save.

    ⭐ **EVERY EXCLUSION IS A HUMAN EDIT.** The app seeds none, so an `excluded` tile got there because
    he pressed `E` (in this session, or in the one this file was saved from). There is no longer any
    such thing as an exclusion the app made on his behalf.

    ⚠️ **THE DIVERTED TILES ARE COUNTED HERE, AND NAMED NEXT TO THE NUMBER THEY CONTAMINATE.** A
    diverted tile is sitting *exactly* on the machine's position — so it lands inside
    `accepted_unchanged` and reads as "the human looked and agreed". He did not: the app never gave
    the correlator a vote there. In the defer flow this can be **302 of 311 tiles**.

    🔴 v1's front end computed these in JS and wrote them into the document — and the backend then
    rebuilt `human_edits` from scratch on every save and **silently dropped them**. So the one place
    the numbers were supposed to survive — the file — was the one place they did not.
    """
    tiles = tiles_of(doc)
    seeded = core.machine_evidence(doc, HOOKS) is not None   # the HISTORY, not the self-declaration
    accepted = moved = rescued = unverified = user_excluded = 0
    moves: list[float] = []
    for tile in tiles.values():
        if not isinstance(tile, dict):
            continue
        st = state_of(tile)
        if st == "unverified":
            unverified += 1
        if st == "excluded":
            user_excluded += 1
        if st not in PLACED_STATES:
            continue
        mv = tile.get("moved_px")
        if mv is None:
            if seeded:
                rescued += 1                             # the solver never placed it; the human did
            continue
        if float(mv) < MOVED_EPS:
            accepted += 1
        else:
            moved += 1
            moves.append(float(mv))

    diverted = sorted(int(k) for k, tile in tiles.items()
                      if isinstance(tile, dict) and tile.get("diverted")
                      and state_of(tile) != "excluded")
    return {
        "accepted_unchanged": accepted,                  # moved < 0.5 px
        "moved": moved,
        "excluded": user_excluded,                       # by the HUMAN. There is no other kind.
        "unverified": unverified,                        # placed but never judged — Space, no decision
        "rescued": rescued,                              # the solver could not place it; the human did
        "median_move_px": round(_median(moves), 3),      # over the MOVED tiles only
        "max_move_px": round(max(moves), 3) if moves else 0.0,
        "diverted_to_solver": len(diverted),
        "diverted_trials": diverted,
        "diverted_note": (
            f"These {len(diverted)} tiles sit at the SOLVER's position: the anchor-composite match "
            f"was not confident and was overruled by the batch solve — not by the human. They are "
            f"also inside `accepted_unchanged`; do not read that number as human agreement for them. "
            f"(Each tile's `rejected_match` records what the matcher wanted.)"
        ) if diverted else None,
    }


# =================================================================================================
# machine_evidence — ⭐ THE VERDICT IS DERIVED FROM THE DOCUMENT'S HISTORY
# =================================================================================================
def machine_evidence(doc: dict) -> dict | None:
    """⭐ **WAS THIS DOCUMENT EVER TOUCHED BY A MACHINE BUILD?** -> a `seeded_from` block, or None.

    Two kinds of evidence, and **neither of them is what the document says about itself**:

      1. a `build` block is still in the document;
      2. a single tile still carries a `machine` position.

    🔴 **THE HOLE THIS CLOSES.** v1 derived the entire provenance verdict from `provenance.seeded_from`
    — a field the FRONT END writes and can therefore erase. And it did: "Skip — place from scratch"
    nulled `build`, nulled `seeded_from`, set `independent_of_method: true` and DELETED the warning
    **without touching a single tile.** Every tile kept t33's position. Score t33 against that and it
    gets ~100 % **by construction**. This is the exact mechanism that already destroyed
    `analysis/archive/challenge_2026-07/benchmark/ground_truth/260620d.json`, which **is** T27's own
    output.

    (Core asks `provenance.seeded_from` first — a *claim*: necessary, never sufficient — and then asks
    this. This function must never consult it back, or the loop closes and the claim wins again.)
    """
    build = doc.get("build")
    if isinstance(build, dict) and build:
        return {"method": build.get("method", "t33"),
                "build_id": build.get("build_id"),
                "config": build.get("config") or {},
                "detected_from": "doc['build'] — the build block is still in the document"}

    tiles = tiles_of(doc)
    m = sorted(int(k) for k, v in tiles.items()
               if isinstance(v, dict) and v.get("machine") not in (None, [], {}))
    if m:
        return {"method": "unknown (a machine build)",
                "build_id": None,
                "config": {},
                "detected_from": (f"{len(m)} tile(s) still carry a `machine` position "
                                  f"({' '.join(str(t) for t in m[:8])}"
                                  f"{' ...' if len(m) > 8 else ''}) — every one of them started as a "
                                  "solver's answer, whatever the provenance block claims")}
    return None


def machine_evidence_report(doc: dict) -> dict:
    """`api.schemas.MachineEvidenceResponse` — what powers the provenance panel and the confirm text
    of *"Skip — place by hand"*.

    ⚠️ **DERIVED FROM THE DOCUMENT'S HISTORY, NEVER FROM WHAT IT SAYS ABOUT ITSELF.** It asks
    `machine_evidence()` (a build block, or a tile still carrying a `machine` position) and it does
    **not** consult `provenance.seeded_from`, which is writable and *has been erased*: v1's "Skip —
    place from scratch" nulled it, set `independent_of_method: true` and deleted the warning —
    **without touching a single tile.**

    ⭐ It lives here, and not in the router, because it is a **document rule**. The router validates,
    delegates and shapes the reply; it does not derive provenance. (`routes.post_machine_evidence`
    called a function of this name before one existed, and 500'd on every load of the panel.)

    🔴 `warning` is `PROVENANCE_WARNING` **verbatim, never paraphrased**, and it is present **iff**
    `independent_of_method` is false.
    """
    seeded = machine_evidence(doc)                        # ⭐ the HISTORY. Not the self-declaration.
    build = doc.get("build")
    n_machine = sum(1 for t in tiles_of(doc).values()
                    if isinstance(t, dict) and t.get("machine") not in (None, [], {}))
    return {
        "seeded_from": seeded,
        "has_build": isinstance(build, dict) and bool(build),
        "n_machine_tiles": n_machine,
        "independent_of_method": seeded is None,
        "warning": None if seeded is None else core.PROVENANCE_WARNING,
    }


def qc_report(doc: dict, app_version: str | None = None) -> dict:
    """`api.schemas.QcReport` — what the human did vs what the machine said.

    ⭐ **EVERY NUMBER STATES ITS DENOMINATOR**, and the denominator is the document's own `excluded`
    set and nothing else — the app has no list of its own.

    The computation belongs to the exporter (it is the same report `qc.json` / `qc.md` carry, and it
    must not exist twice), so this is a **one-line delegation** that gives the router a single, honest
    seam: the router asks the *document* module for a document report, and never has to know that the
    numbers are assembled next to the pixels.

    ⚠️ The import is **inside the function**: `export.py` imports this module at its top, so a
    module-level import here would be a cycle — and `export` pulls in tifffile and matplotlib, which
    `document` must never drag into a caller that only wants to read a tile's state.
    """
    from camea.features.mosaic.export import qc_report as _export_qc

    return _export_qc(doc, app_version)[0]               # (json, markdown) -> the JSON half


# =================================================================================================
# validate — the payload half.  ⛔ NO TRIAL NUMBER IS SPECIAL.
# =================================================================================================
def validate(doc: dict) -> list[Problem]:
    """-> `[(kind, message)]`, `kind` in `{"hard", "derived", "warn"}`.

    * **hard** — `normalise()` CANNOT fix it: a broken state machine, a placed tile with no position,
      a tile outside the trial range. Refuse the document.
    * **derived** — a field `normalise()`/`stamp()` recomputes. Repair it; never reject the save for
      it. The derived fields are *exactly* the ones that drift the moment the user excludes a tile.
    * **warn** — worth saying. Never blocks a write.

    ⛔ **NOTHING HERE MAY REJECT A DOCUMENT FOR *WHICH* TRIALS IT PLACED.** There is no built-in
    exclusion list to check a tile against — the only exclusions are the human's, and a human exclusion
    is never invalid. The guard that used to live here ("tile 284 is THROWN OUT and carries a
    position") made the user's own test session **unsaveable the moment he anchored 284**. It is gone.
    Do not bring it back: a dataset ruling belongs in the project file, not in the app.
    """
    p: list[Problem] = []

    for key in ("trial_range", "tiles"):
        if key not in doc:
            p.append(("hard", f"missing required key {key!r}"))
    for key in ("tile_px", "coordinates", "origin_trial", "unusable_tiles", "gaps", "tolerance_px"):
        if key not in doc:
            p.append(("derived", f"missing required key {key!r} (recomputed on save)"))

    if doc.get("tile_px") not in (None, TILE_PX):
        p.append(("hard", f"tile_px is {doc.get('tile_px')!r}; the mosaic is built on {TILE_PX} px "
                          f"tiles (t33.TILE) and only {TILE_PX} is supported"))

    tr = doc.get("trial_range")
    if isinstance(tr, (list, tuple)) and len(tr) == 2 and all(
            isinstance(v, int) and not isinstance(v, bool) for v in tr) and tr[0] <= tr[1]:
        tr = [int(tr[0]), int(tr[1])]
    else:
        p.append(("hard", f"trial_range must be [lo, hi] integers with lo <= hi; got {tr!r}"))
        tr = None

    tol = doc.get("tolerance_px")
    if tol is not None and not isinstance(tol, dict):
        p.append(("hard", f"tolerance_px must be an object; got {type(tol).__name__}"))
    elif isinstance(tol, dict) and not isinstance(tol.get("region_default"), (int, float)):
        p.append(("derived", "tolerance_px.region_default is missing — `score.load_gt()` reads it as "
                             "the fallback per-tile tolerance `r`, and a project the scorer cannot "
                             "read is a project that cannot be checked"))

    tiles = doc.get("tiles")
    if not isinstance(tiles, dict):
        if "tiles" in doc:
            p.append(("hard", "tiles must be an object keyed by trial number"))
        return p                                         # nothing below can be asked

    for k, tile in tiles.items():
        if not re.fullmatch(r"[0-9]+", str(k)) or (len(str(k)) > 1 and str(k).startswith("0")):
            p.append(("hard",
                      f"tile key {k!r} is not an unpadded decimal trial number ('11', not '011')"))
            continue
        t = int(k)
        if not isinstance(tile, dict):
            p.append(("hard", f"tile {t}: not an object"))
            continue

        st, status = tile.get("state"), tile.get("status")
        if st is None and status in STATUS_TO_STATE:
            p.append(("derived", f"tile {t}: no `state` (a bench-written ground truth has none); "
                                 f"deriving it from status {status!r} on save"))
            st = STATUS_TO_STATE[status]
        elif st is None:
            p.append(("derived", f"tile {t}: no `state` and status {status!r} is not one of "
                                 f"{tuple(STATUS_TO_STATE)}; deriving the state from its position"))
            st = state_of(tile)
        elif st not in STATES:
            p.append(("hard", f"tile {t}: state {st!r} is not one of {STATES}"))
            continue
        elif status is not None and status != STATE_TO_STATUS[st]:
            # ⚠️ HARD, and deliberately so. `normalise()` *could* pick one — and that is exactly the
            # danger: `status == "anchor"` is what puts a tile into the exported ground truth. A
            # document that says two different things about a tile is a document nobody may guess at.
            p.append(("hard", f"tile {t}: status {status!r} disagrees with state {st!r} "
                              f"(expected {STATE_TO_STATUS[st]!r}). Refusing to guess which is true: "
                              "`status == \"anchor\"` is what lands a tile in a ground truth."))

        x, y = tile.get("x"), tile.get("y")
        if st in PLACED_STATES:
            if not (isinstance(x, (int, float)) and not isinstance(x, bool)
                    and isinstance(y, (int, float)) and not isinstance(y, bool)
                    and math.isfinite(float(x)) and math.isfinite(float(y))):
                p.append(("hard", f"tile {t}: state {st!r} must have finite numeric x and y; "
                                  f"got {x!r},{y!r}"))
        elif x is not None or y is not None:
            p.append(("hard", f"tile {t}: state {st!r} must have x = y = null; got {x!r},{y!r} "
                              f"(an `E` moves the position to `last_xy`, it does not keep it)"))

        # ⛔ NO TRIAL NUMBER IS SPECIAL. See this function's docstring. The only check on a trial
        # number is that it is inside the range the document itself declares.
        if tr and not (tr[0] <= t <= tr[1]):
            p.append(("hard", f"tile {t} is outside trial_range {tr}"))

    # origin_trial: anchored (or, before any anchor exists, the first placed tile) at exactly [0, 0]
    anchored = anchored_trials(doc)
    placed = placed_trials(doc)
    want_origin = anchored[0] if anchored else (placed[0] if placed else None)
    if want_origin is not None:
        o = doc.get("origin_trial")
        if o != want_origin:
            p.append(("derived", f"origin_trial is {o!r}; it must be "
                                 f"min({'anchored' if anchored else 'placed'}) = {want_origin}"))
        ot = tiles.get(str(o)) or {}
        if ot.get("x") not in (0, 0.0) or ot.get("y") not in (0, 0.0):
            p.append(("derived", f"origin_trial {o} must sit at exactly [0.0, 0.0] after "
                                 f"normalisation; it is at [{ot.get('x')!r}, {ot.get('y')!r}]"))

    want_unusable = excluded_trials(doc)
    if [int(v) for v in (doc.get("unusable_tiles") or [])] != want_unusable:
        p.append(("derived", f"unusable_tiles is {doc.get('unusable_tiles')!r}; the excluded tiles "
                             f"are {want_unusable!r}"))

    # ⚠️ THE GAP INVARIANT. NOT COSMETIC — this is an ERROR, and `normalise()` is the only thing
    # allowed to satisfy it. A document that reaches a SOLVER with stale gaps applies the one-step
    # prior across a multi-step jump and silently places the whole tail wrong.
    want_gaps = compute_gaps(doc)
    got_gaps = [[int(a), int(b)] for a, b in (doc.get("gaps") or [])]
    if got_gaps != want_gaps:
        p.append(("derived", f"gaps is {got_gaps!r}; the excluded tiles imply {want_gaps!r}"))

    c = doc.get("cursor")
    if c is not None and not isinstance(c, bool) and isinstance(c, int) and str(c) not in tiles:
        p.append(("warn", f"cursor is trial {c}, which is not in the document"))
    elif c is not None and not (isinstance(c, int) and not isinstance(c, bool)):
        p.append(("derived", f"cursor must be an integer trial number or null; got {c!r}. "
                             "(`Esc` deselects; it does not abandon the tile under judgement.)"))

    bs = doc.get("blank_scan")
    if isinstance(bs, dict):
        stray = sorted(int(t) for t in (bs.get("blank") or []) if str(int(t)) not in tiles)
        if stray:
            p.append(("warn", f"blank_scan.blank names {stray[:12]}, which are not in the document"))

    stale, why = is_build_stale(doc)
    if stale:
        p.append(("warn", f"the batch build is STALE: {why}"))
    return p


# =================================================================================================
# migrate
# =================================================================================================
def migrate(doc: dict) -> tuple[dict, list[str]]:
    """Bring an older / bench-written payload up to date **WITHOUT LOSING A KEY**.

    Everything it does not name, it does not touch. That is why a v1 project file and a hand-authored
    ground truth (which predates the app and has no `state` field at all) both open unchanged.

    ⛔ **THE ONE KEY IT DELETES: `EXCLUDED_TRIALS`.** v1 wrote a hard-coded block of *dataset
    knowledge* — 26 named trials of one acquisition — into every file. Loading an old file and
    re-saving it must not silently resurrect it. It is not a hand-written note; it is the exact thing
    the standing ruling forbids. The **only** exclusion record that survives is `unusable_tiles`,
    rebuilt by `normalise()` from what the HUMAN actually excluded. (BEHAVIOUR R2.4.)
    """
    doc = copy.deepcopy(doc)
    w: list[str] = []

    if "EXCLUDED_TRIALS" in doc:
        doc.pop("EXCLUDED_TRIALS")
        w.append("dropped the `EXCLUDED_TRIALS` block: the app carries no dataset knowledge, and "
                 "neither does anything it writes. The exclusions that survive are the ones the "
                 "tiles themselves record.")

    for tile in tiles_of(doc).values():
        if not isinstance(tile, dict):
            continue
        old = tile.get("status")
        if old is not None and old not in STATUS_TO_STATE and "legacy_status" not in tile:
            tile["legacy_status"] = old                  # e.g. a GT's "region" / "pending" rows
        st = state_of(tile)                              # `state` wins; else derived from `status`
        tile["state"] = st
        tile["status"] = STATE_TO_STATUS[st]

    doc.setdefault("tile_px", TILE_PX)
    doc.setdefault("coordinates", coordinates(""))
    tol = doc.get("tolerance_px")
    doc["tolerance_px"] = tol = dict(tol) if isinstance(tol, dict) else {}
    for k, v in TOLERANCE_PX.items():
        tol.setdefault(k, v)
    doc.setdefault("unusable_tiles", [])
    doc.setdefault("gaps", [])
    doc.setdefault("pass_split", None)
    doc.setdefault("build", None)

    # ⭐ THE SESSION-RESUME KEYS. The project file is the app's only memory, so every part of a
    # session must survive a round-trip: where he was (`cursor`), how the frames were displayed
    # (`tone`), and which frames the matcher is to refuse (`blank_scan`). A document that predates
    # them opens with them empty rather than with them missing.
    doc.setdefault("cursor", None)
    doc.setdefault("tone", {})
    bs = doc.get("blank_scan")
    doc["blank_scan"] = bs = dict(bs) if isinstance(bs, dict) else {}
    bs.setdefault("measure", BLANK_MEASURE)
    bs.setdefault("threshold", None)
    bs.setdefault("blank", [])
    bs.setdefault("scanned", list(bs.get("blank") or []))
    bs.setdefault("accepted", False)
    bs.setdefault("overruled_by_user", [])

    run = doc.get("run")
    doc["run"] = run = dict(run) if isinstance(run, dict) else {}
    run.setdefault("detected", True)
    run.setdefault("why", "")
    run.setdefault("pass_split_detected", True)
    run.setdefault("pass_split_why", "")
    run.setdefault("n_trials", len(tiles_of(doc)))

    # The hand-authored ground truths carry no `trial_range` — they predate this schema. Derive it
    # from the tiles they DO carry, so the range guard has something to compare, rather than refusing
    # to open a real ground truth.
    ts = trials_of(doc)
    tr = doc.get("trial_range")
    if not (isinstance(tr, (list, tuple)) and len(tr) == 2):
        if ts:
            doc["trial_range"] = [ts[0], ts[-1]]
            w.append(f"no trial_range — derived [{ts[0]}, {ts[-1]}] from the tiles present.")
        else:
            doc["trial_range"] = [0, 0]
    else:
        doc["trial_range"] = [int(tr[0]), int(tr[1])]

    if "origin_trial" not in doc:
        placed = placed_trials(doc)
        doc["origin_trial"] = placed[0] if placed else (ts[0] if ts else 0)
    return doc, w


# =================================================================================================
# identity / counts — what core needs to guard a slot and draw a browser card
# =================================================================================================
def identity(doc: dict) -> str:
    """This document's slot within its dataset: its trial range, `"11-348"`.

    🔴 **THIS IS THE RANGE GUARD.** Two mosaics of one dataset are legal, and pass 2's autosave once
    **silently overwrote pass 1's ground-truth records** because the slot keyed on the DIRECTORY and
    not on the range. Core compares this string for equality and refuses a mismatch (409). It never
    parses it.
    """
    tr = doc.get("trial_range")
    if isinstance(tr, (list, tuple)) and len(tr) == 2 and tr[0] is not None and tr[1] is not None:
        return f"{int(tr[0])}-{int(tr[1])}"
    ts = trials_of(doc)
    return f"{ts[0]}-{ts[-1]}" if ts else ""


def counts(doc: dict) -> dict:
    """The numbers on the dataset browser's card. Core forwards these; it never learns what a tile is."""
    return {"n_tiles": len(tiles_of(doc)),
            "n_anchored": len(anchored_trials(doc)),
            "n_excluded": len(excluded_trials(doc))}


# =================================================================================================
# The hooks — the ONE place this feature is plugged into core
# =================================================================================================
class MosaicHooks:
    """What core needs to know about a mosaic payload. Every method is a thin delegation to the module
    function above it, so that everything is callable directly (the routes and the exporter want the
    plain functions) and core sees one object.

    ⛔ Core never imports this module. The arrow is one-way — `api -> features -> core -> engine` —
    and `register_feature` at the bottom of this file is how the feature reaches core without core
    reaching back.
    """

    name = FEATURE

    def machine_evidence(self, doc: dict) -> dict | None:
        return machine_evidence(doc)

    def normalise(self, doc: dict) -> dict:
        return normalise(doc)

    def validate(self, doc: dict) -> list[Problem]:
        return validate(doc)

    def migrate(self, doc: dict) -> tuple[dict, list[str]]:
        return migrate(doc)

    def human_edits(self, doc: dict) -> dict:
        return human_edits(doc)

    def identity(self, doc: dict) -> str:
        return identity(doc)

    def counts(self, doc: dict) -> dict:
        return counts(doc)

    def new_payload(self, doc: dict, **kwargs: Any) -> dict:
        return new_payload(doc, **kwargs)


#: One instance, registered once. Importing this module registers the feature — so
#: `core.document.load()` can open a mosaic document without anything else being imported first.
HOOKS = MosaicHooks()
core.register_feature(FEATURE, HOOKS)


# =================================================================================================
# The convenience wrappers over core.  (They exist so no caller has to remember to pass HOOKS.)
# =================================================================================================
def new_document(**kwargs: Any) -> dict:
    """A fresh mosaic document: core's envelope + this feature's payload, FLAT. See `new_payload`."""
    return core.new_document(feature=FEATURE, hooks=HOOKS, **kwargs)


def stamp(doc: dict) -> dict:
    """Core's provenance stamp, with this feature's evidence. ⚠️ Never skipped on the way out: any
    machine evidence ⇒ `independent_of_method: false` + `PROVENANCE_WARNING`, verbatim."""
    return core.stamp(doc, HOOKS)


def prepare(doc: dict) -> dict:
    """**structural-validate -> normalise -> stamp -> full-validate.** The document, ready to write."""
    return core.prepare(doc, HOOKS)


__all__ = [
    "FEATURE", "TILE_PX", "STATES", "PLACED_STATES", "STATE_TO_STATUS", "STATUS_TO_STATE",
    "R_PLACED", "R_UNPLACED", "MOVED_EPS", "TOLERANCE_PX", "BLANK_MEASURE", "THIN_MARGIN",
    "SeedRefused", "coordinates",
    "tiles_of", "trials_of", "state_of", "trials_in_state", "anchored_trials", "placed_trials",
    "excluded_trials", "active_trials", "positions", "refusal_set", "compute_gaps", "pass_of",
    "cursor_of",
    "new_payload", "seed_from_build", "discard_machine",
    "mark_stale_if_input_changed", "is_build_stale", "normalise", "human_edits", "machine_evidence",
    "machine_evidence_report", "qc_report",
    "validate", "migrate", "identity", "counts",
    "MosaicHooks", "HOOKS", "new_document", "stamp", "prepare",
]
