---
{"id": "ai_ml_engineer:case:contract_review", "type": "case_study", "project": "contract_review", "title": "Contract clause extraction", "client_industry": "real estate", "date": "2024-10-06", "skills": ["Python", "LLM", "RAG", "NLP"], "synthetic": true}
---

# Contract clause extraction

## Context

A real estate client, Beacon Group, came to me because paralegals read 40-page contracts to find renewal and liability clauses.

## What I did

- Section-aware chunking.
- Stored embeddings next to the source rows so retrieval stayed consistent.
- Clause retrieval plus extraction with citations.
- Evaluation on 120 annotated contracts.
- Covered the critical paths with automated tests before refactoring.

## Results

- Review time per contract down 62%.
- Clause recall 93%.
- 1k contracts reviewed.

Engagement: 9 weeks, finished 2024-10.

## Stack

Python, LLM, RAG, NLP
