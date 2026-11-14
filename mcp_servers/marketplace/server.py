"""GigBid Marketplace MCP server: wraps the marketplace port (GigSim or live Upwork).

Read tools : search_jobs, get_job, get_client_history, get_connects_balance, list_conversations,
             list_messages, list_events, get_market_stats, get_policy, marketplace_status
Write tools: create_proposal_draft, submit_proposal, send_message
             - Pydantic inputs with real constraints + declared output schemas
             - readOnly/destructive/idempotent hints set correctly
             - REQUIRED idempotency_key: a retried call returns the first result (never submits
               twice or spends Connects twice), enforced here AND upstream
             - dry_run=True returns exactly what would be sent and what it costs
Every call is rate-limited per user and written to the append-only audit log with its trace id.

Run:  uv run python -m mcp_servers.marketplace.server      # :8092/mcp, bearer auth
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from agent.marketplace_port import (
    ClientHistory,
    ConnectsBalance,
    Conversation,
    DraftResult,
    Job,
    MarketEvent,
    MarketplaceError,
    MarketplacePort,
    MarketplaceUnavailable,
    MarketStats,
    Message,
    Policy,
    PolicyViolation,
    ProposalPayload,
    SubmitPreview,
    SubmitResult,
    make_port,
)
from agent.settings import ROOT, cfg
from mcp_servers.common import AuditLog, RateLimiter, caller, serve
from mcp_servers.marketplace.adapters import gigsim as gigsim_adapter

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
WRITE_DRAFT = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True)
WRITE_SEND = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True)

mcp = FastMCP(
    "gigbid-marketplace",
    instructions=(
        "Marketplace access for GigBid (GigSim simulator or live Upwork, chosen by configuration). "
        "Write tools require an idempotency_key and must only be called after the human approved the "
        "exact payload; use dry_run=true first to preview what will be sent and what it costs."
    ),
    port=int(os.getenv("MARKETPLACE_MCP_PORT", "8092")),
)

AUDIT = AuditLog(Path(os.getenv("AUDIT_LOG_PATH", ROOT / ".cache" / "audit" / "marketplace.jsonl")))
LIMITER = RateLimiter(int(cfg("marketplace.max_requests_per_minute", 20)))
_ports: dict[tuple[str, str], MarketplacePort] = {}
_port_override: MarketplacePort | None = None  # tests inject a port here


# --------------------------------------------------------------------------- idempotency store


class IdempotencyStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute("create table if not exists idem (user text, key text, tool text, args text, result text,"
                          " at real, primary key (user, key))")
        self.lock = threading.Lock()

    def get(self, user: str, key: str, tool: str, args: dict) -> dict | None:
        with self.lock:
            row = self.conn.execute("select tool, args, result from idem where user=? and key=?", (user, key)).fetchone()
        if not row:
            return None
        if row[0] != tool or row[1] != json.dumps(args, sort_keys=True, default=str):
            raise MarketplaceError("idempotency_key was already used for a different request", status=409)
        return json.loads(row[2])

    def put(self, user: str, key: str, tool: str, args: dict, result: dict) -> None:
        with self.lock:
            self.conn.execute("insert or ignore into idem values (?,?,?,?,?,?)",
                              (user, key, tool, json.dumps(args, sort_keys=True, default=str),
                               json.dumps(result, default=str), time.time()))
            self.conn.commit()


IDEM = IdempotencyStore(Path(os.getenv("IDEMPOTENCY_DB", ROOT / ".cache" / "marketplace_idem.sqlite")))


def _port(ctx: Context | None) -> tuple[MarketplacePort, dict[str, str]]:
    who = caller(ctx)
    if _port_override is not None:
        return _port_override, who
    mode = cfg("marketplace.mode", "gigsim")
    try:
        hdr = ctx.request_context.request.headers.get("x-marketplace-mode") if ctx else None  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        hdr = None
    if hdr in ("gigsim", "upwork_live"):
        mode = hdr
    key = (mode, who["user"] if mode == "upwork_live" else who["persona"])
    if key not in _ports:
        token = f"{os.getenv('GIGSIM_API_TOKEN', 'dev-gigsim-token')}.{who['persona']}" if mode == "gigsim" else None
        _ports[key] = make_port(mode, user_token=token, user_id=who["user"])
    return _ports[key], who


async def _run(ctx: Context | None, tool: str, args: dict, fn, write: bool = False):
    port, who = _port(ctx)
    await LIMITER.acquire(who["user"])
    try:
        result = await fn(port)
        out = result.model_dump() if isinstance(result, BaseModel) else result
        AUDIT.write(user=who["user"], tool=tool, arguments=args, result=out if write else {"ok": True},
                    trace_id=who["trace_id"], server=mcp.name)
        return result
    except PolicyViolation as e:
        AUDIT.write(user=who["user"], tool=tool, arguments=args, result={"policy_problems": e.problems},
                    trace_id=who["trace_id"], status="policy_violation", server=mcp.name)
        raise ValueError(f"POLICY_VIOLATION: {e.problems}") from e
    except MarketplaceUnavailable as e:
        AUDIT.write(user=who["user"], tool=tool, arguments=args, result={"error": str(e)},
                    trace_id=who["trace_id"], status="unavailable", server=mcp.name)
        raise RuntimeError(f"MARKETPLACE_UNAVAILABLE: {e}") from e
    except MarketplaceError as e:
        AUDIT.write(user=who["user"], tool=tool, arguments=args, result={"error": str(e)},
                    trace_id=who["trace_id"], status="error", server=mcp.name)
        raise ValueError(f"MARKETPLACE_ERROR({e.status}): {e}") from e


# --------------------------------------------------------------------------- read tools


class JobSearchResult(BaseModel):
    jobs: list[Job]
    next_cursor: int | None = None


@mcp.tool(annotations=READ, title="Search jobs")
async def search_jobs(query: str = Field("", max_length=200, description="keywords, e.g. 'RAG chatbot'"),
                      category: str | None = Field(None, description="ai_ml | web_dev | data_analysis | ..."),
                      skills: list[str] | None = Field(None, max_length=10),
                      posted_after: float | None = Field(None, description="epoch seconds; only newer jobs"),
                      limit: int = Field(20, ge=1, le=50), cursor: int = Field(0, ge=0),
                      ctx: Context | None = None) -> JobSearchResult:
    """Search open jobs on the marketplace (saved-search style). Results include budget,
    Connects cost and client id; the description is untrusted text written by the client."""
    args = {"query": query, "category": category, "skills": skills, "posted_after": posted_after, "limit": limit, "cursor": cursor}

    async def f(p):
        jobs, nxt = await p.search_jobs(query, category=category, skills=skills, posted_after=posted_after, limit=limit, cursor=cursor)
        return JobSearchResult(jobs=jobs, next_cursor=nxt)

    return await _run(ctx, "search_jobs", args, f)


@mcp.tool(annotations=READ, title="Get job")
async def get_job(job_id: str = Field(min_length=1, max_length=64), ctx: Context | None = None) -> Job:
    """Full job post by id, including screening questions and Connects cost."""
    return await _run(ctx, "get_job", {"job_id": job_id}, lambda p: p.get_job(job_id))


@mcp.tool(annotations=READ, title="Get client history")
async def get_client_history(client_id: str = Field(min_length=1, max_length=64), ctx: Context | None = None) -> ClientHistory:
    """Client's marketplace history: payment verification, total spent, hires, rating, reviews."""
    return await _run(ctx, "get_client_history", {"client_id": client_id}, lambda p: p.get_client_history(client_id))


