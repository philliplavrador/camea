/**
 * Path-text helpers for the paste box (PathField.tsx). Pure string work — no fetch, no React — so
 * the paste tolerance the user actually feels is unit-testable (pathText.test.ts).
 */

/**
 * Normalise what a human actually pastes into what the backend wants:
 * `"D:\Projects\Camea\data"` (Explorer's Copy-as-path, quotes and all) → `D:/Projects/Camea/data`.
 */
export function normalisePath(raw: string): string {
  let s = raw.trim();
  if (s.length >= 2 && ((s[0] === '"' && s.endsWith('"')) || (s[0] === "'" && s.endsWith("'")))) {
    s = s.slice(1, -1).trim();
  }
  s = s.replace(/\\/g, '/');
  // Collapse runs of slashes, but keep a leading `//` — that is a UNC share, not a typo.
  const unc = s.startsWith('//');
  s = s.replace(/\/{2,}/g, '/');
  return unc ? `/${s}` : s;
}

/** The part before the last `/` (the folder to list) and the part after it (what to match on). */
export function splitPath(text: string): { dir: string; frag: string } {
  const i = text.lastIndexOf('/');
  if (i < 0) return { dir: '', frag: text };
  return { dir: text.slice(0, i + 1), frag: text.slice(i + 1) };
}

/**
 * A chip-sized label for a path. The distinctive part of `D:/Projects/Camea/data/drive/260620/…`
 * is its TAIL, so keep the last segments and elide the head — truncating the end would render three
 * different roots as three identical chips. The full path stays in the `title`.
 */
export function shortPath(p: string, maxLen = 34): string {
  const s = normalisePath(p).replace(/\/$/, '');
  if (s.length <= maxLen) return s;
  const parts = s.split('/').filter(Boolean);
  for (let take = 2; take >= 1; take--) {
    const tail = `…/${parts.slice(-take).join('/')}`;
    if (tail.length <= maxLen || take === 1) return tail;
  }
  return s;
}

/** Trailing `/` is noise to the scanner — except on `D:/`, where it is the whole path. */
export function forSubmit(text: string): string {
  const s = normalisePath(text);
  if (s.length > 1 && s.endsWith('/') && !/^[A-Za-z]:\/$/.test(s)) return s.slice(0, -1);
  return s;
}
