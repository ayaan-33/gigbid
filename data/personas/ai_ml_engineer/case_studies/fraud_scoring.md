---
{"id": "ai_ml_engineer:case:fraud_scoring", "type": "case_study", "project": "fraud_scoring", "title": "Transaction fraud scoring", "client_industry": "marketplace", "date": "2024-06-06", "skills": ["Python", "XGBoost", "Statistics"], "synthetic": true}
---

# Transaction fraud scoring

## Context

Signal Retail (marketplace) had a familiar problem: rule-based fraud checks blocked good customers.

## What I did

- Gradient-boosted model on device, velocity and merchant features.
- Pulled the history straight from their warehouse with window-function queries.
- Cost-sensitive thresholding.
- Monitoring for drift weekly.
- Versioned every model and promoted it through staging with tracked metrics.

## Results

- Fraud caught up 31%.
- False declines down 26%.
- Latency under 45 ms.

Engagement: 7 weeks, finished 2024-06.

## Stack

Python, XGBoost, Statistics
