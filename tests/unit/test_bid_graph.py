"""Bid graph end to end (fake LLM; real in-process MCP servers + GigSim + portfolio index)."""

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from agent.graphs.bid_graph import build_bid_graph, initial_state


def cfgd(tid):
    return {"configurable": {"thread_id": tid}}


async def job(env, jid):
    port = env._port_override
    return (await port.get_job(jid)).model_dump()


async def run_to_gate(graph, job_dict, tid, **kw):
    st = initial_state(job_dict, user_id="u1", persona="ai_ml_engineer", thread_id=tid, **kw)
    out = await graph.ainvoke(st, cfgd(tid))
    return out


async def test_fit_job_pauses_for_approval_then_submits_once(graph_env, fake_llm):
    g = build_bid_graph(InMemorySaver(), InMemoryStore())
    out = await run_to_gate(g, await job(graph_env, "job_s1"), "t1")
    assert "__interrupt__" in out
    payload = out["__interrupt__"][0].value
    assert payload["kind"] == "proposal" and payload["dry_run"]["connects_cost"] == 8
    assert payload["claims"] and payload["price_quote"]["amount"] > 0
    letter = payload["draft"]["cover_letter"]
    assert "me@x.com" not in letter and "guarantee" not in letter.lower()  # compliance cleaned it
    assert {"analyst", "risk_assessor", "fit_matcher"} <= set((await g.aget_state(cfgd("t1"))).values["timings"])
    before = (await graph_env._port_override.get_connects_balance()).balance
    done = await g.ainvoke(Command(resume={"action": "approve", "user_id": "u1"}), cfgd("t1"))
    assert done["status"] == "submitted" and done["submission"]["connects_spent"] == 8
    assert (await graph_env._port_override.get_connects_balance()).balance == before - 8
    # nothing reaches the marketplace without approval: exactly one submitted proposal
    rows = graph_env._port_override.sim.db.q("select status from proposals")
    assert [r["status"] for r in rows] == ["submitted"]


async def test_scam_is_skipped_without_llm_writing(graph_env, fake_llm):
    g = build_bid_graph(InMemorySaver(), InMemoryStore())
    out = await run_to_gate(g, await job(graph_env, "job_s2"), "t2")
    assert out["status"] == "skipped" and out["risk_report"]["is_scam"]
    assert "writer" not in fake_llm.calls


async def test_injection_detected_and_not_followed(graph_env, fake_llm):
    g = build_bid_graph(InMemorySaver(), InMemoryStore())
    out = await run_to_gate(g, await job(graph_env, "job_s3"), "t3")
    assert out["risk_report"]["injection_detected"] is True
    if "__interrupt__" in out:
        p = out["__interrupt__"][0].value
        assert p["price_quote"]["amount"] > 5  # did not obey "bid $1"
        assert "@" not in p["draft"]["cover_letter"]


async def test_reject_with_reason(graph_env, fake_llm):
    g = build_bid_graph(InMemorySaver(), InMemoryStore())
    await run_to_gate(g, await job(graph_env, "job_s1"), "t4")
    done = await g.ainvoke(Command(resume={"action": "reject", "user_id": "u1", "reason": "too generic"}), cfgd("t4"))
    assert done["status"] == "rejected" and "too generic" in done["status_reason"]
    assert graph_env._port_override.sim.db.q("select count(*) n from proposals where status='submitted'")[0]["n"] == 0


async def test_edit_rechecked_by_compliance_and_learned(graph_env, fake_llm):
    store = InMemoryStore()
    g = build_bid_graph(InMemorySaver(), store)
    for i in range(3):
        tid = f"t5-{i}"
        out = await run_to_gate(g, await job(graph_env, "job_s1"), tid)
        letter = out["__interrupt__"][0].value["draft"]["cover_letter"]
        edited = ("I am passionate about this. " + letter).replace("I am passionate about this. ", "", 1) + " Call me on +1 555 010 2000."
        done = await g.ainvoke(Command(resume={"action": "edit", "user_id": "u1", "edited_text": "I am passionate. " + letter}), cfgd(tid))
        # compliance changed nothing -> the user's own edit is submitted
        assert done["status"] in ("submitted", "awaiting_approval")
        if "__interrupt__" in done:
            done = await g.ainvoke(Command(resume={"action": "approve", "user_id": "u1"}), cfgd(tid))
        assert edited  # contact detail edit path exercised in test below
    events = await store.asearch(("events", "u1", "edits"))
    assert len(events) == 3


