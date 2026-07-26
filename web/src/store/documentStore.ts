// THE DOCUMENT STORE — holds the current analysis document, tracks dirty state, saves from ANYWHERE
// (Ctrl+S, above every screen gate), and runs the debounced autosave crash-net.
//
// WHY ZUSTAND: the same reason the sweep store is zustand. `Ctrl+S` is a global key handler that lives
// OUTSIDE the React tree (BEHAVIOUR R5.2 — handled above the `screen !== 'sweep'` gate), and it must be
// able to call `save()` with no Provider plumbing: `useDocument.getState().saveAs()`. The autosave
// debounce timer and the "A/E autosave unconditionally" hook are likewise imperative.
//
// 🔴 UNKNOWN KEYS ROUND-TRIP VERBATIM (task requirement; BEHAVIOUR: the backend preserves a whole
// feature payload and a hand-written GT note it has never heard of). This store NEVER reconstructs a
// document from known fields: it holds the exact object the server returned, and every edit is a
// SPREAD over it (`{...doc, ...patch}`), so unknown top-level keys survive untouched. The one place
// dataset knowledge would be stripped — a stale `EXCLUDED_TRIALS` block on re-save (R2.4) — is the
// SERVER's normalise step, not ours; the front end must never resurrect it, and never authors it either.
//
// ⭐ AUTO-SAVE IS THE DURABLE SAVE NOW (2026-07-24). Projects "save themselves": every change is
// written to the durable analysis document (`PUT`, not the sidecar) and CLEARS `dirty`. There is no
// manual Save button — a quiet "Saved" indicator reads `autosave.state`/`at` (see `app/SaveIndicator`).
// An auto-save FAILURE is still LOUD (W4): recorded in `autosave.state = 'failed'` with a message the
// UI surfaces — never swallowed. (Was a crash-net-only sidecar before the project-manager reframe.)
//
// ⛔ NO DATASET KNOWLEDGE. This store holds whatever document it is given; it names no trial, count or
// exclusion, and it is feature-agnostic (it knows only the generic `Document` envelope). A feature
// reads its own payload by casting, e.g. `useDocument.getState().doc as MosaicDocument`.

import { create } from 'zustand';
import {
  saveDocumentAs,
  putDocument,
  pickSaveFilePath,
  type Document,
  type SaveResult,
} from '../api';

/** Autosave debounce (BEHAVIOUR §7 `AUTOSAVE_MS`), plus fired unconditionally on every A/E by the caller. */
export const AUTOSAVE_MS = 2000;

export type AutosaveState = 'idle' | 'pending' | 'saving' | 'ok' | 'failed';

export interface AutosaveStatus {
  state: AutosaveState;
  /** The loud failure text (W4). Present iff `state === 'failed'`. */
  message: string | null;
  /** `saved_at` of the last successful autosave. */
  at: string | null;
}

export interface DocumentStore {
  /** The analysis id (the autosave slot key). Null for a file-only project or before an analysis exists. */
  analysisId: string | null;
  /** The current document, held VERBATIM. Null before one is opened. Cast to a feature type to read a payload. */
  doc: Document | null;
  /** Unsaved changes since the last real save. Autosave does NOT clear this (it is a crash-net). */
  dirty: boolean;
  /** A real save (save-as / workspace) is in flight. */
  saving: boolean;
  lastSavedAt: string | null;
  lastSavedPath: string | null;
  autosave: AutosaveStatus;

  // ── loading ──
  /** Adopt a document as the current one, CLEAN (from `Load a project…` or a workspace read). */
  openDocument: (doc: Document, meta?: { analysisId?: string | null; path?: string | null }) => void;
  /** Bind the analysis id (e.g. after the server authored the doc in `createAnalysis`). */
  setAnalysisId: (analysisId: string | null) => void;
  /** Surface the crash-net as UNAVAILABLE — there is no analysis slot to autosave into (e.g. no
   *  workspace is set). LOUD, never silent (W4): the Mosaic note and the sweep overlay both read
   *  `autosave.state === 'failed'`, so the user is told autosave cannot run instead of losing work
   *  to a silent no-op. Cleared by the next `openDocument`. */
  markAutosaveUnavailable: (message?: string) => void;

  // ── local edits (mark dirty + schedule the crash-net) ──
  /** Replace the whole document (e.g. after a server transform like seed/discard). Marks dirty. */
  setDocument: (next: Document) => void;
  /** Shallow-merge a patch over the document. Spreads, so unknown keys survive. Marks dirty. */
  patchDocument: (patch: Partial<Document>) => void;
  /** Transform the document with an updater that receives and returns the whole object. Marks dirty. */
  updateDocument: (updater: (doc: Document) => Document) => void;

  // ── real saves (clear dirty) ──
  /** `Save…` / Ctrl+S: a file the user names. Picks a path (native dialog → prompt, R38) if none given. */
  saveAs: (path?: string) => Promise<SaveResult | null>;
  /** Durable workspace save (`PUT`). Needs an `analysisId`. Clears dirty. */
  saveToWorkspace: () => Promise<SaveResult>;

