"""Portfolio index: dense (cosine) + BM25 over chunks, with metadata filters.

`PortfolioIndex` holds two chunk sets per persona:
  * structured  - heading/code/item-aware chunks with metadata (used by V1+)
  * fixed       - naive fixed-size windows over raw item text, no metadata (V0 baseline)

The same object backs evals (in memory) and the API. In production the chunk rows and vectors
are also persisted to Postgres/pgvector (rag/index/pg.py) so the index survives restarts and
supports incremental re-indexing; this in-memory view is rebuilt from those rows on start-up.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

from rag.index.embed import embed
from rag.ingest.loaders import PERSONA_DIR, Chunk, load_persona, split_words

_TOKEN = re.compile(r"[a-z0-9][a-z0-9+#.\-]*")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


@dataclass
class _Part:
    chunks: list[Chunk]
    vecs: np.ndarray
    bm25: BM25Okapi
    by_id: dict[str, int] = field(default_factory=dict)


class PortfolioIndex:
    def __init__(self) -> None:
        self.parts: dict[tuple[str, str], _Part] = {}
        self.items: dict[str, dict] = {}  # evidence_id -> manifest metadata

    # ------------------------------------------------------------------ build
    def build(self, persona: str, chunks: list[Chunk] | None = None, context_lines: dict[str, str] | None = None) -> None:
        chunks = chunks if chunks is not None else load_persona(persona)
        if context_lines:
            for c in chunks:
                c.context = context_lines.get(c.chunk_id, "")
        self._set(persona, "structured", chunks)
        self._set(persona, "fixed", fixed_chunks(persona, chunks))
        man = PERSONA_DIR / persona / "manifest.json"
        if man.exists():
            for m in json.loads(man.read_text())["items"]:
                self.items[m["id"]] = m

    def add_chunks(self, persona: str, new: list[Chunk]) -> int:
        """Incremental re-index: replace chunks of the same evidence items, keep the rest."""
        part = self.parts.get((persona, "structured"))
        ids = {c.evidence_id for c in new}
        keep = [c for c in (part.chunks if part else []) if c.evidence_id not in ids]
        self._set(persona, "structured", keep + new)
        return len(new)

    def _set(self, persona: str, kind: str, chunks: list[Chunk]) -> None:
        texts = [(c.context + "\n" + c.text).strip() for c in chunks]
        vecs = embed(texts) if texts else np.zeros((0, 768), dtype=np.float32)
        bm25 = BM25Okapi([tokenize(t) for t in texts] or [["empty"]])
        self.parts[(persona, kind)] = _Part(chunks, vecs, bm25, {c.chunk_id: i for i, c in enumerate(chunks)})

    # ------------------------------------------------------------------ search
    def _mask(self, part: _Part, filters: dict | None) -> np.ndarray:
        n = len(part.chunks)
        m = np.ones(n, dtype=bool)
        if not filters:
            return m
        for i, c in enumerate(part.chunks):
            if "type" in filters and c.type not in _as_list(filters["type"]):
                m[i] = False
            if "skills" in filters and not set(_as_list(filters["skills"])) & set(c.skills):
                m[i] = False
            if "outcome" in filters and c.outcome not in _as_list(filters["outcome"]):
                m[i] = False
            if "client_industry" in filters and (c.client_industry or "").lower() not in [x.lower() for x in _as_list(filters["client_industry"])]:
                m[i] = False
            if "since" in filters and (c.date or "") < filters["since"]:
                m[i] = False
        return m

    def dense(self, persona: str, query: str, k: int = 30, kind: str = "structured",
              filters: dict | None = None, qvec: np.ndarray | None = None) -> list[tuple[Chunk, float]]:
        part = self.parts[(persona, kind)]
        if not part.chunks:
            return []
        q = qvec if qvec is not None else embed([query], kind="query")[0]
        scores = part.vecs @ q
        scores = np.where(self._mask(part, filters), scores, -np.inf)
        top = np.argsort(-scores)[:k]
        return [(part.chunks[i], float(scores[i])) for i in top if np.isfinite(scores[i])]

    def bm25(self, persona: str, query: str, k: int = 30, kind: str = "structured",
             filters: dict | None = None) -> list[tuple[Chunk, float]]:
        part = self.parts[(persona, kind)]
        if not part.chunks:
            return []
        scores = np.asarray(part.bm25.get_scores(tokenize(query)), dtype=float)
        scores = np.where(self._mask(part, filters), scores, -np.inf)
        top = np.argsort(-scores)[:k]
        return [(part.chunks[i], float(scores[i])) for i in top if np.isfinite(scores[i]) and scores[i] > 0]

    def chunks(self, persona: str, kind: str = "structured") -> list[Chunk]:
        return self.parts[(persona, kind)].chunks

    def item_chunks(self, persona: str, evidence_id: str) -> list[Chunk]:
        return [c for c in self.chunks(persona) if c.evidence_id == evidence_id]

    def project_items(self, persona: str, project: str) -> list[str]:
        return sorted({c.evidence_id for c in self.chunks(persona) if c.project == project})


def _as_list(x) -> list:
    return x if isinstance(x, list) else [x]


def fixed_chunks(persona: str, structured: list[Chunk], words: int = 200) -> list[Chunk]:
    """V0 baseline chunks: concatenate each item's raw text, then cut fixed windows (no metadata)."""
    by_item: dict[str, list[Chunk]] = {}
    for c in structured:
        by_item.setdefault(c.evidence_id, []).append(c)
    out = []
    for eid, cs in by_item.items():
        text = "\n".join(c.text for c in cs)
        for i, w in enumerate(split_words(text, words, 0)):
            out.append(Chunk(chunk_id=f"{eid}#fixed{i}", evidence_id=eid, persona=persona, type=cs[0].type,
                             text=w, title=cs[0].title, project=cs[0].project, date=cs[0].date,
                             outcome=cs[0].outcome))
    return out


_GLOBAL: PortfolioIndex | None = None


def get_index(personas: list[str] | None = None) -> PortfolioIndex:
    """Process-wide index (built lazily from data/personas)."""
    global _GLOBAL
    if _GLOBAL is None:
        _GLOBAL = PortfolioIndex()
        for p in personas or sorted(x.name for x in Path(PERSONA_DIR).iterdir() if (x / "manifest.json").exists()):
            _GLOBAL.build(p)
    return _GLOBAL
