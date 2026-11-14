import importlib
import re as _re

import httpx
import pytest


@pytest.fixture()
def gigsim_port(tmp_path, monkeypatch):
    """GigSim app in-process (ASGI transport) behind the real GigSim adapter."""
    monkeypatch.setenv("GIGSIM_DB", str(tmp_path / "sim.sqlite"))
    monkeypatch.setenv("GIGSIM_SEED_DIR", str(tmp_path / "none"))  # tiny sample seed
    monkeypatch.setenv("GIGSIM_API_TOKEN", "tok")
    monkeypatch.setenv("GIGSIM_ADMIN_TOKEN", "adm")
    monkeypatch.setenv("GIGSIM_ERROR_RATE", "0")
    monkeypatch.setenv("GIGSIM_POST_COMMIT_ERROR_RATE", "0")
    monkeypatch.setenv("GIGSIM_GRADER", "heuristic")
    monkeypatch.setenv("GIGSIM_DISABLE_LOOP", "1")
    monkeypatch.setenv("GIGSIM_RATE_LIMIT_PER_MIN", "1000")
    import gigsim.app as sim

    sim = importlib.reload(sim)
    from gigsim.seed import ensure_seeded

    ensure_seeded(sim.db, sim.SEED_DIR, "tok")
    from mcp_servers.marketplace.adapters import gigsim as ad

    ad.BREAKER.success()
    port = ad.GigSimAdapter(token="tok.ai_ml_engineer", base_url="http://gigsim",
                            transport=httpx.ASGITransport(app=sim.app), max_retries=4)
    port.sim = sim
    return port


@pytest.fixture()
def mserver(gigsim_port, tmp_path, monkeypatch):
    from mcp_servers.common import AuditLog
    from mcp_servers.marketplace import server

    monkeypatch.setattr(server, "_port_override", gigsim_port)
    monkeypatch.setattr(server, "AUDIT", AuditLog(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(server, "IDEM", server.IdempotencyStore(tmp_path / "idem.sqlite"))
    return server


# --------------------------------------------------------------------------- graph test helpers



from agent.testing import FakeLLM  # noqa: E402,F401  (re-exported for tests)


@pytest.fixture()
def fake_llm(monkeypatch):
    import agent.llm as llm

    f = FakeLLM()
    monkeypatch.setattr(llm, "complete", f)
    return f


@pytest.fixture(scope="session")
def ai_index():
    from rag.index.store import PortfolioIndex

    idx = PortfolioIndex()
    idx.build("ai_ml_engineer")
    return idx


@pytest.fixture()
def graph_env(mserver, ai_index, monkeypatch, tmp_path):
    """In-process MCP servers + GigSim + portfolio index, lexical reranker, no external calls."""
    from mcp_servers.portfolio import server as pserver
    from mcp_servers.workspace import server as wserver
    from mcp_servers.workspace.store import WorkspaceStore

    monkeypatch.setenv("MCP_TRANSPORT", "inprocess")
    monkeypatch.setenv("PORTFOLIO_PERSONA", "ai_ml_engineer")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(pserver.service, "_index", ai_index)
    monkeypatch.setattr(pserver.service, "variant", "v2_hybrid")
    monkeypatch.setattr(wserver, "STORE", WorkspaceStore(tmp_path / "ws.sqlite"))

    def lexical_rerank(query, docs):
        q = set(_re.findall(r"[a-z]{3,}", query.lower()))
        return [4 * len(q & set(_re.findall(r"[a-z]{3,}", d.lower()))) / max(1, len(q)) - 1 for d in docs]

    import rag.index.embed as emb

    monkeypatch.setattr(emb, "rerank", lexical_rerank)
    return mserver
