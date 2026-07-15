import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { Document } from '../api';

// Mock the api boundary the store calls. Only the runtime functions need stubbing (types are erased).
const saveDocumentAs = vi.fn();
const putDocument = vi.fn();
const autosaveDocument = vi.fn();
const pickSaveFilePath = vi.fn();

vi.mock('../api', () => ({
  saveDocumentAs: (...a: unknown[]) => saveDocumentAs(...a),
  putDocument: (...a: unknown[]) => putDocument(...a),
  autosaveDocument: (...a: unknown[]) => autosaveDocument(...a),
  pickSaveFilePath: (...a: unknown[]) => pickSaveFilePath(...a),
}));

// Imported AFTER the mock is registered.
const { useDocument, AUTOSAVE_MS } = await import('./documentStore');

/** A minimal valid envelope plus an UNKNOWN top-level key + a feature payload, to prove preservation. */
function makeDoc(): Document {
  return {
    schema_version: '3',
    app: { name: 'camea', version: '0.2.0' },
    id: 'analysis-1',
    feature: 'mosaic',
    dataset: 'demo',
    experiment: '',
    data_dir: '/data/demo',
    dataset_key: 'demo#abc',
    created: '2026-07-14T00:00:00Z',
    modified: '2026-07-14T00:00:00Z',
    provenance: { authored_by: 'human', app_version: '0.2.0', workflow: 'sweep', independent_of_method: true },
    // an unknown top-level key the app has never heard of — must survive verbatim:
    a_hand_written_note: 'do not lose me',
    // a whole feature payload the generic store does not understand:
    tiles: { '11': { status: 'unplaced', state: 'unplaced', blank: false, human: false, stale: false, diverted: false } },
  } as Document;
}

const reset = () => useDocument.getState().reset();

beforeEach(() => {
  reset();
  saveDocumentAs.mockReset();
  putDocument.mockReset();
  autosaveDocument.mockReset();
  pickSaveFilePath.mockReset();
});
afterEach(() => vi.useRealTimers());

describe('documentStore — loading & dirty tracking', () => {
  it('openDocument adopts the doc CLEAN (not dirty) and idle autosave', () => {
    useDocument.getState().openDocument(makeDoc(), { analysisId: 'analysis-1', path: '/ws/demo.camea.json' });
    const s = useDocument.getState();
    expect(s.doc).not.toBeNull();
    expect(s.dirty).toBe(false);
    expect(s.analysisId).toBe('analysis-1');
    expect(s.lastSavedPath).toBe('/ws/demo.camea.json');
    expect(s.autosave.state).toBe('idle');
  });

  it('patchDocument marks dirty and PRESERVES unknown top-level keys + the feature payload', () => {
    useDocument.getState().openDocument(makeDoc(), { analysisId: 'analysis-1' });
    useDocument.getState().patchDocument({ modified: '2026-07-14T01:00:00Z' });
    const doc = useDocument.getState().doc as Record<string, unknown>;
    expect(useDocument.getState().dirty).toBe(true);
    expect(doc.modified).toBe('2026-07-14T01:00:00Z');
    expect(doc.a_hand_written_note).toBe('do not lose me'); // unknown key survived the spread
    expect(doc.tiles).toBeDefined(); // feature payload survived
  });

  it('updateDocument runs an arbitrary transform and marks dirty', () => {
    useDocument.getState().openDocument(makeDoc(), { analysisId: 'analysis-1' });
    useDocument.getState().updateDocument((d) => ({ ...d, cursor: 14 }) as Document);
    expect(useDocument.getState().dirty).toBe(true);
    expect((useDocument.getState().doc as Record<string, unknown>).cursor).toBe(14);
  });
});

