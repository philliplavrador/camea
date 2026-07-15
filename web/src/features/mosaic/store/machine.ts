// ⭐ THE TILE STATE MACHINE (BEHAVIOUR §4). Four states, no others. These are PURE functions over a
// tiles map — they take a `Tiles` object and return a NEW one (immutable), with no store, network, or
// dataset knowledge. `applyState` is the ONE place a tile's state is ever written; it is the analogue of
// v1's `setState`, and getting the state↔status mapping wrong lands nothing or everything in the exported
// ground truth (`load_gt` keeps every `status === "anchor"`).
//
// The FIVE FACTS THAT ARE NOT STATES (§4.3) attach to a tile and are handled here, not modelled as
// states: `blank` (MEASURED — never cleared, not even by E→A), `diverted` (dies when a hand rewrites the
// position — R34), `human` (a hand put it here; advance never re-matches over it — R24b), `stale`
// (matched against a field that has since changed), `machine` (what the solver said, translated).

import type { Tile, TileState, Tiles, Position } from './types';

const STATUS: Record<TileState, Tile['status']> = {
  unplaced: 'unplaced',
  unverified: 'unverified',
  anchored: 'anchor',
  excluded: 'excluded',
};

const STATE_FROM_STATUS: Record<Tile['status'], TileState> = {
  unplaced: 'unplaced',
  unverified: 'unverified',
  anchor: 'anchored',
  excluded: 'excluded',
};

/** The on-disk `status` for an in-memory `state`. ⚠️ `anchored` ↔ `"anchor"` — they differ (§4). */
export function statusFor(state: TileState): Tile['status'] {
  return STATUS[state];
}

/** On load, `state` wins if present, else it is derived from `status` (§4). */
export function stateFor(tile: Pick<Tile, 'state' | 'status'>): TileState {
  return tile.state ?? STATE_FROM_STATUS[tile.status];
}

const K = (t: number): string => String(t);

/** A tile record, or undefined. */
export function tileOf(tiles: Tiles, t: number): Tile | undefined {
  return tiles[K(t)];
}

// ── Derived views over the tiles map (no dataset knowledge — `order` is whatever the run is) ──────────

/** The certified field: the trials (in run order) whose state is `anchored`. This — and only this — is
 *  what a match sees. An `unverified` tile the human has not certified does NOT get a vote. */
export function anchoredTrials(tiles: Tiles, order: number[]): number[] {
  return order.filter((t) => tileOf(tiles, t)?.state === 'anchored');
}

/** Everything the user has NOT excluded — what a build is given (BEHAVIOUR R35). */
export function activeTrials(tiles: Tiles, order: number[]): number[] {
  return order.filter((t) => tileOf(tiles, t)?.state !== 'excluded');
}

/** Does any tile have a position at all? (Guards the origin branch of `A`.) */
export function anyPlaced(tiles: Tiles, order: number[]): boolean {
  return order.some((t) => {
    const tl = tileOf(tiles, t);
    return tl != null && tl.x != null;
  });
}

/** The next non-excluded trial after `t`. No wrapping — at the end, the sweep is done (§4.2). */
export function nextTrial(order: number[], tiles: Tiles, t: number | null): number | null {
  const i = t === null ? -1 : order.indexOf(t);
  for (let j = i + 1; j < order.length; j++) {
    if (tileOf(tiles, order[j])?.state !== 'excluded') return order[j];
  }
  return null;
}

/** The previous non-excluded trial before `t`. */
export function prevTrial(order: number[], tiles: Tiles, t: number | null): number | null {
  const i = t === null ? order.length : order.indexOf(t);
  for (let j = i - 1; j >= 0; j--) {
    if (tileOf(tiles, order[j])?.state !== 'excluded') return order[j];
  }
  return null;
}

/** Header counts. `diverted` counts ONLY still-`unverified` diverts (an anchored tile keeps its divert
 *  record as provenance but must not nag from the header — §4.3). */
export interface Counts {
  anchored: number;
  unverified: number;
  unplaced: number;
  excluded: number;
  diverted: number;
}
export function counts(tiles: Tiles, order: number[]): Counts {
  const c: Counts = { anchored: 0, unverified: 0, unplaced: 0, excluded: 0, diverted: 0 };
  for (const t of order) {
    const tl = tileOf(tiles, t);
    if (!tl) continue;
    c[tl.state] += 1;
    if (tl.diverted && tl.state === 'unverified' && tl.x != null) c.diverted += 1;
  }
  return c;
}

// ── The transition primitives ─────────────────────────────────────────────────────────────────────

/** Return `tiles` with `t` replaced by `next` (immutable, one shallow clone). */
function withTile(tiles: Tiles, t: number, next: Tile): Tiles {
  return { ...tiles, [K(t)]: next };
}

