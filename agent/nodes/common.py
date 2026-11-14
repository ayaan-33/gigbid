"""Helpers shared by nodes: caller identity, persona profile, toolboxes, injection guard."""

from __future__ import annotations

import json
import os
from functools import cache
from pathlib import Path
from typing import Any

from agent.guardrails import injection_heuristic
from agent.mcp_client import Caller, ToolBox
from agent.settings import ROOT, cfg


def caller(state: dict) -> Caller:
    return Caller(user=state.get("user_id", "local"), persona=state.get("persona", "ai_ml_engineer"),
                  trace_id=state.get("trace_id", "") or state.get("thread_id", ""))


def tools(agent: str, state: dict) -> ToolBox:
    return ToolBox(agent, caller(state))


@cache
def profile(persona: str) -> dict[str, Any]:
    p = Path(ROOT) / "data" / "personas" / persona / "profile.json"
    if p.exists():
        return json.loads(p.read_text())
    return {"persona_id": persona, "name": "Freelancer", "headline": "", "voice": "clear and specific",
            "hourly_rate": 40, "fixed_floor": 200, "categories": [], "secondary": [], "capabilities": [], "skills": []}


async def prompt_guard(text: str) -> float | None:
    """Probability that `text` is a prompt-injection/jailbreak (Llama Prompt Guard 2 on Groq, free).
    Returns None when unavailable; callers then rely on the heuristic."""
    model = (cfg(f"models.profiles.{os.getenv('MODEL_PROFILE') or cfg('models.profile')}") or {}).get("injection_guard")
    key = os.getenv("GROQ_API_KEY")
    if not model or not key or not cfg("guardrails.injection_classifier", True):
        return None
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10) as c:
            # the guard scores up to 512 tokens; score the tail where injected text usually sits
            r = await c.post("https://api.groq.com/openai/v1/chat/completions",
                             headers={"Authorization": f"Bearer {key}"},
                             json={"model": model, "messages": [{"role": "user", "content": text[-1800:]}]})
            r.raise_for_status()
            return float(r.json()["choices"][0]["message"]["content"].strip())
    except Exception:  # noqa: BLE001
        return None


async def detect_injection(text: str) -> tuple[bool, str | None, dict]:
    hit, excerpt = injection_heuristic(text)
    p = await prompt_guard(text)
    detected = hit or (p is not None and p >= 0.8)
    return detected, excerpt, {"heuristic": hit, "prompt_guard": p}
