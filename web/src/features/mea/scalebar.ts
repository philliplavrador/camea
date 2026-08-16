// THE SCALE BAR'S ARITHMETIC — which round µm length to draw at a given zoom.
//
// Its own module for the reason `hitRadius.ts` is: the rule is the part worth testing on its own,
// and a component file that also exports helpers breaks fast refresh.
//
// ⭐ **Honest by construction**: the µm come straight from the file's own pad coordinates
// (`x_um`/`y_um`), the same frame everything on the canvas is drawn in. No device constant and no
// assumed pitch is involved — I1/R45.8 need nothing carved out here, because nothing is known.

/** The on-screen length the bar aims for, CSS px. A display choice, nothing more. */
const TARGET_PX = 90;

export interface ScaleBar {
  /** The round distance the bar stands for, µm. */
  um: number;
  /** How wide to draw it, CSS px. */
  px: number;
  /** The label, e.g. `100 µm` — plain decimals, never scientific notation (same rule as
   *  `formatRate`: notation a biologist has to decode is not a label). */
  label: string;
}

/**
 * The largest 1–2–5 × 10^k µm length that fits inside ~`targetPx` at this zoom
 * (`scale` = CSS px per µm). -> `null` when there is no view yet, so the caller draws
 * nothing rather than `NaN µm`.
 */
export function scaleBar(scale: number, targetPx: number = TARGET_PX): ScaleBar | null {
  if (!(scale > 0) || !Number.isFinite(scale)) return null;
  const raw = targetPx / scale; // the µm span that would fill the target exactly
  const pow = Math.pow(10, Math.floor(Math.log10(raw)));
  let um = pow;
  for (const m of [2, 5]) {
    if (m * pow <= raw) um = m * pow;
  }
  return { um, px: um * scale, label: `${formatUm(um)} µm` };
}

/** Plain decimals at every magnitude — `0.2`, `5`, `100`, `2000`. Never `2e-1`. */
function formatUm(um: number): string {
  if (um >= 1) return String(Math.round(um));
  // Below 1 µm the 1–2–5 steps have one significant figure, so this is exact.
  return um.toPrecision(1);
}
