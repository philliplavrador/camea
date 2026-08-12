// ─────────────────────────────────────────────────────────────────────────────────────────────
// ViewerEngine — the feature-agnostic LAYERED 2-D canvas that IS the hero (docs/DESIGN_BRIEF §0/§4).
//
// WHY LAYERS (BEHAVIOUR R20, archive/app-v1/SPEED.md). An immediate-mode loop redraws every placed
// image each frame: 89.5 ms/frame at 1:1 = 10 fps, and "the 1-second fade would be a SLIDESHOW."
// Instead, images bake into offscreen WORLD-SPACE canvases (one per layer), and a frame is just:
//     fill  +  one drawImage per layer  +  the floating tile(s)  +  vector chrome.
// Appending on A is ONE drawImage into the offscreen canvas (~0.1 ms); removing one is a local
// clip-and-repair. A full rebake (~257 ms for 312 tiles) happens ONLY on setTiles / tone flush —
// 🔴 NEVER for a single-tile change. Measured 89.5 → ~6 ms/frame, locked 60 fps.
//
// WHAT IT KNOWS. Images placed in world space, grouped into named layers, one floating item under
// inspection, and vector overlays. It knows NOTHING about anchors / unverified / diverts / mosaics —
// that meaning is the feature's, passed as a layer key, a `reference` flag and a per-tile outline.
//
// ⚠️ POSITIONS ARE TOP-LEFT CORNERS. Every centre-of-tile calculation adds `half` (= tileSize/2).
//    Off-by-half is the classic bug in this project (BEHAVIOUR R19).
// ⚠️ NO PER-TILE TONE. The engine never sets ctx.filter and never brightness/contrast-adjusts a tile;
//    overlapping tiles must agree in tone or Difference mode is meaningless (BEHAVIOUR R18).
// ─────────────────────────────────────────────────────────────────────────────────────────────

import {
  clamp,
  fitView,
  screenToWorld as camScreenToWorld,
  worldToScreen as camWorldToScreen,
  zoomToView,
  type Bbox,
} from './camera';
import { buildFeatherMask } from './feather';
import { mapCameraKey } from './keymap';
import {
  FADE_MS,
  FEATHER_PX,
  TILE_SIZE,
  type Candidate,
  type LayerInfo,
  type LayerSpec,
  type ModelInfo,
  type TileId,
  type TileOutline,
  type ViewerCallbacks,
  type ViewerStats,
  type ViewerTile,
  type ViewMatrix,
} from './types';

const MAX_LAYER_DIM = 16384; // Chrome's canvas hard limit; past it a layer falls back to immediate mode
const LABEL_MIN_PX = 48; // don't paint a tile label smaller than this on screen
const REVEAL_MARGIN = 64;
const FIT_PAD = 48;

/** Normalise an id: numeric strings collapse to numbers so `{ 11: … }` and `setTile(11, …)` agree. */
function normId(id: TileId): TileId {
  if (typeof id === 'number') return id;
  return /^-?\d+$/.test(id) ? Number(id) : id;
}
function cmpId(a: TileId, b: TileId): number {
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  return String(a).localeCompare(String(b));
}

interface Tile {
  id: TileId;
  x: number;
  y: number;
  src: string;
  layer: string;
  feather: boolean;
  outline: TileOutline | null;
}

interface Layer {
  key: string;
  alpha: number;
  visible: boolean;
  reference: boolean;
  order: number;
  cv: HTMLCanvasElement;
  g: CanvasRenderingContext2D | null;
  ox: number;
  oy: number;
  w: number;
  h: number;
  members: Set<TileId>;
  drawn: Set<TileId>;
  overflow: boolean;
}

interface Fade {
  fid: number;
  tile: TileId;
  t0: number;
  resolve(ok: boolean): void;
}

interface Alts {
  tile: TileId;
  candidates: Candidate[];
}

type DragState =
  | { kind: 'pan'; mx: number; my: number; tx: number; ty: number }
  | { kind: 'marquee' }
  | {
      kind: 'move';
      mx: number;
      my: number;
      tile: TileId;
      movers: TileId[];
      start: Array<{ x: number; y: number }>;
      pushed: boolean;
    };

interface Theme {
  canvas: string;
  canvasDiff: string;
  grid: string;
  cursor: string;
  alt: string;
  marquee: string;
  labelInk: string;
}

export interface EngineOptions {
  layers: LayerSpec[];
  cb: ViewerCallbacks;
  tileSize?: number;
  grid?: boolean;
  /** A VIEWING mount: tile drag-move, marquee select and nudge are suppressed — every left-drag
   *  pans. Camera gestures (wheel, pan, F/0/G/±) are untouched. Default false (the sweep edits). */
  readOnly?: boolean;
}

export class ViewerEngine {
  private readonly canvas: HTMLCanvasElement;
  private readonly ctx: CanvasRenderingContext2D | null;
  private readonly cb: ViewerCallbacks;

  private readonly tileSize: number;
  private readonly readOnly: boolean;
  private readonly half: number;
  private readonly featherMask: HTMLCanvasElement;
  private readonly stampCv: HTMLCanvasElement;
  private readonly stampG: CanvasRenderingContext2D | null;

  private readonly tiles = new Map<TileId, Tile>();
  private readonly bitmaps = new Map<string, ImageBitmap>();
  private readonly pending = new Map<string, Promise<ImageBitmap | null>>();

  private readonly layers: Layer[] = [];
  private readonly layerByKey = new Map<string, Layer>();

  private cursor: TileId | null = null;
  private dragTile: TileId | null = null;
  private fade: Fade | null = null;
  private fadeSeq = 0;
  private diff = false;
  private floatAlpha = 1;
  private alts: Alts | null = null;
  private readonly sel = new Set<TileId>();
  private marquee: { x0: number; y0: number; x1: number; y1: number; add: boolean } | null = null;
  private showGrid: boolean;

  private cssW = 0;
  private cssH = 0;
  private dpr = 1;
  private readonly view: ViewMatrix = { scale: 1, tx: 0, ty: 0 };

  private theme: Theme = {
    canvas: '#000000',
    canvasDiff: '#000000',
    grid: '#1a2029',
    cursor: '#4aa3ff',
    alt: '#a78bfa',
    marquee: '#4aa3ff',
    labelInk: '#04121f',
  };

  private mounted = false;
  private needsDraw = false;
  private drag: DragState | null = null;
  private readonly perf = { ms: [] as number[], rafDt: [] as number[], last: 0, frames: 0 };

  private ro: ResizeObserver | null = null;
  private mo: MutationObserver | null = null;
  private mql: MediaQueryList | null = null;
  private readonly cleanups: Array<() => void> = [];

