# web/tests/e2e — the acceptance contract

These Playwright specs turn `docs/BEHAVIOUR.md` (the ~44 numbered rulings the user paid days to
discover) into **failing tests written BEFORE the UI exists**. They fail today by design — every
helper times out on a `data-testid` the UI has not grown yet. They are the contract the Wizard/Core
agents build against: **a screen is done when its rulings go green, not when it "looks fine".**

> Every ruling is cited by its `R#` from `docs/BEHAVIOUR.md`. Read that file, not this one, for the
> *why*. This README is the **selector/route contract** the UI must satisfy.

---

## ⚠️ ONE CONFIG CHANGE IS NEEDED (I do not own the file)

`web/playwright.config.ts` currently sets `testDir: './e2e'`, which points at the scaffold's
`web/e2e/smoke.spec.ts`. My task assigns me `web/tests/e2e/**`, so these specs live there. **Until the
config owner changes `testDir` to `'./tests/e2e'` (or adds it), Playwright will not discover these
specs.** That one-line change is the only thing standing between this suite and a red run. (The
existing `web/e2e/smoke.spec.ts` is a separate plumbing smoke owned by the scaffold agent — leave it,
or fold it in; these specs supersede it with a fixture-accurate §8 path in `smoke-path.spec.ts`.)

Nothing else here is blocked on that: the specs are valid TypeScript and compile against the generated
API types today.

---

## How to run

```bash
cd web
npm run e2e                     # boots backend (headless, at tests/fixtures) + vite, runs everything
npx playwright test --grep-invert @slow    # the FAST lane — skips build-dependent specs
npx playwright test --grep @slow           # only the specs that run a real build
```

`@slow` marks every test that runs the solver (a real build). The fast lane needs no build and stays
quick on the synthetic fixture.

---

## The selector contract — what the UI MUST expose

All selectors are `data-testid` unless a role is named. The machine-readable source is
[`pages.ts`](./pages.ts) (`TID`); this table is the human copy. Where a `data-*` attribute is listed,
the UI must set it — specs assert on it.

### Home / shell

| testid | element | notes |
|---|---|---|
| `project-manager` | the home | ⭐ no first-run prompt — nothing is picked before he can start (R41.2, 2026-07-25) |
| `project-card` | one project | `data-project-id`; the card is the Open affordance |
| `project-name` / `project-data-dir` | card facts | the name he typed, and where its **data** came from. ⛔ The project's own folder is Camea's and is never advertised (R44.7) |
| `project-rename` / `project-export` / `project-delete` | card menu | ⭐ **Delete means delete** (R44.8) — there is no Remove; the confirm says so |
| `projects-unreadable` | store folders that would not read | said out loud, never silently dropped |
| `projects-migrated` | the one-time R44 notice | which projects moved into the store, and what did not |
| `project-paths` | the where-**from** step | ONE `PathField` — **no root registry, no browse grid, and no save folder** (R44.2) |
| `from-field` | the data path box | `path-input` · `path-submit` · `path-browse` · `path-error` inside it |
| `dataset-choice` | disambiguation chip | shown **only** when one folder holds several acquisitions |
| `dataset-card` | the RECEIPT for the folder he typed | a confirmation, not a card in a grid |
| `dataset-name` / `dataset-snapshots` / `dataset-shapes` | receipt facts | read straight off `/api/datasets/at` |
| `np-create` | **Create project** | disabled until the ONE path resolves |

### Outputs — ⭐ the only door to a project's files (R44)

Mounted by **both** feature screens; the same component, not a copy.

| testid | element | notes |
|---|---|---|
| `outputs-panel` | the whole panel | lists `<project>/outputs/`, read off the DIRECTORY, never the document |
| `outputs-list` / `output-row` | the files | `data-name` = the filename |
| `output-pick` / `output-look` | tick · preview | `output-preview` renders the image inline |
| `outputs-empty` | nothing built yet | a normal state, not an error |
| `copy-into-field` | where a copy goes | a `PathField` — typed box + `path-browse`, so it stays drivable headless (R38) |
| `outputs-copied` | the receipt | "Copied into …". ⛔ A clash refuses the WHOLE request, inline, via `path-error` |

