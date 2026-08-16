// ⏱️ THE ELAPSED CLOCK FOR A WAIT THAT IS NOT A JOB (BEHAVIOUR R48.4).
//
// A job gets this for free: `useJob` reads the server's `elapsed_s` and ticks it at 1 Hz. A plain
// `await` — reading the document, reading the chip's footprint — has no job behind it and therefore
// no clock, and `<Progress>` would then show *"working out how long this will take…"* with nothing
// moving beside it. R48.4 asks for both halves: the sentence AND a number that advances.
//
// ⛔ It is NOT an estimate and must never be dressed as one (R48b): elapsed counts UP because that
// is what elapsed does. The four waits it serves have no denominator at all — a single read, or a
// directory walk (R48.9's blessed no-ETA shape) — so counting up is the whole truth available.

import { useEffect, useReducer, useRef } from 'react';
import { formatElapsed } from '../../api';

/** The countdown/count-up cadence, the same 1 Hz the job clock uses (BEHAVIOUR R8.1). */
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
