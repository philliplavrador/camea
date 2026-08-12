// THE ELECTRODE READOUT PANEL — the one identification surface both features mount (the snapshot
// Electrodes step and the videomosaic screen). It renders FACTS about the current selection and the
// fitted grid; it owns no job and no viewer. The Map / Re-run button is the CALLER's (each feature
// starts its own job kind), passed through `action` into the panel header; the coverage question is
// the caller's too, passed through `coverage` — it is what the NEXT run would be told.
//
// Numbers, not prose (R3/R7): the readout is id · grid coordinate · centre px · centre µm · clicked
// pixel · distance · detected/inferred, then the grid stats. Staleness, a corrected shape and the
// partial-view caveat are LIVE WARNINGS about current state (R3.8/§5) — they stay on the page, never
// behind a `?`.
//
// ⭐ **µm ARE A MEASURED CONVERSION, NOT A DATASHEET NUMBER** (R45.8). `um_per_px` is the device's
// known pitch over the pitch THIS image actually shows, and the per-cell µm are the measured centres
// carried into the array's own frame — so they land near (col−1)·pitch but keep the real deviation.
// When no device supplied a scale (a map written before R45.8), the µm facts are ABSENT rather than
// zero: "not known" must never be shown as a number.
//
// ⛔ **AND NEVER A DEVICE NUMBER THIS PAYLOAD DID NOT CARRY.** Every pitch in the prose below is read
// off `payload.device`; where it is missing the sentence says what is true instead of falling back to
// a remembered "17.5 µm" (the 2026-08-11 review, finding #4). Same rule as the coverage question,
// which now READS the spec off `GET /api/electrodes/device` rather than repeating it — see device.ts.

import type { ReactNode } from 'react';
import type { ElectrodeMapPayload } from '../../api';
import { Help, LiveWarning, Panel } from '../../design';
import type { ElectrodeHit } from './lookup';
import { kindCounts } from './lookup';
import styles from './ElectrodePanel.module.css';

/** The current selection: the resolved electrode plus the pixel that selected it (null when the
 *  selection arrived by arrow key — a step has no clicked pixel, and the readout says `—`). */
export interface ElectrodeSelection {
  hit: ElectrodeHit;
  clickX: number | null;
  clickY: number | null;
}

export interface ElectrodePanelProps {
  payload: ElectrodeMapPayload;
  selection: ElectrodeSelection | null;
  /** The map no longer matches the mosaic (server `stale`, or edits observed since it was fetched). */
  stale: boolean;
  /** The caller-owned Map / Re-run button, rendered in the panel header. */
  action?: ReactNode;
  /**
   * The caller-owned coverage control (R45.8), rendered above the readout. It is here and not only
   * on the pre-map screen because **Re-run is a mapping too**: without it, a project mapped as
   * "partial" could never be re-declared whole, and a Re-run would silently reuse an answer the user
   * can no longer see.
   */
  coverage?: ReactNode;
}

const px = (v: number): string => v.toFixed(1);

// ── Reading the free-dict corners of the payload ────────────────────────────────────────────────
// `stats` and `device` are server-owned dicts in the contract, so read them defensively: a missing
// number is simply not shown, never faked.
const num = (v: unknown): number | null =>
  typeof v === 'number' && Number.isFinite(v) ? v : null;
const rec = (v: unknown): Record<string, unknown> | null =>
  v != null && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : null;

// ⛔ **THERE IS NO "SHAPE CORRECTED" WARNING ANY MORE, AND ITS ABSENCE IS THE FEATURE.** A full map
// used to be repairable — a near miss had an edge line added or dropped, and this panel carried a
// live warning saying so, because the repair could renumber the array. Two repair rules were built
// and both were caught shifting every id by a constant while reporting the right shape, so the
// repair is gone (see `_enforce_device_shape`): under "whole chip imaged" the fit either IS the
// device's shape, registered where the pixels put the array's edge, or the job REFUSES. A warning
// about a correction is therefore a warning about something that can no longer happen — and the
// refusal, which the caller renders whole, is what tells him instead.

function Fact({ label, help, children }: { label: string; help?: string; children: ReactNode }) {
  return (
    <div className={styles.fact}>
      <dt className={styles.factLabel}>
        {label}
        {help ? <Help body={help} /> : null}
      </dt>
      <dd className={styles.factValue}>{children}</dd>
    </div>
  );
}

