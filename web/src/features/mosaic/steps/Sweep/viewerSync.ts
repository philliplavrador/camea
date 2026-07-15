// ─────────────────────────────────────────────────────────────────────────────────────────────
// THE STORE → VIEWER RECONCILER.  (docs/BEHAVIOUR.md R9, R10, R20.)
//
// The sweep store owns the document; the Viewer owns the pixels. This installs a subscription that keeps
// the imperative viewer in step with the store WITHOUT ever calling `setTiles` for a single-tile change
// (R20 — that is a full rebake, catastrophic in the loop). Every doc mutation is diffed per-tile and
// applied with `setTile` (~0.1 ms).
//
// R9 — THE CANVAS DRAWS ONLY THE CERTIFIED FIELD + THE ONE TILE UNDER JUDGEMENT:
//   • anchored tiles  → the `anchor` layer (feathered — R10; it is the Difference reference).
//   • unverified tiles → the `unverified` layer, which is MAINTAINED BUT NOT DRAWN (visible:false).
//   • the cursor tile  → a crisp float (R10.2), shown even when it has no committed position yet
//     ("trial 11 fades in over nothing" — R9), at the nearest placed neighbour's spot, or the origin.
//   • unplaced / excluded → not drawn at all.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { useEffect, useRef } from 'react';
import type { RefObject } from 'react';
import type {
  ViewerHandle,
  ViewerTile,
  Candidate as ViewerCandidate,
} from '../../../../core/viewer';
import type { MosaicDocument } from '../../../../api';
import { useSweepStore } from '../../store';
import type { SweepState } from '../../store';

type Tile = MosaicDocument['tiles'][string];

const K = (t: number): string => String(t);

/** The world position of the nearest PLACED trial before `cursor` in run order, or null. */
function nearestPlaced(
  doc: MosaicDocument,
  order: number[],
  cursor: number,
): [number, number] | null {
  const i = order.indexOf(cursor);
  for (let j = i - 1; j >= 0; j--) {
    const t = doc.tiles[K(order[j])];
    if (t && t.x != null && t.y != null) return [t.x, t.y];
  }
  return null;
}

/** The ViewerTile a document tile maps to, or null when it is not drawn (unplaced / excluded). */
export function viewerTileFor(tile: Tile, src: string): ViewerTile | null {
  if (tile.x == null || tile.y == null || tile.state === 'excluded') return null;
  if (tile.state === 'anchored') {
    return { x: tile.x, y: tile.y, src, layer: 'anchor', feather: true, outline: null };
  }
  if (tile.state === 'unverified') {
    return { x: tile.x, y: tile.y, src, layer: 'unverified', feather: false, outline: null };
  }
  return null;
}

function tileEqual(a: ViewerTile | null, b: ViewerTile | null): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  return (
    a.x === b.x &&
    a.y === b.y &&
    a.src === b.src &&
    a.layer === b.layer &&
    !!a.feather === !!b.feather
  );
}

/** Diff the document against what the viewer holds and apply the minimal per-tile changes (R20). */
function syncTiles(
  v: ViewerHandle,
  doc: MosaicDocument | null,
  order: number[],
  cursor: number | null,
  src: (t: number) => string,
  applied: Map<string, ViewerTile | null>,
): void {
  if (!doc) return;

  // The tile under judgement is ALWAYS shown as a float, even before it has a committed position
  // (R9 — "trial 11 fades in over nothing"). Give it a display position: the nearest placed neighbour,
  // or the world origin for the very first tile.
  const cursorTile = cursor != null ? doc.tiles[K(cursor)] : undefined;
  const cursorNeedsDisplay =
    cursor != null &&
    cursorTile != null &&
    cursorTile.state !== 'excluded' &&
    (cursorTile.x == null || cursorTile.y == null);
  const displayPos: [number, number] = cursorNeedsDisplay
    ? (nearestPlaced(doc, order, cursor) ?? [0, 0])
    : [0, 0];

  const keys = new Set<string>();
  for (const t of order) {
    const key = K(t);
    keys.add(key);
    const tile = doc.tiles[key];
    let vt = tile ? viewerTileFor(tile, src(t)) : null;
    if (vt === null && tile && t === cursor && cursorNeedsDisplay) {
      vt = {
        x: displayPos[0],
        y: displayPos[1],
        src: src(t),
        layer: 'unverified',
        feather: false,
        outline: null,
      };
    }
    const prevVt = applied.get(key) ?? null;
    if (!tileEqual(vt, prevVt)) {
      v.setTile(t, vt);
      applied.set(key, vt);
    }
  }
  // A tile that fell out of the run order entirely (defensive — the order rarely changes mid-sweep).
  for (const key of applied.keys()) {
    if (!keys.has(key) && applied.get(key) != null) {
      v.setTile(Number(key), null);
      applied.set(key, null);
    }
  }
}