  constructor(canvas: HTMLCanvasElement, opts: EngineOptions) {
    this.canvas = canvas;
    this.cb = opts.cb;
    this.tileSize = opts.tileSize ?? TILE_SIZE;
    this.readOnly = opts.readOnly ?? false;
    this.half = this.tileSize / 2;
    this.showGrid = opts.grid ?? false;

    this.featherMask = buildFeatherMask(this.tileSize, FEATHER_PX);
    this.stampCv = document.createElement('canvas');
    this.stampCv.width = this.stampCv.height = this.tileSize;
    this.stampG = this.stampCv.getContext('2d');

    opts.layers.forEach((spec, order) => {
      const layer = this.newLayer(spec, order);
      this.layers.push(layer);
      this.layerByKey.set(layer.key, layer);
    });

    // Not desynchronized: the Difference-mode pixel probes (BEHAVIOUR §3.5) read this canvas back.
    this.ctx = canvas.getContext('2d', { alpha: false });
    this.mounted = true;
    this.readTheme();
    this.attach();
    this.resize();
    this.reflect();
  }

  // ── layers ──────────────────────────────────────────────────────────────────────────────────
  private newLayer(spec: LayerSpec, order: number): Layer {
    const cv = document.createElement('canvas');
    cv.width = cv.height = 1;
    return {
      key: spec.key,
      alpha: spec.alpha ?? 1,
      visible: spec.visible ?? true,
      reference: spec.reference ?? false,
      order,
      cv,
      g: cv.getContext('2d'),
      ox: 0,
      oy: 0,
      w: 0,
      h: 0,
      members: new Set(),
      drawn: new Set(),
      overflow: false,
    };
  }

  private layerFor(tile: Tile): Layer | null {
    return this.layerByKey.get(tile.layer) ?? null;
  }

  private isFloat(id: TileId): boolean {
    return (
      id === this.cursor || id === this.dragTile || (this.fade !== null && this.fade.tile === id)
    );
  }

  /** Feather a bitmap into the reused scratch canvas (edges ramped to 0). Degrades to the raw bitmap
   *  where no 2-D context exists (jsdom). Still exactly ONE drawImage into the layer afterwards. */
  private feathered(bmp: ImageBitmap): CanvasImageSource {
    const g = this.stampG;
    if (!g) return bmp;
    const s = this.tileSize;
    g.globalCompositeOperation = 'source-over';
    g.globalAlpha = 1;
    g.clearRect(0, 0, s, s);
    g.drawImage(bmp, 0, 0, s, s);
    g.globalCompositeOperation = 'destination-in';
    g.drawImage(this.featherMask, 0, 0);
    g.globalCompositeOperation = 'source-over';
    return this.stampCv;
  }

  private layerGrow(L: Layer, x: number, y: number): boolean {
    const s = this.tileSize;
    const nx0 = Math.floor(Math.min(L.w ? L.ox : x, x));
    const ny0 = Math.floor(Math.min(L.h ? L.oy : y, y));
    const nx1 = Math.ceil(Math.max(L.w ? L.ox + L.w : x + s, x + s));
    const ny1 = Math.ceil(Math.max(L.h ? L.oy + L.h : y + s, y + s));
    const nw = nx1 - nx0;
    const nh = ny1 - ny0;
    if (nw === L.w && nh === L.h && nx0 === L.ox && ny0 === L.oy) return true;
    if (nw > MAX_LAYER_DIM || nh > MAX_LAYER_DIM) {
      L.overflow = true;
      return false;
    }
    const old = L.cv;
    const ow = L.w;
    const oh = L.h;
    const oox = L.ox;
    const ooy = L.oy;
    const cv = document.createElement('canvas');
    cv.width = nw;
    cv.height = nh;
    const g = cv.getContext('2d');
    if (ow && oh && g) g.drawImage(old, oox - nx0, ooy - ny0);
    L.cv = cv;
    L.g = g;
    L.ox = nx0;
    L.oy = ny0;
    L.w = nw;
    L.h = nh;
    return true;
  }

  /** Paint one tile into its layer. The A-press path — ~0.1 ms, never a rebake. */
  private layerAdd(L: Layer, id: TileId): void {
    L.members.add(id);
    if (L.drawn.has(id) || L.overflow) return;
    const t = this.tiles.get(id);
    if (!t) return;
    const bmp = this.bitmaps.get(t.src);
    if (!bmp) {
      void this.ensureBitmap(t.src); // painted when the bitmap lands
      return;
    }
    if (!this.layerGrow(L, t.x, t.y) || !L.g) return;
    L.g.globalAlpha = 1;
    L.g.globalCompositeOperation = 'source-over';
    const src = t.feather ? this.feathered(bmp) : bmp;
    L.g.drawImage(src, t.x - L.ox, t.y - L.oy, this.tileSize, this.tileSize);
    L.drawn.add(id);
  }

  /** Take a tile back OUT of a layer without a rebake: clip to its rect, clear, redraw only the
   *  members that overlap it. The repair MUST re-feather or the patched rect returns hard-edged. */
  private layerRemove(L: Layer, id: TileId): void {
    if (!L.members.has(id)) return;
    const t = this.tiles.get(id);
    const was = L.drawn.has(id);
    L.members.delete(id);
    L.drawn.delete(id);
    if (!was || L.overflow || !t || !L.g) return;
    const s = this.tileSize;
    const x = t.x - L.ox;
    const y = t.y - L.oy;
    const g = L.g;
    g.save();
    g.beginPath();
    g.rect(x, y, s, s);
    g.clip();
    g.clearRect(x, y, s, s);
    g.globalAlpha = 1;
    g.globalCompositeOperation = 'source-over';
    const order = [...L.drawn].sort(cmpId);
    for (const oid of order) {
      const ot = this.tiles.get(oid);
      if (!ot) continue;
      if (ot.x + s <= t.x || ot.x >= t.x + s || ot.y + s <= t.y || ot.y >= t.y + s) continue;
      const bmp = this.bitmaps.get(ot.src);
      if (bmp) g.drawImage(ot.feather ? this.feathered(bmp) : bmp, ot.x - L.ox, ot.y - L.oy, s, s);
    }
    g.restore();
  }

  private removeFromLayers(id: TileId): void {
    for (const L of this.layers) this.layerRemove(L, id);
  }

  /** Put `id` in exactly the layer its `layer` key names — or in none, if it floats. */
  private syncTileLayer(id: TileId): void {
    const t = this.tiles.get(id);
    const want = t && !this.isFloat(id) ? this.layerFor(t) : null;
    for (const L of this.layers) if (L !== want && L.members.has(id)) this.layerRemove(L, id);
    if (want && !want.members.has(id)) this.layerAdd(want, id);
  }

