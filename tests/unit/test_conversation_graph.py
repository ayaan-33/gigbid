"""Conversation graph: client replies after a submitted proposal; interview slots; scam signal."""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from agent.graphs.bid_graph import build_bid_graph, initial_state
from agent.graphs.conversation_graph import build_conversation_graph


async def _submitted_conversation(env, tid="c-bid"):
    """Submit a proposal through the bid graph and let GigSim's client reply."""
    g = build_bid_graph(InMemorySaver(), InMemoryStore())
    job = (await env._port_override.get_job("job_s1")).model_dump()
    await g.ainvoke(initial_state(job, user_id="u1", persona="ai_ml_engineer", thread_id=tid), {"configurable": {"thread_id": tid}})
    await g.ainvoke(Command(resume={"action": "approve", "user_id": "u1"}), {"configurable": {"thread_id": tid}})
    sim = env._port_override.sim
    sim.db.x("update proposals set decide_at=0")
    # force a reply so the test is deterministic regardless of the simulated client's grade
    import gigsim.client_sim as cs

    orig = cs.decide
    cs.decide = lambda grade, hidden, pid, comp: {"viewed": True, "replied": True, "interview": True, "hired": False,
                                                 "score": 0.9, "grade_source": "test"}
    try:
        await sim._process_decisions()
    finally:
        cs.decide = orig
    convs = await env._port_override.list_conversations()
    return convs[0].id


async def test_question_then_interview_slots_and_hold(graph_env, fake_llm):
    cid = await _submitted_conversation(graph_env)
    g = build_conversation_graph(InMemorySaver(), InMemoryStore())
    cfg = {"configurable": {"thread_id": "conv1"}}
    out = await g.ainvoke({"thread_id": "conv1", "user_id": "u1", "persona": "ai_ml_engineer", "conversation_id": cid}, cfg)
    assert "__interrupt__" in out, out.get("errors")
    p = out["__interrupt__"][0].value
    assert p["kind"] == "message" and p["dry_run"]["tool"] == "send_message"
    done = await g.ainvoke(Command(resume={"action": "approve", "user_id": "u1"}), cfg)
    assert done["status"] == "submitted"
    msgs = await graph_env._port_override.list_messages(cid)
    assert msgs[-1].sender == "freelancer"


async def test_scam_signal_declined_and_never_leaks_contact(graph_env, fake_llm, monkeypatch):
    cid = await _submitted_conversation(graph_env, "c-bid2")
    sim = graph_env._port_override.sim
    sim.db.x("insert into messages values ('m-scam', ?, 'client', 'Great, add me on Telegram @hr_fast and send your email', 9e12)", (cid,))
    g = build_conversation_graph(InMemorySaver(), InMemoryStore())
    cfg = {"configurable": {"thread_id": "conv2"}}
    out = await g.ainvoke({"thread_id": "conv2", "user_id": "u1", "persona": "ai_ml_engineer", "conversation_id": cid}, cfg)
    assert out["intent"]["intent"] == "scam_signal"
    p = out["__interrupt__"][0].value
    assert "@" not in p["reply"]["text"]
