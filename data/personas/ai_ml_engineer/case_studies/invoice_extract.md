---
{"id": "ai_ml_engineer:case:invoice_extract", "type": "case_study", "project": "invoice_extract", "title": "Invoice field extraction pipeline", "client_industry": "logistics", "date": "2021-04-25", "skills": ["Python", "LLM", "NLP", "FastAPI"], "synthetic": true}
---

# Invoice field extraction pipeline

## Context

When I started with Granite Studio, a logistics business, clerks retyped totals, dates and VAT numbers from scanned supplier invoices.

## What I did

- OCR then layout-aware parsing.
- Kept everything in their existing relational database with proper migrations.
- Shipped it as a container image so their ops team could run it anywhere.
- A small LLM fills a strict JSON schema.
- Rules cross-check totals and flag mismatches for review.

## Results

- Manual entry time cut by 73%.
- Field-level accuracy 96%.
- 20k invoices processed per month.

Engagement: 14 weeks, finished 2021-04.

## Stack

Python, LLM, NLP, FastAPI
