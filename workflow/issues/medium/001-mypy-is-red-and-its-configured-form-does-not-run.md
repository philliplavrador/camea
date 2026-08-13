---
id: 001
title: mypy cannot run as configured, and reports 48 errors when invoked so that it can
kind: bug
tier: medium
status: open
found: 2026-08-13
found-while: importing the Labstock workflow — wiring the Stop hook's gate table
resolved-by: ~
---

# 001 — mypy cannot run as configured, and reports 48 errors when invoked so that it can

## What's wrong

Two separate faults, found together.

**The configured invocation does not work at all.** `pyproject.toml` sets
`[tool.mypy] packages = ["camea"]`, so a bare `uv run mypy` resolves the *installed*
package and stops:

```
Package 'camea' cannot be type checked due to missing py.typed marker
```

It exits **2** — a usage error, not a type error — so anything treating a non-zero exit as
"types are broken" reads it wrong.

**Invoked so that it can run, it is red.** `uv run mypy src/camea` works and finds
**48 errors in 14 files**. None of them was introduced by this change; they were already
there.

## Evidence

```
$ uv run mypy
Package 'camea' cannot be type checked due to missing py.typed marker
See https://mypy.readthedocs.io/en/stable/installed_packages.html for more details
exit 2                                                              (measured 2026-08-13)

$ uv run mypy src/camea
src\camea\features\videomosaic\routes.py:365: error: Argument 1 to "load_analysis" has
  incompatible type "ProjectSet"; expected "Workspace"  [arg-type]
src\camea\features\videomosaic\routes.py:463: error: (same)
src\camea\features\videomosaic\routes.py:493: error: (same)
Found 48 errors in 14 files (checked 48 source files)
exit 1, 4.4s
```

The `ProjectSet` / `Workspace` mismatch above is the one worth a look first: three call
sites pass a `ProjectSet` where `load_analysis` is annotated for a `Workspace`. Either the
annotation is stale after the project-manager reframe (2026-07-24) or those calls are
wrong.

## Why this tier

`medium`. Nothing is broken for a user today — mypy is not in CI and nothing gates on it.
What it costs is the gate: **a type checker that cannot be trusted cannot be wired in**, so
[.claude/hooks/stop-gates.js](../../../.claude/hooks/stop-gates.js) had to mark `mypy` as
`deferred` on the day the hook landed. Until this is fixed, type errors reach `master`
unchallenged, and the three `load_analysis` call sites may be a real defect hiding behind
the noise.

Not `high`: no verified work is lost and the science is untouched.

## What it would take

Two pieces, and the first is mechanical.

1. **Make the configured form run.** Either add a `py.typed` marker to `src/camea/` (and
   list it in the package data) so `packages = ["camea"]` resolves, or change
   `[tool.mypy]` to `files = ["src/camea"]` so it type-checks the source tree directly.
   The second is a one-line change and is probably right for a repo that installs itself
   editable.

2. **Decide what to do with the 48.** There is a real fork here and `/resolve` should ask:
   fix them all before wiring the gate, or add a `--max`-style ratchet like the one
   `scripts/check-rulings.js` already uses, so the existing debt is tolerated and a 49th
   fails. The ratchet is cheaper and starts protecting immediately; fixing them all is
   cleaner and may surface a genuine bug in `load_analysis`.

When it is green (or ratcheted), delete `deferred: true` from the `mypy` row in
[stop-gates.js](../../../.claude/hooks/stop-gates.js).

## Not investigated

Whether any of the 48 is an actual runtime bug rather than a stale annotation. The three
`ProjectSet` / `Workspace` ones look like the best candidates and nothing else was read.
The other 45 were not classified.
