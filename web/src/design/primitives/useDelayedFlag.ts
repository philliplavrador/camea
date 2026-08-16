import { useEffect, useState } from 'react';

/**
 * ⏱️ **THE GRACE BEFORE A WAIT IS SHOWN (BEHAVIOUR R48.1).** 400 ms.
 *
 * His answer when asked whether a sub-second wait should show a bar: *"wait a moment first"*. Most
 * of this app's round trips finish inside this window — a pad read is ~50 ms, a project rename is
 * two hops, `fs/list` is sub-second on a local disk — and a bar that flashes on and off at every
 * click is worse than no bar at all.
 *
 * ⛔ **It is a delay before APPEARING, never a delay before starting the work.** Fire the request
 * first, then arm this.
 */
export const WAIT_GRACE_MS = 400;

/**
 * `true` once `active` has been continuously true for `delayMs` — the "show the waiting UI now"
 * flag (R48.1).
 *
 * Falls back to `false` the instant `active` goes false, with no trailing delay: work that finishes
 * must stop claiming to be running immediately. A minimum-visible-duration would be the obvious
 * next idea and it is the wrong one here — it holds a bar on screen after the answer has arrived,
 * which is a lie about current state.
 *
 * ```tsx
 * const busy = useDelayedFlag(saving);
 * {busy && <Progress label="Saving the project" pct={null} />}
 * ```
 */
export function useDelayedFlag(active: boolean, delayMs: number = WAIT_GRACE_MS): boolean {
  const [shown, setShown] = useState(false);

  useEffect(() => {
    if (!active) {
      setShown(false);
      return;
    }
    const id = setTimeout(() => setShown(true), delayMs);
    return () => clearTimeout(id);
  }, [active, delayMs]);

  return shown;
}