/**
 * ⭐ THE ONLY PLACE A TILE'S STATE IS WRITTEN (v1 `setState`). Returns a NEW tile record.
 *
 * - Writes both `state` and `status` (they differ for anchored/"anchor").
 * - 🔴 A tile that LEAVES `excluded` stops claiming it was thrown out: `excluded_reason` /
 *   `unusable_reason` / `last_xy` are cleared (R34). ⚠️ `blank` is NOT cleared — a measurement, not a
 *   judgement. `diverted` is NOT cleared here either (only a hand move clears it — see `applyPos`); an
 *   anchored diverted tile keeps its provenance.
 * - `x`/`y` are nulled for `excluded`/`unplaced`, else set from `pos`.
 * - `seq` is bumped (by the caller's counter, passed in) for `anchored`/`unverified` — the stale cascade
 *   keys on it.
 * - `moved_px` is kept honest wherever a position is written (|position − machine|).
 */
export function applyState(
  tile: Tile,
  state: TileState,
  pos: Position | null,
  seq: number | undefined,
): Tile {
  const next: Tile = { ...tile, state, status: STATUS[state] };

  if (state !== 'excluded') {
    next.excluded_reason = undefined;
    next.unusable_reason = undefined;
    next.last_xy = undefined;
    // `excluded` was a v1 non-schema boolean; clear it via the extras index so a re-anchored tile does
    // not carry a self-contradicting `excluded: true`.
    delete (next as Record<string, unknown>).excluded;
  }

  if (state === 'excluded' || state === 'unplaced') {
    next.x = null;
    next.y = null;
  } else if (pos) {
    next.x = pos[0];
    next.y = pos[1];
  }

  if (state === 'anchored' || state === 'unverified') next.seq = seq;

  if (next.machine && next.x != null && next.y != null) {
    next.moved_px = Math.hypot(next.x - next.machine[0], next.y - next.machine[1]);
  }
  return next;
}

/**
 * A HAND has taken the tile over (a drag, `S`, an arrow nudge, a `V`/digit pick). Rewrites the position
 * and 🔴 KILLS THE DIVERT CLAIM (R34) — at the single place a position is rewritten. Leaves `state`
 * untouched (a drag never demotes an anchor — R24; the caller sets `human`). Does not clear `blank`.
 */
export function applyPos(tile: Tile, pos: Position): Tile {
  const next: Tile = { ...tile, x: pos[0], y: pos[1] };
  next.diverted = false;
  next.divert_reason = undefined;
  next.rejected_match = undefined;
  if (next.machine) {
    next.moved_px = Math.hypot(pos[0] - next.machine[0], pos[1] - next.machine[1]);
  }
  return next;
}

/**
 * 🔴 MARK DOWNSTREAM TILES STALE (BEHAVIOUR R11.3 / R24). Every `anchored`/`unverified` tile with
 * `seq > afterSeq` (except `exceptTrial`) was matched against a field that contained the tile that just
 * moved / un-anchored / excluded. Returns the new tiles map and the list flagged.
 *
 * 🔴 AND ITS EVIDENCE DIES WITH IT — the caller drops `evidence[t]` for each returned trial, or `V`
 * happily moves the tile onto a candidate measured against the old field (R22, R25).
 *
 * Self-limiting: un-anchoring the tile you JUST anchored has the highest seq, so nothing is flagged.
 */
export function markStaleAfter(
  tiles: Tiles,
  order: number[],
  afterSeq: number | undefined,
  exceptTrial: number,
): { tiles: Tiles; stale: number[] } {
  if (afterSeq === undefined) return { tiles, stale: [] };
  let out = tiles;
  const stale: number[] = [];
  for (const t of order) {
    if (t === exceptTrial) continue;
    const tl = tileOf(out, t);
    if (!tl) continue;
    if (
      (tl.state === 'anchored' || tl.state === 'unverified') &&
      tl.seq != null &&
      tl.seq > afterSeq
    ) {
      out = withTile(out, t, { ...tl, stale: true });
      stale.push(t);
    }
  }
  return { tiles: out, stale };
}

/** Put a single tile back into the map (immutable). Exposed for the store's orchestration. */
export function setTile(tiles: Tiles, t: number, next: Tile): Tiles {
  return withTile(tiles, t, next);
}

/** The world positions of a set of trials, as the match request wants them (`{ "12": [x, y] }`). Skips
 *  any trial without a position. */
export function positionsOf(tiles: Tiles, trials: number[]): Record<string, Position> {
  const out: Record<string, Position> = {};
  for (const t of trials) {
    const tl = tileOf(tiles, t);
    if (tl && tl.x != null && tl.y != null) out[K(t)] = [tl.x, tl.y];
  }
  return out;
}

/** The solver's position for a tile (`tile.machine`, already translated), or null. */
export function solverXY(tile: Tile | undefined): Position | null {
  const m = tile?.machine;
  if (Array.isArray(m) && m.length === 2 && Number.isFinite(m[0]) && Number.isFinite(m[1])) {
    return [m[0], m[1]];
  }
  return null;
}
