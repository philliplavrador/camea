// ─────────────────────────────────────────────────────────────────────────────────────────────
// RECOMPUTE — ⭐ the tool the user reaches for (docs/BEHAVIOUR.md, the Recompute ruling).
//
// After anchoring the tiles he trusts, one press re-places every OTHER tile against their combined
// composite: `POST /api/mosaic/recompute` (a 202 job — `recheck`'s per-target `match_anchor` loop, but
// it WRITES). The job result is the transformed DOCUMENT; adopting it re-hydrates the sweep exactly as
// seeding a build does, then flows through the store's persistence hook (auto-save picks it up).
//
// 🔴 It never moves an anchored / hand-placed / excluded tile, and NOTHING is auto-anchored (I3): every
// re-placed tile lands `unverified`. A tile with no measurable overlap is left where it was. The loop is
// anchor → recompute → verify → anchor more → recompute.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { useEffect, useMemo, useState } from 'react';
import { useSweepStore } from '../../store';
import { startRecompute, useJob, useStopJob } from '../../../../api';
import type { MosaicDocument, RecomputeResult } from '../../../../api';
import { useToast } from '../../../../app';
import { Panel, Button, Progress } from '../../../../design';
import styles from './RecomputePanel.module.css';

export function RecomputePanel() {
  const doc = useSweepStore((s) => s.doc);
  const order = useSweepStore((s) => s.order);
  const toast = useToast();
  const stopJob = useStopJob();

  // ⏱️ R48 — the job is WATCHED, not just awaited: `useJob` owns the ticking countdown (R8) and the
  // elapsed clock, so this panel renders a real bar with a real time instead of a 5 px green meter
  // and a button caption. The imperative `pollJobUntilDone` it replaced threw both away.
  const [starting, setStarting] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useJob(jobId);
  const running = jobId != null && !job.isTerminal;
  const busy = starting || running;

  // The frozen reference (anchored) and what a recompute would re-place (everything else that is not
  // hand-placed or excluded). Mirrors the server's target rule, so the counts are honest.
  const { nRef, nTargets } = useMemo(() => {
    const tiles = doc?.tiles ?? {};
    let ref = 0;
    let targets = 0;
    for (const t of order) {
      const tl = tiles[String(t)];
      if (!tl) continue;
      if (tl.state === 'anchored') ref++;
      else if (tl.state !== 'excluded' && !tl.human) targets++;
    }
    return { nRef: ref, nTargets: targets };
  }, [doc, order]);

  /**
   * ⏱️ R48.9 — **the wait ends OUT LOUD, including badly.** Every terminal state says something: a
   * failure, a Stop, a finished run that carried no document, and the good case's summary. A panel
   * whose bar simply vanishes leaves the user unable to tell "done" from "gave up".
   */
  useEffect(() => {
    if (!jobId || !job.isTerminal) return;
    const finished = job.job;
    setJobId(null);
    if (job.state === 'failed') {
      toast.push(`Recompute failed${job.error?.message ? ` — ${job.error.message}` : '.'}`, {
        tone: 'danger',
      });
      return;
    }
    if (job.state !== 'done') {
      toast.push('Recompute stopped — nothing moved.', { tone: 'default' });
      return;
    }
    const result = finished?.result;
    if (!result || result.kind !== 'recompute') {
      toast.push('Recompute finished but returned no document.', { tone: 'danger' });
      return;
    }
    // Adopt the transformed document — re-hydrate the sweep spine and push it through the store's
    // persistence hook (the same seam an A/E judgement uses), so auto-save keeps it.
    const s = useSweepStore.getState();
    s.hydrate(result.doc, { sessionId: s.sessionId });
    useSweepStore.getState().hooks.onChange?.(result.doc, { judgement: false });
    toast.push(summarise(result), { tone: 'good' });
  }, [jobId, job.isTerminal, job.state, job.job, job.error, toast]);

  async function run(): Promise<void> {
    const cur = useSweepStore.getState().doc;
    const sid = useSweepStore.getState().sessionId;
    if (!cur || !sid || busy || nRef === 0) return;
    setStarting(true);
    try {
      const ref = await startRecompute({ session_id: sid, doc: cur as MosaicDocument });
      setJobId(ref.job_id);
    } catch (e) {
      toast.push(`Recompute failed — ${e instanceof Error ? e.message : String(e)}`, {
        tone: 'danger',
      });
    } finally {
      setStarting(false);
    }
  }

  const disabled = busy || nRef === 0;

  return (
    <Panel
      title="Recompute"
      help="Freeze the tiles you've anchored and re-place every other tile against their combined composite. Anchor the ones you trust, recompute, verify, then anchor more and recompute again. It never moves an anchored, hand-placed, or excluded tile; a tile with no overlap is left where it is; nothing is ever auto-anchored."
      className={styles.panel}
    >
      <div data-testid="recompute-panel">
        <p className={styles.lead} data-testid="recompute-summary">
          <strong>{nRef}</strong> anchored → re-place <strong>{nTargets}</strong>
        </p>
        {/* ⛔ The job's narration no longer hijacks the caption (R48.6): the button says what it does,
            and the bar below says what is happening. */}
        <Button
          variant="primary"
          size="sm"
          block
          data-testid="recompute-btn"
          onClick={() => void run()}
          disabled={disabled}
        >
          Recompute
        </Button>
        {nRef === 0 && (
          <p className={styles.hint} data-testid="recompute-hint">
            Anchor a tile you trust first.
          </p>
        )}
        {busy && (
          <Progress
            className={styles.progress}
            compact
            data-testid="recompute-progress"
            label={job.job?.said_as || 'Re-placing the tiles you have not anchored'}
            pct={job.pct}
            etaText={job.etaText}
            elapsedText={job.elapsedText}
            phase={job.phase}
            message={job.message}
            onStop={
              running && jobId && (job.job?.cancellable ?? true)
                ? () => void stopJob(jobId)
                : undefined
            }
          />
        )}
      </div>
    </Panel>
  );
}

function summarise(rc: RecomputeResult): string {
  const anchors = `${rc.n_reference} anchor${rc.n_reference === 1 ? '' : 's'}`;
  const left = rc.n_unmeasurable ? `, ${rc.n_unmeasurable} left (no overlap)` : '';
  return `Recomputed against ${anchors} — ${rc.n_placed} re-placed${left}.`;
}
