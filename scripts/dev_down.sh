#!/usr/bin/env bash
cd "$(dirname "$0")/.."
for f in .cache/logs/*.pid; do [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null; rm -f "$f"; done
pkill -f "gigsim.app:app|mcp_servers.(portfolio|marketplace|workspace).server|apps.api.main:app" 2>/dev/null || true
echo stopped
