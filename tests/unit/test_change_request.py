"""Change request (platform policy v2): absorbed by editing agent/config.yaml only.

v2 = (a) +4 Connects on jobs with >= 20 proposals, (b) proposals must carry an AI-assistance
disclosure. With config still on v1 GigBid warns about policy drift and the marketplace rejects the
submission; after the 2-line config change the same graph produces a compliant, accepted proposal.
"""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from agent.graphs.bid_graph import build_bid_graph, initial_state

ADMIN = {"X-Admin-Token": "adm"}


def _cfg_override(monkeypatch, values: dict):
    from agent import settings

    real = settings.cfg

    def fake(path, default=None):
        return values[path] if path in values else real(path, default)

    for mod in ("agent.nodes.proposal", "agent.nodes.decide_price"):
        monkeypatch.setattr(f"{mod}.cfg", fake)


async def _run(env, tid):
    g = build_bid_graph(InMemorySaver(), InMemoryStore())
    job = (await env._port_override.get_job("job_s3")).model_dump()  # 22 proposals -> surcharge applies
    out = await g.ainvoke(initial_state(job, user_id="u1", persona="ai_ml_engineer", thread_id=tid), {"configurable": {"thread_id": tid}})
    return g, out


async def test_policy_v2_without_config_change_is_detected_and_blocked_upstream(graph_env, fake_llm, monkeypatch):
    graph_env._port_override.sim.db.set_sim("policy_version", 2)
    _cfg_override(monkeypatch, {"policy.version": 1, "policy.require_ai_disclosure": False})  # config before the change
    g, out = await _run(graph_env, "cr1")
    q = out["price_quote"]
    assert q["connects_cost"] == 16  # marketplace figure (12 + 4), not double-counted
    assert "policy is v2" in q["rationale"]  # drift warning shown to the user
    done = await g.ainvoke(Command(resume={"action": "approve", "user_id": "u1"}), {"configurable": {"thread_id": "cr1"}})
    assert done["status"] != "submitted"  # GigSim rejects: missing AI disclosure


async def test_policy_v2_after_two_line_config_change(graph_env, fake_llm, monkeypatch):
    graph_env._port_override.sim.db.set_sim("policy_version", 2)
    _cfg_override(monkeypatch, {"policy.version": 2, "policy.require_ai_disclosure": True})
    g, out = await _run(graph_env, "cr2")
    p = out["__interrupt__"][0].value
    assert "Drafted with AI assistance" in p["draft"]["cover_letter"]
    assert "policy is v2" not in p["price_quote"]["rationale"]
    done = await g.ainvoke(Command(resume={"action": "approve", "user_id": "u1"}), {"configurable": {"thread_id": "cr2"}})
    assert done["status"] == "submitted" and done["submission"]["connects_spent"] == 16


async def test_unknown_fit_is_never_skipped():
    """A degraded Fit Matcher (score None) must not be turned into a 'poor fit' skip."""
    from agent.nodes.decide_price import decide
    state = {"job": {"budget": {"type": "fixed", "max": 5000}}, "risk_report": {"score": 0.0},
             "fit_report": {"score": None}, "persona": "ai_ml_engineer"}
    out = await decide(state)
    assert out["decision"]["action"] == "watch"
    assert "unknown" in out["status_reason"]
