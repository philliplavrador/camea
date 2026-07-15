import { useEffect, useState } from 'react';
import { useSweepStore, anyPlaced as computeAnyPlaced } from '../../store';
import {
  detectRun,
  getThumbsLayout,
  thumbsPngUrl,
  type RunDetection,
  type ThumbsResponse,
} from '../../../../api';
import { useToast } from '../../../../app';
import { Button, Help } from '../../../../design';
import { patchWorkingDoc } from '../mutate';
import { FactsStrip, Fact } from '../Fact';
import type { RangeStepProps } from '../types';
import shell from '../step.module.css';
import styles from './RangeStep.module.css';

const errMsg = (e: unknown): string => (e instanceof Error ? e.message : String(e));

const GAPS_HELP =
  'Consecutive trials that are NOT one acquisition step apart — because something between them was ' +
  'excluded.\n\nThe serpentine one-step prior does not hold across a gap, so the solver is told about ' +
  'them. Recomputed every time you exclude a tile.';
const APPLY_HELP =
  'Reloading re-scopes the run. Changing lo/hi discards the build, the tone window and the blank scan — ' +
  'they were computed for the old range.';

/**
 * 2 · RANGE — "which trials are the mosaic?" (BEHAVIOUR §2 step 2).
 *
 * A numbers-only facts strip — **Trials · Range · Pass split · Gaps** — every explanation behind its
 * `?` (R4.6). The run and the pass split are MEASURED from the session's timestamps and are shown as
 * VALUES THE USER CAN OVERRIDE — never a hard-coded 166 (I1/R2, the task's core Range requirement).
 * Gaps are LIVE: `none` on a fresh open, and they grow only when the USER excludes a frame (R2.3), read
 * straight off the working document the sweep store maintains.
 */
