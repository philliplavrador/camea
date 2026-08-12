// The canvas overlays (BEHAVIOUR R4.7/R4.8, §5): the running banner, the live-warning stack, the header
// counts, the seven action buttons (each with its own `?` — R7.1), and the camera controls. Everything
// here floats over the true-black stage; only the interactive bits catch the pointer.

import { useMemo } from 'react';
import type { RefObject, ReactNode } from 'react';
import type { ViewerHandle } from '../../../../core/viewer';
import {
  useSweepStore,
  counts,
  activeTrials,
  THIN_MARGIN,
  CONFIDENT_DISAGREE_PX,
  SMALL_APERTURE_MAX,
} from '../../store';
import { useDocument } from '../../../../store/documentStore';
import { Button, Help, LiveWarning, Badge, cx } from '../../../../design';
import { fmtNcc, fmtMargin, fmtXY } from './format';
import styles from './SweepOverlay.module.css';

export interface SweepOverlayProps {
  viewerRef: RefObject<ViewerHandle | null>;
  /** Move to the Place step to re-solve a stale build (W1). */
  onNavigate: (step: 'place') => void;
}

/** One action button + its own hover `?` (R7.1). The testid + optional toggle state sit on the wrapper
 *  so the `?` is a DESCENDANT of the tested control (R7.5 — the audit checks each control's OWN help). */
function Action({
  id,
  kbd,
  label,
  help,
  onClick,
  pressed,
}: {
  id: string;
  kbd: ReactNode;
  label: string;
  help: string;
  onClick: () => void;
  pressed?: boolean;
}) {
  return (
    <div className={styles.action} data-testid={id} aria-pressed={pressed}>
      <Button size="sm" kbd={kbd} onClick={onClick} className={pressed ? styles.actOn : undefined}>
        {label}
      </Button>
      <Help body={help} />
    </div>
  );
}

/** One live warning that STAYS on the page (never a tooltip — R3.8). The testid is on a wrapper so the
 *  LiveWarning primitive keeps its own role/styling. */
function Warn({
  id,
  variant,
  children,
}: {
  id: string;
  variant?: 'warn' | 'loud' | 'info';
  children: ReactNode;
}) {
  return (
    <div data-testid={id} className={styles.warnItem}>
      <LiveWarning variant={variant}>{children}</LiveWarning>
    </div>
  );
}

