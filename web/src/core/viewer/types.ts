// The Viewer's public vocabulary. It is FEATURE-AGNOSTIC: it knows IMAGES placed in world space,
// grouped into named LAYERS, plus one floating item under inspection and some vector OVERLAYS. It
// does NOT know about anchors, unverified tiles, diverts or mosaics — those are the feature's
// meaning, conveyed through generic knobs (a layer key, a `reference` flag, a per-tile outline).

/**
 * A tile identifier. The feature uses trial numbers; the viewer treats it as an opaque key. Numeric
 * strings are coerced to numbers so `setTiles({ 11: … })` (object keys are strings) and
 * `setTile(11, …)` address the same tile.
 */
export type TileId = number | string;

/** A vector outline drawn over a tile — the viewer's ONLY per-tile decoration knob. The feature
 *  chooses the colour (e.g. its "unverified" or "diverted" hue); the viewer knows no such names. */
export interface TileOutline {
  /** Any CSS colour. Resolve your design token to a value, or pass a `var(--…)` string. */
  color: string;
  /** Dash pattern, e.g. `[6, 4]`. Omit for a solid line. */
  dash?: number[];
  /** Line width in screen px (default 1). */
  width?: number;
}

/** One placed image. Position is the TOP-LEFT world corner (never the centre — BEHAVIOUR R19). */
export interface ViewerTile {
  x: number;
  y: number;
  /** Image URL. **This string is the bitmap cache key** — bake your cache-buster into it so the same
   *  URL never maps to different bytes (BEHAVIOUR R31/R32). Changing the URL re-fetches. */
  src: string;
  /** Which baked layer this tile belongs to. Must be one of the keys given to the viewer. */
  layer: string;
  /** Feather this tile's edges into its layer? Layers feather; the float never does (R10.2). */
  feather?: boolean;
  /** An optional vector outline, drawn only while the tile's layer is visible (R9.5). */
  outline?: TileOutline | null;
}

/** A baked draw layer. Order is the array order given at mount; earlier = drawn first (below). */
export interface LayerSpec {
  key: string;
  /** Whole-layer draw alpha, 0–1 (default 1). */
  alpha?: number;
  /** Drawn at all? A maintained-but-hidden layer still holds its tiles (default true). */
  visible?: boolean;
  /** Part of the difference-mode REFERENCE field. In Difference mode ONLY reference layers are drawn,
   *  and the float is composited against them (BEHAVIOUR §3.5 — "the destination MUST be the anchor
   *  field alone"). Default false. */
  reference?: boolean;
}

/** A ranked alternative position to ghost on the canvas. `rank` is 0-indexed storage; the DISPLAY
 *  label (`#rank+1`) is the feature's to format (BEHAVIOUR R12.3) — pass it in `label`. */
export interface Candidate {
  rank: number;
  x: number;
  y: number;
  label?: string;
}

export interface ViewMatrix {
  scale: number;
  tx: number;
  ty: number;
}

/** Per-layer state the feature reflects onto the canvas (e.g. `data-anchor-layer`). */
export interface LayerInfo {
  /** Placed tiles whose `layer` is this key — INCLUDING one currently floating as the cursor. This is
   *  the "certified count" the sweep shows: pressing A adds the cursor tile to its layer at once. */
  placed: number;
  /** Tiles actually baked into the offscreen layer canvas right now (excludes floats mid-fade). */
  baked: number;
  visible: boolean;
  reference: boolean;
  overflow: boolean;
}

/** Emitted after every discrete model change so the feature can reflect semantic canvas attributes
 *  (`data-anchor-layer` = layers.<ref>.placed, `data-unverified-drawn` = layers.<other>.visible, …).
 *  NOT emitted inside the render loop. */
export interface ModelInfo {
  layers: Record<string, LayerInfo>;
  difference: boolean;
  floatAlpha: number;
  cursor: TileId | null;
}

export interface ViewerStats {
  /** Mean ms per rendered frame. It MUST read ~6 ms; ~90 ms means a full rebake per frame (R20). */
  ms: number;
  msMedian: number;
  msP95: number;
  msMax: number;
  fps: number;
  frames: number;
  samples: number;
}

