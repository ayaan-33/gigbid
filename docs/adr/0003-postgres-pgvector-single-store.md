# ADR 0003: Postgres + pgvector as the one store

**Status:** accepted

## Decision
One Postgres instance (the `pgvector/pgvector:pg16` image) holds:
- the app tables;
- the LangGraph checkpointer and store (long-term memory);
- the vector index.

BM25 is computed in memory from the same chunks.

## Why
- **Fewer services** on a free VM.
- **One backup** (`pg_dump`).
- **Tenant scoping** works with plain SQL.
- **Durability:** the checkpointer and the app data share it, so approvals survive restarts (C6).

## Trade-off
- **Scale:** in-memory BM25 and the dense matrix are rebuilt per process. That's fine for a single
  freelancer's portfolio (hundreds of chunks), and wouldn't be for millions.
