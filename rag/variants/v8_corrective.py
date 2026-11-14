"""V8: corrective / self-RAG loop as a LangGraph sub-graph.

retrieve -> grade (cross-encoder relevance per requirement) -> weak requirements are rewritten
and re-queried (at most `rag.corrective_max_requeries` times) -> requirements that still have
no relevant evidence are reported as `unsupported_requirements` and their evidence is dropped,
so the Writer is told to make NO claim about them ("refuse to claim when none").
"""

from __future__ import annotations

import asyncio
import math
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from agent.settings import cfg
from rag.index.embed import rerank
from rag.variants.pipeline import (
    EvidenceHit,
    Pipeline,
    Query,
    RetrievalResult,
    heuristic_requirements,
)
from scripts.data.taxonomy import SKILLS, extract_skills

NAME = "v8_corrective"


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def heuristic_rewrite(text: str) -> str:
    """Expand with taxonomy aliases so implied phrasing meets explicit skill names (no LLM)."""
    skills = extract_skills(text)
    extra = []
    for s in skills:
        extra += SKILLS.get(s, [])[:3]
    return f"{text} {' '.join(extra)}".strip() if extra else f"{text} project experience results"


class CState(TypedDict, total=False):
    persona: str
    query: Query
    filters: dict | None
    k: int
    requirements: list[dict]
    hits: dict[str, list[EvidenceHit]]
    grades: dict[str, float]
    rounds: int
    rewrites: dict[str, str]
    trace: list[dict]


class CorrectiveRetriever:
    def __init__(self, base: Pipeline, use_llm_rewrite: bool = False):
        self.base = base
        self.use_llm_rewrite = use_llm_rewrite
        self.min_score = cfg("rag.corrective_min_score", 0.35)
        self.max_rounds = cfg("rag.corrective_max_requeries", 2)
        self.graph = self._build()

    # ---------------------------------------------------------------- nodes
    def _retrieve(self, s: CState) -> dict:
        hits = dict(s.get("hits") or {})
        for r in s["requirements"]:
            if r["id"] in hits and s.get("grades", {}).get(r["id"], 0) >= self.min_score:
                continue
            text = s.get("rewrites", {}).get(r["id"], r["text"])
            sub = Query(s["query"].title, s["query"].description, [{"id": r["id"], "text": text}])
            res = self.base.retrieve(s["persona"], sub, k=s["k"], filters=s.get("filters"))
            hits[r["id"]] = res.items[: s["k"]]
        return {"hits": hits}

    def _grade(self, s: CState) -> dict:
        grades = {}
        for r in s["requirements"]:
            hs = s["hits"].get(r["id"], [])
            if not hs:
                grades[r["id"]] = 0.0
                continue
            scores = rerank(r["text"], [h.snippet for h in hs[:5]])
            grades[r["id"]] = max(_sigmoid(x) for x in scores) if scores else 0.0
        tr = list(s.get("trace") or []) + [{"round": s.get("rounds", 0), "grades": grades}]
        return {"grades": grades, "trace": tr}

    async def _rewrite_llm(self, text: str, title: str) -> str:
        from agent.llm import complete
        from agent.prompts import load_prompt

        p = load_prompt("query_rewrite")
        out = await complete("scout", p.text, f"Job: {title}\nRequirement: {text}", max_tokens=80)
        return out.strip().split("\n")[0][:300] or heuristic_rewrite(text)

    def _rewrite(self, s: CState) -> dict:
        rewrites = dict(s.get("rewrites") or {})
        for r in s["requirements"]:
            if s["grades"].get(r["id"], 0) < self.min_score:
                base = rewrites.get(r["id"], r["text"])
                if self.use_llm_rewrite:
                    try:
                        rewrites[r["id"]] = asyncio.run(self._rewrite_llm(base, s["query"].title))
                        continue
                    except Exception:  # noqa: BLE001 - fall back to deterministic expansion
                        pass
                rewrites[r["id"]] = heuristic_rewrite(base)
        return {"rewrites": rewrites, "rounds": s.get("rounds", 0) + 1}

    def _route(self, s: CState) -> str:
        weak = [rid for rid, g in s["grades"].items() if g < self.min_score]
        return "rewrite" if weak and s.get("rounds", 0) < self.max_rounds else END

    def _build(self):
        g = StateGraph(CState)
        g.add_node("retrieve", self._retrieve)
        g.add_node("grade", self._grade)
        g.add_node("rewrite", self._rewrite)
        g.set_entry_point("retrieve")
        g.add_edge("retrieve", "grade")
        g.add_conditional_edges("grade", self._route, {"rewrite": "rewrite", END: END})
        g.add_edge("rewrite", "retrieve")
        return g.compile()

    # ---------------------------------------------------------------- API
    def retrieve(self, persona: str, q: Query, k: int | None = None, filters: dict | None = None) -> RetrievalResult:
        k = k or cfg("rag.top_k", 5)
        reqs = q.requirements or heuristic_requirements(q.title, q.description)
        final: dict[str, Any] = self.graph.invoke(
            {"persona": persona, "query": q, "filters": filters, "k": k, "requirements": reqs, "rounds": 0}
        )
        return self._finalize(final, k)

    async def aretrieve(self, persona: str, q: Query, k: int | None = None, filters: dict | None = None) -> RetrievalResult:
        return await asyncio.to_thread(self.retrieve, persona, q, k, filters)

    def _finalize(self, s: dict, k: int) -> RetrievalResult:
        unsupported = [rid for rid, g in s["grades"].items() if g < self.min_score]
        per_req = {rid: [h.evidence_id for h in hs] for rid, hs in s["hits"].items() if rid not in unsupported}
        best: dict[str, EvidenceHit] = {}
        order: list[str] = []
        queues = {rid: list(hs) for rid, hs in s["hits"].items() if rid not in unsupported}
        while any(queues.values()):
            for rid, qu in queues.items():
                while qu:
                    h = qu.pop(0)
                    if h.evidence_id not in best:
                        best[h.evidence_id] = h
                        order.append(h.evidence_id)
                        break
                    if rid not in best[h.evidence_id].requirement_ids:
                        best[h.evidence_id].requirement_ids.append(rid)
        return RetrievalResult(
            items=[best[e] for e in order][: max(k, 10)],
            per_requirement=per_req,
            unsupported_requirements=unsupported,
            trace={"variant": NAME, "rounds": s.get("rounds", 0), "grades": s["grades"],
                   "rewrites": s.get("rewrites", {}), "history": s.get("trace", [])},
        )
