"""R&D question C: is the multi-agent design worth it?

Same jobs, same model, same MCP tools, three architectures:
  (a) react      : ONE prebuilt ReAct agent (langgraph.prebuilt.create_react_agent) holding every tool
  (b) supervisor : prebuilt supervisor (langgraph-supervisor) over 3 worker agents
                   (market researcher, portfolio researcher, writer)
  (c) graph      : GigBid's hand-built bid graph (parallel analysts, verifier, critic, compliance)
For each job: bid/skip accuracy, scam caught, proposal text -> unsupported claims (deterministic
verifier against the portfolio), compliance violations left in the final text, tokens, latency.
Bid proposals are then submitted to an in-process GigSim (evaluation only: approval simulated) and
the seeded simulated clients decide -> reply rate.
Writes evals/results/multiagent_compare_<profile>.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics as st
import time
import uuid
from pathlib import Path

from langchain_core.messages import HumanMessage

from agent import llm
from agent.llm import start_ledger
from agent.nodes.proposal import rule_compliance
from agent.prompts import load_prompt
from evals.harness import env, load_gold, public_job

ROOT = Path(__file__).resolve().parents[2]
DECISION = re.compile(r'"?action"?\s*[:=]\s*"?(bid|skip|watch)', re.I)
SCAM = re.compile(r'"?is_scam"?\s*[:=]\s*"?(true|yes)', re.I)
PRICE = re.compile(r'"?price"?\s*[:=]\s*"?\$?([\d,.]+)', re.I)


def msg_tokens(messages) -> int:
    """Prebuilt agents call the model directly: sum the usage reported on every AI message."""
    return sum(((getattr(m, "usage_metadata", None) or {}).get("total_tokens", 0)) for m in messages)


def parse_final(text: str) -> dict:
    text = text.split("</think>")[-1]
    try:
        d = json.loads(text[text.find("{"): text.rfind("}") + 1])
        return {"action": str(d.get("action", "skip")).lower(), "is_scam": bool(d.get("is_scam")),
                "price": float(str(d.get("price") or 0).replace(",", "").replace("$", "") or 0),
                "proposal": d.get("proposal") or ""}
    except Exception:  # noqa: BLE001 - tolerate free-form endings
        m = DECISION.search(text)
        p = PRICE.search(text)
        return {"action": (m.group(1).lower() if m else "skip"), "is_scam": bool(SCAM.search(text)),
                "price": float(p.group(1).replace(",", "")) if p else 0.0, "proposal": text if "proposal" in text.lower() else ""}


async def mcp_tools(persona: str):
    """All GigBid MCP tools as LangChain tools over in-memory sessions (no allowlist: baselines)."""
    from langchain_mcp_adapters.tools import load_mcp_tools
    from mcp.shared.memory import create_connected_server_and_client_session

    from mcp_servers.common import CURRENT_CALLER
    from mcp_servers.marketplace import server as ms
    from mcp_servers.portfolio import server as ps

    CURRENT_CALLER.set({"user": f"eval-{persona}", "persona": persona, "trace_id": uuid.uuid4().hex})
    stack = []
    tools = []
    for srv in (ms, ps):
        cm = create_connected_server_and_client_session(srv.mcp._mcp_server)
        s = await cm.__aenter__()
        stack.append(cm)
        tools += await load_mcp_tools(s)
    read_only = [t for t in tools if t.name not in ("create_proposal_draft", "submit_proposal", "send_message")]
    return read_only, stack


async def run_react(job: dict, persona: str) -> dict:
    from langgraph.prebuilt import create_react_agent

    tools, stack = await mcp_tools(persona)
    try:
        agent = create_react_agent(llm.chat_model("writer"), tools, prompt=load_prompt("baseline_react").text)
        out = await agent.ainvoke({"messages": [HumanMessage(f"Job id: {job['id']}. Decide and, if bidding, draft the proposal.")]},
                                  {"recursion_limit": 24})
        last = out["messages"][-1].content
        return {**parse_final(last if isinstance(last, str) else str(last)), "tokens": msg_tokens(out["messages"])}
    finally:
        for cm in reversed(stack):
            await cm.__aexit__(None, None, None)


async def run_supervisor(job: dict, persona: str) -> dict:
    from langgraph.prebuilt import create_react_agent
    from langgraph_supervisor import create_supervisor

    tools, stack = await mcp_tools(persona)
    try:
        m = llm.chat_model("writer")
        market = create_react_agent(m, [t for t in tools if t.name in ("get_job", "get_client_history", "get_market_stats",
                                                                       "get_connects_balance", "get_policy")],
                                    name="market_researcher", prompt="You research the job, client and market. Report facts only.")
        port = create_react_agent(m, [t for t in tools if t.name in ("search_evidence", "get_case_study", "list_skills")],
                                  name="portfolio_researcher", prompt="You find portfolio evidence for each requirement. Report evidence ids.")
        writer = create_react_agent(m, [], name="writer", prompt="You write proposals using only evidence given to you; cite [evidence_id].")
        sup = create_supervisor([market, port, writer], model=m, prompt=load_prompt("baseline_react").text,
                                output_mode="full_history").compile()  # full history so every token is counted
        out = await sup.ainvoke({"messages": [HumanMessage(f"Job id: {job['id']}. Decide and, if bidding, draft the proposal.")]},
                                {"recursion_limit": 40})
        last = out["messages"][-1].content
        return {**parse_final(last if isinstance(last, str) else str(last)), "tokens": msg_tokens(out["messages"])}
    finally:
        for cm in reversed(stack):
            await cm.__aexit__(None, None, None)


async def run_graph(job: dict, persona: str) -> dict:
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore

    from agent.graphs.bid_graph import build_bid_graph, initial_state

    g = build_bid_graph(InMemorySaver(), InMemoryStore())
    tid = f"rdc-{job['id']}"
    out = await g.ainvoke(initial_state(job, user_id=f"eval-{persona}", persona=persona, thread_id=tid), {"configurable": {"thread_id": tid}})
    dec = (out.get("decision") or {}).get("action", "skip")
    proposal = (out.get("draft") or {}).get("cover_letter", "") if "__interrupt__" in out else ""
    viol = len((out.get("compliance") or {}).get("violations", []))
    return {"action": dec, "is_scam": bool((out.get("risk_report") or {}).get("is_scam")),
            "price": (out.get("price_quote") or {}).get("amount", 0.0), "proposal": proposal, "violations_caught": viol}


async def _retrying(fn, job: dict, persona: str) -> dict:
    """Prebuilt agents crash when the provider rejects a hallucinated tool call (HTTP 400 'tool
    call validation failed'). Retry up to 3 times, as a production wrapper would, and count it."""
    errors = 0
    attempts = 0
    while attempts < 3:
        try:
            r = await fn(job, persona)
            r["tool_call_errors"] = errors
            return r
        except Exception as e:  # noqa: BLE001
            wait = llm._retry_after(e)
            if wait is not None:  # free-tier rate limit: wait as the provider asks, not a failure
                await asyncio.sleep(wait)
                continue
            if "tool call validation failed" in str(e) or "Failed to parse tool call" in str(e):
                errors += 1
                attempts += 1
                continue
            raise
    return {"action": "error", "is_scam": False, "price": 0, "proposal": "", "tool_call_errors": errors}


async def react_retry(job, persona):
    return await _retrying(run_react, job, persona)


async def supervisor_retry(job, persona):
    return await _retrying(run_supervisor, job, persona)


SYSTEMS = {"react": react_retry, "supervisor": supervisor_retry, "graph": run_graph}


def unsupported_claims(persona: str, text: str, idx) -> int:
    from rag.verify import heuristic_label, is_claim, split_claims

    n = 0
    for s in split_claims(text):
        if not is_claim(s):
            continue
        hits = idx.bm25(persona, s, 5) or []
        ev = [(c.evidence_id, c.text) for c, _ in hits]
        lab, _, _ = heuristic_label(s, ev)
        n += lab.value == "unsupported"
    return n


async def run(systems: list[str], per_persona: int) -> dict:
    personas = ["ai_ml_engineer", "fullstack_dev", "data_analyst"]
    rows = []
    async with env(personas) as e:
        idx = e["index"]
        for p in personas:
            gold = load_gold(p)
            by: dict[str, list] = {}
            for g in gold:
                if g["job_type"] != "duplicate":
                    by.setdefault(g["job_type"], []).append(g)
            sample = [g for t, gs in by.items() for g in gs[: max(1, round(per_persona * len(gs) / len(gold)))]][:per_persona]
            port = e["port_for"](p)
            for g in sample:
                job = await public_job(port, g["job_id"])
                for s in systems:
                    led = start_ledger()
                    t0 = time.perf_counter()
                    try:
                        r = await asyncio.wait_for(SYSTEMS[s](job, p), 600)
                        err = None
                    except Exception as ex:  # noqa: BLE001
                        r, err = {"action": "error", "is_scam": False, "price": 0, "proposal": ""}, f"{type(ex).__name__}: {ex}"[:200]
                    dt = time.perf_counter() - t0
                    text = r.get("proposal") or ""
                    _, left, _ = rule_compliance(text) if text else ("", [], False)
                    replied = None
                    if r["action"] == "bid" and text and len(text) >= 50:
                        try:  # evaluation-only submission to the simulator (approval simulated)
                            from agent.marketplace_port import ProposalPayload

                            key = f"rdc-{s}-{g['job_id']}"
                            d = await port.create_proposal_draft(ProposalPayload(job_id=job["id"], cover_letter=text[:5000],
                                                                                  bid_amount=max(1.0, float(r.get("price") or 1))), key)
                            await port.submit_proposal(d.proposal_id, key + "-s")
                            sim = e["sim"]
                            sim.db.x("update proposals set decide_at=0 where id=?", (d.proposal_id,))
                            await sim._process_decisions()
                            row = sim.db.one("select outcome from proposals where id=?", (d.proposal_id,))
                            replied = bool(json.loads(row["outcome"] or "{}").get("replied"))
                        except Exception as ex:  # noqa: BLE001
                            err = (err or "") + f" submit:{ex}"[:120]
                    rows.append({"system": s, "persona": p, "job_id": g["job_id"], "job_type": g["job_type"],
                                 "gold": g["action"], "pred": "bid" if r["action"] == "bid" else "skip",
                                 "gold_scam": g["is_scam"], "pred_scam": r["is_scam"],
                                 "unsupported_claims": unsupported_claims(p, text, idx) if text else 0,
                                 "violations_left": len(left), "violations_caught": r.get("violations_caught", 0),
                                 "replied": replied, "tool_call_errors": r.get("tool_call_errors", 0), "tokens": r.get("tokens") or led.total_tokens, "latency_s": round(dt, 2), "error": err})
                    print(s, p, g["job_id"], rows[-1]["pred"], g["action"], rows[-1]["tokens"], f"{dt:.0f}s", flush=True)
    summary = {}
    for s in systems:
        R = [r for r in rows if r["system"] == s]
        props = [r for r in R if r["pred"] == "bid"]
        reps = [r["replied"] for r in R if r["replied"] is not None]
        summary[s] = {
            "n": len(R),
            "bid_skip_accuracy": round(sum(r["pred"] == r["gold"] for r in R) / len(R), 4),
            "scam_recall": round(sum(r["pred_scam"] for r in R if r["gold_scam"]) / max(1, sum(r["gold_scam"] for r in R)), 4),
            "unsupported_claims_per_proposal": round(sum(r["unsupported_claims"] for r in props) / max(1, len(props)), 3),
            "compliance_violations_left": sum(r["violations_left"] for r in R),
            "compliance_violations_caught": sum(r["violations_caught"] for r in R),
            "gigsim_reply_rate": round(sum(reps) / len(reps), 4) if reps else None, "n_submitted": len(reps),
            "tokens_per_job": round(st.mean(r["tokens"] for r in R), 1),
            "p50_latency_s": round(st.median(r["latency_s"] for r in R), 2),
            "p95_latency_s": round(sorted(r["latency_s"] for r in R)[int(0.95 * (len(R) - 1))], 2),
            "errors": sum(1 for r in R if r["error"]),
            "tool_call_validation_errors": sum(r.get("tool_call_errors", 0) for r in R),
            "by_job_type": {t: round(sum(r["pred"] == r["gold"] for r in R if r["job_type"] == t) /
                                     max(1, sum(1 for r in R if r["job_type"] == t)), 3) for t in sorted({r["job_type"] for r in R})},
        }
    out = {"model": llm.model_for("writer"), "profile": llm.profile_name(), "summary": summary}
    name = f"multiagent_compare_{llm.profile_name()}"
    (ROOT / "evals" / "results" / f"{name}.json").write_text(json.dumps(out, indent=1))
    (ROOT / "evals" / "results" / f"{name}_rows.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(json.dumps(summary, indent=1))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--systems", nargs="+", default=list(SYSTEMS))
    ap.add_argument("--per-persona", type=int, default=17, help="17 x 3 personas ~= 50 jobs")
    a = ap.parse_args()
    asyncio.run(run(a.systems, a.per_persona))
