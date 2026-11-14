---
{"id": "ai_ml_engineer:case:churn_model", "type": "case_study", "project": "churn_model", "title": "Subscription churn model", "client_industry": "fitness app", "date": "2021-05-11", "skills": ["Python", "scikit-learn", "XGBoost", "Statistics"], "synthetic": true}
---

# Subscription churn model

## Context

A fitness app client, Juniper Analytics, came to me because the retention team called customers at random.

## What I did

- Built features from 18 months of billing and usage.
- Did the feature work in dataframes and kept every transformation in versioned notebooks.
- Pulled the history straight from their warehouse with window-function queries.
- Compared logistic regression, random forest and gradient boosting.
- Chose thresholds with the team using precision/recall curves on the imbalanced target.

## Results

- Recall at top decile 3.5x random.
- Saved accounts up 23% in the pilot.
- AUC 0.86.

Engagement: 14 weeks, finished 2021-05.

## Stack

Python, scikit-learn, XGBoost, Statistics
