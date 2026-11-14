"""Live Upwork adapter contract: discovered tool names map onto the port; writes are drafts only."""

import json

import pytest

from agent.marketplace_port import ProposalPayload
from mcp_servers.marketplace.adapters.upwork_live import EncryptedTokenStorage, UpworkLiveAdapter


class FakeTool:
    def __init__(self, name, fn):
        self.name, self.fn = name, fn

    async def ainvoke(self, args):
        return json.dumps(self.fn(**args))


class FakeUpworkClient:
    """Stands in for MultiServerMCPClient connected to mcp.upwork.com (names differ from GigSim)."""

    def __init__(self):
        self.calls = []

    async def get_tools(self):
        def rec(name, out):
            def f(**kw):
                self.calls.append((name, kw))
                return out
            return FakeTool(name, f)

        return [rec("job_search", {"jobs": [{"id": "~01abc", "title": "RAG chatbot", "description": "Build it",
                                             "budget": {"amount": 800}, "skills": [{"name": "Python"}]}]}),
                rec("get_job_details", {"id": "~01abc", "title": "RAG chatbot", "description": "Build it"}),
                rec("draft_proposal", {"draft_id": "d-1"}),
                rec("draft_message", {"id": "m-1"})]


async def test_maps_discovered_tools_and_never_submits():
    fake = FakeUpworkClient()
    ad = UpworkLiveAdapter("u1", client=fake)
    jobs, _ = await ad.search_jobs("rag")
    assert jobs[0].id == "~01abc" and jobs[0].budget.max == 800 and jobs[0].marketplace == "upwork_live"
    d = await ad.create_proposal_draft(ProposalPayload(job_id="~01abc", cover_letter="x" * 60, bid_amount=500), "k-1")
    assert d.status == "draft_on_upwork"
    s = await ad.submit_proposal(d.proposal_id, "k-2")
    assert s.requires_confirmation_on_marketplace and s.status == "awaiting_confirmation_on_upwork"
    assert [c[0] for c in fake.calls] == ["job_search", "draft_proposal"]  # no submit call upstream


async def test_unmapped_operation_is_explicit():
    ad = UpworkLiveAdapter("u1", client=FakeUpworkClient())
    with pytest.raises(Exception, match="not offered"):
        await ad.get_client_history("c1")


async def test_tokens_encrypted_at_rest(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet
    from mcp.shared.auth import OAuthToken

    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    st = EncryptedTokenStorage("user-a", db_path=tmp_path / "t.sqlite")
    await st.set_tokens(OAuthToken(access_token="SECRET-ACCESS", token_type="Bearer"))
    raw = (tmp_path / "t.sqlite").read_bytes()
    assert b"SECRET-ACCESS" not in raw
    assert (await st.get_tokens()).access_token == "SECRET-ACCESS"
    assert await EncryptedTokenStorage("user-b", db_path=tmp_path / "t.sqlite").get_tokens() is None  # tenant scoped
