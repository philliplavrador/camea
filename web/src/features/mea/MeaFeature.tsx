// ─────────────────────────────────────────────────────────────────────────────────────────────
// ANALYZE MEA — the standalone electrical task. Mounted at /project/:id by the FeatureGate for
// projects whose feature is "mea".
//
// ⭐ **TODAY THIS IS AN EMPTY ROOM WITH A DOOR IN IT, AND THAT IS THE POINT.** Plan 001 exists to
// make `Analyze MEA` a project you can create, list, rename, reopen and delete like any other;
// plan 002 is what fills the screen (import several `.h5` at once → a shelf → the chip drawn from
// the file's own µm coordinates → click a pad, read its trace). Building the shell first is what
// let 001 be verified end to end without any of that.
//
// ⛔ **NO PIPELINE NAV.** The video feature is a pipeline — survey → mosaic → electrodes → regions,
// each step locked until the one before it is done (R46.1). This is not: it is a shelf and a
// viewer, and the order you look at things in is yours. ⛔ Do not import `PipelineNav`.
//
// ⛔ **AND NO SEATING WARNING, EVER.** `features/electrodes/MeaTracePanel` carries three live
// warnings, one of which says the chip's orientation under the microscope is provisional (issue
// 003). Two of them will belong here in 002 (a pad that was never routed; a raw stream that did
// not decode). The third must never be copied across: there is no microscope in this task, the
// file states its own `electrode`/`x_um`/`y_um`, and importing that warning would teach a doubt
// that does not exist.
//
// ⭐ There is no Outputs drawer either. This feature produces no outputs yet; when it does, R44/R47
// say where they go and the drawer arrives with them — not before, as an empty button.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import type { AnalysisSummary } from '../../api';
import { Button, Help } from '../../design';
import styles from './MeaFeature.module.css';

/**
 * Why the one control on this screen is off. ⭐ **His ruling, 2026-08-14: behind the `?`.** It was
 * a line of prose under the button; R3 says explanations live in exactly one place and this is it.
 *
 * ⛔ It is NOT a `LiveWarning`. R3's standing exception is for a warning about the current state of
 * his work — a stale build, a recording that moved. "This part is not written yet" is a fact about
 * Camea, not about his project, and a permanent banner saying so would be the prose R3 removed
 * wearing a different hat.
 */
const WHY_OFF =
  'Importing MaxWell .h5 recordings is the next piece of work. This button turns on when it ' +
  'lands, and then it opens several recordings at once.';

export interface MeaFeatureProps {
  /** The manager's summary for this project — the FeatureGate already fetched it. */
  project: AnalysisSummary;
}

export function MeaFeature({ project }: MeaFeatureProps) {
  return (
    <section className={styles.pane} data-testid="mea-feature">
      <header className={styles.head}>
        <h1 className={styles.title} data-testid="mea-project-name">
          {project.name}
        </h1>
        <span className={styles.task}>Analyze MEA</span>
      </header>

      <div className={styles.empty} data-testid="mea-empty">
        <p className={styles.lead}>No recordings yet.</p>
        {/* One button and one `?` — R3's shape exactly, the same pair the video screen's Build
            makes. The button is here DISABLED rather than absent: the shape of the screen is the
            promise, and a screen that grows a control later reads as a different screen.

            ⛔ **THE `?` IS A SIBLING OF THE BUTTON, NEVER A CHILD.** A `Help` trigger is itself a
            <button>, and a button inside a button is invalid markup that no keyboard can reach —
            the trap `features/videomosaic/PipelineNav.tsx` documents and refuses. It matters more
            than usual here: this button is DISABLED, so it takes no focus at all, and the `?` is
            the only thing on the screen a Tab can land on. */}
        <div className={styles.action}>
          <Button variant="primary" disabled data-testid="mea-add-recordings">
            + Add recordings
          </Button>
          <Help body={WHY_OFF} label="Why Add recordings is off" />
        </div>
      </div>
    </section>
  );
}
