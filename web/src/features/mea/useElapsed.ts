// ⏱️ THE ELAPSED CLOCK FOR A WAIT THAT IS NOT A JOB (BEHAVIOUR R48.4).
//
// A job gets this for free: `useJob` reads the server's `elapsed_s` and ticks it at 1 Hz. A plain
// `await` — walking a folder for recordings — has no job behind it and therefore no clock, and
// `<Progress>` would then show *"working out how long this will take…"* with nothing moving beside
// it. R48.4 asks for both halves: the sentence AND a number that advances.
//
// ⛔ It is NOT an estimate and must never be dressed as one (R48b): elapsed counts UP because that
// is what elapsed does. The wait it serves here has no denominator at all — R48.9 names the
// unbounded directory walk as one of the four with no ETA, because no count of files exists until
// the walk returns — so counting up is the whole truth available.
//
// ⚠️ **THIS IS A DUPLICATE OF `features/videomosaic/useElapsed.ts`, AND DELIBERATELY IDENTICAL.**
// A feature may not import another feature's files, and both waves of R48 landed at once; the two
// copies are byte-comparable so that hoisting ONE of them into `design/` beside `useDelayedFlag`
// and deleting both is a mechanical change rather than a rewrite. Do not let them drift.

import { useEffect, useReducer, useRef } from 'react';
import { formatElapsed } from '../../api';

/** The count-up cadence, the same 1 Hz the job clock uses (BEHAVIOUR R8.1). */
const TICK_MS = 1000;

/**
 * How long `active` has been continuously true, formatted (`"12 s"`, `"1m 04s"`). `null` while it
 * is false, so the caller can hand it straight to `<Progress elapsedText=…>`.
 */
export function useElapsedText(active: boolean): string | null {
  const startedRef = useRef<number | null>(null);
  const [, tick] = useReducer((n: number) => (n + 1) % 1_000_000, 0);

  if (active && startedRef.current == null) startedRef.current = Date.now();
  if (!active && startedRef.current != null) startedRef.current = null;

  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => tick(), TICK_MS);
    return () => clearInterval(id);
  }, [active]);

  if (!active || startedRef.current == null) return null;
  return formatElapsed((Date.now() - startedRef.current) / 1000);
}
