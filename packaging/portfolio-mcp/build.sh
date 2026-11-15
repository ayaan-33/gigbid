#!/usr/bin/env bash
# Assemble a minimal source tree from the monorepo and build the wheel + sdist into dist/.
set -euo pipefail
cd "$(dirname "$0")"
rm -rf src dist && mkdir -p src/mcp_servers src/agent src/scripts/data src/rag
R=../..
cp $R/mcp_servers/__init__.py $R/mcp_servers/common.py src/mcp_servers/
cp -r $R/mcp_servers/portfolio src/mcp_servers/ && rm -rf src/mcp_servers/portfolio/tests
cp $R/agent/__init__.py $R/agent/settings.py $R/agent/guardrails.py $R/agent/config.yaml src/agent/
mkdir -p src/agent/prompts && cp $R/agent/prompts/__init__.py $R/agent/prompts/query_rewrite.md src/agent/prompts/
cp -r $R/rag/__init__.py $R/rag/retriever.py $R/rag/ingest $R/rag/index $R/rag/variants src/rag/
cp $R/scripts/__init__.py src/scripts/ && cp $R/scripts/data/__init__.py $R/scripts/data/taxonomy.py src/scripts/data/
find src -name "__pycache__" -prune -exec rm -rf {} +
uv build --out-dir dist
