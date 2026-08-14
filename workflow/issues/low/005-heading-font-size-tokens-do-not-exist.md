---
id: 005
title: Screen headings ask for --fs-h1/--fs-h2 and small text for --fs-small; none of the three exists
kind: defect
tier: low
status: open
found: 2026-08-14
found-while: building plan 001 (Analyze MEA) — the frontend review checked whether the new shell's tokens were real
resolved-by: ~
---

# 005 — `--fs-h1` / `--fs-h2` / `--fs-small` are used by eight files and defined by none

[`web/src/design/tokens.css`](../../../web/src/design/tokens.css) defines the type scale as
`--fs-readout-lg` · `--fs-readout` · `--fs-body` · `--fs-label` · `--fs-micro`. It does **not**
define `--fs-h1` or `--fs-h2`. Six stylesheets ask for them anyway:

| file | rule |
|---|---|
| `web/src/features/home/ProjectManager.module.css` | `.greeting` |
| `web/src/features/home/NewProjectFlow.module.css` | `.title`, `.prompt` |
| `web/src/app/FeatureGate.module.css` | `.gateTitle` |
| `web/src/features/videomosaic/VideoMosaicFeature.module.css` | its heading |
| `web/src/features/mea/MeaFeature.module.css` | `.title`, `.lead` |

⭐ **AND A THIRD ONE, FOUND WHILE BUILDING PLAN 002 (2026-08-14): `--fs-small`.** Same story, same
`tokens.css`, two more files — so this is not a heading problem, it is the type scale having two
names in circulation. Whoever fixes the headings should fix this in the same breath.

| file | rule |
|---|---|
| `web/src/features/electrodes/CoverageChoice.module.css` | `.hint` |
| `web/src/features/electrodes/ElectrodePanel.module.css` | its label row |

`font-size` is inherited, so an undefined custom property with no fallback resolves to the
**inherited** value — every one of these headings silently renders at body size and is distinguished
only by its `font-weight`. It looks deliberate on screen, which is exactly why nobody has caught it.

⚠️ Plan 002's new stylesheets (`features/mea/ImportRecordings.module.css`, `RecordingShelf.module.css`)
deliberately use `--fs-readout` / `--fs-label`, which do exist, rather than adding to this pile.

## Why low

Nothing is broken and nothing is unreadable — the app has looked like this for its whole life, and
he has been using it. It is a defect in the sense that the code says one thing and does another, and
the next person to write a heading will copy a reference that does nothing.

## Why it is not a one-line fix

Defining the two tokens would resize **six existing screens at once**, including the home screen and
the video pipeline. That is a visible design change nobody asked for, so it wants his eye (or a
deliberate decision to point both tokens at `--fs-readout-lg` / `--fs-body`, which changes nothing
and makes the code honest). Either way it is a decision, not a repair.
