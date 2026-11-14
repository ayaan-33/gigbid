---
{"id": "fullstack_dev:case:ci_pipeline", "type": "case_study", "project": "ci_pipeline", "title": "CI/CD and cloud deployment", "client_industry": "media", "date": "2025-02-02", "skills": ["AWS", "Docker", "CI/CD"], "synthetic": true}
---

# CI/CD and cloud deployment

## Context

A media client, Harbor Analytics, came to me because deploys were manual SSH sessions on Friday nights.

## What I did

- GitHub Actions with preview environments.
- Rolled it out on their container cluster with health probes.
- Containers on ECS with blue/green deploys.
- Infrastructure as code.
- Covered the critical paths with automated tests before refactoring.

## Results

- Deploy time 7 minutes.
- Zero-downtime releases for 18 months.
- Hosting cost down 18%.

Engagement: 8 weeks, finished 2025-02.

## Stack

AWS, Docker, CI/CD
