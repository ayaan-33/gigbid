"""Portfolio MCP server through an in-memory MCP client session."""

import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from mcp_servers.portfolio import server
from rag.index.store import PortfolioIndex

PERSONA = "ai_ml_engineer"


@pytest.fixture(scope="module")
def index():
    idx = PortfolioIndex()
    idx.build(PERSONA)
    return idx


@pytest.fixture()
def session(index, monkeypatch):
    """Returns a factory; each test opens the in-memory session in its own task."""
    monkeypatch.setenv("PORTFOLIO_PERSONA", PERSONA)
    server.service._index = index
    server.service.variant = "v2_hybrid"  # no reranker download in unit tests
    return lambda: create_connected_server_and_client_session(server.mcp._mcp_server)


async def test_lists_tools_with_read_only_annotations(session):
    async with session() as session:
        tools = {t.name: t for t in (await session.list_tools()).tools}
        assert set(tools) == {"search_evidence", "get_case_study", "list_skills"}
        for t in tools.values():
            assert t.annotations.readOnlyHint is True and t.annotations.destructiveHint is False
            assert t.outputSchema is not None


async def test_search_evidence_returns_typed_items(session):
    async with session() as session:
        r = await session.call_tool("search_evidence", {"requirement": "hybrid search with BM25 and embeddings", "k": 5})
        assert not r.isError
        data = r.structuredContent
        assert data["items"] and len(data["items"]) <= 5
        first = data["items"][0]
        assert {"id", "type", "source", "date", "outcome", "snippet"} <= set(first)
        assert first["id"].startswith(PERSONA)


async def test_filters_restrict_type_and_outcome(session):
    async with session() as session:
        r = await session.call_tool("search_evidence", {"requirement": "churn model", "k": 5,
                                                        "filters": {"type": ["proposal"], "outcome": ["won"]}})
        items = r.structuredContent["items"]
        assert items and all(i["type"] == "proposal" and i["outcome"] == "won" for i in items)


async def test_bad_arguments_are_rejected(session):
    async with session() as session:
        r = await session.call_tool("search_evidence", {"requirement": "x", "k": 99})
        assert r.isError


async def test_case_study_and_resources(session):
    async with session() as session:
        r = await session.call_tool("get_case_study", {"id": f"{PERSONA}:case:support_rag"})
        assert "## Results" in r.structuredContent["markdown"]
        templates = {t.uriTemplate for t in (await session.list_resource_templates()).resourceTemplates}
        assert {"portfolio://case/{case_key}", "portfolio://proposal/{proposal_key}"} <= templates
        res = await session.read_resource("portfolio://proposal/p001")
        assert json.loads(res.contents[0].text)["outcome"] in {"won", "replied", "ignored"}


async def test_prompts_available(session):
    async with session() as session:
        names = {p.name for p in (await session.list_prompts()).prompts}
        assert "answer_screening_question" in names
        p = await session.get_prompt("answer_screening_question", {"question": "How do you evaluate RAG?"})
        assert "search_evidence" in p.messages[0].content.text


async def test_list_skills(session):
    async with session() as session:
        r = await session.call_tool("list_skills", {})
        skills = r.structuredContent["result"]
        assert any(s["skill"] == "RAG" for s in skills)
