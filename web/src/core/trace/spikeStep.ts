// ─────────────────────────────────────────────────────────────────────────────────────────────
// SPIKE STEPPING — the next/previous detected spike from where the view is standing.
//
// ⭐ **CORE, LIKE THE REST OF `core/trace`**: both trace panels (the Analyze MEA viewer and the
// videomosaic voltage panel) mount the same controls, and a feature may not import another
// feature's files.
//
// ⭐ **IT WORKS BEYOND THE LOADED WINDOW WITHOUT A NEW ROUTE, AND THAT IS A MEASURED FACT, NOT A
// SHORTCUT.** Both panels open a pad with one whole-recording request (`t0=0`, no `t1`,
// `max_points`), and the trace payload's `spikes` list covers the window that was served — so the
// arrival payload (`whole`) carries **every spike the file's own table holds for that channel**,
// which is the same list the strip's density row is already drawn from. Stepping consults that
// list, never the close-up's window, so a jump lands anywhere in the recording. A backend
// next-spike lookup would re-serve data the client is already holding.
//
// ⚠️ **NOTHING HERE IS ABOUT ANYBODY'S DATA** (the hard rule): no rate, no duration, no expected
// spike anything. Two pure searches over a list the server produced.
// ─────────────────────────────────────────────────────────────────────────────────────────────

/** The one field stepping reads. Both trace payloads' spike shapes satisfy it. */
export interface SpikeTime {
  t_s: number;
}

/**
 * The earliest spike strictly after `after + eps`, or `null` when there is none.
 *
 * `eps` exists so a view already centered on a spike steps to the NEXT one rather than re-finding
 * the spike under its own feet — float error can put the recomputed centre an ulp either side of
 * the spike time, and without the tolerance the button would stick there. Callers pass something
 * tiny relative to the view (`span * 1e-6`).
 *
 * The list is scanned, not bisected, on purpose: the server's order is not part of its contract,
 * and a scan of even a very busy pad's list is microseconds per click.
 */
export function nextSpike(spikes: readonly SpikeTime[], after: number, eps = 0): number | null {
  let best: number | null = null;
  for (const s of spikes) {
    if (s.t_s > after + eps && (best === null || s.t_s < best)) best = s.t_s;
  }
  return best;
}

/** The latest spike strictly before `before - eps`, or `null`. The mirror of `nextSpike`. */
export function prevSpike(spikes: readonly SpikeTime[], before: number, eps = 0): number | null {
  let best: number | null = null;
  for (const s of spikes) {
    if (s.t_s < before - eps && (best === null || s.t_s > best)) best = s.t_s;
  }
  return best;
}
