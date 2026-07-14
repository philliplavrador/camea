"""The project file — read, write, validate, migrate.

OWNER: agent 7. Nobody else edits this file.
CONTRACT: app/API.md §11 + **app/project_schema.json** (the schema is normative; read it).

⭐ **THE PROJECT FILE IS A GROUND-TRUTH DOCUMENT WITH EXTRA KEYS.** One file, two uses: the app
round-trips it, and `analysis/benchmark/score.py` scores it **unchanged**. `score.load_gt()` reads

    doc["tiles"][k]["status"] == "anchor"   and   x / y
    doc["tolerance_px"]["region_default"]   (the fallback per-tile `r`)

and nothing else. Those keys are REQUIRED. Everything the app adds is additive and score.py ignores
it. **Keep it that way: a project the scorer cannot read is a project that cannot be checked.**

THE TILE STATE MACHINE lives in API.md §2 and in the schema. Four states — `anchored`, `unverified`,
`unplaced`, `excluded` — and two spellings of each, because the ground truths say `"anchor"` where
the app says `"anchored"`. **Write BOTH `status` and `state` on every tile**, so no reader ever has
to reverse-map. On load: `state` wins if present; otherwise derive it from `status`.

⭐ `Space` without a decision leaves a tile **`unverified`: placed, drawn dimmer, NOT part of the
anchor field, and it does not block progress.** That is the whole point of the state — deferring a
hard tile must never stall the sweep.

--------------------------------------------------------------------------------------------------
IMPLEMENTATION NOTES (agent 7), the three that a reader will otherwise trip on:

0. ⭐ **THE APP KNOWS NOTHING ABOUT ANY DATASET. THE PROJECT FILE IS ITS ONLY MEMORY.** The user,
   2026-07-14: *"the app itself shouldn't store the exclusions for this experiment"*. Every trial in
   a new document starts `unplaced`; **nothing** starts `excluded`. The ONLY things that can ever
   exclude a frame are (a) the human, in this session, or (b) a project file he loaded. There is no
   built-in list, no ruling, no per-dataset special case — and therefore no guard that can refuse to
   save his own work. (`analysis/ground_truth/excluded.py` still governs the *analysis* tree; the
   app just stops consulting it, except for the one pure function `gaps()`.)

1. **ORDER OF OPERATIONS ON SAVE is `structural-validate -> normalise -> stamp -> full-validate ->
   write`, not `validate -> normalise`.** The derived fields (`gaps`, `unusable_tiles`,
   `origin_trial`, `moved_px`, `human_edits`) are *exactly the ones that drift* when the user
   excludes a tile or anchors an earlier one — and `normalise()` is what repairs them. Validating
   them BEFORE normalising would reject a perfectly good document for drift the very next line of
   code fixes. So we validate first only for the things `normalise` cannot fix (state/status
   disagreement, a placed tile with no position), then normalise, then run the FULL validation as a
   **post-condition** and refuse to write if it still fails.

2. **`normalise()` shifts `machine` (and `last_xy`) by the same translation as `x`/`y`.** A layout
   is defined only up to a global translation, so this loses nothing — and it keeps
   `moved_px = |final - machine|` meaningful, which is the whole basis of the QC report. The
   untouched machine answer is preserved separately in `build.positions`.

3. ⚠️ **EXCLUDING A TILE CHANGES THE INPUT TO THE SOLVER.** It opens a gap in acquisition order,
   where the serpentine one-step prior does **not** hold. `normalise()` recomputes `gaps` from
   `analysis/ground_truth/excluded.py :: gaps()` — a PURE function of a trial list, carrying no
   dataset knowledge; never a local reimplementation — and, if the active trial list or the gaps
   differ from the ones the build was solved on, it marks the build **STALE** (`build.stale`,
   `build.stale_reason`). The app must offer a re-solve. It must never keep using a stale build as
   if nothing happened.
"""
from __future__ import annotations

import copy
import json
import math
import os
import re
import sys
import tempfile
import threading
import time as _time
from datetime import datetime, timezone
from pathlib import Path

# --- the gap rule. NEVER reimplemented locally. -----------------------------------------------
# ⚠️ `_excluded.gaps(trials)` ONLY. It is a pure function of an arbitrary trial list (which
# consecutive pairs are not one acquisition step apart) and holds NO dataset knowledge. The app must
# never touch `_excluded.EXCLUDED` / `BLANK` / `BLURRY` — those are the *analysis* tree's ruling
# about one acquisition, and the app knows nothing about any acquisition.
_HERE = Path(__file__).resolve().parent               # app/backend
_ROOT = _HERE.parent.parent                           # the Camea repo root
_GT_DIR = _ROOT / "analysis" / "ground_truth"
if str(_GT_DIR) not in sys.path:
    sys.path.insert(0, str(_GT_DIR))
import excluded as _excluded                          # noqa: E402  gaps() ONLY

SCHEMA_VERSION = "camea-project-1.0"
APP_NAME = "Camea Mosaic Builder"
APP_VERSION = "1.0.0"
TILE_PX = 512

STATES = ("anchored", "unverified", "unplaced", "excluded")
PLACED_STATES = ("anchored", "unverified")
# the app's `state` <-> the ground truth's `status`. The ONLY spelling difference is anchored/anchor.
STATE_TO_STATUS = {"anchored": "anchor", "unverified": "unverified",
                   "unplaced": "unplaced", "excluded": "excluded"}
STATUS_TO_STATE = {v: k for k, v in STATE_TO_STATUS.items()}

R_PLACED = 96
R_UNPLACED = 256
MOVED_EPS = 0.5           # < 0.5 px == "accepted unchanged"

COORDINATES = ("RELATIVE. Tile TOP-LEFT in px, measured FROM `origin_trial` at (0,0), in the "
               "vscope-displayed (180deg-flipped) frame. Absolute position is meaningless; a scorer "
               "must slide a build onto this with a CONSENSUS translation before measuring.")

TOLERANCE_PX = {"anchor": 96, "region_default": 256, "grading": 10}

PROVENANCE_WARNING = (
    "NOT AN INDEPENDENT GROUND TRUTH. Every position here started as a machine build's output and "
    "was confirmed or corrected by a human who could see it. It MUST NEVER be used to score that "
    "method or any method derived from it — the score would be 100 % by construction. This project "
    "has already destroyed one benchmark exactly this way.")


# =============================================================================
# errors
# =============================================================================
class ProjectError(Exception):
    """Base class."""


class ValidationError(ProjectError):
    """The document is not a valid project. `.problems` is the list validate() returned."""

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems[:6]) +
                         (f" (+{len(self.problems) - 6} more)" if len(self.problems) > 6 else ""))


class RangeMismatch(ProjectError):
    """The project is for a different dataset / trial range than the open session. -> HTTP 409.

    ⚠️ This guard exists because **pass 2's autosave once silently overwrote pass 1's ground-truth
    records.** The bench has it (template.html:2012). Do not re-open that hole.
    """


