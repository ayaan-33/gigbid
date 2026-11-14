"""Business services shared by the API and the worker (no HTTP here)."""

from __future__ import annotations

import asyncio
import os
import random
import time
import uuid
from typing import Any

from sqlalchemy import and_, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from agent import runtime
from agent.guardrails import mask_obj
from agent.mcp_client import Caller, Degraded, ToolBox
from apps.api import db

# --------------------------------------------------------------------------- persistence


async def persist_event(thread_id: str, user_id: str, event: dict) -> None:
    async with db.engine().begin() as c:
        await c.execute(insert(db.run_events).values(thread_id=thread_id, user_id=user_id, event=mask_obj(event)))


runtime.set_event_sink(persist_event)


async def user_settings(user_id: str) -> dict:
    async with db.engine().connect() as c:
        row = (await c.execute(select(db.user_settings).where(db.user_settings.c.user_id == user_id))).mappings().first()
        u = (await c.execute(select(db.users).where(db.users.c.id == user_id))).mappings().first()
        week_ago = time.time() - 7 * 86400
        spent = (await c.execute(select(func.coalesce(func.sum(db.pipeline.c.connects_spent), 0)).where(
            and_(db.pipeline.c.user_id == user_id, db.pipeline.c.updated_at >= func.to_timestamp(week_ago))))).scalar()
    s = dict(row or {})
    s["persona"] = (u or {}).get("persona", "ai_ml_engineer")
    s["connects_spent_this_week"] = int(spent or 0)
    return s


def pick_strategy(settings: dict, job_id: str) -> str:
    mode = settings.get("strategy_mode") or "ab_test"
    if mode != "ab_test":
        return mode
    # extension X2: deterministic randomisation per job (reproducible assignment)
    return "evidence_first" if random.Random(job_id).random() < 0.5 else "question_led"


async def record_result(user_id: str, kind: str, res: dict, job_id: str | None = None,
                        conversation_id: str | None = None) -> None:
    v = res.get("values") or {}
    status = res.get("status") or ("awaiting_approval" if res.get("interrupt") else v.get("status"))
    if res.get("interrupt"):
        status = "awaiting_approval"
    async with db.engine().begin() as c:
        stmt = pg_insert(db.threads).values(
            thread_id=res["thread_id"], user_id=user_id, kind=kind, job_id=job_id, conversation_id=conversation_id,
            status=status, status_reason=res.get("status_reason") or "", strategy=v.get("strategy"),
            trace_id=res["thread_id"], tokens=res.get("tokens", 0), cost_usd=res.get("cost_usd", 0.0),
            latency_s=res.get("latency_s", 0.0))
        await c.execute(stmt.on_conflict_do_update(index_elements=["thread_id"], set_={
            "status": status, "status_reason": res.get("status_reason") or "",
            "tokens": db.threads.c.tokens + res.get("tokens", 0), "cost_usd": db.threads.c.cost_usd + res.get("cost_usd", 0.0),
            "latency_s": db.threads.c.latency_s + res.get("latency_s", 0.0), "updated_at": db.now()}))
        for call in res.get("tool_calls", []):
            await c.execute(insert(db.tool_events).values(
                thread_id=res["thread_id"], user_id=user_id, agent=call["agent"], server=call["server"], tool=call["tool"],
                args=mask_obj(call["args"]), ok=call["ok"], latency_s=call["latency_s"], error=call.get("error"),
                result_preview=call.get("result_preview")))
        if kind == "bid" and job_id:
            fit, risk, dec, q = v.get("fit_report") or {}, v.get("risk_report") or {}, v.get("decision") or {}, v.get("price_quote") or {}
            await c.execute(update(db.jobs).where(and_(db.jobs.c.user_id == user_id, db.jobs.c.job_id == job_id)).values(
                thread_id=res["thread_id"], status=status, action=dec.get("action"), fit=fit.get("score"),
                risk=risk.get("score"), is_scam=bool(risk.get("is_scam")), injection=bool(risk.get("injection_detected")),
                price=q.get("amount"), connects_cost=q.get("connects_cost"),
                summary={"decision_reasons": dec.get("reasons", []), "risk_flags": risk.get("flags", []),
                         "status_reason": res.get("status_reason")}))
            sub = v.get("submission") or {}
            if status == "submitted" and sub.get("proposal_id"):
                job = v.get("job") or {}
                st = pg_insert(db.pipeline).values(user_id=user_id, proposal_id=sub["proposal_id"], job_id=job_id,
                                                   thread_id=res["thread_id"], title=job.get("title"), category=job.get("category"),
                                                   strategy=v.get("strategy"), stage="submitted",
                                                   connects_spent=sub.get("connects_spent", 0))
                await c.execute(st.on_conflict_do_nothing())
        if kind == "conversation" and conversation_id:
            stage = v.get("pipeline_stage")
            vals = {"thread_id": res["thread_id"]}
            if v.get("last_client_message"):
                vals["last_handled_message"] = v["last_client_message"].get("id")
            await c.execute(update(db.conversations).where(and_(db.conversations.c.user_id == user_id,
                                                                db.conversations.c.conversation_id == conversation_id)).values(**vals))
            if stage:
                await c.execute(update(db.pipeline).where(and_(db.pipeline.c.user_id == user_id,
                                                               db.pipeline.c.conversation_id == conversation_id)).values(stage=stage))


