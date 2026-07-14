"""document.py — **THE GENERIC ANALYSIS DOCUMENT.** Save / load / autosave / validate / migrate.

This is the envelope, and nothing but the envelope: *which* dataset, *which* feature, when, and —
above all — **what made this**. The feature's own payload (mosaic's tiles, anchors and gaps; the next
feature's whatever) rides **flat, at the top level, beside these keys**, and core treats it as an
opaque blob it round-trips faithfully.

Extracted from `archive/app-v1/backend/project.py` (1,339 lines, of which ~1,050 were mosaic).

---------------------------------------------------------------------------------------------------
THE FOUR THINGS THAT MUST SURVIVE ANY REWRITE OF THIS FILE
---------------------------------------------------------------------------------------------------

1. ⭐ **THE PROVENANCE VERDICT IS DERIVED FROM THE DOCUMENT'S HISTORY, NEVER FROM WHAT THE DOCUMENT
   SAYS ABOUT ITSELF.** `stamp()` asks the FEATURE for evidence (`machine_evidence`) and, if there is
   any, forces `independent_of_method: false` and attaches `PROVENANCE_WARNING` **verbatim**. No
   feature may opt out; there is no flag. v1 derived the verdict from `provenance.seeded_from` alone —
   a field the front end writes — and *"Skip — place from scratch"* erased it while every tile kept
   the solver's position. **This project has already destroyed one benchmark exactly that way.**

2. ⛔ **UNKNOWN KEYS ARE PRESERVED VERBATIM**, at the top level and (via the feature) per record. A
   saved document is also somebody's *ground truth* and may carry a hand-written note. A lossy
   round-trip destroys it. Nothing here ever rebuilds a document from scratch — it deep-copies and
   edits, and it only ever touches the keys it names.

3. ⛔ **THE PAYLOAD IS FLAT.** The obvious envelope — `{..., "feature": "mosaic", "payload": {...}}` —
   is FORBIDDEN: `benchmark/score.py :: load_gt()` reads `doc["tiles"][k]["status"]` and
   `doc["tolerance_px"]["region_default"]` at the **top level**, and a project the scorer cannot read
   is a project that cannot be checked. Route on `doc["feature"]`; do not nest. (SPLIT §4.2.)

4. ⛔ **NO TRIAL NUMBER IS SPECIAL, AND NO DATASET IS KNOWN.** Nothing here may reject a document for
   *which* things it placed. The guard that used to live in v1's validator ("tile 284 is thrown out
   and carries a position") made the user's own session **unsaveable** the moment he anchored 284.

---------------------------------------------------------------------------------------------------
WHERE THE BYTES GO — and why none of that is in this file
---------------------------------------------------------------------------------------------------
`core.workspace` is the filesystem: it owns paths, the read-only-data guard, the atomic writer and
the analysis directory (one per analysis, each with its own `document.camea.json` and its own
`autosave.camea.json`). **This module owns the CONTENT**: it validates, normalises and stamps, and
hands the finished document over to be written.

That line is the whole reason v1's autosave bug cannot recur. v1 keyed the autosave slot on the
*dataset directory*, so two trial ranges of one dataset collided and **pass 2's autosave silently
overwrote pass 1's ground-truth records**. A range is now an *analysis*, an analysis is a *directory*,
and the collision is structurally impossible rather than merely guarded.

---------------------------------------------------------------------------------------------------
THE FEATURE BOUNDARY
---------------------------------------------------------------------------------------------------
Core knows *that* a feature has a payload. It never knows *what*. Everything payload-shaped is a
hook (see `FeatureHooks`), registered once at the feature package's import:

    from camea.core.document import register_feature
    register_feature("mosaic", MosaicHooks())

⛔ **CORE MAY NOT IMPORT FROM `features/`.** The arrow is one-way: `api → features → core → engine`.
The registry is how a feature reaches core without core reaching back.

⚠️ **AN UNREGISTERED FEATURE FAILS CLOSED.** A document whose feature has no hooks cannot be stamped,
because its provenance verdict cannot be derived — and defaulting to `independent_of_method: true` is
precisely how a machine build gets laundered into a "ground truth". So it raises. The safe direction
is *refuse*, never *assume honest*.
"""

from __future__ import annotations

import copy
import json
import math
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import camea

if TYPE_CHECKING:                                        # a type hint only — never an import cycle
    from camea.core.workspace import Workspace

# =================================================================================================
# Constants
# =================================================================================================

#: The envelope's schema. Bumped from v1's `camea-project-1.0` — a *project* was a mosaic; a
#: *document* is any feature's analysis. `_migrate_envelope` accepts the old string, and a document
#: with no `schema_version` at all (the hand-authored ground truths predate the app entirely).
SCHEMA_VERSION = "camea-document-1.0"

#: Every `schema_version` this app has ever written. A file written by v1 must still open.
LEGACY_SCHEMA_VERSIONS = ("camea-project-1.0",)

APP_NAME = "Camea"

#: v1 had exactly one feature, and its documents carry no `feature` key — nor do the hand-authored
#: ground truths, which predate the app. This is the ONLY place core names a feature; it is used ONLY
#: when migrating a document written before the key existed; and it is FORMAT knowledge (what a
#: `camea-project-1.0` file *is*), not dataset knowledge. Every document this app writes says so
#: explicitly.
LEGACY_FEATURE = "mosaic"

#: The two workflows a document can have been produced by. `stamp()` chooses from the EVIDENCE.
WORKFLOW_SEEDED = "machine-seeded verification sweep"
WORKFLOW_HAND = "hand placement from scratch"

