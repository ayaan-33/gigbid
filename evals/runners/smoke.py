"""CI smoke eval (E2): 30 dev jobs (10 per persona, stratified), no API keys needed.

  1. decisions  : graph front half with rules-only risk -> bid/skip F1, scam P/R
  2. retrieval  : shipped RAG variant Recall@5 on the smoke bid jobs
  3. claims     : deterministic claim verification on the labelled claim set
Fails (exit 1) if any metric crosses evals/thresholds.yaml. Writes evals/results/smoke_eval.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics as st
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


async def main(jobs: int) -> int:
    from agent.settings import cfg
    from evals.runners import claim_eval, decision_eval
    from evals.runners.rag_eval import load_gold, load_jobs, recall_at
    from rag.index.store import PortfolioIndex
    from rag.retriever import build
    from rag.variants.pipeline import Query

    per = max(1, jobs // 3)
    dec = await decision_eval.run(["ai_ml_engineer", "fullstack_dev", "data_analyst"], per, False, "smoke")
    claims = await claim_eval.run("heuristic", None)
    variant = cfg("rag.variant")
    idx = PortfolioIndex()
    allj = load_jobs()
    rec = []
    for p in ["ai_ml_engineer", "fullstack_dev", "data_analyst"]:
        idx.build(p)
        r = build(variant, idx)
        for g in [g for g in load_gold(p) if g["action"] == "bid"][: max(3, per // 2)]:
            j = allj[g["job_id"]]
            rec.append(recall_at(r.retrieve(p, Query(j["title"], j["description"]), 10).ids, set(g["relevant_evidence"])))
    out = {"jobs": dec["personas"]["all"]["n"], "decision": dec["personas"]["all"], "claims": claims,
           "retrieval": {"variant": variant, "recall@5": round(st.mean(rec), 4), "n": len(rec)}}
    th = yaml.safe_load((ROOT / "evals" / "thresholds.yaml").read_text())
    fails = []
    d, c = out["decision"], out["claims"]
    if th["decision"]["bid_skip_f1_min"] is not None and d["bid_skip_f1"] < th["decision"]["bid_skip_f1_min"]:
        fails.append(f"bid_skip_f1 {d['bid_skip_f1']} < {th['decision']['bid_skip_f1_min']}")
    if d["scam_recall"] < th["decision"]["scam_recall_min"]:
        fails.append(f"scam_recall {d['scam_recall']} < {th['decision']['scam_recall_min']}")
    if d["scam_precision"] < th["decision"]["scam_precision_min"]:
        fails.append(f"scam_precision {d['scam_precision']} < {th['decision']['scam_precision_min']}")
    if c["unsupported_or_wrong_after_per_proposal"] > th["claims"]["unsupported_after_per_proposal_max"]:
        fails.append(f"unsupported claims after verification {c['unsupported_or_wrong_after_per_proposal']} rose above "
                     f"{th['claims']['unsupported_after_per_proposal_max']}")
    if c["fabricated_kept"] > th["claims"]["fabricated_kept_max"]:
        fails.append(f"fabricated claims kept: {c['fabricated_kept']}")
    if out["retrieval"]["recall@5"] < th["retrieval"]["recall_at_5_min"]:
        fails.append(f"recall@5 {out['retrieval']['recall@5']} < {th['retrieval']['recall_at_5_min']}")
    out["thresholds"] = th
    out["failures"] = fails
    (ROOT / "evals" / "results" / "smoke_eval.json").write_text(json.dumps(out, indent=1))
    print("SMOKE EVAL", "FAILED" if fails else "PASSED", fails)
    return 1 if fails else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=30)
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.jobs)))
