---
{"id": "fullstack_dev:case:stripe_billing", "type": "case_study", "project": "stripe_billing", "title": "Subscription billing integration", "client_industry": "online courses", "date": "2022-08-13", "skills": ["Stripe", "Node.js", "TypeScript"], "synthetic": true}
---

# Subscription billing integration

## Context

A online courses client, Beacon Health, came to me because billing was manual invoices and chasing payments.

## What I did

- Stripe Billing with webhooks for every state change.
- Kept everything in their existing relational database with proper migrations.
- Idempotent webhook handlers.
- Covered the critical paths with automated tests before refactoring.
- Self-serve upgrade and downgrade.

## Results

- Failed-payment recovery up 29%.
- Finance time saved 15 hours a month.
- 1k subscribers migrated.

Engagement: 9 weeks, finished 2022-08.

## Stack

Stripe, Node.js, TypeScript
