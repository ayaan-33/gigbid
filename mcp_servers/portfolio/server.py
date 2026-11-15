"""GigBid Portfolio MCP server (read-only).

Run (HTTP):   uv run python -m mcp_servers.portfolio.server            # :8091/mcp, bearer auth
Run (stdio):  uv run python -m mcp_servers.portfolio.server --stdio   # Claude Desktop / Cursor
"""

from __future__ import annotations

import os
import sys

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from mcp_servers.common import caller, serve
from mcp_servers.portfolio import prompts, resources
from mcp_servers.portfolio.tools import (
    CaseStudy,
    EvidenceFilters,
    PortfolioService,
    SearchResult,
    SkillSummary,
)

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

mcp = FastMCP(
    "gigbid-portfolio",
    instructions=(
        "Read-only access to one freelancer's portfolio: CV, case studies, code repositories, client "
        "reviews and past proposals with outcomes. Use search_evidence to find proof for a job requirement "
        "and cite returned ids. Never claim experience that no evidence supports."
    ),
    port=int(os.getenv("PORTFOLIO_MCP_PORT", "8091")),
)
service = PortfolioService()


def persona_of(ctx: Context | None) -> str:
    return caller(ctx)["persona"]


@mcp.tool(annotations=READ_ONLY, title="Search portfolio evidence")
def search_evidence(requirement: str, k: int = 5, filters: EvidenceFilters | None = None,
                    ctx: Context | None = None) -> SearchResult:
    """Find portfolio evidence (case studies, repos, reviews, past proposals) proving ONE job
    requirement, e.g. "hybrid search with exact product codes". Returns up to k items with
    id, type, source, date and outcome. Call once per requirement; cite results as [id]."""
    if not requirement.strip() or len(requirement) > 1000:
        raise ValueError("requirement must be 1-1000 characters")
    if not 1 <= k <= 20:
        raise ValueError("k must be between 1 and 20")
    return service.search(persona_of(ctx), requirement, k, filters)


@mcp.tool(annotations=READ_ONLY, title="Get a case study")
def get_case_study(id: str, ctx: Context | None = None) -> CaseStudy:
    """Full case study by evidence id (e.g. "ai_ml_engineer:case:support_rag")."""
    return service.case_study(persona_of(ctx), id)


@mcp.tool(annotations=READ_ONLY, title="List skills with evidence counts")
def list_skills(ctx: Context | None = None) -> list[SkillSummary]:
    """Every skill evidenced in the portfolio, with how many items and which projects prove it."""
    return service.skills(persona_of(ctx))


resources.register(mcp, service, persona_of)
prompts.register(mcp)

def main() -> None:
    """`ayaan33-gigbid-portfolio-mcp` entry point: stdio by default (Claude Desktop / Cursor), --http to serve."""
    if "--http" in sys.argv:
        serve(mcp, int(os.getenv("PORTFOLIO_MCP_PORT", "8091")))
    else:
        mcp.run("stdio")


if __name__ == "__main__":
    if "--stdio" in sys.argv:
        mcp.run("stdio")
    else:
        serve(mcp, int(os.getenv("PORTFOLIO_MCP_PORT", "8091")))
