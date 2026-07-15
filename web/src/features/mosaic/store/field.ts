// THE ANCHOR-FIELD LAYER — the request bodies that ARE the R21/R22 cache key, and the signature that
// stamps every cached evidence entry.
//
// 🔴 THE REQUEST BODY IS THE MEMO KEY (BEHAVIOUR R21). The server memoises `match/anchor` on
// {session, target, sorted anchors + their positions, mode, near, radius, max, sorted refuse}. So:
//   * a match request must ALWAYS carry the CURRENT anchor set (never a trial-keyed client cache — §6.8);
//   * the prefetch is the SAME POST fired early, with the tile under judgement ADDED to `anchors` (it
//     assumes the user will press `A`), and its answer is DISCARDED. A warm foreground call is then a
//     ~1 ms memo hit iff — and only iff — the anchor set it sends is the one the prefetch assumed.
//
// 🔴 A TILE IS NEVER AN ANCHOR FOR ITS OWN MATCH. `target` is filtered out of `anchors` here, once, so
//    re-matching an already-anchored tile (a correction — R24) does not ship it inside its own field and
//    earn a 400. Filtering it out also leaves the prefetch's A-branch untouched (there `target` is the
//    NEXT tile, never the one being certified).

import type { MatchAnchorRequest, MatchScoreRequest } from '../../../api';
import type { Tiles, Position } from './types';
import { anchoredTrials, positionsOf, tileOf } from './machine';
import { SNAP_RADIUS, MAX_CANDIDATES } from './constants';

export interface MatchInputs {
  sessionId: string;
  target: number;
  tiles: Tiles;
  order: number[];
  /** The blank list the human left standing (`doc.blank_scan.blank`) — part of the cache key (R16/R21). */
  refuse: number[];
}

/**
 * Build the `match/anchor` request for `target` against the CURRENT anchor field. `mode: 'global'` by
 * default; `local` (with `near`) for a drag-snap. Returns null when there is no anchor to match against —
 * the caller treats that as `refused: no_anchors` (a tile cannot match against an empty field).
 */
export function buildMatchRequest(
  inp: MatchInputs,
  opts: { mode?: 'global' | 'local'; near?: Position | null; anchors?: number[] } = {},
): MatchAnchorRequest | null {
  const field = (opts.anchors ?? anchoredTrials(inp.tiles, inp.order)).filter(
    (t) => t !== inp.target,
  );
  if (field.length === 0) return null;
  return {
    session_id: inp.sessionId,
    target: inp.target,
    anchors: field,
    positions: positionsOf(inp.tiles, field),
    mode: opts.mode ?? 'global',
    near: opts.near ?? null,
    radius: SNAP_RADIUS,
    max_candidates: MAX_CANDIDATES,
    refuse: inp.refuse,
  };
}

/**
 * 🔴 THE PREFETCH REQUEST (BEHAVIOUR R21). Match `next`, ASSUMING the user is about to press `A` on
 * `judged` — i.e. with `judged` added to the anchor field at its current position. Exact by construction.
 * Returns null when there is nothing to warm (no field, or `judged` cannot join it).
 *
 * ⚠️ The answer must be DISCARDED by the caller. This builds the same shape `buildMatchRequest` does, so
 * the foreground call for `next` produces a byte-identical body — and hits the memo — precisely when the
 * user does press `A`. Press `E` or defer, and the anchor set differs → the key differs → an honest miss.
 */
export function buildPrefetchRequest(
  inp: Omit<MatchInputs, 'target'>,
  judged: number,
  next: number,
): MatchAnchorRequest | null {
  let field = anchoredTrials(inp.tiles, inp.order);
  const jt = tileOf(inp.tiles, judged);
  // The A-branch: if `judged` has a position and is not excluded and not already an anchor, assume it is
  // about to become one, at exactly where it sits now.
  if (jt && jt.state !== 'excluded' && jt.x != null && !field.includes(judged)) {
    field = field.concat([judged]);
  }
  field = field.filter((t) => t !== next);
  if (field.length === 0) return null;
  return {
    session_id: inp.sessionId,
    target: next,
    anchors: field,
    positions: positionsOf(inp.tiles, field),
    mode: 'global',
    near: null,
    radius: SNAP_RADIUS,
    max_candidates: MAX_CANDIDATES,
    refuse: inp.refuse,
  };
}

/** Build the `match/score` request — "you dropped it here; what do the pixels say?" (one exact NCC). */
export function buildScoreRequest(inp: MatchInputs, at: Position): MatchScoreRequest | null {
  const field = anchoredTrials(inp.tiles, inp.order).filter((t) => t !== inp.target);
  if (field.length === 0) return null;
  return {
    session_id: inp.sessionId,
    target: inp.target,
    anchors: field,
    positions: positionsOf(inp.tiles, field),
    at,
    refuse: inp.refuse,
  };
}

/**
 * ⭐ THE FIELD SIGNATURE (BEHAVIOUR R22). A stable hash of the anchor field a match against `target`
 * would see (the anchored set MINUS target, with positions). Two calls agree ⟺ the server would return
 * the same answer. Every cached evidence entry is stamped with this; anything that would ACT on it (`V`,
 * `1`–`9`) re-fetches unless the stamp still matches the field the app has NOW.
 *
 * djb2 over the SAME payload the server's memo key is built from (hashed, not stored raw: at 312 anchors
 * the literal string is ~6 kB and it is snapshotted into all 100 undo entries).
 */
export function fieldSignature(tiles: Tiles, order: number[], target: number): string {
  const field = anchoredTrials(tiles, order);
  let h = 5381;
  let n = 0;
  for (const t of field) {
    if (t === target) continue;
    const tl = tileOf(tiles, t);
    if (!tl || tl.x == null || tl.y == null) continue;
    const s = `${t}:${tl.x.toFixed(3)},${tl.y.toFixed(3)}|`;
    for (let k = 0; k < s.length; k++) h = (((h << 5) + h) ^ s.charCodeAt(k)) >>> 0;
    n += 1;
  }
  return `${h.toString(16)}.${n}`;
}
