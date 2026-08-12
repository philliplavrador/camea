// The contact sheet's RED FRAME (his ask, 2026-07-24): a snapshot that is not a tile of this mosaic is
// framed red, and it says why on hover.
//
// A project opens on every square snapshot the dataset holds, and a real acquisition carries strays taken
// before the scan started (`1`, `5-7` ahead of the run on 260620d). They were rendered exactly like the
// tiles, so the sheet claimed 342 tiles for a 338-tile mosaic.
//
// ⛔ Red is NOT `excluded`. Excluding is `E`, in the sweep, and it is his. This test pins that too.
// ⛔ And the membership rule is the SERVER's (`POST /api/mosaic/run` — log.txt + the per-trial XML
//    shape): the sheet only renders the answer, so the mock here is the whole rule.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { MosaicDocument } from '../../../../api';

const RUN = [11, 12, 13];
const LOADED = [1, 5, ...RUN]; // what the session holds: the strays AND the run

const detectRun = vi.fn(async ({ lo, hi }: { lo?: number | null; hi?: number | null }) => {
  const l = lo ?? 11;
  const h = hi ?? 13;
  return {
    lo: l,
    hi: h,
    // the shape gate: trial 5 is real data at the wrong shape, so it is NEVER a tile
    trials: LOADED.filter((t) => t >= l && t <= h && t !== 5),
    n: LOADED.filter((t) => t >= l && t <= h && t !== 5).length,
    n_in_range: h - l + 1,
    detected: lo == null && hi == null,
    why: 'longest run of Snapshot trials',
    blocks: [],
    dropped: LOADED.filter((t) => t === 5 && t >= l && t <= h).map((t) => ({
      trial: t,
      reason: 'off_shape' as const,
      w: 512,
      h: 128,
    })),
    pass_split: { value: 12, detected: true, why: 'measured', n_pass1: 2, n_pass2: 1 },
    gaps: [],
  };
});

vi.mock('../../../../api', () => ({
  detectRun: (req: { lo?: number | null; hi?: number | null }) => detectRun(req),
  rescopeDocument: vi.fn(async () => ({})),
  getThumbsLayout: vi.fn(async () => ({
    grid: 3,
    cell: 64,
    trials: LOADED,
    n: LOADED.length,
    version: 'v1',
  })),
  thumbsPngUrl: () => 'about:blank',
  matchAnchor: vi.fn(async () => ({})),
  matchScore: vi.fn(async () => ({})),
  computeGaps: vi.fn(async () => ({ gaps: [] })),
}));

import { ToastProvider } from '../../../../app';
import { useSweepStore } from '../../store';
import { RangeStep } from './RangeStep';

function mkDoc(): MosaicDocument {
  const tile = { status: 'unplaced', state: 'unplaced', x: null, y: null, blank: false };
  return {
    tiles: Object.fromEntries(LOADED.map((t) => [String(t), { ...tile }])),
    cursor: null,
    origin_trial: LOADED[0],
    gaps: [],
    unusable_tiles: [],
    trial_range: [LOADED[0], LOADED[LOADED.length - 1]],
    pass_split: 12,
    modified: 't0',
  } as unknown as MosaicDocument;
}

const cellOf = (trial: number): HTMLElement | null =>
  document.querySelector(`[data-testid="contact-cell"][data-trial="${trial}"]`);

beforeEach(() => {
  detectRun.mockClear();
  useSweepStore.getState().reset();
  useSweepStore.getState().hydrate(mkDoc(), { sessionId: 'S', order: LOADED });
});
afterEach(() => {
  cleanup();
  useSweepStore.getState().reset();
});

function mount(onNavigate: (id: string) => void = () => {}) {
  return render(
    <ToastProvider>
      <RangeStep onNavigate={onNavigate as never} />
    </ToastProvider>,
  );
}

describe('the contact sheet marks what is not a tile of this mosaic', () => {
  it('frames the snapshots that are not tiles of the detected run, and nothing else', async () => {
    mount();
    await waitFor(() => expect(cellOf(11)).toBeInTheDocument());

    await waitFor(() => expect(cellOf(1)).toHaveAttribute('data-out'));
    expect(cellOf(5)).toHaveAttribute('data-out');
    for (const t of RUN) expect(cellOf(t)).not.toHaveAttribute('data-out');
    expect(screen.getByTestId('sheet-n-out')).toHaveTextContent('2');
  });

  it('says WHY on hover, and tells the two causes apart', async () => {
    mount();
    await waitFor(() => expect(cellOf(1)).toHaveAttribute('data-out'));
    expect(cellOf(1)).toHaveAttribute('data-out-reason', 'range');
    expect(cellOf(1)!.getAttribute('title')).toMatch(/outside the range 11–13/);
    expect(cellOf(12)!.getAttribute('title')).toBe('trial 12');

    // Widen the range so 5 is INSIDE it: it is still not a tile — now for the other reason.
    fireEvent.change(screen.getByTestId('range-lo'), { target: { value: '1' } });
    await waitFor(() => expect(cellOf(5)).toHaveAttribute('data-out-reason', 'unusable'));
    expect(cellOf(5)!.getAttribute('title')).toMatch(/not a tile: the frame is 512×128/);
  });

  it('a framed cell is not a destination — it does not jump into the sweep', async () => {
    const onNavigate = vi.fn();
    mount(onNavigate);
    await waitFor(() => expect(cellOf(1)).toHaveAttribute('data-out'));

    fireEvent.click(cellOf(1)!);
    expect(onNavigate).not.toHaveBeenCalled();

    fireEvent.click(cellOf(12)!); // an ordinary tile still is one
    expect(onNavigate).toHaveBeenCalledWith('sweep');
  });

  it('⛔ red is not an exclusion: the document is untouched until Apply', async () => {
    mount();
    await waitFor(() => expect(cellOf(1)).toHaveAttribute('data-out'));
    const doc = useSweepStore.getState().doc!;
    expect(doc.unusable_tiles).toEqual([]);
    expect(doc.tiles['1'].state).toBe('unplaced');
  });

  it('the marking is LIVE against the range he is typing', async () => {
    mount();
    await waitFor(() => expect(cellOf(1)).toHaveAttribute('data-out'));

    fireEvent.change(screen.getByTestId('range-lo'), { target: { value: '1' } });
    // 1 rejoins the mosaic; 5 stays framed, because its FRAME is the wrong shape.
    await waitFor(() => expect(cellOf(1)).not.toHaveAttribute('data-out'));
    expect(cellOf(5)).toHaveAttribute('data-out-reason', 'unusable');
    expect(screen.getByTestId('sheet-n-out')).toHaveTextContent('1');
  });
});
