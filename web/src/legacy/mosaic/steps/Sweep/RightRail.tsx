// The sweep's RIGHT rail (BEHAVIOUR §2 Sweep): the Evidence for the tile under judgement (NCC + meter,
// margin, anchors, composite, overlap, took), the ranked Alternatives (numbered #1–#9 — R12.3), and the
// Staleness panel (W8 — a re-check that is allowed to say NO, R25). Every number is a measurement; a
// missing one is an em dash, never a fabricated zero.

import { useEffect, useMemo, useState } from 'react';
import { useSweepStore, fieldSignature } from '../../store';
import { startRecheck, useJob, useStopJob } from '../../../../api';
import type { RecheckRow, MosaicDocument } from '../../../../api';
import { Panel, Progress } from '../../../../design';
import { RecomputePanel } from './RecomputePanel';
import { fmtNcc, fmtMargin, fmtInt } from './format';
import styles from './RightRail.module.css';

export interface RightRailProps {
  onGoToTrial: (trial: number) => void;
}

export function RightRail({ onGoToTrial }: RightRailProps) {
  const doc = useSweepStore((s) => s.doc);
  const order = useSweepStore((s) => s.order);
  const cursor = useSweepStore((s) => s.cursor);
  const altsOn = useSweepStore((s) => s.altsOn);
  const evidence = useSweepStore((s) => s.evidence);

  const tile = cursor != null && doc ? doc.tiles[String(cursor)] : undefined;
  const ev = cursor != null ? evidence[String(cursor)] : undefined;

  const ncc = tile?.ncc ?? ev?.result.best?.ncc ?? null;
  const margin = tile?.margin ?? ev?.result.margin ?? null;
  const nAnchors = tile?.n_anchors ?? ev?.result.n_anchors ?? null;
  const overlap = tile?.npix ?? ev?.result.best?.npix ?? null;
  const composite = ev?.result.composite ?? null;

  const fieldNow = useMemo(
    () => (doc && cursor != null ? fieldSignature(doc.tiles, order, cursor) : ''),
    [doc, order, cursor],
  );
  const earlierField = !!ev && ev.field !== fieldNow;

  const took = ev
    ? `${Math.round(ev.result.elapsed_ms)} ms${ev.result.cached ? ' · cached' : ''}${earlierField ? ' · AN EARLIER ANCHOR FIELD' : ''}`
    : '—';

  const machineNote = machineNoteFor(tile);

  const meterPct = ncc != null && Number.isFinite(ncc) ? Math.max(0, Math.min(100, ncc * 100)) : 0;

  // ── staleness (W8) ───────────────────────────────────────────────────────────────────────────────
  const staleTrials = useMemo(
    () => (doc ? order.filter((t) => doc.tiles[String(t)]?.stale) : []),
    [doc, order],
  );
  const [disagree, setDisagree] = useState<RecheckRow[] | null>(null);
  const [recheckNote, setRecheckNote] = useState<string | null>(null);
  // ⏱️ R48 — the re-check was a DISABLED BUTTON CAPTION and nothing else: it was polled with no
  // `onUpdate`, so every one of its updates was discarded on arrival. 120 stale tiles is ~2 minutes
  // behind the word "Re-checking…". `useJob` watches it instead, which is also where R8's ticking
  // countdown comes from.
  const [starting, setStarting] = useState(false);
  const [recheckJobId, setRecheckJobId] = useState<string | null>(null);
  const recheckJob = useJob(recheckJobId);
  const recheckRunning = recheckJobId != null && !recheckJob.isTerminal;
  const recheckBusy = starting || recheckRunning;
  const stopJob = useStopJob();

  /** R48.9 — the wait ends out loud: cleared flags applied, or a sentence saying why nothing moved. */
  useEffect(() => {
    if (!recheckJobId || !recheckJob.isTerminal) return;
    const finished = recheckJob.job;
    setRecheckJobId(null);
    if (recheckJob.state === 'failed') {
      setRecheckNote(
        `The re-check failed${recheckJob.error?.message ? ` — ${recheckJob.error.message}` : '.'} Nothing was cleared.`,
      );
      return;
    }
    if (recheckJob.state !== 'done') {
      setRecheckNote('The re-check was stopped — nothing was cleared.');
      return;
    }
    const result = finished?.result;
    if (!result || result.kind !== 'recheck') {
      setRecheckNote('The re-check finished but returned nothing.');
      return;
    }
    // R25/W8 — the re-check returns the flags it is ALLOWED to clear; apply them so the "N stale" panel
    // and the dashed chips actually clear. Disagreeing tiles stay flagged ("go and look").
    if (result.cleared.length > 0) useSweepStore.getState().clearStale(result.cleared);
    setRecheckNote(null);
    setDisagree(result.disagree);
  }, [recheckJobId, recheckJob.isTerminal, recheckJob.state, recheckJob.job, recheckJob.error]);

  async function runRecheck(): Promise<void> {
    const cur = useSweepStore.getState().doc;
    const sid = useSweepStore.getState().sessionId;
    if (!cur || !sid || recheckBusy) return;
    setDisagree(null);
    setRecheckNote(null);
    setStarting(true);
    try {
      const ref = await startRecheck({
        session_id: sid,
        doc: cur as MosaicDocument,
        tolerance_px: 5,
      });
      setRecheckJobId(ref.job_id);
    } catch (e) {
      setRecheckNote(
        `The re-check could not start — ${e instanceof Error ? e.message : String(e)}`,
      );
    } finally {
      setStarting(false);
    }
  }

  return (
    <aside className={styles.rail} data-testid="right-rail">
      <RecomputePanel />

      <div data-testid="evidence">
        <Panel
          title="Evidence"
          help="What the matcher found for the tile under judgement, measured against the certified anchor field. Judge alignment here and tone on the Mosaic step — the live view is faithful to geometry, not photometry."
          className={styles.panel}
        >
          {tile?.blank && (
            <div className={styles.refused}>REFUSED — blank. The matcher gets no vote here.</div>
          )}
          <div className={styles.evRow}>
            <span className={styles.evLabel}>NCC</span>
            <span className={styles.evVal} data-testid="evidence-ncc">
              {fmtNcc(ncc)}
            </span>
          </div>
          <div className={styles.meter} data-testid="evidence-ncc-meter">
            <div className={styles.meterFill} style={{ width: `${meterPct}%` }} />
          </div>
          <div className={styles.evRow}>
            <span className={styles.evLabel}>margin</span>
            <span className={styles.evVal} data-testid="evidence-margin">
              {fmtMargin(margin)}
            </span>
          </div>
          <div className={styles.evRow}>
            <span className={styles.evLabel}>anchors</span>
            <span className={styles.evVal} data-testid="evidence-anchors">
              {fmtInt(nAnchors)}
            </span>
          </div>
          <div className={styles.evRow}>
            <span className={styles.evLabel}>composite</span>
            <span className={styles.evVal} data-testid="evidence-composite-area">
              {composite ? `${composite.w}×${composite.h}` : '—'}
            </span>
          </div>
          <div className={styles.evRow}>
            <span className={styles.evLabel}>overlap</span>
            <span className={styles.evVal} data-testid="evidence-overlap">
              {overlap != null ? `${fmtInt(overlap)} px` : '—'}
            </span>
          </div>
          <div className={styles.evRow}>
            <span className={styles.evLabel}>took</span>
            <span className={styles.evTook} data-testid="evidence-took">
              {took}
            </span>
          </div>
          <div className={styles.machineNote} data-testid="evidence-machine-note">
            {machineNote}
          </div>
        </Panel>
      </div>

      {altsOn && ev && ev.candidates.length > 0 && (
        <Panel title="Alternatives" className={styles.panel}>
          <ul className={styles.alts} data-testid="alternatives-list">
            {ev.candidates.map((c) => (
              <li key={c.rank}>
                <button
                  type="button"
                  className={styles.altItem}
                  data-testid="alternatives-item"
                  data-rank={c.rank}
                  onClick={() => void useSweepStore.getState().jumpToRank(c.rank)}
                >
                  <span className={styles.altRank}>#{c.rank + 1}</span>
                  <span className={styles.altNcc}>NCC {fmtNcc(c.ncc)}</span>
                </button>
              </li>
            ))}
          </ul>
        </Panel>
      )}

      {staleTrials.length > 0 && (
        <Panel title="Staleness" className={styles.panel}>
          <div data-testid="stale-panel">
            <p className={styles.staleLead} data-testid="warn-stale">
              <strong>{staleTrials.length} stale</strong> — matched against an anchor field that has
              since changed.
            </p>
            <button
              type="button"
              className={styles.smallBtn}
              data-testid="stale-recheck"
              onClick={() => void runRecheck()}
              disabled={recheckBusy}
            >
              Re-check
            </button>
            {recheckBusy && (
              <Progress
                className={styles.recheckProgress}
                compact
                data-testid="stale-recheck-progress"
                label={recheckJob.job?.said_as || 'Re-checking the stale tiles'}
                pct={recheckJob.pct}
                etaText={recheckJob.etaText}
                elapsedText={recheckJob.elapsedText}
                phase={recheckJob.phase}
                message={recheckJob.message}
                onStop={
                  recheckRunning && recheckJobId && (recheckJob.job?.cancellable ?? true)
                    ? () => void stopJob(recheckJobId)
                    : undefined
                }
              />
            )}
            {/* R48.9 — a re-check that ended badly says so, rather than leaving the tile list looking
                as though it had answered. */}
            {recheckNote && (
              <p className={styles.staleLead} data-testid="stale-recheck-note">
                {recheckNote}
              </p>
            )}
            {!recheckBusy && !recheckNote && disagree != null && (
              <p className={styles.staleLead}>
                {disagree.length === 0
                  ? 'All agree within 5 px.'
                  : `${disagree.length} disagree by > 5 px — go and look:`}
              </p>
            )}
            <div className={styles.staleList}>
              {(disagree ? disagree.map((r) => r.trial) : staleTrials).map(
                (trial) => (
                  <button
                    key={trial}
                    type="button"
                    className={styles.smallBtn}
                    data-testid="stale-item"
                    data-trial={trial}
                    onClick={() => onGoToTrial(trial)}
                  >
                    #{trial}
                  </button>
                ),
              )}
            </div>
          </div>
        </Panel>
      )}
    </aside>
  );
}

type TileRec = MosaicDocument['tiles'][string];

function machineNoteFor(tile: TileRec | undefined): string {
  if (!tile) return '—';
  if (tile.diverted) return "At the solver's position — the matcher was refused here.";
  if (tile.machine != null) {
    const moved = tile.moved_px ?? 0;
    if (moved < 0.5) return "At the machine's position, untouched.";
    return `Moved ${Math.round(moved)} px from the machine's answer.`;
  }
  return tile.source ?? '—';
}
