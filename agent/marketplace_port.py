"""R1: the single marketplace port. Everything that touches a marketplace goes through this
interface; two adapters implement it and config (`marketplace.mode`) picks one:

  * mcp_servers/marketplace/adapters/gigsim.py       -> GigSim REST simulator
  * mcp_servers/marketplace/adapters/upwork_live.py  -> official Upwork MCP server (OAuth 2.1)

Agents never import this module directly: they call the Marketplace MCP server's tools, and that
server is the only consumer of the port. So the graph cannot tell which marketplace is behind it.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- normalised models


class Budget(BaseModel):
    type: Literal["fixed", "hourly"] = "fixed"
    min: float | None = None
    max: float | None = None
    currency: str = "USD"


class Job(BaseModel):
    id: str
    title: str
    description: str
    category: str = "other"
    skills: list[str] = Field(default_factory=list)
    budget: Budget = Field(default_factory=Budget)
    duration_days: int | None = None
    experience_level: str | None = None
    screening_questions: list[str] = Field(default_factory=list)
    connects_cost: int = 0
    proposals_count: int = 0
    client_id: str | None = None
    posted_at: float | None = None
    status: str = "open"
    marketplace: str = "gigsim"


class ClientHistory(BaseModel):
    id: str
    name: str | None = None
    country: str | None = None
    payment_verified: bool = False
    total_spent: float = 0
    hires: int = 0
    jobs_posted: int = 0
    avg_rating_given: float | None = None
    member_since: str | None = None
    reviews: list[str] = Field(default_factory=list)


class ConnectsBalance(BaseModel):
    balance: int
    ledger: list[dict[str, Any]] = Field(default_factory=list)


class ProposalPayload(BaseModel):
    job_id: str
    cover_letter: str = Field(min_length=50, max_length=5000)
    bid_amount: float = Field(gt=0, le=1_000_000)
    bid_unit: Literal["fixed", "hourly"] = "fixed"
    screening_answers: list[dict[str, str]] = Field(default_factory=list, max_length=10)


class DraftResult(BaseModel):
    proposal_id: str
    status: str
    job_id: str


class SubmitPreview(BaseModel):
    proposal_id: str
    job_id: str
    connects_cost: int
    balance_before: int
    balance_after: int
    policy_version: int
    policy_problems: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)


class SubmitResult(BaseModel):
    proposal_id: str
    status: str
    connects_spent: int = 0
    balance_after: int | None = None
    requires_confirmation_on_marketplace: bool = False  # live Upwork: user confirms on Upwork


class Message(BaseModel):
    id: str
    sender: Literal["client", "freelancer", "system"]
    text: str
    at: float


class Conversation(BaseModel):
    id: str
    client_id: str
    job_id: str | None = None
    proposal_id: str | None = None
    state: str = "open"
    last_message: Message | None = None


class MarketEvent(BaseModel):
    id: int
    type: str
    ref: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    at: float


class MarketStats(BaseModel):
    category: str | None = None
    budget_type: str = "fixed"
    n: int = 0
    p10: float | None = None
    p25: float | None = None
    median: float | None = None
    p75: float | None = None
    p90: float | None = None


class Policy(BaseModel):
    version: int
    effective: str | None = None
    rules: list[str] = Field(default_factory=list)
    connects_surcharge: dict[str, Any] | None = None
    require_ai_disclosure: bool = False


# --------------------------------------------------------------------------- errors


class MarketplaceError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class MarketplaceUnavailable(MarketplaceError):
    """Upstream down or circuit open: callers switch to degraded mode and queue work."""


class PolicyViolation(MarketplaceError):
    def __init__(self, problems: list[str]):
        super().__init__(f"policy violation: {problems}", status=422)
        self.problems = problems


# --------------------------------------------------------------------------- the port


@runtime_checkable
class MarketplacePort(Protocol):
    name: str

    async def search_jobs(self, query: str = "", *, category: str | None = None, skills: list[str] | None = None,
                          posted_after: float | None = None, limit: int = 20, cursor: int = 0) -> tuple[list[Job], int | None]: ...

    async def get_job(self, job_id: str) -> Job: ...

    async def get_client_history(self, client_id: str) -> ClientHistory: ...

    async def get_connects_balance(self) -> ConnectsBalance: ...

    async def list_conversations(self) -> list[Conversation]: ...

    async def list_messages(self, conversation_id: str) -> list[Message]: ...

    async def list_events(self, since_id: int = 0) -> list[MarketEvent]: ...

    async def market_stats(self, category: str | None, budget_type: str = "fixed") -> MarketStats: ...

    async def get_policy(self) -> Policy: ...

    async def create_proposal_draft(self, payload: ProposalPayload, idempotency_key: str) -> DraftResult: ...

    async def preview_submit(self, proposal_id: str) -> SubmitPreview: ...

    async def submit_proposal(self, proposal_id: str, idempotency_key: str) -> SubmitResult: ...

    async def send_message(self, conversation_id: str, text: str, idempotency_key: str) -> Message: ...

    async def aclose(self) -> None: ...


def make_port(mode: str | None = None, *, user_token: str | None = None, user_id: str | None = None) -> MarketplacePort:
    """Factory used by the Marketplace MCP server. `mode` defaults to config."""
    from agent.settings import cfg

    mode = mode or cfg("marketplace.mode", "gigsim")
    if mode == "gigsim":
        from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter

        return GigSimAdapter(token=user_token)
    if mode == "upwork_live":
        from mcp_servers.marketplace.adapters.upwork_live import UpworkLiveAdapter

        return UpworkLiveAdapter(user_id=user_id or "local")
    raise ValueError(f"unknown marketplace mode {mode!r}")
