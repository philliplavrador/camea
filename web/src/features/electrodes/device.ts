// ─────────────────────────────────────────────────────────────────────────────────────────────
// ⭐ **THE DEVICE IS READ, NEVER RETYPED** (R45.8 + the 2026-08-11 review, finding #1).
//
// Every device number lives in exactly ONE place — the backend's `DeviceSpec`/`MAXWELL`, which is
// also the thing that ENFORCES them. The coverage question wrote them out a second time as button
// prose ("220 × 120", "26,400", "17.5 µm") in TypeScript, and a second copy of a rule is a copy that
// will one day disagree with it: change `DeviceSpec.axes` and the panel goes on promising the old
// array while the fitter refuses fits against the new one. **The UI describing a rule it is not the
// one enforcing** is the exact failure R45.8's "one place" was written to prevent.
//
// So this module fetches the spec once per app process and hands it out; every formatter below reads
// the served fields. There is no fallback spec here and there must never be one — a stale number
// presented as the device's is worse than no number, because it reads exactly like a true one.
//
// ⛔ NOT dataset knowledge (HARD RULE 3). A `DeviceSpec` is a fact about the HARDWARE that the user
// himself asserts by answering "whole chip imaged"; it says nothing about any particular acquisition.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { useEffect, useState } from 'react';
import { getElectrodeDevice, type ElectrodeDevice } from '../../api';

// One spec, one process. The chip cannot change while the app is open, so every mount of the
// coverage question (both features, the pre-map panel AND the readout's Re-run copy) shares one
// request instead of firing its own.
let cached: ElectrodeDevice | null = null;
let inflight: Promise<ElectrodeDevice> | null = null;

/**
 * The served device spec, or **null while it is in flight or if the fetch failed**.
 *
 * ⭐ NULL IS A RENDERABLE STATE, NOT AN ERROR SCREEN. The coverage question must stay answerable
 * whatever the network did — the user declaring what he imaged is not blocked on a number, and the
 * enforcement happens server-side either way. Callers name NO numbers while this is null (see
 * `coverageHelp`); they never fall back to remembered ones.
 */
export function useElectrodeDevice(): ElectrodeDevice | null {
  const [device, setDevice] = useState<ElectrodeDevice | null>(cached);

  useEffect(() => {
    if (cached) return;
    let live = true;
    // `??=` so N mounts share ONE request; a failure clears it so the next mount may try again —
    // the spec is cheap and total, and a transient miss should not blank the numbers forever.
    inflight ??= getElectrodeDevice();
    void inflight.then(
      (d) => {
        cached = d;
        if (live) setDevice(d);
      },
      () => {
        inflight = null;
      },
    );
    return () => {
      live = false;
    };
  }, []);

  return device;
}

/**
 * `"220 × 120"` — the two axis lengths, LONG SIDE FIRST.
 *
 * ⚠️ `axes` is ORIENTATION-FREE by contract: the chip can sit portrait or landscape in a mosaic, so
 * neither the fitter nor this UI may claim which one is columns. The order here is therefore a
 * READING choice (it is how he says it out loud), never a statement about the picture — which is
 * also why the fitted grid's own shape is reported separately, from the fit.
 */
export function deviceShape(d: ElectrodeDevice): string {
  const [a, b] = d.axes;
  return `${Math.max(a, b)} × ${Math.min(a, b)}`;
}

/** `"26,400"` — the count the served spec derives from `axes`; the UI only groups the digits. */
export function deviceCount(d: ElectrodeDevice): string {
  return d.electrodes.toLocaleString('en-US');
}

/** `"17.5 µm"` — the served pitch, with float noise and trailing zeros trimmed off the display. */
export function devicePitch(d: ElectrodeDevice): string {
  return `${Number(d.pitch_um.toFixed(3))} µm`;
}

// ── The prose that quotes the spec ───────────────────────────────────────────────────────────────
// It lives HERE, beside the formatters, and not next to the control it explains: every number in it
// is a served field, so the sentence and the formatter that fills it must never drift apart. A
// component file would also have to export it, which is the one thing this codebase's Fast-Refresh
// rule forbids — a nudge in the same direction.

/**
 * The `?` behind both features' "Map electrodes" panel, and behind the coverage question itself —
 * what the answer costs, in prose.
 *
 * With `device === null` (in flight, or the fetch failed) it says the same things WITHOUT NAMING ANY
 * NUMBERS, which is the only honest fallback: a remembered number reads exactly like a true one.
 */
export function coverageHelp(device: ElectrodeDevice | null): string {
  const array = device
    ? `the ${device.name} array: ${deviceShape(device)} = ${deviceCount(device)} electrodes at ` +
      `${devicePitch(device)}`
    : "the device's own array — its shape, its electrode count and its pitch";
  const pitch = device ? `the ${devicePitch(device)} pitch` : "the device's pitch";

  return (
    'The lattice is measured from THESE pixels either way — pitch, rotation and phase are never ' +
    'assumed. What you answer here says what the picture contains.\n' +
    '\n' +
    `Whole chip imaged — the measured shape is checked against ${array}, strictly: the map either ` +
    'comes back as that exact shape with every one of its positions numbered, or it is refused ' +
    'naming what it found. A fit one line short or one line long is corrected only where the ' +
    'PIXELS say which edge is missing, and the readout says what moved; a fit further off, or one ' +
    'whose two ends look alike, is refused rather than renumbered — wrong ids look exactly like ' +
    'right ones.\n' +
    '\n' +
    `Part of the chip — nothing is enforced but ${pitch}, which is what sets the µm scale. ` +
    'Numbering starts at what is imaged, so electrode 1-1 is the top-left of the imaged region, ' +
    'not of the chip.'
  );
}

/** `coverageHelp` bound to the served spec — what a caller's "Map electrodes" panel passes to `help`. */
export function useCoverageHelp(): string {
  return coverageHelp(useElectrodeDevice());
}
