// ⭐⭐ THE MOSAIC SWEEP STORE — the shared spine the six step-UIs consume. It holds NO JSX. It ports the
// BEHAVIOUR of v1's sweep.js (archive/app-v1/frontend/sweep.js) into an idiomatic zustand store: the tile
// state machine, the cursor, the A/E/Space rhythm, the solver fallback, the prefetch, the evidence store,
// undo/redo, and the live banner.
//
// ⛔ NO DATASET KNOWLEDGE (HARD RULE 3). No trial numbers, ranges, counts or exclusion list live here. The
//    run's trial ORDER, the blank REFUSE list and the pass split all arrive via `hydrate` from the
//    human's document; the store names none of them.
//
// WHY ZUSTAND: the sweep is driven by a key handler and a prefetch that live partly OUTSIDE React (R21,
// R33). `useSweepStore.getState()` reaches the store with no Provider plumbing, and selector
// subscriptions keep a cursor tick from re-rendering the rails (the R20 frame budget).
//
// PERSISTENCE: the store owns the working document but not SAVING. The document store (src/store) owns
// Ctrl+S-from-any-screen, the debounced crash-net and the loud autosave-failure. The glue wires the two
// through `setHooks` — see types.ts `SweepHooks`. A judgement (A/E) autosaves UNCONDITIONALLY (R29).

import { create } from 'zustand';
import {
  matchAnchor,
  matchScore,
  computeGaps,
  type MosaicDocument,
  type MatchResult,
  type MatchAnchorRequest,
  type Candidate,
} from '../../../api';
import type {
  Tile,
  Tiles,
  TileState,
  Position,
  Evidence,
  Banner,
  UndoEntry,
  PlacementDecision,
  SweepHooks,
} from './types';
import {
  FLOAT_ALPHA,
  FLOAT_ALPHA_MIN,
  FLOAT_ALPHA_MAX,
  FLOAT_ALPHA_STEP,
  UNDO_DEPTH,
  FOLD_MS,
  CONFIDENT_DISAGREE_PX,
} from './constants';
import {
  tileOf,
  setTile,
  applyState,
  applyPos,
  markStaleAfter,
  anchoredTrials as computeAnchored,
  activeTrials as computeActive,
  anyPlaced,
  nextTrial,
  prevTrial,
  counts as computeCounts,
  solverXY,
  type Counts,
} from './machine';
import { classifyPlacement } from './placement';
import {
  buildMatchRequest,
  buildPrefetchRequest,
  buildScoreRequest,
  fieldSignature,
} from './field';

const iso = (): string => new Date().toISOString();
const K = (t: number): string => String(t);
const clone = <T>(v: T): T => structuredClone(v);
const fmtN = (n: number | null | undefined): string => (n == null ? '—' : n.toFixed(4));

// ── Module-scoped transients (v1's closure vars). NOT reactive, NOT snapshotted into undo. ─────────────
let matchSeqCounter = 0; // increments per foreground match; a superseded response is discarded (R33)
let fadeToken = 0; // bumped to (re)trigger the 1 s fade; `replay` bumps it (R)
let lastPrefetchKey: string | null = null; // a KEY, never a RESULT (R21 / §6.8)
let lastTag: string | null = null; // undo fold tag
let lastPushT = 0;
// The in-flight advance's promise. A DISPLAY action (V / 1–9) offered while a tile is still being placed
// waits for the placement to settle and then acts on the tile it lands on — it is NOT a judgement, so
// R33's "refuse mid-flight" (which guards A/E/S) does not apply; refusing it would just drop the keypress.
let inflightAdvance: Promise<void> | null = null;
async function settleAdvance(): Promise<void> {
  const p = inflightAdvance;
  if (p) await p;
}

// 🔴 IN-FLIGHT MATCH COALESCING (R21). The prefetch fires the SAME `match/anchor` POST the foreground
// call is about to fire (§6.8). Rather than let the two race the backend into computing the identical
// match twice (which, under load, pushes the foreground past its window), share ONE in-flight promise
// when the request bodies are byte-identical. The key is the FULL request body — which is exactly the
// server memo key — NEVER the trial number: a changed anchor field is a different key, so V/1–9 still
// re-fetch against the field they will act on (R22). Only IN-FLIGHT promises are shared; a settled one
// is dropped at once, so this is request de-duplication, not a result cache (`lastPrefetchKey` stays a
// KEY, never a RESULT). A superseded foreground response is still discarded by `matchSeqCounter`.
const inflightMatches = new Map<string, Promise<MatchResult>>();
function matchKey(req: MatchAnchorRequest): string {
  return JSON.stringify([
    req.session_id,
    req.target,
    req.anchors,
    req.positions,
    req.mode ?? null,
    req.near ?? null,
    req.radius ?? null,
    req.max_candidates ?? null,
    req.refuse ?? null,
  ]);
}
/** `matchAnchor`, but a byte-identical request already in flight is shared instead of re-fired. */
function coalescedMatch(req: MatchAnchorRequest): Promise<MatchResult> {
  const key = matchKey(req);
  const existing = inflightMatches.get(key);
  if (existing) return existing;
  const p = matchAnchor(req).finally(() => {
    if (inflightMatches.get(key) === p) inflightMatches.delete(key);
  });
  inflightMatches.set(key, p);
  return p;
}

function resetTransients(): void {
  matchSeqCounter = 0;
  fadeToken = 0;
  lastPrefetchKey = null;
  lastTag = null;
  lastPushT = 0;
  inflightAdvance = null;
  inflightMatches.clear();
}

/** A synthetic no-anchors refusal — a tile cannot match against an empty field (mirrors v1). */
function noAnchorsResult(target: number, mode: 'global' | 'local'): MatchResult {
  return {
    target,
    mode,
    n_anchors: 0,
    candidates: [],
    best: null,
    margin: null,
    margin_thin: false,
    refused: {
      reason: 'no_anchors',
      trials: [],
      message: 'No anchors yet. Press A on this tile to make it the origin.',
    },
    gpu: false,
    elapsed_ms: 0,
    cached: false,
    cache_key: '',
  };
}

