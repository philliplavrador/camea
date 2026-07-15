// TILE & THUMBNAIL PIXEL URLS — the one place the app assembles a URL by hand, because these are
// `<img src>` / `<canvas>` sources, not `fetch` calls the typed client can build.
//
// 🔴 THE CACHE-BUSTER IS LOAD-BEARING (BEHAVIOUR R31/R32). Tile PNGs are served
// `Cache-Control: immutable, max-age=1y`: the SAME URL can carry DIFFERENT bytes (open a second
// acquisition whose trial numbers overlap, or change the tone) and the browser will not revalidate for
// a year. The buster must be `{session.nonce}.{tone.version}` — the nonce is a FRESH identity per open,
// so it changes when the pixels do. ⛔ It is NOT the tone version alone: that is a dataclass default
// that resets to 1 on every open, while the pixels behind the URL change.

import { API_BASE } from './client';
import type { SessionResponse } from './types';

/**
 * The pixel cache-buster for a session, `{nonce}.{tone_version}` (BEHAVIOUR R31). Pass an override tone
 * version after a `putTone` (the returned `Tone.version`) so a tone change re-fetches immediately;
 * otherwise the session's own tone version is used.
 */
export function cacheBuster(session: Pick<SessionResponse, 'nonce' | 'tone'>, toneVersion?: number): string {
  const v = toneVersion ?? session.tone.version;
  return `${session.nonce}.${v}`;
}

function seg(value: string | number): string {
  return encodeURIComponent(String(value));
}

/** 8-bit grayscale PNG of one tile: flat-fielded, through the one global tone window. */
export function tilePngUrl(sessionId: string, trial: number, version: string): string {
  return `${API_BASE}/api/sessions/${seg(sessionId)}/tiles/${seg(trial)}.png?v=${seg(version)}`;
}

/** uint16 little-endian raw camera counts of one tile (no flat-field, no tone). Pixel data, not a picture. */
export function tileRawUrl(sessionId: string, trial: number, version: string): string {
  return `${API_BASE}/api/sessions/${seg(sessionId)}/tiles/${seg(trial)}.raw?v=${seg(version)}`;
}

/** The contact-sheet sprite: ONE PNG, row-major in trial order (pair with `getThumbsLayout`). */
export function thumbsPngUrl(sessionId: string, version: string): string {
  return `${API_BASE}/api/sessions/${seg(sessionId)}/thumbs.png?v=${seg(version)}`;
}

/**
 * One browser-card frame for a dataset, WITHOUT a session (`GET /api/datasets/{key}/thumbnail.png`).
 * Prefer `DatasetSummary.thumbnail_url` when the browser already handed you one.
 */
export function datasetThumbnailUrl(key: string): string {
  return `${API_BASE}/api/datasets/${seg(key)}/thumbnail.png`;
}
