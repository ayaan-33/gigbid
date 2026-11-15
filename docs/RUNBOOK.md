# Runbook

## Start / stop

| What | Command |
|---|---|
| Everything in Docker (local) | `docker compose -f infra/docker-compose.yml up --build` (add `--profile local` for Ollama) |
| Dev without Docker (Postgres/Redis in Docker) | `docker compose -f infra/docker-compose.yml up -d postgres redis` then `./scripts/dev_up.sh` · stop with `./scripts/dev_down.sh` |
| Web dev server | `npm --prefix apps/web run dev` → http://localhost:3000 |
| E2E backend (fake LLM, isolated DB) | `./scripts/e2e_stack.sh` then `cd apps/web && npx playwright test` |
| Worker | `arq worker.main.WorkerSettings` (compose service `worker`) |
| Evals | `make eval` (full) · `uv run python -m evals.runners.smoke` (CI smoke) |

## Services and ports

| Service | Port | Health |
|---|---|---|
| web (Next.js) | 3000 | `/login` |
| api (FastAPI) | 8000 | `/health` |
| mcp-portfolio | 8091 | `/health` (MCP at `/mcp`, Bearer) |
| mcp-marketplace | 8092 | `/health` |
| mcp-workspace | 8093 | `/health` |
| gigsim | 8081 | `/health` |
| postgres (pgvector) | 5432 | `pg_isready` |
| redis | 6379 | `redis-cli ping` |

## Scheduling (E1)

The worker's `tick` cron runs **every 5 minutes**. For each enabled saved search, it enqueues a
scout once that search's own interval has passed:
- **default:** every 30 minutes (configurable per search, minimum 15 minutes);
- **pipeline sync:** every tick, for each user.

### Live Upwork polling interval: why 4 hours

`marketplace.live_poll_interval_minutes: 240`. The worker never polls the real platform more than
once every 4 hours per saved search. It also clamps any shorter interval a user sets.

1. **It is not scraping.** We read through the official MCP server only, at a cadence a human
   would plausibly use: checking a job feed a few times a day.
2. **4 hours is still competitive.** Most jobs keep accepting proposals for days. Scouting 6 times
   a day still finds them early, and the user can always press "Scout now", which counts as one
   read.
3. **It respects the platform's limits.** Each tick is at most one `search_jobs` call per saved
   search, plus `get_job` for new results. With 3 searches that's about 18 searches and a few
   dozen reads per day, far below any reasonable rate limit.
4. **There are no write side effects.** Writes are only drafts that the user creates after
   approval and then confirms on Upwork.

For GigSim, a 30-minute default is used, because the simulator's clock runs 60× faster
(`GIGSIM_SPEED`).

### Idempotency
- Arq job ids are deterministic (`run_bid:<user>:<job>`, `scout:<search>:<5-min bucket>`). A
  duplicate enqueue does nothing.
- `run_bid` skips jobs that are already analysed unless forced from the UI.
- Every marketplace write carries an idempotency key derived from the thread, the draft version and
  a hash of the text. It is enforced by the MCP server's store and by GigSim. A restart that
  replays a submit is answered with the original result, and no Connects are spent twice.

## Degraded mode (marketplace down)
- **When the circuit opens:** the GigSim adapter's circuit breaker opens after 4 consecutive
  failures and cools down for 20 s. Tools then return `MARKETPLACE_UNAVAILABLE`, and graph threads
  move to `queued_degraded`.
- **What the user sees:** the UI shows the banner "Marketplace unavailable: work is queued…"
  (driven by `/api/status`).
- **Recovery:** on each tick, the worker checks `marketplace_status` and, once it's healthy,
  re-queues the parked threads.
- **Viva demo:** run `docker compose stop mcp-marketplace` (or `gigsim`). Watch the banner appear,
  trigger "Scout now", then `docker compose start mcp-marketplace`. The banner clears and the
  queued work resumes.

## Crash and resume (C6)
- An approval waits in the Postgres checkpoint, not in memory.
- **Demo:** start a job until it waits for approval. Then
  `docker compose restart api worker`. Refresh the studio, click **Approve**, and confirm in the
  run viewer and in GigSim that exactly one proposal was submitted.
- **Replay:** the run viewer's Checkpoints panel can replay any super-step
  (`POST /api/runs/{thread}/replay/{checkpoint}`).

## Rate limits (free tiers)
- **Groq free tier:** about 8k tokens per minute and about 200k tokens per day per model. The
  client paces itself (`models.profiles.open.tokens_per_minute`). A provider 429 with a
  `try again in Xs` hint is honoured, within `rate_limit_wait_budget_s`. On the final attempt a
  node falls back to `fallback_small` or `fallback_large`.
- **GigSim:** 30 requests per minute per token. The marketplace MCP server limits itself to 20 per
  minute per user.

## Secrets
- Secrets come from environment variables only (`.env` locally, the VM's `.env` in production).
  `.env.example` lists every variable. CI fails if a `.env` file is ever committed, and gitleaks
  scans every push.
- OAuth tokens are Fernet-encrypted per user (`TOKEN_ENCRYPTION_KEY`) and never logged.
- Logs and traces are PII-masked: emails, phone numbers, card and IBAN numbers, crypto wallets
  and messaging handles.

## Change request: platform policy update
1. `POST /admin/policy {"version": 2}` on GigSim, using the admin token.
2. Mirror the change in `agent/config.yaml → policy`. The Connects surcharge and the AI disclosure
   are both config-driven.
3. Check that the writer and Compliance Guard pick it up. See `docs/CHANGE_REQUEST.md` for the
   timed walkthrough.

## Logs
- **Dev:** `.cache/logs/<service>.log`.
- **Docker:** `docker compose logs -f <service>`.
- **Audit logs:** `.cache/audit/*.jsonl`, hash-chained. Verify them with
  `python -c "from mcp_servers.common import AuditLog; ..."`.
