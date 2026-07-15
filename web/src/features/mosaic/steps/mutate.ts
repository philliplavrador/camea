// A small write seam for the Range/Screen steps.
//
// The sweep store's public API covers tile-state transitions (`excludeAt` / `unexclude`) and the live
// gaps, but NOT the blank REFUSAL list nor the pass-split override — those are edits the wizard's early
// steps make to the working document that the store leaves to the caller (the store sets `refuse` only
// at `hydrate`). Rather than reach into a second store, this patches the sweep store's own document and
// pushes the change through the store's OWN persistence hook (`hooks.onChange`) — the exact seam an
// A/E judgement uses (see store/types.ts `SweepHooks`), so the crash-net / Save pick the edit up.
//
// ⛔ NO DATASET KNOWLEDGE: this names no trial, count or exclusion; it only forwards a caller's patch.

import { useSweepStore } from '../store';
import type { MosaicDocument } from '../../../api';

const iso = (): string => new Date().toISOString();

/**
 * Patch the working document held by the sweep store and notify the persistence hook.
 *
 * @param patch  a shallow merge over the document (unknown keys survive — it is a spread).
 * @param refuse when given, also replaces the live blank list the matcher reads (`store.refuse`) —
 *               keep it in step with `doc.blank_scan.blank`.
 */
export function patchWorkingDoc(patch: Partial<MosaicDocument>, refuse?: number[]): void {
  const s = useSweepStore.getState();
  if (!s.doc) return;
  const doc: MosaicDocument = { ...s.doc, ...patch, modified: iso() };
  useSweepStore.setState(refuse !== undefined ? { doc, refuse } : { doc });
  s.hooks.onChange?.(doc, { judgement: false });
}