export function ElectrodePanel({
  payload,
  selection,
  stale,
  action,
  coverage,
}: ElectrodePanelProps) {
  const n = kindCounts(payload);
  const hit = selection?.hit ?? null;
  const umPerPx = num(payload.um_per_px);
  const device = rec(payload.device);
  const deviceName = typeof device?.name === 'string' ? device.name : null;
  const pitchUm = num(device?.pitch_um);
  const partial = payload.array_coverage !== 'full';

  // ⭐ **NEVER PRINT A DEVICE NUMBER THIS PAYLOAD DID NOT CARRY** (the 2026-08-11 review, finding #4).
  // A map written before R45.8 has no `device` block and no `um_per_px` at all, and the notes below
  // used to promise "only its 17.5 µm pitch, which is what sets the µm scale below" over exactly that
  // payload — a number nobody measured, describing a scale that is not on the page. `pitchText` is
  // null in that case and every sentence that would have named a pitch says what is true instead.
  const pitchText = pitchUm != null ? `${pitchUm} µm` : null;

  return (
    <div data-testid="electrode-panel">
      <Panel title="Electrodes" actions={action}>
        <div className={styles.body}>
          {stale && (
            <div data-testid="electrode-stale">
              <LiveWarning
                help={
                  'The mosaic changed after this grid was fitted (tiles moved, or a rebuild). The centres below may sit on drifted pixels until the mapping runs again.'
                }
              >
                electrode map is stale — re-run Map electrodes.
              </LiveWarning>
            </div>
          )}

          {/* ⭐ A PARTIAL MAP MUST SAY WHOSE TOP-LEFT 1-1 IS (R45.8) — right where the ids are read. */}
          {partial && (
            <div data-testid="electrode-partial-note">
              <LiveWarning
                variant="info"
                help={
                  'You said this mosaic shows only part of the array, so nothing was checked ' +
                  "against the device's shape" +
                  // ⭐ Three payloads, three truths (review finding #4) — and NO invented pitch.
                  (pitchText != null && umPerPx != null
                    ? ` — only its ${pitchText} pitch, which is what sets the µm scale below.`
                    : pitchText != null
                      ? ` — only its ${pitchText} pitch. This map carries no µm scale, so the ` +
                        'readout below is pixels only.'
                      : '. This map names no device at all — it was written before one was ' +
                        'recorded — so nothing set a µm scale either, and the readout below is ' +
                        'pixels only.') +
                  '\n' +
                  '\n' +
                  'Numbering therefore starts at what is imaged: move the field of view and the ' +
                  'same physical electrode gets a different id. Map a mosaic of the whole chip if ' +
                  "you need ids that match the device's own numbering."
                }
              >
                part of the chip — <b>1-1 is the top-left of the imaged region</b>, not of the chip.
              </LiveWarning>
            </div>
          )}

          {coverage}

          {hit ? (
            <dl className={styles.facts}>
              <Fact
                label="Electrode"
                help={'The id is col-row on the fitted grid. Every grid position has one.'}
              >
                <span className={styles.id} data-testid="electrode-id" data-kind={hit.kind}>
                  {hit.electrode}
                </span>
              </Fact>
              <Fact label="Grid">
                col {hit.col} · row {hit.row}
              </Fact>
              <Fact
                label="Source"
                help={
                  'detected — this pad was found on the pixels. inferred — the lattice says a pad belongs here (occluded or dead), so the centre is computed, not seen.'
                }
              >
                {hit.kind === 2 ? 'inferred' : 'detected'}
              </Fact>
              <Fact label="Centre px">
                {px(hit.centerX)}, {px(hit.centerY)}
              </Fact>
              {hit.xUm != null && hit.yUm != null && (
                <Fact
                  label="Centre µm"
                  help={
                    "The same centre in the ARRAY's own frame: x along columns, y along rows, " +
                    'rotation taken out, origin at electrode 1-1. Converted from the MEASURED ' +
                    'pixels, so it lands near ' +
                    // No pitch on the payload, no pitch in the sentence (review finding #4).
                    (pitchText != null
                      ? `(col−1)·${pitchUm} µm`
                      : 'a whole number of pitches from 1-1') +
                    ' but carries the real deviation of this pad rather than the ideal.'
                  }
                >
                  <span data-testid="electrode-um">
                    {hit.xUm.toFixed(1)}, {hit.yUm.toFixed(1)}
                  </span>
                </Fact>
              )}
              <Fact label="Clicked px">
                {selection && selection.clickX != null && selection.clickY != null
                  ? `${px(selection.clickX)}, ${px(selection.clickY)}`
                  : '—'}
              </Fact>
              <Fact
                label="Distance px"
                help={
                  `Clicked pixel to centre. Zoomed in, a click resolves only within ` +
                  `${px(payload.hit_radius_px)} px of a centre and the gaps select nothing; zoomed ` +
                  `out — where a pad is a couple of pixels wide — it resolves to the electrode you ` +
                  `pointed at, never past the halfway line to its neighbour.`
                }
              >
                {selection && selection.clickX != null ? px(hit.distance) : '—'}
              </Fact>
            </dl>
          ) : (
            <p className={styles.hint}>
              no electrode selected
              <Help
                body={
                  `Click an electrode to identify it — within ${px(payload.hit_radius_px)} px of its centre at full zoom, ` +
                  'and whatever the zoom can honestly resolve when pulled back. ' +
                  'Arrow keys step the selection one cell: Up/Down = row∓1, Left/Right = col∓1. Esc clears it.'
                }
              />
            </p>
          )}

          <hr className={styles.divider} />

          <dl className={styles.facts}>
            <Fact label="Grid">
              {payload.cols} × {payload.rows}
            </Fact>
            <Fact label="Pitch px">{px(payload.pitch_px)}</Fact>
            <Fact label="Angle °">{payload.angle_deg.toFixed(2)}</Fact>
            {umPerPx != null && (
              <Fact
                label="µm/px"
                help={
                  'The MEASURED scale: ' +
                  // Same rule again — the pitch is named only when the payload carried one.
                  (pitchText != null ? `the device pitch (${pitchText})` : "the device's pitch") +
                  ' over the pitch this image actually shows. It is not a number anyone typed, ' +
                  "and it is not the export pane's hand-entered µm/px — that one stays out of the " +
                  'provenance stamp (R30).'
                }
              >
                <span data-testid="electrode-um-per-px">{umPerPx.toFixed(4)}</span>
              </Fact>
            )}
            <Fact
              label="Coverage"
              help={
                partial
                  ? 'You declared that only part of the chip is in this mosaic, so the shape was not checked against the device — 1-1 is the top-left of the imaged region.'
                  : // ⭐ STRICT (his word, 2026-08-11): a "whole chip" map that EXISTS is the device
                    // shape with every position numbered. There is no third outcome — the fit
                    // refuses instead, so this map having been returned is itself the guarantee.
                    'You declared the whole chip imaged, so this map IS the device: its exact shape, with every one of its positions numbered. A near miss was corrected where the pixels showed which edge (see the notice above); anything further off would have been refused rather than renumbered.'
              }
            >
              <span data-testid="electrode-coverage-mode" data-coverage={payload.array_coverage}>
                {partial ? 'part of chip' : 'whole chip'}
              </span>
            </Fact>
            {deviceName != null && (
              <Fact
                label="Device"
                help={
                  'The named sensor spec that supplied the µm scale, and — when the whole chip is ' +
                  'declared imaged — the shape the fit is held to. The lattice itself is still ' +
                  'measured from the pixels; the spec only checks and completes the result.'
                }
              >
                <span data-testid="electrode-device">{deviceName}</span>
              </Fact>
            )}
            <Fact label="Detected">{n.detected}</Fact>
            <Fact
              label="Inferred"
              help={
                'Grid positions the fit placed without seeing a pad — occluded or dead. ' +
                (partial
                  ? 'Only positions the lattice reaches are here: what was not imaged is simply not on this map.'
                  : 'Declaring the whole chip imaged fills EVERY device position, so one the pixels never showed is inferred here rather than missing.')
              }
            >
              {n.inferred}
            </Fact>
          </dl>
        </div>
      </Panel>
    </div>
  );
}
