import { IconButton } from '../design/primitives/IconButton';
import { useTheme } from './useTheme';

/**
 * The theme toggle — the one bit of chrome that changes the palette. It shows the CURRENT theme's
 * glyph (a moon in dark, a sun in light) and its accessible name states the action it performs.
 * Icons are inline SVG: the app runs offline in WebView2 with a CSP, so there is no icon-font pipeline.
 */
export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const next = theme === 'dark' ? 'light' : 'dark';
  return (
    <IconButton
      variant="ghost"
      size="sm"
      aria-label={`Switch to ${next} theme`}
      title={`Switch to ${next} theme`}
      data-testid="theme-toggle"
      onClick={toggle}
    >
      {theme === 'dark' ? <MoonIcon /> : <SunIcon />}
    </IconButton>
  );
}

function MoonIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" aria-hidden="true" fill="currentColor">
      <path d="M21 12.8A8.5 8.5 0 0 1 11.2 3a7 7 0 1 0 9.8 9.8Z" />
    </svg>
  );
}

function SunIcon() {
  return (
    <svg
      width="15"
      height="15"
      viewBox="0 0 24 24"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
    >
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </svg>
  );
}