export interface SweepState {
  // ── the working document (authoritative during the sweep) ──
  doc: MosaicDocument | null;
  sessionId: string | null;
  /** The run's trial ORDER (acquisition order). Arrives from the session; the store names no numbers. */
  order: number[];
  /** The blank REFUSE list the human left standing — part of every match's cache key (R16/R21). */
  refuse: number[];

  // ── sweep state ──
  /** The trial under judgement. `null` only before a sweep begins. (R14: never nulled by Esc.) */
  cursor: number | null;
  /** Judgement order — the stale cascade keys on `seq >`. Snapshotted into undo. */
  seq: number;
  /** Per-trial evidence, stamped with the field it was measured against (R22). */
  evidence: Record<string, Evidence>;

  // ── display prefs (SESSION only — never saved to the project file, R13.6) ──
  /** The floating tile's opacity, 0.15–1.00 (R13). */
  floatAlpha: number;
  /** Difference mode (R13.4 / §3.5) — a mirror of the viewer toggle. */
  diffMode: boolean;
  /** Alternatives rail/ghosts on. */
  altsOn: boolean;

  // ── live commentary + warnings ──
  banner: Banner | null;
  /** Live warnings the store owns. W10 (no anchors left) is set the moment the anchor set empties. */
  warnings: { noAnchors: boolean };
  /** The fade trigger the viewer subscribes to: `token` bumps to (re)run the 1 s fade. */
  fade: { trial: number; token: number } | null;

  // ── in-flight guard (R33) ──
  advancing: boolean;

  // ── undo/redo (R36) ──
  undoStack: UndoEntry[];
  redoStack: UndoEntry[];

  hooks: SweepHooks;

  // ── lifecycle ──
  setHooks: (hooks: SweepHooks) => void;
  hydrate: (
    doc: MosaicDocument,
    opts: { sessionId: string | null; order?: number[]; refuse?: number[] },
  ) => void;
  reset: () => void;

  // ── cursor ──
  /** ⭐ R14: IGNORES null. A viewer `Escape` reports `onSelect(null)`; nulling the cursor would freeze the
   *  sweep (advance/anchor/exclude all no-op on a null cursor). Esc DESELECTS — it does not abandon the
   *  tile you are judging. */
  setCursor: (trial: number | null) => void;
  /** If the cursor is null (fresh sweep), land it on the first non-excluded trial. */
  ensureCursor: () => void;

  // ── the A/E/Space rhythm ──
  anchor: () => Promise<void>;
  exclude: () => Promise<void>;
  advance: () => Promise<void>;
  replay: () => void;

  // ── hand moves / alternatives / snap / rescue ──
  snap: () => Promise<void>;
  showAlternatives: () => Promise<void>;
  jumpToRank: (rank: number) => Promise<void>;
  move: (trial: number, pos: Position) => void;
  pickAlternative: (trial: number, candidate: Candidate) => void;
  rescue: (trial: number) => Promise<void>;
  handPlace: (trial: number) => void;

  // ── Screen-step transitions (tile state is the store's, wherever it is written) ──
  excludeAt: (trial: number) => Promise<void>;
  unexclude: (trial: number) => void;

  // ── display prefs ──
  setFloatAlpha: (alpha: number) => void;
  setDiff: (on: boolean) => void;
  toggleDiff: () => void;

  // ── build integration ──
  activeTrials: () => number[];
  anchoredTrials: () => number[];
  counts: () => Counts;
  recomputeGaps: () => Promise<void>;

  /** W8/R25 — the stale re-check returns the trials it is allowed to clear (`RecheckResult.cleared`);
   *  unset `stale` on exactly those, so the panel and dashed chips clear. Disagreeing tiles STAY flagged. */
  clearStale: (trials: number[]) => void;

  // ── undo/redo ──
  undo: () => void;
  redo: () => void;

  // ── selectors ──
  currentEvidence: () => Evidence | undefined;
}

const HYDRATE_DEFAULTS = {
  cursor: null as number | null,
  seq: 0,
  evidence: {} as Record<string, Evidence>,
  floatAlpha: FLOAT_ALPHA,
  diffMode: false,
  altsOn: false,
  banner: null as Banner | null,
  warnings: { noAnchors: false },
  fade: null as { trial: number; token: number } | null,
  advancing: false,
  undoStack: [] as UndoEntry[],
  redoStack: [] as UndoEntry[],
};

/** The next seq counter value: greater than every seq already on a tile. */
function seqFloor(tiles: Tiles): number {
  let max = 0;
  for (const k of Object.keys(tiles)) {
    const s = tiles[k].seq;
    if (s != null && s > max) max = s;
  }
  return max;
}

