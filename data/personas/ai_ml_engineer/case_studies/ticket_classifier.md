---
{"id": "ai_ml_engineer:case:ticket_classifier", "type": "case_study", "project": "ticket_classifier", "title": "Ticket triage classifier", "client_industry": "travel", "date": "2021-11-30", "skills": ["Python", "NLP", "Hugging Face", "Fine-tuning"], "synthetic": true}
---

# Ticket triage classifier

## Context

A travel client, Willow Retail, came to me because tickets sat in a shared queue until someone triaged them.

## What I did

- Labelled 6k historical tickets with the support leads.
- Fine-tuned a DistilBERT model with class weights.
- Versioned every model and promoted it through staging with tracked metrics.
- Wrote the training loop myself so we controlled augmentation and early stopping.
- Served it behind an API with a confidence threshold.

## Results

- Routing accuracy 95%.
- Median triage delay down from 4 hours to minutes.
- Macro-F1 0.86.

Engagement: 6 weeks, finished 2021-11.

## Stack

Python, NLP, Hugging Face, Fine-tuning
