// ─────────────────────────────────────────────────────────────────────────────────────────────
// ANALYZE MEA — the standalone electrical task. Mounted at /project/:id by the FeatureGate for
// projects whose feature is "mea".
//
// ⭐ **THE SHELF, AS OF PLAN 002.** 001 shipped this as an empty room with a door in it; the door
// now opens. A project arrives from the wizard with its recordings already on it, and the shelf
// lists them: what each one is, how long, how many spikes, and where Camea is reading it from while
// its copy runs. Plan 003 is what happens when you pick one — the chip drawn from the file's own µm
// coordinates, click a pad, read its trace.
//
// ⛔ **NO PIPELINE NAV.** The video feature is a pipeline — survey → mosaic → electrodes → regions,
// each step locked until the one before it is done (R46.1). This is not: it is a shelf and a
// viewer, and the order you look at things in is yours. ⛔ Do not import `PipelineNav`.
//
// ⛔ **AND NO SEATING WARNING, EVER.** `features/electrodes/MeaTracePanel` carries three live
// warnings, one of which says the chip's orientation under the microscope is provisional (issue
// 003). Two of them belong here — one arrived with 002 (a recording that is not where you left it),
// one arrives with 003 (a raw stream that did not decode). The third must never be copied across:
// there is no microscope in this task, the file states its own `electrode`/`x_um`/`y_um`, and
// importing that warning would teach a doubt that does not exist.
//
// ⭐ There is no Outputs drawer either. This feature produces no outputs yet; when it does, R44/R47
// say where they go and the drawer arrives with them — not before, as an empty button.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { useState } from 'react';
import type { AnalysisSummary } from '../../api';
import { Help } from '../../design';
import { OpenRecording } from './OpenRecording';
import { RecordingShelf } from './RecordingShelf';
import styles from './MeaFeature.module.css';

/**
 * What **+ Add recordings** does. ⭐ **His ruling, 2026-08-14: behind the `?`.** It was a line of
 * prose under the button; R3 says explanations live in exactly one place and this is it.
 *
 * ⚠️ **THIS TEXT CHANGED WITH PLAN 002, AND THAT WAS NOT OPTIONAL.** It used to read *"this button
 * turns on when it lands"* — which was true while the button was disabled and became a **lie** the
 * moment the import worked. An enabled button whose `?` says it is not built yet is worse than no
 * `?` at all, because it is the one place on the screen he is invited to trust.
 *
 * ⛔ It is NOT a `LiveWarning`, and the distinction is the one this screen must keep straight. R3's
 * standing exception is for a warning about the current state of **his work** — a recording that is
 * no longer where he left it, which `RecordingShelf` puts on the page and never behind a `?`. This
 * is a fact about **Camea**: what a control does. Those live behind the `?`. Getting these the
 * wrong way round hides a fact about his data, or nags him about the app.
 */
const WHAT_ADD_DOES =
  'Point Camea at the folder your MaxWell .h5 recordings are in and tick the ones you want — ' +
  'several at a time. Each one works straight away, read from where it already sits, while ' +
  'Camea copies it into the project behind you. Your own files are never moved or changed.';

export interface MeaFeatureProps {
  /** The manager's summary for this project — the FeatureGate already fetched it. */
  project: AnalysisSummary;
}

export function MeaFeature({ project }: MeaFeatureProps) {
  // ⭐ **THE SHELF OR ONE RECORDING, NEVER BOTH** — *"you pick one to load, and it opens it up"*
  // (his interview, 2026-08-14). Held here rather than in the URL because a recording id is a
  // Camea-minted handle on a row of the document, not an address the user should be able to type
  // or bookmark past a `Remove`.
  const [openId, setOpenId] = useState<string | null>(null);

  return (
    <section className={styles.pane} data-testid="mea-feature">
      <header className={styles.head}>
        <h1 className={styles.title} data-testid="mea-project-name">
          {project.name}
        </h1>
        <span className={styles.task}>Analyze MEA</span>
        {/* ⛔ **THE `?` IS A SIBLING OF THE BUTTON, NEVER A CHILD.** A `Help` trigger is itself a
            <button>, and a button inside a button is invalid markup that no keyboard can reach —
            the trap `features/videomosaic/PipelineNav.tsx` documents and refuses. It sits in the
            header rather than beside the button because the button now moves: it is in the shelf's
            own header when there are recordings, and the shelf owns that row. */}
        <Help body={WHAT_ADD_DOES} label="What Add recordings does" />
      </header>

      {openId ? (
        <OpenRecording
          analysisId={project.analysis_id}
          recordingId={openId}
          onClose={() => setOpenId(null)}
        />
      ) : (
        <RecordingShelf analysisId={project.analysis_id} onOpen={setOpenId} />
      )}
    </section>
  );
}
