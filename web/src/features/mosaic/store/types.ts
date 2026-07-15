// The sweep store's working types. Every backend-owned shape is an ALIAS of a generated contract type
// (HARD RULE 2) — nothing here re-declares a request/response body. The store-only types (Evidence,
// PlacementDecision, Banner, UndoEntry, SweepHooks) describe client state the backend never sees.

import type {
  MosaicDocument,
  TileRecord,
  MatchResult,
  Candidate,
  RejectedMatch,
} from '../../../api';

/** A world top-left corner `[x, y]` (BEHAVIOUR R19 — TOP-LEFT, never a centre). */
export type Position = [number, number];

/** The FOUR tile states. There are no others (BEHAVIOUR §4). Derived from the contract. */
export type TileState = TileRecord['state'];

/** A tile record, exactly as the document carries it. */
export type Tile = TileRecord;

/** The document's tile map, keyed by `String(trial)`. */
export type Tiles = MosaicDocument['tiles'];

/**
 * ⭐ Per-trial evidence, STAMPED with the anchor field it was measured against (BEHAVIOUR R22). Anything
 * that would ACT on it (`V`, `1`–`9`) re-fetches unless `field` is bit-for-bit the field the app has
 * now — otherwise a cached candidate list is a set of world coordinates against a reference that no
 * longer exists, offered to the user with a confident NCC beside it.
 */
export interface Evidence {
  /** The raw match result (the rail reads NCC/margin/anchors/composite from here). */
  result: MatchResult;
  /** Signature of the anchor field this was measured against (see `fieldSignature`). */
  field: string;
  /** The ranked peaks (`V` and `1`–`9` read these). */
  candidates: Candidate[];
  /** If the human took a runner-up here, which one (0-indexed rank). Display is +1 (R12.3). */
  pickedRank?: number;
}

export type BannerKind = 'ok' | 'warn' | 'bad' | 'info';

/** The loud running commentary above the canvas (divert / stale / end-of-run / origin-trap). A live
 *  warning about CURRENT STATE — it stays on the page, it is not a tooltip (BEHAVIOUR R3.8, §5). */
export interface Banner {
  kind: BannerKind;
  /** PLAIN text. The UI owns any emphasis; the store never emits markup. */
  message: string;
}

/**
 * ⭐ The solver-fallback decision (BEHAVIOUR R15) — a PURE function of a match result and the solver's
 * position. It decides a POSITION, never a STATE: everything it places lands `unverified`. Nothing is
 * ever auto-anchored (I3).
 */
export interface PlacementDecision {
  /** Where the tile goes, or `null` when there is no match AND no solver position (it stays unplaced). */
  position: Position | null;
  /** The position is the SOLVER's, not the matcher's — a divert (W3, magenta outline). */
  diverted: boolean;
  /** The match cleared BOTH gates (margin ≥ 0.20 and ncc ≥ 0.65) — the match wins. */
  confident: boolean;
  /** The matcher gave nothing at all (blank refusal / empty candidate list). */
  none: boolean;
  /** There was no solver position to fall back on — the match is used anyway, and it is announced. */
  noSolver: boolean;
  /** |best − solver| in px, or null when one of them is missing. */
  disagreePx: number | null;
  /** PLAIN-text reasons the match was not trusted (also written to `tile.divert_reason` and QC). */
  why: string[];
  /** The rejected match, kept in full as the *evidence for* the divert (null when not diverted). */
  rejected: RejectedMatch | null;
}

/** One undo entry — a deep snapshot. 🔴 The evidence store is PART of the snapshot (BEHAVIOUR R36): an
 *  undo that restores the document but not the evidence leaves the rail describing a field the document
 *  no longer has. */
export interface UndoEntry {
  doc: MosaicDocument;
  cursor: number | null;
  seq: number;
  evidence: Record<string, Evidence>;
}

/** Why a placement is happening — drives the `source` string and the `human` flag. */
export type MoveSource = 'drag' | 'nudge' | 'snap' | 'alternative' | 'handplace' | 'rescue';

/**
 * The persistence seam. The sweep store owns the working document but NOT saving — that is the document
 * store's job (Ctrl+S from any screen, the debounced crash-net, the loud autosave-failure). The wizard
 * glue wires this once so a judgement flows out to the saver:
 *
 *   useSweepStore.getState().setHooks({
 *     onChange: (doc, { judgement }) => {
 *       useDocument.getState().setDocument(doc);          // mark dirty + schedule the crash-net
 *       if (judgement) void useDocument.getState().autosaveNow();  // A/E autosave UNCONDITIONALLY (R29)
 *     },
 *   });
 *
 * Left undefined (the default), the store is fully functional and unit-testable with no saver attached.
 */
export interface SweepHooks {
  onChange?: (doc: MosaicDocument, opts: { judgement: boolean }) => void;
}
