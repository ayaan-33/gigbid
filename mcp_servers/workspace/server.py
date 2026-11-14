"""GigBid Workspace MCP server: calendar free slots, tentative interview holds, email drafts.

Backed by a local mock (SQLite, `store.py`). A Google Calendar/Gmail backend can implement the same
store interface; the agent sees MCP tools only either way.

Run:  uv run python -m mcp_servers.workspace.server        # :8093/mcp, bearer auth
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field, field_validator

from agent.settings import ROOT
from mcp_servers.common import AuditLog, caller, serve
from mcp_servers.workspace.store import WorkspaceStore

mcp = FastMCP("gigbid-workspace", instructions="Calendar availability, tentative interview holds and email drafts "
              "for the freelancer. Holds and drafts are created only after the human approved them.",
              port=int(os.getenv("WORKSPACE_MCP_PORT", "8093")))
STORE = WorkspaceStore(Path(os.getenv("WORKSPACE_DB", ROOT / ".cache" / "workspace.sqlite")))
AUDIT = AuditLog(Path(os.getenv("WORKSPACE_AUDIT_LOG", ROOT / ".cache" / "audit" / "workspace.jsonl")))

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)


class Slot(BaseModel):
    start: datetime
    end: datetime
    tz: str = "UTC"


class SlotList(BaseModel):
    slots: list[Slot]


@mcp.tool(annotations=READ, title="Find free calendar slots")
def find_free_slots(duration_min: int = Field(30, ge=15, le=240), days_ahead: int = Field(5, ge=1, le=21),
                    work_start_hour: int = Field(9, ge=0, le=23), work_end_hour: int = Field(17, ge=1, le=24),
                    max_slots: int = Field(3, ge=1, le=10), ctx: Context | None = None) -> SlotList:
    """Free slots in the freelancer's calendar over the next `days_ahead` working days (UTC)."""
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    who = caller(ctx)
    slots = STORE.free_slots(who["user"], now, days_ahead, duration_min, work_start_hour, work_end_hour, max_slots)
    return SlotList(slots=[Slot(start=a, end=b) for a, b in slots])


class HoldInput(BaseModel):
    start: datetime
    end: datetime
    title: str = Field(min_length=3, max_length=120)
    idempotency_key: str = Field(min_length=8, max_length=128)

    @field_validator("end")
    @classmethod
    def _after(cls, v, info):
        if "start" in info.data and v <= info.data["start"]:
            raise ValueError("end must be after start")
        return v


class Hold(BaseModel):
    id: str
    start: str
    end: str
    title: str
    replayed: bool


@mcp.tool(annotations=WRITE, title="Create tentative interview hold")
def create_interview_hold(inp: HoldInput, ctx: Context | None = None) -> Hold:
    """Block a tentative calendar slot for a client interview (after the human approved the reply)."""
    who = caller(ctx)
    out = STORE.hold(who["user"], inp.start, inp.end, inp.title, inp.idempotency_key)
    AUDIT.write(user=who["user"], tool="create_interview_hold", arguments=inp.model_dump(), result=out,
                trace_id=who["trace_id"], server=mcp.name)
    return Hold(**out)


class EmailDraftInput(BaseModel):
    to_label: str = Field(min_length=1, max_length=120, description="recipient label (no address stored)")
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=8000)
    idempotency_key: str = Field(min_length=8, max_length=128)


class EmailDraft(BaseModel):
    id: str
    replayed: bool


@mcp.tool(annotations=WRITE, title="Create email draft")
def create_email_draft(inp: EmailDraftInput, ctx: Context | None = None) -> EmailDraft:
    """Save an email DRAFT (never sends). Used for interview confirmations and follow-ups."""
    who = caller(ctx)
    out = STORE.draft(who["user"], inp.to_label, inp.subject, inp.body, inp.idempotency_key)
    AUDIT.write(user=who["user"], tool="create_email_draft", arguments=inp.model_dump(), result=out,
                trace_id=who["trace_id"], server=mcp.name)
    return EmailDraft(**out)


if __name__ == "__main__":
    serve(mcp, int(os.getenv("WORKSPACE_MCP_PORT", "8093")))
