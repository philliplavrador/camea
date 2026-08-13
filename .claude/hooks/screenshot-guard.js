#!/usr/bin/env node
// PreToolUse (screenshot tools) — keep browser screenshots out of the repo root.
//
// Imported from Labstock's screenshot-guard.js on 2026-08-13; only the allowed
// destinations are Camea's.
//
// Both MCP browsers resolve a BARE filename against the process cwd, which is the repo:
// Playwright's `filename: "sweep.png"` and chrome-devtools' `filePath: "sweep.png"` both
// write D:\Projects\Camea\sweep.png. Playwright's own tool description even says to
// "prefer relative file names to stay within the output directory" — it is wrong; the
// relative path never consults --output-dir. Camea's .gitignore does not exclude stray
// PNGs at the root, so one that lands there ships with the next `git add`.
//
// Silent unless it denies. The best case — chrome-devtools with NO path, which returns the
// image inline and never touches disk — must sail straight through, so a missing path is
// an exit-0 allow, not a warning.
//
// Fails OPEN on any internal error (exit 0).

const fs = require('fs');
const path = require('path');

const REPO = (process.env.CLAUDE_PROJECT_DIR || process.cwd()).replace(/\\/g, '/');

// Repo-relative directories a screenshot may legitimately land in.
//   .scratch/                  throwaway, gitignored
//   docs/screenshots/          embedded in a doc
//   web/tests/e2e/screenshots/ script-owned — the Playwright suite writes here itself, so
//                              it is allowed to keep its own harness unblocked, not
//                              somewhere to hand-place a file.
//   .playwright-mcp/           the MCP server's own output dir, already gitignored
const ALLOWED = ['.scratch/', 'docs/screenshots/', 'web/tests/e2e/screenshots/', '.playwright-mcp/'];

function main() {
  let payload;
  try {
    payload = JSON.parse(fs.readFileSync(0, 'utf8'));
  } catch {
    process.exit(0);
  }

  // If the harness tells us which tool this is, only judge the screenshot ones — a broad
  // matcher must not start policing every tool that happens to carry a filePath (e.g.
  // take_heapsnapshot). Absent tool_name, judge it: the path is the evidence.
  const tool = payload?.tool_name;
  if (typeof tool === 'string' && tool && !/screenshot/i.test(tool)) process.exit(0);

  const input = payload?.tool_input || {};
  const raw = input.filename ?? input.filePath; // Playwright ?? chrome-devtools
  if (typeof raw !== 'string' || !raw.trim()) process.exit(0); // no path → inline image

  const given = raw.trim();
  if (isAllowed(given)) process.exit(0);

  process.stdout.write(
    JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'PreToolUse',
        permissionDecision: 'deny',
        permissionDecisionReason: reasonFor(given),
      },
    }),
  );
  process.exit(0);
}

function isAllowed(given) {
  // Relative is never allowed, even `.scratch/x.png`: what it resolves against is the
  // whole bug. Absolute is the only form whose destination is knowable from the call.
  if (!/^([a-zA-Z]:[\\/]|\\\\|\/)/.test(given)) return false;

  const abs = path.resolve(given).replace(/\\/g, '/'); // collapses any ../ escape
  const lower = abs.toLowerCase();
  const repo = REPO.toLowerCase();
  const inRepo = lower === repo || lower.startsWith(`${repo}/`);
  if (!inRepo) return true; // outside the repo entirely — the session scratchpad case

  const rel = abs.slice(REPO.length + 1).toLowerCase();
  return ALLOWED.some((dir) => rel.startsWith(dir));
}

function reasonFor(given) {
  return (
    `Screenshot path "${given}" would land somewhere it must not. A bare or relative name ` +
    `resolves against the repo root, so it writes ${REPO}/${path.basename(given)} — and ` +
    `Camea's .gitignore does not exclude a stray PNG at the root, so it ships with the ` +
    `next commit. Pass an ABSOLUTE path in one of:\n` +
    `  • throwaway → your session scratchpad, outside the repo (chrome-devtools only)\n` +
    `  • keep it locally, never committed → ${REPO}/.scratch/\n` +
    `  • embedded in a doc → ${REPO}/docs/screenshots/\n` +
    `Best of all, for chrome-devtools' take_screenshot: pass NO path — it returns the ` +
    `image inline and never touches disk. That is usually the right answer.\n` +
    `For Playwright's browser_take_screenshot the scratchpad is NOT an option: it refuses ` +
    `absolute paths outside its own allowed roots. Use an absolute path under ` +
    `${REPO}/.scratch/, or under PLAYWRIGHT_MCP_OUTPUT_DIR.`
  );
}

try {
  main();
} catch {
  process.exit(0); // a broken guard must never block a screenshot it has no opinion on
}
