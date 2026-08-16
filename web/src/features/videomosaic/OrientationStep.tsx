// ─────────────────────────────────────────────────────────────────────────────────────────────
// ORIENTATION — ⭐ which way round is the chip sitting in this mosaic? (his ruling 2026-08-15:
// its own step after Regions, and the four candidates shown as PICTURES he can pick from by eye.)
//
// The pairing this whole app exists to produce needs one more fact that no file records: which
// corner of the mosaic the chip's own origin landed in. Four seatings are possible; pick wrong and
// every neuron is paired with the wrong electrode, invisibly.
//
// Two ways to settle it, both HUMAN acts:
//   • ⭐ BY EYE. The rail shows all four seatings as small pictures — the mosaic with every
//     recorded electrode drawn where THAT seating puts it, and the located recordings outlined.
//     Clicking a card previews it on the big picture; "Use this seating" confirms it. The routed
//     block usually sits under the imaged fields in exactly one of the four, so the eye can often
//     answer what the numbers cannot.
//   • THE TEST. Scores the four seatings against the located recordings. What it must never do is
//     make the answer look more settled than it is, so three rules are baked in:
//       1. 🔴 **The caveat is always on screen, verbatim, never behind a `?`** (issue 003, R47.7).
//          The clock alignment can rest on the 2P lamp marks and those did not survive checking.
//          He asked for the test built anyway; he did not ask to be lied to about it.
//       2. ⭐ **"Cannot tell" is a real outcome and gets said plainly.** When the seatings are not
//          separated the server sends no winner at all (`decisive: false`, `best: null`), so there
//          is nothing here to apply. Measured: P003693's four seatings land within 0.004.
//       3. ⭐ **"Untestable" is not a bad score.** A seating with no recorded electrode under a
//          field was never tested; "none under it" stays a word, never a number.
//
// ⭐ CONFIRMATION IS A HUMAN ACT, whichever road he takes. The job never applies anything, the
// footprint proposes nothing — a card's "Use this seating" click is what turns a candidate into
// the seating the pairing is built on, and picking another card later simply re-confirms.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  attachMea,
  getMeaFootprint,
  testMeaOrientation,
  useJob,
  useStopJob,
  videoOutputUrl,
} from '../../api';
import type {
  ElectrodeMapPayload,
  MeaAttachment,
  MeaFootprintSeating,
  OrientationTestResult,
  RegionRecord,
} from '../../api';
import { Button, LiveWarning, Panel, Progress, cx, useDelayedFlag } from '../../design';
import { buildElectrodeIndex, electrodeAt, type ElectrodeIndex } from '../electrodes/lookup';
import { phaseOf } from './format';
import { PreviewViewer, type ViewFrame } from './PreviewViewer';
import { useElapsedText } from './useElapsed';
import { WorkFrame } from './WorkFrame';
import styles from './OrientationStep.module.css';

const errMsg = (e: unknown): string => (e instanceof Error ? e.message : String(e));

/** The seating in the words the app has always used for it. */
const seatingName = (flipX: boolean, flipY: boolean): string =>
  !flipX && !flipY
    ? 'as-is'
    : `flipped ${[flipX && 'top–bottom', flipY && 'left–right'].filter(Boolean).join(' and ')}`;

const keyOf = (flipX: boolean, flipY: boolean): string => `${flipX ? 1 : 0}${flipY ? 1 : 0}`;

/** The recorded pads' dots — the same green the lattice overlay uses for a detected pad. */
const DOT = 'rgba(110, 231, 160, 0.9)';
/** The located recordings' outlines — the outstanding-work amber, quiet context. */
const REGION = 'rgba(255, 196, 61, 0.9)';
/** How far off-stage a dot may be before it is culled (big viewer). */
const CULL_PX = 8;
/** The card thumbnails' internal render width, px (2× a ~180 px card for crispness). */
const THUMB_W = 360;

// ── Where each seating's recorded pads sit, in mosaic px ─────────────────────────────────────
// The footprint serves Camea "col-row" grid ids; the electrode map says where each grid cell is
// on THIS mosaic (R45.8 — the map is the one place that knows, never a retyped device number).
// A flat [x0,y0,x1,y1,…] per seating, computed once per payload pair.