# =============================================================================
# small helpers
# =============================================================================
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _jsonable(obj):
    """Make an arbitrary object JSON-safe.

    ⚠️ **t33's `info["config"]` is NOT JSON-serializable** — it holds a nested `t27.Config` object
    and `json.dumps(info)` **crashes**. `build_mosaic.ipynb` handles it with
    `default=lambda o: vars(o)`; we do the same, and also coerce numpy scalars/arrays, which are all
    over `info`. Kept local (a few lines) so this module does not import `engine` — and therefore
    neither numpy, CuPy, nor spectralign — just to write a JSON file.
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        if isinstance(obj, float) and not math.isfinite(obj):
            return None                                  # NaN/inf are not JSON
        return obj
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in obj]
    if hasattr(obj, "tolist"):                           # np.ndarray, np.float64, np.int64
        return _jsonable(obj.tolist())
    if hasattr(obj, "item") and not hasattr(obj, "__dict__"):
        try:
            return _jsonable(obj.item())
        except Exception:
            pass
    if hasattr(obj, "__dict__"):                         # t27.Config / t33.Config / dataclasses
        return _jsonable(vars(obj))
    return str(obj)


def _get(obj, key, default=None):
    """Read `key` from a dict OR an object with attributes (the session may be either)."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _trials(doc: dict) -> list[int]:
    """Every trial in the document, sorted."""
    return sorted(int(k) for k in doc.get("tiles", {}))


def _state_of(tile: dict) -> str:
    """`state` wins if present; otherwise derive it from `status` (a bench-written doc has no
    `state` field at all)."""
    st = tile.get("state")
    if st in STATES:
        return st
    status = tile.get("status")
    if status in STATUS_TO_STATE:
        return STATUS_TO_STATE[status]
    # legacy rows ("pending", "region", ...): placed => unverified, else unplaced.
    if tile.get("x") is not None and tile.get("y") is not None:
        return "unverified"
    return "unplaced"


def active_trials(doc: dict) -> list[int]:
    """The trials that are still INPUT to the solver: everything not `excluded`.

    `unplaced` counts — it has no position yet, but it is still a frame the build will be given.
    Only `excluded` leaves the input, and that is exactly what opens a gap.
    """
    tiles = doc.get("tiles", {})
    return sorted(int(k) for k, v in tiles.items() if _state_of(v) != "excluded")


def compute_gaps(doc: dict) -> list[list[int]]:
    """⚠️ DERIVED, and it MUST be recomputed on every change to the excluded set.

    Consecutive pairs in the *active* trial list that are NOT one acquisition step apart.
    **The serpentine one-axis step prior does NOT hold across these.** A build that assumes them
    away silently places the whole tail wrong.

    Delegates to `analysis/ground_truth/excluded.py :: gaps()` — the one canonical rule.
    """
    return [[a, b] for a, b in _excluded.gaps(active_trials(doc))]


def _pass_of(trial: int, pass_split) -> int | None:
    if pass_split is None:
        return None
    return 1 if trial <= int(pass_split) else 2


def _dist(ax, ay, bx, by) -> float:
    return float(math.hypot(float(ax) - float(bx), float(ay) - float(by)))