  /** Full rebake of every layer. ~257 ms for 312 tiles — fine ONCE (setTiles / tone flush), fatal in
   *  the loop. AGENT NOTE: setTile is the single-tile path; never route one tile through here. */
  private bakeBackground(): void {
    const s = this.tileSize;
    for (const L of this.layers) {
      L.members.clear();
      L.drawn.clear();
      L.overflow = false;
      L.ox = L.oy = L.w = L.h = 0;
      L.cv = document.createElement('canvas');
      L.cv.width = L.cv.height = 1;
      L.g = L.cv.getContext('2d');
    }
    // Size each layer once up front so we never grow mid-bake.
    for (const L of this.layers) {
      let x0 = Infinity;
      let y0 = Infinity;
      let x1 = -Infinity;
      let y1 = -Infinity;
      let n = 0;
      for (const t of this.tiles.values()) {
        if (this.isFloat(t.id) || this.layerFor(t) !== L) continue;
        x0 = Math.min(x0, t.x);
        y0 = Math.min(y0, t.y);
        x1 = Math.max(x1, t.x + s);
        y1 = Math.max(y1, t.y + s);
        n++;
      }
      if (!n) continue;
      const w = Math.ceil(x1) - Math.floor(x0);
      const h = Math.ceil(y1) - Math.floor(y0);
      if (w > MAX_LAYER_DIM || h > MAX_LAYER_DIM) {
        L.overflow = true;
        continue;
      }
      L.cv.width = w;
      L.cv.height = h;
      L.g = L.cv.getContext('2d');
      L.ox = Math.floor(x0);
      L.oy = Math.floor(y0);
      L.w = w;
      L.h = h;
    }
    const order = [...this.tiles.keys()].sort(cmpId);
    for (const id of order) {
      const t = this.tiles.get(id);
      if (!t || this.isFloat(id)) continue;
      const L = this.layerFor(t);
      if (L) this.layerAdd(L, id);
    }
    this.draw();
  }

  // ── bitmaps (keyed by URL — the URL IS the cache key, BEHAVIOUR R31/R32) ──────────────────────
  private ensureBitmap(src: string): Promise<ImageBitmap | null> {
    const have = this.bitmaps.get(src);
    if (have) return Promise.resolve(have);
    const inflight = this.pending.get(src);
    if (inflight) return inflight;
    const p = (async (): Promise<ImageBitmap | null> => {
      try {
        const r = await fetch(src);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const bmp = await createImageBitmap(await r.blob());
        this.bitmaps.set(src, bmp);
        // Paint every placed, non-floating tile that was waiting on this URL.
        for (const t of this.tiles.values()) {
          if (t.src !== src || this.isFloat(t.id)) continue;
          const L = this.layerFor(t);
          if (L && L.members.has(t.id)) this.layerAdd(L, t.id);
        }
        this.draw();
        return bmp;
      } catch (e) {
        const owner = [...this.tiles.values()].find((t) => t.src === src);
        if (owner) this.cb.onError?.(owner.id, e);
        return null; // render() simply skips a tile with no bitmap
      } finally {
        this.pending.delete(src);
      }
    })();
    this.pending.set(src, p);
    return p;
  }

  preload(srcs: string[]): void {
    for (const s of srcs) void this.ensureBitmap(s);
  }

  clearBitmapCache(): void {
    for (const b of this.bitmaps.values()) b.close?.();
    this.bitmaps.clear();
    this.pending.clear();
    for (const t of this.tiles.values()) void this.ensureBitmap(t.src);
    this.bakeBackground();
  }

  // ── camera ────────────────────────────────────────────────────────────────────────────────────
  screenToWorld(sx: number, sy: number): [number, number] {
    return camScreenToWorld(this.view, sx, sy);
  }
  worldToScreen(wx: number, wy: number): [number, number] {
    return camWorldToScreen(this.view, wx, wy);
  }

  private bbox(): Bbox | null {
    const s = this.tileSize;
    let x0 = Infinity;
    let y0 = Infinity;
    let x1 = -Infinity;
    let y1 = -Infinity;
    let n = 0;
    for (const t of this.tiles.values()) {
      x0 = Math.min(x0, t.x);
      y0 = Math.min(y0, t.y);
      x1 = Math.max(x1, t.x + s);
      y1 = Math.max(y1, t.y + s);
      n++;
    }
    return n ? { x0, y0, x1, y1 } : null;
  }

  fit(): void {
    const b = this.bbox();
    if (!b) return;
    const v = fitView(b, this.cssW, this.cssH, FIT_PAD);
    this.view.scale = v.scale;
    this.view.tx = v.tx;
    this.view.ty = v.ty;
    this.onView();
  }

  private zoomTo(scale: number, cx?: number, cy?: number): void {
    const sx = cx ?? this.cssW / 2;
    const sy = cy ?? this.cssH / 2;
    const v = zoomToView(this.view, scale, sx, sy);
    this.view.scale = v.scale;
    this.view.tx = v.tx;
    this.view.ty = v.ty;
    this.onView();
  }
  zoomBy(k: number, cx?: number, cy?: number): void {
    this.zoomTo(this.view.scale * k, cx, cy);
  }
  oneToOne(): void {
    this.zoomTo(1, this.cssW / 2, this.cssH / 2);
  }

  centreOn(id: TileId): void {
    const t = this.tiles.get(normId(id));
    if (!t) return;
    this.view.tx = this.cssW / 2 - (t.x + this.half) * this.view.scale;
    this.view.ty = this.cssH / 2 - (t.y + this.half) * this.view.scale;
    this.onView();
  }

  /** Pan (never zoom) a tile back on screen if it landed off the edge; a lone first tile gets a fit. */
  reveal(id: TileId): void {
    const t = this.tiles.get(normId(id));
    if (!t) return;
    if (this.tiles.size <= 1) {
      this.view.scale = clamp(this.view.scale, 0.25, 2);
      this.centreOn(id);
      return;
    }
    const [cx, cy] = this.worldToScreen(t.x + this.half, t.y + this.half);
    const m = REVEAL_MARGIN;
    if (cx < m || cy < m || cx > this.cssW - m || cy > this.cssH - m) {
      this.view.tx += this.cssW / 2 - cx;
      this.view.ty += this.cssH / 2 - cy;
      this.onView();
    }
  }

  private onView(): void {
    this.cb.onView?.({ ...this.view });
    this.draw();
  }

  // ── render loop ──────────────────────────────────────────────────────────────────────────────
  private draw(): void {
    if (!this.mounted || this.needsDraw) return;
    this.needsDraw = true;
    requestAnimationFrame(this.frame);
  }

  private frame = (ts: number): void => {
    this.needsDraw = false;
    if (this.perf.last) this.push(this.perf.rafDt, ts - this.perf.last);
    this.perf.last = ts;
    const t0 = performance.now();
    this.render(ts);
    this.push(this.perf.ms, performance.now() - t0);
    this.perf.frames++;
    if (this.fade) this.draw(); // the fade keeps the loop alive, and nothing else does
  };

  private push(a: number[], v: number): void {
    a.push(v);
    if (a.length > 240) a.shift();
  }

