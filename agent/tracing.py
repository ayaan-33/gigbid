"""Observability (E3): Langfuse traces with one trace id per graph thread.

The thread id is the trace/session id: it is created when the UI request starts a run, passed to
the graph config, sent to every MCP server as `X-Trace-Id` (and written in their audit logs), and
used as the Langfuse session id, so one id links UI request -> API -> graph -> MCP -> audit log.
Inputs/outputs are PII-masked before they leave the process. Tokens and cost per node come from
the LLM ledger and are attached as metadata.
"""

from __future__ import annotations

import os
from functools import cache

from agent.guardrails import mask_obj


@cache
def _client():
    if not (os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")):
        return None
    try:
        from langfuse import Langfuse

        return Langfuse(mask=lambda data, **_: mask_obj(data))
    except Exception:  # noqa: BLE001
        return None


def langfuse_handler(trace_name: str, session_id: str, user_id: str):
    if _client() is None or os.getenv("LANGFUSE_DISABLED") == "1":
        return None
    try:
        from langfuse.langchain import CallbackHandler

        return CallbackHandler()  # session/user/trace name travel in run metadata (see trace_metadata)
    except Exception:  # noqa: BLE001
        return None


def trace_metadata(trace_name: str, session_id: str, user_id: str) -> dict:
    return {"langfuse_session_id": session_id, "langfuse_user_id": user_id, "langfuse_trace_name": trace_name,
            "langfuse_tags": ["gigbid", trace_name]}


def trace_url(session_id: str) -> str | None:
    host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com").rstrip("/")
    pid = os.getenv("LANGFUSE_PROJECT_ID")
    if _client() is None:
        return None
    return f"{host}/project/{pid}/sessions/{session_id}" if pid else f"{host}/sessions/{session_id}"


def flush() -> None:
    c = _client()
    if c:
        try:
            c.flush()
        except Exception:  # noqa: BLE001
            pass
