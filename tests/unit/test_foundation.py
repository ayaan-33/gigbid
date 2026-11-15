from fastapi.testclient import TestClient

from agent import llm
from agent.handoffs import Claim, ClaimLabel, ClaimReport, EvidenceRef, FitReport, RequirementMatch
from agent.settings import cfg
from apps.api.main import app


def test_config_has_every_node_model():
    for node in [
        "scout",
        "analyst",
        "risk_assessor",
        "fit_matcher",
        "pricing",
        "writer",
        "critic",
        "compliance",
        "client_liaison",
    ]:
        assert cfg(f"models.nodes.{node}") in {"small", "large"}


def test_model_routing_open_profile(monkeypatch):
    monkeypatch.setenv("MODEL_PROFILE", "open")
    assert llm.model_for("writer") == "openai/gpt-oss-120b"
    assert llm.model_for("risk_assessor") == "openai/gpt-oss-20b"


def test_no_paid_profile():
    assert set(cfg("models.profiles")) == {"open", "open_local"}


def test_extract_json_handles_think_and_fences():
    assert llm._extract_json('<think>x</think>```json\n{"a": 1}\n```') == {"a": 1}


def test_fit_report_evidence_ids_dedup():
    ev = EvidenceRef(evidence_id="e1")
    fr = FitReport(
        score=0.5,
        matches=[RequirementMatch(requirement_id="r1", requirement="x", evidence=[ev, ev])],
    )
    assert fr.evidence_ids == ["e1"]


def test_claim_supported_ratio():
    rep = ClaimReport(
        claims=[
            Claim(text="a", label=ClaimLabel.supported),
            Claim(text="b", label=ClaimLabel.unsupported, action="removed"),
        ]
    )
    assert rep.supported_ratio == 1.0


def test_health():
    assert TestClient(app).get("/health").json()["status"] == "ok"


async def test_structured_falls_back_when_provider_json_mode_fails(monkeypatch):
    """Groq's JSON mode sometimes returns HTTP 400 'Failed to generate JSON': retry as plain text."""
    from pydantic import BaseModel

    calls = []

    async def fake(node, system, user, *, json_mode=False, temperature=None, max_tokens=None):
        calls.append(json_mode)
        if json_mode:
            raise llm.LLMError("writer: all attempts failed: Error code: 400 - Failed to generate JSON.")
        return 'Sure: {"x": 1}'

    monkeypatch.setattr(llm, "complete", fake)

    class M(BaseModel):
        x: int

    assert (await llm.structured("writer", "s", "u", M)).x == 1
    assert calls == [True, False]