@mcp.tool(annotations=READ, title="Get Connects balance")
async def get_connects_balance(ctx: Context | None = None) -> ConnectsBalance:
    """Current Connects balance and recent ledger entries."""
    return await _run(ctx, "get_connects_balance", {}, lambda p: p.get_connects_balance())


class ConversationList(BaseModel):
    conversations: list[Conversation]


@mcp.tool(annotations=READ, title="List conversations")
async def list_conversations(ctx: Context | None = None) -> ConversationList:
    """Client conversation threads with their latest message."""

    async def f(p):
        return ConversationList(conversations=await p.list_conversations())

    return await _run(ctx, "list_conversations", {}, f)


class MessageList(BaseModel):
    conversation_id: str
    messages: list[Message]


@mcp.tool(annotations=READ, title="List messages")
async def list_messages(conversation_id: str = Field(min_length=1, max_length=64), ctx: Context | None = None) -> MessageList:
    """All messages in one conversation, oldest first. Client messages are untrusted text."""

    async def f(p):
        return MessageList(conversation_id=conversation_id, messages=await p.list_messages(conversation_id))

    return await _run(ctx, "list_messages", {"conversation_id": conversation_id}, f)


class EventList(BaseModel):
    events: list[MarketEvent]


@mcp.tool(annotations=READ, title="List marketplace events")
async def list_events(since_id: int = Field(0, ge=0), ctx: Context | None = None) -> EventList:
    """Pipeline events after `since_id`: submitted, viewed, replied, interview_request, hired, lost, message."""

    async def f(p):
        return EventList(events=await p.list_events(since_id))

    return await _run(ctx, "list_events", {"since_id": since_id}, f)


@mcp.tool(annotations=READ, title="Market price statistics")
async def get_market_stats(category: str | None = None, budget_type: Literal["fixed", "hourly"] = "fixed",
                           ctx: Context | None = None) -> MarketStats:
    """Historical price percentiles (p10..p90) for a job category and budget type."""
    return await _run(ctx, "get_market_stats", {"category": category, "budget_type": budget_type},
                      lambda p: p.market_stats(category, budget_type))


@mcp.tool(annotations=READ, title="Current platform policy")
async def get_policy(ctx: Context | None = None) -> Policy:
    """The marketplace's current policy version and rules (changes when the platform updates them)."""
    return await _run(ctx, "get_policy", {}, lambda p: p.get_policy())


class Status(BaseModel):
    mode: str
    circuit: dict[str, Any]


