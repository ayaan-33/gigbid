"""Conversation graph (C1): one thread per client conversation.

  load ─► classify ─┬ interview_request ─► find_slots ─┐
                    ├ question / negotiation ─────────┼► draft_reply ► check ─► approval (interrupt)
                    ├ scam_signal ────────────────────┘                          │approve/edit  │reject
                    └ acceptance / rejection ─► update_pipeline ─► END          ▼              ▼
                                                                         send (+hold) ─► END  END
Client messages are untrusted: they are spotlighted, checked for injection, and the reply always
passes the Compliance Guard; nothing is sent without approval.
"""

from __future__ import annotations

import hashlib

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agent import llm
from agent.guardrails import spotlight
from agent.handoffs import ApprovalAction, ApprovalDecision, Intent, IntentClassification
from agent.llm import structured
from agent.nodes.base import TERMINAL, node
from agent.nodes.common import detect_injection, profile, tools
from agent.nodes.proposal import rule_compliance
from agent.prompts import load_prompt
from agent.state import ConvState

SCAM_WORDS = ("telegram", "whatsapp", "crypto", "gift card", "outside the platform", "outside upwork", "wire",
              "your email", "your phone", "personal email", "bank details")


@node("liaison_load", budget_key="max_tokens_per_conversation_turn")
async def load(state: dict) -> dict:
    tb = tools("client_liaison", state)
    msgs = (await tb.call("list_messages", {"conversation_id": state["conversation_id"]}))["messages"]
    last_client = next((m for m in reversed(msgs) if m["sender"] == "client"), None)
    return {"messages": msgs, "last_client_message": last_client or {}, "status": "analysing"}


@node("intent", budget_key="max_tokens_per_conversation_turn")
async def classify(state: dict) -> dict:
    msg = (state.get("last_client_message") or {}).get("text", "")
    injected, excerpt, _ = await detect_injection(msg)
    low = msg.lower()
    if any(w in low for w in SCAM_WORDS):
        ic = IntentClassification(intent=Intent.scam_signal, confidence=0.9, summary="asks to leave the platform / share details")
    else:
        p = load_prompt("intent")
        try:
            ic = await structured("intent", p.text, spotlight("client_message", msg), IntentClassification)
        except Exception:  # noqa: BLE001
            ic = IntentClassification(intent=Intent.other, confidence=0.3, summary="classifier unavailable")
    ic.injection_detected = ic.injection_detected or injected
    out = {"intent": ic.model_dump(mode="json")}
    if injected:
        out["errors"] = [f"injection attempt ignored: {excerpt}"]
    return out


def route_intent(state: dict) -> str:
    it = (state.get("intent") or {}).get("intent")
    if it == "interview_request":
        return "find_slots"
    if it in ("acceptance", "rejection"):
        return "update_pipeline"
    return "draft_reply"


@node("find_slots", budget_key="max_tokens_per_conversation_turn")
async def find_slots(state: dict) -> dict:
    slots = (await tools("client_liaison", state).call("find_free_slots", {"duration_min": 30, "days_ahead": 5, "max_slots": 3}))["slots"]
    return {"slots": slots}


@node("client_liaison", budget_key="max_tokens_per_conversation_turn")
async def draft_reply(state: dict) -> dict:
    persona = profile(state["persona"])
    msg = (state.get("last_client_message") or {}).get("text", "")
    intent = (state.get("intent") or {}).get("intent", "other")
    evidence = []
    if intent == "question":
        try:
            res = await tools("client_liaison", state).call("search_evidence", {"requirement": msg[:500], "k": 3})
            evidence = [{"id": i["id"], "snippet": i["snippet"][:400]} for i in res["items"]]
        except Exception:  # noqa: BLE001
            evidence = []
    slots = "; ".join(f"{s['start'][:16].replace('T', ' ')}" for s in state.get("slots", [])) or "n/a"
    floor = persona["hourly_rate"]
    p = load_prompt("client_liaison")
    system = p.render(persona_name=persona["name"], headline=persona.get("headline", ""), voice=persona.get("voice", ""),
                      intent=intent, slots=slots, floor=f"${floor}/hr")
    history = "\n".join(f"{m['sender']}: {m['text'][:300]}" for m in (state.get("messages") or [])[-6:])
    user = (f"CONVERSATION SO FAR (oldest first):\n{history}\n\nEVIDENCE: {evidence}\n\n" + spotlight("client_message", msg))
    text = (await llm.complete("client_liaison", system, user, max_tokens=400)).strip()
    if "</think>" in text:
        text = text.split("</think>")[-1].strip()
    if state.get("slots") and not any(s["start"][:10] in text for s in state["slots"]):
        text += "\n\nProposed times (UTC): " + "; ".join(s["start"][:16].replace("T", " ") for s in state["slots"])
    return {"reply": {"conversation_id": state["conversation_id"], "text": text, "proposed_slots": state.get("slots", []),
                      "evidence_ids": [e["id"] for e in evidence]}, "evidence": evidence}


