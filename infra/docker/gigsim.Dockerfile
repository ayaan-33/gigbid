# GigSim marketplace simulator
FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    FASTEMBED_CACHE_PATH=/models/fastembed HF_HOME=/models/hf
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.13.5
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
RUN uv sync --frozen --no-dev && useradd -m -u 10001 app && mkdir -p /app/.cache /models && chown -R app /app/.cache /models
ENV PATH="/app/.venv/bin:$PATH"
USER app
CMD ["uvicorn", "gigsim.app:app", "--host", "0.0.0.0", "--port", "8081"]
