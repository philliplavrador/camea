// THE ONE BAR — the clauses of BEHAVIOUR R48 that are the component's own, not a screen's.
//
// The rendered end-to-end behaviour (a bar appearing after the grace, a countdown ticking, the strip)
// is proved by `web/tests/e2e/progress-eta.spec.ts` in the LIVE Playwright lane. This file holds the
// things that are cheaper and sharper to assert in isolation: the never-empty time slot, the ARIA
// contract, and the 2 % floor that must NOT apply to an indeterminate bar.

import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Progress, ESTIMATING_TEXT } from './Progress';

describe('Progress — R48.4, the time slot is never empty', () => {
  it('renders the estimate when there is one', () => {
    render(<Progress label="Reading the recording" pct={31} etaText="42 s" data-testid="p" />);
    expect(screen.getByTestId('p-eta').textContent).toContain('42 s');
  });

  it('says it is working the time out when there is no estimate yet — never a blank slot', () => {
    // This is the bug the ruling was written against: four screens rendered an empty <span> here.
    render(<Progress label="Building" pct={4} etaText={null} data-testid="p" />);
    const slot = screen.getByTestId('p-eta');
    expect(slot.textContent).toContain(ESTIMATING_TEXT);
    expect(slot.textContent?.trim()).not.toBe('');
  });

  it('runs the elapsed clock beside it, so a silent phase still has a number that moves', () => {
    // R48.4/R48b — this is what satisfies the rule WITHOUT the forbidden server-side heartbeat.
    render(<Progress label="Building" pct={4} etaText={null} elapsedText="3m 41s" data-testid="p" />);
    expect(screen.getByTestId('p-eta').textContent).toContain('3m 41s so far');
  });
});

describe('Progress — R48.2, the ARIA contract', () => {
  it('a determinate bar carries its value', () => {
    render(<Progress label="Copying a recording in" pct={68} data-testid="p" />);
    const bar = screen.getByRole('progressbar');
    expect(bar.getAttribute('aria-valuenow')).toBe('68');
    expect(bar.getAttribute('aria-valuemin')).toBe('0');
    expect(bar.getAttribute('aria-valuemax')).toBe('100');
    expect(bar.getAttribute('aria-label')).toBe('Copying a recording in');
  });

  it('an indeterminate bar carries NO value — that is how "running, length unknown" is said', () => {
    render(<Progress label="Looking for recordings" pct={null} data-testid="p" />);
    const bar = screen.getByRole('progressbar');
    expect(bar.getAttribute('aria-valuenow')).toBeNull();
    expect(bar.getAttribute('aria-busy')).toBe('true');
  });
});

describe('Progress — R48.9, an unknown length must not look like a stalled bar', () => {
  it('a determinate bar floors at 2% so 0% reads as started, not broken', () => {
    render(<Progress label="Building" pct={0} data-testid="p" />);
    expect(screen.getByTestId('p-bar').style.width).toBe('2%');
  });

  it('an indeterminate bar gets NO inline width — a bar parked at 2% is what R48.9 forbids', () => {
    render(<Progress label="Looking" pct={null} data-testid="p" />);
    expect(screen.getByTestId('p-bar').style.width).toBe('');
  });

  it('clamps above 100 rather than overflowing its track', () => {
    render(<Progress label="Building" pct={140} data-testid="p" />);
    expect(screen.getByTestId('p-bar').style.width).toBe('100%');
  });

  it('shows no percentage at all when indeterminate — an invented number is worse than none', () => {
    render(<Progress label="Looking" pct={null} data-testid="p" />);
    expect(screen.queryByTestId('p-pct')).toBeNull();
  });
});

describe('Progress — R48.7, never render a Stop that is not wired', () => {
  it('renders Stop when it is wired, and it calls back', () => {
    const stop = vi.fn();
    render(<Progress label="Building" pct={10} onStop={stop} data-testid="p" />);
    screen.getByTestId('p-stop').click();
    expect(stop).toHaveBeenCalledOnce();
  });

  it('renders NO button when there is no handler — it says why instead', () => {
    render(
      <Progress
        label="Deleting the project"
        pct={null}
        unstoppableWhy="a delete cannot be stopped once it starts"
        data-testid="p"
      />,
    );
    expect(screen.queryByTestId('p-stop')).toBeNull();
    expect(screen.getByText(/cannot be stopped once it starts/)).toBeTruthy();
  });

  it('renders nothing where the button would be when neither is given', () => {
    render(<Progress label="Building" pct={10} data-testid="p" />);
    expect(screen.queryByTestId('p-stop')).toBeNull();
  });
});
