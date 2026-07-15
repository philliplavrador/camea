import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { formatEta, reanchorEta } from './jobs';
import type { Job } from './types';

// A Job carrying only the field `reanchorEta` reads. Fixtures may use literal numbers (HARD RULE 3
// forbids dataset knowledge in APP code, not in tests).
const job = (eta: number | null | undefined): Job => ({ eta_s: eta }) as unknown as Job;

describe('formatEta — the Place ETA format (BEHAVIOUR R8.6, R8.3)', () => {
  it('formats minutes+seconds with a zero-padded second: 901 → "15m 01s"', () => {
    expect(formatEta(901)).toBe('15m 01s');
  });

  it('formats sub-minute as "N s": 47 → "47 s"', () => {
    expect(formatEta(47)).toBe('47 s');
  });

  it('rolls 60 up into minutes: 60 → "1m 00s"', () => {
    expect(formatEta(60)).toBe('1m 00s');
  });

  it('shows "almost there…" below 1 s — never a countdown to zero that reads as done', () => {
    expect(formatEta(0.4)).toBe('almost there…');
    expect(formatEta(0)).toBe('almost there…');
  });

  it('NEVER renders a negative time (R8.3): a clamped-to-0 input is "almost there…"', () => {
    // The hook clamps at 0 before formatting; formatEta must also never emit a "-" for a stray negative.
    expect(formatEta(-437)).toBe('almost there…');
  });

  it('returns null when there is no ETA to show (a silent phase before any number)', () => {
    expect(formatEta(null)).toBeNull();
  });

  it('every formatted value matches the e2e ETA_FORMAT regex', () => {
    const ETA_FORMAT = /^(?:\d+m \d{2}s|\d+ s|almost there…?)$/i;
    for (const s of [901, 47, 60, 3599, 3600, 1, 0.4, 0]) {
      const txt = formatEta(s);
      expect(txt, `formatEta(${s})`).toMatch(ETA_FORMAT);
      expect(txt).not.toMatch(/-\d/);
    }
  });
});

describe('reanchorEta — re-anchor ONLY on a genuine server change (BEHAVIOUR R8.2/R8.4)', () => {
  const T0 = 1_000_000;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(T0);
  });
  afterEach(() => vi.useRealTimers());

  it('anchors on the first real number', () => {
    const lastRaw = { current: null as number | null };
    const anchor = { current: null as { etaS: number; at: number } | null };
    reanchorEta(job(205), lastRaw, anchor);
    expect(anchor.current).toEqual({ etaS: 205, at: T0 });
    expect(lastRaw.current).toBe(205);
  });

  it('🔴 the SAME number repeated does NOT re-anchor — this is what keeps the countdown moving', () => {
    const lastRaw = { current: null as number | null };
    const anchor = { current: null as { etaS: number; at: number } | null };
    reanchorEta(job(205), lastRaw, anchor); // anchor at T0
    vi.setSystemTime(T0 + 5000); // 5 s of silent polls later
    reanchorEta(job(205), lastRaw, anchor); // server still says 205
    reanchorEta(job(205), lastRaw, anchor);
    // The anchor is untouched, so the client clock keeps ticking down from T0 (not reset to T0+5000).
    expect(anchor.current).toEqual({ etaS: 205, at: T0 });
  });

  it('a NULL (silent phase) does not re-anchor and keeps the clock running', () => {
    const lastRaw = { current: null as number | null };
    const anchor = { current: null as { etaS: number; at: number } | null };
    reanchorEta(job(205), lastRaw, anchor);
    vi.setSystemTime(T0 + 3000);
    reanchorEta(job(null), lastRaw, anchor);
    expect(anchor.current).toEqual({ etaS: 205, at: T0 });
    expect(lastRaw.current).toBeNull();
  });

  it('a CHANGED number re-anchors (fresh clock), including an honest upward jump (R8.4)', () => {
    const lastRaw = { current: null as number | null };
    const anchor = { current: null as { etaS: number; at: number } | null };
    reanchorEta(job(30), lastRaw, anchor);
    vi.setSystemTime(T0 + 1000);
    reanchorEta(job(120), lastRaw, anchor); // the silent phase reported a WORSE estimate
    expect(anchor.current).toEqual({ etaS: 120, at: T0 + 1000 });
  });

  it('the same number AFTER a null is a fresh report and re-anchors', () => {
    const lastRaw = { current: null as number | null };
    const anchor = { current: null as { etaS: number; at: number } | null };
    reanchorEta(job(90), lastRaw, anchor); // anchor at T0
    vi.setSystemTime(T0 + 2000);
    reanchorEta(job(null), lastRaw, anchor); // silence
    vi.setSystemTime(T0 + 4000);
    reanchorEta(job(90), lastRaw, anchor); // child printed again — a real new 90
    expect(anchor.current).toEqual({ etaS: 90, at: T0 + 4000 });
  });
});
