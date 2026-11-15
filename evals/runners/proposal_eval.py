"""End-to-end proposal quality per RAG variant (README / report results table, B5).

For each fit dev job and each variant: Fit Matcher (variant's retrieval via the Portfolio MCP
server) -> Pricing -> Writer -> claim verification -> Compliance; then
  * unsupported claims per proposal (before and after verification),
  * LLM-judge overall score (rubric, judge calibrated in judge_calibration.json),
  * GigSim simulated reply rate (seeded clients),
  * latency (p50/p95) and cost per proposal (list price; free tier actually used).
Writes evals/results/proposal_eval.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics as st
import time
from pathlib import Path

from agent import llm
from evals.harness import env, load_gold, public_job

ROOT = Path(__file__).resolve().parents[2]


async def one(job: dict, persona: str, variant: str, e) -> dict:
    from agent.graphs.bid_graph import initial_state
    from agent.marketplace_port import ProposalPayload
    from agent.nodes import analysts, decide_price
    from agent.nodes.proposal import compliance, verifier, writer
    from evals.runners.judge import judge
    from mcp_servers.portfolio import server as ps

    ps.service.variant = variant
    led = llm.start_ledger()
    t0 = time.perf_counter()
    st_ = initial_state(job, user_id=f"pe-{persona}", persona=persona, thread_id=f"pe-{variant}-{job['id']}", strategy="default")
    for node in (analysts.fit_matcher, decide_price.price, writer, verifier, compliance):
        upd = await node(st_)
        for k, v in upd.items():
            if k in ("evidence", "draft_history", "critiques", "approvals", "errors"):
                st_[k] = (st_.get(k) or []) + (v or [])
            elif k not in ("steps", "tokens", "usage", "timings"):
                st_[k] = v
        if st_.get("status") in ("dead_letter", "blocked", "needs_attention", "queued_degraded"):
            raise RuntimeError(st_.get("status_reason"))
    dt = time.perf_counter() - t0
    text = st_["draft"]["cover_letter"]
    rep = st_.get("claim_report") or {}
    js = await judge(job["title"], job["description"], text)
    port = e["port_for"](persona)
    key = f"pe-{variant}-{persona}-{job['id']}"
    d = await port.create_proposal_draft(ProposalPayload(job_id=job["id"], cover_letter=text[:5000],
                                                         bid_amount=float(st_["price_quote"]["amount"])), key)
    await port.submit_proposal(d.proposal_id, key + "-s")
    sim = e["sim"]
    sim.db.x("update proposals set decide_at=0 where id=?", (d.proposal_id,))
    await sim._process_decisions()
    o = json.loads(sim.db.one("select outcome from proposals where id=?", (d.proposal_id,))["outcome"] or "{}")
    return {"unsupported_before": rep.get("unsupported_before", 0), "unsupported_after": rep.get("unsupported_after", 0),
            "claims": rep.get("total_claims", 0), "judge_overall": js.overall, "replied": bool(o.get("replied")),
            "latency_s": round(dt, 2), "cost_usd": led.total_cost, "tokens": led.total_tokens}


async def run(variants: list[str], per_persona: int) -> dict:
    rows = []
    async with env() as e:
        for p in ["ai_ml_engineer", "fullstack_dev", "data_analyst"]:
            port = e["port_for"](p)
            for g in [g for g in load_gold(p) if g["job_type"] == "fit"][10:10 + per_persona]:  # disjoint from the A/B jobs
                job = await public_job(port, g["job_id"])
                for v in variants:
                    try:
                        r = await one(job, p, v, e)
                        rows.append({"variant": v, "persona": p, "job_id": g["job_id"], **r})
                        print(v, p, g["job_id"], r["unsupported_before"], r["judge_overall"], r["replied"], flush=True)
                    except Exception as ex:  # noqa: BLE001
                        print("error", v, g["job_id"], str(ex)[:160], flush=True)
    out = {"writer_model": llm.model_for("writer"), "judge_model": llm.model_for("judge"), "variants": {}}
    for v in variants:
        R = [r for r in rows if r["variant"] == v]
        if not R:
            continue
        lat = sorted(r["latency_s"] for r in R)
        out["variants"][v] = {
            "n": len(R),
            "unsupported_claims_per_proposal_before": round(st.mean(r["unsupported_before"] for r in R), 3),
            "unsupported_claims_per_proposal": round(st.mean(r["unsupported_after"] for r in R), 3),
            "judge_score": round(st.mean(r["judge_overall"] for r in R), 3),
            "gigsim_reply_rate": round(sum(r["replied"] for r in R) / len(R), 4),
            "p95_latency_s": lat[int(0.95 * (len(lat) - 1))],
            "cost_per_proposal_usd": round(st.mean(r["cost_usd"] for r in R), 5),
            "tokens_per_proposal": round(st.mean(r["tokens"] for r in R)),
        }
    (ROOT / "evals" / "results" / "proposal_eval.json").write_text(json.dumps(out, indent=1))
    (ROOT / "evals" / "results" / "proposal_eval_rows.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", nargs="+", default=["v0_naive", "v5_norerank"])
    ap.add_argument("--per-persona", type=int, default=4)
    a = ap.parse_args()
    asyncio.run(run(a.variants, a.per_persona))