@node("reply_compliance", budget_key="max_tokens_per_conversation_turn")
async def check(state: dict) -> dict:
    text = (state.get("approval") or {}).get("edited_text") or state["reply"]["text"]
    cleaned, violations, blocked = rule_compliance(text)
    reply = {**state["reply"], "text": cleaned}
    out = {"reply": reply, "compliance": {"allowed": not blocked, "violations": [v.model_dump() for v in violations]}}
    if blocked:
        out.update(status="blocked", status_reason="reply would move the conversation off-platform")
    else:
        out.update(status="awaiting_approval", status_reason="reply waiting for your approval")
    return out


@node("reply_approval", budget_key="max_tokens_per_conversation_turn")
async def approval(state: dict) -> dict:
    resume = interrupt({"kind": "message", "thread_id": state["thread_id"], "conversation_id": state["conversation_id"],
                        "client_message": state.get("last_client_message"), "intent": state.get("intent"),
                        "reply": state["reply"], "compliance": state.get("compliance"), "evidence": state.get("evidence", []),
                        "dry_run": {"tool": "send_message", "payload": {"conversation_id": state["conversation_id"],
                                                                        "text": state["reply"]["text"]},
                                    "also": "tentative calendar hold for the first slot the client picks" if state.get("slots") else None},
                        "allowed_actions": ["approve", "edit", "reject"]})
    d = ApprovalDecision.model_validate(resume)
    rec = d.model_dump(mode="json")
    if d.action == ApprovalAction.reject:
        return {"approval": rec, "approvals": [rec], "status": "rejected", "status_reason": d.reason or "reply rejected"}
    if d.action == ApprovalAction.edit and d.edited_text:
        cleaned, violations, blocked = rule_compliance(d.edited_text)
        if blocked or violations:
            return {"approval": {**rec, "action": "recheck"}, "approvals": [rec], "reply": {**state["reply"], "text": cleaned},
                    "compliance": {"allowed": not blocked, "violations": [v.model_dump() for v in violations]},
                    "status": "awaiting_approval", "status_reason": "your edit was cleaned by Compliance; please re-approve"}
        return {"approval": rec, "approvals": [rec], "reply": {**state["reply"], "text": d.edited_text}, "status": "approved"}
    return {"approval": rec, "approvals": [rec], "status": "approved"}


def after_approval(state: dict) -> str:
    if state.get("status") == "rejected":
        return END
    if (state.get("approval") or {}).get("action") == "recheck":
        return "reply_approval"
    return "send"


@node("send", budget_key="max_tokens_per_conversation_turn")
async def send(state: dict) -> dict:
    tb = tools("client_liaison", state)
    text = state["reply"]["text"]
    key = f"{state['thread_id']}:msg:{hashlib.sha256(text.encode()).hexdigest()[:12]}"
    r = await tb.call("send_message", {"inp": {"conversation_id": state["conversation_id"], "text": text,
                                               "idempotency_key": key, "approved_by": state["approval"]["user_id"]}})
    out = {"sent": r, "status": "submitted", "status_reason": "reply sent"}
    if state.get("slots"):
        s = state["slots"][0]
        out["hold"] = await tb.call("create_interview_hold", {"inp": {"start": s["start"], "end": s["end"],
                                                                      "title": f"Tentative: client call ({state['conversation_id']})",
                                                                      "idempotency_key": f"{key}:hold"}})
        out["pipeline_stage"] = "interview"
    return out


@node("update_pipeline", budget_key="max_tokens_per_conversation_turn")
async def update_pipeline(state: dict) -> dict:
    it = (state.get("intent") or {}).get("intent")
    stage = {"acceptance": "hired", "rejection": "lost"}.get(it, "replied")
    return {"pipeline_stage": stage, "status": "skipped", "status_reason": f"no reply needed ({it})"}


def _ok(nxt: str):
    """Continue to `nxt` unless the previous node ended the thread (dead letter, degraded, ...)."""
    return lambda s: END if s.get("status") in TERMINAL else nxt


def build_conversation_graph(checkpointer=None, store=None):
    g = StateGraph(ConvState)
    g.add_node("load", load)
    g.add_node("classify", classify)
    g.add_node("find_slots", find_slots)
    g.add_node("draft_reply", draft_reply)
    g.add_node("check", check)
    g.add_node("reply_approval", approval)
    g.add_node("send", send)
    g.add_node("update_pipeline", update_pipeline)
    g.add_edge(START, "load")
    g.add_conditional_edges("load", _ok("classify"), ["classify", END])
    g.add_conditional_edges("classify", lambda s: END if s.get("status") in TERMINAL else route_intent(s),
                            ["find_slots", "draft_reply", "update_pipeline", END])
    g.add_conditional_edges("find_slots", _ok("draft_reply"), ["draft_reply", END])
    g.add_conditional_edges("draft_reply", _ok("check"), ["check", END])
    g.add_conditional_edges("check", lambda s: END if s.get("status") == "blocked" else "reply_approval",
                            ["reply_approval", END])
    g.add_conditional_edges("reply_approval", after_approval, ["send", "reply_approval", END])
    g.add_edge("send", END)
    g.add_edge("update_pipeline", END)
    return g.compile(checkpointer=checkpointer, store=store, name="conversation_graph")
