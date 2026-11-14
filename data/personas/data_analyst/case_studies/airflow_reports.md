---
{"id": "data_analyst:case:airflow_reports", "type": "case_study", "project": "airflow_reports", "title": "Scheduled reporting pipeline", "client_industry": "logistics", "date": "2025-04-05", "skills": ["Airflow", "SQL", "Python"], "synthetic": true}
---

# Scheduled reporting pipeline

## Context

Signal Partners (logistics) had a familiar problem: a daily KPI email depended on one person running queries at 7am.

## What I did

- Airflow DAG with retries and SLAs.
- Built the extract-clean-load steps so the numbers refresh without anyone touching them.
- Data checks that block bad numbers.
- Alerting on failures.
- Did the feature work in dataframes and kept every transformation in versioned notebooks.

## Results

- 99% on-time delivery over 6 months.
- 25 reports automated.
- Manual work cut 12 hours a week.

Engagement: 3 weeks, finished 2025-04.

## Stack

Airflow, SQL, Python
