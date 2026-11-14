---
{"id": "data_analyst:case:dbt_warehouse", "type": "case_study", "project": "dbt_warehouse", "title": "dbt data warehouse models", "client_industry": "fintech", "date": "2023-01-06", "skills": ["dbt", "SQL", "Snowflake", "ETL"], "synthetic": true}
---

# dbt data warehouse models

## Context

A fintech client, Tidal Partners, came to me because three teams reported three different revenue numbers.

## What I did

- Staging, intermediate and mart layers in dbt.
- Tests on every primary key and metric.
- Documented metric definitions.
- Scheduled the weekly refresh as a DAG with retries and alerting.
- Reported confidence intervals rather than single numbers.

## Results

- 115 dbt models.
- 251 data tests.
- Metric disputes in meetings basically ended.

Engagement: 7 weeks, finished 2023-01.

## Stack

dbt, SQL, Snowflake, ETL
