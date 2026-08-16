// ─────────────────────────────────────────────────────────────────────────────────────────────
// ONE RECORDING, OPEN — *"you pick one to load, and it opens it up"* (his interview, 2026-08-14).
//
// ⭐ **ONE AT A TIME, AND THAT IS A DECISION, NOT A LIMITATION.** Comparing recordings side by
// side, overlaying two traces and averaging across pads were all explicitly rejected. This screen
// is one recording, one pad, one trace.
//
// It loads the two GETs the chip needs — the chip's own layout, and the per-pad tally — and hands
// them to `ChipMap`. ⭐ Both are plain GETs because I measured them: 2.3–21 ms end to end on the
// real 300 s recordings under `data/`, the worst being 982 channels against 244,925 spikes. Neither
// needed to be a job, so the picture is there on the first paint and there is no progress bar.
//
// ⚠️ **A recording is read from wherever it currently lives** — his original while the copy runs,
// the project's own copy once it has landed. That is decided once, on the server
// (`features/mea/recordings.py :: open_path`), so nothing here has to know or care.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { useCallback, useEffect, useRef, useState } from 'react';
import { meaChipActivity, meaChipLayout } from '../../api';
import type { MeaChipActivity, MeaChipLayout } from '../../api';
import { Button, Help, LiveWarning } from '../../design';
import { ChipMap } from './ChipMap';
import { formatSeconds } from './format';
import { MeaTrace } from './MeaTrace';
import styles from './OpenRecording.module.css';

/**
 * How long the view has to sit still before the chip is re-coloured for it. The trace panel
 * already settles its own fetch (90 ms) and reports only served data, so this only has to absorb
 * a walk through history — not every pointermove of a drag.
 */
const FOLLOW_SETTLE_MS = 150;

/** The `?` on the mode toggle (R7: a mode control earns one). Plain words, no jargon. */
const FOLLOW_VIEW_HELP =
  "Normally the chip's colours count every spike in the whole recording.\n" +
  '\n' +
  'Turn this on and the colours count only the stretch of time the trace panel is showing — ' +
  'zoom in on a burst and the chip shows which pads fired during it. The legend, the counts and ' +
  'the bars beside the map follow the same stretch, and the length written beside the no-spikes ' +
  "count switches to that stretch's length.\n" +
  '\n' +
  'Turn it off and the picture is the whole recording again.';

export interface OpenRecordingProps {
  analysisId: string;
  recordingId: string;
  /** Back to the shelf. */
  onClose: () => void;
}

