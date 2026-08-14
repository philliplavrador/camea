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
        body: {
          title: opts.title ?? 'Open a file',
          filters: opts.filters ?? [],
          allow_multiple: false,
        },
      }),
    opts.title ?? 'File to open (path):',
  );
}

/**
 * Pick SEVERAL existing files in one gesture — *"opens file explorer, can import multiple at a
 * time"* (his words, 2026-08-14).
 *
 *   `string[]` — what he chose (`[]` = he opened the dialog and cancelled)
 *   `null`     — ⭐ **there is no file explorer in this mode**, which is the ordinary answer over
 *                VSCode remote, where he actually works.
 *
 * ⚠️ **No `window.prompt` fallback, deliberately** — the one place in this file that departs from
 * the R38 pattern above. A prompt carries one path, not a list, and asking him to type several
 * separated by something is worse than the alternative: the caller
 * (`features/mea/ImportRecordings`) already has a served tick-list on screen that works in every
 * mode. `null` is what lets it say so in one line instead of appearing to do nothing.
 */
export async function pickOpenFilePaths(
  opts: { title?: string; filters?: string[] } = {},
): Promise<string[] | null> {
  const res = await api.POST('/api/dialog/open-file', {
    body: {
      title: opts.title ?? 'Open files',
      filters: opts.filters ?? [],
      allow_multiple: true,
    },
  });
  if (res.response.status === HEADLESS_STATUS) return null;
  if (res.error !== undefined || res.data === undefined) {
    throw new Error(`dialog failed (${res.response.status})`);
  }
  return res.data.paths ?? [];
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

// ⛔ **`revealPath` / `POST /api/fs/reveal` were DELETED on 2026-08-10 (R44).** Showing a project
// in Explorer was the last door out of the app to a project'''s files, and his ruling closed it: the
// app is how you browse your project data. What replaced it is `copyOutputs` (./outputs.ts) — you
// take a copy of what you chose, to where you chose, deliberately.
