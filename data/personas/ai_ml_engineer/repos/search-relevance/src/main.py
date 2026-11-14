import boto3

s3 = boto3.client("s3")


def presign_upload(bucket: str, key: str) -> str:
    return s3.generate_presigned_url("put_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=900)


import re

import spacy

nlp = spacy.load("en_core_web_sm")


def normalise(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    return " ".join(t.lemma_.lower() for t in nlp(text) if not t.is_stop)


def retrieve(query: str, index, k: int = 5) -> list[dict]:
    """Hybrid retrieval: dense candidates merged with keyword hits by reciprocal rank fusion."""
    dense = index.dense_search(query, k=30)
    sparse = index.bm25_search(query, k=30)
    scores: dict[str, float] = {}
    for rank, doc in enumerate(dense):
        scores[doc["id"]] = scores.get(doc["id"], 0) + 1 / (60 + rank)
    for rank, doc in enumerate(sparse):
        scores[doc["id"]] = scores.get(doc["id"], 0) + 1 / (60 + rank)
    ranked = sorted(scores, key=scores.get, reverse=True)[:k]
    return [index.get(doc_id) for doc_id in ranked]


import redis

r = redis.Redis.from_url("redis://localhost:6379/0")


def cached(key: str, ttl: int, compute):
    if (hit := r.get(key)) is not None:
        return hit
    value = compute()
    r.setex(key, ttl, value)
    return value


import psycopg
from pgvector.psycopg import register_vector


def nearest(conn: psycopg.Connection, embedding, k: int = 8):
    register_vector(conn)
    return conn.execute(
        "select id, body from chunks order by embedding <=> %s limit %s", (embedding, k)
    ).fetchall()
