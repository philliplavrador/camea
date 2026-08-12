// The wizard-step contract, shared by the Load · Range · Screen step UIs (this task) and consumed by
// the wizard SHELL (`MosaicFeature`, another agent) that mounts them.
//
// The split of responsibility, so the steps stay thin (they hold the JSX; the store holds the spine):
//   • The SHELL owns step state, the R4 lock gate, and the session → document → hydrate lifecycle
//     (opening a dataset navigates to Range with the sweep store already hydrated — R4.5).
//   • A STEP BODY reads the working document from the sweep store, fetches its own session-derived
//     facts (detectRun / proposeScreen) off the store's `sessionId`, and asks the shell to move the
//     user on via `onNavigate`.
//
// Kept here (a plain .ts), not in a component file, so the step .tsx files export ONLY components
// (React Fast Refresh — `react-refresh/only-export-components`).

/** The wizard steps, by id (BEHAVIOUR R4.1 + the optional post-export Electrodes stage,
 *  2026-08-11). The first six mirror the design system's `MOSAIC_STEPS`. */
export type MosaicStepId =
  | 'load'
  | 'range'
  | 'screen'
  | 'place'
  | 'sweep'
  | 'mosaic'
  | 'electrodes';

/**
 * Every step can ask to move to another step. The shell decides whether the target is REACHABLE — a
 * click on a locked step toasts and does not navigate (R4.2/R4.3) — so the body just asks.
 */
export interface WizardStepProps {
  onNavigate: (step: MosaicStepId) => void;
}

/**
 * Load confirms the dataset the browser already opened; its secondary affordances (open a different
 * directory, resume a project file) drive the session lifecycle the shell owns, so they are delegated
 * up as optional callbacks. When a callback is absent the control is still present (so the testids and
 * layout are stable) and it nudges the user via a toast rather than half-doing a re-open.
 */
export interface LoadStepProps extends WizardStepProps {
  /** Re-open a *different* acquisition directory (re-init session + document). The shell owns it. */
  onOpenDirectory?: (dir: string) => Promise<void> | void;
  /** `Load a project…` — resume from a saved file. The shell owns load → hydrate → navigate (R5.3). */
  onLoadProject?: () => Promise<void> | void;
  /** Live open-progress phase, painted at `load-phase` while a (re)open runs (BEHAVIOUR §2 step 1). */
  openPhase?: string | null;
}

export interface RangeStepProps extends WizardStepProps {
  /**
   * `Apply` a new lo/hi/pass-split. Re-scoping the trial SET (lo/hi) re-hydrates the session, which is
   * the shell's lifecycle; when omitted, Range applies the (client-safe) pass-split override and
   * re-detects the facts, and notes that a range change needs a re-open.
   */
  onApplyRange?: (lo: number, hi: number, passSplit: number | null) => Promise<void> | void;
}

export type ScreenStepProps = WizardStepProps;
