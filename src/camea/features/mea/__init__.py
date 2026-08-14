"""Analyze MEA — open a MaxWell recording on its own, with no calcium anywhere in sight.

The third task, and the first one that is **not a mosaic**. Where `videomosaic` pairs an
optical survey with an electrical record — the experiment the author calls *"Simultaneous
MEA + 2P"* — this one throws the optics away entirely: a project is a **shelf** you put
`.h5` recordings on, and the screen is about the chip's own electrical record.

⭐ **WHY IT IS ITS OWN FEATURE AND NOT A MODE OF `videomosaic`** (his interview, 2026-08-14):
the two share `core/mearecording.py` and *nothing else*. Bolting this onto the video pipeline
would drag the mosaic, the electrode-lattice fit and the unresolved chip-seating question
(`utils/knowledge/mea-recordings.md`, issue 003) into a screen that needs none of them — and
worse, would teach a doubt that does not exist here. In the chip's own frame the file states
its own `electrode`, `x_um`, `y_um`; there is no microscope to guess the seating of.

What this package holds **today** (plan 001) is the thinnest thing that is still a real
project: a create route and the document hooks. There is no recording, no chip map and no
trace yet — that is plan 002, which fills the screen this one puts up.

    document.py   the feature's document hooks (registers "mea" with core)
    routes.py     the API — `POST /api/mea/projects`, and nothing else yet

Importing this package registers the feature with `core.document`, exactly as
`features.videomosaic` does. ⛔ Nothing heavy at import time: `/openapi.json` must import
clean on a box with no CUDA, no cv2 and no data.
"""

from . import document as document  # noqa: F401  (import registers the feature)

FEATURE = document.FEATURE
