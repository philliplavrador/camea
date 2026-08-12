// ⭐ THE MOSAIC FEATURE — the six-step wizard shell (BEHAVIOUR §2, R4/R5).
//
// This is the seam where every parallel piece meets: the project manager navigates here with a PROJECT
// `:id` (the analysis id); this component loads THAT project's document, opens the SESSION for its
// dataset, hydrates the SWEEP STORE, wires the force-save (Ctrl+S), owns the STEP GATE (R4.3) and mounts
// the active step. The steps hold the JSX; the stores hold the spine; this holds the lifecycle.
//
// (2026-07-24 project-manager reframe: keyed on a PROJECT id, not a dataset key. A project's document
// already exists — the server authored it at creation — so this LOADS it rather than adopt-or-creating.
// Auto-save is the durable save now, so there is no manual save; Ctrl+S just flushes it.)
//
// ⛔ NO DATASET KNOWLEDGE (HARD RULE 3). The only "numbers" here are the session's own trial list — never
// a literal trial, count, range or exclusion.

import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  getDataset,
  openSessionAndWait,
  listSessions,
  getDocument,
  tilePngUrl,
  cacheBuster,
  type SessionResponse,
  type MosaicDocument,
} from '../../api';
import { useToast, useRegisterSaver } from '../../app';
import { mosaicTrials } from './trials';
import { useDocument } from '../../store/documentStore';
import { useSweepStore, anyPlaced } from './store';
import { WizardNav } from './WizardNav';
import { LoadStep } from './steps/Load';
import { RangeStep } from './steps/Range';
import { ScreenStep } from './steps/Screen';
import { PlaceStep } from './steps/Place';
import { SweepStep } from './steps/Sweep';
import { MosaicStep } from './steps/Mosaic';
import { ElectrodesStep } from './steps/Electrodes';
import type { MosaicStepId } from './steps/types';
import styles from './MosaicFeature.module.css';

const STEP_INDEX: Record<MosaicStepId, number> = {
  load: 0,
  range: 1,
  screen: 2,
  place: 3,
  sweep: 4,
  mosaic: 5,
  electrodes: 6,
};

const errMsg = (e: unknown): string => (e instanceof Error ? e.message : String(e));

/** An already-open session for this dataset + trial set, or null. ⭐ Reused so opening a project right
 *  after creating it does NOT load the ~340 MiB frame stack a second time — the new-project flow already
 *  opened one to author the document. Matches on dataset AND the exact loaded trial set (both derive
 *  from the same deterministic `mosaicTrials`, so a match is exact). */
async function findOpenSession(dsKey: string, trials: number[]): Promise<SessionResponse | null> {
  try {
    const { sessions } = await listSessions();
    const key = trials.join(',');
    return sessions.find((s) => s.dataset_key === dsKey && s.trials.join(',') === key) ?? null;
  } catch {
    return null; // listing failed — fall back to opening a fresh session
  }
}

