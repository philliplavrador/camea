/**
 * THE VIEWER — the feature-agnostic, layered 2-D canvas that IS the hero of Camea
 * (docs/DESIGN_BRIEF §0/§4, BEHAVIOUR R9/R10/R13/R14/R18/R19/R20/§3.5).
 *
 * It knows IMAGES placed in world space, grouped into named LAYERS, one floating item under
 * inspection, and vector OVERLAYS — NOT anchors, unverified tiles, diverts or mosaics. The feature
 * (Sweep today; segmentation/annotation tomorrow) drives it through `ViewerHandle` (a ref) and gives
 * meaning to layers via their keys, a `reference` flag (the Difference-mode field) and per-tile
 * outline styles.
 *
 * ```tsx
 * const viewer = useRef<ViewerHandle>(null);
 * <Viewer
 *   ref={viewer}
 *   layers={[{ key: 'anchor', reference: true }, { key: 'unverified', visible: false }]}
 *   canvasProps={{ 'data-testid': 'sweep-canvas', 'data-anchor-layer': anchorCount }}
 *   onModelChange={(m) => setAnchorCount(m.layers.anchor.placed)}
 *   onDragEnd={(id, x, y) => …}
 * />
 * // one-tile change (0.1 ms, never a rebake):
 * viewer.current.setTile(11, { x: 0, y: 0, src: `/api/tile/11.png?v=${nonce}`, layer: 'anchor', feather: true });
 * ```
 *
 * See ./README.md for the full boundary + the data-* reflection contract.
 */
export { Viewer } from './Viewer';
export type { ViewerProps } from './Viewer';

export type {
  TileId,
  TileOutline,
  ViewerTile,
  LayerSpec,
  Candidate,
  ViewMatrix,
  LayerInfo,
  ModelInfo,
  ViewerStats,
  ViewerCallbacks,
  ViewerHandle,
} from './types';
export { TILE_SIZE, FADE_MS, FEATHER_PX } from './types';
