"""Portfolio loaders + chunkers (B1).

Every chunk carries: persona, evidence_id (item), chunk_id, type, project, title, skills,
date, client_industry, outcome (proposals), view (summary | readme | code | prose), source.

Loaders: PDF CV (pypdf), Markdown case studies, repo READMEs + code (local folder or via the
GitHub MCP server, see rag/ingest/github_mcp.py), reviews (JSON) and past proposals (JSONL).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from scripts.data.taxonomy import extract_skills

ROOT = Path(__file__).resolve().parents[2]
PERSONA_DIR = ROOT / "data" / "personas"
CODE_EXT = {".py", ".ts", ".tsx", ".js", ".sql", ".dax", ".vue"}
CONFIG_FILES = {"requirements.txt", "package.json", "Dockerfile"}


@dataclass
class Chunk:
    chunk_id: str
    evidence_id: str
    persona: str
    type: str
    text: str
    title: str = ""
    project: str | None = None
    skills: list[str] = field(default_factory=list)
    date: str | None = None
    client_industry: str | None = None
    outcome: str | None = None
    view: str = "prose"
    source: str = ""
    context: str = ""  # V6 contextual-retrieval line (filled by the indexer when enabled)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def content_hash(self) -> str:
        return hashlib.sha1(self.text.encode()).hexdigest()[:16]


def _words(text: str) -> list[str]:
    return text.split()


def split_words(text: str, max_words: int = 220, overlap: int = 40) -> list[str]:
    w = _words(text)
    if len(w) <= max_words:
        return [text.strip()]
    out, i = [], 0
    while i < len(w):
        out.append(" ".join(w[i : i + max_words]))
        i += max_words - overlap
    return out


def split_markdown(md: str) -> list[tuple[str, str]]:
    """(heading, body) sections; headings kept so fragments keep their meaning."""
    sections, head, buf = [], "", []
    for line in md.splitlines():
        if line.startswith("#"):
            if buf:
                sections.append((head, "\n".join(buf).strip()))
            head, buf = line.lstrip("# ").strip(), []
        else:
            buf.append(line)
    if buf:
        sections.append((head, "\n".join(buf).strip()))
    return [(h, b) for h, b in sections if b]


def split_code(src: str, max_lines: int = 60) -> list[str]:
    """Split code at top-level defs/classes/exports, capped at max_lines per chunk."""
    lines = src.splitlines()
    starts = [i for i, ln in enumerate(lines) if re.match(r"^(def |class |async def |export |@app|with DAG|[A-Z_]+ = )", ln)]
    starts = sorted(set([0] + starts))
    blocks = []
    for a, b in zip(starts, starts[1:] + [len(lines)], strict=False):
        block = lines[a:b]
        for k in range(0, len(block), max_lines):
            text = "\n".join(block[k : k + max_lines]).strip()
            if text:
                blocks.append(text)
    # attach the import header to the first block so libraries stay visible
    return blocks


# --------------------------------------------------------------------------- per-type loaders


def load_case_study(pid: str, path: Path) -> list[Chunk]:
    raw = path.read_text(encoding="utf-8")
    _, front, body = raw.split("---", 2)
    meta = json.loads(front.strip())
    out = []
    for i, (head, text) in enumerate(split_markdown(body)):
        for j, part in enumerate(split_words(text)):
            out.append(Chunk(
                chunk_id=f"{meta['id']}#s{i}.{j}", evidence_id=meta["id"], persona=pid, type="case_study",
                text=f"{meta['title']} — {head}\n{part}" if head else part, title=meta["title"],
                project=meta["project"], skills=sorted(set(meta["skills"]) | set(extract_skills(part))),
                date=meta["date"], client_industry=meta["client_industry"], view="summary" if i <= 1 else "prose",
                source=str(path.relative_to(ROOT)),
            ))
    return out


def load_cv(pid: str, path: Path) -> list[Chunk]:
    text = "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    out = []
    # CV sections are separated by their headings; fall back to word windows
    parts = re.split(r"\n(?=(Summary|Skills|Selected freelance work|Education)\n)", text)
    parts = [p for p in parts if p and p not in {"Summary", "Skills", "Selected freelance work", "Education"}]
    for i, part in enumerate(parts):
        for j, w in enumerate(split_words(part, 180, 30)):
            out.append(Chunk(chunk_id=f"{pid}:cv#{i}.{j}", evidence_id=f"{pid}:cv", persona=pid, type="cv",
                             text=w, title="CV", skills=extract_skills(w), date="2026-10-01",
                             source=str(path.relative_to(ROOT))))
    return out


def load_repo(pid: str, repo_dir: Path, meta: dict) -> list[Chunk]:
    out = []
    eid = meta["id"]
    readme = repo_dir / "README.md"
    if readme.exists():
        t = readme.read_text(encoding="utf-8")
        out.append(Chunk(chunk_id=f"{eid}#readme", evidence_id=eid, persona=pid, type="repo", text=t,
                         title=meta["title"], project=meta["project"], skills=extract_skills(t), date=meta["date"],
                         client_industry=meta.get("client_industry"), view="readme",
                         source=str(readme.relative_to(ROOT))))
    for f in sorted(repo_dir.rglob("*")):
        if not f.is_file() or f.name == "README.md":
            continue
        if f.suffix not in CODE_EXT and f.name not in CONFIG_FILES:
            continue
        src = f.read_text(encoding="utf-8", errors="ignore")
        blocks = split_code(src) if f.suffix in CODE_EXT else [src]
        for k, block in enumerate(blocks):
            text = f"# file: {meta['title']}/{f.relative_to(repo_dir)}\n{block}"
            out.append(Chunk(chunk_id=f"{eid}#{f.relative_to(repo_dir)}:{k}", evidence_id=eid, persona=pid, type="repo",
                             text=text, title=meta["title"], project=meta["project"], skills=extract_skills(text),
                             date=meta["date"], client_industry=meta.get("client_industry"), view="code",
                             source=str(f.relative_to(ROOT))))
    return out


def load_reviews(pid: str, path: Path) -> list[Chunk]:
    out = []
    for r in json.loads(path.read_text()):
        out.append(Chunk(chunk_id=f"{r['id']}#0", evidence_id=r["id"], persona=pid, type="review",
                         text=f"Client review ({r['stars']}/5, {r['client_industry']}): {r['text']}",
                         title=f"Review {r['stars']}/5", project=r["project"], skills=extract_skills(r["text"]),
                         date=r["date"], client_industry=r["client_industry"], source=str(path.relative_to(ROOT))))
    return out


def load_proposals(pid: str, path: Path) -> list[Chunk]:
    out = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        p = json.loads(line)
        out.append(Chunk(chunk_id=f"{p['id']}#0", evidence_id=p["id"], persona=pid, type="proposal",
                         text=f"Past proposal for '{p['job_title']}' (outcome: {p['outcome']}):\n{p['text']}",
                         title=p["job_title"][:80], project=(p["cited_projects"] or [None])[0],
                         skills=sorted(set(p["job_skills"]) | set(extract_skills(p["text"]))), date=p["date"],
                         outcome=p["outcome"], source=str(path.relative_to(ROOT))))
    return out


def load_persona(pid: str, root: Path | None = None) -> list[Chunk]:
    base = (root or PERSONA_DIR) / pid
    manifest = {m["id"]: m for m in json.loads((base / "manifest.json").read_text())["items"]}
    chunks: list[Chunk] = []
    for f in sorted((base / "case_studies").glob("*.md")):
        chunks += load_case_study(pid, f)
    if (base / "cv.pdf").exists():
        chunks += load_cv(pid, base / "cv.pdf")
    for m in manifest.values():
        if m["type"] == "repo":
            chunks += load_repo(pid, base / m["path"], m)
    if (base / "reviews.json").exists():
        chunks += load_reviews(pid, base / "reviews.json")
    if (base / "proposals.jsonl").exists():
        chunks += load_proposals(pid, base / "proposals.jsonl")
    return chunks


def load_uploaded(pid: str, filename: str, data: bytes, kind: str) -> list[Chunk]:
    """User uploads from the UI (PDF CV, Markdown case study, plain text). Incremental index."""
    eid = f"{pid}:upload:{hashlib.sha1(filename.encode()).hexdigest()[:10]}"
    if filename.lower().endswith(".pdf"):
        import io

        text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)
    else:
        text = data.decode("utf-8", errors="ignore")
    parts = [b for _, b in split_markdown(text)] if filename.endswith(".md") else split_words(text)
    return [Chunk(chunk_id=f"{eid}#{i}", evidence_id=eid, persona=pid, type=kind, text=p, title=filename,
                  skills=extract_skills(p), source=f"upload:{filename}") for i, p in enumerate(parts) if p.strip()]
