// SESSIONS — a live, server-side load of one dataset's frames (the ~340 MiB stack). The session id and
// its `nonce` are what the cache-buster (BEHAVIOUR R31) and the match primitive key on.
//
// ⛔ NO DATASET KNOWLEDGE. A session serves EVERY snapshot trial on disk in range; nothing is dropped
// by trial number, only by shape, and only with a reason in `skipped` (BEHAVIOUR §6.1).

import { useEffect, useState } from 'react';
import { api, unwrap } from './client';
import type {
  SessionResponse,
  SessionListResponse,
  Tone,
  ToneUpdate,
  TextureResponse,
  LogResponse,
  ThumbsResponse,
} from './types';

// ── Request functions ───────────────────────────────────────────────────────────

export async function getSession(sessionId: string): Promise<SessionResponse> {
  return unwrap(
    await api.GET('/api/sessions/{session_id}', { params: { path: { session_id: sessionId } } }),
  );
}

export async function listSessions(): Promise<SessionListResponse> {
  return unwrap(await api.GET('/api/sessions'));
}

/** Free the stack (~340 MiB). Idempotent enough for a cleanup path. */
export async function deleteSession(sessionId: string): Promise<void> {
  await unwrap(
    await api.DELETE('/api/sessions/{session_id}', { params: { path: { session_id: sessionId } } }),
  );
}

export async function getTone(sessionId: string): Promise<Tone> {
  return unwrap(
    await api.GET('/api/sessions/{session_id}/tone', { params: { path: { session_id: sessionId } } }),
  );
}

/**
 * Update the GLOBAL display window (`PUT /api/sessions/{id}/tone`). ⚠️ Tone is display-only and GLOBAL,
 * never per-tile (BEHAVIOUR R18) — it never touches the matcher or the exported TIFF. The returned
 * `Tone.version` is half of the pixel cache-buster: bump the cache-buster whenever this changes (R31).
 */
export async function putTone(sessionId: string, update: ToneUpdate): Promise<Tone> {
  return unwrap(
    await api.PUT('/api/sessions/{session_id}/tone', {
      params: { path: { session_id: sessionId } },
      body: update,
    }),
  );
}

/**
 * The texture measure per trial — `std(DoG(3,30))`, a property of the frame (`GET .../texture`).
 * ⛔ There is no threshold or policy here; turning a number into a proposal is the Screen step's job
 * (`proposeScreen`), and turning a proposal into a decision is the human's (BEHAVIOUR R17, §6.3).
 */
export async function getTexture(sessionId: string): Promise<TextureResponse> {
  return unwrap(
    await api.GET('/api/sessions/{session_id}/texture', {
      params: { path: { session_id: sessionId } },
    }),
  );
}

export async function getSessionLog(sessionId: string): Promise<LogResponse> {
  return unwrap(
    await api.GET('/api/sessions/{session_id}/log', { params: { path: { session_id: sessionId } } }),
  );
}

/** The contact-sheet layout (which trial is in which cell). The pixels are the sprite PNG in `tiles.ts`. */
export async function getThumbsLayout(sessionId: string): Promise<ThumbsResponse> {
  return unwrap(
    await api.GET('/api/sessions/{session_id}/thumbs.json', {
      params: { path: { session_id: sessionId } },
    }),
  );
}

// ── A small read hook ─────────────────────────────────────────────────────────────

export type SessionState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; session: SessionResponse };

/** Fetch a session by id (e.g. to rehydrate after a cold `Load a project…`). `null` id = idle. */
export function useSession(sessionId: string | null): SessionState {
  const [state, setState] = useState<SessionState>({ status: sessionId ? 'loading' : 'idle' });

  useEffect(() => {
    if (sessionId == null) {
      setState({ status: 'idle' });
      return;
    }
    let cancelled = false;
    setState({ status: 'loading' });
    getSession(sessionId)
      .then((session) => {
        if (!cancelled) setState({ status: 'ready', session });
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setState({ status: 'error', message: e instanceof Error ? e.message : String(e) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  return state;
}
