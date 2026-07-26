import { useEffect, useMemo, useState } from 'react';
import { useSweepStore, tileOf } from '../../store';
import {
  detectRun,
  getThumbsLayout,
  rescopeDocument,
  thumbsPngUrl,
  type MosaicDocument,
  type RunDetection,
  type ThumbsResponse,
} from '../../../../api';
import { useToast } from '../../../../app';
import { Button, Help } from '../../../../design';
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
  'Apply re-scopes the project to the trials in range: the ones outside it stop being tiles of this ' +
  'mosaic.\n\nEvery tile that stays keeps its position and your judgement. A tile that leaves takes its ' +
  'position with it, and a changed trial list makes the build stale — it was solved on a different set.';
const OUT_HELP =
  'Red = not a tile of this mosaic.\n\nEither it falls outside the range you set, or the frame itself ' +
  'cannot be a tile (wrong shape, or no readable frame on disk). Hover a red cell to see which.\n\nThey ' +
  'are NOT excluded — they were never part of this mosaic. Excluding is `E`, in the sweep, and yours.';

/** How long to wait after a keystroke before re-measuring the run for the typed range (ms). */
const PREVIEW_DEBOUNCE = 250;

/**
 * 2 · RANGE — "which trials are the mosaic?" (BEHAVIOUR §2 step 2).
 *
 * A numbers-only facts strip — **Trials · Range · Gaps** — every explanation behind its `?` (R4.6). The
 * run is MEASURED from the session's inventory (never a hard-coded number — I1/R2).
 *
 * ⭐ **THE PASS SPLIT IS NOT SHOWN OR EDITED HERE** (2026-07-24). A pause in the log is not a second
 * pass, so the split is not a user concern: it stays a purely INTERNAL detail of the cold first-draft
 * build (`t33.Config.pass_split`), auto-detected and carried on the document. If the guess is ever
 * wrong, the human corrects it with anchors + Recompute — the human-in-the-loop is the fix. See
 * `utils/knowledge/mosaic-builder-direction.md`.
 *
 * ⭐ **THE CONTACT SHEET SAYS WHICH SNAPSHOTS ARE NOT TILES OF THIS MOSAIC** (2026-07-24, his ask): a
 * project opens on every square snapshot the dataset holds, and a real acquisition has strays taken
 * before the scan started (`1`, `5-7` ahead of the run on 260620d). They get a **red frame** and are not
 * clickable — hovering says whether they fall outside the range or cannot be a tile at all (wrong shape,
 * no readable frame). The marking is LIVE against the `lo`/`hi` he is typing, re-measured by the server
 * (`POST /api/mosaic/run` — milliseconds), so the range he types is the range he sees.
 * ⛔ Red is **not** excluded. Nothing here excludes anything; `E` in the sweep is his, and only his.
 *
 * `Apply` then makes it stick — `POST /api/mosaic/document/rescope` re-authors the tile set ON THE
 * SERVER (never in the browser) and the sweep re-hydrates on the answer.
 *
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
  const [preview, setPreview] = useState<RunDetection | null>(null);
  const [thumbs, setThumbs] = useState<ThumbsResponse | null>(null);
  const [lo, setLo] = useState('');
  const [hi, setHi] = useState('');
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

  // Seed the range inputs from the detection (and re-seed after a re-detect).
  useEffect(() => {
    if (!detection) return;
    setLo(String(detection.lo));
    setHi(String(detection.hi));
  }, [detection]);

  // ⭐ LIVE: re-measure the run for the range he is TYPING, so the red frames answer the number under
  // his cursor and not the one he last applied. The route is a pure function of the session's inventory
  // (milliseconds, no reload) — but it is still a round trip, so it is debounced.
  // ⛔ The membership rule stays on the SERVER: which frames can be tiles is `log.txt` + the per-trial
  // XML shape, and the browser must not grow a second opinion about it.
  useEffect(() => {
    if (!sessionId) return;
    const loN = Number(lo);
    const hiN = Number(hi);
    if (lo === '' || hi === '' || !Number.isFinite(loN) || !Number.isFinite(hiN) || loN > hiN)
      return;
    let cancelled = false;
    const id = window.setTimeout(() => {
      detectRun({ session_id: sessionId, lo: loN, hi: hiN }).then(
        (d) => {
          if (!cancelled) setPreview(d);
        },
        () => {
          /* soft: the sheet falls back to the applied detection */
        },
      );
    }, PREVIEW_DEBOUNCE);
    return () => {
      cancelled = true;
      window.clearTimeout(id);
    };
  }, [sessionId, lo, hi]);

  const scope = preview ?? detection;

  /** The trials that ARE tiles of this mosaic, as measured for the range in the inputs. */
  const inMosaic = useMemo(() => new Set(scope?.trials ?? order), [scope, order]);

  /** Why a frame is not one — the server's own reason, verbatim where it has one. */
  const whyOut = useMemo(() => {
    const m = new Map<number, string>();
    for (const d of scope?.dropped ?? []) {
      m.set(
        d.trial,
        d.reason === 'off_shape'
          ? `not a tile: the frame is ${d.w}×${d.h}, not square`
          : 'not a tile: no readable single-frame snapshot on disk',
      );
    }
    return m;
  }, [scope]);

  const outsideRange = (t: number): boolean => !!scope && (t < scope.lo || t > scope.hi);
  const reasonFor = (t: number): string =>
    whyOut.get(t) ?? (scope ? `outside the range ${scope.lo}–${scope.hi}` : 'not in the mosaic');

  const nOut = (thumbs?.trials ?? []).filter((t) => !inMosaic.has(t)).length;

  /** The placed work that would LEAVE if he applied this range — what the confirm must name. */
  const placedLeaving = useMemo(() => {
    if (!doc || !scope) return [];
    return order.filter((t) => !inMosaic.has(t) && tileOf(doc.tiles, t)?.x != null);
  }, [doc, order, scope, inMosaic]);

  const trialRange = doc?.trial_range ?? (detection ? [detection.lo, detection.hi] : null);
  const rangeText = trialRange ? `${trialRange[0]}–${trialRange[1]}` : '—';
  const trialsN = detection?.n ?? order.length;
  const gaps = doc?.gaps ?? [];
  const gapsText = gaps.length ? gaps.map(([a, b]) => `${a}→${b}`).join(', ') : 'none';

  async function apply() {
    const loN = Number(lo);
    const hiN = Number(hi);
    if (!Number.isFinite(loN) || !Number.isFinite(hiN)) {
      toast.push('lo and hi must be numbers.', { tone: 'danger' });
      return;
    }
    if (loN > hiN) {
      toast.push('lo must not be above hi.', { tone: 'danger' });
      return;
    }
    // ⚠️ DESTRUCTIVE only for the tiles that LEAVE — say what actually dies, in one line, and let him
    // stop. (It used to warn that everything on the canvas was discarded. It is not: a re-scope keeps
    // every surviving tile's position and judgement, and over-warning teaches him to click through.)
    if (placedLeaving.length) {
      const shown = placedLeaving.slice(0, 8).join(', ') + (placedLeaving.length > 8 ? ' …' : '');
      if (
        !window.confirm(
          `${placedLeaving.length} placed tile(s) fall outside ${loN}–${hiN} and leave the mosaic ` +
            `(${shown}). Their positions are discarded. Continue?`,
        )
      )
        return;
    }
    setApplying(true);
    try {
      if (onApplyRange) {
        await onApplyRange(loN, hiN, null); // the shell re-scopes; the pass split is auto-detected
        return;
      }
      const cur = useSweepStore.getState().doc;
      if (!sessionId || !cur) {
        toast.push('Open a project first.', { tone: 'danger' });
        return;
      }
      // ⭐ THE SERVER RE-AUTHORS THE TILE SET. The document is never built in the browser (that is how
      // v1 dropped the human-edit counters), and a changed trial list also changes the GAPS and stales
      // the build — one route does all three. The pass split is auto-detected for the new range: it is
      // an internal build detail now, not a user override (2026-07-24).
      const res = await rescopeDocument({
        session_id: sessionId,
        doc: cur as MosaicDocument,
        lo: loN,
        hi: hiN,
      });
      // Adopt it: re-hydrate the sweep spine on the new tile set, then push it through the store's own
      // persistence hook — the same seam an A/E judgement uses — so auto-save keeps it.
      const s = useSweepStore.getState();
      s.hydrate(res.doc, { sessionId: s.sessionId });
      useSweepStore.getState().hooks.onChange?.(res.doc, { judgement: false });
      setDetection(res.run);
      setPreview(res.run);

      const bits = [`${res.n_trials} trials in the mosaic`];
      if (res.n_removed) bits.push(`${res.n_removed} dropped`);
      if (res.n_added) bits.push(`${res.n_added} added`);
      if (res.doc.build?.stale) bits.push('the build is stale — place again');
      toast.push(`Range applied: ${bits.join(' · ')}.`, { tone: 'good' });
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
        <Button onClick={apply} disabled={applying} data-testid="range-apply">
          Apply
        </Button>
        <span className={styles.applyHelp}>
          <Help body={APPLY_HELP} />
        </span>
      </div>

      <h2 className={shell.h2}>
        Contact sheet
        <Help body={OUT_HELP} />
      </h2>
      {sprite && thumbs ? (
        <>
          <div className={styles.sheetWrap}>
            <div className={styles.sheet} data-testid="contact-sheet">
              {thumbs.trials.map((t, i) => {
                const col = i % thumbs.grid;
                const row = Math.floor(i / thumbs.grid);
                const out = !inMosaic.has(t);
                return (
                  <button
                    key={t}
                    type="button"
                    className={styles.cell}
                    data-testid="contact-cell"
                    data-trial={t}
                    // ⭐ the red frame, and WHY it is red — the two causes are told apart on hover.
                    data-out={out || undefined}
                    data-out-reason={out ? (outsideRange(t) ? 'range' : 'unusable') : undefined}
                    title={out ? `trial ${t} — ${reasonFor(t)}` : `trial ${t}`}
                    // Not a tile of this mosaic ⇒ there is nothing to sweep. It stays visible, and it
                    // stays hoverable, but it does not pretend to be a destination.
                    disabled={out}
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
          <p className={styles.legend} data-testid="sheet-legend">
            <span className={styles.swatch} aria-hidden="true" />
            {nOut > 0 ? (
              <>
                <b data-testid="sheet-n-out">{nOut}</b> of {thumbs.trials.length} snapshots are not
                tiles of this mosaic
                {scope ? ` (outside ${scope.lo}–${scope.hi}, or not a usable frame)` : ''}. Apply
                drops them.
              </>
            ) : (
              <>
                Every loaded snapshot is a tile of this mosaic
                {scope ? ` (${scope.lo}–${scope.hi})` : ''}.
              </>
            )}
          </p>
        </>
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