export function OpenRecording({ analysisId, recordingId, onClose }: OpenRecordingProps) {
  const [layout, setLayout] = useState<MeaChipLayout | null>(null);
  const [activity, setActivity] = useState<MeaChipActivity | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [channel, setChannel] = useState<number | null>(null);
  // ── "Colors follow the view" (2026-08-16) ───────────────────────────────────────────────────
  // Default OFF: the whole-recording picture is the settled default and the mode is a choice.
  const [followView, setFollowView] = useState(false);
  /** The stretch the trace panel is actually showing (its SERVED range), or null = the whole. */
  const [traceView, setTraceView] = useState<{ t0: number; t1: number } | null>(null);
  /** The windowed tally the chip is coloured by while following; null = use the whole recording. */
  const [viewActivity, setViewActivity] = useState<MeaChipActivity | null>(null);
  /**
   * ⭐ **THE COLOURS ON SCREEN ARE THE PREVIOUS STRETCH'S, AND THEY SAY SO** (R48.10, 2026-08-16).
   * "Colors follow the view" is a promise, and for the ~200 ms between a zoom and its windowed
   * tally landing the chip was quietly still coloured by the stretch he had just left — while the
   * chart beside it correctly dimmed and badged `previous`. Same pattern, same word: this is the
   * house answer for a sub-second interactive read, and R48 explicitly says NOT to put a bar here.
   */
  const [followPending, setFollowPending] = useState(false);
  // The existing ticket idiom (MeaTrace's): a late windowed reply holding a stale ticket is
  // dropped, so a slow wide request can never recolour the view he already left.
  const followTicket = useRef(0);

  useEffect(() => {
    let cancelled = false;
    setLayout(null);
    setActivity(null);
    setError(null);
    setChannel(null);
    setTraceView(null);
    setViewActivity(null);
    followTicket.current++;
    void Promise.all([
      meaChipLayout(analysisId, recordingId),
      meaChipActivity(analysisId, recordingId),
    ])
      .then(([l, a]) => {
        if (cancelled) return;
        setLayout(l);
        setActivity(a);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [analysisId, recordingId]);

  /** What the trace panel reports — kept identity-stable so an unchanged range refires nothing. */
  const onTraceView = useCallback((w: { t0: number; t1: number } | null) => {
    setTraceView((prev) =>
      prev === w || (prev != null && w != null && prev.t0 === w.t0 && prev.t1 === w.t1) ? prev : w,
    );
  }, []);

  // ── the follow fetch: debounced, ticketed, honest ───────────────────────────────────────────
  // Off, or on the whole recording, the windowed tally is CLEARED rather than left stale — the
  // chip falls back to the whole-recording activity it opened with. A reply that fails clears it
  // too: wrong-but-current colours claiming to follow the view would be a quiet lie, and the
  // legend's wording follows the same object, so screen and words always move together.
  useEffect(() => {
    const mine = ++followTicket.current;
    if (!followView || traceView == null) {
      setViewActivity(null);
      setFollowPending(false);
      return;
    }
    // R48.10 — from this moment the colours under him are the OLD window's, and the badge below
    // says so until the new tally lands. Set before the settle, not inside it: the stretch he is
    // looking at has already changed, and that is when the picture stops being current.
    setFollowPending(true);
    const timer = setTimeout(() => {
      void meaChipActivity(analysisId, recordingId, { t0: traceView.t0, t1: traceView.t1 })
        .then((a) => {
          if (mine !== followTicket.current) return;
          setViewActivity(a);
          setFollowPending(false);
        })
        .catch(() => {
          if (mine !== followTicket.current) return;
          setViewActivity(null);
          setFollowPending(false);
        });
    }, FOLLOW_SETTLE_MS);
    return () => clearTimeout(timer);
  }, [followView, traceView, analysisId, recordingId]);

  return (
    <section className={styles.open} data-testid="mea-open-recording">
      <header className={styles.head}>
        <Button size="sm" variant="ghost" onClick={onClose} data-testid="mea-close-recording">
          ← All recordings
        </Button>
        <h2 className={styles.title} data-testid="mea-open-label">
          {layout?.label || '…'}
        </h2>
        {layout && (
          <span className={styles.facts} data-testid="mea-open-facts">
            {formatSeconds(layout.duration_s)} · {layout.n_channels.toLocaleString()} channels ·{' '}
            {layout.n_spikes.toLocaleString()} spikes
          </span>
        )}
        {/* ⭐ MAXWELL §7.6: the file's total counts every spike the detector logged; the chip map
            can only colour the ones whose channel is in the routed mapping, and on real files the
            two genuinely differ (22,367 vs 15,688 on one of his). Said whenever non-zero, beside
            the total — ⛔ never "fixed" by printing only the placed total, which §7.6 forbids. */}
        {layout && activity && (activity.n_spikes_unplaced ?? 0) > 0 && (
          <span className={styles.unplaced} data-testid="mea-open-unplaced">
            {(activity.n_spikes_unplaced ?? 0).toLocaleString()} of them could not be placed on the
            chip
          </span>
        )}
      </header>

      {/* 🔴 A recording that has lost its file refuses to open and SAYS SO, naming it. Never an
          empty chip map — a chip drawn with no dots is indistinguishable from a chip on which
          nothing happened, and that would be a lie about his data. */}
      {error && (
        <LiveWarning variant="loud">
          <span data-testid="mea-open-error">{error}</span>
        </LiveWarning>
      )}

      {/* ⭐ **THE WAVEFORM SITUATION, SAID ONCE, BEFORE ANY PAD IS CLICKED** (R3.8: a fact about
          his data, on the page — never behind a `?`). The server already knows at open time whether
          the MaxWell decode plug-in is on this machine, so nothing here springs it on him per
          trace. Quiet on purpose: the chip map and every spike count need no decoder and are
          exactly right — nothing on this screen is wrong. The per-trace warnings in MeaTrace stay;
          this is the same fact, a screen earlier, in the same words. */}
      {!error && layout && !layout.decoder_present && (
        <p className={styles.decoderNote} data-testid="mea-open-no-decoder">
          MaxWell compresses the raw recording with its own method, and the software that unpacks
          it (part of MaxLab Live) is not installed on this machine — so waveforms cannot be shown.
          The chip map and the spike marks come from the chip&rsquo;s own detector and are
          unaffected.
        </p>
      )}

      {!error && layout && activity && (
        <div className={styles.split}>
          <div className={styles.mapCol}>
            {/* ⭐ **COLORS FOLLOW THE VIEW** — zoom the trace and the chip re-colours by who fired
                in that stretch. Default OFF; a mode control, so it earns a `?` (R7). The legend
                and the spread re-band from the same windowed tally, so the words, the window
                length and the colours can never disagree. */}
            <div className={styles.followRow} data-testid="mea-follow-view">
              <label className={styles.follow}>
                <input
                  type="checkbox"
                  checked={followView}
                  onChange={(e) => setFollowView(e.target.checked)}
                  data-testid="mea-follow-view-tick"
                />
                Colors follow the view
              </label>
              <Help body={FOLLOW_VIEW_HELP} label="What 'Colors follow the view' does" />
              {/* ⭐ One word, exactly as on the trace beside it: what is coloured in is the stretch
                  he just left. ⛔ Not a bar — R48 names this read as one the picture answers. */}
              {followPending && (
                <span className={styles.staleBadge} data-testid="mea-follow-stale">
                  previous
                </span>
              )}
            </div>
            <div className={followPending ? `${styles.map} ${styles.stale}` : styles.map}>
              <ChipMap
                layout={layout}
                activity={viewActivity ?? activity}
                selected={channel}
                onSelect={setChannel}
              />
            </div>
          </div>
          <div className={styles.side}>
            <MeaTrace
              analysisId={analysisId}
              recordingId={recordingId}
              channel={channel}
              onViewChange={onTraceView}
            />
          </div>
        </div>
      )}
    </section>
  );
}
