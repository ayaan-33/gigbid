---
{"id": "fullstack_dev:case:fastapi_backend", "type": "case_study", "project": "fastapi_backend", "title": "FastAPI backend for a mobile app", "client_industry": "language learning", "date": "2021-10-07", "skills": ["FastAPI", "PostgreSQL", "REST API", "Docker"], "synthetic": true}
---

# FastAPI backend for a mobile app

## Context

When I started with Willow Group, a language learning business, the prototype backend fell over at a few hundred users.

## What I did

- Async FastAPI with connection pooling.
- Covered the critical paths with automated tests before refactoring.
- Added an in-memory cache for the hottest reads.
- Redis caching for hot reads.
- Load-tested before launch.

## Results

- Handled 7k requests per minute.
- P95 latency 85 ms.
- 99% test coverage on core routes.

Engagement: 5 weeks, finished 2021-10.

## Stack

FastAPI, PostgreSQL, REST API, Docker