  resize(): void {
    const r = this.canvas.getBoundingClientRect();
    this.dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.cssW = Math.max(1, Math.round(r.width));
    this.cssH = Math.max(1, Math.round(r.height));
    this.canvas.width = Math.round(this.cssW * this.dpr);
    this.canvas.height = Math.round(this.cssH * this.dpr);
    this.draw();
  }

  private render(ts: number): void {
    const ctx = this.ctx;
    if (!ctx) return;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.globalCompositeOperation = 'source-over';
    ctx.globalAlpha = 1;

    // 🔴 In Difference mode the clear MUST be black (BEHAVIOUR §3.5). `difference` composites
    // |tile − destination|; where the reference field does not cover the tile the destination IS the
    // clear colour, and black is the only one for which "no reference here" reads as "no difference".
    ctx.fillStyle = this.diff ? this.theme.canvasDiff : this.theme.canvas;
    ctx.fillRect(0, 0, this.cssW, this.cssH);
    if (this.showGrid && !this.diff) this.drawGrid();

    ctx.imageSmoothingEnabled = this.view.scale < 2; // above 2×, show the real pixels

    // The baked layers: one drawImage each. In Difference mode ONLY reference layers are drawn — an
    // unverified tile is not a trusted reference and would muddy the check (BEHAVIOUR §3.5, R9).
    for (const L of this.layers) {
      if (this.diff && !L.reference) continue;
      if (!this.diff && !L.visible) continue;
      this.drawLayer(L, L.alpha);
    }

    // The floating tile(s): the cursor and/or the one fading in.
    const fa = this.fadeAlpha(ts);
    const s = this.tileSize * this.view.scale;
    for (const id of this.floats()) {
      const t = this.tiles.get(id);
      if (!t) continue;
      const bmp = this.bitmaps.get(t.src);
      if (!bmp) continue;
      const isFading = this.fade !== null && this.fade.tile === id;
      // 🔴 Difference mode ignores the opacity slider (BEHAVIOUR R13.4): dimming the tile would drag
      //    the result toward the background and WEAKEN the doubling that is the signal. Force a = 1.
      let a = this.diff ? 1 : this.floatAlpha;
      if (isFading) a *= fa; // the fade ramps 0 → (floatAlpha | 1); at 1 it is bit-identical to before
      const [sx, sy] = this.worldToScreen(t.x, t.y);
      ctx.globalCompositeOperation = this.diff ? 'difference' : 'source-over';
      ctx.globalAlpha = a;
      ctx.drawImage(bmp, sx, sy, s, s);
    }
    ctx.globalCompositeOperation = 'source-over';
    ctx.globalAlpha = 1;

    this.drawChrome();
  }

  private drawLayer(L: Layer, alpha: number): void {
    const ctx = this.ctx;
    if (!ctx) return;
    if (L.overflow) {
      this.drawLayerImmediate(L, alpha);
      return;
    }
    if (!L.w || !L.h) return;
    // Clip the SOURCE rect to what is on screen (9.5 → 2.6 ms/frame at 1:1; BEHAVIOUR R20).
    const [w0x, w0y] = this.screenToWorld(0, 0);
    const [w1x, w1y] = this.screenToWorld(this.cssW, this.cssH);
    let sx = Math.floor(w0x - L.ox) - 1;
    let sy = Math.floor(w0y - L.oy) - 1;
    let ex = Math.ceil(w1x - L.ox) + 1;
    let ey = Math.ceil(w1y - L.oy) + 1;
    sx = Math.max(0, sx);
    sy = Math.max(0, sy);
    ex = Math.min(L.w, ex);
    ey = Math.min(L.h, ey);
    const sw = ex - sx;
    const sh = ey - sy;
    if (sw <= 0 || sh <= 0) return;
    ctx.globalAlpha = alpha;
    ctx.drawImage(
      L.cv,
      sx,
      sy,
      sw,
      sh,
      (L.ox + sx) * this.view.scale + this.view.tx,
      (L.oy + sy) * this.view.scale + this.view.ty,
      sw * this.view.scale,
      sh * this.view.scale,
    );
    ctx.globalAlpha = 1;
  }

  /** Fallback ONLY when a layer's bbox blew past the 16,384-px limit. Still culled to the viewport. */
  private drawLayerImmediate(L: Layer, alpha: number): void {
    const ctx = this.ctx;
    if (!ctx) return;
    ctx.globalAlpha = alpha;
    const s = this.tileSize * this.view.scale;
    for (const id of L.members) {
      const t = this.tiles.get(id);
      if (!t) continue;
      const bmp = this.bitmaps.get(t.src);
      if (!bmp) continue;
      const [sx, sy] = this.worldToScreen(t.x, t.y);
      if (sx > this.cssW || sy > this.cssH || sx + s < 0 || sy + s < 0) continue;
      ctx.drawImage(bmp, sx, sy, s, s);
    }
    ctx.globalAlpha = 1;
  }

  private fadeAlpha(ts: number): number {
    if (!this.fade) return 1;
    const e = (ts || performance.now()) - this.fade.t0;
    if (e >= FADE_MS) return 1;
    return Math.max(0, e / FADE_MS);
  }

  private floats(): TileId[] {
    const out: TileId[] = [];
    const seen = new Set<TileId>();
    for (const id of [this.cursor, this.dragTile, this.fade?.tile ?? null]) {
      if (id == null || seen.has(id)) continue;
      seen.add(id);
      if (this.tiles.has(id)) out.push(id);
    }
    // The fading tile composites LAST, on top of everything including the cursor.
    const fadeTile = this.fade?.tile;
    out.sort((a, b) => (a === fadeTile ? 1 : 0) - (b === fadeTile ? 1 : 0));
    return out;
  }

  private drawGrid(): void {
    const ctx = this.ctx;
    if (!ctx) return;
    const step = this.tileSize * this.view.scale;
    if (step < 26) return;
    ctx.save();
    ctx.strokeStyle = this.theme.grid;
    ctx.globalAlpha = 0.25;
    ctx.lineWidth = 1;
    ctx.beginPath();
    const x0 = this.view.tx % step;
    const y0 = this.view.ty % step;
    for (let x = x0; x < this.cssW; x += step) {
      ctx.moveTo(Math.round(x) + 0.5, 0);
      ctx.lineTo(Math.round(x) + 0.5, this.cssH);
    }
    for (let y = y0; y < this.cssH; y += step) {
      ctx.moveTo(0, Math.round(y) + 0.5);
      ctx.lineTo(this.cssW, Math.round(y) + 0.5);
    }
    ctx.stroke();
    ctx.restore();
  }

