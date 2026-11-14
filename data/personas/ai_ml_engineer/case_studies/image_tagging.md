---
{"id": "ai_ml_engineer:case:image_tagging", "type": "case_study", "project": "image_tagging", "title": "Automatic image tagging", "client_industry": "fashion e-commerce", "date": "2025-04-28", "skills": ["Python", "Computer Vision", "Hugging Face"], "synthetic": true}
---

# Automatic image tagging

## Context

Bright Health (fashion e-commerce) had a familiar problem: merchandisers tagged colour and style for every photo by hand.

## What I did

- CLIP embeddings with a light classifier per attribute.
- Active learning to pick images for labelling.
- Batch job on new uploads.
- Wrote the training loop myself so we controlled augmentation and early stopping.
- Deployed on their existing cloud account with least-privilege roles.

## Results

- Tagging time down 81%.
- Attribute accuracy 91%.
- 131k images tagged.

Engagement: 10 weeks, finished 2025-04.

## Stack

Python, Computer Vision, Hugging Face
