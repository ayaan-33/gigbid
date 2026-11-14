"""Agent run viewer: live node-by-node progress over SSE, history, checkpoints, trace links."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import and_, desc, select
from sse_starlette.sse import EventSourceResponse

from agent import runtime
from agent.tracing import trace_url
from apps.api import db
from apps.api.auth.security import CurrentUser
from apps.api.schemas import ThreadOut

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.get("", response_model=list[ThreadOut])
async def list_runs(uid: str = CurrentUser, limit: int = Query(50, le=200), status: str | None = None) -> list[ThreadOut]:
    s = select(db.threads).where(db.threads.c.user_id == uid)
    if status:
        s = s.where(db.threads.c.status == status)
    async with db.engine().connect() as c:
        rows = (await c.execute(s.order_by(desc(db.threads.c.updated_at)).limit(limit))).mappings().all()
    return [ThreadOut(**{k: r[k] for k in ThreadOut.model_fields if k in r}, trace_url=trace_url(r["thread_id"])) for r in rows]


async def _own(uid: str, thread_id: str):
    async with db.engine().connect() as c:
        t = (await c.execute(select(db.threads).where(and_(db.threads.c.thread_id == thread_id,
                                                           db.threads.c.user_id == uid)))).mappings().first()
    if not t:
        raise HTTPException(404, "run not found")
    return t


@router.get("/{thread_id}")
async def run_detail(thread_id: str, uid: str = CurrentUser) -> dict:
    t = await _own(uid, thread_id)
    async with db.engine().connect() as c:
        ev = (await c.execute(select(db.run_events.c.event, db.run_events.c.at).where(
            db.run_events.c.thread_id == thread_id).order_by(db.run_events.c.id))).all()
        tools = (await c.execute(select(db.tool_events).where(db.tool_events.c.thread_id == thread_id)
                                 .order_by(db.tool_events.c.id))).mappings().all()
    st = await runtime.state(t["kind"], thread_id)
    v = st["values"]
    return {"thread": {k: t[k] for k in t.keys()}, "events": [e for e, _ in ev],
            "tool_events": [dict(x) for x in tools], "next": st["next"],
            "usage": v.get("usage", {}), "timings": v.get("timings", {}), "status": v.get("status"),
            "status_reason": v.get("status_reason"), "errors": v.get("errors", []), "trace_url": trace_url(thread_id)}


@router.get("/{thread_id}/stream")
async def stream(thread_id: str, request: Request, uid: str = CurrentUser) -> EventSourceResponse:
    """Server-Sent Events: replays persisted events first (refresh-safe), then streams live ones."""
    await _own(uid, thread_id)

    async def gen():
        async with db.engine().connect() as c:
            past = (await c.execute(select(db.run_events.c.id, db.run_events.c.event).where(
                db.run_events.c.thread_id == thread_id).order_by(db.run_events.c.id))).all()
        last_id = 0
        for i, e in past:
            last_id = i
            yield {"event": "node", "id": str(i), "data": json.dumps(e, default=str)}
        r = await runtime._r()
        if r:
            ps = r.pubsub()
            await ps.subscribe(f"run:{thread_id}")
            try:
                while not await request.is_disconnected():
                    m = await ps.get_message(ignore_subscribe_messages=True, timeout=15)
                    if m and m["type"] == "message":
                        yield {"event": "node", "data": m["data"]}
                    else:
                        yield {"event": "ping", "data": "{}"}
            finally:
                await ps.unsubscribe()
        else:  # no Redis: poll the persisted events
            while not await request.is_disconnected():
                await asyncio.sleep(1.0)
                async with db.engine().connect() as c:
                    new = (await c.execute(select(db.run_events.c.id, db.run_events.c.event).where(and_(
                        db.run_events.c.thread_id == thread_id, db.run_events.c.id > last_id)).order_by(db.run_events.c.id))).all()
                for i, e in new:
                    last_id = i
                    yield {"event": "node", "id": str(i), "data": json.dumps(e, default=str)}

    return EventSourceResponse(gen(), headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


@router.get("/{thread_id}/history")
async def checkpoints(thread_id: str, uid: str = CurrentUser) -> list[dict]:
    t = await _own(uid, thread_id)
    return await runtime.history(t["kind"], thread_id)


@router.post("/{thread_id}/replay/{checkpoint_id}")
async def replay(thread_id: str, checkpoint_id: str, uid: str = CurrentUser) -> dict:
    """Replay a job from any node using checkpoint history (C6)."""
    t = await _own(uid, thread_id)
    return await runtime.replay(t["kind"], thread_id, checkpoint_id, uid)