function seatingCentres(
  index: ElectrodeIndex | null,
  seatings: MeaFootprintSeating[],
): Map<string, number[]> {
  const m = new Map<string, number[]>();
  if (!index) return m;
  for (const s of seatings) {
    const pts: number[] = [];
    for (const id of s.electrodes ?? []) {
      const dash = id.indexOf('-');
      if (dash <= 0) continue;
      const hit = electrodeAt(index, Number(id.slice(0, dash)), Number(id.slice(dash + 1)));
      if (hit) pts.push(hit.centerX, hit.centerY);
    }
    m.set(keyOf(s.flip_x, s.flip_y), pts);
  }
  return m;
}

// ── props ─────────────────────────────────────────────────────────────────────────────────────

export interface OrientationStepProps {
  analysisId: string;
  /** The build's stamp — the cache-buster for every picture on this step. */
  builtAt: string | null;
  /** The mosaic's own size, so mosaic px mean something on screen and on the thumbnails. */
  canvas: { w: number; h: number } | null;
  /** The electrode map — where each grid id sits on the mosaic. Null while unfetched/missing. */
  payload: ElectrodeMapPayload | null;
  /** The located recordings, off the DOCUMENT — drawn for context on every picture. */
  regions: RegionRecord[];
  /** The project's electrical attachment; its `orientation` is the settled state. */
  mea: MeaAttachment | null;
  /** A confirm returns the saved attachment — the parent adopts it (it owns `mea`). */
  onMeaChanged: (mea: MeaAttachment) => void;
}

// ── the step ──────────────────────────────────────────────────────────────────────────────────

