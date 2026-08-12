// ─────────────────────────────────────────────────────────────────────────────────────────────
// ⭐ **THE QUESTION THAT MUST BE ASKED BEFORE ANY MAPPING** (his ruling, 2026-08-11 — R45.8).
//
//   *"Allow the user to select if it's a partially imaged or fully imaged before allowing them to
//    map electrodes. If they select full imaging enforce all the rules I gave. If they pick partial
//    only enforce the 17.5 um rule"*
//   *"just to be clear if the user select full imaging then I want the rules to be strictly
//    enforced"*
//
// Only he can know what the picture CONTAINS. The lattice itself is still MEASURED from the pixels
// either way (R45.1 — pitch, rotation and phase are never assumed); what this answer changes is what
// the fit is allowed to be CHECKED against afterwards:
//   • whole chip  — STRICT. The run ends in exactly one of two states: a map that IS the device's
//                   shape with every one of its positions numbered, or a refusal that says what it
//                   found. A near miss is corrected only where the PIXELS say which edge is missing
//                   (and the panel says what moved, never silently); anything else is REFUSED,
//                   because renumbering a partial view as if it were the whole array would hand him
//                   electrode ids that are wrong by a constant nobody could see.
//   • part of it  — nothing is enforced but the device pitch, which is what sets the µm scale. The
//                   numbering starts at what is imaged, so **1-1 is the top-left of the IMAGED
//                   REGION, not of the chip** — a caveat the readout carries wherever ids are read.
//
// ⛔ THERE IS NO DEFAULT. `value` is null until he picks, and the caller's Map button is disabled
// while it is — a map that quietly assumed "partial" would be an answer he never gave.
//
// ⛔ AND THERE ARE NO DEVICE NUMBERS IN THIS FILE. They are SERVED (`useElectrodeDevice`), because
// the one place that owns them is the one place that enforces them (see `device.ts`, which also
// holds `coverageHelp` — the prose that quotes them). While the fetch is in flight, or if it failed,
// this component names no numbers AT ALL rather than remembered ones: the question is still fully
// answerable, and the server enforces the same rule either way.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import type { ArrayCoverage } from '../../api';
import { Choice, Help } from '../../design';
import { coverageHelp, deviceCount, deviceShape, useElectrodeDevice } from './device';
import styles from './CoverageChoice.module.css';

export interface CoverageChoiceProps {
  value: ArrayCoverage | null;
  onChange: (next: ArrayCoverage) => void;
  disabled?: boolean;
  className?: string;
}

/** The two-option control itself, plus the one-line prompt and its `?`. Mounted by BOTH features. */
export function CoverageChoice({ value, onChange, disabled, className }: CoverageChoiceProps) {
  const device = useElectrodeDevice();

  return (
    <div className={className}>
      <p className={styles.prompt}>
        Is the whole chip in this mosaic?
        <Help body={coverageHelp(device)} label="What the coverage answer changes" />
      </p>
      <Choice<ArrayCoverage>
        label="Array coverage"
        testid="electrode-coverage"
        value={value}
        onChange={onChange}
        disabled={disabled}
        options={[
          {
            value: 'full',
            label: 'Whole chip imaged',
            // ⛔ No numbers until the served spec brings them. "enforces the device's full array" is
            // true whatever the chip is; "enforces 220 × 120" would be a promise this file cannot keep.
            blurb: device
              ? `enforces ${deviceShape(device)} = ${deviceCount(device)} electrodes`
              : "enforces the device's full array",
            testid: 'electrode-coverage-full',
          },
          {
            value: 'partial',
            label: 'Part of the chip',
            blurb: '1-1 is the top-left of what is imaged',
            testid: 'electrode-coverage-partial',
          },
        ]}
      />
    </div>
  );
}