describe('documentStore — real saves clear dirty', () => {
  it('saveAs(path) writes and CLEARS dirty, recording where/when', async () => {
    saveDocumentAs.mockResolvedValue({ path: '/ws/demo.camea.json', bytes: 10, saved_at: '2026-07-14T02:00:00Z' });
    useDocument.getState().openDocument(makeDoc(), { analysisId: 'analysis-1' });
    useDocument.getState().patchDocument({ modified: 'x' });
    expect(useDocument.getState().dirty).toBe(true);

    const result = await useDocument.getState().saveAs('/ws/demo.camea.json');
    expect(result).not.toBeNull();
    expect(saveDocumentAs).toHaveBeenCalledWith('/ws/demo.camea.json', expect.any(Object));
    expect(useDocument.getState().dirty).toBe(false);
    expect(useDocument.getState().lastSavedAt).toBe('2026-07-14T02:00:00Z');
  });

  it('saveAs() with no path picks one via the dialog; a cancel returns null and leaves dirty', async () => {
    pickSaveFilePath.mockResolvedValue(null); // the user cancelled the picker
    useDocument.getState().openDocument(makeDoc(), { analysisId: 'analysis-1' });
    useDocument.getState().patchDocument({ modified: 'x' });

    const result = await useDocument.getState().saveAs();
    expect(result).toBeNull();
    expect(saveDocumentAs).not.toHaveBeenCalled();
    expect(useDocument.getState().dirty).toBe(true); // still unsaved
  });

  it('saveToWorkspace PUTs and clears dirty', async () => {
    putDocument.mockResolvedValue({ path: '/ws/analysis-1', bytes: 10, saved_at: '2026-07-14T03:00:00Z' });
    useDocument.getState().openDocument(makeDoc(), { analysisId: 'analysis-1' });
    useDocument.getState().patchDocument({ modified: 'x' });
    await useDocument.getState().saveToWorkspace();
    expect(putDocument).toHaveBeenCalledWith('analysis-1', expect.any(Object));
    expect(useDocument.getState().dirty).toBe(false);
  });
});

describe('documentStore — autosave is a CRASH-NET, not a save (BEHAVIOUR R5.4/R29/W4)', () => {
  it('🔴 a successful autosave does NOT clear dirty', async () => {
    autosaveDocument.mockResolvedValue({ path: '/ws/.autosave', bytes: 10, saved_at: '2026-07-14T04:00:00Z' });
    useDocument.getState().openDocument(makeDoc(), { analysisId: 'analysis-1' });
    useDocument.getState().patchDocument({ modified: 'x' });
    expect(useDocument.getState().dirty).toBe(true);

    await useDocument.getState().autosaveNow();
    expect(autosaveDocument).toHaveBeenCalledWith('analysis-1', expect.any(Object));
    expect(useDocument.getState().autosave.state).toBe('ok');
    expect(useDocument.getState().dirty).toBe(true); // still dirty — autosave is not a save
  });

  it('🔴 an autosave failure is LOUD (recorded, message set) and never thrown to the caller', async () => {
    autosaveDocument.mockRejectedValue(new Error('AUTOSAVE FAILED: range_mismatch'));
    useDocument.getState().openDocument(makeDoc(), { analysisId: 'analysis-1' });
    useDocument.getState().patchDocument({ modified: 'x' });

    await expect(useDocument.getState().autosaveNow()).resolves.toBeUndefined(); // does not reject
    const a = useDocument.getState().autosave;
    expect(a.state).toBe('failed');
    expect(a.message).toContain('range_mismatch');
    expect(useDocument.getState().dirty).toBe(true);
  });

  it('scheduleAutosave is a no-op without an analysis (nowhere to autosave to)', () => {
    useDocument.getState().openDocument(makeDoc(), { analysisId: null });
    useDocument.getState().patchDocument({ modified: 'x' }); // calls scheduleAutosave internally
    expect(useDocument.getState().autosave.state).toBe('idle');
  });

  it('scheduleAutosave debounces and fires autosaveNow after AUTOSAVE_MS', async () => {
    vi.useFakeTimers();
    autosaveDocument.mockResolvedValue({ path: '/ws/.autosave', bytes: 10, saved_at: 't' });
    useDocument.getState().openDocument(makeDoc(), { analysisId: 'analysis-1' });

    useDocument.getState().patchDocument({ modified: 'a' });
    expect(useDocument.getState().autosave.state).toBe('pending');
    expect(autosaveDocument).not.toHaveBeenCalled();

    // A second edit inside the window must not fire a second timer's worth of saves.
    useDocument.getState().patchDocument({ modified: 'b' });
    await vi.advanceTimersByTimeAsync(AUTOSAVE_MS + 5);
    expect(autosaveDocument).toHaveBeenCalledTimes(1);
  });
});

describe('documentStore — reset', () => {
  it('clears everything', () => {
    useDocument.getState().openDocument(makeDoc(), { analysisId: 'analysis-1' });
    useDocument.getState().patchDocument({ modified: 'x' });
    useDocument.getState().reset();
    const s = useDocument.getState();
    expect(s.doc).toBeNull();
    expect(s.analysisId).toBeNull();
    expect(s.dirty).toBe(false);
    expect(s.autosave.state).toBe('idle');
  });
});