# --------------------------------------------------------------------------- runs


async def run_bid(user_id: str, job_id: str) -> dict:
    s = await user_settings(user_id)
    async with db.engine().connect() as c:
        row = (await c.execute(select(db.jobs).where(and_(db.jobs.c.user_id == user_id, db.jobs.c.job_id == job_id)))).mappings().first()
    if not row:
        raise KeyError(job_id)
    job = dict(row["data"])
    tid = row["thread_id"] if row["thread_id"] and row["status"] in ("queued_degraded",) else None
    res = await runtime.start_bid(job, user_id=user_id, persona=s["persona"], settings=s,
                                  strategy=pick_strategy(s, job_id), thread_id=tid)
    await record_result(user_id, "bid", res, job_id=job_id)
    return res


async def resume_thread(user_id: str, thread_id: str, decision: dict) -> dict:
    async with db.engine().connect() as c:
        t = (await c.execute(select(db.threads).where(and_(db.threads.c.thread_id == thread_id,
                                                           db.threads.c.user_id == user_id)))).mappings().first()
    if not t:
        raise KeyError(thread_id)
    res = await runtime.resume(t["kind"], thread_id, user_id, decision)
    await record_result(user_id, t["kind"], res, job_id=t["job_id"], conversation_id=t["conversation_id"])
    return res


async def run_conversation(user_id: str, conversation_id: str) -> dict:
    s = await user_settings(user_id)
    res = await runtime.start_conversation(conversation_id, user_id=user_id, persona=s["persona"])
    await record_result(user_id, "conversation", res, conversation_id=conversation_id)
    return res


_tasks: set[asyncio.Task] = set()
_SEM: asyncio.Semaphore | None = None


def _sem() -> asyncio.Semaphore:
    """Inline mode mirrors the worker: at most `worker.max_concurrent_jobs` graph runs at once."""
    global _SEM
    if _SEM is None:
        from agent.settings import cfg

        _SEM = asyncio.Semaphore(int(cfg("worker.max_concurrent_jobs", 3)))
    return _SEM


async def dispatch(task: str, **kw: Any) -> str:
    """Run long work in the worker (Arq on Redis) or, in dev/tests, as a local background task."""
    job_id = f"{task}:{uuid.uuid4().hex[:8]}"
    if os.getenv("WORKER_MODE", "inline") == "arq":
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(RedisSettings.from_dsn(os.getenv("REDIS_URL", "redis://localhost:6379/0")))
        await pool.enqueue_job(task, _job_id=kw.pop("_job_id", None), **kw)
        return job_id
    fn = {"run_bid": run_bid, "resume_thread": resume_thread, "run_conversation": run_conversation,
          "scout_user": scout_user, "sync_pipeline": sync_pipeline}[task]

    async def guarded():
        try:
            async with _sem():
                await fn(**kw)
        except Exception as e:  # noqa: BLE001
            print(f"[dispatch] {task} failed: {type(e).__name__}: {e}")

    t = asyncio.create_task(guarded())
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)
    return job_id


# --------------------------------------------------------------------------- scouting + pipeline sync


def _fingerprint(job: dict) -> str:
    from agent.graphs.bid_graph import job_fingerprint

    return job_fingerprint(job)


