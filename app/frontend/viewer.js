/* Camea Mosaic Builder — the canvas / viewer.
 *
 * OWNER: agent 4 (with style.css). Nobody else edits this file.
 * CONTRACT: app/API.md §5 (pixels), §6 (tone), §15 (front-end obligations).
 *
 * THE BOUNDARY — read this before writing a line, agents 4 and 5.
 * ---------------------------------------------------------------
 *   viewer.js (this file)  owns:  the canvas, the camera (pan/zoom), the LAYERED background,
 *                                 the tile-bitmap cache, the fade animation, Difference mode,
 *                                 hit-testing and the raw pointer/drag gestures.
 *                          It knows NOTHING about A/E/Space, the anchor field, the API, or undo.
 *
 *   sweep.js  (agent 5)    owns:  the document (tile states + positions), the undo/redo stack,
 *                                 the keyboard map, every fetch() call, the prefetch, the panels.
 *                          It DRIVES the viewer through the methods below and listens to its
 *                          callbacks. It NEVER reaches into the viewer's canvases.
 *
 * They talk through exactly one object — `window.Viewer` — and the callbacks it invokes.
 *
 *
 * 🔴 LAYERED CANVAS — WHAT THIS FILE ACTUALLY DOES (and why it is not the bench's loop)
 * -----------------------------------------------------------------------------------
 * The bench (utils/artifact/template.html:834) is immediate-mode: it redraws all 312 tiles every
 * frame. Measured: 89.5 ms/frame at 1:1 zoom = 10 fps. The 1-second fade would be a SLIDESHOW.
 *
 * Here, tiles live in TWO offscreen WORLD-SPACE canvases, baked at native 1:1 resolution:
 *
 *     L_anchor      every `anchored` tile          drawn at alpha 1.00  (BOTTOM layer)
 *     L_unverified  every `unverified` tile        drawn at alpha 0.55  (above it)
 *
 * A frame is then exactly: fill + drawImage(L_anchor) + drawImage(L_unverified)
 *                          + ONE tile (the cursor / the fading tile) + vector chrome.
 *
 * Tiles are added to a layer INCREMENTALLY (one drawImage into the offscreen canvas, ~0.1 ms).
 * Removing one is a local repair — clip to its rect, clear, redraw only the neighbours that
 * overlap it — never a full rebake. A full rebake (`bakeBackground`) happens only on undo, a
 * tone change, or `setTiles`.
 *
 * The tile under judgement is FLOATING: it is deliberately kept OUT of both layers, so it can
 * fade, be dragged, and be differenced without touching a baked pixel.
 *
 * MEASURED, IN CHROME WITH GPU COMPOSITING DISABLED (the worst case), 312 real tiles:
 *     bench immediate-mode ...... 89.5 ms/frame   (10 fps)
 *     this file ................. see app/frontend — reported in the build report; < 16.7 ms.
 *
 * WebGL/WebGPU would take 1.4 ms -> 0.1 ms: zero perceived gain (you cannot draw faster than the
 * monitor refreshes) for a second renderer to maintain. We are not doing it.
 *
 *
 * PORTED FROM THE BENCH (2,149 lines in which the user authored all three ground truths):
 *   * the pan / zoom / marquee camera (template.html:919-1014), smoothing off above 2x zoom;
 *   * anchors forced to the BOTTOM layer (:834);
 *   * `reveal()` — pan (never zoom) a newly placed tile back on screen (:744);
 *   * the camera half of the keyboard map (F fit, 0 = 1:1, D = Difference, arrows nudge).
 * Replaced: ONLY the immediate-mode render loop.
 *
 *
 * ⚠️ POSITIONS ARE TOP-LEFT CORNERS, NOT CENTRES. Every marker, label or crosshair adds +256.
 *    Off-by-256 is the classic bug in this project. Search this file for `HALF` — every one of
 *    those is a deliberate +256.
 * ⚠️ THE TONE WINDOW IS GLOBAL. Tiles arrive from the server already flat-fielded and windowed
 *    (`GET /api/tile/{trial}.png?v={toneVersion}`). NEVER apply a per-tile brightness/contrast in
 *    JS, not even to a thumbnail: overlapping tiles would disagree in tone and that DESTROYS the
 *    Difference-mode check the whole verification loop depends on. There is no filter/ctx.filter
 *    call anywhere in this file, and there must never be one.
 */
'use strict';

