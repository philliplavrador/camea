"""The `mea` document — the shelf, and the two provenance answers that had to be argued for.

Payload (FLAT beside the envelope, like every feature — `core.document` §3):

    recordings: [ {...}, ... ]   one entry per imported `.h5`.

⭐ **THERE IS NO `source` KEY, AND THAT IS DELIBERATE.** `videomosaic` has one because a video
project *is* a wrapper around one file, probed at create time. This project is a **shelf**, and
a shelf has no single source. Plan 001 § Approach guessed at "an empty `source`" by analogy with
the video feature; `recordings: []` is the same emptiness with the right name on it, and it is
the block plan 002 grew into rather than one it had to migrate away from.

⚠️ **EMPTY IS STILL AN ORDINARY STATE, even though the wizard now fills it (plan 002).** A project
whose recordings he has all removed is empty and must keep working — that is what the `+ Add
recordings` button on the empty state is for, and `POST /api/mea/projects` with no `paths` is still
exactly what it was in 001.

---------------------------------------------------------------------------------------------
ONE RECORDING, AS THE DOCUMENT RECORDS IT
---------------------------------------------------------------------------------------------
    { "id": "rec_3f9a2c",                            minted, stable; ⛔ never the path
      "label": "Network/000690",                     what a human calls it
      "run_id": "000690", "assay": "Network",
      "source_path": "D:/…/data.raw.h5",             where it came from
      "stored_path": "recordings/<id>/data.raw.h5",  project-relative, once the copy lands
      "copy_state": "referenced"|"copying"|"stored"|"failed",
      "copy_error": "",                              why the copy did not finish, if it did not
      "bytes": 0, "added": "2026-08-14T…Z" }

⛔ **`source_path` IS A PATH, NOT DATASET KNOWLEDGE** — the same standing as the manifest's
`data_dir`. And ⛔ **nothing about what is *in* the recording is written down**: not a channel list,
not a spike count, not a threshold. Every number the shelf shows is read off the file at the moment
it is asked for (`features/mea/recordings.py :: facts_of`). A cached channel count would be dataset
knowledge with a timestamp on it, and it would go stale the first time a file changed under us.

⭐ **`copy_state` IS THE LAST KNOWN STATE, NOT THE TRUTH.** The shelf derives what is actually true
from the disk and the job registry — see `recordings.shelf_entry`. That is what keeps a copy
interrupted by a restart from reporting for ever as a `copying` that will never finish.

⚠️ **`id` is minted and is not the path.** He may add the same file twice (two projects, or the
same project after a remove), and the project's own copy has to live somewhere that cannot collide.
A path is not an identity; it is a fact about where something was.

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

    ⛔ Takes no arguments and wants none — including the `paths` the wizard's Files step now
    collects. The document is authored empty and the recordings are **added** to it by
    `features/mea/recordings.py`, inside the same request, through the one code path that the in-
    project `+ Add recordings` button also uses. ⚠️ That is not tidiness: a second way to put a
    recording into a document is a second place for the copy state to be got wrong, and the two
    doors would drift.
    """
    if kwargs:
        raise core.DocumentError(
            f"a mea document is created empty; it was given {sorted(kwargs)}. Recordings are "
            "added to the payload by features/mea/recordings.py, never seeded here."
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
    """The two structural claims this payload makes: `recordings` is a list of objects, and each
    one carries an `id` and a `source_path`.

    ⭐ **THE `id` IS CHECKED BECAUSE EVERYTHING ELSE IS ADDRESSED BY IT** — the copy's folder,
    the DELETE route, the shelf row. A recording without one is a row nobody can remove.
    `source_path` is checked because without it the recording cannot be read at all: a `stored`
    entry could survive on its copy alone, but then the day the copy was lost there would be
    nothing left to say where it came from.

    ⛔ It says nothing about what is *in* a recording, and it does not check `copy_state`: nothing
    here knows a plate, a run, a channel count or an expected spike rate (I1 / no dataset
    knowledge), and a document that refused to open because a recording carried a value this build
    has not heard of would be the lossy round-trip `core.document` exists to prevent. An unknown
    `copy_state` is treated as `referenced` when the shelf is read, which is the safe answer:
    read the original.
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
        if not str(rec.get("id") or ""):
            problems.append(("hard", f"recordings[{i}]: has no id"))
        if not str(rec.get("source_path") or ""):
            problems.append(("hard", f"recordings[{i}]: has no source_path"))
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