export function RangeStep({ onNavigate, onApplyRange }: RangeStepProps) {
  const doc = useSweepStore((s) => s.doc);
  const order = useSweepStore((s) => s.order);
  const sessionId = useSweepStore((s) => s.sessionId);
  const setCursor = useSweepStore((s) => s.setCursor);
  const toast = useToast();

  const [detection, setDetection] = useState<RunDetection | null>(null);
  const [thumbs, setThumbs] = useState<ThumbsResponse | null>(null);
  const [lo, setLo] = useState('');
  const [hi, setHi] = useState('');
  const [split, setSplit] = useState('');
  const [applying, setApplying] = useState(false);

  // The run + pass split — a PURE function of the session's inventory (`POST /api/mosaic/run`), not a
  // reload. Fetched once the session is known; re-fetched after an Apply.
  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    detectRun({ session_id: sessionId }).then(
      (d) => {
        if (!cancelled) setDetection(d);
      },
      () => {
        /* the facts fall back to the document's own trial_range / pass_split */
      },
    );
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  // The contact sheet: ONE sprite sheet (`GET /api/sessions/{id}/thumbs.json` + thumbs.png).
  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    getThumbsLayout(sessionId).then(
      (t) => {
        if (!cancelled) setThumbs(t);
      },
      () => {
        /* no contact sheet is a soft failure — the facts and inputs still work */
      },
    );
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  // Seed the override inputs from the detection (and re-seed after a re-detect).
  useEffect(() => {
    if (!detection) return;
    setLo(String(detection.lo));
    setHi(String(detection.hi));
    setSplit(detection.pass_split.value != null ? String(detection.pass_split.value) : '');
  }, [detection]);

  const trialRange = doc?.trial_range ?? (detection ? [detection.lo, detection.hi] : null);
  const rangeText = trialRange ? `${trialRange[0]}–${trialRange[1]}` : '—';
  const trialsN = detection?.n ?? order.length;
  const passSplitValue = detection?.pass_split.value ?? doc?.pass_split ?? null;
  const gaps = doc?.gaps ?? [];
  const gapsText = gaps.length ? gaps.map(([a, b]) => `${a}→${b}`).join(', ') : 'none';

  async function apply() {
    const loN = Number(lo);
    const hiN = Number(hi);
    const splitN = split.trim() === '' ? null : Number(split);
    if (!Number.isFinite(loN) || !Number.isFinite(hiN)) {
      toast.push('lo and hi must be numbers.', { tone: 'danger' });
      return;
    }
    // ⚠️ DESTRUCTIVE when there is work on the canvas — say what dies, in one line, and let him stop.
    if (doc && computeAnyPlaced(doc.tiles, order)) {
      if (!window.confirm('Reloading discards the build and every position in it. Continue?'))
        return;
    }
    setApplying(true);
    try {
      if (onApplyRange) {
        await onApplyRange(loN, hiN, splitN); // the shell re-scopes the session + re-hydrates
        return;
      }
      // Fallback: apply the (client-safe) pass-split override and re-detect the facts. Re-scoping the
      // trial SET (lo/hi) re-hydrates the session — the shell's lifecycle — so note it if it changed.
      if (sessionId) {
        const d = await detectRun({ session_id: sessionId, lo: loN, hi: hiN, pass_split: splitN });
        setDetection(d);
      }
      patchWorkingDoc({ pass_split: splitN });
      void useSweepStore.getState().recomputeGaps();
      const rangeChanged = !!trialRange && (loN !== trialRange[0] || hiN !== trialRange[1]);
      toast.push(
        rangeChanged
          ? 'Pass split applied. Re-open from Load to change the trial range.'
          : 'Pass split applied.',
        { tone: 'good' },
      );
    } catch (e) {
      toast.push(`Apply failed: ${errMsg(e)}`, { tone: 'danger' });
    } finally {
      setApplying(false);
    }
  }

  const sprite = sessionId && thumbs ? thumbsPngUrl(sessionId, thumbs.version) : null;

  return (
    <div className={shell.pane}>
      <header className={shell.head}>
        <h1 className={shell.h1}>Range</h1>
        <p className={shell.lede}>Which trials are the mosaic?</p>
      </header>

      <FactsStrip testid="range-facts">
        <Fact
          label="Trials"
          help={detection?.why ?? ''}
          value={trialsN}
          valueTestid="fact-trials"
        />
        <Fact label="Range" value={rangeText} valueTestid="fact-range" />
        <Fact
          label="Pass split"
          help={detection?.pass_split.why ?? ''}
          value={passSplitValue ?? '—'}
          valueTestid="fact-passsplit"
          sub={
            detection ? (
              <>
                {detection.pass_split.n_pass1} &middot; {detection.pass_split.n_pass2}
              </>
            ) : null
          }
        />
        <Fact
          label="Gaps"
          help={GAPS_HELP}
          value={<span className={styles.gaps}>{gapsText}</span>}
          valueTestid="fact-gaps"
          tone={gaps.length ? 'warn' : undefined}
        />
      </FactsStrip>

      <div className={shell.inline}>
        <label className={shell.field}>
          <span className={shell.fieldLabel}>lo</span>
          <input
            className={`${shell.input} ${shell.num}`}
            type="number"
            value={lo}
            onChange={(e) => setLo(e.target.value)}
            data-testid="range-lo"
          />
        </label>
        <label className={shell.field}>
          <span className={shell.fieldLabel}>hi</span>
          <input
            className={`${shell.input} ${shell.num}`}
            type="number"
            value={hi}
            onChange={(e) => setHi(e.target.value)}
            data-testid="range-hi"
          />
        </label>
        <label className={shell.field}>
          <span className={shell.fieldLabel}>pass split</span>
          <input
            className={`${shell.input} ${shell.num}`}
            type="number"
            value={split}
            onChange={(e) => setSplit(e.target.value)}
            data-testid="range-split"
          />
        </label>
        <Button onClick={apply} disabled={applying} data-testid="range-apply">
          Apply
        </Button>
        <span className={styles.applyHelp}>
          <Help body={APPLY_HELP} />
        </span>
      </div>

      <h2 className={shell.h2}>Contact sheet</h2>
      {sprite && thumbs ? (
        <div className={styles.sheetWrap}>
          <div className={styles.sheet} data-testid="contact-sheet">
            {thumbs.trials.map((t, i) => {
              const col = i % thumbs.grid;
              const row = Math.floor(i / thumbs.grid);
              return (
                <button
                  key={t}
                  type="button"
                  className={styles.cell}
                  data-testid="contact-cell"
                  data-trial={t}
                  title={`trial ${t}`}
                  onClick={() => {
                    setCursor(t);
                    onNavigate('sweep');
                  }}
                  style={{
                    width: thumbs.cell,
                    height: thumbs.cell,
                    backgroundImage: `url(${sprite})`,
                    backgroundPosition: `-${col * thumbs.cell}px -${row * thumbs.cell}px`,
                  }}
                >
                  <span className={styles.cellT}>{t}</span>
                </button>
              );
            })}
          </div>
        </div>
      ) : (
        <div className={shell.muted} data-testid="contact-sheet">
          no contact sheet
        </div>
      )}

      <div className={shell.stepnav}>
        <Button variant="ghost" onClick={() => onNavigate('load')}>
          &larr; Load
        </Button>
        <span className={shell.spacer} />
        <Button variant="primary" onClick={() => onNavigate('screen')}>
          Screen the frames &rarr;
        </Button>
      </div>
    </div>
  );
}
