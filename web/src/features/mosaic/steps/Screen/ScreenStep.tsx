import { useCallback, useEffect, useState } from 'react';
import { useSweepStore } from '../../store';
import {
  proposeScreen,
  useSession,
  cacheBuster,
  tilePngUrl,
  type BlankProposal,
  type BlankScanBlock,
} from '../../../../api';
import { useToast } from '../../../../app';
import { Button, cx } from '../../../../design';
import { patchWorkingDoc } from '../mutate';
import { FactsStrip, Fact } from '../Fact';
import type { ScreenStepProps } from '../types';
import shell from '../step.module.css';
import styles from './ScreenStep.module.css';

type Choice = 'keep' | 'hand' | 'exclude';

const CALL_HELP =
  'KEEP — the frame is in the mosaic and the matcher places it.\n\n' +
  'HAND PLACE — the frame is in the mosaic, but the matcher will NOT position it. You do, in the ' +
  'sweep. This is the default on a scanned frame: a near-featureless frame does not align on tissue, ' +
  'it aligns on SENSOR pattern, so two of them register confidently and WRONGLY.\n\n' +
  'EXCLUDE — the frame is thrown out of the mosaic entirely. Not drawn, not matched, not exported. It ' +
  'opens an acquisition gap and marks any existing build stale.\n\n' +
  'The measure has no margin at the boundary — usable and blank frames interleave below it. Look at ' +
  'the thumbnail and decide. Nothing is auto-excluded, ever.';

const fmt1 = (n: number | null | undefined): string => (n == null ? '—' : n.toFixed(1));
const fmt2 = (n: number | null | undefined): string => (n == null ? '—' : n.toFixed(2));

/**
 * 3 · SCREEN — "which frames do you want thrown out?" (BEHAVIOUR §2 step 3, R6/R6b).
 *
 * ONE control, THREE mutually-exclusive buttons per scanned frame — **Keep · Hand place · Exclude** —
 * with Hand place the default (R6.1/R6.2). The choice APPLIES IMMEDIATELY, no Apply button (R6.5).
 *
 * 🔴 THE CARD RE-DERIVES FROM LIVE TILE STATE EVERY RENDER (R6.6): `data-choice` is computed from the
 * document the sweep store holds, never a variable kept in step — so pressing `E` on this frame in the
 * sweep, an undo, or a resume all show up here correctly. The card claims to BE the state.
 *
 * 🔴 TWO MECHANISMS, KEPT SEPARATE (R6.4): `Exclude` drives the TILE STATE (via the store, which also
 * recomputes the live gaps and the stale cascade); `Keep` vs `Hand place` drives the REFUSAL LIST
 * (`doc.blank_scan` + the matcher's live `refuse`). Conflating them once lifted the refusal on a frame
 * that genuinely misleads the matcher.
 *
 * ⛔ NO bulk buttons (R6b) and NO blur score anywhere (R17). The scan recommends; the human decides.
 */
