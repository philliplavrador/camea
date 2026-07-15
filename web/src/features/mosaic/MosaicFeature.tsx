// ⭐ THE MOSAIC FEATURE — the six-step wizard shell (BEHAVIOUR §2, R4/R5).
//
// This is the seam where every parallel piece meets: the home browser navigates here with a dataset
// `:key`; this component opens the SESSION, authors the working DOCUMENT, hydrates the SWEEP STORE, wires
// SAVE (R5) and the crash-net, owns the STEP GATE (R4.3) and mounts the active step. The steps hold the
// JSX; the stores hold the spine; this holds the lifecycle.
//
// ⛔ NO DATASET KNOWLEDGE (HARD RULE 3). The only "numbers" here are the session's own trial list and the
// run detection the backend measured — never a literal trial, count, range or exclusion.

import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  getDataset,
  openSessionAndWait,
  scanDatasets,
  detectRun,
  proposeScreen,
  loadDocument,
  pickOpenFilePath,
  tilePngUrl,
  cacheBuster,
  getWorkspace,
  createAnalysis,
  listAnalyses,
  type SessionResponse,
  type MosaicDocument,
  type BlankProposal,
  type WorkspaceInfo,
} from '../../api';
import { useToast, useRegisterSaver } from '../../app';
import { useDocument } from '../../store/documentStore';
import { useSweepStore, anyPlaced } from './store';
import { newMosaicDocument } from './newDocument';
import { WizardNav } from './WizardNav';
import { LoadStep } from './steps/Load';
import { RangeStep } from './steps/Range';
import { ScreenStep } from './steps/Screen';
import { PlaceStep } from './steps/Place';
import { SweepStep } from './steps/Sweep';
import { MosaicStep } from './steps/Mosaic';
import type { MosaicStepId } from './steps/types';
import styles from './MosaicFeature.module.css';

const STEP_INDEX: Record<MosaicStepId, number> = {
  load: 0,
  range: 1,
  screen: 2,
  place: 3,
  sweep: 4,
  mosaic: 5,
};

const errMsg = (e: unknown): string => (e instanceof Error ? e.message : String(e));

/** The largest SQUARE (N×N) shape group's trials — a mosaic wants square tiles, and a session holds
 *  exactly one shape (the backend refuses a mixed-shape open). No trial number is named. */
function squareTrials(shapes: { w: number; h: number; n: number; trials: number[] }[]): number[] | null {
  const square = shapes.filter((s) => s.w === s.h).sort((a, b) => b.n - a.n)[0];
  return square ? [...square.trials].sort((a, b) => a - b) : null;
}

// ── THE AUTOSAVE SLOT (R29). The crash-net keys on an ANALYSIS ID — with none, `scheduleAutosave`/
//    `autosaveNow` early-return and NOTHING is crash-saved during a sweep. So opening a dataset must
//    ESTABLISH one (create-or-adopt). The document's `id` IS the analysis id (the server's slot guard
//    refuses a mismatch), which is why a fresh doc is authored WITH the minted id. No writable
//    workspace ⇒ there is nowhere to autosave to; that is surfaced as the loud W4 state, never a
//    silent no-op. Neither helper THROWS — a slot problem must not block opening or sweeping.
type SlotResult = { id: string | null; reason?: string };

const NO_WORKSPACE_REASON = 'unavailable — set a workspace';

async function readWorkspace(): Promise<WorkspaceInfo | { reason: string }> {
  try {
    return await getWorkspace();
  } catch (e) {
    return { reason: `unavailable — ${errMsg(e)}` };
  }
}

/** Mint the slot for a freshly authored document: create an analysis when a writable workspace exists.
 *  The returned `id` becomes BOTH the document's `id` and the autosave slot key. */
async function createAnalysisSlot(sess: SessionResponse, trials: number[]): Promise<SlotResult> {
  const ws = await readWorkspace();
  if ('reason' in ws) return { id: null, reason: ws.reason };
  if (!ws.path || !ws.writable) return { id: null, reason: NO_WORKSPACE_REASON };
  try {
    const summary = await createAnalysis({
      session_id: sess.session_id,
      feature: 'mosaic',
      name: sess.dataset || 'mosaic',
      trials,
    });
    return { id: summary.analysis_id };
  } catch (e) {
    // A workspace exists but the slot could not be made — say so honestly; do not block the open.
    return { id: null, reason: `unavailable — could not create an analysis (${errMsg(e)})` };
  }
}

