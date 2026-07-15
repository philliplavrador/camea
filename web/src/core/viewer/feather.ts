// The feather ramp — the alpha falloff that cross-fades one baked tile's seam into whatever is
// already under it (BEHAVIOUR R10: "as i confirm anchor i want anchors to blend together").
//
// It is a SEPARABLE cosine falloff: opaque core, ramping to 0 over the outer `feather` px of each
// edge — the same shape analysis/mosaic/render.py uses for the exported mosaic, so the live field
// and the shipped one blend the same way. Baking the ramp into a reused scratch canvas keeps a
// layer bake at exactly ONE drawImage per tile (R10.3, R10.4 — no per-frame weight buffer).
//
// ⚠️ Only LAYERS feather. The floating tile under judgement is drawn straight from its bitmap,
//    crisp — softening the very tile being inspected would blur the misalignment (R10.2).

/**
 * A 1-D alpha ramp of length `size`: 1 in the interior, cosine-falling to 0 over `feather` px at
 * each end. Pure and testable. The 2-D mask is the outer product ramp[x]·ramp[y].
 */
export function featherRamp(size: number, feather: number): Float32Array {
  const ramp = new Float32Array(size);
  for (let i = 0; i < size; i++) {
    const d = Math.min(i, size - 1 - i); // distance to the nearest edge
    ramp[i] = d >= feather ? 1 : 0.5 - 0.5 * Math.cos((d / feather) * Math.PI);
  }
  return ramp;
}

/**
 * The `size × size` feather mask as a white bitmap whose ALPHA is ramp[x]·ramp[y]. Multiplied into a
 * tile via `destination-in`, it keeps the tile where the mask is opaque and fades its edges.
 * Built once per viewer. Returns a bare canvas if a 2-D context is unavailable (e.g. jsdom), so the
 * caller degrades to an un-feathered draw rather than throwing.
 */
export function buildFeatherMask(size: number, feather: number): HTMLCanvasElement {
  const cv = document.createElement('canvas');
  cv.width = cv.height = size;
  const g = cv.getContext('2d');
  if (!g) return cv;
  const ramp = featherRamp(size, feather);
  const img = g.createImageData(size, size);
  const px = img.data;
  for (let y = 0; y < size; y++) {
    const ry = ramp[y];
    for (let x = 0; x < size; x++) {
      const o = (y * size + x) * 4;
      px[o] = px[o + 1] = px[o + 2] = 255;
      px[o + 3] = Math.round(255 * ramp[x] * ry);
    }
  }
  g.putImageData(img, 0, 0);
  return cv;
}
