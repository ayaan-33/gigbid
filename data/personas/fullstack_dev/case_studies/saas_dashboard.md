---
{"id": "fullstack_dev:case:saas_dashboard", "type": "case_study", "project": "saas_dashboard", "title": "Multi-tenant SaaS dashboard", "client_industry": "property management", "date": "2019-12-28", "skills": ["React", "TypeScript", "Next.js", "PostgreSQL"], "synthetic": true}
---

# Multi-tenant SaaS dashboard

## Context

Lumen Co. (property management) had a familiar problem: customers exported CSVs because the old portal was slow.

## What I did

- Next.js app router with server components.
- Row-level tenant isolation in Postgres.
- Exposed it over a documented HTTP API their other systems could call.
- Charts that load in under a second.
- Built a small utility-first design system.

## Results

- Page load from 7s to under 1s.
- 104 tenant companies.
- Support tickets about the portal down 56%.

Engagement: 13 weeks, finished 2019-12.

## Stack

React, TypeScript, Next.js, PostgreSQL
