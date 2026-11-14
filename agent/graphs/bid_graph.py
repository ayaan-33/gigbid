"""Bid graph (C1): one thread per job. Hand-written LangGraph StateGraph.

  ingest ──Send──► job_analyst ─┐
         ├─Send──► risk_assessor ┼─► decide ─bid─► pricing ─worth─► writer ► verifier ► critic ─┐
         └─Send──► fit_matcher ─┘      │skip/watch          │not worth            ▲  revise≤2 │
                                       ▼                    ▼                     └───────────┘
                                      END                  END (watch)      compliance ─blocked─► END
                                                                                 │
                                         apply_edit ◄─edit── approval_gate ◄─────┘   (interrupt)
                                             │                 │approve        │reject
                                             └─► compliance    ▼               ▼
                                                             submit ──► END   END
"""

from __future__ import annotations

import hashlib
import re
import time

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from agent.nodes.analysts import fit_matcher, job_analyst, risk_assessor
from agent.nodes.approval import apply_edit, approval_gate, submit
from agent.nodes.base import TERMINAL, node
from agent.nodes.common import tools
from agent.nodes.decide_price import decide, price
from agent.nodes.proposal import compliance, critic, verifier, writer
from agent.settings import cfg
from agent.state import BidState


def job_fingerprint(job: dict) -> str:
    norm = re.sub(r"\W+", " ", f"{job.get('title', '')} {job.get('description', '')[:400]}".lower()).strip()
    norm = norm.replace(" re posted", "")
    return hashlib.sha1(norm.encode()).hexdigest()[:16]


@node("ingest")
async def ingest(state: dict) -> dict:
    """Scout hand-off: load the full job via MCP if needed and de-duplicate by fingerprint."""
    job = state.get("job") or {}
    if not job.get("description"):
        job = await tools("scout", state).call("get_job", {"job_id": job["id"]})
    out = {"job": job, "status": "analysing", "status_reason": "analysing job"}
    try:
        from langgraph.config import get_store

        store = get_store()
        ns = ("events", state.get("user_id", "local"), "seen_jobs")
        fp = job_fingerprint(job)
        seen = await store.aget(ns, fp)
        if seen and seen.value.get("job_id") != job["id"]:
            return {"job": job, "status": "duplicate", "status_reason": f"duplicate of {seen.value['job_id']}"}
        await store.aput(ns, fp, {"job_id": job["id"], "at": time.time()})
    except Exception:  # noqa: BLE001 - no store configured (e.g. a bare unit test)
        pass
    return out


def fan_out(state: dict):
    if state.get("status") in TERMINAL:
        return END
    return [Send("job_analyst", state), Send("risk_assessor", state), Send("fit_matcher", state)]


def after_decide(state: dict) -> str:
    return "pricing" if (state.get("decision") or {}).get("action") == "bid" and state.get("status") not in TERMINAL else END


def after_pricing(state: dict) -> str:
    if state.get("status") in TERMINAL:
        return END
    return "writer" if (state.get("price_quote") or {}).get("connects_worth_it", True) else "not_worth"


@node("not_worth")
async def not_worth(state: dict) -> dict:
    return {"status": "watch", "status_reason": "Connects cost not worth it: " + state["price_quote"]["rationale"]}


def after_critic(state: dict) -> str:
    if state.get("status") in TERMINAL:
        return END
    last = (state.get("critiques") or [{}])[-1]
    # critic increments `revision` only when it sends the draft back (bounded by max_revisions)
    sent_back = not last.get("passed", True) and state.get("revision", 0) > len(
        [h for h in state.get("draft_history", []) if h["by"] == "writer"]) - 1
    return "writer" if sent_back else "compliance"


def after_compliance(state: dict) -> str:
    if state.get("status") in TERMINAL:
        return END
    a = state.get("approval") or {}
    # an edit that Compliance did not change needs no second approval: the user approved their own text
    if a.get("action") == "edit" and (state.get("draft") or {}).get("edited_by_user"):
        changed = [v for v in (state.get("compliance") or {}).get("violations", []) if v.get("fix") != "kept"]
        if not changed:
            return "submit"
    return "approval_gate"


def after_approval(state: dict) -> str:
    a = (state.get("approval") or {}).get("action")
    if state.get("status") == "rejected":
        return END
    if a == "edit":
        return "apply_edit"
    if a == "approve":
        return "submit"
    return "approval_gate"


@node("mark_awaiting")
async def mark_awaiting(state: dict) -> dict:
    return {"status": "awaiting_approval", "status_reason": "waiting for your approval"}


def _ok(nxt: str):
    return lambda s: END if s.get("status") in TERMINAL else nxt


def build_bid_graph(checkpointer=None, store=None):
    g = StateGraph(BidState)
    g.add_node("ingest", ingest)
    g.add_node("job_analyst", job_analyst)
    g.add_node("risk_assessor", risk_assessor)
    g.add_node("fit_matcher", fit_matcher)
    g.add_node("decide", decide, defer=True)  # waits for all three parallel branches
    g.add_node("pricing", price)
    g.add_node("not_worth", not_worth)
    g.add_node("writer", writer)
    g.add_node("verifier", verifier)
    g.add_node("critic", critic)
    g.add_node("compliance", compliance)
    g.add_node("mark_awaiting", mark_awaiting)
    g.add_node("approval_gate", approval_gate)
    g.add_node("apply_edit", apply_edit)
    g.add_node("submit", submit)

    g.add_edge(START, "ingest")
    g.add_conditional_edges("ingest", fan_out, ["job_analyst", "risk_assessor", "fit_matcher", END])
    for n in ("job_analyst", "risk_assessor", "fit_matcher"):
        g.add_edge(n, "decide")
    g.add_conditional_edges("decide", after_decide, {"pricing": "pricing", END: END})
    g.add_conditional_edges("pricing", after_pricing, {"writer": "writer", "not_worth": "not_worth", END: END})
    g.add_edge("not_worth", END)
    g.add_conditional_edges("writer", _ok("verifier"), ["verifier", END])
    g.add_conditional_edges("verifier", _ok("critic"), ["critic", END])
    g.add_conditional_edges("critic", after_critic, {"writer": "writer", "compliance": "compliance", END: END})
    g.add_conditional_edges("compliance", after_compliance,
                            {"approval_gate": "mark_awaiting", "submit": "submit", END: END})
    g.add_edge("mark_awaiting", "approval_gate")
    g.add_conditional_edges("approval_gate", after_approval,
                            {"apply_edit": "apply_edit", "submit": "submit", "approval_gate": "approval_gate", END: END})
    g.add_conditional_edges("apply_edit", _ok("compliance"), ["compliance", END])
    g.add_edge("submit", END)
    return g.compile(checkpointer=checkpointer, store=store, name="bid_graph")


def initial_state(job: dict, *, user_id: str, persona: str, thread_id: str, strategy: str | None = None,
                  settings: dict | None = None) -> dict:
    s = settings or {}
    return {"job": job, "user_id": user_id, "persona": persona, "thread_id": thread_id, "trace_id": thread_id,
            "strategy": strategy or s.get("strategy") or "default", "status": "new", "revision": 0,
            "autonomy": s.get("autonomy", cfg("autonomy.default_level", "suggest")),
            "weekly_connects_budget": s.get("weekly_connects_budget", cfg("connects.weekly_budget_default", 80)),
            "connects_spent_this_week": s.get("connects_spent_this_week", 0)}
