"""Open embedding + reranker models on CPU (fastembed / ONNX), with a persistent vector cache."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from functools import cache
from pathlib import Path

import numpy as np

from agent.settings import ROOT, cfg

_CACHE_PATH = Path(os.getenv("EMBED_CACHE_PATH", ROOT / ".cache" / "embeddings.sqlite"))
_lock = threading.Lock()


@cache
def _db() -> sqlite3.Connection:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(_CACHE_PATH, check_same_thread=False)
    c.execute("create table if not exists e (k text primary key, v blob)")
    return c


@cache
def _model():
    from fastembed import TextEmbedding

    return TextEmbedding(cfg("models.embeddings"), threads=int(os.getenv("EMBED_THREADS", "2")))


@cache
def _reranker(name: str | None = None):
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    return TextCrossEncoder(name or cfg("models.reranker"), threads=int(os.getenv("RERANK_THREADS", "4")))


def _prefix(kind: str) -> str:
    # nomic-embed-text requires task prefixes; other models ignore them harmlessly
    return "search_query: " if kind == "query" else "search_document: "


def embed(texts: list[str], kind: str = "document") -> np.ndarray:
    model_name = cfg("models.embeddings")
    keys = [hashlib.sha1(f"{model_name}|{kind}|{t}".encode()).hexdigest() for t in texts]
    out: list[np.ndarray | None] = [None] * len(texts)
    db = _db()
    with _lock:
        for i, k in enumerate(keys):
            row = db.execute("select v from e where k=?", (k,)).fetchone()
            if row:
                out[i] = np.frombuffer(row[0], dtype=np.float32)
    missing = [i for i, v in enumerate(out) if v is None]
    if missing:
        vecs = list(_model().embed([_prefix(kind) + texts[i] for i in missing], batch_size=32))
        with _lock:
            for i, v in zip(missing, vecs, strict=True):
                v = np.asarray(v, dtype=np.float32)
                v /= np.linalg.norm(v) + 1e-9
                out[i] = v
                db.execute("insert or replace into e values (?,?)", (keys[i], v.tobytes()))
            db.commit()
    return np.vstack(out) if out else np.zeros((0, cfg("models.embedding_dim", 768)), dtype=np.float32)


def rerank(query: str, docs: list[str]) -> list[float]:
    if not docs:
        return []
    try:
        model = _reranker()
    except Exception:  # noqa: BLE001 - fall back to the small reranker if the big one fails to load
        model = _reranker(cfg("models.reranker_fallback"))
    return [float(s) for s in model.rerank(query, docs, batch_size=16)]
