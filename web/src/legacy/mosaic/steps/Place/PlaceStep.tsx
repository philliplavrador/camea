// ─────────────────────────────────────────────────────────────────────────────────────────────
// STEP 4 · PLACE — "run the solver."  (docs/BEHAVIOUR.md §2 Place, R8, R26, R27, R35, W9.)
//
// The one big Run, an honest cost line, and a JOB with a TICKING ETA that never freezes (R8 — the whole
// countdown lives in `useJob`; this screen only renders `etaText`). After the build the server SEEDS it
// onto the working document (R26 — anchored/human tiles are kept, the rest is translated around them),
// and a "go look here first" worklist appears — which is NOT a verdict, and is blind to pass 1 (W9).
//
// ⛔ NO DATASET KNOWLEDGE (HARD RULE 3). `trials` is the document's ACTIVE list (everything the user has
//    not excluded — R35); `pass_split` is the value already on the document (Range detected it); nothing
//    here names a trial, a count, or an exclusion.
//
// `Skip — place by hand` is DESTRUCTIVE, OR NOTHING (R27): it discards every machine position and the
// build after a confirm that names the count. It never launders a seeded build into an "independent
// ground truth".
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { useEffect, useRef, useState } from 'react';
import {
  startBuild,
  seedBuild,
  discardMachine,
  getMachineEvidence,
  cancelJob,
  useJob,
  useSession,
} from '../../../../api';
import type { BuildConfig, BuildResult, MosaicDocument } from '../../../../api';
import { useSweepStore } from '../../store';
import { useDocument } from '../../../../store/documentStore';
import { Button, Toggle, Help, Panel, LiveWarning, Badge } from '../../../../design';
import type { WizardStepProps } from '../types';
import shell from '../step.module.css';
import styles from './PlaceStep.module.css';

/**
 * The Place step. It reads the working document from the sweep store (the single source of truth across
 * the wizard) and, on a finished build, SEEDS the result onto that document (server-side — R26) before
 * asking the shell to move the user on.
 */
export type PlaceStepProps = WizardStepProps;

interface AdvancedCfg {
  pass_split?: string;
  anchor_ncc?: string;
  split_px?: string;
  look?: string;
  min_side?: string;
  t27_conf?: string;
  t27_run_conf?: string;
}

function errMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/** Collect the Advanced knobs into a BuildConfig, or null when none is set (the one-button path). */
function assembleConfig(c: AdvancedCfg): BuildConfig | null {
  const n = (s?: string): number | null => {
    if (s == null || s.trim() === '') return null;
    const v = Number(s);
    return Number.isFinite(v) ? v : null;
  };
  const cfg: BuildConfig = {};
  let any = false;
  const ps = n(c.pass_split);
  if (ps !== null) {
    cfg.pass_split = ps;
    any = true;
  }
  const an = n(c.anchor_ncc);
  if (an !== null) {
    cfg.anchor_ncc = an;
    any = true;
  }
  const sp = n(c.split_px);
  if (sp !== null) {
    cfg.split_px = sp;
    any = true;
  }
  const lk = n(c.look);
  if (lk !== null) {
    cfg.look = lk;
    any = true;
  }
  const ms = n(c.min_side);
  if (ms !== null) {
    cfg.min_side = ms;
    any = true;
  }
  const tc = n(c.t27_conf);
  const trc = n(c.t27_run_conf);
  if (tc !== null || trc !== null) {
    const t27: NonNullable<BuildConfig['t27']> = {};
    if (tc !== null) t27.conf = tc;
    if (trc !== null) t27.run_conf = trc;
    cfg.t27 = t27;
    any = true;
  }
  return any ? cfg : null;
}

/**
 * Adopt a server-transformed document (a seeded build, or a Skip's discard) as the new working document.
 * A build is a fresh baseline, so the sweep spine is RE-HYDRATED (cursor / evidence / undo reset, the
 * blank list re-read); the change is then pushed through the store's own persistence hook — the same
 * seam an A/E judgement uses (store/types.ts `SweepHooks`) — so the crash-net and Save pick it up.
 */
function applyDoc(next: MosaicDocument): void {
  const s = useSweepStore.getState();
  s.hydrate(next, { sessionId: s.sessionId });
  useSweepStore.getState().hooks.onChange?.(next, { judgement: false });
}

