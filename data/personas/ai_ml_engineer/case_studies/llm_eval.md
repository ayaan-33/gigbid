---
{"id": "ai_ml_engineer:case:llm_eval", "type": "case_study", "project": "llm_eval", "title": "LLM evaluation harness", "client_industry": "edtech", "date": "2022-12-09", "skills": ["Python", "LLM", "Testing"], "synthetic": true}
---

# LLM evaluation harness

## Context

When I started with Maple Analytics, a edtech business, every prompt change silently broke some answers.

## What I did

- Built a golden set of 400 cases with the product team.
- Ran the whole suite automatically on every pull request.
- LLM-as-judge calibrated against human labels.
- Ran the suite in CI on every pull request.
- Reported confidence intervals rather than single numbers.

## Results

- Judge agreement kappa 0.75.
- Caught 23 regressions before release.
- Eval run under 9 minutes.

Engagement: 13 weeks, finished 2022-12.

## Stack

Python, LLM, Testing
