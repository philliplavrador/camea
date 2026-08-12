// ─────────────────────────────────────────────────────────────────────────────────────────────
// STEP 7 · ELECTRODES — the optional post-export identification stage (2026-08-11).
//
// A READ-ONLY mount of the core viewer over ALL PLACED tiles (anchored + unverified — this is NOT
// the sweep screen, so R9's certified-only rule does not bind it; R9 protects the judging canvas).
// Once "Map electrodes" has run, a click resolves to electrode `col-row` through the pure client
// lookup (the server's own rule: within hit_radius_px of a centre, gaps select NOTHING — a miss
// DESELECTS). Arrow keys step the selection one grid cell (his misclick recovery); Esc clears it —
// R14 protects only the SWEEP cursor, not this selection.
//
// THE ONE DISPATCH POINT (§3.4): a single window keydown handler — electrode keys first, the rest to
// `viewer.handleKey` (F/0/G/± still work; the read-only engine refuses nudge, so arrows never move
// tiles). The highlight + ID labels are a DOM overlay repositioned from `onView` — the tile layers
// are never rebaked per frame (R20).
//
// THE DOCUMENT IS CLIENT-OWNED here (unlike the videomosaic): the finished job's `electrodes` block
// is merged into the working doc and saved through the SAME durable path every judgement uses
// (documentStore.setDocument → autosaveNow, i.e. PUT /api/analyses/{id}/document).
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { CanvasHTMLAttributes } from 'react';
import { Viewer } from '../../../../core/viewer';
import type { ViewerHandle, ViewerTile, ViewMatrix } from '../../../../core/viewer';
import {
  ApiError,
  cancelJob,
  getElectrodeMap,
  mapElectrodes,
  useJob,
  type ArrayCoverage,
  type ElectrodeMapPayload,
  type MosaicDocument,
} from '../../../../api';
import { Button, Help, LiveWarning, Panel, cx } from '../../../../design';
import { useSweepStore } from '../../store';
import { useDocument } from '../../../../store/documentStore';
import { CoverageChoice } from '../../../../features/electrodes/CoverageChoice';
import { useCoverageHelp } from '../../../../features/electrodes/device';
import {
  ElectrodePanel,
  type ElectrodeSelection,
} from '../../../../features/electrodes/ElectrodePanel';
import { GridOverlay, IDS_MIN_STEP_PX } from '../../../../features/electrodes/GridOverlay';
import {
  buildElectrodeIndex,
  electrodeAt,
  hitRadiusAt,
  lookupElectrode,
  type ElectrodeIndex,
} from '../../../../features/electrodes/lookup';
import styles from './ElectrodesStep.module.css';

// One layer, drawn and feathered — the whole placed field, marked `reference` so a stray D
// (Difference) keeps showing the same picture instead of a black stage.
const LAYERS = [{ key: 'tiles', reference: true }];

/** A press that travels further than this is a pan, not an identification click. */
const CLICK_SLOP_PX = 4;

const errMsg = (e: unknown): string => (e instanceof Error ? e.message : String(e));

/** The payload's coverage, narrowed to the union (the contract types it as a plain string). */
const asCoverage = (v: string): ArrayCoverage => (v === 'full' ? 'full' : 'partial');

const ARROW: Record<string, { dc: number; dr: number }> = {
  ArrowUp: { dc: 0, dr: -1 }, //    Up = row−1
  ArrowDown: { dc: 0, dr: 1 }, //   Down = row+1
  ArrowLeft: { dc: -1, dr: 0 }, //  Left = col−1
  ArrowRight: { dc: 1, dr: 0 }, //  Right = col+1
};

/** A signature of the placed tiles' positions — the client's honest staleness check: if it differs
 *  from the one captured when the map was fetched, the mosaic moved under the map. */
