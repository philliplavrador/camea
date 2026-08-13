// ─────────────────────────────────────────────────────────────────────────────────────────────
// THE VIDEOMOSAIC FEATURE — one screen: build, watch, look, take a copy. Mounted at /project/:id by
// the FeatureGate for projects whose feature is "videomosaic".
//
// ⛔ THE SERVER OWNS THE DOCUMENT. The build job updates and SAVES it server-side; the polled result
// (`VideoMosaicBuildResult.doc`) is already durable, so this screen adopts it — it never authors a
// document, never writes a keyframe, never invents a stat.
//
// ⭐ **THERE IS NO FOLDER QUESTION AT ALL** (his ruling 2026-08-10 — R44). The project has been in
// Camea's store since Create, and the build writes into its `outputs/`. The screen ends in the
// shared **OutputsPanel** — browse what was built, tick what you want, copy it where you want.
//
// ⚠️ Two panels died with R44 and their reasons are worth keeping: `SavePanel` asked for the folder
// the finished project moved into (R43), and `SavedPanel` offered "Open folder" in Explorer. There
// is nothing to move and, by his ruling, no door out of the app to offer.
//
// Numbers, not prose (R3): the outcome is a stats strip read off `doc.build.stats`. The ETA counts
// down every second (R8) — `useJob` owns the countdown; this only renders `etaText`.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ApiError,
  getDocument,
  startVideoBuild,
  videoOutputUrl,
  videoMapElectrodes,
  videoGetElectrodeMap,
  cancelJob,
  useJob,
  listJobs,
  isTerminalState,
  getMea,
  attachMea,
} from '../../api';
import type {
  AnalysisSummary,
  ArrayCoverage,
  ElectrodeMapPayload,
  MeaAttachment,
  VideoMosaicDocument,
} from '../../api';
import { Button, ButtonLink, Help, Panel, LiveWarning } from '../../design';
import { OutputsDrawer } from '../outputs/OutputsDrawer';
import { CoverageChoice } from '../electrodes/CoverageChoice';
import { useCoverageHelp } from '../electrodes/device';
import { ElectrodePanel, type ElectrodeSelection } from '../electrodes/ElectrodePanel';
import { MeaTracePanel } from '../electrodes/MeaTracePanel';
import { buildElectrodeIndex, electrodeAt, lookupElectrode } from '../electrodes/lookup';
import { fmtDuration, fmtFps } from './format';
import { PipelineNav, PIPELINE_STEPS, type PipelineStepId } from './PipelineNav';
import { PreviewViewer } from './PreviewViewer';
import { RegionsStep } from './RegionsStep';
import { WorkFrame } from './WorkFrame';
import { useToast } from '../../app';
import styles from './VideoMosaicFeature.module.css';

const errMsg = (e: unknown): string => (e instanceof Error ? e.message : String(e));

