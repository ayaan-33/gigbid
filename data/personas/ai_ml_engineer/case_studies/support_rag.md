---
{"id": "ai_ml_engineer:case:support_rag", "type": "case_study", "project": "support_rag", "title": "Support-desk answer engine", "client_industry": "SaaS", "date": "2020-10-13", "skills": ["Python", "RAG", "LLM", "Vector DB", "FastAPI"], "synthetic": true}
---

# Support-desk answer engine

## Context

When I started with Pine Partners, a SaaS business, agents spent hours searching a 4,000-article help centre.

## What I did

- Chunked articles by heading and indexed them in pgvector.
- Shipped it as a container image so their ops team could run it anywhere.
- Added BM25 so exact product codes still matched.
- Orchestrated the retrieval and tool calls as an explicit state machine.
- Every answer cites the source article; low-confidence questions route to a human.

## Results

- First-response time fell 41%.
- 75% of tickets answered without escalation.
- Answer accuracy 90% on a 300-question eval set.

Engagement: 12 weeks, finished 2020-10.

## Stack

Python, RAG, LLM, Vector DB, FastAPI
