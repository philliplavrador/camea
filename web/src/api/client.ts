// The typed API client.
//
// HARD RULE 2: the contract is GENERATED, never hand-written. `paths` comes from schema.d.ts, which
// `npm run gen:api` regenerates from docs/openapi.json (itself dumped from the backend). If you find
// yourself hand-declaring a request or response body the backend owns, STOP and regenerate.
//
// openapi-fetch gives a tiny (~6 kB) fetch wrapper that is fully typed against `paths`: the path
// string, its params, its request body and its response are all checked against the live contract.

import createClient from 'openapi-fetch';
import type { paths } from './schema';

/**
 * Base URL for API calls. Empty in dev — the Vite proxy forwards /api to the backend.
 *
 * Exported because the pixel endpoints (tiles, thumbs, dataset thumbnails) are `<img src>` / `<canvas>`
 * sources, not `fetch` calls — the typed client cannot build those URLs, so `tiles.ts` composes them
 * against this base. It is the ONE place a URL is assembled by hand, and it stays in sync with the
 * client because both read the same constant.
 */
export const API_BASE = import.meta.env.VITE_API_BASE ?? '';

export const api = createClient<paths>({ baseUrl: API_BASE });

/**
 * The shape every non-2xx response carries (API.md: "Every non-2xx in this app has an
 * ErrorEnvelope"). We keep it loose — the exact `error` body is not in the schema as a typed union,
 * so we read it defensively rather than assert a shape the contract does not guarantee.
 */
export interface ErrorEnvelope {
  error?: { code?: string; message?: string; detail?: unknown };
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | undefined;
  constructor(status: number, body: ErrorEnvelope | undefined) {
    const inner = body?.error;
    super(inner?.message ?? `request failed with status ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.code = inner?.code;
  }
}

/**
 * Unwrap an openapi-fetch result: return `data` or throw `ApiError`. Use for calls where an error is
 * exceptional and should bubble to an error boundary / caught state.
 */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined || result.data === undefined) {
    throw new ApiError(result.response.status, result.error as ErrorEnvelope | undefined);
  }
  return result.data;
}
