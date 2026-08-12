// A render smoke for the Place step on an EMPTY sweep store (the state before the shell hydrates). With
// no session it fires no network calls, so this needs no mocks — it is the pre-hydrate safety net (the
// full build/seed behaviour is the Playwright e2e against the real backend).

import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { useSweepStore } from '../../store';
import { PlaceStep } from './PlaceStep';

afterEach(() => {
  cleanup();
  useSweepStore.getState().reset();
});

describe('PlaceStep renders on an empty (pre-hydrate) store', () => {
  it('exposes its cost / gpu / run / cache / skip / advanced controls', () => {
    render(<PlaceStep onNavigate={() => {}} />);
    expect(screen.getByTestId('place-cost')).toBeInTheDocument();
    expect(screen.getByTestId('place-gpu')).toBeInTheDocument();
    expect(screen.getByTestId('place-run')).toBeInTheDocument();
    expect(screen.getByTestId('place-use-cache')).toBeInTheDocument();
    expect(screen.getByTestId('place-skip')).toBeInTheDocument();
    expect(screen.getByTestId('place-advanced')).toBeInTheDocument();
  });

  it('the Advanced drawer says it is off the validated path (R7.4)', () => {
    render(<PlaceStep onNavigate={() => {}} />);
    expect(screen.getByTestId('place-advanced')).toHaveTextContent(/off the validated path/i);
  });

  it('Run is disabled with no session/document to build', () => {
    render(<PlaceStep onNavigate={() => {}} />);
    expect(screen.getByTestId('place-run')).toBeDisabled();
  });
});
