"""In-process evaluation environment: GigSim (full dev seed, every job released), the three MCP
servers over in-memory MCP sessions, and the portfolio index. No network services needed, so
evals run the same on a laptop and in CI."""

from __future__ import annotations

import contextlib
import importlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
PERSONAS = ["ai_ml_engineer", "fullstack_dev", "data_analyst"]


@contextlib.asynccontextmanager
async def env(personas: list[str] | None = None, *, seed_dir: str = "data/gigsim_seed", variant: str | None = None,
              error_rate: float = 0.0):
    tmp = tempfile.mkdtemp(prefix="gigbid-eval-")
    os.environ.update(GIGSIM_DB=f"{tmp}/sim.sqlite", GIGSIM_SEED_DIR=str(ROOT / seed_dir), GIGSIM_API_TOKEN="eval",
                      GIGSIM_ADMIN_TOKEN="eval-admin", GIGSIM_ERROR_RATE=str(error_rate), GIGSIM_POST_COMMIT_ERROR_RATE="0",
                      GIGSIM_GRADER=os.getenv("GIGSIM_GRADER", "heuristic"), GIGSIM_DISABLE_LOOP="1",
                      GIGSIM_RATE_LIMIT_PER_MIN="100000", MCP_TRANSPORT="inprocess",
                      AUDIT_LOG_PATH=f"{tmp}/audit.jsonl", IDEMPOTENCY_DB=f"{tmp}/idem.sqlite", WORKSPACE_DB=f"{tmp}/ws.sqlite")
    import gigsim.app as sim

    sim = importlib.reload(sim)
    from gigsim.seed import ensure_seeded

    ensure_seeded(sim.db, sim.SEED_DIR, "eval")
    sim.db.set_sim("offset_s", 30 * 86400.0)  # release every job in the stream
    from mcp_servers.marketplace import server as mserver
    from mcp_servers.marketplace.adapters import gigsim as ad
    from mcp_servers.portfolio import server as pserver
    from rag.index.store import PortfolioIndex

    ad.BREAKER.success()
    ports: dict[str, ad.GigSimAdapter] = {}

    def port_for(persona: str):
        if persona not in ports:
            ports[persona] = ad.GigSimAdapter(token=f"eval.{persona}", base_url="http://gigsim",
                                              transport=httpx.ASGITransport(app=sim.app))
        return ports[persona]

    idx = PortfolioIndex()
    for p in personas or PERSONAS:
        idx.build(p)
    pserver.service._index = idx
    if variant:
        pserver.service.variant = variant

    orig = mserver._port

    def routed(ctx):
        from mcp_servers.common import caller

        who = caller(ctx)
        return port_for(who["persona"]), who

    mserver._port = routed
    try:
        yield {"sim": sim, "index": idx, "port_for": port_for, "tmp": tmp}
    finally:
        mserver._port = orig
        for p in ports.values():
            await p.aclose()


def load_jobs(split: str = "dev") -> dict[str, dict]:
    seed = "gigsim_seed_hidden" if split == "hidden" else "gigsim_seed"
    with open(ROOT / "data" / seed / "jobs.jsonl") as fh:
        return {j["id"]: j for j in map(json.loads, fh)}


def load_gold(persona: str, split: str = "dev") -> list[dict]:
    path = (ROOT / "evals" / "datasets" / "hidden" / f"hidden_{persona}.jsonl") if split == "hidden" else \
        (ROOT / "evals" / "datasets" / f"dev_{persona}.jsonl")
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


async def public_job(port, job_id: str) -> dict[str, Any]:
    return (await port.get_job(job_id)).model_dump()