⛔ **There is no `project-folder`, no `into-field`, no `folder-receipt`, no `project-forget`, no
`vm-save` and no `vm-open-folder`.** R44 retired every one of them; a spec asserting `toHaveCount(0)`
on those names is guarding the ruling, not a leftover.
| `topbar` | the shell top bar | |
| `save-project` | **Save…** button | visible & functional on ALL six steps (R5.1) |
| `toast` | transient message region | `role=status`/`alert`; carries "Finish the step…", "Resumed…" |

### Wizard nav

| testid | notes |
|---|---|
| `wizard` | the feature container |
| `wizard-steps` | the step header (a progress indicator, not a menu — R4.2) |
| `wizard-step-{load,range,screen,place,sweep,mosaic}` | each step tab. **Attrs:** `data-locked="true\|false"` (R4.3), `data-active="true\|false"` or `aria-current="step"`, and a visible label (Load/Range/…). |

### 1 · Load

`load-dir`, `load-browse`, `load-open`, `load-phase`, `load-project` (**Load a project…**, R5.3).
**Must NOT exist:** `load-result` (opening a dataset navigates — R4.5/§6.6).

### 2 · Range

`range-facts`; the facts `fact-trials`, `fact-range`, `fact-passsplit`, `fact-gaps` (text **"none"** on
a fresh open — R2.3); inputs `range-lo`, `range-hi`, `range-split`, `range-apply`; `contact-sheet` with
`contact-cell` (`data-trial`).

### 3 · Screen

`screen-facts`, `fact-recommended`, `fact-threshold`, `screen-grid`.
`screen-card` — one per scanned frame; **attrs** `data-trial`, `data-choice="keep|hand|exclude"`
(default **hand** — R6.2). Within a card: `screen-keep`, `screen-handplace`, `screen-exclude`
(`aria-pressed`), `screen-card-texture`. `screen-place-next` (**"Place the tiles →"**, fires the
refusal PUT first — R6.7).
**Must NOT exist:** `screen-tick-all`, `screen-tick-none`, `screen-exclude-ticked` (R6b).

### 4 · Place

