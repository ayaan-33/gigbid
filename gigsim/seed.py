"""Loads seed files into the GigSim database.

Seed directory layout (produced by `make seed`, see scripts/data/build_all.py):
  accounts.json         [{freelancer_id, name, connects}]
  clients.json          [{id, public: {...history...}, hidden: {...preferences...}}]
  jobs.jsonl            one job per line: {id, client_id, category, release_offset_min, ...public fields}
  historical_jobs.jsonl closed jobs with final_price (pricing statistics)

Account bearer token = f"{GIGSIM_API_TOKEN}.{freelancer_id}".
"""

from __future__ import annotations

import json
from pathlib import Path

from gigsim.db import DB

SAMPLE = Path(__file__).parent / "sample_seed"


def _load(seed_dir: Path) -> Path:
    return seed_dir if (seed_dir / "jobs.jsonl").exists() else SAMPLE


def ensure_seeded(db: DB, seed_dir: Path, secret: str) -> None:
    if db.one("select count(*) n from jobs")["n"] == 0:
        reseed(db, seed_dir, secret)


def reseed(db: DB, seed_dir: Path, secret: str) -> None:
    import time

    src = _load(seed_dir)
    with db.tx():
        for t in [
            "accounts",
            "clients",
            "jobs",
            "historical_jobs",
            "proposals",
            "idempotency",
            "connects_ledger",
            "conversations",
            "messages",
            "events",
            "sim",
        ]:
            db.conn.execute(f"delete from {t}")
        now = time.time()
        epoch = (
            json.loads((src / "meta.json").read_text())["sim_epoch"]
            if (src / "meta.json").exists()
            else now
        )
        db.conn.execute("insert into sim values ('real_start', ?)", (json.dumps(now),))
        db.conn.execute("insert into sim values ('sim_epoch', ?)", (json.dumps(epoch),))
        db.conn.execute("insert into sim values ('policy_version', '1')")
        for a in json.loads((src / "accounts.json").read_text()):
            db.conn.execute(
                "insert into accounts values (?,?,?,?)",
                (
                    f"{secret}.{a['freelancer_id']}",
                    a["freelancer_id"],
                    a.get("name"),
                    a.get("connects", 200),
                ),
            )
        for c in json.loads((src / "clients.json").read_text()):
            db.conn.execute(
                "insert into clients values (?,?,?)",
                (c["id"], json.dumps(c["public"]), json.dumps(c["hidden"])),
            )
        with open(src / "jobs.jsonl", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                j = json.loads(line)
                release = epoch + float(j.pop("release_offset_min", 0)) * 60
                jid, cid, cat = j.pop("id"), j.pop("client_id"), j.get("category", "other")
                db.conn.execute(
                    "insert into jobs(id,client_id,release_at,category,data,proposals_count) values (?,?,?,?,?,?)",
                    (jid, cid, release, cat, json.dumps(j), int(j.get("initial_proposals", 0))),
                )
        hist = src / "historical_jobs.jsonl"
        if hist.exists():
            with open(hist, encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        h = json.loads(line)
                        db.conn.execute(
                            "insert into historical_jobs values (?,?,?)",
                            (h.pop("id"), h.get("category"), json.dumps(h)),
                        )
