"""GigBid API (FastAPI). Typed contract -> the web client is generated from /openapi.json."""

from __future__ import annotations

import contextlib
import logging
import os
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from agent import runtime
from agent.guardrails import mask_pii
from apps.api import db
from apps.api.routers import approvals, auth, jobs, pipeline, runs, settings


class PiiMaskingFilter(logging.Filter):
    """E4: emails, phones, payment details are masked in every log line."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = mask_pii(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(mask_pii(a) if isinstance(a, str) else a for a in record.args)
        return True


for name in ("", "uvicorn", "uvicorn.access", "uvicorn.error", "httpx"):
    logging.getLogger(name).addFilter(PiiMaskingFilter())


async def seed_reviewer() -> None:
    """Reviewer login preloaded with a persona + saved searches (R10)."""
    from sqlalchemy import insert, select

    from apps.api.auth.security import hash_password

    email = os.getenv("REVIEWER_EMAIL", "reviewer@gigbid.dev").lower()
    pwd = os.getenv("REVIEWER_PASSWORD")
    if not pwd:
        return
    async with db.engine().begin() as c:
        if (await c.execute(select(db.users.c.id).where(db.users.c.email == email))).first():
            return
        uid = "u_reviewer"
        await c.execute(insert(db.users).values(id=uid, email=email, password_hash=hash_password(pwd), name="Reviewer",
                                                persona="ai_ml_engineer", onboarded=True))
        await c.execute(insert(db.user_settings).values(user_id=uid, weekly_connects_budget=120))
        for i, (name, q, cat) in enumerate([("ML & LLM jobs", "machine learning", "ai_ml"), ("RAG / chatbots", "chatbot", "ai_ml"),
                                            ("Data science", "data scientist", None)]):
            await c.execute(insert(db.saved_searches).values(id=f"ss_rev{i}", user_id=uid, name=name, query=q, category=cat,
                                                             skills=[], interval_minutes=30, enabled=True))


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    await db.create_all()
    await runtime.init()
    await seed_reviewer()
    yield
    await runtime.close()


app = FastAPI(title="GigBid API", version="1.0.0", lifespan=lifespan,
              description="Multi-agent freelancer copilot: jobs, proposals, approvals, messages, runs, analytics.")
app.add_middleware(CORSMiddleware, allow_origins=[os.getenv("PUBLIC_WEB_URL", "http://localhost:3000")],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def trace_id(request: Request, call_next):
    """One trace id from the UI request onwards (also returned to the browser)."""
    tid = request.headers.get("x-trace-id") or uuid.uuid4().hex
    request.state.trace_id = tid
    resp = await call_next(request)
    resp.headers["x-trace-id"] = tid
    return resp


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "gigbid-api"}


for r in (auth.router, jobs.router, approvals.router, runs.router, pipeline.router, settings.router):
    app.include_router(r)
