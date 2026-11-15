"""R&D question B: ablate the best retrieval pipeline one component at a time.

Best = V5 (requirement decomposition + hybrid BM25/dense RRF + cross-encoder rerank + multi-vector
projects). Each row removes (or adds) ONE component. Reported per persona and for jobs with >= 4
requirements (the hypothesis). Also measures V8's refusal behaviour: share of requirements it
marks unsupported on fit jobs vs low-fit jobs (it should refuse more on jobs to skip).
Writes evals/results/ablation.json
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from dataclasses import replace
from pathlib import Path

from evals.runners.rag_eval import load_gold, load_jobs, mrr, ndcg, recall_at
from rag.index.store import PortfolioIndex
from rag.variants.pipeline import Pipeline, Query
from rag.variants.presets import PRESETS

ROOT = Path(__file__).resolve().parents[2]
PERSONAS = ["ai_ml_engineer", "fullstack_dev", "data_analyst"]
BEST = PRESETS["v5_multivector"]
ROWS = {
    "best (V5)": BEST,
    "- multivector (=V3)": replace(BEST, multivector=False),
    "- rerank": replace(BEST, rerank=False),
    "- hybrid (dense only)": replace(BEST, hybrid=False),
    "- decomposition (whole post)": replace(BEST, decompose=False),
    "+ outcome boost": replace(BEST, outcome=True),
    "+ diversify": replace(BEST, diversify=True),
}


def main(limit: int) -> None:
    jobs = load_jobs()
    idx = PortfolioIndex()
    for p in PERSONAS:
        idx.build(p)
    out: dict = {"best": "v5_multivector", "jobs_per_persona": limit, "rows": {}}
    for name, flags in ROWS.items():
        pipe = Pipeline(idx, flags, name)
        res: dict = {}
        allr = []
        for p in PERSONAS:
            gold = [g for g in load_gold(p) if g["action"] == "bid"][:limit]
            rs = []
            for g in gold:
                j = jobs[g["job_id"]]
                ids = pipe.retrieve(p, Query(j["title"], j["description"]), 10).ids
                G = set(g["relevant_evidence"])
                rs.append({"r5": recall_at(ids, G), "mrr": mrr(ids, G), "nd": ndcg(ids, G), "nreq": len(g["requirements"])})
            res[p] = {"recall@5": round(st.mean(r["r5"] for r in rs), 4), "mrr": round(st.mean(r["mrr"] for r in rs), 4),
                      "ndcg@10": round(st.mean(r["nd"] for r in rs), 4)}
            allr += rs
        many = [r for r in allr if r["nreq"] >= 4]
        res["all"] = {"recall@5": round(st.mean(r["r5"] for r in allr), 4), "ndcg@10": round(st.mean(r["nd"] for r in allr), 4),
                      "recall@5_4plus_req": round(st.mean(r["r5"] for r in many), 4) if many else None, "n_4plus": len(many)}
        out["rows"][name] = res
        print(f"{name:28s} R@5 {res['all']['recall@5']:.3f} nDCG {res['all']['ndcg@10']:.3f} "
              f"| 4+req {res['all']['recall@5_4plus_req']}", flush=True)

    # V8 refusal behaviour
    from rag.retriever import build

    v8 = build("v8_corrective", idx)
    refuse: dict = {}
    for kind in ("fit", "lowfit"):
        fracs = []
        for p in PERSONAS:
            for g in [g for g in load_gold(p) if g["job_type"] == kind][: max(5, limit // 3)]:
                j = jobs[g["job_id"]]
                r = v8.retrieve(p, Query(j["title"], j["description"]), 5)
                n = max(1, len(r.per_requirement) + len(r.unsupported_requirements))
                fracs.append(len(r.unsupported_requirements) / n)
        refuse[kind] = round(st.mean(fracs), 4)
    out["v8_unsupported_requirement_share"] = refuse
    print("V8 refuses (share of requirements with no evidence):", refuse)
    (ROOT / "evals" / "results" / "ablation.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=30)
    main(ap.parse_args().limit)
