---
description: Start the app — backend on 8000, frontend on 5173
allowed-tools: Bash, Read, Glob, Grep, AskUserQuestion
---

# Run it

Camea is two processes. The Vite dev server proxies `/api` and `/openapi.json` to the
FastAPI process, so you open **one** address: `http://127.0.0.1:5173`.

## Before you start anything, check what is already up

```bash
curl -s -o /dev/null -w 'web %{http_code}\n' http://127.0.0.1:5173
curl -s -o /dev/null -w 'api %{http_code}\n' http://127.0.0.1:8000/openapi.json
cat workflow/.locks/main-checkout.json 2>/dev/null
```

**If something is listening, use it. Do not restart it.** A `/build` session or a
`/bug-hunter` run may own those servers, and the lock file says whether one holds this
checkout. Killing them costs somebody else their state.

## Start them

**Terminal 1 — the backend, headless, pointed at a folder of datasets:**

```bash
uv run camea --headless --port 8000 --open tests/fixtures
```

`tests/fixtures` holds the committed synthetic dataset (~5.6 MB), which is what makes the
app runnable on a machine with no mirror. Point `--open` somewhere else if he says so.

> ⚠️ **There is no `--data-dir` flag, and `--open` does not open anything.** It puts a path
> in `settings.recent_datasets` — *"start me near here"* — and nothing else. It opens no
> dataset and scans nothing. That is HARD RULE 3 showing through the CLI: the app carries
> no dataset knowledge. See [docs/FRONTEND.md](../../docs/FRONTEND.md).
>
> ⛔ **Never point it at `data/`.** That is the read-only 35 GB rclone mirror. Nothing
> writes there, and nothing should be casually reading a 35 GB tree to render a dev screen.

**Terminal 2 — the frontend:**

```bash
cd web && npm install && npm run dev
```

`http://127.0.0.1:5173`. Override the proxy target with
`VITE_BACKEND=http://127.0.0.1:<port>` if the backend is somewhere else.

> Vite binds `127.0.0.1` explicitly — its default `localhost` resolves to IPv6 `[::1]` on
> Windows, which would not answer the IPv4 backend.

## Ports, and who owns them

| Port | Whose |
|---|---|
| 5173 / 8000 | **his**, these. Nothing else may take them. |
| 5200, 5210, 5220 … | [/preview](preview.md), one slot per pile, backend on the next number up |

## Looking at it

Drive at the viewport the e2e suite uses (`devices['Desktop Chrome']`, per
`web/playwright.config.ts`), so what you see is what the tests see. Screenshots go to your
scratchpad or `.scratch/`, **never the repo root** — a hook will refuse a bare filename.

## Stop them

Stop what **you** started, and leave alone what you didn't. If you are not sure which is
which, say so rather than killing both.