window.Viewer = (function () {

  const TILE = 512;
  const HALF = TILE / 2;   // +256. The ONLY reason this constant exists: top-left -> centre.
  const FADE_MS = 1000;    // transparent -> opaque. Do not shorten it "to feel snappier".

  const MAX_LAYER_DIM = 16384;   // canvas hard limit in Chrome; past it we fall back to immediate mode
  const NMS_LABEL_PX = 48;       // don't paint a trial label on a tile smaller than this on screen

  /** Tile draw styles, one per state (API.md §2). The dimming is what tells the user, at a glance,
   *  which tiles are still outstanding.
   *    anchored   1.00 alpha, BOTTOM layer, baked into the background canvas
   *    unverified 0.55 alpha + a dashed outline, drawn ABOVE the background, never baked
   *    unplaced   not drawn
   *    excluded   not drawn
   *
   *  ONE deliberate exception: the tile currently under judgement (the CURSOR) is drawn at full
   *  opacity whatever its state — it is the thing being looked at, and the 1 s fade ends OPAQUE.
   *  The 0.55 dimming applies to the *field* of not-yet-judged tiles, which is what it is for.
   */
  const STYLE = {
    anchored:   { alpha: 1.00, outline: null },
    unverified: { alpha: 0.55, outline: 'dashed' },
    unplaced:   null,
    excluded:   null,
  };

  const PLACED = { anchored: 1, unverified: 1 };

  // ---------------------------------------------------------------------------------------
  // state
  // ---------------------------------------------------------------------------------------
  let canvas = null, ctx = null;
  let apiBase = '';
  let toneVersion = 0;
  let cb = {};                       // the callbacks handed in at mount()

  let cssW = 0, cssH = 0, dpr = 1;
  const view = { scale: 1, tx: 0, ty: 0 };

  const tiles   = new Map();         // trial -> {trial, state, x, y}   (x/y null when not placed)
  const bitmaps = new Map();         // trial -> ImageBitmap
  const pendingBmp = new Map();      // trial -> Promise

  let cursor = null;                 // the tile under judgement. ALWAYS floating (never baked).
  let dragTrial = null;              // the tile being dragged. Also floating.
  let fade = null;                   // {id, trial, t0, resolve}
  let fadeSeq = 0;
  let diff = false;                  // Difference mode
  let alts = null;                   // {trial, candidates:[{rank,x,y,ncc,npix}]}
  const sel = new Set();             // marquee / click selection
  let marquee = null;
  let showGrid = false, showLabels = false, showOutlines = true;
  let mounted = false;

  // ---------------------------------------------------------------------------------------
  // theme tokens — the canvas is painted imperatively so it cannot inherit a CSS theme flip
  // ---------------------------------------------------------------------------------------
  let T = {};
  const cssVar = (n, d) => {
    const v = getComputedStyle(document.documentElement).getPropertyValue(n).trim();
    return v || d;
  };
  function readTheme() {
    T = {
      canvas:     cssVar('--canvas', '#0b0d10'),
      grid:       cssVar('--grid', '#2a3038'),
      faint:      cssVar('--faint', '#5b6472'),
      anchored:   cssVar('--c-anchored', '#6ee7a8'),
      unverified: cssVar('--c-unverified', '#f5c451'),
      diverted:   cssVar('--c-diverted', '#e879f9'),
      cursorC:    cssVar('--c-cursor', '#60a5fa'),
      alt:        cssVar('--c-alt', '#a78bfa'),
      thin:       cssVar('--c-thin-margin', '#f87171'),
      marquee:    cssVar('--marquee', '#60a5fa'),
      ink:        cssVar('--ink', '#e6eaf0'),
    };
    draw();
  }

  // ---------------------------------------------------------------------------------------
  // ⭐ THE LAYERS.  A layer is one offscreen canvas in WORLD space at native 1:1 resolution.
  //    (ox, oy) is the world position of its own pixel (0, 0).
  // ---------------------------------------------------------------------------------------
  function newLayer(name) {
    const cv = document.createElement('canvas');
    cv.width = cv.height = 1;
    return {
      name,
      cv,
      g: cv.getContext('2d', { alpha: true, willReadFrequently: false }),
      ox: 0, oy: 0, w: 0, h: 0,
      members: new Set(),   // trials that BELONG in this layer (bitmap may not have arrived yet)
      drawn: new Set(),     // trials actually painted into it
      overflow: false,      // true if the bbox blew past MAX_LAYER_DIM -> immediate-mode fallback
    };
  }
  const L_anchor = newLayer('anchored');
  const L_unver  = newLayer('unverified');
  const LAYERS = [L_anchor, L_unver];

  const layerFor = (state) => (state === 'anchored' ? L_anchor : state === 'unverified' ? L_unver : null);

  /** A tile is FLOATING (kept out of every layer, drawn individually on top) when it is the
   *  cursor, the tile being dragged, or the tile currently fading in. */
  const isFloat = (t) => t === cursor || t === dragTrial || (fade !== null && fade.trial === t);

  const isPlaced = (tile) => !!(tile && PLACED[tile.state] && tile.x != null && tile.y != null);

  /** Grow the layer's canvas so world rect (x, y, 512, 512) fits. Copies the old pixels across —
   *  it never rebakes. */
  function layerGrow(L, x, y) {
    const nx0 = Math.floor(Math.min(L.w ? L.ox : x, x));
    const ny0 = Math.floor(Math.min(L.h ? L.oy : y, y));
    const nx1 = Math.ceil(Math.max(L.w ? L.ox + L.w : x + TILE, x + TILE));
    const ny1 = Math.ceil(Math.max(L.h ? L.oy + L.h : y + TILE, y + TILE));
    const nw = nx1 - nx0, nh = ny1 - ny0;
    if (nw === L.w && nh === L.h && nx0 === L.ox && ny0 === L.oy) return true;
    if (nw > MAX_LAYER_DIM || nh > MAX_LAYER_DIM) { L.overflow = true; return false; }

    const old = L.cv, ow = L.w, oh = L.h, oox = L.ox, ooy = L.oy;
    const cv = document.createElement('canvas');
    cv.width = nw; cv.height = nh;
    const g = cv.getContext('2d');
    if (ow && oh) g.drawImage(old, oox - nx0, ooy - ny0);
    L.cv = cv; L.g = g; L.ox = nx0; L.oy = ny0; L.w = nw; L.h = nh;
    return true;
  }

  /** Paint one tile into a layer. ~0.1 ms. This is the `A`-press path. */
  function layerAdd(L, trial) {
    if (!L) return;
    L.members.add(trial);
    if (L.drawn.has(trial) || L.overflow) return;
    const t = tiles.get(trial);
    if (!isPlaced(t)) return;
    const bmp = bitmaps.get(trial);
    if (!bmp) { ensureBitmap(trial); return; }        // painted when the bitmap lands
    if (!layerGrow(L, t.x, t.y)) return;
    L.g.globalAlpha = 1;
    L.g.globalCompositeOperation = 'source-over';
    L.g.drawImage(bmp, t.x - L.ox, t.y - L.oy, TILE, TILE);
    L.drawn.add(trial);
  }

  /** Take one tile back OUT of a layer without rebaking it: clip to the tile's rect, clear it,
   *  and redraw only the members that overlap that rect. Typically <10 drawImages. */
  function layerRemove(L, trial) {
    if (!L || !L.members.has(trial)) return;
    const t = tiles.get(trial);
    const was = L.drawn.has(trial);
    L.members.delete(trial);
    L.drawn.delete(trial);
    if (!was || L.overflow || !t || t.x == null) return;

    const x = t.x - L.ox, y = t.y - L.oy;
    const g = L.g;
    g.save();
    g.beginPath();
    g.rect(x, y, TILE, TILE);
    g.clip();
    g.clearRect(x, y, TILE, TILE);
    g.globalAlpha = 1;
    g.globalCompositeOperation = 'source-over';
    const order = [...L.drawn].sort((a, b) => a - b);
    for (const o of order) {
      const ot = tiles.get(o);
      if (!isPlaced(ot)) continue;
      if (ot.x + TILE <= t.x || ot.x >= t.x + TILE || ot.y + TILE <= t.y || ot.y >= t.y + TILE) continue;
      const bmp = bitmaps.get(o);
      if (bmp) g.drawImage(bmp, ot.x - L.ox, ot.y - L.oy, TILE, TILE);
    }
    g.restore();
  }

  function removeFromLayers(trial) {
    for (const L of LAYERS) layerRemove(L, trial);
  }

  /** Put `trial` in exactly the layer its state says it belongs in (or none, if it floats). */
  function syncTileLayer(trial) {
    const t = tiles.get(trial);
    const want = (isPlaced(t) && !isFloat(trial)) ? layerFor(t.state) : null;
    for (const L of LAYERS) if (L !== want && L.members.has(trial)) layerRemove(L, trial);
    if (want && !want.members.has(trial)) layerAdd(want, trial);
  }

  /** Full rebake of both layers.
   *
   *  ⚠️ MEASURED AT 257 ms for 312 tiles (two fresh ~8.7 Mpx canvases + 312 drawImage). That is
   *  fine — and ONLY fine — because it happens once per `setTiles` / undo / tone change, never in
   *  the render loop. AGENT 5: do NOT call `setTiles()` for a single-tile change. `setTile()` is
   *  0.2 ms (append) / 0.1 ms (local repair). Calling `setTiles()` on every keystroke would put a
   *  quarter-second stall on every `A` and hand you back the bug this file exists to prevent. */
  function bakeBackground() {
    for (const L of LAYERS) {
      L.members.clear(); L.drawn.clear(); L.overflow = false;
      L.ox = L.oy = L.w = L.h = 0;
      L.cv = document.createElement('canvas');
      L.cv.width = L.cv.height = 1;
      L.g = L.cv.getContext('2d');
    }
    // size each layer once, up front, so we never grow mid-bake
    for (const L of LAYERS) {
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity, n = 0;
      for (const t of tiles.values()) {
        if (!isPlaced(t) || isFloat(t.trial) || layerFor(t.state) !== L) continue;
        x0 = Math.min(x0, t.x); y0 = Math.min(y0, t.y);
        x1 = Math.max(x1, t.x + TILE); y1 = Math.max(y1, t.y + TILE);
        n++;
      }
      if (!n) continue;
      const w = Math.ceil(x1) - Math.floor(x0), h = Math.ceil(y1) - Math.floor(y0);
      if (w > MAX_LAYER_DIM || h > MAX_LAYER_DIM) { L.overflow = true; continue; }
      L.cv.width = w; L.cv.height = h;
      L.g = L.cv.getContext('2d');
      L.ox = Math.floor(x0); L.oy = Math.floor(y0); L.w = w; L.h = h;
    }
    const order = [...tiles.keys()].sort((a, b) => a - b);
    for (const trial of order) {
      const t = tiles.get(trial);
      if (!isPlaced(t) || isFloat(trial)) continue;
      layerAdd(layerFor(t.state), trial);
    }
    draw();
  }

  // ---------------------------------------------------------------------------------------
  // tile pixels — server-rendered, GLOBALLY tone-mapped 8-bit PNGs (API.md §5.1)
  // ---------------------------------------------------------------------------------------
  const tileUrl = (t) => `${apiBase}/api/tile/${t}.png?v=${toneVersion}`;

  function ensureBitmap(trial) {
    if (bitmaps.has(trial)) return Promise.resolve(bitmaps.get(trial));
    if (pendingBmp.has(trial)) return pendingBmp.get(trial);
    const p = (async () => {
      try {
        const r = await fetch(tileUrl(trial));
        if (!r.ok) throw new Error('HTTP ' + r.status);
        const bmp = await createImageBitmap(await r.blob());
        bitmaps.set(trial, bmp);
        const t = tiles.get(trial);
        if (isPlaced(t) && !isFloat(trial)) {
          const L = layerFor(t.state);
          if (L && L.members.has(trial)) layerAdd(L, trial);
        }
        draw();
        return bmp;
      } catch (e) {
        if (cb.onError) cb.onError(trial, e);
        return null;                        // render() simply skips a tile with no bitmap
      } finally {
        pendingBmp.delete(trial);
      }
    })();
    pendingBmp.set(trial, p);
    return p;
  }

  /** Warm the bitmap cache (the sweep prefetches tile N+1's PIXELS while the server matches it). */
  function preload(trials) { for (const t of trials) ensureBitmap(t); }

  // ---------------------------------------------------------------------------------------
  // camera
  // ---------------------------------------------------------------------------------------
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const screenToWorld = (sx, sy) => [(sx - view.tx) / view.scale, (sy - view.ty) / view.scale];
  const worldToScreen = (wx, wy) => [wx * view.scale + view.tx, wy * view.scale + view.ty];

  function bbox() {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity, n = 0;
    for (const t of tiles.values()) {
      if (!isPlaced(t)) continue;
      x0 = Math.min(x0, t.x); y0 = Math.min(y0, t.y);
      x1 = Math.max(x1, t.x + TILE); y1 = Math.max(y1, t.y + TILE);
      n++;
    }
    return n ? { x0, y0, x1, y1 } : null;
  }

  function fit() {
    const b = bbox();
    if (!b) return;
    const pad = 48;
    view.scale = clamp(Math.min((cssW - pad) / (b.x1 - b.x0), (cssH - pad) / (b.y1 - b.y0)), 0.02, 16);
    view.tx = cssW / 2 - ((b.x0 + b.x1) / 2) * view.scale;
    view.ty = cssH / 2 - ((b.y0 + b.y1) / 2) * view.scale;
    onView();
  }

  function zoomTo(scale, cx, cy) {
    const sx = cx == null ? cssW / 2 : cx;
    const sy = cy == null ? cssH / 2 : cy;
    const [wx, wy] = screenToWorld(sx, sy);
    view.scale = clamp(scale, 0.02, 16);
    view.tx = sx - wx * view.scale;
    view.ty = sy - wy * view.scale;
    onView();
  }
  const zoomBy = (k, cx, cy) => zoomTo(view.scale * k, cx, cy);

  /** `0` — 1:1, keeping the view centre put. */
  function oneToOne() { zoomTo(1, cssW / 2, cssH / 2); }

  /** Centre the camera on a tile's CENTRE (+256 — positions are top-left corners). */
  function centreOn(trial) {
    const t = tiles.get(trial);
    if (!isPlaced(t)) return;
    view.tx = cssW / 2 - (t.x + HALF) * view.scale;
    view.ty = cssH / 2 - (t.y + HALF) * view.scale;
    onView();
  }

  /** Bench :744 — pan (never zoom) a tile back on screen if it landed off the edge. The first
   *  tile of a fresh session gets a full fit instead. */
  function reveal(trial) {
    const t = tiles.get(trial);
    if (!isPlaced(t)) return;
    let nPlaced = 0;
    for (const q of tiles.values()) if (isPlaced(q)) nPlaced++;
    if (nPlaced <= 1) { view.scale = clamp(view.scale, 0.25, 2); centreOn(trial); return; }
    const [cx, cy] = worldToScreen(t.x + HALF, t.y + HALF);
    const m = 64;
    if (cx < m || cy < m || cx > cssW - m || cy > cssH - m) {
      view.tx += cssW / 2 - cx;
      view.ty += cssH / 2 - cy;
      onView();
    }
  }

  function onView() {
    if (cb.onView) cb.onView({ scale: view.scale, tx: view.tx, ty: view.ty });
    draw();
  }

  // ---------------------------------------------------------------------------------------
  // rendering
  // ---------------------------------------------------------------------------------------
  const perf = { ms: [], rafDt: [], last: 0, frames: 0 };
  let needsDraw = false;

  function draw() {
    if (!mounted || needsDraw) return;
    needsDraw = true;
    requestAnimationFrame(frame);
  }

  function frame(ts) {
    needsDraw = false;
    if (perf.last) push(perf.rafDt, ts - perf.last);
    perf.last = ts;
    const t0 = performance.now();
    render(ts);
    push(perf.ms, performance.now() - t0);
    perf.frames++;
    if (fade) draw();                     // the fade keeps the loop alive, and nothing else does
  }
  function push(a, v) { a.push(v); if (a.length > 240) a.shift(); }

  function resize() {
    const r = canvas.getBoundingClientRect();
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    cssW = Math.max(1, Math.round(r.width));
    cssH = Math.max(1, Math.round(r.height));
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
    draw();
  }

  function drawGrid() {
    const step = TILE * view.scale;
    if (step < 26) return;
    ctx.save();
    ctx.strokeStyle = T.grid; ctx.globalAlpha = 0.25; ctx.lineWidth = 1;
    ctx.beginPath();
    const x0 = view.tx % step, y0 = view.ty % step;
    for (let x = x0; x < cssW; x += step) { ctx.moveTo(Math.round(x) + 0.5, 0); ctx.lineTo(Math.round(x) + 0.5, cssH); }
    for (let y = y0; y < cssH; y += step) { ctx.moveTo(0, Math.round(y) + 0.5); ctx.lineTo(cssW, Math.round(y) + 0.5); }
    ctx.stroke();
    ctx.restore();
  }

  /** ⭐ ONE drawImage for a whole layer. This is the line that turns the bench's 312-drawImage
   *  loop into a constant-cost frame.
   *
   *  The SOURCE rect is clipped to what is actually on screen. At 1:1 zoom the layer is 2242x3831
   *  and the viewport shows ~1600x900 of it — handing the compositor the whole 8.7 Mpx image every
   *  frame costs real time for pixels nobody sees. Measured: 9.5 ms -> 2.6 ms/frame at 1:1.
   *  (Clipping is exact: the destination is derived from the clipped source, so the geometry is
   *  identical to the unclipped draw.) */
  function drawLayer(L, alpha) {
    if (L.overflow) { drawLayerImmediate(L, alpha); return; }
    if (!L.w || !L.h) return;

    // the viewport, in this layer's own pixel coordinates
    const [w0x, w0y] = screenToWorld(0, 0);
    const [w1x, w1y] = screenToWorld(cssW, cssH);
    let sx = Math.floor(w0x - L.ox) - 1, sy = Math.floor(w0y - L.oy) - 1;
    let ex = Math.ceil(w1x - L.ox) + 1, ey = Math.ceil(w1y - L.oy) + 1;
    sx = Math.max(0, sx); sy = Math.max(0, sy);
    ex = Math.min(L.w, ex); ey = Math.min(L.h, ey);
    const sw = ex - sx, sh = ey - sy;
    if (sw <= 0 || sh <= 0) return;                       // the layer is entirely off screen

    ctx.globalAlpha = alpha;
    ctx.drawImage(L.cv, sx, sy, sw, sh,
      (L.ox + sx) * view.scale + view.tx, (L.oy + sy) * view.scale + view.ty,
      sw * view.scale, sh * view.scale);
    ctx.globalAlpha = 1;
  }

  /** Fallback ONLY when a layer's bbox blew past the 16,384 px canvas limit (someone dragged a
   *  tile a mile away). Culled to the viewport, so it is still not the bench's loop. */
  function drawLayerImmediate(L, alpha) {
    ctx.globalAlpha = alpha;
    const s = TILE * view.scale;
    for (const trial of L.members) {
      const t = tiles.get(trial);
      const bmp = bitmaps.get(trial);
      if (!isPlaced(t) || !bmp) continue;
      const [sx, sy] = worldToScreen(t.x, t.y);
      if (sx > cssW || sy > cssH || sx + s < 0 || sy + s < 0) continue;
      ctx.drawImage(bmp, sx, sy, s, s);
    }
    ctx.globalAlpha = 1;
  }

  function fadeAlpha(ts) {
    if (!fade) return 1;
    const e = (ts || performance.now()) - fade.t0;
    if (e >= FADE_MS) return 1;
    return Math.max(0, e / FADE_MS);           // linear, transparent -> opaque. Honest and readable.
  }

  function floats() {
    const out = [];
    const seen = new Set();
    for (const t of [cursor, dragTrial, fade && fade.trial]) {
      if (t == null || seen.has(t)) continue;
      seen.add(t);
      if (isPlaced(tiles.get(t))) out.push(t);
    }
    // the fading tile goes LAST so it composites on top of everything, including the cursor
    out.sort((a, b) => (fade && a === fade.trial ? 1 : 0) - (fade && b === fade.trial ? 1 : 0));
    return out;
  }

  function render(ts) {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.globalCompositeOperation = 'source-over';
    ctx.globalAlpha = 1;

    // ⚠️ IN DIFFERENCE MODE THE CLEAR COLOUR MUST BE BLACK — it is not a style choice.
    // `difference` composites |tile - destination|. Where the anchor field does NOT cover the
    // tile, the destination IS the clear colour, so:
    //     black clear (0)   ->  |tile - 0|   = tile      the uncovered part just looks normal
    //     light clear (223) ->  |tile - 223| = INVERTED  the uncovered part is bright garbage
    // In the LIGHT theme --canvas is #dfe4ea (223), and the anchor field never covers the whole
    // tile — so without this line, half of what the user is looking at in the one check the whole
    // verification loop depends on would be a photographic negative of the tile. Black is the only
    // destination for which "no reference here" reads as "no difference here".
    ctx.fillStyle = diff ? '#000000' : T.canvas;
    ctx.fillRect(0, 0, cssW, cssH);
    if (showGrid && !diff) drawGrid();

    ctx.imageSmoothingEnabled = view.scale < 2;    // above 2x, show the real pixels

    // ---- the two baked layers: exactly two drawImage calls -----------------------------
    drawLayer(L_anchor, 1);
    // ⚠️ In Difference mode the destination MUST be the ANCHOR FIELD ALONE. The difference is
    // read against a *trusted* reference; an `unverified` tile is by definition not one, and
    // blending it in at 55 % would muddy the very pixels the user is judging. So the unverified
    // layer is not drawn in Difference mode — which also means: if nothing around the cursor is
    // anchored yet, the tile differences against black and simply looks like itself. That is the
    // honest answer — you have nothing certified to check it against.
    if (!diff) drawLayer(L_unver, STYLE.unverified.alpha);

    // ---- the floating tile(s): the cursor and/or the one fading in ----------------------
    const fa = fadeAlpha(ts);
    const s = TILE * view.scale;
    for (const trial of floats()) {
      const t = tiles.get(trial);
      const bmp = bitmaps.get(trial);
      if (!bmp) continue;
      const isFading = fade && fade.trial === trial;
      let a = 1;                                   // the tile under judgement is always full strength
      if (isFading) a = fa;
      const [sx, sy] = worldToScreen(t.x, t.y);
      // ⭐ Difference mode: |tile - background| in the overlap. FREE — one composite op, +0.6 ms.
      // MEASURED on 312 real tiles (trial 91 against the full anchored field): aligned, the blobs
      // and the electrode grid CANCEL and the overlap goes smooth; 40 px off, every blob grows a
      // bright/dark echo and the grid doubles. That doubling is the signal, and it is unmistakable
      // by eye. (Do NOT try to reduce it to a mean — the mean of |diff| is dominated by a constant
      // illumination offset between the two frames and moves only 74.3 -> 75.9 across a 40 px
      // error. The STRUCTURE is the evidence, which is exactly why this is a human's check and not
      // a metric's.)
      // ⚠️ It only works because the tone window is GLOBAL (API.md §6). A per-tile stretch makes
      // overlapping tiles disagree in brightness and the difference image becomes meaningless.
      ctx.globalCompositeOperation = diff ? 'difference' : 'source-over';
      ctx.globalAlpha = a;
      ctx.drawImage(bmp, sx, sy, s, s);
    }
    ctx.globalCompositeOperation = 'source-over';
    ctx.globalAlpha = 1;

    drawChrome();
  }

  /** Vector chrome: outlines, the cursor box, the alternatives, the marquee. All culled to the
   *  viewport, and the 312 unverified outlines are ONE Path2D + ONE stroke — not 312 strokes. */
  function drawChrome() {
    const s = TILE * view.scale;
    const vis = (t) => {
      const [sx, sy] = worldToScreen(t.x, t.y);
      return !(sx > cssW || sy > cssH || sx + s < 0 || sy + s < 0);
    };

    // ⭐ unverified: 55 % opacity + a DASHED OUTLINE. This is what says "still outstanding", and
    // the sweep's whole "deferring a tile must never stall you" rests on a deferred tile LOOKING
    // deferred (API.md §2).
    //
    // The outline's alpha RAMPS with the tile's on-screen size, and that is deliberate: right
    // after a build there are 312 unverified tiles, and at fit zoom 312 dashed boxes is a cage of
    // noise that hides the very mosaic you are checking. The two signals divide the labour —
    // at OVERVIEW zoom the 55 % DIMMING carries the state; at WORKING zoom the DASH does.
    // Neither is ever absent; the dash just stops shouting when it cannot be read.
    // `Viewer.setOutlines(false)` kills them outright.
    //
    // ⭐ AND THE DIVERTED ONES GET THEIR OWN COLOUR (his fallback ruling, 2026-07-12). A tile the app
    // placed at the SOLVER's position — because the match was not confident AND disagreed with the
    // solver — was being drawn IDENTICALLY to a confidently-matched one. In the defer flow that is
    // almost every tile on the canvas sitting on a position the matcher never agreed with, and the
    // only way to find out was to put the cursor on it. Two Path2Ds, two strokes, same single pass.
    const oAlpha = showOutlines ? Math.max(0, Math.min(1, (s - 64) / 160)) * 0.8 : 0;
    if (oAlpha > 0.02) {
      const p = new Path2D();
      const pd = new Path2D();            // the diverted ones
      let n = 0, nd = 0;
      for (const t of tiles.values()) {
        if (t.state !== 'unverified' || !isPlaced(t) || t.trial === cursor || sel.has(t.trial)) continue;
        if (!vis(t)) continue;
        const [sx, sy] = worldToScreen(t.x, t.y);
        if (t.diverted) { pd.rect(Math.round(sx) + 0.5, Math.round(sy) + 0.5, s - 1, s - 1); nd++; }
        else            { p.rect(Math.round(sx) + 0.5, Math.round(sy) + 0.5, s - 1, s - 1); n++; }
      }
      if (n || nd) {
        ctx.save();
        ctx.globalAlpha = oAlpha;
        ctx.lineWidth = 1;
        if (n) {
          ctx.setLineDash([6, 4]);
          ctx.strokeStyle = T.unverified;
          ctx.stroke(p);                  // ONE stroke for all 312 — not 312 strokes
        }
        if (nd) {
          ctx.setLineDash([2, 3]);        // a TIGHTER dash, so it reads even in monochrome
          ctx.strokeStyle = T.diverted;
          ctx.lineWidth = 1.5;
          ctx.globalAlpha = Math.min(1, oAlpha + 0.2);
          ctx.stroke(pd);
        }
        ctx.restore();
      }
    }

    // selection
    if (sel.size && s > 6) {
      ctx.save();
      ctx.strokeStyle = T.marquee; ctx.lineWidth = 2; ctx.globalAlpha = 1;
      const p = new Path2D();
      for (const trial of sel) {
        const t = tiles.get(trial);
        if (!isPlaced(t) || !vis(t)) continue;
        const [sx, sy] = worldToScreen(t.x, t.y);
        p.rect(Math.round(sx) + 0.5, Math.round(sy) + 0.5, s - 1, s - 1);
      }
      ctx.stroke(p);
      ctx.restore();
    }

    // the tile under judgement
    if (cursor != null) {
      const t = tiles.get(cursor);
      if (isPlaced(t) && vis(t)) {
        const [sx, sy] = worldToScreen(t.x, t.y);
        ctx.save();
        ctx.strokeStyle = T.cursorC; ctx.lineWidth = 2; ctx.globalAlpha = 1;
        ctx.strokeRect(Math.round(sx) + 0.5, Math.round(sy) + 0.5, s - 1, s - 1);
        if (s > NMS_LABEL_PX) label(String(cursor), sx, sy, T.cursorC, '#08111f');
        ctx.restore();
      }
    }

    // ranked alternatives from POST /api/match/anchor (§7.1) — ghost boxes at WORLD top-left,
    // label at the CENTRE (+256).
    if (alts && alts.candidates && alts.candidates.length) {
      ctx.save();
      ctx.setLineDash([5, 5]);
      ctx.font = '600 12px ui-monospace, Consolas, monospace';
      ctx.textBaseline = 'middle';
      for (const c of alts.candidates) {
        if (c.rank === 0) continue;                       // rank 0 IS the placement; don't ghost it
        const [sx, sy] = worldToScreen(c.x, c.y);
        if (sx > cssW || sy > cssH || sx + s < 0 || sy + s < 0) continue;
        ctx.strokeStyle = T.alt; ctx.globalAlpha = 0.9; ctx.lineWidth = 1.5;
        ctx.strokeRect(sx + 0.5, sy + 0.5, s - 1, s - 1);
        const [lx, ly] = worldToScreen(c.x + HALF, c.y + HALF);   // ⚠️ +256: centre, not corner
        const txt = `#${c.rank}  ${c.ncc.toFixed(3)}`;
        const w = ctx.measureText(txt).width + 12;
        ctx.globalAlpha = 0.92;
        ctx.fillStyle = 'rgba(0,0,0,.7)';
        ctx.fillRect(lx - w / 2, ly - 10, w, 20);
        ctx.fillStyle = T.alt;
        ctx.textAlign = 'center';
        ctx.fillText(txt, lx, ly + 1);
        ctx.textAlign = 'left';
      }
      ctx.restore();
    }

    if (showLabels && s > NMS_LABEL_PX) {
      ctx.save();
      ctx.font = '600 11px ui-monospace, Consolas, monospace';
      for (const t of tiles.values()) {
        if (!isPlaced(t) || !vis(t) || t.trial === cursor) continue;
        const [sx, sy] = worldToScreen(t.x, t.y);
        label(String(t.trial), sx, sy,
              t.state === 'anchored' ? T.anchored : (t.diverted ? T.diverted : T.unverified),
              '#08111f');
      }
      ctx.restore();
    }

    if (marquee) {
      const { x0, y0, x1, y1 } = marquee;
      ctx.save();
      ctx.strokeStyle = T.marquee; ctx.fillStyle = T.marquee;
      ctx.globalAlpha = 0.12; ctx.fillRect(x0, y0, x1 - x0, y1 - y0);
      ctx.globalAlpha = 1; ctx.setLineDash([4, 3]);
      ctx.strokeRect(x0 + 0.5, y0 + 0.5, x1 - x0, y1 - y0);
      ctx.restore();
    }
  }

  function label(txt, sx, sy, bg, fg) {
    ctx.font = '600 11px ui-monospace, Consolas, monospace';
    ctx.textBaseline = 'alphabetic';
    ctx.textAlign = 'left';
    const w = ctx.measureText(txt).width + 10;
    ctx.globalAlpha = 1;
    ctx.fillStyle = bg;
    ctx.fillRect(sx, sy, w, 16);
    ctx.fillStyle = fg;
    ctx.fillText(txt, sx + 5, sy + 12);
  }

  // ---------------------------------------------------------------------------------------
  // the public model API — sweep.js drives the viewer through exactly these
  // ---------------------------------------------------------------------------------------

  /** Replace the whole model. `tiles` = {trial: {state, x, y}}. Rebakes the background. */
  function setTiles(model) {
    tiles.clear();
    for (const k of Object.keys(model || {})) {
      const trial = Number(k);
      const t = model[k] || {};
      tiles.set(trial, {
        trial,
        state: t.state || 'unplaced',
        // ⭐ NOT a state — a fact about an `unverified` tile: its position came from the SOLVER, not
        // from the matcher (the fallback ruling, 2026-07-12). It changes NO layer and NO alpha (a
        // diverted tile is unverified, and it is drawn as one); it changes only the OUTLINE COLOUR,
        // which is the only thing on the canvas that can say so.
        diverted: !!t.diverted,
        x: (t.x == null ? null : +t.x),
        y: (t.y == null ? null : +t.y),
      });
    }
    for (const t of tiles.values()) if (isPlaced(t)) ensureBitmap(t.trial);
    bakeBackground();
  }

  /** One tile changed. Cheap: an `A` press is one drawImage into the offscreen canvas (0.1 ms);
   *  it never rebakes. */
  function setTile(trial, t) {
    trial = Number(trial);
    const state = (t && t.state) || 'unplaced';
    const placed = PLACED[state] && t && t.x != null && t.y != null;
    const cur = tiles.get(trial);
    // a position/state change means the old baked pixels are stale -> local repair, then re-add
    if (cur) removeFromLayers(trial);
    tiles.set(trial, {
      trial, state,
      diverted: !!(t && t.diverted),        // see setTiles: outline colour only, never a layer
      x: placed ? +t.x : null,
      y: placed ? +t.y : null,
    });
    if (placed) {
      ensureBitmap(trial);
      if (!isFloat(trial)) layerAdd(layerFor(state), trial);
    }
    draw();
  }

  function getTile(trial) {
    const t = tiles.get(Number(trial));
    return t ? { trial: t.trial, state: t.state, diverted: !!t.diverted, x: t.x, y: t.y } : null;
  }

  /** ⭐ Flip the DIVERTED flag (the tile is on the solver's position, not the matcher's). It is
   *  learned a beat AFTER the placement — `recordPlacement()` decides it, and on a divert it then
   *  goes and re-measures the NCC — so it needs its own setter. Deliberately NOT `setTile`: the
   *  flag touches the OUTLINE ONLY. No layer, no bake, no bitmap, no state change. Just a redraw. */
  function setDiverted(trial, on) {
    const t = tiles.get(Number(trial));
    if (!t || !!t.diverted === !!on) return;
    t.diverted = !!on;
    draw();
  }

  /** ⭐⭐ THE FADE. Place `trial` at (x, y) and fade it transparent -> opaque over FADE_MS.
   *  Watching the tile materialise on top of the anchored background is HOW THE USER SEES whether
   *  it lines up. Returns a Promise that resolves when the fade ends (or is superseded). */
  function fadeIn(trial, x, y) {
    trial = Number(trial);
    if (x != null && y != null) {
      const cur = tiles.get(trial);
      const state = (cur && PLACED[cur.state]) ? cur.state : 'unverified';
      setTile(trial, { state, x, y });
    }
    const t = tiles.get(trial);
    if (!isPlaced(t)) return Promise.resolve(false);

    if (fade) { const f = fade; fade = null; syncTileLayer(f.trial); f.resolve(false); }
    removeFromLayers(trial);                         // it floats for the duration of the fade
    ensureBitmap(trial);
    return new Promise((resolve) => {
      // ⚠️ The tick is keyed on a unique fade ID, not on the trial. `R` (replay) restarts the fade
      // on the SAME trial, so a trial-keyed guard would let the superseded tick keep running and
      // fire `onFadeEnd` TWICE — which, on the sweep side, is a double autosave and a double
      // advance. Ask me how I know.
      const id = ++fadeSeq;
      fade = { id, trial, t0: performance.now(), resolve };
      draw();
      const tick = () => {
        if (!fade || fade.id !== id) return;         // superseded: this tick is dead
        if (performance.now() - fade.t0 >= FADE_MS) {
          const f = fade; fade = null;
          syncTileLayer(f.trial);                    // back into its layer, unless it is the cursor
          draw();
          if (cb.onFadeEnd) cb.onFadeEnd(f.trial);
          f.resolve(true);
          return;
        }
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
  }

  /** `R` — replay the fade on the tile under judgement. The user will want this constantly. */
  function replayFade() {
    const trial = (fade && fade.trial) != null ? fade.trial : cursor;
    if (trial == null) return Promise.resolve(false);
    const t = tiles.get(trial);
    if (!isPlaced(t)) return Promise.resolve(false);
    return fadeIn(trial, t.x, t.y);
  }

  /** `D` — Difference mode. `globalCompositeOperation = 'difference'` on the floating tile:
   *  |tile - background| in the overlap, and misalignment shows as bright doubling.
   *  ⚠️ It is only meaningful because the tone window is GLOBAL. */
  function setDifference(on) {
    diff = !!on;
    if (cb.onDifference) cb.onDifference(diff);
    draw();
  }
  const isDifference = () => diff;

  /** Draw the ranked alternatives from POST /api/match/anchor as ghost rectangles + their NCC.
   *  `candidates` = [{rank, x, y, ncc, npix}] — WORLD TOP-LEFT positions, already converted by the
   *  server (§3.3). Nothing is added to or subtracted from them. Clicking one calls
   *  opts.onAlternativePick(trial, candidate). */
  function showAlternatives(trial, candidates) {
    alts = { trial: Number(trial), candidates: (candidates || []).slice() };
    draw();
  }
  function clearAlternatives() { alts = null; draw(); }

  /** The tile currently under judgement: floats above the layers, full opacity, draggable. */
  function setCursor(trial) {
    const t = trial == null ? null : Number(trial);
    if (t === cursor) return;
    const prev = cursor;
    cursor = null;
    if (prev != null) syncTileLayer(prev);          // the tile he just judged drops into its layer
    cursor = t;
    if (t != null) removeFromLayers(t);             // and the new one is lifted out of it
    if (t != null) ensureBitmap(t);
    clearAlternatives();
    draw();
  }
  const getCursor = () => cursor;

  /** Selection (marquee / click). The sweep does not need it, but the bench's multi-select is
   *  useful for a bulk nudge and it is 20 lines. */
  function setSelection(trials) {
    sel.clear();
    for (const t of (trials || [])) sel.add(Number(t));
    draw();
  }
  const getSelection = () => [...sel];

  /** Arrow-key nudge, in WORLD px (1, or 10 with Shift). Moves the cursor tile, or the selection
   *  if there is one. Reports through onDragEnd so sweep can fold it into ONE undo step. */
  function nudge(dx, dy) {
    const targets = sel.size ? [...sel] : (cursor != null ? [cursor] : []);
    if (!targets.length) return false;
    for (const trial of targets) {
      const t = tiles.get(trial);
      if (!isPlaced(t)) continue;
      const nx = t.x + dx, ny = t.y + dy;
      if (isFloat(trial)) { t.x = nx; t.y = ny; }
      else { removeFromLayers(trial); t.x = nx; t.y = ny; layerAdd(layerFor(t.state), trial); }
      if (cb.onDragEnd) cb.onDragEnd(trial, t.x, t.y, { via: 'nudge' });
    }
    draw();
    return true;
  }

  /** Drop every cached bitmap and re-fetch with the new `?v=`. Call on a tone change (§6.2) **and on
   *  every session open / run change** — sweep.js does both.
   *
   *  ⚠️ `v` IS AN OPAQUE STRING, `{session_nonce}.{tone_version}` — NOT the tone version alone. The
   *  tone version resets to 1 on every open, so a bare version could be *unchanged* across two
   *  different datasets while the pixels behind `/api/tile/{t}.png?v=1` were completely different —
   *  and `bitmaps` (keyed on the trial number) would keep the previous dataset's ImageBitmaps
   *  because this function early-returns when the value has not changed. The nonce makes "unchanged"
   *  mean what it says. */
  function setToneVersion(v) {
    if (v === toneVersion) return;
    toneVersion = v;
    for (const b of bitmaps.values()) { if (b.close) b.close(); }
    bitmaps.clear();
    pendingBmp.clear();
    for (const t of tiles.values()) if (isPlaced(t)) ensureBitmap(t.trial);
    bakeBackground();
  }

  /** Perf counter for the dev overlay: ms/frame, averaged. It MUST read ~6 ms, not ~90 ms. If it
   *  reads 90, the background is being rebaked every frame — that is the bug this file exists to
   *  prevent. */
  function stats() {
    const q = (a, p) => {
      if (!a.length) return 0;
      const s = [...a].sort((x, y) => x - y);
      return s[Math.min(s.length - 1, Math.floor(p * s.length))];
    };
    const mean = (a) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0);
    let anchored = 0, unverified = 0, placed = 0;
    for (const t of tiles.values()) {
      if (t.state === 'anchored') anchored++;
      else if (t.state === 'unverified') unverified++;
      if (isPlaced(t)) placed++;
    }
    return {
      ms: +mean(perf.ms).toFixed(2),
      msMedian: +q(perf.ms, 0.5).toFixed(2),
      msP95: +q(perf.ms, 0.95).toFixed(2),
      msMax: +Math.max(0, ...perf.ms).toFixed(2),
      rafDt: +mean(perf.rafDt).toFixed(2),
      fps: perf.rafDt.length ? +(1000 / mean(perf.rafDt)).toFixed(1) : 0,
      frames: perf.frames,
      samples: perf.ms.length,
      tiles: tiles.size, placed, anchored, unverified,
      bitmaps: bitmaps.size,
      layer: {
        anchored: { w: L_anchor.w, h: L_anchor.h, n: L_anchor.drawn.size, overflow: L_anchor.overflow },
        unverified: { w: L_unver.w, h: L_unver.h, n: L_unver.drawn.size, overflow: L_unver.overflow },
      },
      scale: +view.scale.toFixed(4),
      fading: !!fade,
      difference: diff,
    };
  }
  function resetStats() { perf.ms.length = 0; perf.rafDt.length = 0; perf.frames = 0; perf.last = 0; }

  // ---------------------------------------------------------------------------------------
  // hit-testing + pointer (ported from the bench, :919-1014)
  // ---------------------------------------------------------------------------------------
  /** Priority: an alternative ghost, then the cursor tile, then unverified, then anchored.
   *  Anchors ARE hittable — a drag never demotes an anchor (API.md §2.1), the user is correcting
   *  it — but they lose every tie, because they are the bottom layer. */
  function hit(sx, sy) {
    const [wx, wy] = screenToWorld(sx, sy);
    const inside = (t) => wx >= t.x && wx < t.x + TILE && wy >= t.y && wy < t.y + TILE;
    if (cursor != null) { const t = tiles.get(cursor); if (isPlaced(t) && inside(t)) return cursor; }
    let best = null, bestRank = 9;
    for (const t of tiles.values()) {
      if (!isPlaced(t) || !inside(t)) continue;
      const rank = t.state === 'unverified' ? 1 : 2;
      if (rank < bestRank) { best = t.trial; bestRank = rank; }
    }
    return best;
  }

  function hitAlt(sx, sy) {
    if (!alts) return null;
    const [wx, wy] = screenToWorld(sx, sy);
    for (const c of alts.candidates) {
      if (c.rank === 0) continue;
      if (wx >= c.x && wx < c.x + TILE && wy >= c.y && wy < c.y + TILE) return c;
    }
    return null;
  }

  let drag = null;

  function onPointerDown(e) {
    canvas.setPointerCapture(e.pointerId);
    const mx = e.offsetX, my = e.offsetY;
    const rightBtn = e.button === 2;
    const panBtn = e.button === 1 || e.altKey;      // middle mouse or Alt. NOT Space — see handleKey.

    if (!panBtn && !rightBtn) {
      const a = hitAlt(mx, my);
      if (a && cb.onAlternativePick) { cb.onAlternativePick(alts.trial, a); return; }
    }

    const trial = (panBtn || rightBtn) ? null : hit(mx, my);
    if (trial != null) {
      if (e.ctrlKey || e.metaKey) { sel.has(trial) ? sel.delete(trial) : sel.add(trial); }
      else if (!sel.has(trial)) { sel.clear(); }
      const t = tiles.get(trial);
      dragTrial = trial;
      removeFromLayers(trial);                        // lift it out so it moves without a ghost
      drag = {
        kind: 'move', mx, my, trial,
        movers: (sel.size ? [...sel] : [trial]).filter((k) => isPlaced(tiles.get(k))),
        start: null, pushed: false,
      };
      drag.start = drag.movers.map((k) => ({ x: tiles.get(k).x, y: tiles.get(k).y }));
      for (const k of drag.movers) if (k !== trial) removeFromLayers(k);
      if (cb.onSelect) cb.onSelect(trial);
      canvas.classList.add('over-tile');
    } else if (rightBtn || (e.shiftKey && !panBtn)) {
      marquee = { x0: mx, y0: my, x1: mx, y1: my, add: e.ctrlKey || e.metaKey };
      drag = { kind: 'marquee' };
    } else {
      drag = { kind: 'pan', mx, my, tx: view.tx, ty: view.ty };
      canvas.classList.add('panning');
    }
    draw();
  }

  function onPointerMove(e) {
    const mx = e.offsetX, my = e.offsetY;
    if (cb.onHover) {
      const [wx, wy] = screenToWorld(mx, my);
      cb.onHover(Math.round(wx), Math.round(wy), drag ? null : hit(mx, my));
    }
    if (!drag) {
      canvas.classList.toggle('over-tile', hit(mx, my) != null || hitAlt(mx, my) != null);
      return;
    }
    if (drag.kind === 'pan') {
      view.tx = drag.tx + (mx - drag.mx);
      view.ty = drag.ty + (my - drag.my);
      onView();
      return;
    }
    if (drag.kind === 'marquee') { marquee.x1 = mx; marquee.y1 = my; draw(); return; }

    // move. Sweep pushes ONE undo step on the first pointermove (the bench's tagged folding).
    if (!drag.pushed) { drag.pushed = true; if (cb.onDragStart) cb.onDragStart(drag.trial); }
    let dx = (mx - drag.mx) / view.scale, dy = (my - drag.my) / view.scale;
    if (e.shiftKey) { Math.abs(dx) > Math.abs(dy) ? (dy = 0) : (dx = 0); }   // axis lock
    drag.movers.forEach((k, i) => {
      const t = tiles.get(k);
      t.x = drag.start[i].x + dx;
      t.y = drag.start[i].y + dy;
      if (cb.onDragMove) cb.onDragMove(k, t.x, t.y);
    });
    draw();
  }

  function endDrag() {
    if (!drag) return;
    if (drag.kind === 'marquee' && marquee) {
      const [ax, ay] = screenToWorld(Math.min(marquee.x0, marquee.x1), Math.min(marquee.y0, marquee.y1));
      const [bx, by] = screenToWorld(Math.max(marquee.x0, marquee.x1), Math.max(marquee.y0, marquee.y1));
      if (!marquee.add) sel.clear();
      for (const t of tiles.values()) {
        if (!isPlaced(t)) continue;
        if (t.x + TILE > ax && t.x < bx && t.y + TILE > ay && t.y < by) sel.add(t.trial);
      }
      if (cb.onSelect) cb.onSelect(sel.size === 1 ? [...sel][0] : null);
    } else if (drag.kind === 'move') {
      for (const k of drag.movers) {
        const t = tiles.get(k);
        if (cb.onDragEnd) cb.onDragEnd(k, t.x, t.y, { via: 'drag' });
      }
      dragTrial = null;
      for (const k of drag.movers) syncTileLayer(k);   // back into their layers at the new position
    }
    drag = null;
    marquee = null;
    dragTrial = null;
    canvas.classList.remove('panning', 'over-tile');
    draw();
  }

  function onWheel(e) {
    e.preventDefault();
    zoomBy(Math.exp(-e.deltaY * 0.0016), e.offsetX, e.offsetY);
  }

  // ---------------------------------------------------------------------------------------
  // keyboard — the CAMERA half only (API.md §15.6). A / E / Space / undo belong to sweep.js.
  //
  // sweep.js owns the keyboard map. This listener is a SAFETY NET, not a competitor: it is
  // registered on `window` in the bubble phase and it BAILS OUT on any event whose
  // defaultPrevented is already set. So if sweep handles a key (and calls preventDefault, as it
  // must), the viewer never sees it. Pass `bindKeys: false` to mount() to turn it off entirely,
  // or call Viewer.handleKey(e) yourself from sweep's own handler.
  // ---------------------------------------------------------------------------------------
  function handleKey(e) {
    const tag = (e.target && e.target.tagName) || '';
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(tag)) return false;
    if (e.ctrlKey || e.metaKey) return false;              // Ctrl+Z / Ctrl+Y are sweep's

    // ⛔ NO SPACE-TO-PAN. The bench used hold-Space as a pan modifier (template.html:1024). In THIS
    // app `Space` is the ADVANCE key — the single most-pressed key in the whole product (API.md
    // §15.6) — so a Space pan modifier is both wrong and a trap: sweep.js mounts with
    // `bindKeys:false` and delegates here, which means the viewer's own `keyup` listener is not
    // registered, so a `spaceDown` flag set here would NEVER BE CLEARED and every subsequent
    // left-drag would silently become a pan. Pan is: middle mouse, Alt+drag, or drag on empty space.
    if (e.code === 'Space') return false;

    const step = e.shiftKey ? 10 : 1;
    const n = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[e.key];
    if (n) { if (nudge(n[0], n[1])) { e.preventDefault(); return true; } return false; }

    const k = (e.key || '').toLowerCase();
    if (k === 'f') { fit(); e.preventDefault(); return true; }
    if (k === '0') { oneToOne(); e.preventDefault(); return true; }
    if (k === 'd') { setDifference(!diff); e.preventDefault(); return true; }
    if (k === 'g') { showGrid = !showGrid; draw(); e.preventDefault(); return true; }
    if (k === 'escape') {
      sel.clear(); clearAlternatives();
      if (cb.onSelect) cb.onSelect(null);
      draw(); e.preventDefault(); return true;
    }
    if (k === '+' || k === '=') { zoomBy(1.3); e.preventDefault(); return true; }
    if (k === '-' || k === '_') { zoomBy(1 / 1.3); e.preventDefault(); return true; }
    return false;
  }

  // ---------------------------------------------------------------------------------------
  // mount
  // ---------------------------------------------------------------------------------------
  /**
   * @param {HTMLCanvasElement} canvas
   * @param {object} opts
   * @param {string}  opts.apiBase          - window.CAMEA_API
   * @param {number}  opts.toneVersion      - bumps -> every cached bitmap is dropped and re-fetched
   * @param {boolean} opts.bindKeys         - default true; see the note above
   * @param {(trial, x, y) => void}          opts.onDragMove          - live, during a drag
   * @param {(trial, x, y, meta) => void}    opts.onDragEnd           - committed drop / nudge
   * @param {(trial) => void}                opts.onDragStart         - push ONE undo step here
   * @param {(trial|null) => void}           opts.onSelect
   * @param {(trial) => void}                opts.onFadeEnd
   * @param {(trial, candidate) => void}     opts.onAlternativePick   - a ghost box was clicked
   * @param {(wx, wy, trialUnderPointer) => void} opts.onHover
   * @param {(view) => void}                 opts.onView              - {scale, tx, ty}
   * @param {(trial, err) => void}           opts.onError
   */
  function mount(el, opts) {
    canvas = el;
    cb = opts || {};
    apiBase = (cb.apiBase != null ? cb.apiBase : (window.CAMEA_API || '')) || '';
    if (apiBase.endsWith('/')) apiBase = apiBase.slice(0, -1);
    toneVersion = cb.toneVersion || 0;
    ctx = canvas.getContext('2d', { alpha: false, desynchronized: true });
    mounted = true;

    readTheme();
    try {
      matchMedia('(prefers-color-scheme: dark)').addEventListener('change', readTheme);
      new MutationObserver(readTheme).observe(document.documentElement,
        { attributes: true, attributeFilter: ['data-theme'] });
    } catch (_) { /* non-fatal */ }

    canvas.addEventListener('contextmenu', (e) => e.preventDefault());
    canvas.addEventListener('pointerdown', onPointerDown);
    canvas.addEventListener('pointermove', onPointerMove);
    canvas.addEventListener('pointerup', endDrag);
    canvas.addEventListener('pointercancel', endDrag);
    canvas.addEventListener('wheel', onWheel, { passive: false });

    // sweep.js mounts with bindKeys:false and calls Viewer.handleKey(e) itself — that is the
    // supported path, and it is why handleKey is public.
    if (cb.bindKeys !== false) {
      window.addEventListener('keydown', (e) => { if (!e.defaultPrevented) handleKey(e); });
    }

    try { new ResizeObserver(resize).observe(canvas); } catch (_) { window.addEventListener('resize', resize); }
    window.addEventListener('resize', resize);
    resize();
    return API;
  }

  const API = {
    mount, setTiles, setTile, getTile, setDiverted, bakeBackground, fadeIn, replayFade,
    setDifference, isDifference, showAlternatives, clearAlternatives,
    setCursor, getCursor, setSelection, getSelection, nudge,
    fit, zoomTo, zoomBy, oneToOne, centreOn, reveal, screenToWorld, worldToScreen,
    setToneVersion, preload, stats, resetStats, handleKey, resize,
    setGrid: (on) => { showGrid = !!on; draw(); },
    setLabels: (on) => { showLabels = !!on; draw(); },
    setOutlines: (on) => { showOutlines = !!on; draw(); },
    redraw: draw,
    get view() { return { scale: view.scale, tx: view.tx, ty: view.ty }; },
    TILE, HALF, FADE_MS, STYLE,
  };
  return API;
})();