#: ⭐⭐ **VERBATIM. NEVER PARAPHRASED, NEVER SHORTENED, NEVER "IMPROVED".** `stamp()` attaches it to
#: every document with any machine evidence in it. It is the text that has to persuade a future reader
#: of a stray JSON file, and it applies to every feature, present and future — which is exactly why it
#: lives in core and not in the mosaic.
PROVENANCE_WARNING = (
    "NOT AN INDEPENDENT GROUND TRUTH. Every position here started as a machine build's output and "
    "was confirmed or corrected by a human who could see it. It MUST NEVER be used to score that "
    "method or any method derived from it — the score would be 100 % by construction. This project "
    "has already destroyed one benchmark exactly this way.")


# =================================================================================================
# Errors
# =================================================================================================
class DocumentError(Exception):
    """Base class. (v1: `ProjectError`.)"""


class ValidationError(DocumentError):
    """The document cannot be made valid. `.problems` is what `validate()` returned. -> HTTP 400."""

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems[:6]) +
                         (f" (+{len(self.problems) - 6} more)" if len(self.problems) > 6 else ""))


class RangeMismatch(DocumentError):
    """This document is not for the session it is being opened into. -> HTTP 409 `range_mismatch`.

    ⚠️ **Pass 2's autosave once silently overwrote pass 1's ground-truth records.** It is not merged,
    not renamed, not "repaired" — it is refused.

    ⚠️ Distinct from `workspace.SlotMismatch`, which is the same rule one layer down: *this document
    does not belong in this analysis DIRECTORY*. This one is about the open SESSION. Both are 409.
    """


class UnknownFeature(DocumentError):
    """No hooks are registered for this document's `feature`. -> HTTP 400.

    Deliberately fatal: without the feature's `machine_evidence` the provenance verdict cannot be
    derived, and the *safe* default is not "independent" — it is "refuse to answer".
    """


# =================================================================================================
# Shared utilities
# =================================================================================================
def iso_now() -> str:
    """The clock: UTC, ISO-8601, `Z`-suffixed. `Z` and never `+00:00` — every file already on the
    user's disk says `Z`, and pydantic's `datetime` would serialise the other one.

    (`core.dataset.iso(dt)` is the *formatter* for a datetime you already have. This is the *clock*,
    and it lives here so that writing a JSON file does not drag numpy into the import graph.)
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def jsonable(obj: Any) -> Any:
    """⭐ **THE COERCER.** Make an arbitrary object JSON-safe. Run a document through this before
    handing it to `workspace.dumps()`, which deliberately refuses to coerce.

    ⚠️ **t33's `info["config"]` is NOT JSON-serialisable** — it holds a nested `t27.Config` and
    `json.dumps(info)` **crashes** without this. It also coerces numpy scalars/arrays, which are all
    over `info`, and drops NaN/inf (which are not JSON) to null.

    ⚠️ **A warm cache hit hands back a plain dict, not a `t33.Config`** — which is why this dispatches
    on *shape* (`__dict__`, `tolist`, `item`) and never on `hasattr(cfg, "t27_config")`. Keying it on
    the type made it a no-op on every cached build, which is the common case.

    Kept dependency-free on purpose: v1 had three copies of this (project, engine, export) precisely
    because nobody wanted to import numpy, CuPy and spectralign in order to write a JSON file. This is
    the one. Do not write a fourth.
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        if isinstance(obj, float) and not math.isfinite(obj):
            return None                                  # NaN/inf are not JSON
        return obj
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [jsonable(v) for v in obj]
    if hasattr(obj, "tolist"):                           # np.ndarray, np.float64, np.int64
        return jsonable(obj.tolist())
    if hasattr(obj, "item") and not hasattr(obj, "__dict__"):
        try:
            return jsonable(obj.item())
        except Exception:                                # noqa: BLE001 — a best-effort coercion
            pass
    if hasattr(obj, "__dict__"):                         # t27.Config / t33.Config / dataclasses
        return jsonable(vars(obj))
    return str(obj)


# =================================================================================================
# The workspace — the ONE writer, the ONE path guard.  (Lazily imported; see `_workspace`.)
# =================================================================================================
_WORKSPACE_API = ("refuse_write", "atomic_write_text", "dumps")


def _workspace():
    """`camea.core.workspace`. Imported lazily, for two reasons that are both real:

    * *reading* or *validating* a document must not need the filesystem layer at all — the API
      validates request bodies that never touch disk;
    * it keeps the dependency one-way at import time. `workspace` writes what `document` hands it and
      does not import back; a lazy import means it never can, even by accident.
    """
    from camea.core import workspace  # noqa: PLC0415 — deliberate; see the docstring
    missing = [n for n in _WORKSPACE_API if not callable(getattr(workspace, n, None))]
    if missing:
        raise DocumentError(
            f"camea.core.workspace is missing {missing} — core.document keeps no writer and no path "
            f"guard of its own (it needs: {list(_WORKSPACE_API)}).")
    return workspace


