"""Resource templates so an MCP host can load full portfolio items."""

from __future__ import annotations

import json

from rag.ingest.loaders import PERSONA_DIR


def register(mcp, service, persona_of) -> None:
    @mcp.resource("portfolio://case/{case_key}", name="case_study", mime_type="text/markdown",
                  description="Full case study (Markdown). case_key e.g. support_rag")
    def case(case_key: str) -> str:
        p = persona_of(None)
        cs = service.case_study(p, f"{p}:case:{case_key}")
        return f"# {cs.title}\n\n{cs.markdown}"

    @mcp.resource("portfolio://proposal/{proposal_key}", name="past_proposal", mime_type="application/json",
                  description="A past proposal with its outcome (won/replied/ignored). proposal_key e.g. p042")
    def proposal(proposal_key: str) -> str:
        p = persona_of(None)
        return json.dumps(service.proposal(p, f"{p}:proposal:{proposal_key}"), indent=1)

    @mcp.resource("portfolio://repo/{repo}", name="repo_readme", mime_type="text/markdown",
                  description="README and file list of a portfolio repository")
    def repo(repo: str) -> str:
        base = PERSONA_DIR / persona_of(None) / "repos" / repo
        if not base.is_dir() or ".." in repo:
            raise ValueError("unknown repo")
        files = sorted(str(f.relative_to(base)) for f in base.rglob("*") if f.is_file())
        return (base / "README.md").read_text() + "\n\nFiles:\n" + "\n".join(f"- {f}" for f in files)

    @mcp.resource("portfolio://cv", name="cv", mime_type="text/markdown", description="The freelancer's CV")
    def cv() -> str:
        return (PERSONA_DIR / persona_of(None) / "cv.md").read_text()

    @mcp.resource("portfolio://profile", name="profile", mime_type="application/json",
                  description="Rates, headline, skills and project list")
    def profile() -> str:
        return (PERSONA_DIR / persona_of(None) / "profile.json").read_text()
