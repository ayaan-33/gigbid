"""R&D question A: does tool granularity change agent behaviour?

40 tasks with a known correct call (canonical intent + arguments) are posed to an LLM with tool
calling enabled, under three tool designs that expose the SAME capabilities:
  fine    : 20 narrow tools (one per field / per evidence type)
  coarse  : 3 broad tools with an `action` enum (marketplace, portfolio, workspace)
  best    : GigBid's actual MCP tool set with rewritten, example-rich descriptions
Metrics per design: tool-selection accuracy, argument accuracy (all required args right),
tokens per task (prompt incl. tool schemas + completion), p50 latency.
Writes evals/results/tool_granularity.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics as st
import time
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from pydantic import Field, create_model

from agent import llm
from agent.prompts import load_prompt

ROOT = Path(__file__).resolve().parents[2]

# --------------------------------------------------------------------------- tasks (canonical intents)
# (task text, canonical op, canonical args)
TASKS: list[tuple[str, str, dict[str, Any]]] = [
    ("Find open jobs about RAG chatbots.", "search_jobs", {"query": "RAG chatbot"}),
    ("Look for Power BI dashboard gigs.", "search_jobs", {"query": "Power BI dashboard"}),
    ("Any new Next.js projects posted?", "search_jobs", {"query": "Next.js"}),
    ("Search the marketplace for churn prediction work.", "search_jobs", {"query": "churn prediction"}),
    ("Show me Stripe integration jobs.", "search_jobs", {"query": "Stripe integration"}),
    ("Open job job_00073 so I can read it.", "get_job", {"job_id": "job_00073"}),
    ("What exactly does job_00004 ask for?", "get_job", {"job_id": "job_00004"}),
    ("Pull up the full post for job_00118.", "get_job", {"job_id": "job_00118"}),
    ("Is client cl_job_00044 payment-verified and how much have they spent?", "get_client_history", {"client_id": "cl_job_00044"}),
    ("Check the hiring history of client cl_job_00200.", "get_client_history", {"client_id": "cl_job_00200"}),
    ("Has client cl_job_00104 left reviews for freelancers?", "get_client_history", {"client_id": "cl_job_00104"}),
    ("How many Connects do I have left?", "get_connects_balance", {}),
    ("Can I afford to bid this week? Check my Connects.", "get_connects_balance", {}),
    ("What do fixed-price ai_ml jobs usually pay?", "get_market_stats", {"category": "ai_ml", "budget_type": "fixed"}),
    ("Typical hourly rates for web_dev jobs?", "get_market_stats", {"category": "web_dev", "budget_type": "hourly"}),
    ("Median budget for data_analysis fixed-price work?", "get_market_stats", {"category": "data_analysis", "budget_type": "fixed"}),
    ("What are the platform's current rules?", "get_policy", {}),
    ("Did the marketplace change its policy recently?", "get_policy", {}),
    ("Show my client conversations.", "list_conversations", {}),
    ("Which clients have written to me?", "list_conversations", {}),
    ("Read the messages in conversation conv_dd4fdca65f9c.", "list_messages", {"conversation_id": "conv_dd4fdca65f9c"}),
    ("What did the client say in conv_877531ebdf78?", "list_messages", {"conversation_id": "conv_877531ebdf78"}),
    ("What events happened on my proposals since event 40?", "list_events", {"since_id": 40}),
    ("Is the marketplace up right now?", "marketplace_status", {}),
    ("Find portfolio evidence that I have done hybrid search with BM25.", "search_evidence", {"requirement": "hybrid search with BM25"}),
    ("Do I have proof of deploying models with Docker?", "search_evidence", {"requirement": "deploying models with Docker"}),
    ("Find past work on fraud detection for fintech clients.", "search_evidence", {"requirement": "fraud detection fintech"}),
    ("Which of my projects show time-series forecasting?", "search_evidence", {"requirement": "time-series forecasting"}),
    ("Find evidence of Stripe webhooks in my portfolio.", "search_evidence", {"requirement": "Stripe webhooks"}),
    ("Show past proposals of mine that won for dashboard jobs.", "search_evidence",
     {"requirement": "dashboard", "type": "proposal", "outcome": "won"}),
    ("Find client reviews that mention communication.", "search_evidence", {"requirement": "communication", "type": "review"}),
    ("Show code repositories where I used FastAPI.", "search_evidence", {"requirement": "FastAPI", "type": "repo"}),
    ("Open my case study ai_ml_engineer:case:support_rag.", "get_case_study", {"id": "ai_ml_engineer:case:support_rag"}),
    ("I need the full write-up of ai_ml_engineer:case:churn_model.", "get_case_study", {"id": "ai_ml_engineer:case:churn_model"}),
    ("Which skills does my portfolio prove?", "list_skills", {}),
    ("List my evidenced skills with counts.", "list_skills", {}),
    ("When am I free for a 30-minute call this week?", "find_free_slots", {"duration_min": 30}),
    ("Find three free 60-minute slots for an interview.", "find_free_slots", {"duration_min": 60}),
    ("Draft an email to the client confirming Tuesday's interview.", "create_email_draft", {}),
    ("Put a tentative hold in my calendar for the client call.", "create_interview_hold", {}),
]

# --------------------------------------------------------------------------- tool designs


def _tool(name: str, desc: str, fields: dict[str, tuple[type, Any, str]]) -> StructuredTool:
    model = create_model(f"{name}_args", **{k: (t, Field(d, description=h)) for k, (t, d, h) in fields.items()})

    def _noop(**kw):  # never executed: we evaluate the FIRST call the model chooses
        return "ok"

    return StructuredTool.from_function(func=_noop, name=name, description=desc, args_schema=model)


S, I, O = str, int, (str | None)


def fine_tools() -> tuple[list[StructuredTool], dict]:
    t = [
        _tool("search_jobs_by_keyword", "Search jobs by keyword.", {"keyword": (S, ..., "keyword")}),
        _tool("search_jobs_by_skill", "Search jobs by skill.", {"skill": (S, ..., "skill")}),
        _tool("search_jobs_by_category", "Search jobs by category.", {"category": (S, ..., "category")}),
        _tool("get_job_title", "Get a job's title.", {"job_id": (S, ..., "job id")}),
        _tool("get_job_description", "Get a job's description.", {"job_id": (S, ..., "job id")}),
        _tool("get_job_budget", "Get a job's budget.", {"job_id": (S, ..., "job id")}),
        _tool("get_client_payment_status", "Client payment verification.", {"client_id": (S, ..., "client id")}),
        _tool("get_client_spend", "Client total spend.", {"client_id": (S, ..., "client id")}),
        _tool("get_client_reviews", "Client reviews.", {"client_id": (S, ..., "client id")}),
        _tool("get_connects_balance", "Connects balance.", {}),
        _tool("get_fixed_price_stats", "Fixed price stats.", {"category": (S, ..., "category")}),
        _tool("get_hourly_rate_stats", "Hourly stats.", {"category": (S, ..., "category")}),
        _tool("get_policy", "Policy.", {}),
        _tool("list_conversations", "Conversations.", {}),
        _tool("list_messages", "Messages.", {"conversation_id": (S, ..., "conversation id")}),
        _tool("list_events", "Events.", {"since_id": (I, 0, "cursor")}),
        _tool("marketplace_status", "Status.", {}),
        _tool("search_case_studies", "Search case studies.", {"query": (S, ..., "query")}),
        _tool("search_repos", "Search repos.", {"query": (S, ..., "query")}),
        _tool("search_reviews", "Search reviews.", {"query": (S, ..., "query")}),
        _tool("search_won_proposals", "Search past proposals that won.", {"query": (S, ..., "query")}),
        _tool("get_case_study", "Case study.", {"id": (S, ..., "id")}),
        _tool("list_skills", "Skills.", {}),
        _tool("find_free_slots", "Free slots.", {"duration_min": (I, 30, "minutes")}),
        _tool("create_interview_hold", "Hold.", {"start": (S, ..., "iso"), "end": (S, ..., "iso"), "title": (S, ..., "title")}),
        _tool("create_email_draft", "Email draft.", {"to_label": (S, ..., "to"), "subject": (S, ..., "subject"), "body": (S, ..., "body")}),
    ]

    def expect(op: str, args: dict) -> list[tuple[str, dict]]:
        """All acceptable (tool, key args) for a canonical intent under this design."""
        m = {
            "search_jobs": lambda: [("search_jobs_by_keyword", {"keyword": args.get("query")}),
                                    ("search_jobs_by_skill", {"skill": args.get("query")})],
            "get_job": lambda: [(n, {"job_id": args["job_id"]}) for n in ("get_job_description", "get_job_title", "get_job_budget")],
            "get_client_history": lambda: [(n, {"client_id": args["client_id"]})
                                           for n in ("get_client_payment_status", "get_client_spend", "get_client_reviews")],
            "get_market_stats": lambda: [("get_fixed_price_stats" if args.get("budget_type") == "fixed" else "get_hourly_rate_stats",
                                          {"category": args["category"]})],
            "search_evidence": lambda: [({"proposal": "search_won_proposals", "review": "search_reviews", "repo": "search_repos"}
                                         .get(args.get("type"), "search_case_studies"), {"query": args["requirement"]})],
        }
        if op in m:
            return m[op]()
        return m.get(op, [(op, {k: v for k, v in args.items()})])

    return t, expect


def coarse_tools() -> tuple[list[StructuredTool], dict]:
    t = [
        _tool("marketplace", "Marketplace access. action: search_jobs | get_job | get_client_history | get_connects_balance | "
              "get_market_stats | get_policy | list_conversations | list_messages | list_events | status",
              {"action": (S, ..., "operation"), "query": (O, None, "keywords"), "id": (O, None, "job/client/conversation id"),
               "category": (O, None, "category"), "budget_type": (O, None, "fixed|hourly"), "since_id": (int | None, None, "cursor")}),
        _tool("portfolio", "Portfolio access. action: search | get_case_study | list_skills",
              {"action": (S, ..., "operation"), "query": (O, None, "what to find"), "type": (O, None, "case_study|repo|review|proposal"),
               "outcome": (O, None, "won|replied|ignored"), "id": (O, None, "case study id")}),
        _tool("workspace", "Calendar and email. action: free_slots | hold | email_draft",
              {"action": (S, ..., "operation"), "duration_min": (int | None, None, "minutes")}),
    ]

    def expect(op: str, args: dict) -> list[tuple[str, dict]]:
        mk = {"search_jobs": ("marketplace", {"action": "search_jobs", "query": args.get("query")}),
              "get_job": ("marketplace", {"action": "get_job", "id": args.get("job_id")}),
              "get_client_history": ("marketplace", {"action": "get_client_history", "id": args.get("client_id")}),
              "get_connects_balance": ("marketplace", {"action": "get_connects_balance"}),
              "get_market_stats": ("marketplace", {"action": "get_market_stats", "category": args.get("category"), "budget_type": args.get("budget_type")}),
              "get_policy": ("marketplace", {"action": "get_policy"}),
              "list_conversations": ("marketplace", {"action": "list_conversations"}),
              "list_messages": ("marketplace", {"action": "list_messages", "id": args.get("conversation_id")}),
              "list_events": ("marketplace", {"action": "list_events", "since_id": args.get("since_id")}),
              "marketplace_status": ("marketplace", {"action": "status"}),
              "search_evidence": ("portfolio", {"action": "search", "query": args.get("requirement"), "type": args.get("type"), "outcome": args.get("outcome")}),
              "get_case_study": ("portfolio", {"action": "get_case_study", "id": args.get("id")}),
              "list_skills": ("portfolio", {"action": "list_skills"}),
              "find_free_slots": ("workspace", {"action": "free_slots", "duration_min": args.get("duration_min")}),
              "create_interview_hold": ("workspace", {"action": "hold"}),
              "create_email_draft": ("workspace", {"action": "email_draft"})}
        return [mk[op]]

    return t, expect


def best_tools() -> tuple[list[StructuredTool], dict]:
    """GigBid's real tool surface (names/args as in the MCP servers) with rewritten descriptions."""
    t = [
        _tool("search_jobs", "Search OPEN jobs on the marketplace by keywords (e.g. 'RAG chatbot', 'Power BI'). Use for "
              "'find/look for/any new ... jobs'.", {"query": (S, ..., "keywords from the request, e.g. 'Next.js'"), "category": (O, None, "optional")}),
        _tool("get_job", "Read ONE job post in full (title, description, budget, screening questions, Connects cost) by id like "
              "'job_00073'.", {"job_id": (S, ..., "job id, e.g. job_00073")}),
        _tool("get_client_history", "A client's marketplace record: payment verified, total spent, hires, rating, reviews. "
              "Use for any question about a client id like 'cl_job_00044'.", {"client_id": (S, ..., "client id")}),
        _tool("get_connects_balance", "The freelancer's remaining Connects (bidding credits).", {}),
        _tool("get_market_stats", "Historical price percentiles for a job category. budget_type 'fixed' for fixed-price/budget "
              "questions, 'hourly' for rate questions.", {"category": (S, ..., "ai_ml | web_dev | data_analysis | ..."),
                                                           "budget_type": (S, "fixed", "fixed | hourly")}),
        _tool("get_policy", "The platform's CURRENT rules and policy version (detects policy updates).", {}),
        _tool("list_conversations", "All client conversation threads (who wrote to me).", {}),
        _tool("list_messages", "Messages of one conversation id like 'conv_dd4fdca65f9c'.", {"conversation_id": (S, ..., "conversation id")}),
        _tool("list_events", "Proposal events (viewed/replied/hired/lost) after an event id.", {"since_id": (I, 0, "last seen event id")}),
        _tool("marketplace_status", "Is the marketplace reachable/healthy right now?", {}),
        _tool("search_evidence", "Search the freelancer's OWN portfolio for proof of ONE requirement. Optional filters: "
              "type (case_study|repo|review|proposal), outcome for past proposals (won|replied|ignored).",
              {"requirement": (S, ..., "what needs proving, e.g. 'hybrid search with BM25'"), "type": (O, None, "evidence type"),
               "outcome": (O, None, "won|replied|ignored")}),
        _tool("get_case_study", "Full case study by evidence id like 'ai_ml_engineer:case:support_rag'.", {"id": (S, ..., "evidence id")}),
        _tool("list_skills", "Every skill the portfolio proves, with evidence counts.", {}),
        _tool("find_free_slots", "Free calendar slots for a call/interview of duration_min minutes.", {"duration_min": (I, 30, "minutes")}),
        _tool("create_interview_hold", "Tentative calendar hold for a client call.", {"start": (S, ..., "ISO time"), "end": (S, ..., "ISO time"),
                                                                                      "title": (S, ..., "title")}),
        _tool("create_email_draft", "Save an email DRAFT (never sends) e.g. interview confirmations.",
              {"to_label": (S, ..., "recipient label"), "subject": (S, ..., "subject"), "body": (S, ..., "body")}),
    ]

    def expect(op: str, args: dict) -> list[tuple[str, dict]]:
        return [(op, dict(args))]

    return t, expect