def _median(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    return float(s[mid]) if n % 2 else float(0.5 * (s[mid - 1] + s[mid]))


# =============================================================================
# new_doc
# =============================================================================
def new_doc(session) -> dict:
    """A fresh project document for an open session (a `GET /api/session` body — dict or object).

    ⭐ **EVERY TRIAL IN THE RUN STARTS `unplaced`. NOTHING STARTS `excluded`.** The app has no
    built-in exclusion list and no per-dataset special case (the user, 2026-07-14: *"the app itself
    shouldn't store the exclusions for this experiment"*). A frame becomes `excluded` only when the
    human presses `E`, or when a project file he loaded says so.

    The blank scan may still *recommend* tiles (`blank_scan.blank`, and `tile.blank`) — a
    recommendation, on a tile that is otherwise ordinary `unplaced` data. It excludes nothing.

    provenance starts `seeded_from: null` / `independent_of_method: true` — nothing has seeded it.
    """
    run = _get(session, "run", {}) or {}
    split = _get(session, "pass_split", {}) or {}
    tone = _get(session, "tone", {}) or {}
    blank = _get(session, "blank", {}) or {}

    lo = int(_get(run, "lo", 0) or 0)
    hi = int(_get(run, "hi", 0) or 0)
    trials = [int(t) for t in (_get(run, "trials", []) or [])]
    pass_split = _get(split, "value", None)
    pass_split = None if pass_split is None else int(pass_split)

    sess_tiles = _get(session, "tiles", {}) or {}
    blank_list = set(int(t) for t in (_get(blank, "blank", []) or []))
    texture = {int(k): v for k, v in (_get(blank, "texture", {}) or {}).items()}

    tiles: dict[str, dict] = {}
    for t in trials:
        info = _get(sess_tiles, str(t), {}) or _get(sess_tiles, t, {}) or {}
        tiles[str(t)] = {
            "status": "unplaced", "state": "unplaced", "x": None, "y": None,
            "r": R_UNPLACED,
            "pass": _pass_of(t, pass_split),
            "machine": None, "moved_px": None,
            "ncc": None, "margin": None, "n_anchors": None,
            "blank": bool(_get(info, "blank", t in blank_list)),
            "texture": _get(info, "texture", texture.get(t)),
            "judged_at": None,
        }

    doc = {
        "schema_version": SCHEMA_VERSION,
        "app": {"name": APP_NAME, "version": APP_VERSION},
        "dataset": _get(session, "dataset", "") or "",
        # the acquisition's own name (log.txt's `New experiment:`), not the folder's. Recorded
        # because a directory label can lie about which acquisition this is; nothing branches on it.
        "experiment": _get(session, "experiment", "") or "",
        "data_dir": _get(session, "data_dir", "") or "",
        "tile_px": TILE_PX,
        "created": _now(),
        "modified": _now(),
        "trial_range": [lo, hi],
        "pass_split": pass_split,
        "gaps": [],                                     # filled by normalise(), below
        "coordinates": COORDINATES,
        "origin_trial": trials[0] if trials else lo,
        "tolerance_px": dict(TOLERANCE_PX),
        # ⭐ the sweep position. Saved, so `load()` resumes the session where he left it.
        "cursor": None,
        "unusable_tiles": [],                           # filled by normalise()
        "run": {
            "detected": bool(_get(run, "detected", True)),
            "why": _get(run, "why", ""),
            "pass_split_detected": bool(_get(split, "detected", True)),
            "pass_split_why": _get(split, "why", ""),
            "n_trials": len(trials),
        },
        "tone": {k: v for k, v in (tone.items() if isinstance(tone, dict) else [])
                 if k in ("lo", "hi", "level", "flat_sigma", "pct_lo", "pct_hi", "auto")},
        "blank_scan": {
            "threshold": _get(blank, "threshold", None),
            "measure": "std of DoG(sigma=3, sigma=30) of the flipped frame",
            "blank": sorted(blank_list),
            "accepted": False,                          # the scan RECOMMENDS; the user ticks.
        },
        "build": None,
        "provenance": {
            "authored_by": APP_NAME,
            "app_version": APP_VERSION,
            "workflow": "hand placement from scratch",
            "seeded_from": None,
            "independent_of_method": True,
            "human_edits": {},
            "scale": {"um_per_px": None, "source": "unknown"},
        },
        "tiles": tiles,
    }
    return normalise(doc)


# =============================================================================
# seed_from_build
# =============================================================================
def seed_from_build(doc: dict, build: dict) -> dict:
    """Apply a build's positions: every `unplaced` tile the solver placed becomes **`unverified`**
    at the build's position, with `machine` = that position.

    Tiles the solver could not place STAY `unplaced` — they go on the rescue list, and the sweep
    handles them with the same anchor-composite call as everything else (API.md §7).

    Already-`anchored` / `excluded` tiles are NOT touched: the human's decision outranks the machine.

    ⚠️ This flips the provenance: `seeded_from` = {method, build_id, config},
    `independent_of_method` = **false**, and the `warning` becomes **required**. See `stamp()`.
    """
    doc = copy.deepcopy(doc)
    build = _jsonable(build or {})
    positions = {int(k): [float(v[0]), float(v[1])] for k, v in (build.get("positions") or {}).items()}

    for k, tile in doc["tiles"].items():
        t = int(k)
        if t not in positions:
            continue
        if _state_of(tile) in ("anchored", "excluded"):
            # the human already ruled on this tile; record what the machine said, change nothing else
            tile["machine"] = list(positions[t])
            continue
        x, y = positions[t]
        tile["state"] = "unverified"
        tile["status"] = "unverified"
        tile["x"] = float(x)
        tile["y"] = float(y)
        tile["r"] = R_PLACED
        tile["machine"] = [float(x), float(y)]
        tile.setdefault("source", "t33 build (unverified)")

    doc["build"] = {
        "build_id": build.get("build_id"),
        "method": build.get("method", "t33"),
        "created": build.get("created") or _now(),
        "seconds": build.get("seconds"),
        "gpu": build.get("gpu"),
        "n_placed": build.get("n_placed", len(positions)),
        "config": (build.get("info") or {}).get("config") or build.get("config") or {},
        "info": build.get("info") or {},
        "positions": {str(t): list(p) for t, p in sorted(positions.items())},
        # what the solver was ACTUALLY given. If this stops matching the document, the build is
        # stale — see mark_stale_if_input_changed().
        "trials": active_trials(doc),
        "gaps": compute_gaps(doc),
        "stale": False,
        "stale_reason": None,
    }

    prov = doc.setdefault("provenance", {})
    prov["workflow"] = "machine-seeded verification sweep"
    prov["seeded_from"] = {
        "method": build.get("method", "t33"),
        "build_id": build.get("build_id"),
        "config": doc["build"]["config"],
    }
    prov["independent_of_method"] = False
    prov["warning"] = PROVENANCE_WARNING
    return normalise(doc)


# =============================================================================
# staleness — excluding a tile CHANGES THE INPUT
# =============================================================================
def mark_stale_if_input_changed(doc: dict) -> dict:
    """⚠️ If the trial list or the gaps have changed since the build ran, the build was solved on a
    DIFFERENT PROBLEM. Mark it stale.

    Excluding a tile removes a frame from the solver's input and opens a gap in acquisition order,
    and **the serpentine one-step prior does not hold across a gap** — a re-solve that assumed it
    away would silently place the whole tail wrong. So the app must OFFER A RE-SOLVE. It must never
    keep using the old positions as if nothing happened.

    (The gap check alone is not enough: excluding the FIRST or LAST trial of the run opens no gap
    but still changes the input. So we compare the trial list too.)

    🔴 **THE FALLBACK THAT DISARMED THIS.** It used to read

        was_trials = [int(t) for t in (b.get("trials") or now_trials)]

    — i.e. when the build block did not record what it was solved on, it **compared the current
    trial list with itself**, found them equal, and never fired. And the build block is written by
    the front end, which never wrote `trials` or `gaps`. So the whole apparatus was inert: the user
    could press `E` on trial 200 mid-sweep, open a gap at 199->201, and the app would keep — and
    autosave, and export — the positions of 200's neighbours, which had been solved THROUGH it,
    while asserting `stale: false`. A missing input record is now itself a reason: **unknown is not
    the same as unchanged.**
    """
    b = doc.get("build")
    if not isinstance(b, dict):
        return doc
    now_trials = active_trials(doc)
    now_gaps = compute_gaps(doc)

    if b.get("trials") is None:
        b["stale"] = True
        b["stale_reason"] = ("this build does not record which trials it was solved on, so it "
                             "cannot be checked against the current input. Re-solve.")
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
    if not isinstance(b, dict):
        return False, None
    return bool(b.get("stale")), b.get("stale_reason")


# =============================================================================
# normalise
# =============================================================================
def normalise(doc: dict) -> dict:
    """Pin `origin_trial` (= min(anchored trials)) at exactly [0.0, 0.0] by subtracting its position
    from every placed tile, and recompute the derived fields (`unusable_tiles`, `gaps`, `moved_px`,
    `provenance.human_edits`, build staleness).

    A layout is defined only up to a **global translation**, so this loses nothing and it makes the
    exported GT directly comparable with `analysis/ground_truth/` (which has trial 11 at (0,0)).

    ⚠️ The same translation is applied to `machine` and `last_xy`, so `moved_px = |final - machine|`
    stays meaningful. `build.positions` keeps the machine's untouched answer.
    """
    doc = copy.deepcopy(doc)
    tiles = doc.setdefault("tiles", {})

    # 1. every tile carries BOTH spellings and a sane `r`.
    for tile in tiles.values():
        st = _state_of(tile)
        tile["state"] = st
        tile["status"] = STATE_TO_STATUS[st]
        if st in PLACED_STATES:
            tile["r"] = float(tile.get("r") or R_PLACED)
        else:
            tile["x"] = None
            tile["y"] = None
            tile["r"] = float(tile.get("r") or R_UNPLACED)
        if st == "excluded":
            tile["excluded"] = True
        elif "excluded" in tile:
            tile["excluded"] = False

    # 2. origin: min(anchored), else min(placed). Everything shifts so it sits at exactly [0, 0].
    anchored = sorted(int(k) for k, v in tiles.items() if v["state"] == "anchored")
    placed = sorted(int(k) for k, v in tiles.items() if v["state"] in PLACED_STATES)
    origin = anchored[0] if anchored else (placed[0] if placed else None)
    if origin is not None:
        ox = float(tiles[str(origin)]["x"] or 0.0)
        oy = float(tiles[str(origin)]["y"] or 0.0)
        doc["origin_trial"] = origin
        if ox or oy:
            for tile in tiles.values():
                if tile["x"] is not None:
                    tile["x"] = float(tile["x"]) - ox
                    tile["y"] = float(tile["y"]) - oy
                m = tile.get("machine")
                if isinstance(m, (list, tuple)) and len(m) == 2 and m[0] is not None:
                    tile["machine"] = [float(m[0]) - ox, float(m[1]) - oy]
                lx = tile.get("last_xy")
                if isinstance(lx, (list, tuple)) and len(lx) == 2 and lx[0] is not None:
                    tile["last_xy"] = [float(lx[0]) - ox, float(lx[1]) - oy]
        # kill -0.0
        tiles[str(origin)]["x"] = 0.0
        tiles[str(origin)]["y"] = 0.0

    # 3. moved_px = |final - machine|  (both now in the same frame)
    for tile in tiles.values():
        m = tile.get("machine")
        if (tile["state"] in PLACED_STATES and isinstance(m, (list, tuple)) and len(m) == 2
                and m[0] is not None):
            tile["moved_px"] = round(_dist(tile["x"], tile["y"], m[0], m[1]), 4)
        else:
            tile["moved_px"] = None

    # 4. the derived lists
    doc["unusable_tiles"] = sorted(int(k) for k, v in tiles.items() if v["state"] == "excluded")
    doc["gaps"] = compute_gaps(doc)                     # ⚠️ never assumed away
    doc.setdefault("pass_split", None)
    if doc.get("pass_split") is not None:
        for k, tile in tiles.items():
            tile["pass"] = _pass_of(int(k), doc["pass_split"])

    mark_stale_if_input_changed(doc)
    doc["provenance"] = _human_edits(doc, doc.get("provenance") or {})
    return doc


def _human_edits(doc: dict, prov: dict) -> dict:
    """The honest record of what the human actually did. Recomputed on every normalise/stamp.

    ⭐ **EVERY EXCLUSION IS A HUMAN EDIT.** The app seeds none, so an `excluded` tile got there
    because he pressed `E` (in this session or in the one this file was saved from). There is no
    longer any such thing as an exclusion the app made on his behalf.
    """
    tiles = doc.get("tiles", {})
    seeded = machine_evidence(doc) is not None      # ⭐ the history, not the self-declaration
    accepted = moved = rescued = unverified = user_excluded = 0
    moves: list[float] = []
    for tile in tiles.values():
        st = _state_of(tile)
        if st == "unverified":
            unverified += 1
        if st == "excluded":
            user_excluded += 1
        if st not in PLACED_STATES:
            continue
        mv = tile.get("moved_px")
        if mv is None:
            if seeded:
                rescued += 1                            # the solver never placed it; the human did
            continue
        if float(mv) < MOVED_EPS:
            accepted += 1
        else:
            moved += 1
            moves.append(float(mv))

    # ⭐ THE DIVERTED TILES — and they must be counted HERE, in the backend.
    #
    # 🔴 The front end computes these in `exportDoc()` and writes them into `provenance.human_edits`
    # — and this function then REBUILT that dict from scratch on every normalise/save, silently
    # dropping them. Driven on the real app: a QC export of a sweep with 6 diverted tiles carried
    # `human_edits` with NO divert keys at all. So the one place the numbers were supposed to
    # survive — the file — was the one place they did not.
    #
    # It matters because a diverted tile IS sitting exactly on the machine's position, so it lands
    # in `accepted_unchanged` and reads as "the human looked and agreed". He did not: the app never
    # gave the correlator a vote there. Say so, next to the number it contaminates.
    diverted = sorted(int(k) for k, tile in tiles.items()
                      if tile.get("diverted") and _state_of(tile) != "excluded")
    prov = dict(prov)
    prov["human_edits"] = {
        "accepted_unchanged": accepted,                 # moved < 0.5 px
        "moved": moved,
        "excluded": user_excluded,                      # by the USER, during the sweep
        "unverified": unverified,                       # placed but never judged — Space, no decision
        "rescued": rescued,                             # the solver could not place it; the human did
        "median_move_px": round(_median(moves), 3),     # over the MOVED tiles only
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
    return prov


# =============================================================================
# stamp — ⚠️ THE PROVENANCE IS NOT DECORATION
# =============================================================================
def machine_evidence(doc: dict) -> dict | None:
    """⭐ **WAS THIS DOCUMENT EVER TOUCHED BY A MACHINE BUILD?** -> a `seeded_from` block, or None.

    🔴 **THE HOLE THIS CLOSES.** `stamp()` used to derive the entire provenance verdict from ONE
    field — `provenance.seeded_from` — which the FRONT END writes and can therefore erase. And it
    did: "Skip — place from scratch" (`sweep.js :: skipBuild`) nulled `build`, nulled `seeded_from`,
    set `independent_of_method: true` and DELETED the warning — **without touching a single tile.**
    Every tile kept t33's position and its `machine` answer. The button is reachable at any time
    (the step-3 breadcrumb never locks), and it reads like "don't run another build".

    Demonstrated on a document seeded from t33 and then "skipped": `independent_of_method: true`,
    `workflow: "hand placement from scratch"`, no warning, `validate() -> []` — and
    `human_edits: {accepted_unchanged: 3, max_move_px: 0.0}`, computed FROM the `machine` fields, is
    the fingerprint of the very thing the file denies. Score t33 against that and it gets ~100 % **by
    construction**. This is the exact mechanism that already destroyed
    `analysis/archive/challenge_2026-07/benchmark/ground_truth/260620d.json`.

    So the verdict is derived from the document's HISTORY — the build block and the `machine`
    positions that are still sitting in the tiles — and not from a self-declaration.
    """
    prov = doc.get("provenance") or {}
    seeded = prov.get("seeded_from")
    if seeded:
        return dict(seeded)

    build = doc.get("build")
    if isinstance(build, dict) and build:
        return {"method": build.get("method", "t33"),
                "build_id": build.get("build_id"),
                "config": build.get("config") or {},
                "detected_from": "doc['build'] — the build block is still in the document"}

    tiles = doc.get("tiles") or {}
    m = sorted(int(k) for k, v in tiles.items()
               if isinstance(v, dict) and v.get("machine") not in (None, [], {}))
    if m:
        return {"method": "unknown (a machine build)",
                "build_id": None,
                "config": {},
                "detected_from": (f"{len(m)} tile(s) still carry a `machine` position "
                                  f"({' '.join(str(t) for t in m[:8])}"
                                  f"{' ...' if len(m) > 8 else ''}) — every one of them started as "
                                  "a solver's answer, whatever the provenance block claims")}
    return None


def stamp(doc: dict, app_version: str = APP_VERSION) -> dict:
    """⚠️ **STAMP THE PROVENANCE. THIS IS NOT DECORATION.** Called on every save and every GT export.

    Pass 1's ground truth got tiles **128/129/130/148 wrong** *precisely because* it was seeded from
    a build and the human deferred to it — caught only because pass 2 was later authored blind. A
    verification UI that shows the machine's answer and invites a human to click "accept" is
    structurally that same hazard. This project has ALREADY destroyed one benchmark exactly this way
    (`analysis/archive/challenge_2026-07/benchmark/ground_truth/260620d.json` **is T27's own
    output**, after which T27 scored 100 % by construction and the benchmark could no longer detect
    its own errors).

      * ANY machine evidence  =>  `independent_of_method: false` AND the `warning` (verbatim).
        Evidence is `provenance.seeded_from`, **OR a `build` block, OR a single tile still carrying
        a `machine` position** — see `machine_evidence()`. The stamp is derived from the document's
        history, NOT from what the document says about itself.
      * No evidence anywhere  =>  `independent_of_method: true`, and the warning is OMITTED.
        That document *is* an honest truth.
    """
    doc = copy.deepcopy(doc)
    prov = dict(doc.get("provenance") or {})
    prov.setdefault("authored_by", APP_NAME)
    prov["app_version"] = app_version

    seeded = machine_evidence(doc)                       # ⭐ derived, not self-declared
    if seeded:
        prov["seeded_from"] = seeded
        prov["workflow"] = "machine-seeded verification sweep"
        prov["independent_of_method"] = False
        prov["warning"] = PROVENANCE_WARNING            # verbatim. Never paraphrased.
    else:
        prov["seeded_from"] = None
        prov["workflow"] = "hand placement from scratch"
        prov["independent_of_method"] = True
        prov.pop("warning", None)                       # an honest truth carries no warning
    prov.setdefault("scale", {"um_per_px": None, "source": "unknown"})

    doc["provenance"] = _human_edits(doc, prov)
    doc["app"] = {"name": APP_NAME, "version": app_version}
    doc["schema_version"] = SCHEMA_VERSION
    doc["modified"] = _now()
    doc.setdefault("created", doc["modified"])
    return doc


# =============================================================================
# validate
# =============================================================================
def _problems(doc: dict, session=None) -> list[tuple[str, str]]:
    """-> [(kind, message)]. `kind` is "hard" (normalise/stamp CANNOT fix it — refuse the document)
    or "derived" (a field normalise/stamp recomputes — repair it, do not reject the save)."""
    p: list[tuple[str, str]] = []
    if not isinstance(doc, dict):
        return [("hard", "the document is not a JSON object")]

    if doc.get("schema_version") != SCHEMA_VERSION:
        p.append(("derived",
                  f"schema_version is {doc.get('schema_version')!r}, expected {SCHEMA_VERSION!r}"))
    for key in ("dataset", "tile_px", "trial_range", "tolerance_px", "tiles"):
        if key not in doc:
            p.append(("hard", f"missing required key {key!r}"))
    for key in ("created", "coordinates", "origin_trial", "provenance", "unusable_tiles"):
        if key not in doc:
            p.append(("derived", f"missing required key {key!r} (recomputed on save)"))
    if doc.get("tile_px") not in (None, TILE_PX):
        p.append(("hard", f"tile_px is {doc.get('tile_px')!r}; only {TILE_PX} is supported"))

    tr = doc.get("trial_range")
    if not (isinstance(tr, list) and len(tr) == 2 and all(isinstance(v, int) for v in tr)
            and tr[0] <= tr[1]):
        p.append(("hard", f"trial_range must be [lo, hi] integers with lo <= hi; got {tr!r}"))
        tr = None

    tol = doc.get("tolerance_px")
    if not isinstance(tol, dict) or any(k not in tol for k in ("anchor", "region_default", "grading")):
        p.append(("hard", "tolerance_px must have anchor / region_default / grading — "
                          "score.load_gt() reads tolerance_px.region_default as the fallback `r`"))

    tiles = doc.get("tiles")
    if not isinstance(tiles, dict):
        p.append(("hard", "tiles must be an object keyed by trial number"))
        return p

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
        if st not in STATES:
            p.append(("hard", f"tile {t}: state {st!r} is not one of {STATES}"))
            continue
        if status != STATE_TO_STATUS[st]:
            p.append(("hard", f"tile {t}: status {status!r} disagrees with state {st!r} "
                              f"(expected {STATE_TO_STATUS[st]!r})"))
        x, y = tile.get("x"), tile.get("y")
        if st in PLACED_STATES:
            if not (isinstance(x, (int, float)) and not isinstance(x, bool)
                    and isinstance(y, (int, float)) and not isinstance(y, bool)
                    and math.isfinite(float(x)) and math.isfinite(float(y))):
                p.append(("hard", f"tile {t}: state {st!r} must have finite numeric x and y; "
                                  f"got {x!r},{y!r}"))
        elif x is not None or y is not None:
            p.append(("hard", f"tile {t}: state {st!r} must have x = y = null; got {x!r},{y!r}"))
        # ⛔ NO TRIAL NUMBER IS SPECIAL. There is no built-in exclusion list to check a tile against
        # — the only exclusions are the human's, and a human exclusion is never invalid. The guard
        # that used to live here ("tile 284 is THROWN OUT and carries a position") made the user's
        # own test session UNSAVEABLE the moment he anchored 284. It is gone. Do not bring it back:
        # a dataset ruling belongs in the project file, not in the app.
        if tr and not (tr[0] <= t <= tr[1]):
            p.append(("hard", f"tile {t} is outside trial_range {tr}"))

    # origin_trial: anchored (or, before any anchor exists, the first placed tile) at exactly [0,0]
    anchored = sorted(int(k) for k, v in tiles.items()
                      if isinstance(v, dict) and v.get("state") == "anchored")
    placed = sorted(int(k) for k, v in tiles.items()
                    if isinstance(v, dict) and v.get("state") in PLACED_STATES)
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

    want_unusable = sorted(int(k) for k, v in tiles.items()
                           if isinstance(v, dict) and v.get("state") == "excluded")
    if [int(v) for v in (doc.get("unusable_tiles") or [])] != want_unusable:
        p.append(("derived", f"unusable_tiles is {doc.get('unusable_tiles')!r}; the excluded tiles "
                             f"are {want_unusable!r}"))

    # ⚠️ THE GAP INVARIANT. NOT COSMETIC — this is an ERROR, and `normalise` is the only thing
    # allowed to satisfy it. A doc that reaches a SOLVER with stale gaps applies the one-step prior
    # across a multi-step jump and silently places the whole tail wrong.
    want_gaps = compute_gaps(doc)
    got_gaps = [[int(a), int(b)] for a, b in (doc.get("gaps") or [])]
    if got_gaps != want_gaps:
        p.append(("derived", f"gaps is {got_gaps!r}; the excluded tiles imply {want_gaps!r}"))

    prov = doc.get("provenance")
    if not isinstance(prov, dict):
        p.append(("derived", "provenance is missing — it is MANDATORY and it is not decoration"))
    else:
        for key in ("authored_by", "workflow", "seeded_from", "independent_of_method"):
            if key not in prov:
                p.append(("derived", f"provenance.{key} is missing"))
        # ⭐ SEEDED IS DERIVED FROM THE DOCUMENT'S HISTORY (a build block, or any tile still carrying
        # a `machine` position), never from `seeded_from` alone — that field is front-end-writable
        # and a "skip the build" click could erase it while every tile kept the solver's answer.
        ev = machine_evidence(doc)
        seeded = ev is not None
        if seeded and prov.get("seeded_from") is None:
            p.append(("derived",
                      "provenance.seeded_from is null, but this document IS machine-seeded: "
                      f"{ev.get('detected_from')}. A document that claims to be an independent "
                      "ground truth while every position started as a solver's output scores that "
                      "solver ~100 % BY CONSTRUCTION. This project has already destroyed one "
                      "benchmark exactly this way."))
        if seeded and prov.get("independent_of_method") is not False:
            p.append(("derived", "provenance.independent_of_method must be FALSE when the document "
                                 "was seeded from a build — it must never be used to score the "
                                 "method that produced it"))
        if seeded and not prov.get("warning"):
            p.append(("derived",
                      "provenance.warning is REQUIRED when the document was seeded from a build"))
        if not seeded and prov.get("independent_of_method") is not True:
            p.append(("derived", "provenance.independent_of_method must be TRUE when nothing in the "
                                 "document came from a machine build"))
        if not seeded and prov.get("warning"):
            p.append(("derived", "provenance.warning must be OMITTED when the document is "
                                 "independent of any method"))

    if session is not None:
        run = _get(session, "run", {}) or {}
        run_trials = set(int(t) for t in (_get(run, "trials", []) or []))
        if run_trials:
            stray = sorted(int(k) for k in tiles if int(k) not in run_trials)
            if stray:
                p.append(("hard", f"tiles {stray[:12]} are not in the session's run"))
        ds = _get(session, "dataset", None)
        if ds and doc.get("dataset") and doc["dataset"] != ds:
            p.append(("hard", f"dataset {doc['dataset']!r} != the open session's {ds!r}"))
    return p


def validate(doc: dict, session=None) -> list[str]:
    """-> a list of human-readable problems ([] = valid).

    ⚠️ `jsonschema` IS NOT INSTALLED (and must not be pip-installed while six other agents share
    this env), so the checks are hand-rolled. That is no loss: the interesting invariants are ones a
    JSON Schema cannot express anyway — above all **`gaps` == `excluded.gaps(active_trials)`**, which
    is an ERROR, not a warning. `project_schema.json` stays the normative documentation.
    """
    return [m for _kind, m in _problems(doc, session)]


# =============================================================================
# save / load / autosave
# =============================================================================
def _structural_problems(doc: dict) -> list[str]:
    """The problems `normalise()` + `stamp()` CANNOT fix — a broken state machine, a placed tile with
    no position, a missing `tolerance_px`.

    Everything else (`gaps`, `unusable_tiles`, `origin_trial`, `moved_px`, `human_edits`, the
    provenance stamp) is DERIVED, and normalise/stamp recompute it. Rejecting a save for that drift
    would reject a perfectly good document — the drift is *expected*: it is exactly what happens the
    moment the user excludes a tile or anchors an earlier one.

    ⛔ **Nothing here may reject a document for WHICH trials it placed.** A save that refuses the
    user's own work is a bug, not a guard.
    """
    return [m for kind, m in _problems(doc) if kind == "hard"]


def save(path, doc: dict, session=None, app_version: str = APP_VERSION) -> dict:
    """structural-validate -> normalise -> stamp -> full-validate -> write ATOMICALLY.
    -> {"path", "bytes", "saved_at", "doc"}.   ⛔ `data/` is NEVER written to.
    Raises ValidationError (-> HTTP 400) if the document cannot be made valid.

    `session` is accepted (the server passes it) and used only by the caller's range guard — the
    document is the sole authority on what is excluded, and the session never overrides it.
    """
    problems = _structural_problems(doc)
    if problems:
        raise ValidationError(problems)

    out = stamp(normalise(doc), app_version)

    # ⚠️ deliberately WITHOUT `session`: the session-aware checks (stray tiles / dataset mismatch)
    # are a LOAD-time guard. Running them here would turn a legitimate run-range change into a hard
    # 400 on the next autosave. The post-condition is "never write a structurally broken file".
    problems = validate(out)                            # post-condition: never write a broken file
    if problems:
        raise ValidationError(problems)

    path = Path(path)
    _refuse_data_dir(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(_jsonable(out), indent=2, ensure_ascii=False) + "\n"
    _atomic_write(path, payload)
    return {"path": str(path).replace("\\", "/"),
            "bytes": len(payload.encode("utf-8")),
            "saved_at": out["modified"],
            "doc": out}


def _refuse_data_dir(path: Path) -> None:
    """⛔ `data/` is a READ-ONLY MIRROR (an rclone mirror of a public Drive folder). Never write."""
    try:
        rp = path.resolve()
    except OSError:
        rp = path
    guarded = [_ROOT / "data"]
    dd = getattr(_excluded, "DATA_DIR", None)
    if dd is not None:
        guarded.append(Path(dd))
    for g in guarded:
        try:
            if rp == g or g.resolve() in rp.parents:
                raise ProjectError(f"refusing to write inside the read-only data mirror: {rp}")
        except OSError:
            continue


#: 🔴 **SERIALISES EVERY WRITE.** `os.replace` is atomic, but on Windows it is *not* safe against a
#: second replace landing on the same target at the same instant: the loser gets
#: `PermissionError: [WinError 5] Access is denied`. Two autosaves ARE routinely in flight at once —
#: the front end's 2 s debounce can fire into the unconditional `autosaveNow()` on `A` — and the
#: loser's document was **silently lost** (the POST 500'd and nothing retried). Reproduced
#: deterministically: 4 concurrent POST /api/project/autosave -> 1 failed. One process-wide lock;
#: the writes are milliseconds, so contention is irrelevant.
_WRITE_LOCK = threading.Lock()


def _atomic_write(path: Path, text: str) -> None:
    """temp file in the same directory + os.replace, under `_WRITE_LOCK`. A crash never leaves a
    half-written project, and two concurrent savers never destroy each other's write.

    The lock covers this process. `os.replace` can still lose to an *external* holder of the target
    (an antivirus scanner, an editor, a second Camea) — so the replace is retried briefly rather than
    failing the save on a transient share-violation.
    """
    with _WRITE_LOCK:
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".camea-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())
            last: OSError | None = None
            for attempt in range(6):                    # ~0.31 s worst case: 10,20,40,80,160 ms
                try:
                    os.replace(tmp, path)              # atomic on Windows and POSIX
                    return
                except PermissionError as e:           # WinError 5 / 32: someone else holds it
                    last = e
                    _time.sleep(0.01 * (2 ** attempt))
            raise last                                  # type: ignore[misc]
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def load(path, session=None) -> tuple[dict, list[str]]:
    """-> (doc, warnings). Migrates an older `schema_version`; derives `state` from `status` for a
    document written by the bench (which never had a `state` field).

    ⭐ **THIS FILE IS THE APP'S ONLY MEMORY OF THE RUN** — its exclusions, placements, cursor, build
    and tone window. The app itself remembers nothing between sessions, so whatever is `excluded`
    here is excluded, and nothing else is. `save()` -> quit -> `load()` restores the session whole.

    ⚠️ **GUARDS THE RANGE.** If `session` is given and the document's `dataset` / `trial_range` do
    not match it, **raises RangeMismatch** (the caller returns 409). **Pass 2's autosave once
    silently overwrote pass 1's ground-truth records.** Do not re-open that hole.

    ⚠️ **UNKNOWN KEYS ARE PRESERVED VERBATIM**, per tile and at the top level. A lossy round-trip
    quietly destroys a hand-written note — and this file is also somebody's ground truth.
    """
    path = Path(path)
    doc = json.loads(path.read_text(encoding="utf-8"))
    warnings: list[str] = []
    if not isinstance(doc, dict) or "tiles" not in doc:
        raise ProjectError(f"{path} is not a Camea project (no `tiles`)")

    doc, migrated = _migrate(doc)
    warnings += migrated

    # ⚠️ THE GUARD. Before anything else touches the session.
    if session is not None:
        ds = _get(session, "dataset", None)
        run = _get(session, "run", {}) or {}
        lo, hi = _get(run, "lo", None), _get(run, "hi", None)
        d_ds = doc.get("dataset")
        d_tr = doc.get("trial_range") or [None, None]
        if (ds and d_ds and d_ds != ds) or (lo is not None and hi is not None and d_tr[:2] != [lo, hi]):
            raise RangeMismatch(
                f"this project is for trials {d_tr[0]}-{d_tr[1]} of {d_ds}; "
                f"the open session is {lo}-{hi} of {ds}")

    problems = _structural_problems(doc)
    if problems:
        raise ValidationError(problems)

    doc = normalise(doc)                                # repairs the derived fields, flags staleness
    stale, why = is_build_stale(doc)
    if stale:
        warnings.append("The batch build is STALE: " + str(why))
    for m in validate(doc, session):
        warnings.append("validation: " + m)
    return doc, warnings


def _migrate(doc: dict) -> tuple[dict, list[str]]:
    """Bring an older / bench-written document up to camea-project-1.0 WITHOUT losing a key."""
    doc = copy.deepcopy(doc)
    w: list[str] = []
    sv = doc.get("schema_version")
    if sv is None:
        w.append("no schema_version — treating it as a bench-written ground truth and deriving "
                 "`state` from `status`.")
    elif sv != SCHEMA_VERSION:
        w.append(f"schema_version {sv!r} -> {SCHEMA_VERSION!r}")
    doc["schema_version"] = SCHEMA_VERSION

    for tile in doc.get("tiles", {}).values():
        if isinstance(tile, dict):
            old = tile.get("status")
            if old is not None and old not in STATUS_TO_STATE and "legacy_status" not in tile:
                tile["legacy_status"] = old             # e.g. the GT's "region" / "pending" rows
            st = _state_of(tile)                        # `state` wins; else derived from `status`
            tile["state"] = st
            tile["status"] = STATE_TO_STATUS[st]

    doc.setdefault("tile_px", TILE_PX)
    doc.setdefault("coordinates", COORDINATES)
    doc.setdefault("tolerance_px", dict(TOLERANCE_PX))
    for k, v in TOLERANCE_PX.items():
        doc["tolerance_px"].setdefault(k, v)
    doc.setdefault("created", _now())
    doc.setdefault("unusable_tiles", [])
    doc.setdefault("gaps", [])
    doc.setdefault("pass_split", None)
    doc.setdefault("build", None)
    # ⭐ THE SESSION-RESUME KEYS. The project file is the app's only memory, so every part of a
    # session must survive a round-trip: where he was (`cursor`), how the frames were being displayed
    # (`tone`), and whether he had accepted the blank scan's recommendation (`blank_scan.accepted`).
    # A document that predates them opens with them empty rather than with them missing.
    doc.setdefault("cursor", None)
    doc.setdefault("tone", {})
    bs = doc.setdefault("blank_scan", {})
    if isinstance(bs, dict):
        bs.setdefault("blank", [])
        bs.setdefault("accepted", False)

    # The existing hand-authored ground truths (analysis/ground_truth/*.json) carry no
    # `trial_range` — they predate this schema. Derive it from the tiles they DO carry, so the
    # range guard has something to compare, rather than refusing to open a real ground truth.
    ts = sorted(int(k) for k in doc.get("tiles", {}))
    if not (isinstance(doc.get("trial_range"), list) and len(doc.get("trial_range") or []) == 2):
        if ts:
            doc["trial_range"] = [ts[0], ts[-1]]
            w.append(f"no trial_range — derived [{ts[0]}, {ts[-1]}] from the tiles present.")
        else:
            doc["trial_range"] = [0, 0]
    if not isinstance(doc.get("provenance"), dict):
        doc["provenance"] = {"authored_by": doc.get("authored_by", "unknown"),
                             "workflow": "hand placement from scratch",
                             "seeded_from": None, "independent_of_method": True}
        w.append("no provenance block — assuming hand placement (seeded_from: null).")
    if "origin_trial" not in doc:
        placed = sorted(int(k) for k, v in doc.get("tiles", {}).items()
                        if v.get("x") is not None)
        doc["origin_trial"] = placed[0] if placed else 0
    return doc, w


def autosave_path(dataset: str) -> Path:
    """`%LOCALAPPDATA%/Camea/autosave/<dataset>.camea.json`. Created on demand."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_STATE_HOME") \
        or str(Path.home() / ".local" / "state")
    d = Path(base) / "Camea" / "autosave"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{dataset or 'untitled'}.camea.json"


def autosave(doc: dict, app_version: str = APP_VERSION) -> dict:
    """Crash recovery. Debounced at 2 s by the front end + unconditionally on every `A` / `E`.
    -> {"path", "saved_at", "warnings"}.

    ⚠️ **THE OVERWRITE GUARD.** The autosave filename is `<dataset>.camea.json` (API.md §4.2), so
    two DIFFERENT RANGES of the same dataset would collide — and *that is precisely the accident
    that happened*: pass 2's autosave silently overwrote pass 1's ground-truth records. So if the
    file already there is for a different `trial_range`, we DO NOT overwrite it; we write to
    `<dataset>__<lo>-<hi>.camea.json` beside it and say so.

    Autosave never raises on a document the user is mid-way through building: it saves what it can.
    """
    dataset = doc.get("dataset") or "untitled"
    tr = doc.get("trial_range") or [None, None]
    path = autosave_path(dataset)
    warnings: list[str] = []

    if path.exists():
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
            ptr = prev.get("trial_range") or [None, None]
            if (prev.get("dataset") or dataset) != dataset or list(ptr[:2]) != list(tr[:2]):
                path = path.with_name(f"{dataset}__{tr[0]}-{tr[1]}.camea.json")
                warnings.append(
                    f"the autosave slot for {dataset} already holds trials {ptr[0]}-{ptr[1]}; "
                    f"refusing to overwrite it. This document ({tr[0]}-{tr[1]}) goes to "
                    f"{path.name} instead.")
        except (OSError, ValueError):
            pass                                        # unreadable autosave: overwrite it

    out = stamp(normalise(doc), app_version)
    _refuse_data_dir(path)
    payload = json.dumps(_jsonable(out), indent=2, ensure_ascii=False) + "\n"
    _atomic_write(path, payload)
    return {"path": str(path).replace("\\", "/"), "saved_at": out["modified"],
            "bytes": len(payload.encode("utf-8")), "warnings": warnings}


# =============================================================================
# exports  (called by export.py)
# =============================================================================
def to_gt(doc: dict, app_version: str = APP_VERSION) -> dict:
    """The document -> a ground-truth JSON scoreable by `analysis/benchmark/score.py` **unchanged**.

    `score.load_gt()` keeps ONLY `status == "anchor"` rows with a non-null x/y, and falls back to
    `tolerance_px.region_default` for a missing per-tile `r`. Every app-only key is left in place —
    score.py ignores them.

    ⛔ **DO NOT REIMPLEMENT `score.robust_align`** anywhere in this app. A reimplementation with a
    different tie-break scored the same positions **152/156** where the canonical one gives
    **155/156**. Import it.
    """
    return stamp(normalise(doc), app_version)           # the stamp cannot be skipped on the way out


def to_positions_csv(doc: dict, include_unverified: bool = True) -> str:
    """The document -> `positions.csv`. Header **exactly**:

        trial,x,y,state

    The first three column names are what `benchmark/score.py :: load_positions` reads
    (`csv.DictReader` on `trial`, `x`, `y`). Do not rename them, do not reorder them, do not add a
    column before them. `excluded` and `unplaced` tiles are omitted — they have no position.
    """
    doc = normalise(doc)
    rows = ["trial,x,y,state"]
    for t in _trials(doc):
        tile = doc["tiles"][str(t)]
        st = tile["state"]
        if st == "anchored" or (st == "unverified" and include_unverified):
            rows.append(f"{t},{float(tile['x']):.4f},{float(tile['y']):.4f},{st}")
    return "\n".join(rows) + "\n"


def qc_report(doc: dict, app_version: str = APP_VERSION) -> tuple[dict, str]:
    """-> (json_dict, markdown_text). **What the human did vs what the machine said.**

    This report *is* the honest record of the anchoring hazard, and it is the thing that makes the
    output safe to hand to somebody else. **Every number states its denominator** — a percentage
    without one is how the 182-vs-156 confusion started. The denominator is the document's own
    `excluded` set, nothing else: the app has no list of its own.
    """
    doc = to_gt(doc, app_version)
    tiles = doc["tiles"]
    prov = doc["provenance"]
    he = prov["human_edits"]

    n_total = len(tiles)
    n_run = len(active_trials(doc))
    by = {s: sorted(int(k) for k, v in tiles.items() if v["state"] == s) for s in STATES}

    moved_rows = sorted(
        ({"trial": int(k), "moved_px": float(v["moved_px"]),
          "from": list(v["machine"]), "to": [float(v["x"]), float(v["y"])],
          "state": v["state"], "ncc": v.get("ncc"), "margin": v.get("margin"),
          "n_anchors": v.get("n_anchors"), "note": v.get("note")}
         for k, v in tiles.items()
         if v["state"] in PLACED_STATES and v.get("moved_px") is not None
         and float(v["moved_px"]) >= MOVED_EPS),
        key=lambda r: -r["moved_px"])

    thin = sorted((int(k) for k, v in tiles.items()
                   if v.get("margin") is not None and float(v["margin"]) < 0.10
                   and v["state"] in PLACED_STATES))
    rescued = sorted(int(k) for k, v in tiles.items()
                     if v["state"] in PLACED_STATES and v.get("machine") is None
                     and prov.get("seeded_from"))
    stale, stale_why = is_build_stale(doc)

    rep = {
        "dataset": doc.get("dataset"),
        "trial_range": doc.get("trial_range"),
        "pass_split": doc.get("pass_split"),
        "generated": _now(),
        "app": {"name": APP_NAME, "version": app_version},
        "denominator": {
            "trials_in_document": n_total,
            "usable_trials": n_run,                     # everything not `excluded`
            "excluded": len(by["excluded"]),            # excluded by the human / by this file
            "excluded_trials": by["excluded"],
            "note": "Every percentage in this report is over the usable trials, never over the "
                    "document's row count.",
        },
        "states": {s: {"n": len(by[s]), "trials": by[s]} for s in STATES},
        "human_edits": he,
        "moved": moved_rows,
        "rescued": rescued,
        "thin_margin": {
            "trials": thin,
            "note": "A thin margin (< 0.10 best-minus-second NCC) is the signature of a surviving "
                    "alias. Look at these first.",
        },
        "gaps": doc.get("gaps"),
        "gaps_note": "The serpentine one-step prior does NOT hold across these. A build that assumes "
                     "them away places the whole tail wrong.",
        "build": ({k: v for k, v in (doc.get("build") or {}).items() if k != "positions"}
                  if doc.get("build") else None),
        "build_stale": {"stale": stale, "why": stale_why},
        "provenance": prov,
    }

    pct = (lambda n: f"{100.0 * n / n_run:.1f} %" if n_run else "—")
    L = [f"# QC report — {rep['dataset']}  (trials {doc['trial_range'][0]}–{doc['trial_range'][1]})",
         "",
         f"Generated {rep['generated']} by {APP_NAME} {app_version}.",
         ""]

    if not prov.get("independent_of_method"):
        L += ["> ## ⚠️ THIS IS NOT AN INDEPENDENT GROUND TRUTH",
              ">",
              "> " + PROVENANCE_WARNING,
              ">",
              f"> Seeded from **{(prov.get('seeded_from') or {}).get('method')}**, build "
              f"`{(prov.get('seeded_from') or {}).get('build_id')}`.",
              ""]
    else:
        L += ["> **Hand placement from scratch.** No build seeded this document, so it is an "
              "independent truth and may be used to score a method.",
              ""]

    if stale:
        L += ["> ## ⚠️ THE BATCH BUILD IS STALE",
              ">",
              "> " + str(stale_why),
              ""]

    n_excl = len(by["excluded"])
    L += ["## The denominator",
          "",
          f"- **{n_run}** usable trials. Every percentage below is over those {n_run}.",
          f"- {n_total} tile rows in the document; **{n_excl}** excluded.",
          "",
          "## What the human did",
          "",
          "| | tiles | of the run |",
          "|---|---:|---:|",
          f"| **anchored** (`A` — ground truth) | {len(by['anchored'])} | {pct(len(by['anchored']))} |",
          f"| **unverified** (`Space`, no decision) | {len(by['unverified'])} | {pct(len(by['unverified']))} |",
          f"| **unplaced** (never placed) | {len(by['unplaced'])} | {pct(len(by['unplaced']))} |",
          f"| **excluded** (`E`) | {n_excl} | — |",
          "",
          "## Human vs machine",
          ""]
    if doc.get("build"):
        L += [f"- **accepted unchanged** (moved < {MOVED_EPS} px): **{he['accepted_unchanged']}**",
              f"- **moved by hand**: **{he['moved']}**  "
              f"(median {he['median_move_px']:.2f} px, max {he['max_move_px']:.2f} px — over the "
              "moved tiles only)",
              f"- **rescued** (the solver could not place it; the human did): **{he['rescued']}**",
              f"- **still unverified**: **{he['unverified']}**",
              ""]
        # ⭐ AND THE DIVERTS — the tiles the app placed at the SOLVER's position because the
        # anchor-composite match was not trustworthy there. They are AT the machine's position, so
        # they are inside `accepted unchanged` above; without this block that number reads as human
        # agreement it never got. (See `_human_edits`.)
        if he.get("diverted_to_solver"):
            L += [f"### ⚠️ {he['diverted_to_solver']} tiles were DIVERTED to the solver",
                  "",
                  "- " + " ".join(str(t) for t in he["diverted_trials"]),
                  "- " + str(he["diverted_note"]),
                  ""]
        if moved_rows:
            L += ["### Tiles the human moved (worst first)",
                  "",
                  "| trial | moved (px) | machine | human | NCC | margin | anchors |",
                  "|---:|---:|---|---|---:|---:|---:|"]
            for r in moved_rows:
                f_ = f"({r['from'][0]:.1f}, {r['from'][1]:.1f})"
                t_ = f"({r['to'][0]:.1f}, {r['to'][1]:.1f})"
                ncc = "—" if r["ncc"] is None else f"{float(r['ncc']):.3f}"
                mg = "—" if r["margin"] is None else f"{float(r['margin']):.3f}"
                na = "—" if r["n_anchors"] is None else str(r["n_anchors"])
                L.append(f"| {r['trial']} | {r['moved_px']:.2f} | {f_} | {t_} | {ncc} | {mg} | {na} |")
            L.append("")
    else:
        L += ["- No build seeded this document — every position is the human's.", ""]

    if thin:
        L += ["### ⚠️ Thin margins (< 0.10) — the signature of a surviving alias",
              "",
              "- " + " ".join(str(t) for t in thin),
              ""]
    if by["unplaced"]:
        L += ["### Still unplaced", "", "- " + " ".join(str(t) for t in by["unplaced"]), ""]

    L += ["## Acquisition gaps",
          "",
          ("- " + "  ".join(f"{a}→{b}" for a, b in (doc.get("gaps") or []))) if doc.get("gaps")
          else "- none",
          "- " + rep["gaps_note"],
          "",
          "## Scale",
          "",
          "- **Pixels only, unless you typed a µm/px in.** This app does not measure it. Calibrate "
          "from the **stage** (commanded µm per trial vs measured pixel displacement), not from the "
          "electrode grid — the grid pitch tracks focus, not magnification (`app/SCALE.md`).",
          ""]
    return rep, "\n".join(L)