# =================================================================================================
# Scope — what a document COVERS
# =================================================================================================
@dataclass(frozen=True)
class Scope:
    """**What this document is about**, in the two terms core understands plus one the feature owns.

    `identity` is the feature's slot *within* the dataset — for the mosaic it is its trial range
    (`"11-348"`). Core never parses it; it only ever compares it for equality. That is enough to make
    the load-time range guard work for a feature core has never heard of.

    ⚠️ `dataset_key` (basename + sha1 of the *resolved* directory) is the real identity: two folders
    with the same basename under different parents must not be mistaken for each other. `dataset` is
    the human-readable name and is compared only as a fallback.
    """

    dataset: str = ""
    dataset_key: str = ""
    identity: str = ""

    def agrees_with(self, other: Scope) -> bool:
        """Do these describe the same work? **Blanks abstain.** A document that predates a field must
        still open, and a guard that fires on a missing field is a guard the user learns to route
        around."""
        if self.dataset_key and other.dataset_key and self.dataset_key != other.dataset_key:
            return False
        if self.dataset and other.dataset and self.dataset != other.dataset:
            return False
        if self.identity and other.identity and self.identity != other.identity:
            return False
        return True

    def describe(self) -> str:
        bits = [self.dataset or self.dataset_key or "?"]
        if self.identity:
            bits.append(f"({self.identity})")
        return " ".join(bits)


# =================================================================================================
# The feature boundary
# =================================================================================================
#: `(kind, message)`. `kind` is one of:
#:   "hard"    — `normalise()`/`stamp()` CANNOT fix it. Refuse the document.
#:   "derived" — a field normalise/stamp recomputes. Repair it; never reject the save for it.
#:   "warn"    — worth saying. Never blocks a write.
#:
#: ⚠️ The hard/derived line is load-bearing. The derived fields are *exactly* the ones that drift the
#: moment the user excludes a record — and `normalise()` is what repairs them. Validating them BEFORE
#: normalising rejects a perfectly good document for drift the very next line of code fixes.
Problem = tuple[str, str]

_KINDS = ("hard", "derived", "warn")


@runtime_checkable
class FeatureHooks(Protocol):
    """What a feature must teach core about its payload.

    Every method is optional **except `machine_evidence`**, which is the one thing core may not
    delegate away and may not skip.
    """

    def machine_evidence(self, doc: dict) -> dict | None:
        """⭐ **WAS THIS DOCUMENT EVER TOUCHED BY A MACHINE?** -> a `seeded_from` block, or None.

        Answer from the document's **HISTORY** — a build block, a record still carrying the solver's
        answer — and **never** from `provenance.seeded_from`, which is writable and has been erased.
        Return at least `method`; add `build_id` / `config` / `detected_from` if you have them.
        `detected_from` is the *evidence*, and the user is shown it.
        """
        ...

    # ---- optional --------------------------------------------------------------------------------
    def normalise(self, doc: dict) -> dict:
        """Repair the payload's derived fields. -> a new document. Must not touch the envelope."""

    def validate(self, doc: dict) -> list[Problem]:
        """Payload problems, as `(kind, message)`. See `Problem`."""

    def migrate(self, doc: dict) -> tuple[dict, list[str]]:
        """Bring an older payload up to date **without losing a key**. -> (doc, warnings)."""

    def human_edits(self, doc: dict) -> dict:
        """The honest record of what the human actually did -> `provenance.human_edits`.
        **Every number states its denominator**, and a contaminated number says so *next to the number
        it contaminates*."""

    def identity(self, doc: dict) -> str:
        """This document's slot within its dataset — the mosaic's `"11-348"`. Used by the range guard.
        `""` if the feature has no such notion."""

    def counts(self, doc: dict) -> dict:
        """The numbers on the browser card, e.g. `{"n_tiles", "n_anchored", "n_excluded"}`. Any
        subset. Forwarded to `core.workspace`, which lists analyses without knowing what a tile is."""

    def new_payload(self, doc: dict, **kwargs: Any) -> dict:
        """Add the feature's keys to a fresh envelope, **FLAT**. -> the whole document."""


_FEATURES: dict[str, FeatureHooks] = {}
_FEATURES_LOCK = threading.Lock()


def register_feature(name: str, hooks: FeatureHooks) -> None:
    """Teach core about a feature's payload. Called once, at the feature package's import.

    ⭐ **THIS IS THE ONE REGISTRATION POINT.** It also forwards `counts` and `machine_evidence` to
    `core.workspace`'s own registry, which the dataset browser reads. Registering in two places is
    how one of them silently ends up empty — and the one that would have gone quiet is the browser
    card's `independent_of_method`, i.e. the flag that stops a machine-seeded document being mistaken
    for a truth.
    """
    if not name:
        raise DocumentError("a feature must have a name")
    if not callable(getattr(hooks, "machine_evidence", None)):
        raise DocumentError(
            f"feature {name!r} must implement `machine_evidence(doc)`. It is not optional: without "
            "it the provenance verdict cannot be derived, and the default a missing hook would imply "
            "— 'this is an independent ground truth' — is the single most expensive wrong answer in "
            "this project's history.")
    with _FEATURES_LOCK:
        _FEATURES[name] = hooks

    from camea.core import workspace  # noqa: PLC0415 — see the docstring
    workspace.register_feature(
        name,
        counts=_hook(hooks, "counts"),
        machine_evidence=hooks.machine_evidence,
    )


def registered_features() -> list[str]:
    with _FEATURES_LOCK:
        return sorted(_FEATURES)