export const useSweepStore = create<SweepState>((set, get) => {
  // ── private helpers (close over set/get) ──────────────────────────────────────────────────────────

  /** Fire the persistence hook with the current doc. `judgement` = an A/E that must autosave now (R29). */
  function notify(judgement: boolean): void {
    const { hooks, doc } = get();
    if (doc) hooks.onChange?.(doc, { judgement });
  }

  /** Patch the document's tiles immutably and stamp `modified`. */
  function writeDoc(patch: Partial<MosaicDocument>): void {
    const doc = get().doc;
    if (!doc) return;
    set({ doc: { ...doc, ...patch, modified: iso() } });
  }

  /** (Re)trigger the 1 s fade for a tile — the viewer subscribes to `fade`. */
  function fadeIn(trial: number): void {
    fadeToken += 1;
    set({ fade: { trial, token: fadeToken } });
  }

  /** Commit the cursor at the point of DISPLAY (R33). Clears the alternatives overlay. */
  function commitCursor(next: number): void {
    const doc = get().doc;
    set({ cursor: next, altsOn: false, doc: doc ? { ...doc, cursor: next } : doc });
    notify(false);
  }

  /** The judgement tail shared by A and E: autosave NOW, warm the next tile assuming `A` (R21). */
  function afterJudge(t: number): void {
    notify(true);
    prefetchNext(t);
  }

  // R33's protection: a judgement must NEVER be applied to a tile still being placed, nor overwritten by
  // a late match response. We honour that by having every judgement/move key AWAIT the in-flight
  // placement (`settleAdvance`) and then read a fresh cursor — so it acts on the tile that actually
  // landed, is never lost, and never races the response. (Space itself still self-drops a second advance
  // via the `advancing` flag — the one-flag rule.)

  function pushUndo(tag: string): void {
    const now = typeof performance !== 'undefined' ? performance.now() : Date.now();
    if (tag === lastTag && now - lastPushT < FOLD_MS) {
      lastPushT = now;
      return;
    }
    const s = get();
    if (!s.doc) return;
    const entry: UndoEntry = {
      doc: clone(s.doc),
      cursor: s.cursor,
      seq: s.seq,
      evidence: clone(s.evidence),
    };
    const undoStack = s.undoStack.concat([entry]);
    if (undoStack.length > UNDO_DEPTH) undoStack.shift();
    set({ undoStack, redoStack: [] });
    lastTag = tag;
    lastPushT = now;
  }

  function restore(entry: UndoEntry): void {
    // 🔴 The evidence store is part of the snapshot (R36) — restore it WITH the document, or the rail and
    // `V`'s list describe a field the document no longer has.
    set({ doc: entry.doc, cursor: entry.cursor, seq: entry.seq, evidence: entry.evidence });
    notify(false);
  }

  /** The solver-fallback decision for a tile, given a match result. */
  function decide(tiles: Tiles, target: number, res: MatchResult | null): PlacementDecision {
    return classifyPlacement(res, solverXY(tileOf(tiles, target)));
  }

  /** A foreground match: guards a stale response (R33). Returns a synthetic no-anchors refusal when there
   *  is no field to match against. */
  async function foregroundMatch(
    target: number,
    mode: 'global' | 'local',
    near: Position | null,
  ): Promise<MatchResult | null> {
    const s = get();
    if (!s.sessionId || !s.doc) return null;
    const req = buildMatchRequest(
      { sessionId: s.sessionId, target, tiles: s.doc.tiles, order: s.order, refuse: s.refuse },
      { mode, near },
    );
    if (!req) return noAnchorsResult(target, mode);
    const my = ++matchSeqCounter;
    try {
      // Reuse an in-flight identical request (the prefetch is the same POST — R21), so a slow backend
      // is hit once, not twice. The superseded-response guard below is unchanged.
      const res = await coalescedMatch(req);
      if (my !== matchSeqCounter) return null; // a newer request overtook this one
      return res;
    } catch {
      set({ banner: { kind: 'bad', message: `Match failed for trial ${target}.` } });
      return null;
    }
  }

  /** 🔴 THE PREFETCH (R21). The SAME POST fired early, with `judged` added to the anchor set (assume `A`),
   *  and the answer DISCARDED — the server memo makes the foreground call a ~1 ms hit iff the anchor set
   *  matches. `lastPrefetchKey` holds a KEY, never a RESULT: it only stops us firing the byte-identical
   *  POST twice. ⛔ Never a client-side cache keyed on the trial number (§6.8). */
  function prefetchNext(judged: number): void {
    const s = get();
    if (!s.sessionId || !s.doc) return;
    const nxt = nextTrial(s.order, s.doc.tiles, judged);
    if (nxt === null) return;
    if (tileOf(s.doc.tiles, nxt)?.state === 'anchored') return;
    const req = buildPrefetchRequest(
      { sessionId: s.sessionId, tiles: s.doc.tiles, order: s.order, refuse: s.refuse },
      judged,
      nxt,
    );
    if (!req) return;
    const key = `${req.target}|${req.anchors.map((t) => `${t}:${req.positions[K(t)]?.join(',')}`).join('|')}`;
    if (key === lastPrefetchKey) return;
    lastPrefetchKey = key;
    // FIRE AND FORGET — the answer is discarded on purpose (see the header). Routed through the coalescer
    // so the foreground call for the same tile shares this exact in-flight POST (R21) instead of racing
    // the backend into computing it a second time.
    coalescedMatch(req).then(
      () => {},
      () => {},
    );
  }

  /** Stash a response for the rail and for `V`/`1`–`9`, STAMPED with the field it was measured against. */
  function stashEvidence(t: number, res: MatchResult): void {
    const s = get();
    if (!s.doc) return;
    const field = fieldSignature(s.doc.tiles, s.order, t);
    const ev: Evidence = { result: res, field, candidates: res.candidates ?? [] };
    set({ evidence: { ...s.evidence, [K(t)]: ev } });
  }

  function evidenceIsCurrent(t: number): boolean {
    const s = get();
    const ev = s.evidence[K(t)];
    return !!ev && !!s.doc && ev.field === fieldSignature(s.doc.tiles, s.order, t);
  }

  /** The `source` provenance string for a placement. */
  function sourceFor(
    dec: PlacementDecision,
    kind: 'space' | 'anchor' | 'rescue',
    tile: Tile,
  ): string {
    if (kind === 'anchor') {
      return dec.diverted
        ? "anchored at the SOLVER's position (the anchor-composite match was not confident) — A"
        : 'placed against the anchor composite (A)';
    }
    if (kind === 'rescue') {
      return dec.diverted
        ? "rescued to the SOLVER's position (the anchor-composite match was not confident)"
        : 'rescued against the anchor composite';
    }
    // space
    if (dec.diverted)
      return "the SOLVER's position (the anchor-composite match was not confident) — Space";
    return tile.machine
      ? 't33 build, re-placed against the anchor composite (Space)'
      : 'placed against the anchor composite (Space)';
  }

  /** The loud placement notice (divert / no-solver). Confident placements banner nothing here. */
  function placementBanner(t: number, dec: PlacementDecision): Banner | null {
    if (dec.noSolver && !dec.confident) {
      return {
        kind: 'warn',
        message: `Trial ${t}: match not confident (${dec.why.join(', ')}) and there is no solver position to fall back on. Check it (D) before A.`,
      };
    }
    if (!dec.diverted) return null;
    const detail = dec.none
      ? `The matcher gave nothing (${dec.why.join(', ')}).`
      : `Match not confident (${dec.why.join(', ')}), ${dec.disagreePx == null ? '?' : Math.round(dec.disagreePx)} px from the solver.`;
    return {
      kind: 'warn',
      message: `Trial ${t} — diverted to the solver. ${detail} Unverified. D to check, A to accept, V for the matcher's answer, or drag it.`,
    };
  }

  /** Record the evidence for a placement that may have been DIVERTED (R15c). On a divert, the tile is NOT
   *  at `res.best`, so `best.ncc` is thrown away and the honest NCC is re-measured where the tile actually
   *  sits (~31 ms). The rejected match is kept in full. */
  async function recordPlacement(
    t: number,
    res: MatchResult | null,
    dec: PlacementDecision,
  ): Promise<void> {
    if (res) stashEvidence(t, res);
    const before = get().doc;
    if (!before) return;
    const tl = tileOf(before.tiles, t);
    if (!tl) return;
    const nAnchors = res?.n_anchors ?? computeAnchored(before.tiles, get().order).length;
    const nt: Tile = {
      ...tl,
      n_anchors: nAnchors,
      margin: res?.margin ?? null,
      alt_rank: undefined,
    };
    if (!dec.diverted) {
      nt.ncc = res?.best ? res.best.ncc : null;
      nt.npix = res?.best ? res.best.npix : null;
      nt.diverted = false;
      nt.divert_reason = undefined;
      nt.rejected_match = undefined;
    } else {
      nt.diverted = true;
      nt.divert_reason = dec.why.join('; ');
      nt.rejected_match = dec.rejected;
      nt.ncc = null;
      nt.npix = null;
    }
    writeDoc({ tiles: setTile(before.tiles, t, nt) });

    if (dec.diverted && dec.position && res) {
      const s = get();
      if (!s.sessionId || !s.doc) return;
      const req = buildScoreRequest(
        { sessionId: s.sessionId, target: t, tiles: s.doc.tiles, order: s.order, refuse: s.refuse },
        dec.position,
      );
      if (!req) return;
      try {
        const score = await matchScore(req);
        // ⚠️ `ncc: null` means NOT MEASURABLE — keep it null, never 0.0.
        if (score.ncc != null && Number.isFinite(score.ncc)) {
          // Re-entrancy guard: only write if the evidence entry is still the one we stashed.
          const ev = get().evidence[K(t)];
          const now = get().doc;
          const cur = now ? tileOf(now.tiles, t) : undefined;
          if (ev && ev.result === res && cur) {
            writeDoc({
              tiles: setTile(now!.tiles, t, { ...cur, ncc: score.ncc, npix: score.npix }),
            });
          }
        }
      } catch {
        /* leave ncc null — the honest answer */
      }
    }
  }

  /** Write a tile's numbers when the tile IS being moved to `res.best` (snap / rescue-place). */
  function recordEvidence(t: number, res: MatchResult): void {
    stashEvidence(t, res);
    const doc = get().doc;
    if (!doc) return;
    const tl = tileOf(doc.tiles, t);
    if (!tl) return;
    writeDoc({
      tiles: setTile(doc.tiles, t, {
        ...tl,
        ncc: res.best ? res.best.ncc : null,
        npix: res.best ? res.best.npix : null,
        margin: res.margin ?? null,
        n_anchors: res.n_anchors ?? computeAnchored(doc.tiles, get().order).length,
        alt_rank: undefined,
      }),
    });
  }

  /** ⭐⭐ `A` ON AN ANCHORED TILE UN-ANCHORS IT (R11). Toggles CERTIFICATION, not position. */
  function unanchor(t: number): void {
    const s = get();
    if (!s.doc) return;
    const tile = tileOf(s.doc.tiles, t);
    if (!tile) return;
    pushUndo(`unanchor:${t}`);
    const oldSeq = tile.seq; // BEFORE the write — it bumps seq
    const seq = s.seq + 1;
    let nt = applyState(tile, 'unverified', [tile.x!, tile.y!], seq);
    nt = {
      ...nt,
      source: `${tile.source ? `${tile.source}, ` : ''}un-anchored by the user`,
      judged_at: iso(),
    };
    let tiles = setTile(s.doc.tiles, t, nt);
    const staled = markStaleAfter(tiles, s.order, oldSeq ?? undefined, t);
    tiles = staled.tiles;
    const evidence = { ...s.evidence };
    for (const st of staled.stale) delete evidence[K(st)];
    const left = computeAnchored(tiles, s.order).length;
    set({
      doc: { ...s.doc, tiles, modified: iso() },
      seq,
      evidence,
      warnings: { ...s.warnings, noAnchors: left === 0 },
      banner: {
        kind: staled.stale.length || !left ? 'warn' : 'ok',
        message:
          `Un-anchored ${t}. It keeps its position.` +
          (staled.stale.length
            ? ` ${staled.stale.length} tile${staled.stale.length === 1 ? '' : 's'} flagged stale — they were matched against a field that contained it.`
            : '') +
          (left ? '' : ' No anchors left — press A on a placed tile to certify one.'),
      },
    });
    afterJudge(t);
  }

  // ── the public store ──────────────────────────────────────────────────────────────────────────────
  return {
    doc: null,
    sessionId: null,
    order: [],
    refuse: [],
    ...HYDRATE_DEFAULTS,
    hooks: {},

    setHooks: (hooks) => set({ hooks }),

    hydrate: (doc, opts) => {
      resetTransients();
      const order =
        opts.order ??
        Object.keys(doc.tiles)
          .map(Number)
          .sort((a, b) => a - b);
      const refuse = opts.refuse ?? doc.blank_scan?.blank ?? [];
      set({
        doc,
        sessionId: opts.sessionId,
        order,
        refuse,
        ...HYDRATE_DEFAULTS,
        cursor: doc.cursor ?? null,
        seq: seqFloor(doc.tiles),
        warnings: { noAnchors: computeAnchored(doc.tiles, order).length === 0 },
      });
    },

    reset: () => {
      resetTransients();
      set({
        doc: null,
        sessionId: null,
        order: [],
        refuse: [],
        ...HYDRATE_DEFAULTS,
      });
    },

    setCursor: (trial) => {
      if (trial === null) return; // ⭐ R14 — Esc's onSelect(null) must NOT null the cursor
      const doc = get().doc;
      set({ cursor: trial, altsOn: false, doc: doc ? { ...doc, cursor: trial } : doc });
      notify(false);
    },

    ensureCursor: () => {
      const s = get();
      if (s.cursor !== null || !s.doc) return;
      const first = s.order.find((t) => tileOf(s.doc!.tiles, t)?.state !== 'excluded') ?? null;
      if (first !== null) get().setCursor(first);
    },

    anchor: async () => {
      await settleAdvance(); // act on the tile that actually landed, never one in flight (R33)
      const s = get();
      const t = s.cursor;
      if (t === null || !s.doc) return; // ⭐ no-op when cursor is null
      const tile = tileOf(s.doc.tiles, t);
      if (!tile) return;

      // THE TOGGLE — anchored already? `A` takes it back.
      if (tile.state === 'anchored') {
        unanchor(t);
        return;
      }

      if (tile.x == null) {
        // No position yet.
        if (!anyPlaced(s.doc.tiles, s.order)) {
          // ORIGIN — this tile is (0, 0).
          pushUndo(`anchor:${t}`);
          const seq = s.seq + 1;
          let nt = applyState(tile, 'anchored', [0, 0], seq);
          nt = { ...nt, source: 'origin tile', judged_at: iso(), stale: false };
          set({
            doc: {
              ...s.doc,
              tiles: setTile(s.doc.tiles, t, nt),
              origin_trial: t,
              cursor: t,
              modified: iso(),
            },
            seq,
            warnings: { ...s.warnings, noAnchors: false },
            banner: { kind: 'ok', message: `Origin — trial ${t} is (0, 0).` },
          });
          fadeIn(t);
          afterJudge(t);
          return;
        }
        if (computeAnchored(s.doc.tiles, s.order).length === 0) {
          // 🔴 THE ORIGIN TRAP (R11.4): un-anchored down to zero anchors. Those tiles hold positions, so
          // `anyPlaced()` is true, but there is nothing to match against. Do NOT match — name both exits.
          set({
            banner: {
              kind: 'bad',
              message: `Trial ${t}: nothing to match against — no anchors yet. Press A on a tile that already has a position to certify it, or drag this one into place, then A.`,
            },
          });
          return;
        }
        // Match first, then certify where it lands (or the solver's position — never an alias).
        const res = await foregroundMatch(t, 'global', null);
        const dec = decide(get().doc!.tiles, t, res);
        if (!dec.position) {
          set({
            banner: {
              kind: 'bad',
              message: `Trial ${t}: nothing to match against. Press A on a tile that already has a position, or drag this one into place, then A.`,
            },
          });
          return;
        }
        pushUndo(`anchor:${t}`);
        const seq = get().seq + 1;
        const cur = tileOf(get().doc!.tiles, t)!;
        let nt = applyState(cur, 'anchored', dec.position, seq);
        nt = { ...nt, source: sourceFor(dec, 'anchor', cur), judged_at: iso(), stale: false };
        set((st) => ({
          seq,
          doc: { ...st.doc!, tiles: setTile(st.doc!.tiles, t, nt), modified: iso() },
        }));
        await recordPlacement(t, res, dec);
        const b = placementBanner(t, dec);
        if (b) set({ banner: b });
        fadeIn(t);
        afterJudge(t);
        return;
      }

      // Has a position, not anchored → certify in place.
      pushUndo(`anchor:${t}`);
      const seq = s.seq + 1;
      let nt = applyState(tile, 'anchored', [tile.x, tile.y!], seq);
      nt = { ...nt, judged_at: iso(), stale: false };
      if (!nt.source) nt.source = 'accepted at its current position (A)';
      const originPatch = s.doc.origin_trial == null ? { origin_trial: t } : {};
      set({
        doc: { ...s.doc, ...originPatch, tiles: setTile(s.doc.tiles, t, nt), modified: iso() },
        seq,
        warnings: { ...s.warnings, noAnchors: false },
        banner: null,
      });
      afterJudge(t);
    },

    exclude: async () => {
      await settleAdvance(); // act on the tile that actually landed, never one in flight (R33)
      const t = get().cursor;
      if (t === null) return; // ⭐ no-op when cursor is null
      await get().excludeAt(t);
    },

    excludeAt: async (t) => {
      const s = get();
      if (!s.doc) return;
      const tile = tileOf(s.doc.tiles, t);
      if (!tile) return;
      pushUndo(`exclude:${t}`);
      const wasAnchored = tile.state === 'anchored';
      const oldSeq = tile.seq;
      const lastXy: Position | null = tile.x != null && tile.y != null ? [tile.x, tile.y] : null;
      let excludedTile = applyState(tile, 'excluded', null, undefined);
      excludedTile = {
        ...excludedTile,
        last_xy: lastXy,
        unusable_reason: tile.blank ? 'blank' : 'other',
        excluded_reason: tile.blank
          ? 'measured blank (band-passed std below threshold) — and the user excluded it'
          : "the user's eye",
        judged_at: iso(),
      };
      let tiles = setTile(s.doc.tiles, t, excludedTile);
      let staleList: number[] = [];
      if (wasAnchored) {
        const r = markStaleAfter(tiles, s.order, oldSeq ?? undefined, t);
        tiles = r.tiles;
        staleList = r.stale;
      }
      const evidence = { ...s.evidence };
      for (const st of staleList) delete evidence[K(st)];
      const unusable = s.order.filter((x) => tileOf(tiles, x)?.state === 'excluded');
      const noAnchors = computeAnchored(tiles, s.order).length === 0;
      set({
        doc: { ...s.doc, tiles, unusable_tiles: unusable, modified: iso() },
        evidence,
        warnings: { ...s.warnings, noAnchors },
      });
      // 🔴 Propagate + autosave the EXCLUSION now, before the async gaps fetch. A judgement must reach
      // the document store immediately (R29) — otherwise a Ctrl+S fired during the gaps round-trip would
      // persist a document that still shows the tile placed (measured: a resume brought it back
      // `unverified`). The gaps are a refinement written a beat later, below.
      notify(true);
      // ⚠️ Gaps go through the route (R2.5) and are recomputed BEFORE any rebuild. The app never
      // reimplements the exclusion module's gap logic locally.
      let gaps: [number, number][] = s.doc.gaps ?? [];
      try {
        gaps = (await computeGaps(computeActive(tiles, s.order))).gaps;
      } catch {
        /* keep the previous gaps; a failed fetch must not wedge the sweep */
      }
      const cur = get().doc;
      if (cur) set({ doc: { ...cur, gaps } });
      set({
        banner: {
          kind: staleList.length ? 'warn' : 'ok',
          message:
            `Excluded ${t}. ` +
            (gaps.length
              ? `${gaps.length} gap${gaps.length === 1 ? '' : 's'}: ${gaps.map((p) => `${p[0]}→${p[1]}`).join(', ')}.`
              : 'No gaps.') +
            (staleList.length
              ? ` ${t} was an anchor — ${staleList.length} tile${staleList.length === 1 ? '' : 's'} flagged stale.`
              : ''),
        },
      });
      afterJudge(t);
    },

    unexclude: (t) => {
      const s = get();
      if (!s.doc) return;
      const tile = tileOf(s.doc.tiles, t);
      if (!tile) return;
      const lastXy = tile.last_xy ?? null; // ⚠️ read BEFORE applyState clears it
      pushUndo(`unexclude:${t}`);
      const restoreState: TileState = lastXy ? 'unverified' : 'unplaced';
      const seq = restoreState === 'unverified' ? s.seq + 1 : s.seq;
      const nt = applyState(
        tile,
        restoreState,
        lastXy,
        restoreState === 'unverified' ? seq : undefined,
      );
      const tiles = setTile(s.doc.tiles, t, nt);
      set({
        doc: {
          ...s.doc,
          tiles,
          unusable_tiles: s.order.filter((x) => tileOf(tiles, x)?.state === 'excluded'),
          modified: iso(),
        },
        seq,
      });
      void get().recomputeGaps();
      notify(false);
    },

    advance: async () => {
      const s = get();
      if (!s.sessionId || s.cursor === null) return; // ⭐ no-op when cursor is null
      if (s.advancing) return; // 🔴 R33 — a second Space must not start a second advance
      set({ advancing: true });
      const run = (async () => {
        try {
          await runAdvance();
        } finally {
          set({ advancing: false });
          inflightAdvance = null;
        }
      })();
      inflightAdvance = run;
      await run;

      async function runAdvance(): Promise<void> {
        const cur = get().cursor!;
        const order = get().order;

        // 1. The CURRENT tile: place it if it has nowhere to be (Space ALWAYS places — R15/R9b).
        const curTile = tileOf(get().doc!.tiles, cur)!;
        if (curTile.state === 'unplaced' && computeAnchored(get().doc!.tiles, order).length) {
          const res = await foregroundMatch(cur, 'global', null);
          const dec = decide(get().doc!.tiles, cur, res);
          if (dec.position) {
            pushUndo(`place:${cur}`);
            const seq = get().seq + 1;
            const tl = tileOf(get().doc!.tiles, cur)!;
            const placed = {
              ...applyState(tl, 'unverified', dec.position, seq),
              source: sourceFor(dec, 'space', tl),
            };
            set((st) => ({
              seq,
              doc: { ...st.doc!, tiles: setTile(st.doc!.tiles, cur, placed), modified: iso() },
            }));
            await recordPlacement(cur, res, dec);
            const b = placementBanner(cur, dec);
            if (b) set({ banner: b });
          }
        }

        // 2. The NEXT tile.
        const nxt = nextTrial(order, get().doc!.tiles, cur);
        if (nxt === null) {
          set({
            banner: {
              kind: 'ok',
              message: `End of the run. ${computeCounts(get().doc!.tiles, order).unverified} still unverified.`,
            },
          });
          return;
        }
        const nextTile = tileOf(get().doc!.tiles, nxt)!;
        if (nextTile.state === 'anchored') {
          // Already certified — nothing to place. (Falls through to commit/fade.)
        } else if (nextTile.human && nextTile.x != null) {
          // 🔴 A hand-moved tile is NEVER re-matched over (R24b).
          set({
            banner: {
              kind: 'ok',
              message: `Trial ${nxt} is where you put it — not re-matched. S to snap, V for alternatives, A to certify.`,
            },
          });
        } else if (computeAnchored(get().doc!.tiles, order).length === 0) {
          commitCursor(nxt);
          set({
            banner: {
              kind: 'warn',
              message: `No anchors — A makes trial ${nxt} the origin (0, 0).`,
            },
          });
          return;
        } else {
          const res = await foregroundMatch(nxt, 'global', null);
          const dec = decide(get().doc!.tiles, nxt, res);
          if (dec.position) {
            pushUndo(`place:${nxt}`);
            const seq = get().seq + 1;
            const tl = tileOf(get().doc!.tiles, nxt)!;
            const placed = {
              ...applyState(tl, 'unverified', dec.position, seq),
              source: sourceFor(dec, 'space', tl),
            };
            set((st) => ({
              seq,
              doc: { ...st.doc!, tiles: setTile(st.doc!.tiles, nxt, placed), modified: iso() },
            }));
            await recordPlacement(nxt, res, dec);
            const b = placementBanner(nxt, dec);
            if (b) set({ banner: b });
            // W11 — a CONFIDENT match that disagrees with the solver by > 20 px: the field wins, say so.
            const t2 = tileOf(get().doc!.tiles, nxt)!;
            if (!dec.diverted && t2.machine && (t2.moved_px ?? 0) > CONFIDENT_DISAGREE_PX) {
              set({
                banner: {
                  kind: 'warn',
                  message: `Trial ${nxt}: the anchor field disagrees with the solver by ${Math.round(t2.moved_px!)} px, but the match is confident (NCC ${fmtN(t2.ncc)}, margin ${fmtN(t2.margin)}) — so the field wins. Check it (D) before you anchor.`,
                },
              });
            }
          } else if (tileOf(get().doc!.tiles, nxt)!.x == null) {
            // No match, no solver position, nowhere to be: stays unplaced; the cursor still advances.
            commitCursor(nxt);
            return;
          }
          // else: refused (blank) but had a position — keep it. (Falls through to commit/fade.)
        }

        // 3. Commit the cursor at the point of DISPLAY (R33), fade it in, warm the next (R21).
        commitCursor(nxt);
        fadeIn(nxt);
        prefetchNext(nxt);
      }
    },

    replay: () => {
      const t = get().cursor;
      if (t === null) return;
      fadeIn(t);
    },

    snap: async () => {
      await settleAdvance(); // act on the tile that actually landed, never one in flight (R33)
      const t = get().cursor;
      if (t === null || !get().doc) return;
      const tile = tileOf(get().doc!.tiles, t);
      if (!tile) return;
      if (tile.x == null) {
        set({ banner: { kind: 'bad', message: `Trial ${t} has no position to snap.` } });
        return;
      }
      const before: Position = [tile.x, tile.y!];
      const res = await foregroundMatch(t, 'local', before);
      if (!res || res.refused || !res.best) return;
      pushUndo(`snap:${t}`);
      const cur = tileOf(get().doc!.tiles, t)!;
      let nt = applyPos(cur, [res.best.x, res.best.y]);
      nt = { ...nt, human: true };
      if (!/snapped/.test(nt.source ?? '')) {
        nt.source = nt.machine
          ? 't33 build, corrected by hand + snapped against the anchor composite'
          : 'hand-dragged + snapped against the anchor composite';
      }
      set((st) => ({ doc: { ...st.doc!, tiles: setTile(st.doc!.tiles, t, nt), modified: iso() } }));
      recordEvidence(t, res);
      const d = Math.hypot(res.best.x - before[0], res.best.y - before[1]);
      set({
        banner: {
          kind: res.margin_thin ? 'warn' : 'ok',
          message: `Snapped ${d.toFixed(2)} px. NCC ${fmtN(res.best.ncc)}${res.margin != null ? `, margin ${res.margin.toFixed(3)}` : ''}.`,
        },
      });
      fadeIn(t);
      notify(false);
    },

    showAlternatives: async () => {
      // V is a DISPLAY toggle, not a judgement: if a placement is in flight, wait for it to settle and
      // show the alternatives for the tile it lands on (rather than dropping the keypress — R33 guards
      // A/E/S, not this).
      await settleAdvance();
      const s = get();
      const t = s.cursor;
      if (t === null || !s.doc) return;
      if (s.altsOn) {
        set({ altsOn: false });
        return;
      }
      let res: MatchResult | null = evidenceIsCurrent(t)
        ? (s.evidence[K(t)]?.result ?? null)
        : null;
      if (!res || !res.candidates) res = await foregroundMatch(t, 'global', null);
      if (!res || res.refused) {
        set({ altsOn: false });
        return;
      }
      stashEvidence(t, res);
      const doc = get().doc!;
      const tl = tileOf(doc.tiles, t)!;
      set({ altsOn: true, doc: { ...doc, tiles: setTile(doc.tiles, t, { ...tl, stale: false }) } });
    },

    jumpToRank: async (rank) => {
      // A digit jump acts on the settled tile — wait out any in-flight placement first (as V does).
      await settleAdvance();
      const s = get();
      const t = s.cursor;
      if (t === null || !s.doc) return;
      let cands: Candidate[] | null = evidenceIsCurrent(t)
        ? (s.evidence[K(t)]?.candidates ?? null)
        : null;
      if (!cands || !cands.length) {
        const res = await foregroundMatch(t, 'global', null);
        if (!res || !res.candidates || !res.candidates.length) {
          set({
            banner: { kind: 'bad', message: `Trial ${t}: no candidate positions to jump to.` },
          });
          return;
        }
        stashEvidence(t, res);
        const doc = get().doc!;
        const tl = tileOf(doc.tiles, t)!;
        set({ doc: { ...doc, tiles: setTile(doc.tiles, t, { ...tl, stale: false }) } });
        cands = res.candidates;
      }
      const c = cands.find((x) => x.rank === rank);
      if (!c) {
        set({
          banner: {
            kind: 'bad',
            message: `Trial ${t}: only ${cands.length} candidate${cands.length === 1 ? '' : 's'}. Press 1–${cands.length}.`,
          },
        });
        return;
      }
      get().pickAlternative(t, c);
    },

    move: (t, pos) => {
      const s = get();
      if (!s.doc) return;
      const tile = tileOf(s.doc.tiles, t);
      if (!tile || tile.state === 'excluded') return;
      const wasAnchored = tile.state === 'anchored';
      const oldSeq = tile.seq;
      pushUndo(`move:${t}`);
      const wasUnplaced = tile.state === 'unplaced';
      const seq = wasUnplaced ? s.seq + 1 : s.seq;
      let nt = wasUnplaced ? applyState(tile, 'unverified', pos, seq) : applyPos(tile, pos);
      nt = { ...nt, human: true };
      if (!/corrected|hand/.test(nt.source ?? '')) {
        nt.source = nt.machine
          ? 't33 build, corrected by hand'
          : nt.source
            ? `${nt.source}, corrected by hand`
            : 'hand-dragged';
      }
      let tiles = setTile(s.doc.tiles, t, nt);
      let staleList: number[] = [];
      if (wasAnchored) {
        const r = markStaleAfter(tiles, s.order, oldSeq ?? undefined, t);
        tiles = r.tiles;
        staleList = r.stale;
      }
      const evidence = { ...s.evidence };
      for (const st of staleList) delete evidence[K(st)];
      set({
        doc: { ...s.doc, tiles, modified: iso() },
        seq,
        evidence,
        banner: staleList.length
          ? {
              kind: 'warn',
              message: `Anchor moved — ${staleList.length} tile${staleList.length === 1 ? '' : 's'} may be stale.`,
            }
          : s.banner,
      });
      notify(false);
    },

    pickAlternative: (t, c) => {
      const s = get();
      if (!s.doc || !c) return;
      if (!tileOf(s.doc.tiles, t)) return;
      // 🔴 ONE helper, both routes (rail list AND canvas ghost, §3.6). `move()` pushes undo, flags human,
      // kills the divert claim. Then the peak's numbers follow the tile to its new position.
      get().move(t, [c.x, c.y]);
      set((st) => {
        const doc = st.doc!;
        const tl = tileOf(doc.tiles, t)!;
        const nt: Tile = { ...tl, ncc: c.ncc ?? null, npix: c.npix, alt_rank: c.rank };
        if (c.rank !== 0) {
          // ⚠️ Write BOTH conventions — display is +1 (the key he pressed), storage is 0-indexed (R12.4).
          nt.source = `${tl.machine ? 't33 build, ' : ''}moved by hand to alternative ${c.rank + 1} of the anchor-composite search (rank ${c.rank}; rank 0 was a thin-margin alias)`;
        }
        const evidence = { ...st.evidence };
        const ev = evidence[K(t)];
        if (ev) evidence[K(t)] = { ...ev, result: { ...ev.result, best: c }, pickedRank: c.rank };
        return { doc: { ...doc, tiles: setTile(doc.tiles, t, nt) }, evidence };
      });
      set({
        banner: {
          kind: 'ok',
          message: `Moved to alternative ${c.rank + 1} (NCC ${fmtN(c.ncc)}). S to snap.`,
        },
      });
      fadeIn(t);
      notify(false);
    },

    rescue: async (t) => {
      get().setCursor(t);
      const res = await foregroundMatch(t, 'global', null);
      const dec = decide(get().doc!.tiles, t, res);
      if (!dec.position) return;
      pushUndo(`rescue:${t}`);
      const seq = get().seq + 1;
      const tile = tileOf(get().doc!.tiles, t)!;
      const nt = {
        ...applyState(tile, 'unverified', dec.position, seq),
        source: sourceFor(dec, 'rescue', tile),
      };
      set((st) => ({
        seq,
        doc: { ...st.doc!, tiles: setTile(st.doc!.tiles, t, nt), modified: iso() },
      }));
      await recordPlacement(t, res, dec);
      const b = placementBanner(t, dec);
      if (b) set({ banner: b });
      fadeIn(t);
      notify(false);
    },

    handPlace: (t) => {
      const s = get();
      if (!s.doc) return;
      const p = prevTrial(s.order, s.doc.tiles, t);
      const src = p !== null ? tileOf(s.doc.tiles, p) : undefined;
      if (!src || src.x == null || src.y == null) {
        set({ banner: { kind: 'bad', message: 'Nothing placed nearby to drop it beside.' } });
        return;
      }
      const tile = tileOf(s.doc.tiles, t);
      if (!tile) return;
      pushUndo(`handplace:${t}`);
      const seq = s.seq + 1;
      let nt = applyState(tile, 'unverified', [src.x, src.y], seq);
      nt = {
        ...nt,
        source: 'hand-dragged (no snap — blank tile, matcher refused)',
        ncc: null,
        margin: null,
        human: true,
        diverted: false,
        divert_reason: undefined,
        rejected_match: undefined,
      };
      set({
        doc: { ...s.doc, tiles: setTile(s.doc.tiles, t, nt), modified: iso() },
        seq,
        banner: {
          kind: 'warn',
          message: `Trial ${t} dropped by hand. It will not snap — blank frames are refused. Drag it.`,
        },
      });
      fadeIn(t);
      notify(false);
    },

    setFloatAlpha: (alpha) => {
      const clamped = Math.min(
        FLOAT_ALPHA_MAX,
        Math.max(FLOAT_ALPHA_MIN, Math.round(alpha / FLOAT_ALPHA_STEP) * FLOAT_ALPHA_STEP),
      );
      set({ floatAlpha: clamped });
    },
    setDiff: (on) => set({ diffMode: on }),
    toggleDiff: () => set((st) => ({ diffMode: !st.diffMode })),

    activeTrials: () => {
      const s = get();
      return s.doc ? computeActive(s.doc.tiles, s.order) : [];
    },
    anchoredTrials: () => {
      const s = get();
      return s.doc ? computeAnchored(s.doc.tiles, s.order) : [];
    },
    counts: () => {
      const s = get();
      return s.doc
        ? computeCounts(s.doc.tiles, s.order)
        : { anchored: 0, unverified: 0, unplaced: 0, excluded: 0, diverted: 0 };
    },

    recomputeGaps: async () => {
      const s = get();
      if (!s.doc) return;
      try {
        const gaps = (await computeGaps(computeActive(s.doc.tiles, s.order))).gaps;
        const cur = get().doc;
        if (!cur) return;
        set({
          doc: {
            ...cur,
            gaps,
            unusable_tiles: s.order.filter((x) => tileOf(cur.tiles, x)?.state === 'excluded'),
          },
        });
        notify(false);
      } catch {
        /* leave the gaps; a failed fetch must not wedge the sweep */
      }
    },

    clearStale: (trials) => {
      const s = get();
      if (!s.doc || trials.length === 0) return;
      let tiles = s.doc.tiles;
      let changed = false;
      for (const t of trials) {
        const tl = tileOf(tiles, t);
        if (tl?.stale) {
          tiles = setTile(tiles, t, { ...tl, stale: false });
          changed = true;
        }
      }
      if (!changed) return;
      // The old candidate list is NOT resurrected — a cleared flag means the field agrees where the tile
      // SITS now, not that evidence measured against the earlier field is valid again (R22).
      writeDoc({ tiles });
      notify(false);
    },

    undo: () => {
      const s = get();
      if (!s.undoStack.length) {
        set({ banner: { kind: 'info', message: 'Nothing to undo.' } });
        return;
      }
      if (!s.doc) return;
      const cur: UndoEntry = {
        doc: clone(s.doc),
        cursor: s.cursor,
        seq: s.seq,
        evidence: clone(s.evidence),
      };
      const undoStack = s.undoStack.slice();
      const entry = undoStack.pop()!;
      set({ undoStack, redoStack: s.redoStack.concat([cur]) });
      restore(entry);
      lastTag = null;
    },

    redo: () => {
      const s = get();
      if (!s.redoStack.length) {
        set({ banner: { kind: 'info', message: 'Nothing to redo.' } });
        return;
      }
      if (!s.doc) return;
      const cur: UndoEntry = {
        doc: clone(s.doc),
        cursor: s.cursor,
        seq: s.seq,
        evidence: clone(s.evidence),
      };
      const redoStack = s.redoStack.slice();
      const entry = redoStack.pop()!;
      set({ redoStack, undoStack: s.undoStack.concat([cur]) });
      restore(entry);
      lastTag = null;
    },

    currentEvidence: () => {
      const s = get();
      return s.cursor === null ? undefined : s.evidence[K(s.cursor)];
    },
  };
});
