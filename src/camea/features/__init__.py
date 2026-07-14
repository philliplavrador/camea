"""camea.features — the analyses the app HOSTS. Mosaic is the first, not the only one.

The dependency arrow is one-way and it is not negotiable:

    api  ->  features  ->  core  ->  engine

A feature may use `camea.core` freely. It may **not** reach around core (no second frame reader, no
second document writer, no second job registry), it may **not** put its own concepts into core (a
*tile*, an *anchor*, a *pass split* are mosaic's words), and it may **not** import `camea.api` —
that is the cycle the arrow forbids.
"""
