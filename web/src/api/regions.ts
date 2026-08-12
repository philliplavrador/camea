// REGIONS — the typed request boundary for locating a fixed-field recording on a built video mosaic.
// Same seam as mosaic.ts / videomosaic.ts / electrodes.ts: features call THESE, never
// `api.POST('/api/videomosaic/regions/...')` directly. That seam is what keeps HARD RULE 2 true —
// one place names a backend shape, and it is generated.
//
// ⛔ THE SERVER OWNS THE DOCUMENT — the same rule as the videomosaic build and the video electrode
// map, and the OPPOSITE of the snapshot mosaic. Nothing here authors, merges or saves a document: the
// `locate`/`snap` jobs write `doc["regions"]` server-side and the polled result's `doc` is ALREADY
// durable, so the UI adopts `result.doc` or refetches with `getRegions`. A client that built its own
// region list and PUT it back would be racing the job that already saved one.
//
// The two mutations that are the USER'S WORD are synchronous, because there is nothing to compute:
// `updateRegion` (rename / confirm) and `deleteRegion`. The two that look at pixels are jobs (202
// `JobRef`, poll with `useJob`) because they decode video and search a whole mosaic plane.
//
// ⭐ **CONFIRM IS THE HUMAN'S SIGNATURE.** A located region is born `unconfirmed` and NOTHING here
// promotes it — not a high NCC, not a fat margin, not a "confident" flag. That is I3 (nothing is
// auto-anchored) applied to a rectangle instead of a tile: the machine may place, only he may certify.
// `RegionRecord.confident` is evidence for him to weigh, never a substitute for his click.
//
// ⚠️ `locate` REFUSES without a built mosaic and without an electrode map (his ruling: the pipeline is
// step by step). Both refusals arrive as a 4xx `ApiError` whose message is worth showing verbatim —
// they are instructions ("build first", "map the electrodes first"), not failures to swallow.
//
// ⚠️ STALENESS IS REPORTED, NEVER REPAIRED. Every region carries the build's `built_at` it was placed
// against, and `RegionsPayload.stale` goes true the moment the mosaic is rebuilt underneath it. A
// location never silently drifts onto new pixels — the UI says so and the user re-snaps.

import { api, unwrap } from './client';
import type { JobRef, RegionRecord, RegionUpdateRequest, RegionsPayload } from './types';

/**
 * Add a recording and find where on the built mosaic it was taken (`POST
 * /api/videomosaic/regions/locate` → 202 `JobRef`, job kind `locate_region`). Holds the heavy lease:
 * it decodes the video, builds several stills (median / max / std — whether the neurons are bright at
 * rest or only when firing is a property of the preparation, not something the app may assume) and
 * matches each against the whole mosaic plane.
 *
 * ⭐ `path` is THE ONE path question allowed inside a project (R44). It is not a save location — it is
 * where the recording came *from*. The file is COPIED into the project, which then owns it, which is
 * also why `deleteRegion` can take it away again.
 *
 * `name` is a label only; the server defaults it to the file's own name when left empty.
 */
export async function locateRegion(analysisId: string, path: string, name = ''): Promise<JobRef> {
  return unwrap(
    await api.POST('/api/videomosaic/regions/locate', {
      body: { analysis_id: analysisId, path, name },
    }),
  );
}

/**
 * *"I dragged it here, now snap it"* (`POST /api/videomosaic/regions/snap` → 202 `JobRef`) — a bounded
 * local re-search seeded at the top-left the user dropped. `x`/`y` are TOP-LEFT corners in mosaic px
 * (R19), never centres.
 *
 * ⭐ Correct beats fast (R23): about a second, because the committed number is the server's masked NCC
 * on the real pixels rather than a browser-side guess at what the drag meant.
 *
 * `radius` is the local search half-width and is CLAMPED server-side — pass it only when the UI has a
 * reason. A local search has no whole-plane view, so a wide one stops being a refinement and becomes
 * an alias generator; omitting it takes the server's own bound.
 */
export async function snapRegion(
  analysisId: string,
  regionId: string,
  x: number,
  y: number,
  radius?: number | null,
): Promise<JobRef> {
  return unwrap(
    await api.POST('/api/videomosaic/regions/snap', {
      body: { analysis_id: analysisId, region_id: regionId, x, y, radius },
    }),
  );
}

/**
 * Rename a region, or confirm it (`PATCH /api/videomosaic/regions` → `RegionRecord`). Both are the
 * user's word, so both are synchronous and both return the saved record — adopt it, don't re-derive
 * one. Omitted fields are left alone; this is a patch, not a replace.
 */
export async function updateRegion(
  analysisId: string,
  regionId: string,
  patch: Pick<RegionUpdateRequest, 'name' | 'status'>,
): Promise<RegionRecord> {
  return unwrap(
    await api.PATCH('/api/videomosaic/regions', {
      body: { analysis_id: analysisId, region_id: regionId, ...patch },
    }),
  );
}

/**
 * Forget a located region (`DELETE /api/videomosaic/{analysis_id}/regions/{region_id}`). Its still and
 * the project's copy of the video go with it — the project holds those files because `locateRegion`
 * copied them in, so removing the region removes what it brought.
 *
 * Returns the FULL remaining payload, not a receipt: the server's list after the removal is the one to
 * render. ⚠️ Files are destroyed — the confirmation is the caller's job.
 */
export async function deleteRegion(analysisId: string, regionId: string): Promise<RegionsPayload> {
  return unwrap(
    await api.DELETE('/api/videomosaic/{analysis_id}/regions/{region_id}', {
      params: { path: { analysis_id: analysisId, region_id: regionId } },
    }),
  );
}

/**
 * Every located region of a project, plus `stale` and the `outputs` filenames the stills live under
 * (`GET /api/videomosaic/{analysis_id}/regions`). This is the refetch half of server-ownership: after
 * a `locate`/`snap` job, either adopt the result's `doc` or come back here — never author the list.
 *
 * Region x/y/w/h are `mosaic.png` canvas px, 1:1 — the same space the video electrode map's cells use.
 */
export async function getRegions(analysisId: string): Promise<RegionsPayload> {
  return unwrap(
    await api.GET('/api/videomosaic/{analysis_id}/regions', {
      params: { path: { analysis_id: analysisId } },
    }),
  );
}
