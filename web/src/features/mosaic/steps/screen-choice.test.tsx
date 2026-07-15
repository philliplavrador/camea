// Behavioural unit test for the Screen step's three-way control (BEHAVIOUR R6). It hydrates the sweep
// store with two scanned frames and mocks the blank proposal, then drives the buttons — the parts the
// pre-hydrate smoke cannot reach. The full path (E in the actual sweep) is a Playwright e2e; here we
// stand in for it by calling the store's `excludeAt` directly, which is exactly what the sweep does.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import type { MosaicDocument } from '../../../api';

// One mock of the api barrel covers BOTH importers (the store and the Screen) — they resolve to the
// same module. Provide every value export either uses; types are erased.
vi.mock('../../../api', () => ({
  matchAnchor: vi.fn(async () => ({})),
  matchScore: vi.fn(async () => ({})),
  computeGaps: vi.fn(async () => ({ gaps: [] })),
  proposeScreen: vi.fn(async () => ({
    threshold: 5.0,
    threshold_source: 'the 2.0th percentile of pass-1 texture',
    measure: 'std of DoG(sigma=3, sigma=30)',
    texture: { '12': 10.2, '13': 20.4 },
    proposed: [12, 13],
    n_proposed: 2,
    n_scanned: 2,
    margin_warning: null,
  })),
  useSession: () => ({ status: 'idle' as const }),
  cacheBuster: () => 'nonce.1',
  tilePngUrl: () => 'about:blank',
}));

import { ToastProvider } from '../../../app';
import { useSweepStore } from '../store';
import { ScreenStep } from './Screen';

function mkDoc(): MosaicDocument {
  const tile = {
    status: 'unplaced',
    state: 'unplaced',
    x: null,
    y: null,
    blank: false,
    human: false,
    stale: false,
    diverted: false,
  };
  return {
    tiles: { '12': { ...tile }, '13': { ...tile } },
    cursor: null,
    origin_trial: 0,
    gaps: [],
    unusable_tiles: [],
    trial_range: [12, 13],
    pass_split: 12,
    modified: 't0',
  } as unknown as MosaicDocument;
}

const cardOf = (trial: number): HTMLElement | null =>
  document.querySelector(`[data-testid="screen-card"][data-trial="${trial}"]`);

beforeEach(() => {
  useSweepStore.getState().reset();
  useSweepStore.getState().hydrate(mkDoc(), { sessionId: 'S', order: [12, 13] });
});
afterEach(() => {
  cleanup();
  useSweepStore.getState().reset();
});

describe('Screen three-way control (R6)', () => {
  it('R6.1/R6.2: each card has Keep · Hand place · Exclude, with Hand place the default', async () => {
    render(
      <ToastProvider>
        <ScreenStep onNavigate={() => {}} />
      </ToastProvider>,
    );
    const cards = await screen.findAllByTestId('screen-card');
    expect(cards).toHaveLength(2);
    const card = cardOf(12)!;
    expect(card).toHaveAttribute('data-choice', 'hand');
    const q = within(card);
    expect(q.getByTestId('screen-keep')).toBeInTheDocument();
    expect(q.getByTestId('screen-handplace')).toHaveAttribute('aria-pressed', 'true');
    expect(q.getByTestId('screen-exclude')).toBeInTheDocument();
    // Exactly one selected.
    expect(q.getByTestId('screen-keep')).toHaveAttribute('aria-pressed', 'false');
    expect(q.getByTestId('screen-exclude')).toHaveAttribute('aria-pressed', 'false');
  });

  it('R6.5: Exclude applies immediately (no Apply button)', async () => {
    render(
      <ToastProvider>
        <ScreenStep onNavigate={() => {}} />
      </ToastProvider>,
    );
    await screen.findAllByTestId('screen-card');
    fireEvent.click(within(cardOf(12)!).getByTestId('screen-exclude'));
    await waitFor(() => expect(cardOf(12)).toHaveAttribute('data-choice', 'exclude'));
  });

  it('R6.6: the card RE-DERIVES from live state — excluding in the sweep flips the card', async () => {
    render(
      <ToastProvider>
        <ScreenStep onNavigate={() => {}} />
      </ToastProvider>,
    );
    await screen.findAllByTestId('screen-card');
    expect(cardOf(13)).toHaveAttribute('data-choice', 'hand');
    // Stand in for pressing E in the sweep: the sweep calls the same store action.
    await act(async () => {
      await useSweepStore.getState().excludeAt(13);
    });
    await waitFor(() => expect(cardOf(13)).toHaveAttribute('data-choice', 'exclude'));
  });
});
