# `core/viewer` — the feature-agnostic canvas that IS the hero

The Camea viewer: a **layered 2-D canvas** for panning, zooming and compositing images in world space,
with one **floating item under inspection** (fade, opacity, Difference mode) and vector **overlays**.
It is the reusable core every feature mounts — Sweep today; segmentation/annotation tomorrow.

> **It knows images and overlays — NOT anchors, unverified tiles, diverts or mosaics.** Those are the
> _feature's_ meaning. You convey them with generic knobs: a **layer key**, a layer's **`reference`**
> flag (the Difference-mode field), and a **per-tile `outline`** style. If you find yourself wishing
> the viewer had an "anchor" concept, model it as a layer instead.

Serves BEHAVIOUR **R9, R10, R13, R14, R18, R19, R20, §3.4, §3.5, §6.7** and DESIGN_BRIEF §0/§4.

---

## The boundary

| the **viewer** owns | the **feature** owns |
| --- | --- |
| the `<canvas>`, camera (pan/zoom/fit/1:1), the layered bake, the bitmap cache, the fade, Difference mode, hit-testing, raw pointer/marquee gestures, the camera keys | the document (tile states/positions), undo/redo, **all** `fetch`, the prefetch, the panels, and **A / E / Space** and every non-camera key |
| emits gestures via callbacks; never interprets them | gives meaning: which layer a tile is in, whether it feathers, its outline, when to `fadeIn` |

The viewer **mounts with keyboard OFF**. It never adds a `window` keydown listener — you call
`handle.handleKey(e)` from your own key handler so there is **one dispatch point** (double-handling
`D` would toggle Difference twice). `Space` and Ctrl/⌘ combos always return `false` from `handleKey`
— they are yours (`Space` is ADVANCE, never a pan modifier — §6.7).

---

## Wiring it (the Sweep, concretely)

```tsx
import { Viewer, type ViewerHandle } from '@/core/viewer'; // (use a RELATIVE path — no @ alias yet)

const viewer = useRef<ViewerHandle>(null);
const [attrs, setAttrs] = useState({ 'data-anchor-layer': 0, 'data-unverified-drawn': 'false' });

<Viewer
  ref={viewer}
  // The certified field is the Difference reference; the unverified layer is maintained but NOT
  // drawn in the sweep (R9.4) — model that as visible:false, not as a special case.
  layers={[
    { key: 'anchor', reference: true },
    { key: 'unverified', visible: false },
  ]}
  canvasProps={{ 'data-testid': 'sweep-canvas', ...attrs }}
  onModelChange={(m) =>
    setAttrs({
      'data-anchor-layer': m.layers.anchor.placed, // certified count (R9.1=0, +1 per A)
      'data-unverified-drawn': String(m.layers.unverified.visible), // "false" in the sweep
    })
  }
  onDragEnd={(id, x, y) => doc.move(id, x, y)} // one undo step; a drag never demotes an anchor (R24)
  onSelect={(id) => {
    if (id !== null) setCursor(id); // 🔴 R14: on null (Esc) DO NOTHING — Esc must not kill the sweep
  }}
  onFadeEnd={(id) => autosaveAndPrefetch(id)}
  onAlternativePick={(id, c) => doc.moveToCandidate(id, c)} // same path as the rail's list (§3.6)
  onView={(v) => setZoomReadout(v.scale)}
  onDifference={(on) => setDiffPressed(on)} // mirror to sweep-difference aria-pressed
/>;

// certify (A): one-tile change, ~0.1 ms, NEVER a rebake — and it fades in on the NEXT tile:
viewer.current!.setTile(11, {
  x, y, layer: 'anchor', feather: true, src: tileUrl(11), // feather the field (R10); float stays crisp
});
// advance (Space): fade the next tile in over the 1 s check
await viewer.current!.fadeIn(12, mx, my);
```

### The four canvas attributes the specs read

| attribute | who sets it | value |
| --- | --- | --- |
| `data-diff` | **the viewer** (automatic) | `"true"`/`"false"` — mirror of Difference mode |
| `data-float-alpha` | **the viewer** (automatic) | the float opacity `0.15`–`1.00` (default `"1"`) |
| `data-anchor-layer` | **you**, from `onModelChange` | `m.layers.<referenceKey>.placed` |
| `data-unverified-drawn` | **you**, from `onModelChange` | `String(m.layers.<otherKey>.visible)` |

