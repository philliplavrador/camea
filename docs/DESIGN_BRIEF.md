# DESIGN_BRIEF.md — the Camea design system

> **What this is.** The design plan and vocabulary for the `web/` rewrite: the palette, the type,
> the structural devices, the one signature element, and the primitive components every feature
> screen is built from. It is owned alongside `web/src/design/**`. Feature screens (Load, Range,
> Screen, Place, Sweep, Mosaic) are built *out of* this vocabulary; they are not specified here.
>
> **Grounding.** Read `docs/BEHAVIOUR.md` first — this brief serves it. Every colour below is a
> *measurement the user acts on*, not a brand choice; every rule here has a citation there.

---

## 0. The subject, in one breath

Camea is a **precision instrument for hand-verifying microscopy mosaics**. A biologist sits in a dim
room for an hour and judges, one tile at a time, whether the aligner put a 512-px snapshot in the
right place — pressing `Space` to advance, `A` to certify, `E` to throw out, over a one-second fade.
The product is *the human looking at the pixels*. So the design has exactly one job: **get out of the
way of the pixels, and make the one number he is about to act on unmissable.** A radiologist's reading
room, not a dashboard.

Audience: one expert user, keyboard-first, who already knows what everything does (BEHAVIOUR I2 — the
app is a **tool, not an explainer**). The chrome is read a thousand times an hour; it must never
compete with the tissue and must never make him think.

---

## 1. PALETTE

Dark is the working theme (a dim microscope room). Light is provided and is theme-sensitive in one
load-bearing place (§1.3). Values are the whole palette — components reference *tokens*, never hex.

### 1.1 The two blacks — the load-bearing decision

Camea needs **a true-black stage** and **a near-black chrome that is clearly distinguishable from it.**
This is not taste; it falls out of a ruling. Difference mode (`D`) composites `|tile − field|` and
**must clear to pure black**, because black is the only destination for which *"no reference here"*
reads as *"no difference here"* (BEHAVIOUR §3.5). I make the *normal* stage true black too, so the
backdrop does not shift when he toggles `D`, and so the tissue is the only lit thing on it.

| token | dark | role |
|---|---|---|
| `--canvas` | **`#000000`** | THE STAGE. True black. Read by the viewer via `getComputedStyle`. The one surface the tiles sit on. |
| `--canvas-diff` | **`#000000`** | Difference-mode clear. Black in **both** themes — the ruling is theme-sensitive (§1.3). |
| `--bg` | `#07090b` | the void behind panels |
| `--bg-raised` | `#0e1319` | top bar, rails — near-black chrome with a faint blue-graphite cast |
| `--bg-card` | `#131a22` | a dataset card, a pane, a fact |
| `--bg-inset` | `#05070a` | wells: thumbnails, the log tail, readouts — darker than chrome, **not** `#000` so it reads as a well and not as the stage |

The chrome (`#0e1319`) sits a measurable step above the stage (`#000`) and carries a cool graphite
cast rather than neutral grey — the instrument-housing tone around a black aperture.

### 1.2 The data palette — every hue is a tile state

The bright colours do **not** belong to the chrome. They belong to the **data**, and each one is a
state the user acts on (BEHAVIOUR §4, §5). This is the discipline that keeps Camea off the generic
"dark UI with one accent" road: the accent recedes; the *measurements* carry the colour.

| token | dark | meaning — and the action it drives |
|---|---|---|
| `--anchored` (`--good`) | `#5ad48a` green | **certified by the human.** Baked into the anchor field. |
| `--unverified` (`--warn`) | `#e0a53a` amber | **outstanding work.** It should nag. Also every live warning's rail. |
| `--thin-margin` (`--danger`) | `#ff6b6b` red | `best − second < 0.10` — **the signature of a surviving grid alias.** LOUD (W2). |
| `--cursor` | `#4aa3ff` blue | **the tile under judgement.** Same blue as the accent — the cursor *is* the app's focus. |
| `--alt` | `#a78bfa` violet | a ranked alternative candidate (`V`, keys `1`–`9`). |
| `--diverted` | `#e879f9` fuchsia | placed at the **solver's** position, not the matcher's (W3). Without this hue a diverted tile looks confidently matched. |
| `--excluded` | `#6b7280` grey | thrown out. Not drawn, not matched, not exported. |

### 1.3 The accent, deliberately quiet

`--accent: #4aa3ff` (dark) / `#1f6fc4` (light) is spent **only** on: keyboard focus, the active
wizard step, the cursor tile, and a link. It is *the same blue as `--cursor`* on purpose — the one
thing the chrome may light up is the thing the user is judging. It never fills a card, never paints a
header, never gradients. If the accent is doing decorative work, that is the bug.

### 1.4 Ink

`--text #e6edf3` (labels) · `--text-dim #94a1ad` · `--text-faint #5a6672` (units, tile outlines) ·
`--data #d7e7f5` — the mono measurement ink, a cool near-white pitched **brighter than the label
text**, because in an instrument the *number* is the figure and the label is the ground (§2).

