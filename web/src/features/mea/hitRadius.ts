// THE CHIP MAP'S CLICK TOLERANCE — how close a click has to land to count as picking a pad.
//
// Its own module rather than a corner of `ChipMap.tsx`, for the reason `features/electrodes/
// lookup.ts` is its own module: the click rule is the part most worth testing on its own, and a
// component file that also exports helpers breaks fast refresh.

/** The on-screen target a click should have, CSS px. R45.7's number, for R45.7's reason. */
const MIN_HIT_PX = 6;

/** See {@link hitRadiusUm} — deliberately looser than the electrode map's 0.30, and why. */
const HIT_FLOOR_FRACTION = 0.5;

/**
 * How close a click has to land, **in µm**, at a given screen `scale` (CSS px per µm).
 *
 * ⚠️ **THE LESSON R45.7 COST AN AFTERNOON, APPLIED HERE UP FRONT.** A hit radius expressed in world
 * units becomes a **sub-pixel target** when the picture is zoomed out, and because the hit then
 * depends on sub-pixel phase the failures come in *bands* — which reads to a user as *"there are
 * missing patches on my chip"*, not as *"my click missed"*. Measured on the electrode map at fit
 * zoom before that fix: **24 % of clicks resolved.** So the radius **grows** to keep a usable
 * on-screen target, and is **capped at the cell circumradius** (`pitch/√2`) so that nearest-centre
 * can never reach past the cell the click actually landed in. That geometric cap is what replaces
 * a tuned threshold, and it is the half of the rule that must not move.
 *
 * ⚠️ **THE FLOOR IS DELIBERATELY LOOSER THAN THE ELECTRODE MAP'S, AND THAT IS NOT AN OVERSIGHT.**
 * `features/electrodes/lookup.ts` uses that map's strict `hit_radius_px` (≈ 0.30 × pitch), because
 * there a click **assigns an identity** on a lattice where every position is numbered, and a
 * generous radius would let a near miss claim a neighbour's id. This screen is a **viewer**: the
 * routed dots are the only things drawn, most of the chip is not routed at all, and a click means
 * *"read this pad"*. So the floor is `0.5 × pitch` — forgiving between two pads that are genuinely
 * adjacent, where there is no gap to fall into and refusing would only be obstructive.
 *
 * ⭐ **A REAL GAP STILL SELECTS NOTHING**, which is the property that matters: a missing pad puts
 * the nearest routed pad a whole pitch away, and the cap (0.707 × pitch) is less than that.
 */
export function hitRadiusUm(pitchUm: number, scale: number): number {
  const pitch = pitchUm > 0 ? pitchUm : 1;
  const wanted = scale > 0 ? MIN_HIT_PX / scale : Infinity;
  return Math.min(pitch * Math.SQRT1_2, Math.max(pitch * HIT_FLOOR_FRACTION, wanted));
}
