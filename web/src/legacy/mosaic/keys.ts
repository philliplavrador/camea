// THE FEATURE HALF OF THE KEYBOARD MAP (BEHAVIOUR §3), as a PURE decision function so the whole map is
// unit-testable without a DOM. It mirrors core/viewer/keymap.ts (`mapCameraKey`, the CAMERA half): the
// viewer mounts with keys OFF, and the feature is the ONE dispatch point (§3.4) — it runs `mapSweepKey`
// first, and only if that returns null does it hand the event to the engine's camera map. One event, one
// handler; nothing is double-handled (else `D` toggles Difference twice and lands back where it started).
//
//   const action = mapSweepKey(e, screen);
//   if (action) { e.preventDefault(); dispatch(action); return; }
//   if (screen === 'sweep') { const cam = mapCameraKey(e); if (cam) engine.apply(cam); }
//
// ⛔ DELIBERATELY-UNBOUND KEYS STAY UNBOUND (see UNBOUND below): `0` is the viewer's 1:1 zoom and is NOT
//    an alternatives key (R12.6); `[` / `]` were a nice-to-have for the opacity slider and were never
//    shipped (R13.7); Space is ADVANCE and is NEVER a pan modifier (§6.7). Adding any of these back is a
//    regression, not a convenience.

/** What a sweep key resolves to. `null` = not a sweep key (the caller tries the camera map next). */
export type SweepKeyAction =
  // Global — handled on EVERY screen, above the `screen !== 'sweep'` gate (R5.2, §3.2):
  | { kind: 'save' } // Ctrl/⌘+S — Save the project file (R5.2)
  | { kind: 'undo' } // Ctrl/⌘+Z (R36)
  | { kind: 'redo' } // Ctrl/⌘+Y
  // Sweep-only — fire only when `screen === 'sweep'` (§3.3):
  | { kind: 'advance' } // Space — ADVANCE (R15/R9b/R33)
  | { kind: 'anchor' } // A — anchor, a TOGGLE (R11)
  | { kind: 'exclude' } // E — exclude (recomputes gaps, stale cascade)
  | { kind: 'replay' } // R — replay the fade
  | { kind: 'alternatives' } // V — the ranked runner-ups (R22)
  | { kind: 'snap' } // S — snap locally against the anchor composite (R23)
  | { kind: 'jump'; rank: number }; // 1–9 — jump to the Nth-best peak; `rank` is 0-INDEXED (digit − 1, R12)

interface KeyLike {
  key: string;
  code?: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
  altKey?: boolean;
  shiftKey?: boolean;
  target?: EventTarget | null;
}

export type Screen = 'load' | 'range' | 'screen' | 'place' | 'sweep' | 'mosaic';

const EDITABLE = /^(INPUT|TEXTAREA|SELECT)$/;

/**
 * The keys the FEATURE owns. The global guard (§3.1) runs first, in order:
 *   1. focus in an editable → return null (nothing fires; this is why the digits do not fight the tone
 *      and range fields — R12.7);
 *   2. Ctrl/⌘ + S / Z / Y → save / undo / redo, on EVERY screen (R5.2);
 *   3. any OTHER Ctrl/⌘/Alt combination → null;
 *   4. everything below only fires when `screen === 'sweep'` (§3.3).
 */
export function mapSweepKey(e: KeyLike, screen: Screen): SweepKeyAction | null {
  const tag = (e.target as HTMLElement | null)?.tagName ?? '';
  if (EDITABLE.test(tag) || (e.target as HTMLElement | null)?.isContentEditable) return null;

  // 2 — Ctrl/⌘ + S/Z/Y first, on every screen. An hour into a sweep is exactly when Ctrl+S is wanted.
  if (e.ctrlKey || e.metaKey) {
    switch (e.key.toLowerCase()) {
      case 's':
        return { kind: 'save' };
      case 'z':
        return { kind: 'undo' };
      case 'y':
        return { kind: 'redo' };
      default:
        return null; // 3 — any other Ctrl/⌘ combination is ignored
    }
  }
  // 3 — Alt combinations belong to nothing here (Alt+drag is a viewer pan gesture).
  if (e.altKey) return null;

  // 4 — the sweep's own keys only fire on the sweep.
  if (screen !== 'sweep') return null;

  // ⛔ Space is ADVANCE, never a pan modifier (§6.7). Match by `code` so a remapped layout still advances.
  if (e.code === 'Space' || e.key === ' ') return { kind: 'advance' };

  switch (e.key.toLowerCase()) {
    case 'a':
      return { kind: 'anchor' };
    case 'e':
      return { kind: 'exclude' };
    case 'r':
      return { kind: 'replay' };
    case 'v':
      return { kind: 'alternatives' };
    case 's':
      return { kind: 'snap' };
  }

  // ⭐ 1–9 — jump to the Nth-best computed position (R12). `1` = the best peak. Storage is 0-indexed, so
  // digit `d` maps to rank `d − 1`; the rail displays `rank + 1`, so the number he READS and the number
  // he PRESSES agree. ⚠️ `0` is NOT here — it is the viewer's 1:1 zoom (R12.6).
  if (e.key >= '1' && e.key <= '9') {
    return { kind: 'jump', rank: Number(e.key) - 1 };
  }

  return null;
}

/**
 * The keys that are DELIBERATELY UNBOUND at the feature level, and must stay that way. Documented (and
 * exported for the keymap test) so a future agent does not "helpfully" bind one:
 *   - '0'  → the viewer's 1:1 zoom, NOT an alternatives key (R12.6).
 *   - '['  → an opacity-slider step was a nice-to-have only; never shipped (R13.7).
 *   - ']'  → as '['.
 *   - '+' / '=' / '-' / '_' → the viewer's zoom (R13.7 — do not take these).
 *   - 'f' / 'd' / 'g' / 'Escape' / arrows → the viewer's CAMERA map (`mapCameraKey`), delegated after this.
 * `mapSweepKey` returns null for every one of them, on purpose.
 */
export const UNBOUND_SWEEP_KEYS = ['0', '[', ']', '+', '=', '-', '_'] as const;
