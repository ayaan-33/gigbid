---
{"id": "ai_ml_engineer:case:defect_vision", "type": "case_study", "project": "defect_vision", "title": "Visual defect detection", "client_industry": "packaging", "date": "2022-10-02", "skills": ["Python", "Computer Vision", "PyTorch"], "synthetic": true}
---

# Visual defect detection

## Context

When I started with Cobalt Studio, a packaging business, manual inspection missed hairline cracks at line speed.

## What I did

- Collected and labelled 9k images with the QA team.
- Trained an EfficientNet classifier with heavy augmentation.
- Versioned every model and promoted it through staging with tracked metrics.
- Shipped it as a container image so their ops team could run it anywhere.
- Deployed on an edge box beside the camera.

## Results

- Defect recall 95%.
- False rejects under 4%.
- Inspection at 35 items per second.

Engagement: 11 weeks, finished 2022-10.

## Stack

Python, Computer Vision, PyTorch
