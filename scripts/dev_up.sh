#!/usr/bin/env bash
# Start GigSim + 3 MCP servers + API locally (outside Docker) for development.
# Postgres/Redis come from: docker compose -f infra/docker-compose.yml up -d postgres redis
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
export MCP_TRANSPORT=http WORKER_MODE=${WORKER_MODE:-inline} GIGSIM_SEED_DIR=${GIGSIM_SEED_DIR:-data/gigsim_seed}
mkdir -p .cache/logs
start() { local name=$1; shift; nohup "$@" > ".cache/logs/$name.log" 2>&1 & echo $! > ".cache/logs/$name.pid"; echo "started $name ($!)"; }
start gigsim uv run uvicorn gigsim.app:app --port 8081
start mcp-portfolio uv run python -m mcp_servers.portfolio.server
start mcp-marketplace uv run python -m mcp_servers.marketplace.server
start mcp-workspace uv run python -m mcp_servers.workspace.server
start api uv run uvicorn apps.api.main:app --port 8000
for p in 8081 8091 8092 8093 8000; do
  for i in $(seq 1 60); do curl -sf "localhost:$p/health" >/dev/null && break; sleep 1; done
  echo "port $p: $(curl -s -o /dev/null -w '%{http_code}' localhost:$p/health)"
done
