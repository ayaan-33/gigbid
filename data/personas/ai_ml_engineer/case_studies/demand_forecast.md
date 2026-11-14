---
{"id": "ai_ml_engineer:case:demand_forecast", "type": "case_study", "project": "demand_forecast", "title": "Store demand forecasting", "client_industry": "pharmacy chain", "date": "2022-03-01", "skills": ["Python", "Time Series", "XGBoost"], "synthetic": true}
---

# Store demand forecasting

## Context

Vertex Labs (pharmacy chain) had a familiar problem: stock-outs on top SKUs and overstock everywhere else.

## What I did

- Hierarchical forecasts per store and SKU.
- Scheduled the weekly refresh as a DAG with retries and alerting.
- Holiday and promotion features.
- Did the feature work in dataframes and kept every transformation in versioned notebooks.
- Weekly retraining job with backtesting.

## Results

- MAPE improved from 30% to 16%.
- Stock-outs down 18%.
- 64 stores covered.

Engagement: 14 weeks, finished 2022-03.

## Stack

Python, Time Series, XGBoost
