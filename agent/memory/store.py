"""Long-term memory on the LangGraph store (PostgresStore in production, InMemoryStore in tests).

Namespaces
  ("events", user, "edits")              raw approved-edit pattern log      (NOT memory)
  ("events", user, "outcomes")           raw marketplace outcome log         (NOT memory)
  ("memory", user, "style")              promoted style rules               (memory)
  ("memory", user, "outcome")            promoted outcome insights per category (memory)
Only `promote()` writes the memory namespaces, and only through promotion_rules.
The Settings screen lists and deletes items in the memory namespaces.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from langgraph.store.base import BaseStore

from agent.memory.promotion_rules import edit_patterns, promote_outcomes, promote_style


async def record_edit(store: BaseStore, user: str, draft: str, edited: str, thread_id: str) -> list[str]:
    pats = edit_patterns(draft, edited)
    await store.aput(("events", user, "edits"), f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}",
                     {"patterns": pats, "thread_id": thread_id, "at": time.time()})
    await promote(store, user)
    return pats


async def record_outcome(store: BaseStore, user: str, category: str, strategy: str, replied: bool, ref: str) -> None:
    await store.aput(("events", user, "outcomes"), ref, {"category": category, "strategy": strategy,
                                                          "replied": bool(replied), "at": time.time()})
    await promote(store, user)


async def _all(store: BaseStore, ns: tuple, limit: int = 1000) -> list:
    return await store.asearch(ns, limit=limit)


async def promote(store: BaseStore, user: str) -> dict[str, Any]:
    edits = sorted(await _all(store, ("events", user, "edits")), key=lambda i: i.key)
    style = promote_style([i.value["patterns"] for i in edits])
    deleted = {i.key for i in await _all(store, ("events", user, "deleted_memory"))}
    for pattern, v in style.items():
        if f"style:{pattern}" not in deleted:
            await store.aput(("memory", user, "style"), pattern, {**v, "promoted_at": time.time()})
    outs = [i.value for i in await _all(store, ("events", user, "outcomes"))]
    insight = promote_outcomes(outs)
    for cat, v in insight.items():
        if f"outcome:{cat}" not in deleted:
            await store.aput(("memory", user, "outcome"), cat, {**v, "promoted_at": time.time()})
    return {"style": style, "outcome": insight}


async def style_rules(store: BaseStore | None, user: str) -> list[str]:
    if store is None:
        return []
    return [i.value["rule"] for i in await _all(store, ("memory", user, "style"))]


async def outcome_hint(store: BaseStore | None, user: str, category: str) -> dict | None:
    if store is None:
        return None
    item = await store.aget(("memory", user, "outcome"), category)
    return item.value if item else None


async def list_memory(store: BaseStore, user: str) -> list[dict]:
    out = []
    for kind in ("style", "outcome"):
        for i in await _all(store, ("memory", user, kind)):
            out.append({"kind": kind, "key": i.key, **i.value})
    return out


async def delete_memory(store: BaseStore, user: str, kind: str, key: str) -> None:
    """User deletes something GigBid learned; a tombstone stops it being re-promoted."""
    await store.adelete(("memory", user, kind), key)
    await store.aput(("events", user, "deleted_memory"), f"{kind}:{key}", {"at": time.time()})
