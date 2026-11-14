"""Node wrapper shared by every graph node (C4, C7, R8).

`@node("writer")` gives a node:
  * per-node timeout (`nodes.timeouts.<name>` or default) and bounded retries with backoff
    (the LLM layer additionally falls back to a smaller model on its last attempt);
  * step + token accounting into state (`steps`, `tokens`, `usage[node]`), enforced against the
    thread budgets in config -> over budget moves the thread to a visible `needs_attention` state;
  * Degraded (marketplace down) -> `queued_degraded` (the worker retries later; UI shows banner);
  * any other failure after retries -> `dead_letter` with the error kept for the run viewer;
  * custom stream events ("node_start"/"node_end") so the UI can show live node-by-node progress.
"""

from __future__ import annotations

import asyncio
import functools
import time
from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.errors import GraphBubbleUp

from agent.llm import current_ledger, start_ledger
from agent.mcp_client import Degraded
from agent.settings import cfg

TERMINAL = {"skipped", "rejected", "blocked", "needs_attention", "dead_letter", "queued_degraded", "submitted", "duplicate"}


class BudgetExceeded(RuntimeError):
    pass


def _emit(event: dict[str, Any]) -> None:
    try:
        from langgraph.config import get_stream_writer

        get_stream_writer()(event)
    except Exception:  # noqa: BLE001 - outside a streaming run
        pass


def node(name: str, budget_key: str = "max_tokens_per_job"):
    def deco(fn: Callable[[dict], Awaitable[dict]]):
        @functools.wraps(fn)
        async def wrapper(state: dict) -> dict:
            steps = state.get("steps", 0) + 1
            if steps > cfg("budgets.max_graph_steps", 40):
                return {"status": "needs_attention", "status_reason": f"step budget exceeded at {name}", "steps": 1}
            if state.get("tokens", 0) > cfg(f"budgets.{budget_key}", 30000):
                return {"status": "needs_attention", "status_reason": f"token budget exceeded before {name}", "steps": 1}
            led = current_ledger() or start_ledger()
            before = len(led.records)
            t0 = time.perf_counter()
            _emit({"type": "node_start", "node": name, "ts": time.time()})
            attempts = cfg("nodes.max_attempts", 2)
            timeout = cfg(f"nodes.timeouts.{name}", cfg("nodes.timeouts.default", 120))
            last_err: Exception | None = None
            out: dict | None = None
            for attempt in range(attempts):
                try:
                    out = await asyncio.wait_for(fn(state), timeout)
                    break
                except GraphBubbleUp:
                    raise  # interrupt() / Command: must reach LangGraph untouched
                except Degraded as e:
                    _emit({"type": "node_end", "node": name, "status": "degraded"})
                    return {"status": "queued_degraded", "status_reason": str(e), "steps": 1,
                            "errors": [f"{name}: {e}"]}
                except BudgetExceeded as e:
                    return {"status": "needs_attention", "status_reason": str(e), "steps": 1}
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    await asyncio.sleep(0.5 * 2**attempt)
            dt = round(time.perf_counter() - t0, 3)
            recs = led.records[before:]
            tok = sum(r.input_tokens + r.output_tokens for r in recs)
            usage = {name: {"tokens": tok, "cost_usd": round(sum(r.cost_usd for r in recs), 6), "calls": len(recs),
                            "latency_s": dt}}
            if out is None:
                _emit({"type": "node_end", "node": name, "status": "failed", "latency_s": dt})
                return {"status": "dead_letter", "status_reason": f"{name} failed: {type(last_err).__name__}: {last_err}"[:500],
                        "errors": [f"{name}: {last_err}"], "steps": 1, "tokens": tok, "usage": usage, "timings": {name: dt}}
            _emit({"type": "node_end", "node": name, "status": "ok", "latency_s": dt, "tokens": tok})
            return {**out, "steps": 1, "tokens": tok, "usage": usage, "timings": {name: dt}}

        wrapper.node_name = name  # type: ignore[attr-defined]
        return wrapper

    return deco
