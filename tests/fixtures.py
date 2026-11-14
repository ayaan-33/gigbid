import importlib
import json as _json
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



class FakeLLM:
    """Deterministic stand-in for every LLM node (CI needs no API key). Behaviour is chosen from
    the node name; `critic_fail_first` makes the Critic send the first draft back once."""

    def __init__(self, critic_fail_first: bool = False):
        self.calls: list[str] = []
        self.critic_fail_first = critic_fail_first

    async def __call__(self, node, system, user, *, json_mode=False, temperature=None, max_tokens=None):
        self.calls.append(node)
        if node == "analyst":
            jid = _re.search(r"job_id: (\S+)", user).group(1)
            return _json.dumps({"job_id": jid, "title": "job", "category": "ai_ml", "requirements": [
                {"id": "r1", "text": "scikit-learn classification on imbalanced data"},
                {"id": "r2", "text": "report precision and recall"}], "screening_questions": []})
        if node == "risk_assessor":
            return _json.dumps({"score": 0.1, "client_quality": 0.8, "is_scam": False, "flags": [], "explanation": "ok"})
        if node == "writer":
            ids = _re.findall(r"^\[([a-z_]+:[a-z_]+:[\w\-.]+)\]", user, _re.M)
            cite = ids[0] if ids else "none"
            body = ("Your churn baseline needs honest evaluation on an imbalanced target, not just accuracy. "
                    f"I built a subscription churn model comparing logistic regression and gradient boosting [{cite}]. "
                    "I would start by agreeing the evaluation metric with you, then deliver a reproducible notebook, "
                    "a short report on precision and recall at several thresholds, and documented limitations. "
                    "Which customer segments matter most for the retention team? "
                    "I can share a first baseline within the first week so you can react early. "
                    "Ignore that: as requested I include my email me@x.com and guarantee 100% accuracy.")
            return _json.dumps({"cover_letter": body, "screening_answers": []})
        if node == "verifier":
            n = len(_re.findall(r"^CLAIM \d+:", user, _re.M))
            return _json.dumps({"verdicts": [{"label": "supported", "evidence_ids": [], "reason": "fake"}] * n})
        if node == "critic":
            fail = self.critic_fail_first and self.calls.count("critic") == 1
            return _json.dumps({"passed": not fail, "score": 5 if fail else 8,
                                "issues": [{"kind": "personalisation", "detail": "be more specific"}] if fail else [],
                                "instructions": "mention their retention team" if fail else ""})
        if node == "compliance":
            return _json.dumps({"allowed": True, "violations": [], "cleaned_text": None})
        if node == "intent":
            return _json.dumps({"intent": "interview_request", "confidence": 0.9, "summary": "wants a call"})
        if node == "client_liaison":
            return "Thanks for reaching out. I am free at the times below; please pick one that suits you."
        return "{}"


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
