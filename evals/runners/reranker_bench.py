"""Benchmark open cross-encoder rerankers on CPU: quality (Recall@5 after reranking the same
candidates) vs latency per pair. Writes evals/results/reranker_bench.json."""

from __future__ import annotations

import json
import statistics as st
import time
from pathlib import Path

from fastembed.rerank.cross_encoder import TextCrossEncoder

from evals.runners.rag_eval import load_gold, load_jobs, recall_at
from rag.index.store import PortfolioIndex
from rag.variants.pipeline import Flags, Pipeline, heuristic_requirements

ROOT = Path(__file__).resolve().parents[2]
MODELS = ["Xenova/ms-marco-MiniLM-L-6-v2", "jinaai/jina-reranker-v1-turbo-en", "BAAI/bge-reranker-v2-m3-int8"]


def main(n_jobs: int = 20, cand: int = 15, chars: int = 700) -> None:
    persona = "ai_ml_engineer"
    idx = PortfolioIndex()
    idx.build(persona)
    jobs = load_jobs()
    gold = [g for g in load_gold(persona) if g["action"] == "bid"][:n_jobs]
    base = Pipeline(idx, Flags(decompose=True, hybrid=True), "v2")
    base.cand_k = cand
    # identical candidate lists for every model
    cases = []
    for g in gold:
        j = jobs[g["job_id"]]
        reqs = heuristic_requirements(j["title"], j["description"])
        per = [(r["text"], base._search(persona, f"{r['text']} ({j['title']})", None)) for r in reqs]
        cases.append((g, per))
    out = {"persona": persona, "n_jobs": n_jobs, "candidates_per_requirement": cand, "doc_chars": chars, "models": {}}
    for name in MODELS:
        model = TextCrossEncoder(name)
        lat, recs, pairs = [], [], 0
        for g, per in cases:
            t0 = time.perf_counter()
            merged: list[tuple[str, float]] = []
            for text, cands in per:
                docs = [c.text[:chars] for c, _ in cands]
                scores = list(model.rerank(text, docs, batch_size=16)) if docs else []
                pairs += len(docs)
                ranked = sorted(zip([c.evidence_id for c, _ in cands], scores, strict=True), key=lambda t: -t[1])
                merged.append(ranked)
            lat.append(time.perf_counter() - t0)
            # round-robin merge (same as pipeline)
            ids, seen = [], set()
            while any(merged) and len(ids) < 10:
                for lst in merged:
                    while lst:
                        e, _ = lst.pop(0)
                        if e not in seen:
                            seen.add(e)
                            ids.append(e)
                            break
            recs.append(recall_at(ids, set(g["relevant_evidence"])))
        out["models"][name] = {"recall@5": round(st.mean(recs), 4), "p50_job_s": round(st.median(lat), 3),
                               "p95_job_s": round(sorted(lat)[int(0.95 * (len(lat) - 1))], 3),
                               "ms_per_pair": round(1000 * sum(lat) / max(1, pairs), 1)}
        print(name, out["models"][name], flush=True)
    (ROOT / "evals/results/reranker_bench.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
