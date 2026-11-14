"""Shared plumbing for GigBid's own MCP servers.

* Bearer-token auth on the Streamable HTTP endpoint (constant-time compare).
* Caller identity + trace id from headers (`X-GigBid-User`, `X-GigBid-Persona`, `X-Trace-Id`),
  so per-user limits and the audit log work; in-memory test sessions fall back to defaults.
* An append-only, hash-chained audit log (tamper evident) with PII masking.
* A per-user token-bucket rate limiter.
"""

from __future__ import annotations

import contextvars
import hashlib
import hmac
import json
import os
import threading
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from agent.guardrails import mask_obj

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- auth


class BearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, token: str | None, open_paths: tuple[str, ...] = ("/health",)):
        super().__init__(app)
        self.token = token or ""
        self.open_paths = open_paths

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.open_paths:
            return await call_next(request)
        if not self.token:
            return JSONResponse({"error": "server misconfigured: MCP_BEARER_TOKEN unset"}, status_code=500)
        got = request.headers.get("authorization", "")
        if not got.startswith("Bearer ") or not hmac.compare_digest(got[7:].strip(), self.token):
            return JSONResponse({"error": "unauthorized"}, status_code=401,
                                headers={"WWW-Authenticate": 'Bearer realm="gigbid-mcp"'})
        return await call_next(request)


# In-process transport (tests, evals): the toolbox sets the caller here instead of HTTP headers.
CURRENT_CALLER: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar("mcp_caller", default=None)


def caller(ctx: Any | None) -> dict[str, str]:
    """User/persona/trace from the HTTP request behind an MCP call (defaults for stdio/in-memory)."""
    headers: dict[str, str] = {}
    try:
        req = ctx.request_context.request if ctx is not None else None
        if req is not None:
            headers = {k.lower(): v for k, v in req.headers.items()}
    except Exception:  # noqa: BLE001 - no request context (stdio / in-memory)
        headers = {}
    cv = CURRENT_CALLER.get()
    if not headers and cv:
        return {"user": cv.get("user", "local"), "persona": cv.get("persona", "ai_ml_engineer"),
                "trace_id": cv.get("trace_id") or uuid.uuid4().hex, "marketplace_token": ""}
    return {
        "user": headers.get("x-gigbid-user", os.getenv("MCP_DEFAULT_USER", "local")),
        "persona": headers.get("x-gigbid-persona", os.getenv("PORTFOLIO_PERSONA", "ai_ml_engineer")),
        "trace_id": headers.get("x-trace-id", "") or uuid.uuid4().hex,
        "marketplace_token": headers.get("x-marketplace-token", ""),
    }


# --------------------------------------------------------------------------- audit log


class AuditLog:
    """Append-only JSONL; each record carries the hash of the previous one."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self._last = self._tail_hash()

    def _tail_hash(self) -> str:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return "genesis"
        with open(self.path, "rb") as fh:
            fh.seek(max(0, self.path.stat().st_size - 8192))
            last = fh.read().splitlines()[-1]
        return json.loads(last)["hash"]

    def write(self, *, user: str, tool: str, arguments: dict, result: Any, trace_id: str,
              status: str = "ok", server: str = "") -> dict:
        with self.lock:
            rec = {"ts": time.time(), "server": server, "user": user, "tool": tool,
                   "arguments": mask_obj(arguments), "result": mask_obj(result), "status": status,
                   "trace_id": trace_id, "prev": self._last}
            rec["hash"] = hashlib.sha256(json.dumps(rec, sort_keys=True, default=str).encode()).hexdigest()
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, default=str) + "\n")
            self._last = rec["hash"]
            return rec

    def read(self, limit: int = 200, user: str | None = None) -> list[dict]:
        if not self.path.exists():
            return []
        rows = [json.loads(x) for x in self.path.read_text().splitlines() if x.strip()]
        if user:
            rows = [r for r in rows if r["user"] == user]
        return rows[-limit:]

    def verify(self) -> bool:
        prev = "genesis"
        for line in self.path.read_text().splitlines() if self.path.exists() else []:
            rec = json.loads(line)
            h = rec.pop("hash")
            if rec["prev"] != prev or hashlib.sha256(json.dumps(rec, sort_keys=True, default=str).encode()).hexdigest() != h:
                return False
            prev = h
        return True


# --------------------------------------------------------------------------- rate limiting


class RateLimiter:
    """Token bucket per key. `acquire` waits (politely) instead of failing, up to max_wait."""

    def __init__(self, per_minute: int):
        self.rate = per_minute / 60.0
        self.capacity = max(1, per_minute // 4)
        self.state: dict[str, tuple[float, float]] = defaultdict(lambda: (float(self.capacity), time.monotonic()))
        self.lock = threading.Lock()

    def _take(self, key: str) -> float:
        with self.lock:
            tokens, last = self.state[key]
            now = time.monotonic()
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            if tokens >= 1:
                self.state[key] = (tokens - 1, now)
                return 0.0
            self.state[key] = (tokens, now)
            return (1 - tokens) / self.rate

    async def acquire(self, key: str, max_wait: float = 30.0) -> None:
        import asyncio

        waited = 0.0
        while (delay := self._take(key)) > 0:
            if waited + delay > max_wait:
                raise RuntimeError("rate limit: try again later")
            await asyncio.sleep(delay)
            waited += delay


def serve(mcp, port: int, token_env: str = "MCP_BEARER_TOKEN") -> None:
    """Run a FastMCP server over Streamable HTTP behind bearer auth (+ /health)."""
    import uvicorn
    from starlette.routing import Route

    app = mcp.streamable_http_app()

    async def health(_req):
        return JSONResponse({"status": "ok", "server": mcp.name})

    app.router.routes.append(Route("/health", health))
    app.add_middleware(BearerAuthMiddleware, token=os.getenv(token_env))
    uvicorn.run(app, host=os.getenv("MCP_HOST", "0.0.0.0"), port=port, log_level="info")
