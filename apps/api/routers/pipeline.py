"""Pipeline board, messages and analytics."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import and_, desc, func, select

from agent import runtime
from agent.mcp_client import Caller, Degraded, ToolBox
from apps.api import db, services
from apps.api.auth.security import CurrentUser
from apps.api.schemas import AnalyticsOut, ConversationOut, PipelineCard

router = APIRouter(prefix="/api", tags=["pipeline"])
STAGES = ["drafted", "submitted", "viewed", "replied", "interview", "hired", "lost"]


@router.get("/pipeline", response_model=list[PipelineCard])
async def board(uid: str = CurrentUser) -> list[PipelineCard]:
    async with db.engine().connect() as c:
        rows = (await c.execute(select(db.pipeline).where(db.pipeline.c.user_id == uid)
                                .order_by(desc(db.pipeline.c.updated_at)))).mappings().all()
        drafted = (await c.execute(select(db.threads).where(and_(db.threads.c.user_id == uid, db.threads.c.kind == "bid",
                                                                 db.threads.c.status == "awaiting_approval")))).mappings().all()
        titles = {r["job_id"]: (r["title"], r["category"]) for r in (await c.execute(
            select(db.jobs.c.job_id, db.jobs.c.title, db.jobs.c.category).where(db.jobs.c.user_id == uid))).mappings()}
    out = [PipelineCard(**{k: r[k] for k in PipelineCard.model_fields}) for r in rows]
    for t in drafted:
        title, cat = titles.get(t["job_id"], (None, None))
        out.append(PipelineCard(proposal_id=f"draft:{t['thread_id']}", job_id=t["job_id"], title=title, category=cat,
                                stage="drafted", strategy=t["strategy"], connects_spent=0, conversation_id=None,
                                thread_id=t["thread_id"], updated_at=t["updated_at"]))
    return out


@router.post("/pipeline/sync")
async def sync(uid: str = CurrentUser) -> dict:
    """Pull marketplace events now (normally scheduled by the worker)."""
    return {"queued": await services.dispatch("sync_pipeline", user_id=uid)}


@router.get("/messages", response_model=list[ConversationOut])
async def conversations(uid: str = CurrentUser) -> list[ConversationOut]:
    async with db.engine().connect() as c:
        rows = (await c.execute(select(db.conversations).where(db.conversations.c.user_id == uid)
                                .order_by(desc(db.conversations.c.last_message_at)))).mappings().all()
    return [ConversationOut(conversation_id=r["conversation_id"], job_id=r["job_id"], proposal_id=r["proposal_id"],
                            state=r["state"], thread_id=r["thread_id"]) for r in rows]


@router.get("/messages/{conversation_id}", response_model=ConversationOut)
async def conversation(conversation_id: str, uid: str = CurrentUser) -> ConversationOut:
    async with db.engine().connect() as c:
        r = (await c.execute(select(db.conversations).where(and_(db.conversations.c.user_id == uid,
                                                                 db.conversations.c.conversation_id == conversation_id)))).mappings().first()
    if not r:
        raise HTTPException(404, "conversation not found")
    s = await services.user_settings(uid)
    try:
        msgs = (await ToolBox("client_liaison", Caller(user=uid, persona=s["persona"])).call(
            "list_messages", {"conversation_id": conversation_id}))["messages"]
    except Degraded:
        msgs = []
    pending = await runtime.pending("conversation", r["thread_id"]) if r["thread_id"] else None
    return ConversationOut(conversation_id=conversation_id, job_id=r["job_id"], proposal_id=r["proposal_id"], state=r["state"],
                           thread_id=r["thread_id"], messages=msgs, pending=pending)


@router.post("/messages/{conversation_id}/draft")
async def draft_reply(conversation_id: str, uid: str = CurrentUser) -> dict:
    return {"queued": await services.dispatch("run_conversation", user_id=uid, conversation_id=conversation_id)}


@router.get("/analytics", response_model=AnalyticsOut)
async def analytics(uid: str = CurrentUser) -> AnalyticsOut:
    async with db.engine().connect() as c:
        p = (await c.execute(select(db.pipeline).where(db.pipeline.c.user_id == uid))).mappings().all()
        th = (await c.execute(select(db.threads).where(db.threads.c.user_id == uid))).mappings().all()
        rej = (await c.execute(select(db.threads.c.status_reason, func.count()).where(and_(
            db.threads.c.user_id == uid, db.threads.c.status == "rejected")).group_by(db.threads.c.status_reason)
            .order_by(desc(func.count())).limit(8))).all()
    replied = {"replied", "interview", "hired"}

    def agg(key):
        groups: dict[str, list] = {}
        for r in p:
            groups.setdefault(r[key] or "unknown", []).append(r)
        return [{key: k, "submitted": len(v), "replies": sum(r["stage"] in replied for r in v),
                 "hires": sum(r["stage"] == "hired" for r in v),
                 "reply_rate": round(sum(r["stage"] in replied for r in v) / len(v), 3) if v else 0,
                 "hire_rate": round(sum(r["stage"] == "hired" for r in v) / len(v), 3) if v else 0,
                 "connects": sum(r["connects_spent"] or 0 for r in v)} for k, v in sorted(groups.items())]

    bids = [t for t in th if t["kind"] == "bid"]
    props = [t for t in bids if t["status"] in ("submitted", "awaiting_approval", "rejected")]
    lat = sorted(t["latency_s"] for t in bids if t["latency_s"])
    plat = sorted(t["latency_s"] for t in props if t["latency_s"])

    def p95(xs):
        return round(xs[int(0.95 * (len(xs) - 1))], 2) if xs else None

    spent = sum(r["connects_spent"] or 0 for r in p)
    return AnalyticsOut(
        by_category=agg("category"), by_strategy=agg("strategy"),
        connects={"spent": spent, "replies": sum(r["stage"] in replied for r in p),
                  "connects_per_reply": round(spent / max(1, sum(r["stage"] in replied for r in p)), 1)},
        cost_latency={"jobs_analysed": len(bids), "proposals": len(props),
                      "cost_per_job_usd": round(sum(t["cost_usd"] for t in bids) / max(1, len(bids)), 5),
                      "cost_per_proposal_usd": round(sum(t["cost_usd"] for t in props) / max(1, len(props)), 5),
                      "p95_latency_job_s": p95(lat), "p95_latency_proposal_s": p95(plat),
                      "tokens_per_proposal": round(sum(t["tokens"] for t in props) / max(1, len(props)))},
        rejection_reasons=[{"reason": (r or "")[:120], "count": n} for r, n in rej],
        funnel={s: sum(1 for r in p if r["stage"] == s) for s in STAGES} | {"drafted": sum(1 for t in bids if t["status"] == "awaiting_approval")},
    )
