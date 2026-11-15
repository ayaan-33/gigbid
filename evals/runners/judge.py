"""LLM judge (rubric 1-5) + calibration against human labels (Cohen's kappa).

  uv run python -m evals.runners.judge sample      # pick 30 items -> evals/datasets/judge_items.jsonl
  uv run python -m evals.runners.judge score       # LLM judge scores them -> evals/results/judge_scores.json
  uv run python -m evals.runners.judge label       # YOU label the same 30 in the terminal (~20 min)
  uv run python -m evals.runners.judge kappa       # Cohen's kappa (linear-weighted) judge vs you

Items are proposals for real job posts (past proposals from the persona corpora with varied
outcomes, plus GigBid drafts from the A/B experiment when available), shown blind (no outcome,
no system name).
"""

from __future__ import annotations

import asyncio
import json
import random
import sys
from pathlib import Path

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
ITEMS = ROOT / "evals" / "datasets" / "judge_items.jsonl"
SCORES = ROOT / "evals" / "results" / "judge_scores.json"
LABELS = ROOT / "evals" / "datasets" / "judge_labels_human.json"
OUT = ROOT / "evals" / "results" / "judge_calibration.json"
CRITERIA = ["relevance", "specificity", "personalisation", "clarity", "credibility"]


class JudgeScore(BaseModel):
    relevance: int = Field(ge=1, le=5)
    specificity: int = Field(ge=1, le=5)
    personalisation: int = Field(ge=1, le=5)
    clarity: int = Field(ge=1, le=5)
    credibility: int = Field(ge=1, le=5)
    overall: int = Field(ge=1, le=5)
    reason: str = ""


async def judge(job_title: str, job_desc: str, proposal: str) -> JudgeScore:
    from agent.guardrails import spotlight
    from agent.llm import structured
    from agent.prompts import load_prompt

    p = load_prompt("judge")
    user = f"JOB: {job_title}\n{job_desc[:1500]}\n\n" + spotlight("proposal", proposal)
    return await structured("judge", p.text, user, JudgeScore)


def sample(n: int = 30) -> None:
    rng = random.Random(30)
    jobs = {}
    for line in (ROOT / "data" / "processed" / "real_jobs.jsonl").open() if (ROOT / "data/processed/real_jobs.jsonl").exists() else []:
        j = json.loads(line)
        jobs[j["id"]] = j
    items = []
    for pid in ["ai_ml_engineer", "fullstack_dev", "data_analyst"]:
        props = [json.loads(x) for x in (ROOT / "data" / "personas" / pid / "proposals.jsonl").read_text().splitlines()]
        by = {o: [p for p in props if p["outcome"] == o] for o in ("won", "replied", "ignored")}
        pick = rng.sample(by["won"], 3) + rng.sample(by["replied"], 3) + rng.sample(by["ignored"], 4)
        for p in pick:
            j = jobs.get(p["job_source_id"], {})
            items.append({"item_id": p["id"], "job_title": p["job_title"], "job_desc": (j.get("description") or "")[:1200],
                          "proposal": p["text"], "hidden_outcome": p["outcome"]})
    rng.shuffle(items)
    ITEMS.write_text("".join(json.dumps(i) + "\n" for i in items[:n]))
    print(f"wrote {min(n, len(items))} judge items -> {ITEMS}")


async def score() -> None:
    items = [json.loads(x) for x in ITEMS.read_text().splitlines()]
    out = {}
    for it in items:
        try:
            s = await judge(it["job_title"], it["job_desc"], it["proposal"])
        except Exception as e:  # noqa: BLE001
            print("judge failed", it["item_id"], str(e)[:120], flush=True)
            continue
        out[it["item_id"]] = s.model_dump()
        print(it["item_id"], s.overall, flush=True)
    SCORES.write_text(json.dumps(out, indent=1))


def label() -> None:
    items = [json.loads(x) for x in ITEMS.read_text().splitlines()]
    done = json.loads(LABELS.read_text()) if LABELS.exists() else {}
    print("\nRate each proposal 1-5 as the CLIENT who posted the job: would you reply? (5 = definitely)")
    print("Blind: you do not see the outcome or the AI judge's score. Type q to stop; progress is saved.\n")
    for k, it in enumerate(items, 1):
        if it["item_id"] in done:
            continue
        print("=" * 80)
        print(f"[{k}/{len(items)}] JOB: {it['job_title']}\n{it['job_desc'][:600]}\n")
        print("PROPOSAL:\n" + it["proposal"] + "\n")
        while True:
            v = input("Your overall score 1-5 (q to quit): ").strip().lower()
            if v == "q":
                LABELS.write_text(json.dumps(done, indent=1))
                print(f"saved {len(done)} labels")
                return
            if v in {"1", "2", "3", "4", "5"}:
                done[it["item_id"]] = int(v)
                LABELS.write_text(json.dumps(done, indent=1))
                break
    print(f"all {len(done)} items labelled -> {LABELS}")


def kappa() -> None:
    from scipy.stats import spearmanr
    from sklearn.metrics import cohen_kappa_score

    human = json.loads(LABELS.read_text())
    llm = json.loads(SCORES.read_text())
    ids = sorted(set(human) & set(llm))
    h = [human[i] for i in ids]
    m = [llm[i]["overall"] for i in ids]
    items = {json.loads(x)["item_id"]: json.loads(x) for x in ITEMS.read_text().splitlines()}
    rank = {"won": 3, "replied": 2, "ignored": 1}
    out = {"n": len(ids), "cohen_kappa_linear": round(float(cohen_kappa_score(h, m, weights="linear")), 4),
           "cohen_kappa_unweighted": round(float(cohen_kappa_score(h, m)), 4),
           "exact_agreement": round(sum(a == b for a, b in zip(h, m, strict=True)) / len(ids), 4),
           "within_one": round(sum(abs(a - b) <= 1 for a, b in zip(h, m, strict=True)) / len(ids), 4),
           "spearman_judge_vs_outcome": round(float(spearmanr(m, [rank[items[i]["hidden_outcome"]] for i in ids])[0]), 4),
           "spearman_human_vs_outcome": round(float(spearmanr(h, [rank[items[i]["hidden_outcome"]] for i in ids])[0]), 4),
           "mean_human": round(sum(h) / len(h), 3), "mean_judge": round(sum(m) / len(m), 3)}
    OUT.write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "score"
    {"sample": sample, "label": label, "kappa": kappa}.get(cmd, lambda: asyncio.run(score()))()
