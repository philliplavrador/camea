// ─────────────────────────────────────────────────────────────────────────────────────────────
// THE ONE-OFF WHOLE-RECORDING READ — the words for it, in ONE place.
//
// ⭐ **ONE SENTENCE, FIVE SURFACES.** The note that a recording has not been read end to end yet
// was hand-copied into `features/mea/MeaTrace`, `features/electrodes/MeaTracePanel`, the hover
// title on `RecordingShelf`'s button and TWO python 409 bodies, each carrying a comment asking the
// next person to keep them byte-identical. The three TypeScript copies now import this one.
// ⚠️ The two python copies cannot (`features/mea/routes.py`, `features/videomosaic/routes.py`) —
// they are the 409 this sentence answers, and they have to be kept in step by hand.
//
// ⛔ **IT NO LONGER PROMISES A MINUTE** (R48, 2026-08-16). *"about a minute per recording"* was the
// alone-case and only the alone-case: `recordings.py :: read_turn` reads one recording at a time
// (h5py serialises them whether or not Camea does), so a five-recording backfill is four to five
// minutes of wall clock and the fifth one waits for all of it. The sentence now says what is true
// on every path, and the BAR carries the time — which is the whole point of R48.
//
// 🔴 **R48.9 — A WAIT THAT ENDS MUST SAY THAT IT ENDED, INCLUDING BADLY.** The last two strings are
// that sentence, and they are not hypothetical: an ActivityScan recording stores no continuous
// trace, `ready` never becomes true, and all three pollers used to stop dead with the panel still
// offering to read it. Which of the two is said depends on whether a job was seen running — ⛔ which
// is the only thing the wire distinguishes, and it is NOT the same question as *why* the read ended.
// Neither sentence may claim a cause; see each one's note.
// ─────────────────────────────────────────────────────────────────────────────────────────────

/** Why the whole of a recording cannot be drawn yet, and what it would take. Five surfaces. */
export const NOT_READ_YET =
  'Camea has not read this recording end to end yet, so it cannot show you the whole of it at ' +
  'once. It is a one-off job per recording, and Camea reads one recording at a time.';

/**
 * What the bar is called while the read runs (R48.6 — his words, never `mea_envelope`).
 *
 * ⚠️ A FALLBACK, not the first choice: the job carries its own `said_as` and that is what should be
 * rendered, so the top strip (R48.8) and the panel name the same work in the same words. This is
 * what to show in the moment before the first poll lands.
 */
export const READING_LABEL = 'Reading the recording end to end';

/**
 * R48.9 — a read was running and is not any more, and there is still no whole recording.
 *
 * ⛔ **IT MUST NOT SAY "you stopped it", BECAUSE THE COMMONEST CAUSE IS NOT THAT.** An ActivityScan
 * *does* get a job: `start_envelope` submits before it can know, and `fn` only then opens the file,
 * finds `n_samples == 0` and returns `built: False`. So the sequence a client sees for the case this
 * ruling was written about — a job id, then no job and still not ready — is EXACTLY the sequence a
 * cancel produces, and nothing on the wire tells them apart (`built` never leaves `Job.result`).
 * Naming one cause here would have told him a read had been interrupted every time he clicked an
 * assay that has nothing to read, under a button offering to start it again. Both causes are named
 * until a reason reaches the wire.
 */
export const READ_STOPPED =
  'The read ended without a whole recording to show. Either it was stopped, or this recording ' +
  'holds no continuous trace to read — some recordings store only the spikes the chip detected. ' +
  'Nothing was changed.';

/**
 * R48.9 — the wait ended with no read of this recording running.
 *
 * ⚠️ Reached two ways, and it may not claim either: nothing was ever started (the file is not where
 * it was left, so `start_envelope` returns `None`), **or** a read started and finished before the
 * status reply was composed — which is what a recording with nothing to read does, in milliseconds.
 */
export const READ_NOT_POSSIBLE =
  'Camea has no read running for this recording, and it still cannot be shown whole. Either it ' +
  'holds no continuous trace to read — some recordings store only the spikes the chip detected — ' +
  'or its file is no longer where you left it.';
