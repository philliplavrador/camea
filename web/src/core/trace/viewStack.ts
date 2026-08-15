// ─────────────────────────────────────────────────────────────────────────────────────────────
// THE VIEW STACK — where "Home / ← Back / Forward →" remember the places you have been.
//
// ⭐ **THIS IS A PORT, NOT A DESIGN.** It is matplotlib's `cbook._Stack` driving
// `NavigationToolbar2`'s home/back/forward, transcribed. Every navigation toolbar he has ever used
// behaves this way, so his fingers already know it; inventing our own history would be a third
// vocabulary for no gain. Three details carry the whole behaviour and each one is deliberate:
//
//   1. **`push` truncates the forward branch.** Zoom somewhere after pressing Back and the views
//      you had walked back past are gone — exactly like typing a new address after the browser's
//      Back button. `entries.slice(0, at + 1).concat(v)`, verbatim.
//   2. **`back`/`forward` clamp.** They never wrap and never throw, on an empty stack or a stack of
//      one. A disabled-looking button that silently explodes is worse than one that does nothing.
//   3. 🔴 **`home` IS ITSELF A PUSH** — it does not reset `at` to 0. This is the one that looks like
//      a bug and is not: pushing entry 0 on top means Home is undoable with a **single Back**, so
//      nothing he presses can lose a place he had. matplotlib's `_Stack.home()` does the same, and
//      it is the reason a mis-aimed Home never costs him the stretch he had found.
//
// The enablement predicates are Qt's exact rule from `set_history_buttons`: back is live when
// `at > 0`, forward when `at < len - 1`.
//
// ⚠️ **PURE — no React, no DOM, no timers.** Every operation returns a NEW stack, so it drops
// straight into `useState` and a changed identity is a real change. The clamped no-ops return the
// SAME object on purpose: `back()` at the start of history must not trigger a repaint.
//
// ⛔ It knows nothing about seconds beyond their being numbers — no duration, no sample rate, no
// window width. A view is two numbers and this file never judges them (HARD RULE: no dataset
// knowledge in app code).
// ─────────────────────────────────────────────────────────────────────────────────────────────

/** One place in the recording: the time range a picture is showing, in seconds. */
export interface TimeView {
  t0: number;
  t1: number;
}

/**
 * The history. `entries` is every view visited on the current branch, oldest first; `at` is where
 * the user is standing in it. Treat both as read-only — use the functions below.
 */
export interface ViewStack {
  readonly entries: readonly TimeView[];
  readonly at: number;
}

/** A history with nothing in it yet (no recording open). Every operation on it is a safe no-op. */
export const EMPTY_STACK: ViewStack = { entries: [], at: 0 };

/** The history a freshly opened recording starts with: one entry, which is also its Home. */
export function stackOf(first: TimeView): ViewStack {
  return { entries: [first], at: 0 };
}

/** Where the user is standing, or `null` when there is no history at all. */
export function current(s: ViewStack): TimeView | null {
  return s.entries[s.at] ?? null;
}

/**
 * Record a new view and stand on it. **Everything after the current position is discarded** — the
 * forward branch does not survive a new zoom (see note 1 in the header).
 *
 * Nothing is de-duplicated: pushing the view you are already on is a real entry, because
 * matplotlib's is too. The callers are responsible for not pushing a no-op — which is exactly why
 * `useTimeBrush` refuses a click and a sub-minimum span rather than reporting them.
 */
export function push(s: ViewStack, v: TimeView): ViewStack {
  const entries = [...s.entries.slice(0, s.at + 1), v];
  return { entries, at: entries.length - 1 };
}

/** Step back one place. At the start of history this is a no-op and returns the same stack. */
export function back(s: ViewStack): ViewStack {
  return s.at > 0 ? { entries: s.entries, at: s.at - 1 } : s;
}

/** Step forward one place. At the end of history this is a no-op and returns the same stack. */
export function forward(s: ViewStack): ViewStack {
  return s.at < s.entries.length - 1 ? { entries: s.entries, at: s.at + 1 } : s;
}

/**
 * Return to the first view ever recorded — by **pushing** it, not by rewinding to it. One `back`
 * undoes it and puts him back where he was. Empty history: a no-op.
 */
export function home(s: ViewStack): ViewStack {
  const first = s.entries[0];
  return first ? push(s, first) : s;
}

/** Is there anywhere to go back to? (Qt's `set_history_buttons`.) */
export function canBack(s: ViewStack): boolean {
  return s.at > 0;
}

/** Is there anywhere to go forward to? (Qt's `set_history_buttons`.) */
export function canForward(s: ViewStack): boolean {
  return s.at < s.entries.length - 1;
}