/** Adopt the slot a LOADED document already belongs to: its `id` is the analysis id, and the crash-net
 *  can route to it iff that analysis lives in the current workspace. A standalone project file (Save…'d
 *  outside a workspace) has no slot — autosave stays unavailable until it is saved into one. */
async function adoptAnalysisSlot(docId: string | null | undefined): Promise<SlotResult> {
  const ws = await readWorkspace();
  if ('reason' in ws) return { id: null, reason: ws.reason };
  if (!ws.path || !ws.writable) return { id: null, reason: NO_WORKSPACE_REASON };
  if (!docId) return { id: null, reason: 'unavailable — this project has no analysis id' };
  try {
    const { analyses } = await listAnalyses();
    if (analyses.some((a) => a.analysis_id === docId)) return { id: docId };
  } catch {
    /* fall through to the unavailable notice below */
  }
  return {
    id: null,
    reason: 'unavailable — this project is not in your workspace; use Save… (Ctrl+S)',
  };
}

export function MosaicFeature() {
  const { key } = useParams<{ key: string }>();
  const toast = useToast();

  const [step, setStep] = useState<MosaicStepId>('load');
  const [openPhase, setOpenPhase] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [session, setSession] = useState<SessionResponse | null>(null);

  const doc = useSweepStore((s) => s.doc);
  const sessionId = useSweepStore((s) => s.sessionId);
  const order = useSweepStore((s) => s.order);

  // ── wire the persistence seam ONCE: a sweep-store change flows to the document store (dirty + the
  //    crash-net), and an A/E judgement autosaves unconditionally (R29). ────────────────────────────
  useEffect(() => {
    useSweepStore.getState().setHooks({
      onChange: (nextDoc, { judgement }) => {
        useDocument.getState().setDocument(nextDoc);
        if (judgement) void useDocument.getState().autosaveNow();
      },
    });
  }, []);

  // ── Save from EVERY screen (R5). The shell owns the button + Ctrl/⌘+S; the feature registers WHAT to
  //    save. The saver reads the latest document off the store, so it never goes stale. ──────────────
  useRegisterSaver(
    useCallback(async () => {
      const current = useDocument.getState().doc;
      if (!current) {
        toast.push('Nothing to save yet.', { tone: 'default' });
        return;
      }
      try {
        const res = await useDocument.getState().saveAs();
        if (res) toast.push(`Saved — ${res.path}`, { tone: 'good' });
      } catch (e) {
        toast.push(`Save failed: ${errMsg(e)}`, { tone: 'danger' });
      }
    }, [toast]),
  );

  // ── the open lifecycle: author a fresh document from the session, hydrate the spine, land on Range. ─
  const openToken = useRef(0);

  const openDatasetByKey = useCallback(async (dsKey: string, token: number): Promise<void> => {
    const alive = () => token === openToken.current;
    setError(null);
    setStep('load');
    setOpenPhase('reading dataset…');

    const detail = await getDataset(dsKey);
    if (!alive()) return;
    const trials = squareTrials(detail.summary.shapes ?? []);
    if (!trials || trials.length === 0) {
      throw new Error('this dataset has no square (N×N) frames to build a mosaic from.');
    }

    setOpenPhase('opening session…');
    const sess = await openSessionAndWait(
      { dataset_key: dsKey, trials },
      { onProgress: (j) => alive() && setOpenPhase(j.phase ?? j.message ?? 'opening…') },
    );
    if (!alive()) return;

    const run = await detectRun({ session_id: sess.session_id });
    if (!alive()) return;

    let proposal: BlankProposal | null = null;
    try {
      proposal = await proposeScreen({
        session_id: sess.session_id,
        trials: run.trials,
        pass_split: run.pass_split.value,
      });
    } catch {
      /* the blank recommendation is a soft input — the Screen step re-fetches it too */
    }
    if (!alive()) return;

    const orderTrials = [...run.trials].sort((a, b) => a - b);

    // ⭐ ESTABLISH THE AUTOSAVE SLOT (R29) BEFORE authoring the doc — the fresh document must carry the
    //    minted analysis id as its own `id`, or the server's slot guard refuses every autosave.
    setOpenPhase('preparing the workspace…');
    const slot = await createAnalysisSlot(sess, orderTrials);
    if (!alive()) return;

    const fresh = newMosaicDocument({ session: sess, run, proposal, id: slot.id ?? undefined });
    setSession(sess);
    useDocument.getState().openDocument(fresh, { analysisId: slot.id });
    useSweepStore.getState().hydrate(fresh, {
      sessionId: sess.session_id,
      order: orderTrials,
      refuse: proposal?.proposed ?? fresh.blank_scan?.blank ?? [],
    });
    // No slot ⇒ autosave cannot run. Say so loudly (W4) rather than letting judgements no-op silently.
    if (slot.id == null) useDocument.getState().markAutosaveUnavailable(slot.reason);
    setOpenPhase(null);
    setStep('range'); // R4.5 — opening a dataset NAVIGATES to Range; no in-place result block.
  }, []);

  useEffect(() => {
    if (!key) return;
    const token = ++openToken.current;
    setSession(null);
    useSweepStore.getState().reset();
    useDocument.getState().reset();
    void (async () => {
      try {
        await openDatasetByKey(key, token);
      } catch (e) {
        if (token === openToken.current) {
          setOpenPhase(null);
          setError(errMsg(e));
        }
      }
    })();
    return () => {
      // Invalidate any in-flight open; a later mount re-opens from scratch.
      openToken.current += 1;
    };
  }, [key, openDatasetByKey]);

  // ── the step gate (R4.3). load/range/screen/place/sweep are reachable once a session exists; mosaic
  //    needs something placed. reachable = count of steps reachable from the start (a step at index ≥
  //    reachable is LOCKED). With a session but nothing placed: Sweep REACHABLE, Mosaic LOCKED. ───────
  const placed = doc ? anyPlaced(doc.tiles, order) : false;
  const reachable = !sessionId ? 1 : placed ? 6 : 5;

  const go = useCallback(
    (target: MosaicStepId): void => {
      if (STEP_INDEX[target] >= reachable) {
        toast.push('Finish the step before it first.', { tone: 'default' });
        return;
      }
      setStep(target);
    },
    [reachable, toast],
  );

  // ── Load-step delegates (the shell owns the session lifecycle) ─────────────────────────────────────
  const openDirectory = useCallback(async (dir: string): Promise<void> => {
    const listing = await scanDatasets({ root: dir, depth: 3, remember: true });
    const ds =
      listing.datasets.find((d) => d.path === dir) ?? listing.datasets[0] ?? null;
    if (!ds) throw new Error('no dataset found in that folder.');
    const token = ++openToken.current;
    await openDatasetByKey(ds.key, token);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadProject = useCallback(async (): Promise<void> => {
    const path = await pickOpenFilePath({
      title: 'Load a project…',
      filters: ['Camea project (*.camea.json)'],
    });
    if (!path) return;
    const res = await loadDocument({ path });
    const loaded = res.doc as MosaicDocument;
    const sess = res.session ?? null;
    const sid = sess?.session_id ?? useSweepStore.getState().sessionId;
    if (sess) setSession(sess);
    // ADOPT the analysis this project belongs to so the crash-net (R29) resumes routing to its slot.
    const slot = await adoptAnalysisSlot(loaded.id);
    useDocument.getState().openDocument(loaded, { path, analysisId: slot.id });
    useSweepStore.getState().hydrate(loaded, { sessionId: sid ?? null });
    if (slot.id == null) useDocument.getState().markAutosaveUnavailable(slot.reason);
    const c = useSweepStore.getState().counts();
    toast.push(`Resumed — ${c.anchored} anchored, ${c.excluded} excluded.`, { tone: 'good' });
    setStep('range');
     
  }, [toast]);

  const tileSrc = useCallback(
    (trial: number): string =>
      session && sessionId ? tilePngUrl(sessionId, trial, cacheBuster(session)) : '',
    [session, sessionId],
  );

  return (
    <div className={styles.feature} data-testid="wizard">
      <div className={styles.header}>
        <WizardNav
          current={step}
          reachable={reachable}
          onStep={(id, locked) => {
            if (locked) toast.push('Finish the step before it first.', { tone: 'default' });
            else setStep(id);
          }}
        />
      </div>

      {error && (
        <div className={styles.error} role="alert">
          Could not open the dataset: {error}
        </div>
      )}

      <div className={styles.body} data-step={step}>
        {step === 'load' && (
          <LoadStep
            onNavigate={go}
            onOpenDirectory={openDirectory}
            onLoadProject={loadProject}
            openPhase={openPhase}
          />
        )}
        {step === 'range' && <RangeStep onNavigate={go} />}
        {step === 'screen' && <ScreenStep onNavigate={go} />}
        {step === 'place' && <PlaceStep onNavigate={go} />}
        {step === 'sweep' && <SweepStep tileSrc={tileSrc} onNavigate={go} />}
        {step === 'mosaic' && <MosaicStep />}
      </div>
    </div>
  );
}
