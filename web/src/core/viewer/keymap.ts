// The CAMERA half of the keyboard map, as a PURE decision function so it can be unit-tested without
// a canvas (BEHAVIOUR §3.4). The engine executes whatever this returns; the FEATURE owns A / E /
// Space / undo and calls the engine's handleKey itself (the viewer mounts with keys OFF).
//
// 🔴 Space is NOT here and never will be. In this product Space is ADVANCE — the most-pressed key —
//    so a Space-to-pan modifier is both wrong and a trap (BEHAVIOUR §6.7). mapCameraKey returns null
//    for it, so the engine's handleKey returns false and the feature's Space handler runs.

/** What a camera key resolves to. `null` = not a camera key; the engine leaves it for the feature. */
export type CameraKeyAction =
  | { kind: 'nudge'; dx: number; dy: number }
  | { kind: 'fit' }
  | { kind: 'oneToOne' }
  | { kind: 'difference' }
  | { kind: 'grid' }
  | { kind: 'escape' }
  | { kind: 'zoom'; factor: number };

interface KeyLike {
  key: string;
  code?: string;
  shiftKey?: boolean;
  ctrlKey?: boolean;
  metaKey?: boolean;
  target?: EventTarget | null;
}

const EDITABLE = /^(INPUT|TEXTAREA|SELECT)$/;

export function mapCameraKey(e: KeyLike): CameraKeyAction | null {
  // Never steal a key while the user is typing (this is why the digits do not fight the tone/range
  // inputs — the guard is shared with the feature's own handler, BEHAVIOUR §3.1).
  const tag = (e.target as HTMLElement | null)?.tagName ?? '';
  if (EDITABLE.test(tag) || (e.target as HTMLElement | null)?.isContentEditable) return null;

  // Ctrl/⌘ combinations belong to the feature (Save / Undo / Redo). Never a camera gesture.
  if (e.ctrlKey || e.metaKey) return null;

  // ⛔ Space is ADVANCE, handled by the feature. The viewer never sees it as a camera key.
  if (e.code === 'Space' || e.key === ' ') return null;

  const step = e.shiftKey ? 10 : 1;
  switch (e.key) {
    case 'ArrowLeft':
      return { kind: 'nudge', dx: -step, dy: 0 };
    case 'ArrowRight':
      return { kind: 'nudge', dx: step, dy: 0 };
    case 'ArrowUp':
      return { kind: 'nudge', dx: 0, dy: -step };
    case 'ArrowDown':
      return { kind: 'nudge', dx: 0, dy: step };
  }

  switch ((e.key || '').toLowerCase()) {
    case 'f':
      return { kind: 'fit' };
    case '0':
      return { kind: 'oneToOne' }; // 1:1 — NOT an alternatives key (BEHAVIOUR R12.6)
    case 'd':
      return { kind: 'difference' };
    case 'g':
      return { kind: 'grid' };
    case 'escape':
      return { kind: 'escape' }; // clears selection/alternatives; MUST NOT touch the cursor (R14)
    case '+':
    case '=':
      return { kind: 'zoom', factor: 1.3 };
    case '-':
    case '_':
      return { kind: 'zoom', factor: 1 / 1.3 };
    default:
      return null;
  }
}
