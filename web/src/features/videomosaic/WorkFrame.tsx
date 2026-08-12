// ─────────────────────────────────────────────────────────────────────────────────────────────
// ⭐ THE WORK FRAME (R47) — picture left, tools right, and nothing else scrolls.
//
// His complaint, 2026-08-12: *"it's hard to check whether the region placed correctly because the
// opacity slider is hard to access — the user has to scroll all the way down. I need all the tools
// to be accessible while the user is looking at the image."* He was right, and the cause was
// structural: every picture step was a 1100 px scroll column with a 68 vh viewer on top and its
// controls a screenful below. Sliding the overlay is how you check a placement, so the control and
// the thing it tests have to be visible at the same instant.
//
// So the three picture steps mount THIS instead: a two-pane frame that fills the window, where the
// rail is the only scroller on the page. One component on purpose — Mosaic, Electrodes and Regions
// sharing a frame by copy would drift, and the drift would read as "this tab looks different",
// which is the same reasoning that pulled `PreviewViewer` out of the feature in the first place.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import type { ReactNode } from 'react';
import styles from './VideoMosaicFeature.module.css';

export interface WorkFrameProps {
  /** The stage — a `PreviewViewer`, which takes the whole pane. */
  picture: ReactNode;
  /** The tools, in the order they are reached for. This is the only pane that scrolls. */
  rail: ReactNode;
  /** The step's own hook for the specs (`vm-step-regions`, …). */
  testId?: string;
}

export function WorkFrame({ picture, rail, testId }: WorkFrameProps) {
  return (
    <div className={styles.work} data-testid={testId}>
      <div className={styles.stage}>{picture}</div>
      <aside className={styles.rail} data-testid="vm-rail">
        {rail}
      </aside>
    </div>
  );
}
