"""Application tables (SQLAlchemy Core, async). Every query is scoped by user_id (tenant)."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

metadata = MetaData()


def now() -> datetime:
    return datetime.now(UTC)


users = Table(
    "users", metadata,
    Column("id", String(40), primary_key=True),
    Column("email", String(200), unique=True, nullable=False),
    Column("password_hash", String(200), nullable=False),
    Column("name", String(120), nullable=False),
    Column("persona", String(60), nullable=False, default="ai_ml_engineer"),
    Column("role", String(20), nullable=False, default="freelancer"),
    Column("onboarded", Boolean, nullable=False, default=False),
    Column("created_at", DateTime(timezone=True), default=now),
)

user_settings = Table(
    "user_settings", metadata,
    Column("user_id", String(40), primary_key=True),
    Column("autonomy", String(20), default="suggest"),
    Column("weekly_connects_budget", Integer, default=80),
    Column("hourly_rate", Float, nullable=True),
    Column("fixed_floor", Float, nullable=True),
    Column("filters", JSON, default=dict),
    Column("marketplace_mode", String(20), default="gigsim"),
    Column("strategy_mode", String(30), default="ab_test"),  # ab_test | default | evidence_first | question_led
    Column("updated_at", DateTime(timezone=True), default=now, onupdate=now),
)

saved_searches = Table(
    "saved_searches", metadata,
    Column("id", String(40), primary_key=True),
    Column("user_id", String(40), index=True, nullable=False),
    Column("name", String(120), nullable=False),
    Column("query", String(200), default=""),
    Column("category", String(40), nullable=True),
    Column("skills", JSON, default=list),
    Column("interval_minutes", Integer, default=30),
    Column("enabled", Boolean, default=True),
    Column("last_run_at", DateTime(timezone=True), nullable=True),
    Column("last_seen_posted_at", Float, nullable=True),
)

jobs = Table(
    "jobs", metadata,
    Column("user_id", String(40), primary_key=True),
    Column("job_id", String(80), primary_key=True),
    Column("data", JSON, nullable=False),
    Column("title", Text, nullable=False),
    Column("category", String(40)),
    Column("fingerprint", String(32), index=True),
    Column("discovered_at", DateTime(timezone=True), default=now),
    Column("thread_id", String(80), nullable=True),
    Column("status", String(30), default="new"),
    Column("action", String(10), nullable=True),
    Column("fit", Float, nullable=True),
    Column("risk", Float, nullable=True),
    Column("is_scam", Boolean, default=False),
    Column("injection", Boolean, default=False),
    Column("price", Float, nullable=True),
    Column("connects_cost", Integer, nullable=True),
    Column("summary", JSON, default=dict),
)

threads = Table(
    "threads", metadata,
    Column("thread_id", String(80), primary_key=True),
    Column("user_id", String(40), index=True, nullable=False),
    Column("kind", String(20), nullable=False),  # bid | conversation
    Column("job_id", String(80), nullable=True),
    Column("conversation_id", String(80), nullable=True),
    Column("status", String(30), default="new"),
    Column("status_reason", Text, default=""),
    Column("strategy", String(30), nullable=True),
    Column("trace_id", String(80)),
    Column("tokens", Integer, default=0),
    Column("cost_usd", Float, default=0.0),
    Column("latency_s", Float, default=0.0),
    Column("created_at", DateTime(timezone=True), default=now),
    Column("updated_at", DateTime(timezone=True), default=now, onupdate=now),
)

pipeline = Table(
    "pipeline", metadata,
    Column("user_id", String(40), primary_key=True),
    Column("proposal_id", String(80), primary_key=True),
    Column("job_id", String(80)),
    Column("thread_id", String(80)),
    Column("title", Text),
    Column("category", String(40)),
    Column("strategy", String(30)),
    Column("stage", String(20), default="submitted"),  # drafted submitted viewed replied interview hired lost
    Column("connects_spent", Integer, default=0),
    Column("conversation_id", String(80), nullable=True),
    Column("updated_at", DateTime(timezone=True), default=now, onupdate=now),
)

conversations = Table(
    "conversations", metadata,
    Column("user_id", String(40), primary_key=True),
    Column("conversation_id", String(80), primary_key=True),
    Column("job_id", String(80)),
    Column("proposal_id", String(80)),
    Column("state", String(20), default="open"),
    Column("last_message_at", Float, default=0),
    Column("last_handled_message", String(80), nullable=True),
    Column("thread_id", String(80), nullable=True),
)

tool_events = Table(  # execution trace (separate from state and memory)
    "tool_events", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("thread_id", String(80), index=True),
    Column("user_id", String(40), index=True),
    Column("agent", String(40)),
    Column("server", String(40)),
    Column("tool", String(60)),
    Column("args", JSON),
    Column("ok", Boolean),
    Column("latency_s", Float),
    Column("error", Text, nullable=True),
    Column("result_preview", Text, nullable=True),
    Column("at", DateTime(timezone=True), default=now),
)

run_events = Table(  # node-by-node timeline for the run viewer (replayable after refresh)
    "run_events", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("thread_id", String(80), index=True),
    Column("user_id", String(40), index=True),
    Column("event", JSON),
    Column("at", DateTime(timezone=True), default=now),
)

outcomes = Table(
    "outcomes", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", String(40), index=True),
    Column("proposal_id", String(80)),
    Column("category", String(40)),
    Column("strategy", String(30)),
    Column("event", String(30)),
    Column("at", DateTime(timezone=True), default=now),
    UniqueConstraint("user_id", "proposal_id", "event"),
)

judge_labels = Table(
    "judge_labels", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", String(40)),
    Column("item_id", String(120), index=True),
    Column("scores", JSON),
    Column("at", DateTime(timezone=True), default=now),
    UniqueConstraint("user_id", "item_id"),
)

panel_votes = Table(
    "panel_votes", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("voter", String(80)),
    Column("pair_id", String(120), index=True),
    Column("choice", String(5)),  # A | B | tie
    Column("at", DateTime(timezone=True), default=now),
    UniqueConstraint("voter", "pair_id"),
)

_engine: AsyncEngine | None = None


def async_url() -> str:
    url = os.getenv("DATABASE_URL", "postgresql://gigbid:gigbid@localhost:5432/gigbid")
    return url.replace("postgresql://", "postgresql+asyncpg://").replace("postgresql+psycopg://", "postgresql+asyncpg://")


def engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(async_url(), pool_size=10, max_overflow=10, pool_pre_ping=True)
    return _engine


async def create_all() -> None:
    async with engine().begin() as conn:
        await conn.run_sync(metadata.create_all)
