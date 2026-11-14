---
{"id": "ai_ml_engineer:case:search_relevance", "type": "case_study", "project": "search_relevance", "title": "Site search relevance", "client_industry": "e-commerce", "date": "2025-09-05", "skills": ["Python", "RAG", "Vector DB", "NLP"], "synthetic": true}
---

# Site search relevance

## Context

A e-commerce client, Juniper Partners, came to me because customers searched with words the catalogue never used.

## What I did

- Hybrid BM25 plus dense retrieval.
- Cross-encoder reranking of the top 50.
- Offline evaluation with click logs.
- Added an in-memory cache for the hottest reads.
- Deployed on their existing cloud account with least-privilege roles.

## Results

- Zero-result searches down 39%.
- Search conversion up 12%.
- P95 latency 125 ms.

Engagement: 9 weeks, finished 2025-09.

## Stack

Python, RAG, Vector DB, NLP
