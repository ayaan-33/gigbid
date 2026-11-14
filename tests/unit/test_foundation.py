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
