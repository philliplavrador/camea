export interface Step {
  id: string;
  label: string;
}

/**
 * The mosaic wizard's six steps, in order (BEHAVIOUR R4.1). A convenience default — the Stepper is
 * otherwise sequence-agnostic. These are UI structure (the wizard's steps), not dataset knowledge.
 */
export const MOSAIC_STEPS: Step[] = [
  { id: 'load', label: 'Load' },
  { id: 'range', label: 'Range' },
  { id: 'screen', label: 'Screen' },
  { id: 'place', label: 'Place' },
  { id: 'sweep', label: 'Sweep' },
  { id: 'mosaic', label: 'Mosaic' },
];