def hooks_for(doc_or_feature: dict | str) -> FeatureHooks:
    """The hooks for a document (or a bare feature name). Raises `UnknownFeature` — see the class."""
    feature = (doc_or_feature if isinstance(doc_or_feature, str)
               else (doc_or_feature or {}).get("feature"))
    with _FEATURES_LOCK:
        hooks = _FEATURES.get(feature or "")
    if hooks is None:
        raise UnknownFeature(
            f"no feature is registered under {feature!r} (registered: {registered_features()}). "
            "This document cannot be stamped, because its provenance verdict cannot be derived — and "
            "assuming it is an independent ground truth is exactly how a machine build gets laundered "
            "into one.")
    return hooks


def _hook(hooks: FeatureHooks, name: str):
    """An optional hook, or None. `machine_evidence` is never optional and is never fetched here."""
    fn = getattr(hooks, name, None)
    return fn if callable(fn) else None


def _resolve(doc: dict, hooks: FeatureHooks | None) -> FeatureHooks:
    return hooks if hooks is not None else hooks_for(doc)


# =================================================================================================
# The envelope
# =================================================================================================
def new_envelope(*, feature: str, id: str = "", dataset: str = "", dataset_key: str = "",
                 data_dir: str = "", experiment: str = "", name: str = "",
                 app_version: str | None = None) -> dict:
    """A fresh, empty envelope. No payload — that is the feature's (see `new_document`).

    ⭐ **`id` MUST BE THE WORKSPACE'S `analysis_id`** when the document is going to live in the
    workspace: `workspace._guard_slot` refuses any document whose `id` is not the analysis it is being
    written into, and that guard is what makes v1's slot collision impossible rather than unlikely.
    Create the analysis first (`Workspace.create_analysis`), then pass its id here. A minted uuid is
    for a document with no workspace behind it.

    `experiment` is the acquisition's own name (log.txt's `New experiment:`), which may differ from
    the folder's. It is recorded because a directory label can lie about which acquisition this is.
    **Nothing branches on it.**
    """
    now = iso_now()
    version = app_version or camea.__version__
    doc = {
        "schema_version": SCHEMA_VERSION,
        "app": {"name": APP_NAME, "version": version},
        "id": id or uuid.uuid4().hex,
        "feature": feature,
        "dataset": dataset or "",
        "experiment": experiment or "",
        "data_dir": data_dir or "",
        "dataset_key": dataset_key or "",
        "created": now,
        "modified": now,
        "provenance": {
            "authored_by": APP_NAME,
            "app_version": version,
            "workflow": WORKFLOW_HAND,
            "seeded_from": None,
            "independent_of_method": True,     # nothing has seeded it yet. `stamp()` re-derives it.
            "human_edits": {},
            "scale": {"um_per_px": None, "source": "unknown"},
        },
    }
    if name:
        doc["name"] = name
    return doc


def new_document(*, feature: str, hooks: FeatureHooks | None = None, id: str = "",
                 dataset: str = "", dataset_key: str = "", data_dir: str = "", experiment: str = "",
                 name: str = "", app_version: str | None = None, **payload: Any) -> dict:
    """⭐ **THE SERVER CREATES THE DOCUMENT.** Envelope (core) + payload (the feature's hook).

    🔴 In v1 `new_doc()` and `seed_from_build()` were **dead code** — the front end reimplemented both
    in JS. That is how `human_edits`' divert counters were silently dropped on every save, and how
    *"Skip — place by hand"* could erase `seeded_from` while every record still sat exactly where the
    solver put it. Authoring the document in the browser is not a design; it is the hole. It is closed
    here, and it stays closed.
    """
    hooks = hooks if hooks is not None else hooks_for(feature)
    doc = new_envelope(feature=feature, id=id, dataset=dataset, dataset_key=dataset_key,
                       data_dir=data_dir, experiment=experiment, name=name, app_version=app_version)
    seed = _hook(hooks, "new_payload")
    if seed is not None:
        doc = seed(doc, **payload)
    elif payload:
        raise DocumentError(
            f"feature {feature!r} has no `new_payload` hook but was given {list(payload)}")
    return stamp(normalise(doc, hooks), hooks, app_version)


def scope_of(doc: dict, hooks: FeatureHooks | None = None) -> Scope:
    """What this document covers. The `identity` half is the feature's — see `FeatureHooks.identity`."""
    ident = ""
    try:
        h: FeatureHooks | None = _resolve(doc, hooks)
    except UnknownFeature:
        h = None                                    # a scope is still readable without hooks
    if h is not None:
        fn = _hook(h, "identity")
        if fn is not None:
            ident = str(fn(doc) or "")
    return Scope(dataset=str(doc.get("dataset") or ""),
                 dataset_key=str(doc.get("dataset_key") or ""),
                 identity=ident)


# =================================================================================================
# stamp — ⚠️ THE PROVENANCE IS NOT DECORATION
# =================================================================================================
def machine_evidence(doc: dict, hooks: FeatureHooks | None = None) -> dict | None:
    """⭐ **WAS THIS DOCUMENT EVER TOUCHED BY A MACHINE BUILD?** -> a `seeded_from` block, or None.

    Core asks two questions, and the feature answers the second:

      1. does `provenance.seeded_from` already say so?  — a *claim*. Necessary, never sufficient.
      2. does the feature find machine evidence in the payload?  — the *history*. The real answer.

    🔴 **THE HOLE THIS CLOSES.** v1's `stamp()` derived the entire verdict from question 1 — a field
    the FRONT END writes and can therefore erase. And it did: *"Skip — place from scratch"* nulled the
    build, nulled `seeded_from`, set `independent_of_method: true` and DELETED the warning —
    **without touching a single record.** Every tile kept t33's position and t33's answer. Score t33
    against that document and it gets ~100 % **by construction**. That is the exact mechanism that
    already destroyed `analysis/archive/challenge_2026-07/benchmark/ground_truth/260620d.json`, which
    is T27's own output.
    """
    hooks = _resolve(doc, hooks)
    prov = doc.get("provenance") or {}
    claimed = prov.get("seeded_from")
    if claimed:
        return dict(claimed)
    found = hooks.machine_evidence(doc)              # ⭐ the history, not the self-declaration
    return dict(found) if found else None


