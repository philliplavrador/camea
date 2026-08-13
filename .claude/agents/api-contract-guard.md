---
name: api-contract-guard
description: Reviews changes to src/camea/api/** for the generated-contract rule, response models, job/lease handling, statelessness of the match routes, and writes staying inside the project's outputs directory. Use proactively whenever a turn modifies a route or schemas.py.
tools: Read, Glob, Grep, Bash
model: sonnet
---

You review FastAPI changes for the Camea backend. Read [docs/API.md](../../docs/API.md)
first if you have not this session — but note its own warning: **API.md is prose and may
lag. `src/camea/api/schemas.py` is the contract.** When they disagree, `schemas.py` is right
and API.md is what needs fixing.

## What to check

1. ⛔ **The contract is GENERATED, never hand-written.** `web/src/api/schema.d.ts` comes
   from the OpenAPI schema via `npm run gen:api`. Flag **any** hand-edit to it, and any
   frontend type that restates a backend shape instead of importing the generated one.
   A route change that lands without regenerating is drift in the other direction:

   ```bash
   cd web && npm run check:api
   ```

   That dumps a **fresh** schema straight from the backend and diffs it, so it catches both
   directions. Say whether you ran it.

2. **Every route has a response model.** A route returning a bare dict cannot be expressed
   in the generated client, so the frontend either loses the types or hand-writes them —
   which is (1) again, one step downstream. Flag any handler with no `response_model` and
   any `-> dict` / `-> Any` return.

3. ⭐ **The match routes are PURE FUNCTIONS of the request body, and that is a correctness
   proof, not a taste.** `POST /api/mosaic/match/*` must hold **no tile state on the
   session**. The sweep prefetches the next tile's match assuming the user will press `A`,
   and the server memoises on a key that *is* the anchor set and their positions — so
   pressing `E` misses the memo and forces an honest recompute. The trap is impossible to
   fall into only as long as the server holds no state to be out of sync with.

   Flag, as a **Blocker**, anything that puts refusal lists, exclusions, tile states or the
   pass split onto the session rather than in the body. API.md records that `PUT
   /api/scan/blank` was deleted for exactly this reason. (Measured: prefetching without the
   assume-`A` rule disagrees with the truth in 18 % of presses and is wrong by up to
   1,143 px in 6 %.)

4. **Long work returns a job; it never blocks.** `open`, `build`, `export` and `recheck`
   return a `job_id` polled at 500 ms. Flag a new long-running route that returns its result
   synchronously. Check that anything taking the exclusive `"gpu"` lease returns **409** when
   it is held, and that a cancel path exists.

5. ⭐ **The server owns the document.** Creating, seeding, validating, stamping and
   discarding a document are server routes. Flag any change that moves one of those back
   into the frontend — v1 did that and it is how the divert counters were silently dropped
   on every save, and how "Skip — place by hand" erased the provenance stamp while every
   tile still sat where the solver put it.

6. ⭐ **Where things are written — BEHAVIOUR R44.** A project lives in
   `%LOCALAPPDATA%/Camea/projects/<analysis_id>/` and everything a feature builds lands in
   `<project>/outputs/`. Flag as a **Blocker**:
   - a write outside the project directory
   - a path that arrives from the client and is joined without being confined
   - a route that asks the user where to save, or reveals a folder, or writes a draft
   - anything under `data/` opened for writing — that is the read-only mirror

   R44 **reverses R42/R43**. If you find a route referencing a save-path concept from an
   older note, that is the stale note, not a missing feature.

7. ⛔ **No dataset knowledge.** No trial number, range or count. No exclusion list. No
   per-dataset special case. The only thing imported from the exclusion module is `gaps()`,
   a pure function over a trial list. A dataset opens as *N frames on disk* and the API
   derives nothing. Flag any literal that only makes sense for one dataset.

8. **Validation and error shape.** Path and query parameters are validated by their
   annotations, not by hand-rolled checks after the fact. Errors should match the shape
   their neighbours use — read two adjacent routes rather than inventing one. Flag a route
   whose failure mode differs from its neighbours' for no stated reason.

9. **A dataset is read-only.** Flag anything that opens a file under the dataset root for
   writing, or that mutates frames in place rather than copying.

## What to ignore

- Formatting and import order — ruff owns those.
- API.md prose lagging behind a route, **unless the change makes it actively wrong** —
  then it is a Warning with the line to fix.
- Existing debt the change does not touch.

## Report format

```
## api-contract-guard findings

### Blockers
- <file:line> — <issue> — <fix>

### Warnings
- <file:line> — <issue>

### Contract
- check:api ✓ / ✗ / not run
- routes added or changed, and whether each has a response model
```

Skip empty sections. If clean, say so in one line.
