"""Retriever factory: the deployed variant is chosen by config (rag.variant), which is set from
the evaluation results (docs/adr/0004-rag-variant.md), never by default in code."""

from __future__ import annotations

from agent.settings import cfg
from rag.index.store import PortfolioIndex, get_index
from rag.variants.pipeline import Pipeline, Query, RetrievalResult
from rag.variants.presets import PRESETS


def build(variant: str | None = None, index: PortfolioIndex | None = None):
    name = variant or cfg("rag.variant", "v3_rerank")
    idx = index or get_index()
    if name == "v8_corrective":
        from rag.variants.v8_corrective import CorrectiveRetriever

        return CorrectiveRetriever(Pipeline(idx, PRESETS["v3_rerank"], "v8_corrective"))
    if name not in PRESETS:
        raise ValueError(f"unknown RAG variant {name}; choose one of {sorted(PRESETS)}")
    return Pipeline(idx, PRESETS[name], name)


async def aretrieve(persona: str, q: Query, k: int | None = None, variant: str | None = None,
                    filters: dict | None = None) -> RetrievalResult:
    r = build(variant)
    if hasattr(r, "aretrieve"):
        return await r.aretrieve(persona, q, k=k, filters=filters)
    import asyncio

    return await asyncio.to_thread(r.retrieve, persona, q, k, filters)
