"""The videomosaic document — payload shape, hooks, and the build's write-back.

Payload (FLAT beside the envelope, like every feature):

    source:    the probed video receipt {path,name,width,height,fps,n_frames,duration_s,size_bytes}
    config:    the VideoConfig the last build used (null before the first build)
    build:     the last build's summary {built_at, stats, canvas, outputs} (null = never built)
    keyframes: {"<video frame index>": {x, y, segment, reason, placed}} — canvas-relative
               top-left corners (R19's convention), machine-placed, all of them.

Provenance is the easy case done honestly: this feature IS automation, so any built document
carries machine evidence and `independent_of_method: false` — a video mosaic can never be
mistaken for a human-verified truth, structurally. (`machine_evidence` reads the HISTORY —
the build block / placed keyframes — never a claim.)
"""

from __future__ import annotations

from typing import Any

from ...core import document as core
from ...core.document import Problem, iso_now

FEATURE = "videomosaic"


def new_payload(doc: dict, **kwargs: Any) -> dict:
    """A fresh videomosaic payload: the probed source, nothing built yet."""
    source = kwargs.get("source")
    if not isinstance(source, dict) or not source.get("path"):
        raise core.DocumentError("a videomosaic document needs a probed `source` video")
    doc["source"] = dict(source)
    doc["config"] = None
    doc["build"] = None
    doc["keyframes"] = {}
    return doc


def apply_build(doc: dict, result: dict) -> dict:
    """The build job's result, landed in the document. -> a NEW document dict."""
    out = dict(doc)
    out["config"] = result.get("config")
    out["keyframes"] = {str(k): dict(v) for k, v in (result.get("keyframes") or {}).items()}
    out["build"] = {
        "built_at": iso_now(),
        "canvas": result.get("canvas"),
        "outputs": result.get("outputs"),
        "stats": result.get("stats"),
    }
    return out


def machine_evidence(doc: dict) -> dict | None:
    build = doc.get("build")
    if not build and not doc.get("keyframes"):
        return None
    ev: dict[str, Any] = {"method": "videomosaic"}
    if isinstance(build, dict):
        ev["detected_from"] = (f"build block of {build.get('built_at', '?')} — "
                               "every keyframe position is solver output")
        stats = build.get("stats") or {}
        if isinstance(stats, dict) and stats.get("registration"):
            ev["config"] = doc.get("config")
    else:
        ev["detected_from"] = "machine-placed keyframes present without a build block"
    return ev


def normalise(doc: dict) -> dict:
    """Nothing derived is stored twice in this payload — normalise only tidies types."""
    out = dict(doc)
    out["keyframes"] = {str(k): v for k, v in (doc.get("keyframes") or {}).items()}
    return out


def validate(doc: dict) -> list[Problem]:
    problems: list[Problem] = []
    src = doc.get("source")
    if not isinstance(src, dict) or not src.get("path"):
        problems.append(("hard", "source: a probed video receipt is required"))
    kfs = doc.get("keyframes")
    if not isinstance(kfs, dict):
        problems.append(("hard", "keyframes: must be an object"))
    else:
        for key, rec in kfs.items():
            if not str(key).lstrip("-").isdigit():
                problems.append(("hard", f"keyframes: key {key!r} is not a frame index"))
                break
            if not isinstance(rec, dict) or "placed" not in rec:
                problems.append(("hard", f"keyframes[{key}]: not a keyframe record"))
                break
            if rec.get("placed") and not all(
                    isinstance(rec.get(a), (int, float)) for a in ("x", "y")):
                problems.append(
                    ("hard", f"keyframes[{key}]: placed but x/y are not numbers"))
                break
    build = doc.get("build")
    if build is not None and not isinstance(build, dict):
        problems.append(("hard", "build: must be null or an object"))
    return problems


def counts(doc: dict) -> dict:
    kfs = doc.get("keyframes") or {}
    return {"n_tiles": sum(1 for v in kfs.values() if isinstance(v, dict) and v.get("placed"))}


def identity(doc: dict) -> str:
    src = doc.get("source") or {}
    return str(src.get("name") or "")


class VideoMosaicHooks:
    """Thin delegations, one instance, registered at import — the `MosaicHooks` pattern."""

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


HOOKS = VideoMosaicHooks()
core.register_feature(FEATURE, HOOKS)