export function OrientationStep({
  analysisId,
  builtAt,
  canvas,
  payload,
  regions,
  mea,
  onMeaChanged,
}: OrientationStepProps) {
  const [footprint, setFootprint] = useState<Awaited<
    ReturnType<typeof getMeaFootprint>
  > | null>(null);
  // 🔴 The 409 refusal ("attach the MEA recording first" / "map the electrodes first") is an
  // INSTRUCTION and renders verbatim — never trimmed to a code (the R45.8 discipline).
  const [refusal, setRefusal] = useState<string | null>(null);
  const [previewKey, setPreviewKey] = useState<string | null>(null);
  const [applying, setApplying] = useState<string | null>(null);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [testError, setTestError] = useState<string | null>(null);
  const job = useJob(jobId);
  const running = jobId != null && !job.isTerminal;
  const stopJob = useStopJob();

  // ⏱️ **THE FOOTPRINT IS A WAIT, AND IT LOOKED LIKE A BROKEN STEP (R48.10).** The whole rail is
  // empty until this lands — no cards, no test, no refusal — and the read is not free: it walks the
  // recording folder and opens an HDF5 file. An in-flight fetch and "there is nothing here" are
  // different states and must look different.
  const footprintWait = footprint == null && refusal == null;
  const footprintSlow = useDelayedFlag(footprintWait);
  const footprintFor = useElapsedText(footprintWait);

  // ⏱️ *"Use this seating"* re-runs the ENTIRE MEA scan before it saves (the attach route's
  // `confirm` half), which was minutes behind a button whose only sign of life was the word
  // "Saving…". It is a job now, so the same bar the strip draws is drawn here too, with a Stop.
  const [applyJobId, setApplyJobId] = useState<string | null>(null);
  const applyJob = useJob(applyJobId);

  const result =
    job.job?.result && job.job.result.kind === 'mea_orientation'
      ? (job.job.result as OrientationTestResult)
      : null;

  useEffect(() => {
    let live = true;
    setFootprint(null);
    setRefusal(null);
    getMeaFootprint(analysisId).then(
      (p) => {
        if (live) setFootprint(p);
      },
      (e: unknown) => {
        if (live) setRefusal(errMsg(e));
      },
    );
    return () => {
      live = false;
    };
  }, [analysisId]);

  const seatings = useMemo(() => footprint?.seatings ?? [], [footprint]);
  const settled = mea?.orientation?.confirmed ? mea.orientation : null;

  // The previewed seating: his click wins; before any click, the settled one; failing that, as-is.
  const previewed = useMemo<MeaFootprintSeating | null>(() => {
    if (seatings.length === 0) return null;
    if (previewKey) {
      const picked = seatings.find((s) => keyOf(s.flip_x, s.flip_y) === previewKey);
      if (picked) return picked;
    }
    if (settled) {
      const saved = seatings.find(
        (s) => s.flip_x === settled.flip_x && s.flip_y === settled.flip_y,
      );
      if (saved) return saved;
    }
    return seatings[0];
  }, [seatings, previewKey, settled]);

  const eIndex = useMemo(() => (payload ? buildElectrodeIndex(payload) : null), [payload]);
  const centres = useMemo(() => seatingCentres(eIndex, seatings), [eIndex, seatings]);

  const winner =
    result && result.decisive && result.best
      ? { flipX: result.best.flip_x, flipY: result.best.flip_y }
      : null;

  const start = useCallback(async () => {
    setTestError(null);
    try {
      const ref = await testMeaOrientation(analysisId);
      setJobId(ref.job_id);
    } catch (e: unknown) {
      setTestError(errMsg(e)); // the same 409 instructions as the footprint — verbatim
    }
  }, [analysisId]);

  // 🔴 **R48.9 — A WAIT THAT ENDS MUST SAY IT ENDED, INCLUDING BADLY.** This test reads every frame
  // of every located region: minutes of work whose only failure signal was the button quietly
  // becoming pressable again, with no sentence anywhere. A run that fails or is stopped says so.
  useEffect(() => {
    if (!jobId || !job.isTerminal) return;
    if (job.state === 'failed') {
      setTestError(job.error?.message ?? 'The seating test failed.');
    } else if (job.state === 'cancelled') {
      setTestError('The seating test was stopped. Nothing was applied.');
    }
  }, [jobId, job.isTerminal, job.state, job.error]);

  const use = useCallback(
    async (s: MeaFootprintSeating) => {
      const key = keyOf(s.flip_x, s.flip_y);
      setApplying(key);
      setApplyError(null);
      setApplyJobId(null);
      try {
        // ⭐ Confirmation is a HUMAN act. The job never sets this; this click is what turns a
        // candidate into the seating the pairing is built on. Provenance says which road he took.
        const isTestWinner =
          result?.decisive === true &&
          result.best != null &&
          result.best.flip_x === s.flip_x &&
          result.best.flip_y === s.flip_y;
        const saved = await attachMea(
          analysisId,
          {
            confirm: true,
            orientation: {
              flip_x: s.flip_x,
              flip_y: s.flip_y,
              confirmed: true,
              source: isTestWinner
                ? 'confirmed by you after the seating test'
                : 'chosen by you by eye from the pictures',
            },
          },
          // ⏱️ R48 — the id arrives on the first poll, which is what buys the bar its Stop.
          { onProgress: (j) => setApplyJobId(j.job_id) },
        );
        onMeaChanged(saved);
        setPreviewKey(key); // the big picture shows what he just settled on
      } catch (e: unknown) {
        setApplyError(errMsg(e));
      } finally {
        setApplying(null);
        setApplyJobId(null);
      }
    },
    [analysisId, onMeaChanged, result],
  );

  // ── the big picture's overlay: ONE candidate at a time, in screen space ─────────────────────
  const previewPts = useMemo(
    () => (previewed ? (centres.get(keyOf(previewed.flip_x, previewed.flip_y)) ?? []) : []),
    [previewed, centres],
  );
  const pitchPx = payload?.pitch_px ?? 0;
  const overlay = useCallback(
    (v: ViewFrame): ReactNode => (
      <FootprintLayer
        points={previewPts}
        regions={regions}
        pitchPx={pitchPx}
        flipX={previewed?.flip_x ?? false}
        flipY={previewed?.flip_y ?? false}
        scale={v.scale}
        tx={v.tx}
        ty={v.ty}
        width={v.width}
        height={v.height}
      />
    ),
    [previewPts, regions, pitchPx, previewed?.flip_x, previewed?.flip_y],
  );

  return (
    <div className={styles.step} data-testid="orientation-step">
      <WorkFrame
        testId="orientation-work"
        picture={
          <PreviewViewer
            analysisId={analysisId}
            builtAt={builtAt}
            canvas={canvas}
            payload={payload}
            selection={null}
            // The subject is the FOOTPRINT, not the lattice: 26,400 grid dots would drown the
            // ~1k recorded ones, so the grid layer stays off and the overlay draws its own.
            showGrid={false}
            overlay={overlay}
          />
        }
        rail={
          <>
            {/* ⏱️ R48.10 — WHILE IT IS BEING READ, SAY SO. An empty rail and a rail with nothing
                to show are different states; this one used to render as the second. */}
            {footprintWait && footprintSlow && (
              <Progress
                label="Reading where the recorded pads sit"
                // R48.9 — a folder walk plus one HDF5 open: no denominator exists until it
                // returns, so the sliver and the clock, never a bar creeping up a made-up scale.
                pct={null}
                etaText={null}
                elapsedText={footprintFor}
                unstoppableWhy="this read cannot be stopped once it starts"
                data-testid="orientation-footprint-progress"
              />
            )}

            {/* 🔴 The refusal is the whole story when there is one: it says what to do first
                (attach the recording / map the electrodes), in the server's own sentence. */}
            {refusal && !footprint && (
              <div data-testid="orientation-refusal">
                <LiveWarning variant="loud">{refusal}</LiveWarning>
              </div>
            )}

            {applyError && (
              <div data-testid="orientation-apply-error">
                <LiveWarning variant="loud">{applyError}</LiveWarning>
              </div>
            )}

            {/* ⏱️ *"Use this seating"* re-runs the whole recording scan before it saves — minutes,
                behind one word on a button until R48. The card's Button still says "Saving…"; this
                is the part that says how far it has got and lets him stop it. */}
            {applying != null && (
              <Progress
                label={applyJob.job?.said_as || 'saving the seating'}
                pct={applyJob.pct}
                etaText={applyJob.etaText}
                elapsedText={applyJob.elapsedText}
                phase={phaseOf(applyJob)}
                message={applyJob.message}
                onStop={applyJobId ? () => void stopJob(applyJobId) : undefined}
                unstoppableWhy={applyJobId ? undefined : 'starting…'}
                data-testid="orientation-apply-progress"
              />
            )}

            {settled ? (
              <p className={styles.settled} data-testid="mea-orientation-settled">
                Settled: <b>{seatingName(settled.flip_x, settled.flip_y)}</b>
                {settled.source ? <span className={styles.sub}> — {settled.source}</span> : null}
              </p>
            ) : (
              footprint && (
                <LiveWarning variant="warn">
                  Not established yet, so every electrode identity is provisional.
                </LiveWarning>
              )
            )}

            {footprint && (
              <Panel
                title="The four seatings"
                help={
                  'Which way round the chip sits in this mosaic. Nothing in the recording files ' +
                  'records it, so it has to be picked — and picking wrong pairs every neuron ' +
                  'with the wrong electrode.\n' +
                  '\n' +
                  'Each picture is the mosaic with a dot on every electrode the rig actually ' +
                  'recorded, where THAT seating would put it, plus your located recordings as ' +
                  'outlines. Click a picture to look at it large; press "Use this seating" on ' +
                  'the one where the dots sit under your recordings. You can change your mind ' +
                  'later — picking another card simply re-settles it.'
                }
              >
                <div className={styles.cards} data-testid="orientation-cards">
                  {seatings.map((s) => {
                    const key = keyOf(s.flip_x, s.flip_y);
                    const isPreviewed = previewed != null && keyOf(previewed.flip_x, previewed.flip_y) === key;
                    const isSettled =
                      settled != null && settled.flip_x === s.flip_x && settled.flip_y === s.flip_y;
                    const isWinner =
                      winner != null && winner.flipX === s.flip_x && winner.flipY === s.flip_y;
                    return (
                      <div
                        key={key}
                        className={cx(styles.card, isPreviewed && styles.cardOn)}
                        data-testid="orientation-card"
                        data-flip-x={String(s.flip_x)}
                        data-flip-y={String(s.flip_y)}
                        data-previewed={isPreviewed || undefined}
                        data-settled={isSettled || undefined}
                        data-winner={isWinner || undefined}
                        onClick={() => setPreviewKey(key)}
                      >
                        <div
                          className={styles.thumb}
                          style={{ aspectRatio: canvas ? `${canvas.w} / ${canvas.h}` : '4 / 3' }}
                        >
                          <img
                            className={styles.thumbImg}
                            alt=""
                            aria-hidden="true"
                            draggable={false}
                            src={videoOutputUrl(analysisId, 'preview.png', builtAt)}
                          />
                          <ThumbCanvas
                            points={centres.get(key) ?? []}
                            regions={regions}
                            canvas={canvas}
                          />
                        </div>
                        <div className={styles.cardHead}>
                          <span className={styles.cardName}>
                            {seatingName(s.flip_x, s.flip_y)}
                          </span>
                          {isSettled && (
                            <span
                              className={cx(styles.chip, styles.chipSettled)}
                              data-testid="orientation-settled-badge"
                            >
                              settled
                            </span>
                          )}
                          {isWinner && (
                            <span
                              className={cx(styles.chip, styles.chipWinner)}
                              data-testid="orientation-winner-badge"
                            >
                              test winner
                            </span>
                          )}
                        </div>
                        {/* Rule 3's cousin, applied to geometry: zero covered is a word. */}
                        <div className={styles.cardFacts}>
                          {(s.regions ?? []).map((r) => (
                            <span key={r.region_id} className={styles.cardFact}>
                              {r.region_name || r.region_id}:{' '}
                              {r.n_covered === 0 ? 'none' : r.n_covered} of {r.n_region} pads
                            </span>
                          ))}
                        </div>
                        <Button
                          size="sm"
                          variant={isSettled ? 'ghost' : 'default'}
                          data-testid="orientation-use"
                          disabled={applying != null}
                          onClick={(ev) => {
                            ev.stopPropagation();
                            void use(s);
                          }}
                        >
                          {applying === key ? 'Saving…' : 'Use this seating'}
                        </Button>
                      </div>
                    );
                  })}
                </div>
              </Panel>
            )}

            {footprint && (
              <Panel
                title="The seating test"
                help={
                  'Asks, for each of the four possibilities: do the electrodes it puts under ' +
                  'your located recordings actually fire when those fields light up?\n' +
                  '\n' +
                  'It proposes; it never applies. The caveat it comes back with is part of the ' +
                  'answer, and "cannot tell" is a real outcome.'
                }
              >
                <div className={styles.body}>
                  {/* R48.9 — a failed or stopped run says so here, in the job's own sentence. */}
                  {testError && (
                    <div data-testid="orientation-test-error">
                      <LiveWarning variant="loud">{testError}</LiveWarning>
                    </div>
                  )}

                  <Button
                    size="sm"
                    variant={settled ? 'ghost' : 'primary'}
                    disabled={running || applying != null}
                    onClick={() => void start()}
                    data-testid="mea-test-orientation"
                  >
                    Test the orientation
                  </Button>

                  {/* ⏱️ **THE BUTTON LABEL USED TO BE THE ENTIRE PROGRESS UI** for MINUTES of work
                      — every frame of every located region decoded, scored four ways. `useJob` was
                      already being called for the result and its `pct`/`etaText` were simply never
                      read. The backend wave gave the job an overall pct (R48.5) and progress
                      callbacks inside the two steps that were silent for ~16 s. */}
                  {running && (
                    <Progress
                      label={job.job?.said_as || 'testing the orientation'}
                      pct={job.pct}
                      etaText={job.etaText}
                      elapsedText={job.elapsedText}
                      phase={phaseOf(job)}
                      message={job.message}
                      onStop={jobId ? () => void stopJob(jobId) : undefined}
                      data-testid="orientation-test-progress"
                    />
                  )}

                  {result && <TestResult result={result} />}
                </div>
              </Panel>
            )}
          </>
        }
      />
    </div>
  );
}

