"""`make eval`: run every evaluation in sequence (CPU-heavy steps one at a time) and regenerate the
README tables. Free-tier note: LLM-heavy runs (judge, injection, A/B, proposal, R&D C) use the
LLM cache, so re-runs are cheap; a cold run needs ~1-2 days of free Groq quota or the local profile.
"""

import subprocess
import sys

STEPS = [
    ["evals.runners.rag_eval"],
    ["evals.runners.ablation", "--limit", "30"],
    ["evals.runners.decision_eval", "--tag", "dev_rules"],
    ["evals.runners.claim_eval", "--mode", "heuristic"],
    ["evals.runners.injection_eval"],
    ["evals.runners.tool_granularity"],
    ["evals.runners.judge", "score"],
    ["evals.runners.proposal_eval"],
    ["evals.runners.ab_experiment", "--per-persona", "8"],
    ["evals.runners.multiagent_compare", "--per-persona", "8"],
]


def main() -> int:
    for step in STEPS:
        print(">>", " ".join(step), flush=True)
        r = subprocess.run([sys.executable, "-m", *step])
        if r.returncode:
            print("step failed:", step)
            return r.returncode
    return subprocess.run([sys.executable, "-m", "scripts.make_readme_tables"]).returncode


if __name__ == "__main__":
    sys.exit(main())