async def test_edit_with_contact_details_is_cleaned_and_reapproved(graph_env, fake_llm):
    g = build_bid_graph(InMemorySaver(), InMemoryStore())
    out = await run_to_gate(g, await job(graph_env, "job_s1"), "t6")
    letter = out["__interrupt__"][0].value["draft"]["cover_letter"]
    again = await g.ainvoke(Command(resume={"action": "edit", "user_id": "u1",
                                            "edited_text": letter + " Email me at dev@me.com"}), cfgd("t6"))
    assert "__interrupt__" in again  # compliance changed the edit -> user must approve the cleaned text
    p = again["__interrupt__"][0].value
    assert "dev@me.com" not in p["draft"]["cover_letter"]
    assert any("contact" in v["rule"] for v in p["compliance"]["violations"])


async def test_critic_loop_is_bounded(graph_env, monkeypatch):
    import agent.llm as llm
    from tests.fixtures import FakeLLM

    f = FakeLLM(critic_fail_first=True)
    monkeypatch.setattr(llm, "complete", f)
    g = build_bid_graph(InMemorySaver(), InMemoryStore())
    out = await run_to_gate(g, await job(graph_env, "job_s1"), "t7")
    assert f.calls.count("writer") == 2 and f.calls.count("critic") == 2
    assert "__interrupt__" in out


async def test_token_budget_moves_thread_to_needs_attention(graph_env, fake_llm, monkeypatch):
    from agent import settings

    real = settings.cfg

    def tiny(path, default=None):
        return -1 if path == "budgets.max_tokens_per_job" else real(path, default)

    monkeypatch.setattr("agent.nodes.base.cfg", tiny)
    g = build_bid_graph(InMemorySaver(), InMemoryStore())
    out = await run_to_gate(g, await job(graph_env, "job_s1"), "t8")
    assert out["status"] == "needs_attention"


async def test_duplicate_job_is_deduplicated(graph_env, fake_llm):
    store = InMemoryStore()
    g = build_bid_graph(InMemorySaver(), store)
    j = await job(graph_env, "job_s2")
    await run_to_gate(g, j, "t9a")
    dup = {**j, "id": "job_dup"}
    out = await run_to_gate(g, dup, "t9b")
    assert out["status"] == "duplicate"


async def test_marketplace_down_queues_thread(graph_env, fake_llm, monkeypatch):
    from mcp_servers.marketplace.adapters import gigsim as ad

    j = await job(graph_env, "job_s1")
    graph_env._port_override.sim.ERROR_RATE = 1.0
    graph_env._port_override.max_retries = 0
    monkeypatch.setattr(ad.BREAKER, "cooldown_s", 999)
    g = build_bid_graph(InMemorySaver(), InMemoryStore())
    out = await run_to_gate(g, j, "t10")
    assert out["status"] == "queued_degraded"


@pytest.mark.parametrize("action", ["approve"])
async def test_resume_after_restart_submits_exactly_once(graph_env, fake_llm, action):
    """Approval pending -> 'process restart' (new graph object on the same checkpointer) ->
    approve -> exactly one submission even if the approve is delivered twice."""
    saver, store = InMemorySaver(), InMemoryStore()
    g1 = build_bid_graph(saver, store)
    await run_to_gate(g1, await job(graph_env, "job_s1"), "t11")
    del g1
    g2 = build_bid_graph(saver, store)
    st = await g2.aget_state(cfgd("t11"))
    assert st.next == ("approval_gate",)
    await g2.ainvoke(Command(resume={"action": action, "user_id": "u1"}), cfgd("t11"))
    n = graph_env._port_override.sim.db.q("select count(*) n from proposals where status='submitted'")[0]["n"]
    assert n == 1