`data-diff` / `data-float-alpha` are viewer state, so the viewer stamps them itself. The other two are
_your_ semantics, so you reflect them through `canvasProps` (as above). `data-testid="sweep-canvas"`
is likewise yours to attach.

---

## The rulings baked into the render

- **R9 — the field is only what is certified.** `layerPlacedCount('anchor')` counts placed tiles in a
  layer _including a floating cursor tile that belongs to it_, so pressing A reads `1` at once. Hide the
  unverified layer (`visible:false`) and its **outlines vanish with it** (R9.5) — the yellow cage dies.
- **R10 — the field blends; the float stays crisp.** Set `feather:true` per tile on the layer(s) that
  should blend. The float is **never** feathered — softening the tile you are inspecting would blur the
  very misalignment you are looking for (R10.2). Feathering is a pre-baked cosine ramp multiplied in, so
  a bake is still **one `drawImage` per tile** (R10.3/R10.4). ⚠️ The live view is faithful to **geometry,
  not photometry** (alpha compounds where tiles pile up) — judge alignment here, tone on the Mosaic step.
- **R13 — the opacity slider.** `setFloatAlpha(0.15..1)`. The fade ramps `0 → floatAlpha`; at `1` it is
  bit-identical to before. 🔴 **Difference mode ignores it** — the engine forces `a = 1` in diff so the
  doubling signal is never weakened (R13.4).
- **§3.5 — Difference mode clears to BLACK.** In diff the engine clears to `--canvas-diff` (black in both
  themes), draws **only `reference` layers**, and composites the float with `'difference'`. Where the
  field does not cover the tile the destination is black, so "no reference here" reads as "no difference".
- **R14 — Esc does not kill the sweep.** Escape clears the selection/ghosts and reports `onSelect(null)`;
  it **does not touch the cursor**. Your `onSelect` must ignore `null` (see the snippet).
- **R18 — no per-tile tone.** The engine never sets `ctx.filter`; tiles arrive server-tone-mapped. Never
  add one, or Difference mode becomes meaningless.
- **R19 — top-left corners.** Positions are the tile's top-left; the engine adds `half` only for centre
  math (labels, centre-on).
- **R20 — layered, ~6 ms/frame.** `setTile` (one) appends/repairs; `setTiles` (all) rebakes once
  (~257 ms). **NEVER call `setTiles` for a single-tile change.** Read `handle.stats().ms` for the status
  bar's `ms/frame`; ~90 ms means something is rebaking every frame.

### Bitmaps, the cache key, and the prefetch trap

The viewer caches **pixels** keyed by the **`src` URL**. It caches **no match results** — so R21's
"prefetch keyed on trial number" trap does not exist here. Two consequences for you:

- **Bake your cache-buster into the URL** (`?v={session_nonce}.{tone_version}`). The same URL must never
  map to different bytes (R31/R32); changing it re-fetches. Call `handle.clearBitmapCache()` on a
  session/run change to free memory.
- Prefetch the next tile's **pixels** with `handle.preload([url])` while the server matches it — that is
  pixels only and safe. The **match** prefetch (the POST you throw away) stays entirely yours (R21).

---

## API surface (`ViewerHandle`)

`setTiles` · `setTile` · `getTile` · `setCursor` · `getCursor` · `fadeIn` · `replayFade` ·
`setDifference` · `isDifference` · `setFloatAlpha` · `getFloatAlpha` · `setLayerVisible` ·
`setLayerAlpha` · `layerPlacedCount` · `showAlternatives` · `clearAlternatives` · `setSelection` ·
`getSelection` · `nudge` · `setGrid` · `fit` · `oneToOne` · `zoomBy` · `centreOn` · `reveal` ·
`screenToWorld` · `worldToScreen` · `handleKey` · `preload` · `clearBitmapCache` · `stats` ·
`resetStats` · `redraw` · `resize` · `view`.

Full types and per-method contracts are in [`types.ts`](./types.ts). Tests: `__tests__/` (camera math,
feather ramp, key map, and the engine's model/attribute/keyboard contract). The pixel-level rulings
(§3.5 black clear, R13.4) are Playwright's — they need a real GPU compositor and the assembled feature.