export function SweepOverlay({ viewerRef, onNavigate }: SweepOverlayProps) {
  const doc = useSweepStore((s) => s.doc);
  const order = useSweepStore((s) => s.order);
  const cursor = useSweepStore((s) => s.cursor);
  const banner = useSweepStore((s) => s.banner);
  const altsOn = useSweepStore((s) => s.altsOn);
  const diffMode = useSweepStore((s) => s.diffMode);
  const noAnchors = useSweepStore((s) => s.warnings.noAnchors);
  const evidence = useSweepStore((s) => s.evidence);
  const autosaveFailed = useDocument((s) => s.autosave.state === 'failed');
  const autosaveMsg = useDocument((s) => s.autosave.message);

  const c = useMemo(() => (doc ? counts(doc.tiles, order) : null), [doc, order]);

  const tile = cursor != null && doc ? doc.tiles[String(cursor)] : undefined;
  const ev = cursor != null ? evidence[String(cursor)] : undefined;

  // The reticle readout (§4): the four numbers he acts on — the tile or its last measurement.
  const readoutNcc = tile?.ncc ?? ev?.result.best?.ncc ?? null;
  const readoutMargin = tile?.margin ?? ev?.result.margin ?? null;

  // ── the build-stale check (W1): the active list ≠ what the solver was given ──────────────────────
  const buildStale = useMemo(() => {
    const build = doc?.build;
    if (!build) return null;
    const active = doc ? activeTrials(doc.tiles, order) : [];
    if (!build.trials) return { reason: 'the build did not record its trials.' };
    const excludedSince = build.trials.filter((t) => !active.includes(t));
    if (excludedSince.length === 0) return null;
    return {
      reason: `${excludedSince.length} excluded since the build (${excludedSince.join(', ')}).`,
    };
  }, [doc, order]);

  // ── current-tile warnings (§5) ───────────────────────────────────────────────────────────────────
  const blank = !!tile?.blank;
  const diverted = !!tile?.diverted;
  const smallAperture =
    tile?.n_anchors != null && tile.n_anchors <= SMALL_APERTURE_MAX && tile.x != null;
  const thinMargin =
    (tile?.margin != null && tile.margin < THIN_MARGIN) || !!ev?.result.margin_thin;
  const confidentDisagree =
    !!tile &&
    !tile.diverted &&
    tile.state === 'unverified' &&
    tile.machine != null &&
    tile.ncc != null &&
    (tile.moved_px ?? 0) > CONFIDENT_DISAGREE_PX;

  const rejected = tile?.rejected_match;

  const fit = () => viewerRef.current?.fit();
  const oneToOne = () => viewerRef.current?.oneToOne();
  const toggleDiff = () => viewerRef.current?.setDifference(!diffMode);

  return (
    <div className={styles.overlay} aria-hidden={false}>
      {/* TOP-LEFT: the loud commentary + the live-warning stack */}
      <div className={styles.topLeft}>
        {banner && (
          <div className={styles.banner} data-testid="banner" data-kind={banner.kind} role="status">
            {banner.message}
          </div>
        )}

        {noAnchors && (
          <Warn id="warn-no-anchors" variant="loud">
            <strong>No anchors left</strong> — press A on a placed tile to certify one. The matcher
            has nothing to match against.
          </Warn>
        )}

        {buildStale && (
          <div data-testid="build-stale-panel" className={styles.warnItem}>
            <div data-testid="warn-build-stale">
              <LiveWarning variant="loud">
                <strong>THE BUILD IS STALE.</strong> {buildStale.reason} The tiles either side of an
                excluded one were placed through it — re-solve, or knowingly do not.
                <button
                  type="button"
                  className={styles.inlineBtn}
                  data-testid="build-stale-resolve"
                  onClick={() => onNavigate('place')}
                >
                  Re-solve
                </button>
              </LiveWarning>
            </div>
          </div>
        )}

        {diverted && (
          <Warn id="warn-divert" variant="warn">
            <strong>SOLVER&apos;S POSITION, NOT THE MATCHER&apos;S.</strong>{' '}
            {tile?.divert_reason ?? 'The match was not trustworthy here.'}
            {rejected && (
              <>
                {' '}
                Matcher wanted {fmtXY(rejected.x, rejected.y)} —{' '}
                {rejected.ncc != null ? `NCC ${fmtNcc(rejected.ncc)}` : 'no NCC'}
                {tile?.moved_px != null ? `, ${Math.round(tile.moved_px)} px away` : ''}.
              </>
            )}
          </Warn>
        )}

        {confidentDisagree && (
          <Warn id="warn-confident-disagree" variant="warn">
            The anchor field disagrees with the solver by {Math.round(tile!.moved_px ?? 0)} px, but
            the match is confident (NCC {fmtNcc(tile?.ncc)}) — so the field wins. Check it (D)
            before you anchor.
          </Warn>
        )}

        {blank && (
          <Warn id="warn-refused-blank" variant="warn">
            <strong>REFUSED — blank.</strong> The matcher gets no vote here. Place it by hand, or
            exclude it; it will not S-snap.
          </Warn>
        )}

        {thinMargin && (
          <Warn id="warn-thin-margin" variant="loud">
            <strong>THIN MARGIN.</strong> best − second &lt; {THIN_MARGIN.toFixed(2)} — the
            signature of a surviving grid alias. Check D and V before you anchor.
          </Warn>
        )}

        {smallAperture && (
          <Warn id="warn-small-aperture" variant="warn">
            <strong>Small aperture ({tile?.n_anchors} anchors).</strong> Check it in Difference (D)
            before you anchor.
          </Warn>
        )}

        {autosaveFailed && (
          <Warn id="warn-autosave-failed" variant="loud">
            <strong>autosave: FAILED</strong>
            {autosaveMsg ? ` — ${autosaveMsg}` : ''} — save by hand (Ctrl+S).
          </Warn>
        )}
      </div>

      {/* TOP-RIGHT: header counts + camera */}
      <div className={styles.topRight}>
        <div className={styles.counts}>
          <Badge state="anchored">
            <span data-testid="header-anchored">{c?.anchored ?? 0}</span> anchored
          </Badge>
          <Badge state="unverified">
            <span data-testid="header-unverified">{c?.unverified ?? 0}</span> unverified
          </Badge>
          {!!c && c.diverted > 0 && (
            <Badge state="diverted">
              <span data-testid="header-diverted">{c.diverted}</span> diverted
            </Badge>
          )}
        </div>
        <div className={styles.camera}>
          <Button size="sm" variant="ghost" kbd="F" data-testid="sweep-fit" onClick={fit}>
            Fit
          </Button>
          <Button size="sm" variant="ghost" kbd="0" data-testid="sweep-oneone" onClick={oneToOne}>
            1:1
          </Button>
          <Button
            size="sm"
            variant="ghost"
            data-testid="sweep-undo"
            onClick={() => useSweepStore.getState().undo()}
          >
            Undo
          </Button>
          <Button
            size="sm"
            variant="ghost"
            data-testid="sweep-redo"
            onClick={() => useSweepStore.getState().redo()}
          >
            Redo
          </Button>
        </div>
      </div>

      {/* BOTTOM-LEFT: THE RETICLE READOUT (docs/DESIGN_BRIEF §4) — the only numbers he acts on: the
          tile's TOP-LEFT corner (R19), its NCC and its margin, in mono, red when the margin is thin.
          The corner reticle itself is drawn on the canvas (engine.drawChrome); this is its readout. */}
      {tile && (
        <div
          className={styles.readout}
          data-testid="sweep-readout"
          data-thin={thinMargin ? 'true' : undefined}
        >
          <div className={styles.roRow}>
            <span className={styles.roLabel}>TOP-LEFT</span>
            <span className={styles.roVal} data-testid="readout-topleft">
              {fmtXY(tile.x, tile.y)}
            </span>
          </div>
          <div className={styles.roRow}>
            <span className={styles.roLabel}>NCC</span>
            <span className={styles.roVal}>{fmtNcc(readoutNcc)}</span>
          </div>
          <div className={styles.roRow}>
            <span className={styles.roLabel}>MARGIN</span>
            <span className={cx(styles.roVal, thinMargin && styles.roBad)}>
              {fmtMargin(readoutMargin)}
            </span>
          </div>
        </div>
      )}

      {/* BOTTOM-RIGHT: the seven action controls, quieted and docked off the tissue (each keeps its own
          `?` — R7.1). The keyboard is the instrument; these are the mouse fallback, not a second legend. */}
      <div className={styles.actions}>
        <Action
          id="sweep-anchor"
          kbd="A"
          label="Anchor"
          onClick={() => void useSweepStore.getState().anchor()}
          help="Certify the tile under judgement at its current position — a TOGGLE. Press A again to un-certify it (it keeps its position). Nothing is ever auto-anchored."
        />
        <Action
          id="sweep-exclude"
          kbd="E"
          label="Exclude"
          onClick={() => void useSweepStore.getState().exclude()}
          help="Throw the tile out: not drawn, not matched, not exported. Recomputes the gaps. If it was an anchor, every tile judged after it is flagged stale."
        />
        <Action
          id="sweep-next"
          kbd="Space"
          label="Next"
          onClick={() => void useSweepStore.getState().advance()}
          help="Advance. The current tile is placed if it has nowhere to be, the next tile fades in over one second, and its match is prefetched. Space ALWAYS places; the rhythm never stalls."
        />
        <Action
          id="sweep-replay"
          kbd="R"
          label="Replay"
          onClick={() => useSweepStore.getState().replay()}
          help="Replay the one-second fade on the tile under judgement. It changes nothing — it is for looking again."
        />
        <Action
          id="sweep-difference"
          kbd="D"
          label="Difference"
          onClick={toggleDiff}
          pressed={diffMode}
          help="Composite |tile − field| against the certified field alone, clearing to black. Misalignment shows as bright doubling. It ignores the opacity slider."
        />
        <Action
          id="sweep-alternatives"
          kbd="V"
          label="Alternatives"
          onClick={() => void useSweepStore.getState().showAlternatives()}
          pressed={altsOn}
          help="Show the ranked runner-up positions as violet ghosts. Click one — or press its number — to move the tile there. The list is re-measured against the current anchor field."
        />
        <Action
          id="sweep-snap"
          kbd="S"
          label="Snap"
          onClick={() => void useSweepStore.getState().snap()}
          help="Re-run the matcher locally around where the tile now sits, against the anchors certified so far. The committed number is the server's. A blank tile refuses to snap."
        />
      </div>
    </div>
  );
}
