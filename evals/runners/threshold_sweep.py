"""Choose `thresholds.minimum_fit_score` by measurement (ADR 0005).

Re-applies the deterministic decision rule (agent/nodes/decide_price.decide) to the per-job rows of
the 600-job dev decision eval for each candidate threshold:
  skip if scam  ->  skip if budget below the persona's floor  ->  bid if fit >= t  ->  else skip
(with rules-only risk a non-scam job never exceeds the risk limit, see risk_signals). Picks the
threshold with the best bid/skip F1 across personas. Writes evals/results/threshold_sweep.json.
"""

from __future__ import annotations

import json
from pathlib import Path

from sklearn.metrics import f1_score, precision_score, recall_score

from scripts.data.archetypes import PERSONAS

ROOT = Path(__file__).resolve().parents[2]


def main(tag: str = "dev_rules") -> None:
    rows = [json.loads(x) for x in (ROOT / "evals" / "results" / f"decision_eval_{tag}_rows.jsonl").read_text().splitlines()]
    jobs = {json.loads(x)["id"]: json.loads(x) for x in (ROOT / "data" / "gigsim_seed" / "jobs.jsonl").read_text().splitlines()}
    out = {"source": f"decision_eval_{tag}_rows.jsonl", "sweep": []}
    for t in [round(0.20 + 0.025 * i, 3) for i in range(17)]:
        y, yh = [], []
        for r in rows:
            if r.get("duplicate_caught"):
                continue
            per = PERSONAS[r["persona"]]
            b = jobs[r["job_id"]]["budget"]
            floor = per["fixed_floor"] if b.get("type", "fixed") == "fixed" else per["hourly_rate"] * 0.7
            if r["pred_scam"] or (b.get("max") or 0) < floor:
                pred = False
            else:
                pred = (r.get("fit") or 0) >= t
            y.append(r["gold"] == "bid")
            yh.append(pred)
        out["sweep"].append({"threshold": t, "f1": round(f1_score(y, yh), 4), "precision": round(precision_score(y, yh, zero_division=0), 4),
                             "recall": round(recall_score(y, yh), 4)})
    best = max(out["sweep"], key=lambda r: (r["f1"], r["precision"]))
    out["best"] = best
    (ROOT / "evals" / "results" / "threshold_sweep.json").write_text(json.dumps(out, indent=1))
    for r in out["sweep"]:
        print(r)
    print("BEST", best)


if __name__ == "__main__":
    main()
