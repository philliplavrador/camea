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

import { useMemo, useState } from 'react';
import { useSweepStore } from '../../store';
import { startRecompute, pollJobUntilDone } from '../../../../api';
import type { RecomputeResult, MosaicDocument } from '../../../../api';
import { useToast } from '../../../../app';
import { Panel, Button } from '../../../../design';
import styles from './RecomputePanel.module.css';

export function RecomputePanel() {
  const doc = useSweepStore((s) => s.doc);
  const order = useSweepStore((s) => s.order);
  const toast = useToast();

  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<{ pct: number | null; message: string | null }>({
    pct: null,
    message: null,
  });

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

  async function run(): Promise<void> {
    const cur = useSweepStore.getState().doc;
    const sid = useSweepStore.getState().sessionId;
    if (!cur || !sid || busy || nRef === 0) return;
    setBusy(true);
    setProgress({ pct: 0, message: 'Recomputing…' });
    try {
      const ref = await startRecompute({ session_id: sid, doc: cur as MosaicDocument });
      const finished = await pollJobUntilDone(ref.job_id, {
        onUpdate: (j) => setProgress({ pct: j.pct ?? null, message: j.message ?? null }),
      });
      const result = finished.result;
      const rc = result && result.kind === 'recompute' ? (result as RecomputeResult) : null;
      if (rc) {
        // Adopt the transformed document — re-hydrate the sweep spine and push it through the store's
        // persistence hook (the same seam an A/E judgement uses), so auto-save keeps it.
        const s = useSweepStore.getState();
        s.hydrate(rc.doc, { sessionId: s.sessionId });
        useSweepStore.getState().hooks.onChange?.(rc.doc, { judgement: false });
        toast.push(summarise(rc), { tone: 'good' });
      }
    } catch {
      toast.push('Recompute failed.', { tone: 'danger' });
    } finally {
      setBusy(false);
      setProgress({ pct: null, message: null });
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
        <Button
          variant="primary"
          size="sm"
          block
          data-testid="recompute-btn"
          onClick={() => void run()}
          disabled={disabled}
        >
          {busy ? (progress.message ?? 'Recomputing…') : 'Recompute'}
        </Button>
        {nRef === 0 && (
          <p className={styles.hint} data-testid="recompute-hint">
            Anchor a tile you trust first.
          </p>
        )}
        {busy && progress.pct != null && (
          <div className={styles.meter} data-testid="recompute-meter">
            <div
              className={styles.meterFill}
              style={{ width: `${Math.max(0, Math.min(100, progress.pct))}%` }}
            />
          </div>
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
