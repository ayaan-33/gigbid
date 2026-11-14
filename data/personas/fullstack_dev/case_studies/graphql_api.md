---
{"id": "fullstack_dev:case:graphql_api", "type": "case_study", "project": "graphql_api", "title": "GraphQL API layer", "client_industry": "media", "date": "2025-12-17", "skills": ["GraphQL", "Node.js", "TypeScript"], "synthetic": true}
---

# GraphQL API layer

## Context

A media client, Willow Health, came to me because mobile and web clients called six REST services each.

## What I did

- Apollo gateway over existing services.
- Covered the critical paths with automated tests before refactoring.
- Dataloaders to remove N+1 queries.
- Added an in-memory cache for the hottest reads.
- Schema checks in CI.

## Results

- Mobile payload size down 56%.
- API calls per screen from 7 to 1.
- P95 128 ms.

Engagement: 5 weeks, finished 2025-12.

## Stack

GraphQL, Node.js, TypeScript
