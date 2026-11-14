---
{"id": "ai_ml_engineer:case:model_serving", "type": "case_study", "project": "model_serving", "title": "Model serving platform", "client_industry": "fintech", "date": "2026-03-21", "skills": ["MLOps", "Docker", "Python"], "synthetic": true}
---

# Model serving platform

## Context

Saffron Labs (fintech) had a familiar problem: each model was deployed by hand from a notebook.

## What I did

- MLflow registry with staged promotion.
- Ran the whole suite automatically on every pull request.
- Containerised inference with health checks.
- Canary rollout and automatic rollback.
- Rolled it out on their container cluster with health probes.

## Results

- Deploy time from days to 43 minutes.
- 6 models in production.
- Rollback in under 2 minutes.

Engagement: 14 weeks, finished 2026-03.

## Stack

MLOps, Docker, Python
