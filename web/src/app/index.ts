/**
 * The shell's public surface — what a FEATURE imports to plug into the frame. Features live under
 * `web/src/features/**` and reach the shell only through these hooks; they never touch the shell's
 * internals or the router.
 *
 *   useToast()          — the transient-message channel (locked-step nudge, resume confirmation…).
 *   useRegisterSaver()  — register the feature's save handler (Save/Ctrl+S then reach it — R5).
 *   useTheme()          — read/flip the palette (rarely needed by a feature; the top bar owns the UI).
 */
export { AppShell } from './AppShell';
export { ToastProvider } from './ToastProvider';
export { useToast } from './toastContext';
export type { ToastApi, ToastTone } from './toastContext';
export { SaveControllerProvider, SaveButton } from './SaveController';
export { useSaveController, useRegisterSaver } from './saveContext';
export type { SaveApi, Saver } from './saveContext';
export { useTheme } from './useTheme';
export type { Theme, ThemeControl } from './useTheme';