/** Push the ranked alternatives onto the canvas (violet ghosts), labelled `#rank+1` (R12.3). */
function applyAlts(v: ViewerHandle, s: SweepState): void {
  if (!s.altsOn || s.cursor == null) {
    v.clearAlternatives();
    return;
  }
  const ev = s.evidence[K(s.cursor)];
  if (!ev || !ev.candidates.length) {
    v.clearAlternatives();
    return;
  }
  const cands: ViewerCandidate[] = ev.candidates.map((c) => ({
    rank: c.rank,
    x: c.x,
    y: c.y,
    label: `#${c.rank + 1}`,
  }));
  v.showAlternatives(s.cursor, cands);
}

function modelHasTiles(applied: Map<string, ViewerTile | null>): boolean {
  for (const vt of applied.values()) if (vt != null) return true;
  return false;
}

/**
 * Wire the viewer to the sweep store for the lifetime of the Sweep. It performs one full sync on mount,
 * then reconciles every store mutation imperatively (outside React's render, for the R20 frame budget).
 */
export function useViewerSync(
  viewerRef: RefObject<ViewerHandle | null>,
  tileSrc: (t: number) => string,
): void {
  const srcRef = useRef(tileSrc);
  srcRef.current = tileSrc;

  useEffect(() => {
    const v = viewerRef.current;
    if (!v) return;
    const src = (t: number): string => srcRef.current(t);
    const applied = new Map<string, ViewerTile | null>();

    let prev = useSweepStore.getState();

    // ── initial full sync ──────────────────────────────────────────────────────────────────────
    if (prev.doc) {
      syncTiles(v, prev.doc, prev.order, prev.cursor, src, applied);
      if (v.getCursor() !== prev.cursor) v.setCursor(prev.cursor);
      if (v.getFloatAlpha() !== prev.floatAlpha) v.setFloatAlpha(prev.floatAlpha);
      if (v.isDifference() !== prev.diffMode) v.setDifference(prev.diffMode);
      if (modelHasTiles(applied)) v.fit();
      applyAlts(v, prev);
      // R9 — the tile under judgement fades in on entry (over the field, or over nothing).
      if (prev.cursor != null) void v.fadeIn(prev.cursor);
    }

    // ── reconcile every mutation ────────────────────────────────────────────────────────────────
    const unsub = useSweepStore.subscribe((next) => {
      if (next.doc !== prev.doc) {
        syncTiles(v, next.doc, next.order, next.cursor, src, applied);
      }
      // Keep the engine cursor in step — this also re-asserts it after an excluded tile was removed
      // (removing the cursor's tile nulls the engine cursor, but the store cursor stays put — R14).
      if (v.getCursor() !== next.cursor) v.setCursor(next.cursor);
      if (next.fade !== prev.fade && next.fade) void v.fadeIn(next.fade.trial);
      if (next.floatAlpha !== prev.floatAlpha && v.getFloatAlpha() !== next.floatAlpha) {
        v.setFloatAlpha(next.floatAlpha);
      }
      const altsRelevant =
        next.altsOn !== prev.altsOn ||
        (next.altsOn && (next.evidence !== prev.evidence || next.cursor !== prev.cursor));
      if (altsRelevant) applyAlts(v, next);
      prev = next;
    });
    return unsub;
    // The viewer handle is stable for the component's life; re-running would rebuild the whole model.
  }, [viewerRef]);
}