def stamp(doc: dict, hooks: FeatureHooks | None = None, app_version: str | None = None) -> dict:
    """⚠️ **STAMP THE PROVENANCE. THIS IS NOT DECORATION.** Called on every save and every export.

    Pass 1's ground truth got tiles **128/129/130/148 wrong** *precisely because* it was seeded from a
    build and the human deferred to it — caught only because pass 2 was later authored blind. A
    verification UI that shows the machine's answer and invites a human to click "accept" is
    structurally that same hazard.

      * ANY machine evidence  =>  `independent_of_method: false` AND the `warning`, **verbatim**.
      * No evidence anywhere  =>  `independent_of_method: true`, and the warning is **omitted**.
        That document *is* an honest truth, and a warning that cries wolf is one nobody reads.

    The verdict is derived from the document's history (`machine_evidence`), never from what the
    document says about itself. **No feature may opt out. There is no flag.**

    ⚠️ It assumes a structurally sound payload — it asks the feature a question about it. `prepare()`
    is what guarantees that, by running `structural_problems()` first. Do not call `stamp()` on an
    unvalidated document off the wire.
    """
    hooks = _resolve(doc, hooks)
    version = app_version or camea.__version__
    doc = copy.deepcopy(doc)

    prov = dict(doc.get("provenance") or {})
    prov.setdefault("authored_by", APP_NAME)
    prov["app_version"] = version

    seeded = machine_evidence(doc, hooks)
    if seeded:
        prov["seeded_from"] = seeded
        prov["workflow"] = WORKFLOW_SEEDED
        prov["independent_of_method"] = False
        prov["warning"] = PROVENANCE_WARNING             # verbatim. Never paraphrased.
    else:
        prov["seeded_from"] = None
        prov["workflow"] = WORKFLOW_HAND
        prov["independent_of_method"] = True
        prov.pop("warning", None)                        # an honest truth carries no warning
    prov.setdefault("scale", {"um_per_px": None, "source": "unknown"})

    edits = _hook(hooks, "human_edits")
    prov["human_edits"] = dict(edits(doc)) if edits is not None else (prov.get("human_edits") or {})

    doc["provenance"] = prov
    doc["app"] = {"name": APP_NAME, "version": version}
    doc["schema_version"] = SCHEMA_VERSION
    doc["modified"] = iso_now()
    doc.setdefault("created", doc["modified"])
    doc.setdefault("id", uuid.uuid4().hex)
    for key in ("dataset", "experiment", "data_dir", "dataset_key"):
        doc.setdefault(key, "")
    return doc


def normalise(doc: dict, hooks: FeatureHooks | None = None) -> dict:
    """Repair the derived fields. Core has none of its own — every one of them belongs to the feature
    — so this is a pure delegation. It exists so that the save ORDER lives in exactly one place."""
    hooks = _resolve(doc, hooks)
    fn = _hook(hooks, "normalise")
    return fn(copy.deepcopy(doc)) if fn is not None else copy.deepcopy(doc)


# =================================================================================================
# validate
# =================================================================================================
def _envelope_problems(doc: Any, expect: Scope | None = None) -> list[Problem]:
    """The generic half: is this a Camea document at all, does it know what it is, and is it for the
    session it is being opened into? The payload half is the feature's.

    ⛔ **NOTHING HERE MAY REJECT A DOCUMENT FOR *WHAT* IT PLACED.** No id is special; no dataset is
    known. A save that refuses the user's own work is a bug, not a guard.
    """
    p: list[Problem] = []
    if not isinstance(doc, dict):
        return [("hard", "the document is not a JSON object")]

    if not doc.get("feature"):
        p.append(("hard", "missing required key 'feature' — core routes the payload on it"))
    if "dataset" not in doc:
        p.append(("hard", "missing required key 'dataset'"))

    if doc.get("schema_version") != SCHEMA_VERSION:
        p.append(("derived", f"schema_version is {doc.get('schema_version')!r}, "
                             f"expected {SCHEMA_VERSION!r}"))
    for key in ("id", "app", "created", "modified", "provenance"):
        if key not in doc:
            p.append(("derived", f"missing required key {key!r} (recomputed on save)"))

    if expect is not None:
        got = Scope(dataset=str(doc.get("dataset") or ""),
                    dataset_key=str(doc.get("dataset_key") or ""))
        want = Scope(dataset=expect.dataset, dataset_key=expect.dataset_key)
        if not got.agrees_with(want):
            p.append(("hard", f"this document is for {got.describe()}; "
                              f"the open session is {want.describe()}"))
    return p