### 1.5 Light theme — "bright bench"

Same semantics, re-valued for a lit room. The one theme-sensitive ruling: `--canvas` is a light grey
`#dfe4ea` (a light stage is easier under room light) but **`--canvas-diff` stays `#000000`** — in the
light theme the normal canvas is luminance 223, so difference mode *must* force black or half of what
he is checking becomes a photographic negative (BEHAVIOUR §3.5). Card `#ffffff`, chrome `#f5f7f9`,
ink `#0f151b`, accent `#1f6fc4`; the data hues darken to hold contrast on white (anchored `#1f9d5f`,
unverified `#a9730a`, thin-margin `#c0392b`, diverted `#b32fb8`).

Theme is selected by `data-theme` on the root (the viewer's toggle stamps it); with no attribute the
OS preference is followed. The token file also answers `[data-theme]` on **nested** elements so the
gallery can show both themes at once.

---

## 2. TYPE — an instrument readout, not a webapp

No web fonts (the app runs offline in WebView2; there is no font pipeline and a CSP would block a
CDN). The distinctiveness is in the **treatment**, not an exotic family.

- **Data / readout — mono.** `ui-monospace, "Cascadia Code", "Cascadia Mono", "SF Mono",
  "JetBrains Mono", Consolas, monospace`. Cascadia ships on the Windows target and reads like an
  instrument, not a code editor. **`font-variant-numeric: tabular-nums` everywhere** — a trial number,
  a px offset, an NCC or a coordinate must never reflow as its digits change. Every trial number, px
  offset, NCC, margin and `(x, y)` is mono (BEHAVIOUR R19, §5).
- **Label — humanist sans.** `"Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system,
  Roboto, sans-serif`. Humanist (not geometric) so it stays warm and quiet next to the hard mono.

**The signature typographic move — inversion.** In a webapp the label is prominent and the value is
body text. In an instrument it is the other way round: the **measurement is large and bright and
dominant; the label is a small, dim, upper-cased micro-cap with wide tracking** — the etched legend
beside a lit gauge. That inversion, applied consistently, is what makes a Camea panel unmistakable.

Scale (tokens): `--fs-readout-lg 19px` (a headline stat), `--fs-readout 13px` (inline data),
`--fs-body 14px`, `--fs-label 11px` (uppercase, `letter-spacing .08em`), `--fs-micro 10px`.
Weights: labels **600**, mono data **600**. Nothing lighter than 500 anywhere — thin type reads as
decorative and this is not a decorative product.

---

## 3. STRUCTURE

- **The six-step stepper is a progress indicator, not a menu** (R4.2). A real sequence — you cannot
  Sweep before you Load — so **numbered markers are earned here**, not ornament. `done` steps show a
  green check, the `active` step is picked out in accent, `locked` steps (everything past what the
  gate allows) are dimmed and inert; clicking one is a no-op the feature answers with a toast.
  Numbers are mono. The active node wears a faint **reticle tick** (§4) — the only place the chrome
  borrows the canvas's gesture.
- **Live warning ≠ hover-`?`.** Two visually distinct, non-interchangeable components, because the
  distinction is a ruling (R3.8, §5):
  - **`Help`** — a 14 px muted `?`. Everything explanatory lives in its tooltip. Body-level and
    `position: fixed` so an `overflow:auto` rail cannot clip it; **text-only** (a backend `why` string
    may contain a `"`); an **empty body hides the `?`** so it never promises what it cannot give;
    dismissed on blur, `Escape`, and scroll (capture phase). It is quiet, small, optional.
  - **`LiveWarning`** — a banner that fires **only when something is wrong right now** and changes
    what he would do (the eleven of §5). It **lays out as prose — `display: block`, never flex** — the
    exact bug R1 was filed for: flex made every `<b>` and bare text node its own column. It carries a
    coloured left rule (amber default, red `loud` with a 3-pulse for a thin margin, blue `info`). It is
    loud, and it stays on the page.
- **The status bar** is the instrument's footer readout: `trial n` · a state **badge** · `pass n` ·
  **`top-left (x, y)`** (R19) · a hint · **`ms/frame · fps`**. That perf pair is not decoration — it
  must read **~6 ms** (R20); ~90 ms is the visible symptom of the one architectural bug (a full rebake
  per frame) the layered canvas exists to prevent. The design system ships the shell and the readout
  slot; the sweep drives the numbers.

---

## 4. SIGNATURE — the reticle over the true-black stage

**The one memorable element is the sweep cursor: a corner reticle that locks onto the top-left of the
tile under judgement, with a live mono readout beside it, over a true-black stage where the certified
field feathers into one seamless strip.**

Why this and not a hero number or a gradient: the entire product *is* this gesture — the human's eye
on one tile, deciding. Positions in Camea are **top-left corners** (`+256 = HALF`; R19), so the reticle
is an **L-bracket at the corner**, not a box around the centre — the design encodes the coordinate
convention that has been the classic off-by-256 bug in this project. Beside it floats the only thing he
acts on: `top-left (−268, 432)`, `NCC 0.907`, `margin 0.42`, in mono. When alignment is off, difference
mode doubles it into bright fringing; when the margin is thin, the readout goes red. Everything else on
the page is quiet so that this — the corner, the crosshair, the four numbers — is the figure.

The design system expresses the signature three ways: the `--canvas` true-black token, a `Reticle`
motif component (corner brackets + hairline crosshair in `--cursor`, with the mono readout), and the
readout type treatment of §2. The live canvas is the Sweep feature's to wire; the gallery renders the
reticle **static**, as the vocabulary — not a feature screen.

**Restraint (Chanel's rule — remove one accessory).** The reticle tick is *not* sprayed on every
control. It appears on the canvas signature and, faintly, on the active step. Buttons, panels, chips
stay clean. The boldness is spent in exactly one place.

---

## 5. CRITIQUE — where this could read generic, and what I changed

AI dark UIs cluster on *"near-black background + one bright acid accent, 6-px cards, an amber
warning."* Camea's brief pins the dark instrument look, so I keep it — but I spent every free axis off
the default:

- **Surfaces.** The default charcoal is a single `#0e1015`-ish grey. **Changed:** a *two-black* system
  where the stage is **pure `#000`** (not charcoal) for a subject reason (difference-mode + tissue
  contrast), with the chrome a distinguishable graphite-blue above it. The black is a *decision*, not a
  backdrop.
- **Accent.** The default sprays one bright accent everywhere. **Changed:** the accent **recedes** to
  focus/active/cursor only; the bright colour is handed to the **data** — seven semantic tile-state
  hues, each an action. A Camea screen is colourful exactly where a measurement demands attention and
  grey everywhere else, which is the opposite of the acid-accent look.
- **Type.** The default is neutral system sans with mono relegated to code. **Changed:** the
  **readout inversion** — mono data is the large, bright figure; the humanist-sans label is the small,
  dim, tracked ground. The type treatment itself is the identity.
- **Structure.** Numbered markers are a generic device — but here the content **is** a locked sequence,
  so they carry real information (what you may reach), and the active node borrows the canvas's reticle
  tick to tie the chrome to the core gesture.
- **Signature.** The default hero is a big gradient number. **Explicitly rejected** (the brief forbids
  it). **Changed:** the hero is the **reticle over black** — the product's actual gesture, encoding the
  top-left coordinate convention.

What I kept quiet on purpose: no gradients, no glows beyond the accessible focus ring, no icon
system beyond the reticle, no decorative motion. The only animation that matters is the **1-second
fade** (`--fade-ms`, the core check — never shortened), and `prefers-reduced-motion` stops everything
except it.

---

## 6. The primitives (what `web/src/design/` ships)

Built here, used everywhere; no component kit. Each is a `.tsx` + colocated `.module.css`, referencing
tokens only.

| primitive | what it is | rulings it serves |
|---|---|---|
| `Button` | primary / default / ghost / danger; `sm`/`md`/`lg`; `block`; optional leading `Kbd` | — |
| `IconButton` | square, icon-only, **`aria-label` required** | overlay camera/undo controls |
| `Toggle` | a pill switch (`role="switch"`) — `use cache`, `outstanding only`, `D` | R7.2 |
| `Kbd` | a keycap. The sweep **is** the keyboard, so the keys are shown | §3.3 |
| `Help` | the hover-`?`: body-level fixed tooltip, empty-hides, text-only, blur/Esc/scroll-dismiss | R3 |
| `LiveWarning` | the state banner: **block prose**, amber / `loud` red-pulse / `info` blue | R1, R3.8, §5 |
| `Progress` | ⏱️ **THE ONE BAR.** Gliding track + label + phase + `%` + a time that is never blank + Stop. `pct={null}` = the travelling sliver, for the four cases with no denominator. Replaced five hand-rolled copies | **R48**, R8 |
| `Stepper` | the six-step progress indicator with locked/done/active | R4 |
| `StatusBar` / `StatusItem` | the footer readout shell + the `ms/frame` slot | R20 |
| `Badge` | a tile-state pill (anchored / unverified / excluded / unplaced / blank / diverted / gpu) | §4 |
| `Panel` | a rail section: micro-cap header (+ optional `Help`) + body | §3 |
| `Card` | a raised container (dataset card, fact) | home |
| `Reticle` | the signature motif — corner brackets + crosshair + mono readout over `--canvas` | §4 |

A `/design` route renders every one of them in **both themes** for screenshotting.

---

*Sources: `docs/BEHAVIOUR.md` (the rulings), `archive/app-v1/frontend/style.css` (the v1 instrument
tokens this supersedes). The archive is read-only.*