export function MosaicFeature() {
  const { id } = useParams<{ id: string }>();
  const toast = useToast();

  const [step, setStep] = useState<MosaicStepId>('load');
  const [openPhase, setOpenPhase] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [session, setSession] = useState<SessionResponse | null>(null);

  const doc = useSweepStore((s) => s.doc);
  const sessionId = useSweepStore((s) => s.sessionId);
  const order = useSweepStore((s) => s.order);

  // ── wire the persistence seam ONCE: a sweep-store change flows to the document store (marks dirty +
  //    schedules the durable auto-save), and an A/E judgement flushes the durable save immediately. ────
  useEffect(() => {
    useSweepStore.getState().setHooks({
      onChange: (nextDoc, { judgement }) => {
        useDocument.getState().setDocument(nextDoc);
        if (judgement) void useDocument.getState().autosaveNow();
      },
    });
  }, []);

  // ── Ctrl/⌘+S from every screen forces the durable save NOW (auto-save is the save — R5 reframed). The
  //    shell owns the binding; the feature registers WHAT to flush. `autosaveNow` never throws — it
  //    records a loud failure state — so we read that state to report honestly. ───────────────────────
  useRegisterSaver(
    useCallback(async () => {
      const current = useDocument.getState().doc;
      if (!current) {
        toast.push('Nothing to save yet.', { tone: 'default' });
        return;
      }
      await useDocument.getState().autosaveNow();
      const st = useDocument.getState().autosave;
      if (st.state === 'failed') {
        toast.push(`Couldn't save${st.message ? ` — ${st.message}` : ''}`, { tone: 'danger' });
      } else {
        toast.push('Saved.', { tone: 'good' });
      }
    }, [toast]),
  );

  // ── the open lifecycle: load THIS project's document, open its dataset's session, hydrate, land on
  //    Range. The document already exists (authored at creation), so there is no adopt-or-create. ──────
  const openToken = useRef(0);

  const openProjectById = useCallback(async (projectId: string, token: number): Promise<void> => {
    const alive = () => token === openToken.current;
    setError(null);
    setStep('load');
    setOpenPhase('reading project…');

    const res = await getDocument(projectId);
    if (!alive()) return;
    const projectDoc = res.doc as MosaicDocument;
    const dsKey = projectDoc.dataset_key;
    if (!dsKey) throw new Error('this project has no dataset attached.');

    setOpenPhase('reading dataset…');
    let detail;
    try {
      detail = await getDataset(dsKey);
    } catch (e) {
      // Dataset-missing: the folder may have moved or the drive been disconnected. Fail gracefully.
      throw new Error(
        `The dataset for this project can't be found — it may have moved or been disconnected. (${errMsg(e)})`,
      );
    }
    if (!alive()) return;
    const trials = mosaicTrials(detail.summary.shapes ?? [], detail.blocks ?? []);
    if (!trials || trials.length === 0) {
      throw new Error('this dataset has no square (N×N) frames to build a mosaic from.');
    }

    setOpenPhase('opening session…');
    // ⭐ Reuse a session already open for this dataset (e.g. the one the new-project flow just opened to
    // author the document) instead of loading the ~340 MiB frame stack a SECOND time.
    let sess = await findOpenSession(dsKey, trials);
    if (!alive()) return;
    if (!sess) {
      sess = await openSessionAndWait(
        { dataset_key: dsKey, trials },
        { onProgress: (j) => alive() && setOpenPhase(j.phase ?? j.message ?? 'opening…') },
      );
      if (!alive()) return;
    }

    setSession(sess);
    // The document IS the project (its `id` is the analysis id — the autosave slot). Load it clean.
    useDocument.getState().openDocument(projectDoc, { analysisId: projectId });
    useSweepStore.getState().hydrate(projectDoc, { sessionId: sess.session_id });
    setOpenPhase(null);
    setStep('range'); // R4.5 — opening a project NAVIGATES to Range.
  }, []);

  useEffect(() => {
    if (!id) return;
    const token = ++openToken.current;
    setSession(null);
    useSweepStore.getState().reset();
    useDocument.getState().reset();
    void (async () => {
      try {
        await openProjectById(id, token);
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
  }, [id, openProjectById]);

  // ── the step gate (R4.3). load/range/screen/place/sweep are reachable once a session exists; mosaic
  //    and electrodes need something placed (Electrodes unlocks exactly with Mosaic — both read the
  //    placed field). reachable = count of steps reachable from the start (a step at index ≥
  //    reachable is LOCKED). With a session but nothing placed: Sweep REACHABLE, Mosaic LOCKED. ───────
  const placed = doc ? anyPlaced(doc.tiles, order) : false;
  const reachable = !sessionId ? 1 : placed ? 7 : 5;

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
          onStep={(id2, locked) => {
            if (locked) toast.push('Finish the step before it first.', { tone: 'default' });
            else setStep(id2);
          }}
        />
      </div>

      {error && (
        <div className={styles.error} role="alert" data-testid="open-error">
          Could not open the project: {error}
        </div>
      )}

      <div className={styles.body} data-step={step}>
        {step === 'load' && <LoadStep onNavigate={go} openPhase={openPhase} />}
        {step === 'range' && <RangeStep onNavigate={go} />}
        {step === 'screen' && <ScreenStep onNavigate={go} />}
        {step === 'place' && <PlaceStep onNavigate={go} />}
        {step === 'sweep' && <SweepStep tileSrc={tileSrc} onNavigate={go} />}
        {step === 'mosaic' && <MosaicStep />}
        {step === 'electrodes' && <ElectrodesStep tileSrc={tileSrc} />}
      </div>
    </div>
  );
}
