// ─────────────────────────────────────────────────────────────────────────────────────────────
// STEP 5 · SWEEP — ⭐ THE HEART OF THE APP.  (docs/BEHAVIOUR.md §2 Sweep, R9–R25, R33, §3.)
//
// The sweep IS the stage: the canvas plus both rails, with the status-bar readout beneath (R4.7). It is
// keyboard-first — Space advances, A anchors, E excludes, digits pick alternatives, D toggles Difference,
// arrows nudge — over a one-second fade. Every judgement flows through the ALREADY-BUILT sweep store; this
// component holds the JSX and the wiring, and the store holds the spine.
//
// THE ONE DISPATCH POINT (§3.4): the viewer mounts with `bindKeys:false`; this component's single window
// keydown handler runs `mapSweepKey` first and hands the rest to `viewer.handleKey` — so `D` toggles
// Difference exactly once. Ctrl+S is NOT handled here: the shell's SaveController owns it globally (R5.2),
// and a second binding would save twice.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { useEffect, useRef, useState } from 'react';
import type { CanvasHTMLAttributes } from 'react';
import { Viewer } from '../../../../core/viewer';
import type { ViewerHandle } from '../../../../core/viewer';
import { useSweepStore } from '../../store';
import { mapSweepKey } from '../../keys';
import type { SweepKeyAction } from '../../keys';
import { useViewerSync } from './viewerSync';
import { SweepOverlay } from './SweepOverlay';
import { LeftRail } from './LeftRail';
import { RightRail } from './RightRail';
import { StatusRow } from './StatusRow';
import type { ToneControl } from './LeftRail';
import type { WizardStepProps } from '../types';
import styles from './SweepStep.module.css';

const LAYERS = [
  { key: 'anchor', reference: true }, // the certified field — the Difference reference (R9/§3.5)
  { key: 'unverified', visible: false }, // maintained but NOT drawn in the sweep (R9.4)
] as const;

export interface SweepStepProps extends WizardStepProps {
  /** Build the pixel URL for a trial. The cache-buster (`{nonce}.{tone_version}`) is the session
   *  owner's — R31/R32; this component only calls it. The shell passes it for the Sweep. */
  tileSrc: (trial: number) => string;
  /** Optional global tone controls (display only — R18). If absent, the tone panel is inert. */
  tone?: ToneControl;
}

/** Route a decoded key action to the store. Ctrl+S is the shell's (see the header). */
function dispatch(a: SweepKeyAction): void {
  const s = useSweepStore.getState();
  switch (a.kind) {
    case 'advance':
      void s.advance();
      break;
    case 'anchor':
      void s.anchor();
      break;
    case 'exclude':
      void s.exclude();
      break;
    case 'replay':
      s.replay();
      break;
    case 'alternatives':
      void s.showAlternatives();
      break;
    case 'snap':
      void s.snap();
      break;
    case 'jump':
      void s.jumpToRank(a.rank);
      break;
    case 'undo':
      s.undo();
      break;
    case 'redo':
      s.redo();
      break;
    case 'save':
      break; // the shell's SaveController owns Ctrl+S globally (R5.2)
  }
}

export function SweepStep({ tileSrc, tone, onNavigate }: SweepStepProps) {
  const viewerRef = useRef<ViewerHandle>(null);
  const [anchorLayer, setAnchorLayer] = useState(0);
  const [unverifiedDrawn, setUnverifiedDrawn] = useState(false);
  const [perf, setPerf] = useState({ ms: 0, fps: 0 });

  const doc = useSweepStore((s) => s.doc);

  // Land the cursor on the first non-excluded trial so the status bar never reads "trial —" (R14).
  useEffect(() => {
    if (doc) useSweepStore.getState().ensureCursor();
  }, [doc]);

  useViewerSync(viewerRef, tileSrc);

  // The single dispatch point (§3.4). One window keydown; camera keys fall through to the engine.
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      const action = mapSweepKey(e, 'sweep');
      if (action) {
        if (action.kind === 'save') return; // the shell owns Ctrl+S
        e.preventDefault();
        dispatch(action);
        return;
      }
      const el = e.target as HTMLElement | null;
      const tag = el?.tagName ?? '';
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(tag) || el?.isContentEditable) return;
      viewerRef.current?.handleKey(e);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // The live ms/frame · fps readout (R20). Sampled off the RAF loop, not inside it.
  useEffect(() => {
    const id = setInterval(() => {
      const s = viewerRef.current?.stats();
      if (s) setPerf({ ms: s.ms, fps: s.fps });
    }, 300);
    return () => clearInterval(id);
  }, []);

  // The live data-* attributes the specs read off the <canvas> (R9). Typed as a data-* record so they
  // satisfy the viewer's `CanvasHTMLAttributes` prop (which carries no data-* index signature itself).
  const canvasProps: CanvasHTMLAttributes<HTMLCanvasElement> &
    Record<`data-${string}`, string | number> = {
    'data-testid': 'sweep-canvas',
    'data-anchor-layer': anchorLayer,
    'data-unverified-drawn': String(unverifiedDrawn),
  };

  return (
    <div className={styles.stage} data-testid="stage">
      <LeftRail tone={tone} onGoToTrial={(t) => useSweepStore.getState().setCursor(t)} />

      <div className={styles.canvasArea}>
        <Viewer
          ref={viewerRef}
          layers={LAYERS.map((l) => ({ ...l }))}
          canvasProps={canvasProps}
          onModelChange={(m) => {
            setAnchorLayer(m.layers.anchor?.placed ?? 0);
            setUnverifiedDrawn(m.layers.unverified?.visible ?? false);
          }}
          onDragEnd={(id, x, y) => useSweepStore.getState().move(Number(id), [x, y])}
          onSelect={(id) => {
            // 🔴 R14 — Esc reports onSelect(null); it must NOT abandon the tile under judgement.
            if (id !== null) useSweepStore.getState().setCursor(Number(id));
          }}
          onAlternativePick={(id, c) => {
            const ev = useSweepStore.getState().evidence[String(id)];
            const full = ev?.candidates.find((k) => k.rank === c.rank);
            if (full) useSweepStore.getState().pickAlternative(Number(id), full);
          }}
          onDifference={(on) => useSweepStore.getState().setDiff(on)}
        />
        <SweepOverlay viewerRef={viewerRef} onNavigate={onNavigate} />
      </div>

      <RightRail onGoToTrial={(t) => useSweepStore.getState().setCursor(t)} />

      <StatusRow msPerFrame={perf.ms} fps={perf.fps} />
    </div>
  );
}