// ── the test's results — the honest half of the step ─────────────────────────────────────────

/** What the clock alignment actually rested on, in plain words (`alignment_source`). */
function alignmentSentence(source: string): string | null {
  if (source === 'ttl') {
    return 'The two clocks were lined up by the rig’s own time-stamp, written by the hardware itself.';
  }
  if (source === 'lamp') {
    return (
      'The two clocks were lined up by the lamp marks found in the electrical trace — ' +
      'the signal that did not survive checking.'
    );
  }
  if (source === 'none') return 'The two clocks could not be lined up at all.';
  return null;
}

function TestResult({ result }: { result: OrientationTestResult }) {
  const alignment = alignmentSentence(result.alignment_source);
  const breakdown = result.regions ?? [];
  return (
    <>
      {/* 🔴 Rule 1 — the caveat, VERBATIM, before the numbers, never behind a `?` (R47.7). */}
      <div data-testid="mea-orientation-caveat">
        <LiveWarning variant="warn">{result.caveat}</LiveWarning>
      </div>

      {alignment && (
        <p className={styles.sub} data-testid="orientation-alignment">
          {alignment}
        </p>
      )}

      {/* ⭐ The luck bar, plainly: the 95th percentile of what deliberately-wrong clocks score. */}
      {result.chance_level != null && (
        <p className={styles.sub} data-testid="orientation-chance">
          Scores of {result.chance_level.toFixed(3)} or more happen by luck about 5% of the time
          on this data — measured by re-scoring with the clocks shifted on purpose.
          {result.beats_chance == null
            ? ''
            : result.beats_chance
              ? ' The winning score is above that bar.'
              : ' The winning score is NOT above that bar — a score like it could be luck.'}
        </p>
      )}

      <table className={styles.table} data-testid="mea-orientation-scores">
        <thead>
          <tr>
            <th>Seating</th>
            <th>Electrodes under it</th>
            <th>Spikes</th>
            <th>Match</th>
          </tr>
        </thead>
        <tbody>
          {(result.scores ?? []).map((s) => {
            const isBest =
              result.best != null &&
              result.best.flip_x === s.flip_x &&
              result.best.flip_y === s.flip_y;
            return (
              <tr
                key={`${String(s.flip_x)}-${String(s.flip_y)}`}
                className={isBest ? styles.best : undefined}
              >
                <td>{seatingName(s.flip_x, s.flip_y)}</td>
                <td className={styles.num}>
                  {s.n_recorded} <span className={styles.sub}>of {s.n_region}</span>
                </td>
                <td className={styles.num}>{s.n_spikes.toLocaleString()}</td>
                {/* Rule 3 — untested is its own word, not a number. */}
                <td className={styles.num}>
                  {s.correlation == null ? (
                    <span className={styles.sub}>none under it</span>
                  ) : (
                    s.correlation.toFixed(3)
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {/* ⭐ Each recording alone — two independent fields pointing at one seating is different
          evidence from one field shouting and one silent, and only this can show which. */}
      {breakdown.length > 0 && (
        <div className={styles.breakdown}>
          {breakdown.map((rg) => (
            <div
              key={rg.region_id}
              className={styles.region}
              data-testid="orientation-region-rows"
              data-region-id={rg.region_id}
            >
              <p className={styles.regionName}>{rg.region_name || rg.region_id}</p>
              <table className={styles.table}>
                <tbody>
                  {(rg.seatings ?? []).map((s) => (
                    <tr key={`${String(s.flip_x)}-${String(s.flip_y)}`}>
                      <td>{seatingName(s.flip_x, s.flip_y)}</td>
                      <td className={styles.num}>
                        {s.n_recorded} <span className={styles.sub}>of {rg.n_region}</span>
                      </td>
                      <td className={styles.num}>
                        {s.correlation == null ? (
                          <span className={styles.sub}>none under it</span>
                        ) : (
                          s.correlation.toFixed(3)
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      )}

      {/* Rule 2 — say it, and offer nothing to press. The by-eye cards above stay: they are HIS
          judgement, not the test's. */}
      {!result.decisive || !result.best ? (
        <p className={styles.sub} data-testid="mea-orientation-undecided">
          <b>Cannot tell.</b> The four seatings scored too alike to choose between
          {result.margin != null ? ` (best beats the next by ${result.margin.toFixed(3)})` : ''}.
          Nothing has been applied.
        </p>
      ) : (
        <p className={styles.sub} data-testid="orientation-verdict">
          {result.decided_by === 'coverage' ? (
            <>
              Only <b>{seatingName(result.best.flip_x, result.best.flip_y)}</b> puts any recorded
              electrode under your recording — the other three put none. That is geometry, so it
              does not depend on the timing or on the waveform decoding.
            </>
          ) : (
            <>
              <b>{seatingName(result.best.flip_x, result.best.flip_y)}</b> matched best, by{' '}
              {result.margin?.toFixed(3) ?? '—'}.
            </>
          )}{' '}
          Its card above is marked — <b>Use this seating</b> there applies it.
        </p>
      )}
    </>
  );
}

// ── the drawing — one canvas each, screen space on the stage, mosaic-scaled on the cards ─────

interface FootprintLayerProps {
  /** Flat [x0,y0,x1,y1,…] centres in mosaic px. */
  points: number[];
  regions: RegionRecord[];
  pitchPx: number;
  flipX: boolean;
  flipY: boolean;
  /** The live view matrix: screen = world × scale + t (the PreviewViewer overlay contract). */
  scale: number;
  tx: number;
  ty: number;
  width: number;
  height: number;
}

/** The big viewer's layer: ONE seating's recorded pads + the located recordings, culled offstage. */
function FootprintLayer({
  points,
  regions,
  pitchPx,
  flipX,
  flipY,
  scale,
  tx,
  ty,
  width,
  height,
}: FootprintLayerProps) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const cvs = ref.current;
    if (!cvs || width === 0 || height === 0) return;
    const dpr = window.devicePixelRatio || 1;
    const bw = Math.round(width * dpr);
    const bh = Math.round(height * dpr);
    if (cvs.width !== bw || cvs.height !== bh) {
      cvs.width = bw;
      cvs.height = bh;
    }
    const g = cvs.getContext('2d');
    if (!g) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, width, height);
    if (!(scale > 0)) return;

    // the located recordings, as quiet amber outlines — the context the dots are judged against
    g.strokeStyle = REGION;
    g.lineWidth = 1.5;
    for (const r of regions) {
      g.strokeRect(r.x * scale + tx, r.y * scale + ty, r.w * scale, r.h * scale);
    }

    // the recorded pads under this seating
    const rad = Math.max(1.5, Math.min(5, (pitchPx || 8) * scale * 0.25));
    const path = new Path2D();
    for (let i = 0; i < points.length; i += 2) {
      const px = points[i] * scale + tx;
      if (px < -CULL_PX || px > width + CULL_PX) continue;
      const py = points[i + 1] * scale + ty;
      if (py < -CULL_PX || py > height + CULL_PX) continue;
      path.moveTo(px + rad, py);
      path.arc(px, py, rad, 0, Math.PI * 2);
    }
    g.fillStyle = DOT;
    g.fill(path);
  }, [points, regions, pitchPx, scale, tx, ty, width, height]);

  return (
    <canvas
      ref={ref}
      className={styles.layer}
      data-testid="orientation-footprint"
      data-flip-x={String(flipX)}
      data-flip-y={String(flipY)}
      aria-hidden="true"
    />
  );
}

/** A card's overlay: the same dots and outlines at thumbnail scale, drawn once per payload. */
function ThumbCanvas({
  points,
  regions,
  canvas,
}: {
  points: number[];
  regions: RegionRecord[];
  canvas: { w: number; h: number } | null;
}) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const cvs = ref.current;
    if (!cvs || !canvas || canvas.w <= 0) return;
    const s = THUMB_W / canvas.w;
    const h = Math.max(1, Math.round(canvas.h * s));
    if (cvs.width !== THUMB_W || cvs.height !== h) {
      cvs.width = THUMB_W;
      cvs.height = h;
    }
    const g = cvs.getContext('2d');
    if (!g) return;
    g.clearRect(0, 0, THUMB_W, h);

    g.strokeStyle = REGION;
    g.lineWidth = 1.5;
    for (const r of regions) {
      g.strokeRect(r.x * s, r.y * s, r.w * s, r.h * s);
    }

    const path = new Path2D();
    for (let i = 0; i < points.length; i += 2) {
      const px = points[i] * s;
      const py = points[i + 1] * s;
      path.moveTo(px + 1.4, py);
      path.arc(px, py, 1.4, 0, Math.PI * 2);
    }
    g.fillStyle = DOT;
    g.fill(path);
  }, [points, regions, canvas]);

  return <canvas ref={ref} className={styles.thumbLayer} aria-hidden="true" />;
}
