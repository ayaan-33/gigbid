"""Schema snapshot (A7): fails CI when any MCP tool signature changes unintentionally.

Regenerate deliberately with:  UPDATE_SNAPSHOTS=1 uv run pytest tests/contract/test_tool_schemas.py
"""

import json
import os
from pathlib import Path

from mcp.shared.memory import create_connected_server_and_client_session

from mcp_servers.marketplace import server as marketplace
from mcp_servers.portfolio import server as portfolio
from mcp_servers.workspace import server as workspace

SNAP = Path(__file__).parent / "snapshots" / "tool_schemas.json"


async def _schemas() -> dict:
    out = {}
    for mod in (portfolio, marketplace, workspace):
        async with create_connected_server_and_client_session(mod.mcp._mcp_server) as s:
            tools = (await s.list_tools()).tools
            out[mod.mcp.name] = {
                t.name: {"description": t.description, "input": t.inputSchema, "output": t.outputSchema,
                         "annotations": t.annotations.model_dump(exclude_none=True) if t.annotations else None}
                for t in sorted(tools, key=lambda t: t.name)
            }
            res = await s.list_resource_templates()
            out[mod.mcp.name]["__resource_templates__"] = sorted(r.uriTemplate for r in res.resourceTemplates)
            out[mod.mcp.name]["__prompts__"] = sorted(p.name for p in (await s.list_prompts()).prompts)
    return out


async def test_tool_schemas_match_snapshot():
    current = await _schemas()
    if os.getenv("UPDATE_SNAPSHOTS") == "1" or not SNAP.exists():
        SNAP.write_text(json.dumps(current, indent=1, sort_keys=True))
    expected = json.loads(SNAP.read_text())
    changed = [f"{srv}.{tool}" for srv in current for tool in current[srv]
               if expected.get(srv, {}).get(tool) != current[srv][tool]]
    removed = [f"{srv}.{tool}" for srv in expected for tool in expected[srv] if tool not in current.get(srv, {})]
    assert not changed and not removed, f"tool schema drift: changed={changed} removed={removed}"
