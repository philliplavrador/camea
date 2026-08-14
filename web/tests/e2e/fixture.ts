// ─────────────────────────────────────────────────────────────────────────────
// FIXTURE FACTS — the committed synthetic dataset (tests/fixtures/synthetic/).
//
// These numbers are TEST FIXTURE knowledge, which HARD RULE 3 explicitly permits
// ("Numbers in tests/fixtures are fine; in app code they are a violation"). They
// describe the synthetic acquisition the backend serves under `tests/fixtures`,
// NOT the user's real 260620d dataset — the app must never know anything about
// either one.
//
// Source of truth: tests/fixtures/make_synthetic.py + tests/fixtures/synthetic/log.txt,
// and docs/FRONTEND.md §"The committed synthetic fixture".
// ─────────────────────────────────────────────────────────────────────────────

import { randomUUID } from 'node:crypto';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const FIXTURE = {
  /** The dataset name as it appears on the home card and in the URL slug (`synthetic-…`). */
  name: 'synthetic',

  /** Snapshot trials named in log.txt: 5, 9, 11..20 = 12 snapshots. (Smoke asserts 12.) */
  snapshots: 12,

  /** The mosaic RUN = the longest contiguous 512×512 block = trials 11..20 (10 tiles). */
  runLo: 11,
  runHi: 20,
  runCount: 10,

  /**
   * The pass split, detected from the timestamps alone: a planted 40 s stage-return
   * pause sits between 16 (15:48:10) and 17 (15:48:50), so the split is 16.
   */
  passSplit: 16,

  /** A second, one-tile block outside the run — trial 5. (Present, not excluded, on a fresh open.) */
  strayTrial: 5,

  /** An off-shape frame (512×128) the mosaic shape-gate refuses BY SHAPE, not by number — trial 9. */
  offShapeTrial: 9,

  /** Every tile is 512 px square (BEHAVIOUR §7 TILE = 512). */
  tile: 512,

  /** On a fresh open the app excludes NOTHING (R2.1). This is the only "count" the app owns: zero. */
  excludedOnFreshOpen: 0,
} as const;

/**
 * DATASET-KNOWLEDGE POISON — phrases and numbers that belong to the user's real 260620d dataset and
 * must NEVER appear as an app default (HARD RULE 3, BEHAVIOUR I1/R2/§6.1). These are asserted ABSENT.
 *
 * We test PHRASES, not bare digits: a bare "26" could legitimately be a coordinate or a millisecond
 * reading, but "26 thrown out" / "312 usable of 338" / "EXCLUDED_TRIALS" / "260620d" can only be the
 * app having smuggled the user's answer back in. (R7.5 warns that a loose scan gives false passes.)
 */
export const FORBIDDEN_KNOWLEDGE: RegExp[] = [
  /260620/i, //                    the dataset id must never be recognised
  /EXCLUDED_TRIALS/, //            the deleted project-file block (R2.4, §6.1)
  /\bthrown out\b/i, //            "26 thrown out" (R2.2)
  /\busable of\b/i, //             "312 usable of 338" (R2.2)
  /312\s*\/\s*338/, //             the challenge ratio as a default
  /26\s+(?:frames|tiles|snapshots)?\s*(?:thrown|excluded|removed)/i,
  /hard[-\s]?coded ruling/i, //    the removed provenance source (§6.1)
];

/** A short wait for elements the test EXPECTS to be missing (keeps the red run snappy pre-UI). */
export const SHORT = 4_000;

// ─────────────────────────────────────────────────────────────────────────────
// THE TWO PATHS the new-project flow asks for (2026-07-25).
//
// ⚠️ `saveRoot` is deliberately in the OS temp dir and NOT under the repo: the backend REFUSES a
// project folder inside the checkout (a project under `web/.playwright-state` would be refused with
// `409 refused`, and the test would look like a UI bug). Every run mints a fresh sub-folder, because
// creating a project over an existing one is refused too — by design.
// ─────────────────────────────────────────────────────────────────────────────

/** Forward slashes: it goes into a path box a human would paste into, and the app normalises to `/`. */
const fwd = (p: string): string => p.replace(/\\/g, '/');

const repoRoot = fwd(resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..'));

export const PATHS = {
  /** The committed synthetic acquisition — what goes in "Pull data from". */
  data: `${repoRoot}/tests/fixtures/synthetic`,
  /** Its parent, to exercise "you typed a folder holding acquisitions". */
  dataParent: `${repoRoot}/tests/fixtures`,
  /** Where e2e projects are saved. Outside the repo, or the backend refuses it. */
  saveRoot: fwd(join(tmpdir(), 'camea-e2e')),
} as const;

/** A save folder no other test is using. */
export function freshSaveFolder(label = 'p'): string {
  return `${PATHS.saveRoot}/${label}-${randomUUID().slice(0, 8)}`;
}

/**
 * The committed synthetic survey VIDEO (tests/fixtures/survey.avi — regenerate with
 * `uv run python tests/fixtures/make_synthetic_video.py`). Crops of one generated world
 * panned in a 2-row serpentine; the videomosaic pipeline must build it with SHIPPED
 * DEFAULTS, because the UI sends no config overrides.
 */
export const VIDEO_FIXTURE = {
  path: `${repoRoot}/tests/fixtures/survey.avi`,
  width: 480,
  height: 320,
} as const;

/**
 * The committed synthetic MaxLab session (tests/fixtures/mea/ — regenerate with
 * `uv run python tests/fixtures/make_synthetic_mea.py`). Two recordings under one plate, 19 kB
 * each, so "pick several at once" is a real gesture in a test.
 *
 * ⛔ **The chip in it is 13 × 5 on a 12.5 µm pitch, which is no real device.** A fixture with
 * MaxWell's own 220 / 17.5 would let a hard-coded 220 pass its own test. These are FIXTURE facts,
 * which HARD RULE 3 permits inside `tests/`; the app must know none of them.
 */
export const MEA_FIXTURE = {
  /** The folder to point the import at — it holds both recordings, one level down. */
  dir: `${repoRoot}/tests/fixtures/mea`,
  /** A folder with no recordings under it at all, for the "nothing here" case. */
  emptyDir: `${repoRoot}/tests/fixtures/synthetic`,
  labels: ['Network/000001', 'Network/000002'],
  count: 2,
} as const;
