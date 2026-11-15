"""Labelled claim-verification set (B3 regression set). For sampled case studies, builds a short
draft whose sentences are, by construction:
  supported         - a result copied from the case study (exact number)
  partly_supported  - the same result with the number tampered
  unsupported       - an invented project (never in the portfolio)
Writes evals/datasets/claim_set.jsonl. Deterministic (seeded)."""

from __future__ import annotations

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FAKE = [
    "I also built a self-driving drone fleet controller for a defence contractor, cutting crashes by 64%.",
    "I previously led a 40-person blockchain team at a Fortune 500 bank.",
    "I trained a 70B-parameter language model from scratch for a national space agency.",
    "I designed the payment system used by over 30 million people in Europe.",
    "I won a Kaggle grandmaster title three years in a row.",
]


def main(per_persona: int = 10) -> None:
    rng = random.Random(7)
    rows = []
    for pid in ["ai_ml_engineer", "fullstack_dev", "data_analyst"]:
        prof = json.loads((ROOT / "data" / "personas" / pid / "profile.json").read_text())
        for proj in rng.sample(prof["projects"], k=per_persona):
            eid = f"{pid}:case:{proj['key']}"
            metric = proj["metrics_filled"][0]
            nums = [t for t in metric.replace("%", " %").split() if any(c.isdigit() for c in t)]
            tampered = metric
            if nums:
                n = nums[0]
                try:
                    tampered = metric.replace(n, str(int(float(n.rstrip("x")) * 2 + 7)), 1)
                except ValueError:
                    tampered = metric.replace(n, "99", 1)
            s_sup = f"For a {proj['industry']} client I delivered a {proj['names'][0].lower()}: {metric} [{eid}]."
            s_part = f"On that same {proj['names'][2]} project, {tampered} [{eid}]."
            s_un = rng.choice(FAKE)
            sentences = [(s_sup, "supported"), (s_part, "partly_supported"), (s_un, "unsupported")]
            rng.shuffle(sentences)
            draft = "You need this done right, without a long ramp-up.\n\n" + " ".join(s for s, _ in sentences) + \
                    "\n\nI would start with a short discovery call to agree the success metric."
            rows.append({"id": f"cs-{pid}-{proj['key']}", "persona": pid, "draft": draft, "evidence_id": eid,
                         "claims": [{"text": s, "label": lab} for s, lab in sentences]})
    out = ROOT / "evals" / "datasets" / "claim_set.jsonl"
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"wrote {len(rows)} drafts / {3 * len(rows)} labelled claims -> {out}")


if __name__ == "__main__":
    main()
