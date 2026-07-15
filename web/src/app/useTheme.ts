import { useCallback, useEffect, useState } from 'react';

/**
 * Theme control for the shell. Camea's working theme is DARK (a dim microscope room); LIGHT is the
 * "bright bench" (DESIGN_BRIEF §1.5). The token file (`design/tokens.css`) drives everything off a
 * `data-theme` attribute on <html>, and follows the OS when no attribute is present.
 *
 * So there are three real states:
 *   - explicit "dark"  → stamp data-theme="dark"      (ignore the OS)
 *   - explicit "light" → stamp data-theme="light"
 *   - no choice yet    → remove the attribute          (follow prefers-color-scheme)
 * A manual toggle always writes an EXPLICIT choice. Until then we mirror the OS live.
 */
export type Theme = 'dark' | 'light';

const STORAGE_KEY = 'camea-theme';

function readStored(): Theme | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === 'dark' || v === 'light' ? v : null;
  } catch {
    return null; // private mode / disabled storage — fall back to the OS
  }
}

function osTheme(): Theme {
  return typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-color-scheme: light)').matches
    ? 'light'
    : 'dark';
}

function apply(theme: Theme | null) {
  const root = document.documentElement;
  if (theme) root.setAttribute('data-theme', theme);
  else root.removeAttribute('data-theme'); // follow the OS
}

export interface ThemeControl {
  /** The currently RESOLVED theme (explicit choice, else the OS preference). */
  theme: Theme;
  /** Set an explicit theme (persisted). */
  setTheme: (t: Theme) => void;
  /** Flip to the other theme (always writes an explicit choice). */
  toggle: () => void;
}

export function useTheme(): ThemeControl {
  const [theme, setThemeState] = useState<Theme>(() => readStored() ?? osTheme());

  useEffect(() => {
    const stored = readStored();
    apply(stored); // stamp the explicit choice, or clear the attribute to follow the OS
    if (stored) return;
    // No explicit choice: track OS changes live so the toggle icon and page stay in sync.
    const mq = window.matchMedia('(prefers-color-scheme: light)');
    const onChange = () => setThemeState(osTheme());
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);

  const setTheme = useCallback((t: Theme) => {
    try {
      localStorage.setItem(STORAGE_KEY, t);
    } catch {
      /* storage disabled — the in-memory + DOM state below still applies for this session */
    }
    apply(t);
    setThemeState(t);
  }, []);

  const toggle = useCallback(
    () => setTheme(theme === 'dark' ? 'light' : 'dark'),
    [theme, setTheme],
  );

  return { theme, setTheme, toggle };
}
