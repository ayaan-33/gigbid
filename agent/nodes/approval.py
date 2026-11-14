"""Human-in-the-loop (C5) and the only code path that writes to the marketplace.

approval_gate: `interrupt()` with the full approval payload (draft, evidence behind every claim,
risk report, price rationale, dry_run preview). Resumed by the web UI with an ApprovalDecision:
  approve -> submit
  edit    -> edit diffed + recorded for style memory -> Compliance re-check -> submit if clean,
             otherwise back to the gate showing what Compliance changed
  reject  -> thread ends `rejected` with the reason (analytics: top rejection reasons)
There is no auto-send: even autonomy=auto_skip only skips low-fit jobs.

submit: create_proposal_draft + submit_proposal with idempotency keys derived from
(thread_id, draft version, text hash). If the API crashes after approval, the checkpoint resumes
here and the same keys make the submission happen exactly once.
"""

from __future__ import annotations

import hashlib

from langgraph.types import interrupt

from agent.handoffs import ApprovalAction, ApprovalDecision
from agent.nodes.base import node
from agent.nodes.common import tools


def _keys(state: dict) -> tuple[str, str]:
    d = state["draft"]
    h = hashlib.sha256(d["cover_letter"].encode()).hexdigest()[:10]
    t = state["thread_id"]
    return f"{t}:draft:v{d['version']}:{h}", f"{t}:submit:v{d['version']}:{h}"


async def build_preview(state: dict) -> dict:
    tb = tools("submitter", state)
    draft, q = state["draft"], state.get("price_quote") or {}
    payload = {"job_id": state["job"]["id"], "cover_letter": draft["cover_letter"],
               "bid_amount": q.get("amount") or draft.get("bid_amount") or 1, "bid_unit": q.get("unit", "fixed"),
               "screening_answers": [{"question": a["question"], "answer": a["answer"]} for a in draft.get("screening_answers", [])]}
    dk, sk = _keys(state)
    dry = await tb.call("create_proposal_draft", {"inp": {"proposal": payload, "idempotency_key": dk, "dry_run": True}})
    bal = await tb.call("get_connects_balance", {})
    cost = q.get("connects_cost", 0)
    return {"tool": "submit_proposal", "payload": dry.get("would_send") or payload, "connects_cost": cost,
            "connects_balance": bal.get("balance"), "connects_balance_after": (bal.get("balance") or 0) - cost,
            "idempotency_key": sk, "draft_idempotency_key": dk}


def approval_payload(state: dict, preview: dict) -> dict:
    claims = (state.get("claim_report") or {}).get("claims", [])
    return {
        "kind": "proposal",
        "thread_id": state["thread_id"],
        "job": {k: state["job"].get(k) for k in ("id", "title", "category", "budget", "connects_cost", "client_id")},
        "draft": state["draft"],
        "claims": [c for c in claims if c["label"] != "not_a_claim"],  # evidence behind every claim
        "evidence": state.get("evidence_pack") or {},
        "fit_report": state.get("fit_report"),
        "risk_report": state.get("risk_report"),
        "price_quote": state.get("price_quote"),
        "critiques": state.get("critiques", []),
        "compliance": state.get("compliance"),
        "decision": state.get("decision"),
        "dry_run": preview,
        "allowed_actions": ["approve", "edit", "reject"],
    }


@node("approval_gate")
async def approval_gate(state: dict) -> dict:
    preview = await build_preview(state)
    resume = interrupt(approval_payload(state, preview))
    decision = ApprovalDecision.model_validate(resume)
    rec = decision.model_dump(mode="json")
    out = {"approval": rec, "approvals": [rec], "preview": preview}
    if decision.action == ApprovalAction.reject:
        out.update(status="rejected", status_reason=f"rejected by user: {decision.reason or 'no reason given'}")
        await _log_rejection(state, decision.reason or "")
    elif decision.action == ApprovalAction.edit:
        if not decision.edited_text or len(decision.edited_text.strip()) < 50:
            out.update(status="awaiting_approval", status_reason="edit was empty; draft unchanged")
            out["approval"] = {**rec, "action": "invalid_edit"}
            return out
        await _record_edit(state, decision.edited_text)
        out.update(status="awaiting_approval", status_reason="user edited the draft; re-checking compliance")
    else:
        out.update(status="approved", status_reason=f"approved by {decision.user_id}")
    return out


async def _record_edit(state: dict, edited: str) -> None:
    try:
        from langgraph.config import get_store

        from agent.memory.store import record_edit

        await record_edit(get_store(), state.get("user_id", "local"), state["draft"]["cover_letter"], edited, state["thread_id"])
    except Exception:  # noqa: BLE001 - memory is best-effort; never block an approval
        pass


async def _log_rejection(state: dict, reason: str) -> None:
    try:
        import time

        from langgraph.config import get_store

        await get_store().aput(("events", state.get("user_id", "local"), "rejections"), state["thread_id"],
                               {"reason": reason, "job_id": state["job"]["id"], "category": state["job"].get("category"),
                                "at": time.time()})
    except Exception:  # noqa: BLE001
        pass


@node("apply_edit")
async def apply_edit(state: dict) -> dict:
    """Put the user's edited text into the draft (then Compliance re-checks it)."""
    draft = dict(state["draft"])
    draft["cover_letter"] = state["approval"]["edited_text"].strip()
    draft["version"] = draft["version"] + 1
    draft["edited_by_user"] = True
    return {"draft": draft, "draft_history": [{"version": draft["version"], "text": draft["cover_letter"], "by": "user"}]}


@node("submit")
async def submit(state: dict) -> dict:
    if (state.get("approval") or {}).get("action") not in ("approve", "edit"):
        return {"status": "needs_attention", "status_reason": "submit reached without an approval (refused)"}
    tb = tools("submitter", state)
    preview = state.get("preview") or await build_preview(state)
    dk, sk = _keys(state)
    d = await tb.call("create_proposal_draft", {"inp": {"proposal": preview["payload"] | {"cover_letter": state["draft"]["cover_letter"]},
                                                        "idempotency_key": dk}})
    pid = d["draft"]["proposal_id"]
    s = await tb.call("submit_proposal", {"inp": {"proposal_id": pid, "idempotency_key": sk,
                                                  "approved_by": state["approval"]["user_id"]}})
    result = s.get("result") or {}
    status = "submitted"
    reason = f"submitted; {result.get('connects_spent', 0)} Connects spent"
    if result.get("requires_confirmation_on_marketplace"):
        reason = "draft created on Upwork: confirm it there to send"
    draft = {**state["draft"], "status": "submitted"}
    return {"submission": {"proposal_id": pid, **result, "replayed": s.get("replayed", False)}, "status": status,
            "status_reason": reason, "draft": draft}
