"""Build blind pairwise panel items from the A/B experiment: for each job, the evidence_first (A)
and question_led (B) proposals that GigBid wrote. Reads the experiment's GigSim database (latest
eval temp dir containing A/B proposals). Writes evals/datasets/panel_pairs.json."""

from __future__ import annotations

import glob
import json
import os
import re
import sqlite3
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


CITE = re.compile(r"\s*\[[a-z_]+:[a-z_]+:[\w\-.#:]+\]")


def client_view(text: str) -> str:
    """What the client would actually read: evidence ids are internal and are stripped."""
    text = CITE.sub("", text)
    text = re.sub(r"(^|\n|(?<=[.!?])\s)\W*\w{0,3}\.(?=\s|$)", r"\1", text)  # stray fragments like "At."
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def main() -> None:
    dbs = sorted(glob.glob(os.path.join(tempfile.gettempdir(), "gigbid-eval-*", "sim.sqlite")), key=os.path.getmtime, reverse=True)
    jobs = {json.loads(x)["id"]: json.loads(x) for x in (ROOT / "data" / "gigsim_seed" / "jobs.jsonl").read_text().splitlines()}
    for path in dbs:
        c = sqlite3.connect(path)
        rows = c.execute("select key, response from idempotency where key like 'ab-%' and endpoint='create_proposal'").fetchall()
        if not rows:
            continue
        by: dict[str, dict] = {}
        for key, resp in rows:
            _, arm, rest = key.split("-", 2)
            pid = json.loads(resp)["id"]
            data = json.loads(c.execute("select data from proposals where id=?", (pid,)).fetchone()[0])
            job_id = data["job_id"]
            by.setdefault(job_id, {})["question_led" if arm.startswith("question") else "evidence_first"] = data["cover_letter"]
        pairs = []
        for job_id, arms in by.items():
            if len(arms) == 2:
                j = jobs[job_id]
                pairs.append({"pair_id": f"ab-{job_id}", "job_title": j["title"], "job_description": j["description"],
                              "a_label": "evidence_first", "b_label": "question_led",
                              "a_text": client_view(arms["evidence_first"]), "b_text": client_view(arms["question_led"])})
        out = ROOT / "evals" / "datasets" / "panel_pairs.json"
        out.write_text(json.dumps(pairs, indent=1))
        print(f"wrote {len(pairs)} panel pairs from {path} -> {out}")
        return
    print("no A/B experiment database found; run evals.runners.ab_experiment first")


if __name__ == "__main__":
    main()