DESIGNS = {"fine": fine_tools, "coarse": coarse_tools, "best": best_tools}


def _norm(v: Any) -> str:
    return str(v).strip().lower().replace("-", " ") if v is not None else ""


def args_match(want: dict, got: dict) -> bool:
    for k, v in want.items():
        if v in (None, ""):
            continue
        g = got.get(k)
        if isinstance(v, int | float):
            try:
                if float(g) != float(v):
                    return False
            except (TypeError, ValueError):
                return False
        elif _norm(v) not in _norm(g) and _norm(g) not in _norm(v) and not set(_norm(v).split()) <= set(_norm(g).split()):
            return False
    return True


async def run(designs: list[str], limit: int | None, node: str) -> dict:
    p = load_prompt("tool_router")
    out: dict = {"model": llm.model_for(node), "profile": llm.profile_name(), "tasks": len(TASKS[: limit or None]), "designs": {}}
    for d in designs:
        tools, expect = DESIGNS[d]()
        model = llm.chat_model(node, temperature=0).bind_tools(tools, tool_choice="required" if llm.profile_name() == "open" else None)
        rows = []
        for text, op, args in TASKS[: limit or None]:
            t0 = time.perf_counter()
            calls, tok = [], 0
            schema_tok = sum(len(json.dumps(t.args_schema.model_json_schema())) + len(t.description) for t in tools) // 4
            for _attempt in range(6):  # paced like production calls: free-tier tokens/minute
                await llm.RATE.acquire(llm.model_for(node), schema_tok + 400)
                try:
                    resp = await model.ainvoke([SystemMessage(p.text), HumanMessage(text)])
                    calls = resp.tool_calls or []
                    tok = (resp.usage_metadata or {}).get("total_tokens", 0)
                    break
                except Exception as e:  # noqa: BLE001
                    wait = llm._retry_after(e)
                    if wait is None:
                        print("error", d, text[:40], str(e)[:120])
                        break
                    await asyncio.sleep(wait)
            dt = time.perf_counter() - t0
            first = calls[0] if calls else None
            ok_tool = ok_args = False
            if first:
                for name, a in expect(op, args):
                    if first["name"] == name:
                        ok_tool = True
                        ok_args = ok_args or args_match(a, first.get("args") or {})
            rows.append({"task": text, "op": op, "called": first["name"] if first else None, "args": first.get("args") if first else None,
                         "tool_ok": ok_tool, "args_ok": ok_tool and ok_args, "tokens": tok, "latency_s": round(dt, 3)})
        n = len(rows)
        out["designs"][d] = {"n_tools": len(tools), "tool_selection_accuracy": round(sum(r["tool_ok"] for r in rows) / n, 4),
                             "argument_accuracy": round(sum(r["args_ok"] for r in rows) / n, 4),
                             "tokens_per_task": round(st.mean(r["tokens"] for r in rows), 1),
                             "p50_latency_s": round(st.median(r["latency_s"] for r in rows), 3), "rows": rows}
        print(d, {k: v for k, v in out["designs"][d].items() if k != "rows"}, flush=True)
    tag = os.getenv("TOOLSTUDY_TAG") or llm.profile_name()
    (ROOT / "evals" / "results" / f"tool_granularity_{tag}.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--designs", nargs="+", default=list(DESIGNS))
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--node", default="scout")
    a = ap.parse_args()
    asyncio.run(run(a.designs, a.limit, a.node))
