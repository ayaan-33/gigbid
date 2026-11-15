"""Extension X2: proposal strategy A/B test in GigSim with a significance test on reply rate.

Arms (agent/nodes/proposal.py STRATEGIES):
  A = evidence_first : lead with the most relevant past project + measured result
  B = question_led   : restate the problem, then one sharp clarifying question
Design: for each fit dev job, the real pipeline (Fit Matcher via MCP -> Writer with the arm's
strategy -> claim verification -> Compliance) writes ONE proposal per arm; both are submitted to
GigSim as separate proposals and the seeded simulated client decides each independently.
Tests: paired McNemar (same jobs, both arms) + unpaired two-proportion z-test and Fisher exact.
Writes evals/results/ab_experiment.json (+ rows).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from pathlib import Path

from scipy import stats

from agent import llm
from evals.harness import env, load_gold, public_job

ROOT = Path(__file__).resolve().parents[2]
ARMS = ["evidence_first", "question_led"]


async def write_one(job: dict, persona: str, arm: str) -> tuple[str, float]:
    from agent.graphs.bid_graph import initial_state
    from agent.nodes import analysts, decide_price
    from agent.nodes.proposal import compliance, verifier, writer

    st = initial_state(job, user_id=f"ab-{persona}", persona=persona, thread_id=f"ab-{arm}-{job['id']}", strategy=arm)
    for node in (analysts.fit_matcher, decide_price.price, writer, verifier, compliance):
        upd = await node(st)
        for k, v in upd.items():
            if k in ("evidence", "draft_history", "critiques", "approvals", "errors"):
                st[k] = (st.get(k) or []) + (v or [])
            elif k not in ("steps", "tokens", "usage", "timings"):
                st[k] = v
        if st.get("status") in ("dead_letter", "blocked", "needs_attention", "queued_degraded"):
            raise RuntimeError(st.get("status_reason"))
    return st["draft"]["cover_letter"], float(st.get("price_quote", {}).get("amount") or job["budget"]["max"] or 100)


def mcnemar(a: list[bool], b: list[bool]) -> dict:
    b01 = sum(1 for x, y in zip(a, b, strict=True) if not x and y)
    b10 = sum(1 for x, y in zip(a, b, strict=True) if x and not y)
    n = b01 + b10
    p = stats.binomtest(min(b01, b10), n, 0.5).pvalue if n else 1.0
    return {"A_only": b10, "B_only": b01, "p_value": round(float(p), 4)}


def two_prop(a: list[bool], b: list[bool]) -> dict:
    n1, n2, x1, x2 = len(a), len(b), sum(a), sum(b)
    p1, p2 = x1 / n1, x2 / n2
    pp = (x1 + x2) / (n1 + n2)
    se = math.sqrt(pp * (1 - pp) * (1 / n1 + 1 / n2)) or 1e-9
    z = (p1 - p2) / se
    fisher = stats.fisher_exact([[x1, n1 - x1], [x2, n2 - x2]])
    diff_se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    # jobs per arm needed to detect the observed difference with 80% power at alpha 0.05
    d = abs(p1 - p2)
    need = math.ceil(((1.96 * math.sqrt(2 * pp * (1 - pp)) + 0.84 * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) / d) ** 2) if d else None
    return {"rate_A": round(p1, 4), "rate_B": round(p2, 4), "diff": round(p1 - p2, 4),
            "ci95": [round(p1 - p2 - 1.96 * diff_se, 4), round(p1 - p2 + 1.96 * diff_se, 4)],
            "z": round(z, 3), "p_value_z": round(float(2 * (1 - stats.norm.cdf(abs(z)))), 4),
            "p_value_fisher": round(float(fisher.pvalue), 4), "n_per_arm_for_80pct_power": need}


async def run(per_persona: int) -> dict:
    rows = []
    async with env() as e:
        sim = e["sim"]
        for p in ["ai_ml_engineer", "fullstack_dev", "data_analyst"]:
            port = e["port_for"](p)
            for g in [g for g in load_gold(p) if g["job_type"] == "fit"][:per_persona]:
                job = await public_job(port, g["job_id"])
                out = {"persona": p, "job_id": g["job_id"]}
                for arm in ARMS:
                    try:
                        text, price = await write_one(job, p, arm)
                        from agent.marketplace_port import ProposalPayload

                        key = f"ab-{arm}-{p}-{g['job_id']}"
                        d = await port.create_proposal_draft(ProposalPayload(job_id=job["id"], cover_letter=text[:5000], bid_amount=price), key)
                        await port.submit_proposal(d.proposal_id, key + "-s")
                        sim.db.x("update proposals set decide_at=0 where id=?", (d.proposal_id,))
                        await sim._process_decisions()
                        o = json.loads(sim.db.one("select outcome from proposals where id=?", (d.proposal_id,))["outcome"] or "{}")
                        out[arm] = {"replied": bool(o.get("replied")), "score": o.get("score"), "words": len(text.split())}
                    except Exception as ex:  # noqa: BLE001
                        out[arm] = {"error": str(ex)[:160]}
                rows.append(out)
                print(p, g["job_id"], {a: out[a].get("replied", "err") for a in ARMS}, flush=True)
    ok = [r for r in rows if all("replied" in r[a] for a in ARMS)]
    A = [r[ARMS[0]]["replied"] for r in ok]
    B = [r[ARMS[1]]["replied"] for r in ok]
    res = {"arms": {"A": ARMS[0], "B": ARMS[1]}, "writer_model": llm.model_for("writer"), "grader": "GigSim heuristic (seeded)",
           "n_jobs": len(ok), "unpaired": two_prop(A, B), "paired_mcnemar": mcnemar(A, B),
           "mean_grade": {a: round(sum(r[a]["score"] for r in ok) / max(1, len(ok)), 4) for a in ARMS}}
    (ROOT / "evals" / "results" / "ab_experiment.json").write_text(json.dumps(res, indent=1))
    (ROOT / "evals" / "results" / "ab_experiment_rows.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-persona", type=int, default=10)
    asyncio.run(run(ap.parse_args().per_persona))
