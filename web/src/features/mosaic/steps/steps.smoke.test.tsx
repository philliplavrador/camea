// A render smoke for the Load/Range/Screen step UIs. It mounts each against an EMPTY sweep store (no
// session, no document) — the state before the shell hydrates — and asserts they render without
// crashing and expose their testid contract. With no `sessionId` the steps fire no network calls, so
// this needs no API mocks; it is the pre-hydrate safety net, not the full behavioural suite (that is
// the Playwright e2e against the real backend, which needs the wizard shell to mount these).

import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import type { ReactElement } from 'react';
import { ToastProvider } from '../../../app';
import { useSweepStore } from '../store';
import { LoadStep } from './Load';
import { RangeStep } from './Range';
import { ScreenStep } from './Screen';

function mount(ui: ReactElement) {
  return render(<ToastProvider>{ui}</ToastProvider>);
}

afterEach(() => {
  cleanup();
  useSweepStore.getState().reset();
});

describe('wizard steps render on an empty (pre-hydrate) store', () => {
  it('Load exposes its dir / browse / open / phase / project controls and no load-result', () => {
    mount(<LoadStep onNavigate={() => {}} />);
    expect(screen.getByTestId('load-dir')).toBeInTheDocument();
    expect(screen.getByTestId('load-browse')).toBeInTheDocument();
    expect(screen.getByTestId('load-open')).toBeInTheDocument();
    expect(screen.getByTestId('load-phase')).toBeInTheDocument();
    expect(screen.getByTestId('load-project')).toBeInTheDocument();
    // R4.5/§6.6 — opening a directory NAVIGATES; there is no in-place result block.
    expect(screen.queryByTestId('load-result')).toBeNull();
  });

  it('Range shows the facts strip, the lo/hi/split inputs, and gaps read "none" on a fresh open', () => {
    mount(<RangeStep onNavigate={() => {}} />);
    expect(screen.getByTestId('range-facts')).toBeInTheDocument();
    expect(screen.getByTestId('range-lo')).toBeInTheDocument();
    expect(screen.getByTestId('range-hi')).toBeInTheDocument();
    expect(screen.getByTestId('range-split')).toBeInTheDocument();
    expect(screen.getByTestId('range-apply')).toBeInTheDocument();
    // R2.3 — gaps are "none" until the USER excludes something.
    expect(screen.getByTestId('fact-gaps')).toHaveTextContent(/none/i);
  });

  it('Screen shows the facts + grid, no bulk buttons (R6b), and no blur wording (R17)', () => {
    mount(<ScreenStep onNavigate={() => {}} />);
    expect(screen.getByTestId('screen-facts')).toBeInTheDocument();
    expect(screen.getByTestId('screen-grid')).toBeInTheDocument();
    // R6b — the bulk buttons are gone.
    expect(screen.queryByTestId('screen-tick-all')).toBeNull();
    expect(screen.queryByTestId('screen-tick-none')).toBeNull();
    expect(screen.queryByTestId('screen-exclude-ticked')).toBeNull();
    // R17 — no blur/sharpness score anywhere on the visible page.
    expect(document.body.textContent ?? '').not.toMatch(/blur|sharpness|laplacian|variance of/i);
  });
});
