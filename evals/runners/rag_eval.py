"""B4 retrieval evaluation: evidence Recall@5, MRR, nDCG@10 per variant and persona.

Usage:
  uv run python -m evals.runners.rag_eval --variants v0_naive v1_decompose ... [--personas ...] [--limit N]
Writes evals/results/rag_retrieval.json (+ per-job rows in rag_retrieval_rows.jsonl).

Metric definitions (documented in the report):
  Recall@5  = |top5 ∩ gold| / min(5, |gold|)       (capped so a perfect top-5 scores 1.0)
  MRR       = 1 / rank of the first gold item (0 if none in top 10)
  nDCG@10   = binary-relevance DCG@10 / ideal DCG@10 with min(10, |gold|) relevant items
Only `bid` jobs (the ones a proposal is written for) have gold evidence.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics as st
import time
from pathlib import Path

from rag.index.store import PortfolioIndex
from rag.retriever import build
from rag.variants.pipeline import Query

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "evals" / "results"
PERSONAS = ["ai_ml_engineer", "fullstack_dev", "data_analyst"]
ALL = ["v0_naive", "v1_decompose", "v2_hybrid", "v3_rerank", "v4_outcome", "v5_multivector",
       "v6_contextual", "v7_hyde", "v8_corrective"]


def recall_at(ids: list[str], gold: set[str], k: int = 5) -> float:
    return len(set(ids[:k]) & gold) / min(k, len(gold)) if gold else 0.0


def mrr(ids: list[str], gold: set[str], k: int = 10) -> float:
    for i, e in enumerate(ids[:k]):
        if e in gold:
            return 1 / (i + 1)
    return 0.0


def ndcg(ids: list[str], gold: set[str], k: int = 10) -> float:
    dcg = sum(1 / math.log2(i + 2) for i, e in enumerate(ids[:k]) if e in gold)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(k, len(gold))))
    return dcg / ideal if ideal else 0.0


def load_jobs() -> dict[str, dict]:
    with open(ROOT / "data" / "gigsim_seed" / "jobs.jsonl") as fh:
        return {j["id"]: j for j in map(json.loads, fh)}


def load_gold(persona: str, split: str = "dev") -> list[dict]:
    path = ROOT / "evals" / "datasets" / (f"dev_{persona}.jsonl" if split == "dev" else f"hidden/hidden_{persona}.jsonl")
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def hyde_texts() -> dict[str, str]:
    p = ROOT / "data" / "derived" / "hyde_texts.json"
    return json.loads(p.read_text()) if p.exists() else {}


def context_lines(persona: str) -> dict[str, str]:
    p = ROOT / "data" / "derived" / f"context_lines_{persona}.json"
    return json.loads(p.read_text()) if p.exists() else {}


def build_indexes(personas: list[str], contextual: bool) -> PortfolioIndex:
    idx = PortfolioIndex()
    for p in personas:
        idx.build(p, context_lines=context_lines(p) if contextual else None)
    return idx


def run(variants: list[str], personas: list[str], limit: int | None, out_name: str = "rag_retrieval") -> dict:
    jobs = load_jobs()
    hyde = hyde_texts()
    plain = build_indexes(personas, contextual=False)
    ctx_idx = None
    summary: dict = {"metric_definitions": __doc__.split("Metric definitions")[1].strip(), "variants": {}}
    rows = []
    for v in variants:
        if v == "v6_contextual" and ctx_idx is None:
            ctx_idx = build_indexes(personas, contextual=True)
        idx = ctx_idx if v == "v6_contextual" else plain
        retr = build(v, idx)
        per: dict = {}
        for p in personas:
            gold = [g for g in load_gold(p) if g["action"] == "bid" and g["relevant_evidence"]][: limit or None]
            m = {"recall@5": [], "mrr": [], "ndcg@10": [], "latency_s": []}
            for g in gold:
                j = jobs[g["job_id"]]
                q = Query(j["title"], j["description"], hyde_text=hyde.get(j["id"]) if v == "v7_hyde" else None)
                t0 = time.perf_counter()
                res = retr.retrieve(p, q, 10)
                dt = time.perf_counter() - t0
                ids = res.ids
                G = set(g["relevant_evidence"])
                r5, rr, nd = recall_at(ids, G), mrr(ids, G), ndcg(ids, G)
                for k, val in zip(["recall@5", "mrr", "ndcg@10", "latency_s"], [r5, rr, nd, dt], strict=True):
                    m[k].append(val)
                rows.append({"variant": v, "persona": p, "job_id": g["job_id"], "n_req": len(g["requirements"]),
                             "job_type": g["job_type"], "recall@5": r5, "mrr": rr, "ndcg@10": nd, "latency_s": round(dt, 3),
                             "top5": ids[:5], "unsupported_requirements": res.unsupported_requirements})
            per[p] = {"n": len(gold), **{k: round(st.mean(vals), 4) for k, vals in m.items() if k != "latency_s"},
                      "p50_latency_s": round(st.median(m["latency_s"]), 3),
                      "p95_latency_s": round(sorted(m["latency_s"])[int(0.95 * (len(m["latency_s"]) - 1))], 3)}
            print(f"{v:16s} {p:15s} R@5={per[p]['recall@5']:.3f} MRR={per[p]['mrr']:.3f} nDCG={per[p]['ndcg@10']:.3f} p95={per[p]['p95_latency_s']}s", flush=True)
        allr = [r for r in rows if r["variant"] == v]
        per["all"] = {k: round(st.mean(r[k] for r in allr), 4) for k in ["recall@5", "mrr", "ndcg@10"]}
        per["all"]["n"] = len(allr)
        many = [r for r in allr if r["n_req"] >= 4]
        per["all"]["recall@5_4plus_requirements"] = round(st.mean(r["recall@5"] for r in many), 4) if many else None
        per["all"]["n_4plus_requirements"] = len(many)
        summary["variants"][v] = per
    RESULTS.mkdir(parents=True, exist_ok=True)
    existing = {}
    out = RESULTS / f"{out_name}.json"
    if out.exists():
        existing = json.loads(out.read_text()).get("variants", {})
    summary["variants"] = {**existing, **summary["variants"]}
    out.write_text(json.dumps(summary, indent=1))
    with open(RESULTS / f"{out_name}_rows.jsonl", "a") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", nargs="+", default=ALL)
    ap.add_argument("--personas", nargs="+", default=PERSONAS)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default="rag_retrieval")
    a = ap.parse_args()
    run(a.variants, a.personas, a.limit, a.out)
