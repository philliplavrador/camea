---
id: 012
title: The e2e suite writes test projects into the user's real store whenever a dev backend is already running
kind: bug
tier: medium
confidence: high
status: open
found: 2026-08-15
found-while: he asked why three projects he never made had appeared on his home screen
resolved-by: ~
---

# 012 — The e2e suite writes test projects into the user's real store whenever a dev backend is already running

## What's wrong

`playwright.config.ts` isolates the suite's project store by starting the backend with
`CAMEA_STATE_DIR=web/.playwright-state`, which `app_state_dir()` honours. That isolation is real —
but it only applies to a backend **Playwright itself starts**.

`reuseExistingServer: !process.env.CI` means that if a dev backend is already listening on 8000
(started by hand for browser-driving, which is exactly what a `needs: dev server` build does), the
suite silently attaches to it instead — and that process has **no `CAMEA_STATE_DIR`**, so every
project the tests create lands in `%LOCALAPPDATA%/Camea/projects`, beside his own.

It fails in the quietest possible way: the suite passes, and the damage shows up on his home screen
some time later as projects he never made.

## Evidence

Seen 2026-08-15. Three unexplained cards — *"same picker" ×2* and *"one call"* — plus one folder
reported as unreadable. Their names come straight out of the spec:

- [analyze-mea.spec.ts:98](../../../web/tests/e2e/analyze-mea.spec.ts#L98) — `toFilesStep(page, 'one call')`
- [analyze-mea.spec.ts:140](../../../web/tests/e2e/analyze-mea.spec.ts#L140) — `toFilesStep(page, 'same picker')`

Both stores, side by side — the isolated one holds every run where Playwright started the backend
itself, the real one holds the run that reused a hand-started dev server:

```console
$ ls %LOCALAPPDATA%/Camea/projects
p003658-e48301  p003693-5f2ebd  p003658-19cc31          # his
one-call-a87787  same-picker-a7026b  same-picker-19453e  chip-map-70be8c   # 2026-08-15 15:36–15:39

$ ls web/.playwright-state/projects
same-picker-* x12  removing-a77b48                      # 2026-08-14, correctly isolated
```

`chip-map-70be8c` holds a `document.camea.json` and **no marker file**, so `_read_manifest()` raises
and it lists as unreadable — a project the suite was midway through creating when the servers were
stopped. A torn-down test run leaving a corrupt folder is harmless in a throwaway store; in his it is
a permanent error banner on the first screen he sees.

## Where to start

The config is not wrong about *what* to isolate, only about *when* it can. Two candidates:

- **Make reuse conditional on the state dir matching.** Playwright can't inspect the running
  process's environment, but the backend can report it — `/api/health` could return the store root,
  and a `globalSetup` could refuse to run against a backend whose store isn't the harness's.
  Fails loudly, which is the property that is missing today.
- **Drop `reuseExistingServer` for the backend only** (keep it for Vite, which writes nothing).
  Costs a backend start per run and forces the developer to stop theirs; simple, and impossible to
  get wrong.

⚠️ Whatever lands must not make the failure quieter. The bad outcome here was never the wasted
minute — it was that nothing said a word.

Cleanup of the four folders already in his store is a separate, manual matter; deleting them is safe
(each is a fixture-backed test project, none holds his data).
