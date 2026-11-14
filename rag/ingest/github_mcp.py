"""Ingest repositories through the OFFICIAL GitHub MCP server (third-party server, A5).

Transport: stdio, `docker run -i --rm -e GITHUB_PERSONAL_ACCESS_TOKEN ghcr.io/github/github-mcp-server`
(read-only fine-grained PAT: Contents + Metadata). Only the `repos` / `context` toolsets are enabled.
We call `get_me`, `search_repositories` and `get_file_contents`; nothing is written to GitHub.

Each repo becomes portfolio chunks (type=repo): README (view=readme) + code files (view=code),
chunked by top-level definitions, so V5 multi-vector retrieval can score README and code separately.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

from rag.ingest.loaders import CODE_EXT, Chunk, split_code
from scripts.data.taxonomy import extract_skills

MAX_FILES_PER_REPO = int(os.getenv("GITHUB_INGEST_MAX_FILES", "12"))
MAX_FILE_BYTES = 40_000


def github_client():
    from langchain_mcp_adapters.client import MultiServerMCPClient

    token = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_PERSONAL_ACCESS_TOKEN not set")
    return MultiServerMCPClient({
        "github": {
            "transport": "stdio",
            "command": "docker",
            "args": ["run", "-i", "--rm", "-e", "GITHUB_PERSONAL_ACCESS_TOKEN", "-e", "GITHUB_TOOLSETS",
                     "-e", "GITHUB_READ_ONLY", "ghcr.io/github/github-mcp-server"],
            "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": token, "GITHUB_TOOLSETS": "repos,context",
                    "GITHUB_READ_ONLY": "1", "PATH": os.environ.get("PATH", "")},
        }
    })


def _parse(out: Any) -> Any:
    if isinstance(out, list | tuple) and out and isinstance(out[0], dict) and "text" in out[0]:
        texts = [o.get("text", "") for o in out if isinstance(o, dict)]
        out = texts[0] if len(texts) == 1 else texts
    if isinstance(out, list):
        parsed = []
        for o in out:
            try:
                parsed.append(json.loads(o))
            except (TypeError, json.JSONDecodeError):
                parsed.append(o)
        return parsed
    if isinstance(out, str):
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return out
    return out


def _file_text(res: Any) -> str | None:
    """get_file_contents returns either text content, a resource, or JSON with base64 content."""
    if isinstance(res, list):
        for r in res:
            t = _file_text(r)
            if t:
                return t
        return None
    if isinstance(res, dict):
        if res.get("encoding") == "base64" and res.get("content"):
            return base64.b64decode(res["content"]).decode("utf-8", errors="ignore")
        for k in ("text", "content"):
            if isinstance(res.get(k), str):
                return res[k]
        return None
    return res if isinstance(res, str) else None


async def ingest_github(persona: str, owner: str | None = None, repos: list[str] | None = None,
                        limit: int = 8) -> list[Chunk]:
    client = github_client()
    tools = {t.name: t for t in await client.get_tools()}
    if owner is None:
        me = _parse(await tools["get_me"].ainvoke({}))
        owner = (me if isinstance(me, dict) else {}).get("login")
    if repos is None:
        found = _parse(await tools["search_repositories"].ainvoke({"query": f"user:{owner} fork:false", "perPage": limit}))
        items = found.get("items", []) if isinstance(found, dict) else []
        repos = [r["name"] for r in items][:limit]
    chunks: list[Chunk] = []
    for repo in repos:
        eid = f"{persona}:repo:gh-{repo}"
        listing = _parse(await tools["get_file_contents"].ainvoke({"owner": owner, "repo": repo, "path": "/"}))
        entries = listing if isinstance(listing, list) else []
        names = [e.get("path") or e.get("name") for e in entries if isinstance(e, dict) and e.get("type") == "file"]
        readme = next((n for n in names if n and n.lower().startswith("readme")), None)
        if readme:
            text = _file_text(_parse(await tools["get_file_contents"].ainvoke({"owner": owner, "repo": repo, "path": readme})))
            if text:
                chunks.append(Chunk(chunk_id=f"{eid}#readme", evidence_id=eid, persona=persona, type="repo",
                                    text=f"# {repo}\n{text[:6000]}", title=repo, project=f"gh-{repo}",
                                    skills=extract_skills(text), view="readme", source=f"github:{owner}/{repo}"))
        code = [n for n in names if n and os.path.splitext(n)[1] in CODE_EXT][:MAX_FILES_PER_REPO]
        for path in code:
            text = _file_text(_parse(await tools["get_file_contents"].ainvoke({"owner": owner, "repo": repo, "path": path})))
            if not text or len(text) > MAX_FILE_BYTES:
                continue
            for k, block in enumerate(split_code(text)):
                body = f"# file: {repo}/{path}\n{block}"
                chunks.append(Chunk(chunk_id=f"{eid}#{path}:{k}", evidence_id=eid, persona=persona, type="repo",
                                    text=body, title=repo, project=f"gh-{repo}", skills=extract_skills(body),
                                    view="code", source=f"github:{owner}/{repo}/{path}"))
    return chunks


if __name__ == "__main__":
    import argparse
    import asyncio

    from dotenv import load_dotenv

    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--persona", default="own_profile")
    ap.add_argument("--owner", default=None)
    ap.add_argument("--limit", type=int, default=3)
    a = ap.parse_args()
    cs = asyncio.run(ingest_github(a.persona, a.owner, limit=a.limit))
    print(json.dumps({"chunks": len(cs), "repos": sorted({c.title for c in cs}),
                      "views": {v: sum(c.view == v for c in cs) for v in ("readme", "code")}}, indent=1))
