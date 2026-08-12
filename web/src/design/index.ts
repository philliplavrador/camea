/**
 * The Camea design system — the vocabulary every feature screen is built from.
 *
 * Import the global CSS entry ONCE (tokens + base):   import '@/design/index.css';
 * Import primitives from here:                          import { Button, LiveWarning } from '@/design';
 *
 * See docs/DESIGN_BRIEF.md for the palette, type, structure and signature; docs/BEHAVIOUR.md for the
 * rulings each primitive serves.
 */
export { cx } from './cx';
export type { ClassArg } from './cx';

export { Button } from './primitives/Button';
export type { ButtonProps } from './primitives/Button';

export { ButtonLink } from './primitives/ButtonLink';
export type { ButtonLinkProps } from './primitives/ButtonLink';

export { IconButton } from './primitives/IconButton';
export type { IconButtonProps } from './primitives/IconButton';

export { Toggle } from './primitives/Toggle';
export type { ToggleProps } from './primitives/Toggle';

export { Choice } from './primitives/Choice';
export type { ChoiceProps, ChoiceOption } from './primitives/Choice';

export { Kbd } from './primitives/Kbd';
export type { KbdProps } from './primitives/Kbd';

export { Help } from './primitives/Help';
export type { HelpProps } from './primitives/Help';

export { LiveWarning } from './primitives/LiveWarning';
export type { LiveWarningProps, LiveWarningVariant } from './primitives/LiveWarning';

export { Stepper } from './primitives/Stepper';
export type { StepperProps } from './primitives/Stepper';
export { MOSAIC_STEPS } from './primitives/steps';
export type { Step } from './primitives/steps';

export { StatusBar, StatusItem, PerfReadout } from './primitives/StatusBar';
export type { StatusBarProps, StatusItemProps, PerfReadoutProps } from './primitives/StatusBar';

export { Badge } from './primitives/Badge';
export type { BadgeProps, BadgeState } from './primitives/Badge';

export { Panel } from './primitives/Panel';
export type { PanelProps } from './primitives/Panel';

export { Card } from './primitives/Card';
export type { CardProps } from './primitives/Card';

export { Reticle } from './primitives/Reticle';
export type { ReticleProps } from './primitives/Reticle';
