"""Video mosaic — build a mosaic automatically from a survey video.

The second feature. Where the snapshot mosaic is *acceleration of human verification* (the
machine drafts, the human sweeps), this one is the opposite by design and by his request:
**the user hands Camea a video and gets a mosaic — no frame choosing, no placing, no
keyframe picking.** The two philosophies coexist because they are two different inputs:
338 loose snapshots need a human judge; a 58 fps video carries its own continuity, and that
continuity *is* the placement evidence.

Pipeline (each stage its own module, orchestrated by `pipeline.py`):

    video.py     decode/probe (cv2.VideoCapture, streaming — never the whole video in RAM)
    track.py     pass 1: coarse whole-video motion tracking + automatic keyframe selection
    register.py  pass 2: keyframe-to-keyframe registration (sequential + cross-row links)
    solvelinks.py robust global translation solve (IRLS) over the link graph
    render.py    flat-field, exposure gains, feathered composite, tone, PNG/CSV outputs
    document.py  the feature's document hooks (registers "videomosaic" with core)
    routes.py    the API (probe / create project / build job / outputs / export)

Importing this package registers the feature with `core.document` (same pattern as
`features.mosaic`). Everything heavy (cv2, numpy work) stays out of import time —
`/openapi.json` must import clean.
"""

from . import document as document  # noqa: F401  (import registers the feature)

FEATURE = document.FEATURE
