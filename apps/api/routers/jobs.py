"""Job inbox + job detail + manual actions."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import and_, desc, select, update

from agent import runtime
from apps.api import db, services
from apps.api.auth.security import CurrentUser
from apps.api.schemas import JobCard, JobDetail

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _card(r) -> JobCard:
    d = r["data"] or {}
    return JobCard(job_id=r["job_id"], title=r["title"], category=r["category"], status=r["status"], action=r["action"],
                   fit=r["fit"], risk=r["risk"], is_scam=r["is_scam"], injection=r["injection"], price=r["price"],
                   connects_cost=r["connects_cost"] if r["connects_cost"] is not None else d.get("connects_cost"),
                   budget=d.get("budget"), discovered_at=r["discovered_at"], thread_id=r["thread_id"],
                   reasons=(r["summary"] or {}).get("decision_reasons", []))


@router.get("", response_model=list[JobCard])
async def inbox(uid: str = CurrentUser, status: str | None = None, action: str | None = None,
                q: str | None = Query(None, max_length=100), hide_skipped: bool = False, limit: int = Query(100, le=500)) -> list[JobCard]:
    """New jobs ranked by fit, with risk badges, recommended action, price and Connects cost."""
    s = select(db.jobs).where(db.jobs.c.user_id == uid)
    if status:
        s = s.where(db.jobs.c.status == status)
    if action:
        s = s.where(db.jobs.c.action == action)
    if hide_skipped:
        s = s.where(db.jobs.c.status.notin_(["skipped", "duplicate"]))
    if q:
        s = s.where(db.jobs.c.title.ilike(f"%{q}%"))
    s = s.order_by(desc(db.jobs.c.fit).nulls_last(), desc(db.jobs.c.discovered_at)).limit(limit)
    async with db.engine().connect() as c:
        return [_card(r) for r in (await c.execute(s)).mappings().all()]


@router.get("/{job_id}", response_model=JobDetail)
async def detail(job_id: str, uid: str = CurrentUser) -> JobDetail:
    async with db.engine().connect() as c:
        r = (await c.execute(select(db.jobs).where(and_(db.jobs.c.user_id == uid, db.jobs.c.job_id == job_id)))).mappings().first()
    if not r:
        raise HTTPException(404, "job not found")
    card = _card(r)
    v = {}
    if r["thread_id"]:
        try:
            v = (await runtime.state("bid", r["thread_id"]))["values"]
        except Exception:  # noqa: BLE001
            v = {}
    return JobDetail(**card.model_dump(), job=r["data"], job_spec=v.get("job_spec"), risk_report=v.get("risk_report"),
                     fit_report=v.get("fit_report"), decision=v.get("decision"), price_quote=v.get("price_quote"),
                     status_reason=v.get("status_reason"))


@router.post("/{job_id}/analyse")
async def analyse(job_id: str, uid: str = CurrentUser) -> dict:
    """(Re)run the bid graph for a job in the worker; progress streams to /api/runs/{thread}/stream."""
    async with db.engine().begin() as c:
        await c.execute(update(db.jobs).where(and_(db.jobs.c.user_id == uid, db.jobs.c.job_id == job_id)).values(status="analysing"))
    return {"queued": await services.dispatch("run_bid", user_id=uid, job_id=job_id)}


@router.post("/{job_id}/skip")
async def skip(job_id: str, uid: str = CurrentUser) -> dict:
    async with db.engine().begin() as c:
        await c.execute(update(db.jobs).where(and_(db.jobs.c.user_id == uid, db.jobs.c.job_id == job_id)).values(
            status="skipped", action="skip"))
    return {"ok": True}


@router.post("/scout")
async def scout_now(uid: str = CurrentUser) -> dict:
    """Run saved searches now (normally scheduled by the worker)."""
    return {"queued": await services.dispatch("scout_user", user_id=uid)}