const ADVANCED_KNOBS: Array<{
  key: keyof AdvancedCfg;
  label: string;
  help: string;
  step?: string;
}> = [
  {
    key: 'pass_split',
    label: 'pass_split',
    help: 'The last trial of pass 1. Defaults to the detected value; overriding it is rarely right.',
  },
  {
    key: 'anchor_ncc',
    label: 'anchor_ncc',
    help: 'The NCC a pass-2 tile must reach to be trusted as an anchor in the solve.',
    step: '0.01',
  },
  {
    key: 'split_px',
    label: 'split_px',
    help: 'The maximum residual, in px, before the solver splits a chain.',
  },
  {
    key: 'look',
    label: 'look',
    help: 'How many neighbours back the solver looks when chaining a tile.',
  },
  {
    key: 'min_side',
    label: 'min_side',
    help: 'The minimum overlap side, in px, for a pair to be trusted.',
  },
  { key: 't27_conf', label: 't27.conf', help: "t27's per-tile confidence gate.", step: '0.01' },
  {
    key: 't27_run_conf',
    label: 't27.run_conf',
    help: "t27's per-run confidence gate.",
    step: '0.01',
  },
];

export function PlaceStep({ onNavigate }: PlaceStepProps) {
  const doc = useSweepStore((s) => s.doc);
  const sessionId = useSweepStore((s) => s.sessionId);
  const session = useSession(sessionId);

  const [useCache, setUseCache] = useState(true);
  const [jobId, setJobId] = useState<string | null>(null);
  const [buildResult, setBuildResult] = useState<BuildResult | null>(null);
  const [busy, setBusy] = useState(false); // seeding / discarding
  const [error, setError] = useState<string | null>(null);
  const [cfg, setCfg] = useState<AdvancedCfg>({});

  const job = useJob(jobId);
  const running = jobId != null && !job.isTerminal;
  const seededFor = useRef<string | null>(null);

  const gpu = session.status === 'ready' ? session.session.gpu : null;

  // When the build job finishes, seed it onto the document (server-side — R26) and surface the worklist.
  useEffect(() => {
    if (!jobId || !job.isTerminal) return;
    if (job.state === 'failed') {
      setError(job.error?.message ?? 'The build failed.');
      setJobId(null);
      return;
    }
    if (job.state !== 'done') {
      setJobId(null); // cancelled
      return;
    }
    const result = job.job?.result;
    if (!result || result.kind !== 'build') return;
    if (seededFor.current === result.build_id) return;
    seededFor.current = result.build_id;

    void (async () => {
      setBusy(true);
      setError(null);
      try {
        const current = useSweepStore.getState().doc;
        if (!current) return;
        const seeded = await seedBuild({ doc: current, build_id: result.build_id });
        applyDoc(seeded.doc);
        setBuildResult(result);
      } catch (e) {
        setError(errMessage(e));
      } finally {
        setBusy(false);
        setJobId(null);
      }
    })();
  }, [jobId, job.isTerminal, job.state, job.job, job.error]);

  async function run(): Promise<void> {
    if (!doc || !sessionId || running) return;
    setError(null);
    setBuildResult(null);
    seededFor.current = null;
    const order = useSweepStore.getState().order;
    const active = useSweepStore.getState().activeTrials();
    // pass_split is the value the document already carries (Range detected it). The fallback is derived
    // from the run's own order — never a hard-coded literal (HARD RULE 3).
    const passSplit = doc.pass_split ?? (order.length ? order[order.length - 1] : 0);
    try {
      const ref = await startBuild({
        session_id: sessionId,
        trials: active,
        pass_split: passSplit,
        config: assembleConfig(cfg),
        use_cache: useCache,
        analysis_id: useDocument.getState().analysisId ?? null,
      });
      setJobId(ref.job_id);
    } catch (e) {
      setError(errMessage(e));
    }
  }

  async function cancel(): Promise<void> {
    if (!jobId) return;
    try {
      await cancelJob(jobId);
    } catch {
      /* cancelling a build that already finished is a no-op, not an error to shout about */
    }
    setJobId(null);
  }

  async function skip(): Promise<void> {
    const current = useSweepStore.getState().doc;
    if (!current || busy || running) return;
    let n = 0;
    try {
      n = (await getMachineEvidence(current)).n_machine_tiles;
    } catch {
      /* fall back to a generic confirm */
    }
    const ok = window.confirm(
      n > 0
        ? `Skip discards ${n} machine-placed position${n === 1 ? '' : 's'} and the build. You then place every tile by hand. Continue?`
        : 'Skip — place every tile by hand from scratch. Continue?',
    );
    if (!ok) return;
    setBusy(true);
    setError(null);
    try {
      const res = await discardMachine(current);
      applyDoc(res.doc);
      setBuildResult(null);
      onNavigate('sweep');
    } catch (e) {
      setError(errMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const costText = gpu?.note
    ? gpu.note
    : gpu?.available
      ? '~3 min cold, ~25 s cached. The result is identical.'
      : '~8–10 min. The result is identical.';

  return (
    <div className={shell.pane} data-testid="place">
      <header className={shell.head}>
        <h1 className={shell.h1}>Place the tiles</h1>
        <p className={styles.cost} data-testid="place-cost">
          {costText}
        </p>
        <div className={styles.gpu} data-testid="place-gpu">
          {gpu?.available ? (
            <Badge state="gpu">GPU · {gpu.name ?? gpu.backend}</Badge>
          ) : (
            <span className={styles.noGpu}>
              No GPU
              {gpu?.reason ? ` — ${gpu.reason}` : ''}
              <Help body="A build runs on the CPU when there is no GPU. The result is identical; it is only slower. A CUDA DLL-path problem is fixable and is not the same thing as no card." />
            </span>
          )}
        </div>
      </header>

      {error && (
        <LiveWarning variant="loud" className={styles.block}>
          <strong>Build error.</strong> {error}
        </LiveWarning>
      )}

      {!running && !busy && (
        <div className={styles.controls}>
          <Button
            variant="primary"
            size="lg"
            onClick={() => void run()}
            data-testid="place-run"
            disabled={!doc || !sessionId}
          >
            {buildResult ? 'Run again' : 'Run'}
          </Button>
          <span className={styles.cacheRow} data-testid="place-use-cache">
            <Toggle checked={useCache} onChange={setUseCache}>
              use cache
            </Toggle>
            <Help body="A SPEED switch, not a correctness one: warm ≈ 25 s vs cold ≈ 3 min. The cache filename carries a hash of the trial list + config, so a mismatch is refused, not repaired — it cannot serve a stale answer for a different input." />
          </span>
          <Button variant="ghost" onClick={() => void skip()} data-testid="place-skip">
            Skip — place by hand
          </Button>
        </div>
      )}

      {(running || busy) && (
        <Panel title="Building" className={styles.progress}>
          <div className={styles.barWell}>
            <div
              className={styles.bar}
              data-testid="place-progress-bar"
              style={{ width: `${Math.max(2, Math.min(100, job.pct ?? 0))}%` }}
            />
          </div>
          <div className={styles.progressRow}>
            <span className={styles.phase} data-testid="place-phase">
              {job.phase ?? (busy ? 'seeding' : 'starting…')}
              {job.phaseIndex != null && job.nPhases != null
                ? ` · ${job.phaseIndex + 1}/${job.nPhases}`
                : ''}
            </span>
            {running && (
              <span className={styles.eta} data-testid="place-eta">
                {job.etaText ?? ''}
              </span>
            )}
            {running && (
              <Button
                variant="danger"
                size="sm"
                onClick={() => void cancel()}
                data-testid="place-cancel"
              >
                Cancel
              </Button>
            )}
          </div>
          {job.message && <div className={styles.msg}>{job.message}</div>}
          <pre className={styles.log} data-testid="place-log">
            {(job.logTail.length ? job.logTail : ['…']).join('\n')}
          </pre>
        </Panel>
      )}

      {buildResult && <Worklist result={buildResult} onGoTo={() => onNavigate('sweep')} />}

      <details className={styles.advanced} data-testid="place-advanced">
        <summary className={styles.advSummary}>Advanced</summary>
        <div className={styles.advBody}>
          <p className={styles.advNote}>
            Off the validated path. The shipped 312/312 build used the defaults.
          </p>
          <div className={styles.knobs}>
            {ADVANCED_KNOBS.map((k) => (
              <label key={k.key} className={styles.knob}>
                <span className={styles.knobLabel}>
                  {k.label}
                  <Help body={k.help} />
                </span>
                <input
                  className={styles.knobInput}
                  type="number"
                  step={k.step ?? '1'}
                  value={cfg[k.key] ?? ''}
                  placeholder="default"
                  onChange={(e) => setCfg((c) => ({ ...c, [k.key]: e.target.value }))}
                />
              </label>
            ))}
          </div>
        </div>
      </details>

      <div className={shell.stepnav}>
        <Button variant="ghost" onClick={() => onNavigate('screen')}>
          ← Screen
        </Button>
        <span className={shell.spacer} />
        <Button variant="primary" onClick={() => onNavigate('sweep')} disabled={!buildResult}>
          Sweep →
        </Button>
      </div>
    </div>
  );
}

// ── The "go look here first" worklist (BEHAVIOUR §2 Place, W9) ────────────────────────────────────
interface WorklistRow {
  trial: number;
  anchor_residual_px: number | null;
  anchor_ncc: number | null;
  run_margin: number | null;
  pass: number;
}

function Worklist({ result, onGoTo }: { result: BuildResult; onGoTo?: () => void }) {
  const rows: WorklistRow[] = Object.entries(result.per_tile).map(([t, ev]) => ({
    trial: Number(t),
    anchor_residual_px: ev.anchor_residual_px ?? null,
    anchor_ncc: ev.anchor_ncc ?? null,
    run_margin: ev.run_margin ?? null,
    pass: ev.pass,
  }));

  const byResidual = rows
    .filter((r) => r.anchor_residual_px != null)
    .sort((a, b) => (b.anchor_residual_px ?? 0) - (a.anchor_residual_px ?? 0))
    .slice(0, 12);
  const chosen = new Set(byResidual.map((r) => r.trial));
  const thin = rows.filter(
    (r) => r.run_margin != null && r.run_margin < 0.1 && !chosen.has(r.trial),
  );
  const worklist = [...byResidual, ...thin];

  // Pass-1 tiles have NO per-tile confidence — say so, loudly. The absence of a flag is not a clean bill.
  const hasPass1 = result.trials.some((t) => t <= result.pass_split);

  function goTo(trial: number): void {
    useSweepStore.getState().setCursor(trial);
    onGoTo?.();
  }

  return (
    <Panel
      title="Look here first"
      help="Sorted by anchor residual — it is a 'go look', never a verdict. On a ground-truth-perfect build the automatic quality score flags 11 tiles and all 11 are false positives, so this list is deliberately not built from it."
      className={styles.worklist}
    >
      <div className={styles.summary}>
        <span>
          <b>{result.n_placed}</b> placed
        </span>
        <span>
          took <b>{result.seconds.toFixed(1)} s</b>
        </span>
        <span className={styles.buildId}>build {result.build_id.slice(0, 10)}</span>
      </div>

      {hasPass1 && (
        <div data-testid="warn-pass1-no-confidence" className={styles.block}>
          <LiveWarning variant="info">
            <strong>Pass-1 tiles have no per-tile confidence.</strong> They cannot appear in this
            list at all. The absence of a warning is not a clean bill of health.
          </LiveWarning>
        </div>
      )}

      <ul className={styles.wlList} data-testid="place-worklist">
        {worklist.length === 0 && <li className={styles.wlEmpty}>Nothing flagged.</li>}
        {worklist.map((r) => (
          <li key={r.trial}>
            <button
              type="button"
              className={styles.wlItem}
              data-testid="place-worklist-item"
              data-trial={r.trial}
              onClick={() => goTo(r.trial)}
            >
              <span className={styles.wlTrial}>#{r.trial}</span>
              {r.anchor_residual_px != null && (
                <span className={styles.wlNum}>{r.anchor_residual_px.toFixed(1)} px</span>
              )}
              {r.anchor_ncc != null && (
                <span className={styles.wlNum}>NCC {r.anchor_ncc.toFixed(3)}</span>
              )}
              {r.run_margin != null && r.run_margin < 0.1 && (
                <span className={styles.wlThin}>thin {r.run_margin.toFixed(3)}</span>
              )}
              <span className={styles.wlPass}>pass {r.pass}</span>
            </button>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
