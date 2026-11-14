"""Graph runtime shared by the API and the worker.

* Durable: AsyncPostgresSaver checkpointer + AsyncPostgresStore (long-term memory) on Postgres.
  Approvals survive restarts: the thread is paused in the checkpoint, not in memory.
* Streaming: every node start/end and state update is published to Redis channel `run:<thread>`
  (and persisted in `run_events`), so the UI streams live progress and can replay after refresh.
* Execution trace: tool calls (agent/mcp_client.py) go to `tool_events`; Langfuse gets spans.
* `start()` runs a new thread; `resume()` delivers a human decision to an interrupted thread.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from contextlib import AsyncExitStack
from typing import Any

from langgraph.types import Command

from agent.llm import start_ledger
from agent.mcp_client import drain_calls, start_call_log
from agent.tracing import langfuse_handler, trace_metadata, trace_url

_stack: AsyncExitStack | None = None
_saver = None
_store = None
_graphs: dict[str, Any] = {}
_redis = None


def pg_url() -> str:
    url = os.getenv("DATABASE_URL", "postgresql://gigbid:gigbid@localhost:5432/gigbid")
    return url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg://", "postgresql://")


async def init(checkpointer=None, store=None) -> None:
    """Open the Postgres checkpointer/store once per process (tests may inject in-memory ones)."""
    global _stack, _saver, _store
    if _saver is not None:
        return
    if checkpointer is not None:
        _saver, _store = checkpointer, store
    else:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from langgraph.store.postgres.aio import AsyncPostgresStore

        _stack = AsyncExitStack()
        _saver = await _stack.enter_async_context(AsyncPostgresSaver.from_conn_string(pg_url()))
        _store = await _stack.enter_async_context(AsyncPostgresStore.from_conn_string(pg_url()))
        await _saver.setup()
        await _store.setup()
    _graphs.clear()


async def close() -> None:
    global _stack, _saver, _store
    if _stack:
        await _stack.aclose()
    _stack = _saver = _store = None
    _graphs.clear()


def store():
    return _store


def graph(kind: str):
    if kind not in _graphs:
        from agent.graphs.bid_graph import build_bid_graph
        from agent.graphs.conversation_graph import build_conversation_graph

        builder = build_bid_graph if kind == "bid" else build_conversation_graph
        _graphs[kind] = builder(_saver, _store)
    return _graphs[kind]


# --------------------------------------------------------------------------- event bus


async def _r():
    global _redis
    if _redis is None:
        try:
            import redis.asyncio as aioredis

            _redis = aioredis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
            await _redis.ping()
        except Exception:  # noqa: BLE001 - run without a bus (tests); events still persisted
            _redis = False
    return _redis or None


_listeners: dict[str, list[asyncio.Queue]] = {}


async def publish(thread_id: str, user_id: str, event: dict) -> None:
    event = {"thread_id": thread_id, "ts": time.time(), **event}
    for q in _listeners.get(thread_id, []):
        q.put_nowait(event)
    r = await _r()
    if r:
        await r.publish(f"run:{thread_id}", json.dumps(event, default=str))
    if _on_event:
        await _on_event(thread_id, user_id, event)


_on_event = None  # set by the API to persist run_events


def set_event_sink(fn) -> None:
    global _on_event
    _on_event = fn


def local_listener(thread_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _listeners.setdefault(thread_id, []).append(q)
    return q


# --------------------------------------------------------------------------- run / resume


def _config(thread_id: str, user_id: str, kind: str) -> dict:
    cb = langfuse_handler(trace_name=f"{kind}_graph", session_id=thread_id, user_id=user_id)
    return {"configurable": {"thread_id": thread_id}, "callbacks": [cb] if cb else [],
            "metadata": {"user_id": user_id, "kind": kind, "trace_id": thread_id,
                         **trace_metadata(f"{kind}_graph", thread_id, user_id)}, "run_name": f"{kind}_graph",
            "recursion_limit": 60}


async def _drive(kind: str, thread_id: str, user_id: str, inp: Any) -> dict:
    g = graph(kind)
    led = start_ledger()
    start_call_log()
    t0 = time.perf_counter()
    await publish(thread_id, user_id, {"type": "run_start", "kind": kind})
    final: dict = {}
    interrupted = None
    async for mode, chunk in g.astream(inp, _config(thread_id, user_id, kind), stream_mode=["updates", "custom"]):
        if mode == "custom":
            await publish(thread_id, user_id, chunk)
            continue
        for node, upd in (chunk or {}).items():
            if node == "__interrupt__":
                interrupted = upd[0].value if upd else None
                continue
            if isinstance(upd, dict):
                final.update(upd)
                await publish(thread_id, user_id, {"type": "state", "node": node,
                                                   "status": upd.get("status"), "status_reason": upd.get("status_reason"),
                                                   "keys": sorted(upd)})
    snap = await g.aget_state({"configurable": {"thread_id": thread_id}})
    values = snap.values
    calls = drain_calls()
    result = {"status": values.get("status"), "status_reason": values.get("status_reason"),
              "interrupt": interrupted, "next": list(snap.next), "values": values,
              "tokens": led.total_tokens, "cost_usd": led.total_cost, "latency_s": round(time.perf_counter() - t0, 3),
              "usage_by_node": led.by_node(), "tool_calls": [c.__dict__ for c in calls], "trace_url": trace_url(thread_id)}
    await publish(thread_id, user_id, {"type": "run_end", "status": result["status"], "awaiting_approval": bool(interrupted),
                                       "tokens": result["tokens"], "latency_s": result["latency_s"]})
    return result


async def start_bid(job: dict, *, user_id: str, persona: str, settings: dict | None = None, strategy: str | None = None,
                    thread_id: str | None = None) -> dict:
    from agent.graphs.bid_graph import initial_state

    thread_id = thread_id or f"bid-{user_id[:8]}-{job['id']}-{uuid.uuid4().hex[:6]}"
    st = initial_state(job, user_id=user_id, persona=persona, thread_id=thread_id, strategy=strategy, settings=settings)
    res = await _drive("bid", thread_id, user_id, st)
    res["thread_id"] = thread_id
    return res


async def start_conversation(conversation_id: str, *, user_id: str, persona: str, thread_id: str | None = None) -> dict:
    thread_id = thread_id or f"conv-{user_id[:8]}-{conversation_id}-{uuid.uuid4().hex[:6]}"
    st = {"thread_id": thread_id, "user_id": user_id, "persona": persona, "conversation_id": conversation_id,
          "trace_id": thread_id, "status": "new"}
    res = await _drive("conversation", thread_id, user_id, st)
    res["thread_id"] = thread_id
    return res


async def resume(kind: str, thread_id: str, user_id: str, decision: dict) -> dict:
    res = await _drive(kind, thread_id, user_id, Command(resume={**decision, "user_id": user_id}))
    res["thread_id"] = thread_id
    return res


async def pending(kind: str, thread_id: str) -> dict | None:
    """The interrupt payload waiting for this thread (survives refresh/restart)."""
    snap = await graph(kind).aget_state({"configurable": {"thread_id": thread_id}})
    for t in snap.tasks:
        if t.interrupts:
            return t.interrupts[0].value
    return None


async def state(kind: str, thread_id: str) -> dict:
    snap = await graph(kind).aget_state({"configurable": {"thread_id": thread_id}})
    return {"values": snap.values, "next": list(snap.next), "created_at": snap.created_at}


async def history(kind: str, thread_id: str, limit: int = 50) -> list[dict]:
    """Checkpoint history: every super-step, for replaying a job from any node."""
    out = []
    async for s in graph(kind).aget_state_history({"configurable": {"thread_id": thread_id}}, limit=limit):
        out.append({"checkpoint_id": s.config["configurable"].get("checkpoint_id"), "next": list(s.next),
                    "status": s.values.get("status"), "step": s.metadata.get("step") if s.metadata else None,
                    "writes": sorted((s.metadata or {}).get("writes") or {}) if s.metadata else []})
    return out


async def replay(kind: str, thread_id: str, checkpoint_id: str, user_id: str) -> dict:
    """Re-run a thread from a past checkpoint (forks a new branch of the same thread)."""
    g = graph(kind)
    cfg = {"configurable": {"thread_id": thread_id, "checkpoint_id": checkpoint_id}}
    out = await g.ainvoke(None, {**_config(thread_id, user_id, kind), **cfg})
    return {"status": out.get("status"), "status_reason": out.get("status_reason")}
