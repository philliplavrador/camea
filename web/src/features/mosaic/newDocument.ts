// AUTHOR A FRESH, UNSAVED MOSAIC DOCUMENT — client-side, for a dataset opened without a workspace.
//
// ⭐ WHY THIS EXISTS. The server authors a document only through `POST /api/workspace/analyses`, which
// requires a workspace the user has chosen. But a dataset can be OPENED and swept before any workspace
// exists (the project file is the app's only memory — R2 — and it is written on `Save…`, not on open).
// So the fresh, in-memory skeleton is authored here, and the server takes over the moment it is saved:
// `POST /api/documents/save-as` runs the SAME prepare (structural-validate → normalise → stamp →
// full-validate) that authors it, so the client shape only has to be structurally valid — gaps,
// unusable_tiles and the provenance stamp are (re)derived on the server on the way out.
//
// This mirrors the backend's `new_envelope` (camea.core.document) + `new_payload`
// (camea.features.mosaic.document) EXACTLY, field for field — verified round-tripping through the live
// save-as + load endpoints. It is NOT the forbidden reimplementation of `new_doc`+`seed_from_build`:
// there is no build, no seed, no provenance verdict here — every tile is `unplaced`, which is the one
// honest fresh state (§4.1, R2).
//
// ⛔ NO DATASET KNOWLEDGE (HARD RULE 3). Every value below comes from the session, the run detection or
// the blank proposal the caller passed — never a literal trial number, count, range or exclusion.

import type {
  MosaicDocument,
  SessionResponse,
  RunDetection,
  BlankProposal,
  TileRecord,
} from '../../api';

// Mirrors the backend constants (camea.features.mosaic.document / camea.core.document). These are UI
// structure / schema constants, not dataset knowledge.
const SCHEMA_VERSION = 'camea-document-1.0';
const APP_NAME = 'Camea';
const APP_VERSION = '0.2.0';
const WORKFLOW_HAND = 'hand placement from scratch';
const TILE_PX = 512;
const R_UNPLACED = 256;
const TOLERANCE_PX = { anchor: 96, region_default: 256, grading: 10 };
const BLANK_MEASURE = 'std of DoG(sigma=3, sigma=30) of the frame as read';

function passOf(trial: number, split: number | null): number | null {
  if (split == null) return null;
  return trial <= split ? 1 : 2;
}

function coordinates(frameNote: string): string {
  const note = (frameNote || '').trim() || 'the frame as the reader produced it (see `frame_note`)';
  return `RELATIVE. Tile TOP-LEFT in px, measured FROM \`origin_trial\` at (0,0), in ${note}.`;
}

export interface NewDocInputs {
  session: SessionResponse;
  run: RunDetection;
  /** Optional blank recommendation (Screen step re-fetches it too). Its `proposed` seeds `blank_scan`. */
  proposal?: BlankProposal | null;
  /** A minted analysis id when a workspace exists; a fresh uuid otherwise (matches `new_envelope`). */
  id?: string;
}

/**
 * A fresh mosaic document over the run's trials, every tile `unplaced`. `blank_scan.blank` starts as the
 * scan's proposal because `Hand place` is the DEFAULT on a scanned frame (R6.2) — a recommendation the
 * matcher will refuse, never an exclusion (R16). The document EXCLUDES NOTHING on a fresh open (R2.1).
 */
export function newMosaicDocument({ session, run, proposal, id }: NewDocInputs): MosaicDocument {
  const now = new Date().toISOString();
  const split = run.pass_split.value;
  const trials = [...run.trials].sort((a, b) => a - b);

  const proposed = [...(proposal?.proposed ?? [])].sort((a, b) => a - b);
  const texture = proposal?.texture ?? {};

  const tiles: Record<string, TileRecord> = {};
  for (const t of trials) {
    tiles[String(t)] = {
      status: 'unplaced',
      state: 'unplaced',
      x: null,
      y: null,
      r: R_UNPLACED,
      pass: passOf(t, split),
      machine: null,
      moved_px: null,
      ncc: null,
      margin: null,
      n_anchors: null,
      // a MEASUREMENT about the pixels, not a judgement — never cleared (§4.3).
      blank: proposed.includes(t),
      texture: texture[String(t)] ?? null,
      judged_at: null,
      // The three boolean facts every tile carries (§4.3). All false on a fresh, unjudged tile; the
      // backend fills the same defaults on serialization.
      human: false,
      stale: false,
      diverted: false,
    };
  }

  const uuid =
    id ??
    (typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID().replace(/-/g, '')
      : `web-${Date.now()}-${Math.random().toString(36).slice(2)}`);

  return {
    schema_version: SCHEMA_VERSION,
    app: { name: APP_NAME, version: APP_VERSION },
    id: uuid,
    feature: 'mosaic',
    dataset: session.dataset,
    experiment: session.experiment ?? '',
    data_dir: session.path,
    dataset_key: session.dataset_key,
    created: now,
    modified: now,
    provenance: {
      authored_by: APP_NAME,
      app_version: APP_VERSION,
      workflow: WORKFLOW_HAND,
      seeded_from: null,
      // nothing has seeded it yet; the server's `stamp()` re-derives this on save (R28).
      independent_of_method: true,
      // All zero on a fresh document; the server recomputes `human_edits` from the tiles on every save.
      human_edits: {
        accepted_unchanged: 0,
        moved: 0,
        excluded: 0,
        unverified: 0,
        rescued: 0,
        median_move_px: 0,
        max_move_px: 0,
        diverted_to_solver: 0,
      },
      scale: { um_per_px: null, source: 'unknown' },
    },
    tiles,
    trial_range: [run.lo, run.hi],
    pass_split: split,
    origin_trial: trials.length ? trials[0] : run.lo,
    tile_px: TILE_PX,
    coordinates: coordinates(session.frame_note),
    tolerance_px: TOLERANCE_PX,
    gaps: [], // filled by the server's normalise() on save
    unusable_tiles: [], // filled by the server's normalise() on save
    cursor: trials.length ? trials[0] : null,
    blank_scan: {
      threshold: proposal?.threshold ?? null,
      measure: proposal?.measure ?? BLANK_MEASURE,
      // the DECISION starts AS the proposal (Hand place is the default); `scanned` preserves the
      // measurement so the Screen step still has the frames to list after a Keep overrules one.
      blank: proposed,
      scanned: proposed,
      accepted: false,
      overruled_by_user: [],
    },
    run: {
      detected: run.detected,
      why: run.why ?? '',
      pass_split_detected: run.pass_split.detected,
      pass_split_why: run.pass_split.why ?? '',
      n_trials: trials.length,
    },
    tone: {},
    build: null,
  } as MosaicDocument;
}
