"""Background worker (E1): scheduled scouting and long agent runs, outside web requests.

Run:  arq worker.main.WorkerSettings          (API uses WORKER_MODE=arq to enqueue here)

* `tick` (cron, every 5 min): for each user, runs saved searches whose interval has elapsed
  (live Upwork mode never more often than `marketplace.live_poll_interval_minutes`, see
  docs/RUNBOOK.md), syncs pipeline events, and re-queues threads that were parked in
  `queued_degraded` once the marketplace is healthy again.
* Long runs (`run_bid`, `resume_thread`, `run_conversation`) execute here with bounded
  concurrency (`worker.max_concurrent_jobs`) and a per-job timeout.
* Idempotent: deterministic Arq job ids + `run_bid` skipping already-analysed jobs + MCP
  idempotency keys on every write, so a worker restart never double-analyses or double-submits.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import and_, select, update

from agent import runtime
from agent.settings import cfg
from apps.api import db, services


async def startup(ctx: dict) -> None:
    await db.create_all()
    await runtime.init()


async def shutdown(ctx: dict) -> None:
    await runtime.close()


async def run_bid(ctx: dict, user_id: str, job_id: str, force: bool = False) -> dict:
    res = await services.run_bid(user_id, job_id, force=force)
    return {"thread_id": res.get("thread_id"), "status": res.get("status")}


async def resume_thread(ctx: dict, user_id: str, thread_id: str, decision: dict) -> dict:
    res = await services.resume_thread(user_id, thread_id, decision)
    return {"thread_id": thread_id, "status": res.get("status")}


async def run_conversation(ctx: dict, user_id: str, conversation_id: str) -> dict:
    res = await services.run_conversation(user_id, conversation_id)
    return {"thread_id": res.get("thread_id"), "status": res.get("status")}


async def scout_user(ctx: dict, user_id: str, search_id: str | None = None) -> dict:
    return await services.scout_user(user_id, search_id)


async def sync_pipeline(ctx: dict, user_id: str) -> dict:
    return await services.sync_pipeline(user_id)


def due(search: dict, mode: str, now: datetime) -> bool:
    interval = int(search["interval_minutes"] or 30)
    if mode == "upwork_live":  # polite polling of the real platform
        interval = max(interval, int(cfg("marketplace.live_poll_interval_minutes", 240)))
    last = search["last_run_at"]
    return last is None or now - last >= timedelta(minutes=interval)


async def tick(ctx: dict) -> dict:
    now = datetime.now(UTC)
    redis = ctx["redis"]
    queued = {"scout": 0, "sync": 0, "requeued": 0}
    async with db.engine().connect() as c:
        users = (await c.execute(select(db.users.c.id))).scalars().all()
        modes = dict((await c.execute(select(db.user_settings.c.user_id, db.user_settings.c.marketplace_mode))).all())
        searches = (await c.execute(select(db.saved_searches).where(db.saved_searches.c.enabled))).mappings().all()
        parked = (await c.execute(select(db.jobs.c.user_id, db.jobs.c.job_id).where(db.jobs.c.status == "queued_degraded"))).all()
    for s in searches:
        if due(s, modes.get(s["user_id"], "gigsim"), now):
            # job id per (search, time-bucket): a second tick in the same window is a no-op
            bucket = int(now.timestamp() // 300)
            j = await redis.enqueue_job("scout_user", s["user_id"], s["id"], _job_id=f"scout:{s['id']}:{bucket}")
            queued["scout"] += j is not None
    for u in users:
        j = await redis.enqueue_job("sync_pipeline", u, _job_id=f"sync:{u}:{int(now.timestamp() // 300)}")
        queued["sync"] += j is not None
    if parked:
        try:
            from agent.mcp_client import Caller, ToolBox

            st = await ToolBox("scout", Caller()).call("marketplace_status", {})
            healthy = st.get("circuit", {}).get("state") != "open"
        except Exception:  # noqa: BLE001
            healthy = False
        if healthy:
            for uid, jid in parked:
                async with db.engine().begin() as c:
                    await c.execute(update(db.jobs).where(and_(db.jobs.c.user_id == uid, db.jobs.c.job_id == jid)).values(status="new"))
                await redis.enqueue_job("run_bid", uid, jid, _job_id=f"run_bid:{uid}:{jid}:retry:{int(now.timestamp() // 300)}")
                queued["requeued"] += 1
    return queued


class WorkerSettings:
    functions = [run_bid, resume_thread, run_conversation, scout_user, sync_pipeline]
    cron_jobs = [cron(tick, minute=set(range(0, 60, 5)), run_at_startup=True)]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    max_jobs = int(cfg("worker.max_concurrent_jobs", 3))
    job_timeout = int(cfg("worker.job_timeout_s", 300))
    keep_result = 3600
    allow_abort_jobs = True
