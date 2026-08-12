// The typed API surface — the ONE import features reach for.
//
//   import { datasetsAt, matchAnchor, useJob, formatEta, type MatchResult } from '../../api';
//
// Every function here is a typed wrapper over the generated client (`schema.d.ts` ← docs/openapi.json).
// Features never hand-write a request/response body and never `api.POST('/api/...')` directly — that is
// how a type drifts from the frozen backend, the exact failure this rewrite kills (HARD RULE 2).

// The raw client + error handling (for the rare place a feature needs the envelope directly).
export { api, API_BASE, ApiError, unwrap } from './client';
export type { ErrorEnvelope } from './client';

// The generated contract, aliased under friendly names.
export * from './types';

// Domain modules.
export * from './system';
export * from './datasets';
export * from './sessions';
export * from './tiles';
export * from './workspace';
export * from './outputs';
export * from './documents';
export * from './dialogs';
export * from './mosaic';
export * from './videomosaic';
export * from './electrodes';
export * from './jobs';
