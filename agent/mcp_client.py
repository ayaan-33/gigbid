"""MCP client layer (A6): MultiServerMCPClient setup + per-agent tool allowlists.

Agents never call GigSim, Upwork, a database or a file directly; every capability is an MCP tool
reached through `ToolBox(agent)`:

* allowlist   - an agent can only call tools listed for it in `mcp.allowlists` (config.yaml)
* timeouts    - every call bounded by `mcp.timeout_s`
* retries     - bounded exponential backoff + jitter (writes are safe: idempotency keys)
* degraded    - MARKETPLACE_UNAVAILABLE / connection failures raise `Degraded`; the graph moves the
                thread to a queued state and the UI shows a "marketplace unavailable" banner
* transport   - "http": MultiServerMCPClient over Streamable HTTP with bearer + caller headers
                "inprocess": in-memory MCP sessions against the same FastMCP servers (tests/evals)
"""

from __future__ import annotations

import asyncio
import contextvars as _cv
import json
import os
import random
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from agent.settings import cfg

SERVER_MODULES = {
    "portfolio": "mcp_servers.portfolio.server",
    "marketplace": "mcp_servers.marketplace.server",
    "workspace": "mcp_servers.workspace.server",
}


class ToolNotAllowed(PermissionError):
    pass


class Degraded(RuntimeError):
    """A required MCP server (usually the marketplace) is unavailable; queue and retry later."""

    def __init__(self, server: str, message: str):
        super().__init__(f"{server} unavailable: {message}")
        self.server = server


class ToolError(RuntimeError):
    pass


@dataclass
class CallRecord:
    agent: str
    server: str
    tool: str
    args: dict[str, Any]
    ok: bool
    latency_s: float
    error: str | None = None
    result_preview: str = ""


@dataclass
class Caller:
    user: str = "local"
    persona: str = "ai_ml_engineer"
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    marketplace_mode: str | None = None


# Execution trace (kept apart from graph state and long-term memory): every tool call made in
# the current run. Per-run (context variable), so concurrent graph runs never mix their traces.
_calls_var: _cv.ContextVar[list[CallRecord] | None] = _cv.ContextVar("mcp_calls", default=None)
_global_calls: list[CallRecord] = []  # fallback outside a run (tests, scripts)


def start_call_log() -> list[CallRecord]:
    log: list[CallRecord] = []
    _calls_var.set(log)
    return log


def _calls() -> list[CallRecord]:
    log = _calls_var.get()
    return log if log is not None else _global_calls


def drain_calls() -> list[CallRecord]:
    log = _calls()
    out = list(log)
    log.clear()
    return out


def allowlist(agent: str) -> dict[str, list[str]]:
    al = cfg(f"mcp.allowlists.{agent}")
    if al is None:
        raise ToolNotAllowed(f"agent {agent!r} has no tool allowlist")
    return al or {}


def _server_for(agent: str, tool: str) -> str:
    for server, tools in allowlist(agent).items():
        if tool in tools:
            return server
    raise ToolNotAllowed(f"agent {agent!r} may not call {tool!r}")


def _transport() -> str:
    return os.getenv("MCP_TRANSPORT") or cfg("mcp.transport", "http")


@asynccontextmanager
async def _inprocess_session(server: str):
    import importlib

    from mcp.shared.memory import create_connected_server_and_client_session

    mod = importlib.import_module(SERVER_MODULES[server])
    async with create_connected_server_and_client_session(mod.mcp._mcp_server) as s:
        yield s


def _headers(c: Caller) -> dict[str, str]:
    h = {"Authorization": f"Bearer {os.getenv('MCP_BEARER_TOKEN', '')}", "X-GigBid-User": c.user,
         "X-GigBid-Persona": c.persona, "X-Trace-Id": c.trace_id}
    if c.marketplace_mode:
        h["X-Marketplace-Mode"] = c.marketplace_mode
    return h


