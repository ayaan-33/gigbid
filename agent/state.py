"""Typed graph state (C2) with reducers wherever parallel branches write.

Three things are kept apart (and the report says so):
  * STATE            - what this job / conversation needs right now (this module)
  * EXECUTION TRACE  - every tool name, argument, result and observation: `tool_events` table +
                       Langfuse spans (agent/mcp_client.py records, agent/tracing.py persists)
  * LONG-TERM MEMORY - promoted knowledge only, in the LangGraph store (agent/memory/*), written
                       by explicit promotion rules; raw tool output never goes there
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

Status = Literal[
    "new", "analysing", "skipped", "watch", "drafting", "awaiting_approval", "approved", "submitted",
    "rejected", "blocked", "needs_attention", "dead_letter", "queued_degraded", "duplicate",
]


def merge_dicts(a: dict | None, b: dict | None) -> dict:
    out = dict(a or {})
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


def last(a: Any, b: Any) -> Any:
    return b if b is not None else a


class Usage(TypedDict, total=False):
    tokens: int
    cost_usd: float
    calls: int
    latency_s: float


class BidState(TypedDict, total=False):
    # identity
    thread_id: str
    user_id: str
    persona: str
    trace_id: str
    strategy: str  # proposal strategy arm (extension X2)
    # inputs
    job: dict[str, Any]
    client: dict[str, Any]
    # parallel analyses (each written by exactly one branch)
    job_spec: dict[str, Any]
    risk_report: dict[str, Any]
    fit_report: dict[str, Any]
    retrieval: dict[str, Any]  # per-requirement evidence + unsupported requirements (V8)
    evidence: Annotated[list[dict[str, Any]], operator.add]
    # decision + downstream
    decision: dict[str, Any]
    price_quote: dict[str, Any]
    draft: dict[str, Any]
    draft_history: Annotated[list[dict[str, Any]], operator.add]
    claim_report: dict[str, Any]
    critiques: Annotated[list[dict[str, Any]], operator.add]
    revision: int
    compliance: dict[str, Any]
    preview: dict[str, Any]
    approval: dict[str, Any]
    approvals: Annotated[list[dict[str, Any]], operator.add]
    submission: dict[str, Any]
    outcome: dict[str, Any]
    memory_applied: list[str]
    evidence_pack: dict[str, str]
    # user settings snapshot (taken when the thread starts)
    autonomy: str
    weekly_connects_budget: int
    connects_spent_this_week: int
    # control
    status: Annotated[str, last]
    status_reason: Annotated[str, last]
    steps: Annotated[int, operator.add]
    tokens: Annotated[int, operator.add]
    usage: Annotated[dict[str, Usage], merge_dicts]
    errors: Annotated[list[str], operator.add]
    timings: Annotated[dict[str, float], merge_dicts]


class ConvState(TypedDict, total=False):
    thread_id: str
    user_id: str
    persona: str
    trace_id: str
    conversation_id: str
    job_id: str | None
    proposal_id: str | None
    messages: list[dict[str, Any]]
    last_client_message: dict[str, Any]
    intent: dict[str, Any]
    slots: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    reply: dict[str, Any]
    compliance: dict[str, Any]
    approval: dict[str, Any]
    approvals: Annotated[list[dict[str, Any]], operator.add]
    sent: dict[str, Any]
    hold: dict[str, Any]
    pipeline_stage: str
    status: Annotated[str, last]
    status_reason: Annotated[str, last]
    steps: Annotated[int, operator.add]
    tokens: Annotated[int, operator.add]
    usage: Annotated[dict[str, Usage], merge_dicts]
    errors: Annotated[list[str], operator.add]
    timings: Annotated[dict[str, float], merge_dicts]
