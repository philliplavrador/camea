// NATIVE DIALOGS — the folder / file pickers, with the one guarantee that makes the whole app testable:
// a HEADLESS-ANSWERABLE PATH (BEHAVIOUR R38).
//
// In headless mode the native `/api/dialog/*` routes answer 501 (there is no pywebview window). The
// pickers below fall back to `window.prompt()`, which Playwright CAN answer — and that fallback is the
// ONLY reason the save → kill-server → cold-load → resume round-trip is drivable at all. Keep it.
//
// (For a purely served folder picker with no native dialog and no prompt, use `listDir` in `system.ts`.)

import { api } from './client';
import type { DialogPathResponse } from './types';

const HEADLESS_STATUS = 501;

/** `null` = the user cancelled (or gave an empty answer). */
async function viaDialogOrPrompt(
  call: () => Promise<{ data?: DialogPathResponse; error?: unknown; response: Response }>,
  promptMessage: string,
  promptDefault?: string | null,
): Promise<string | null> {
  const res = await call();
  if (res.response.status === HEADLESS_STATUS) {
    // Headless: no native dialog. Ask via window.prompt so Playwright/WebView2 can answer (R38).
    const answer = window.prompt(promptMessage, promptDefault ?? '');
    const trimmed = answer?.trim();
    return trimmed ? trimmed : null;
  }
  if (res.error !== undefined || res.data === undefined) {
    // A real failure (not the headless 501) — surface it.
    throw new Error(`dialog failed (${res.response.status})`);
  }
  return res.data.path ?? null; // null = cancelled in the native dialog
}

/** Pick a directory (dataset root / workspace / export dir). Falls back to `window.prompt` headless. */
export function pickDirectory(opts: { title?: string; start?: string | null } = {}): Promise<string | null> {
  return viaDialogOrPrompt(
    () =>
      api.POST('/api/dialog/open-directory', {
        body: { title: opts.title ?? 'Choose a directory', start: opts.start ?? null },
      }),
    opts.title ?? 'Directory path:',
    opts.start,
  );
}

/** Pick an existing file (e.g. `Load a project…`). Falls back to `window.prompt` headless (R38). */
export function pickOpenFilePath(opts: { title?: string; filters?: string[] } = {}): Promise<string | null> {
  return viaDialogOrPrompt(
    () =>
      api.POST('/api/dialog/open-file', {
        body: { title: opts.title ?? 'Open a file', filters: opts.filters ?? [] },
      }),
    opts.title ?? 'File to open (path):',
  );
}

/** Pick a save destination (e.g. `Save…`). Falls back to `window.prompt` headless (R38). */
export function pickSaveFilePath(
  opts: { title?: string; defaultName?: string | null; filters?: string[] } = {},
): Promise<string | null> {
  return viaDialogOrPrompt(
    () =>
      api.POST('/api/dialog/save-file', {
        body: {
          title: opts.title ?? 'Save',
          default_name: opts.defaultName ?? null,
          filters: opts.filters ?? [],
        },
      }),
    opts.title ?? 'Save as (path):',
    opts.defaultName,
  );
}