export function ScreenStep({ onNavigate }: ScreenStepProps) {
  const doc = useSweepStore((s) => s.doc);
  const order = useSweepStore((s) => s.order);
  const sessionId = useSweepStore((s) => s.sessionId);
  const toast = useToast();

  const [proposal, setProposal] = useState<BlankProposal | null>(null);
  const passSplit = doc?.pass_split ?? null;

  const sessionState = useSession(sessionId);
  const version = sessionState.status === 'ready' ? cacheBuster(sessionState.session) : null;

  // The blank RECOMMENDATION (`POST /api/mosaic/screen/propose`). It recommends only what the code is
  // sure of (near-featureless frames); it never auto-excludes. A measurement, so fetch it once the
  // run + pass split are known.
  useEffect(() => {
    if (!sessionId || order.length === 0) return;
    let cancelled = false;
    proposeScreen({ session_id: sessionId, trials: order, pass_split: passSplit }).then(
      (p) => {
        if (!cancelled) setProposal(p);
      },
      () => {
        /* no proposal is a soft failure — the step still lets the user exclude by hand */
      },
    );
    return () => {
      cancelled = true;
    };
  }, [sessionId, order, passSplit]);

  /**
   * The refusal must reach the document (R6.7). On arrival establish the SAFE DEFAULT — every proposed
   * frame refused (Hand), nothing overruled, nothing excluded. Refusing is NOT excluding (R16): it opens
   * no gap and throws nothing out. Idempotent: it fires once, and again on the way to Place.
   */
  const ensureRefusalEstablished = useCallback(() => {
    if (!proposal) return;
    const current = useSweepStore.getState().doc;
    if (!current) return;
    const existing = current.blank_scan;
    if (existing?.scanned !== undefined) return; // already established
    const scanned = proposal.proposed;
    const overruled = existing?.overruled_by_user ?? [];
    const overruledSet = new Set(overruled);
    const blank = scanned.filter((t) => !overruledSet.has(t));
    patchWorkingDoc(
      {
        blank_scan: {
          ...existing,
          measure: existing?.measure ?? proposal.measure,
          threshold: existing?.threshold ?? proposal.threshold,
          scanned,
          blank,
          overruled_by_user: overruled,
          accepted: existing?.accepted ?? false,
        },
      },
      blank,
    );
  }, [proposal]);

  useEffect(() => {
    ensureRefusalEstablished();
  }, [ensureRefusalEstablished]);

  const overruled = doc?.blank_scan?.overruled_by_user ?? [];

  /** The frame's fate RIGHT NOW, from live state (v1's `choiceOf`) — this is what makes the card the
   *  state and not a stale request (R6.6). */
  function choiceOf(trial: number): Choice {
    const tile = doc?.tiles[String(trial)];
    if (tile?.state === 'excluded') return 'exclude';
    return overruled.includes(trial) ? 'keep' : 'hand';
  }

  /** Update ONLY the refusal list — Keep lifts the refusal; Hand and Exclude leave the frame refused. */
  function updateRefusal(trial: number, choice: Choice): void {
    if (!proposal) return;
    const current = useSweepStore.getState().doc;
    if (!current) return;
    const scan: BlankScanBlock | undefined = current.blank_scan;
    const scanned = scan?.scanned?.length ? scan.scanned : proposal.proposed;
    const overruledSet = new Set(scan?.overruled_by_user ?? []);
    if (choice === 'keep') overruledSet.add(trial);
    else overruledSet.delete(trial);
    const overruledList = [...overruledSet].sort((a, b) => a - b);
    const blank = scanned.filter((t) => !overruledSet.has(t)).sort((a, b) => a - b);
    patchWorkingDoc(
      {
        blank_scan: {
          ...scan,
          measure: scan?.measure ?? proposal.measure,
          threshold: scan?.threshold ?? proposal.threshold,
          scanned,
          blank,
          overruled_by_user: overruledList,
          accepted: true,
        },
      },
      blank,
    );
  }

  async function setChoice(trial: number, choice: Choice): Promise<void> {
    const store = useSweepStore.getState();
    const current = store.doc;
    if (!current) return;
    const wasExcluded = current.tiles[String(trial)]?.state === 'excluded';

    // 1 — the TILE STATE (the store owns gaps + persistence + the stale cascade).
    if (choice === 'exclude' && !wasExcluded) await store.excludeAt(trial);
    else if (choice !== 'exclude' && wasExcluded) store.unexclude(trial);

    // 2 — the REFUSAL LIST (a separate mechanism, kept separate — R6.4).
    updateRefusal(trial, choice);

    // 3 — one line of acknowledgement (a toast, not a live warning).
    const note =
      choice === 'exclude'
        ? `Excluded ${trial}.`
        : choice === 'keep'
          ? `Trial ${trial}: the matcher will place it.`
          : `Trial ${trial}: you place it, in the sweep.`;
    toast.push(note, { tone: 'default' });
  }

  function placeNext(): void {
    ensureRefusalEstablished(); // R6.7 — the refusal reaches the document on the way to Place
    onNavigate('place');
  }

  const recommendHelp = proposal
    ? [proposal.measure, proposal.threshold_source, proposal.margin_warning]
        .filter(Boolean)
        .join('\n\n')
    : '';
  const proposed = proposal?.proposed ?? [];

  return (
    <div className={shell.pane}>
      <header className={shell.head}>
        <h1 className={shell.h1}>Screen</h1>
        <p className={shell.lede}>Look at each frame. Nothing is decided for you.</p>
      </header>

      <FactsStrip testid="screen-facts">
        <Fact
          label="Recommended"
          help={recommendHelp}
          value={proposal?.n_proposed ?? '—'}
          valueTestid="fact-recommended"
        />
        <Fact label="Threshold" value={fmt2(proposal?.threshold)} valueTestid="fact-threshold" />
        <Fact
          label="Your call, per frame"
          help={CALL_HELP}
          value={
            <span className={styles.callValue}>keep &middot; hand place &middot; exclude</span>
          }
          wide
        />
      </FactsStrip>

      <div className={styles.grid} data-testid="screen-grid">
        {proposed.length === 0 ? (
          <div className={shell.muted}>{proposal ? 'Nothing recommended.' : 'Scanning…'}</div>
        ) : (
          proposed.map((t) => {
            const choice = choiceOf(t);
            return (
              <div
                key={t}
                className={styles.card}
                data-testid="screen-card"
                data-trial={t}
                data-choice={choice}
              >
                <div className={styles.cardHead}>
                  trial <b className={styles.cardTrial}>{t}</b>
                </div>
                {version && sessionId ? (
                  <img
                    className={styles.thumb}
                    src={tilePngUrl(sessionId, t, version)}
                    alt={`trial ${t}`}
                    loading="lazy"
                  />
                ) : (
                  <div className={cx(styles.thumb, styles.noThumb)}>no frame</div>
                )}
                <div className={styles.texture} data-testid="screen-card-texture">
                  texture {fmt1(proposal?.texture[String(t)])}
                </div>
                <div className={styles.choice} role="radiogroup" aria-label={`trial ${t}`}>
                  <ChoiceBtn
                    label="Keep"
                    testid="screen-keep"
                    active={choice === 'keep'}
                    onClick={() => void setChoice(t, 'keep')}
                  />
                  <ChoiceBtn
                    label="Hand place"
                    testid="screen-handplace"
                    active={choice === 'hand'}
                    onClick={() => void setChoice(t, 'hand')}
                  />
                  <ChoiceBtn
                    label="Exclude"
                    testid="screen-exclude"
                    active={choice === 'exclude'}
                    danger
                    onClick={() => void setChoice(t, 'exclude')}
                  />
                </div>
              </div>
            );
          })
        )}
      </div>

      <div className={shell.stepnav}>
        <Button variant="ghost" onClick={() => onNavigate('range')}>
          &larr; Range
        </Button>
        <span className={shell.spacer} />
        <Button variant="primary" onClick={placeNext} data-testid="screen-place-next">
          Place the tiles &rarr;
        </Button>
      </div>
    </div>
  );
}

/** One segment of the three-way control. A real pressed state so exactly one reads selected (R6.1). */
function ChoiceBtn({
  label,
  testid,
  active,
  danger,
  onClick,
}: {
  label: string;
  testid: string;
  active: boolean;
  danger?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={cx(styles.seg, active && styles.segOn, danger && active && styles.segDanger)}
      aria-pressed={active}
      data-testid={testid}
      onClick={onClick}
    >
      {label}
    </button>
  );
}
