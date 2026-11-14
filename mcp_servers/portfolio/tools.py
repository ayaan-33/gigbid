"""Portfolio tools (read-only). Return evidence items with type, source, date and outcome."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field

from rag.index.store import PortfolioIndex, get_index
from rag.ingest.loaders import PERSONA_DIR
from rag.variants.pipeline import Query

EvidenceType = Literal["case_study", "repo", "review", "proposal", "cv", "upload"]


class EvidenceFilters(BaseModel):
    type: list[EvidenceType] | None = Field(None, description="only these evidence types")
    skills: list[str] | None = Field(None, description="evidence must mention at least one of these skills")
    outcome: list[Literal["won", "replied", "ignored"]] | None = Field(None, description="past proposals only: outcomes to keep")
    client_industry: list[str] | None = Field(None, description="e.g. ['fintech', 'SaaS']")
    since: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="ISO date; evidence on/after it")

    def as_dict(self) -> dict:
        return {k: v for k, v in self.model_dump().items() if v}


class EvidenceItem(BaseModel):
    id: str = Field(description="evidence id, cite it as [id] in proposals")
    type: str
    title: str
    source: str = Field(description="file or repo the evidence comes from")
    date: str | None
    outcome: str | None = Field(None, description="won | replied | ignored (past proposals only)")
    project: str | None
    client_industry: str | None = None
    snippet: str
    score: float
    matched_requirements: list[str] = []


class SearchResult(BaseModel):
    requirement: str
    items: list[EvidenceItem]
    variant: str


class CaseStudy(BaseModel):
    id: str
    title: str
    project: str
    client_industry: str
    date: str
    skills: list[str]
    markdown: str


class SkillSummary(BaseModel):
    skill: str
    evidence_count: int
    projects: list[str]


class PortfolioService:
    def __init__(self, index: PortfolioIndex | None = None, variant: str | None = None):
        self._index = index
        self.variant = variant

    @property
    def index(self) -> PortfolioIndex:
        if self._index is None:
            self._index = get_index()
        return self._index

    def search(self, persona: str, requirement: str, k: int, filters: EvidenceFilters | None) -> SearchResult:
        from rag.retriever import build

        r = build(self.variant, self.index)
        res = r.retrieve(persona, Query(title=requirement, description=requirement,
                                         requirements=[{"id": "r1", "text": requirement}]),
                         k, (filters.as_dict() if filters else None) or None)
        items = []
        for h in res.items[:k]:
            meta = self.index.items.get(h.evidence_id, {})
            items.append(EvidenceItem(id=h.evidence_id, type=h.type, title=h.title, source=meta.get("path", ""),
                                      date=meta.get("date"), outcome=h.outcome, project=h.project,
                                      client_industry=meta.get("client_industry"), snippet=h.snippet,
                                      score=round(h.score, 4), matched_requirements=h.requirement_ids))
        return SearchResult(requirement=requirement, items=items, variant=getattr(r, "name", "v8_corrective"))

    def case_study(self, persona: str, case_id: str) -> CaseStudy:
        key = case_id.split(":")[-1]
        path = PERSONA_DIR / persona / "case_studies" / f"{key}.md"
        if not path.exists() or not case_id.startswith(f"{persona}:case:"):
            raise ValueError(f"unknown case study {case_id!r} for this portfolio")
        raw = path.read_text()
        _, front, body = raw.split("---", 2)
        meta = json.loads(front)
        return CaseStudy(id=meta["id"], title=meta["title"], project=meta["project"],
                         client_industry=meta["client_industry"], date=meta["date"], skills=meta["skills"],
                         markdown=body.strip())

    def skills(self, persona: str) -> list[SkillSummary]:
        agg: dict[str, dict] = {}
        for c in self.index.chunks(persona):
            for s in c.skills:
                a = agg.setdefault(s, {"items": set(), "projects": set()})
                a["items"].add(c.evidence_id)
                if c.project:
                    a["projects"].add(c.project)
        return sorted((SkillSummary(skill=s, evidence_count=len(a["items"]), projects=sorted(a["projects"]))
                       for s, a in agg.items()), key=lambda x: -x.evidence_count)

    def proposal(self, persona: str, pid: str) -> dict:
        path = PERSONA_DIR / persona / "proposals.jsonl"
        for line in path.read_text().splitlines():
            p = json.loads(line)
            if p["id"] == pid:
                return p
        raise ValueError(f"unknown proposal {pid!r}")