async def scout_user(user_id: str, search_id: str | None = None, analyse: bool = True, max_new: int = 10) -> dict:
    """Scout agent: run saved searches via the marketplace MCP server, de-duplicate, queue new jobs.
    Idempotent: a job already in the inbox (same id or same fingerprint) is never re-queued."""
    s = await user_settings(user_id)
    tb = ToolBox("scout", Caller(user=user_id, persona=s["persona"]))
    async with db.engine().connect() as c:
        q = select(db.saved_searches).where(and_(db.saved_searches.c.user_id == user_id, db.saved_searches.c.enabled))
        if search_id:
            q = q.where(db.saved_searches.c.id == search_id)
        searches = (await c.execute(q)).mappings().all()
        known = {r[0]: r[1] for r in (await c.execute(select(db.jobs.c.job_id, db.jobs.c.fingerprint).where(
            db.jobs.c.user_id == user_id))).all()}
    fps = set(known.values())
    new_ids: list[str] = []
    dupes = 0
    try:
        for ss in searches:
            res = await tb.call("search_jobs", {"query": ss["query"] or "", "category": ss["category"],
                                                "skills": ss["skills"] or None, "limit": 25})
            for j in res["jobs"]:
                fp = _fingerprint(j)
                if j["id"] in known:
                    continue
                if fp in fps:
                    dupes += 1
                    continue
                fps.add(fp)
                known[j["id"]] = fp
                async with db.engine().begin() as c:
                    await c.execute(pg_insert(db.jobs).values(user_id=user_id, job_id=j["id"], data=j, title=j["title"],
                                                              category=j.get("category"), fingerprint=fp, status="new")
                                    .on_conflict_do_nothing())
                new_ids.append(j["id"])
            async with db.engine().begin() as c:
                await c.execute(update(db.saved_searches).where(db.saved_searches.c.id == ss["id"]).values(last_run_at=db.now()))
    except Degraded as e:
        return {"new": new_ids, "duplicates": dupes, "degraded": str(e)}
    if analyse:
        for jid in new_ids[:max_new]:
            await dispatch("run_bid", user_id=user_id, job_id=jid)
    return {"new": new_ids, "duplicates": dupes}


STAGE_FOR_EVENT = {"submitted": "submitted", "viewed": "viewed", "replied": "replied", "interview_request": "interview",
                   "hired": "hired", "lost": "lost"}


async def sync_pipeline(user_id: str) -> dict:
    """Pull marketplace events -> pipeline stages, conversations, outcome memory; start the Client
    Liaison for new client messages."""
    from agent.memory.store import record_outcome

    s = await user_settings(user_id)
    tb = ToolBox("pipeline_sync", Caller(user=user_id, persona=s["persona"]))
    key = f"events_cursor:{user_id}"
    cursor = int(await _kv_get(key) or 0)
    events = (await tb.call("list_events", {"since_id": cursor}))["events"]
    started = []
    for e in events:
        stage = STAGE_FOR_EVENT.get(e["type"])
        async with db.engine().begin() as c:
            if stage and e.get("ref"):
                vals = {"stage": stage}
                if e["data"].get("conversation_id"):
                    vals["conversation_id"] = e["data"]["conversation_id"]
                await c.execute(update(db.pipeline).where(and_(db.pipeline.c.user_id == user_id,
                                                               db.pipeline.c.proposal_id == e["ref"])).values(**vals))
                row = (await c.execute(select(db.pipeline).where(and_(db.pipeline.c.user_id == user_id,
                                                                      db.pipeline.c.proposal_id == e["ref"])))).mappings().first()
                if row and e["type"] in ("replied", "lost", "hired", "interview_request"):
                    await c.execute(pg_insert(db.outcomes).values(user_id=user_id, proposal_id=e["ref"], category=row["category"],
                                                                  strategy=row["strategy"], event=e["type"]).on_conflict_do_nothing())
            if e["data"].get("conversation_id"):
                cid = e["data"]["conversation_id"]
                await c.execute(pg_insert(db.conversations).values(user_id=user_id, conversation_id=cid, job_id=e["data"].get("job_id"),
                                                                   proposal_id=e.get("ref"), last_message_at=e["at"]).on_conflict_do_update(
                    index_elements=["user_id", "conversation_id"], set_={"last_message_at": e["at"]}))
        if e["type"] in ("replied", "lost") and runtime.store() is not None and row:
            await record_outcome(runtime.store(), user_id, row["category"] or "other", row["strategy"] or "default",
                                 e["type"] == "replied", e["ref"])
        if e["type"] in ("replied", "message", "interview_request") and e["data"].get("conversation_id"):
            started.append(e["data"]["conversation_id"])
        cursor = max(cursor, e["id"])
    await _kv_set(key, str(cursor))
    for cid in dict.fromkeys(started):
        await dispatch("run_conversation", user_id=user_id, conversation_id=cid)
    return {"events": len(events), "conversations_started": len(set(started))}


async def _kv_get(key: str) -> str | None:
    r = await runtime._r()
    return await r.get(key) if r else _KV.get(key)


async def _kv_set(key: str, value: str) -> None:
    r = await runtime._r()
    if r:
        await r.set(key, value)
    else:
        _KV[key] = value


_KV: dict[str, str] = {}
