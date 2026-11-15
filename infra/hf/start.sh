#!/usr/bin/env bash
# Start every GigBid service inside one container (Hugging Face Space). Storage is ephemeral:
# on restart the database is re-created and the reviewer account is re-seeded from secrets.
set -uo pipefail
cd /app
PG=/tmp/pgdata; mkdir -p /app/.cache/logs
if [ ! -s "$PG/PG_VERSION" ]; then
  initdb -D "$PG" -U gigbid --auth=trust >/dev/null
fi
pg_ctl -D "$PG" -o "-k /tmp -c listen_addresses=127.0.0.1" -l /app/.cache/logs/postgres.log start
for i in $(seq 1 30); do pg_isready -h 127.0.0.1 -U gigbid >/dev/null && break; sleep 1; done
psql -h 127.0.0.1 -U gigbid -d postgres -tc "select 1 from pg_database where datname='gigbid'" | grep -q 1 \
  || createdb -h 127.0.0.1 -U gigbid gigbid
redis-server --daemonize yes --bind 127.0.0.1 --save "" --logfile /app/.cache/logs/redis.log

export DATABASE_URL=postgresql://gigbid:gigbid@127.0.0.1:5432/gigbid REDIS_URL=redis://127.0.0.1:6379/0
export GIGSIM_BASE_URL=http://127.0.0.1:8081 PORTFOLIO_MCP_URL=http://127.0.0.1:8091/mcp
export MARKETPLACE_MCP_URL=http://127.0.0.1:8092/mcp WORKSPACE_MCP_URL=http://127.0.0.1:8093/mcp
export MCP_TRANSPORT=http WORKER_MODE=${WORKER_MODE:-arq} APP_ENV=${APP_ENV:-production}
export MODEL_PROFILE=${MODEL_PROFILE:-open} MARKETPLACE_MODE=${MARKETPLACE_MODE:-gigsim}
export GIGSIM_DB=/app/.cache/gigsim.sqlite GIGSIM_SEED_DIR=/app/data/gigsim_seed GIGSIM_GRADER=${GIGSIM_GRADER:-llm}
if [ -n "${SPACE_HOST:-}" ]; then
  export PUBLIC_WEB_URL=${PUBLIC_WEB_URL:-https://$SPACE_HOST} PUBLIC_API_URL=${PUBLIC_API_URL:-https://$SPACE_HOST}
  export UPWORK_OAUTH_REDIRECT_URI=${UPWORK_OAUTH_REDIRECT_URI:-https://$SPACE_HOST/api/auth/upwork/callback}
fi

start() { local name=$1; shift; nohup "$@" > "/app/.cache/logs/$name.log" 2>&1 & }
start gigsim uvicorn gigsim.app:app --host 127.0.0.1 --port 8081
start mcp-portfolio python -m mcp_servers.portfolio.server
start mcp-marketplace python -m mcp_servers.marketplace.server
start mcp-workspace python -m mcp_servers.workspace.server
for p in 8081 8091 8092 8093; do for i in $(seq 1 180); do curl -sf "127.0.0.1:$p/health" >/dev/null && break; sleep 1; done; done
start api uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips='*'
for i in $(seq 1 180); do curl -sf 127.0.0.1:8000/health >/dev/null && break; sleep 1; done
# Warm the portfolio index before any agent runs, so the first Fit Matcher calls don't time out.
python - <<'PY' || true
import asyncio
from agent.mcp_client import ToolBox
async def warm():
    for _ in range(20):
        try:
            await ToolBox("fit_matcher").call("search_evidence", {"requirement": "python", "k": 1}); print("portfolio index warm"); return
        except Exception as e:  # noqa: BLE001
            print("warming portfolio index...", type(e).__name__); await asyncio.sleep(10)
asyncio.run(warm())
PY
[ "$WORKER_MODE" = "arq" ] && start worker arq worker.main.WorkerSettings
echo "GigBid services up:"; for p in 8081 8091 8092 8093 8000; do echo "  $p $(curl -s -o /dev/null -w '%{http_code}' 127.0.0.1:$p/health)"; done
# Stream service logs to the Space's log view, then run the web app in the foreground on 7860.
tail -n +1 -F /app/.cache/logs/api.log /app/.cache/logs/worker.log 2>/dev/null &
cd /app/web && PORT=7860 HOSTNAME=0.0.0.0 NODE_ENV=production exec node server.js