  /** Vector chrome: per-tile outlines (batched), selection, the cursor box, the alternative ghosts,
   *  the marquee. All culled to the viewport; outlines are ONE Path2D + ONE stroke per style (R20). */
  private drawChrome(): void {
    const ctx = this.ctx;
    if (!ctx) return;
    const s = this.tileSize * this.view.scale;
    const vis = (t: Tile): boolean => {
      const [sx, sy] = this.worldToScreen(t.x, t.y);
      return !(sx > this.cssW || sy > this.cssH || sx + s < 0 || sy + s < 0);
    };

    // Per-tile outlines. Drawn only in normal mode and only where the tile's layer is visible — so
    // hiding a layer takes its outlines with it (no dashed cage over nothing, BEHAVIOUR R9.5). The
    // alpha ramps with on-screen size so a fit-zoom field of hundreds does not become a cage of noise.
    if (!this.diff) {
      const oAlpha = clamp((s - 64) / 160, 0, 1) * 0.8;
      if (oAlpha > 0.02) {
        const batches = new Map<string, { style: TileOutline; path: Path2D }>();
        for (const t of this.tiles.values()) {
          if (!t.outline || t.id === this.cursor || this.sel.has(t.id) || !vis(t)) continue;
          const L = this.layerFor(t);
          if (!L || !L.visible) continue;
          const key = `${t.outline.color}|${(t.outline.dash ?? []).join(',')}|${t.outline.width ?? 1}`;
          let batch = batches.get(key);
          if (!batch) {
            batch = { style: t.outline, path: new Path2D() };
            batches.set(key, batch);
          }
          const [sx, sy] = this.worldToScreen(t.x, t.y);
          batch.path.rect(Math.round(sx) + 0.5, Math.round(sy) + 0.5, s - 1, s - 1);
        }
        if (batches.size) {
          ctx.save();
          ctx.globalAlpha = oAlpha;
          for (const { style, path } of batches.values()) {
            ctx.setLineDash(style.dash ?? []);
            ctx.lineWidth = style.width ?? 1;
            ctx.strokeStyle = style.color;
            ctx.stroke(path);
          }
          ctx.restore();
        }
      }
    }

    // Selection boxes.
    if (this.sel.size && s > 6) {
      ctx.save();
      ctx.strokeStyle = this.theme.marquee;
      ctx.lineWidth = 2;
      ctx.globalAlpha = 1;
      const p = new Path2D();
      for (const id of this.sel) {
        const t = this.tiles.get(id);
        if (!t || !vis(t)) continue;
        const [sx, sy] = this.worldToScreen(t.x, t.y);
        p.rect(Math.round(sx) + 0.5, Math.round(sy) + 0.5, s - 1, s - 1);
      }
      ctx.stroke(p);
      ctx.restore();
    }

    // The tile under judgement — THE SIGNATURE (docs/DESIGN_BRIEF §4): a corner RETICLE that locks onto
    // the TOP-LEFT of the tile, with a crosshair centred on that corner. Positions in Camea are top-left
    // corners (+256 = HALF; R19), so the reticle is an L-bracket at the corner, NOT a plain box around
    // it — it encodes the coordinate convention that is the classic off-by-256 bug. Pure vector, drawn
    // in the chrome layer each frame: a handful of strokes, cheaper than the old strokeRect (no rebake,
    // R20). The four readout numbers float in the overlay (SweepOverlay), the feature's reactive data.
    if (this.cursor != null) {
      const t = this.tiles.get(this.cursor);
      if (t && vis(t)) {
        const [sx0, sy0] = this.worldToScreen(t.x, t.y);
        const x = Math.round(sx0) + 0.5;
        const y = Math.round(sy0) + 0.5;
        const w = s - 1;
        const R = x + w;
        const B = y + w;
        const arm = clamp(s * 0.16, 9, 26); // corner-bracket arm length
        ctx.save();
        ctx.globalAlpha = 1;
        ctx.strokeStyle = this.theme.cursor;
        ctx.lineJoin = 'round';
        ctx.lineCap = 'round';

        // The tile footprint — a faint dashed full outline, never the emphasis (matches the static
        // Reticle's dashed `.tile`). The bright corners and the crosshair carry the eye.
        ctx.lineWidth = 1;
        ctx.globalAlpha = 0.5;
        ctx.setLineDash([6, 4]);
        ctx.strokeRect(x, y, w, w);
        ctx.setLineDash([]);
        ctx.globalAlpha = 1;

        // The four corner L-brackets.
        ctx.lineWidth = 2;
        const br = new Path2D();
        br.moveTo(x, y + arm); br.lineTo(x, y); br.lineTo(x + arm, y); // top-left
        br.moveTo(R - arm, y); br.lineTo(R, y); br.lineTo(R, y + arm); // top-right
        br.moveTo(x, B - arm); br.lineTo(x, B); br.lineTo(x + arm, B); // bottom-left
        br.moveTo(R - arm, B); br.lineTo(R, B); br.lineTo(R, B - arm); // bottom-right
        ctx.stroke(br);

        // The crosshair centred on the TOP-LEFT corner — the anchor point (R19).
        const cin = 5; // gap around the corner
        const cout = clamp(s * 0.07, 11, 18);
        const ch = new Path2D();
        ch.moveTo(x, y - cout); ch.lineTo(x, y - cin);
        ch.moveTo(x, y + cin); ch.lineTo(x, y + cout);
        ch.moveTo(x - cout, y); ch.lineTo(x - cin, y);
        ch.moveTo(x + cin, y); ch.lineTo(x + cout, y);
        ctx.lineWidth = 1.4;
        ctx.stroke(ch);

        // The top-left corner dot.
        ctx.fillStyle = this.theme.cursor;
        ctx.beginPath();
        ctx.arc(x, y, 2.2, 0, Math.PI * 2);
        ctx.fill();

        // The trial id, nestled just inside the corner so it never fights the crosshair.
        if (s > LABEL_MIN_PX) this.label(String(this.cursor), sx0 + 7, sy0 + 7, this.theme.cursor);
        ctx.restore();
      }
    }

    // Ranked alternative ghosts (rank 0 IS the placement — never ghosted). Box at the world top-left,
    // label at the centre (+half). The label text is the feature's (display = rank+1, BEHAVIOUR R12.3).
    if (this.alts && this.alts.candidates.length) {
      ctx.save();
      ctx.setLineDash([5, 5]);
      ctx.font = '600 12px ui-monospace, Consolas, monospace';
      ctx.textBaseline = 'middle';
      for (const c of this.alts.candidates) {
        if (c.rank === 0) continue;
        const [sx, sy] = this.worldToScreen(c.x, c.y);
        if (sx > this.cssW || sy > this.cssH || sx + s < 0 || sy + s < 0) continue;
        ctx.strokeStyle = this.theme.alt;
        ctx.globalAlpha = 0.9;
        ctx.lineWidth = 1.5;
        ctx.strokeRect(sx + 0.5, sy + 0.5, s - 1, s - 1);
        if (c.label) {
          const [lx, ly] = this.worldToScreen(c.x + this.half, c.y + this.half);
          const w = ctx.measureText(c.label).width + 12;
          ctx.globalAlpha = 0.92;
          ctx.fillStyle = 'rgba(0,0,0,.7)';
          ctx.fillRect(lx - w / 2, ly - 10, w, 20);
          ctx.fillStyle = this.theme.alt;
          ctx.textAlign = 'center';
          ctx.fillText(c.label, lx, ly + 1);
          ctx.textAlign = 'left';
        }
      }
      ctx.restore();
    }

    if (this.marquee) {
      const { x0, y0, x1, y1 } = this.marquee;
      ctx.save();
      ctx.strokeStyle = this.theme.marquee;
      ctx.fillStyle = this.theme.marquee;
      ctx.globalAlpha = 0.12;
      ctx.fillRect(x0, y0, x1 - x0, y1 - y0);
      ctx.globalAlpha = 1;
      ctx.setLineDash([4, 3]);
      ctx.strokeRect(x0 + 0.5, y0 + 0.5, x1 - x0, y1 - y0);
      ctx.restore();
    }
  }

