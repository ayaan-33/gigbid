"""One configurable retrieval pipeline; every variant V0..V8 is a preset of its flags, so
ablations switch one component off at a time and the full comparison is one command.

Flags
  chunks       "fixed" (V0) | "structured"
  decompose    retrieve once per extracted requirement, then coverage-aware merge   (V1)
  hybrid       BM25 + dense with reciprocal rank fusion                              (V2)
  rerank       cross-encoder rerank of the fused candidates                          (V3)
  outcome      boost evidence/phrasing from proposals that won or got replies        (V4)
  multivector  summary/README/code views scored per project, returned as one project (V5)
  contextual   chunks indexed with a generated context line (index built with it)   (V6)
  hyde         query with a hypothetical ideal proposal paragraph                    (V7)
  corrective   grade evidence, re-query when weak, refuse to claim when none         (V8, see v8_corrective)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from agent.settings import cfg
from rag.index.embed import embed, rerank
from rag.index.store import PortfolioIndex
from rag.ingest.loaders import Chunk


@dataclass
class Flags:
    chunks: str = "structured"
    decompose: bool = False
    hybrid: bool = False
    rerank: bool = False
    outcome: bool = False
    multivector: bool = False
    contextual: bool = False
    hyde: bool = False
    corrective: bool = False


@dataclass
class EvidenceHit:
    evidence_id: str
    score: float
    chunk_id: str
    snippet: str
    type: str
    title: str
    project: str | None
    outcome: str | None
    requirement_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class RetrievalResult:
    items: list[EvidenceHit]
    per_requirement: dict[str, list[str]]
    unsupported_requirements: list[str] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)

    @property
    def ids(self) -> list[str]:
        return [h.evidence_id for h in self.items]


@dataclass
class Query:
    """What retrieval needs from the job. `requirements` come from the Job Analyst's JobSpec
    (or the heuristic extractor below when no JobSpec is available)."""

    title: str
    description: str
    requirements: list[dict] = field(default_factory=list)  # [{id, text}]
    hyde_text: str | None = None

    @property
    def whole(self) -> str:
        return f"{self.title}\n{self.description}"


_BULLET = re.compile(r"^\s*[-*•]\s+(.+)$", re.M)


def heuristic_requirements(title: str, description: str, max_n: int = 6) -> list[dict]:
    """Bullets first, then sentences that name a skill; deterministic, no LLM."""
    from scripts.data.taxonomy import extract_skills

    bullets = [b.strip() for b in _BULLET.findall(description)]
    reqs = bullets[:max_n]
    if len(reqs) < 2:
        for s in re.split(r"(?<=[.!?])\s+", description):
            if extract_skills(s) and s not in reqs:
                reqs.append(s.strip()[:200])
            if len(reqs) >= max_n:
                break
    if not reqs:
        reqs = [title]
    return [{"id": f"r{i + 1}", "text": r} for i, r in enumerate(reqs)]


def _rrf(lists: list[list[tuple[Chunk, float]]], k: int) -> dict[str, tuple[Chunk, float]]:
    out: dict[str, tuple[Chunk, float]] = {}
    for lst in lists:
        for rank, (c, _) in enumerate(lst):
            prev = out.get(c.chunk_id)
            s = 1.0 / (k + rank + 1)
            out[c.chunk_id] = (c, (prev[1] if prev else 0.0) + s)
    return out


class Pipeline:
    def __init__(self, index: PortfolioIndex, flags: Flags, name: str = "custom"):
        self.index, self.flags, self.name = index, flags, name
        self.top_k = cfg("rag.top_k", 5)
        self.cand_k = cfg("rag.candidate_k", 30)
        self.rrf_k = cfg("rag.rrf_k", 60)

    # -------------------------------------------------------------- one query -> scored chunks
    def _search(self, persona: str, text: str, filters: dict | None, qvec: np.ndarray | None = None) -> list[tuple[Chunk, float]]:
        f = self.flags
        kind = "fixed" if f.chunks == "fixed" else "structured"
        dense = self.index.dense(persona, text, self.cand_k, kind, filters, qvec=qvec)
        if not f.hybrid:
            cands = dense
        else:
            sparse = self.index.bm25(persona, text, self.cand_k, kind, filters)
            fused = _rrf([dense, sparse], self.rrf_k)
            cands = sorted(fused.values(), key=lambda t: -t[1])[: self.cand_k]
        if f.rerank and cands:
            scores = rerank(text, [(c.context + "\n" + c.text)[:1500] for c, _ in cands])
            cands = sorted(zip([c for c, _ in cands], scores, strict=True), key=lambda t: -t[1])
        return cands

    def _boost(self, persona: str, scored: list[tuple[Chunk, float]]) -> list[tuple[Chunk, float]]:
        if not self.flags.outcome or not scored:
            return scored
        boost = cfg("rag.outcome_boost", {"won": 0.25, "replied": 0.12, "ignored": -0.1})
        wins = project_win_rates(self.index, persona)
        vals = np.array([s for _, s in scored], dtype=float)
        lo, hi = float(vals.min()), float(vals.max())
        span = (hi - lo) or 1.0
        out = []
        for c, s in scored:
            norm = (s - lo) / span
            b = boost.get(c.outcome or "", 0.0) if c.type == "proposal" else 0.0
            b += 0.15 * wins.get(c.project or "", 0.0)
            out.append((c, norm + b))
        return sorted(out, key=lambda t: -t[1])

    # -------------------------------------------------------------- full retrieval
    def retrieve(self, persona: str, q: Query, k: int | None = None, filters: dict | None = None) -> RetrievalResult:
        k = k or self.top_k
        f = self.flags
        trace: dict[str, Any] = {"variant": self.name, "flags": f.__dict__.copy(), "queries": []}
        reqs = (q.requirements or heuristic_requirements(q.title, q.description)) if f.decompose else []
        per_req_chunks: dict[str, list[tuple[Chunk, float]]] = {}
        if reqs:
            for r in reqs:
                text = f"{r['text']} ({q.title})"
                trace["queries"].append(text)
                per_req_chunks[r["id"]] = self._boost(persona, self._search(persona, text, filters))
        else:
            text = q.whole[:2000]
            qvec = None
            if f.hyde and q.hyde_text:
                qv = embed([q.hyde_text, text], kind="query")
                qvec = qv[0] * 0.6 + qv[1] * 0.4
                qvec /= np.linalg.norm(qvec) + 1e-9
            trace["queries"].append(text[:200])
            per_req_chunks["all"] = self._boost(persona, self._search(persona, q.hyde_text or text, filters, qvec))
        if f.hyde and q.hyde_text and reqs:
            per_req_chunks["hyde"] = self._boost(persona, self._search(persona, q.hyde_text, filters))
        items = self._merge(persona, per_req_chunks, k)
        per_req = {rid: _dedupe([c.evidence_id for c, _ in lst])[:k] for rid, lst in per_req_chunks.items()}
        return RetrievalResult(items=items, per_requirement=per_req, trace=trace)

    def _merge(self, persona: str, per_req: dict[str, list[tuple[Chunk, float]]], k: int) -> list[EvidenceHit]:
        """Coverage-aware merge: round-robin over requirements so every requirement gets its
        best evidence before any requirement gets its second; items aggregate by max score."""
        if self.flags.multivector:
            per_req = {rid: _project_group(self.index, persona, lst) for rid, lst in per_req.items()}
        best: dict[str, EvidenceHit] = {}
        order: list[str] = []
        queues = {rid: list(lst) for rid, lst in per_req.items()}
        while any(queues.values()) and len(order) < max(k * 4, 20):
            for rid, qu in queues.items():
                while qu:
                    c, s = qu.pop(0)
                    h = best.get(c.evidence_id)
                    if h is None:
                        best[c.evidence_id] = EvidenceHit(c.evidence_id, s, c.chunk_id, c.text[:400], c.type, c.title,
                                                          c.project, c.outcome, [rid])
                        order.append(c.evidence_id)
                        break
                    if rid not in h.requirement_ids:
                        h.requirement_ids.append(rid)
                    h.score = max(h.score, s)
        hits = [best[e] for e in order]
        return hits[: max(k, 10)]


def _dedupe(xs: list[str]) -> list[str]:
    seen, out = set(), []
    for x in xs:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _project_group(index: PortfolioIndex, persona: str, lst: list[tuple[Chunk, float]]) -> list[tuple[Chunk, float]]:
    """V5: score each project by its best view, then emit all of that project's items together."""
    proj_score: dict[str, float] = {}
    loose: list[tuple[Chunk, float]] = []
    for c, s in lst:
        if c.project:
            proj_score[c.project] = max(proj_score.get(c.project, -1e9), s)
        else:
            loose.append((c, s))
    out: list[tuple[Chunk, float]] = []
    chunks = index.chunks(persona)
    for proj, s in sorted(proj_score.items(), key=lambda t: -t[1]):
        rank = {"case_study": 0, "repo": 1, "review": 2, "proposal": 3}
        seen: set[str] = set()
        for c in sorted((c for c in chunks if c.project == proj and c.type != "proposal"), key=lambda c: rank.get(c.type, 9)):
            if c.evidence_id not in seen:
                seen.add(c.evidence_id)
                out.append((c, s))
    out += loose
    return out


_WIN_CACHE: dict[str, dict[str, float]] = {}


def project_win_rates(index: PortfolioIndex, persona: str) -> dict[str, float]:
    """Share of past proposals citing a project that won or got a reply (outcome memory signal)."""
    if persona in _WIN_CACHE:
        return _WIN_CACHE[persona]
    tot: dict[str, int] = {}
    good: dict[str, int] = {}
    for m in index.items.values():
        if m.get("type") != "proposal" or not m["id"].startswith(persona):
            continue
        for p in m.get("cited_projects") or []:
            tot[p] = tot.get(p, 0) + 1
            good[p] = good.get(p, 0) + (m.get("outcome") in ("won", "replied"))
    rates = {p: good[p] / tot[p] for p in tot if tot[p] >= 2}
    _WIN_CACHE[persona] = rates
    return rates
