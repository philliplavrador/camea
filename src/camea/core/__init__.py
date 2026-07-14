"""camea.core — feature-agnostic machinery: datasets, frames, workspace, documents, jobs.

⛔ CORE MAY NOT IMPORT FROM `camea.features`. Ever. The dependency arrow is one-way:

    api -> features -> core -> engine

and from `engine` core takes exactly two things: `engine.quality.band_pass` (THE band-pass) and
`engine.excluded.gaps` (a pure function over a trial list). Nothing else.

If a function in here knows what a *tile*, an *anchor*, a *pass split* or a *serpentine scan* is,
it is in the wrong package.
"""