  // ── autosave crash-net (does NOT clear dirty) ──
  /** Debounced 2 s. Every local edit calls this; the caller ALSO calls `autosaveNow` on every A/E. */
  scheduleAutosave: () => void;
  /** Fire the crash-net immediately. Loud on failure; never throws to the (judgement) caller. */
  autosaveNow: () => Promise<void>;

  reset: () => void;
}

// The debounce timer is module-scoped: there is one document store, and Ctrl+S / A-E reach it via
// `getState()` from outside React, so the timer cannot live in a React ref.
let autosaveTimer: ReturnType<typeof setTimeout> | null = null;
function clearAutosaveTimer(): void {
  if (autosaveTimer != null) {
    clearTimeout(autosaveTimer);
    autosaveTimer = null;
  }
}

const IDLE_AUTOSAVE: AutosaveStatus = { state: 'idle', message: null, at: null };

function errMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export const useDocument = create<DocumentStore>((set, get) => ({
  analysisId: null,
  doc: null,
  dirty: false,
  saving: false,
  lastSavedAt: null,
  lastSavedPath: null,
  autosave: IDLE_AUTOSAVE,

  openDocument: (doc, meta) => {
    clearAutosaveTimer();
    set({
      doc,
      analysisId: meta?.analysisId ?? get().analysisId,
      dirty: false,
      lastSavedPath: meta?.path ?? get().lastSavedPath,
      autosave: IDLE_AUTOSAVE,
    });
  },

  setAnalysisId: (analysisId) => set({ analysisId }),

  markAutosaveUnavailable: (message = 'unavailable — set a workspace') =>
    // W4 lives in `autosave.state === 'failed'` — reuse it so the existing Mosaic note + sweep-overlay
    // warning surface this with no new render path. There is nowhere to autosave to, so `at` stays null.
    set({ autosave: { state: 'failed', message, at: null } }),

  setDocument: (next) => {
    set({ doc: next, dirty: true });
    get().scheduleAutosave();
  },

  patchDocument: (patch) => {
    const doc = get().doc;
    if (doc == null) return;
    // Spread preserves EVERY existing key, including unknown ones the app has never heard of.
    set({ doc: { ...doc, ...patch }, dirty: true });
    get().scheduleAutosave();
  },

  updateDocument: (updater) => {
    const doc = get().doc;
    if (doc == null) return;
    set({ doc: updater(doc), dirty: true });
    get().scheduleAutosave();
  },

  saveAs: async (path) => {
    const doc = get().doc;
    if (doc == null) return null;
    let target = path;
    if (target == null) {
      const defaultName = `${doc.dataset || 'project'}.camea.json`;
      const chosen = await pickSaveFilePath({ title: 'Save project as…', defaultName });
      if (chosen == null) return null; // the user cancelled
      target = chosen;
    }
    set({ saving: true });
    try {
      const result = await saveDocumentAs(target, doc);
      set({ dirty: false, lastSavedAt: result.saved_at, lastSavedPath: result.path });
      return result;
    } finally {
      set({ saving: false });
    }
  },

  saveToWorkspace: async () => {
    const { doc, analysisId } = get();
    if (doc == null) throw new Error('no document to save');
    if (analysisId == null) throw new Error('no analysis to save into');
    set({ saving: true });
    try {
      const result = await putDocument(analysisId, doc);
      set({ dirty: false, lastSavedAt: result.saved_at, lastSavedPath: result.path });
      return result;
    } finally {
      set({ saving: false });
    }
  },

  scheduleAutosave: () => {
    // The crash-net keys on the analysis slot; with no analysis there is nowhere to autosave to.
    if (get().analysisId == null) return;
    clearAutosaveTimer();
    set((s) => ({ autosave: { ...s.autosave, state: 'pending' } }));
    autosaveTimer = setTimeout(() => {
      autosaveTimer = null;
      void get().autosaveNow();
    }, AUTOSAVE_MS);
  },

  autosaveNow: async () => {
    clearAutosaveTimer();
    const { doc, analysisId } = get();
    if (doc == null || analysisId == null) return;
    set((s) => ({ autosave: { ...s.autosave, state: 'saving' } }));
    try {
      // ⭐ THE DURABLE SAVE (2026-07-24): write the real document and CLEAR dirty — the project saves
      // itself. (Was `autosaveDocument` → the crash-net sidecar, which deliberately did NOT clear
      // dirty. The reframe promotes auto-save to the durable write; `saveToWorkspace` is the same op.)
      const result = await putDocument(analysisId, doc);
      set({
        dirty: false,
        lastSavedAt: result.saved_at,
        lastSavedPath: result.path,
        autosave: { state: 'ok', message: null, at: result.saved_at },
      });
    } catch (e) {
      // 🔴 Never swallowed — recorded loudly so the indicator + Mosaic note can shout (W4).
      set({ autosave: { state: 'failed', message: errMessage(e), at: get().autosave.at } });
    }
  },

  reset: () => {
    clearAutosaveTimer();
    set({
      analysisId: null,
      doc: null,
      dirty: false,
      saving: false,
      lastSavedAt: null,
      lastSavedPath: null,
      autosave: IDLE_AUTOSAVE,
    });
  },
}));