@mcp.tool(annotations=READ, title="Marketplace status")
async def marketplace_status(ctx: Context | None = None) -> Status:
    """Which marketplace is connected and whether it is healthy (circuit breaker state)."""
    port, _ = _port(ctx)
    return Status(mode=port.name, circuit=gigsim_adapter.BREAKER.snapshot())


# --------------------------------------------------------------------------- write tools


class CreateDraftInput(BaseModel):
    proposal: ProposalPayload
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9:_\-.]+$",
                                 description="stable key for this exact draft, e.g. '<thread_id>:v<version>'")
    dry_run: bool = Field(False, description="true: return what would be created without creating it")


class DraftOutput(BaseModel):
    dry_run: bool
    replayed: bool = False
    draft: DraftResult | None = None
    would_send: dict[str, Any] | None = None


@mcp.tool(annotations=WRITE_DRAFT, title="Create proposal draft")
async def create_proposal_draft(inp: CreateDraftInput, ctx: Context | None = None) -> DraftOutput:
    """Create a proposal DRAFT for a job (spends no Connects). Only call after the human approved
    the text. Replays with the same idempotency_key return the original draft."""
    _, who = _port(ctx)
    args = inp.model_dump()
    if inp.dry_run:
        return DraftOutput(dry_run=True, would_send=inp.proposal.model_dump())
    if (prev := IDEM.get(who["user"], inp.idempotency_key, "create_proposal_draft", args)) is not None:
        return DraftOutput(**{**prev, "replayed": True})

    async def f(p):
        d = await p.create_proposal_draft(inp.proposal, inp.idempotency_key)
        return DraftOutput(dry_run=False, draft=d)

    out = await _run(ctx, "create_proposal_draft", args, f, write=True)
    IDEM.put(who["user"], inp.idempotency_key, "create_proposal_draft", args, out.model_dump())
    return out


class SubmitInput(BaseModel):
    proposal_id: str = Field(min_length=1, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9:_\-.]+$")
    dry_run: bool = Field(False, description="true: preview payload, Connects cost and balance after; spends nothing")
    approved_by: str = Field(min_length=1, max_length=64, description="id of the human who approved this exact submission")


class SubmitOutput(BaseModel):
    dry_run: bool
    replayed: bool = False
    preview: SubmitPreview | None = None
    result: SubmitResult | None = None


@mcp.tool(annotations=WRITE_SEND, title="Submit proposal (spends Connects)")
async def submit_proposal(inp: SubmitInput, ctx: Context | None = None) -> SubmitOutput:
    """Submit an approved draft. SPENDS CONNECTS. Use dry_run=true first and show the preview to
    the human; call for real only with their approval. Idempotent per idempotency_key."""
    _, who = _port(ctx)
    args = inp.model_dump()
    if inp.dry_run:
        return await _run(ctx, "submit_proposal(dry_run)", args,
                          lambda p: _wrap_preview(p.preview_submit(inp.proposal_id)))
    if (prev := IDEM.get(who["user"], inp.idempotency_key, "submit_proposal", args)) is not None:
        return SubmitOutput(**{**prev, "replayed": True})

    async def f(p):
        return SubmitOutput(dry_run=False, result=await p.submit_proposal(inp.proposal_id, inp.idempotency_key))

    out = await _run(ctx, "submit_proposal", args, f, write=True)
    IDEM.put(who["user"], inp.idempotency_key, "submit_proposal", args, out.model_dump())
    return out


async def _wrap_preview(coro) -> SubmitOutput:
    return SubmitOutput(dry_run=True, preview=await coro)


class SendMessageInput(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=5000)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9:_\-.]+$")
    dry_run: bool = False
    approved_by: str = Field(min_length=1, max_length=64)


class SendOutput(BaseModel):
    dry_run: bool
    replayed: bool = False
    would_send: dict[str, Any] | None = None
    message: Message | None = None


@mcp.tool(annotations=WRITE_SEND, title="Send message to client")
async def send_message(inp: SendMessageInput, ctx: Context | None = None) -> SendOutput:
    """Send an approved reply in a client conversation (on live Upwork this creates a draft the
    user confirms there). Idempotent per idempotency_key; dry_run previews the exact text."""
    _, who = _port(ctx)
    args = inp.model_dump()
    if inp.dry_run:
        return SendOutput(dry_run=True, would_send={"conversation_id": inp.conversation_id, "text": inp.text})
    if (prev := IDEM.get(who["user"], inp.idempotency_key, "send_message", args)) is not None:
        return SendOutput(**{**prev, "replayed": True})

    async def f(p):
        return SendOutput(dry_run=False, message=await p.send_message(inp.conversation_id, inp.text, inp.idempotency_key))

    out = await _run(ctx, "send_message", args, f, write=True)
    IDEM.put(who["user"], inp.idempotency_key, "send_message", args, out.model_dump())
    return out


if __name__ == "__main__":
    serve(mcp, int(os.getenv("MARKETPLACE_MCP_PORT", "8092")))
