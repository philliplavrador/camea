// <Viewer> — the thin React shell around ViewerEngine. It owns exactly one <canvas>, creates the
// engine ONCE on mount (props changes never recreate it — the canvas keeps its baked pixels), and
// exposes the imperative ViewerHandle the feature drives it through.
//
// The engine is imperative and RAF-driven; React re-renders here are cheap and NEVER touch the paint
// path. Callbacks are read through a ref so a feature that passes fresh closures each render does not
// churn the engine. Spread `canvasProps` to attach `data-testid` and the semantic data-* attributes
// the feature derives from onModelChange (e.g. `data-anchor-layer`, `data-unverified-drawn`); the
// viewer itself stamps the generic `data-diff` / `data-float-alpha`.

import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react';
import { cx } from '../../design/cx';
import { ViewerEngine } from './engine';
import styles from './Viewer.module.css';
import type {
  Candidate,
  LayerSpec,
  TileId,
  ViewerCallbacks,
  ViewerHandle,
  ViewerTile,
  ViewMatrix,
} from './types';

export interface ViewerProps extends ViewerCallbacks {
  /** The baked draw layers, in draw order (earlier = below). Read ONCE at mount. */
  layers: LayerSpec[];
  /** Tile edge in px (square). Default 512 (BEHAVIOUR §7). Read once at mount. */
  tileSize?: number;
  /** Start with the 512-px world grid on? Default false. Read once at mount. */
  grid?: boolean;
  className?: string;
  /** Extra props spread onto the <canvas> — e.g. `data-testid="sweep-canvas"` and the feature's
   *  derived `data-*` attributes. */
  canvasProps?: React.CanvasHTMLAttributes<HTMLCanvasElement>;
}

const NO_VIEW: ViewMatrix = { scale: 1, tx: 0, ty: 0 };

export const Viewer = forwardRef<ViewerHandle, ViewerProps>(function Viewer(props, ref) {
  const { layers, tileSize, grid, className, canvasProps, ...callbacks } = props;

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const engineRef = useRef<ViewerEngine | null>(null);

  // Latest callbacks, read at call time so fresh closures never recreate the engine.
  const cbRef = useRef<ViewerCallbacks>(callbacks);
  cbRef.current = callbacks;

  // Construction options are captured once — the engine is created a single time.
  const initRef = useRef({ layers, tileSize, grid });

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const cb: ViewerCallbacks = {
      onDragStart: (id) => cbRef.current.onDragStart?.(id),
      onDragMove: (id, x, y) => cbRef.current.onDragMove?.(id, x, y),
      onDragEnd: (id, x, y, meta) => cbRef.current.onDragEnd?.(id, x, y, meta),
      onSelect: (id) => cbRef.current.onSelect?.(id),
      onFadeEnd: (id) => cbRef.current.onFadeEnd?.(id),
      onAlternativePick: (id, c) => cbRef.current.onAlternativePick?.(id, c),
      onHover: (wx, wy, id) => cbRef.current.onHover?.(wx, wy, id),
      onView: (v) => cbRef.current.onView?.(v),
      onDifference: (on) => cbRef.current.onDifference?.(on),
      onModelChange: (info) => cbRef.current.onModelChange?.(info),
      onError: (id, err) => cbRef.current.onError?.(id, err),
    };
    const engine = new ViewerEngine(canvas, {
      layers: initRef.current.layers,
      tileSize: initRef.current.tileSize,
      grid: initRef.current.grid,
      cb,
    });
    engineRef.current = engine;
    return () => {
      engine.destroy();
      engineRef.current = null;
    };
  }, []);

  useImperativeHandle(
    ref,
    (): ViewerHandle => ({
      setTiles: (m) => engineRef.current?.setTiles(m),
      setTile: (id: TileId, t: ViewerTile | null) => engineRef.current?.setTile(id, t),
      getTile: (id) => engineRef.current?.getTile(id) ?? null,
      setCursor: (id) => engineRef.current?.setCursor(id),
      getCursor: () => engineRef.current?.getCursor() ?? null,
      fadeIn: (id, x, y) => engineRef.current?.fadeIn(id, x, y) ?? Promise.resolve(false),
      replayFade: () => engineRef.current?.replayFade() ?? Promise.resolve(false),
      setDifference: (on) => engineRef.current?.setDifference(on),
      isDifference: () => engineRef.current?.isDifference() ?? false,
      setFloatAlpha: (a) => engineRef.current?.setFloatAlpha(a),
      getFloatAlpha: () => engineRef.current?.getFloatAlpha() ?? 1,
      setLayerVisible: (k, on) => engineRef.current?.setLayerVisible(k, on),
      setLayerAlpha: (k, a) => engineRef.current?.setLayerAlpha(k, a),
      layerPlacedCount: (k) => engineRef.current?.layerPlacedCount(k) ?? 0,
      showAlternatives: (id: TileId, c: Candidate[]) => engineRef.current?.showAlternatives(id, c),
      clearAlternatives: () => engineRef.current?.clearAlternatives(),
      setSelection: (ids) => engineRef.current?.setSelection(ids),
      getSelection: () => engineRef.current?.getSelection() ?? [],
      nudge: (dx, dy) => engineRef.current?.nudge(dx, dy) ?? false,
      setGrid: (on) => engineRef.current?.setGrid(on),
      fit: () => engineRef.current?.fit(),
      oneToOne: () => engineRef.current?.oneToOne(),
      zoomBy: (k, cx, cy) => engineRef.current?.zoomBy(k, cx, cy),
      centreOn: (id) => engineRef.current?.centreOn(id),
      reveal: (id) => engineRef.current?.reveal(id),
      screenToWorld: (sx, sy) => engineRef.current?.screenToWorld(sx, sy) ?? [0, 0],
      worldToScreen: (wx, wy) => engineRef.current?.worldToScreen(wx, wy) ?? [0, 0],
      handleKey: (e) => engineRef.current?.handleKey(e) ?? false,
      preload: (srcs) => engineRef.current?.preload(srcs),
      clearBitmapCache: () => engineRef.current?.clearBitmapCache(),
      stats: () =>
        engineRef.current?.stats() ?? {
          ms: 0,
          msMedian: 0,
          msP95: 0,
          msMax: 0,
          fps: 0,
          frames: 0,
          samples: 0,
        },
      resetStats: () => engineRef.current?.resetStats(),
      redraw: () => engineRef.current?.redraw(),
      resize: () => engineRef.current?.resize(),
      get view() {
        return engineRef.current?.viewMatrix ?? NO_VIEW;
      },
    }),
    [],
  );

  return <canvas ref={canvasRef} className={cx(styles.canvas, className)} {...canvasProps} />;
});