`place-cost`, `place-gpu`, `place-run`, `place-cancel`, `place-use-cache`, `place-skip`
(destructive — R27), `place-progress-bar` (a gliding CSS width transition — R8.5), `place-eta`
(ticks down, format `15m 01s` / `47 s` / `almost there…`, never negative — R8), `place-phase`,
`place-log`, `place-worklist` + `place-worklist-item`, `place-advanced` (`<details>`; says "off the
validated path"). Warning: `warn-pass1-no-confidence` (W9).

### 5 · Sweep (the stage)

The sweep **is** the stage; it has no pane (R4.7).

- **Canvas** `sweep-canvas` (a `<canvas>`). **Live attrs the display must set (R9 — the picture must
  not lie about what it draws):**
  - `data-anchor-layer` — integer count of certified tiles BAKED INTO the drawn field (0 at start;
    +1 on each `A`).
  - `data-unverified-drawn` — `"false"` in the sweep (the unverified layer is maintained, not drawn).
  - `data-diff` — `"true"/"false"` Difference mode (mirror of `sweep-difference` `aria-pressed`).
  - `data-float-alpha` — the floating tile's opacity `0.15`–`1.00` (default `1`).
- **Banner** `banner` — the loud running commentary (divert/stale/end-of-run).
- **Actions** (all seven carry their OWN `?` — R7.1, `aria-pressed` where a toggle): `sweep-anchor`,
  `sweep-exclude`, `sweep-next`, `sweep-replay`, `sweep-difference`, `sweep-alternatives`, `sweep-snap`.
- **Camera** `sweep-fit`, `sweep-oneone`, `sweep-undo`, `sweep-redo`.
- **Header counts** `header-anchored`, `header-unverified`, `header-diverted` (hidden at 0 — R15b).
- **Left rail** `queue` + `queue-chip` (**attrs** `data-trial`, `data-state=unplaced|unverified|anchored|excluded`,
  `data-cursor`, `data-stale`), `queue-back`, `queue-filter-outstanding`, `queue-count`; `rescue` +
  `rescue-item` (`data-trial`) + `rescue-btn`; `opacity-slider` (`min=15 max=100 step=5`, default 100 — R13);
  `tone-lo`/`tone-hi`/`tone-apply`/`tone-auto`; `keys-cheatsheet`.
- **Right rail — evidence** `evidence`, `evidence-ncc`, `evidence-ncc-meter`, `evidence-margin`,
  `evidence-anchors`, `evidence-composite-area`, `evidence-overlap`, `evidence-took`,
  `evidence-machine-note`; `alternatives-list` + `alternatives-item` (**attr** `data-rank`, 0-indexed
  storage; **display must read `#rank+1`** — R12.3); `stale-panel`/`stale-recheck`/`stale-item`;
  `build-stale-panel`/`build-stale-resolve`.
- **Status bar** `status-bar`, `status-trial` (`"trial <n>"` — never `"trial —"`, R14),
  `status-state`, `status-pass`, `status-topleft` (`"top-left <x, y>"` — R19), `status-hint`,
  `status-msframe` (~6 ms — R20), `status-fps`.

### 6 · Mosaic

`mosaic-basename` (⛔ **no `mosaic-dir` / `mosaic-browse`** — R44: the export goes into the
project's own `outputs/`, and `outputs-panel` is how it leaves); output chips
`mosaic-out-{tiff,png,csv,gt,qc}`;
`mosaic-render-mode`, `mosaic-include-unverified`, `mosaic-umperpx`, `mosaic-export`,
`mosaic-autosave-note` (separate from Save… — R5.4); `provenance-panel`, `provenance-stamp` (W5:
"NOT AN INDEPENDENT GROUND TRUTH…"); export result `export-files` + `export-file` (**attrs**
`data-kind=tiff|coverage|png|positions|gt|qc|qc_md`, `data-path` = the written absolute path).

### 7 · Electrodes (the post-export identification stage — shared by BOTH features)

The step chrome is `electrodes-*`; the readout that the snapshot step **and** the videomosaic screen
both mount is `electrode-*` (singular); the video screen's own chrome is `vm-*`.

- **Step** `electrodes-viewer` (root), `electrodes-canvas` (the READ-ONLY core viewer),
  `electrodes-map` (**Map electrodes _and_ Re-run — one testid, two mutually-exclusive states**),
  `electrodes-progress` / `electrodes-phase` / `electrodes-cancel`, `electrodes-map-error`
  (**the refusal, verbatim** — see below).
- **Readout** `electrode-panel`, `electrode-id` (text `col-row`; **attr** `data-kind=1|2`),
  `electrode-marker` (**attr** `data-electrode`), `electrode-ids-toggle` (`role=switch`, off by
  default), `electrode-stale` (the "map is stale — re-run" live warning).
- **R45.8 — the device spec and whether the whole chip is in frame.** The app now carries device
  knowledge, but **only because the user supplies it** by declaring the whole chip imaged. The
  lattice is still MEASURED from the pixels (R45.1); the spec only checks and completes the result.
  ⛔ **The numbers are never written in `web/`.** They are served by `GET /api/electrodes/device`
  (`ROUTES.electrodeDevice`) from the one place that also *enforces* them, and the UI formats what it
  is given. The specs stub that endpoint with a **fabricated** chip (`7 × 5 = 35` at `3.5 µm`), so a
  retyped "220 × 120" cannot pass; with the endpoint **down**, the choice still works and names **no
  numbers at all** rather than remembered ones.
  - `electrode-coverage` — `role=radiogroup`, `aria-label="Array coverage"`, with
    `electrode-coverage-full` ("Whole chip imaged") and `electrode-coverage-partial` ("Part of the
    chip"), each carrying `aria-pressed`. ⭐ **There is no default**: both read `false` until he
    picks, and `electrodes-map` / `vm-map-electrodes` are **DISABLED** while neither is pressed. The
    answer goes on the wire as `array_coverage` on the map request.
  - `electrode-coverage-mode` (**attr** `data-coverage=full|partial`), `electrode-um-per-px` (the
    MEASURED scale — device pitch ÷ the pitch this image shows), `electrode-device` (the named spec)
    — grid facts; `electrode-um` — the selection's centre in µm, in the array's own frame
    (**absent** when the map carries no device scale: "not known" is never rendered as a number).
  - `electrode-shape-corrected` — a live warning; **a corrected shape is never silent**. Either
    correction renumbers: a line **added** before column 1 pushes every id up (old 1-1 is 2-1), a
    line **dropped** from that end pulls every id down (old column 2 is column 1).
  - `electrode-partial-note` — a live warning; a partial map must say that **1-1 is the top-left of
    the IMAGED REGION, not of the chip**. ⛔ It names a pitch **only when the payload carried one** —
    over a pre-R45.8 map (no device, no `um_per_px`) it says the readout is pixels only.
  - `electrodes-map-error` / `vm-electrodes-map-error` — ⭐ **the refusal, whole.** Under "whole chip
    imaged" the fit is STRICT: the device's exact shape with every position numbered, or a refusal
    naming both shapes and telling him to answer "part of the chip". It renders verbatim, and the
    coverage question stays on the page beside it so the fix is one click away.
- **Videomosaic** `vm-map-electrodes` (Map electrodes _and_ Re-run — one testid),
  `vm-electrodes-progress`, `vm-electrodes-cancel`, `vm-electrodes-map-error`, `vm-viewer`
  (**attrs** `data-fit`, `data-identify`), `vm-zoom-toggle`, `vm-electrode-marker`,
  `vm-electrode-ids-toggle`.

### Help (R3)

`help` — the reusable `?`: `role=button`, `tabindex=0`, sets `data-empty="true"` when its body is empty
(and then hides itself — R3.3). `help-tooltip` — the bubble: **body-level, `position: fixed`** (R3.4),
dismissed on blur / scroll / `Escape`.

### The eleven live warnings (§5) — each STAYS on the page, never a tooltip

`warn-build-stale` (W1), `warn-thin-margin` (W2), `warn-divert` (W3), `warn-autosave-failed` (W4),
`provenance-stamp` (W5), `warn-refused-blank` (W6), `warn-small-aperture` (W7), `warn-stale` (W8),
`warn-pass1-no-confidence` (W9), `warn-no-anchors` (W10), `warn-confident-disagree` (W11).

### Routes the specs inspect or stub (frozen backend — `docs/openapi.json`)

The sweep's placement match **MUST** go through `POST /api/mosaic/match/anchor`, carrying
`{session_id, target, anchors[], positions{}, refuse[]}` — that request body **is** the R21/R22 cache
key, and the specs both read it and stub it. Also used: `/api/mosaic/match/score`,
`/api/mosaic/build`, `/api/mosaic/export`, `/api/mosaic/screen/propose`, `/api/documents/save-as`,
`/api/documents/load`, `/api/analyses/{id}/autosave`. Headless save/load fall back to `window.prompt`
(R38) so Playwright can answer them.

---

## Specs by area

| file | rulings | count | @slow |
|---|---|--:|---|
| `home-browser.spec.ts` | R-home, R2.1, R2.2, R2.3, R4.5, shape-gate | 6 | — |
| `no-dataset-knowledge.spec.ts` | I1, R2 (no 312/338/26/260620d/EXCLUDED_TRIALS, no toggle) | 3 | — |
| `wizard-steps.spec.ts` | R4.1–R4.4, R5.1–R5.4 | 8 | — |
| `screen-step.spec.ts` | R6.1, R6.2, R6.5, R6.6, R6b, R2.3, R17 | 7 | — |
| `sweep-canvas.spec.ts` | R9.1–R9.4, R9b, R11.1–R11.4, R12.3, R12.8, R12.10 | 9 | — |
| `sweep-keymap.spec.ts` | R14 ×2, R9b, R15, keymap, R19, R23, §3.4, R12.6, §6.7, unbound keys | 12 | — |
| `difference-mode.spec.ts` | §3.5 (black clear), R13.1, R13.2, R13.4 | 4 | — |
| `solver-fallback.spec.ts` | R15 (1)(2)(3)(4), I3, W11 | 5 | 3 |
| `prefetch-evidence.spec.ts` | R21, R22 ×2, §6.8, R33 | 4 | — |
| `save-resume.spec.ts` | R2.4 ×2, R2.6, R14, R38 | 5 | — |
| `provenance-export.spec.ts` | R28, R37, R27 | 3 | 3 |
| `place-eta.spec.ts` | R8.1, R8.2, R8.3, R8.5, R8.6, R8b, §6.9 | 3 | 3 |
| `live-warnings.spec.ts` | §5/R3.8, W10, W1, W9 | 4 | 2 |
| `help-tooltip.spec.ts` | R3.1–R3.4, R7.1, R7.4 | 6 | — |
| `perf-status.spec.ts` | R20 (ms/frame ~6, soft) | 2 | — |
| `smoke-path.spec.ts` | §8 integration (R2/R3/R6/R9/R11/R12/R13/R14) | 1 | — |

**82 specs** across 16 files. `@slow` (11) run the solver; the fast lane is the other 71.

---

## Rulings I could NOT express as a fixture e2e test (and why)

The synthetic fixture is 10 clean tiles with known offsets — deliberately unambiguous, so several
rulings whose whole point is *ambiguity* or *dataset scale* have no trigger on it. Where a ruling is a
pure client decision I forced it with a stubbed match response (`stubMatchAnchor`); where it needs
real ambiguous pixels I could not.

- **W2 (thin-margin), W7 (small-aperture)** — need a surviving grid alias / a genuinely thin aperture.
  The fixture's matches are confident by construction. *Partially* reachable via a stubbed
  low-margin/low-aperture `MatchResult`, but the *pixels* the warning is about are not there.
- **W6 (refused-blank), R16** — need a blank frame (fixed-pattern sensor noise). The fixture has none;
  adding a near-featureless frame to the fixture would let this go green.
- **W4 (autosave failed)** — needs the autosave POST to fail; reachable by routing `/api/analyses/*/autosave`
  to a 500, which I left out to avoid coupling to the (frozen) autosave path shape. Easy to add.
- **R8.1/R8.2 (ETA ticks every second)** — the fixture build is likely < 2 s, too short to watch the
  clock move. The FORMAT and no-negative clauses always hold; the *ticking* clause needs a longer build.
- **R10 (feather / continuous strip, photometry caveat)** — "no hard seams" is a perceptual claim over
  many overlapping tiles; a single pixel probe cannot distinguish a cosine ramp from a hard edge
  reliably on two tiles. Left as a visual-review item; `data-anchor-layer` covers the *structural* half.
- **R20 (~6 ms)** — asserted **soft**: on CI hardware the absolute number varies. The falsifiable line
  is 90 ms (rebake) vs 6 ms (layered); the test flags anything ≥ 33 ms.
- **§8 step 12 (kill the server, cold-load)** — Playwright manages the backend as a shared `webServer`
  and cannot kill it mid-run. `save-resume.spec.ts` proves the file round-trip client-side (reload +
  re-load the project) instead.
- **R7.5/R7.6 (the `?` audit's false-pass trap; controls that are FINE bare)** — "every control has its
  OWN `?`" is asserted for the seven sweep buttons (R7.1); a *complete* audit of all ~65 controls, and
  the negative "these six are fine WITHOUT a `?`", is a lint-style check better done in review than as
  brittle per-control e2e.