def _provenance_problems(doc: dict, hooks: FeatureHooks) -> list[Problem]:
    """⭐ The five cross-checks that stop a document lying about where it came from.

    They are `derived`, not `hard`, on purpose: `stamp()` repairs every one of them and it runs on the
    way to disk. They are here so that a document reaching us from *anywhere else* — a hand edit, an
    old file, another tool — is caught rather than trusted.
    """
    p: list[Problem] = []
    prov = doc.get("provenance")
    if not isinstance(prov, dict):
        return [("derived", "provenance is missing — it is MANDATORY and it is not decoration")]

    for key in ("authored_by", "workflow", "seeded_from", "independent_of_method"):
        if key not in prov:
            p.append(("derived", f"provenance.{key} is missing"))

    ev = machine_evidence(doc, hooks)
    seeded = ev is not None
    if seeded and prov.get("seeded_from") is None:
        p.append(("derived",
                  "provenance.seeded_from is null, but this document IS machine-seeded: "
                  f"{(ev or {}).get('detected_from')}. A document that claims to be an independent "
                  "ground truth while every position started as a solver's output scores that solver "
                  "~100 % BY CONSTRUCTION. This project has already destroyed one benchmark exactly "
                  "this way."))
    if seeded and prov.get("independent_of_method") is not False:
        p.append(("derived", "provenance.independent_of_method must be FALSE when the document was "
                             "seeded from a machine build — it must never be used to score the method "
                             "that produced it"))
    if seeded and prov.get("warning") != PROVENANCE_WARNING:
        p.append(("derived", "provenance.warning is REQUIRED, verbatim, when the document was seeded "
                             "from a machine build"))
    if not seeded and prov.get("independent_of_method") is not True:
        p.append(("derived", "provenance.independent_of_method must be TRUE when nothing in the "
                             "document came from a machine build"))
    if not seeded and prov.get("warning"):
        p.append(("derived", "provenance.warning must be OMITTED when the document is independent of "
                             "any method — a warning that cries wolf is a warning nobody reads"))
    return p


def problems(doc: Any, hooks: FeatureHooks | None = None,
             expect: Scope | None = None) -> list[Problem]:
    """Every problem, as `(kind, message)`: core's envelope, then the payload's, then the provenance.

    ⚠️ **THE PAYLOAD IS CHECKED BEFORE THE PROVENANCE, AND THE ORDER IS NOT COSMETIC.** The provenance
    cross-checks *ask the feature* whether a machine touched its payload — and a feature cannot answer
    that about a payload that is not even the right shape. v1 got this right by accident: its `tiles`
    check `return`ed early, above the provenance block. Split apart, the accident is gone and the
    ordering has to be deliberate, or a malformed payload raises an `AttributeError` **inside a
    feature hook** and the API serves a 500 where it owes the user a 400.
    """
    p = _envelope_problems(doc, expect)
    if any(kind == "hard" and "'feature'" in msg for kind, msg in p):
        return p                                        # we cannot even ask the feature
    hooks = _resolve(doc, hooks)

    if expect is not None and expect.identity:
        got = scope_of(doc, hooks)
        if got.identity and got.identity != expect.identity:
            p.append(("hard", f"this document covers {got.identity}; "
                              f"the open session is {expect.identity}"))

    payload: list[Problem] = []
    fn = _hook(hooks, "validate")
    if fn is not None:
        for kind, msg in fn(doc):
            if kind not in _KINDS:
                raise DocumentError(f"feature {doc.get('feature')!r} returned an unknown problem "
                                    f"kind {kind!r}; expected one of {_KINDS}")
            payload.append((kind, msg))
    p += payload
    if any(kind == "hard" for kind, _ in payload):
        return p                                        # do not ask the feature the impossible

    p += _provenance_problems(doc, hooks)
    return p


def validate(doc: Any, hooks: FeatureHooks | None = None,
             expect: Scope | None = None) -> list[str]:
    """-> human-readable problems ([] = valid). Warnings are excluded: they never block a write.

    ⚠️ `jsonschema` is not a dependency, and that is no loss — the interesting invariants are ones a
    JSON Schema cannot express anyway. Above all: *the provenance verdict matches the history*. That
    is an ERROR, not a note.
    """
    return [m for kind, m in problems(doc, hooks, expect) if kind != "warn"]


def structural_problems(doc: Any, hooks: FeatureHooks | None = None) -> list[str]:
    """The problems `normalise()` + `stamp()` CANNOT fix.

    Everything else is DERIVED, and normalise/stamp recompute it. Rejecting a save for that drift
    would reject a perfectly good document — the drift is *expected*: it is exactly what happens the
    moment the user excludes a record or anchors an earlier one.

    ⛔ **Nothing here may reject a document for WHAT it placed.**
    """
    return [m for kind, m in problems(doc, hooks) if kind == "hard"]


def report(doc: Any, hooks: FeatureHooks | None = None,
           expect: Scope | None = None) -> list[dict]:
    """`problems()` as the API's `DocumentProblem[]`: `{kind, message, severity}`."""
    return [{"kind": kind, "message": msg, "severity": "warning" if kind == "warn" else "error"}
            for kind, msg in problems(doc, hooks, expect)]


# =================================================================================================
# prepare — ⭐ THE ORDER. It lives here, once, and every writer goes through it.
# =================================================================================================
def prepare(doc: dict, hooks: FeatureHooks | None = None,
            app_version: str | None = None) -> dict:
    """**structural-validate -> normalise -> stamp -> full-validate.** -> the document to write.
    Raises `ValidationError` (-> 400).

    ⚠️ **THE ORDER IS THE POINT, AND IT IS NOT `validate -> normalise`.** The derived fields are
    *exactly the ones that drift* when the user excludes a record or anchors an earlier one — and
    `normalise()` is what repairs them. Validating them first would reject a perfectly good document
    for drift the very next line of code fixes. So: check only what normalise/stamp **cannot** fix,
    repair, stamp, and then run the FULL validation as a **post-condition**. **Never write a broken
    file.**

    ⛔ It does **not** take a session. The document is the sole authority on what it excluded, and the
    session never overrides it: the session-aware check is a LOAD-time guard, and running it here
    would turn a legitimate range change into a hard 400 on the next 2-second autosave.
    """
    hooks = _resolve(doc, hooks)

    problems_ = structural_problems(doc, hooks)
    if problems_:
        raise ValidationError(problems_)

    out = stamp(normalise(doc, hooks), hooks, app_version)

    problems_ = validate(out, hooks)                     # post-condition: never write a broken file
    if problems_:
        raise ValidationError(problems_)
    return out


