from datetime import datetime

from mcp.shared.memory import create_connected_server_and_client_session

from mcp_servers.workspace import server
from mcp_servers.workspace.store import WorkspaceStore


async def test_slots_hold_and_draft(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "STORE", WorkspaceStore(tmp_path / "ws.sqlite"))
    async with create_connected_server_and_client_session(server.mcp._mcp_server) as s:
        slots = (await s.call_tool("find_free_slots", {"duration_min": 30, "days_ahead": 7})).structuredContent["slots"]
        assert 1 <= len(slots) <= 3
        st = datetime.fromisoformat(slots[0]["start"])
        assert st.weekday() < 5 and 9 <= st.hour < 17
        args = {"inp": {"start": slots[0]["start"], "end": slots[0]["end"], "title": "Interview: churn model",
                        "idempotency_key": "conv1:hold1"}}
        h1 = (await s.call_tool("create_interview_hold", args)).structuredContent
        h2 = (await s.call_tool("create_interview_hold", args)).structuredContent
        assert h1["id"] == h2["id"] and h2["replayed"]
        d = await s.call_tool("create_email_draft", {"inp": {"to_label": "Client", "subject": "Interview",
                                                             "body": "See you then", "idempotency_key": "conv1:mail1"}})
        assert d.structuredContent["id"].startswith("draft_")
        bad = await s.call_tool("create_interview_hold", {"inp": {"start": slots[0]["end"], "end": slots[0]["start"],
                                                                 "title": "x" * 5, "idempotency_key": "conv1:hold2"}})
        assert bad.isError