/** The events the viewer raises. The feature owns all meaning; the viewer only reports gestures. */
export interface ViewerCallbacks {
  onDragStart?(id: TileId): void;
  onDragMove?(id: TileId, x: number, y: number): void;
  onDragEnd?(id: TileId, x: number, y: number, meta: { via: 'drag' | 'nudge' }): void;
  /** A tile was clicked/marquee-selected, or Escape cleared the selection (`null`). ⚠️ On `null` the
   *  feature MUST NOT clear its cursor — Escape deselects, it does not abandon the tile (R14). */
  onSelect?(id: TileId | null): void;
  onFadeEnd?(id: TileId): void;
  onAlternativePick?(id: TileId, candidate: Candidate): void;
  onHover?(worldX: number, worldY: number, id: TileId | null): void;
  onView?(view: ViewMatrix): void;
  onDifference?(on: boolean): void;
  onModelChange?(info: ModelInfo): void;
  onError?(id: TileId, err: unknown): void;
}

/** The imperative handle the feature drives the viewer through (`ref` on `<Viewer>`). */
export interface ViewerHandle {
  /** Replace the whole model and rebake (~one-off cost). NEVER call this for a single-tile change. */
  setTiles(model: Record<string, ViewerTile> | Map<TileId, ViewerTile>): void;
  /** Upsert or (with `null`) remove ONE tile. Cheap: an append is ~0.1 ms; it never rebakes (R20). */
  setTile(id: TileId, tile: ViewerTile | null): void;
  getTile(id: TileId): (ViewerTile & { id: TileId }) | null;

  /** The tile under judgement: floats above the layers, drawn crisp, draggable, differenceable. */
  setCursor(id: TileId | null): void;
  getCursor(): TileId | null;

  /** Place `id` at (x, y) if given, then fade it 0 → floatAlpha over the 1 s fade. Resolves when the
   *  fade ends (or `false` if superseded). The fade is the core check — its length is fixed. */
  fadeIn(id: TileId, x?: number, y?: number): Promise<boolean>;
  replayFade(): Promise<boolean>;

  setDifference(on: boolean): void;
  isDifference(): boolean;
  /** Opacity of the floating tile, 0.15–1.00. Difference mode ignores it (BEHAVIOUR R13.4). */
  setFloatAlpha(a: number): void;
  getFloatAlpha(): number;

  setLayerVisible(key: string, on: boolean): void;
  setLayerAlpha(key: string, a: number): void;
  /** Placed tiles in a layer, counting a floating cursor tile that belongs to it (see LayerInfo). */
  layerPlacedCount(key: string): number;

  showAlternatives(id: TileId, candidates: Candidate[]): void;
  clearAlternatives(): void;

  setSelection(ids: TileId[]): void;
  getSelection(): TileId[];
  /** Nudge the cursor tile (or the selection) by world px. Reports via onDragEnd for undo folding. */
  nudge(dx: number, dy: number): boolean;
  setGrid(on: boolean): void;

  fit(): void;
  oneToOne(): void;
  zoomBy(k: number, cx?: number, cy?: number): void;
  centreOn(id: TileId): void;
  reveal(id: TileId): void;
  screenToWorld(sx: number, sy: number): [number, number];
  worldToScreen(wx: number, wy: number): [number, number];

  /** Dispatch a camera key (F / 0 / D / G / arrows / +/- / Esc). Returns true iff it acted. `Space`
   *  and Ctrl/⌘ combos always return false — they are the feature's (BEHAVIOUR §3.4, §6.7). */
  handleKey(e: KeyboardEvent): boolean;

  /** Warm the bitmap cache for these URLs (the feature prefetches the next tile's pixels). */
  preload(srcs: string[]): void;
  /** Drop & close every cached ImageBitmap — call on a session/run change to free memory (R31). */
  clearBitmapCache(): void;

  stats(): ViewerStats;
  resetStats(): void;
  redraw(): void;
  resize(): void;
  readonly view: ViewMatrix;
}

// ── Product-wide constants (BEHAVIOUR §7 — these MUST NOT diverge across the two halves) ──────────
/** The tile edge in px. Square. Overridable per mount via `tileSize`, but 512 is the data. */
export const TILE_SIZE = 512;
/** The placement fade. THE FADE IS THE POINT — never shortened "to feel snappier" (R13.3). */
export const FADE_MS = 1000;
/** The baked-field alpha ramp width, of 512. Floats are never feathered (R10.3). */
export const FEATHER_PX = 40;