function positionsSig(doc: MosaicDocument | null): string {
  if (!doc) return '';
  const parts: string[] = [];
  for (const [k, t] of Object.entries(doc.tiles)) {
    if (t.x == null || t.y == null) continue;
    if (t.state !== 'anchored' && t.state !== 'unverified') continue;
    parts.push(`${k}:${t.x},${t.y}`);
  }
  return parts.sort().join(';');
}

export interface ElectrodesStepProps {
  /** Build the pixel URL for a trial — the session owner's, cache-busted (R31/R32), like SweepStep. */
  tileSrc: (trial: number) => string;
}

export function ElectrodesStep({ tileSrc }: ElectrodesStepProps) {
  const viewerRef = useRef<ViewerHandle>(null);
  const stageRef = useRef<HTMLDivElement>(null);

  const doc = useSweepStore((s) => s.doc);
  const sessionId = useSweepStore((s) => s.sessionId);
  const order = useSweepStore((s) => s.order);
  const analysisId = useDocument((s) => s.analysisId);

  const [payload, setPayload] = useState<ElectrodeMapPayload | null>(null);
  const [notMapped, setNotMapped] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);
  const [selection, setSelection] = useState<ElectrodeSelection | null>(null);
  // ⭐ R45.8 — null until HE answers "is the whole chip in this mosaic?". There is no default: the
  // Map button below stays disabled while this is null, so nothing is ever fitted under an
  // assumption he did not make.
  const [coverage, setCoverage] = useState<ArrayCoverage | null>(null);
  const [idsOn, setIdsOn] = useState(false); // the IDs overlay is OFF by default — no clutter
  // The device's own numbers, SERVED (never retyped here — see features/electrodes/device.ts). Null
  // while in flight or if the fetch failed, and the help simply names no numbers then.
  const coverageHelp = useCoverageHelp();
  const [view, setView] = useState<ViewMatrix>({ scale: 1, tx: 0, ty: 0 });
  const [stageSize, setStageSize] = useState({ w: 0, h: 0 });

  const job = useJob(jobId);
  const running = jobId != null && !job.isTerminal;

  // The pure lookup index, rebuilt only when the payload changes.
  const index = useMemo(() => (payload ? buildElectrodeIndex(payload) : null), [payload]);

  // Refs so the single window keydown handler stays stable (§3.4).
  const indexRef = useRef<ElectrodeIndex | null>(index);
  indexRef.current = index;
  const selRef = useRef<ElectrodeSelection | null>(selection);
  selRef.current = selection;
  const viewRef = useRef<ViewMatrix>(view);
  viewRef.current = view;

  // ── fetch the map (404 `not_found` = not mapped yet — a normal first visit, not an error) ──────
  const posSigAtFetch = useRef<string | null>(null);
  const payloadRef = useRef<ElectrodeMapPayload | null>(payload);
  payloadRef.current = payload;
  const fetchMap = useCallback(async () => {
    if (!analysisId) return;
    setLoadError(null);
    try {
      const p = await getElectrodeMap(analysisId);
      posSigAtFetch.current = positionsSig(useSweepStore.getState().doc);
      setPayload(p);
      setNotMapped(false);
      // A map he already made carries his answer — adopt it so a Re-run after a reload repeats the
      // declaration instead of asking again. A choice made in THIS session always wins.
      setCoverage((c) => c ?? asCoverage(p.array_coverage));
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setPayload(null);
        setNotMapped(true);
      } else {
        setLoadError(errMsg(e));
        // ⭐ A HICCUP MUST NOT STRAND HIM. With no map in hand the readout is gone, and with it the
        // coverage question and the Re-run button — so the one screen that could fix anything would
        // offer nothing at all. Mapping again is safe, so keep the Map panel (question + button)
        // reachable; the warning above it still says what went wrong. Same rule the videomosaic
        // screen already follows.
        if (payloadRef.current == null) setNotMapped(true);
      }
    }
  }, [analysisId]);

  useEffect(() => {
    void fetchMap();
  }, [fetchMap]);

  // ── staleness: the server's verdict (vs the SAVED doc) OR positions moved since we fetched ─────
  const currentSig = useMemo(() => positionsSig(doc), [doc]);
  const stale =
    payload != null &&
    (payload.stale || (posSigAtFetch.current != null && currentSig !== posSigAtFetch.current));

  // ── the map job ────────────────────────────────────────────────────────────────────────────────
  const startMap = useCallback(async () => {
    const s = useSweepStore.getState();
    // No coverage, no mapping — the button is disabled, and this is the same rule again in code.
    if (!s.sessionId || !s.doc || running || !coverage) return;
    setJobError(null);
    try {
      const ref = await mapElectrodes(s.sessionId, s.doc, coverage, true);
      setJobId(ref.job_id);
    } catch (e) {
      setJobError(errMsg(e)); // e.g. 409 busy, or the R45.8 refusal naming both shapes — verbatim
    }
  }, [running, coverage]);

  const cancelMap = useCallback(async () => {
    if (!jobId) return;
    try {
      await cancelJob(jobId);
    } catch {
      /* already finished — a no-op, not an error to shout about */
    }
  }, [jobId]);

  // On done: merge `electrodes` into the CLIENT-owned doc, save through the one durable path, refetch.
  useEffect(() => {
    if (!jobId || !job.isTerminal) return;
    if (job.state === 'failed') {
      setJobError(job.error?.message ?? 'Mapping failed.');
      setJobId(null);
      return;
    }
    if (job.state === 'done') {
      const result = job.job?.result;
      if (result && result.kind === 'electrode_map') {
        const s = useSweepStore.getState();
        if (s.doc) {
          const merged: MosaicDocument = { ...s.doc, electrodes: result.electrodes };
          // Keep the sweep spine and the document store on the SAME object, then save durably —
          // setDocument marks dirty + schedules the autosave; autosaveNow flushes it (the exact
          // path an A/E judgement takes), and the GET after it sees fresh `stale`.
          useSweepStore.setState({ doc: merged });
          useDocument.getState().setDocument(merged);
          void (async () => {
            await useDocument.getState().autosaveNow();
            await fetchMap();
          })();
        }
      }
    }
    setJobId(null); // done or cancelled
  }, [jobId, job.isTerminal, job.state, job.job, job.error, fetchMap]);

  // ── the viewer model: ALL placed tiles (anchored + unverified), read-only ──────────────────────
  const didFit = useRef(false);
  useEffect(() => {
    const v = viewerRef.current;
    if (!v || !doc) return;
    const model: Record<string, ViewerTile> = {};
    for (const t of order) {
      const tile = doc.tiles[String(t)];
      if (!tile || tile.x == null || tile.y == null) continue;
      if (tile.state !== 'anchored' && tile.state !== 'unverified') continue;
      model[String(t)] = { x: tile.x, y: tile.y, src: tileSrc(t), layer: 'tiles', feather: true };
    }
    // A one-off rebake per DOC change — never per frame (R20); this step edits nothing, so the doc
    // only changes underneath us when the electrodes block merges in.
    v.setTiles(model);
    if (!didFit.current && Object.keys(model).length > 0) {
      didFit.current = true;
      v.fit();
    }
  }, [doc, order, tileSrc]);

  // ── the ONE keyboard dispatch point for this screen (§3.4) ─────────────────────────────────────
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      const el = e.target as HTMLElement | null;
      const tag = el?.tagName ?? '';
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(tag) || el?.isContentEditable) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return; // Ctrl+S etc. belong to the shell (R5.2)

      // Arrow keys step the SELECTION one grid cell — only while an electrode is selected. Stepping
      // off the array's edge is a no-op (the selection stays).
      const arrow = ARROW[e.key];
      if (arrow && selRef.current && indexRef.current) {
        const cur = selRef.current.hit;
        const next = electrodeAt(indexRef.current, cur.col + arrow.dc, cur.row + arrow.dr);
        if (next) setSelection({ hit: next, clickX: null, clickY: null });
        e.preventDefault();
        return;
      }

      // Esc clears the electrode selection. This is NOT the sweep — R14 protects only the sweep
      // cursor. The engine still gets the key to clear its own ghosts.
      if (e.key === 'Escape') setSelection(null);

      viewerRef.current?.handleKey(e); // the camera half: F / 0 / G / ± (read-only refuses nudge)
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // ── click → world → lookup. A press that panned is not a click (slop threshold). ───────────────
  const downAt = useRef<{ x: number; y: number } | null>(null);
  const canvasProps: CanvasHTMLAttributes<HTMLCanvasElement> & Record<`data-${string}`, string> = {
    'data-testid': 'electrodes-canvas',
    onPointerDown: (e) => {
      downAt.current = { x: e.clientX, y: e.clientY };
    },
    onClick: (e) => {
      const down = downAt.current;
      downAt.current = null;
      if (down && Math.hypot(e.clientX - down.x, e.clientY - down.y) > CLICK_SLOP_PX) return;
      const v = viewerRef.current;
      const idx = indexRef.current;
      if (!v || !idx) return;
      const [wx, wy] = v.screenToWorld(e.nativeEvent.offsetX, e.nativeEvent.offsetY);
      // The zoom goes with the click: the tolerance is a distance on SCREEN (R45.7), so pointing at
      // an electrode works at any camera — never crossing into the next cell.
      const hit = lookupElectrode(idx, wx, wy, viewRef.current.scale);
      // A hit selects; a miss DESELECTS — a wrong highlight must not linger (his rule).
      setSelection(hit ? { hit, clickX: wx, clickY: wy } : null);
    },
  };

  // Track the canvas area's CSS size for overlay culling.
  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    const measure = () => setStageSize({ w: el.clientWidth, h: el.clientHeight });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  if (!doc) {
    return (
      <div className={styles.stage} data-testid="electrodes-viewer">
        <p className={styles.empty}>No document open.</p>
      </div>
    );
  }

  return (
    <div className={styles.stage} data-testid="electrodes-viewer">
      <div className={styles.canvasArea} ref={stageRef}>
        <Viewer
          ref={viewerRef}
          layers={LAYERS.map((l) => ({ ...l }))}
          readOnly
          canvasProps={canvasProps}
          onView={(v) => setView(v)}
        />
        {payload && (
          <>
            {/* The mapped lattice itself — the SAME overlay the videomosaic screen draws. */}
            <GridOverlay
              payload={payload}
              scale={view.scale}
              tx={view.tx}
              ty={view.ty}
              width={stageSize.w}
              height={stageSize.h}
              idsOn={idsOn}
              className={styles.gridLayer}
            />
            <ElectrodeOverlay payload={payload} selection={selection} view={view} />
          </>
        )}
      </div>

      <div className={styles.rail}>
        {loadError && (
          <LiveWarning variant="loud">Could not read the electrode map: {loadError}</LiveWarning>
        )}

        {running && (
          <div data-testid="electrodes-progress">
            <Panel title="Mapping">
              <div className={styles.barWell}>
                <div
                  className={styles.bar}
                  style={{ transform: `scaleX(${Math.max(2, Math.min(100, job.pct ?? 0)) / 100})` }}
                />
              </div>
              <div className={styles.progressRow}>
                <span className={styles.phase} data-testid="electrodes-phase">
                  {job.phase ?? 'starting…'}
                </span>
                <span className={styles.eta}>{job.etaText ?? ''}</span>
                <Button
                  variant="danger"
                  size="sm"
                  onClick={() => void cancelMap()}
                  data-testid="electrodes-cancel"
                >
                  Cancel
                </Button>
              </div>
            </Panel>
          </div>
        )}

        {/* ⭐ **THE REFUSAL IS SHOWN WHOLE** (R45.8 strict). Under "whole chip imaged" the fit ends in
            a map or a REFUSAL, and the refusal is the useful half: it names the shape it found, the
            shape the device wants, and tells him to answer "part of the chip" if that is what this
            mosaic is. So it renders verbatim — never trimmed to a code, never a generic "mapping
            failed" — and the coverage question stays on the page below/above it, so the fix he is
            being told to make is one click away. */}
        {jobError && (
          <div data-testid="electrodes-map-error">
            <LiveWarning variant="loud">
              <strong>Mapping error.</strong> {jobError}
            </LiveWarning>
          </div>
        )}

        {notMapped && !running && (
          <Panel
            title="Map electrodes"
            help={
              'Renders the placed tiles server-side and fits the MEA lattice to them — pitch, rotation and phase measured from THIS mosaic, never assumed. Afterwards a click on the mosaic identifies the electrode under it.\n' +
              '\n' +
              coverageHelp
            }
          >
            {/* ⭐ THE QUESTION COMES FIRST (R45.8): the button below is dead until he answers it. */}
            <CoverageChoice value={coverage} onChange={setCoverage} disabled={running} />
            <div className={styles.mapRow}>
              <Button
                variant="primary"
                data-testid="electrodes-map"
                disabled={!sessionId || running || coverage == null}
                onClick={() => void startMap()}
              >
                Map electrodes
              </Button>
            </div>
          </Panel>
        )}

        {payload && (
          <>
            <ElectrodePanel
              payload={payload}
              selection={selection}
              stale={stale}
              coverage={
                <CoverageChoice value={coverage} onChange={setCoverage} disabled={running} />
              }
              action={
                <Button
                  variant={stale ? 'primary' : 'ghost'}
                  size="sm"
                  data-testid="electrodes-map"
                  disabled={running || !sessionId || coverage == null}
                  onClick={() => void startMap()}
                >
                  Re-run
                </Button>
              }
            />
            <div className={styles.switchRow}>
              <button
                type="button"
                role="switch"
                aria-checked={idsOn}
                data-testid="electrode-ids-toggle"
                className={cx(styles.switch, idsOn && styles.switchOn)}
                onClick={() => setIdsOn((v) => !v)}
              >
                <span className={styles.switchMark} aria-hidden="true" />
                IDs
              </button>
              <Help
                body={`Label every visible electrode with its col-row id. Labels appear only when adjacent centres are ≥ ${IDS_MIN_STEP_PX} px apart on screen — zoom in until they are legible.`}
              />
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ── the overlay: ONE marker, world→screen via the view matrix ───────────────────────────────────
// A DOM node for the highlight (the ids and pads are drawn on the shared GridOverlay canvas — a map
// is tens of thousands of positions, which is a canvas job). The tile layers underneath are never
// touched, let alone rebaked (R20).

function ElectrodeOverlay({
  payload,
  selection,
  view,
}: {
  payload: ElectrodeMapPayload;
  selection: ElectrodeSelection | null;
  view: ViewMatrix;
}) {
  const { scale, tx, ty } = view;
  const toScreen = (wx: number, wy: number): [number, number] => [wx * scale + tx, wy * scale + ty];

  // The ring shows the tolerance actually in force at this zoom (R45.7) — what you see is what
  // would have been selected.
  const sel = selection
    ? {
        at: toScreen(selection.hit.centerX, selection.hit.centerY),
        r: hitRadiusAt(payload, scale) * scale,
      }
    : null;

  return (
    <div className={styles.overlay} aria-hidden="true">
      {sel && selection && (
        <>
          <div
            className={styles.marker}
            data-testid="electrode-marker"
            data-electrode={selection.hit.electrode}
            style={{
              left: sel.at[0],
              top: sel.at[1],
              width: Math.max(8, sel.r * 2),
              height: Math.max(8, sel.r * 2),
            }}
          />
          <span
            className={styles.markerLabel}
            style={{ left: sel.at[0], top: sel.at[1] + Math.max(4, sel.r) + 4 }}
          >
            {selection.hit.electrode}
          </span>
        </>
      )}
    </div>
  );
}
