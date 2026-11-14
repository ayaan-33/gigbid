"""Structured hand-offs between agents (C3). Anything a later step decides on is one of these
Pydantic objects, never free text."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- job analysis


class Requirement(BaseModel):
    id: str = Field(description="short stable id, e.g. r1")
    text: str = Field(description="one atomic requirement in plain words")
    kind: Literal["skill", "deliverable", "domain", "constraint", "soft"] = "skill"
    must_have: bool = True


class JobSpec(BaseModel):
    job_id: str
    title: str
    category: str = "other"
    summary: str = ""
    deliverables: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    requirements: list[Requirement] = Field(default_factory=list)
    budget_type: Literal["fixed", "hourly", "unknown"] = "unknown"
    budget_min: float | None = None
    budget_max: float | None = None
    timeline_days: int | None = None
    screening_questions: list[str] = Field(default_factory=list)
    hidden_needs: list[str] = Field(
        default_factory=list, description="needs implied but not stated by the client"
    )
    experience_level: Literal["entry", "intermediate", "expert", "unknown"] = "unknown"


class RiskFlag(StrEnum):
    off_platform_contact = "off_platform_contact"
    off_platform_payment = "off_platform_payment"
    unpaid_work = "unpaid_work"
    prompt_injection = "prompt_injection"
    unverified_payment = "unverified_payment"
    poor_client_history = "poor_client_history"
    unrealistic_budget = "unrealistic_budget"
    vague_scope = "vague_scope"
    duplicate = "duplicate"
    credential_request = "credential_request"
    other = "other"


class RiskReport(BaseModel):
    score: float = Field(ge=0, le=1, description="0 = safe, 1 = certainly harmful")
    client_quality: float = Field(ge=0, le=1, default=0.5)
    is_scam: bool = False
    flags: list[RiskFlag] = Field(default_factory=list)
    injection_detected: bool = False
    injected_text: str | None = None
    explanation: str = ""


class EvidenceRef(BaseModel):
    evidence_id: str
    title: str = ""
    type: str = ""
    snippet: str = ""
    score: float = 0.0
    outcome: str | None = None


class RequirementMatch(BaseModel):
    requirement_id: str
    requirement: str
    evidence: list[EvidenceRef] = Field(default_factory=list)
    strength: Literal["strong", "partial", "none"] = "none"
    reason: str = ""


class FitReport(BaseModel):
    score: float = Field(ge=0, le=1)
    matches: list[RequirementMatch] = Field(default_factory=list)
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)

    @property
    def evidence_ids(self) -> list[str]:
        seen: list[str] = []
        for m in self.matches:
            for e in m.evidence:
                if e.evidence_id not in seen:
                    seen.append(e.evidence_id)
        return seen


class BidDecision(BaseModel):
    action: Literal["bid", "watch", "skip"]
    confidence: float = Field(ge=0, le=1, default=0.5)
    reasons: list[str] = Field(default_factory=list)
    decided_by: Literal["rules", "llm", "user"] = "rules"


class PriceQuote(BaseModel):
    amount: float = Field(gt=0)
    unit: Literal["fixed", "hourly"] = "fixed"
    currency: str = "USD"
    market_p25: float | None = None
    market_median: float | None = None
    market_p75: float | None = None
    user_floor: float | None = None
    connects_cost: int = 0
    expected_win_prob: float = Field(ge=0, le=1, default=0.1)
    connects_worth_it: bool = True
    rationale: str = ""


# --------------------------------------------------------------------------- proposal


class Citation(BaseModel):
    sentence_index: int
    evidence_ids: list[str]


class ScreeningAnswer(BaseModel):
    question: str
    answer: str
    evidence_ids: list[str] = Field(default_factory=list)


class ProposalDraft(BaseModel):
    job_id: str
    version: int = 1
    cover_letter: str
    screening_answers: list[ScreeningAnswer] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    bid_amount: float | None = None
    strategy: str = "default"  # A/B arm for extension X2
    status: Literal["drafting", "pending_review", "approved", "rejected", "submitted"] = "drafting"

    @property
    def evidence_ids(self) -> list[str]:
        return sorted({e for c in self.citations for e in c.evidence_ids})


class ClaimLabel(StrEnum):
    supported = "supported"
    partly_supported = "partly_supported"
    unsupported = "unsupported"
    not_a_claim = "not_a_claim"


class Claim(BaseModel):
    text: str
    label: ClaimLabel
    evidence_ids: list[str] = Field(default_factory=list)
    reason: str = ""
    action: Literal["kept", "rewritten", "removed"] = "kept"
    rewritten: str | None = None


class ClaimReport(BaseModel):
    claims: list[Claim] = Field(default_factory=list)
    unsupported_before: int = 0
    unsupported_after: int = 0
    total_claims: int = 0

    @property
    def supported_ratio(self) -> float:
        real = [c for c in self.claims if c.label != ClaimLabel.not_a_claim]
        if not real:
            return 1.0
        ok = sum(1 for c in real if c.label != ClaimLabel.unsupported or c.action != "kept")
        return ok / len(real)


class CritiqueIssue(BaseModel):
    kind: Literal["grounding", "personalisation", "length", "tone", "screening", "generic_opening"]
    detail: str
    sentence: str | None = None


class Critique(BaseModel):
    passed: bool
    score: float = Field(ge=0, le=10, default=5)
    issues: list[CritiqueIssue] = Field(default_factory=list)
    instructions: str = ""


class ComplianceViolation(BaseModel):
    rule: str
    excerpt: str
    fix: Literal["removed", "rewritten", "blocked"]


class ComplianceVerdict(BaseModel):
    allowed: bool
    blocked_reason: str | None = None
    violations: list[ComplianceViolation] = Field(default_factory=list)
    cleaned_text: str | None = None
    policy_version: int = 1


# --------------------------------------------------------------------------- approval


class ApprovalAction(StrEnum):
    approve = "approve"
    edit = "edit"
    reject = "reject"


class ApprovalDecision(BaseModel):
    action: ApprovalAction
    edited_text: str | None = None
    reason: str | None = None
    user_id: str
    decided_at: datetime = Field(default_factory=datetime.utcnow)


class DryRunPreview(BaseModel):
    tool: str
    payload: dict
    connects_cost: int = 0
    connects_balance_after: int | None = None
    idempotency_key: str


# --------------------------------------------------------------------------- conversation


class Intent(StrEnum):
    question = "question"
    negotiation = "negotiation"
    interview_request = "interview_request"
    scam_signal = "scam_signal"
    acceptance = "acceptance"
    rejection = "rejection"
    other = "other"


class IntentClassification(BaseModel):
    intent: Intent
    confidence: float = Field(ge=0, le=1, default=0.5)
    injection_detected: bool = False
    summary: str = ""


class InterviewSlot(BaseModel):
    start: datetime
    end: datetime
    tz: str = "UTC"


class ReplyDraft(BaseModel):
    conversation_id: str
    text: str
    proposed_slots: list[InterviewSlot] = Field(default_factory=list)
    counter_rate: float | None = None
    evidence_ids: list[str] = Field(default_factory=list)
