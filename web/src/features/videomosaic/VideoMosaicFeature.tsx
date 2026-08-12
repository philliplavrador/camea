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

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from 'react';
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
} from '../../api';
import type {
  AnalysisSummary,
  ArrayCoverage,
  ElectrodeMapPayload,
  VideoMosaicDocument,
} from '../../api';
import { Button, ButtonLink, Panel, LiveWarning, cx } from '../../design';
import { OutputsPanel } from '../outputs/OutputsPanel';
import { CoverageChoice } from '../electrodes/CoverageChoice';
import { useCoverageHelp } from '../electrodes/device';
import { ElectrodePanel, type ElectrodeSelection } from '../electrodes/ElectrodePanel';
import { GridOverlay, IDS_MIN_STEP_PX } from '../electrodes/GridOverlay';
import {
  buildElectrodeIndex,
  electrodeAt,
  hitRadiusAt,
  lookupElectrode,
} from '../electrodes/lookup';
import { fmtDuration, fmtFps } from './format';
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
  const eIndex = useMemo(() => (emap ? buildElectrodeIndex(emap) : null), [emap]);
  const emapRef = useRef(emap);
  emapRef.current = emap;

  // buildView handles a null doc, so the built-at stamp is safe to derive before the guards below.
  const view = buildView(doc);
  const builtAt = view?.builtAt ?? null;

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
        <h1 className={styles.h1}>{summary.name}</h1>
        {src && (
          <p className={styles.source} data-testid="vm-source">
            {src.name} · {src.width}×{src.height} · {fmtFps(src.fps)} fps ·{' '}
            {fmtDuration(src.duration_s)}
          </p>
        )}
      </header>

      {buildError && (
        <LiveWarning variant="loud" className={styles.block}>
          <strong>Build error.</strong> {buildError}
        </LiveWarning>
      )}

      {!running && !view && (
        <div className={styles.buildPanel}>
          <Button variant="primary" size="lg" onClick={() => void build()} data-testid="vm-build">
            Build mosaic
          </Button>
        </div>
      )}

      {running && (
        <div data-testid="vm-progress">
          <Panel title="Building" className={styles.progress}>
            <div className={styles.barWell}>
              <div
                className={styles.bar}
                style={{ transform: `scaleX(${Math.max(2, Math.min(100, job.pct ?? 0)) / 100})` }}
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
              <Button variant="danger" size="sm" onClick={() => void cancel()} data-testid="vm-cancel">
                Cancel
              </Button>
            </div>
            {job.message && <div className={styles.msg}>{job.message}</div>}
          </Panel>
        </div>
      )}

      {!running && view && (
        <>
          <StatsStrip doc={doc} view={view} />
          <PreviewViewer
            analysisId={analysisId}
            builtAt={view.builtAt}
            canvas={view.canvas}
            payload={emap}
            selection={sel}
            onPick={(x, y, scale) => {
              // A hit selects; a miss DESELECTS — a wrong highlight must not linger (his rule).
              // The zoom goes with the click: the tolerance is a screen distance (R45.7).
              const hit = eIndex ? lookupElectrode(eIndex, x, y, scale) : null;
              setSel(hit ? { hit, clickX: x, clickY: y } : null);
            }}
          />

          {mapping && (
            <div data-testid="vm-electrodes-progress">
              <Panel title="Mapping electrodes" className={styles.progress}>
                <div className={styles.barWell}>
                  <div
                    className={styles.bar}
                    style={{
                      transform: `scaleX(${Math.max(2, Math.min(100, mapJob.pct ?? 0)) / 100})`,
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

          {/* ⭐ **THE REFUSAL IS SHOWN WHOLE** (R45.8 strict). Under "whole chip imaged" the fit ends
              in a map or a REFUSAL, and the refusal is the useful half: it names the shape it found,
              the shape the device wants, and tells him to answer "part of the chip" if that is what
              this mosaic is. So it renders verbatim — never trimmed to a code, never a generic
              "mapping failed" — and the coverage question stays on the page beneath it, so the fix
              he is being told to make is one click away. */}
          {mapError && (
            <div data-testid="vm-electrodes-map-error">
              <LiveWarning variant="loud">
                <strong>Electrode mapping error.</strong> {mapError}
              </LiveWarning>
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

          {/* ⭐ THE QUESTION COMES FIRST (R45.8). It has its own panel rather than a bare button in
              the action row, because the two options need room to say what they cost. */}
          {emapMissing && !mapping && (
            <Panel
              title="Map electrodes"
              help={
                'Fits the MEA lattice to the built mosaic — pitch, rotation and phase measured from THESE pixels, never assumed. Afterwards a click on the preview identifies the electrode under it.\n' +
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

          <div className={styles.builtActions}>
            <Button variant="ghost" onClick={() => void build()} data-testid="vm-rebuild">
              Rebuild
            </Button>
            {/* The whole mosaic, at full canvas resolution — the browser streams it to disk without
                decoding, so this costs the same however big the canvas gets. */}
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
          </div>
          {/* ⭐ Browse what this project built, and take a copy of what you want (R44). The SAME
              panel every feature mounts — not a copy of it. */}
          <OutputsPanel analysisId={analysisId} version={view.builtAt} title="Files" />
        </>
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

// ── The preview — a real zoom/pan viewer over the built mosaic ────────────────────────────────
//
// ⭐ 100 % MEANS 100 % OF THE MOSAIC (2026-08-07). This viewer used to show `preview.png` in both
// states — 2048 px on the long side, 7.3 % of the pixels of a 5331×7552 build — so "view at 100%"
// was a 3.7× lie and the real file, sitting on disk behind a working route the whole time, was
// never once requested. Zooming now fetches `mosaic.png`. The browser was never the bottleneck:
// Chrome decodes the full 40 Mpx file in ~80 ms against a 2²⁹-pixel ceiling. The small preview
// still serves the fit view, so the screen paints instantly after a build; the full file is
// fetched the moment the zoom passes the point where the preview would blur, and layered ON TOP so
// the picture never blanks.
//
// ⭐ **WHEEL TO ZOOM, DRAG TO PAN (2026-08-11).** It used to be a scroll box with a fit ↔ 100 %
// toggle, and that was enough while the screen was only ever *looked* at. Identification made it a
// working surface: at fit, his 5319×7356 mosaic draws 1024 px wide, so an electrode is 5.9 CSS px
// and pointing at one is not a thing a hand can do. Now the camera is continuous between fit and
// 8×, the click identifies whatever the current zoom can honestly resolve (R45.7), and the mapped
// lattice is DRAWN — outline when zoomed out, pad dots as they become separable, ids when there is
// room for text. "Which electrode is this?" is answerable by eye before you even click.

interface ViewState {
  scale: number; // CSS px per mosaic px
  tx: number; //   screen x of mosaic x=0
  ty: number;
}

/** Zoom ceiling — 8 mosaic px per CSS px is well past the point where the pixels themselves show. */
const MAX_SCALE = 8;
/** `preview.png` is ~2048 px on the long side; past this the full file is worth its bytes. */
const FULL_RES_ABOVE = 0.34;
/** A press that travels further than this is a pan, not an identification click. */
const CLICK_SLOP_PX = 4;

function PreviewViewer({
  analysisId,
  builtAt,
  canvas,
  payload,
  selection,
  onPick,
}: {
  analysisId: string;
  builtAt: string | null;
  canvas: { w: number; h: number } | null;
  payload: ElectrodeMapPayload | null;
  selection: ElectrodeSelection | null;
  onPick: (x: number, y: number, scale: number) => void;
}) {
  const boxRef = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({ w: 0, h: 0 });
  const [view, setView] = useState<ViewState | null>(null);
  const [idsOn, setIdsOn] = useState(false);
  const [fullReady, setFullReady] = useState(false);
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);

  // The map exists AND the build told us the canvas: a plain click identifies. Without the canvas
  // size the preview's own pixels are the only frame there is, and the map's coordinates would not
  // mean anything in it — so identification stays off rather than answering with a guess.
  const identify = payload != null && canvas != null;

  // ── the camera ────────────────────────────────────────────────────────────────────────────────
  // The mosaic's own size drives the camera. It comes from the build block; if a build ever lands
  // without one, the preview's natural size stands in — a viewer with no picture is not an option.
  const world = canvas ?? natural;
  const fitScale = world && box.w > 0 ? Math.min(box.w / world.w, box.h / world.h) : 0;

  /** Keep the picture on the stage: centred while it is smaller than the box, inside it when not. */
  const clampView = useCallback(
    (v: ViewState): ViewState => {
      if (!world) return v;
      const w = world.w * v.scale;
      const h = world.h * v.scale;
      const axis = (t: number, drawn: number, avail: number): number =>
        drawn <= avail ? (avail - drawn) / 2 : Math.min(0, Math.max(avail - drawn, t));
      return { scale: v.scale, tx: axis(v.tx, w, box.w), ty: axis(v.ty, h, box.h) };
    },
    [world, box.w, box.h],
  );

  const setScaleAt = useCallback(
    (next: number, sx: number, sy: number) => {
      setView((v) => {
        if (!v || !world) return v;
        const s = Math.min(MAX_SCALE, Math.max(fitScale, next));
        if (s === v.scale) return v;
        const k = s / v.scale;
        return clampView({ scale: s, tx: sx - (sx - v.tx) * k, ty: sy - (sy - v.ty) * k });
      });
    },
    [world, clampView, fitScale],
  );

  const fitNow = useCallback(() => {
    if (!world || box.w === 0) return;
    setView(clampView({ scale: fitScale, tx: 0, ty: 0 }));
  }, [world, box.w, clampView, fitScale]);

  // Measure the stage; fit the first time it and the canvas are both known.
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const measure = (): void => setBox({ w: el.clientWidth, h: el.clientHeight });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    // A new build invalidates the loaded pixels and the camera alike.
    setFullReady(false);
    setView(null);
  }, [builtAt]);

  useEffect(() => {
    if (view == null) fitNow();
    else setView((v) => (v ? clampView(v) : v)); // a resize must not strand the picture off-stage
  }, [view == null, fitNow, clampView]); // eslint-disable-line react-hooks/exhaustive-deps

  // Wheel = zoom at the pointer. A native non-passive listener: React's is passive, so it could not
  // preventDefault and the page would scroll away underneath the zoom.
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent): void => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      const step = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY; // lines vs pixels
      setView((v) =>
        v
          ? ((): ViewState => {
              const s = Math.min(MAX_SCALE, Math.max(fitScale, v.scale * Math.exp(-step * 0.0022)));
              const k = s / v.scale;
              const sx = e.clientX - r.left;
              const sy = e.clientY - r.top;
              return clampView({ scale: s, tx: sx - (sx - v.tx) * k, ty: sy - (sy - v.ty) * k });
            })()
          : v,
      );
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [clampView, fitScale]);

  // Drag = pan. A press that did not travel is a click, and a click identifies. The pointer is
  // CAPTURED for the drag, so a pan that runs off the stage keeps panning and still ends cleanly.
  const drag = useRef<{ x: number; y: number; tx: number; ty: number; moved: boolean } | null>(null);
  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>): void => {
    if (!view || e.button !== 0) return;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    drag.current = { x: e.clientX, y: e.clientY, tx: view.tx, ty: view.ty, moved: false };
  };
  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>): void => {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (!d.moved && Math.hypot(dx, dy) <= CLICK_SLOP_PX) return;
    d.moved = true;
    setView((v) => (v ? clampView({ scale: v.scale, tx: d.tx + dx, ty: d.ty + dy }) : v));
  };
  const onPointerUp = (e: ReactPointerEvent<HTMLDivElement>): void => {
    const d = drag.current;
    drag.current = null;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
    if (!d || d.moved || !view || !identify) return;
    const el = boxRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    onPick(
      (e.clientX - r.left - view.tx) / view.scale,
      (e.clientY - r.top - view.ty) / view.scale,
      view.scale,
    );
  };

  const wantFull = (view?.scale ?? 0) > FULL_RES_ABOVE || fullReady;
  const loading = wantFull && !fullReady;
  const zoomPct = view ? Math.round(view.scale * 100) : null;
  const atFit = view != null && fitScale > 0 && Math.abs(view.scale - fitScale) < 1e-6;
  const marker =
    payload && selection && view
      ? {
          left: selection.hit.centerX * view.scale + view.tx,
          top: selection.hit.centerY * view.scale + view.ty,
          d: Math.max(12, hitRadiusAt(payload, view.scale) * view.scale * 2),
        }
      : null;

  return (
    <div className={styles.viewerWrap}>
      <div
        className={styles.viewer}
        data-testid="vm-viewer"
        ref={boxRef}
        data-fit={atFit || undefined}
        data-loading={loading || undefined}
        data-identify={identify || undefined}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={() => (drag.current = null)}
        onDoubleClick={(e) => {
          const el = boxRef.current;
          if (!el || !view) return;
          const r = el.getBoundingClientRect();
          setScaleAt(view.scale * 2, e.clientX - r.left, e.clientY - r.top);
        }}
        title={
          identify
            ? 'Click an electrode to identify it · wheel to zoom · drag to pan'
            : 'Wheel to zoom · drag to pan'
        }
      >
        <div
          className={styles.world}
          style={
            view && world
              ? {
                  width: world.w,
                  height: world.h,
                  transform: `translate(${view.tx}px, ${view.ty}px) scale(${view.scale})`,
                }
              : { width: 'auto', height: 'auto' }
          }
        >
          {/* The small file paints immediately and stays as the base; the full one layers over it
              once decoded, so zooming never blanks the picture. */}
          <img
            className={styles.preview}
            data-testid="vm-preview"
            alt="Mosaic preview"
            src={videoOutputUrl(analysisId, 'preview.png', builtAt)}
            onLoad={(e) =>
              setNatural({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })
            }
            draggable={false}
          />
          {wantFull && (
            <img
              className={styles.previewFull}
              data-testid="vm-preview-full"
              data-ready={fullReady || undefined}
              alt=""
              aria-hidden="true"
              src={videoOutputUrl(analysisId, 'mosaic.png', builtAt)}
              onLoad={() => setFullReady(true)}
              draggable={false}
            />
          )}
        </div>

        {payload && view && identify && (
          <GridOverlay
            payload={payload}
            scale={view.scale}
            tx={view.tx}
            ty={view.ty}
            width={box.w}
            height={box.h}
            idsOn={idsOn}
            className={styles.gridLayer}
          />
        )}

        {marker && selection && (
          <div
            className={styles.vmMarker}
            data-testid="vm-electrode-marker"
            data-electrode={selection.hit.electrode}
            style={{
              left: marker.left,
              top: marker.top,
              width: marker.d,
              height: marker.d,
            }}
          >
            <span className={styles.vmMarkerLabel}>{selection.hit.electrode}</span>
          </div>
        )}

        {loading && <div className={styles.viewerNote}>loading full resolution…</div>}
      </div>

      <div className={styles.zoomBar}>
        <button
          type="button"
          className={styles.zoomBtn}
          data-testid="vm-zoom-out"
          onClick={() => setScaleAt((view?.scale ?? 1) / 1.6, box.w / 2, box.h / 2)}
          title="Zoom out"
        >
          −
        </button>
        <span className={styles.zoomLevel} data-testid="vm-zoom-level">
          {zoomPct != null ? `${zoomPct}%` : '—'}
        </span>
        <button
          type="button"
          className={styles.zoomBtn}
          data-testid="vm-zoom-in"
          onClick={() => setScaleAt((view?.scale ?? 1) * 1.6, box.w / 2, box.h / 2)}
          title="Zoom in"
        >
          +
        </button>
        <button
          type="button"
          className={styles.zoomBtn}
          data-testid="vm-zoom-toggle"
          onClick={() => (atFit ? setScaleAt(1, box.w / 2, box.h / 2) : fitNow())}
          title={atFit ? 'View the full-resolution mosaic' : 'Fit the whole mosaic'}
        >
          {atFit ? '100%' : 'Fit'}
        </button>
        {identify && (
          <button
            type="button"
            role="switch"
            aria-checked={idsOn}
            className={cx(styles.zoomBtn, idsOn && styles.zoomBtnOn)}
            data-testid="vm-electrode-ids-toggle"
            onClick={() => setIdsOn((v) => !v)}
            title={`Label every visible electrode (from ${IDS_MIN_STEP_PX} px between centres — zoom in)`}
          >
            IDs
          </button>
        )}
      </div>
    </div>
  );
}

