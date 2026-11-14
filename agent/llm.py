"""Model routing, structured output, usage/cost accounting and an LLM response cache.

* The model for a node comes from config (models.nodes.<node> -> tier -> profile model).
* Both profiles are open-weight and speak the OpenAI-compatible API (Groq, Ollama).
* `structured()` returns a validated Pydantic object (JSON mode + one repair retry).
* Usage is recorded per node in a context-local ledger so graphs can enforce token budgets
  and the API can report tokens/cost per node; Langfuse also receives every call.
* A sqlite cache keyed by (model, messages, schema) makes evals reproducible and keeps
  free-tier usage low. Enabled with LLM_CACHE=1 (default on for evals/CI).
"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ValidationError

from agent.settings import ROOT, cfg

T = TypeVar("T", bound=BaseModel)

# --------------------------------------------------------------------------- usage ledger


@dataclass
class UsageRecord:
    node: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_s: float
    cost_usd: float
    cached: bool = False


@dataclass
class UsageLedger:
    records: list[UsageRecord] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return sum(r.input_tokens + r.output_tokens for r in self.records)

    @property
    def total_cost(self) -> float:
        return round(sum(r.cost_usd for r in self.records), 6)

    def by_node(self) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for r in self.records:
            d = out.setdefault(r.node, {"tokens": 0, "cost_usd": 0.0, "calls": 0, "latency_s": 0.0})
            d["tokens"] += r.input_tokens + r.output_tokens
            d["cost_usd"] = round(d["cost_usd"] + r.cost_usd, 6)
            d["calls"] += 1
            d["latency_s"] = round(d["latency_s"] + r.latency_s, 3)
        return out


_ledger: contextvars.ContextVar[UsageLedger | None] = contextvars.ContextVar("ledger", default=None)


def start_ledger() -> UsageLedger:
    led = UsageLedger()
    _ledger.set(led)
    return led


def current_ledger() -> UsageLedger | None:
    return _ledger.get()


# --------------------------------------------------------------------------- routing


def profile_name() -> str:
    return os.getenv("MODEL_PROFILE") or cfg("models.profile", "open")


def _profile() -> dict[str, Any]:
    return cfg(f"models.profiles.{profile_name()}")


def model_for(node: str, fallback: bool = False) -> str:
    prof = _profile()
    tier = cfg(f"models.nodes.{node}", "small")
    if fallback:
        return prof.get(f"fallback_{tier}") or prof["fallback_small"]
    return prof[tier]


def price(model: str, inp: int, out: int) -> float:
    p = (_profile().get("prices_usd_per_mtok") or {}).get(model)
    if not p:
        return 0.0
    return (inp * p["input"] + out * p["output"]) / 1_000_000


def chat_model(node: str, fallback: bool = False, **overrides: Any) -> ChatOpenAI:
    prof = _profile()
    key_env = prof.get("api_key_env")
    api_key = os.getenv(key_env, "") if key_env else "ollama"
    temp = cfg(f"models.temperature.{node}", cfg("models.temperature.default", 0.2))
    return ChatOpenAI(
        model=model_for(node, fallback),
        base_url=prof["base_url"],
        api_key=api_key or "missing-key",
        temperature=overrides.pop("temperature", temp),
        timeout=cfg("models.request_timeout_s", 60),
        max_retries=0,  # we own retries (bounded, with backoff + fallback)
        **overrides,
    )


# --------------------------------------------------------------------------- cache


class _Cache:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute("create table if not exists c (k text primary key, v text)")

    def get(self, k: str) -> str | None:
        row = self.conn.execute("select v from c where k=?", (k,)).fetchone()
        return row[0] if row else None

    def set(self, k: str, v: str) -> None:
        self.conn.execute("insert or replace into c values (?,?)", (k, v))
        self.conn.commit()


_cache: _Cache | None = None


def _get_cache() -> _Cache | None:
    global _cache
    if os.getenv("LLM_CACHE", "0") != "1":
        return None
    if _cache is None:
        _cache = _Cache(Path(os.getenv("LLM_CACHE_PATH", ROOT / ".cache" / "llm.sqlite")))
    return _cache


def _key(model: str, msgs: list[BaseMessage], extra: str) -> str:
    blob = json.dumps([model, [(m.type, m.content) for m in msgs], extra], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


# --------------------------------------------------------------------------- calls


class LLMError(RuntimeError):
    pass


_FAKE = None


class TokenRateLimiter:
    """Client-side pacing per model (free tiers: ~8k tokens/min). Reserves an estimate before a
    call so concurrent graph runs queue politely instead of hammering the provider into 429s."""

    def __init__(self) -> None:
        self.window: dict[str, list[tuple[float, int]]] = {}
        self.lock = asyncio.Lock()

    async def acquire(self, model: str, tokens: int) -> None:
        limit = int(cfg(f"models.profiles.{profile_name()}.tokens_per_minute", 0) or 0)
        if not limit:
            return
        tokens = min(tokens, limit)
        while True:
            async with self.lock:
                now = time.monotonic()
                w = [(t, n) for t, n in self.window.get(model, []) if now - t < 60]
                used = sum(n for _, n in w)
                if used + tokens <= limit:
                    w.append((now, tokens))
                    self.window[model] = w
                    return
                wait = 60 - (now - w[0][0]) + 0.05 if w else 1.0
            await asyncio.sleep(min(wait, 10))


RATE = TokenRateLimiter()


async def complete(
    node: str,
    system: str,
    user: str,
    *,
    json_mode: bool = False,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """One chat completion with bounded retries, fallback model, cache and accounting."""
    if os.getenv("GIGBID_FAKE_LLM") == "1":  # CI / Playwright only
        from agent.testing import FakeLLM

        global _FAKE
        _FAKE = _FAKE or FakeLLM()
        return await _FAKE(node, system, user, json_mode=json_mode, temperature=temperature, max_tokens=max_tokens)
    msgs: list[BaseMessage] = [SystemMessage(system), HumanMessage(user)]
    attempts = cfg("models.max_retries", 2) + 1
    max_tokens = max_tokens or cfg(f"models.max_output_tokens.{node}", cfg("models.max_output_tokens.default", 900))
    last_err: Exception | None = None
    rate_waited = 0.0
    attempt = 0
    while attempt <= attempts:
        use_fallback = attempt == attempts  # final attempt goes to the fallback model
        model = model_for(node, fallback=use_fallback)
        cache = _get_cache()
        ck = _key(model, msgs, f"json={json_mode};t={temperature}")
        if cache and (hit := cache.get(ck)) is not None:
            _record(node, model, 0, 0, 0.0, cached=True)
            return hit
        kwargs: dict[str, Any] = {"max_tokens": max_tokens}
        if temperature is not None:
            kwargs["temperature"] = temperature
        mk: dict[str, Any] = {}
        if json_mode:
            mk["response_format"] = {"type": "json_object"}
        effort = cfg(f"models.reasoning_effort.{node}", cfg("models.reasoning_effort.default"))
        if effort and "gpt-oss" in model:
            kwargs["reasoning_effort"] = effort  # gpt-oss: fewer hidden reasoning tokens on cheap nodes
        if mk:
            kwargs["model_kwargs"] = mk
        llm = chat_model(node, fallback=use_fallback, **kwargs)
        await RATE.acquire(model, (len(system) + len(user)) // 4 + max_tokens)
        t0 = time.perf_counter()
        try:
            resp: AIMessage = await llm.ainvoke(msgs, config={"run_name": node, "tags": [node]})
        except Exception as e:  # noqa: BLE001 - rate limits, 5xx, timeouts
            last_err = e
            wait = _retry_after(e)
            # a provider-told rate-limit wait is not a failure: honour it (within a budget)
            if wait is not None and rate_waited + wait <= cfg("models.rate_limit_wait_budget_s", 90):
                rate_waited += wait
                await asyncio.sleep(wait)
                continue
            await asyncio.sleep(min(2**attempt + 0.25 * attempt, 20))
            attempt += 1
            continue
        dt = time.perf_counter() - t0
        um = resp.usage_metadata or {}
        _record(node, model, um.get("input_tokens", 0), um.get("output_tokens", 0), dt)
        text = resp.content if isinstance(resp.content, str) else json.dumps(resp.content)
        if cache:
            cache.set(ck, text)
        return text
    raise LLMError(f"{node}: all attempts failed: {last_err}")


_RETRY = re.compile(r"try again in (?:(\d+)m)?([\d.]+)s", re.I)


def _retry_after(e: Exception) -> float | None:
    """Seconds the provider asked us to wait on a 429 (None if not a rate limit)."""
    msg = str(e)
    if "429" not in msg and "rate limit" not in msg.lower():
        return None
    if "Request too large" in msg:
        return None  # waiting will not help; fall through to the fallback model
    m = _RETRY.search(msg)
    if not m:
        return 5.0
    return float(m.group(1) or 0) * 60 + float(m.group(2)) + 0.5


def _record(node: str, model: str, inp: int, out: int, dt: float, cached: bool = False) -> None:
    led = _ledger.get()
    if led is not None:
        led.records.append(
            UsageRecord(node, model, inp, out, round(dt, 3), price(model, inp, out), cached)
        )


def _extract_json(text: str) -> Any:
    text = text.strip()
    if "<think>" in text:  # qwen3 thinking traces
        text = text.split("</think>")[-1].strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{") :]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model output")
    return json.loads(text[start : end + 1])


async def structured(node: str, system: str, user: str, schema: type[T], **kw: Any) -> T:
    """Return a validated `schema` instance. One repair round-trip on invalid JSON."""
    schema_hint = json.dumps(schema.model_json_schema(), separators=(",", ":"))
    sys = (
        f"{system}\n\nRespond with ONE JSON object only, matching this JSON schema:\n{schema_hint}"
    )
    raw = await complete(node, sys, user, json_mode=True, **kw)
    try:
        return schema.model_validate(_extract_json(raw))
    except (ValueError, ValidationError) as e:
        repair = (
            f"{user}\n\nYour previous answer was invalid ({str(e)[:400]}). "
            "Return only the corrected JSON object."
        )
        raw = await complete(node, sys, repair, json_mode=True, **kw)
        return schema.model_validate(_extract_json(raw))