/** The project's name, made safe for a Downloads folder on any OS. Never empty. */
const downloadName = (name: string): string =>
  name.replace(/[^\w.-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60) || 'video-mosaic';

// ── Reading the build block ──────────────────────────────────────────────────────────────────
// The contract types `doc.build` as a server-owned free dict ({built_at, canvas, outputs, stats});
// read it defensively — a missing number is simply not shown, never faked.

const rec = (v: unknown): Record<string, unknown> | null =>
  v != null && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
const num = (v: unknown): number | null =>
  typeof v === 'number' && Number.isFinite(v) ? v : null;

/** The payload's coverage, narrowed to the union (the contract types it as a plain string). */
const asCoverage = (v: string): ArrayCoverage => (v === 'full' ? 'full' : 'partial');

interface BuildView {
  builtAt: string | null;
  canvas: { w: number; h: number } | null;
  stats: Record<string, unknown>;
}

function buildView(doc: VideoMosaicDocument | null): BuildView | null {
  const b = rec(doc?.build);
  if (!b) return null;
  const canvas = rec(b.canvas);
  const w = num(canvas?.w);
  const h = num(canvas?.h);
  return {
    builtAt: typeof b.built_at === 'string' ? b.built_at : null,
    canvas: w != null && h != null ? { w, h } : null,
    stats: rec(b.stats) ?? {},
  };
}

export interface VideoMosaicFeatureProps {
  /** The manager's summary for this project — the FeatureGate already fetched it. */
  project: AnalysisSummary;
}

export function VideoMosaicFeature({ project }: VideoMosaicFeatureProps) {
  const analysisId = project.analysis_id;

  const summary = project;

  const [doc, setDoc] = useState<VideoMosaicDocument | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [buildError, setBuildError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  // ⭐ R47 — the outputs panel is a drawer now, not three copies stacked under three steps.
  const [filesOpen, setFilesOpen] = useState(false);

  const job = useJob(jobId);
  const running = jobId != null && !job.isTerminal;

  // ── the electrode map (server-owned, like the build): payload + its identify selection ──────
  const [emap, setEmap] = useState<ElectrodeMapPayload | null>(null);
  const [emapMissing, setEmapMissing] = useState(false);
  const [mapJobId, setMapJobId] = useState<string | null>(null);
  const [mapError, setMapError] = useState<string | null>(null);
  const [sel, setSel] = useState<ElectrodeSelection | null>(null);
  // ⭐ R45.8 — null until HE answers "is the whole chip in this mosaic?". No default, and the Map
  // button stays disabled while it is null: the app must not fit under an answer he never gave.
  const [coverage, setCoverage] = useState<ArrayCoverage | null>(null);
  const mapJob = useJob(mapJobId);
  const mapping = mapJobId != null && !mapJob.isTerminal;
  // The device's own numbers, SERVED (never retyped here — see features/electrodes/device.ts). Null
  // while in flight or if the fetch failed, and the help simply names no numbers then.
  const coverageHelp = useCoverageHelp();
  // ── the electrical half: which MaxWell recordings this project is paired with ───────────────
  // ⭐ Attachment is PROPOSED and confirmed, never assumed (see api/mea.ts). We only read here;
  // the panel below offers the confirm, because attaching the wrong plate would pair one culture's
  // voltages with another culture's neurons.
  const [mea, setMea] = useState<MeaAttachment | null>(null);
  const [meaBusy, setMeaBusy] = useState(false);
  const [meaError, setMeaError] = useState<string | null>(null);
  const eIndex = useMemo(() => (emap ? buildElectrodeIndex(emap) : null), [emap]);
  const emapRef = useRef(emap);
  emapRef.current = emap;

  // buildView handles a null doc, so the built-at stamp is safe to derive before the guards below.
  const view = buildView(doc);
  const builtAt = view?.builtAt ?? null;

  // ── the pipeline ───────────────────────────────────────────────────────────────────────────
  // ⭐ His ask, 2026-08-11: one pipeline with a progress bar at the top, walked step by step.
  // Each step is a genuine precondition of the next — there is no mosaic to map electrodes on
  // before the survey is built, and a located region whose electrodes cannot be named is half an
  // answer — so `reachable` is derived from the DOCUMENT, never from where the user has clicked.
  const toast = useToast();
  const mapped = Boolean(doc?.electrodes?.built_at);
  const reachable = 1 + (doc?.source ? 1 : 0) + (view ? 1 : 0) + (mapped ? 1 : 0);
  const [step, setStep] = useState<PipelineStepId | null>(null);
  // Opening a project lands on the furthest step that is ready: the work is where you left it,
  // and a finished pipeline opens on its answer rather than on its first screen.
  const current: PipelineStepId = step ?? PIPELINE_STEPS[Math.max(0, reachable - 1)];
  const go = useCallback(
    (id: PipelineStepId, locked: boolean): void => {
      if (locked) {
        toast.push('Finish the step before it first.', { tone: 'default' });
        return;
      }
      setStep(id);
    },
    [toast],
  );

  // The saved document is the truth on mount; a finished build replaces it below.
  useEffect(() => {
    let live = true;
    setDoc(null);
    setLoadError(null);
    getDocument(analysisId).then(
      (r) => {
        if (live) setDoc(r.doc as VideoMosaicDocument);
      },
      (e: unknown) => {
        if (live) setLoadError(errMsg(e));
      },
    );
    return () => {
      live = false;
    };
  }, [analysisId]);

  // Re-attach after a remount: the build is a detached server-side job; if one is running,
  // resume showing its progress instead of an idle screen whose Build button would 409.
  useEffect(() => {
    let live = true;
    void listJobs().then(
      (r) => {
        if (!live) return;
        const open = r.jobs.find(
          (j) => j.kind === 'videomosaic_build' && !isTerminalState(j.state),
        );
        if (open) setJobId(open.job_id);
      },
      () => undefined, // listing jobs is best-effort; the idle screen is still usable
    );
    return () => {
      live = false;
    };
  }, [analysisId]);

  // A finished build carries the document the server ALREADY saved — adopt it, never author.
  useEffect(() => {
    if (!jobId || !job.isTerminal) return;
    if (job.state === 'failed') {
      setBuildError(job.error?.message ?? 'The build failed.');
      setJobId(null);
      return;
    }
    if (job.state === 'done') {
      const result = job.job?.result;
      if (result && result.kind === 'videomosaic_build') {
        // A re-attached job could be ANOTHER project's build (one lease, one job at a time):
        // adopt its document only if it is ours; otherwise refetch our own.
        if (result.doc.id === analysisId) setDoc(result.doc);
        else void getDocument(analysisId).then((r) => setDoc(r.doc as VideoMosaicDocument));
      }
    }
    setJobId(null); // done or cancelled
  }, [jobId, job.isTerminal, job.state, job.job, job.error, analysisId]);

  const build = useCallback(async () => {
    if (running) return;
    setBuildError(null);
    try {
      const ref = await startVideoBuild(analysisId);
      setJobId(ref.job_id);
    } catch (e) {
      setBuildError(errMsg(e)); // 409 busy — the backend's reason, inline
    }
  }, [analysisId, running]);

  const cancel = useCallback(async () => {
    if (!jobId) return;
    try {
      await cancelJob(jobId);
    } catch {
      /* it already finished — a no-op, not an error to shout about */
    }
    // The poll observes the terminal state and clears jobId — no optimistic teardown.
  }, [jobId]);

  // ── the electrode map lifecycle ────────────────────────────────────────────────────────────
  // GET answers 404 until mapped — the normal first-visit state. Re-fetched when `builtAt` moves
  // (a rebuild makes the map stale server-side, and the payload's `stale` says so).
  const fetchEmap = useCallback(async () => {
    try {
      const p = await videoGetElectrodeMap(analysisId);
      setEmap(p);
      setEmapMissing(false);
      // A map he already made carries his answer — adopt it so a Re-run after a reload repeats the
      // declaration instead of asking again. A choice made in THIS session always wins.
      setCoverage((c) => c ?? asCoverage(p.array_coverage));
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setEmap(null);
        setEmapMissing(true);
      } else if (emapRef.current == null) {
        // A hiccup with no map in hand: keep the Map button reachable (mapping again is safe).
        setEmapMissing(true);
      }
    }
  }, [analysisId]);

  useEffect(() => {
    setSel(null); // a rebuild invalidates any highlight
    if (builtAt != null) void fetchEmap();
  }, [fetchEmap, builtAt]);

  const startEmap = useCallback(async () => {
    // No coverage, no mapping — the button is disabled, and this is the same rule again in code.
    if (mapping || running || !coverage) return;
    setMapError(null);
    try {
      const ref = await videoMapElectrodes(analysisId, coverage);
      setMapJobId(ref.job_id);
    } catch (e) {
      setMapError(errMsg(e)); // 409 busy, or the R45.8 refusal naming both shapes — verbatim
    }
  }, [analysisId, mapping, running, coverage]);

  const cancelEmap = useCallback(async () => {
    if (!mapJobId) return;
    try {
      await cancelJob(mapJobId);
    } catch {
      /* it already finished — a no-op */
    }
  }, [mapJobId]);

  // ⭐ THE SERVER SAVED THE DOCUMENT (unlike the snapshot feature): the finished job's `doc` is
  // already durable — adopt it if it is ours, refetch otherwise, then pull the typed payload.
  useEffect(() => {
    if (!mapJobId || !mapJob.isTerminal) return;
    if (mapJob.state === 'failed') {
      setMapError(mapJob.error?.message ?? 'Electrode mapping failed.');
      setMapJobId(null);
      return;
    }
    if (mapJob.state === 'done') {
      const result = mapJob.job?.result;
      if (result && result.kind === 'electrode_map') {
        const resultDoc = result.doc as VideoMosaicDocument | null | undefined;
        if (resultDoc && resultDoc.id === analysisId) setDoc(resultDoc);
        else void getDocument(analysisId).then((r) => setDoc(r.doc as VideoMosaicDocument));
        void fetchEmap();
      }
    }
    setMapJobId(null); // done or cancelled
  }, [mapJobId, mapJob.isTerminal, mapJob.state, mapJob.job, mapJob.error, analysisId, fetchEmap]);

  // What electrical data this project already has. Read-only: `attached: false` is a normal
  // first-visit state, and attaching is an explicit act the user takes in the panel below.
  useEffect(() => {
    let live = true;
    setMea(null);
    setMeaError(null);
    getMea(analysisId).then(
      (m) => {
        if (live) setMea(m);
      },
      () => {
        /* a project with no MEA block is not an error — the panel offers to look. */
      },
    );
    return () => {
      live = false;
    };
  }, [analysisId]);

  const findRecordings = useCallback(async (): Promise<void> => {
    setMeaBusy(true);
    setMeaError(null);
    try {
      // Discover, then save in one gesture — the paths land in the panel where he can read them,
      // and re-running it is harmless. What is NOT assumed is the chip's seating: `confirmed`
      // stays false, so every electrode identity stays marked provisional until it is settled.
      setMea(await attachMea(analysisId, { confirm: true }));
    } catch (e: unknown) {
      setMeaError(e instanceof Error ? e.message : String(e));
    } finally {
      setMeaBusy(false);
    }
  }, [analysisId]);

  // Arrow keys step the selection one grid cell; Esc clears it. Only while an electrode is
  // selected — the keys otherwise belong to the page (there is no other keyboard on this screen).
  const selRef = useRef(sel);
  selRef.current = sel;
  const eIndexRef = useRef(eIndex);
  eIndexRef.current = eIndex;
  useEffect(() => {
    const STEP: Record<string, [number, number]> = {
      ArrowUp: [0, -1],
      ArrowDown: [0, 1],
      ArrowLeft: [-1, 0],
      ArrowRight: [1, 0],
    };
    const onKey = (e: KeyboardEvent): void => {
      const el = e.target as HTMLElement | null;
      const tag = el?.tagName ?? '';
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(tag) || el?.isContentEditable) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (!selRef.current) return;
      if (e.key === 'Escape') {
        setSel(null);
        return;
      }
      const step = STEP[e.key];
      if (step && eIndexRef.current) {
        const cur = selRef.current.hit;
        const next = electrodeAt(eIndexRef.current, cur.col + step[0], cur.row + step[1]);
        if (next) setSel({ hit: next, clickX: null, clickY: null });
        e.preventDefault();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // ⛔ **NO "leave and lose it?" PROMPT ANY MORE (R44 retires R43.6).** There is nothing to lose:
  // the project is in the store from the moment it is created, so walking away from a build leaves a
  // real, listed project he can reopen — and delete himself if he does not want it.

  if (loadError) {
    return (
      <div className={styles.pane} data-testid="videomosaic">
        <LiveWarning variant="loud">
          <strong>Could not open the project.</strong> {loadError}
        </LiveWarning>
      </div>
    );
  }
  if (!doc) {
    return (
      <div className={styles.pane} data-testid="videomosaic">
        <p className={styles.loading}>Opening project…</p>
      </div>
    );
  }

  const src = doc.source ?? null;

  return (
    <div className={styles.pane} data-testid="videomosaic">
      <header className={styles.head}>
        <div className={styles.headText}>
          <h1 className={styles.h1}>{summary.name}</h1>
          {src && (
            <p className={styles.source} data-testid="vm-source">
              {src.name} · {src.width}×{src.height} · {fmtFps(src.fps)} fps ·{' '}
              {fmtDuration(src.duration_s)}
            </p>
          )}
        </div>
        {/* ⭐ R44 stands — the app is still the only door to project data. R47 just makes it ONE
            door, reachable from every step, in the way on none of them. */}
        {view && (
          <Button
            variant="ghost"
            size="sm"
            data-testid="vm-files"
            onClick={() => setFilesOpen(true)}
          >
            Files
          </Button>
        )}
      </header>

      <PipelineNav current={current} reachable={reachable} onStep={go} />

      {/* ── 1 · SURVEY — the video the mosaic is built from ────────────────────────────────── */}
      {current === 'survey' && (
        <div className={styles.stepScroll} data-testid="vm-step-survey">
          <Panel
            title="Survey recording"
            help={
              'The calcium video that sweeps the whole MEA. Its frames are what the mosaic is ' +
              'stitched from, so everything downstream is measured in its pixels.\n\n' +
              'It lives in the project — Camea keeps its own copy, so moving or deleting the ' +
              'original does not break the project.'
            }
          >
            {src ? (
              <div className={styles.stats}>
                <span className={styles.fact}>
                  <span className={styles.factLabel}>file</span>
                  {src.name}
                </span>
                {/* "frame" beside "frames" read as the same word twice — one is a SIZE and the
                    other a COUNT, and at a glance neither said which. */}
                <span className={styles.fact}>
                  <span className={styles.factLabel}>frame size</span>
                  {src.width}×{src.height}
                </span>
                <span className={styles.fact}>
                  <span className={styles.factLabel}>frame count</span>
                  {src.n_frames}
                </span>
                <span className={styles.fact}>
                  <span className={styles.factLabel}>rate</span>
                  {fmtFps(src.fps)} fps
                </span>
                <span className={styles.fact}>
                  <span className={styles.factLabel}>length</span>
                  {fmtDuration(src.duration_s)}
                </span>
              </div>
            ) : (
              <LiveWarning variant="loud">
                <strong>This project has no survey video.</strong> It cannot build a mosaic until
                one is added.
              </LiveWarning>
            )}
            {src && (
              <div className={styles.mapRow}>
                <Button
                  variant="primary"
                  onClick={() => setStep('mosaic')}
                  data-testid="vm-to-mosaic"
                >
                  Continue
                </Button>
              </div>
            )}
          </Panel>
        </div>
      )}

      {/* ── 2 · MOSAIC — build it, then look at it ─────────────────────────────────────────── */}
      {/* ⭐ R47 — once it is built, the mosaic IS the screen: the picture takes the frame and the
          stats, the rebuild and the way on move to the rail beside it. Before that there is no
          picture to frame, so the build button and the progress bar keep their centred column. */}
      {current === 'mosaic' && (
        <div
          className={!running && view ? styles.stepFill : styles.stepScroll}
          data-testid="vm-step-mosaic"
        >
          {!running && !view && buildError && (
            <LiveWarning variant="loud" className={styles.block}>
              <strong>Build error.</strong> {buildError}
            </LiveWarning>
          )}

          {!running && !view && (
            <div className={styles.buildPanel}>
              <Button
                variant="primary"
                size="lg"
                onClick={() => void build()}
                data-testid="vm-build"
              >
                Build mosaic
              </Button>
              {/* One button and one `?` — R3's shape exactly. The screen does not lecture, but the
                  answer to "what is about to happen?" is a hover away for anyone who wants it. */}
              <Help
                body={
                  'Stitches the survey video into one picture of the whole chip. Camea picks the ' +
                  'frames worth keeping, registers each against its neighbours, and renders them ' +
                  'onto a single canvas.\n' +
                  '\n' +
                  'Nothing is placed by hand and nothing is asked of you while it runs — it takes ' +
                  'minutes on a long recording, reports where it has got to, and can be ' +
                  'cancelled. You can rebuild afterwards as often as you like.'
                }
              />
            </div>
          )}

          {running && (
            <div data-testid="vm-progress">
              <Panel title="Building" className={styles.progress}>
                <div className={styles.barWell}>
                  <div
                    className={styles.bar}
                    style={{
                      transform: `scaleX(${Math.max(2, Math.min(100, job.pct ?? 0)) / 100})`,
                    }}
                  />
                </div>
                <div className={styles.progressRow}>
                  <span className={styles.phase} data-testid="vm-phase">
                    {job.phase ?? 'starting…'}
                    {job.phaseIndex != null && job.nPhases != null
                      ? ` · ${job.phaseIndex + 1}/${job.nPhases}`
                      : ''}
                  </span>
                  <span className={styles.eta} data-testid="vm-eta">
                    {job.etaText ?? ''}
                  </span>
                  <Button
                    variant="danger"
                    size="sm"
                    onClick={() => void cancel()}
                    data-testid="vm-cancel"
                  >
                    Cancel
                  </Button>
                </div>
                {job.message && <div className={styles.msg}>{job.message}</div>}
              </Panel>
            </div>
          )}

          {!running && view && (
            <WorkFrame
              picture={
                <PreviewViewer
                  analysisId={analysisId}
                  builtAt={view.builtAt}
                  canvas={view.canvas}
                  payload={null}
                  selection={null}
                  showGrid={false}
                />
              }
              rail={
                <>
                  {buildError && (
                    <LiveWarning variant="loud">
                      <strong>Build error.</strong> {buildError}
                    </LiveWarning>
                  )}
                  <Panel
                    title="The build"
                    help={
                      'What the stitcher did with the survey video. keyframes — how many frames it ' +
                      'kept as tiles, and how many it could not place. links ok / rejected — pairs ' +
                      'of tiles it tried to register against each other; a rejected link is one ' +
                      'whose match was not good enough to trust, which is a refusal, not a failure. ' +
                      'canvas — the size of the finished picture in pixels. coverage — how much of ' +
                      'that canvas actually has pixels on it.'
                    }
                  >
                    <StatsStrip doc={doc} view={view} />
                  </Panel>
                  <div className={styles.railActions}>
                    <Button
                      variant="primary"
                      onClick={() => setStep('electrodes')}
                      data-testid="vm-to-electrodes"
                    >
                      Map electrodes
                    </Button>
                    {/* The whole mosaic, at full canvas resolution — the browser streams it to
                        disk without decoding, so this costs the same however big it gets. */}
                    <ButtonLink
                      variant="ghost"
                      href={videoOutputUrl(analysisId, 'mosaic.png', view.builtAt)}
                      download={`${downloadName(summary.name)}.png`}
                      data-testid="vm-download"
                    >
                      Download full resolution
                      {view.canvas && (
                        <span className={styles.downloadSize}>
                          {view.canvas.w}×{view.canvas.h}
                        </span>
                      )}
                    </ButtonLink>
                    <Button variant="ghost" onClick={() => void build()} data-testid="vm-rebuild">
                      Rebuild
                    </Button>
                  </div>
                </>
              }
            />
          )}
        </div>
      )}

      {/* ── 3 · ELECTRODES — number the lattice, then click it ─────────────────────────────── */}
      {current === 'electrodes' && view && (
        <div className={styles.stepFill} data-testid="vm-step-electrodes">
          <WorkFrame
            picture={
              <PreviewViewer
                analysisId={analysisId}
                builtAt={view.builtAt}
                canvas={view.canvas}
                payload={emap}
                selection={sel}
                onPick={(x, y, scale) => {
                  // A hit selects; a miss DESELECTS — a wrong highlight must not linger (his
                  // rule). The zoom goes with the click: the tolerance is a screen distance (R45.7).
                  const hit = eIndex ? lookupElectrode(eIndex, x, y, scale) : null;
                  setSel(hit ? { hit, clickX: x, clickY: y } : null);
                }}
              />
            }
            rail={
              <>
                {mapping && (
                  <div data-testid="vm-electrodes-progress">
                    <Panel title="Mapping electrodes" className={styles.progress}>
                      <div className={styles.barWell}>
                        <div
                          className={styles.bar}
                          style={{
                            transform: `scaleX(${
                              Math.max(2, Math.min(100, mapJob.pct ?? 0)) / 100
                            })`,
                          }}
                        />
                      </div>
                      <div className={styles.progressRow}>
                        <span className={styles.phase}>{mapJob.phase ?? 'starting…'}</span>
                        <span className={styles.eta}>{mapJob.etaText ?? ''}</span>
                        <Button
                          variant="danger"
                          size="sm"
                          onClick={() => void cancelEmap()}
                          data-testid="vm-electrodes-cancel"
                        >
                          Cancel
                        </Button>
                      </div>
                    </Panel>
                  </div>
                )}

                {/* ⭐ **THE REFUSAL IS SHOWN WHOLE** (R45.8 strict). Under "whole chip imaged" the
                    fit ends in a map or a REFUSAL, and the refusal is the useful half: it names the
                    shape it found, the shape the device wants, and tells him to answer "part of the
                    chip" if that is what this mosaic is. So it renders verbatim — never trimmed to
                    a code, never a generic "mapping failed" — and the coverage question stays on
                    the page beneath it, so the fix he is being told to make is one click away. */}
                {mapError && (
                  <div data-testid="vm-electrodes-map-error">
                    <LiveWarning variant="loud">
                      <strong>Electrode mapping error.</strong> {mapError}
                    </LiveWarning>
                  </div>
                )}

                {/* The way on comes FIRST on the rail once the map is good — R47: the next thing to
                    do should not be below a readout you have to scroll past. */}
                {emap && !emap.stale && (
                  <div className={styles.railActions}>
                    <Button
                      variant="primary"
                      onClick={() => setStep('regions')}
                      data-testid="vm-to-regions"
                    >
                      Locate recordings
                    </Button>
                  </div>
                )}

                {emap && (
                  <ElectrodePanel
                    payload={emap}
                    selection={sel}
                    stale={emap.stale}
                    coverage={
                      <CoverageChoice value={coverage} onChange={setCoverage} disabled={mapping} />
                    }
                    action={
                      <Button
                        variant={emap.stale ? 'primary' : 'ghost'}
                        size="sm"
                        data-testid="vm-map-electrodes"
                        disabled={mapping || running || coverage == null}
                        onClick={() => void startEmap()}
                      >
                        Re-run
                      </Button>
                    }
                  />
                )}

                {/* ⭐ THE ELECTRICAL HALF. Only offered once the electrodes are mapped: without a
                    grid there is no "which electrode did I click", and a trace with no identity is
                    not part of the pairing this app exists to build. */}
                {emap && mea && !mea.attached && (
                  <Panel
                    title="Voltage traces"
                    help={
                      'Finds the MaxWell recording that goes with this project, so clicking an ' +
                      'electrode shows what it recorded. Camea looks beside the folder this ' +
                      "project's video came from and shows you what it found — nothing is read " +
                      'until you look at the paths.'
                    }
                  >
                    {meaError && <LiveWarning variant="loud">{meaError}</LiveWarning>}
                    <Button
                      variant="primary"
                      size="sm"
                      disabled={meaBusy}
                      onClick={() => void findRecordings()}
                      data-testid="vm-find-mea"
                    >
                      {meaBusy ? 'Looking…' : 'Find the MEA recording'}
                    </Button>
                  </Panel>
                )}

                {emap && mea?.attached && (
                  <MeaTracePanel
                    analysisId={analysisId}
                    electrode={sel?.hit.electrode ?? null}
                    recordings={mea.recordings ?? []}
                  />
                )}

                {/* ⭐ THE QUESTION COMES FIRST (R45.8). It has its own panel rather than a bare
                    button in the action row, because the two options need room to say what they
                    cost. */}
                {emapMissing && !mapping && (
                  <Panel
                    title="Map electrodes"
                    help={
                      'Fits the MEA lattice to the built mosaic — pitch, rotation and phase ' +
                      'measured from THESE pixels, never assumed. Afterwards a click on the ' +
                      'picture identifies the electrode under it.\n' +
                      '\n' +
                      coverageHelp
                    }
                  >
                    <CoverageChoice value={coverage} onChange={setCoverage} disabled={mapping} />
                    <div className={styles.mapRow}>
                      <Button
                        variant="primary"
                        onClick={() => void startEmap()}
                        data-testid="vm-map-electrodes"
                        disabled={mapping || running || coverage == null}
                      >
                        Map electrodes
                      </Button>
                    </div>
                  </Panel>
                )}
              </>
            }
          />
        </div>
      )}

      {/* ── 4 · REGIONS — where each fixed-field recording was taken ───────────────────────── */}
      {current === 'regions' && view && (
        <RegionsStep
          analysisId={analysisId}
          builtAt={view.builtAt}
          canvas={view.canvas}
          payload={emap}
          onDocChanged={(d: VideoMosaicDocument) => setDoc(d)}
        />
      )}

      {/* ⭐ Browse what this project built, and take a copy of what you want (R44) — the SAME panel
          every feature mounts, not a copy of it. R47 moved it off the bottom of three steps and
          behind the header's Files button: one door, asked for. */}
      {view && (
        <OutputsDrawer
          analysisId={analysisId}
          version={view.builtAt}
          open={filesOpen}
          onClose={() => setFilesOpen(false)}
        />
      )}
    </div>
  );
}

// ── The stats strip (R3 — numbers, not prose) ────────────────────────────────────────────────

function StatsStrip({ doc, view }: { doc: VideoMosaicDocument; view: BuildView }) {
  const entries = Object.values(doc.keyframes ?? {});
  const s = view.stats;
  const placed = entries.length
    ? entries.filter((k) => k.placed).length
    : num(s.keyframes_placed);
  const dropped = num(s.keyframes_dropped);
  const total = entries.length
    ? entries.length
    : placed != null && dropped != null
      ? placed + dropped
      : null;
  const reg = rec(s.registration);
  const ok = num(reg?.links_ok);
  const rejected = num(reg?.links_rejected);
  const coverage = num(rec(s.render)?.coverage_frac);
  const elapsed = num(s.elapsed_s);

  const facts: Array<[string, string]> = [];
  if (placed != null && total != null) facts.push(['keyframes', `${placed}/${total}`]);
  if (ok != null) facts.push(['links ok', String(ok)]);
  if (rejected != null) facts.push(['rejected', String(rejected)]);
  if (view.canvas) facts.push(['canvas', `${view.canvas.w}×${view.canvas.h}`]);
  if (coverage != null) facts.push(['coverage', `${Math.round(coverage * 100)}%`]);
  if (elapsed != null) facts.push(['build', fmtDuration(elapsed)]);

  return (
    <div className={styles.stats} data-testid="vm-stats">
      {facts.map(([label, value]) => (
        <span className={styles.fact} key={label}>
          <span className={styles.factLabel}>{label}</span>
          {value}
        </span>
      ))}
    </div>
  );
}
