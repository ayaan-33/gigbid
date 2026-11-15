# GigBid as ONE Hugging Face Docker Space (free CPU tier, no card).
# Runs Postgres, Redis, GigSim, the 3 MCP servers, the API, the Arq worker and the Next.js web app
# in a single container; only the web app's port (7860) is public and it proxies /api to the API.
FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY apps/web/ ./
ENV NEXT_TELEMETRY_DISABLED=1 API_INTERNAL_URL=http://127.0.0.1:8000
RUN npm run build

FROM python:3.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    HOME=/home/user FASTEMBED_CACHE_PATH=/home/user/models/fastembed HF_HOME=/home/user/models/hf
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates postgresql redis-server \
    && rm -rf /var/lib/apt/lists/*
COPY --from=web /usr/local/bin/node /usr/local/bin/node
RUN pip install --no-cache-dir uv==0.13.5 && useradd -m -u 1000 user
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY agent ./agent
COPY apps/__init__.py ./apps/__init__.py
COPY apps/api ./apps/api
COPY rag ./rag
COPY mcp_servers ./mcp_servers
COPY worker ./worker
COPY gigsim ./gigsim
COPY scripts ./scripts
COPY evals ./evals
COPY data/personas ./data/personas
COPY data/derived ./data/derived
COPY data/policy_pack ./data/policy_pack
COPY data/gigsim_seed ./data/gigsim_seed
RUN uv sync --frozen --no-dev
COPY --from=web /web/.next/standalone /app/web
COPY --from=web /web/.next/static /app/web/.next/static
COPY --from=web /web/public /app/web/public
COPY infra/hf/start.sh /app/start.sh
RUN chmod +x /app/start.sh && mkdir -p /app/.cache /home/user/models && chown -R user /app /home/user
ENV PATH="/app/.venv/bin:/usr/lib/postgresql/15/bin:$PATH"
USER user
EXPOSE 7860
CMD ["/app/start.sh"]
