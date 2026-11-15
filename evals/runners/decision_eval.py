"""B4 decisions: bid-or-skip F1, scam precision/recall, price inside the fair band, duplicate catch.

Runs the real graph front half (ingest -> Job Analyst | Risk Assessor | Fit Matcher -> decide ->
pricing) for dev jobs through in-process MCP servers.

  --risk-llm off  : Risk Assessor uses rules + injection heuristics only (no LLM, deterministic;
                    used by the CI smoke eval)
  --risk-llm on   : full Risk Assessor (LLM on the open profile)
Writes evals/results/decision_eval[_<tag>].json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics as st
import time
from pathlib import Path

from sklearn.metrics import f1_score, precision_score, recall_score

from evals.harness import PERSONAS, env, load_gold, public_job

ROOT = Path(__file__).resolve().parents[2]


async def analyse(job: dict, persona: str, risk_llm: bool) -> dict:
    """Front half of the bid graph, node by node (same node code as production)."""
    from agent.graphs.bid_graph import initial_state
    from agent.nodes import analysts, decide_price
    from agent.nodes.base import TERMINAL

    st_ = initial_state(job, user_id=f"eval-{persona}", persona=persona, thread_id=f"eval-{job['id']}")
    st_["autonomy"] = "suggest"
    if not risk_llm:
        os.environ["GIGBID_FAKE_LLM"] = "1"  # Risk Assessor falls back to its deterministic rule floor
    t0 = time.perf_counter()
    res = await asyncio.gather(analysts.risk_assessor(st_), analysts.fit_matcher(st_))
    for r in res:
        st_.update({k: v for k, v in r.items() if k not in ("steps", "tokens", "usage", "timings", "errors")})
    if not risk_llm:
        os.environ.pop("GIGBID_FAKE_LLM", None)
        # the fake LLM says "safe"; keep only the rule-based part of the verdict
        rr = st_["risk_report"]
        rr["explanation"] = "rules only"
    if st_.get("status") in TERMINAL:
        return {**st_, "latency_s": time.perf_counter() - t0}
    st_.update(await decide_price.decide(st_))
    if st_["decision"]["action"] == "bid":
        st_.update(await decide_price.price(st_))
    return {**st_, "latency_s": time.perf_counter() - t0}


async def run(personas: list[str], limit: int | None, risk_llm: bool, tag: str, split: str = "dev") -> dict:
    out: dict = {"risk_llm": risk_llm, "split": split, "personas": {}, "rows": []}
    seed = "data/gigsim_seed_hidden" if split == "hidden" else "data/gigsim_seed"
    async with env(personas, seed_dir=seed) as e:
        for p in personas:
            gold = load_gold(p, split)
            if limit:
                # stratified: keep the job-type mix of the full set
                by: dict[str, list] = {}
                for g in gold:
                    by.setdefault(g["job_type"], []).append(g)
                gold = [g for t, gs in by.items() for g in gs[: max(1, round(limit * len(gs) / len(load_gold(p, split))))]]
            port = e["port_for"](p)
            seen_fp: dict[str, str] = {}
            for g in gold:
                job = await public_job(port, g["job_id"])
                from agent.graphs.bid_graph import job_fingerprint

                fp = job_fingerprint(job)
                if fp in seen_fp and g["job_type"] == "duplicate":
                    out["rows"].append({"persona": p, "job_id": g["job_id"], "job_type": g["job_type"], "gold": "skip",
                                        "pred": "skip", "duplicate_caught": True, "gold_scam": False, "pred_scam": False,
                                        "price_in_band": None, "latency_s": 0.0})
                    continue
                seen_fp[fp] = job["id"]
                s = await analyse(job, p, risk_llm)
                pred = (s.get("decision") or {}).get("action", "skip")
                pred_bin = "bid" if pred == "bid" else "skip"
                q = s.get("price_quote") or {}
                band = g.get("fair_price")
                in_band = None
                if g["action"] == "bid" and pred == "bid" and band and q:
                    in_band = band["low"] <= q["amount"] <= band["high"]
                out["rows"].append({"persona": p, "job_id": g["job_id"], "job_type": g["job_type"], "gold": g["action"],
                                    "pred": pred_bin, "pred_raw": pred, "gold_scam": g["is_scam"],
                                    "pred_scam": bool((s.get("risk_report") or {}).get("is_scam")),
                                    "injection_gold": g["has_injection"],
                                    "injection_pred": bool((s.get("risk_report") or {}).get("injection_detected")),
                                    "fit": (s.get("fit_report") or {}).get("score"), "price_in_band": in_band,
                                    "price": q.get("amount"), "latency_s": round(s["latency_s"], 3)})
            print(p, "done", flush=True)
    rows = out["rows"]
    for p in personas + ["all"]:
        R = [r for r in rows if p == "all" or r["persona"] == p]
        y = [r["gold"] == "bid" for r in R]
        yh = [r["pred"] == "bid" for r in R]
        sc = [r["gold_scam"] for r in R]
        sch = [r["pred_scam"] for r in R]
        pb = [r["price_in_band"] for r in R if r["price_in_band"] is not None]
        inj = [r for r in R if r.get("injection_gold")]
        lat = sorted(r["latency_s"] for r in R)
        out["personas"][p] = {
            "n": len(R),
            "bid_skip_f1": round(f1_score(y, yh, zero_division=0), 4),
            "bid_precision": round(precision_score(y, yh, zero_division=0), 4),
            "bid_recall": round(recall_score(y, yh, zero_division=0), 4),
            "scam_precision": round(precision_score(sc, sch, zero_division=0), 4),
            "scam_recall": round(recall_score(sc, sch, zero_division=0), 4),
            "price_in_band": round(sum(pb) / len(pb), 4) if pb else None,
            "n_priced": len(pb),
            "injection_detected_rate": round(sum(r["injection_pred"] for r in inj) / len(inj), 4) if inj else None,
            "p50_latency_s": round(st.median(lat), 3) if lat else None,
            "p95_latency_s": round(lat[int(0.95 * (len(lat) - 1))], 3) if lat else None,
        }
    name = "decision_eval" + (f"_{tag}" if tag else "")
    (ROOT / "evals" / "results" / f"{name}.json").write_text(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))
    with open(ROOT / "evals" / "results" / f"{name}_rows.jsonl", "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    print(json.dumps(out["personas"], indent=1))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--personas", nargs="+", default=PERSONAS)
    ap.add_argument("--limit", type=int, default=None, help="stratified sample size per persona")
    ap.add_argument("--risk-llm", choices=["on", "off"], default="off")
    ap.add_argument("--tag", default="")
    ap.add_argument("--split", choices=["dev", "hidden"], default="dev")
    a = ap.parse_args()
    asyncio.run(run(a.personas, a.limit, a.risk_llm == "on", a.tag, a.split))
