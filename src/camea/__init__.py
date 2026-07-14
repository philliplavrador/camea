"""Camea — a microscopy analysis desktop app.

The shape of this package, and why:

    core/       The four things EVERY feature needs, whatever it does.
                  dataset   — open a RAW dataset. read-only, by construction.
                  frames    — .dat IO, flat-field, tone, thumbnails.
                  workspace — where your analyses live. never inside the dataset.
                  document  — save/load/autosave/migrate an analysis.
                  jobs      — run slow things, with progress, cancellably.

    engine/     The science. t27/t33 placement, moved here byte-identical from
                the research tree. Do not "improve" it casually: it is under a
                312/312 regression guard against a hand-authored ground truth.

    features/   What you can DO to a dataset. mosaic/ is the first one, not the
                only one. A feature owns its own routes, document type and UI;
                it borrows everything else from core/.

    api/        FastAPI. Mounts core's routes plus each feature's routes, and
                serves the OpenAPI schema the TypeScript client is generated from.

The rule that keeps this honest: a DATASET IS RAW AND IS NEVER WRITTEN TO.
Everything Camea produces lands in the workspace.
"""

__version__ = "0.2.0"
