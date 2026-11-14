#!/usr/bin/env bash
# Backend for Playwright: isolated database + fresh GigSim + fake (deterministic) LLM.
set -euo pipefail
cd "$(dirname "$0")/.."
./scripts/dev_down.sh >/dev/null 2>&1 || true
set -a; [ -f .env ] && source .env; set +a
PGHOST_URL=${E2E_PG:-postgresql://gigbid:gigbid@localhost:5432}
psql "$PGHOST_URL/gigbid" -tc "select 1 from pg_database where datname='gigbid_e2e'" 2>/dev/null | grep -q 1 \
  || psql "$PGHOST_URL/gigbid" -c "create database gigbid_e2e" >/dev/null 2>&1 \
  || docker compose -f infra/docker-compose.yml exec -T postgres psql -U gigbid -c "create database gigbid_e2e" >/dev/null 2>&1 || true
export DATABASE_URL="$PGHOST_URL/gigbid_e2e" GIGBID_FAKE_LLM=1 MCP_TRANSPORT=http WORKER_MODE=inline
export GIGSIM_DB=.cache/gigsim_e2e.sqlite GIGSIM_SEED_DIR=data/gigsim_seed GIGSIM_GRADER=heuristic
export GIGSIM_ERROR_RATE=0 GIGSIM_POST_COMMIT_ERROR_RATE=0 LANGFUSE_DISABLED=1 GROQ_API_KEY=
export APP_SECRET_KEY=${APP_SECRET_KEY:-e2e-secret-key-that-is-long-enough-1234567890}
export TOKEN_ENCRYPTION_KEY=${TOKEN_ENCRYPTION_KEY:-$(uv run python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())")}
export MCP_BEARER_TOKEN=${MCP_BEARER_TOKEN:-e2e-mcp-token} GIGSIM_API_TOKEN=${GIGSIM_API_TOKEN:-e2e-gigsim-token}
rm -f .cache/gigsim_e2e.sqlite .cache/gigsim_e2e.sqlite-wal .cache/gigsim_e2e.sqlite-shm .cache/marketplace_idem.sqlite
mkdir -p .cache/logs
start() { local name=$1; shift; nohup "$@" > ".cache/logs/$name.log" 2>&1 & echo $! > ".cache/logs/$name.pid"; }
start gigsim uv run uvicorn gigsim.app:app --port 8081
start mcp-portfolio uv run python -m mcp_servers.portfolio.server
start mcp-marketplace uv run python -m mcp_servers.marketplace.server
start mcp-workspace uv run python -m mcp_servers.workspace.server
start api uv run uvicorn apps.api.main:app --port 8000
for p in 8081 8091 8092 8093 8000; do
  for i in $(seq 1 90); do curl -sf "localhost:$p/health" >/dev/null && break; sleep 1; done
  echo "port $p: $(curl -s -o /dev/null -w '%{http_code}' localhost:$p/health)"
done