# =================================================================================================
# save / load / autosave
# =================================================================================================
def save(path: str | Path, doc: dict, hooks: FeatureHooks | None = None,
         app_version: str | None = None) -> dict:
    """**`Save…`** — the document, to a file the USER named. -> `{"path", "bytes", "saved_at", "doc"}`.

    Reachable from every screen (BEHAVIOUR R5): since the app carries no dataset knowledge, this file
    is its *only* memory, and burying it behind the last step meant the one artefact that makes a
    session resumable was the one thing he could not reach mid-session.

    ⛔ Refused inside `data/`, inside the repo, or inside the dataset — `workspace.refuse_write` is the
    one guard (v1 had three, and they had drifted).
    """
    ws = _workspace()
    out = prepare(doc, hooks, app_version)

    path = Path(path)
    ws.refuse_write(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = ws.dumps(jsonable(out))
    ws.atomic_write_text(path, text)
    return {"path": str(path).replace("\\", "/"),
            "bytes": len(text.encode("utf-8")),
            "saved_at": out["modified"],
            "warnings": [],
            "doc": out}


def save_analysis(ws: Workspace, analysis_id: str, doc: dict, hooks: FeatureHooks | None = None,
                  app_version: str | None = None) -> dict:
    """The document, into its analysis in the workspace. -> `api.schemas.SaveResult` + `doc`.

    The slot guard is the workspace's (`_guard_slot`): a document may only be written into the analysis
    whose `id` it carries. That is why `new_document(id=...)` must be given the `analysis_id`.
    """
    out = prepare(doc, hooks, app_version)
    res = dict(ws.save_document(analysis_id, jsonable(out)))
    res["doc"] = out
    return res


def autosave(ws: Workspace, analysis_id: str, doc: dict, hooks: FeatureHooks | None = None,
             app_version: str | None = None) -> dict:
    """The crash net. Debounced 2 s by the front end, **plus unconditionally on every `A`/`E`**.

    ⚠️ **AUTOSAVE IS A CRASH NET, NOT A SUBSTITUTE FOR SAVING.** It writes `autosave.camea.json`
    *beside* the document and never over it — recovery must be able to show the user both and let him
    choose. `save()` writes the file he named, where he can find it. The UI must never let one read as
    the other.

    🔴 **A FAILURE IS LOUD.** It raises, and the route must not swallow it. (v1's browser-side
    `localStorage` fallback failed *silently* in the sandbox and nearly cost a day's work — which is
    why the crash net is a server file at all.)

    ⚠️ It deliberately does **not** structural-validate: it saves what it can, mid-sweep, on a document
    the user has not finished. `normalise`+`stamp` still run — an autosave that is not stamped is an
    unmarked machine-seeded document sitting on disk.
    """
    hooks = _resolve(doc, hooks)
    out = stamp(normalise(doc, hooks), hooks, app_version)
    res = dict(ws.autosave(analysis_id, jsonable(out)))
    res["doc"] = out
    return res


def load(path: str | Path, hooks: FeatureHooks | None = None,
         expect: Scope | None = None) -> tuple[dict, list[str]]:
    """-> `(doc, warnings)`. Migrates an older document; **never loses a key**.

    ⭐ **THIS FILE IS THE APP'S ONLY MEMORY.** The app itself remembers nothing between sessions — no
    exclusions, no rulings, no per-dataset special cases. So whatever this file says is excluded *is*
    excluded, and nothing else is. `save()` -> quit -> `load()` restores the session whole.

    ⚠️ **GUARDS THE SCOPE.** If `expect` is given and the document is for a different dataset or a
    different range, **raises `RangeMismatch`** (-> 409). Pass 2's autosave once silently overwrote
    pass 1's ground-truth records. Do not re-open that hole.

    ⚠️ **UNKNOWN KEYS ARE PRESERVED VERBATIM**, at the top level and (via the feature) per record. A
    lossy round-trip quietly destroys a hand-written note — and this file is also somebody's ground
    truth.
    """
    path = Path(path)
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise DocumentError(f"{path} is not a Camea document (the JSON root is not an object)")

    doc, warnings = _migrate_envelope(doc)
    hooks = _resolve(doc, hooks)

    migrate = _hook(hooks, "migrate")
    if migrate is not None:
        doc, more = migrate(doc)
        warnings += list(more)

    # ⚠️ THE GUARD. Before anything else touches this document.
    if expect is not None:
        got = scope_of(doc, hooks)
        if not got.agrees_with(expect):
            raise RangeMismatch(f"this document is for {got.describe()}; "
                                f"the open session is {expect.describe()}")

    problems_ = structural_problems(doc, hooks)
    if problems_:
        raise ValidationError(problems_)

    doc = normalise(doc, hooks)                     # repairs the derived fields, flags staleness
    warnings += [f"validation: {m}" for m in validate(doc, hooks, expect)]
    return doc, warnings


def load_analysis(ws: Workspace, analysis_id: str, hooks: FeatureHooks | None = None,
                  expect: Scope | None = None, *, recovered: bool = False) -> tuple[dict, list[str]]:
    """The analysis's document from the workspace. `recovered=True` reads the **autosave** instead.

    The Load screen asks `Workspace.recovery(analysis_id)` first: an autosave *newer* than the document
    is a recovery prompt, and the user chooses. An older one is noise.
    """
    path = ws.autosave_path(analysis_id) if recovered else ws.document_path(analysis_id)
    return load(path, hooks, expect)


def _migrate_envelope(doc: dict) -> tuple[dict, list[str]]:
    """Bring an older envelope up to `camea-document-1.0` **WITHOUT LOSING A KEY**.

    Everything it does not name, it does not touch — including the whole feature payload. That is why
    a v1 project file and a hand-authored ground truth both open unchanged.
    """
    doc = copy.deepcopy(doc)
    w: list[str] = []

    sv = doc.get("schema_version")
    if sv is None:
        w.append("no schema_version — treating this as a document written before the app existed.")
    elif sv != SCHEMA_VERSION:
        if sv in LEGACY_SCHEMA_VERSIONS:
            w.append(f"schema_version {sv!r} -> {SCHEMA_VERSION!r}")
        else:
            w.append(f"schema_version {sv!r} is not one this app has ever written "
                     f"({(SCHEMA_VERSION, *LEGACY_SCHEMA_VERSIONS)}) — opening it anyway, and keeping "
                     f"every key it carries.")
    doc["schema_version"] = SCHEMA_VERSION

    # ⚠️ THE LEGACY FEATURE. v1's documents — and the hand-authored ground truths, which predate the
    # app — carry no `feature` key, because there was only ever one. Defaulting is FORMAT knowledge
    # (what a `camea-project-1.0` file *is*), not dataset knowledge, and it is the only reason those
    # files still open. Anything else without a `feature` is not a Camea document, and we say so
    # rather than guess: guessing is how a payload reaches the wrong feature's hooks.
    if not doc.get("feature"):
        legacy = sv in LEGACY_SCHEMA_VERSIONS or isinstance(doc.get("tiles"), dict)
        if not legacy:
            raise DocumentError(
                "this document has no `feature` and does not look like anything any version of this "
                "app has written. Refusing to guess which feature it belongs to.")
        doc["feature"] = LEGACY_FEATURE
        w.append(f"no `feature` key — this predates the split; recording it as {LEGACY_FEATURE!r}.")

    if not doc.get("id"):
        doc["id"] = uuid.uuid4().hex
        w.append("no `id` — minted one. It is stable from now on.")
    for key in ("dataset", "experiment", "data_dir", "dataset_key"):
        doc.setdefault(key, "")
    doc.setdefault("created", iso_now())
    doc.setdefault("modified", doc["created"])
    doc.setdefault("app", {"name": APP_NAME, "version": camea.__version__})

    if not isinstance(doc.get("provenance"), dict):
        doc["provenance"] = {"authored_by": doc.get("authored_by", "unknown"),
                             "workflow": WORKFLOW_HAND,
                             "seeded_from": None,
                             "independent_of_method": True}
        w.append("no provenance block — assuming hand placement (seeded_from: null). ⚠️ `stamp()` "
                 "re-derives this from the document's HISTORY on the way back out: if anything in it "
                 "came from a machine, it will say so, whatever this block claims.")
    return doc, w


# =================================================================================================
# DocumentStore — which documents are open, and where each came from
# =================================================================================================
# v1 kept "which file is open" in a module-level `PROJECT_PATH` on the FastAPI server (server.py:75).
# That is generic state living on the core server, and it can only ever hold ONE. Two features open on
# one dataset — or two mosaics on one dataset, which is legal — need two.

@dataclass
class OpenDocument:
    """An open document and where it came from. `path` is None until it is saved somewhere named."""

    id: str
    feature: str
    doc: dict
    path: str | None = None
    dataset_key: str = ""
    opened_at: str = field(default_factory=iso_now)


class DocumentStore:
    """The open documents, keyed by `id`. Thread-safe: the API serves requests from a thread pool."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._open: dict[str, OpenDocument] = {}

    def put(self, doc: dict, path: str | Path | None = None) -> OpenDocument:
        entry = OpenDocument(id=str(doc["id"]), feature=str(doc["feature"]), doc=doc,
                             path=(str(path).replace("\\", "/") if path else None),
                             dataset_key=str(doc.get("dataset_key") or ""))
        with self._lock:
            existing = self._open.get(entry.id)
            if existing is not None:                     # a re-put keeps the identity it opened with
                entry.opened_at = existing.opened_at
                entry.path = entry.path or existing.path
            self._open[entry.id] = entry
        return entry

    def get(self, doc_id: str) -> OpenDocument:
        with self._lock:
            entry = self._open.get(doc_id)
        if entry is None:
            raise DocumentError(f"no document {doc_id!r} is open")
        return entry

    def list(self) -> list[OpenDocument]:
        with self._lock:
            return list(self._open.values())

    def close(self, doc_id: str) -> None:
        with self._lock:
            self._open.pop(doc_id, None)

    def clear(self) -> None:
        with self._lock:
            self._open.clear()


#: One store, module-level. (`_FEATURES` is likewise one — features register at import.)
DOCUMENTS = DocumentStore()