  private label(txt: string, sx: number, sy: number, bg: string): void {
    const ctx = this.ctx;
    if (!ctx) return;
    ctx.font = '600 11px ui-monospace, Consolas, monospace';
    ctx.textBaseline = 'alphabetic';
    ctx.textAlign = 'left';
    const w = ctx.measureText(txt).width + 10;
    ctx.globalAlpha = 1;
    ctx.fillStyle = bg;
    ctx.fillRect(sx, sy, w, 16);
    ctx.fillStyle = this.theme.labelInk;
    ctx.fillText(txt, sx + 5, sy + 12);
  }

  // ── theme ────────────────────────────────────────────────────────────────────────────────────
  private cssVar(name: string, fallback: string): string {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }
  private readTheme = (): void => {
    this.theme = {
      canvas: this.cssVar('--canvas', '#000000'),
      canvasDiff: this.cssVar('--canvas-diff', '#000000'),
      grid: this.cssVar('--grid', '#1a2029'),
      cursor: this.cssVar('--cursor', '#4aa3ff'),
      alt: this.cssVar('--alt', '#a78bfa'),
      marquee: this.cssVar('--accent', '#4aa3ff'),
      labelInk: this.cssVar('--accent-ink', '#04121f'),
    };
    this.draw();
  };

  // ── the public model API ──────────────────────────────────────────────────────────────────────
  private toTile(id: TileId, input: ViewerTile): Tile {
    return {
      id,
      x: input.x,
      y: input.y,
      src: input.src,
      layer: input.layer,
      feather: input.feather ?? false,
      outline: input.outline ?? null,
    };
  }

  setTiles(model: Record<string, ViewerTile> | Map<TileId, ViewerTile>): void {
    this.tiles.clear();
    const entries: Array<[TileId, ViewerTile]> =
      model instanceof Map ? [...model.entries()] : Object.entries(model);
    for (const [rawId, input] of entries) {
      const id = normId(rawId);
      this.tiles.set(id, this.toTile(id, input));
    }
    for (const t of this.tiles.values()) void this.ensureBitmap(t.src);
    this.bakeBackground();
    this.emitModel();
  }

  setTile(rawId: TileId, input: ViewerTile | null): void {
    const id = normId(rawId);
    const had = this.tiles.has(id);
    if (had) this.removeFromLayers(id);
    if (input === null) {
      this.tiles.delete(id);
      this.sel.delete(id);
      if (this.cursor === id) this.cursor = null;
      this.draw();
      this.emitModel();
      return;
    }
    const t = this.toTile(id, input);
    this.tiles.set(id, t);
    void this.ensureBitmap(t.src);
    if (!this.isFloat(id)) {
      const L = this.layerFor(t);
      if (L) this.layerAdd(L, id);
    }
    this.draw();
    this.emitModel();
  }

  getTile(rawId: TileId): (ViewerTile & { id: TileId }) | null {
    const t = this.tiles.get(normId(rawId));
    if (!t) return null;
    return {
      id: t.id,
      x: t.x,
      y: t.y,
      src: t.src,
      layer: t.layer,
      feather: t.feather,
      outline: t.outline,
    };
  }

  setCursor(rawId: TileId | null): void {
    const id = rawId == null ? null : normId(rawId);
    if (id === this.cursor) return;
    const prev = this.cursor;
    this.cursor = null;
    if (prev != null) this.syncTileLayer(prev); // the tile just judged drops into its layer
    this.cursor = id;
    if (id != null) {
      this.removeFromLayers(id); // and the new one is lifted out of it
      const t = this.tiles.get(id);
      if (t) void this.ensureBitmap(t.src);
    }
    this.clearAlternatives();
    this.draw();
    this.emitModel();
  }
  getCursor(): TileId | null {
    return this.cursor;
  }

