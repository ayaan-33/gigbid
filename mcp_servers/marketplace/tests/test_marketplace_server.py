"""Marketplace MCP server over an in-memory MCP session, backed by a real in-process GigSim."""

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

LETTER = ("Your churn baseline needs honest evaluation on an imbalanced target. In my retail churn project "
          "I compared logistic regression and random forest with scikit-learn and lifted recall by 18%.")


def session(server):
    return create_connected_server_and_client_session(server.mcp._mcp_server)


async def test_read_tools(mserver):
    async with session(mserver) as s:
        r = await s.call_tool("search_jobs", {"query": "churn"})
        assert [j["id"] for j in r.structuredContent["jobs"]] == ["job_s1"]
        c = await s.call_tool("get_client_history", {"client_id": "cl_scam"})
        assert c.structuredContent["payment_verified"] is False
        bal = await s.call_tool("get_connects_balance", {})
        assert bal.structuredContent["balance"] == 200


async def test_draft_submit_exactly_once_with_post_commit_faults(mserver, gigsim_port):
    """GigSim drops 100% of write responses AFTER committing. The adapter retries with the SAME
    idempotency key and gets GigSim's stored result, so the call succeeds, exactly one draft exists
    and Connects are spent exactly once."""
    gigsim_port.sim.POST_COMMIT_ERROR_RATE = 1.0
    async with session(mserver) as s:
        d = await s.call_tool("create_proposal_draft", {"inp": {"proposal": {"job_id": "job_s1", "cover_letter": LETTER,
                                                                           "bid_amount": 400}, "idempotency_key": "thread-1:v1"}})
        assert not d.isError
        pid = d.structuredContent["draft"]["proposal_id"]
        drafts = gigsim_port.sim.db.q("select id from proposals")
        assert len(drafts) == 1  # one draft despite the retries

        pre = await s.call_tool("submit_proposal", {"inp": {"proposal_id": pid, "idempotency_key": "thread-1:submit",
                                                            "dry_run": True, "approved_by": "u1"}})
        assert pre.structuredContent["preview"]["connects_cost"] == 8
        args = {"inp": {"proposal_id": pid, "idempotency_key": "thread-1:submit", "approved_by": "u1"}}
        first = await s.call_tool("submit_proposal", args)
        second = await s.call_tool("submit_proposal", args)
        assert not first.isError and second.structuredContent["replayed"] is True
        bal = (await s.call_tool("get_connects_balance", {})).structuredContent["balance"]
        assert bal == 200 - 8


async def test_idempotency_key_reuse_for_other_payload_rejected(mserver):
    async with session(mserver) as s:
        base = {"proposal": {"job_id": "job_s1", "cover_letter": LETTER, "bid_amount": 400}, "idempotency_key": "same-key-1"}
        assert not (await s.call_tool("create_proposal_draft", {"inp": base})).isError
        other = {**base, "proposal": {**base["proposal"], "bid_amount": 999}}
        r = await s.call_tool("create_proposal_draft", {"inp": other})
        assert r.isError and "different request" in r.content[0].text


async def test_policy_violation_is_reported(mserver):
    async with session(mserver) as s:
        d = await s.call_tool("create_proposal_draft", {"inp": {"proposal": {"job_id": "job_s1", "cover_letter": LETTER + " WhatsApp me",
                                                                           "bid_amount": 400}, "idempotency_key": "thread-2:v1"}})
        pid = d.structuredContent["draft"]["proposal_id"]
        r = await s.call_tool("submit_proposal", {"inp": {"proposal_id": pid, "idempotency_key": "thread-2:submit", "approved_by": "u1"}})
        assert r.isError and "POLICY_VIOLATION" in r.content[0].text


async def test_schema_constraints(mserver):
    async with session(mserver) as s:
        r = await s.call_tool("create_proposal_draft", {"inp": {"proposal": {"job_id": "job_s1", "cover_letter": "too short",
                                                                           "bid_amount": -5}, "idempotency_key": "x"}})
        assert r.isError
        r = await s.call_tool("search_jobs", {"limit": 500})
        assert r.isError


async def test_audit_log_is_hash_chained_and_masks_pii(mserver):
    async with session(mserver) as s:
        await s.call_tool("create_proposal_draft", {"inp": {"proposal": {"job_id": "job_s1", "cover_letter": LETTER + " me@x.com",
                                                                       "bid_amount": 400}, "idempotency_key": "thread-3:v1"}})
    rows = mserver.AUDIT.read()
    assert rows and rows[-1]["tool"] == "create_proposal_draft" and rows[-1]["trace_id"]
    assert "me@x.com" not in str(rows) and "[email]" in str(rows)
    assert mserver.AUDIT.verify()


async def test_degraded_mode_when_gigsim_down(mserver, gigsim_port, monkeypatch):
    from mcp_servers.marketplace.adapters import gigsim as ad

    gigsim_port.sim.ERROR_RATE = 1.0
    gigsim_port.max_retries = 1
    monkeypatch.setattr(ad.BREAKER, "cooldown_s", 999)
    async with session(mserver) as s:
        for _ in range(3):
            r = await s.call_tool("get_job", {"job_id": "job_s1"})
            assert r.isError and "MARKETPLACE_UNAVAILABLE" in r.content[0].text
        st = await s.call_tool("marketplace_status", {})
        assert st.structuredContent["circuit"]["state"] == "open"
    gigsim_port.sim.ERROR_RATE = 0.0
    ad.BREAKER.cooldown_s = 0
    async with session(mserver) as s:  # recovers after cooldown (half-open -> closed)
        assert not (await s.call_tool("get_job", {"job_id": "job_s1"})).isError


async def test_toolbox_allowlist_and_degraded(mserver, gigsim_port, monkeypatch):
    from agent.mcp_client import Degraded, ToolBox, ToolNotAllowed
    from mcp_servers.marketplace.adapters import gigsim as ad

    monkeypatch.setenv("MCP_TRANSPORT", "inprocess")
    scout = ToolBox("scout")
    jobs = await scout.call("search_jobs", {"query": "churn"})
    assert jobs["jobs"][0]["id"] == "job_s1"
    with pytest.raises(ToolNotAllowed):
        await scout.call("submit_proposal", {})
    with pytest.raises(ToolNotAllowed):
        await ToolBox("analyst").call("get_job", {"job_id": "job_s1"})
    gigsim_port.sim.ERROR_RATE = 1.0
    gigsim_port.max_retries = 0
    monkeypatch.setattr(ad.BREAKER, "cooldown_s", 999)
    with pytest.raises(Degraded):
        await scout.call("get_job", {"job_id": "job_s1"})