def multi_server_client(caller: Caller, servers: list[str] | None = None):
    """The MultiServerMCPClient used in http mode (and by the single-agent / supervisor baselines)."""
    from langchain_mcp_adapters.client import MultiServerMCPClient

    conns = {name: {"transport": "streamable_http", "url": cfg(f"mcp.servers.{name}"), "headers": _headers(caller),
                    "timeout": cfg("mcp.timeout_s", 30)}
             for name in (servers or list(SERVER_MODULES))}
    return MultiServerMCPClient(conns)


class ToolBox:
    def __init__(self, agent: str, caller: Caller | None = None):
        self.agent = agent
        self.caller = caller or Caller()
        self.timeout = cfg("mcp.timeout_s", 30)
        self.retries = cfg("mcp.max_retries", 2)

    def tools(self) -> list[str]:
        return sorted(t for ts in allowlist(self.agent).values() for t in ts)

    async def call(self, tool: str, args: dict[str, Any] | None = None) -> Any:
        server = _server_for(self.agent, tool)
        args = args or {}
        last = ""
        t0 = time.perf_counter()
        for attempt in range(self.retries + 1):
            try:
                result = await asyncio.wait_for(self._call_once(server, tool, args), self.timeout)
                _calls().append(CallRecord(self.agent, server, tool, args, True, round(time.perf_counter() - t0, 3),
                                         result_preview=json.dumps(result, default=str)[:300]))
                return result
            except ToolError as e:
                msg = str(e)
                if "MARKETPLACE_UNAVAILABLE" in msg:
                    last = msg
                    break  # adapter already retried with backoff; don't hammer it
                _calls().append(CallRecord(self.agent, server, tool, args, False, round(time.perf_counter() - t0, 3), msg[:300]))
                raise
            except (TimeoutError, ConnectionError, OSError) as e:
                last = f"{type(e).__name__}: {e}"
            except Exception as e:  # noqa: BLE001 - httpx / anyio transport failures
                if "connect" in type(e).__name__.lower() or "ExceptionGroup" in type(e).__name__:
                    last = f"{type(e).__name__}: {e}"
                else:
                    raise
            await asyncio.sleep(min(8, 0.5 * 2**attempt) * (0.5 + random.random() / 2))
        _calls().append(CallRecord(self.agent, server, tool, args, False, round(time.perf_counter() - t0, 3), last[:300]))
        raise Degraded(server, last)

    async def _call_once(self, server: str, tool: str, args: dict[str, Any]) -> Any:
        if _transport() == "inprocess":
            from mcp_servers.common import CURRENT_CALLER

            token = CURRENT_CALLER.set({"user": self.caller.user, "persona": self.caller.persona,
                                        "trace_id": self.caller.trace_id})
            try:
                async with _inprocess_session(server) as s:
                    r = await s.call_tool(tool, args)
            finally:
                CURRENT_CALLER.reset(token)
        else:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client

            async with streamablehttp_client(cfg(f"mcp.servers.{server}"), headers=_headers(self.caller),
                                             timeout=self.timeout) as (read, write, _):
                async with ClientSession(read, write) as s:
                    await s.initialize()
                    r = await s.call_tool(tool, args)
        if r.isError:
            text = " ".join(getattr(c, "text", "") for c in r.content)
            raise ToolError(text or f"{tool} failed")
        if r.structuredContent is not None:
            sc = r.structuredContent
            return sc["result"] if set(sc) == {"result"} else sc
        texts = [getattr(c, "text", "") for c in r.content]
        try:
            return json.loads(texts[0]) if texts else None
        except json.JSONDecodeError:
            return texts[0]


async def langchain_tools(agent: str | None, caller: Caller, servers: list[str] | None = None):
    """LangChain tools filtered by the agent's allowlist (None = every tool, for the baselines)."""
    client = multi_server_client(caller, servers)
    tools = await client.get_tools()
    if agent is None:
        return tools
    allowed = {t for ts in allowlist(agent).values() for t in ts}
    return [t for t in tools if t.name in allowed]
