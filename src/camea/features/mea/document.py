"""The `mea` document — the shelf, and the two provenance answers that had to be argued for.

Payload (FLAT beside the envelope, like every feature — `core.document` §3):

    recordings: []   one entry per imported `.h5`. **Empty at creation, and that is the
                     ordinary state**: he names the project, picks the task, and *then* puts
                     recordings on it ("you create the project, you pick Analyze MEA, and you
                     go into the project, you can add however many H5 files you want").

⭐ **THERE IS NO `source` KEY, AND THAT IS DELIBERATE.** `videomosaic` has one because a video
project *is* a wrapper around one file, probed at create time. This project is a **shelf**, and
a shelf has no single source — asking for the first `.h5` during creation was explicitly
rejected in the interview. Plan 001 § Approach guessed at "an empty `source`" by analogy with
the video feature; `recordings: []` is the same emptiness with the right name on it, and it is
the block plan 002 grows into rather than one it has to migrate away from.

---------------------------------------------------------------------------------------------
THE TWO ANSWERS CORE ASKS EVERY FEATURE FOR, AND WHY THIS ONE ANSWERS THEM THE WAY IT DOES
---------------------------------------------------------------------------------------------

1. ⭐ **`machine_evidence` -> None, always.** Core forces `independent_of_method: false` and
   attaches `PROVENANCE_WARNING` to any document a machine build ever touched, because a
   human-confirmed machine placement scores that method ~100 % by construction and this
   project has already destroyed one benchmark exactly that way. **None of that mechanism
   applies here, because this feature places nothing.** There is no solver, no position, no
   "accept the machine's answer" gesture — the spikes are MaxWell's own detections read off
   the file, and Camea neither produces them nor invites a human to confirm them. A warning
   attached to a document that carries no machine placement is a warning that cries wolf, and
   `stamp()` says in as many words that those are the ones nobody reads.

   ⚠️ **This is the answer for as long as this feature only READS.** The moment something here
   proposes a number a human is invited to confirm — a pairing, a seating, a sorted unit — this
   hook must start finding it in the payload. It is not optional and there is no flag; see
   `core.document.FeatureHooks.machine_evidence`.

2. **`counts` -> {}.** `n_tiles` / `n_anchored` / `n_excluded` are sweep words. This project
   has no tiles and anchors nothing, so it reports none of them and the home-screen card shows
   no count rather than a zero that would read as "nothing done yet". (`read_analysis` leaves
   them `None`, and `ProjectCard` already renders that as absent.)

`identity` is `""` for the same reason the mosaic's is `"11-348"`: it is the feature's slot
*within* a dataset, used by the load-time range guard. An MEA project has no dataset and no
range, so it abstains — and `Scope.agrees_with` treats a blank as "no opinion", which is
exactly right.
"""

from __future__ import annotations

from typing import Any

from ...core import document as core
from ...core.document import Problem

FEATURE = "mea"


def new_payload(doc: dict, **kwargs: Any) -> dict:
    """A fresh `mea` payload: an empty shelf.

    ⛔ Takes no arguments and wants none. Creating one of these asks the user for a name and
    nothing else — no path, no probe, no folder (R44) — so there is nothing to seed it from.
    """
    if kwargs:
        raise core.DocumentError(
            f"a mea document is created empty; it was given {sorted(kwargs)}. Recordings are "
            "added to the project afterwards, not at creation."
        )
    doc["recordings"] = []
    return doc


def machine_evidence(doc: dict) -> dict | None:
    """⭐ **Nothing in an `mea` document ever came from a machine build.** See the module
    docstring, point 1 — this is an argued answer, not a stub."""
    return None


def normalise(doc: dict) -> dict:
    """Nothing derived is stored twice in this payload — normalise only tidies types."""
    out = dict(doc)
    recs = doc.get("recordings")
    out["recordings"] = list(recs) if isinstance(recs, list) else []
    return out


def validate(doc: dict) -> list[Problem]:
    """The one structural claim this payload makes: `recordings` is a list of objects.

    ⛔ It says nothing about what is *in* a recording. Nothing here knows a plate, a run, a
    channel count or an expected spike rate (I1 / no dataset knowledge) — and a document that
    refused to open because a recording carried a key this build has not heard of would be the
    lossy round-trip `core.document` exists to prevent.
    """
    problems: list[Problem] = []
    recs = doc.get("recordings")
    if not isinstance(recs, list):
        problems.append(("hard", "recordings: must be a list"))
        return problems
    for i, rec in enumerate(recs):
        if not isinstance(rec, dict):
            problems.append(("hard", f"recordings[{i}]: not a recording record"))
            break
    return problems


def counts(doc: dict) -> dict:
    """No tiles, no anchors, nothing excluded — see the module docstring, point 2."""
    return {}


def identity(doc: dict) -> str:
    """No dataset, so no slot within one."""
    return ""


class MeaHooks:
    """Thin delegations, one instance, registered at import — the `VideoMosaicHooks` pattern."""

    name = FEATURE

    def machine_evidence(self, doc: dict) -> dict | None:
        return machine_evidence(doc)

    def normalise(self, doc: dict) -> dict:
        return normalise(doc)

    def validate(self, doc: dict) -> list[Problem]:
        return validate(doc)

    def counts(self, doc: dict) -> dict:
        return counts(doc)

    def identity(self, doc: dict) -> str:
        return identity(doc)

    def new_payload(self, doc: dict, **kwargs: Any) -> dict:
        return new_payload(doc, **kwargs)


HOOKS = MeaHooks()
core.register_feature(FEATURE, HOOKS)
