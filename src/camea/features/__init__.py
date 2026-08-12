"""camea.features — the analyses the app OFFERS. `videomosaic` is the live one.

⭐ **The SNAPSHOT mosaic builder used to live here (`features/mosaic`). On 2026-08-11 it moved to
`camea.legacy.mosaic`** — retired from the New-project screen because the user's work is
video-based, *not* because it is broken. It is still mounted and still opens every project already
built with it; `camea/legacy/__init__.py` says what "legacy" means and what may not be done to it.

The dependency arrow is one-way and it is not negotiable:

    api  ->  features (and legacy)  ->  core  ->  engine

A feature may use `camea.core` freely. It may **not** reach around core (no second frame reader, no
second document writer, no second job registry), it may **not** put its own concepts into core (a
*tile*, an *anchor*, a *pass split* are mosaic's words), and it may **not** import `camea.api` —
that is the cycle the arrow forbids.
"""