  fadeIn(rawId: TileId, x?: number, y?: number): Promise<boolean> {
    const id = normId(rawId);
    const t = this.tiles.get(id);
    if (!t) return Promise.resolve(false);
    if (x != null && y != null) {
      this.removeFromLayers(id);
      t.x = x;
      t.y = y;
    }
    if (this.fade) {
      const f = this.fade;
      this.fade = null;
      this.syncTileLayer(f.tile);
      f.resolve(false);
    }
    this.removeFromLayers(id); // it floats for the fade's duration
    void this.ensureBitmap(t.src);
    return new Promise<boolean>((resolve) => {
      const fid = ++this.fadeSeq;
      this.fade = { fid, tile: id, t0: performance.now(), resolve };
      this.draw();
      // The tick keys on a unique fade id, NOT the tile — replay (R) restarts the fade on the SAME
      // tile, and a tile-keyed guard would let a superseded tick fire onFadeEnd twice (BEHAVIOUR R-R).
      const tick = (): void => {
        if (!this.fade || this.fade.fid !== fid) return;
        if (performance.now() - this.fade.t0 >= FADE_MS) {
          const f = this.fade;
          this.fade = null;
          this.syncTileLayer(f.tile);
          this.draw();
          this.cb.onFadeEnd?.(f.tile);
          this.emitModel();
          f.resolve(true);
          return;
        }
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
  }

  replayFade(): Promise<boolean> {
    const id = this.fade?.tile ?? this.cursor;
    if (id == null || !this.tiles.has(id)) return Promise.resolve(false);
    const t = this.tiles.get(id);
    if (!t) return Promise.resolve(false);
    return this.fadeIn(id, t.x, t.y);
  }

  setDifference(on: boolean): void {
    this.diff = !!on;
    this.cb.onDifference?.(this.diff);
    this.reflect();
    this.draw();
  }
  isDifference(): boolean {
    return this.diff;
  }

  setFloatAlpha(a: number): void {
    this.floatAlpha = clamp(a, 0, 1);
    this.reflect();
    this.draw();
  }
  getFloatAlpha(): number {
    return this.floatAlpha;
  }

  setLayerVisible(key: string, on: boolean): void {
    const L = this.layerByKey.get(key);
    if (!L) return;
    L.visible = !!on;
    this.draw();
    this.emitModel();
  }
  setLayerAlpha(key: string, a: number): void {
    const L = this.layerByKey.get(key);
    if (!L) return;
    L.alpha = clamp(a, 0, 1);
    this.draw();
  }
  layerPlacedCount(key: string): number {
    let n = 0;
    for (const t of this.tiles.values()) if (t.layer === key) n++;
    return n;
  }

  showAlternatives(rawId: TileId, candidates: Candidate[]): void {
    this.alts = { tile: normId(rawId), candidates: candidates.slice() };
    this.draw();
  }
  clearAlternatives(): void {
    this.alts = null;
    this.draw();
  }

  setSelection(ids: TileId[]): void {
    this.sel.clear();
    for (const id of ids) this.sel.add(normId(id));
    this.draw();
  }
  getSelection(): TileId[] {
    return [...this.sel];
  }

  nudge(dx: number, dy: number): boolean {
    if (this.readOnly) return false; // nothing moves in a viewing mount — arrows fall to the feature
    const targets = this.sel.size ? [...this.sel] : this.cursor != null ? [this.cursor] : [];
    if (!targets.length) return false;
    for (const id of targets) {
      const t = this.tiles.get(id);
      if (!t) continue;
      if (this.isFloat(id)) {
        t.x += dx;
        t.y += dy;
      } else {
        this.removeFromLayers(id);
        t.x += dx;
        t.y += dy;
        const L = this.layerFor(t);
        if (L) this.layerAdd(L, id);
      }
      this.cb.onDragEnd?.(id, t.x, t.y, { via: 'nudge' });
    }
    this.draw();
    return true;
  }

  setGrid(on: boolean): void {
    this.showGrid = !!on;
    this.draw();
  }

  // ── attributes the viewer OWNS + the model snapshot the feature reflects ─────────────────────
  private reflect(): void {
    this.canvas.setAttribute('data-diff', String(this.diff));
    this.canvas.setAttribute('data-float-alpha', String(this.floatAlpha));
  }

  private emitModel(): void {
    this.reflect();
    if (!this.cb.onModelChange) return;
    const layers: Record<string, LayerInfo> = {};
    for (const L of this.layers) {
      layers[L.key] = {
        placed: this.layerPlacedCount(L.key),
        baked: L.drawn.size,
        visible: L.visible,
        reference: L.reference,
        overflow: L.overflow,
      };
    }
    const info: ModelInfo = {
      layers,
      difference: this.diff,
      floatAlpha: this.floatAlpha,
      cursor: this.cursor,
    };
    this.cb.onModelChange(info);
  }

  // ── perf ─────────────────────────────────────────────────────────────────────────────────────
  stats(): ViewerStats {
    const q = (a: number[], p: number): number => {
      if (!a.length) return 0;
      const sorted = [...a].sort((x, y) => x - y);
      return sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))];
    };
    const mean = (a: number[]): number => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0);
    return {
      ms: +mean(this.perf.ms).toFixed(2),
      msMedian: +q(this.perf.ms, 0.5).toFixed(2),
      msP95: +q(this.perf.ms, 0.95).toFixed(2),
      msMax: +Math.max(0, ...this.perf.ms).toFixed(2),
      fps: this.perf.rafDt.length ? +(1000 / mean(this.perf.rafDt)).toFixed(1) : 0,
      frames: this.perf.frames,
      samples: this.perf.ms.length,
    };
  }
  resetStats(): void {
    this.perf.ms.length = 0;
    this.perf.rafDt.length = 0;
    this.perf.frames = 0;
    this.perf.last = 0;
  }
  redraw(): void {
    this.draw();
  }
  get viewMatrix(): ViewMatrix {
    return { ...this.view };
  }

  // ── hit-testing + pointer ────────────────────────────────────────────────────────────────────
  private inside(t: Tile, wx: number, wy: number): boolean {
    return wx >= t.x && wx < t.x + this.tileSize && wy >= t.y && wy < t.y + this.tileSize;
  }

  /** Priority: the cursor, then the topmost layer's tile. A drag never demotes a tile — it corrects
   *  it (BEHAVIOUR R24); the feature keeps its state. */
  private hit(sx: number, sy: number): TileId | null {
    const [wx, wy] = this.screenToWorld(sx, sy);
    if (this.cursor != null) {
      const c = this.tiles.get(this.cursor);
      if (c && this.inside(c, wx, wy)) return this.cursor;
    }
    let best: TileId | null = null;
    let bestOrder = -Infinity;
    for (const t of this.tiles.values()) {
      if (!this.inside(t, wx, wy)) continue;
      const order = this.layerFor(t)?.order ?? -1;
      if (order > bestOrder) {
        best = t.id;
        bestOrder = order;
      }
    }
    return best;
  }

  private hitAlt(sx: number, sy: number): Candidate | null {
    if (!this.alts) return null;
    const [wx, wy] = this.screenToWorld(sx, sy);
    for (const c of this.alts.candidates) {
      if (c.rank === 0) continue;
      if (wx >= c.x && wx < c.x + this.tileSize && wy >= c.y && wy < c.y + this.tileSize) return c;
    }
    return null;
  }

  private onPointerDown = (e: PointerEvent): void => {
    this.canvas.setPointerCapture(e.pointerId);
    const mx = e.offsetX;
    const my = e.offsetY;
    const rightBtn = e.button === 2;
    const panBtn = e.button === 1 || e.altKey; // middle mouse or Alt — NOT Space (see handleKey)

    if (!panBtn && !rightBtn) {
      const a = this.hitAlt(mx, my);
      if (a && this.alts) {
        this.cb.onAlternativePick?.(this.alts.tile, a);
        return;
      }
    }

    // Read-only mounts never start a tile move or a marquee — every non-pan press falls to pan.
    const id = panBtn || rightBtn || this.readOnly ? null : this.hit(mx, my);
    if (id != null) {
      if (e.ctrlKey || e.metaKey) {
        if (this.sel.has(id)) this.sel.delete(id);
        else this.sel.add(id);
      } else if (!this.sel.has(id)) {
        this.sel.clear();
      }
      this.dragTile = id;
      this.removeFromLayers(id);
      const movers = (this.sel.size ? [...this.sel] : [id]).filter((k) => this.tiles.has(k));
      this.drag = {
        kind: 'move',
        mx,
        my,
        tile: id,
        movers,
        start: movers.map((k) => {
          const t = this.tiles.get(k)!;
          return { x: t.x, y: t.y };
        }),
        pushed: false,
      };
      for (const k of movers) if (k !== id) this.removeFromLayers(k);
      this.cb.onSelect?.(id);
    } else if (!this.readOnly && (rightBtn || (e.shiftKey && !panBtn))) {
      this.marquee = { x0: mx, y0: my, x1: mx, y1: my, add: e.ctrlKey || e.metaKey };
      this.drag = { kind: 'marquee' };
    } else {
      this.drag = { kind: 'pan', mx, my, tx: this.view.tx, ty: this.view.ty };
    }
    this.draw();
  };

  private onPointerMove = (e: PointerEvent): void => {
    const mx = e.offsetX;
    const my = e.offsetY;
    if (this.cb.onHover) {
      const [wx, wy] = this.screenToWorld(mx, my);
      this.cb.onHover(Math.round(wx), Math.round(wy), this.drag ? null : this.hit(mx, my));
    }
    const drag = this.drag;
    if (!drag) return;
    if (drag.kind === 'pan') {
      this.view.tx = drag.tx + (mx - drag.mx);
      this.view.ty = drag.ty + (my - drag.my);
      this.onView();
      return;
    }
    if (drag.kind === 'marquee') {
      if (this.marquee) {
        this.marquee.x1 = mx;
        this.marquee.y1 = my;
      }
      this.draw();
      return;
    }
    // move — the feature pushes ONE undo entry on the first pointermove (tagged folding).
    if (!drag.pushed) {
      drag.pushed = true;
      this.cb.onDragStart?.(drag.tile);
    }
    let dx = (mx - drag.mx) / this.view.scale;
    let dy = (my - drag.my) / this.view.scale;
    if (e.shiftKey) {
      if (Math.abs(dx) > Math.abs(dy)) dy = 0;
      else dx = 0;
    }
    drag.movers.forEach((k, i) => {
      const t = this.tiles.get(k);
      if (!t) return;
      t.x = drag.start[i].x + dx;
      t.y = drag.start[i].y + dy;
      this.cb.onDragMove?.(k, t.x, t.y);
    });
    this.draw();
  };

  private endDrag = (): void => {
    const drag = this.drag;
    if (!drag) {
      return;
    }
    if (drag.kind === 'marquee' && this.marquee) {
      const [ax, ay] = this.screenToWorld(
        Math.min(this.marquee.x0, this.marquee.x1),
        Math.min(this.marquee.y0, this.marquee.y1),
      );
      const [bx, by] = this.screenToWorld(
        Math.max(this.marquee.x0, this.marquee.x1),
        Math.max(this.marquee.y0, this.marquee.y1),
      );
      if (!this.marquee.add) this.sel.clear();
      const s = this.tileSize;
      for (const t of this.tiles.values()) {
        if (t.x + s > ax && t.x < bx && t.y + s > ay && t.y < by) this.sel.add(t.id);
      }
      this.cb.onSelect?.(this.sel.size === 1 ? [...this.sel][0] : null);
    } else if (drag.kind === 'move') {
      for (const k of drag.movers) {
        const t = this.tiles.get(k);
        if (t) this.cb.onDragEnd?.(k, t.x, t.y, { via: 'drag' });
      }
      this.dragTile = null;
      for (const k of drag.movers) this.syncTileLayer(k);
    }
    this.drag = null;
    this.marquee = null;
    this.dragTile = null;
    this.draw();
  };

  private onWheel = (e: WheelEvent): void => {
    e.preventDefault();
    this.zoomBy(Math.exp(-e.deltaY * 0.0016), e.offsetX, e.offsetY);
  };

  // ── keyboard (the CAMERA half only — BEHAVIOUR §3.4) ─────────────────────────────────────────
  handleKey(e: KeyboardEvent): boolean {
    const action = mapCameraKey(e);
    if (!action) return false; // Space, Ctrl/⌘ combos and typing all fall through to the feature
    switch (action.kind) {
      case 'nudge':
        if (this.nudge(action.dx, action.dy)) {
          e.preventDefault();
          return true;
        }
        return false;
      case 'fit':
        this.fit();
        break;
      case 'oneToOne':
        this.oneToOne();
        break;
      case 'difference':
        this.setDifference(!this.diff);
        break;
      case 'grid':
        this.setGrid(!this.showGrid);
        break;
      case 'zoom':
        this.zoomBy(action.factor);
        break;
      case 'escape':
        // Esc clears the selection and the ghosts. 🔴 It MUST NOT touch the cursor (BEHAVIOUR R14):
        // the feature is told onSelect(null) and is contractually required to ignore the null.
        this.sel.clear();
        this.clearAlternatives();
        this.cb.onSelect?.(null);
        this.draw();
        break;
    }
    e.preventDefault();
    return true;
  }

  // ── mount / unmount ──────────────────────────────────────────────────────────────────────────
  private attach(): void {
    const c = this.canvas;
    const onCtx = (e: Event): void => e.preventDefault();
    c.addEventListener('contextmenu', onCtx);
    c.addEventListener('pointerdown', this.onPointerDown);
    c.addEventListener('pointermove', this.onPointerMove);
    c.addEventListener('pointerup', this.endDrag);
    c.addEventListener('pointercancel', this.endDrag);
    c.addEventListener('wheel', this.onWheel, { passive: false });
    this.cleanups.push(() => {
      c.removeEventListener('contextmenu', onCtx);
      c.removeEventListener('pointerdown', this.onPointerDown);
      c.removeEventListener('pointermove', this.onPointerMove);
      c.removeEventListener('pointerup', this.endDrag);
      c.removeEventListener('pointercancel', this.endDrag);
      c.removeEventListener('wheel', this.onWheel);
    });

    // The engine mounts with keyboard OFF — the FEATURE owns keys and calls handleKey itself. No
    // window keydown listener is registered here, by design (BEHAVIOUR §3.4, task rule).

    try {
      this.ro = new ResizeObserver(() => this.resize());
      this.ro.observe(c);
    } catch {
      const onResize = (): void => this.resize();
      window.addEventListener('resize', onResize);
      this.cleanups.push(() => window.removeEventListener('resize', onResize));
    }
    try {
      this.mql = matchMedia('(prefers-color-scheme: dark)');
      this.mql.addEventListener('change', this.readTheme);
      this.mo = new MutationObserver(this.readTheme);
      this.mo.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ['data-theme'],
      });
    } catch {
      /* non-fatal — the theme simply will not live-update */
    }
  }

  destroy(): void {
    this.mounted = false;
    if (this.fade) {
      this.fade.resolve(false);
      this.fade = null;
    }
    for (const fn of this.cleanups) fn();
    this.cleanups.length = 0;
    this.ro?.disconnect();
    this.mo?.disconnect();
    this.mql?.removeEventListener('change', this.readTheme);
    for (const b of this.bitmaps.values()) b.close?.();
    this.bitmaps.clear();
    this.pending.clear();
  }
}
