import { cx } from '../cx';
import styles from './Choice.module.css';

export interface ChoiceOption<T extends string> {
  value: T;
  label: string;
  /** One line of CONSEQUENCE under the label — what picking this actually does to the result. */
  blurb?: string;
  /** `data-testid` for this segment (the e2e contract names one per option). */
  testid?: string;
}

export interface ChoiceProps<T extends string> {
  /** The accessible name of the group (`aria-label` on the radiogroup). */
  label: string;
  /**
   * The current choice — or **null**, which is a real state: "he has not answered yet". Callers gate
   * the action that consumes the answer on it, so nothing runs on a default nobody chose.
   */
  value: T | null;
  onChange: (next: T) => void;
  options: ReadonlyArray<ChoiceOption<T>>;
  disabled?: boolean;
  className?: string;
  /** `data-testid` for the group itself. */
  testid?: string;
}

/**
 * A SEGMENTED CHOICE — n mutually-exclusive options, exactly one pressed, and `null` until the user
 * picks. Plain `<button aria-pressed>` inside a `role="radiogroup"`, the same shape the Screen step's
 * Keep / Hand place / Exclude control has always used (R6.1: a real pressed state, so exactly one
 * segment reads selected); promoted here the moment a second screen needed it.
 *
 * ⛔ NOT a `Toggle`. A switch is on/off and therefore *has* a default; this exists precisely where a
 * default would be a lie — where the app must not act until the user has said which world he is in
 * (R45.8: "whole chip imaged" vs "part of the chip" changes what the electrode fit is allowed to do).
 */
export function Choice<T extends string>({
  label,
  value,
  onChange,
  options,
  disabled,
  className,
  testid,
}: ChoiceProps<T>) {
  return (
    <div
      className={cx(styles.choice, className)}
      role="radiogroup"
      aria-label={label}
      data-testid={testid}
      data-empty={value == null || undefined}
    >
      {options.map((o) => {
        const active = value === o.value;
        return (
          <button
            key={o.value}
            type="button"
            className={cx(styles.seg, active && styles.segOn)}
            aria-pressed={active}
            disabled={disabled}
            data-testid={o.testid}
            onClick={() => onChange(o.value)}
          >
            <span className={styles.segLabel}>{o.label}</span>
            {o.blurb != null && <span className={styles.segBlurb}>{o.blurb}</span>}
          </button>
        );
      })}
    </div>
  );
}
