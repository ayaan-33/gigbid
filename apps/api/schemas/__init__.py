"""Request/response models for the typed API contract (TypeScript client is generated from these)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    name: str = Field(min_length=1, max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    persona: str
    onboarded: bool


class OnboardingIn(BaseModel):
    persona: Literal["ai_ml_engineer", "fullstack_dev", "data_analyst", "own_profile"]
    hourly_rate: float | None = Field(None, gt=0, le=1000)
    fixed_floor: float | None = Field(None, gt=0, le=100000)
    weekly_connects_budget: int = Field(80, ge=0, le=1000)
    marketplace_mode: Literal["gigsim", "upwork_live"] = "gigsim"
    saved_search: str | None = Field(None, max_length=200)
    category: str | None = None


class SettingsOut(BaseModel):
    autonomy: Literal["suggest", "auto_skip"] = "suggest"
    weekly_connects_budget: int = 80
    hourly_rate: float | None = None
    fixed_floor: float | None = None
    marketplace_mode: str = "gigsim"
    strategy_mode: str = "ab_test"
    connects_spent_this_week: int = 0
    persona: str = "ai_ml_engineer"


class SettingsIn(BaseModel):
    autonomy: Literal["suggest", "auto_skip"] | None = None
    weekly_connects_budget: int | None = Field(None, ge=0, le=1000)
    hourly_rate: float | None = Field(None, gt=0, le=1000)
    fixed_floor: float | None = Field(None, gt=0, le=100000)
    strategy_mode: Literal["ab_test", "default", "evidence_first", "question_led"] | None = None


class SavedSearchIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    query: str = Field("", max_length=200)
    category: str | None = None
    skills: list[str] = Field(default_factory=list, max_length=10)
    interval_minutes: int = Field(30, ge=15, le=1440)
    enabled: bool = True


class SavedSearchOut(SavedSearchIn):
    id: str
    last_run_at: datetime | None = None


class JobCard(BaseModel):
    job_id: str
    title: str
    category: str | None
    status: str
    action: str | None = None
    fit: float | None = None
    risk: float | None = None
    is_scam: bool = False
    injection: bool = False
    price: float | None = None
    connects_cost: int | None = None
    budget: dict[str, Any] | None = None
    discovered_at: datetime | None = None
    thread_id: str | None = None
    reasons: list[str] = Field(default_factory=list)


class JobDetail(JobCard):
    job: dict[str, Any]
    job_spec: dict[str, Any] | None = None
    risk_report: dict[str, Any] | None = None
    fit_report: dict[str, Any] | None = None
    decision: dict[str, Any] | None = None
    price_quote: dict[str, Any] | None = None
    status_reason: str | None = None


class ApprovalIn(BaseModel):
    action: Literal["approve", "edit", "reject"]
    edited_text: str | None = Field(None, max_length=6000)
    reason: str | None = Field(None, max_length=500)


class RegenerateIn(BaseModel):
    paragraph_index: int = Field(ge=0, le=20)
    instruction: str | None = Field(None, max_length=300)


class ThreadOut(BaseModel):
    thread_id: str
    kind: str
    job_id: str | None
    conversation_id: str | None
    status: str
    status_reason: str | None
    strategy: str | None
    tokens: int
    cost_usd: float
    latency_s: float
    created_at: datetime | None
    updated_at: datetime | None
    trace_url: str | None = None


class PendingApproval(BaseModel):
    thread_id: str
    kind: str
    payload: dict[str, Any]


class PipelineCard(BaseModel):
    proposal_id: str
    job_id: str | None
    title: str | None
    category: str | None
    stage: str
    strategy: str | None
    connects_spent: int
    conversation_id: str | None
    thread_id: str | None
    updated_at: datetime | None


class ConversationOut(BaseModel):
    conversation_id: str
    job_id: str | None
    proposal_id: str | None
    state: str
    thread_id: str | None
    messages: list[dict[str, Any]] = Field(default_factory=list)
    pending: dict[str, Any] | None = None


class MemoryItem(BaseModel):
    kind: str
    key: str
    rule: str
    support: int | None = None
    window: int | None = None
    reply_rate: float | None = None
    baseline: float | None = None


class StatusOut(BaseModel):
    marketplace: str
    marketplace_mode: str
    circuit: dict[str, Any] = Field(default_factory=dict)
    queued_threads: int = 0
    message: str | None = None


class AnalyticsOut(BaseModel):
    by_category: list[dict[str, Any]]
    by_strategy: list[dict[str, Any]]
    connects: dict[str, Any]
    cost_latency: dict[str, Any]
    rejection_reasons: list[dict[str, Any]]
    funnel: dict[str, int]
