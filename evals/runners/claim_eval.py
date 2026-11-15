"""B3 claim verification eval on the labelled claim set: unsupported-claim rate before and after
verification, and per-label accuracy of the verifier.

  --mode heuristic : deterministic checker only (CI)
  --mode llm       : batched LLM verifier + deterministic number gate (open profile)
Writes evals/results/claim_eval_<mode>.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from rag.index.store import PortfolioIndex
from rag.verify import verify_claims_async

ROOT = Path(__file__).resolve().parents[2]


async def run(mode: str, limit: int | None) -> dict:
    rows = [json.loads(x) for x in (ROOT / "evals" / "datasets" / "claim_set.jsonl").read_text().splitlines()][: limit or None]
    idx = PortfolioIndex()
    built: set[str] = set()
    tot = {"claims": 0, "unsupported_before": 0, "unsupported_after": 0, "fabricated_kept": 0, "tampered_kept_unchanged": 0}
    correct = {"supported": [0, 0], "partly_supported": [0, 0], "unsupported": [0, 0]}
    for r in rows:
        if r["persona"] not in built:
            idx.build(r["persona"])
            built.add(r["persona"])
        chunks = {c.evidence_id: c for c in idx.chunks(r["persona"])}

        def lookup(eid: str, _c=chunks, _p=r["persona"]):
            return " ".join(c.text for c in idx.item_chunks(_p, eid)) or None

        text, rep = await verify_claims_async(r["draft"], lookup, None, use_llm=("batch" if mode == "llm" else False))
        gold = {c["text"]: c["label"] for c in r["claims"]}
        for c in rep.claims:
            g = gold.get(c.text)
            if not g:
                continue
            tot["claims"] += 1
            pred = c.label.value
            correct[g][1] += 1
            correct[g][0] += int(pred == g or (g == "unsupported" and c.action != "kept"))
            if g == "unsupported":
                tot["unsupported_before"] += 1
                if c.action == "kept":
                    tot["fabricated_kept"] += 1
            if g == "partly_supported" and c.action == "kept":
                tot["tampered_kept_unchanged"] += 1
        tot["unsupported_after"] += sum(1 for c in r["claims"] if c["label"] != "supported" and c["text"] in text)
    n = len(rows)
    out = {"mode": mode, "drafts": n, **tot,
           "unsupported_rate_before": round(tot["unsupported_before"] * 2 / max(1, tot["claims"]), 4),
           "unsupported_or_wrong_after_per_proposal": round(tot["unsupported_after"] / max(1, n), 4),
           "unsupported_before_per_proposal": round(2 * n / max(1, n), 4),
           "label_accuracy": {k: round(a / b, 4) if b else None for k, (a, b) in correct.items()}}
    (ROOT / "evals" / "results" / f"claim_eval_{mode}.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["heuristic", "llm"], default="heuristic")
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    asyncio.run(run(a.mode, a.limit))
